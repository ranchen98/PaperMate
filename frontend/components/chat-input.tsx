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
import { AgentModeToggle } from "@/components/agent-mode-toggle";
import type { AgentMode } from "@/lib/types";

type ChatInputProps = {
  isStreaming: boolean;
  mode: AgentMode;
  onModeChange: (mode: AgentMode) => void;
  onSend: (content: string) => void;
  onStop: () => void;
};

export function ChatInput({
  isStreaming,
  mode,
  onModeChange,
  onSend,
  onStop,
}: ChatInputProps) {
  const [value, setValue] = useState("");

  const handleSubmit = () => {
    if (!value.trim() || isStreaming) return;
    onSend(value);
    setValue("");
  };

  const placeholder =
    mode === "multi"
      ? "描述你需要生成的科研报告… (Enter 发送, Shift+Enter 换行)"
      : "输入消息… (Enter 发送, Shift+Enter 换行)";

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pb-4">
      <PromptInput
        value={value}
        onValueChange={setValue}
        onSubmit={handleSubmit}
        isLoading={isStreaming}
        className="rounded-2xl"
      >
        <div className="flex items-center justify-between px-2 pt-1">
          <AgentModeToggle
            mode={mode}
            onModeChange={onModeChange}
            disabled={isStreaming}
          />
        </div>
        <PromptInputTextarea placeholder={placeholder} />
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