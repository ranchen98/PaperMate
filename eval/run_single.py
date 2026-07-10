"""单 Agent RAG 评估 CLI。

流程：
1. 加载人工测试集（user_input + reference + 可选 reference_contexts + 可选 category）
2. 非侵入式 trace：跑 chat_agent.invoke 提炼 retrieved_contexts + response
3. 按 category 分组（content / metadata）分别用对应指标集做 ragas.evaluate
4. 合并结果输出 CSV + Markdown 报告

用法示例：
    python -m eval.run_single                         # 默认沙盒测试集 sandbox_pointcloud.json
    python -m eval.run_single --dataset path/to.json
    python -m eval.run_single --metrics extended      # 含 answer_correctness
    python -m eval.run_single --limit 1               # 只跑首条，用于验证
    python -m eval.run_single --traces-file traces.json
                                                       # 跳过 trace 收集，直接评估
    python -m eval.run_single --user-id sandbox_user

依赖：后端服务需已启动并连通 ES（trace 阶段会真实调用知识库检索与 DashScope）。
沙盒知识库需先就绪：python -m eval.seed_sandbox
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from eval import _ragas_compat  # noqa: F401  保证 ragas 可导入
from eval.metrics import (
    DEFAULT_METRICS,
    EXTENDED_METRICS,
    METADATA_DEFAULT_METRICS,
    METADATA_EXTENDED_METRICS,
    build_evaluator_embeddings,
    build_evaluator_llm,
    default_run_config,
)
from eval.trace_collector import collect_trace

from app.utils.logger_handler import logger

DEFAULT_DATASET = Path(__file__).resolve().parent / "datasets" / "sandbox_pointcloud.json"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "reports"
DEFAULT_USER_ID = "sandbox_user"

CONTENT_CATEGORY = "content"
METADATA_CATEGORY = "metadata"


def load_dataset(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"测试集不存在: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("测试集根节点必须是 list")
    return data


def collect_traces(
    items: list[dict[str, Any]],
    user_id: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """跑 Agent 收集 trace，组装成 ragas 样本（保留 category 字段）。"""
    samples: list[dict[str, Any]] = []
    n = len(items) if limit is None else min(limit, len(items))
    for i, item in enumerate(items[:n] if limit else items):
        query = item.get("user_input", "")
        if not query:
            logger.warning(f"[eval] 第 {i + 1} 条缺少 user_input，跳过")
            continue
        t0 = time.time()
        trace = collect_trace(query, user_id=user_id)
        dt = time.time() - t0
        if trace.get("error") or not trace["response"]:
            logger.error(
                f"[eval] 第 {i + 1} 条 trace 失败或无响应: {trace.get('error', '空响应')} (耗时 {dt:.1f}s)"
            )
            continue
        sample = {
            "user_input": trace["user_input"],
            "retrieved_contexts": trace["retrieved_contexts"],
            "response": trace["response"],
            "reference": item.get("reference", ""),
        }
        if item.get("reference_contexts"):
            sample["reference_contexts"] = item["reference_contexts"]
        category = item.get("category") or CONTENT_CATEGORY
        sample["category"] = category
        samples.append(sample)
        logger.info(
            f"[eval] [{i + 1}/{n}] trace 完成 (耗时 {dt:.1f}s, "
            f"contexts={len(trace['retrieved_contexts'])}, "
            f"tools={trace['tool_calls']}, category={category})"
        )
    return samples


def load_precollected_traces(path: Path) -> list[dict[str, Any]]:
    """读取已收集的 trace 文件，直接用于评估。"""
    if not path.exists():
        raise FileNotFoundError(f"trace 文件不存在: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("trace 文件根节点必须是 list")
    return data


def _metrics_for(category: str, metrics_name: str) -> list:
    """按 category + metrics_name 选择指标集。"""
    if category == METADATA_CATEGORY:
        return METADATA_EXTENDED_METRICS if metrics_name == "extended" else METADATA_DEFAULT_METRICS
    return EXTENDED_METRICS if metrics_name == "extended" else DEFAULT_METRICS


def _run_one_group(
    samples: list[dict[str, Any]], category: str, metrics_name: str,
) -> Any:
    """对单组样本做 ragas.evaluate，返回 result。"""
    from ragas import EvaluationDataset, evaluate

    dataset = EvaluationDataset.from_list(samples)
    metrics = _metrics_for(category, metrics_name)
    llm = build_evaluator_llm()
    embeddings = build_evaluator_embeddings()
    run_config = default_run_config()
    logger.info(
        f"[eval] ragas.evaluate [{category}] {len(samples)} 条, "
        f"指标={[type(m).__name__ for m in metrics]}"
    )
    result = evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=llm,
        embeddings=embeddings,
        run_config=run_config,
        show_progress=True,
        raise_exceptions=False,
    )
    return result


def run_evaluation(samples: list[dict[str, Any]], metrics_name: str) -> dict[str, Any]:
    """按 category 分组评估，返回 {category: ragas_result}。"""
    groups: dict[str, list[dict[str, Any]]] = {}
    for s in samples:
        cat = s.get("category") or CONTENT_CATEGORY
        groups.setdefault(cat, []).append(s)

    results: dict[str, Any] = {}
    for category, group in groups.items():
        if not group:
            continue
        results[category] = _run_one_group(group, category, metrics_name)
    if not results:
        raise ValueError("无可评估样本")
    return results


def _df_to_rows(df) -> list[dict[str, Any]]:
    """pandas DataFrame -> list[dict]，便于合并。"""
    return df.to_dict(orient="records")


def write_report(
    results: dict[str, Any], output_dir: Path, tag: str,
) -> tuple[Path, Path]:
    """合并各 category 结果输出 CSV + Markdown 摘要报告。"""
    import pandas as pd

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"{tag}.csv"
    md_path = output_dir / f"{tag}.md"

    frames: list[pd.DataFrame] = []
    for category, result in results.items():
        df = result.to_pandas()
        df.insert(0, "category", category)
        frames.append(df)
    merged = pd.concat(frames, ignore_index=True)
    merged.to_csv(csv_path, index=False, encoding="utf-8-sig")

    non_metric_cols = {
        "category", "user_input", "retrieved_contexts", "response",
        "reference", "reference_contexts",
    }
    numeric_cols = [c for c in merged.columns if c not in non_metric_cols]

    lines = ["# RAG 评估报告\n", f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"]

    # 按 category 分组的指标均值
    for category in results.keys():
        sub = merged[merged["category"] == category]
        lines.append(f"## 指标均值（category={category}）\n")
        if numeric_cols:
            lines.append("| 指标 | 均值 |")
            lines.append("|---|---|")
            for c in numeric_cols:
                if c in sub.columns:
                    vals = sub[c].dropna()
                    mean = vals.mean() if len(vals) else float("nan")
                    lines.append(f"| {c} | {mean:.4f} |")
            lines.append("")

    # 全量明细
    lines.append("## 明细\n")
    header_cols = ["#", "category", "user_input"] + numeric_cols
    lines.append("| " + " | ".join(header_cols) + " |")
    lines.append("|---" * len(header_cols) + "|")
    for idx, row in merged.iterrows():
        q = str(row.get("user_input", ""))[:40].replace("|", "/")
        cells = [str(idx + 1), str(row.get("category", "")), q]
        for c in numeric_cols:
            v = row.get(c, "")
            try:
                cells.append(f"{float(v):.4f}")
            except (TypeError, ValueError):
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path, md_path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PaperMate 单 Agent RAG 评估 (ragas)")
    p.add_argument("--dataset", type=Path, default=DEFAULT_DATASET,
                   help=f"测试集 JSON 路径（默认 {DEFAULT_DATASET}）")
    p.add_argument("--metrics", choices=["default", "extended"], default="default",
                   help="指标集：default=faithfulness/relevancy/ctx_precision/ctx_recall；"
                        "extended 额外含 answer_correctness（metadata 类始终无 context 指标）")
    p.add_argument("--user-id", default=DEFAULT_USER_ID,
                   help=f"trace 用的用户 id（默认 {DEFAULT_USER_ID}，须已就绪沙盒知识库）")
    p.add_argument("--limit", type=int, default=None,
                   help="只跑前 N 条（验证用）")
    p.add_argument("--traces-file", type=Path, default=None,
                   help="已收集的 trace JSON；提供时跳过 trace 阶段直接评估")
    p.add_argument("--save-traces", type=Path, default=None,
                   help="将本次收集到的 trace 保存到该路径，便于下次复用")
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                   help=f"报告输出目录（默认 {DEFAULT_OUTPUT_DIR}）")
    p.add_argument("--tag", default=None,
                   help="报告文件名标签（默认时间戳）")
    p.add_argument("--skip-ready-check", action="store_true",
                   help="跳过沙盒知识库就绪检查")
    return p.parse_args()


def _check_sandbox_ready(user_id: str) -> bool:
    """轻量检查沙盒知识库就绪状态。"""
    if user_id != DEFAULT_USER_ID:
        return True  # 非 sandbox_user 不强制检查
    try:
        from eval.seed_sandbox import check_status
        status = check_status()
        if status["ready"]:
            logger.info(
                f"[eval] 沙盒知识库已就绪: {status['expected_files']} 篇, "
                f"{status['es_chunk_count']} chunks"
            )
            return True
        logger.warning(
            f"[eval] 沙盒知识库未就绪: files={len(status['files'])}/"
            f"{status['expected_files']}, es_chunk={status['es_chunk_count']}/"
            f"{status['expected_chunks']}"
        )
        print("沙盒知识库未就绪，请先运行: python -m eval.seed_sandbox")
        return False
    except Exception as e:
        logger.warning(f"[eval] 就绪检查失败（继续执行）: {e}")
        return True


def main() -> int:
    args = parse_args()
    tag = args.tag or time.strftime("eval_%Y%m%d_%H%M%S")

    if not args.skip_ready_check and not _check_sandbox_ready(args.user_id):
        return 1

    if args.traces_file:
        samples = load_precollected_traces(args.traces_file)
        logger.info(f"[eval] 已加载预收集 trace {len(samples)} 条: {args.traces_file}")
    else:
        items = load_dataset(args.dataset)
        logger.info(f"[eval] 加载测试集 {len(items)} 条: {args.dataset}")
        samples = collect_traces(items, user_id=args.user_id, limit=args.limit)
        logger.info(f"[eval] trace 收集完成，有效样本 {len(samples)} 条")
        if args.save_traces:
            args.save_traces.parent.mkdir(parents=True, exist_ok=True)
            args.save_traces.write_text(
                json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info(f"[eval] trace 已保存: {args.save_traces}")

    if not samples:
        logger.error("[eval] 无有效样本，终止")
        return 1

    results = run_evaluation(samples, args.metrics)
    csv_path, md_path = write_report(results, args.output_dir, tag)
    logger.info(f"[eval] 评估完成: CSV={csv_path} MD={md_path}")
    print(f"\n评估完成。\n  CSV : {csv_path}\n  MD  : {md_path}")
    for category, result in results.items():
        try:
            tokens = result.total_tokens()
        except Exception:
            tokens = "n/a"
        try:
            cost = result.total_cost()
        except Exception:
            cost = "n/a"
        print(f"  [{category}] Tokens: {tokens}  Cost: {cost}")
    return 0


if __name__ == "__main__":
    # ragas.evaluate 内部使用 asyncio；脚本顶层无事件循环，默认 sync 调用即可。
    sys.exit(main())
