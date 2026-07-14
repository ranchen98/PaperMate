import type {
  AuthUser,
  ChatRequest,
  HistoryResponse,
  PaperFile,
  ResumeRequest,
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
  return getJson<AuthUser>("/api/auth/me");
}

export async function login(username: string, password: string): Promise<AuthUser> {
  return getJson<AuthUser>("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
}

export async function register(username: string, password: string): Promise<AuthUser> {
  return getJson<AuthUser>("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
}

export async function logout(): Promise<void> {
  await getJson<null>("/api/auth/logout", { method: "POST" });
}

export async function fetchThreads(): Promise<ThreadListResponse> {
  return getJson<ThreadListResponse>(`/api/chat/get_thread_ids`);
}

export async function fetchHistory(threadId: string): Promise<HistoryResponse> {
  return getJson<HistoryResponse>(
    `/api/chat/get_history?thread_id=${encodeURIComponent(threadId)}`,
  );
}

export async function deleteThread(threadId: string): Promise<void> {
  await getJson(`/api/chat/delete_session?thread_id=${encodeURIComponent(threadId)}`);
}

export async function fetchPapers(): Promise<PaperFile[]> {
  return getJson<PaperFile[]>(`/api/paper/files`);
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

  const res = await fetch("/api/paper/upload", {
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

export async function downloadReport(threadId: string): Promise<void> {
  const res = await fetch(
    `/api/chat/download_report?thread_id=${encodeURIComponent(threadId)}`,
    { credentials: "same-origin" },
  );
  if (!res.ok) {
    if (res.status === 401) notifyUnauthorized();
    throw new ApiError(res.status, "下载失败");
  }
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename\*=UTF-8''(.+)/);
  const filename = match ? decodeURIComponent(match[1]) : "report.md";
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export async function deletePaper(fileId: string): Promise<void> {
  const res = await fetch(`/api/paper/files/${encodeURIComponent(fileId)}`, {
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

export async function stopChat(threadId: string): Promise<void> {
  await getJson<null>(`/api/chat/stop`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id: threadId }),
  });
}

export async function* streamChat(
  request: ChatRequest,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent, void, unknown> {
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(request),
    signal,
  });

  if (!res.ok || !res.body) {
    if (res.status === 401) notifyUnauthorized();
    throw new ApiError(res.status, `HTTP ${res.status}: ${res.statusText}`);
  }

  yield* parseSseStream(res);
}

export async function* resumeChat(
  request: ResumeRequest,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent, void, unknown> {
  const res = await fetch("/api/chat/resume", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(request),
    signal,
  });

  if (!res.ok || !res.body) {
    if (res.status === 401) notifyUnauthorized();
    throw new ApiError(res.status, `HTTP ${res.status}: ${res.statusText}`);
  }

  yield* parseSseStream(res);
}

async function* parseSseStream(
  res: Response,
): AsyncGenerator<StreamEvent, void, unknown> {
  const reader = res.body!.getReader();
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

      let parsed: {
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

      yield parsed as unknown as StreamEvent;
    }
  }
}
