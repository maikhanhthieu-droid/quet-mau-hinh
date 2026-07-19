from __future__ import annotations

import argparse
import base64
import json
import sqlite3
from collections import Counter
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
    from .digitized_pattern_engine import (
        DigitizedPatternLibrary,
        HeadShouldersBottomFamilyScanner,
        PivotSequenceScanner,
    )
    from .pattern_scanner import PatternScanner
except ImportError:  # pragma: no cover
    from review_plot_helpers import (
        _ensure_dir,
        _load_symbol_ohlcv,
        _plot_candles,
        _slice_window,
        _write_json,
        _write_text,
    )
    from digitized_pattern_engine import (
        DigitizedPatternLibrary,
        HeadShouldersBottomFamilyScanner,
        PivotSequenceScanner,
    )
    from pattern_scanner import PatternScanner


HARD_REJECT_RULES = {
    "invalid_metrics",
    "shoulder_clearance_nonpositive",
    "bottom_flat_microstructure",
}

FAILURE_SLACKS = {
    "shoulder_diff_pct": 2.5,
    "shoulder_ratio_min": 0.08,
    "shoulder_ratio_max": 0.08,
    "head_prominence_pct": 1.8,
    "height_pct_min": 5.0,
    "height_pct_max": 6.0,
    "neckline_slope_deg": 1.5,
    "side_span_ratio": 0.9,
    "bottom_shoulder_clearance_pct": 2.5,
    "bottom_zero_range_ratio": 0.05,
}


def _load_symbols(
    price_db: Path,
    *,
    min_rows: int,
    limit: Optional[int],
    symbols_csv: Optional[str],
) -> List[str]:
    if symbols_csv:
        return [s.strip() for s in str(symbols_csv).split(",") if s.strip()]

    conn = sqlite3.connect(str(price_db))
    try:
        df = pd.read_sql_query(
            """
            SELECT symbol, COUNT(*) AS cnt
            FROM stock_price_history
            GROUP BY symbol
            HAVING cnt >= ?
            ORDER BY symbol
            """,
            conn,
            params=[int(min_rows)],
        )
        symbols = [str(x) for x in df["symbol"].tolist()]
        try:
            idx_df = pd.read_sql_query("SELECT index_code FROM indices", conn)
            index_symbols = {str(x) for x in idx_df["index_code"].dropna().tolist()}
        except Exception:
            index_symbols = set()
        if index_symbols:
            symbols = [s for s in symbols if s not in index_symbols]
        if limit is not None:
            symbols = symbols[: int(limit)]
        return symbols
    finally:
        conn.close()


def _near_miss_ok(failures: List[Dict[str, Any]]) -> bool:
    if not failures or len(failures) > 2:
        return False
    for failure in failures:
        rule = str(failure.get("rule") or "")
        if rule in HARD_REJECT_RULES:
            return False
        slack = FAILURE_SLACKS.get(rule)
        if slack is None:
            return False
        margin = float(failure.get("margin") or 0.0)
        if margin > float(slack):
            return False
    return True


def _score_failures(failures: List[Dict[str, Any]]) -> float:
    score = 0.0
    for failure in failures:
        rule = str(failure.get("rule") or "")
        margin = float(failure.get("margin") or 0.0)
        slack = float(FAILURE_SLACKS.get(rule) or 1.0)
        score += margin / max(slack, 1e-9)
    return round(score, 4)


