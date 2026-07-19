from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle


def _ensure_dir(path: str) -> str:
    p = os.path.abspath(path)
    os.makedirs(p, exist_ok=True)
    return p


def _write_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True, default=str, ensure_ascii=False)


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _load_symbol_ohlcv(price_db_path: str, symbol: str) -> pd.DataFrame:
    conn = sqlite3.connect(os.path.abspath(price_db_path))
    try:
        df = pd.read_sql_query(
            "SELECT time as date, open, high, low, close, volume FROM stock_price_history WHERE symbol = ? ORDER BY time",
            conn,
            params=[symbol],
        )
    finally:
        conn.close()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)
    return df


def _slice_window(
    df: pd.DataFrame,
    *,
    formation_start: str,
    formation_end: str,
    breakout_date: Optional[str],
    pre_bars: int = 30,
    post_bars: int = 30,
) -> Tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp, Optional[pd.Timestamp], int]:
    fs = pd.to_datetime(formation_start, errors="coerce")
    fe = pd.to_datetime(formation_end, errors="coerce")
    bd = pd.to_datetime(breakout_date, errors="coerce") if breakout_date else pd.NaT
    bd = bd if pd.notna(bd) else pd.NaT

    if df.empty or pd.isna(fs) or pd.isna(fe):
        return df.iloc[:0].copy(), fs, fe, (bd if pd.notna(bd) else None), 0

    idx_start = int(df["date"].searchsorted(fs, side="left"))
    idx_end = int(df["date"].searchsorted(fe, side="right"))
    if idx_end <= idx_start:
        idx_end = min(len(df), idx_start + 1)

    w0 = max(0, idx_start - int(pre_bars))
    w1 = min(len(df), idx_end + int(post_bars))
    out = df.iloc[w0:w1].copy().reset_index(drop=True)
    return out, fs, fe, (bd if pd.notna(bd) else None), int(w0)


