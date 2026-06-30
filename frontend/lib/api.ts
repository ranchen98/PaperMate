import type {
  AgentName,
  AuthUser,
  ChatRequest,
  HistoryResponse,
  PaperFile,
  StreamEvent,
  ThreadListResponse,
} from "@/lib/types";
import { ApiError } from "@/lib/types";

export const UNAUTHORIZED_EVENT = "papermate:unauthorized";

function notifyUnauthorized() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
  }
}

async function parseBody(res: Response): Promise<{ code: number; message: string; data: unknown }> {
  try {
    return await res.json();
  } catch {
    return { code: res.status, message: "", data: null };
  }
}

async function getJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { credentials: "same-origin", ...init });
  if (!res.ok) {
    const body = await parseBody(res);
    if (res.status === 401) notifyUnauthorized();
    throw new ApiError(
      res.status,
      body?.message || `HTTP ${res.status}: ${res.statusText}`,
    );
  }
  const body = await res.json();
  if (body.code !== 200) {
    if (body.code === 401) notifyUnauthorized();
    throw new ApiError(body.code, body.message || `业务错误 ${body.code}`);
  }
  return body.data as T;
}

export async function fetchMe(): Promise<AuthUser> {
  return getJson<AuthUser>("/auth/me");
}

export async function login(username: string, password: string): Promise<AuthUser> {
  return getJson<AuthUser>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
}

export async function register(username: string, password: string): Promise<AuthUser> {
  return getJson<AuthUser>("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
}

export async function logout(): Promise<void> {
  await getJson<null>("/auth/logout", { method: "POST" });
}

export async function fetchThreads(): Promise<ThreadListResponse> {
  return getJson<ThreadListResponse>(`/chat/get_thread_ids`);
}

export async function fetchHistory(threadId: string): Promise<HistoryResponse> {
  return getJson<HistoryResponse>(
    `/chat/get_history?thread_id=${encodeURIComponent(threadId)}`,
  );
}

export async function deleteThread(threadId: string): Promise<void> {
  await getJson(`/chat/delete_session?thread_id=${encodeURIComponent(threadId)}`);
}

export async function fetchPapers(): Promise<PaperFile[]> {
  return getJson<PaperFile[]>(`/paper/files`);
}

export async function uploadPapers(
  files: File[],
  topic: string = "",
): Promise<PaperFile[]> {
  const form = new FormData();
  for (const file of files) {
    form.append("files", file);
  }
  form.append("topic", topic);

  const res = await fetch("/paper/upload", {
    method: "POST",
    credentials: "same-origin",
    body: form,
  });
  if (!res.ok) {
    const body = await parseBody(res);
    if (res.status === 401) notifyUnauthorized();
    throw new ApiError(
      res.status,
      body?.message || `HTTP ${res.status}: ${res.statusText}`,
    );
  }
  const body = await res.json();
  if (body.code !== 200) {
    if (body.code === 401) notifyUnauthorized();
    throw new ApiError(body.code, body.message || `业务错误 ${body.code}`);
  }
  return body.data as PaperFile[];
}

export async function deletePaper(fileId: string): Promise<void> {
  const res = await fetch(`/paper/files/${encodeURIComponent(fileId)}`, {
    method: "DELETE",
    credentials: "same-origin",
  });
  if (!res.ok) {
    const body = await parseBody(res);
    if (res.status === 401) notifyUnauthorized();
    throw new ApiError(
      res.status,
      body?.message || `HTTP ${res.status}: ${res.statusText}`,
    );
  }
  const body = await res.json();
  if (body.code !== 200) {
    if (body.code === 401) notifyUnauthorized();
    throw new ApiError(body.code, body.message || `业务错误 ${body.code}`);
  }
}

export async function* streamChat(
  request: ChatRequest,
): AsyncGenerator<StreamEvent, void, unknown> {
  const res = await fetch("/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(request),
  });

  if (!res.ok || !res.body) {
    if (res.status === 401) notifyUnauthorized();
    throw new ApiError(res.status, `HTTP ${res.status}: ${res.statusText}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";

    for (const event of events) {
      const lines = event.split("\n");
      let eventName = "message";
      let dataLine = "";
      for (const line of lines) {
        if (line.startsWith("event: ")) {
          eventName = line.slice(7).trim();
        } else if (line.startsWith("data: ")) {
          dataLine = line.slice(6);
        }
      }
      if (!dataLine) continue;

      if (eventName === "error") {
        let errMsg = "调用失败";
        try {
          const err = JSON.parse(dataLine);
          errMsg = err.message || errMsg;
        } catch {
          errMsg = dataLine;
        }
        throw new ApiError(500, errMsg);
      }

      // 解析 data 负载（agent_start/agent_end 与 ai/tool 共用 JSON data 体）
      let parsed: {
        agent?: string;
        role?: string;
        content?: string;
        tool_name?: string;
      };
      try {
        parsed = JSON.parse(dataLine);
      } catch {
        yield { role: "ai", content: dataLine };
        continue;
      }

      if (eventName === "agent_start" || eventName === "agent_end") {
        yield {
          event: eventName,
          agent: parsed.agent as AgentName,
        } as StreamEvent;
        continue;
      }

      yield parsed as unknown as StreamEvent;
    }
  }
}
