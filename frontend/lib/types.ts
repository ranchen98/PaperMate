export type Role = "human" | "ai" | "tool" | "agent";

// 多 Agent 系统的专家节点名
export type AgentName = "retrieval" | "writing" | "review";

// 工具调用记录（用于 AgentResponse 组件展示）
export type ToolCall = {
  id: string;
  name: string;
  input?: unknown;
  output?: unknown;
  status: "pending" | "running" | "completed" | "failed";
  duration?: number;
};

export type ChatMessage = {
  id: string;
  role: Role;
  content: string;
  timestamp?: string;
  tool_name?: string;
  isStreaming?: boolean;
  // 多 Agent：标记该消息归属哪个专家 Agent
  agent?: AgentName;
  // Agent 消息的运行状态
  status?: "running" | "done";
  // Agent 消息持有的工具调用列表（agents-ui AgentResponse 消费）
  toolCalls?: ToolCall[];
};

export type Thread = {
  thread_id: string;
  latest_message: string;
  update_time: string;
};

export type ChatRequest = {
  thread_id: string;
  message: string;
  user_id: string;
};

export type RawHistoryItem = {
  role: string;
  content: string;
  timestamp?: string;
  tool_name?: string;
  agent?: AgentName;
};

export type HistoryResponse = RawHistoryItem[];

export type StreamEvent =
  | { role: "ai"; content: string; agent?: AgentName }
  | { role: "tool"; tool_name: string; agent?: AgentName }
  | { event: "agent_start"; agent: AgentName }
  | { event: "agent_end"; agent: AgentName };

export type ThreadListResponse = Thread[];

export type PaperFile = {
  file_id: string;
  user_id: string;
  file_name: string;
  file_path: string;
  md5: string;
  topic: string;
  upload_time: string;
  update_time: string;
};

export type AuthUser = {
  user_id: string;
  username: string;
};

export class ApiError extends Error {
  code: number;
  constructor(code: number, message: string) {
    super(message);
    this.code = code;
    this.name = "ApiError";
  }
}

export function generateThreadId(): string {
  return `sess_${Date.now()}`;
}
