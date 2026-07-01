"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchHistory, streamChat } from "@/lib/api";
import {
  type AgentName,
  type ChatMessage,
  type RawHistoryItem,
  type Role,
  type StreamEvent,
  type ToolCall,
} from "@/lib/types";

let msgSeq = 0;
function makeId() {
  return `msg-${++msgSeq}`;
}

// 历史回放：把后端分组结构还原为前端流式所需的消息序列：
//   human -> 各 agent 卡（含 turn_id）-> 最终答复（isFinalAnswer）
function adaptHistory(items: RawHistoryItem[]): ChatMessage[] {
  const out: ChatMessage[] = [];
  let turnId = 0;
  for (const item of items) {
    if (item.role === "human") {
      out.push({
        id: makeId(),
        role: "human" as Role,
        content: item.content ?? "",
        timestamp: item.timestamp ?? undefined,
        turn_id: turnId,
      });
      continue;
    }
    // role === "turn"
    for (const card of (item as Extract<RawHistoryItem, { role: "turn" }>).agents ?? []) {
      out.push({
        id: makeId(),
        role: "agent" as Role,
        agent: card.agent,
        content: card.thought, // 过程专家卡保留思考过程（不再提升为最终答复）
        status: "done",
        isStreaming: false,
        toolCalls: (card.tools ?? []).map((name) => ({
          id: makeId(),
          name,
          status: "completed" as const,
        })),
        turn_id: turnId,
      });
    }
    const final_answer = (item as Extract<RawHistoryItem, { role: "turn" }>).final_answer ?? "";
    if (final_answer) {
      out.push({
        id: makeId(),
        role: "ai" as Role,
        content: final_answer,
        isStreaming: false,
        turn_id: turnId,
        isFinalAnswer: true,
      });
    }
    turnId += 1;
  }
  return out;
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
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!threadId) {
      setMessages([]);
      setError(null);
      return;
    }

    let cancelled = false;
    setIsLoadingHistory(true);
    setError(null);

    fetchHistory(threadId)
      .then((data) => {
        if (cancelled) return;
        setMessages(adaptHistory(data));
      })
      .catch((err) => {
        if (cancelled) return;
        console.error("[useChat] load history error:", err);
        setError("加载历史消息失败");
        setMessages([]);
      })
      .finally(() => {
        if (!cancelled) setIsLoadingHistory(false);
      });

    return () => {
      cancelled = true;
    };
  }, [threadId]);

  const sendMessage = useCallback(
    async (content: string) => {
      if (!threadId || !content.trim() || isStreaming) return;

      // 本轮 turn_id：若已有消息则取最大 turn_id + 1，否则从 0 起
      const turnId =
        messages.length === 0
          ? 0
          : Math.max(...messages.map((m) => m.turn_id ?? -1)) + 1;

      const userMsg: ChatMessage = {
        id: makeId(),
        role: "human",
        content: content.trim(),
        timestamp: new Date().toISOString(),
        turn_id: turnId,
      };

      setMessages((prev) => [...prev, userMsg]);
      setIsStreaming(true);
      setError(null);

      // 最终答复气泡 id：到达首个 final 内容（或无 agent 的兜底 ai）时才追加到末尾，
      // 保证渲染顺序为 user → agent 组 → 最终答复（在“本轮处理”卡片下方）。
      let finalMsgId: string | null = null;

      const request = {
        thread_id: threadId,
        message: content.trim(),
        user_id: userId,
      };

      const findRunningAgentMsg = (
        prev: ChatMessage[],
        agent: AgentName,
      ): string | null => {
        for (let i = prev.length - 1; i >= 0; i--) {
          const m = prev[i];
          if (
            m.role === "agent" &&
            m.agent === agent &&
            m.status === "running" &&
            m.turn_id === turnId
          ) {
            return m.id;
          }
        }
        return null;
      };

      try {
        for await (const ev of streamChat(request)) {
          if ("event" in ev) {
            if (ev.event === "agent_start") {
              const agentId = makeId();
              const agentMsg: ChatMessage = {
                id: agentId,
                role: "agent",
                agent: ev.agent,
                content: "",
                status: "running",
                isStreaming: true,
                toolCalls: [],
                turn_id: turnId,
              };
              setMessages((prev) => [...prev, agentMsg]);
            } else if (ev.event === "agent_end") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.role === "agent" && m.agent === ev.agent && m.status === "running" && m.turn_id === turnId
                    ? { ...m, status: "done", isStreaming: false }
                    : m,
                ),
              );
            }
            continue;
          }

          if (ev.role === "tool") {
            const toolAgent = ev.agent;
            if (toolAgent) {
              const call: ToolCall = {
                id: makeId(),
                name: ev.tool_name,
                status: "completed",
              };
              setMessages((prev) =>
                prev.map((m) => {
                  if (
                    m.role === "agent" &&
                    m.agent === toolAgent &&
                    m.status === "running" &&
                    m.turn_id === turnId
                  ) {
                    return { ...m, toolCalls: [...(m.toolCalls ?? []), call] };
                  }
                  return m;
                }),
              );
            }
          } else if (ev.role === "ai" && ev.content) {
            const piece = ev.content;
            if (ev.final || !ev.agent) {
              // 最终整合输出 / 无 agent 的兜底：进入最终答复气泡
              if (finalMsgId === null) {
                const newId = makeId();
                finalMsgId = newId;
                setMessages((prev) => [
                  ...prev,
                  {
                    id: newId,
                    role: "ai",
                    content: piece,
                    isStreaming: true,
                    turn_id: turnId,
                    isFinalAnswer: true,
                  },
                ]);
              } else {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === finalMsgId
                      ? { ...m, content: m.content + piece, isFinalAnswer: true }
                      : m,
                  ),
                );
              }
            } else {
              const agent = ev.agent;
              setMessages((prev) => {
                const agentId = findRunningAgentMsg(prev, agent);
                if (agentId) {
                  return prev.map((m) =>
                    m.id === agentId
                      ? { ...m, content: m.content + piece }
                      : m,
                  );
                }
                const agentId2 = makeId();
                const agentMsg: ChatMessage = {
                  id: agentId2,
                  role: "agent",
                  agent,
                  content: piece,
                  status: "running",
                  isStreaming: true,
                  toolCalls: [],
                  turn_id: turnId,
                };
                return [...prev, agentMsg];
              });
            }
          }
        }
      } catch (err) {
        console.error("[useChat] send error:", err);
        const errMsg = (err instanceof Error && err.message) || "调用失败，请重试";
        setError(errMsg);
        setMessages((prev) => {
          if (finalMsgId === null) {
            const id = makeId();
            finalMsgId = id;
            return [
              ...prev,
              {
                id,
                role: "ai",
                content: errMsg,
                isStreaming: false,
                turn_id: turnId,
                isFinalAnswer: true,
              },
            ];
          }
          return prev.map((m) =>
            m.id === finalMsgId
              ? { ...m, content: m.content || errMsg, isFinalAnswer: true }
              : m,
          );
        });
      } finally {
        setMessages((prev) =>
          prev.map((m) =>
            m.role === "agent" && m.status === "running"
              ? { ...m, status: "done", isStreaming: false }
              : m,
          ),
        );
        // 最终答复气泡结束流式（可能为 null：全程未收到任何 final/fallback 内容）
        if (finalMsgId !== null) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === finalMsgId ? { ...m, isStreaming: false } : m,
            ),
          );
        }
        setIsStreaming(false);
        onStreamComplete?.();
      }
    },
    [threadId, isStreaming, onStreamComplete],
  );

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const clearMessages = useCallback(() => {
    setMessages([]);
    setError(null);
  }, []);

  return {
    messages,
    isStreaming,
    isLoadingHistory,
    error,
    sendMessage,
    stopStreaming,
    clearMessages,
  };
}