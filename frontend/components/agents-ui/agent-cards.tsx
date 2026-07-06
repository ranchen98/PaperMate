"use client";

import { useEffect, useRef, useState } from "react";
import {
  Check,
  ChevronDown,
  ClipboardList,
  Download,
  FileEdit,
  Loader2,
  PenLine,
  Search,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Markdown } from "@/components/prompt-kit/markdown";
import type { AgentCard as AgentCardData, AgentCardSection } from "@/lib/types";

const AGENT_CONFIG: Record<string, { title: string; icon: React.ElementType }> = {
  planner: { title: "规划智能体", icon: ClipboardList },
  researcher: { title: "研究智能体", icon: Search },
  writer: { title: "章节撰写", icon: PenLine },
  editor: { title: "全局编辑", icon: FileEdit },
};

export type AgentCardsProps = {
  cards: AgentCardData[];
  isReportReady?: boolean;
  onDownload?: () => void;
  className?: string;
};

export function AgentCards({
  cards,
  isReportReady,
  onDownload,
  className,
}: AgentCardsProps) {
  return (
    <div className={cn("space-y-2", className)}>
      {cards.map((card, i) => (
        <AgentCardItem key={`${card.agent}-${i}`} card={card} />
      ))}
      {isReportReady && (
        <button
          onClick={onDownload}
          className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-border px-3 py-2.5 text-sm text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground"
        >
          <Download className="size-4" />
          <span>下载 Markdown 报告</span>
        </button>
      )}
    </div>
  );
}

function AgentCardItem({ card }: { card: AgentCardData }) {
  const [isOpen, setIsOpen] = useState(false);
  const config = AGENT_CONFIG[card.agent] ?? { title: card.agent, icon: FileEdit };
  const Icon = config.icon;

  useEffect(() => {
    setIsOpen(card.status === "running");
  }, [card.status]);

  const hasSections = card.sections.some((s) => s.sectionId);

  return (
    <div className="rounded-lg border border-border">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex w-full items-center gap-2 px-3 py-2 text-sm transition-colors hover:bg-muted/30"
      >
        <Icon className="size-4 text-muted-foreground shrink-0" />
        <span className="font-medium">{config.title}</span>
        {card.status === "running" ? (
          <Loader2 className="size-3.5 animate-spin text-muted-foreground ml-auto" />
        ) : (
          <Check className="size-3.5 text-green-500 ml-auto" />
        )}
        <ChevronDown
          className={cn(
            "size-4 text-muted-foreground transition-transform",
            isOpen && "rotate-180",
          )}
        />
      </button>
      {isOpen && (
        <div className="border-t border-border">
          {hasSections
            ? card.sections.map((section, i) => (
                <SectionBlock
                  key={`${section.sectionId ?? "flat"}-${i}`}
                  section={section}
                />
              ))
            : card.sections[0] && (
                <SectionBlock section={card.sections[0]} />
              )}
        </div>
      )}
    </div>
  );
}

function SectionBlock({ section }: { section: AgentCardSection }) {
  return (
    <div className="border-b border-border last:border-0">
      {section.sectionTitle && (
        <div className="px-3 py-1.5 text-xs font-medium bg-muted/30">
          {section.sectionTitle}
        </div>
      )}
      {section.thinking && <ThinkingArea content={section.thinking} />}
      {section.content ? (
        <div className="px-3 py-2 prose prose-sm dark:prose-invert max-w-none break-words">
          <Markdown>{section.content}</Markdown>
        </div>
      ) : !section.thinking ? (
        <div className="px-3 py-2 text-xs text-muted-foreground">（无内容）</div>
      ) : null}
    </div>
  );
}

function ThinkingArea({ content }: { content: string }) {
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (contentRef.current) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight;
    }
  }, [content]);

  return (
    <div
      ref={contentRef}
      className="px-3 py-2 border-b border-border/50 text-xs text-muted-foreground italic max-h-40 overflow-y-auto"
    >
      <span className="font-medium not-italic">思考过程</span>
      <div className="mt-1 whitespace-pre-wrap break-words">{content}</div>
    </div>
  );
}
