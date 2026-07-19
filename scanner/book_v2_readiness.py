from __future__ import annotations

from typing import Any, Dict, List, Tuple


def chapter_readiness(
    *,
    valid_metrics: Dict[str, Any],
    calib_metrics: Dict[str, Any],
    phase3_row: Dict[str, Any],
    benchmark_row: Dict[str, Any],
) -> Tuple[str, List[str]]:
    valid_evals = int(valid_metrics.get("evals") or 0)
    calib_evals = int(calib_metrics.get("evals") or 0)
    total_evals = valid_evals + calib_evals
    phase3 = str(phase3_row.get("phase3_status") or "")
    strategy = str(phase3_row.get("strategy_gate") or "")
    benchmark = str(benchmark_row.get("benchmark_status") or "")

    flags: List[str] = []
    if valid_evals == 0:
        flags.append("no_valid_evals")
    elif valid_evals < 20:
        flags.append("thin_valid_evals")
    if calib_evals == 0:
        flags.append("no_calib_evals")
    elif calib_evals < 20:
        flags.append("thin_calib_evals")
    if benchmark == "sparse":
        flags.append("sparse_benchmark")
    if benchmark == "materially_weaker":
        flags.append("materially_weaker_than_reference")
    if phase3 == "recalibrate":
        flags.append("needs_recalibration")
    if phase3 == "retire_from_strategy" or strategy == "retired":
        flags.append("reference_only_governance")

    if strategy in {"candidate", "watchlist"}:
        return "strategy_appendix", flags
    if phase3 == "retire_from_strategy" or strategy == "retired":
        return "reference_only", flags
    if valid_evals >= 20 and calib_evals >= 20:
        return "core_research_chapter", flags
    if total_evals >= 5:
        return "thin_research_chapter", flags
    return "reference_only", flags
