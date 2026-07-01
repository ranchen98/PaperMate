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
  // 该消息所属"用户提问轮次"的 id（同一次 sendMessage 下所有消息共用一个 turn_id）
  turn_id?: number;
  // 标记：该消息的正文已被提升为"最终答复"展示在主对话框，
  // 其所在 Agent 卡片不再重复显示正文（仅展示工具/状态摘要）
  isFinalSource?: boolean;
  // 标记：这是一条"最终答复"消息（role 为 ai，渲染在主对话框突出位置）
  isFinalAnswer?: boolean;
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

// 历史回放中的单条专家卡片（来自后端分组结构）
export type HistoryAgentCard = {
  agent: AgentName;
  thought: string;
  tools: string[];
};

// 历史回放分组项：用户消息 / 一轮 Agent 处理
export type RawHistoryItem =
  | { role: "human"; content: string; timestamp?: string }
  | {
      role: "turn";
      turn_id: number;
      agents: HistoryAgentCard[];
      final_answer: string;
    };

export type HistoryResponse = RawHistoryItem[];

export type StreamEvent =
  | { role: "ai"; content: string; agent?: AgentName; final?: boolean }
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
