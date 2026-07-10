"""进程内流式生成中断信号注册表。

为 /chat/stop 提供"软中断"能力：stop 请求 set 一个 threading.Event，
正在跑的 chat_streaming_response 生成器在两次 chunk 之间检查该 Event，
命中则提前结束循环，从而让 LangGraph 停在最近的未完成 super-step
（checkpoint 的 state.next 非空），配合既有的 is_interrupted 检测与
/chat/resume 断点续聊链路即可恢复生成。

约束：依赖 uvicorn 单 worker（当前 docker-compose 默认），多 worker
需改为共享存储（如 Redis 或 SQLite 信号位）。
"""

import threading


class StreamRegistry:
    def __init__(self):
        self._events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def register(self, thread_id: str) -> threading.Event:
        with self._lock:
            ev = threading.Event()
            self._events[thread_id] = ev
            return ev

    def get(self, thread_id: str) -> threading.Event | None:
        with self._lock:
            return self._events.get(thread_id)

    def cancel(self, thread_id: str) -> bool:
        with self._lock:
            ev = self._events.get(thread_id)
        if ev is None:
            return False
        ev.set()
        return True

    def unregister(self, thread_id: str) -> None:
        with self._lock:
            self._events.pop(thread_id, None)


stream_registry = StreamRegistry()