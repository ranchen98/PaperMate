"use client";

import { useState } from "react";
import { ArrowUp, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  PromptInput,
  PromptInputTextarea,
  PromptInputActions,
  PromptInputAction,
} from "@/components/prompt-kit/prompt-input";

type ChatInputProps = {
  isStreaming: boolean;
  onSend: (content: string) => void;
  onStop: () => void;
};

export function ChatInput({ isStreaming, onSend, onStop }: ChatInputProps) {
  const [value, setValue] = useState("");

  const handleSubmit = () => {
    if (!value.trim() || isStreaming) return;
    onSend(value);
    setValue("");
  };

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pb-4">
      <PromptInput
        value={value}
        onValueChange={setValue}
        onSubmit={handleSubmit}
        isLoading={isStreaming}
        className="rounded-2xl"
      >
        <PromptInputTextarea placeholder="输入消息… (Enter 发送, Shift+Enter 换行)" />
        <PromptInputActions className="justify-end">
          {isStreaming ? (
            <Button
              size="icon"
              variant="destructive"
              onClick={onStop}
              title="停止生成"
            >
              <Square className="size-4" />
            </Button>
          ) : (
            <PromptInputAction tooltip="发送">
              <Button
                size="icon"
                onClick={handleSubmit}
                disabled={!value.trim()}
              >
                <ArrowUp />
              </Button>
            </PromptInputAction>
          )}
        </PromptInputActions>
      </PromptInput>
    </div>
  );
}
