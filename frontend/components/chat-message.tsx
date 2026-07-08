"use client";

import { cn } from "@/lib/utils";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Loader } from "@/components/prompt-kit/loader";
import { Bot, User, CornerUpLeft, Play } from "lucide-react";
import type { ChatMessage } from "@/lib/types";
import { AgentResponse } from "@/components/agents-ui/agent-response";
import { AgentCards } from "@/components/agents-ui/agent-cards";

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
  onDownload?: () => void;
  onRewind?: (messageId: string) => void;
  onResume?: () => void;
  canRewind?: boolean;
};

export function ChatMessageItem({
  message,
  onDownload,
  onRewind,
  onResume,
  canRewind,
}: ChatMessageItemProps) {
  const isHuman = message.role === "human";
  const hasToolCalls = (message.toolCalls?.length ?? 0) > 0;
  const isMultiAgent = (message.agentCards?.length ?? 0) > 0;
  const showLoader = message.isStreaming && !message.content && !hasToolCalls && !isMultiAgent;

  return (
    <div
      className={cn(
        "group flex gap-3 px-1",
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
          <>
            <div className="whitespace-pre-wrap break-words rounded-lg bg-primary p-2.5 text-primary-foreground">
              {message.content}
            </div>
            {canRewind && onRewind && message.forkCheckpointId && (
              <Button
                variant="ghost"
                size="sm"
                className="h-6 gap-1 px-2 text-xs text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
                onClick={() => onRewind(message.id)}
                title="回溯到此点重新提问"
              >
                <CornerUpLeft className="size-3" />
                回溯
              </Button>
            )}
          </>
        ) : isMultiAgent ? (
          <div className="rounded-lg bg-secondary p-2.5 w-full max-w-full">
            <AgentCards
              cards={message.agentCards!}
              isReportReady={message.isReportReady}
              onDownload={onDownload}
            />
          </div>
        ) : (
          <div className="rounded-lg bg-secondary p-2.5">
            <AgentResponse
              id={message.id}
              message={message.content}
              thinking={message.thinking}
              toolCalls={message.toolCalls}
              isStreaming={message.isStreaming}
            />
          </div>
        )}
        {message.isInterrupted && onResume && (
          <Button
            variant="outline"
            size="sm"
            className="h-7 gap-1.5 text-xs"
            onClick={onResume}
          >
            <Play className="size-3" />
            继续生成
          </Button>
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
