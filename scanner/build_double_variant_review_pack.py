from __future__ import annotations

import argparse
import base64
import json
import os
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

try:
    from .review_plot_helpers import (
        _ensure_dir,
        _load_symbol_ohlcv,
        _plot_candles,
        _slice_window,
        _write_json,
        _write_text,
    )
except ImportError:  # pragma: no cover
    from review_plot_helpers import (
        _ensure_dir,
        _load_symbol_ohlcv,
        _plot_candles,
        _slice_window,
        _write_json,
        _write_text,
    )


NON_AA_PATTERNS = [
    "double_bottoms_adam_eve",
    "double_bottoms_eve_adam",
    "double_bottoms_eve_eve",
    "double_tops_adam_eve",
    "double_tops_eve_adam",
    "double_tops_eve_eve",
]

VARIANT_BY_PATTERN = {
    "double_bottoms_adam_eve": "AE",
    "double_bottoms_eve_adam": "EA",
    "double_bottoms_eve_eve": "EE",
    "double_tops_adam_eve": "AE",
    "double_tops_eve_adam": "EA",
    "double_tops_eve_eve": "EE",
}


def _latest_run_id(results_db_path: Path) -> str:
    conn = sqlite3.connect(str(results_db_path))
    try:
        row = conn.execute(
            "SELECT run_id FROM scanner_runs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            raise SystemExit(f"No scanner_runs found in {results_db_path}")
        return str(row[0])
    finally:
        conn.close()


def _parse_pivot_indices(raw: Any) -> List[int]:
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    if not isinstance(raw, list):
        return []
    out: List[int] = []
    for x in raw:
        try:
            out.append(int(x))
        except Exception:
            continue
    return out


def _family_from_pattern(pattern_name: str) -> str:
    return "double_tops" if str(pattern_name).startswith("double_tops") else "double_bottoms"


def _load_review_rows(results_db_path: Path, *, split: str, run_id: str) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(str(results_db_path))
    conn.row_factory = sqlite3.Row
    try:
        sql = f"""
        SELECT
            d.pattern_id,
            d.symbol,
            d.pattern_name,
            d.pattern_type,
            d.formation_start,
            d.formation_end,
            d.breakout_date,
            d.breakout_direction,
            d.breakout_price,
            d.target_price,
            d.stop_loss_price,
            d.confidence_score,
            d.pattern_width_bars,
            d.touch_count,
            d.pattern_height_pct,
            d.pivot_indices_json,
            e.variant,
            e.peak1_width_bars,
            e.peak2_width_bars,
            e.max_favorable_excursion_pct,
            e.max_adverse_excursion_pct,
            e.bust_failure_5pct,
            e.boundary_invalidated,
            e.target_achieved_intraday,
            e.throwback_pullback_occurred,
            e.ultimate_price,
            e.ultimate_date,
            e.days_to_ultimate
        FROM pattern_detections d
        LEFT JOIN post_breakout_results e
          ON e.run_id = d.run_id
         AND e.pattern_id = d.pattern_id
        WHERE d.run_id = ?
          AND d.pattern_name IN ({",".join("?" for _ in NON_AA_PATTERNS)})
        ORDER BY d.pattern_name, d.symbol, d.formation_end
        """
        rows = conn.execute(sql, [run_id, *NON_AA_PATTERNS]).fetchall()
    finally:
        conn.close()

    out: List[Dict[str, Any]] = []
    for row in rows:
        pattern_name = str(row["pattern_name"])
        variant = str(row["variant"]) if row["variant"] is not None else VARIANT_BY_PATTERN.get(pattern_name)
        out.append(
            {
                "split": split,
                "run_id": run_id,
                "pattern_id": str(row["pattern_id"]),
                "symbol": str(row["symbol"]),
                "pattern_name": pattern_name,
                "family": _family_from_pattern(pattern_name),
                "variant": variant,
                "pattern_type": row["pattern_type"],
                "formation_start": row["formation_start"],
                "formation_end": row["formation_end"],
                "breakout_date": row["breakout_date"],
                "breakout_direction": row["breakout_direction"],
                "breakout_price": row["breakout_price"],
                "target_price": row["target_price"],
                "stop_loss_price": row["stop_loss_price"],
                "confidence_score": row["confidence_score"],
                "pattern_width_bars": row["pattern_width_bars"],
                "touch_count": row["touch_count"],
                "pattern_height_pct": row["pattern_height_pct"],
                "pivot_indices": _parse_pivot_indices(row["pivot_indices_json"]),
                "peak1_width_bars": row["peak1_width_bars"],
                "peak2_width_bars": row["peak2_width_bars"],
                "max_favorable_excursion_pct": row["max_favorable_excursion_pct"],
                "max_adverse_excursion_pct": row["max_adverse_excursion_pct"],
                "bust_failure_5pct": row["bust_failure_5pct"],
                "boundary_invalidated": row["boundary_invalidated"],
                "target_achieved_intraday": row["target_achieved_intraday"],
                "throwback_pullback_occurred": row["throwback_pullback_occurred"],
                "ultimate_price": row["ultimate_price"],
                "ultimate_date": row["ultimate_date"],
                "days_to_ultimate": row["days_to_ultimate"],
            }
        )
    return out


def _sort_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        rows,
        key=lambda r: (
            str(r["family"]),
            str(r["variant"] or ""),
            0 if str(r["split"]) == "valid" else 1,
            0 if r.get("breakout_date") else 1,
            -(int(r.get("confidence_score") or 0)),
            str(r["symbol"]),
            str(r["pattern_id"]),
        ),
    )


