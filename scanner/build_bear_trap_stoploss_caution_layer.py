"""Build bear-trap stop-loss caution artifacts.

This layer deliberately replaces the abandoned bear-trap long branch.  A failed
bearish breakdown can matter, but the current evidence does not justify
promoting it into a BUY setup.  The correct product use is a stop-loss caution:
after a bearish pattern breaks down, watch whether price quickly closes back
above the broken support, neckline, or lower boundary before treating the first
breakdown as clean.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


LAYER_ID = "bear_trap_stoploss_caution_layer_v1"
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bear_trap_stoploss_caution")

PATTERN_SPECS: dict[str, dict[str, Any]] = {
    "bear_flags": {
        "events_path": Path("artifacts/scanner_v2/bear_flags_db_source_parity/db_active/events.csv"),
        "path_path": Path("artifacts/scanner_v2/bear_flags_db_source_parity/db_active/post_breakout_path.csv"),
        "level_columns": ("flag_lower_breakout_value", "breakout_price"),
    },
    "bear_pennants": {
        "events_path": Path("artifacts/scanner_v2/pennants/events.csv"),
        "path_path": Path("artifacts/scanner_v2/pennants/post_breakout_path.csv"),
        "level_columns": ("flag_lower_breakout_value", "breakout_price"),
        "event_filters": {"variant": ("bear_pennant",)},
    },
    "triangles_descending": {
        "events_path": Path("artifacts/scanner_v2/descending_triangles_db_source_parity/db_active/events.csv"),
        "path_path": Path("artifacts/scanner_v2/descending_triangles_db_source_parity/db_active/post_breakout_path.csv"),
        "level_columns": ("triangle_support", "breakout_price"),
    },
    "double_tops_adam_adam": {
        "events_path": Path("artifacts/scanner_v2/double_pattern_family/double_tops/db_active/events.csv"),
        "path_path": Path("artifacts/scanner_v2/double_pattern_family/double_tops/db_active/post_breakout_path.csv"),
        "level_columns": ("neckline_price", "breakout_price"),
        "event_filters": {"variant": ("AA",)},
    },
    "double_tops_adam_eve": {
        "events_path": Path("artifacts/scanner_v2/double_pattern_family/double_tops/db_active/events.csv"),
        "path_path": Path("artifacts/scanner_v2/double_pattern_family/double_tops/db_active/post_breakout_path.csv"),
        "level_columns": ("neckline_price", "breakout_price"),
        "event_filters": {"variant": ("AE",)},
    },
    "double_tops_eve_adam": {
        "events_path": Path("artifacts/scanner_v2/double_pattern_family/double_tops/db_active/events.csv"),
        "path_path": Path("artifacts/scanner_v2/double_pattern_family/double_tops/db_active/post_breakout_path.csv"),
        "level_columns": ("neckline_price", "breakout_price"),
        "event_filters": {"variant": ("EA",)},
    },
    "double_tops_eve_eve": {
        "events_path": Path("artifacts/scanner_v2/double_pattern_family/double_tops/db_active/events.csv"),
        "path_path": Path("artifacts/scanner_v2/double_pattern_family/double_tops/db_active/post_breakout_path.csv"),
        "level_columns": ("neckline_price", "breakout_price"),
        "event_filters": {"variant": ("EE",)},
    },
    "head_and_shoulders_tops": {
        "events_path": Path("artifacts/scanner_v2/head_shoulders_family/head_and_shoulders_tops/db_active/events.csv"),
        "path_path": Path("artifacts/scanner_v2/head_shoulders_family/head_and_shoulders_tops/db_active/post_breakout_path.csv"),
        "level_columns": ("neckline_price", "breakout_price"),
    },
    "head_and_shoulders_tops_complex": {
        "events_path": Path("artifacts/scanner_v2/head_shoulders_family/head_and_shoulders_tops_complex/db_active/events.csv"),
        "path_path": Path("artifacts/scanner_v2/head_shoulders_family/head_and_shoulders_tops_complex/db_active/post_breakout_path.csv"),
        "level_columns": ("neckline_price", "breakout_price"),
    },
    "measured_move_down": {
        "events_path": Path("artifacts/scanner_v2/measured_move_family/measured_move_down/db_active/events.csv"),
        "path_path": Path("artifacts/scanner_v2/measured_move_family/measured_move_down/db_active/post_breakout_path.csv"),
        "level_columns": ("correction_end_price", "breakout_price"),
    },
    "rectangle_tops": {
        "events_path": Path("artifacts/scanner_v2/rectangle_family/rectangle_tops/db_active/events.csv"),
        "path_path": Path("artifacts/scanner_v2/rectangle_family/rectangle_tops/db_active/post_breakout_path.csv"),
        "level_columns": ("rectangle_support", "breakout_price"),
    },
    "broadening_tops": {
        "events_path": Path("artifacts/scanner_v2/broadening_family/broadening_tops/db_active/events.csv"),
        "path_path": Path("artifacts/scanner_v2/broadening_family/broadening_tops/db_active/post_breakout_path.csv"),
        "level_columns": ("broadening_support", "horizontal_low", "pattern_low", "breakout_price"),
    },
    "pipe_tops": {
        "events_path": Path("artifacts/scanner_v2/pipe_family/pipe_tops/db_active/events.csv"),
        "path_path": Path("artifacts/scanner_v2/pipe_family/pipe_tops/db_active/post_breakout_path.csv"),
        "level_columns": ("support_resistance_price", "low_boundary_price", "breakout_price"),
    },
    "triple_tops": {
        "events_path": Path("artifacts/scanner_v2/triple_family/triple_tops/db_active/events.csv"),
        "path_path": Path("artifacts/scanner_v2/triple_family/triple_tops/db_active/post_breakout_path.csv"),
        "level_columns": ("boundary_price", "breakout_price"),
    },
    "bump_and_run_reversal_tops": {
        "events_path": Path("artifacts/scanner_v2/bump_and_run_family/bump_and_run_reversal_tops/db_active/events.csv"),
        "path_path": Path("artifacts/scanner_v2/bump_and_run_family/bump_and_run_reversal_tops/db_active/post_breakout_path.csv"),
        "level_columns": ("trendline_at_confirmation", "breakout_price"),
    },
    "rounding_tops": {
        "events_path": Path("artifacts/scanner_v2/rounding_family/rounding_tops/db_active/events.csv"),
        "path_path": Path("artifacts/scanner_v2/rounding_family/rounding_tops/db_active/post_breakout_path.csv"),
        "level_columns": ("breakout_level", "breakout_price"),
    },
    "horn_tops": {
        "events_path": Path("artifacts/scanner_v2/horn_family/horn_tops/db_active/events.csv"),
        "path_path": Path("artifacts/scanner_v2/horn_family/horn_tops/db_active/post_breakout_path.csv"),
        "level_columns": ("support_resistance_price", "low_boundary_price", "breakout_price"),
    },
    "diamond_tops": {
        "events_path": Path("artifacts/scanner_v2/diamond_family/diamond_tops/db_active/events.csv"),
        "path_path": Path("artifacts/scanner_v2/diamond_family/diamond_tops/db_active/post_breakout_path.csv"),
        "level_columns": ("right_lower_breakout_level", "low_boundary_price", "breakout_price"),
    },
}


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path, low_memory=False)
    if "event_id" not in frame.columns and "detection_id" in frame.columns:
        frame["event_id"] = frame["detection_id"]
    return frame


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(fieldnames or (list(rows[0].keys()) if rows else []))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _as_float(value: Any, default: float = np.nan) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float(default)
    return out if np.isfinite(out) else float(default)


def _bool_series(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    text = series.astype(str).str.strip().str.lower()
    return text.isin({"1", "true", "yes", "y"})


def _first_existing_level(event: Mapping[str, Any], level_columns: Sequence[str]) -> tuple[str, float]:
    for column in level_columns:
        value = _as_float(event.get(column))
        if np.isfinite(value) and value > 0:
            return column, value
    return "breakout_price", _as_float(event.get("breakout_price"))


def _apply_event_filters(events: pd.DataFrame, filters: Mapping[str, Sequence[Any]] | None) -> pd.DataFrame:
    if not filters:
        return events
    out = events.copy()
    for column, allowed in filters.items():
        if column not in out.columns:
            return out.iloc[0:0].copy()
        allowed_text = {str(item).strip().lower() for item in allowed}
        out = out[out[column].astype(str).str.strip().str.lower().isin(allowed_text)].copy()
    return out


def _level_column_coverage(events: pd.DataFrame, level_columns: Sequence[str]) -> dict[str, Any]:
    usable: dict[str, int] = {}
    for column in level_columns:
        if column not in events.columns:
            usable[column] = 0
            continue
        values = pd.to_numeric(events[column], errors="coerce")
        usable[column] = int(((values.notna()) & (values > 0)).sum())
    source_columns = [column for column in level_columns if column != "breakout_price"]
    source_specific_count = sum(usable.get(column, 0) for column in source_columns)
    fallback_count = usable.get("breakout_price", 0)
    if source_specific_count > 0:
        status = "source_specific_reclaim_level_available"
    elif fallback_count > 0:
        status = "breakout_price_fallback_only"
    else:
        status = "no_reclaim_level_available"
    return {
        "level_coverage_status": status,
        "level_columns": list(level_columns),
        "level_usable_counts": usable,
    }


def _quality_score(event: Mapping[str, Any]) -> float:
    for column in ("publication_quality_score", "pattern_quality_score", "confidence_score", "tradability_quality_score"):
        score = _as_float(event.get(column))
        if np.isfinite(score):
            return max(0.0, min(100.0, score))
    return 55.0


def _severity(reclaim_20d_rate_pct: float, reclaim_10d_rate_pct: float) -> str:
    if reclaim_20d_rate_pct >= 60.0 or reclaim_10d_rate_pct >= 35.0:
        return "high_stoploss_caution"
    if reclaim_20d_rate_pct >= 25.0 or reclaim_10d_rate_pct >= 15.0:
        return "moderate_stoploss_caution"
    if reclaim_20d_rate_pct > 0.0:
        return "limited_stoploss_caution"
    return "no_current_caution_evidence"


def _build_one_pattern_cautions(
    pattern_id: str,
    *,
    reclaim_window_bars: int = 20,
    reclaim_threshold_pct: float = 0.0,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    spec = PATTERN_SPECS[pattern_id]
    events = _read_csv(spec["events_path"])
    path = _read_csv(spec["path_path"])
    if events.empty or path.empty:
        return pd.DataFrame(), {"status": "missing_events_or_path", "pattern_id": pattern_id}

    events = _apply_event_filters(events, spec.get("event_filters"))
    if events.empty:
        return pd.DataFrame(), {
            "status": "no_events_after_filters",
            "pattern_id": pattern_id,
            "event_filters": spec.get("event_filters") or {},
            "source_events": 0,
            "caution_events": 0,
            "decision": "not_measurable_no_events_after_filters",
            "tradable_promotion_allowed": False,
        }

    if "breakout_direction" in events.columns:
        events = events[events["breakout_direction"].astype(str).str.lower().eq("down")].copy()
    if events.empty:
        return pd.DataFrame(), {
            "status": "no_down_breakout_events",
            "pattern_id": pattern_id,
            "event_filters": spec.get("event_filters") or {},
            "source_events": 0,
            "caution_events": 0,
            "decision": "not_measurable_no_down_breakouts",
            "tradable_promotion_allowed": False,
        }
    if "is_primary_event_60d" in events.columns:
        primary = events[_bool_series(events["is_primary_event_60d"])].copy()
        if len(primary) >= max(10, int(len(events) * 0.25)):
            events = primary
    level_audit = _level_column_coverage(events, spec["level_columns"])

    path = path.copy()
    path["bar_after_breakout"] = pd.to_numeric(path.get("bar_after_breakout"), errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        if column in path.columns:
            path[column] = pd.to_numeric(path[column], errors="coerce")
    path_groups = {str(event_id): group.sort_values("bar_after_breakout").copy() for event_id, group in path.groupby("event_id", dropna=False)}

    rows: list[dict[str, Any]] = []
    source_count = 0
    for _, source_event in events.iterrows():
        source = source_event.to_dict()
        event_id = str(source.get("event_id"))
        raw_source_path = path_groups.get(event_id)
        if raw_source_path is None or raw_source_path.empty or not {"close", "high", "low"}.issubset(raw_source_path.columns):
            continue
        source_path = raw_source_path.dropna(subset=["close", "high", "low"]).copy()
        if source_path.empty:
            continue
        source_count += 1
        level_column, reclaim_level = _first_existing_level(source, spec["level_columns"])
        if not np.isfinite(reclaim_level) or reclaim_level <= 0:
            continue

        search = source_path[
            (source_path["bar_after_breakout"] >= 1)
            & (source_path["bar_after_breakout"] <= int(reclaim_window_bars))
        ].copy()
        threshold = reclaim_level * (1.0 + float(reclaim_threshold_pct) / 100.0)
        reclaim_rows = search[search["close"] >= threshold].copy()
        if reclaim_rows.empty:
            continue

        reclaim = reclaim_rows.iloc[0]
        reclaim_bar = int(reclaim["bar_after_breakout"])
        reclaim_price = float(reclaim["close"])
        before_reclaim = source_path[
            (source_path["bar_after_breakout"] >= 1)
            & (source_path["bar_after_breakout"] <= reclaim_bar)
        ].copy()
        after_reclaim = source_path[source_path["bar_after_breakout"] > reclaim_bar].copy()
        max_downside_before_reclaim_pct = max(0.0, (1.0 - float(before_reclaim["low"].min()) / reclaim_level) * 100.0)
        rebound_after_reclaim_pct = (
            max(0.0, (float(after_reclaim["high"].max()) / reclaim_price - 1.0) * 100.0)
            if not after_reclaim.empty
            else 0.0
        )
        second_breakdown_20d = (
            bool((after_reclaim[after_reclaim["bar_after_breakout"] <= reclaim_bar + 20]["low"] < reclaim_level * 0.98).any())
            if not after_reclaim.empty
            else False
        )
        rows.append(
            {
                "caution_event_id": f"stoploss_caution:{pattern_id}:{event_id}",
                "source_event_id": event_id,
                "source_pattern_id": pattern_id,
                "symbol": source.get("symbol"),
                "market_group": source.get("market_group"),
                "market_regime": source.get("market_regime"),
                "source_breakdown_date": source.get("breakout_date"),
                "reclaim_date": str(reclaim.get("trade_date")),
                "reclaim_bar_after_breakdown": reclaim_bar,
                "reclaim_level": round(reclaim_level, 6),
                "reclaim_level_source": level_column,
                "level_coverage_status": level_audit["level_coverage_status"],
                "reclaim_close": round(reclaim_price, 6),
                "reclaim_strength_pct": round((reclaim_price / reclaim_level - 1.0) * 100.0, 4),
                "max_downside_before_reclaim_pct": round(max_downside_before_reclaim_pct, 4),
                "rebound_after_reclaim_pct": round(rebound_after_reclaim_pct, 4),
                "second_breakdown_20d": second_breakdown_20d,
                "pattern_quality_score": round(_quality_score(source), 2),
                "pattern_quality_tier": source.get("pattern_quality_tier") or source.get("publication_quality_tier"),
                "liquidity_bucket": source.get("liquidity_bucket"),
                "stoploss_caution_action": "watch_reclaim_before_treating_breakdown_as_clean",
                "allowed_use": "risk_management_context_only",
                "forbidden_use": "buy_setup_or_tradable_promotion",
            }
        )

    caution_df = pd.DataFrame(rows)
    reclaim_bars = pd.to_numeric(caution_df.get("reclaim_bar_after_breakdown"), errors="coerce") if not caution_df.empty else pd.Series(dtype=float)
    reclaim_20d_rate = float(len(caution_df) / source_count * 100.0) if source_count else 0.0
    reclaim_10d_rate = float((reclaim_bars <= 10).mean() * reclaim_20d_rate) if source_count and not caution_df.empty else 0.0
    reclaim_5d_rate = float((reclaim_bars <= 5).mean() * reclaim_20d_rate) if source_count and not caution_df.empty else 0.0
    summary = {
        "status": "complete",
        "pattern_id": pattern_id,
        "event_filters": spec.get("event_filters") or {},
        "source_events": int(source_count),
        "caution_events": int(len(caution_df)),
        **level_audit,
        "reclaim_window_bars": int(reclaim_window_bars),
        "reclaim_threshold_pct": float(reclaim_threshold_pct),
        "failed_breakdown_reclaim_20d_rate_pct": round(reclaim_20d_rate, 2),
        "fast_reclaim_10d_rate_pct": round(reclaim_10d_rate, 2),
        "fast_reclaim_5d_rate_pct": round(reclaim_5d_rate, 2),
        "median_reclaim_bar": None if reclaim_bars.empty else round(float(reclaim_bars.median()), 2),
        "second_breakdown_after_reclaim_20d_rate_pct": (
            round(float(caution_df["second_breakdown_20d"].mean() * 100.0), 2) if not caution_df.empty else 0.0
        ),
        "caution_severity": _severity(reclaim_20d_rate, reclaim_10d_rate),
        "decision": (
            "publish_as_stoploss_caution_only"
            if level_audit["level_coverage_status"] == "source_specific_reclaim_level_available"
            else "publish_with_breakout_price_fallback_caveat"
        ),
        "tradable_promotion_allowed": False,
    }
    return caution_df.reset_index(drop=True), summary


def _write_markdown(path: Path, summaries: Sequence[Mapping[str, Any]]) -> None:
    lines = [
        "# Bear-Trap Stop-Loss Caution Layer",
        "",
        f"Layer: `{LAYER_ID}`",
        "",
        "Lớp này thay thế nhánh `bear-trap long setup`.  Kết luận dự án hiện tại là: bẫy giảm không đủ bền để nâng thành setup mua, nhưng đủ quan trọng để dùng như cảnh báo khi áp dụng stop-loss cơ học trên phá vỡ giảm.",
        "",
        "| Level status | Pattern | Source events | Caution events | Reclaim 20d | Reclaim 10d | Median reclaim bar | Second breakdown after reclaim | Severity |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in summaries:
        lines.append(
            f"| {row.get('level_coverage_status', row.get('status'))} | `{row.get('pattern_id')}` | "
            f"{row.get('source_events', 0)} | {row.get('caution_events', 0)} | "
            f"{row.get('failed_breakdown_reclaim_20d_rate_pct', 0)}% | {row.get('fast_reclaim_10d_rate_pct', 0)}% | "
            f"{row.get('median_reclaim_bar')} | {row.get('second_breakdown_after_reclaim_20d_rate_pct', 0)}% | "
            f"{row.get('caution_severity')} |"
        )
    lines += [
        "",
        "## Cách dùng",
        "",
        "- Dùng để nhắc người đọc không xem mọi breakdown bearish là sạch ngay ở phiên đầu.",
        "- Theo dõi việc giá đóng cửa reclaim lại vùng phá vỡ trong 5/10/20 phiên.",
        "- Không dùng lớp này để tạo BUY alert, không chấm điểm tradable, không sinh release candidate.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_bear_trap_stoploss_caution_layer(
    *,
    out_dir: Path = DEFAULT_OUT_DIR,
    patterns: Sequence[str] = tuple(PATTERN_SPECS),
    reclaim_window_bars: int = 20,
    reclaim_threshold_pct: float = 0.0,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []
    for pattern_id in patterns:
        pattern_dir = out_dir / pattern_id
        pattern_dir.mkdir(parents=True, exist_ok=True)
        events, summary = _build_one_pattern_cautions(
            pattern_id,
            reclaim_window_bars=reclaim_window_bars,
            reclaim_threshold_pct=reclaim_threshold_pct,
        )
        events.to_csv(pattern_dir / "stoploss_caution_events.csv", index=False)
        _write_json(pattern_dir / "stoploss_caution_summary.json", summary)
        summaries.append(summary)

    report = {
        "layer_id": LAYER_ID,
        "status": "PASS",
        "policy": {
            "replaces": "bear_trap_long_branch_v1",
            "allowed_use": "stop-loss caution, breakdown cleanliness check, defensive risk context",
            "forbidden_use": "BUY setup, long-cash promotion, tradable-final scoring",
            "event_anchor": "original bearish breakdown; reclaim is a caution observation, not a new entry event",
        },
        "summary": {
            "pattern_count": len(summaries),
            "caution_pattern_count": sum(1 for row in summaries if int(row.get("caution_events") or 0) > 0),
            "source_specific_measurable_count": sum(
                1 for row in summaries if row.get("level_coverage_status") == "source_specific_reclaim_level_available"
            ),
            "breakout_fallback_only_count": sum(1 for row in summaries if row.get("level_coverage_status") == "breakout_price_fallback_only"),
            "not_measurable_count": sum(1 for row in summaries if str(row.get("status")) != "complete"),
            "tradable_promotion_allowed": False,
        },
        "patterns": summaries,
    }
    _write_json(out_dir / "bear_trap_stoploss_caution_report.json", report)
    _write_csv(
        out_dir / "bear_trap_stoploss_caution_summary.csv",
        summaries,
        fieldnames=[
            "pattern_id",
            "status",
            "level_coverage_status",
            "source_events",
            "caution_events",
            "failed_breakdown_reclaim_20d_rate_pct",
            "fast_reclaim_10d_rate_pct",
            "fast_reclaim_5d_rate_pct",
            "median_reclaim_bar",
            "second_breakdown_after_reclaim_20d_rate_pct",
            "caution_severity",
            "decision",
            "tradable_promotion_allowed",
        ],
    )
    _write_markdown(out_dir / "bear_trap_stoploss_caution_report.md", summaries)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build bear-trap stop-loss caution artifacts.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--patterns", default="")
    parser.add_argument("--reclaim-window-bars", type=int, default=20)
    parser.add_argument("--reclaim-threshold-pct", type=float, default=0.0)
    args = parser.parse_args(argv)
    patterns = tuple(item.strip() for item in str(args.patterns).split(",") if item.strip()) or tuple(PATTERN_SPECS)
    unknown = sorted(set(patterns) - set(PATTERN_SPECS))
    if unknown:
        raise SystemExit(f"Unknown patterns: {', '.join(unknown)}")
    report = build_bear_trap_stoploss_caution_layer(
        out_dir=args.out_dir,
        patterns=patterns,
        reclaim_window_bars=args.reclaim_window_bars,
        reclaim_threshold_pct=args.reclaim_threshold_pct,
    )
    print(json.dumps({"status": report["status"], "summary": report["summary"], "out_dir": str(args.out_dir)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
