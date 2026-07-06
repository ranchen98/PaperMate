export type Role = "human" | "ai" | "tool";

export type AgentMode = "single" | "multi";

export type ToolCall = {
  id: string;
  name: string;
  input?: unknown;
  output?: unknown;
  status: "pending" | "running" | "completed" | "failed";
  duration?: number;
};

export type AgentCardSection = {
  sectionId?: string;
  sectionTitle?: string;
  content: string;
  thinking?: string;
};

export type AgentCard = {
  agent: string;
  sections: AgentCardSection[];
  status: "running" | "done";
};

export type ChatMessage = {
  id: string;
  role: Role;
  content: string;
  timestamp?: string;
  tool_name?: string;
  isStreaming?: boolean;
  toolCalls?: ToolCall[];
  thinking?: string;
  agentCards?: AgentCard[];
  isReportReady?: boolean;
};

export type Thread = {
  thread_id: string;
  latest_message: string;
  update_time: string;
  agent_mode?: AgentMode;
};

export type ChatRequest = {
  thread_id: string;
  message: string;
  user_id: string;
  agent_mode: AgentMode;
};

export type RawHistoryItem =
  | { role: "human"; content: string; timestamp?: string }
  | {
      role: "turn";
      turn_id: number;
      tools: string[];
      ai_content: string;
      thinking?: string;
      is_multi?: boolean;
      agent_messages?: {
        agent: string;
        section_id?: string;
        section_title?: string;
        content: string;
      }[];
      report_ready?: boolean;
    };

export type HistoryResponse = RawHistoryItem[];

export type StreamEvent =
  | { role: "ai"; content: string; agent?: string; section_id?: string; section_title?: string }
  | { role: "thinking"; content: string; agent?: string; section_id?: string; section_title?: string }
  | { role: "tool"; tool_name: string };

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
