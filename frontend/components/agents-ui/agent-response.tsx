"use client"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import {
  Copy,
  RefreshCw,
  Wrench,
} from "lucide-react"
import { Markdown } from "@/components/prompt-kit/markdown"
import {
  Reasoning,
  ReasoningTrigger,
  ReasoningContent,
} from "@/components/prompt-kit/reasoning"
import type { ToolCall } from "@/lib/types"
import { getToolDisplayName } from "@/lib/tool-names"

export interface AgentResponseProps {
  message: string
  thinking?: string
  toolCalls?: ToolCall[]
  isStreaming?: boolean
  id?: string
  className?: string
  onRegenerate?: () => void
  onCopy?: () => void
}

export function AgentResponse({
  message,
  thinking,
  toolCalls = [],
  isStreaming = false,
  id,
  className,
  onRegenerate,
  onCopy,
}: AgentResponseProps) {
  return (
    <div className={cn("space-y-3", className)}>
      {/* Thinking Process */}
      {thinking && (
        <Reasoning isStreaming={isStreaming}>
          <ReasoningTrigger className="text-xs text-muted-foreground">
            思考过程
          </ReasoningTrigger>
          <ReasoningContent className="max-h-40 overflow-y-auto">
            <div className="text-xs italic whitespace-pre-wrap break-words">
              {thinking}
            </div>
          </ReasoningContent>
        </Reasoning>
      )}

      {/* Tool Calls */}
      {toolCalls.length > 0 && (
        <div className="space-y-1.5">
          {toolCalls.map((toolCall) => (
            <div
              key={toolCall.id}
              className="flex items-center gap-2 text-xs text-muted-foreground"
            >
              <Wrench className="size-3.5 shrink-0" />
              <span>使用工具: {getToolDisplayName(toolCall.name)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Main Message */}
      {message ? (
        <div className="prose prose-sm dark:prose-invert max-w-none break-words">
          <Markdown id={id}>{message}</Markdown>
          {isStreaming && (
            <span className="inline-block w-1 h-4 bg-foreground animate-pulse ml-1" />
          )}
        </div>
      ) : isStreaming && !thinking ? (
        <div className="text-sm text-muted-foreground animate-pulse">
          thinking...
        </div>
      ) : null}

      {/* Actions */}
      {!isStreaming && (onRegenerate || onCopy) && (
        <div className="flex items-center gap-2 pt-2">
          {onRegenerate && (
            <Button
              size="sm"
              variant="ghost"
              onClick={onRegenerate}
              className="h-8 text-xs"
            >
              <RefreshCw className="h-3 w-3 mr-1" />
              Regenerate
            </Button>
          )}
          {onCopy && (
            <Button
              size="sm"
              variant="ghost"
              onClick={onCopy}
              className="h-8 text-xs"
            >
              <Copy className="h-3 w-3 mr-1" />
              Copy
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
