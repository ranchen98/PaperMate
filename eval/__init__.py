"""PaperMate 评估模块。

仅做单 Agent RAG 评估：非侵入式 trace + ragas 指标。
导入本包时会先行注册 ragas 兼容 shim（见 _ragas_compat）。
"""

from eval import _ragas_compat  # noqa: F401  保证 shim 先生效