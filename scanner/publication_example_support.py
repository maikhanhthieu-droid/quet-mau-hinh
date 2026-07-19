"""Shared publication example helpers.

These helpers are intentionally neutral: they do not own a chapter flow and
must not be used to render final PDFs directly. They exist so family builders
can load approved editorial sections and create example charts without
importing historical chapter builders.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

from scanner.canonical_chapter_content import load_approved_editorial_sections
from scanner.canonical_example_charts import _load_ohlcv


def load_public_editorial_sections(path: Path | None) -> dict[str, Any]:
    """Load approved AI/human editorial sections in the canonical schema."""

    if path is None or not path.exists():
        return {}
    return dict(load_approved_editorial_sections(path))


def slice_around_event(df: pd.DataFrame, event: Mapping[str, Any], pre_bars: int = 35, post_bars: int = 35) -> pd.DataFrame:
    """Return a compact OHLCV window around a pattern event."""

    fs = pd.to_datetime(event["formation_start_date"])
    bd = pd.to_datetime(event["breakout_date"])
    start_idx = int(df["date"].searchsorted(fs, side="left"))
    breakout_idx = int(df["date"].searchsorted(bd, side="left"))
    lo = max(0, start_idx - pre_bars)
    hi = min(len(df), breakout_idx + post_bars + 1)
    return df.iloc[lo:hi].copy().reset_index(drop=True)


def plot_event_chart(df: pd.DataFrame, event: Mapping[str, Any], out_path: Path, title: str) -> None:
    """Draw a generic candlestick example chart for non-canonical drafts.

    Final public chapters should prefer ``canonical_example_charts``. This
    helper remains for older family build scripts whose chart code is still
    being migrated, but it is no longer tied to Bull Flag legacy builders.
    """

    fs = pd.to_datetime(event["formation_start_date"])
    fe = pd.to_datetime(event["formation_end_date"])
    bd = pd.to_datetime(event["breakout_date"])
    x = np.arange(len(df))

    fig, ax = plt.subplots(figsize=(9.2, 4.8), dpi=180)
    for i, row in df.iterrows():
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        color = "#1b8a5a" if c >= o else "#c44e52"
        ax.vlines(i, l, h, color="#222222", linewidth=0.7, alpha=0.75)
        ax.add_patch(
            Rectangle(
                (i - 0.32, min(o, c)),
                0.64,
                max(abs(c - o), 1e-6),
                facecolor=color,
                edgecolor=color,
                linewidth=0.5,
                alpha=0.9,
            )
        )
    ax.plot(x, df["close"], color="#222222", linewidth=0.9, alpha=0.28)

    def nearest(ts: pd.Timestamp) -> int:
        idx = int(df["date"].searchsorted(ts, side="left"))
        return max(0, min(idx, len(df) - 1))

    i0, i1, ib = nearest(fs), nearest(fe), nearest(bd)
    ax.axvspan(i0 - 0.5, i1 + 0.5, color="#1f77b4", alpha=0.10)
    ax.axvline(ib, color="#6f4aa8", linewidth=1.15)
    ax.text(ib + 0.3, float(df["high"].max()), "Phá vỡ", fontsize=8, color="#6f4aa8", va="bottom")

    breakout_price = float(event["breakout_price"])
    target_price = float(event["target_price"])
    ax.axhline(breakout_price, color="#245b5a", linestyle="--", linewidth=0.9, alpha=0.85)
    ax.axhline(target_price, color="#e98b2a", linestyle="--", linewidth=0.9, alpha=0.9)
    ax.text(0.5, breakout_price, "giá phá vỡ", fontsize=7, color="#245b5a", va="bottom")
    ax.text(0.5, target_price, "mục tiêu", fontsize=7, color="#e98b2a", va="bottom")

    ax.set_title(title, fontsize=10, loc="left")
    ax.grid(True, alpha=0.14)
    y_min = min(float(df["low"].min()), breakout_price, target_price)
    y_max = max(float(df["high"].max()), breakout_price, target_price)
    pad = max(0.01, (y_max - y_min) * 0.08)
    ax.set_ylim(y_min - pad, y_max + pad)
    step = max(1, len(df) // 7)
    ticks = list(range(0, len(df), step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([pd.to_datetime(df.iloc[i]["date"]).strftime("%Y-%m-%d") for i in ticks], rotation=35, ha="right", fontsize=7)
    ax.tick_params(axis="y", labelsize=7)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
