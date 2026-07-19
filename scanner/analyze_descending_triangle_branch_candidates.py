"""Select candidate interpretation branches for Descending Triangle.

This script deliberately does not change detector geometry. It reads the
Triangle publication audit and classifies which scope is strong enough to be a
headline branch under the current available-series data limits.
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


DEFAULT_AUDIT_DIR = Path("artifacts/scanner_v2/descending_triangle_publication_quality_audit")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/descending_triangle_branch_candidates")


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
    return str(row.get("row_id") or row.get("scope") or "unknown")


def _classify(row: Mapping[str, Any]) -> str:
    n = _as_int(row.get("n"))
    hit = _as_float(row.get("target_hit_rate_pct"))
    first = _as_float(row.get("target_first_before_adverse_5pct_rate_pct"))
    failure = _as_float(row.get("failure_5pct_rate_pct"))
    ratio = _as_float(row.get("mfe_mae_median_ratio"))
    if n >= 100 and hit >= 78.0 and first >= 48.0 and failure <= 15.0 and ratio >= 1.15:
        return "headline_defensive_reference_candidate"
    if n >= 100 and hit >= 68.0 and first >= 35.0 and failure <= 22.0 and ratio >= 0.85:
        return "supporting_defensive_reference"
    if n >= 30 and hit >= 60.0 and first >= 30.0 and failure <= 25.0:
        return "informational_reference"
    return "appendix_or_exclude_from_headline"


def _score(row: Mapping[str, Any]) -> float:
    hit = _as_float(row.get("target_hit_rate_pct"))
    first = _as_float(row.get("target_first_before_adverse_5pct_rate_pct"))
    failure = _as_float(row.get("failure_5pct_rate_pct"))
    ratio = _as_float(row.get("mfe_mae_median_ratio"))
    n = min(_as_int(row.get("n")), 500) / 500.0 * 10.0
    return round(hit * 0.25 + first * 0.35 + max(0.0, 30.0 - failure) * 0.8 + min(ratio, 2.0) * 10.0 + n, 2)


def build_branch_candidates(*, audit_dir: Path = DEFAULT_AUDIT_DIR, out_dir: Path = DEFAULT_OUT_DIR) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    audit = _read_json(audit_dir / "triangle_publication_quality_audit.json")
    subgroup_path = audit_dir / "public_grade_subgroup_robustness.csv"
    interaction_path = audit_dir / "regime_liquidity_interaction.csv"
    target_path = audit_dir / "target_family_by_publication_tier.csv"

    rows: List[Dict[str, Any]] = []
    for source, path in (("subgroup", subgroup_path), ("interaction", interaction_path), ("target_tier", target_path)):
        if not path.exists():
            continue
        frame = pd.read_csv(path)
        if source == "target_tier":
            frame = frame[(frame.get("tier") == "premium+standard") & (pd.to_numeric(frame.get("target_multiple"), errors="coerce") == 0.5)].copy()
        for _, raw_row in frame.iterrows():
            row = raw_row.to_dict()
            row["source"] = source
            row["branch_label"] = _branch_label(row)
            row["branch_score"] = _score(row)
            row["classification"] = _classify(row)
            rows.append(row)

    rows = sorted(rows, key=lambda item: (_as_float(item.get("branch_score")), _as_int(item.get("n"))), reverse=True)
    headline = [row for row in rows if row["classification"] == "headline_defensive_reference_candidate"]
    supporting = [row for row in rows if row["classification"] == "supporting_defensive_reference"]
    payload = {
        "analysis_id": "descending_triangle_branch_candidates_v1",
        "pattern_id": "triangles_descending",
        "audit_id": audit.get("audit_id"),
        "premium_visual_validation_summary": audit.get("premium_visual_validation_summary"),
        "recommended_headline_scope": headline[0] if headline else None,
        "recommended_supporting_scopes": supporting[:5],
        "all_candidates": rows,
        "decision": (
            "USE_BRANCH_HEADLINE"
            if headline
            else "KEEP_AS_INFORMATIONAL_UNTIL_STRONGER_BRANCH_OR_DATA"
        ),
        "decision_note": "Descending Triangle should not use aggregate statistics as the public headline; branch by liquidity/regime first.",
    }
    (out_dir / "descending_triangle_branch_candidates.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    pd.DataFrame(rows).to_csv(out_dir / "descending_triangle_branch_candidates.csv", index=False)
    lines = [
        "# Descending Triangle branch candidates",
        "",
        f"**Decision:** {payload['decision']}",
        "",
        "| Branch | N | Hit 0.5x | Target-first | Failure | MFE/MAE | Classification |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows[:12]:
        lines.append(
            f"| {row.get('branch_label')} | {row.get('n')} | {row.get('target_hit_rate_pct')} | "
            f"{row.get('target_first_before_adverse_5pct_rate_pct')} | {row.get('failure_5pct_rate_pct')} | "
            f"{row.get('mfe_mae_median_ratio')} | {row.get('classification')} |"
        )
    (out_dir / "descending_triangle_branch_candidates.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze Descending Triangle branch candidates.")
    parser.add_argument("--audit-dir", default=str(DEFAULT_AUDIT_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    payload = build_branch_candidates(audit_dir=Path(args.audit_dir), out_dir=Path(args.out_dir))
    print(json.dumps({"decision": payload["decision"], "headline": payload["recommended_headline_scope"]}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
