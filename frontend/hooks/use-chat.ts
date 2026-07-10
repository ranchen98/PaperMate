"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchHistory, resumeChat, stopChat, streamChat } from "@/lib/api";
import type {
  AgentCard,
  AgentCardSection,
  AgentMode,
  ChatMessage,
  HistoryResponse,
  RawHistoryItem,
  Role,
  StreamEvent,
  ToolCall,
} from "@/lib/types";

let msgSeq = 0;
function makeId() {
  return `msg-${++msgSeq}`;
}

function adaptHistory(items: RawHistoryItem[], isInterrupted: boolean): ChatMessage[] {
  const out: ChatMessage[] = [];
  let lastAiMsgId: string | null = null;

  for (const item of items) {
    if (item.role === "human") {
      out.push({
        id: makeId(),
        role: "human" as Role,
        content: item.content ?? "",
        timestamp: item.timestamp ?? undefined,
        forkCheckpointId: item.fork_checkpoint_id || undefined,
      });
      continue;
    }
    const turn = item as Extract<RawHistoryItem, { role: "turn" }>;

    if (turn.is_multi && turn.agent_messages) {
      const cards: AgentCard[] = [];
      for (const am of turn.agent_messages) {
        const agentName = am.agent || "unknown";
        let card = cards.find((c) => c.agent === agentName);
        if (!card) {
          card = { agent: agentName, sections: [], status: "done" };
          cards.push(card);
        }
        const sectionId = am.section_id || undefined;
        let section: AgentCardSection | undefined = sectionId
          ? card.sections.find((s) => s.sectionId === sectionId)
          : card.sections[0];
        if (!section) {
          section = {
            sectionId,
            sectionTitle: am.section_title || undefined,
            content: am.content,
          };
          card.sections.push(section);
        } else {
          section.content += am.content;
        }
      }
      const aiId = makeId();
      lastAiMsgId = aiId;
      out.push({
        id: aiId,
        role: "ai" as Role,
        content: "",
        isStreaming: false,
        agentCards: cards,
        isReportReady: turn.report_ready,
        isInterrupted: false,
      });
    } else {
      const toolCalls: ToolCall[] | undefined =
        turn.tools && turn.tools.length > 0
          ? turn.tools.map((name) => ({
              id: makeId(),
              name,
              status: "completed" as const,
            }))
          : undefined;
      if (toolCalls || turn.ai_content) {
        const aiId = makeId();
        lastAiMsgId = aiId;
        out.push({
          id: aiId,
          role: "ai" as Role,
          content: turn.ai_content ?? "",
          thinking: turn.thinking,
          isStreaming: false,
          toolCalls,
          isInterrupted: false,
        });
      }
    }
  }

  if (isInterrupted && lastAiMsgId) {
    const idx = out.findIndex((m) => m.id === lastAiMsgId);
    if (idx !== -1) {
      out[idx] = { ...out[idx], isInterrupted: true };
    }
  }
  return out;
}

function updateCardField(
  cards: AgentCard[],
  agentName: string,
  sectionId: string | undefined,
  sectionTitle: string | undefined,
  content: string,
  isThinking: boolean,
): AgentCard[] {
  const newCards = [...cards];
  let cardIdx = newCards.findIndex((c) => c.agent === agentName);

  if (cardIdx === -1) {
    for (let i = 0; i < newCards.length; i++) {
      if (newCards[i].status === "running") {
        newCards[i] = { ...newCards[i], status: "done" as const };
      }
    }
    const section: AgentCardSection = {
      sectionId: sectionId || undefined,
      sectionTitle: sectionTitle || undefined,
      content: isThinking ? "" : content,
      thinking: isThinking ? content : undefined,
    };
    newCards.push({ agent: agentName, sections: [section], status: "running" });
  } else {
    const card = { ...newCards[cardIdx] };
    const sections = [...card.sections];
    let secIdx = sectionId
      ? sections.findIndex((s) => s.sectionId === sectionId)
      : 0;
    if (secIdx === -1) {
      sections.push({
        sectionId: sectionId || undefined,
        sectionTitle: sectionTitle || undefined,
        content: isThinking ? "" : content,
        thinking: isThinking ? content : undefined,
      });
    } else {
      const sec = { ...sections[secIdx] };
      if (isThinking) {
        sec.thinking = (sec.thinking || "") + content;
      } else {
        sec.content = sec.content + content;
      }
      sections[secIdx] = sec;
    }
    card.sections = sections;
    newCards[cardIdx] = card;
  }

  return newCards;
}

