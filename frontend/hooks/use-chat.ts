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
      // 兜底 AI 气泡：用于不带 agent 标签的 ai 内容（如 test 旁路、异常降级）
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

      const findRunningAgentMsg = (
        prev: ChatMessage[],
        agent: AgentName,
      ): string | null => {
        // 从末尾向前找最近一个 agent===该值 且 status==="running" 的消息
        for (let i = prev.length - 1; i >= 0; i--) {
          const m = prev[i];
          if (m.role === "agent" && m.agent === agent && m.status === "running") {
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
              };
              setMessages((prev) => [...prev, agentMsg]);
            } else if (ev.event === "agent_end") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.role === "agent" && m.agent === ev.agent && m.status === "running"
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
              // 归属某 Agent：追加到该 agent 消息的 toolCalls 数组（供 AgentResponse 展示）
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
                    m.status === "running"
                  ) {
                    return { ...m, toolCalls: [...(m.toolCalls ?? []), call] };
                  }
                  return m;
                }),
              );
            } else {
              // 无 agent 归属（历史兼容）：创建独立 tool 消息
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
            }
          } else if (ev.role === "ai" && ev.content) {
            if (ev.agent) {
              const agent = ev.agent;
              const piece = ev.content;
              // 追加到对应 agent 的 running 消息
              setMessages((prev) => {
                const agentId = findRunningAgentMsg(prev, agent);
                if (agentId) {
                  return prev.map((m) =>
                    m.id === agentId
                      ? { ...m, content: m.content + piece }
                      : m,
                  );
                }
                // 找不到则新建一个 agent 消息（兜底，正常不会走到）
                const agentId2 = makeId();
                const agentMsg: ChatMessage = {
                  id: agentId2,
                  role: "agent",
                  agent,
                  content: piece,
                  status: "running",
                  isStreaming: true,
                  toolCalls: [],
                };
                return [...prev, agentMsg];
              });
            } else {
              // 无 agent 标签：追加到兜底 aiMsg
              const piece = ev.content;
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
        setMessages((prev) =>
          prev.map((m) =>
            m.id === aiMsgId
              ? { ...m, content: m.content || errMsg }
              : m,
          ),
        );
      } finally {
        // 结束所有仍 running 的 agent 消息
        setMessages((prev) =>
          prev.map((m) =>
            m.role === "agent" && m.status === "running"
              ? { ...m, status: "done", isStreaming: false }
              : m,
          ),
        );
        // 兜底 aiMsg 若仍空则移除（本次走了 agent 分区路径）
        setMessages((prev) => {
          const ai = prev.find((m) => m.id === aiMsgId);
          if (ai && !ai.content) {
            return prev.filter((m) => m.id !== aiMsgId);
          }
          return prev.map((m) =>
            m.id === aiMsgId ? { ...m, isStreaming: false } : m,
          );
        });
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
