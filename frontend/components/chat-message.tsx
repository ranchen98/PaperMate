"use client";

import { cn, formatTime } from "@/lib/utils";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Markdown } from "@/components/prompt-kit/markdown";
import { Loader } from "@/components/prompt-kit/loader";
import { Bot, User, Wrench, Check, Loader2 } from "lucide-react";
import type { ChatMessage } from "@/lib/types";
import { getToolDisplayName, getAgentDisplay } from "@/lib/tool-names";
import { AgentResponse } from "@/components/agents-ui/agent-response";

type ChatMessageItemProps = {
  message: ChatMessage;
};

export function ChatMessageItem({ message }: ChatMessageItemProps) {
  if (message.role === "tool") {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground">
        <Wrench className="size-3.5 shrink-0" />
        <span>使用工具: {getToolDisplayName(message.tool_name)}</span>
      </div>
    );
  }

  if (message.role === "agent") {
    return <AgentSection message={message} />;
  }

  const isHuman = message.role === "human";
  const showLoader = message.isStreaming && !message.content;

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
          <Markdown className="prose prose-sm max-w-none rounded-lg bg-secondary p-2.5 break-words whitespace-normal dark:prose-invert">
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

type AgentSectionProps = {
  message: ChatMessage;
};

function AgentSection({ message }: AgentSectionProps) {
  const display = getAgentDisplay(message.agent);
  const Icon = display?.icon ?? Bot;
  const name = display?.name ?? "Agent";
  const isRunning = message.status === "running";

  return (
    <div className="flex gap-3 px-1">
      <Avatar className="size-8 shrink-0">
        <AvatarFallback className="bg-muted text-muted-foreground">
          <Icon className="size-4" />
        </AvatarFallback>
      </Avatar>

      <div className="flex max-w-[80%] flex-col gap-1.5 items-start">
        {/* 头部：Agent 名 + 状态徽标 */}
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="font-medium text-foreground/80">{name}</span>
          {isRunning ? (
            <span className="inline-flex items-center gap-1 text-primary">
              <Loader2 className="size-3 animate-spin" />
              <span>运行中</span>
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-muted-foreground">
              <Check className="size-3" />
              <span>完成</span>
            </span>
          )}
        </div>

        {/* agents-kit AgentResponse：展示工具调用 + 流式正文 */}
        <div className="w-full rounded-lg bg-secondary/50 p-3">
          <AgentResponse
            id={message.id}
            message={message.content}
            toolCalls={message.toolCalls}
            isStreaming={message.isStreaming}
          />
        </div>
      </div>
    </div>
  );
}
