"""Executable Bull Flag setup backtest layer.

This module intentionally sits above the Bull Flag reference scanner. The
scanner asks whether the pattern has useful conditional post-breakout behavior;
this layer asks whether a concrete long-only execution rule remains viable
after entry, exit, costs, sizing, capacity, and chronological OOS splits.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd


DEFAULT_PROFILE_ID = "bull_flag_v2_split_stable_recovery"
DEFAULT_ADAPTIVE_GRID_DIR = Path("artifacts/scanner_v2/bull_flags_adaptive_grid")
DEFAULT_PROFILE_DIR = DEFAULT_ADAPTIVE_GRID_DIR / "scans" / DEFAULT_PROFILE_ID
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bull_flags_tradable_setup")
FROZEN_RULE_VERSION = "bull_flag_tradable_risk_sized_continuation@2026-05-18"
FROZEN_STRATEGY_ID = "bf_v2_setup60_context_guard_delay3_risk_sized_base046_stop7_max60_pos10_cap30"
FROZEN_RULE_NOTE = (
    "Frozen after the Bull Flag tradable research pass: avoid overextended bear-regime "
    "high-liquidity setups, prefer delayed entry over immediate post-breakout entry, "
    "evaluate only the reliable known-regime research window, and scale position size "
    "by entry-time continuation quality."
)


@dataclass(frozen=True)
class ExecutionConfig:
    strategy_id: str
    target_multiple: float = 0.46
    stop_loss_pct: float = 5.0
    max_holding_days: int = 60
    position_size_pct: float = 0.10
    max_positions: int = 10
    initial_equity: float = 1_000_000_000.0
    commission_bps_per_side: float = 15.0
    slippage_bps_per_side: float = 10.0
    sell_tax_bps: float = 10.0
    same_bar_policy: str = "stop_first"
    max_adtv_participation_pct: float = 20.0
    target_adtv_participation_pct: Optional[float] = None
    adtv_unit_multiplier: float = 1_000.0
    value_unit_multiplier: float = 1_000.0
    min_position_notional: float = 0.0
    max_single_order_notional: Optional[float] = None
    max_entry_bar_participation_pct: float = 30.0
    entry_delay_bars: int = 1
    min_pre_entry_close_return_pct: Optional[float] = None
    min_pre_entry_mfe_pct: Optional[float] = None
    max_pre_entry_mae_pct: Optional[float] = None
    min_pre_entry_positive_close_share: Optional[float] = None
    min_pre_entry_gain_capture_pct: Optional[float] = None
    min_pre_entry_continuation_score: Optional[float] = None
    max_entry_gap_pct: Optional[float] = None
    risk_sizing_enabled: bool = False
    risk_high_gap_threshold_pct: float = 3.0
    risk_high_mae_threshold_pct: float = 4.0
    risk_high_continuation_score_threshold: Optional[float] = None
    risk_high_multiplier: float = 0.50
    risk_low_gap_threshold_pct: float = 1.5
    risk_low_mae_threshold_pct: float = 2.0
    risk_low_continuation_score_threshold: Optional[float] = None
    risk_low_multiplier: float = 1.20
    min_setup_score: Optional[float] = None
    min_confirmation_score: Optional[float] = None
    min_breakout_date: Optional[str] = None
    max_breakout_date: Optional[str] = None
    allowed_liquidity_buckets: Optional[tuple[str, ...]] = None
    allowed_market_regimes: Optional[tuple[str, ...]] = None
    allowed_publication_quality_tiers: Optional[tuple[str, ...]] = None
    min_pole_move_pct: Optional[float] = None
    max_pennant_to_pole_pct: Optional[float] = None
    max_compression_ratio: Optional[float] = None
    min_breakout_volume_ratio: Optional[float] = None
    require_volume_confirmed: bool = False
    allowed_pre_breakout_regime_branches: Optional[tuple[str, ...]] = None
    excluded_pole_exhaustion_branches: Optional[tuple[str, ...]] = None
    max_prior_pennant_cluster_count_10d: Optional[int] = None
    max_pre_breakout_volatility_20d_pct: Optional[float] = None
    cooldown_days: Optional[int] = None
    exclude_bear_high_liquidity_setup_score_min: Optional[float] = None
    low_liquidity_extra_slippage_bps: float = 0.0
    mid_liquidity_extra_slippage_bps: float = 0.0
    high_liquidity_extra_slippage_bps: float = 0.0
    gap_slippage_threshold_pct: float = 3.0
    gap_extra_slippage_bps: float = 0.0
    limit_range_threshold_pct: float = 6.5
    limit_extra_slippage_bps: float = 0.0


DEFAULT_STRATEGY_GRID: Sequence[ExecutionConfig] = (
    ExecutionConfig(strategy_id="bf_v2_base046_stop5_max20_pos10", target_multiple=0.46, stop_loss_pct=5.0, max_holding_days=20),
    ExecutionConfig(strategy_id="bf_v2_base046_stop5_max60_pos10", target_multiple=0.46, stop_loss_pct=5.0, max_holding_days=60),
    ExecutionConfig(strategy_id="bf_v2_base046_stop7_max60_pos10", target_multiple=0.46, stop_loss_pct=7.0, max_holding_days=60),
    ExecutionConfig(strategy_id="bf_v2_stretch075_stop5_max60_pos10", target_multiple=0.75, stop_loss_pct=5.0, max_holding_days=60),
    ExecutionConfig(strategy_id="bf_v2_setup65_base046_stop7_max60_pos10", target_multiple=0.46, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=65.0),
    ExecutionConfig(strategy_id="bf_v2_setup70_base046_stop7_max60_pos10", target_multiple=0.46, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=70.0),
    ExecutionConfig(strategy_id="bf_v2_setup75_base046_stop7_max60_pos10", target_multiple=0.46, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=75.0),
    ExecutionConfig(strategy_id="bf_v2_setup70_conf50_base046_stop7_max60_pos10", target_multiple=0.46, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=70.0, min_confirmation_score=50.0),
    ExecutionConfig(strategy_id="bf_v2_setup70_liq_mid_high_base046_stop7_max60_pos10", target_multiple=0.46, stop_loss_pct=7.0, max_holding_days=60, min_setup_score=70.0, allowed_liquidity_buckets=("mid", "high")),
    ExecutionConfig(strategy_id="bf_v2_setup70_base046_stop7_max60_pos12_max8_cap30", target_multiple=0.46, stop_loss_pct=7.0, max_holding_days=60, position_size_pct=0.125, max_positions=8, max_adtv_participation_pct=30.0, min_setup_score=70.0),
    ExecutionConfig(strategy_id="bf_v2_setup70_base046_stop7_max60_pos15_max6_cap30", target_multiple=0.46, stop_loss_pct=7.0, max_holding_days=60, position_size_pct=0.15, max_positions=6, max_adtv_participation_pct=30.0, min_setup_score=70.0),
    ExecutionConfig(
        strategy_id="bf_v2_context_guard_target065_stop7_max60_pos10_cap30",
        target_multiple=0.65,
        stop_loss_pct=7.0,
        max_holding_days=60,
        max_adtv_participation_pct=30.0,
        min_setup_score=65.0,
        exclude_bear_high_liquidity_setup_score_min=80.0,
    ),
    ExecutionConfig(
        strategy_id="bf_v2_context_guard_delay3_base046_stop7_max60_pos10_cap30",
        target_multiple=0.46,
        stop_loss_pct=7.0,
        max_holding_days=60,
        max_adtv_participation_pct=30.0,
        entry_delay_bars=3,
        min_setup_score=65.0,
        exclude_bear_high_liquidity_setup_score_min=80.0,
    ),
    ExecutionConfig(
        strategy_id="bf_v2_context_guard_delay3_risk_reduce_base046_stop7_max60_pos10_cap30",
        target_multiple=0.46,
        stop_loss_pct=7.0,
        max_holding_days=60,
        max_adtv_participation_pct=30.0,
        entry_delay_bars=3,
        min_setup_score=65.0,
        exclude_bear_high_liquidity_setup_score_min=80.0,
        risk_sizing_enabled=True,
        risk_high_multiplier=0.50,
        risk_low_multiplier=1.0,
    ),
    ExecutionConfig(
        strategy_id="bf_v2_context_guard_delay3_risk_sized_base046_stop7_max60_pos10_cap30",
        target_multiple=0.46,
        stop_loss_pct=7.0,
        max_holding_days=60,
        max_adtv_participation_pct=30.0,
        entry_delay_bars=3,
        min_setup_score=65.0,
        exclude_bear_high_liquidity_setup_score_min=80.0,
        risk_sizing_enabled=True,
    ),
    ExecutionConfig(
        strategy_id="bf_v2_setup60_context_guard_delay3_risk_sized_base046_stop7_max60_pos10_cap30",
        target_multiple=0.46,
        stop_loss_pct=7.0,
        max_holding_days=60,
        max_adtv_participation_pct=30.0,
        target_adtv_participation_pct=10.0,
        entry_delay_bars=3,
        min_setup_score=60.0,
        min_breakout_date="2019-01-01",
        allowed_market_regimes=("bull", "bear"),
        exclude_bear_high_liquidity_setup_score_min=80.0,
        risk_sizing_enabled=True,
        risk_high_gap_threshold_pct=2.5,
        risk_high_mae_threshold_pct=5.0,
        risk_high_multiplier=0.35,
        risk_low_gap_threshold_pct=2.0,
        risk_low_mae_threshold_pct=2.5,
        risk_low_multiplier=1.35,
    ),
    ExecutionConfig(
        strategy_id="bf_v2_setup60_stage4_confirm50_risk_sized_base046_stop7_max60_pos10_cap30",
        target_multiple=0.46,
        stop_loss_pct=7.0,
        max_holding_days=60,
        max_adtv_participation_pct=30.0,
        entry_delay_bars=4,
        min_setup_score=60.0,
        exclude_bear_high_liquidity_setup_score_min=80.0,
        min_pre_entry_close_return_pct=0.0,
        max_pre_entry_mae_pct=4.0,
        min_pre_entry_positive_close_share=0.50,
        min_pre_entry_gain_capture_pct=35.0,
        min_pre_entry_continuation_score=50.0,
        risk_sizing_enabled=True,
        risk_high_gap_threshold_pct=2.5,
        risk_high_mae_threshold_pct=5.0,
        risk_high_multiplier=0.35,
        risk_low_gap_threshold_pct=2.0,
        risk_low_mae_threshold_pct=2.5,
        risk_low_multiplier=1.35,
    ),
    ExecutionConfig(
        strategy_id="bf_v2_setup60_stage4_quality_sized_base046_stop7_max60_pos10_cap30",
        target_multiple=0.46,
        stop_loss_pct=7.0,
        max_holding_days=60,
        max_adtv_participation_pct=30.0,
        entry_delay_bars=4,
        min_setup_score=60.0,
        exclude_bear_high_liquidity_setup_score_min=80.0,
        risk_sizing_enabled=True,
        risk_high_gap_threshold_pct=2.5,
        risk_high_mae_threshold_pct=5.0,
        risk_high_continuation_score_threshold=45.0,
        risk_high_multiplier=0.35,
        risk_low_gap_threshold_pct=2.0,
        risk_low_mae_threshold_pct=2.5,
        risk_low_continuation_score_threshold=60.0,
        risk_low_multiplier=1.35,
    ),
    ExecutionConfig(
        strategy_id="bf_v2_setup60_stage5_confirm55_risk_sized_base046_stop7_max60_pos10_cap30",
        target_multiple=0.46,
        stop_loss_pct=7.0,
        max_holding_days=60,
        max_adtv_participation_pct=30.0,
        entry_delay_bars=5,
        min_setup_score=60.0,
        exclude_bear_high_liquidity_setup_score_min=80.0,
        min_pre_entry_close_return_pct=0.25,
        max_pre_entry_mae_pct=4.0,
        min_pre_entry_positive_close_share=0.60,
        min_pre_entry_gain_capture_pct=40.0,
        min_pre_entry_continuation_score=55.0,
        risk_sizing_enabled=True,
        risk_high_gap_threshold_pct=2.5,
        risk_high_mae_threshold_pct=5.0,
        risk_high_multiplier=0.35,
        risk_low_gap_threshold_pct=2.0,
        risk_low_mae_threshold_pct=2.5,
        risk_low_multiplier=1.35,
    ),
    ExecutionConfig(
        strategy_id="bf_v2_setup60_stage5_quality_sized_base046_stop7_max60_pos10_cap30",
        target_multiple=0.46,
        stop_loss_pct=7.0,
        max_holding_days=60,
        max_adtv_participation_pct=30.0,
        entry_delay_bars=5,
        min_setup_score=60.0,
        exclude_bear_high_liquidity_setup_score_min=80.0,
        risk_sizing_enabled=True,
        risk_high_gap_threshold_pct=2.5,
        risk_high_mae_threshold_pct=5.0,
        risk_high_continuation_score_threshold=45.0,
        risk_high_multiplier=0.35,
        risk_low_gap_threshold_pct=2.0,
        risk_low_mae_threshold_pct=2.5,
        risk_low_continuation_score_threshold=60.0,
        risk_low_multiplier=1.35,
    ),
    ExecutionConfig(
        strategy_id="bf_v2_setup60_stage6_confirm60_risk_sized_base046_stop7_max60_pos10_cap30",
        target_multiple=0.46,
        stop_loss_pct=7.0,
        max_holding_days=60,
        max_adtv_participation_pct=30.0,
        entry_delay_bars=6,
        min_setup_score=60.0,
        exclude_bear_high_liquidity_setup_score_min=80.0,
        min_pre_entry_close_return_pct=0.50,
        max_pre_entry_mae_pct=4.0,
        min_pre_entry_positive_close_share=0.67,
        min_pre_entry_gain_capture_pct=45.0,
        min_pre_entry_continuation_score=60.0,
        risk_sizing_enabled=True,
        risk_high_gap_threshold_pct=2.5,
        risk_high_mae_threshold_pct=5.0,
        risk_high_multiplier=0.35,
        risk_low_gap_threshold_pct=2.0,
        risk_low_mae_threshold_pct=2.5,
        risk_low_multiplier=1.35,
    ),
)


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def load_bull_flag_v2_artifacts(profile_dir: Path = DEFAULT_PROFILE_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    events = _read_csv(profile_dir / "events.csv")
    path = _read_csv(profile_dir / "post_breakout_path.csv")
    for frame in (events, path):
        if not frame.empty and "event_id" not in frame.columns and "detection_id" in frame.columns:
            frame["event_id"] = frame["detection_id"]
    for col in ("breakout_price", "target_dist_pct", "b_exec_price"):
        if col in events.columns:
            events[col] = pd.to_numeric(events[col], errors="coerce")
    for col in ("bar_after_breakout", "open", "high", "low", "close", "volume"):
        if col in path.columns:
            path[col] = pd.to_numeric(path[col], errors="coerce")
    return events, path


def frozen_rule_contract(config: ExecutionConfig, *, profile_id: str = DEFAULT_PROFILE_ID) -> Dict[str, Any]:
    return {
        "rule_version": FROZEN_RULE_VERSION,
        "profile_id": profile_id,
        "note": FROZEN_RULE_NOTE,
        "selection_policy": "strategy must pass validation gates, then is ranked by train+validation pre-holdout utility; holdout and walk-forward remain OOS diagnostics",
        "entry_rule": "long at the configured post-breakout open; entry_delay_bars=1 means next available open",
        "exit_rule": "first target, stop, or max holding day; same-bar target/stop uses stop-first",
        "target_rule": f"{config.target_multiple}x local Bull Flag pole target",
        "stop_loss_pct": config.stop_loss_pct,
        "max_holding_days": config.max_holding_days,
        "sizing": {
            "position_size_pct": config.position_size_pct,
            "max_positions": config.max_positions,
            "max_adtv_participation_pct": config.max_adtv_participation_pct,
            "target_adtv_participation_pct": config.target_adtv_participation_pct,
            "max_entry_bar_participation_pct": config.max_entry_bar_participation_pct,
            "max_single_order_notional": config.max_single_order_notional,
        },
        "continuation_entry": {
            "entry_delay_bars": config.entry_delay_bars,
            "min_pre_entry_close_return_pct": config.min_pre_entry_close_return_pct,
            "min_pre_entry_mfe_pct": config.min_pre_entry_mfe_pct,
            "max_pre_entry_mae_pct": config.max_pre_entry_mae_pct,
            "min_pre_entry_positive_close_share": config.min_pre_entry_positive_close_share,
            "min_pre_entry_gain_capture_pct": config.min_pre_entry_gain_capture_pct,
            "min_pre_entry_continuation_score": config.min_pre_entry_continuation_score,
            "max_entry_gap_pct": config.max_entry_gap_pct,
        },
        "risk_sizing": {
            "risk_sizing_enabled": config.risk_sizing_enabled,
            "risk_high_gap_threshold_pct": config.risk_high_gap_threshold_pct,
            "risk_high_mae_threshold_pct": config.risk_high_mae_threshold_pct,
            "risk_high_continuation_score_threshold": config.risk_high_continuation_score_threshold,
            "risk_high_multiplier": config.risk_high_multiplier,
            "risk_low_gap_threshold_pct": config.risk_low_gap_threshold_pct,
            "risk_low_mae_threshold_pct": config.risk_low_mae_threshold_pct,
            "risk_low_continuation_score_threshold": config.risk_low_continuation_score_threshold,
            "risk_low_multiplier": config.risk_low_multiplier,
            "uses_entry_time_information_only": True,
        },
        "execution_filters": {
            "min_setup_score": config.min_setup_score,
            "min_confirmation_score": config.min_confirmation_score,
            "min_breakout_date": config.min_breakout_date,
            "max_breakout_date": config.max_breakout_date,
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
            "exclude_bear_high_liquidity_setup_score_min": config.exclude_bear_high_liquidity_setup_score_min,
        },
        "cost_model": {
            "commission_bps_per_side": config.commission_bps_per_side,
            "slippage_bps_per_side": config.slippage_bps_per_side,
            "sell_tax_bps": config.sell_tax_bps,
            "liquidity_extra_slippage_bps": {
                "low": config.low_liquidity_extra_slippage_bps,
                "mid": config.mid_liquidity_extra_slippage_bps,
                "high": config.high_liquidity_extra_slippage_bps,
            },
            "gap_slippage_threshold_pct": config.gap_slippage_threshold_pct,
            "gap_extra_slippage_bps": config.gap_extra_slippage_bps,
            "limit_range_threshold_pct": config.limit_range_threshold_pct,
            "limit_extra_slippage_bps": config.limit_extra_slippage_bps,
        },
        "caveat": "This rule is frozen for confirmation; it should not be treated as production until verified on fresh data or an expanded OOS sample.",
    }


def _bar_trade_value(row: Mapping[str, Any], *, multiplier: float) -> Optional[float]:
    price = pd.to_numeric(pd.Series([row.get("close") or row.get("open")]), errors="coerce").iloc[0]
    volume = pd.to_numeric(pd.Series([row.get("volume")]), errors="coerce").iloc[0]
    if pd.isna(price) or pd.isna(volume) or float(price) <= 0 or float(volume) <= 0:
        return None
    return float(price) * float(volume) * float(multiplier)


def _bar_range_pct(row: Mapping[str, Any]) -> Optional[float]:
    high = pd.to_numeric(pd.Series([row.get("high")]), errors="coerce").iloc[0]
    low = pd.to_numeric(pd.Series([row.get("low")]), errors="coerce").iloc[0]
    close = pd.to_numeric(pd.Series([row.get("close")]), errors="coerce").iloc[0]
    if pd.isna(high) or pd.isna(low) or pd.isna(close) or float(close) <= 0:
        return None
    return max(0.0, (float(high) - float(low)) / float(close) * 100.0)


def _optional_float(value: Any) -> Optional[float]:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return None
    return float(numeric)


def _clip(value: float, low: float, high: float) -> float:
    return max(float(low), min(float(high), float(value)))


def _pre_entry_continuation_metrics(pre_entry: pd.DataFrame, breakout_price: float) -> Dict[str, float]:
    if pre_entry.empty or breakout_price <= 0:
        return {
            "pre_entry_close_return_pct": 0.0,
            "pre_entry_mfe_pct": 0.0,
            "pre_entry_mae_pct": 0.0,
            "pre_entry_positive_close_count": 0.0,
            "pre_entry_positive_close_share": 0.0,
            "pre_entry_gain_capture_pct": 0.0,
            "pre_entry_continuation_score": 0.0,
        }
    closes = pd.to_numeric(pre_entry["close"], errors="coerce").dropna()
    if closes.empty:
        positive_count = 0
        positive_share = 0.0
    else:
        positive_count = int((closes >= breakout_price).sum())
        positive_share = float(positive_count / len(closes))
    pre_entry_close = float(pre_entry.iloc[-1]["close"])
    close_return_pct = (pre_entry_close / breakout_price - 1.0) * 100.0
    mfe_pct = (float(pre_entry["high"].max()) / breakout_price - 1.0) * 100.0
    mae_pct = (1.0 - float(pre_entry["low"].min()) / breakout_price) * 100.0
    gain_capture_pct = close_return_pct / mfe_pct * 100.0 if mfe_pct > 0 else 0.0
    continuation_score = (
        25.0 * _clip(close_return_pct / 3.0, 0.0, 1.0)
        + 20.0 * _clip(mfe_pct / 4.0, 0.0, 1.0)
        + 25.0 * _clip(1.0 - mae_pct / 5.0, 0.0, 1.0)
        + 20.0 * _clip(positive_share, 0.0, 1.0)
        + 10.0 * _clip(gain_capture_pct / 100.0, 0.0, 1.0)
    )
    return {
        "pre_entry_close_return_pct": close_return_pct,
        "pre_entry_mfe_pct": mfe_pct,
        "pre_entry_mae_pct": mae_pct,
        "pre_entry_positive_close_count": float(positive_count),
        "pre_entry_positive_close_share": positive_share,
        "pre_entry_gain_capture_pct": gain_capture_pct,
        "pre_entry_continuation_score": continuation_score,
    }


def _risk_size_multiplier(trade: Mapping[str, Any], config: ExecutionConfig) -> tuple[float, str]:
    if not bool(config.risk_sizing_enabled):
        return 1.0, "fixed_size"

    entry_gap = _optional_float(trade.get("entry_gap_pct"))
    pre_entry_mae = _optional_float(trade.get("pre_entry_mae_pct"))
    pre_entry_continuation_score = _optional_float(trade.get("pre_entry_continuation_score"))
    high_risk_reasons: List[str] = []
    if entry_gap is not None and entry_gap >= float(config.risk_high_gap_threshold_pct):
        high_risk_reasons.append("entry_gap")
    if pre_entry_mae is not None and pre_entry_mae >= float(config.risk_high_mae_threshold_pct):
        high_risk_reasons.append("pre_entry_mae")
    if (
        config.risk_high_continuation_score_threshold is not None
        and pre_entry_continuation_score is not None
        and pre_entry_continuation_score <= float(config.risk_high_continuation_score_threshold)
    ):
        high_risk_reasons.append("weak_pre_entry_continuation")
    if high_risk_reasons:
        return max(0.0, float(config.risk_high_multiplier)), "risk_reduce_" + "+".join(high_risk_reasons)

    has_clean_gap = entry_gap is not None and entry_gap <= float(config.risk_low_gap_threshold_pct)
    has_clean_mae = pre_entry_mae is not None and pre_entry_mae <= float(config.risk_low_mae_threshold_pct)
    has_clean_continuation = (
        config.risk_low_continuation_score_threshold is None
        or (pre_entry_continuation_score is not None and pre_entry_continuation_score >= float(config.risk_low_continuation_score_threshold))
    )
    if has_clean_gap and has_clean_mae and has_clean_continuation:
        return max(0.0, float(config.risk_low_multiplier)), "risk_boost_clean_entry"

    return 1.0, "risk_neutral"


def _dynamic_slippage_bps(event: Mapping[str, Any], row: Mapping[str, Any], config: ExecutionConfig, *, raw_price: float) -> float:
    slippage_bps = float(config.slippage_bps_per_side)
    liquidity = str(event.get("liquidity_bucket") or "")
    if liquidity == "low":
        slippage_bps += float(config.low_liquidity_extra_slippage_bps)
    elif liquidity == "mid":
        slippage_bps += float(config.mid_liquidity_extra_slippage_bps)
    elif liquidity == "high":
        slippage_bps += float(config.high_liquidity_extra_slippage_bps)

    breakout_price = pd.to_numeric(pd.Series([event.get("breakout_price")]), errors="coerce").iloc[0]
    if pd.notna(breakout_price) and float(breakout_price) > 0 and raw_price > 0:
        gap_pct = abs(raw_price / float(breakout_price) - 1.0) * 100.0
        if gap_pct >= float(config.gap_slippage_threshold_pct):
            slippage_bps += float(config.gap_extra_slippage_bps)

    range_pct = _bar_range_pct(row)
    if range_pct is not None and range_pct >= float(config.limit_range_threshold_pct):
        slippage_bps += float(config.limit_extra_slippage_bps)
    return slippage_bps


def _exit_trade_on_path(event: Mapping[str, Any], event_path: pd.DataFrame, config: ExecutionConfig) -> Optional[Dict[str, Any]]:
    if event_path.empty:
        return None
    working = event_path.copy().sort_values("bar_after_breakout")
    working["bar_after_breakout"] = pd.to_numeric(working["bar_after_breakout"], errors="coerce")
    working = working.dropna(subset=["open", "high", "low", "close"])
    if working.empty:
        return None

    entry_bar = max(1, int(config.entry_delay_bars))
    breakout_price = pd.to_numeric(pd.Series([event.get("breakout_price")]), errors="coerce").iloc[0]
    if entry_bar > 1:
        if pd.isna(breakout_price) or float(breakout_price) <= 0:
            return None
        pre_entry = working[working["bar_after_breakout"] < entry_bar].copy()
        if pre_entry.empty:
            return None
        pre_entry_metrics = _pre_entry_continuation_metrics(pre_entry, float(breakout_price))
        pre_entry_close_return_pct = pre_entry_metrics["pre_entry_close_return_pct"]
        pre_entry_mfe_pct = pre_entry_metrics["pre_entry_mfe_pct"]
        pre_entry_mae_pct = pre_entry_metrics["pre_entry_mae_pct"]
        pre_entry_positive_close_count = pre_entry_metrics["pre_entry_positive_close_count"]
        pre_entry_positive_close_share = pre_entry_metrics["pre_entry_positive_close_share"]
        pre_entry_gain_capture_pct = pre_entry_metrics["pre_entry_gain_capture_pct"]
        pre_entry_continuation_score = pre_entry_metrics["pre_entry_continuation_score"]
        if config.min_pre_entry_close_return_pct is not None and pre_entry_close_return_pct < float(config.min_pre_entry_close_return_pct):
            return None
        if config.min_pre_entry_mfe_pct is not None and pre_entry_mfe_pct < float(config.min_pre_entry_mfe_pct):
            return None
        if config.max_pre_entry_mae_pct is not None and pre_entry_mae_pct > float(config.max_pre_entry_mae_pct):
            return None
        if config.min_pre_entry_positive_close_share is not None and pre_entry_positive_close_share < float(config.min_pre_entry_positive_close_share):
            return None
        if config.min_pre_entry_gain_capture_pct is not None and pre_entry_gain_capture_pct < float(config.min_pre_entry_gain_capture_pct):
            return None
        if config.min_pre_entry_continuation_score is not None and pre_entry_continuation_score < float(config.min_pre_entry_continuation_score):
            return None
    else:
        pre_entry_close_return_pct = None
        pre_entry_mfe_pct = None
        pre_entry_mae_pct = None
        pre_entry_positive_close_count = None
        pre_entry_positive_close_share = None
        pre_entry_gain_capture_pct = None
        pre_entry_continuation_score = None

    max_exit_bar = entry_bar + int(config.max_holding_days) - 1
    working = working[(working["bar_after_breakout"] >= entry_bar) & (working["bar_after_breakout"] <= max_exit_bar)].copy()
    if working.empty:
        return None

    first = working.iloc[0]
    raw_entry = float(first["open"])
    if raw_entry <= 0:
        return None
    entry_gap_pct = abs(raw_entry / float(breakout_price) - 1.0) * 100.0 if pd.notna(breakout_price) and float(breakout_price) > 0 else None
    if config.max_entry_gap_pct is not None:
        if entry_gap_pct is None or entry_gap_pct > float(config.max_entry_gap_pct):
            return None
    entry_slippage_bps = _dynamic_slippage_bps(event, first.to_dict(), config, raw_price=raw_entry)
    entry_slippage = float(entry_slippage_bps) / 10_000.0
    buy_fee = float(config.commission_bps_per_side) / 10_000.0
    sell_fee = (float(config.commission_bps_per_side) + float(config.sell_tax_bps)) / 10_000.0
    entry_fill = raw_entry * (1.0 + entry_slippage)
    target_dist_pct = float(event.get("target_dist_pct") or 0.0) * float(config.target_multiple)
    if target_dist_pct <= 0:
        return None
    target_price = entry_fill * (1.0 + target_dist_pct / 100.0)
    stop_price = entry_fill * (1.0 - float(config.stop_loss_pct) / 100.0)

    exit_reason = "time_exit"
    exit_bar_number = int(working.iloc[-1]["bar_after_breakout"])
    holding_days = exit_bar_number - entry_bar + 1
    raw_exit = float(working.iloc[-1]["close"])
    exit_date = str(working.iloc[-1]["trade_date"])
    exit_row = working.iloc[-1]
    for _, row in working.iterrows():
        high = float(row["high"])
        low = float(row["low"])
        target_hit = high >= target_price
        stop_hit = low <= stop_price
        if target_hit and stop_hit:
            exit_reason = "stop_loss" if config.same_bar_policy == "stop_first" else "target"
            raw_exit = stop_price if exit_reason == "stop_loss" else target_price
        elif stop_hit:
            exit_reason = "stop_loss"
            raw_exit = stop_price
        elif target_hit:
            exit_reason = "target"
            raw_exit = target_price
        else:
            continue
        exit_bar_number = int(row["bar_after_breakout"])
        holding_days = exit_bar_number - entry_bar + 1
        exit_date = str(row["trade_date"])
        exit_row = row
        break

    exit_slippage_bps = _dynamic_slippage_bps(event, exit_row.to_dict(), config, raw_price=raw_exit)
    exit_slippage = float(exit_slippage_bps) / 10_000.0
    exit_fill = raw_exit * (1.0 - exit_slippage)
    gross_return = exit_fill / entry_fill - 1.0
    net_return = (exit_fill * (1.0 - sell_fee)) / (entry_fill * (1.0 + buy_fee)) - 1.0
    entry_trade_value = _bar_trade_value(first.to_dict(), multiplier=float(config.value_unit_multiplier))
    exit_trade_value = _bar_trade_value(exit_row.to_dict(), multiplier=float(config.value_unit_multiplier))
    return {
        "event_id": event.get("event_id"),
        "symbol": event.get("symbol"),
        "time_split": event.get("time_split"),
        "entry_date": str(first["trade_date"]),
        "exit_date": exit_date,
        "entry_price": round(entry_fill, 6),
        "exit_price": round(exit_fill, 6),
        "raw_entry_price": round(raw_entry, 6),
        "raw_exit_price": round(raw_exit, 6),
        "target_price": round(target_price, 6),
        "stop_price": round(stop_price, 6),
        "target_dist_pct": round(target_dist_pct, 4),
        "holding_days": holding_days,
        "entry_delay_bars": entry_bar,
        "pre_entry_close_return_pct": round(pre_entry_close_return_pct, 4) if pre_entry_close_return_pct is not None else None,
        "pre_entry_mfe_pct": round(pre_entry_mfe_pct, 4) if pre_entry_mfe_pct is not None else None,
        "pre_entry_mae_pct": round(pre_entry_mae_pct, 4) if pre_entry_mae_pct is not None else None,
        "pre_entry_positive_close_count": int(pre_entry_positive_close_count) if pre_entry_positive_close_count is not None else None,
        "pre_entry_positive_close_share": round(pre_entry_positive_close_share, 4) if pre_entry_positive_close_share is not None else None,
        "pre_entry_gain_capture_pct": round(pre_entry_gain_capture_pct, 4) if pre_entry_gain_capture_pct is not None else None,
        "pre_entry_continuation_score": round(pre_entry_continuation_score, 4) if pre_entry_continuation_score is not None else None,
        "exit_reason": exit_reason,
        "gross_return_pct": round(gross_return * 100.0, 4),
        "net_return_pct": round(net_return * 100.0, 4),
        "entry_slippage_bps": round(entry_slippage_bps, 4),
        "exit_slippage_bps": round(exit_slippage_bps, 4),
        "entry_trade_value": round(entry_trade_value, 2) if entry_trade_value is not None else None,
        "exit_trade_value": round(exit_trade_value, 2) if exit_trade_value is not None else None,
        "entry_gap_pct": round(entry_gap_pct, 4) if entry_gap_pct is not None else None,
        "entry_bar_range_pct": round(_bar_range_pct(first.to_dict()) or 0.0, 4),
        "exit_bar_range_pct": round(_bar_range_pct(exit_row.to_dict()) or 0.0, 4),
    }


def _apply_execution_filters(events: pd.DataFrame, config: ExecutionConfig) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    filtered = events.copy()
    mask = pd.Series(True, index=filtered.index)
    def series(name: str, default: Any = "") -> pd.Series:
        value = filtered.get(name)
        if isinstance(value, pd.Series):
            return value
        return pd.Series(default, index=filtered.index)

    if config.min_setup_score is not None:
        mask &= pd.to_numeric(series("setup_score"), errors="coerce").fillna(-np.inf) >= float(config.min_setup_score)
    if config.min_confirmation_score is not None:
        mask &= pd.to_numeric(series("confirmation_score"), errors="coerce").fillna(-np.inf) >= float(config.min_confirmation_score)
    if config.allowed_liquidity_buckets:
        allowed = {str(item) for item in config.allowed_liquidity_buckets}
        mask &= series("liquidity_bucket").astype(str).isin(allowed)
    if config.allowed_market_regimes:
        allowed = {str(item) for item in config.allowed_market_regimes}
        mask &= series("market_regime").astype(str).isin(allowed)
    if config.allowed_publication_quality_tiers and "publication_quality_tier" in filtered.columns:
        allowed = {str(item) for item in config.allowed_publication_quality_tiers}
        mask &= series("publication_quality_tier").astype(str).isin(allowed)
    if config.min_pole_move_pct is not None and "pole_move_pct" in filtered.columns:
        mask &= pd.to_numeric(series("pole_move_pct"), errors="coerce").fillna(-np.inf) >= float(config.min_pole_move_pct)
    if config.max_pennant_to_pole_pct is not None and "pennant_to_pole_pct" in filtered.columns:
        mask &= pd.to_numeric(series("pennant_to_pole_pct"), errors="coerce").fillna(np.inf) <= float(config.max_pennant_to_pole_pct)
    if config.max_compression_ratio is not None and "compression_ratio" in filtered.columns:
        mask &= pd.to_numeric(series("compression_ratio"), errors="coerce").fillna(np.inf) <= float(config.max_compression_ratio)
    if config.min_breakout_volume_ratio is not None and "breakout_volume_ratio" in filtered.columns:
        mask &= pd.to_numeric(series("breakout_volume_ratio"), errors="coerce").fillna(-np.inf) >= float(config.min_breakout_volume_ratio)
    if config.require_volume_confirmed and "volume_confirmed" in filtered.columns:
        mask &= series("volume_confirmed").map(lambda value: bool(value) if isinstance(value, bool) else str(value).strip().lower() in {"true", "1", "yes", "y"})
    if config.allowed_pre_breakout_regime_branches and "pre_breakout_regime_branch" in filtered.columns:
        allowed = {str(item) for item in config.allowed_pre_breakout_regime_branches}
        mask &= series("pre_breakout_regime_branch").astype(str).isin(allowed)
    if config.excluded_pole_exhaustion_branches and "pole_exhaustion_branch" in filtered.columns:
        excluded = {str(item) for item in config.excluded_pole_exhaustion_branches}
        mask &= ~series("pole_exhaustion_branch").astype(str).isin(excluded)
    if config.max_prior_pennant_cluster_count_10d is not None and "prior_pennant_cluster_count_10d" in filtered.columns:
        mask &= pd.to_numeric(series("prior_pennant_cluster_count_10d"), errors="coerce").fillna(np.inf) <= int(config.max_prior_pennant_cluster_count_10d)
    if config.max_pre_breakout_volatility_20d_pct is not None and "pre_breakout_volatility_20d_pct" in filtered.columns:
        mask &= pd.to_numeric(series("pre_breakout_volatility_20d_pct"), errors="coerce").fillna(np.inf) <= float(config.max_pre_breakout_volatility_20d_pct)
    if config.exclude_bear_high_liquidity_setup_score_min is not None:
        overextended_bear_high_liquidity = (
            (series("market_regime").astype(str) == "bear")
            & (series("liquidity_bucket").astype(str) == "high")
            & (pd.to_numeric(series("setup_score"), errors="coerce").fillna(-np.inf) >= float(config.exclude_bear_high_liquidity_setup_score_min))
        )
        mask &= ~overextended_bear_high_liquidity
    return filtered[mask].copy()


def apply_event_scope(events: pd.DataFrame, path: pd.DataFrame, config: ExecutionConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply event-level research scope before chronological splits."""

    if events.empty:
        return events.copy(), path.copy()
    scoped = events.copy()
    mask = pd.Series(True, index=scoped.index)
    if config.min_breakout_date is not None or config.max_breakout_date is not None:
        dates = pd.to_datetime(scoped.get("breakout_date"), errors="coerce")
        if config.min_breakout_date is not None:
            mask &= dates >= pd.Timestamp(config.min_breakout_date)
        if config.max_breakout_date is not None:
            mask &= dates <= pd.Timestamp(config.max_breakout_date)
    scoped = scoped[mask].copy()
    if config.cooldown_days is not None and not scoped.empty and {"symbol", "breakout_date"}.issubset(scoped.columns):
        ordered = scoped.copy()
        ordered["_breakout_ts"] = pd.to_datetime(ordered["breakout_date"], errors="coerce")
        ordered = ordered.dropna(subset=["_breakout_ts"]).sort_values(["symbol", "_breakout_ts"]).copy()
        keep: List[Any] = []
        last_by_symbol: Dict[str, pd.Timestamp] = {}
        for idx, row in ordered.iterrows():
            symbol = str(row.get("symbol") or "")
            ts = row["_breakout_ts"]
            last = last_by_symbol.get(symbol)
            if last is None or (ts - last).days >= int(config.cooldown_days):
                keep.append(idx)
                last_by_symbol[symbol] = ts
        scoped = ordered.loc[keep].drop(columns=["_breakout_ts"], errors="ignore").sort_values(["breakout_date", "symbol"]).copy()
    if path.empty or scoped.empty or "event_id" not in scoped.columns or "event_id" not in path.columns:
        return scoped, path.copy()
    event_ids = set(scoped["event_id"].astype(str))
    scoped_path = path[path["event_id"].astype(str).isin(event_ids)].copy()
    return scoped, scoped_path