def _render_markdown(rows: List[Dict[str, Any]], summary: Dict[str, Any], out_dir: Path) -> str:
    lines: List[str] = []
    lines.append("# Double Variant Visual Review Pack")
    lines.append("")
    lines.append("## Scope")
    lines.append("")
    lines.append("Review pack này chỉ chứa các non-AA survivors (`AE`, `EA`, `EE`) của batch refactor `double_bottoms / double_tops` trên hai rerun targeted `calib` và `valid`.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- total rows: `{summary['total_rows']}`")
    lines.append(f"- by split: `{summary['by_split']}`")
    lines.append(f"- by family: `{summary['by_family']}`")
    lines.append(f"- by variant: `{summary['by_variant']}`")
    lines.append(f"- with breakout: `{summary['with_breakout']}`")
    lines.append("")
    lines.append("| Split | Family | Variant | Count | With breakout |")
    lines.append("|---|---|---:|---:|---:|")
    for split in ("valid", "calib"):
        for family in ("double_bottoms", "double_tops"):
            for variant in ("AE", "EA", "EE"):
                bucket = [
                    r for r in rows
                    if str(r["split"]) == split and str(r["family"]) == family and str(r["variant"]) == variant
                ]
                if not bucket:
                    continue
                lines.append(
                    f"| {split} | {family} | {variant} | {len(bucket)} | {sum(1 for r in bucket if r.get('breakout_date'))} |"
                )
    lines.append("")

    current_group: Optional[tuple[str, str, str]] = None
    for row in rows:
        group = (str(row["split"]), str(row["family"]), str(row["variant"]))
        if group != current_group:
            current_group = group
            lines.append(f"## {group[0]} / {group[1]} / {group[2]}")
            lines.append("")
        fig_path = row.get("figure_path")
        rel = os.path.relpath(str(fig_path), str(out_dir)) if fig_path else ""
        metrics = []
        if row.get("peak1_width_bars") is not None or row.get("peak2_width_bars") is not None:
            metrics.append(f"widths={row.get('peak1_width_bars')}/{row.get('peak2_width_bars')}")
        if row.get("pattern_width_bars") is not None:
            metrics.append(f"pattern_w={row.get('pattern_width_bars')}")
        if row.get("pattern_height_pct") is not None:
            metrics.append(f"height={float(row['pattern_height_pct']):.1f}%")
        if row.get("max_favorable_excursion_pct") is not None:
            metrics.append(f"mfe={float(row['max_favorable_excursion_pct']):.2f}%")
        if row.get("max_adverse_excursion_pct") is not None:
            metrics.append(f"mae={float(row['max_adverse_excursion_pct']):.2f}%")
        lines.append(
            f"- `{row['symbol']}` | `{row['pattern_name']}` | breakout=`{row.get('breakout_date') or 'none'}` | conf=`{row.get('confidence_score')}` | "
            + ", ".join(metrics)
        )
        if rel:
            lines.append("")
            lines.append(f"  ![]({rel})")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def build_review_pack(
    *,
    price_db: Path,
    calib_db: Path,
    valid_db: Path,
    out_dir: Path,
    pre_bars: int,
    post_bars: int,
) -> Dict[str, Any]:
    out_dir = Path(_ensure_dir(str(out_dir)))
    figures_dir = Path(_ensure_dir(str(out_dir / "figures")))

    rows = _load_review_rows(calib_db, split="calib", run_id=_latest_run_id(calib_db))
    rows.extend(_load_review_rows(valid_db, split="valid", run_id=_latest_run_id(valid_db)))
    rows = _sort_rows(rows)

    symbol_cache: Dict[str, pd.DataFrame] = {}
    for row in rows:
        symbol = str(row["symbol"])
        if symbol not in symbol_cache:
            symbol_cache[symbol] = _load_symbol_ohlcv(str(price_db), symbol)
        df_sym = symbol_cache[symbol]
        df_win, fs, fe, bd, w0 = _slice_window(
            df_sym,
            formation_start=str(row["formation_start"]),
            formation_end=str(row["formation_end"]),
            breakout_date=str(row["breakout_date"]) if row.get("breakout_date") else None,
            pre_bars=int(pre_bars),
            post_bars=int(post_bars),
        )
        safe_id = base64.urlsafe_b64encode(str(row["pattern_id"]).encode("utf-8")).decode("utf-8").rstrip("=")
        out_png = figures_dir / f"{row['split']}_{row['pattern_name']}_{safe_id}.png"
        piv_local = [
            int(pi) - int(w0)
            for pi in (row.get("pivot_indices") or [])
            if int(w0) <= int(pi) < int(w0) + len(df_win)
        ]
        widths = ""
        if row.get("peak1_width_bars") is not None or row.get("peak2_width_bars") is not None:
            widths = f" | widths={row.get('peak1_width_bars')}/{row.get('peak2_width_bars')}"
        title = (
            f"{row['split']} | {row['pattern_name']} | {row['symbol']} | var={row.get('variant') or '?'}"
            f" | conf={row.get('confidence_score')}{widths}"
        )
        _plot_candles(
            df_win,
            formation_start=fs,
            formation_end=fe,
            breakout_date=bd if bd is not None and not pd.isna(bd) else None,
            breakout_direction=row.get("breakout_direction"),
            target_price=row.get("target_price"),
            stop_loss_price=row.get("stop_loss_price"),
            pivot_local_indices=piv_local,
            title=title,
            out_png=str(out_png),
        )
        row["figure_path"] = str(out_png.resolve())

    summary = {
        "total_rows": len(rows),
        "with_breakout": sum(1 for r in rows if r.get("breakout_date")),
        "by_split": dict(Counter(str(r["split"]) for r in rows)),
        "by_family": dict(Counter(str(r["family"]) for r in rows)),
        "by_variant": dict(Counter(str(r["variant"]) for r in rows)),
    }

    payload = {"summary": summary, "rows": rows}
    _write_json(str(out_dir / "review_queue.json"), payload)
    _write_text(str(out_dir / "review_gallery.md"), _render_markdown(rows, summary, out_dir))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--price-db", default="vietnam_stocks.db")
    parser.add_argument("--calib-db", required=True)
    parser.add_argument("--valid-db", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--pre-bars", type=int, default=40)
    parser.add_argument("--post-bars", type=int, default=40)
    args = parser.parse_args()

    payload = build_review_pack(
        price_db=Path(args.price_db).resolve(),
        calib_db=Path(args.calib_db).resolve(),
        valid_db=Path(args.valid_db).resolve(),
        out_dir=Path(args.out_dir).resolve(),
        pre_bars=int(args.pre_bars),
        post_bars=int(args.post_bars),
    )
    print("=== Double Variant Review Pack ===")
    print(f"out_dir: {Path(args.out_dir).resolve()}")
    print(f"total_rows: {payload['summary']['total_rows']}")
    print(f"by_variant: {payload['summary']['by_variant']}")


if __name__ == "__main__":
    main()
