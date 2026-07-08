"use client";

import { useEffect, useState } from "react";
import {
  ChatContainerRoot,
  ChatContainerContent,
} from "@/components/prompt-kit/chat-container";
import { ScrollButton } from "@/components/prompt-kit/scroll-button";
import { Loader } from "@/components/prompt-kit/loader";
import { ChatMessageItem } from "@/components/chat-message";
import type { ChatMessage } from "@/lib/types";

type ChatMessageListProps = {
  messages: ChatMessage[];
  isLoadingHistory: boolean;
  onDownload?: () => void;
  onRewind?: (messageId: string) => void;
  onResume?: () => void;
  canRewind?: boolean;
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

export function ChatMessageList({
  messages,
  isLoadingHistory,
  onDownload,
  onRewind,
  onResume,
  canRewind,
}: ChatMessageListProps) {
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
            messages.map((message) => (
              <ChatMessageItem
                key={message.id}
                message={message}
                onDownload={onDownload}
                onRewind={onRewind}
                onResume={onResume}
                canRewind={canRewind}
              />
            ))
          )}
          <ClientScrollButton />
        </ChatContainerContent>
      </ChatContainerRoot>
    </div>
  );
}