def build_signal_trades(events: pd.DataFrame, path: pd.DataFrame, config: ExecutionConfig) -> pd.DataFrame:
    if events.empty or path.empty:
        return pd.DataFrame()
    events = _apply_execution_filters(events, config)
    if events.empty:
        return pd.DataFrame()
    path_groups = {str(event_id): group for event_id, group in path.groupby("event_id", dropna=False)}
    trades: List[Dict[str, Any]] = []
    for _, event in events.sort_values("breakout_date").iterrows():
        event_id = str(event.get("event_id"))
        trade = _exit_trade_on_path(event.to_dict(), path_groups.get(event_id, pd.DataFrame()), config)
        if trade:
            trade.update(
                {
                    "strategy_id": config.strategy_id,
                    "breakout_date": event.get("breakout_date"),
                    "breakout_price": event.get("breakout_price"),
                    "setup_score": event.get("setup_score"),
                    "confirmation_score": event.get("confirmation_score"),
                    "followthrough_score": event.get("followthrough_score"),
                    "liquidity_bucket": event.get("liquidity_bucket"),
                    "adtv20_value": event.get("adtv20_value"),
                    "market_regime": event.get("market_regime"),
                    "market_group": event.get("market_group"),
                    "pre_breakout_regime_branch": event.get("pre_breakout_regime_branch"),
                    "pole_exhaustion_branch": event.get("pole_exhaustion_branch"),
                    "cluster_noise_branch": event.get("cluster_noise_branch"),
                    "prior_pennant_cluster_count_10d": event.get("prior_pennant_cluster_count_10d"),
                    "pre_breakout_volatility_20d_pct": event.get("pre_breakout_volatility_20d_pct"),
                }
            )
            trades.append(trade)
    return pd.DataFrame(trades)


