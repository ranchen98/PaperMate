"use client";

import { useEffect, useState } from "react";
import {
  ChatContainerRoot,
  ChatContainerContent,
} from "@/components/prompt-kit/chat-container";
import { ScrollButton } from "@/components/prompt-kit/scroll-button";
import { Loader } from "@/components/prompt-kit/loader";
import { ChatMessageItem } from "@/components/chat-message";
import { AgentTurnGroup } from "@/components/agent-turn-group";
import type { ChatMessage } from "@/lib/types";

type ChatMessageListProps = {
  messages: ChatMessage[];
  isLoadingHistory: boolean;
};

function ClientScrollButton() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return null;
  return (
    <div className="sticky bottom-4 flex w-full justify-center">
      <ScrollButton />
    </div>
  );
}

/**
 * 把扁平 messages 切分为按 turn_id 分组的渲染单元：
 *   - human 消息 -> ChatMessageItem（气泡）
 *   - 同 turn_id 的连续 agent 消息 -> AgentTurnGroup（折叠组）
 *   - role==="ai" 兜底 / 最终答复 -> ChatMessageItem（主对话气泡）
 * 注意：isFinalSource 标记的 agent 卡不显示正文（已提升为主对话最终答复），
 *       故不在此处重复渲染；AgentTurnGroup 内部的 AgentCard 自行处理。
 */
type RenderUnit =
  | { kind: "single"; message: ChatMessage }
  | { kind: "group"; messages: ChatMessage[] };

function buildRenderUnits(messages: ChatMessage[]): RenderUnit[] {
  const units: RenderUnit[] = [];
  let i = 0;
  while (i < messages.length) {
    const m = messages[i];
    if (m.role === "tool") {
      // 无 agent 归属的兼容态工具行：独立渲染
      units.push({ kind: "single", message: m });
      i += 1;
      continue;
    }
    if (m.role !== "agent") {
      units.push({ kind: "single", message: m });
      i += 1;
      continue;
    }
    // 聚合同 turn_id 的连续 agent 消息为一组
    const tid = m.turn_id;
    const group: ChatMessage[] = [];
    while (
      i < messages.length &&
      messages[i].role === "agent" &&
      messages[i].turn_id === tid
    ) {
      group.push(messages[i]);
      i += 1;
    }
    units.push({ kind: "group", messages: group });
  }
  return units;
}

export function ChatMessageList({
  messages,
  isLoadingHistory,
}: ChatMessageListProps) {
  const units = buildRenderUnits(messages);
  return (
    <div className="relative flex-1 overflow-hidden">
      <ChatContainerRoot className="h-full">
        <ChatContainerContent className="mx-auto w-full max-w-3xl gap-4 px-4 py-6">
          {isLoadingHistory ? (
            <div className="flex items-center justify-center py-20">
              <Loader variant="classic" size="md" />
            </div>
          ) : messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 py-20 text-center">
              <div className="rounded-full bg-muted p-4">
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  className="size-8 text-muted-foreground"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 0 1 .865-.501 48.172 48.172 0 0 0 3.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0 0 12 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018Z"
                  />
                </svg>
              </div>
              <div className="space-y-1">
                <p className="text-lg font-medium">PaperMate</p>
                <p className="text-sm text-muted-foreground">
                  开始新的对话，问我任何问题
                </p>
              </div>
            </div>
          ) : (
            units.map((unit, idx) =>
              unit.kind === "single" ? (
                <ChatMessageItem
                  key={unit.message.id}
                  message={unit.message}
                />
              ) : (
                <AgentTurnGroup
                  key={`turn-${unit.messages[0]?.turn_id ?? idx}`}
                  messages={unit.messages}
                />
              ),
            )
          )}
          <ClientScrollButton />
        </ChatContainerContent>
      </ChatContainerRoot>
    </div>
  );
}
