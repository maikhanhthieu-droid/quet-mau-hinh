"""Shared Scanner V2 source-data helpers."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

import pandas as pd


DEFAULT_SOURCE_DIR = Path("../market_stats/web/stock_series")
DEFAULT_MEMBERSHIP_DB = Path("../market_stats/cache/membership_history.sqlite")
DEFAULT_INDEX_DB = Path("vietnam_stocks.db")
DEFAULT_INDEX_SYMBOL = "VNINDEX"


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def symbol_from_path(path: Path) -> str:
    return path.stem.split(" ", 1)[0].strip().upper()


def load_market_stats_symbol(path: Path) -> pd.DataFrame:
    rows = read_json(path)
    if not isinstance(rows, list):
        raise ValueError(f"{path} must contain a list of OHLCV rows")
    symbol = symbol_from_path(path)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["symbol"] = symbol
    df["date"] = pd.to_datetime(df["date"])
    cols = ["symbol", "date", "open", "high", "low", "close", "volume"]
    return df[cols].copy()


def load_index_series(index_db: Path, index_symbol: str) -> pd.DataFrame:
    if not index_db.exists():
        return pd.DataFrame(columns=["date", "close"])
    conn = sqlite3.connect(str(index_db))
    try:
        df = pd.read_sql_query(
            "SELECT time AS date, close FROM stock_price_history WHERE symbol = ? ORDER BY time",
            conn,
            params=[index_symbol],
        )
    except Exception:
        return pd.DataFrame(columns=["date", "close"])
    finally:
        conn.close()
    if df.empty:
        return pd.DataFrame(columns=["date", "close"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df.dropna(subset=["date", "close"]).sort_values("date")[["date", "close"]].copy()


def classify_market_regimes(
    detections: Sequence[Mapping[str, Any]],
    *,
    index_db: Path = DEFAULT_INDEX_DB,
    index_symbol: str = DEFAULT_INDEX_SYMBOL,
    anchor_field: str = "formation_start_date",
) -> Tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = [dict(d) for d in detections]
    if not rows:
        return rows, {
            "enabled": False,
            "reason": "no_detections",
            "index_symbol": index_symbol,
            "anchor_field": anchor_field,
        }
    index_df = load_index_series(index_db, index_symbol)
    if index_df.empty:
        for row in rows:
            row["market_regime"] = "unknown"
        return rows, {
            "enabled": False,
            "reason": "missing_index_series",
            "index_db": str(index_db),
            "index_symbol": index_symbol,
            "anchor_field": anchor_field,
        }

    anchors = pd.DataFrame({"row_id": list(range(len(rows))), "anchor_date": [d.get(anchor_field) for d in rows]})
    anchors["anchor_date"] = pd.to_datetime(anchors["anchor_date"], errors="coerce")
    anchors = anchors.dropna(subset=["anchor_date"]).sort_values("anchor_date")
    idx = index_df.rename(columns={"close": "index_close"}).sort_values("date")
    at_anchor = pd.merge_asof(anchors, idx, left_on="anchor_date", right_on="date", direction="backward").rename(
        columns={"index_close": "close_anchor"}
    )
    lookback = anchors[["row_id", "anchor_date"]].copy()
    lookback["lookback_date"] = lookback["anchor_date"] - pd.DateOffset(months=18)
    at_lookback = pd.merge_asof(
        lookback[["row_id", "lookback_date"]].sort_values("lookback_date"),
        idx,
        left_on="lookback_date",
        right_on="date",
        direction="backward",
    ).rename(columns={"index_close": "close_lookback"})
    merged = at_anchor.merge(at_lookback[["row_id", "close_lookback"]], on="row_id", how="left")
    regimes: Dict[int, str] = {}
    for row_id, close_anchor, close_lookback in zip(merged["row_id"], merged["close_anchor"], merged["close_lookback"]):
        if pd.isna(close_anchor) or pd.isna(close_lookback):
            regimes[int(row_id)] = "unknown"
        elif float(close_anchor) > float(close_lookback):
            regimes[int(row_id)] = "bull"
        else:
            regimes[int(row_id)] = "bear"
    for i, row in enumerate(rows):
        row["market_regime"] = regimes.get(i, "unknown")
    return rows, {
        "enabled": True,
        "method": "VNINDEX 18-month close change at formation_start_date",
        "index_db": str(index_db),
        "index_symbol": index_symbol,
        "anchor_field": anchor_field,
        "index_rows": int(len(index_df)),
        "unknown_count": sum(1 for row in rows if row.get("market_regime") == "unknown"),
    }


def symbol_concentration(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts: Dict[str, int] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "UNKNOWN").upper()
        counts[symbol] = counts.get(symbol, 0) + 1
    total = sum(counts.values())
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    if total <= 0:
        return {"top10_symbol_share": None, "hhi_symbol": None, "top_symbols": []}
    return {
        "top10_symbol_share": round(sum(n for _, n in ranked[:10]) / total * 100.0, 2),
        "hhi_symbol": round(sum((n / total) ** 2 for _, n in ranked), 4),
        "top_symbols": [{"symbol": sym, "events": n} for sym, n in ranked[:10]],
    }


def load_current_members(index_code: str, membership_db: Path = DEFAULT_MEMBERSHIP_DB) -> set[str]:
    if not membership_db.exists():
        return set()
    conn = sqlite3.connect(str(membership_db))
    try:
        rows = conn.execute(
            """
            SELECT ticker
            FROM index_membership_history
            WHERE index_code = ? AND effective_to IS NULL
            """,
            (index_code,),
        ).fetchall()
    finally:
        conn.close()
    return {str(row[0]).upper() for row in rows}


def market_group(symbol: str, vn30: set[str], vn100: set[str]) -> str:
    sym = str(symbol).upper()
    if sym in vn30:
        return "VN30"
    if sym in vn100:
        return "VN100 ex VN30"
    return "Outside VN100"


def attach_current_market_groups(
    detections: Sequence[dict[str, Any]],
    membership_db: Path = DEFAULT_MEMBERSHIP_DB,
) -> dict[str, Any]:
    vn30 = load_current_members("VN30", membership_db)
    vn100 = load_current_members("VN100", membership_db)
    for row in detections:
        row["market_group"] = market_group(str(row.get("symbol") or ""), vn30, vn100)
    return {
        "method": "current membership snapshot from Market Stats V1 membership DB",
        "point_in_time": False,
        "membership_db": str(membership_db),
        "vn30_members": len(vn30),
        "vn100_members": len(vn100),
    }
