import type {
  ChatRequest,
  HistoryResponse,
  StreamEvent,
  ThreadListResponse,
} from "@/lib/types";

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  const body = await res.json();
  if (body.code !== 200) throw new Error(body.message || `业务错误 ${body.code}`);
  return body.data as T;
}

export async function fetchThreads(userId: string): Promise<ThreadListResponse> {
  return getJson<ThreadListResponse>(
    `/chat/get_thread_ids?user_id=${encodeURIComponent(userId)}`,
  );
}

export async function fetchHistory(threadId: string): Promise<HistoryResponse> {
  return getJson<HistoryResponse>(
    `/chat/get_history?thread_id=${encodeURIComponent(threadId)}`,
  );
}

export async function deleteThread(threadId: string): Promise<void> {
  await getJson(
    `/chat/delete_session?thread_id=${encodeURIComponent(threadId)}`,
  );
}

export async function* streamChat(
  request: ChatRequest,
): AsyncGenerator<StreamEvent, void, unknown> {
  const res = await fetch("/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  if (!res.body) throw new Error("Response body is null");

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
          // 非 JSON 错误，用原文
          errMsg = dataLine;
        }
        throw new Error(errMsg);
      }

      try {
        yield JSON.parse(dataLine) as StreamEvent;
      } catch {
        // 兼容旧格式纯文本，作为 ai content 处理
        yield { role: "ai", content: dataLine };
      }
    }
  }
}
