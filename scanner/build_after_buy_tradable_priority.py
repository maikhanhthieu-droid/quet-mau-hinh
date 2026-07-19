"""Build the After-the-Buy Vietnam BUY-priority queue.

The queue answers a narrow question: among Edition 1 chapters that are allowed
to receive a Vietnam BUY-first After-the-Buy layer, which ones should be worked
on first based on existing tradable evidence?
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

from scanner.after_buy_source_grounding import (  # noqa: E402
    DEFAULT_OUT_DIR as DEFAULT_AFTER_BUY_OUT_DIR,
    build_after_buy_source_map,
)


PRIORITY_ID = "after_buy_vietnam_tradable_priority_v1"
DEFAULT_SOURCE_MAP = DEFAULT_AFTER_BUY_OUT_DIR / "after_buy_source_map.json"
DEFAULT_GOVERNANCE = Path("artifacts/final_chapters/governance/chapter_governance_matrix.json")
DEFAULT_OUT_DIR = DEFAULT_AFTER_BUY_OUT_DIR


def _read_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _governance_by_pattern(path: Path) -> dict[str, Mapping[str, Any]]:
    data = _read_json(path)
    chapters = data.get("chapters") if isinstance(data.get("chapters"), list) else []
    return {str(row.get("pattern_id")): row for row in chapters if isinstance(row, Mapping) and row.get("pattern_id")}


def _score_gap(score: Any) -> float:
    try:
        return max(0.0, 95.0 - float(score))
    except (TypeError, ValueError):
        return 95.0


def _priority_bucket(role: str, score: float | None, blockers: str) -> str:
    if score is not None and score >= 95 and not blockers:
        return "already_tradable_final_or_benchmark"
    if role == "buy_core":
        return "buy_core_needs_after_buy_lift"
    if role == "buy_watchlist":
        return "buy_watchlist_needs_after_buy_lift"
    return "not_buy_priority"


def build_after_buy_tradable_priority(
    *,
    source_map_path: Path = DEFAULT_SOURCE_MAP,
    governance_path: Path = DEFAULT_GOVERNANCE,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    if not source_map_path.exists():
        source_map = build_after_buy_source_map(out_dir=source_map_path.parent)
    else:
        source_map = _read_json(source_map_path)
    governance = _governance_by_pattern(governance_path)

    rows: list[dict[str, Any]] = []
    for chapter in source_map.get("chapters") or []:
        for pattern_role in chapter.get("edition1_pattern_buy_roles") or []:
            if not pattern_role.get("buy_layer_allowed"):
                continue
            pattern_id = str(pattern_role.get("pattern_id"))
            gov = governance.get(pattern_id, {})
            raw_score = gov.get("tradable_score")
            score = None
            if raw_score is not None:
                try:
                    score = float(raw_score)
                except (TypeError, ValueError):
                    score = None
            blockers = str(gov.get("tradable_blockers") or "")
            role = str(pattern_role.get("local_role") or chapter.get("local_role"))
            score_gap = _score_gap(score)
            branch_bonus = 8.0 if pattern_role.get("buy_scope") == "up_breakout_branch_only" else 0.0
            priority_score = score_gap + (10.0 if role == "buy_core" else 4.0) + branch_bonus
            rows.append(
                {
                    "pattern_id": pattern_id,
                    "source_chapter_no": chapter.get("source_chapter_no"),
                    "source_title": chapter.get("source_title"),
                    "local_role": role,
                    "buy_scope": pattern_role.get("buy_scope"),
                    "priority_bucket": _priority_bucket(role, score, blockers),
                    "priority_score": round(priority_score, 2),
                    "tradable_score": score,
                    "tradable_status": gov.get("tradable_status"),
                    "tradable_blockers": blockers,
                    "next_after_buy_action": _next_action(role, pattern_role, gov),
                }
            )

    rows.sort(key=lambda row: (-float(row["priority_score"]), str(row["pattern_id"])))
    result = {
        "priority_id": PRIORITY_ID,
        "source_grounding_id": source_map.get("source_grounding_id"),
        "governance_path": str(governance_path),
        "row_count": len(rows),
        "rows": rows,
        "top_priority_pattern_ids": [row["pattern_id"] for row in rows[:10]],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "after_buy_tradable_priority.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_csv(out_dir / "after_buy_tradable_priority.csv", rows)
    _write_markdown(out_dir / "after_buy_tradable_priority.md", result)
    return result


def _next_action(role: str, pattern_role: Mapping[str, Any], gov: Mapping[str, Any]) -> str:
    scope = str(pattern_role.get("buy_scope") or "")
    blockers = str(gov.get("tradable_blockers") or "")
    if scope == "up_breakout_branch_only":
        return "Extract After-the-Buy entry/stop logic, then test only the up-breakout branch; do not use aggregate downside rows."
    if "walk_forward_has_negative_fold" in blockers:
        return "Use After-the-Buy configuration/throwback/stop rules to repair fold stability before chasing score."
    if "validation_trade_count" in blockers or "sample" in blockers:
        return "Prefer family-level or setup-subtype testing; do not over-tighten sample to force a score."
    if role == "buy_core":
        return "Build BUY setup rules: entry trigger, stop location, target band, time exit, and busted-pattern handling."
    return "Build watchlist rules first; promote to BUY only if validation and fold stability improve."


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = [
        "pattern_id",
        "source_chapter_no",
        "source_title",
        "local_role",
        "buy_scope",
        "priority_bucket",
        "priority_score",
        "tradable_score",
        "tradable_status",
        "tradable_blockers",
        "next_after_buy_action",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def _write_markdown(path: Path, result: Mapping[str, Any]) -> None:
    lines = [
        "# After-the-Buy Vietnam Tradable Priority",
        "",
        f"- Priority ID: `{result['priority_id']}`",
        f"- Source grounding: `{result.get('source_grounding_id')}`",
        f"- BUY eligible Edition 1 rows: `{result['row_count']}`",
        "",
        "| Rank | Pattern | Source | Role | Score | Priority | Next action |",
        "|---:|---|---|---|---:|---:|---|",
    ]
    for idx, row in enumerate(result.get("rows") or [], 1):
        score = "" if row.get("tradable_score") is None else f"{float(row['tradable_score']):.2f}"
        lines.append(
            f"| {idx} | `{row['pattern_id']}` | {row['source_title']} | `{row['local_role']}` | {score} | {row['priority_score']} | {row['next_after_buy_action']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the After-the-Buy Vietnam tradable priority queue.")
    parser.add_argument("--source-map", type=Path, default=DEFAULT_SOURCE_MAP)
    parser.add_argument("--governance", type=Path, default=DEFAULT_GOVERNANCE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    result = build_after_buy_tradable_priority(source_map_path=args.source_map, governance_path=args.governance, out_dir=args.out_dir)
    print(json.dumps({"status": "PASS", "row_count": result["row_count"], "top_priority_pattern_ids": result["top_priority_pattern_ids"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
