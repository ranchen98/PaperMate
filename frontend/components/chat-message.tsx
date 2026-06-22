"use client";

import { cn, formatTime } from "@/lib/utils";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Markdown } from "@/components/prompt-kit/markdown";
import { Loader } from "@/components/prompt-kit/loader";
import { Bot, User, Wrench } from "lucide-react";
import type { ChatMessage } from "@/lib/types";

type ChatMessageItemProps = {
  message: ChatMessage;
};

export function ChatMessageItem({ message }: ChatMessageItemProps) {
  if (message.role === "tool") {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground">
        <Wrench className="size-3.5 shrink-0" />
        <span>使用工具: {message.tool_name}</span>
      </div>
    );
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
