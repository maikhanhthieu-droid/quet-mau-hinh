"""Audit Bear Flag sample depth and data-scope options.

This script answers a narrow release question: can we increase Bear Flag
headline sample size without losing the outcome-quality gates that made the
branch scanner useful?
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.v2.bear_flags_monograph import run_pipeline  # noqa: E402
from scanner.v2.bull_flags_monograph import DEFAULT_MARKET_STATS_JSON  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bear_flags_sample_depth_scope_audit")
QUALITY_GATES = {
    "min_headline_n": 15,
    "min_hit_rate": 65.0,
    "max_failure_rate": 20.0,
    "min_mfe_mae_ratio": 1.2,
}
PROMOTION_MIN_N_UPLIFT_PCT = 15.0

GRID_CONFIGS: dict[str, dict[str, Any]] = {
    "default": {},
    "more_events": {"max_events_per_symbol": 15, "breakout_cooldown_bars": 10},
    "wider_width": {"width_max_bars": 30, "max_events_per_symbol": 15, "breakout_cooldown_bars": 10},
    "looser_pole": {"pole_min_change_pct": 8.0, "pole_min_slope_deg": 6.0, "max_events_per_symbol": 15, "breakout_cooldown_bars": 10},
    "looser_parallel": {"parallel_tol_deg": 6.0, "max_events_per_symbol": 15, "breakout_cooldown_bars": 10},
    "height_wider": {"height_min_pct": 2.5, "height_max_pct": 18.0, "max_events_per_symbol": 15, "breakout_cooldown_bars": 10},
    "combo_light": {
        "width_max_bars": 30,
        "pole_min_change_pct": 8.0,
        "pole_min_slope_deg": 6.0,
        "parallel_tol_deg": 5.0,
        "height_min_pct": 2.5,
        "height_max_pct": 18.0,
        "max_events_per_symbol": 15,
        "breakout_cooldown_bars": 10,
    },
    "combo_wide": {
        "width_max_bars": 35,
        "pole_min_change_pct": 7.0,
        "pole_min_slope_deg": 5.0,
        "parallel_tol_deg": 7.0,
        "height_min_pct": 2.0,
        "height_max_pct": 20.0,
        "flag_to_pole_max_pct": 65.0,
        "breakout_search_bars": 15,
        "max_events_per_symbol": 20,
        "breakout_cooldown_bars": 8,
    },
}


def _read_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _quality_pass(row: Mapping[str, Any]) -> bool:
    return (
        int(row.get("headline_n") or 0) >= QUALITY_GATES["min_headline_n"]
        and _num(row.get("headline_hit_rate")) >= QUALITY_GATES["min_hit_rate"]
        and _num(row.get("headline_failure_5pct_rate"), 100.0) <= QUALITY_GATES["max_failure_rate"]
        and _num(row.get("headline_mfe_mae_ratio")) >= QUALITY_GATES["min_mfe_mae_ratio"]
    )


def _summarize_run(*, scope_id: str, config_id: str, config: Mapping[str, Any], stats_path: Path) -> dict[str, Any]:
    stats = _read_json(stats_path)
    headline = stats.get("bear_branch_headline") if isinstance(stats.get("bear_branch_headline"), Mapping) else {}
    row = {
        "scope_id": scope_id,
        "config_id": config_id,
        "config": dict(config),
        "n_all": int(stats.get("detection_count") or 0),
        "symbols_scanned": int(stats.get("symbols_scanned") or 0),
        "headline_scope": headline.get("aggregate_id") or headline.get("branch_id") or "n/a",
        "headline_n": int(headline.get("n") or 0),
        "headline_n_symbols": int(headline.get("n_symbols") or 0),
        "headline_hit_rate": headline.get("base_target_hit_rate"),
        "headline_target_first_rate": headline.get("base_target_first_before_adverse_5pct_rate"),
        "headline_failure_5pct_rate": headline.get("failure_5pct_rate"),
        "headline_mfe_mae_ratio": headline.get("mfe_mae_median_ratio"),
        "headline_mfe_pct": headline.get("median_mfe_pct"),
        "headline_mae_pct": headline.get("median_mae_pct"),
        "headline_ci_width": (
            round(_num(headline.get("base_target_hit_ci_high")) - _num(headline.get("base_target_hit_ci_low")), 2)
            if headline.get("base_target_hit_ci_high") is not None and headline.get("base_target_hit_ci_low") is not None
            else None
        ),
    }
    row["quality_gate_pass"] = _quality_pass(row)
    return row


def select_recommendation(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    current = next((dict(row) for row in rows if row.get("scope_id") == "active_current" and row.get("config_id") == "default"), None)
    eligible = [dict(row) for row in rows if row.get("quality_gate_pass")]
    best_eligible = max(
        eligible,
        key=lambda row: (int(row.get("headline_n") or 0), _num(row.get("headline_hit_rate")), -_num(row.get("headline_failure_5pct_rate"), 100.0)),
        default=None,
    )
    best_depth = max(rows, key=lambda row: int(row.get("headline_n") or 0), default={})
    current_n = int((current or {}).get("headline_n") or 0)
    best_n = int((best_eligible or {}).get("headline_n") or 0)
    uplift_pct = round((best_n - current_n) / current_n * 100.0, 2) if current_n else None
    promote = bool(best_eligible and current and best_n > current_n and (uplift_pct or 0.0) >= PROMOTION_MIN_N_UPLIFT_PCT)
    return {
        "decision": "PROMOTE_SAMPLE_DEPTH_CONFIG" if promote else "KEEP_CURRENT_HEADLINE_CONFIG",
        "current": current,
        "best_quality_preserving": best_eligible,
        "best_depth_even_if_quality_fails": dict(best_depth) if best_depth else None,
        "headline_n_uplift_pct": uplift_pct,
        "promotion_min_n_uplift_pct": PROMOTION_MIN_N_UPLIFT_PCT,
        "quality_gates": dict(QUALITY_GATES),
        "rationale": (
            "A larger configuration passed quality gates with material N uplift."
            if promote
            else "No tested scope/config materially improves headline N while preserving hit/failure/MFE-MAE gates; keep current headline and report depth limits."
        ),
    }


def run_audit(*, out_dir: Path = DEFAULT_OUT_DIR, skip_run: bool = False) -> dict[str, Any]:
    scopes: dict[str, tuple[Optional[Path], Sequence[str]]] = {
        "active_current": (DEFAULT_MARKET_STATS_JSON, tuple(GRID_CONFIGS)),
        # Scope expansion is diagnostic only, so keep it to representative
        # profiles instead of spending runtime on every tuning variant.
        "all_source_probe": (None, ("default", "height_wider", "combo_wide")),
    }
    rows: list[dict[str, Any]] = []
    for scope_id, (market_stats_json, config_ids) in scopes.items():
        for config_id in config_ids:
            config = GRID_CONFIGS[config_id]
            run_dir = out_dir / "runs" / scope_id / config_id
            if not skip_run:
                run_pipeline(out_dir=run_dir, detector_config=config, market_stats_json=market_stats_json)
            rows.append(_summarize_run(scope_id=scope_id, config_id=config_id, config=config, stats_path=run_dir / "statistics.json"))
    recommendation = select_recommendation(rows)
    return {
        "audit_version": "bear_flag_sample_depth_scope_v1",
        "rows": rows,
        "recommendation": recommendation,
        "scope_policy": {
            "active_current": "Main publication scope, matching the user's active-symbol research constraint.",
            "all_source_probe": "Diagnostic only. It can include symbols outside current active scope and must not be promoted without official status tape.",
        },
    }


def _md_table(rows: Sequence[Sequence[Any]]) -> list[str]:
    if not rows:
        return []
    out = ["| " + " | ".join(str(x) for x in rows[0]) + " |", "| " + " | ".join("---" for _ in rows[0]) + " |"]
    out.extend("| " + " | ".join(str(x) for x in row) + " |" for row in rows[1:])
    return out


def write_audit(audit: Mapping[str, Any], out_dir: Path = DEFAULT_OUT_DIR) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "bear_flag_sample_depth_scope_audit.json"
    csv_path = out_dir / "bear_flag_sample_depth_scope_grid.csv"
    md_path = out_dir / "bear_flag_sample_depth_scope_audit.md"
    json_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    pd.DataFrame(audit.get("rows") or []).to_csv(csv_path, index=False)
    rec = audit.get("recommendation") or {}
    lines = [
        "# Bear Flag sample-depth and scope audit",
        "",
        f"**Decision:** {rec.get('decision')}",
        "",
        f"**Rationale:** {rec.get('rationale')}",
        "",
        "## Grid results",
        "",
        *_md_table(
            [
                ["Scope", "Config", "All N", "Headline", "Headline N", "Hit", "Target-first", "Failure", "MFE/MAE", "Pass"],
                *[
                    [
                        row.get("scope_id"),
                        row.get("config_id"),
                        row.get("n_all"),
                        row.get("headline_scope"),
                        row.get("headline_n"),
                        f"{row.get('headline_hit_rate')}%",
                        f"{row.get('headline_target_first_rate')}%",
                        f"{row.get('headline_failure_5pct_rate')}%",
                        row.get("headline_mfe_mae_ratio"),
                        row.get("quality_gate_pass"),
                    ]
                    for row in audit.get("rows", [])
                ],
            ]
        ),
        "",
        "## Recommendation",
        "",
        f"- Current headline N: {(rec.get('current') or {}).get('headline_n')}",
        f"- Best quality-preserving N: {(rec.get('best_quality_preserving') or {}).get('headline_n')}",
        f"- Best depth even if quality fails: {(rec.get('best_depth_even_if_quality_fails') or {}).get('headline_n')}",
        f"- Headline N uplift: {rec.get('headline_n_uplift_pct')}%",
        "",
        "## Scope policy",
        "",
        "- `active_current` remains the main publication scope.",
        "- `all_source_probe` is diagnostic only unless official status tape is added.",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "md": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Bear Flag sample-depth and data-scope audit.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--skip-run", action="store_true", help="Reuse existing run directories and only rebuild summary artifacts.")
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    audit = run_audit(out_dir=out_dir, skip_run=args.skip_run)
    paths = write_audit(audit, out_dir=out_dir)
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