def _render_markdown(rows: List[Dict[str, Any]], summary: Dict[str, Any], out_dir: Path) -> str:
    lines: List[str] = []
    lines.append("# Inverse Head and Shoulders Recall Pack")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- symbols scanned: `{summary['symbols_scanned']}`")
    lines.append(f"- base candidates: `{summary['base_candidates']}`")
    lines.append(f"- survivors: `{summary['survivors']}`")
    lines.append(f"- near misses: `{summary['near_misses']}`")
    lines.append(f"- by status: `{summary['by_status']}`")
    lines.append(f"- top fail rules: `{summary['top_fail_rules']}`")
    lines.append("")

    for row in rows:
        rel = Path(row["figure_path"]).resolve().relative_to(out_dir.resolve())
        metrics = row.get("family_metrics") or {}
        failure_rules = [str(x.get("rule") or "") for x in row.get("failures") or []]
        lines.append(
            f"## {row['status']} | {row['symbol']} | conf={row.get('confidence_score')} | fail={','.join(failure_rules) or 'none'}"
        )
        lines.append("")
        lines.append(
            "- "
            + ", ".join(
                [
                    f"pattern_id=`{row['pattern_id']}`",
                    f"width={row.get('pattern_width_bars')}",
                    f"height={row.get('pattern_height_pct')}",
                    f"shoulder_diff={metrics.get('shoulder_diff_pct')}",
                    f"head_prom={metrics.get('head_prominence_pct')}",
                    f"shoulder_clear={metrics.get('shoulder_clearance_pct')}",
                    f"neck_slope={metrics.get('neckline_slope_deg')}",
                    f"span_ratio={metrics.get('side_span_ratio')}",
                    f"fail_score={row.get('failure_score')}",
                ]
            )
        )
        lines.append("")
        if row.get("failures"):
            lines.append("```json")
            lines.append(json.dumps(row["failures"], ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")
        lines.append(f"![{row['symbol']}]({str(rel)})")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def build_recall_pack(
    *,
    price_db: Path,
    out_dir: Path,
    min_rows: int,
    limit: Optional[int],
    symbols_csv: Optional[str],
    max_near_miss: int,
    max_survivors: int,
    pre_bars: int,
    post_bars: int,
) -> Dict[str, Any]:
    out_dir = Path(_ensure_dir(str(out_dir)))
    figures_dir = Path(_ensure_dir(str(out_dir / "figures")))

    lib = DigitizedPatternLibrary()
    scanner = HeadShouldersBottomFamilyScanner("head_and_shoulders_bottom", lib.load("head_and_shoulders_bottom"))
    scanner_core = PatternScanner(pattern_set="bulkowski_53_strict")

    symbols = _load_symbols(price_db, min_rows=min_rows, limit=limit, symbols_csv=symbols_csv)
    rows: List[Dict[str, Any]] = []
    base_candidates = 0
    symbol_cache: Dict[str, pd.DataFrame] = {}

    for symbol in symbols:
        df_sym = _load_symbol_ohlcv(str(price_db), symbol)
        if len(df_sym) < int(min_rows):
            continue
        df_norm, _ = scanner_core.normalizer.normalize(df_sym)
        raw_pivots = scanner_core.pivot_detector.detect_pivots(df_norm, scanner_core.config.pivot_type)
        pivots_filtered = scanner_core.pivot_detector.get_filtered_pivots(raw_pivots, min_spacing=10)

        base_rows = PivotSequenceScanner.scan(
            scanner,
            symbol=symbol,
            df=df_norm,
            pivots_filtered=pivots_filtered,
            pivots_raw=raw_pivots,
        )
        survivors = {
            str(r["pattern_id"]): r
            for r in scanner.scan(
                symbol=symbol,
                df=df_norm,
                pivots_filtered=pivots_filtered,
                pivots_raw=raw_pivots,
            )
        }

        for row in base_rows:
            if row.get("breakout_idx") is None or row.get("breakout_price") is None:
                continue
            base_candidates += 1
            metrics = scanner._family_metrics(df_norm, row.get("pivot_indices") or [])
            failures = scanner._family_gate_failures(metrics or {})
            status = "survivor" if not failures else ("near_miss" if _near_miss_ok(failures) else "rejected")
            if status == "rejected":
                continue

            variant = survivors.get(str(row["pattern_id"]))
            payload = dict(row)
            payload["status"] = status
            payload["family_metrics"] = metrics or {}
            payload["failures"] = failures
            payload["failure_score"] = _score_failures(failures) if failures else 0.0
            if variant:
                payload["variant_code"] = variant.get("variant_code")
                payload["variant_confidence"] = variant.get("variant_confidence")
                payload["variant_evidence"] = (
                    json.loads(str(variant.get("variant_evidence_json") or "{}"))
                    if variant.get("variant_evidence_json")
                    else {}
                )
            rows.append(payload)

    near_misses = [r for r in rows if str(r["status"]) == "near_miss"]
    near_misses.sort(
        key=lambda r: (
            int(len(r.get("failures") or [])),
            float(r.get("failure_score") or 999.0),
            -int(r.get("confidence_score") or 0),
            str(r["symbol"]),
        )
    )
    survivors = [r for r in rows if str(r["status"]) == "survivor"]
    survivors.sort(key=lambda r: (-int(r.get("confidence_score") or 0), str(r["symbol"])))
    rows = near_misses[: int(max_near_miss)] + survivors[: int(max_survivors)]

    symbol_cache = {}
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
        out_png = figures_dir / f"{row['status']}_{safe_id}.png"
        piv_local = [
            int(pi) - int(w0)
            for pi in (row.get("pivot_indices") or [])
            if int(w0) <= int(pi) < int(w0) + len(df_win)
        ]
        fail_short = ",".join(str(x.get("rule") or "") for x in row.get("failures") or [])
        title = (
            f"{row['status']} | {row['symbol']}"
            f" | conf={row.get('confidence_score')} | fail={fail_short or 'none'}"
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
        "symbols_scanned": len(symbols),
        "base_candidates": int(base_candidates),
        "survivors": len([r for r in rows if str(r["status"]) == "survivor"]),
        "near_misses": len([r for r in rows if str(r["status"]) == "near_miss"]),
        "by_status": dict(Counter(str(r["status"]) for r in rows)),
        "top_fail_rules": dict(
            Counter(str(x.get("rule") or "") for r in near_misses for x in (r.get("failures") or []))
        ),
    }
    payload = {"summary": summary, "rows": rows}
    _write_json(str(out_dir / "review_queue.json"), payload)
    _write_text(str(out_dir / "review_gallery.md"), _render_markdown(rows, summary, out_dir))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--price-db", default="vietnam_stocks.db")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--min-rows", type=int, default=500)
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--max-near-miss", type=int, default=24)
    parser.add_argument("--max-survivors", type=int, default=8)
    parser.add_argument("--pre-bars", type=int, default=60)
    parser.add_argument("--post-bars", type=int, default=60)
    args = parser.parse_args()

    payload = build_recall_pack(
        price_db=Path(args.price_db).resolve(),
        out_dir=Path(args.out_dir).resolve(),
        min_rows=int(args.min_rows),
        limit=int(args.limit) if args.limit is not None else None,
        symbols_csv=args.symbols,
        max_near_miss=int(args.max_near_miss),
        max_survivors=int(args.max_survivors),
        pre_bars=int(args.pre_bars),
        post_bars=int(args.post_bars),
    )
    print("=== H&S Bottom Recall Pack ===")
    print(f"out_dir: {Path(args.out_dir).resolve()}")
    print(f"summary: {payload['summary']}")


if __name__ == "__main__":
    main()
