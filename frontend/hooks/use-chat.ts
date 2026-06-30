"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchHistory, streamChat } from "@/lib/api";
import {
  type ChatMessage,
  type RawHistoryItem,
  type Role,
} from "@/lib/types";

let msgSeq = 0;
function makeId() {
  return `msg-${++msgSeq}`;
}

function adaptHistory(items: RawHistoryItem[]): ChatMessage[] {
  return items.map((item) => ({
    id: makeId(),
    role: (item.role ?? "ai") as Role,
    content: item.content ?? "",
    timestamp: item.timestamp ?? undefined,
    tool_name: item.tool_name || undefined,
  }));
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
      const aiMsgId = makeId();
      const aiMsg: ChatMessage = {
        id: aiMsgId,
        role: "ai",
        content: "",
        isStreaming: true,
      };

      setMessages((prev) => [...prev, userMsg, aiMsg]);
      setIsStreaming(true);
      setError(null);

      const request = {
        thread_id: threadId,
        message: content.trim(),
        user_id: userId,
      };

      try {
        for await (const ev of streamChat(request)) {
          if (ev.role === "tool") {
            const toolMsg: ChatMessage = {
              id: makeId(),
              role: "tool",
              content: "",
              tool_name: ev.tool_name,
            };
            setMessages((prev) => {
              const aiIdx = prev.findIndex((m) => m.id === aiMsgId);
              if (aiIdx === -1) return [...prev, toolMsg];
              const next = [...prev];
              next.splice(aiIdx, 0, toolMsg);
              return next;
            });
          } else if (ev.role === "ai" && ev.content) {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === aiMsgId
                  ? { ...m, content: m.content + ev.content }
                  : m,
              ),
            );
          }
        }
      } catch (err) {
        console.error("[useChat] send error:", err);
        const errMsg = (err instanceof Error && err.message) || "调用失败，请重试";
        setError(errMsg);
        setMessages((prev) =>
          prev.map((m) =>
            m.id === aiMsgId
              ? { ...m, content: m.content || errMsg }
              : m,
          ),
        );
      } finally {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === aiMsgId ? { ...m, isStreaming: false } : m,
          ),
        );
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
