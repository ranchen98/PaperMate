"""ragas 0.4.x / langchain-community 0.4 兼容 shim。

langchain-community 0.4 已移除 `langchain_community.chat_models.vertexai`，
但 ragas 0.4.3 在顶层无条件 `from langchain_community.chat_models.vertexai import ChatVertexAI`，
导致非 Vertex 用户也无法 import。本 shim 在 import ragas 前注册一个最小 stub 模块，
仅用作 `isinstance` / 类型参考，永远不会被实例化（我们用 DashScope 兼容的 ChatOpenAI）。
"""

from __future__ import annotations

import sys
import types


def _ensure_stub() -> None:
    mod_name = "langchain_community.chat_models.vertexai"
    if mod_name in sys.modules:
        return
    try:
        __import__(mod_name)
        return
    except ImportError:
        pass

    stub = types.ModuleType(mod_name)
    stub.__doc__ = "Stub injected by eval/_ragas_compat.py for ragas 0.4 compatibility."

    class ChatVertexAI:  # noqa: D401 - minimal stub, never instantiated
        """Placeholder for langchain_community VertexAI chat model.

        ragas references this class only in MULTIPLE_COMPLETION_SUPPORTED /
        isinstance checks; it is never constructed by PaperMate evaluations.
        """

    stub.ChatVertexAI = ChatVertexAI
    sys.modules[mod_name] = stub

    # 让 `import langchain_community.chat_models.vertexai` 也能从父包 getattr 命中
    try:
        import langchain_community.chat_models as _cm  # noqa: F401

        if not hasattr(_cm, "vertexai"):
            _cm.vertexai = stub
    except Exception:
        pass


_ensure_stub()