import type { LucideIcon } from "lucide-react";
import { Search, PenLine, ShieldCheck } from "lucide-react";
import type { AgentName } from "@/lib/types";

const TOOL_DISPLAY_NAMES: Record<string, string> = {
  web_search: "联网搜索",
  search_paper_content: "论文内容检索",
  get_paper_chunk_context: "上下文扩展",
  query_paper_metadata: "论文信息查询",
};

export function getToolDisplayName(name?: string): string {
  if (!name) return "工具";
  return TOOL_DISPLAY_NAMES[name] ?? name;
}

// 多 Agent 显示信息
const AGENT_DISPLAY: Record<
  AgentName,
  { name: string; icon: LucideIcon }
> = {
  retrieval: { name: "检索 Agent", icon: Search },
  writing: { name: "写作 Agent", icon: PenLine },
  review: { name: "审查 Agent", icon: ShieldCheck },
};

export function getAgentDisplay(agent?: AgentName): {
  name: string;
  icon: LucideIcon;
} | null {
  if (!agent) return null;
  return AGENT_DISPLAY[agent] ?? null;
}
