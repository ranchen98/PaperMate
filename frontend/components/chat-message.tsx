"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Markdown } from "@/components/prompt-kit/markdown";
import { Loader } from "@/components/prompt-kit/loader";
import { Bot, User, Wrench, Check, Loader2, ChevronRight } from "lucide-react";
import type { ChatMessage } from "@/lib/types";
import { getToolDisplayName, getAgentDisplay } from "@/lib/tool-names";
import { AgentResponse } from "@/components/agents-ui/agent-response";

function formatTime(ts: string): string {
  const num = Number(ts);
  const date = Number.isFinite(num) ? new Date(num * 1000) : new Date(ts);
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

type ChatMessageItemProps = {
  message: ChatMessage;
};

export function ChatMessageItem({ message }: ChatMessageItemProps) {
  // 工具行（无 agent 归属的兼容态）：尽量不直接走到这里，由 AgentTurnGroup 处理
  if (message.role === "tool") {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground">
        <Wrench className="size-3.5 shrink-0" />
        <span>使用工具: {getToolDisplayName(message.tool_name)}</span>
      </div>
    );
  }

  if (message.role === "agent") {
    return <AgentCard message={message} expanded />; // 兜底独立渲染（不应触发）
  }

  const isHuman = message.role === "human";
  const showLoader = message.isStreaming && !message.content;
  const isFinalAnswer = message.isFinalAnswer;

  return (
    <div
      className={cn(
        "flex gap-3 px-1",
        isHuman && "flex-row-reverse",
      )}
    >
      <Avatar className="size-8 shrink-0">
        <AvatarFallback
          className={cn(
            isHuman
              ? "bg-primary text-primary-foreground"
              : "bg-muted text-muted-foreground",
          )}
        >
          {isHuman ? <User className="size-4" /> : <Bot className="size-4" />}
        </AvatarFallback>
      </Avatar>

      <div
        className={cn(
          "flex max-w-[80%] flex-col gap-1",
          isHuman ? "items-end" : "items-start",
        )}
      >
        {showLoader ? (
          <div className="rounded-lg bg-secondary p-3">
            <Loader variant="typing" size="sm" />
          </div>
        ) : isHuman ? (
          <div className="whitespace-pre-wrap break-words rounded-lg bg-primary p-2.5 text-primary-foreground">
            {message.content}
          </div>
        ) : message.isStreaming ? (
          <div className="whitespace-pre-wrap break-words rounded-lg bg-secondary p-2.5">
            {message.content}
            <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-foreground align-middle" />
          </div>
        ) : (
          <Markdown
            className={cn(
              "prose prose-sm max-w-none rounded-lg bg-secondary p-2.5 break-words whitespace-normal dark:prose-invert",
              isFinalAnswer && "border border-primary/30 bg-primary/5",
            )}
          >
            {message.content}
          </Markdown>
        )}
        {message.timestamp && isHuman && (
          <span className="px-1 text-xs text-muted-foreground">
            {formatTime(message.timestamp)}
          </span>
        )}
      </div>
    </div>
  );
}

type AgentCardProps = {
  message: ChatMessage;
  expanded?: boolean;
  defaultExpanded?: boolean;
  onToggle?: (open: boolean) => void;
};

/** 单个专家卡：折叠展开 + 工具 chip + 思考过程正文。 */
export function AgentCard({
  message,
  defaultExpanded,
  onToggle,
}: AgentCardProps) {
  const display = getAgentDisplay(message.agent);
  const Icon = display?.icon ?? Bot;
  const name = display?.name ?? "Agent";
  const isRunning = message.status === "running";
  const isFinalSource = message.isFinalSource;

  // 默认全部折叠（含流式进行中的卡）；用户主动点开查看进度
  const [open, setOpen] = useState(defaultExpanded ?? false);

  const handleToggle = () => {
    const next = !open;
    setOpen(next);
    onToggle?.(next);
  };

  return (
    <div className="rounded-lg border bg-secondary/40">
      {/* 标题行 */}
      <button
        type="button"
        onClick={handleToggle}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-secondary/60"
      >
        <Avatar className="size-6 shrink-0">
          <AvatarFallback className="bg-muted text-muted-foreground">
            <Icon className="size-3.5" />
          </AvatarFallback>
        </Avatar>
        <span className="font-medium text-foreground/80">{name}</span>
        {isRunning ? (
          <span className="inline-flex items-center gap-1 text-primary">
            <Loader2 className="size-3 animate-spin" />
            <span className="text-xs">工作中</span>
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-muted-foreground">
            <Check className="size-3" />
            <span className="text-xs">完成</span>
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

      {/* 展开体 */}
      {open && (
        <div className="border-t px-3 py-2.5">
          <AgentResponse
            id={message.id}
            message={isFinalSource ? "" : message.content}
            toolCalls={message.toolCalls}
            isStreaming={message.isStreaming}
          />
          {isFinalSource && (
            <div className="text-xs text-muted-foreground">
              已输出最终答复，见下方对话框。
            </div>
          )}
        </div>
      )}
    </div>
  );
}