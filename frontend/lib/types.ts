export type Role = "human" | "ai" | "tool";

export type ChatMessage = {
  id: string;
  role: Role;
  content: string;
  timestamp?: string;
  tool_name?: string;
  isStreaming?: boolean;
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
};

export type HistoryResponse = RawHistoryItem[];

export type StreamEvent =
  | { role: "ai"; content: string }
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