def _max_drawdown_pct(equity_values: Sequence[float]) -> float:
    if not equity_values:
        return 0.0
    peak = float(equity_values[0])
    max_dd = 0.0
    for value in equity_values:
        value = float(value)
        peak = max(peak, value)
        if peak > 0:
            max_dd = min(max_dd, value / peak - 1.0)
    return round(max_dd * 100.0, 2)


def _concat_trade_frames(frames: Sequence[pd.DataFrame]) -> pd.DataFrame:
    clean = [frame.dropna(axis=1, how="all") for frame in frames if not frame.empty]
    return pd.concat(clean, ignore_index=True) if clean else pd.DataFrame()


def run_portfolio(trades: pd.DataFrame, config: ExecutionConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    if trades.empty:
        return trades.copy(), pd.DataFrame()
    working = trades.copy()
    working["_entry_ts"] = pd.to_datetime(working["entry_date"], errors="coerce")
    working["_exit_ts"] = pd.to_datetime(working["exit_date"], errors="coerce")
    working = working.dropna(subset=["_entry_ts", "_exit_ts"]).sort_values(["_entry_ts", "symbol"]).reset_index(drop=True)
    equity = float(config.initial_equity)
    open_positions: List[Dict[str, Any]] = []
    executed_rows: List[Dict[str, Any]] = []
    curve_rows: List[Dict[str, Any]] = [{"date": str(working.iloc[0]["entry_date"]), "equity": equity, "event": "start"}]

    def close_due(current_date: pd.Timestamp) -> None:
        nonlocal equity, open_positions
        remaining: List[Dict[str, Any]] = []
        for pos in sorted(open_positions, key=lambda item: item["exit_ts"]):
            if pos["exit_ts"] <= current_date:
                equity += pos["position_notional"] * float(pos["net_return_pct"]) / 100.0
                curve_rows.append({"date": str(pos["exit_date"]), "equity": round(equity, 2), "event": "exit"})
            else:
                remaining.append(pos)
        open_positions = remaining

    for _, row in working.iterrows():
        entry_ts = row["_entry_ts"]
        close_due(entry_ts)
        trade = row.drop(labels=["_entry_ts", "_exit_ts"]).to_dict()
        if len(open_positions) >= int(config.max_positions):
            trade.update({"executed": False, "skip_reason": "max_positions", "position_notional": 0.0, "pnl": 0.0})
            executed_rows.append(trade)
            continue
        base_notional = equity * float(config.position_size_pct)
        risk_size_multiplier, risk_size_reason = _risk_size_multiplier(trade, config)
        risk_adjusted_base_notional = base_notional * risk_size_multiplier
        raw_adtv = pd.to_numeric(pd.Series([trade.get("adtv20_value")]), errors="coerce").iloc[0]
        estimated_adtv = float(raw_adtv) * float(config.adtv_unit_multiplier) if pd.notna(raw_adtv) and float(raw_adtv) > 0 else None
        capacity_notional = (
            estimated_adtv * float(config.max_adtv_participation_pct) / 100.0
            if estimated_adtv and float(config.max_adtv_participation_pct) > 0
            else None
        )
        target_adtv_notional = (
            estimated_adtv * float(config.target_adtv_participation_pct) / 100.0
            if estimated_adtv and config.target_adtv_participation_pct is not None and float(config.target_adtv_participation_pct) > 0
            else None
        )
        entry_trade_value = pd.to_numeric(pd.Series([trade.get("entry_trade_value")]), errors="coerce").iloc[0]
        entry_bar_notional = (
            float(entry_trade_value) * float(config.max_entry_bar_participation_pct) / 100.0
            if pd.notna(entry_trade_value) and float(entry_trade_value) > 0 and float(config.max_entry_bar_participation_pct) > 0
            else None
        )
        max_order_notional = float(config.max_single_order_notional) if config.max_single_order_notional is not None else None
        notional_limits = [risk_adjusted_base_notional]
        if capacity_notional is not None:
            notional_limits.append(capacity_notional)
        if target_adtv_notional is not None:
            notional_limits.append(target_adtv_notional)
        if entry_bar_notional is not None:
            notional_limits.append(entry_bar_notional)
        if max_order_notional is not None and max_order_notional > 0:
            notional_limits.append(max_order_notional)
        notional = min(notional_limits)
        if notional < float(config.min_position_notional):
            trade.update(
                {
                    "executed": False,
                    "skip_reason": "capacity_below_min_notional",
                    "position_notional": 0.0,
                    "pnl": 0.0,
                    "base_position_notional": round(base_notional, 2),
                    "risk_size_multiplier": round(risk_size_multiplier, 4),
                    "risk_size_reason": risk_size_reason,
                    "risk_adjusted_base_notional": round(risk_adjusted_base_notional, 2),
                    "estimated_adtv_value": round(estimated_adtv, 2) if estimated_adtv is not None else None,
                    "adtv_participation_pct": None,
                    "target_adtv_participation_pct": config.target_adtv_participation_pct,
                    "entry_bar_participation_pct": None,
                    "exit_bar_participation_pct": None,
                    "risk_sizing_limited": bool(risk_adjusted_base_notional < base_notional),
                    "capacity_limited": bool(notional < risk_adjusted_base_notional),
                    "capacity_limit_reason": "below_min_notional",
                }
            )
            executed_rows.append(trade)
            continue
        adtv_participation = notional / estimated_adtv * 100.0 if estimated_adtv and estimated_adtv > 0 else None
        entry_bar_participation = notional / float(entry_trade_value) * 100.0 if pd.notna(entry_trade_value) and float(entry_trade_value) > 0 else None
        exit_trade_value = pd.to_numeric(pd.Series([trade.get("exit_trade_value")]), errors="coerce").iloc[0]
        exit_bar_participation = notional / float(exit_trade_value) * 100.0 if pd.notna(exit_trade_value) and float(exit_trade_value) > 0 else None
        limit_reasons: List[str] = []
        if capacity_notional is not None and capacity_notional <= notional + 1e-9 and capacity_notional < risk_adjusted_base_notional:
            limit_reasons.append("adtv")
        if target_adtv_notional is not None and target_adtv_notional <= notional + 1e-9 and target_adtv_notional < risk_adjusted_base_notional:
            limit_reasons.append("target_adtv")
        if entry_bar_notional is not None and entry_bar_notional <= notional + 1e-9 and entry_bar_notional < risk_adjusted_base_notional:
            limit_reasons.append("entry_bar")
        if max_order_notional is not None and max_order_notional <= notional + 1e-9 and max_order_notional < risk_adjusted_base_notional:
            limit_reasons.append("max_order")
        pnl = notional * float(trade["net_return_pct"]) / 100.0
        trade.update(
            {
                "executed": True,
                "skip_reason": "",
                "position_notional": round(notional, 2),
                "pnl": round(pnl, 2),
                "base_position_notional": round(base_notional, 2),
                "risk_size_multiplier": round(risk_size_multiplier, 4),
                "risk_size_reason": risk_size_reason,
                "risk_adjusted_base_notional": round(risk_adjusted_base_notional, 2),
                "estimated_adtv_value": round(estimated_adtv, 2) if estimated_adtv is not None else None,
                "adtv_participation_pct": round(adtv_participation, 4) if adtv_participation is not None else None,
                "target_adtv_participation_pct": config.target_adtv_participation_pct,
                "entry_bar_participation_pct": round(entry_bar_participation, 4) if entry_bar_participation is not None else None,
                "exit_bar_participation_pct": round(exit_bar_participation, 4) if exit_bar_participation is not None else None,
                "risk_sizing_limited": bool(risk_adjusted_base_notional < base_notional),
                "capacity_limited": bool(notional < risk_adjusted_base_notional),
                "capacity_limit_reason": "+".join(limit_reasons),
            }
        )
        open_positions.append(trade | {"exit_ts": row["_exit_ts"]})
        executed_rows.append(trade)
    close_due(pd.Timestamp.max)
    curve = pd.DataFrame(curve_rows)
    return pd.DataFrame(executed_rows), curve


def summarize_trades(trades: pd.DataFrame, curve: pd.DataFrame, *, split: str = "all") -> Dict[str, Any]:
    executed = trades[trades.get("executed", pd.Series(False, index=trades.index)) == True].copy() if not trades.empty else pd.DataFrame()
    skipped = int((trades.get("executed", pd.Series([], dtype=bool)) == False).sum()) if not trades.empty else 0
    if executed.empty:
        return {"split": split, "trades": 0, "skipped": skipped}
    returns = pd.to_numeric(executed["net_return_pct"], errors="coerce").dropna()
    wins = returns[returns > 0]
    losses = returns[returns <= 0]
    profit_factor = float(wins.sum() / abs(losses.sum())) if not losses.empty and abs(float(losses.sum())) > 0 else None
    final_equity = float(curve.iloc[-1]["equity"]) if not curve.empty else None
    initial_equity = float(curve.iloc[0]["equity"]) if not curve.empty else None
    participation = pd.to_numeric(executed.get("adtv_participation_pct"), errors="coerce")
    entry_participation = pd.to_numeric(executed.get("entry_bar_participation_pct"), errors="coerce")
    exit_participation = pd.to_numeric(executed.get("exit_bar_participation_pct"), errors="coerce")
    position_notional = pd.to_numeric(executed.get("position_notional"), errors="coerce")
    risk_multiplier = pd.to_numeric(executed.get("risk_size_multiplier"), errors="coerce")
    risk_reason = executed.get("risk_size_reason", pd.Series("", index=executed.index)).astype(str)
    capacity_reason = executed.get("capacity_limit_reason", pd.Series("", index=executed.index)).fillna("").astype(str)
    return {
        "split": split,
        "trades": int(len(executed)),
        "skipped": skipped,
        "win_rate_pct": round(float((returns > 0).mean()) * 100.0, 2),
        "avg_net_return_pct": round(float(returns.mean()), 2),
        "median_net_return_pct": round(float(returns.median()), 2),
        "total_return_pct": round((final_equity / initial_equity - 1.0) * 100.0, 2) if final_equity and initial_equity else None,
        "max_drawdown_pct": _max_drawdown_pct([float(value) for value in curve["equity"]]) if not curve.empty else None,
        "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
        "avg_holding_days": round(float(pd.to_numeric(executed["holding_days"], errors="coerce").mean()), 2),
        "target_exit_rate_pct": round(float((executed["exit_reason"] == "target").mean()) * 100.0, 2),
        "stop_exit_rate_pct": round(float((executed["exit_reason"] == "stop_loss").mean()) * 100.0, 2),
        "capacity_limited_rate_pct": round(float(executed.get("capacity_limited", pd.Series(False, index=executed.index)).astype(bool).mean()) * 100.0, 2),
        "target_adtv_limited_rate_pct": round(float(capacity_reason.str.contains("target_adtv", regex=False).mean()) * 100.0, 2) if not capacity_reason.empty else None,
        "median_adtv_participation_pct": round(float(participation.median()), 4) if not participation.dropna().empty else None,
        "median_entry_bar_participation_pct": round(float(entry_participation.median()), 4) if not entry_participation.dropna().empty else None,
        "median_exit_bar_participation_pct": round(float(exit_participation.median()), 4) if not exit_participation.dropna().empty else None,
        "high_entry_bar_participation_rate_pct": round(float((entry_participation > float(25.0)).mean()) * 100.0, 2) if not entry_participation.dropna().empty else None,
        "high_exit_bar_participation_rate_pct": round(float((exit_participation > float(25.0)).mean()) * 100.0, 2) if not exit_participation.dropna().empty else None,
        "avg_position_notional": round(float(position_notional.mean()), 2) if not position_notional.dropna().empty else None,
        "median_risk_size_multiplier": round(float(risk_multiplier.median()), 4) if not risk_multiplier.dropna().empty else None,
        "risk_reduced_rate_pct": round(float(risk_reason.str.startswith("risk_reduce").mean()) * 100.0, 2) if not risk_reason.empty else None,
        "risk_boosted_rate_pct": round(float((risk_reason == "risk_boost_clean_entry").mean()) * 100.0, 2) if not risk_reason.empty else None,
    }


def evaluate_strategy(events: pd.DataFrame, path: pd.DataFrame, config: ExecutionConfig) -> tuple[Dict[str, Any], pd.DataFrame, pd.DataFrame]:
    events, path = apply_event_scope(events, path, config)
    signal_trades = build_signal_trades(events, path, config)
    portfolio_trades, curve = run_portfolio(signal_trades, config)
    all_summary = summarize_trades(portfolio_trades, curve, split="all") | asdict(config)
    split_summaries: Dict[str, Dict[str, Any]] = {}
    for split in ("train_60", "validation_20", "holdout_20"):
        split_signals = signal_trades[signal_trades["time_split"].astype(str) == split].copy() if not signal_trades.empty else pd.DataFrame()
        split_portfolio, split_curve = run_portfolio(split_signals, config)
        split_summaries[split] = summarize_trades(split_portfolio, split_curve, split=split)
    for split, summary in split_summaries.items():
        prefix = split.replace("_20", "").replace("_60", "")
        for key, value in summary.items():
            if key != "split":
                all_summary[f"{prefix}_{key}"] = value
    return all_summary, portfolio_trades, curve


def _strategy_utility(
    row: Mapping[str, Any],
    *,
    return_key: str,
    drawdown_key: str,
    win_rate_key: str,
    trades_key: str,
    profit_factor_key: str,
) -> float:
    ret = _score_between(row.get(return_key), 0.0, 8.0)
    dd = _score_between(row.get(drawdown_key), -10.0, -2.0)
    win = _score_between(row.get(win_rate_key), 45.0, 70.0)
    trades = _score_between(row.get(trades_key), 8.0, 40.0)
    pf = _score_between(row.get(profit_factor_key), 1.0, 2.5)
    participation = _score_between(10.0 - float(row.get("median_adtv_participation_pct") or 10.0), 0.0, 10.0)
    return float(0.30 * ret + 0.20 * win + 0.18 * pf + 0.14 * dd + 0.10 * trades + 0.08 * participation)


def _validation_utility(row: Mapping[str, Any]) -> float:
    return _strategy_utility(
        row,
        return_key="validation_total_return_pct",
        drawdown_key="validation_max_drawdown_pct",
        win_rate_key="validation_win_rate_pct",
        trades_key="validation_trades",
        profit_factor_key="validation_profit_factor",
    )


def _train_utility(row: Mapping[str, Any]) -> float:
    if row.get("train_trades") is None:
        return _validation_utility(row)
    return _strategy_utility(
        row,
        return_key="train_total_return_pct",
        drawdown_key="train_max_drawdown_pct",
        win_rate_key="train_win_rate_pct",
        trades_key="train_trades",
        profit_factor_key="train_profit_factor",
    )


def _pre_holdout_utility(row: Mapping[str, Any]) -> float:
    # Holdout remains untouched for selection. The train term rewards rules that
    # keep working before holdout, instead of ranking on a single short
    # validation slice.
    return float(0.60 * _validation_utility(row) + 0.40 * _train_utility(row))


def _sample_utility(row: Mapping[str, Any]) -> float:
    return _strategy_utility(
        row,
        return_key="total_return_pct",
        drawdown_key="max_drawdown_pct",
        win_rate_key="win_rate_pct",
        trades_key="trades",
        profit_factor_key="profit_factor",
    )


def select_strategy(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
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
    selected = max(pool, key=_pre_holdout_utility)
    return {
        "status": "selected_tradable_setup" if passing else "no_strategy_passed_validation_gate",
        "selection_basis": "validation_gate_then_pre_holdout_train_validation_utility_holdout_and_walk_forward_reported_out_of_sample",
        "selected_strategy_id": selected.get("strategy_id"),
        "selected_metrics": selected,
        "passing_count": len(passing),
        "candidate_count": len(candidates),
    }


def _select_on_sample(rows: Sequence[Mapping[str, Any]], *, min_trades: int = 10, max_drawdown_floor: float = -20.0) -> Dict[str, Any]:
    candidates = [dict(row) for row in rows]
    if not candidates:
        return {"status": "no_strategy_rows"}
    passing = [
        row
        for row in candidates
        if int(row.get("trades") or 0) >= int(min_trades)
        and float(row.get("total_return_pct") or -999.0) > 0.0
        and float(row.get("max_drawdown_pct") or -999.0) >= float(max_drawdown_floor)
    ]
    pool = passing if passing else candidates
    selected = max(pool, key=_sample_utility)
    return {
        "status": "selected_on_sample" if passing else "no_strategy_passed_sample_gate",
        "selected_strategy_id": selected.get("strategy_id"),
        "selected_metrics": selected,
        "passing_count": len(passing),
        "candidate_count": len(candidates),
    }


def _summary_for_subset(events: pd.DataFrame, path: pd.DataFrame, config: ExecutionConfig) -> Dict[str, Any]:
    summary, _, _ = evaluate_strategy(events, path, config)
    return summary


def run_walk_forward_validation(
    events: pd.DataFrame,
    path: pd.DataFrame,
    configs: Sequence[ExecutionConfig],
    *,
    min_train_events: int = 25,
    test_events: int = 10,
) -> tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    if events.empty or path.empty:
        return pd.DataFrame(), pd.DataFrame(), {"status": "no_events"}
    if configs:
        min_dates = {config.min_breakout_date for config in configs}
        max_dates = {config.max_breakout_date for config in configs}
        if len(min_dates) == 1 and len(max_dates) == 1:
            events, path = apply_event_scope(events, path, configs[0])
    ordered = events.copy()
    ordered["_breakout_ts"] = pd.to_datetime(ordered["breakout_date"], errors="coerce")
    ordered = ordered.dropna(subset=["_breakout_ts"]).sort_values(["_breakout_ts", "symbol"]).reset_index(drop=True)
    fold_rows: List[Dict[str, Any]] = []
    trade_rows: List[pd.DataFrame] = []
    fold_id = 1
    start = int(min_train_events)
    while start < len(ordered):
        end = min(start + int(test_events), len(ordered))
        train_events = ordered.iloc[:start].drop(columns=["_breakout_ts"], errors="ignore").copy()
        test_events_df = ordered.iloc[start:end].drop(columns=["_breakout_ts"], errors="ignore").copy()
        if test_events_df.empty:
            break
        train_rows = [_summary_for_subset(train_events, path, config) for config in configs]
        selected = _select_on_sample(train_rows, min_trades=max(8, min(15, len(train_events) // 3)))
        selected_id = str(selected.get("selected_strategy_id") or "")
        selected_config = next((config for config in configs if config.strategy_id == selected_id), configs[0])
        test_summary, test_portfolio, _ = evaluate_strategy(test_events_df, path, selected_config)
        row = {
            "fold_id": fold_id,
            "train_events": int(len(train_events)),
            "test_events": int(len(test_events_df)),
            "test_start": str(test_events_df["breakout_date"].min()),
            "test_end": str(test_events_df["breakout_date"].max()),
            "selected_strategy_id": selected_id,
            "selection_status": selected.get("status"),
            "train_selected_total_return_pct": (selected.get("selected_metrics") or {}).get("total_return_pct"),
            "train_selected_max_drawdown_pct": (selected.get("selected_metrics") or {}).get("max_drawdown_pct"),
            "test_trades": test_summary.get("trades"),
            "test_total_return_pct": test_summary.get("total_return_pct"),
            "test_max_drawdown_pct": test_summary.get("max_drawdown_pct"),
            "test_win_rate_pct": test_summary.get("win_rate_pct"),
            "test_profit_factor": test_summary.get("profit_factor"),
        }
        fold_rows.append(row)
        if not test_portfolio.empty:
            fold_trades = test_portfolio.copy()
            fold_trades["walk_forward_fold_id"] = fold_id
            fold_trades["walk_forward_selected_strategy_id"] = selected_id
            trade_rows.append(fold_trades)
        fold_id += 1
        start = end

    folds = pd.DataFrame(fold_rows)
    trades = _concat_trade_frames(trade_rows)
    if folds.empty:
        return folds, trades, {"status": "no_folds"}
    test_returns = pd.to_numeric(folds["test_total_return_pct"], errors="coerce").dropna()
    test_dd = pd.to_numeric(folds["test_max_drawdown_pct"], errors="coerce").dropna()
    summary = {
        "status": "walk_forward_complete",
        "folds": int(len(folds)),
        "test_trades": int(pd.to_numeric(folds["test_trades"], errors="coerce").fillna(0).sum()),
        "positive_fold_rate_pct": round(float((test_returns > 0).mean()) * 100.0, 2) if not test_returns.empty else None,
        "mean_fold_return_pct": round(float(test_returns.mean()), 2) if not test_returns.empty else None,
        "median_fold_return_pct": round(float(test_returns.median()), 2) if not test_returns.empty else None,
        "sum_fold_return_pct": round(float(test_returns.sum()), 2) if not test_returns.empty else None,
        "worst_fold_return_pct": round(float(test_returns.min()), 2) if not test_returns.empty else None,
        "worst_fold_drawdown_pct": round(float(test_dd.min()), 2) if not test_dd.empty else None,
    }
    return folds, trades, summary


def run_fixed_strategy_walk_forward(
    events: pd.DataFrame,
    path: pd.DataFrame,
    config: ExecutionConfig,
    *,
    min_train_events: int = 25,
    test_events: int = 10,
) -> tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    if events.empty or path.empty:
        return pd.DataFrame(), pd.DataFrame(), {"status": "no_events"}
    events, path = apply_event_scope(events, path, config)
    if events.empty or path.empty:
        return pd.DataFrame(), pd.DataFrame(), {"status": "no_events_after_scope"}
    ordered = events.copy()
    ordered["_breakout_ts"] = pd.to_datetime(ordered["breakout_date"], errors="coerce")
    ordered = ordered.dropna(subset=["_breakout_ts"]).sort_values(["_breakout_ts", "symbol"]).reset_index(drop=True)
    fold_rows: List[Dict[str, Any]] = []
    trade_rows: List[pd.DataFrame] = []
    fold_id = 1
    start = int(min_train_events)
    while start < len(ordered):
        end = min(start + int(test_events), len(ordered))
        train_events = ordered.iloc[:start].drop(columns=["_breakout_ts"], errors="ignore").copy()
        test_events_df = ordered.iloc[start:end].drop(columns=["_breakout_ts"], errors="ignore").copy()
        if test_events_df.empty:
            break
        train_summary, _, _ = evaluate_strategy(train_events, path, config)
        test_summary, test_portfolio, _ = evaluate_strategy(test_events_df, path, config)
        fold_rows.append(
            {
                "fold_id": fold_id,
                "train_events": int(len(train_events)),
                "test_events": int(len(test_events_df)),
                "test_start": str(test_events_df["breakout_date"].min()),
                "test_end": str(test_events_df["breakout_date"].max()),
                "strategy_id": config.strategy_id,
                "train_trades": train_summary.get("trades"),
                "train_total_return_pct": train_summary.get("total_return_pct"),
                "train_max_drawdown_pct": train_summary.get("max_drawdown_pct"),
                "test_trades": test_summary.get("trades"),
                "test_total_return_pct": test_summary.get("total_return_pct"),
                "test_max_drawdown_pct": test_summary.get("max_drawdown_pct"),
                "test_win_rate_pct": test_summary.get("win_rate_pct"),
                "test_profit_factor": test_summary.get("profit_factor"),
            }
        )
        if not test_portfolio.empty:
            fold_trades = test_portfolio.copy()
            fold_trades["fixed_walk_forward_fold_id"] = fold_id
            fold_trades["fixed_walk_forward_strategy_id"] = config.strategy_id
            trade_rows.append(fold_trades)
        fold_id += 1
        start = end

    folds = pd.DataFrame(fold_rows)
    trades = _concat_trade_frames(trade_rows)
    if folds.empty:
        return folds, trades, {"status": "no_folds"}
    test_returns = pd.to_numeric(folds["test_total_return_pct"], errors="coerce").dropna()
    test_dd = pd.to_numeric(folds["test_max_drawdown_pct"], errors="coerce").dropna()
    summary = {
        "status": "fixed_walk_forward_complete",
        "folds": int(len(folds)),
        "test_trades": int(pd.to_numeric(folds["test_trades"], errors="coerce").fillna(0).sum()),
        "positive_fold_rate_pct": round(float((test_returns > 0).mean()) * 100.0, 2) if not test_returns.empty else None,
        "mean_fold_return_pct": round(float(test_returns.mean()), 2) if not test_returns.empty else None,
        "median_fold_return_pct": round(float(test_returns.median()), 2) if not test_returns.empty else None,
        "sum_fold_return_pct": round(float(test_returns.sum()), 2) if not test_returns.empty else None,
        "worst_fold_return_pct": round(float(test_returns.min()), 2) if not test_returns.empty else None,
        "worst_fold_drawdown_pct": round(float(test_dd.min()), 2) if not test_dd.empty else None,
    }
    return folds, trades, summary


def run_calendar_oos_validation(events: pd.DataFrame, path: pd.DataFrame, config: ExecutionConfig) -> tuple[pd.DataFrame, Dict[str, Any]]:
    if events.empty:
        return pd.DataFrame(), {"status": "no_events"}
    events, path = apply_event_scope(events, path, config)
    if events.empty:
        return pd.DataFrame(), {"status": "no_events_after_scope"}
    working = events.copy()
    working["_breakout_ts"] = pd.to_datetime(working["breakout_date"], errors="coerce")
    working = working.dropna(subset=["_breakout_ts"]).copy()
    if working.empty:
        return pd.DataFrame(), {"status": "no_valid_breakout_dates"}
    working["breakout_year"] = working["_breakout_ts"].dt.year
    rows: List[Dict[str, Any]] = []
    for year, group in working.groupby("breakout_year"):
        summary, _, _ = evaluate_strategy(group.drop(columns=["_breakout_ts"], errors="ignore"), path, config)
        rows.append(
            {
                "year": int(year),
                "events": int(len(group)),
                "trades": summary.get("trades"),
                "total_return_pct": summary.get("total_return_pct"),
                "max_drawdown_pct": summary.get("max_drawdown_pct"),
                "win_rate_pct": summary.get("win_rate_pct"),
                "profit_factor": summary.get("profit_factor"),
                "median_adtv_participation_pct": summary.get("median_adtv_participation_pct"),
            }
        )
    table = pd.DataFrame(rows).sort_values("year")
    returns = pd.to_numeric(table.get("total_return_pct"), errors="coerce").dropna()
    trade_counts = pd.to_numeric(table.get("trades"), errors="coerce").fillna(0)
    summary = {
        "status": "calendar_oos_complete",
        "years": int(len(table)),
        "trades": int(trade_counts.sum()),
        "positive_year_rate_pct": round(float((returns > 0).mean()) * 100.0, 2) if not returns.empty else None,
        "sum_year_return_pct": round(float(returns.sum()), 2) if not returns.empty else None,
        "worst_year_return_pct": round(float(returns.min()), 2) if not returns.empty else None,
        "underpowered_years": int((trade_counts < 5).sum()) if not table.empty else 0,
    }
    return table, summary


def build_cost_stress_configs(config: ExecutionConfig) -> Sequence[ExecutionConfig]:
    return (
        replace(config, strategy_id=f"{config.strategy_id}__base_cost"),
        replace(config, strategy_id=f"{config.strategy_id}__slippage_2x", slippage_bps_per_side=config.slippage_bps_per_side * 2.0),
        replace(config, strategy_id=f"{config.strategy_id}__slippage_3x", slippage_bps_per_side=config.slippage_bps_per_side * 3.0),
        replace(config, strategy_id=f"{config.strategy_id}__high_cost", commission_bps_per_side=25.0, slippage_bps_per_side=30.0, sell_tax_bps=10.0),
        replace(config, strategy_id=f"{config.strategy_id}__thin_liquidity", commission_bps_per_side=20.0, slippage_bps_per_side=50.0, sell_tax_bps=10.0),
        replace(
            config,
            strategy_id=f"{config.strategy_id}__liquidity_tiered",
            low_liquidity_extra_slippage_bps=40.0,
            mid_liquidity_extra_slippage_bps=20.0,
            high_liquidity_extra_slippage_bps=8.0,
        ),
        replace(
            config,
            strategy_id=f"{config.strategy_id}__gap_limit_stress",
            gap_extra_slippage_bps=30.0,
            limit_extra_slippage_bps=30.0,
        ),
    )


def run_cost_stress(events: pd.DataFrame, path: pd.DataFrame, config: ExecutionConfig) -> tuple[pd.DataFrame, Dict[str, Any]]:
    rows = []
    for stress_config in build_cost_stress_configs(config):
        summary, _, _ = evaluate_strategy(events, path, stress_config)
        summary["stress_scenario"] = stress_config.strategy_id.replace(f"{config.strategy_id}__", "")
        rows.append(summary)
    stress = pd.DataFrame(rows)
    returns_source = stress["total_return_pct"] if "total_return_pct" in stress.columns else pd.Series(dtype=float)
    drawdowns_source = stress["max_drawdown_pct"] if "max_drawdown_pct" in stress.columns else pd.Series(dtype=float)
    returns = pd.to_numeric(returns_source, errors="coerce").dropna()
    drawdowns = pd.to_numeric(drawdowns_source, errors="coerce").dropna()
    summary = {
        "status": "cost_stress_complete" if not stress.empty else "no_stress_rows",
        "scenario_count": int(len(stress)),
        "positive_scenario_rate_pct": round(float((returns > 0).mean()) * 100.0, 2) if not returns.empty else None,
        "worst_scenario_return_pct": round(float(returns.min()), 2) if not returns.empty else None,
        "worst_scenario_drawdown_pct": round(float(drawdowns.min()), 2) if not drawdowns.empty else None,
    }
    return stress, summary


def monte_carlo_trade_sequence(
    trades: pd.DataFrame,
    config: ExecutionConfig,
    *,
    iterations: int = 2_000,
    seed: int = 42,
) -> tuple[pd.DataFrame, Dict[str, Any]]:
    executed = trades[trades.get("executed", pd.Series(False, index=trades.index)) == True].copy() if not trades.empty else pd.DataFrame()
    returns_source = executed["net_return_pct"] if "net_return_pct" in executed.columns else pd.Series(dtype=float)
    returns = pd.to_numeric(returns_source, errors="coerce").dropna().to_numpy(dtype=float)
    if returns.size == 0:
        return pd.DataFrame(), {"status": "no_executed_trades"}
    rng = np.random.default_rng(seed)
    rows: List[Dict[str, Any]] = []
    for iteration in range(int(iterations)):
        sampled = rng.choice(returns, size=len(returns), replace=True)
        equity_values = [float(config.initial_equity)]
        equity = float(config.initial_equity)
        for ret in sampled:
            equity *= 1.0 + float(config.position_size_pct) * float(ret) / 100.0
            equity_values.append(equity)
        rows.append(
            {
                "iteration": iteration + 1,
                "total_return_pct": round((equity / float(config.initial_equity) - 1.0) * 100.0, 4),
                "max_drawdown_pct": _max_drawdown_pct(equity_values),
            }
        )
    sims = pd.DataFrame(rows)
    sim_returns = pd.to_numeric(sims["total_return_pct"], errors="coerce")
    sim_dd = pd.to_numeric(sims["max_drawdown_pct"], errors="coerce")
    summary = {
        "status": "monte_carlo_complete",
        "iterations": int(iterations),
        "trade_count": int(len(returns)),
        "prob_positive_pct": round(float((sim_returns > 0).mean()) * 100.0, 2),
        "total_return_p05_pct": round(float(sim_returns.quantile(0.05)), 2),
        "total_return_p50_pct": round(float(sim_returns.quantile(0.50)), 2),
        "total_return_p95_pct": round(float(sim_returns.quantile(0.95)), 2),
        "max_drawdown_p05_pct": round(float(sim_dd.quantile(0.05)), 2),
        "max_drawdown_p50_pct": round(float(sim_dd.quantile(0.50)), 2),
    }
    return sims, summary


def build_daily_mark_to_market_curve(trades: pd.DataFrame, path: pd.DataFrame, config: ExecutionConfig) -> tuple[pd.DataFrame, Dict[str, Any]]:
    executed = trades[trades.get("executed", pd.Series(False, index=trades.index)) == True].copy() if not trades.empty else pd.DataFrame()
    if executed.empty or path.empty:
        return pd.DataFrame(), {"status": "no_executed_trades"}
    executed["_entry_ts"] = pd.to_datetime(executed["entry_date"], errors="coerce")
    executed["_exit_ts"] = pd.to_datetime(executed["exit_date"], errors="coerce")
    executed = executed.dropna(subset=["_entry_ts", "_exit_ts"]).copy()
    if executed.empty:
        return pd.DataFrame(), {"status": "no_valid_trade_dates"}

    path_work = path.copy()
    path_work["_trade_ts"] = pd.to_datetime(path_work["trade_date"], errors="coerce")
    path_work["close"] = pd.to_numeric(path_work.get("close"), errors="coerce")
    path_work = path_work.dropna(subset=["_trade_ts", "close"])
    path_groups = {str(event_id): group.sort_values("_trade_ts") for event_id, group in path_work.groupby("event_id", dropna=False)}
    all_dates = sorted(
        date
        for date in path_work["_trade_ts"].dropna().unique()
        if pd.Timestamp(executed["_entry_ts"].min()) <= pd.Timestamp(date) <= pd.Timestamp(executed["_exit_ts"].max())
    )
    if not all_dates:
        return pd.DataFrame(), {"status": "no_path_dates"}

    rows: List[Dict[str, Any]] = []
    initial_equity = float(config.initial_equity)
    for date in all_dates:
        ts = pd.Timestamp(date)
        closed = executed[executed["_exit_ts"] <= ts]
        open_trades = executed[(executed["_entry_ts"] <= ts) & (executed["_exit_ts"] > ts)]
        closed_pnl = float(pd.to_numeric(closed.get("pnl"), errors="coerce").fillna(0.0).sum()) if not closed.empty else 0.0
        unrealized_pnl = 0.0
        gross_exposure = 0.0
        for _, trade in open_trades.iterrows():
            event_path = path_groups.get(str(trade.get("event_id")), pd.DataFrame())
            if event_path.empty:
                continue
            available = event_path[event_path["_trade_ts"] <= ts]
            if available.empty:
                continue
            mark_close = float(available.iloc[-1]["close"])
            entry_price = float(trade.get("entry_price") or 0.0)
            notional = float(trade.get("position_notional") or 0.0)
            if entry_price <= 0 or notional <= 0:
                continue
            unrealized_pnl += notional * (mark_close / entry_price - 1.0)
            gross_exposure += notional
        equity = initial_equity + closed_pnl + unrealized_pnl
        rows.append(
            {
                "date": str(ts.date()),
                "equity": round(equity, 2),
                "closed_pnl": round(closed_pnl, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "open_positions": int(len(open_trades)),
                "gross_exposure": round(gross_exposure, 2),
                "gross_exposure_pct": round(gross_exposure / equity * 100.0, 4) if equity > 0 else None,
            }
        )
    curve = pd.DataFrame(rows)
    summary = {
        "status": "daily_mtm_complete",
        "days": int(len(curve)),
        "total_return_pct": round((float(curve.iloc[-1]["equity"]) / initial_equity - 1.0) * 100.0, 2) if not curve.empty else None,
        "max_drawdown_pct": _max_drawdown_pct([float(value) for value in curve["equity"]]) if not curve.empty else None,
        "max_open_positions": int(pd.to_numeric(curve["open_positions"], errors="coerce").max()) if not curve.empty else None,
        "avg_open_positions": round(float(pd.to_numeric(curve["open_positions"], errors="coerce").mean()), 2) if not curve.empty else None,
        "max_gross_exposure_pct": round(float(pd.to_numeric(curve["gross_exposure_pct"], errors="coerce").max()), 2) if not curve.empty else None,
    }
    return curve, summary


def _score_between(value: Any, low: float, high: float) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return 0.0
    if high == low:
        return 100.0 if float(numeric) >= high else 0.0
    return max(0.0, min(100.0, (float(numeric) - low) / (high - low) * 100.0))


def score_tradable_setup(
    selection: Mapping[str, Any],
    walk_forward_summary: Mapping[str, Any],
    cost_stress_summary: Mapping[str, Any],
    monte_carlo_summary: Mapping[str, Any],
) -> Dict[str, Any]:
    selected = selection.get("selected_metrics") if isinstance(selection.get("selected_metrics"), Mapping) else {}
    execution_contract = 100.0 if selection.get("status") == "selected_tradable_setup" else 55.0
    validation_holdout = (
        0.25 * _score_between(selected.get("validation_total_return_pct"), 0.0, 5.0)
        + 0.20 * _score_between(selected.get("validation_trades"), 8, 15)
        + 0.25 * _score_between(selected.get("holdout_total_return_pct"), 0.0, 6.0)
        + 0.15 * _score_between(selected.get("holdout_trades"), 8, 12)
        + 0.15 * _score_between(selected.get("holdout_max_drawdown_pct"), -8.0, -1.0)
    )
    walk_forward = (
        0.35 * _score_between(walk_forward_summary.get("positive_fold_rate_pct"), 50.0, 100.0)
        + 0.25 * _score_between(walk_forward_summary.get("sum_fold_return_pct"), 0.0, 8.0)
        + 0.20 * _score_between(walk_forward_summary.get("test_trades"), 25, 40)
        + 0.20 * _score_between(walk_forward_summary.get("worst_fold_drawdown_pct"), -10.0, -2.0)
    )
    cost_stress = (
        0.40 * _score_between(cost_stress_summary.get("positive_scenario_rate_pct"), 60.0, 100.0)
        + 0.35 * _score_between(cost_stress_summary.get("worst_scenario_return_pct"), 0.0, 12.0)
        + 0.25 * _score_between(cost_stress_summary.get("worst_scenario_drawdown_pct"), -10.0, -3.0)
    )
    has_capacity_guard = 100.0 if float(selected.get("max_adtv_participation_pct") or 0.0) > 0.0 or float(selected.get("target_adtv_participation_pct") or 0.0) > 0.0 else 0.0
    capacity = (
        0.35 * has_capacity_guard
        + 0.25 * _score_between(10.0 - float(selected.get("median_adtv_participation_pct") or 10.0), 0.0, 10.0)
        + 0.20 * _score_between(100.0 - float(selected.get("skipped") or 0.0), 90.0, 100.0)
        + 0.20 * _score_between(selected.get("trades"), 50, 65)
    )
    monte_carlo = (
        0.45 * _score_between(monte_carlo_summary.get("prob_positive_pct"), 60.0, 95.0)
        + 0.35 * _score_between(monte_carlo_summary.get("total_return_p05_pct"), -5.0, 5.0)
        + 0.20 * _score_between(monte_carlo_summary.get("total_return_p50_pct"), 0.0, 20.0)
    )
    governance = 100.0
    weighted = (
        0.15 * execution_contract
        + 0.20 * validation_holdout
        + 0.20 * walk_forward
        + 0.15 * cost_stress
        + 0.15 * capacity
        + 0.10 * monte_carlo
        + 0.05 * governance
    )
    score = round(float(weighted), 2)
    if score >= 90:
        classification = "tradable-research-candidate"
    elif score >= 80:
        classification = "tradable-watchlist"
    elif score >= 70:
        classification = "tradable-provisional"
    else:
        classification = "research-only"
    promotion_blockers: List[str] = []
    if float(selected.get("validation_trades") or 0.0) < 12.0:
        promotion_blockers.append("validation_trade_count_below_12")
    if float(selected.get("holdout_trades") or 0.0) < 12.0:
        promotion_blockers.append("holdout_trade_count_below_12")
    if float(walk_forward_summary.get("positive_fold_rate_pct") or 0.0) < 100.0:
        promotion_blockers.append("walk_forward_has_negative_fold")
    if float(walk_forward_summary.get("sum_fold_return_pct") or 0.0) < 8.0:
        promotion_blockers.append("walk_forward_sum_return_below_8pct")
    if float(selected.get("median_adtv_participation_pct") or 999.0) > 5.0:
        promotion_blockers.append("median_adtv_participation_above_5pct")
    return {
        "score": score,
        "classification": classification,
        "promotion_target": "95+ requires blockers resolved without lookahead or holdout-driven parameter selection.",
        "promotion_blockers": promotion_blockers,
        "component_scores": {
            "execution_contract": round(float(execution_contract), 2),
            "validation_holdout": round(float(validation_holdout), 2),
            "walk_forward": round(float(walk_forward), 2),
            "cost_stress": round(float(cost_stress), 2),
            "capacity": round(float(capacity), 2),
            "monte_carlo": round(float(monte_carlo), 2),
            "governance": round(float(governance), 2),
        },
        "score_interpretation": "90+ requires positive validation/holdout, robust walk-forward folds, positive cost-stress scenarios, capacity-aware sizing, and favorable Monte Carlo fragility diagnostics.",
    }


def render_tradable_setup_report(
    selection: Mapping[str, Any],
    grid_rows: Sequence[Mapping[str, Any]],
    *,
    walk_forward_summary: Optional[Mapping[str, Any]] = None,
    cost_stress_summary: Optional[Mapping[str, Any]] = None,
    monte_carlo_summary: Optional[Mapping[str, Any]] = None,
    calendar_oos_summary: Optional[Mapping[str, Any]] = None,
    daily_mtm_summary: Optional[Mapping[str, Any]] = None,
    scorecard: Optional[Mapping[str, Any]] = None,
) -> str:
    selected = selection.get("selected_metrics") if isinstance(selection.get("selected_metrics"), Mapping) else {}
    lines = [
        "# Bull Flag V2 Tradable Setup Backtest",
        "",
        "Scope: long-only executable setup layer for the Bull Flag V2 pilot. This is separate from the Bulkowski-style reference chapter.",
        "",
        "## Execution Contract",
        "",
        "- Entry: configured post-breakout open; delayed-entry strategies wait before entry and do not use holdout for selection.",
        "- Exit: first target, stop, or max holding day; same-bar target/stop uses conservative stop-first.",
        "- Costs: commission per side, sell tax, and slippage are applied from the strategy config.",
        "- Sizing: fixed fraction of equity per position with max concurrent positions.",
        "- Selection: strategy must pass validation gates, then is ranked on train+validation pre-holdout utility; holdout is reported as OOS evidence.",
        "",
        "## Selection",
        "",
        f"- Status: `{selection.get('status')}`",
        f"- Selected strategy: `{selection.get('selected_strategy_id')}`",
        f"- Passing count: `{selection.get('passing_count')}` / `{selection.get('candidate_count')}`",
        "",
        "## Selected Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for key in (
        "trades",
        "total_return_pct",
        "max_drawdown_pct",
        "win_rate_pct",
        "median_net_return_pct",
        "profit_factor",
        "avg_holding_days",
        "entry_delay_bars",
        "max_entry_gap_pct",
        "min_pre_entry_positive_close_share",
        "min_pre_entry_gain_capture_pct",
        "min_pre_entry_continuation_score",
        "min_setup_score",
        "min_breakout_date",
        "allowed_market_regimes",
        "target_multiple",
        "stop_loss_pct",
        "risk_sizing_enabled",
        "risk_high_gap_threshold_pct",
        "risk_high_mae_threshold_pct",
        "risk_high_continuation_score_threshold",
        "risk_high_multiplier",
        "risk_low_gap_threshold_pct",
        "risk_low_mae_threshold_pct",
        "risk_low_continuation_score_threshold",
        "risk_low_multiplier",
        "median_risk_size_multiplier",
        "risk_reduced_rate_pct",
        "risk_boosted_rate_pct",
        "target_exit_rate_pct",
        "stop_exit_rate_pct",
        "capacity_limited_rate_pct",
        "target_adtv_participation_pct",
        "target_adtv_limited_rate_pct",
        "median_adtv_participation_pct",
        "validation_trades",
        "validation_total_return_pct",
        "validation_max_drawdown_pct",
        "holdout_trades",
        "holdout_total_return_pct",
        "holdout_max_drawdown_pct",
    ):
        lines.append(f"| {key} | {selected.get(key)} |")
    lines.extend(
        [
            "",
            "## Strategy Grid",
            "",
            "| Strategy | Trades | Val return | Val DD | Holdout trades | Holdout return | Holdout DD |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in grid_rows:
        lines.append(
            "| {sid} | {trades} | {vr} | {vdd} | {ht} | {hr} | {hdd} |".format(
                sid=row.get("strategy_id"),
                trades=row.get("trades"),
                vr=row.get("validation_total_return_pct"),
                vdd=row.get("validation_max_drawdown_pct"),
                ht=row.get("holdout_trades"),
                hr=row.get("holdout_total_return_pct"),
                hdd=row.get("holdout_max_drawdown_pct"),
            )
        )
    if walk_forward_summary:
        lines.extend(
            [
                "",
                "## Walk-Forward Validation",
                "",
                "| Metric | Value |",
                "|---|---:|",
            ]
        )
        for key in ("folds", "test_trades", "positive_fold_rate_pct", "sum_fold_return_pct", "worst_fold_return_pct", "worst_fold_drawdown_pct"):
            lines.append(f"| {key} | {walk_forward_summary.get(key)} |")
    if cost_stress_summary:
        lines.extend(
            [
                "",
                "## Cost Stress",
                "",
                "| Metric | Value |",
                "|---|---:|",
            ]
        )
        for key in ("scenario_count", "positive_scenario_rate_pct", "worst_scenario_return_pct", "worst_scenario_drawdown_pct"):
            lines.append(f"| {key} | {cost_stress_summary.get(key)} |")
    if calendar_oos_summary:
        lines.extend(
            [
                "",
                "## Calendar OOS",
                "",
                "| Metric | Value |",
                "|---|---:|",
            ]
        )
        for key in ("years", "trades", "positive_year_rate_pct", "sum_year_return_pct", "worst_year_return_pct", "underpowered_years"):
            lines.append(f"| {key} | {calendar_oos_summary.get(key)} |")
    if daily_mtm_summary:
        lines.extend(
            [
                "",
                "## Daily Mark-To-Market Portfolio",
                "",
                "| Metric | Value |",
                "|---|---:|",
            ]
        )
        for key in ("days", "total_return_pct", "max_drawdown_pct", "max_open_positions", "avg_open_positions", "max_gross_exposure_pct"):
            lines.append(f"| {key} | {daily_mtm_summary.get(key)} |")
    if monte_carlo_summary:
        lines.extend(
            [
                "",
                "## Monte Carlo Fragility",
                "",
                "| Metric | Value |",
                "|---|---:|",
            ]
        )
        for key in ("iterations", "prob_positive_pct", "total_return_p05_pct", "total_return_p50_pct", "total_return_p95_pct", "max_drawdown_p50_pct"):
            lines.append(f"| {key} | {monte_carlo_summary.get(key)} |")
    if scorecard:
        lines.extend(
            [
                "",
                "## Tradable Scorecard",
                "",
                f"- Classification: `{scorecard.get('classification')}`",
                f"- Score: `{scorecard.get('score')}` / 100",
                "",
                "| Component | Score |",
                "|---|---:|",
            ]
        )
        components = scorecard.get("component_scores") if isinstance(scorecard.get("component_scores"), Mapping) else {}
        for key, value in components.items():
            lines.append(f"| {key} | {value} |")
        blockers = scorecard.get("promotion_blockers") if isinstance(scorecard.get("promotion_blockers"), list) else []
        if blockers:
            lines.extend(["", "Promotion blockers:"])
            lines.extend([f"- `{blocker}`" for blocker in blockers])
    return "\n".join(lines) + "\n"


def run_bull_flag_tradable_backtest(
    *,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    out_dir: Path = DEFAULT_OUT_DIR,
    configs: Sequence[ExecutionConfig] = DEFAULT_STRATEGY_GRID,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    events, path = load_bull_flag_v2_artifacts(profile_dir)
    grid_rows: List[Dict[str, Any]] = []
    trades_by_strategy: Dict[str, pd.DataFrame] = {}
    curves_by_strategy: Dict[str, pd.DataFrame] = {}
    for config in configs:
        summary, trades, curve = evaluate_strategy(events, path, config)
        grid_rows.append(summary)
        trades_by_strategy[config.strategy_id] = trades
        curves_by_strategy[config.strategy_id] = curve
    selection = select_strategy(grid_rows)
    selected_id = str(selection.get("selected_strategy_id") or "")
    config_by_id = {config.strategy_id: config for config in configs}
    selected_config = config_by_id.get(selected_id, configs[0] if configs else ExecutionConfig(strategy_id="fallback"))
    selected_trades = trades_by_strategy.get(selected_id, pd.DataFrame())
    selected_curve = curves_by_strategy.get(selected_id, pd.DataFrame())
    walk_forward_folds, walk_forward_trades, walk_forward_summary = run_fixed_strategy_walk_forward(events, path, selected_config)
    adaptive_walk_forward_folds, adaptive_walk_forward_trades, adaptive_walk_forward_summary = run_walk_forward_validation(events, path, configs)
    calendar_oos, calendar_oos_summary = run_calendar_oos_validation(events, path, selected_config)
    cost_stress, cost_stress_summary = run_cost_stress(events, path, selected_config)
    monte_carlo_sims, monte_carlo_summary = monte_carlo_trade_sequence(selected_trades, selected_config)
    daily_mtm_curve, daily_mtm_summary = build_daily_mark_to_market_curve(selected_trades, path, selected_config)
    scorecard = score_tradable_setup(selection, walk_forward_summary, cost_stress_summary, monte_carlo_summary)
    rule_contract = frozen_rule_contract(selected_config, profile_id=profile_dir.name)
    selection = dict(selection)
    selection["frozen_rule_contract"] = rule_contract
    selection["walk_forward_summary"] = walk_forward_summary
    selection["adaptive_walk_forward_summary"] = adaptive_walk_forward_summary
    selection["calendar_oos_summary"] = calendar_oos_summary
    selection["cost_stress_summary"] = cost_stress_summary
    selection["monte_carlo_summary"] = monte_carlo_summary
    selection["daily_mark_to_market_summary"] = daily_mtm_summary
    selection["tradable_scorecard"] = scorecard

    paths = {
        "rule_contract_json": out_dir / "bull_flag_tradable_frozen_rule_contract.json",
        "strategy_grid_csv": out_dir / "bull_flag_tradable_strategy_grid.csv",
        "selected_strategy_json": out_dir / "bull_flag_tradable_selected_strategy.json",
        "selected_trades_csv": out_dir / "bull_flag_tradable_trades.csv",
        "equity_curve_csv": out_dir / "bull_flag_tradable_equity_curve.csv",
        "daily_mtm_curve_csv": out_dir / "bull_flag_tradable_daily_mtm_curve.csv",
        "walk_forward_folds_csv": out_dir / "bull_flag_tradable_walk_forward_folds.csv",
        "walk_forward_trades_csv": out_dir / "bull_flag_tradable_walk_forward_trades.csv",
        "adaptive_walk_forward_folds_csv": out_dir / "bull_flag_tradable_adaptive_walk_forward_folds.csv",
        "adaptive_walk_forward_trades_csv": out_dir / "bull_flag_tradable_adaptive_walk_forward_trades.csv",
        "calendar_oos_csv": out_dir / "bull_flag_tradable_calendar_oos.csv",
        "cost_stress_csv": out_dir / "bull_flag_tradable_cost_stress.csv",
        "monte_carlo_csv": out_dir / "bull_flag_tradable_monte_carlo.csv",
        "scorecard_json": out_dir / "bull_flag_tradable_scorecard.json",
        "report_md": out_dir / "bull_flag_tradable_backtest_report.md",
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
    paths["rule_contract_json"].write_text(json.dumps(rule_contract, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    paths["selected_strategy_json"].write_text(json.dumps(selection, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    paths["scorecard_json"].write_text(json.dumps(scorecard, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    paths["report_md"].write_text(
        render_tradable_setup_report(
            selection,
            grid_rows,
            walk_forward_summary=walk_forward_summary,
            cost_stress_summary=cost_stress_summary,
            monte_carlo_summary=monte_carlo_summary,
            calendar_oos_summary=calendar_oos_summary,
            daily_mtm_summary=daily_mtm_summary,
            scorecard=scorecard,
        ),
        encoding="utf-8",
    )
    return paths


__all__ = [
    "DEFAULT_OUT_DIR",
    "DEFAULT_PROFILE_DIR",
    "DEFAULT_STRATEGY_GRID",
    "ExecutionConfig",
    "apply_event_scope",
    "build_daily_mark_to_market_curve",
    "build_cost_stress_configs",
    "build_signal_trades",
    "evaluate_strategy",
    "frozen_rule_contract",
    "load_bull_flag_v2_artifacts",
    "monte_carlo_trade_sequence",
    "run_calendar_oos_validation",
    "run_bull_flag_tradable_backtest",
    "run_cost_stress",
    "run_fixed_strategy_walk_forward",
    "run_walk_forward_validation",
    "run_portfolio",
    "score_tradable_setup",
    "select_strategy",
    "summarize_trades",
]