export function useChat(
  threadId: string | null,
  onStreamComplete?: () => void,
  userId: string = "",
) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isInterrupted, setIsInterrupted] = useState(false);
  const [rewindCheckpointId, setRewindCheckpointId] = useState<string | null>(null);
  const [rewindDraft, setRewindDraft] = useState<{ text: string; nonce: number } | null>(null);

  useEffect(() => {
    if (!threadId) {
      setMessages([]);
      setError(null);
      setIsInterrupted(false);
      setRewindCheckpointId(null);
      return;
    }

    let cancelled = false;
    setIsLoadingHistory(true);
    setError(null);
    setRewindCheckpointId(null);

    fetchHistory(threadId)
      .then((data: HistoryResponse) => {
        if (cancelled) return;
        setMessages(adaptHistory(data.messages, data.is_interrupted));
        setIsInterrupted(data.is_interrupted);
      })
      .catch((err) => {
        if (cancelled) return;
        console.error("[useChat] load history error:", err);
        setError("加载历史消息失败");
        setMessages([]);
        setIsInterrupted(false);
      })
      .finally(() => {
        if (!cancelled) setIsLoadingHistory(false);
      });

    return () => {
      cancelled = true;
    };
  }, [threadId]);

  const processStreamEvents = useCallback(
    async (
      stream: AsyncGenerator<StreamEvent, void, unknown>,
      mode: AgentMode,
    ): Promise<boolean> => {
      let aiMsgId: string | null = null;
      let completed = true;

      const ensureAiMsg = (): string => {
        if (aiMsgId !== null) return aiMsgId;
        const newId = makeId();
        aiMsgId = newId;
        setMessages((prev) => [
          ...prev,
          {
            id: newId,
            role: "ai",
            content: "",
            isStreaming: true,
            toolCalls: [],
          },
        ]);
        return newId;
      };

      try {
        for await (const ev of stream) {
          if (ev.role === "stopped") {
            completed = false;
            break;
          }
          if (ev.role === "tool") {
            const id = ensureAiMsg();
            const call: ToolCall = {
              id: makeId(),
              name: ev.tool_name,
              status: "completed",
            };
            setMessages((prev) =>
              prev.map((m) =>
                m.id === id
                  ? { ...m, toolCalls: [...(m.toolCalls ?? []), call] }
                  : m,
              ),
            );
          } else if (ev.role === "thinking" && ev.content) {
            const piece = ev.content;
            const id = ensureAiMsg();
            const agentName = ev.agent;
            const sectionId = ev.section_id || undefined;
            const sectionTitle = ev.section_title || undefined;

            if (mode === "multi" && agentName) {
              setMessages((prev) =>
                prev.map((m) => {
                  if (m.id !== id) return m;
                  return {
                    ...m,
                    agentCards: updateCardField(
                      m.agentCards ?? [],
                      agentName,
                      sectionId,
                      sectionTitle,
                      piece,
                      true,
                    ),
                  };
                }),
              );
            } else {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === id
                    ? { ...m, thinking: (m.thinking ?? "") + piece }
                    : m,
                ),
              );
            }
          } else if (ev.role === "ai" && ev.content) {
            const piece = ev.content;
            const id = ensureAiMsg();
            const agentName = ev.agent;
            const sectionId = ev.section_id || undefined;
            const sectionTitle = ev.section_title || undefined;

            if (mode === "multi" && agentName) {
              setMessages((prev) =>
                prev.map((m) => {
                  if (m.id !== id) return m;
                  return {
                    ...m,
                    agentCards: updateCardField(
                      m.agentCards ?? [],
                      agentName,
                      sectionId,
                      sectionTitle,
                      piece,
                      false,
                    ),
                  };
                }),
              );
            } else {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === id
                    ? { ...m, content: m.content + piece }
                    : m,
                ),
              );
            }
          }
        }
      } finally {
        if (aiMsgId !== null) {
          setMessages((prev) =>
            prev.map((m) => {
              if (m.id !== aiMsgId) return m;
              if (mode === "multi") {
                return {
                  ...m,
                  isStreaming: false,
                  isReportReady: completed,
                  isInterrupted: !completed,
                  agentCards: m.agentCards?.map((c) => ({
                    ...c,
                    status: "done" as const,
                  })),
                };
              }
              return {
                ...m,
                isStreaming: false,
                isInterrupted: !completed,
              };
            }),
          );
        }
      }
      return completed;
    },
    [],
  );

  const sendMessage = useCallback(
    async (content: string, mode: AgentMode = "single") => {
      if (!threadId || !content.trim() || isStreaming) return;

      const userMsg: ChatMessage = {
        id: makeId(),
        role: "human",
        content: content.trim(),
        timestamp: new Date().toISOString(),
      };

      setMessages((prev) => [...prev, userMsg]);
      setIsStreaming(true);
      setError(null);
      setIsInterrupted(false);

      const request = {
        thread_id: threadId,
        message: content.trim(),
        user_id: userId,
        agent_mode: mode,
        ...(rewindCheckpointId ? { checkpoint_id: rewindCheckpointId } : {}),
      };

      try {
        await processStreamEvents(streamChat(request), mode);
        setRewindCheckpointId(null);
        setRewindDraft(null);
      } catch (err) {
        console.error("[useChat] send error:", err);
        const errMsg = (err instanceof Error && err.message) || "调用失败，请重试";
        setError(errMsg);
        setMessages((prev) => {
          const lastAi = [...prev].reverse().find((m) => m.role === "ai");
          if (!lastAi) return prev;
          return prev.map((m) =>
            m.id === lastAi.id
              ? { ...m, content: m.content || errMsg, isStreaming: false }
              : m,
          );
        });
      } finally {
        setIsStreaming(false);
        onStreamComplete?.();
      }
    },
    [threadId, isStreaming, onStreamComplete, userId, rewindCheckpointId, processStreamEvents],
  );

  const resume = useCallback(
    async (mode: AgentMode = "single") => {
      if (!threadId || isStreaming) return;

      setIsStreaming(true);
      setError(null);
      setIsInterrupted(false);

      try {
        await processStreamEvents(
          resumeChat({
            thread_id: threadId,
            user_id: userId,
            agent_mode: mode,
          }),
          mode,
        );
      } catch (err) {
        console.error("[useChat] resume error:", err);
        const errMsg = (err instanceof Error && err.message) || "续聊失败，请重试";
        setError(errMsg);
      } finally {
        setIsStreaming(false);
        onStreamComplete?.();
      }
    },
    [threadId, isStreaming, userId, onStreamComplete, processStreamEvents],
  );

  const rewindTo = useCallback(
    (messageId: string) => {
      if (isStreaming) return;
      const target = messages.find((m) => m.id === messageId);
      if (!target || target.role !== "human" || !target.forkCheckpointId) return;

      const idx = messages.findIndex((m) => m.id === messageId);
      setMessages(messages.slice(0, idx));
      setRewindCheckpointId(target.forkCheckpointId);
      setRewindDraft({ text: target.content, nonce: Date.now() });
      setIsInterrupted(false);
    },
    [messages, isStreaming],
  );

  const cancelRewind = useCallback(() => {
    setRewindCheckpointId(null);
    setRewindDraft(null);
    if (!threadId) return;
    fetchHistory(threadId)
      .then((data: HistoryResponse) => {
        setMessages(adaptHistory(data.messages, data.is_interrupted));
        setIsInterrupted(data.is_interrupted);
      })
      .catch((err) => {
        console.error("[useChat] cancelRewind reload error:", err);
      });
  }, [threadId]);

  const stopStreaming = useCallback(() => {
      if (!threadId) return;
      setIsInterrupted(true);
      stopChat(threadId).catch((err) => {
        console.error("[useChat] stop error:", err);
      });
    }, [threadId]);

  const clearMessages = useCallback(() => {
    setMessages([]);
    setError(null);
    setRewindCheckpointId(null);
    setIsInterrupted(false);
  }, []);

  return {
    messages,
    isStreaming,
    isLoadingHistory,
    error,
    isInterrupted,
    rewindCheckpointId,
    rewindDraft,
    sendMessage,
    resume,
    rewindTo,
    cancelRewind,
    stopStreaming,
    clearMessages,
  };
}
