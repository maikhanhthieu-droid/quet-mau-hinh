"""Lock Falling Wedge current-data decision as watchlist/reference."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


PATTERN_ID = "wedges_falling"
GOVERNANCE_PATH = Path("artifacts/final_chapters/governance/chapter_governance_matrix.json")
LOCAL_AUDIT = Path("artifacts/scanner_v2/falling_wedge_tradable_blocker_audit/falling_wedge_tradable_blocker_audit.json")
OUT_DIR = Path("artifacts/scanner_v2/falling_wedge_watchlist_lock")
LOCK_ID = "falling_wedge_watchlist_lock_v1"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _governance_row() -> dict[str, Any]:
    governance = _read_json(GOVERNANCE_PATH)
    for row in governance.get("chapters") or []:
        if row.get("pattern_id") == PATTERN_ID:
            return dict(row)
    return {}


def run_lock(*, out_dir: Path = OUT_DIR) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    row = _governance_row()
    audit = _read_json(LOCAL_AUDIT)
    local_best = (audit.get("rows") or [{}])[0]
    payload = {
        "lock_id": LOCK_ID,
        "pattern_id": PATTERN_ID,
        "decision": "LOCK_AS_WATCHLIST_REFERENCE_UNDER_CURRENT_DATA",
        "reason": "current local and priority branches still carry walk-forward and/or liquidity blockers; promotion would require over-lift or new data/entry model",
        "governance_score": row.get("tradable_score"),
        "governance_evidence_id": row.get("tradable_evidence_id"),
        "governance_blockers": row.get("tradable_blockers"),
        "local_best_score": audit.get("best_score"),
        "local_best_strategy_id": audit.get("best_strategy_id"),
        "local_best_blockers": local_best.get("promotion_blockers"),
        "local_best_walk_forward_positive_fold_rate_pct": local_best.get("walk_forward_positive_fold_rate_pct"),
        "local_best_walk_forward_sum_return_pct": local_best.get("walk_forward_sum_return_pct"),
        "local_best_holdout_total_return_pct": local_best.get("holdout_total_return_pct"),
        "required_to_reopen": [
            "cleaner liquidity/status data that reduces participation and stale-print uncertainty",
            "or a source-safe entry model that removes negative folds without selecting on holdout",
        ],
    }
    paths = {
        "json": out_dir / "falling_wedge_watchlist_lock.json",
        "md": out_dir / "falling_wedge_watchlist_lock.md",
    }
    _write_json(paths["json"], payload)
    lines = [
        "# Falling Wedge Watchlist Lock",
        "",
        f"Lock: `{LOCK_ID}`",
        "",
        f"- Decision: `{payload['decision']}`",
        f"- Governance score: `{payload.get('governance_score')}`",
        f"- Local best score: `{payload.get('local_best_score')}`",
        f"- Local best blockers: `{payload.get('local_best_blockers')}`",
        f"- Reopen only if: `{'; '.join(payload['required_to_reopen'])}`",
        "",
    ]
    paths["md"].write_text("\n".join(lines), encoding="utf-8")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Lock Falling Wedge current-data watchlist decision.")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    args = parser.parse_args()
    for key, path in run_lock(out_dir=Path(args.out_dir)).items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
