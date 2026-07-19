"""Analyze branch candidates for Falling Wedge.

Falling Wedge is an upward breakout lane, but the aggregate detector is not
automatically a publication chapter. This script scores geometry tiers,
liquidity/regime branches, and temporal robustness after the scanner has
produced a publication-quality audit.
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


DEFAULT_AUDIT_DIR = Path("artifacts/scanner_v2/falling_wedge_publication_quality_audit")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/falling_wedge_branch_candidates")


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


def _branch_label(row: Mapping[str, Any]) -> str:
    if row.get("dimension"):
        return f"{row.get('dimension')}:{row.get('bucket')}"
    if row.get("market_regime") is not None and row.get("liquidity_bucket") is not None:
        return f"interaction:{row.get('market_regime')}:{row.get('liquidity_bucket')}"
    if row.get("split_type") and row.get("period"):
        return f"{row.get('split_type')}:{row.get('period')}"
    if row.get("tier"):
        return f"tier:{row.get('tier')}"
    return str(row.get("row_id") or row.get("scope") or "unknown")


def _classify(row: Mapping[str, Any], *, premium_visual_gate: str) -> str:
    n = _as_int(row.get("n"))
    hit = _as_float(row.get("target_hit_rate_pct"))
    first = _as_float(row.get("target_first_before_adverse_5pct_rate_pct"))
    failure = _as_float(row.get("failure_5pct_rate_pct"))
    ratio = _as_float(row.get("mfe_mae_median_ratio"))
    visual_ok = premium_visual_gate == "PASS"
    if visual_ok and n >= 120 and hit >= 70.0 and first >= 45.0 and failure <= 17.0 and ratio >= 1.40:
        return "headline_watchlist_reference_candidate"
    if n >= 100 and hit >= 65.0 and first >= 32.0 and failure <= 20.0 and ratio >= 1.05:
        return "supporting_watchlist_reference"
    if n >= 30 and hit >= 60.0 and first >= 25.0 and failure <= 25.0:
        return "informational_reference"
    return "appendix_or_research_only"


def _score(row: Mapping[str, Any]) -> float:
    hit = _as_float(row.get("target_hit_rate_pct"))
    first = _as_float(row.get("target_first_before_adverse_5pct_rate_pct"))
    failure = _as_float(row.get("failure_5pct_rate_pct"))
    ratio = _as_float(row.get("mfe_mae_median_ratio"))
    n_bonus = min(_as_int(row.get("n")), 500) / 500.0 * 10.0
    return round(hit * 0.23 + first * 0.40 + max(0.0, 28.0 - failure) * 0.75 + min(ratio, 2.5) * 9.0 + n_bonus, 2)


def _load_rows(path: Path, *, source: str) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    frame = pd.read_csv(path)
    if source == "target_tier":
        frame = frame[(frame.get("target_multiple") == 0.5) & (frame.get("tier").isin(["premium", "premium+standard", "all"]))].copy()
    out: List[Dict[str, Any]] = []
    for _, raw_row in frame.iterrows():
        row = raw_row.to_dict()
        row["source"] = source
        row["branch_label"] = _branch_label(row)
        row["branch_score"] = _score(row)
        out.append(row)
    return out


def build_branch_candidates(*, audit_dir: Path = DEFAULT_AUDIT_DIR, out_dir: Path = DEFAULT_OUT_DIR) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    audit = _read_json(audit_dir / "triangle_publication_quality_audit.json")
    visual = audit.get("premium_visual_validation_summary") if isinstance(audit.get("premium_visual_validation_summary"), dict) else {}
    premium_visual_gate = str(visual.get("premium_visual_gate") or "UNKNOWN")

    rows: List[Dict[str, Any]] = []
    rows.extend(_load_rows(audit_dir / "target_family_by_publication_tier.csv", source="target_tier"))
    rows.extend(_load_rows(audit_dir / "public_grade_subgroup_robustness.csv", source="subgroup"))
    rows.extend(_load_rows(audit_dir / "regime_liquidity_interaction.csv", source="interaction"))
    rows.extend(_load_rows(audit_dir / "temporal_split_robustness.csv", source="temporal"))

    for row in rows:
        row["classification"] = _classify(row, premium_visual_gate=premium_visual_gate)
    rows = sorted(rows, key=lambda item: (_as_float(item.get("branch_score")), _as_int(item.get("n"))), reverse=True)
    headline = [row for row in rows if row.get("classification") == "headline_watchlist_reference_candidate"]
    supporting = [row for row in rows if row.get("classification") == "supporting_watchlist_reference"]
    payload = {
        "analysis_id": "falling_wedge_branch_candidates_v1",
        "pattern_id": "wedges_falling",
        "audit_id": audit.get("audit_id"),
        "premium_visual_validation_summary": visual,
        "recommended_headline_scope": headline[0] if headline else None,
        "recommended_supporting_scopes": supporting[:5],
        "all_candidates": rows,
        "decision": "USE_BRANCH_HEADLINE" if headline else "KEEP_AS_WATCHLIST_OR_RESEARCH_CANDIDATE",
        "decision_note": "Falling Wedge has a visually valid premium tier, but aggregate public-grade results are only moderate; use branch-first interpretation until robustness improves.",
    }
    (out_dir / "falling_wedge_branch_candidates.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    pd.DataFrame(rows).to_csv(out_dir / "falling_wedge_branch_candidates.csv", index=False)

    lines = [
        "# Falling Wedge branch candidates",
        "",
        f"**Decision:** {payload['decision']}",
        "",
        "| Branch | N | Hit 0.5x | Target-first | Failure | MFE/MAE | Classification |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows[:16]:
        lines.append(
            f"| {row.get('branch_label')} | {row.get('n')} | {row.get('target_hit_rate_pct')} | "
            f"{row.get('target_first_before_adverse_5pct_rate_pct')} | {row.get('failure_5pct_rate_pct')} | "
            f"{row.get('mfe_mae_median_ratio')} | {row.get('classification')} |"
        )
    (out_dir / "falling_wedge_branch_candidates.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze Falling Wedge branch candidates.")
    parser.add_argument("--audit-dir", default=str(DEFAULT_AUDIT_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    payload = build_branch_candidates(audit_dir=Path(args.audit_dir), out_dir=Path(args.out_dir))
    print(json.dumps({"decision": payload["decision"], "headline": payload["recommended_headline_scope"]}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
