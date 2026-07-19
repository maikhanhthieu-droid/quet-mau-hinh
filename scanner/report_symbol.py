"""
Symbol-centric chart-pattern research report for Vietnam data.

This complements `scanner/report_bulkowski.py` by providing the opposite lens:
given a stock symbol, summarize which patterns appear, how often (bull/bear),
and how they performed post-breakout (when evaluation is available).

Examples:
  python3 scanner/report_symbol.py \\
    --results-db scan_results/databases/final/audit_bulkowski_v3.sqlite \\
    --price-db vietnam_stocks.db \\
    --index-symbol VN30 \\
    --symbol FPT \\
    --out-md scan_results/reports/FPT_symbol_report.md
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

try:
    from .pattern_set_metadata import build_pattern_metadata  # type: ignore
except Exception:  # pragma: no cover
    from pattern_set_metadata import build_pattern_metadata  # type: ignore


def _latest_run_id(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT run_id FROM scanner_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        raise SystemExit("No runs found in scanner_runs.")
    return str(row[0])


def _load_run_config(conn: sqlite3.Connection, run_id: str) -> Dict[str, Any]:
    row = conn.execute("SELECT run_config_json FROM scanner_runs WHERE run_id = ?", (run_id,)).fetchone()
    if not row or not row[0]:
        return {}
    try:
        return json.loads(row[0])
    except Exception:
        return {}


def _load_run_frame(conn: sqlite3.Connection, run_id: str) -> pd.DataFrame:
    q = """
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
        d.pattern_width_bars,
        d.confidence_score,
        d.pattern_height_pct,
        d.pivot_indices_json,
        r.ultimate_price,
        r.ultimate_date,
        r.days_to_ultimate,
        r.ultimate_stop_reason,
        r.throwback_pullback_occurred,
        r.throwback_pullback_date,
        r.days_to_throwback_pullback,
        r.retested_breakout_level,
        r.retested_boundary_level,
        r.target_achieved_intraday,
        r.target_achieved_close,
        r.target_achievement_date,
        r.days_to_target,
        r.max_favorable_excursion_pct,
        r.max_adverse_excursion_pct,
        r.bust_failure_5pct,
        r.bust_failure_10pct,
        r.boundary_invalidated,
        r.evaluation_window_bars
    FROM pattern_detections d
    LEFT JOIN post_breakout_results r
      ON r.run_id = d.run_id AND r.pattern_id = d.pattern_id
    WHERE d.run_id = ?
    """
    df = pd.read_sql_query(q, conn, params=[run_id])
    for col in [
        "formation_start",
        "formation_end",
        "breakout_date",
        "ultimate_date",
        "throwback_pullback_date",
        "target_achievement_date",
    ]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def _load_index_series(price_db_path: str, index_symbol: str) -> pd.DataFrame:
    conn = sqlite3.connect(price_db_path)
    try:
        df = pd.read_sql_query(
            "SELECT time as date, close FROM stock_price_history WHERE symbol = ? ORDER BY time",
            conn,
            params=[index_symbol],
        )
    finally:
        conn.close()

    if df.empty:
        raise SystemExit(f"Index series not found in stock_price_history for symbol={index_symbol!r}.")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "close"]).sort_values("date")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"])
    return df[["date", "close"]]


def _load_index_symbols(price_db_path: str) -> set[str]:
    conn = sqlite3.connect(price_db_path)
    try:
        rows = conn.execute("SELECT index_code FROM indices").fetchall()
    except Exception:
        rows = []
    finally:
        conn.close()
    return {str(r[0]) for r in rows if r and r[0] is not None}


def _apply_overlap_policy(df: pd.DataFrame, policy: str) -> pd.DataFrame:
    if policy == "none" or df.empty:
        return df

    required = {"pattern_id", "pattern_width_bars", "confidence_score"}
    if not required.issubset(set(df.columns)):
        return df

    def _bar_interval(row: pd.Series) -> Optional[tuple[int, int]]:
        piv = row.get("pivot_indices_json")
        if piv is None or (isinstance(piv, float) and np.isnan(piv)):
            return None
        try:
            xs = json.loads(piv) if isinstance(piv, str) else list(piv)
        except Exception:
            return None
        if not isinstance(xs, (list, tuple)) or not xs:
            return None
        out = []
        for x in xs:
            try:
                out.append(int(x))
            except Exception:
                continue
        if not out:
            return None
        return (min(out), max(out))

    def _overlaps_iv(a: tuple[int, int], b: tuple[int, int]) -> bool:
        return not (a[1] < b[0] or b[1] < a[0])

    g = df.copy()
    g["pattern_width_bars"] = pd.to_numeric(g["pattern_width_bars"], errors="coerce").fillna(0)
    g["confidence_score"] = pd.to_numeric(g["confidence_score"], errors="coerce").fillna(0)
    g["_confirmed"] = (
        g["breakout_date"].notna() & pd.to_numeric(g["breakout_price"], errors="coerce").notna()
    ).astype(int)
    g = g.sort_values(
        by=["pattern_width_bars", "_confirmed", "confidence_score", "pattern_name", "pattern_id"],
        ascending=[False, False, False, True, True],
    )

    kept: list[int] = []
    kept_ranges: list[tuple[int, int]] = []
    for i, row in g.iterrows():
        iv = _bar_interval(row)
        if iv is None:
            kept.append(i)
            continue
        if any(_overlaps_iv(iv, jv) for jv in kept_ranges):
            continue
        kept.append(i)
        kept_ranges.append(iv)

    return g.loc[kept].reset_index(drop=True)


def _classify_market_regime(df: pd.DataFrame, index_df: pd.DataFrame, *, anchor_col: str) -> pd.Series:
    """
    Bull if index close increased over the prior 18 months, else bear.
    Uses the nearest available index close on-or-before each date.
    """
    if anchor_col not in df.columns:
        return pd.Series([None] * len(df), index=df.index, dtype="object")

    anchors = df[["pattern_id", anchor_col]].copy()
    anchors = anchors.rename(columns={anchor_col: "anchor_date"})
    anchors["anchor_date"] = pd.to_datetime(anchors["anchor_date"], errors="coerce")
    anchors = anchors.dropna(subset=["anchor_date"]).copy()
    if anchors.empty:
        return pd.Series([None] * len(df), index=df.index, dtype="object")

    idx = index_df.sort_values("date").copy()
    idx = idx.rename(columns={"close": "index_close"})

    anchors_sorted = anchors.sort_values("anchor_date")

    at_anchor = pd.merge_asof(
        anchors_sorted,
        idx,
        left_on="anchor_date",
        right_on="date",
        direction="backward",
    ).rename(columns={"index_close": "close_anchor"})

    lookback = anchors_sorted.copy()
    lookback["lookback_date"] = lookback["anchor_date"] - pd.DateOffset(months=18)
    at_lookback = pd.merge_asof(
        lookback[["pattern_id", "lookback_date"]].sort_values("lookback_date"),
        idx,
        left_on="lookback_date",
        right_on="date",
        direction="backward",
    ).rename(columns={"index_close": "close_lookback"})

    merged = at_anchor.merge(at_lookback[["pattern_id", "close_lookback"]], on="pattern_id", how="left")

    ca = pd.to_numeric(merged["close_anchor"], errors="coerce")
    cl = pd.to_numeric(merged["close_lookback"], errors="coerce")
    valid = ca.notna() & cl.notna()
    bull = valid & (ca > cl)
    bear = valid & (ca <= cl)

    out = pd.Series([None] * len(merged), index=merged.index, dtype="object")
    out.loc[bull == True] = "bull"
    out.loc[bear == True] = "bear"

    out.index = merged["pattern_id"]
    return df["pattern_id"].map(out.to_dict())


def _rate(series: pd.Series) -> Optional[float]:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return None
    return float(s.mean() * 100.0)


def _median(series: pd.Series) -> Optional[float]:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return None
    return float(s.median())


def _compress_int_ranges(values: list[int]) -> str:
    xs = sorted(set(int(x) for x in values))
    if not xs:
        return ""
    start = prev = xs[0]
    out: list[str] = []
    for x in xs[1:]:
        if x == prev + 1:
            prev = x
            continue
        out.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = x
    out.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(out)


def _bulkowski_base_name(name: str) -> str:
    s = str(name or "").strip()
    if not s:
        return ""
    if " (" in s:
        s = s.split(" (", 1)[0].strip()
    if "," in s:
        s = s.split(",", 1)[0].strip()
    return s


def _pattern_group(pattern_key: str, *, group_by: str, meta_map: Dict[str, Dict[str, Any]]) -> str:
    if group_by == "pattern_key":
        return str(pattern_key)
    m = meta_map.get(str(pattern_key), {})
    if isinstance(m, dict):
        if group_by == "canonical_key":
            ck = m.get("canonical_key")
            if ck:
                return str(ck)
        if group_by == "spec_key":
            sk = m.get("spec_key")
            if sk:
                return str(sk)
    return str(pattern_key)


def _meta_rollup(pattern_keys: list[str], meta_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    chapters: list[int] = []
    names: list[str] = []
    kinds: list[str] = []
    for pk in pattern_keys:
        mm = meta_map.get(pk)
        if not isinstance(mm, dict):
            continue
        chap = mm.get("bulkowski_chapter")
        if isinstance(chap, int):
            chapters.append(int(chap))
        bn = mm.get("bulkowski_name")
        if bn:
            names.append(str(bn))
        kd = mm.get("kind")
        if kd:
            kinds.append(str(kd))

    base_names = sorted(set(_bulkowski_base_name(x) for x in names if _bulkowski_base_name(x)))
    display = base_names[0] if len(base_names) == 1 else ""
    return {
        "bulkowski_chapters": sorted(set(chapters)),
        "bulkowski_chapter_ranges": _compress_int_ranges(chapters) if chapters else "",
        "bulkowski_names": sorted(set(names)),
        "kinds": sorted(set(kinds)),
        "pattern_display_name": display,
    }


@dataclass(frozen=True, order=True)
class PerfGroupKey:
    pattern: str
    breakout_direction: str
    regime: str


def _summarize_frequency(
    df: pd.DataFrame,
    *,
    group_by: str,
    meta_map: Dict[str, Dict[str, Any]],
) -> list[dict[str, Any]]:
    if df.empty:
        return []
    gdf = df.copy()
    gdf["_pattern_key"] = gdf["pattern_name"].astype(str)
    gdf["_pattern_group"] = gdf["_pattern_key"].map(lambda k: _pattern_group(k, group_by=group_by, meta_map=meta_map))
    gdf["_confirmed"] = gdf["breakout_date"].notna() & gdf["breakout_price"].notna()
    gdf["_evaluated"] = gdf["evaluation_window_bars"].notna()
    gdf["_dir"] = gdf["breakout_direction"].fillna("unknown").astype(str)

    out: list[dict[str, Any]] = []
    for (pat, regime), g in gdf.groupby(["_pattern_group", "market_regime"], dropna=False):
        pattern_keys = sorted(set(str(x) for x in g["_pattern_key"].dropna().tolist()))
        meta = _meta_rollup(pattern_keys, meta_map)

        n_det = int(len(g))
        n_conf = int(g["_confirmed"].sum())
        n_eval = int(g["_evaluated"].sum())

        conf_up = int(((g["_confirmed"] == True) & (g["_dir"] == "up")).sum())
        conf_down = int(((g["_confirmed"] == True) & (g["_dir"] == "down")).sum())
        conf_unk = int(((g["_confirmed"] == True) & (g["_dir"] == "unknown")).sum())

        out.append(
            {
                "pattern": str(pat),
                "pattern_display_name": meta.get("pattern_display_name") or "",
                "pattern_keys": pattern_keys,
                "bulkowski_chapter_ranges": meta.get("bulkowski_chapter_ranges") or "",
                "market_regime": str(regime) if regime is not None else "unknown",
                "n_detections": n_det,
                "n_confirmed": n_conf,
                "n_evaluated": n_eval,
                "confirm_rate_pct": (n_conf / n_det * 100.0) if n_det else None,
                "eval_coverage_pct": (n_eval / n_conf * 100.0) if n_conf else None,
                "confirmed_up": conf_up,
                "confirmed_down": conf_down,
                "confirmed_unknown_dir": conf_unk,
            }
        )

    out.sort(key=lambda r: (-int(r.get("n_confirmed", 0) or 0), -int(r.get("n_detections", 0) or 0), str(r.get("market_regime")), str(r.get("pattern"))))
    return out


def _summarize_performance(
    df: pd.DataFrame,
    *,
    group_by: str,
    meta_map: Dict[str, Dict[str, Any]],
) -> list[dict[str, Any]]:
    if df.empty:
        return []

    df = df.copy()
    df["_confirmed"] = df["breakout_date"].notna() & df["breakout_price"].notna()
    df = df[df["_confirmed"]].copy()
    if df.empty:
        return []

    df["_evaluated"] = df["evaluation_window_bars"].notna()
    df["_pattern_key"] = df["pattern_name"].astype(str)
    df["_pattern_group"] = df["_pattern_key"].map(lambda k: _pattern_group(k, group_by=group_by, meta_map=meta_map))

    move = pd.to_numeric(df["max_favorable_excursion_pct"], errors="coerce")
    for thr in (5.0, 10.0, 15.0):
        col = f"failure_lt_{int(thr)}pct"
        df[col] = np.where(move.isna(), np.nan, move < float(thr))

    keys: list[PerfGroupKey] = []
    for _, row in df[["_pattern_group", "breakout_direction", "market_regime"]].fillna("unknown").iterrows():
        keys.append(PerfGroupKey(str(row["_pattern_group"]), str(row["breakout_direction"]), str(row["market_regime"])))
    df["_group_key"] = keys

    out: list[dict[str, Any]] = []
    for gk, g in df.groupby("_group_key"):
        g_eval = g[g["_evaluated"]].copy()
        n_conf = int(len(g))
        n_eval = int(g["_evaluated"].sum())
        pattern_keys = sorted(set(str(x) for x in g["_pattern_key"].dropna().tolist()))
        meta = _meta_rollup(pattern_keys, meta_map)

        display_name = str(gk.pattern)
        if group_by == "pattern_key":
            if meta.get("bulkowski_names"):
                display_name = str(meta["bulkowski_names"][0])
        else:
            if meta.get("pattern_display_name"):
                display_name = str(meta["pattern_display_name"])

        out.append(
            {
                "pattern": str(gk.pattern),
                "pattern_display_name": display_name,
                "pattern_keys": pattern_keys,
                "bulkowski_chapter_ranges": meta.get("bulkowski_chapter_ranges") or "",
                "breakout_direction": str(gk.breakout_direction),
                "market_regime": str(gk.regime),
                "n_confirmed": n_conf,
                "n_evaluated": n_eval,
                "eval_coverage_pct": (n_eval / n_conf * 100.0) if n_conf else None,
                "median_move_pct": _median(g_eval["max_favorable_excursion_pct"]),
                "median_days_to_ultimate": _median(g_eval["days_to_ultimate"]),
                "throwback_pullback_rate_pct": _rate(g_eval["throwback_pullback_occurred"]),
                "target_hit_rate_intraday_pct": _rate(g_eval["target_achieved_intraday"]),
                "boundary_invalidation_rate_pct": _rate(g_eval["boundary_invalidated"]),
                "busted_5pct_rate_pct": _rate(g_eval["bust_failure_5pct"]),
                "failure_lt_5pct_rate_pct": _rate(g_eval["failure_lt_5pct"]),
                "failure_lt_10pct_rate_pct": _rate(g_eval["failure_lt_10pct"]),
                "failure_lt_15pct_rate_pct": _rate(g_eval["failure_lt_15pct"]),
            }
        )

    out.sort(
        key=lambda r: (
            str(r.get("market_regime")),
            str(r.get("breakout_direction")),
            -int(r.get("n_evaluated", 0) or 0),
            -int(r.get("n_confirmed", 0) or 0),
            str(r.get("pattern")),
        )
    )
    return out


def _to_markdown(payload: Dict[str, Any]) -> str:
    def fmt(x: Any, digits: int = 2) -> str:
        if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
            return ""
        try:
            return f"{float(x):.{digits}f}"
        except Exception:
            return ""

    lines: list[str] = []
    lines.append("# Symbol Report")
    lines.append("")
    lines.append(f"- run_id: `{payload.get('run_id')}`")
    lines.append(f"- symbol: `{payload.get('symbol')}`")
    lines.append(f"- pattern_set: `{payload.get('pattern_set')}`")
    lines.append(f"- group_by: `{payload.get('group_by')}`")
    lines.append(f"- index_symbol: `{payload.get('index_symbol')}` (18-month regime)")
    lines.append(f"- anchor: `{payload.get('anchor')}`")
    lines.append(f"- overlap_policy: `{payload.get('overlap_policy')}`")
    lines.append(f"- min_breakout_price: `{payload.get('min_breakout_price')}`")
    lines.append(f"- detections: `{payload.get('n_detections')}`")
    lines.append(f"- confirmed breakouts: `{payload.get('n_confirmed')}`")
    lines.append(f"- evaluated: `{payload.get('n_evaluated')}`")
    lines.append("")

    lines.append("## Frequency (by regime)")
    lines.append("")
    lines.append("| Regime | Chap | Pattern | n_det | n_conf | n_eval | Conf% | Eval% | Conf up | Conf down |")
    lines.append("|---|---:|---|---:|---:|---:|---:|---:|---:|---:|")

    freq = payload.get("frequency", []) or []
    for r in freq:
        pat = str(r.get("pattern") or "")
        disp = str(r.get("pattern_display_name") or "")
        chap = str(r.get("bulkowski_chapter_ranges") or "")
        pat_s = f"{disp} (`{pat}`)" if disp and disp != pat else f"`{pat}`"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(r.get("market_regime") or ""),
                    chap,
                    pat_s,
                    str(int(r.get("n_detections", 0) or 0)),
                    str(int(r.get("n_confirmed", 0) or 0)),
                    str(int(r.get("n_evaluated", 0) or 0)),
                    fmt(r.get("confirm_rate_pct")),
                    fmt(r.get("eval_coverage_pct")),
                    str(int(r.get("confirmed_up", 0) or 0)),
                    str(int(r.get("confirmed_down", 0) or 0)),
                ]
            )
            + " |"
        )

    lines.append("")
    lines.append("## Performance (confirmed breakouts)")
    lines.append("")
    lines.append("| Regime | Dir | Chap | Pattern | n_eval | n_conf | Median move % | Median days to ultimate | TB/PB % | Fail<5% % | Target hit % | Boundary % | Busted5 % |")
    lines.append("|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")

    groups = payload.get("performance", []) or []
    for g in groups:
        pat = str(g.get("pattern") or "")
        disp = str(g.get("pattern_display_name") or "")
        chap = str(g.get("bulkowski_chapter_ranges") or "")
        pat_s = f"{disp} (`{pat}`)" if disp and disp != pat else f"`{pat}`"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(g.get("market_regime") or ""),
                    str(g.get("breakout_direction") or ""),
                    chap,
                    pat_s,
                    str(int(g.get("n_evaluated", 0) or 0)),
                    str(int(g.get("n_confirmed", 0) or 0)),
                    fmt(g.get("median_move_pct")),
                    fmt(g.get("median_days_to_ultimate"), digits=0),
                    fmt(g.get("throwback_pullback_rate_pct")),
                    fmt(g.get("failure_lt_5pct_rate_pct")),
                    fmt(g.get("target_hit_rate_intraday_pct")),
                    fmt(g.get("boundary_invalidation_rate_pct")),
                    fmt(g.get("busted_5pct_rate_pct")),
                ]
            )
            + " |"
        )

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    try:
        from .legacy_guard import require_legacy_enabled  # type: ignore
    except Exception:  # pragma: no cover
        from legacy_guard import require_legacy_enabled  # type: ignore

    require_legacy_enabled("scanner/report_symbol.py")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--results-db",
        default=os.path.join("scan_results", "pattern_scans.sqlite"),
        help="SQLite results DB produced by scanner/run_full_scan.py",
    )
    parser.add_argument("--run-id", default=None, help="run_id to report (default: latest).")
    parser.add_argument(
        "--pattern-set-hint",
        choices=[
            "digitized",
            "bulkowski_53",
            "bulkowski_53_strict",
            "bulkowski_strict_ohlcv",
            "bulkowski_49_strict_ohlcv",
            "event_ohlcv",
            "bulkowski_55_ohlcv",
        ],
        default=None,
        help="Optional hint to reconstruct pattern metadata for older runs that lack persisted metadata.",
    )
    parser.add_argument(
        "--price-db",
        default="vietnam_stocks.db",
        help="Source price DB containing stock_price_history (used for market regime index).",
    )
    parser.add_argument(
        "--index-symbol",
        default="VN30",
        help="Market index symbol present in stock_price_history (default: VN30).",
    )
    parser.add_argument("--symbol", required=True, help="Stock symbol to report, e.g. FPT.")
    parser.add_argument(
        "--anchor",
        choices=["formation_start", "breakout_date"],
        default="formation_start",
        help="Which detection timestamp anchors the 18-month regime lookback (default: formation_start).",
    )
    parser.add_argument(
        "--group-by",
        choices=["pattern_key", "canonical_key", "spec_key"],
        default="pattern_key",
        help="How to group patterns (default: pattern_key).",
    )
    parser.add_argument(
        "--overlap-policy",
        choices=["none", "bulkowski"],
        default="bulkowski",
        help="How to handle overlapping patterns before stats (default: bulkowski).",
    )
    parser.add_argument(
        "--min-breakout-price",
        type=float,
        default=None,
        help="Exclude patterns with breakout_price below this threshold (default: None).",
    )
    parser.add_argument("--out-json", default=None, help="Write JSON report to this path.")
    parser.add_argument("--out-md", default=None, help="Write Markdown report to this path.")
    args = parser.parse_args()

    results_db = os.path.abspath(args.results_db)
    if not os.path.exists(results_db):
        raise SystemExit(f"Results DB not found: {results_db}")

    price_db = os.path.abspath(args.price_db)
    if not os.path.exists(price_db):
        raise SystemExit(f"Price DB not found: {price_db}")

    conn = sqlite3.connect(results_db)
    try:
        run_id = str(args.run_id or _latest_run_id(conn))
        run_cfg = _load_run_config(conn, run_id)
        df = _load_run_frame(conn, run_id)
    finally:
        conn.close()

    symbol = str(args.symbol)
    if "symbol" not in df.columns:
        raise SystemExit("Results DB frame missing `symbol` column.")
    df = df[df["symbol"].astype(str) == symbol].copy()
    if df.empty:
        raise SystemExit(f"No detections found for symbol={symbol!r} in run_id={run_id!r}.")

    index_symbols = _load_index_symbols(price_db)
    if index_symbols and symbol in index_symbols:
        raise SystemExit(f"Refusing to report on index symbol {symbol!r}. Pick a stock symbol.")

    if args.min_breakout_price is not None and "breakout_price" in df.columns:
        df["breakout_price"] = pd.to_numeric(df["breakout_price"], errors="coerce")
        df = df[(df["breakout_price"].isna()) | (df["breakout_price"] >= float(args.min_breakout_price))].copy()

    if args.overlap_policy != "none":
        df = _apply_overlap_policy(df, str(args.overlap_policy))

    index_df = _load_index_series(price_db, str(args.index_symbol))

    anchor_col = str(args.anchor)
    if anchor_col not in df.columns:
        raise SystemExit(f"anchor column not present in results: {anchor_col}")
    df["market_regime"] = _classify_market_regime(df, index_df, anchor_col=anchor_col)
    df["market_regime"] = df["market_regime"].fillna("unknown")

    meta_payload = run_cfg.get("pattern_metadata") if isinstance(run_cfg, dict) else None
    meta_map: Dict[str, Dict[str, Any]] = {}
    if isinstance(meta_payload, dict):
        meta_map = meta_payload.get("patterns") if isinstance(meta_payload.get("patterns"), dict) else {}
    if (not meta_map) and args.pattern_set_hint:
        run_patterns = sorted(set(df["pattern_name"].dropna().astype(str).tolist()))
        meta_payload = build_pattern_metadata(pattern_set=str(args.pattern_set_hint), scanners={}, patterns=run_patterns)
        meta_map = meta_payload.get("patterns") if isinstance(meta_payload.get("patterns"), dict) else {}
    meta_map = meta_map or {}

    frequency = _summarize_frequency(df, group_by=str(args.group_by), meta_map=meta_map)
    performance = _summarize_performance(df, group_by=str(args.group_by), meta_map=meta_map)

    n_det = int(len(df))
    n_conf = int((df["breakout_date"].notna() & df["breakout_price"].notna()).sum())
    n_eval = int(df["evaluation_window_bars"].notna().sum())

    payload: Dict[str, Any] = {
        "run_id": run_id,
        "results_db": results_db,
        "price_db": price_db,
        "symbol": symbol,
        "pattern_set": (run_cfg.get("pattern_set") if isinstance(run_cfg, dict) else None) or args.pattern_set_hint,
        "pattern_metadata": meta_payload,
        "index_symbol": str(args.index_symbol),
        "anchor": anchor_col,
        "group_by": str(args.group_by),
        "overlap_policy": str(args.overlap_policy),
        "min_breakout_price": float(args.min_breakout_price) if args.min_breakout_price is not None else None,
        "n_detections": n_det,
        "n_confirmed": n_conf,
        "n_evaluated": n_eval,
        "frequency": frequency,
        "performance": performance,
    }

    md = _to_markdown(payload)

    if args.out_json:
        out_json = os.path.abspath(args.out_json)
        os.makedirs(os.path.dirname(out_json), exist_ok=True)
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True, default=str)
        print(f"Wrote JSON: {out_json}")

    if args.out_md:
        out_md = os.path.abspath(args.out_md)
        os.makedirs(os.path.dirname(out_md), exist_ok=True)
        with open(out_md, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"Wrote Markdown: {out_md}")

    if not args.out_json and not args.out_md:
        print(md)


if __name__ == "__main__":
    main()
