"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { ChevronRight, Layers } from "lucide-react";
import type { ChatMessage } from "@/lib/types";
import { AgentCard } from "@/components/chat-message";

type AgentTurnGroupProps = {
  messages: ChatMessage[];
};

/**
 * 一轮用户提问下的"专家处理组"：把同 turn_id 的 consecutive agent 消息
 * 聚合到一个折叠容器里，仅展示最终答复在主对话框（由调用方负责）。
 */
export function AgentTurnGroup({ messages }: AgentTurnGroupProps) {
  const running = messages.some((m) => m.status === "running");
  // 整组默认：有正在工作的卡 -> 展开；否则折叠
  const [open, setOpen] = useState(running);

  const experts = messages.length;

  return (
    <div className="flex gap-3 px-1">
      <div className="flex-1">
        <div className="rounded-lg border bg-muted/30">
          {/* 组标题 */}
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted/50"
          >
            <Layers className="size-4 text-muted-foreground" />
            <span className="font-medium text-foreground/80">
              本轮处理
            </span>
            <span className="text-xs text-muted-foreground">
              · {experts} 个 Agent
            </span>
            {running && (
              <span className="inline-flex items-center gap-1 text-primary">
                <span className="size-1.5 animate-pulse rounded-full bg-primary" />
                <span className="text-xs">进行中</span>
              </span>
            )}
            <span className="ml-auto text-muted-foreground">
              <ChevronRight
                className={cn(
                  "size-4 transition-transform",
                  open && "rotate-90",
                )}
              />
            </span>
          </button>

          {/* 展开体：各专家卡（自管折叠状态） */}
          {open && (
            <div className="space-y-2 border-t px-3 py-3">
              {messages.map((m) => (
                <AgentCard key={m.id} message={m} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}