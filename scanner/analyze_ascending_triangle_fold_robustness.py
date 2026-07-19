"""Explain Ascending Triangle walk-forward fold instability."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import fields
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.run_chapter_tradable_layer import (  # noqa: E402
    CHAPTER_SPECS,
    GenericExecutionConfig,
    evaluate_strategy,
    load_chapter_events_and_path,
    run_walk_forward,
)


PATTERN_ID = "triangles_ascending"
SOURCE_AUDIT = Path("artifacts/scanner_v2/ascending_triangle_tradable_blocker_audit/ascending_triangle_tradable_blocker_audit.json")
OUT_DIR = Path("artifacts/scanner_v2/ascending_triangle_fold_robustness")
AUDIT_ID = "ascending_triangle_fold_robustness_v1"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows([{key: row.get(key) for key in fieldnames} for row in rows])


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _config_from_row(row: Mapping[str, Any]) -> GenericExecutionConfig:
    raw = row.get("selected_config") if isinstance(row.get("selected_config"), Mapping) else {}
    allowed = {field.name for field in fields(GenericExecutionConfig)}
    return GenericExecutionConfig(**{key: value for key, value in raw.items() if key in allowed})


def _mode(series: pd.Series) -> str | None:
    clean = series.dropna().astype(str)
    if clean.empty:
        return None
    return str(clean.mode().iloc[0])


def _fold_trade_rows(trades: pd.DataFrame, folds: pd.DataFrame) -> list[dict[str, Any]]:
    if trades.empty or folds.empty:
        return []
    work = trades.copy()
    work["breakout_date"] = pd.to_datetime(work["breakout_date"], errors="coerce")
    rows: list[dict[str, Any]] = []
    for _, fold in folds.iterrows():
        start = pd.to_datetime(fold.get("test_start"), errors="coerce")
        end = pd.to_datetime(fold.get("test_end"), errors="coerce")
        sub = work[(work["breakout_date"] >= start) & (work["breakout_date"] <= end)].copy()
        returns = pd.to_numeric(sub.get("net_return_pct"), errors="coerce")
        rows.append(
            {
                "fold_id": fold.get("fold_id"),
                "test_start": fold.get("test_start"),
                "test_end": fold.get("test_end"),
                "fold_return_pct": fold.get("test_total_return_pct"),
                "fold_drawdown_pct": fold.get("test_max_drawdown_pct"),
                "trades": int(len(sub)),
                "median_trade_return_pct": round(float(returns.median()), 2) if not returns.dropna().empty else None,
                "stop_exit_rate_pct": round(float((sub.get("exit_reason", pd.Series(dtype=object)).astype(str) == "stop_loss").mean()) * 100.0, 2) if not sub.empty else None,
                "target_exit_rate_pct": round(float((sub.get("exit_reason", pd.Series(dtype=object)).astype(str) == "target").mean()) * 100.0, 2) if not sub.empty else None,
                "dominant_regime": _mode(sub.get("market_regime", pd.Series(dtype=object))),
                "dominant_liquidity": _mode(sub.get("liquidity_bucket", pd.Series(dtype=object))),
                "median_setup_score": round(float(pd.to_numeric(sub.get("setup_score"), errors="coerce").median()), 2) if not sub.empty else None,
                "median_confirmation_score": round(float(pd.to_numeric(sub.get("confirmation_score"), errors="coerce").median()), 2) if not sub.empty else None,
            }
        )
    return rows


def run_audit(*, out_dir: Path = OUT_DIR) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    source = _read_json(SOURCE_AUDIT)
    best = (source.get("rows") or [{}])[0]
    config = _config_from_row(best)
    events, path, source_scope = load_chapter_events_and_path(CHAPTER_SPECS[PATTERN_ID])
    summary, trades, _ = evaluate_strategy(events, path, config)
    _, _, fixed_folds, fixed_summary = run_walk_forward(events, path, [config], config)
    fold_rows = _fold_trade_rows(trades, fixed_folds)
    frame = pd.DataFrame(fold_rows)
    negative = frame[pd.to_numeric(frame.get("fold_return_pct"), errors="coerce") < 0].copy() if not frame.empty else pd.DataFrame()
    positive = frame[pd.to_numeric(frame.get("fold_return_pct"), errors="coerce") >= 0].copy() if not frame.empty else pd.DataFrame()
    diagnostics = {
        "negative_fold_count": int(len(negative)),
        "negative_fold_ids": [int(value) for value in negative.get("fold_id", pd.Series(dtype=int)).tolist()],
        "negative_mean_stop_exit_rate_pct": round(float(negative["stop_exit_rate_pct"].mean()), 2) if not negative.empty else None,
        "positive_mean_stop_exit_rate_pct": round(float(positive["stop_exit_rate_pct"].mean()), 2) if not positive.empty else None,
        "negative_median_trade_return_pct": round(float(negative["median_trade_return_pct"].median()), 2) if not negative.empty else None,
        "positive_median_trade_return_pct": round(float(positive["median_trade_return_pct"].median()), 2) if not positive.empty else None,
        "interpretation": "negative folds are execution/path instability rather than missing setup-score filter" if not negative.empty else "no negative fold",
    }
    payload = {
        "audit_id": AUDIT_ID,
        "pattern_id": PATTERN_ID,
        "selected_strategy_id": config.strategy_id,
        "source_scope": source_scope,
        "summary": summary,
        "fixed_walk_forward_summary": fixed_summary,
        "diagnostics": diagnostics,
        "fold_rows": fold_rows,
        "decision": "KEEP_PUBLICATION_REFERENCE_DO_NOT_PROMOTE_TRADABLE" if diagnostics["negative_fold_count"] else "ELIGIBLE_FOR_FURTHER_TRADABLE_REVIEW",
    }
    paths = {
        "json": out_dir / "ascending_triangle_fold_robustness.json",
        "csv": out_dir / "ascending_triangle_fold_rows.csv",
        "md": out_dir / "ascending_triangle_fold_robustness.md",
    }
    _write_json(paths["json"], payload)
    _write_csv(paths["csv"], fold_rows)
    lines = [
        "# Ascending Triangle Fold Robustness",
        "",
        f"Audit: `{AUDIT_ID}`",
        "",
        f"- Strategy: `{config.strategy_id}`",
        f"- Decision: `{payload['decision']}`",
        f"- Negative folds: `{diagnostics['negative_fold_count']}`",
        f"- Negative fold IDs: `{diagnostics['negative_fold_ids']}`",
        f"- Negative mean stop-exit rate: `{diagnostics['negative_mean_stop_exit_rate_pct']}`",
        f"- Positive mean stop-exit rate: `{diagnostics['positive_mean_stop_exit_rate_pct']}`",
        "",
    ]
    paths["md"].write_text("\n".join(lines), encoding="utf-8")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Ascending Triangle fold robustness audit.")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    args = parser.parse_args()
    for key, path in run_audit(out_dir=Path(args.out_dir)).items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
