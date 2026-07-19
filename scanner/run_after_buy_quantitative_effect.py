"""Run a source-guided quantitative effect check for After-the-Buy V2.

The application layer proves that rules are mapped into scanner/stat/trade
layers.  This pass answers the next question: does rerunning the executable
branch layer with the current source-guided infrastructure improve any priority
chapter, and if not, what remains blocked?

The script writes into a separate V2 directory and never overwrites canonical
chapter scorecards.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.build_after_buy_application_layer import PRIORITY_PATTERNS  # noqa: E402
from scanner.run_chapter_branch_optimization import run_all_branch_optimizations  # noqa: E402


EFFECT_ID = "after_buy_quantitative_effect_v1"
DEFAULT_AFTER_BUY_V2_DIR = Path("artifacts/scanner_v2/after_buy_vietnam_v2")
DEFAULT_OUT_DIR = DEFAULT_AFTER_BUY_V2_DIR / "quantitative_effect"
DEFAULT_GOVERNANCE_MATRIX = Path("artifacts/final_chapters/governance/chapter_governance_matrix.json")


def _read_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_json(path: Path, payload: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _governance_by_pattern(path: Path = DEFAULT_GOVERNANCE_MATRIX) -> dict[str, Mapping[str, Any]]:
    data = _read_json(path)
    rows = data.get("chapters") if isinstance(data.get("chapters"), list) else []
    return {str(row.get("pattern_id")): row for row in rows if isinstance(row, Mapping) and row.get("pattern_id")}


def _branch_rows(summary_path: Path) -> dict[str, Mapping[str, Any]]:
    data = _read_json(summary_path)
    rows = data.get("rows") if isinstance(data.get("rows"), list) else []
    return {str(row.get("pattern_id")): row for row in rows if isinstance(row, Mapping) and row.get("pattern_id")}


def _effect_decision(before_score: float | None, after_score: float | None, after_release: str | None, after_blockers: str) -> str:
    if after_score is None:
        return "not_measured"
    if after_release == "PASS" and after_score >= 95.0:
        return "promoted_to_tradable_final"
    if before_score is not None and after_score > before_score + 1.0 and "walk_forward_has_negative_fold" not in after_blockers:
        return "improved_but_not_final"
    if before_score is not None and abs(after_score - before_score) <= 1.0:
        return "unchanged_within_noise_band"
    if before_score is not None and after_score < before_score - 1.0:
        return "worse_or_more_conservative"
    return "blocked_after_rerun"


def build_after_buy_quantitative_effect(
    *,
    after_buy_v2_dir: Path = DEFAULT_AFTER_BUY_V2_DIR,
    out_dir: Path = DEFAULT_OUT_DIR,
    governance_path: Path = DEFAULT_GOVERNANCE_MATRIX,
    patterns: Sequence[str] = PRIORITY_PATTERNS,
    reuse_existing: bool = False,
) -> dict[str, Any]:
    branch_dir = out_dir / "branch_rerun"
    run_all_branch_optimizations(out_dir=branch_dir, chapters=set(patterns), reuse_existing=reuse_existing)
    rerun_rows = _branch_rows(branch_dir / "all_chapters_branch_optimization_summary.json")
    governance = _governance_by_pattern(governance_path)
    app_config = _read_json(after_buy_v2_dir / "after_buy_scanner_stat_trade_config.json")
    config_rows = {
        str(row.get("pattern_id")): row
        for row in app_config.get("patterns", [])
        if isinstance(row, Mapping) and row.get("pattern_id")
    }

    comparison: list[dict[str, Any]] = []
    for pattern_id in patterns:
        before = governance.get(pattern_id, {})
        after = rerun_rows.get(pattern_id, {})
        config = config_rows.get(pattern_id, {})
        before_score = _float(before.get("tradable_score"))
        after_score = _float(after.get("score"))
        after_blockers = ",".join(after.get("promotion_blockers") or after.get("failures") or [])
        before_blockers = str(before.get("tradable_blockers") or "")
        delta = None if before_score is None or after_score is None else round(after_score - before_score, 2)
        comparison.append(
            {
                "pattern_id": pattern_id,
                "before_score": before_score,
                "after_score": after_score,
                "score_delta": delta,
                "before_release_status": before.get("tradable_release_status"),
                "after_release_status": after.get("release_status"),
                "before_blockers": before_blockers,
                "after_blockers": after_blockers,
                "trade_layer_mode": config.get("trade_layer_mode"),
                "after_buy_no_overfit_blocked": bool((config.get("no_overfit_gate") or {}).get("currently_blocked")),
                "branch_count": after.get("branch_count"),
                "selected_strategy_id": after.get("selected_strategy_id"),
                "fixed_positive_fold_rate_pct": (after.get("fixed_walk_forward_summary") or {}).get("positive_fold_rate_pct")
                if isinstance(after.get("fixed_walk_forward_summary"), Mapping)
                else None,
                "fixed_worst_fold_return_pct": (after.get("fixed_walk_forward_summary") or {}).get("worst_fold_return_pct")
                if isinstance(after.get("fixed_walk_forward_summary"), Mapping)
                else None,
                "decision": _effect_decision(before_score, after_score, after.get("release_status"), after_blockers),
            }
        )

    summary = {
        "effect_id": EFFECT_ID,
        "pattern_count": len(patterns),
        "promoted_count": sum(1 for row in comparison if row["decision"] == "promoted_to_tradable_final"),
        "improved_count": sum(1 for row in comparison if row["decision"] == "improved_but_not_final"),
        "unchanged_count": sum(1 for row in comparison if row["decision"] == "unchanged_within_noise_band"),
        "blocked_after_rerun_count": sum(1 for row in comparison if row["decision"] == "blocked_after_rerun"),
        "worse_or_conservative_count": sum(1 for row in comparison if row["decision"] == "worse_or_more_conservative"),
        "blocked_count": sum(1 for row in comparison if row["after_release_status"] != "PASS"),
    }
    report = {
        "effect_id": EFFECT_ID,
        "status": "PASS",
        "branch_rerun_dir": str(branch_dir),
        "summary": summary,
        "rows": comparison,
        "interpretation": (
            "This is a real branch-rerun comparison. Score increases are accepted only when release/no-overfit gates also improve; "
            "otherwise the result is a governance/statistical clarity improvement, not a tradable-performance improvement."
        ),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "after_buy_quantitative_effect_report.json", report)
    _write_csv(out_dir / "after_buy_quantitative_effect_comparison.csv", comparison)
    _write_markdown(out_dir / "after_buy_quantitative_effect_report.md", report)
    return report


def _write_markdown(path: Path, report: Mapping[str, Any]) -> None:
    lines = [
        "# After-the-Buy Quantitative Effect Report",
        "",
        f"- Effect ID: `{report['effect_id']}`",
        f"- Branch rerun dir: `{report['branch_rerun_dir']}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for key, value in report["summary"].items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(
        [
            "",
            "## Before / After by Pattern",
            "",
            "| Pattern | Before | After | Delta | Release | Decision | Blockers |",
            "|---|---:|---:|---:|---|---|---|",
        ]
    )
    for row in report.get("rows", []):
        before = "" if row.get("before_score") is None else f"{float(row['before_score']):.2f}"
        after = "" if row.get("after_score") is None else f"{float(row['after_score']):.2f}"
        delta = "" if row.get("score_delta") is None else f"{float(row['score_delta']):.2f}"
        lines.append(
            f"| `{row.get('pattern_id')}` | {before} | {after} | {delta} | {row.get('after_release_status')} | "
            f"{row.get('decision')} | {row.get('after_blockers')} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run After-the-Buy quantitative effect checks.")
    parser.add_argument("--after-buy-v2-dir", type=Path, default=DEFAULT_AFTER_BUY_V2_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--governance", type=Path, default=DEFAULT_GOVERNANCE_MATRIX)
    parser.add_argument("--patterns", default="")
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args(argv)
    patterns = tuple(item.strip() for item in str(args.patterns).split(",") if item.strip()) or PRIORITY_PATTERNS
    result = build_after_buy_quantitative_effect(
        after_buy_v2_dir=args.after_buy_v2_dir,
        out_dir=args.out_dir,
        governance_path=args.governance,
        patterns=patterns,
        reuse_existing=bool(args.reuse_existing),
    )
    print(json.dumps({"status": result["status"], "summary": result["summary"], "out_dir": str(args.out_dir)}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
