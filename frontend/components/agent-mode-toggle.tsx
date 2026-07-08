"use client";

import { FlaskConical } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { AgentMode } from "@/lib/types";

type AgentModeToggleProps = {
  mode: AgentMode;
  onModeChange: (mode: AgentMode) => void;
  disabled?: boolean;
};

export function AgentModeToggle({
  mode,
  onModeChange,
  disabled,
}: AgentModeToggleProps) {
  const checked = mode === "multi";

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            className={cn(
              "flex items-center gap-1.5",
              disabled && "pointer-events-none opacity-60",
            )}
          >
            <FlaskConical
              className={cn(
                "size-3.5 shrink-0",
                checked ? "text-primary" : "text-muted-foreground",
              )}
            />
            <span
              className={cn(
                "select-none text-xs",
                checked
                  ? "font-medium text-primary"
                  : "text-muted-foreground",
              )}
            >
              科研报告
            </span>
            <Switch
              checked={checked}
              onCheckedChange={(v) => onModeChange(v ? "multi" : "single")}
              disabled={disabled}
              aria-label="切换科研报告模式"
            />
          </div>
        </TooltipTrigger>
        <TooltipContent side="top">
          科研报告模式：多 Agent 协作生成科研报告
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}