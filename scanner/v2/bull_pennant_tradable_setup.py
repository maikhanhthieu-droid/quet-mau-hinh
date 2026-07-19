"""Executable Bull Pennant setup backtest layer.

This module mirrors the Bull Flag KPI layer, but keeps Pennant-specific
geometry, scoring, target language, and release artifacts separate. The shared
execution engine is reused only for portfolio mechanics, costs, sizing,
walk-forward, and fragility diagnostics.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

import numpy as np
import pandas as pd

from scanner.run_pennant_candidate_quality_audit import _load_events, _load_path, _target_path_flags
from scanner.v2.bull_flag_tradable_setup import (
    ExecutionConfig,
    build_daily_mark_to_market_curve,
    evaluate_strategy,
    monte_carlo_trade_sequence,
    render_tradable_setup_report,
    run_calendar_oos_validation,
    run_cost_stress,
    run_fixed_strategy_walk_forward,
    run_walk_forward_validation,
    score_tradable_setup,
)
from scanner.v2.source_data import DEFAULT_SOURCE_DIR, load_market_stats_symbol, symbol_from_path


DEFAULT_EVENTS = Path("artifacts/scanner_v2/pennants/events.csv")
DEFAULT_PATH = Path("artifacts/scanner_v2/pennants/post_breakout_path.csv")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bull_pennants_tradable_setup")
FROZEN_RULE_VERSION = "bull_pennant_tradable_continuation@2026-05-21"
FROZEN_STRATEGY_ID = "bp_setup60_base050_stop7_max60_pos10_cap30"
FROZEN_RULE_NOTE = (
    "Bull Pennant executable KPI pass uses the source-grounded Pennant scanner, "
    "public-grade events only, a 0.5x pole-height local target, and the same "
    "execution/cost/walk-forward contract used for the Bull Flag KPI layer."
)


def _clip_score(value: Any) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return 0.0
    return round(max(0.0, min(100.0, float(numeric))), 2)


def _score_setup(row: Mapping[str, Any]) -> float:
    """Score only pre-breakout Pennant geometry and pole quality."""

    pattern_quality = _clip_score(row.get("pattern_quality_score"))
    compression = pd.to_numeric(pd.Series([row.get("compression_ratio")]), errors="coerce").iloc[0]
    pole_move = pd.to_numeric(pd.Series([row.get("pole_move_pct")]), errors="coerce").iloc[0]
    pennant_to_pole = pd.to_numeric(pd.Series([row.get("pennant_to_pole_pct")]), errors="coerce").iloc[0]

    compression_score = _clip_score((0.80 - float(compression if pd.notna(compression) else 0.80)) / 0.55 * 100.0)
    pole_score = _clip_score((float(pole_move if pd.notna(pole_move) else 0.0) - 10.0) / 25.0 * 100.0)
    body_score = _clip_score((65.0 - float(pennant_to_pole if pd.notna(pennant_to_pole) else 65.0)) / 45.0 * 100.0)
    return round(0.35 * pattern_quality + 0.25 * compression_score + 0.25 * pole_score + 0.15 * body_score, 2)


def _score_confirmation(row: Mapping[str, Any]) -> float:
    """Score breakout confirmation from volume and detector quality fields."""

    pattern_quality = _clip_score(row.get("pattern_quality_score"))
    volume_ratio = pd.to_numeric(pd.Series([row.get("breakout_volume_ratio")]), errors="coerce").iloc[0]
    volume_score = _clip_score((float(volume_ratio if pd.notna(volume_ratio) else 1.0) - 0.70) / 1.60 * 100.0)
    volume_confirmed = str(row.get("volume_confirmed")).strip().lower() in {"true", "1", "yes", "y"}
    volume_gate_score = 100.0 if volume_confirmed else 45.0
    return round(0.45 * pattern_quality + 0.35 * volume_score + 0.20 * volume_gate_score, 2)


def _score_followthrough(row: Mapping[str, Any]) -> float:
    """Diagnostic-only post-breakout score; never used for entry selection."""

    mfe = pd.to_numeric(pd.Series([row.get("mfe_pct")]), errors="coerce").iloc[0]
    mae = pd.to_numeric(pd.Series([row.get("mae_pct")]), errors="coerce").iloc[0]
    ratio = float(mfe if pd.notna(mfe) else 0.0) / max(float(mae if pd.notna(mae) else 0.0), 1.0)
    target_hit = bool(row.get("target_hit"))
    target_first = bool(row.get("target_first_before_adverse_5pct"))
    failure = bool(row.get("failure_5pct"))
    score = 45.0 + min(25.0, ratio * 10.0)
    if target_hit:
        score += 12.0
    if target_first:
        score += 13.0
    if failure:
        score -= 25.0
    return _clip_score(score)


def _assign_time_splits(events: pd.DataFrame) -> pd.DataFrame:
    out = events.sort_values(["breakout_date", "symbol"]).reset_index(drop=True).copy()
    n = len(out)
    train_end = int(np.floor(n * 0.60))
    validation_end = int(np.floor(n * 0.80))
    out["time_split"] = "holdout_20"
    if n:
        out.loc[: max(train_end - 1, 0), "time_split"] = "train_60"
        out.loc[train_end : max(validation_end - 1, train_end), "time_split"] = "validation_20"
    return out


def _source_paths_by_symbol(source_dir: Path) -> Dict[str, Path]:
    if not source_dir.exists():
        return {}
    return {symbol_from_path(path): path for path in sorted(source_dir.glob("*.json"))}


def _pre_breakout_regime_branch(ret20: float | None, ret60: float | None, volatility20: float | None) -> str:
    if ret20 is None and ret60 is None:
        return "unknown"
    r20 = float(ret20 or 0.0)
    r60 = float(ret60 or 0.0)
    vol20 = float(volatility20 or 0.0)
    if r20 >= 25.0 or r60 >= 60.0 or (r20 >= 18.0 and vol20 >= 18.0):
        return "overheated"
    if r60 >= 20.0 and r20 >= 5.0:
        return "strong_uptrend"
    if r60 >= 10.0 and r20 >= 0.0:
        return "fresh_uptrend"
    if r20 <= -5.0 or r60 <= -10.0:
        return "pullback_or_weak"
    return "choppy"


def _pre_breakout_features(row: Mapping[str, Any], source_paths: Mapping[str, Path]) -> Dict[str, Any]:
    symbol = str(row.get("symbol") or "").upper()
    path = source_paths.get(symbol)
    breakout_date = pd.to_datetime(row.get("breakout_date"), errors="coerce")
    if path is None or pd.isna(breakout_date):
        return {
            "pre_breakout_return_20d_pct": np.nan,
            "pre_breakout_return_60d_pct": np.nan,
            "pre_breakout_volatility_20d_pct": np.nan,
            "pre_breakout_zero_volume_rate_20d": np.nan,
            "pre_breakout_regime_branch": "unknown",
        }
    try:
        series = load_market_stats_symbol(path)
    except Exception:
        return {
            "pre_breakout_return_20d_pct": np.nan,
            "pre_breakout_return_60d_pct": np.nan,
            "pre_breakout_volatility_20d_pct": np.nan,
            "pre_breakout_zero_volume_rate_20d": np.nan,
            "pre_breakout_regime_branch": "unknown",
        }
    history = series[series["date"] < breakout_date].sort_values("date").tail(80).copy()
    if history.empty:
        return {
            "pre_breakout_return_20d_pct": np.nan,
            "pre_breakout_return_60d_pct": np.nan,
            "pre_breakout_volatility_20d_pct": np.nan,
            "pre_breakout_zero_volume_rate_20d": np.nan,
            "pre_breakout_regime_branch": "unknown",
        }
    closes = pd.to_numeric(history["close"], errors="coerce").dropna()
    ret20 = None
    ret60 = None
    if len(closes) >= 21 and float(closes.iloc[-21]) > 0:
        ret20 = (float(closes.iloc[-1]) / float(closes.iloc[-21]) - 1.0) * 100.0
    if len(closes) >= 61 and float(closes.iloc[-61]) > 0:
        ret60 = (float(closes.iloc[-1]) / float(closes.iloc[-61]) - 1.0) * 100.0
    daily_returns = closes.pct_change().dropna().tail(20)
    volatility20 = float(daily_returns.std(ddof=0) * np.sqrt(20) * 100.0) if len(daily_returns) >= 5 else None
    volumes = pd.to_numeric(history["volume"], errors="coerce").tail(20)
    zero_volume_rate = float((volumes <= 0).mean() * 100.0) if len(volumes) else np.nan
    return {
        "pre_breakout_return_20d_pct": round(ret20, 4) if ret20 is not None else np.nan,
        "pre_breakout_return_60d_pct": round(ret60, 4) if ret60 is not None else np.nan,
        "pre_breakout_volatility_20d_pct": round(volatility20, 4) if volatility20 is not None else np.nan,
        "pre_breakout_zero_volume_rate_20d": round(zero_volume_rate, 4) if not pd.isna(zero_volume_rate) else np.nan,
        "pre_breakout_regime_branch": _pre_breakout_regime_branch(ret20, ret60, volatility20),
    }


def _attach_pre_breakout_features(events: pd.DataFrame, source_dir: Path) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    source_paths = _source_paths_by_symbol(source_dir)
    rows = [_pre_breakout_features(row.to_dict(), source_paths) for _, row in events.iterrows()]
    features = pd.DataFrame(rows, index=events.index)
    return pd.concat([events.copy(), features], axis=1)


def _pole_exhaustion_branch(row: Mapping[str, Any]) -> str:
    pole_move = pd.to_numeric(pd.Series([row.get("pole_move_pct")]), errors="coerce").iloc[0]
    pole_bars = pd.to_numeric(pd.Series([row.get("pole_bars")]), errors="coerce").iloc[0]
    slope = pd.to_numeric(pd.Series([row.get("pole_slope_deg")]), errors="coerce").iloc[0]
    if pd.isna(pole_move):
        return "unknown"
    bars = max(float(pole_bars), 1.0) if pd.notna(pole_bars) else 1.0
    daily_move = float(pole_move) / bars
    slope_value = float(slope) if pd.notna(slope) else 0.0
    if float(pole_move) >= 55.0 or slope_value >= 82.0 or daily_move >= 3.5:
        return "exhausted_pole"
    if float(pole_move) >= 35.0 or slope_value >= 68.0 or daily_move >= 2.5:
        return "extended_pole"
    return "normal_pole"


def _attach_pole_exhaustion(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    out = events.copy()
    pole_move = pd.to_numeric(out.get("pole_move_pct"), errors="coerce")
    pole_bars = pd.to_numeric(out.get("pole_bars"), errors="coerce").replace(0, np.nan)
    out["pole_daily_move_pct"] = (pole_move / pole_bars).round(4)
    out["pole_exhaustion_branch"] = out.apply(lambda row: _pole_exhaustion_branch(row.to_dict()), axis=1)
    return out


def _attach_cluster_features(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty or "breakout_date" not in events.columns:
        return events.copy()
    out = events.copy()
    out["_breakout_ts"] = pd.to_datetime(out["breakout_date"], errors="coerce")
    ordered = out.dropna(subset=["_breakout_ts"]).sort_values(["_breakout_ts", "symbol"]).copy()
    prior10: Dict[Any, int] = {}
    prior20: Dict[Any, int] = {}
    dates: list[pd.Timestamp] = []
    for idx, row in ordered.iterrows():
        ts = row["_breakout_ts"]
        prior10[idx] = sum(1 for previous in dates if pd.Timedelta(days=0) < ts - previous <= pd.Timedelta(days=10))
        prior20[idx] = sum(1 for previous in dates if pd.Timedelta(days=0) < ts - previous <= pd.Timedelta(days=20))
        dates.append(ts)
    out["prior_pennant_cluster_count_10d"] = out.index.map(lambda idx: prior10.get(idx, 0)).astype(int)
    out["prior_pennant_cluster_count_20d"] = out.index.map(lambda idx: prior20.get(idx, 0)).astype(int)
    same_day = ordered.groupby("_breakout_ts")["event_id"].transform("count")
    out["same_day_pennant_count"] = out.index.map(dict(zip(ordered.index, same_day))).fillna(1).astype(int)
    out["cluster_noise_branch"] = np.where(
        out["prior_pennant_cluster_count_10d"] >= 20,
        "crowded",
        np.where(out["prior_pennant_cluster_count_10d"] >= 10, "elevated", "normal"),
    )
    return out.drop(columns=["_breakout_ts"], errors="ignore")


def load_bull_pennant_tradable_artifacts(
    events_csv: Path = DEFAULT_EVENTS,
    path_csv: Path = DEFAULT_PATH,
    *,
    target_multiple: float = 0.5,
    source_dir: Path = DEFAULT_SOURCE_DIR,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    path = _load_path(path_csv)
    events = _load_events(events_csv, path)
    scoped = events[
        (events["variant"].astype(str) == "bull_pennant")
        & events["publication_quality_tier"].isin(["premium", "standard"])
    ].copy()
    flags = _target_path_flags(scoped, path, target_multiple=target_multiple)
    scoped = scoped.merge(flags, on="event_id", how="left")
    scoped["target_hit"] = scoped["target_hit_band"].fillna(False).astype(bool)
    scoped["target_first_before_adverse_5pct"] = scoped["target_first_band"].fillna(False).astype(bool)
    scoped["days_to_target"] = pd.to_numeric(scoped["days_to_target_band"], errors="coerce")
    scoped["adtv20_value"] = pd.to_numeric(scoped.get("post_breakout_value20_median"), errors="coerce")
    scoped["setup_score"] = scoped.apply(lambda row: _score_setup(row.to_dict()), axis=1)
    scoped["confirmation_score"] = scoped.apply(lambda row: _score_confirmation(row.to_dict()), axis=1)
    scoped["followthrough_score"] = scoped.apply(lambda row: _score_followthrough(row.to_dict()), axis=1)
    scoped = _attach_pre_breakout_features(scoped, source_dir)
    scoped = _attach_pole_exhaustion(scoped)
    scoped = _attach_cluster_features(scoped)
    scoped = _assign_time_splits(scoped)
    event_ids = set(scoped["event_id"].astype(str))
    scoped_path = path[path["event_id"].astype(str).isin(event_ids)].copy()
    return scoped.reset_index(drop=True), scoped_path.reset_index(drop=True)


DEFAULT_STRATEGY_GRID: Sequence[ExecutionConfig] = (
    ExecutionConfig(strategy_id="bp_base050_stop5_max30_pos10", target_multiple=0.50, stop_loss_pct=5.0, max_holding_days=30, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_base050_stop7_max60_pos10", target_multiple=0.50, stop_loss_pct=7.0, max_holding_days=60, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id=FROZEN_STRATEGY_ID, target_multiple=0.50, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=60.0, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_setup65_base050_stop7_max60_pos10_cap30", target_multiple=0.50, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=65.0, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_setup70_base050_stop7_max60_pos10_cap30", target_multiple=0.50, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=70.0, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_setup60_conf55_base050_stop7_max60_pos10_cap30", target_multiple=0.50, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=60.0, min_confirmation_score=55.0, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_setup70_liq_mid_high_base050_stop5_max60_pos10_cap30", target_multiple=0.50, stop_loss_pct=5.0, max_holding_days=60, min_setup_score=70.0, allowed_liquidity_buckets=("mid", "high"), max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_delay3_setup60_base050_stop7_max60_pos10_cap30", target_multiple=0.50, stop_loss_pct=7.0, max_holding_days=60, entry_delay_bars=3, min_setup_score=60.0, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_delay3_setup60_risk_sized_base050_stop7_max60_pos10_cap30", target_multiple=0.50, stop_loss_pct=7.0, max_holding_days=60, entry_delay_bars=3, min_setup_score=60.0, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0, risk_sizing_enabled=True, risk_high_gap_threshold_pct=2.5, risk_high_mae_threshold_pct=5.0, risk_high_multiplier=0.35, risk_low_gap_threshold_pct=2.0, risk_low_mae_threshold_pct=2.5, risk_low_multiplier=1.35),
    ExecutionConfig(strategy_id="bp_delay4_setup60_risk_sized_base050_stop7_max60_pos10_cap30", target_multiple=0.50, stop_loss_pct=7.0, max_holding_days=60, entry_delay_bars=4, min_setup_score=60.0, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0, risk_sizing_enabled=True, risk_high_gap_threshold_pct=2.5, risk_high_mae_threshold_pct=5.0, risk_high_multiplier=0.35, risk_low_gap_threshold_pct=2.0, risk_low_mae_threshold_pct=2.5, risk_low_multiplier=1.35),
    ExecutionConfig(strategy_id="bp_stretch075_setup60_stop7_max60_pos10_cap30", target_multiple=0.75, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=60.0, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_branch_premium_stretch075_setup60_stop7_max60_pos10_cap30", target_multiple=0.75, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=60.0, allowed_publication_quality_tiers=("premium",), max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_branch_liq_mid_high_stretch075_setup60_stop7_max60_pos10_cap30", target_multiple=0.75, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=60.0, allowed_liquidity_buckets=("mid", "high"), max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_branch_liq_mid_high_risk_balanced_stretch075_setup60_stop7_max60_pos05_max20_cap30", target_multiple=0.75, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=60.0, allowed_liquidity_buckets=("mid", "high"), position_size_pct=0.05, max_positions=20, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_branch_liq_mid_high_risk_balanced_stretch075_setup60_stop8_max60_pos05_max20_cap30", target_multiple=0.75, stop_loss_pct=8.0, max_holding_days=60, min_setup_score=60.0, allowed_liquidity_buckets=("mid", "high"), position_size_pct=0.05, max_positions=20, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_branch_liq_mid_high_defensive_stretch075_setup60_stop7_max60_pos033_max30_cap30", target_multiple=0.75, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=60.0, allowed_liquidity_buckets=("mid", "high"), position_size_pct=0.033, max_positions=30, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_branch_liq_mid_high_defensive_stretch075_setup60_stop8_max60_pos033_max30_cap30", target_multiple=0.75, stop_loss_pct=8.0, max_holding_days=60, min_setup_score=60.0, allowed_liquidity_buckets=("mid", "high"), position_size_pct=0.033, max_positions=30, max_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_branch_compact_body_stretch075_setup60_stop7_max60_pos10_cap30", target_multiple=0.75, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=60.0, max_pennant_to_pole_pct=35.0, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_branch_tight_compression_stretch075_setup60_stop7_max60_pos10_cap30", target_multiple=0.75, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=60.0, max_compression_ratio=0.45, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_branch_strong_pole_stretch075_setup60_stop7_max60_pos10_cap30", target_multiple=0.75, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=60.0, min_pole_move_pct=20.0, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_branch_cooldown120_stretch075_setup60_stop7_max60_pos10_cap30", target_multiple=0.75, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=60.0, cooldown_days=120, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_branch_premium_liq_mid_high_stretch075_setup60_stop7_max60_pos10_cap30", target_multiple=0.75, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=60.0, allowed_publication_quality_tiers=("premium",), allowed_liquidity_buckets=("mid", "high"), max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_branch_prebreakout_uptrend_liq_mid_high_defensive_stretch075_setup60_stop7_max60_pos033_max30_cap30", target_multiple=0.75, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=60.0, allowed_liquidity_buckets=("mid", "high"), allowed_pre_breakout_regime_branches=("fresh_uptrend", "strong_uptrend"), position_size_pct=0.033, max_positions=30, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_branch_no_exhausted_pole_liq_mid_high_defensive_stretch075_setup60_stop7_max60_pos033_max30_cap30", target_multiple=0.75, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=60.0, allowed_liquidity_buckets=("mid", "high"), excluded_pole_exhaustion_branches=("exhausted_pole",), position_size_pct=0.033, max_positions=30, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_branch_exclude_extended_pole_liq_mid_high_defensive_stretch075_setup60_stop7_max60_pos033_max30_cap30", target_multiple=0.75, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=60.0, allowed_liquidity_buckets=("mid", "high"), excluded_pole_exhaustion_branches=("extended_pole",), position_size_pct=0.033, max_positions=30, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_branch_exclude_extended_pole_liq_mid_high_defensive_stretch075_setup60_stop8_max60_pos033_max30_cap30", target_multiple=0.75, stop_loss_pct=8.0, max_holding_days=60, min_setup_score=60.0, allowed_liquidity_buckets=("mid", "high"), excluded_pole_exhaustion_branches=("extended_pole",), position_size_pct=0.033, max_positions=30, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_branch_exclude_extended_low_noise_liq_mid_high_defensive_stretch075_setup60_stop8_max60_pos033_max30_cap30", target_multiple=0.75, stop_loss_pct=8.0, max_holding_days=60, min_setup_score=60.0, allowed_liquidity_buckets=("mid", "high"), excluded_pole_exhaustion_branches=("extended_pole",), max_prior_pennant_cluster_count_10d=8, position_size_pct=0.033, max_positions=30, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_branch_low_cluster_liq_mid_high_defensive_stretch075_setup60_stop7_max60_pos033_max30_cap30", target_multiple=0.75, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=60.0, allowed_liquidity_buckets=("mid", "high"), max_prior_pennant_cluster_count_10d=15, position_size_pct=0.033, max_positions=30, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_branch_low_vol_prebreakout_liq_mid_high_defensive_stretch075_setup60_stop7_max60_pos033_max30_cap30", target_multiple=0.75, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=60.0, allowed_liquidity_buckets=("mid", "high"), max_pre_breakout_volatility_20d_pct=16.0, position_size_pct=0.033, max_positions=30, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
    ExecutionConfig(strategy_id="bp_branch_clean_context_liq_mid_high_defensive_stretch075_setup60_stop7_max60_pos033_max30_cap30", target_multiple=0.75, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=60.0, allowed_liquidity_buckets=("mid", "high"), allowed_pre_breakout_regime_branches=("fresh_uptrend", "strong_uptrend"), excluded_pole_exhaustion_branches=("exhausted_pole",), max_prior_pennant_cluster_count_10d=15, max_pre_breakout_volatility_20d_pct=18.0, position_size_pct=0.033, max_positions=30, max_adtv_participation_pct=30.0, target_adtv_participation_pct=10.0),
)


def _score_between(value: Any, low: float, high: float) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return 0.0
    if high == low:
        return 100.0 if float(numeric) >= high else 0.0
    return max(0.0, min(100.0, (float(numeric) - low) / (high - low) * 100.0))


def _pennant_pre_holdout_utility(row: Mapping[str, Any]) -> float:
    """Pennant selection utility using train/validation and capacity only.

    Holdout and walk-forward remain diagnostics. Compared with Bull Flag,
    Pennant receives a larger drawdown/capacity weight because the candidate
    sample is broad and noisy; this avoids selecting a high-return branch that
    reaches the same score by accepting unstable fold risk.
    """

    validation_return = _score_between(row.get("validation_total_return_pct"), 0.0, 8.0)
    validation_drawdown = _score_between(row.get("validation_max_drawdown_pct"), -10.0, -2.0)
    validation_trades = _score_between(row.get("validation_trades"), 20.0, 100.0)
    train_return = _score_between(row.get("train_total_return_pct"), 0.0, 20.0)
    train_drawdown = _score_between(row.get("train_max_drawdown_pct"), -16.0, -4.0)
    capacity = _score_between(5.0 - float(row.get("median_adtv_participation_pct") or 5.0), 0.0, 5.0)
    skipped = _score_between(120.0 - float(row.get("skipped") or 120.0), 0.0, 120.0)
    return float(
        0.24 * validation_return
        + 0.20 * validation_drawdown
        + 0.12 * validation_trades
        + 0.16 * train_return
        + 0.12 * train_drawdown
        + 0.10 * capacity
        + 0.06 * skipped
    )


def select_bull_pennant_strategy(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    candidates = [dict(row) for row in rows]
    if not candidates:
        return {"status": "no_strategy_rows"}
    passing = [
        row
        for row in candidates
        if int(row.get("validation_trades") or 0) >= 12
        and int(row.get("holdout_trades") or 0) >= 12
        and float(row.get("validation_total_return_pct") or -999.0) > 0.0
        and float(row.get("validation_max_drawdown_pct") or -999.0) >= -20.0
        and float(row.get("median_adtv_participation_pct") or 999.0) <= 5.0
    ]
    pool = passing if passing else candidates
    selected = max(pool, key=_pennant_pre_holdout_utility)
    return {
        "status": "selected_tradable_setup" if passing else "no_strategy_passed_validation_gate",
        "selection_basis": "bull_pennant_validation_gate_then_train_validation_risk_capacity_utility_holdout_and_walk_forward_reported_out_of_sample",
        "selected_strategy_id": selected.get("strategy_id"),
        "selected_metrics": selected,
        "passing_count": len(passing),
        "candidate_count": len(candidates),
    }


def frozen_rule_contract(config: ExecutionConfig) -> Dict[str, Any]:
    return {
        "rule_version": FROZEN_RULE_VERSION,
        "note": FROZEN_RULE_NOTE,
        "selection_policy": "same KPI policy as Bull Flag: validation gate first, holdout and walk-forward reported out of sample",
        "entry_rule": "long at configured post-breakout open; delayed-entry strategies wait before entry",
        "exit_rule": "first target, stop, or max holding day; same-bar target/stop uses stop-first",
        "target_rule": f"{config.target_multiple}x local Bull Pennant pole-height target",
        "stop_loss_pct": config.stop_loss_pct,
        "max_holding_days": config.max_holding_days,
        "sizing": {
            "position_size_pct": config.position_size_pct,
            "max_positions": config.max_positions,
            "max_adtv_participation_pct": config.max_adtv_participation_pct,
            "target_adtv_participation_pct": config.target_adtv_participation_pct,
            "max_entry_bar_participation_pct": config.max_entry_bar_participation_pct,
        },
        "execution_filters": {
            "min_setup_score": config.min_setup_score,
            "min_confirmation_score": config.min_confirmation_score,
            "allowed_liquidity_buckets": config.allowed_liquidity_buckets,
            "allowed_market_regimes": config.allowed_market_regimes,
            "allowed_publication_quality_tiers": config.allowed_publication_quality_tiers,
            "min_pole_move_pct": config.min_pole_move_pct,
            "max_pennant_to_pole_pct": config.max_pennant_to_pole_pct,
            "max_compression_ratio": config.max_compression_ratio,
            "min_breakout_volume_ratio": config.min_breakout_volume_ratio,
            "require_volume_confirmed": config.require_volume_confirmed,
            "allowed_pre_breakout_regime_branches": config.allowed_pre_breakout_regime_branches,
            "excluded_pole_exhaustion_branches": config.excluded_pole_exhaustion_branches,
            "max_prior_pennant_cluster_count_10d": config.max_prior_pennant_cluster_count_10d,
            "max_pre_breakout_volatility_20d_pct": config.max_pre_breakout_volatility_20d_pct,
            "cooldown_days": config.cooldown_days,
        },
        "cost_model": {
            "commission_bps_per_side": config.commission_bps_per_side,
            "slippage_bps_per_side": config.slippage_bps_per_side,
            "sell_tax_bps": config.sell_tax_bps,
        },
        "claim_boundary": "Executable research layer only; not a production trading system.",
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def run_bull_pennant_tradable_backtest(
    *,
    events_csv: Path = DEFAULT_EVENTS,
    path_csv: Path = DEFAULT_PATH,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    out_dir: Path = DEFAULT_OUT_DIR,
    configs: Sequence[ExecutionConfig] = DEFAULT_STRATEGY_GRID,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    events, path = load_bull_pennant_tradable_artifacts(events_csv, path_csv, source_dir=source_dir)
    grid_rows: List[Dict[str, Any]] = []
    trades_by_strategy: Dict[str, pd.DataFrame] = {}
    curves_by_strategy: Dict[str, pd.DataFrame] = {}
    for config in configs:
        summary, trades, curve = evaluate_strategy(events, path, config)
        grid_rows.append(summary)
        trades_by_strategy[config.strategy_id] = trades
        curves_by_strategy[config.strategy_id] = curve

    selection = select_bull_pennant_strategy(grid_rows)
    selected_id = str(selection.get("selected_strategy_id") or "")
    config_by_id = {config.strategy_id: config for config in configs}
    selected_config = config_by_id.get(selected_id, configs[0] if configs else ExecutionConfig(strategy_id="fallback"))
    selected_trades = trades_by_strategy.get(selected_id, pd.DataFrame())
    selected_curve = curves_by_strategy.get(selected_id, pd.DataFrame())
    walk_forward_folds, walk_forward_trades, walk_forward_summary = run_fixed_strategy_walk_forward(events, path, selected_config)
    # Pennant public-grade sample is much deeper than the Bull Flag release
    # sample. Keep the same adaptive-walk-forward evidence type, but use larger
    # chronological blocks so the run remains practical and each test fold is
    # still event-rich.
    adaptive_walk_forward_folds, adaptive_walk_forward_trades, adaptive_walk_forward_summary = run_walk_forward_validation(
        events,
        path,
        configs,
        min_train_events=100,
        test_events=50,
    )
    calendar_oos, calendar_oos_summary = run_calendar_oos_validation(events, path, selected_config)
    cost_stress, cost_stress_summary = run_cost_stress(events, path, selected_config)
    monte_carlo_sims, monte_carlo_summary = monte_carlo_trade_sequence(selected_trades, selected_config, iterations=1_000)
    daily_mtm_curve, daily_mtm_summary = build_daily_mark_to_market_curve(selected_trades, path, selected_config)
    scorecard = score_tradable_setup(selection, walk_forward_summary, cost_stress_summary, monte_carlo_summary)
    rule_contract = frozen_rule_contract(selected_config)

    selection = dict(selection)
    selection["frozen_rule_contract"] = rule_contract
    selection["walk_forward_summary"] = walk_forward_summary
    selection["adaptive_walk_forward_summary"] = adaptive_walk_forward_summary
    selection["calendar_oos_summary"] = calendar_oos_summary
    selection["cost_stress_summary"] = cost_stress_summary
    selection["monte_carlo_summary"] = monte_carlo_summary
    selection["daily_mark_to_market_summary"] = daily_mtm_summary
    selection["tradable_scorecard"] = scorecard
    selection["source_scope"] = {
        "events_csv": str(events_csv),
        "path_csv": str(path_csv),
        "source_dir": str(source_dir),
        "public_grade_events": int(len(events)),
        "public_grade_symbols": int(events["symbol"].nunique()) if "symbol" in events.columns else None,
        "variant": "bull_pennant",
    }

    paths = {
        "rule_contract_json": out_dir / "bull_pennant_tradable_frozen_rule_contract.json",
        "strategy_grid_csv": out_dir / "bull_pennant_tradable_strategy_grid.csv",
        "selected_strategy_json": out_dir / "bull_pennant_tradable_selected_strategy.json",
        "selected_trades_csv": out_dir / "bull_pennant_tradable_trades.csv",
        "equity_curve_csv": out_dir / "bull_pennant_tradable_equity_curve.csv",
        "daily_mtm_curve_csv": out_dir / "bull_pennant_tradable_daily_mtm_curve.csv",
        "walk_forward_folds_csv": out_dir / "bull_pennant_tradable_walk_forward_folds.csv",
        "walk_forward_trades_csv": out_dir / "bull_pennant_tradable_walk_forward_trades.csv",
        "adaptive_walk_forward_folds_csv": out_dir / "bull_pennant_tradable_adaptive_walk_forward_folds.csv",
        "adaptive_walk_forward_trades_csv": out_dir / "bull_pennant_tradable_adaptive_walk_forward_trades.csv",
        "calendar_oos_csv": out_dir / "bull_pennant_tradable_calendar_oos.csv",
        "cost_stress_csv": out_dir / "bull_pennant_tradable_cost_stress.csv",
        "monte_carlo_csv": out_dir / "bull_pennant_tradable_monte_carlo.csv",
        "scorecard_json": out_dir / "bull_pennant_tradable_scorecard.json",
        "report_md": out_dir / "bull_pennant_tradable_backtest_report.md",
    }
    pd.DataFrame(grid_rows).to_csv(paths["strategy_grid_csv"], index=False)
    selected_trades.to_csv(paths["selected_trades_csv"], index=False)
    selected_curve.to_csv(paths["equity_curve_csv"], index=False)
    daily_mtm_curve.to_csv(paths["daily_mtm_curve_csv"], index=False)
    walk_forward_folds.to_csv(paths["walk_forward_folds_csv"], index=False)
    walk_forward_trades.to_csv(paths["walk_forward_trades_csv"], index=False)
    adaptive_walk_forward_folds.to_csv(paths["adaptive_walk_forward_folds_csv"], index=False)
    adaptive_walk_forward_trades.to_csv(paths["adaptive_walk_forward_trades_csv"], index=False)
    calendar_oos.to_csv(paths["calendar_oos_csv"], index=False)
    cost_stress.to_csv(paths["cost_stress_csv"], index=False)
    monte_carlo_sims.to_csv(paths["monte_carlo_csv"], index=False)
    _write_json(paths["rule_contract_json"], rule_contract)
    _write_json(paths["selected_strategy_json"], selection)
    _write_json(paths["scorecard_json"], scorecard)
    report = render_tradable_setup_report(
        selection,
        grid_rows,
        walk_forward_summary=walk_forward_summary,
        cost_stress_summary=cost_stress_summary,
        monte_carlo_summary=monte_carlo_summary,
        calendar_oos_summary=calendar_oos_summary,
        daily_mtm_summary=daily_mtm_summary,
        scorecard=scorecard,
    ).replace("Bull Flag V2 Tradable Setup Backtest", "Bull Pennant Tradable Setup Backtest").replace(
        "Bull Flag V2 pilot", "Bull Pennant public-grade candidate"
    )
    paths["report_md"].write_text(report, encoding="utf-8")
    return paths


__all__ = [
    "DEFAULT_EVENTS",
    "DEFAULT_OUT_DIR",
    "DEFAULT_PATH",
    "DEFAULT_SOURCE_DIR",
    "DEFAULT_STRATEGY_GRID",
    "FROZEN_STRATEGY_ID",
    "ExecutionConfig",
    "frozen_rule_contract",
    "load_bull_pennant_tradable_artifacts",
    "run_bull_pennant_tradable_backtest",
]
