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
