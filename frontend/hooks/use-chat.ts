"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchHistory, streamChat } from "@/lib/api";
import type { ChatMessage, RawHistoryItem, Role, StreamEvent, ToolCall } from "@/lib/types";

let msgSeq = 0;
function makeId() {
  return `msg-${++msgSeq}`;
}

function adaptHistory(items: RawHistoryItem[]): ChatMessage[] {
  const out: ChatMessage[] = [];
  for (const item of items) {
    if (item.role === "human") {
      out.push({
        id: makeId(),
        role: "human" as Role,
        content: item.content ?? "",
        timestamp: item.timestamp ?? undefined,
      });
      continue;
    }
    const turn = item as Extract<RawHistoryItem, { role: "turn" }>;
    if (turn.tools && turn.tools.length > 0) {
      out.push({
        id: makeId(),
        role: "ai" as Role,
        content: turn.ai_content ?? "",
        isStreaming: false,
        toolCalls: turn.tools.map((name) => ({
          id: makeId(),
          name,
          status: "completed" as const,
        })),
      });
    } else if (turn.ai_content) {
      out.push({
        id: makeId(),
        role: "ai" as Role,
        content: turn.ai_content,
        isStreaming: false,
      });
    }
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

      const userMsg: ChatMessage = {
        id: makeId(),
        role: "human",
        content: content.trim(),
        timestamp: new Date().toISOString(),
      };

      setMessages((prev) => [...prev, userMsg]);
      setIsStreaming(true);
      setError(null);

      let aiMsgId: string | null = null;

      const request = {
        thread_id: threadId,
        message: content.trim(),
        user_id: userId,
      };

      try {
        for await (const ev of streamChat(request)) {
          if (ev.role === "tool") {
            const call: ToolCall = {
              id: makeId(),
              name: ev.tool_name,
              status: "completed",
            };
            setMessages((prev) =>
              prev.map((m) => {
                if (m.id === aiMsgId) {
                  return { ...m, toolCalls: [...(m.toolCalls ?? []), call] };
                }
                return m;
              }),
            );
          } else if (ev.role === "ai" && ev.content) {
            const piece = ev.content;
            if (aiMsgId === null) {
              const newId = makeId();
              aiMsgId = newId;
              setMessages((prev) => [
                ...prev,
                {
                  id: newId,
                  role: "ai",
                  content: piece,
                  isStreaming: true,
                },
              ]);
            } else {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === aiMsgId
                    ? { ...m, content: m.content + piece }
                    : m,
                ),
              );
            }
          }
        }
      } catch (err) {
        console.error("[useChat] send error:", err);
        const errMsg = (err instanceof Error && err.message) || "调用失败，请重试";
        setError(errMsg);
        if (aiMsgId === null) {
          const id = makeId();
          aiMsgId = id;
          setMessages((prev) => [
            ...prev,
            {
              id,
              role: "ai",
              content: errMsg,
              isStreaming: false,
            },
          ]);
        } else {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === aiMsgId
                ? { ...m, content: m.content || errMsg }
                : m,
            ),
          );
        }
      } finally {
        if (aiMsgId !== null) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === aiMsgId ? { ...m, isStreaming: false } : m,
            ),
          );
        }
        setIsStreaming(false);
        onStreamComplete?.();
      }
    },
    [threadId, isStreaming, onStreamComplete, userId],
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