def _plot_candles(
    df: pd.DataFrame,
    *,
    formation_start: pd.Timestamp,
    formation_end: pd.Timestamp,
    breakout_date: Optional[pd.Timestamp],
    breakout_direction: Optional[str],
    target_price: Optional[float],
    stop_loss_price: Optional[float],
    pivot_local_indices: Optional[List[int]],
    title: str,
    out_png: str,
) -> None:
    if df.empty:
        return

    g = df.copy()
    g = g.dropna(subset=["date", "open", "high", "low", "close"]).reset_index(drop=True)
    if g.empty:
        return

    x = np.arange(len(g))
    dates = g["date"].tolist()

    fig_w = max(11.0, min(14.0, len(g) / 12.0))
    fig_h = 6.5
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=170)

    up_color = "#2ca02c"
    down_color = "#d62728"
    wick_color = "#111111"

    for i, row in g.iterrows():
        o = float(row["open"])
        h = float(row["high"])
        l = float(row["low"])
        c = float(row["close"])
        color = up_color if c >= o else down_color
        ax.vlines(x[i], l, h, color=wick_color, linewidth=0.8, alpha=0.9)
        y0 = min(o, c)
        height = max(1e-9, abs(c - o))
        rect = Rectangle((x[i] - 0.3, y0), 0.6, height, facecolor=color, edgecolor=color, linewidth=0.6, alpha=0.85)
        ax.add_patch(rect)

    ax.plot(x, g["close"].to_numpy(), color="#111111", linewidth=0.9, alpha=0.28, label="_nolegend_")

    def _nearest_idx(ts: pd.Timestamp) -> Optional[int]:
        if ts is None or pd.isna(ts):
            return None
        j = int(g["date"].searchsorted(ts, side="left"))
        if j < 0:
            return 0
        if j >= len(g):
            return len(g) - 1
        return j

    i0 = _nearest_idx(pd.to_datetime(formation_start))
    i1 = _nearest_idx(pd.to_datetime(formation_end))
    if i0 is not None and i1 is not None and i1 >= i0:
        ax.axvspan(i0 - 0.5, i1 + 0.5, color="#1f77b4", alpha=0.08, label="Formation")
        ax.axvline(i0, color="#1f77b4", linewidth=0.8, alpha=0.55, label="_nolegend_")
        ax.axvline(i1, color="#1f77b4", linewidth=0.8, alpha=0.55, label="_nolegend_")

    if breakout_date is not None and not pd.isna(breakout_date):
        ib = _nearest_idx(pd.to_datetime(breakout_date))
        if ib is not None:
            ax.axvline(ib, color="#9467bd", linewidth=1.2, alpha=0.9)
            lbl = f"Breakout ({(breakout_direction or '').lower() or '?'})"
            ax.text(ib + 0.2, float(g["high"].max()), lbl, fontsize=8, color="#9467bd", va="bottom")

    if pivot_local_indices:
        def _infer_pivot_price(idx: int) -> float:
            j0 = max(0, idx - 2)
            j1 = min(len(g), idx + 3)
            hi = float(g.iloc[idx]["high"])
            lo = float(g.iloc[idx]["low"])
            win = g.iloc[j0:j1]
            try:
                if np.isfinite(hi) and hi >= float(win["high"].max()) - 1e-12:
                    return hi
                if np.isfinite(lo) and lo <= float(win["low"].min()) + 1e-12:
                    return lo
            except Exception:
                pass
            return float(g.iloc[idx]["close"])

        piv_x: List[float] = []
        piv_y: List[float] = []
        piv_sorted = [int(i) for i in pivot_local_indices if isinstance(i, (int, np.integer))]
        piv_sorted = [i for i in piv_sorted if 0 <= i < len(g)]
        for k, idx in enumerate(piv_sorted):
            px = float(x[idx])
            py = _infer_pivot_price(idx)
            piv_x.append(px)
            piv_y.append(py)
            ax.scatter([px], [py], s=48, color="#111111", alpha=0.85, zorder=6, label="_nolegend_")
            ax.text(
                px,
                py,
                str(k + 1),
                fontsize=7,
                color="white",
                ha="center",
                va="center",
                zorder=7,
                bbox={"boxstyle": "circle,pad=0.2", "facecolor": "#111111", "edgecolor": "none", "alpha": 0.65},
            )
        if len(piv_x) >= 2:
            ax.plot(piv_x, piv_y, color="#111111", linewidth=1.25, alpha=0.55, zorder=5, label="Pivots")

    if target_price is not None and np.isfinite(float(target_price)):
        ax.axhline(float(target_price), color="#ff7f0e", linestyle="--", linewidth=1.0, alpha=0.9, label="Target")
    if stop_loss_price is not None and np.isfinite(float(stop_loss_price)):
        ax.axhline(float(stop_loss_price), color="#7f7f7f", linestyle="--", linewidth=1.0, alpha=0.9, label="Stop")

    ax.set_title(title)
    ax.set_xlim(-1, len(g))
    ax.grid(True, alpha=0.15)

    y_vals = [float(g["low"].min()), float(g["high"].max())]
    if target_price is not None and np.isfinite(float(target_price)):
        y_vals.append(float(target_price))
    if stop_loss_price is not None and np.isfinite(float(stop_loss_price)):
        y_vals.append(float(stop_loss_price))
    y_min = float(np.nanmin(y_vals))
    y_max = float(np.nanmax(y_vals))
    pad = 0.08 * (y_max - y_min) if y_max > y_min else 1.0
    ax.set_ylim(y_min - pad, y_max + pad)

    step = max(1, int(len(g) / 10))
    ticks = list(range(0, len(g), step))
    labels = [pd.to_datetime(dates[i]).strftime("%Y-%m-%d") for i in ticks]
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)

    handles, labels = ax.get_legend_handles_labels()
    uniq: Dict[str, Any] = {}
    for h, l in zip(handles, labels):
        if not l or l == "_nolegend_":
            continue
        if l not in uniq:
            uniq[l] = h
    if uniq:
        ax.legend(uniq.values(), uniq.keys(), loc="upper left", fontsize=8, frameon=False)

    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_png)
    plt.close(fig)
