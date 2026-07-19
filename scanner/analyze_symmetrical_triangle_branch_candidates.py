"""Analyze branch candidates for Symmetrical Triangle.

Symmetrical Triangle is direction-agnostic at setup time, so this analysis
does not allow an aggregate headline by default. It scores direction,
direction x liquidity, and direction x regime branches on public-grade events.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.run_triangle_publication_quality_audit import _metrics  # noqa: E402


DEFAULT_EVENTS = Path("artifacts/scanner_v2/symmetrical_triangles_db_source_parity/db_active/events.csv")
DEFAULT_PATH = Path("artifacts/scanner_v2/symmetrical_triangles_db_source_parity/db_active/post_breakout_path.csv")
DEFAULT_AUDIT = Path("artifacts/scanner_v2/symmetrical_triangle_publication_quality_audit/triangle_publication_quality_audit.json")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/symmetrical_triangle_branch_candidates")


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _as_float(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value: Any) -> int:
    try:
        if value is None:
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    return series.astype(str).str.lower().isin({"true", "1", "yes", "y"})


def _classify(row: Mapping[str, Any]) -> str:
    n = _as_int(row.get("n"))
    hit = _as_float(row.get("target_hit_rate_pct"))
    first = _as_float(row.get("target_first_before_adverse_5pct_rate_pct"))
    failure = _as_float(row.get("failure_5pct_rate_pct"))
    ratio = _as_float(row.get("mfe_mae_median_ratio"))
    direction = str(row.get("breakout_direction") or "")
    if direction == "up" and n >= 250 and hit >= 62.0 and first >= 30.0 and failure <= 16.0 and ratio >= 1.10:
        return "headline_watchlist_reference_candidate"
    if n >= 100 and hit >= 58.0 and first >= 28.0 and failure <= 20.0 and ratio >= 0.95:
        return "supporting_reference"
    if n >= 50 and hit >= 50.0 and first >= 20.0:
        return "informational_reference"
    return "appendix_or_research_only"


def _score(row: Mapping[str, Any]) -> float:
    hit = _as_float(row.get("target_hit_rate_pct"))
    first = _as_float(row.get("target_first_before_adverse_5pct_rate_pct"))
    failure = _as_float(row.get("failure_5pct_rate_pct"))
    ratio = _as_float(row.get("mfe_mae_median_ratio"))
    n_bonus = min(_as_int(row.get("n")), 600) / 600.0 * 10.0
    return round(hit * 0.24 + first * 0.38 + max(0.0, 28.0 - failure) * 0.75 + min(ratio, 2.0) * 10.0 + n_bonus, 2)


def _row(events: pd.DataFrame, path: pd.DataFrame, *, label: str, target_multiple: float = 0.5) -> Dict[str, Any]:
    out = _metrics(events.copy(), path, target_multiple=target_multiple, row_id=label)
    out["branch_label"] = label
    out["branch_score"] = _score(out)
    return out


def build_branch_candidates(
    *,
    events_path: Path = DEFAULT_EVENTS,
    path_path: Path = DEFAULT_PATH,
    audit_path: Path = DEFAULT_AUDIT,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    events = pd.read_csv(events_path)
    path = pd.read_csv(path_path)
    if "event_id" not in events.columns and "detection_id" in events.columns:
        events["event_id"] = events["detection_id"]
    for column in ("target_hit", "failure_5pct", "target_first_before_adverse_5pct"):
        if column in events.columns:
            events[column] = _bool_series(events[column])
    public = events[events.get("publication_quality_tier").isin(["premium", "standard"])].copy()
    if public.empty:
        public = events.copy()

    rows: List[Dict[str, Any]] = []
    for direction in ("up", "down"):
        subset = public[public["breakout_direction"] == direction].copy()
        if not subset.empty:
            row = _row(subset, path, label=f"direction:{direction}")
            row["breakout_direction"] = direction
            row["source"] = "direction"
            row["classification"] = _classify(row)
            rows.append(row)
        for liquidity in ("high", "mid", "low"):
            branch = subset[subset.get("liquidity_bucket") == liquidity].copy()
            if not branch.empty:
                row = _row(branch, path, label=f"direction:{direction}:liquidity:{liquidity}")
                row["breakout_direction"] = direction
                row["liquidity_bucket"] = liquidity
                row["source"] = "direction_liquidity"
                row["classification"] = _classify(row)
                rows.append(row)
        for regime in ("bull", "bear", "unknown"):
            branch = subset[subset.get("market_regime") == regime].copy()
            if not branch.empty:
                row = _row(branch, path, label=f"direction:{direction}:regime:{regime}")
                row["breakout_direction"] = direction
                row["market_regime"] = regime
                row["source"] = "direction_regime"
                row["classification"] = _classify(row)
                rows.append(row)

    rows = sorted(rows, key=lambda item: (_as_float(item.get("branch_score")), _as_int(item.get("n"))), reverse=True)
    headline = [row for row in rows if row.get("classification") == "headline_watchlist_reference_candidate"]
    payload = {
        "analysis_id": "symmetrical_triangle_branch_candidates_v1",
        "pattern_id": "triangles_symmetrical",
        "audit_id": _read_json(audit_path).get("audit_id"),
        "scope": "premium+standard publication_quality_tier",
        "recommended_headline_scope": headline[0] if headline else None,
        "all_candidates": rows,
        "decision": "USE_DIRECTION_BRANCH_HEADLINE" if headline else "KEEP_AS_RESEARCH_CANDIDATE",
        "decision_note": "Symmetrical Triangle should be read direction-first; aggregate up/down behavior is not a valid public headline.",
    }
    (out_dir / "symmetrical_triangle_branch_candidates.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    pd.DataFrame(rows).to_csv(out_dir / "symmetrical_triangle_branch_candidates.csv", index=False)
    lines = [
        "# Symmetrical Triangle branch candidates",
        "",
        f"**Decision:** {payload['decision']}",
        "",
        "| Branch | N | Hit 0.5x | Target-first | Failure | MFE/MAE | Classification |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows[:14]:
        lines.append(
            f"| {row.get('branch_label')} | {row.get('n')} | {row.get('target_hit_rate_pct')} | "
            f"{row.get('target_first_before_adverse_5pct_rate_pct')} | {row.get('failure_5pct_rate_pct')} | "
            f"{row.get('mfe_mae_median_ratio')} | {row.get('classification')} |"
        )
    (out_dir / "symmetrical_triangle_branch_candidates.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze Symmetrical Triangle branch candidates.")
    parser.add_argument("--events", default=str(DEFAULT_EVENTS))
    parser.add_argument("--path", default=str(DEFAULT_PATH))
    parser.add_argument("--audit", default=str(DEFAULT_AUDIT))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    payload = build_branch_candidates(events_path=Path(args.events), path_path=Path(args.path), audit_path=Path(args.audit), out_dir=Path(args.out_dir))
    print(json.dumps({"decision": payload["decision"], "headline": payload["recommended_headline_scope"]}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
