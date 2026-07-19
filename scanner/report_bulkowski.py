"""
Bulkowski-style research report for Vietnam data.

Reads:
  1) A scan results DB produced by `scanner/run_full_scan.py`
  2) A price DB (default: `vietnam_stocks.db`) for market-regime classification

Key methodology alignment (see `extraction_phase_1/global/methodology.json`):
  - Primary statistics use medians (not means).
  - Time metrics are calendar days.
  - Bull/bear regime is based on index performance over the prior 18 months.

Example:
  python3 scanner/report_bulkowski.py \\
    --results-db scan_results/databases/final/audit_kpi.sqlite \\
    --price-db vietnam_stocks.db \\
    --index-symbol VN30 \\
    --out-json scan_results/reports/bulkowski_report.json \\
    --out-md scan_results/reports/bulkowski_report.md
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

    for col in ["formation_start", "formation_end", "breakout_date", "ultimate_date", "throwback_pullback_date", "target_achievement_date"]:
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


def _overlaps(a0: pd.Timestamp, a1: pd.Timestamp, b0: pd.Timestamp, b1: pd.Timestamp) -> bool:
    return not (a1 < b0 or b1 < a0)


def _apply_overlap_policy(df: pd.DataFrame, policy: str) -> pd.DataFrame:
    if policy == "none" or df.empty:
        return df

    required = {"symbol", "pattern_id", "pattern_width_bars", "confidence_score"}
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

    out_rows = []
    for sym, g in df.groupby("symbol"):
        g = g.copy()

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

        out_rows.append(g.loc[kept])

    if not out_rows:
        return df.iloc[:0].copy()
    return pd.concat(out_rows, ignore_index=True)


def _classify_market_regime(
    df: pd.DataFrame,
    index_df: pd.DataFrame,
    *,
    anchor_col: str,
) -> pd.Series:
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

    # Re-align to original df order.
    out.index = merged["pattern_id"]
    return df["pattern_id"].map(out.to_dict())


def _rate(series: pd.Series) -> Optional[float]:
    s = pd.to_numeric(series, errors="coerce")
    s = s.dropna()
    if s.empty:
        return None
    return float(s.mean() * 100.0)


def _median(series: pd.Series) -> Optional[float]:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return None
    return float(s.median())


@dataclass(frozen=True, order=True)
class GroupKey:
    pattern_name: str
    breakout_direction: str
    regime: str


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


def _summarize(
    df: pd.DataFrame,
    *,
    group_by: str = "pattern_key",
    meta_map: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    df = df.copy()

    # Keep only rows with confirmed breakouts (required for post-breakout stats).
    df = df[df["breakout_date"].notna() & df["breakout_price"].notna()].copy()
    if df.empty:
        return {"total_confirmed": 0, "groups": []}

    df["_evaluated"] = df["evaluation_window_bars"].notna()
    df["_pattern_key"] = df["pattern_name"].astype(str)

    # Bulkowski-style failure thresholds (move to ultimate < X%).
    move = pd.to_numeric(df["max_favorable_excursion_pct"], errors="coerce")
    for thr in (5.0, 10.0, 15.0):
        col = f"failure_lt_{int(thr)}pct"
        df[col] = np.where(move.isna(), np.nan, move < float(thr))

    def _group_key_for_pattern(pattern_key: str) -> str:
        if group_by == "pattern_key":
            return str(pattern_key)
        m = meta_map.get(str(pattern_key)) if isinstance(meta_map, dict) else None
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

    df["_pattern_group"] = df["_pattern_key"].map(_group_key_for_pattern)

    keys = []
    for _, row in df[["_pattern_group", "breakout_direction", "market_regime"]].fillna("unknown").iterrows():
        keys.append(GroupKey(str(row["_pattern_group"]), str(row["breakout_direction"]), str(row["market_regime"])))
    df["_group_key"] = keys

    out_groups = []
    for gk, g in df.groupby("_group_key"):
        g_eval = g[g["_evaluated"]].copy()
        n_confirmed = int(len(g))
        n_evaluated = int(g["_evaluated"].sum())

        pattern_keys = sorted(set(str(x) for x in g["_pattern_key"].dropna().tolist()))
        chapters: list[int] = []
        bulk_names: list[str] = []
        kinds: list[str] = []
        for pk in pattern_keys:
            mm = meta_map.get(pk) if isinstance(meta_map, dict) else None
            if not isinstance(mm, dict):
                continue
            chap = mm.get("bulkowski_chapter")
            if isinstance(chap, int):
                chapters.append(int(chap))
            bn = mm.get("bulkowski_name")
            if bn:
                bulk_names.append(str(bn))
            kd = mm.get("kind")
            if kd:
                kinds.append(str(kd))

        display_name = str(gk.pattern_name)
        if group_by == "pattern_key":
            if bulk_names:
                display_name = str(bulk_names[0])
        else:
            base_names = sorted(set(_bulkowski_base_name(x) for x in bulk_names if _bulkowski_base_name(x)))
            if len(base_names) == 1:
                display_name = base_names[0]

        group = {
            "pattern_name": gk.pattern_name,
            "pattern_display_name": display_name,
            "pattern_keys": pattern_keys,
            "bulkowski_chapters": sorted(set(chapters)),
            "bulkowski_chapter_ranges": _compress_int_ranges(chapters) if chapters else "",
            "bulkowski_names": sorted(set(bulk_names)),
            "kinds": sorted(set(kinds)),
            "breakout_direction": gk.breakout_direction,
            "market_regime": gk.regime,
            "n_confirmed": n_confirmed,
            "n_evaluated": n_evaluated,
            "eval_coverage_pct": (n_evaluated / n_confirmed * 100.0) if n_confirmed else None,
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
        out_groups.append(group)

    out_groups.sort(
        key=lambda x: (
            -int(x.get("n_evaluated", 0) or 0),
            -int(x.get("n_confirmed", 0) or 0),
            str(x.get("pattern_name")),
            str(x.get("market_regime")),
            str(x.get("breakout_direction")),
        )
    )
    return {
        "total_confirmed": int(len(df)),
        "total_evaluated": int(df["_evaluated"].sum()),
        "groups": out_groups,
    }


def _add_rank(groups: list[dict[str, Any]]) -> None:
    # Rank patterns by median_move_pct per (market_regime, breakout_direction).
    by_bucket: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for g in groups:
        bucket = (str(g.get("market_regime")), str(g.get("breakout_direction")))
        by_bucket.setdefault(bucket, []).append(g)

    for bucket, items in by_bucket.items():
        sortable = [x for x in items if isinstance(x.get("median_move_pct"), (int, float))]
        sortable.sort(
            key=lambda x: (
                -float(x["median_move_pct"]),
                -int(x.get("n_evaluated", 0) or 0),
                -int(x.get("n_confirmed", 0) or 0),
                str(x.get("pattern_name")),
            )
        )
        for i, g in enumerate(sortable, start=1):
            g["rank_by_median_move"] = i


def _to_markdown(payload: Dict[str, Any]) -> str:
    run_id = payload.get("run_id")
    pattern_set = payload.get("pattern_set")
    group_by = payload.get("group_by") or "pattern_key"
    idx = payload.get("index_symbol")
    overlap = payload.get("overlap_policy")
    min_bp = payload.get("min_breakout_price")
    total = int(payload.get("summary", {}).get("total_confirmed", 0) or 0)
    total_eval = int(payload.get("summary", {}).get("total_evaluated", 0) or 0)

    meta_payload = payload.get("pattern_metadata") if isinstance(payload, dict) else None
    meta_map = {}
    if isinstance(meta_payload, dict):
        meta_map = meta_payload.get("patterns") if isinstance(meta_payload.get("patterns"), dict) else {}
    meta_map = meta_map or {}

    lines = [
        f"# Bulkowski-style Report",
        "",
        f"- run_id: `{run_id}`",
        f"- pattern_set: `{pattern_set}`",
        f"- group_by: `{group_by}`",
        f"- index_symbol: `{idx}` (18-month regime)",
        f"- overlap_policy: `{overlap}`",
        f"- min_breakout_price: `{min_bp}`",
        f"- confirmed breakouts: `{total}`",
        f"- evaluated: `{total_eval}`",
        "",
        "## Groups",
        "",
        "| Regime | Dir | Rank | Chap | Pattern | n_eval | n_conf | Median move % | Median days to ultimate | TB/PB % | Fail<5% % | Target hit % | Boundary % | Busted5 % |",
        "|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    groups = payload.get("summary", {}).get("groups", []) or []
    # Prefer ranked ordering where available.
    groups_sorted = sorted(
        groups,
        key=lambda g: (
            str(g.get("market_regime")),
            str(g.get("breakout_direction")),
            int(g.get("rank_by_median_move", 10**9)),
            -int(g.get("n_evaluated", 0) or 0),
            -int(g.get("n_confirmed", 0) or 0),
            str(g.get("pattern_name")),
        ),
    )

    def fmt(x: Any, digits: int = 2) -> str:
        if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
            return ""
        try:
            return f"{float(x):.{digits}f}"
        except Exception:
            return ""

    for g in groups_sorted:
        pat_key = str(g.get("pattern_name", "") or "")
        chap_s = ""
        if str(group_by) == "pattern_key":
            chaps = g.get("bulkowski_chapters") if isinstance(g, dict) else None
            if isinstance(chaps, list) and len(chaps) == 1 and isinstance(chaps[0], int):
                chap_s = str(int(chaps[0]))
            else:
                meta = meta_map.get(pat_key) if meta_map else None
                chap = meta.get("bulkowski_chapter") if isinstance(meta, dict) else None
                chap_s = str(int(chap)) if isinstance(chap, int) else ""
            pat_name = str(g.get("pattern_display_name") or pat_key)
        else:
            chap_s = str(g.get("bulkowski_chapter_ranges") or "")
            disp = str(g.get("pattern_display_name") or pat_key)
            pat_name = f"{disp} (`{pat_key}`)" if disp and disp != pat_key else f"`{pat_key}`"

        lines.append(
            "| "
            + " | ".join(
                [
                    str(g.get("market_regime", "")),
                    str(g.get("breakout_direction", "")),
                    str(g.get("rank_by_median_move", "")) if g.get("rank_by_median_move") is not None else "",
                    chap_s,
                    pat_name,
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

    require_legacy_enabled("scanner/report_bulkowski.py")
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
        help="How to group patterns in the report (default: pattern_key).",
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

    payload = generate_bulkowski_payload(
        results_db_path=str(args.results_db),
        price_db_path=str(args.price_db),
        index_symbol=str(args.index_symbol),
        run_id=str(args.run_id) if args.run_id else None,
        pattern_set_hint=str(args.pattern_set_hint) if args.pattern_set_hint else None,
        anchor=str(args.anchor),
        group_by=str(args.group_by),
        overlap_policy=str(args.overlap_policy),
        min_breakout_price=float(args.min_breakout_price) if args.min_breakout_price is not None else None,
    )

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


def generate_bulkowski_payload(
    *,
    results_db_path: str,
    price_db_path: str,
    index_symbol: str = "VN30",
    run_id: Optional[str] = None,
    pattern_set_hint: Optional[str] = None,
    anchor: str = "formation_start",
    group_by: str = "pattern_key",
    overlap_policy: str = "bulkowski",
    min_breakout_price: Optional[float] = None,
) -> Dict[str, Any]:
    results_db = os.path.abspath(results_db_path)
    if not os.path.exists(results_db):
        raise SystemExit(f"Results DB not found: {results_db}")

    price_db = os.path.abspath(price_db_path)
    if not os.path.exists(price_db):
        raise SystemExit(f"Price DB not found: {price_db}")

    conn = sqlite3.connect(results_db)
    try:
        rid = str(run_id or _latest_run_id(conn))
        run_cfg = _load_run_config(conn, rid)
        df = _load_run_frame(conn, rid)
    finally:
        conn.close()

    # Exclude index series from the stock sample (Bulkowski-style common-stock filter).
    index_symbols = _load_index_symbols(price_db)
    if index_symbols and "symbol" in df.columns:
        df = df[~df["symbol"].astype(str).isin(index_symbols)].copy()

    if min_breakout_price is not None and "breakout_price" in df.columns:
        df["breakout_price"] = pd.to_numeric(df["breakout_price"], errors="coerce")
        df = df[(df["breakout_price"].isna()) | (df["breakout_price"] >= float(min_breakout_price))].copy()

    # Overlap handling should happen before regime classification and stats.
    if overlap_policy != "none":
        df = _apply_overlap_policy(df, str(overlap_policy))

    index_df = _load_index_series(price_db, str(index_symbol))

    anchor_col = str(anchor)
    if anchor_col not in df.columns:
        raise SystemExit(f"anchor column not present in results: {anchor_col}")

    df["market_regime"] = _classify_market_regime(df, index_df, anchor_col=anchor_col)

    meta_payload = run_cfg.get("pattern_metadata") if isinstance(run_cfg, dict) else None
    meta_map = {}
    if isinstance(meta_payload, dict):
        meta_map = meta_payload.get("patterns") if isinstance(meta_payload.get("patterns"), dict) else {}
    if (not meta_map) and pattern_set_hint:
        run_patterns = sorted(set(df["pattern_name"].dropna().astype(str).tolist()))
        meta_payload = build_pattern_metadata(pattern_set=str(pattern_set_hint), scanners={}, patterns=run_patterns)
        meta_map = meta_payload.get("patterns") if isinstance(meta_payload.get("patterns"), dict) else {}
    meta_map = meta_map or {}

    summary = _summarize(df, group_by=str(group_by), meta_map=meta_map)
    _add_rank(summary.get("groups", []))

    return {
        "run_id": rid,
        "results_db": results_db,
        "price_db": price_db,
        "pattern_set": (run_cfg.get("pattern_set") if isinstance(run_cfg, dict) else None) or pattern_set_hint,
        "pattern_metadata": meta_payload,
        "index_symbol": str(index_symbol),
        "anchor": anchor_col,
        "group_by": str(group_by),
        "overlap_policy": str(overlap_policy),
        "min_breakout_price": float(min_breakout_price) if min_breakout_price is not None else None,
        "summary": summary,
    }


if __name__ == "__main__":
    main()
