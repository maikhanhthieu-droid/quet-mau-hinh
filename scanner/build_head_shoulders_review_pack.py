from __future__ import annotations

import argparse
import base64
import json
import os
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

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


PATTERNS = [
    "head_and_shoulders_tops",
    "head_and_shoulders_tops_complex",
    "head_and_shoulders_bottoms",
    "head_and_shoulders_bottoms_complex",
]


OPTIONAL_DETECTION_COLUMNS = {
    "base_pattern_name": "d.base_pattern_name",
    "variant_code": "d.variant_code",
    "variant_confidence": "d.variant_confidence",
    "variant_evidence_json": "d.variant_evidence_json",
    "family_metrics_json": "d.family_metrics_json",
}


def _latest_run_id(results_db_path: Path) -> str:
    conn = sqlite3.connect(str(results_db_path))
    try:
        row = conn.execute("SELECT run_id FROM scanner_runs ORDER BY created_at DESC LIMIT 1").fetchone()
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


def _family(pattern_name: str) -> str:
    if "tops" in str(pattern_name):
        return "head_and_shoulders_top"
    return "head_and_shoulders_bottom"


def _variant(pattern_name: str) -> str:
    return "complex" if str(pattern_name).endswith("_complex") else "standard"


def _load_rows(results_db_path: Path, *, split: str, run_id: str) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(str(results_db_path))
    conn.row_factory = sqlite3.Row
    try:
        cols = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(pattern_detections)").fetchall()
        }
        optional_selects = [
            f"{expr} AS {name}"
            for name, expr in OPTIONAL_DETECTION_COLUMNS.items()
            if name in cols
        ]
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
            {",".join(optional_selects) + "," if optional_selects else ""}
            e.max_favorable_excursion_pct,
            e.max_adverse_excursion_pct,
            e.bust_failure_5pct,
            e.boundary_invalidated,
            e.target_achieved_intraday,
            e.throwback_pullback_occurred
        FROM pattern_detections d
        LEFT JOIN post_breakout_results e
          ON e.run_id = d.run_id
         AND e.pattern_id = d.pattern_id
        WHERE d.run_id = ?
          AND d.pattern_name IN ({",".join("?" for _ in PATTERNS)})
        ORDER BY d.pattern_name, d.breakout_date DESC, d.symbol
        """
        rows = conn.execute(sql, [run_id, *PATTERNS]).fetchall()
    finally:
        conn.close()

    out: List[Dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "split": split,
                "run_id": run_id,
                "pattern_id": str(row["pattern_id"]),
                "symbol": str(row["symbol"]),
                "pattern_name": str(row["pattern_name"]),
                "family": _family(str(row["pattern_name"])),
                "variant": _variant(str(row["pattern_name"])),
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
                "base_pattern_name": row["base_pattern_name"] if "base_pattern_name" in row.keys() else None,
                "variant_code": row["variant_code"] if "variant_code" in row.keys() else None,
                "variant_confidence": row["variant_confidence"] if "variant_confidence" in row.keys() else None,
                "variant_evidence_json": (
                    json.loads(row["variant_evidence_json"])
                    if "variant_evidence_json" in row.keys() and row["variant_evidence_json"]
                    else None
                ),
                "family_metrics_json": (
                    json.loads(row["family_metrics_json"])
                    if "family_metrics_json" in row.keys() and row["family_metrics_json"]
                    else None
                ),
                "max_favorable_excursion_pct": row["max_favorable_excursion_pct"],
                "max_adverse_excursion_pct": row["max_adverse_excursion_pct"],
                "bust_failure_5pct": row["bust_failure_5pct"],
                "boundary_invalidated": row["boundary_invalidated"],
                "target_achieved_intraday": row["target_achieved_intraday"],
                "throwback_pullback_occurred": row["throwback_pullback_occurred"],
            }
        )
    return out


def _sort_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        rows,
        key=lambda r: (
            str(r["family"]),
            str(r["variant"]),
            0 if str(r["split"]) == "valid" else 1,
            0 if r.get("breakout_date") else 1,
            -(int(r.get("confidence_score") or 0)),
            str(r["symbol"]),
        ),
    )


def _render_markdown(rows: List[Dict[str, Any]], summary: Dict[str, Any], out_dir: Path) -> str:
    lines: List[str] = []
    lines.append("# Head and Shoulders Visual Review Pack")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- total rows: `{summary['total_rows']}`")
    lines.append(f"- by split: `{summary['by_split']}`")
    lines.append(f"- by pattern: `{summary['by_pattern']}`")
    lines.append(f"- with breakout: `{summary['with_breakout']}`")
    lines.append("")
    lines.append("| Split | Pattern | Count | With breakout |")
    lines.append("|---|---|---:|---:|")
    for split in ("valid", "calib"):
        for pattern in PATTERNS:
            bucket = [r for r in rows if str(r["split"]) == split and str(r["pattern_name"]) == pattern]
            if not bucket:
                continue
            lines.append(f"| {split} | {pattern} | {len(bucket)} | {sum(1 for r in bucket if r.get('breakout_date'))} |")
    lines.append("")

    current_group = None
    for row in rows:
        group = (str(row["split"]), str(row["pattern_name"]))
        if group != current_group:
            current_group = group
            lines.append(f"## {group[0]} / {group[1]}")
            lines.append("")
        rel = os.path.relpath(str(row["figure_path"]), str(out_dir))
        metrics = []
        if row.get("variant_code"):
            metrics.append(f"variant={row['variant_code']}")
        if row.get("variant_confidence") is not None:
            metrics.append(f"variant_conf={row['variant_confidence']}")
        if row.get("pattern_width_bars") is not None:
            metrics.append(f"width={row['pattern_width_bars']}")
        if row.get("pattern_height_pct") is not None:
            metrics.append(f"height={float(row['pattern_height_pct']):.1f}%")
        if row.get("max_favorable_excursion_pct") is not None:
            metrics.append(f"mfe={float(row['max_favorable_excursion_pct']):.2f}%")
        if row.get("max_adverse_excursion_pct") is not None:
            metrics.append(f"mae={float(row['max_adverse_excursion_pct']):.2f}%")
        evidence = row.get("variant_evidence_json") or {}
        if evidence:
            extras_left = evidence.get("extra_shoulders_left")
            extras_right = evidence.get("extra_shoulders_right")
            if extras_left is not None or extras_right is not None:
                metrics.append(f"extras={extras_left}/{extras_right}")
            if evidence.get("width_exceeds_standard_max"):
                metrics.append("wide=1")
        lines.append(
            f"- `{row['symbol']}` | breakout=`{row.get('breakout_date') or 'none'}` | conf=`{row.get('confidence_score')}` | "
            + ", ".join(metrics)
        )
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

    rows = _load_rows(calib_db, split="calib", run_id=_latest_run_id(calib_db))
    rows.extend(_load_rows(valid_db, split="valid", run_id=_latest_run_id(valid_db)))
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
        title = (
            f"{row['split']} | {row['pattern_name']} | {row['symbol']}"
            f" | conf={row.get('confidence_score')} | w={row.get('pattern_width_bars')}"
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
        "by_pattern": dict(Counter(str(r["pattern_name"]) for r in rows)),
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
    parser.add_argument("--pre-bars", type=int, default=50)
    parser.add_argument("--post-bars", type=int, default=50)
    args = parser.parse_args()

    payload = build_review_pack(
        price_db=Path(args.price_db).resolve(),
        calib_db=Path(args.calib_db).resolve(),
        valid_db=Path(args.valid_db).resolve(),
        out_dir=Path(args.out_dir).resolve(),
        pre_bars=int(args.pre_bars),
        post_bars=int(args.post_bars),
    )
    print("=== Head and Shoulders Review Pack ===")
    print(f"out_dir: {Path(args.out_dir).resolve()}")
    print(f"total_rows: {payload['summary']['total_rows']}")
    print(f"by_pattern: {payload['summary']['by_pattern']}")


if __name__ == "__main__":
    main()
