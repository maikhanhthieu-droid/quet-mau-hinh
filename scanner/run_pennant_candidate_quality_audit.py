"""Publication-readiness audit for Pennant candidates.

This is not a chapter builder. It checks whether the source-grounded Pennant
scanner is strong enough to move into the public chapter workflow.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

from scanner.v2.source_data import DEFAULT_SOURCE_DIR, load_market_stats_symbol, symbol_from_path


DEFAULT_EVENTS = Path("artifacts/scanner_v2/pennants/events.csv")
DEFAULT_PATH = Path("artifacts/scanner_v2/pennants/post_breakout_path.csv")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/pennant_candidate_quality_audit")
TARGET_BANDS = (0.5, 0.75, 1.0)
TIER_MAP = {"clean": "premium", "usable": "standard", "loose": "loose"}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _pct(num: float, den: float) -> Optional[float]:
    return round(float(num) / float(den) * 100.0, 2) if den else None


def _median(values: Sequence[Any]) -> Optional[float]:
    series = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna()
    return round(float(series.median()), 2) if not series.empty else None


def _wilson_interval(successes: int, total: int, *, z: float = 1.959963984540054) -> dict[str, Optional[float]]:
    if total <= 0:
        return {"low": None, "high": None, "half_width": None}
    p = successes / total
    denom = 1.0 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt((p * (1.0 - p) + z * z / (4 * total)) / total) / denom
    low = max(0.0, centre - margin) * 100.0
    high = min(1.0, centre + margin) * 100.0
    return {"low": round(low, 2), "high": round(high, 2), "half_width": round((high - low) / 2.0, 2)}


def _as_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin({"true", "1", "yes", "y"})


def _load_events(path: Path, path_frame: pd.DataFrame) -> pd.DataFrame:
    events = pd.read_csv(path)
    if "event_id" not in events.columns and "detection_id" in events.columns:
        events["event_id"] = events["detection_id"]
    for column in ("target_hit", "failure_5pct", "target_first_before_adverse_5pct", "volume_confirmed"):
        if column in events.columns:
            events[column] = _as_bool(events[column])
    numeric_cols = (
        "target_dist_pct",
        "mfe_pct",
        "mae_pct",
        "pattern_quality_score",
        "pennant_to_pole_pct",
        "compression_ratio",
        "pole_move_pct",
        "pattern_width_bars",
    )
    for column in numeric_cols:
        if column in events.columns:
            events[column] = pd.to_numeric(events[column], errors="coerce")
    events["breakout_ts"] = pd.to_datetime(events.get("breakout_date"), errors="coerce")
    events["publication_quality_tier"] = events.get("pattern_quality_tier", pd.Series("", index=events.index)).astype(str).map(TIER_MAP).fillna("data_limited")
    if "mfe_pct" in events.columns:
        missing = events["mfe_pct"].isna() | events.get("mae_pct", pd.Series(np.nan, index=events.index)).isna()
        events.loc[missing, "publication_quality_tier"] = "data_limited"
    liquidity = _liquidity_features(path_frame)
    events = events.merge(liquidity, on="event_id", how="left")
    return events


def _load_path(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    for column in ("bar_after_breakout", "signed_high_excursion_pct", "signed_low_excursion_pct", "close", "volume"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.sort_values(["event_id", "bar_after_breakout"]).reset_index(drop=True)


def _liquidity_features(path: pd.DataFrame) -> pd.DataFrame:
    if path.empty or not {"event_id", "close", "volume", "bar_after_breakout"}.issubset(path.columns):
        return pd.DataFrame(columns=["event_id", "post_breakout_value20_median", "liquidity_bucket"])
    scoped = path[path["bar_after_breakout"].between(1, 20, inclusive="both")].copy()
    scoped["value"] = pd.to_numeric(scoped["close"], errors="coerce") * pd.to_numeric(scoped["volume"], errors="coerce")
    values = scoped.groupby("event_id", as_index=False)["value"].median().rename(columns={"value": "post_breakout_value20_median"})
    nonzero = values["post_breakout_value20_median"].replace([np.inf, -np.inf], np.nan).dropna()
    if len(nonzero) >= 3:
        q1, q2 = nonzero.quantile([1 / 3, 2 / 3]).tolist()
        values["liquidity_bucket"] = np.select(
            [values["post_breakout_value20_median"] <= q1, values["post_breakout_value20_median"] <= q2],
            ["low", "mid"],
            default="high",
        )
    else:
        values["liquidity_bucket"] = "unknown"
    return values


def _target_path_flags(events: pd.DataFrame, path: pd.DataFrame, *, target_multiple: float, horizon: int = 120) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(columns=["event_id", "target_hit_band", "target_first_band", "days_to_target_band"])
    targets = events[["event_id", "target_dist_pct"]].copy()
    targets["target_threshold_pct"] = pd.to_numeric(targets["target_dist_pct"], errors="coerce") * float(target_multiple)
    working = path[path["bar_after_breakout"].between(1, int(horizon), inclusive="both")].merge(targets, on="event_id", how="inner")
    rows: list[dict[str, Any]] = []
    for event_id, group in working.groupby("event_id", sort=False):
        threshold = pd.to_numeric(group["target_threshold_pct"], errors="coerce").dropna()
        if threshold.empty:
            continue
        target_level = float(threshold.iloc[0])
        days_to_target: Optional[int] = None
        days_to_adverse: Optional[int] = None
        for row in group.sort_values("bar_after_breakout").itertuples(index=False):
            bar = int(getattr(row, "bar_after_breakout"))
            high_exc = float(getattr(row, "signed_high_excursion_pct"))
            low_exc = float(getattr(row, "signed_low_excursion_pct"))
            if days_to_target is None and high_exc >= target_level:
                days_to_target = bar
            if days_to_adverse is None and low_exc <= -5.0:
                days_to_adverse = bar
        hit = days_to_target is not None
        rows.append(
            {
                "event_id": event_id,
                "target_hit_band": bool(hit),
                "target_first_band": bool(hit and (days_to_adverse is None or int(days_to_target) < int(days_to_adverse))),
                "days_to_target_band": int(days_to_target) if days_to_target is not None else None,
            }
        )
    flags = pd.DataFrame(rows)
    return events[["event_id"]].merge(flags, on="event_id", how="left").fillna({"target_hit_band": False, "target_first_band": False})


def _metrics(events: pd.DataFrame, path: pd.DataFrame, *, target_multiple: float, row_id: str) -> dict[str, Any]:
    if {"target_hit_band", "target_first_band"}.issubset(events.columns):
        working = events.copy()
    else:
        flags = _target_path_flags(events, path, target_multiple=target_multiple)
        working = events.merge(flags, on="event_id", how="left")
    n = int(len(working))
    hit = int(working["target_hit_band"].fillna(False).sum()) if n else 0
    first = int(working["target_first_band"].fillna(False).sum()) if n else 0
    failure = int(working.get("failure_5pct", pd.Series(False, index=working.index)).fillna(False).sum()) if n else 0
    med_mfe = _median(working.get("mfe_pct", []))
    med_mae = _median(working.get("mae_pct", []))
    return {
        "row_id": row_id,
        "target_multiple": float(target_multiple),
        "n": n,
        "target_hit_rate_pct": _pct(hit, n),
        "target_hit_wilson": _wilson_interval(hit, n),
        "target_first_before_adverse_5pct_rate_pct": _pct(first, n),
        "target_first_wilson": _wilson_interval(first, n),
        "failure_5pct_rate_pct": _pct(failure, n),
        "median_mfe_pct": med_mfe,
        "median_mae_pct": med_mae,
        "mfe_mae_median_ratio": round(float(med_mfe) / max(float(med_mae), 1.0), 2) if med_mfe is not None and med_mae is not None else None,
    }


def _target_tables(events: pd.DataFrame, path: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    banded_by_multiple = {
        target_multiple: events.merge(_target_path_flags(events, path, target_multiple=target_multiple), on="event_id", how="left")
        for target_multiple in TARGET_BANDS
    }
    for target_multiple, banded in banded_by_multiple.items():
        for variant in ("bull_pennant", "bear_pennant", "all"):
            base = banded if variant == "all" else banded[banded["variant"].astype(str) == variant]
            for tier in ("premium", "standard", "loose", "premium+standard", "all"):
                subset = base if tier == "all" else base[base["publication_quality_tier"].isin(["premium", "standard"])] if tier == "premium+standard" else base[base["publication_quality_tier"].astype(str) == tier]
                rows.append({"variant": variant, "tier": tier, **_metrics(subset.copy(), path, target_multiple=target_multiple, row_id=f"{variant}:{tier}")})
    return rows


def _cooldown(events: pd.DataFrame, days: int) -> pd.DataFrame:
    scoped = events.sort_values(["symbol", "breakout_ts"]).copy()
    keep: list[int] = []
    last_by_symbol: dict[str, pd.Timestamp] = {}
    for idx, row in scoped.iterrows():
        symbol = str(row.get("symbol"))
        ts = row.get("breakout_ts")
        if pd.isna(ts):
            continue
        last = last_by_symbol.get(symbol)
        if last is None or (ts - last).days >= days:
            keep.append(idx)
            last_by_symbol[symbol] = ts
    return scoped.loc[keep].copy()


def _robustness_tables(events: pd.DataFrame, path: pd.DataFrame, *, target_multiple: float = 0.5) -> dict[str, list[dict[str, Any]]]:
    if not {"target_hit_band", "target_first_band"}.issubset(events.columns):
        events = events.merge(_target_path_flags(events, path, target_multiple=target_multiple), on="event_id", how="left")
    bull_public = events[(events["variant"].astype(str) == "bull_pennant") & events["publication_quality_tier"].isin(["premium", "standard"])].copy()
    temporal_rows: list[dict[str, Any]] = []
    if not bull_public.empty:
        ranked = bull_public.sort_values("breakout_ts").reset_index(drop=True)
        split_indices = np.array_split(np.arange(len(ranked)), 3)
        splits = [ranked.iloc[idx].copy() for idx in split_indices]
        for name, split in zip(("early_third", "middle_third", "late_third"), splits):
            row = _metrics(split.copy(), path, target_multiple=target_multiple, row_id=name)
            row["period"] = name
            row["date_start"] = str(split["breakout_ts"].min().date()) if not split.empty else None
            row["date_end"] = str(split["breakout_ts"].max().date()) if not split.empty else None
            temporal_rows.append(row)
    cooldown_rows = []
    for days in (30, 60, 90):
        reduced = _cooldown(bull_public, days)
        row = _metrics(reduced, path, target_multiple=target_multiple, row_id=f"cooldown_{days}d")
        row["cooldown_days"] = days
        row["retention_pct"] = _pct(len(reduced), len(bull_public))
        cooldown_rows.append(row)
    interaction_rows = []
    if not bull_public.empty:
        for (regime, liquidity), group in bull_public.groupby(["market_regime", "liquidity_bucket"], dropna=False):
            row = _metrics(group.copy(), path, target_multiple=target_multiple, row_id=f"{regime}:{liquidity}")
            row["market_regime"] = str(regime)
            row["liquidity_bucket"] = str(liquidity)
            interaction_rows.append(row)
    return {"temporal_split": temporal_rows, "cooldown": cooldown_rows, "regime_liquidity": interaction_rows}


def _cluster_bootstrap(events: pd.DataFrame, path: pd.DataFrame, *, target_multiple: float = 0.5, seed: int = 20260521, reps: int = 300) -> dict[str, Any]:
    scoped = events[(events["variant"].astype(str) == "bull_pennant") & events["publication_quality_tier"].isin(["premium", "standard"])].copy()
    if scoped.empty:
        return {"status": "NO_DATA"}
    flags = _target_path_flags(scoped, path, target_multiple=target_multiple)
    scoped = scoped.merge(flags, on="event_id", how="left")
    grouped = []
    for symbol, group in scoped.groupby(scoped["symbol"].astype(str), sort=False):
        grouped.append(
            {
                "symbol": str(symbol),
                "hit": group["target_hit_band"].fillna(False).to_numpy(dtype=bool),
                "first": group["target_first_band"].fillna(False).to_numpy(dtype=bool),
                "mfe": pd.to_numeric(group["mfe_pct"], errors="coerce").dropna().to_numpy(dtype=float),
                "mae": pd.to_numeric(group["mae_pct"], errors="coerce").dropna().to_numpy(dtype=float),
            }
        )
    symbols = np.arange(len(grouped))
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(reps):
        sampled = rng.choice(symbols, size=len(symbols), replace=True)
        hit_arrays = [grouped[int(i)]["hit"] for i in sampled]
        first_arrays = [grouped[int(i)]["first"] for i in sampled]
        mfe_arrays = [grouped[int(i)]["mfe"] for i in sampled if len(grouped[int(i)]["mfe"]) > 0]
        mae_arrays = [grouped[int(i)]["mae"] for i in sampled if len(grouped[int(i)]["mae"]) > 0]
        hit_values = np.concatenate(hit_arrays) if hit_arrays else np.array([], dtype=bool)
        first_values = np.concatenate(first_arrays) if first_arrays else np.array([], dtype=bool)
        mfe_values = np.concatenate(mfe_arrays) if mfe_arrays else np.array([], dtype=float)
        mae_values = np.concatenate(mae_arrays) if mae_arrays else np.array([], dtype=float)
        n = int(len(hit_values))
        hit = int(hit_values.sum())
        first = int(first_values.sum())
        med_mfe = round(float(np.nanmedian(mfe_values)), 2) if len(mfe_values) else None
        med_mae = round(float(np.nanmedian(mae_values)), 2) if len(mae_values) else None
        rows.append(
            {
                "target_hit_rate_pct": _pct(hit, n),
                "target_first_before_adverse_5pct_rate_pct": _pct(first, n),
                "mfe_mae_median_ratio": round(float(med_mfe) / max(float(med_mae), 1.0), 2) if med_mfe is not None and med_mae is not None else None,
            }
        )
    frame = pd.DataFrame(rows)
    out: dict[str, Any] = {"status": "OK", "reps": reps, "symbol_clusters": int(len(grouped))}
    for column in frame.columns:
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        out[column + "_ci"] = {
            "low": round(float(values.quantile(0.025)), 2),
            "high": round(float(values.quantile(0.975)), 2),
            "median": round(float(values.median()), 2),
        }
    return out


def _load_symbol_ohlcv(source_dir: Path, symbol: str) -> pd.DataFrame:
    candidates = sorted(source_dir.glob(f"{str(symbol).upper()}*.json"))
    exact = [path for path in candidates if symbol_from_path(path) == str(symbol).upper()]
    if not exact:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    df = load_market_stats_symbol(exact[0])
    for column in ("open", "high", "low", "close", "volume"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df.dropna(subset=["date", "open", "high", "low", "close"]).reset_index(drop=True)


def _window_for_event(df: pd.DataFrame, event: Mapping[str, Any], *, pre_bars: int = 20, post_bars: int = 40) -> tuple[pd.DataFrame, int]:
    start = pd.to_datetime(event.get("formation_start_date"), errors="coerce")
    breakout = pd.to_datetime(event.get("breakout_date"), errors="coerce")
    if pd.isna(start) or pd.isna(breakout):
        return df.iloc[:0].copy(), 0
    start_idx = int(df["date"].searchsorted(start, side="left"))
    breakout_idx = int(df["date"].searchsorted(breakout, side="left"))
    left = max(0, start_idx - pre_bars)
    right = min(len(df), breakout_idx + post_bars + 1)
    return df.iloc[left:right].copy().reset_index(drop=True), left


def _draw_event(ax: plt.Axes, df: pd.DataFrame, event: Mapping[str, Any], offset: int) -> None:
    if df.empty:
        ax.axis("off")
        return
    x = np.arange(len(df))
    for i, row in df.iterrows():
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        color = "#1b8a5a" if c >= o else "#c44e52"
        ax.vlines(i, l, h, color="#222222", linewidth=0.55, alpha=0.72)
        ax.add_patch(Rectangle((i - 0.3, min(o, c)), 0.6, max(abs(c - o), 1e-6), facecolor=color, edgecolor=color, linewidth=0.4, alpha=0.88))
    ax.plot(x, df["close"].to_numpy(), color="#222222", linewidth=0.8, alpha=0.25)

    formation_start = pd.to_datetime(event.get("formation_start_date"), errors="coerce")
    formation_end = pd.to_datetime(event.get("formation_end_date"), errors="coerce")
    breakout = pd.to_datetime(event.get("breakout_date"), errors="coerce")

    def ix(ts: pd.Timestamp) -> Optional[int]:
        if pd.isna(ts):
            return None
        j = int(df["date"].searchsorted(ts, side="left"))
        return min(max(j, 0), len(df) - 1)

    i0, i1, ib = ix(formation_start), ix(formation_end), ix(breakout)
    if i0 is not None and i1 is not None and i1 >= i0:
        ax.axvspan(i0, i1, color="#4C78A8", alpha=0.1)
    if ib is not None:
        ax.axvline(ib, color="#7A5195", linewidth=1.0)
    for price, color, style in ((event.get("target_price"), "#F58518", "--"), (event.get("breakout_price"), "#7A5195", ":")):
        try:
            ax.axhline(float(price), color=color, linestyle=style, linewidth=0.8, alpha=0.85)
        except (TypeError, ValueError):
            pass

    def draw_trendline(prefix: str, color: str) -> None:
        if i0 is None:
            return
        trend_end = max(v for v in (i1, ib, i0) if v is not None)
        formation_x = [i for i in range(len(df)) if i0 <= i <= trend_end]
        try:
            idx0 = int(event.get(f"flag_{prefix}_idx0"))
            price0 = float(event.get(f"flag_{prefix}_price0"))
            slope = float(event.get(f"flag_{prefix}_slope_per_bar"))
            y = [price0 + slope * ((i + offset) - idx0) for i in formation_x]
            ax.plot(formation_x, y, color=color, linewidth=0.9, alpha=0.95)
        except (TypeError, ValueError):
            return

    draw_trendline("upper", "#E45756")
    draw_trendline("lower", "#54A24B")
    ax.set_title(
        f"{event.get('symbol')} {event.get('breakout_date')} {event.get('variant')}\n"
        f"{event.get('publication_quality_tier')} score={event.get('pattern_quality_score')} "
        f"MFE/MAE={event.get('mfe_pct')}/{event.get('mae_pct')}",
        fontsize=8,
    )
    ax.grid(alpha=0.15)
    ax.tick_params(axis="both", labelsize=7)


def _visual_score_proxy(row: Mapping[str, Any]) -> tuple[float, str]:
    score = 3.0
    reasons: list[str] = []
    if float(row.get("pattern_quality_score") or 0) >= 90:
        score += 0.7
        reasons.append("high scanner score")
    if 0.2 <= float(row.get("compression_ratio") or 0) <= 0.72:
        score += 0.5
        reasons.append("clear convergence")
    if float(row.get("pole_move_pct") or 0) >= 14:
        score += 0.4
        reasons.append("visible pole")
    if float(row.get("pennant_to_pole_pct") or 999) <= 45:
        score += 0.3
        reasons.append("compact body")
    if bool(row.get("volume_confirmed")):
        score += 0.1
        reasons.append("breakout volume")
    return min(5.0, round(score, 1)), "; ".join(reasons)


def _visual_pack(events: pd.DataFrame, *, source_dir: Path, out_dir: Path, variant: str, sample_total: int, seed: int) -> dict[str, Any]:
    visual_dir = out_dir / "manual_visual_scoring"
    visual_dir.mkdir(parents=True, exist_ok=True)
    scoped = events[(events["variant"].astype(str) == variant) & (events["publication_quality_tier"].astype(str) == "premium")].copy()
    if scoped.empty:
        return {"status": "NO_PREMIUM_EVENTS"}
    rng = np.random.default_rng(seed)
    chosen = scoped.loc[rng.choice(scoped.index.to_numpy(), size=min(sample_total, len(scoped)), replace=False)].sort_values(["symbol", "breakout_date"]).reset_index(drop=True)
    cols = 2
    rows = int(math.ceil(len(chosen) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(12, max(4, rows * 3.0)), dpi=150)
    axes_array = np.atleast_1d(axes).reshape(rows, cols)
    for ax in axes_array.flat:
        ax.axis("off")
    cache: dict[str, pd.DataFrame] = {}
    scoring_rows: list[dict[str, Any]] = []
    for sample_no, (ax, (_, event)) in enumerate(zip(axes_array.flat, chosen.iterrows()), start=1):
        symbol = str(event.get("symbol"))
        if symbol not in cache:
            cache[symbol] = _load_symbol_ohlcv(source_dir, symbol)
        window, offset = _window_for_event(cache[symbol], event)
        ax.axis("on")
        _draw_event(ax, window, event.to_dict(), offset)
        ax.text(0.01, 0.98, f"#{sample_no}", transform=ax.transAxes, va="top", ha="left", fontsize=10, weight="bold", color="#7A5195")
        proxy_score, proxy_note = _visual_score_proxy(event.to_dict())
        scoring_rows.append(
            {
                "sample_no": sample_no,
                "event_id": event.get("event_id"),
                "symbol": symbol,
                "breakout_date": event.get("breakout_date"),
                "variant": event.get("variant"),
                "publication_quality_tier": event.get("publication_quality_tier"),
                "pattern_quality_score": event.get("pattern_quality_score"),
                "compression_ratio": event.get("compression_ratio"),
                "pennant_to_pole_pct": event.get("pennant_to_pole_pct"),
                "pole_move_pct": event.get("pole_move_pct"),
                "mfe_pct": event.get("mfe_pct"),
                "mae_pct": event.get("mae_pct"),
                "visual_score_proxy_1_to_5": proxy_score,
                "visual_proxy_note": proxy_note,
                "manual_visual_score_1_to_5": "",
                "manual_reviewer_note": "",
            }
        )
    fig.suptitle(f"{variant} premium visual validation pack", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.98])
    sheet_path = visual_dir / f"{variant}_premium_visual_contact_sheet.png"
    fig.savefig(sheet_path)
    plt.close(fig)
    scoring_csv = visual_dir / f"{variant}_premium_visual_scoring_template.csv"
    pd.DataFrame(scoring_rows).to_csv(scoring_csv, index=False)
    scores = [row["visual_score_proxy_1_to_5"] for row in scoring_rows]
    return {
        "status": "READY",
        "variant": variant,
        "sample_total": len(scoring_rows),
        "contact_sheet": str(sheet_path),
        "scoring_csv": str(scoring_csv),
        "visual_score_proxy_median": round(float(np.median(scores)), 2) if scores else None,
        "visual_score_proxy_pass_rate_pct": _pct(sum(1 for score in scores if score >= 4.0), len(scores)),
    }


def _render_markdown(summary: Mapping[str, Any]) -> str:
    bull = next((row for row in summary["target_table"] if row["variant"] == "bull_pennant" and row["tier"] == "premium+standard" and row["target_multiple"] == 0.5), {})
    bear = next((row for row in summary["target_table"] if row["variant"] == "bear_pennant" and row["tier"] == "premium+standard" and row["target_multiple"] == 0.5), {})
    return "\n".join(
        [
            "# Pennant Candidate Quality Audit",
            "",
            f"Status: {summary['status']}",
            "",
            "## Main Read",
            "",
            f"- Bull Pennant public-grade 0.5x: N={bull.get('n')}, hit={bull.get('target_hit_rate_pct')}%, target-first={bull.get('target_first_before_adverse_5pct_rate_pct')}%, failure={bull.get('failure_5pct_rate_pct')}%, MFE/MAE={bull.get('mfe_mae_median_ratio')}.",
            f"- Bear Pennant public-grade 0.5x: N={bear.get('n')}, hit={bear.get('target_hit_rate_pct')}%, target-first={bear.get('target_first_before_adverse_5pct_rate_pct')}%, failure={bear.get('failure_5pct_rate_pct')}%, MFE/MAE={bear.get('mfe_mae_median_ratio')}.",
            f"- Cluster bootstrap: {summary['cluster_bootstrap']}",
            f"- Visual pack: {summary['visual_pack']}",
            "",
            "## Decision",
            "",
            summary["decision"],
            "",
        ]
    )


def run_audit(
    *,
    events_csv: Path,
    path_csv: Path,
    source_dir: Path,
    out_dir: Path,
    sample_total: int = 30,
    seed: int = 20260521,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = _load_path(path_csv)
    events = _load_events(events_csv, path)
    target_table = _target_tables(events, path)
    robustness = _robustness_tables(events, path)
    bootstrap = _cluster_bootstrap(events, path, seed=seed)
    visual_pack = _visual_pack(events, source_dir=source_dir, out_dir=out_dir, variant="bull_pennant", sample_total=sample_total, seed=seed)
    bull_base = next(row for row in target_table if row["variant"] == "bull_pennant" and row["tier"] == "premium+standard" and row["target_multiple"] == 0.5)
    status = "PASS_CANDIDATE" if (bull_base["n"] >= 250 and (bull_base["mfe_mae_median_ratio"] or 0) >= 1.2 and (bull_base["target_first_before_adverse_5pct_rate_pct"] or 0) >= 30.0) else "REVIEW_REQUIRED"
    decision = (
        "Bull Pennant is eligible for the next source-aligned branch-calibration and visual-review round, but not yet a final public chapter."
        if status == "PASS_CANDIDATE"
        else "Pennant scanner needs branch tuning before it should enter chapter writing."
    )
    summary = {
        "audit_id": "pennant_candidate_quality_audit_v1",
        "status": status,
        "events_csv": str(events_csv),
        "path_csv": str(path_csv),
        "source_dir": str(source_dir),
        "event_count": int(len(events)),
        "variant_counts": events["variant"].value_counts().to_dict(),
        "tier_counts": events["publication_quality_tier"].value_counts().to_dict(),
        "target_table": target_table,
        "robustness": robustness,
        "cluster_bootstrap": bootstrap,
        "visual_pack": visual_pack,
        "decision": decision,
    }
    pd.DataFrame(target_table).to_csv(out_dir / "target_table.csv", index=False)
    pd.DataFrame(robustness["temporal_split"]).to_csv(out_dir / "temporal_split.csv", index=False)
    pd.DataFrame(robustness["cooldown"]).to_csv(out_dir / "cooldown_sensitivity.csv", index=False)
    pd.DataFrame(robustness["regime_liquidity"]).to_csv(out_dir / "regime_liquidity_interaction.csv", index=False)
    _write_json(out_dir / "pennant_candidate_quality_audit.json", summary)
    (out_dir / "pennant_candidate_quality_audit.md").write_text(_render_markdown(summary), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Pennant candidate quality.")
    parser.add_argument("--events", default=str(DEFAULT_EVENTS))
    parser.add_argument("--path", default=str(DEFAULT_PATH))
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--sample-total", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20260521)
    args = parser.parse_args()
    summary = run_audit(
        events_csv=Path(args.events),
        path_csv=Path(args.path),
        source_dir=Path(args.source_dir),
        out_dir=Path(args.out_dir),
        sample_total=int(args.sample_total),
        seed=int(args.seed),
    )
    print(json.dumps({"status": summary["status"], "event_count": summary["event_count"], "variant_counts": summary["variant_counts"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
