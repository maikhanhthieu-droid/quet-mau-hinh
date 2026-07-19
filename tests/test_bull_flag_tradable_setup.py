from __future__ import annotations

from pathlib import Path

import pandas as pd

from scanner.run_bull_flag_tradable_robustness import normalize_profile_schema, robustness_gate
from scanner.v2.bull_flag_tradable_setup import (
    ExecutionConfig,
    apply_event_scope,
    build_daily_mark_to_market_curve,
    build_signal_trades,
    frozen_rule_contract,
    monte_carlo_trade_sequence,
    run_calendar_oos_validation,
    run_cost_stress,
    run_fixed_strategy_walk_forward,
    run_portfolio,
    run_walk_forward_validation,
    score_tradable_setup,
    select_strategy,
    summarize_trades,
)


def _events() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "event_id": ["e1", "e2"],
            "symbol": ["AAA", "BBB"],
            "breakout_date": ["2024-01-01", "2024-01-01"],
            "breakout_price": [100.0, 100.0],
            "target_dist_pct": [10.0, 10.0],
            "time_split": ["validation_20", "holdout_20"],
            "setup_score": [80.0, 80.0],
            "confirmation_score": [70.0, 70.0],
        }
    )


def test_trade_exit_uses_conservative_same_bar_stop_first() -> None:
    path = pd.DataFrame(
        {
            "event_id": ["e1"],
            "symbol": ["AAA"],
            "trade_date": ["2024-01-02"],
            "bar_after_breakout": [1],
            "open": [100.0],
            "high": [106.0],
            "low": [94.0],
            "close": [105.0],
        }
    )
    config = ExecutionConfig(strategy_id="test", target_multiple=0.46, stop_loss_pct=5.0, max_holding_days=5, slippage_bps_per_side=0, commission_bps_per_side=0, sell_tax_bps=0)

    trades = build_signal_trades(_events().iloc[:1], path, config)

    assert trades.iloc[0]["exit_reason"] == "stop_loss"
    assert trades.iloc[0]["net_return_pct"] == -5.0


def test_trade_costs_reduce_target_return() -> None:
    path = pd.DataFrame(
        {
            "event_id": ["e1", "e1"],
            "symbol": ["AAA", "AAA"],
            "trade_date": ["2024-01-02", "2024-01-03"],
            "bar_after_breakout": [1, 2],
            "open": [100.0, 102.0],
            "high": [102.0, 106.0],
            "low": [99.0, 101.0],
            "close": [101.0, 105.0],
        }
    )
    free = ExecutionConfig(strategy_id="free", target_multiple=0.46, stop_loss_pct=5.0, commission_bps_per_side=0, slippage_bps_per_side=0, sell_tax_bps=0)
    costly = ExecutionConfig(strategy_id="costly", target_multiple=0.46, stop_loss_pct=5.0, commission_bps_per_side=15, slippage_bps_per_side=10, sell_tax_bps=10)

    free_trade = build_signal_trades(_events().iloc[:1], path, free).iloc[0]
    costly_trade = build_signal_trades(_events().iloc[:1], path, costly).iloc[0]

    assert free_trade["exit_reason"] == "target"
    assert costly_trade["net_return_pct"] < free_trade["net_return_pct"]


def test_liquidity_and_gap_slippage_increase_trade_cost() -> None:
    events = _events().iloc[:1].copy()
    events["liquidity_bucket"] = ["low"]
    path = pd.DataFrame(
        {
            "event_id": ["e1", "e1"],
            "symbol": ["AAA", "AAA"],
            "trade_date": ["2024-01-02", "2024-01-03"],
            "bar_after_breakout": [1, 2],
            "open": [104.0, 105.0],
            "high": [105.0, 110.0],
            "low": [103.0, 104.0],
            "close": [104.0, 109.0],
            "volume": [1000, 1000],
        }
    )
    base = ExecutionConfig(strategy_id="base", target_multiple=0.46, stop_loss_pct=5.0, commission_bps_per_side=0, slippage_bps_per_side=0, sell_tax_bps=0)
    stressed = ExecutionConfig(
        strategy_id="stressed",
        target_multiple=0.46,
        stop_loss_pct=5.0,
        commission_bps_per_side=0,
        slippage_bps_per_side=0,
        sell_tax_bps=0,
        low_liquidity_extra_slippage_bps=20,
        gap_extra_slippage_bps=20,
    )

    base_trade = build_signal_trades(events, path, base).iloc[0]
    stressed_trade = build_signal_trades(events, path, stressed).iloc[0]

    assert stressed_trade["entry_slippage_bps"] > base_trade["entry_slippage_bps"]
    assert stressed_trade["net_return_pct"] < base_trade["net_return_pct"]


def test_delayed_continuation_entry_waits_for_pre_entry_confirmation() -> None:
    events = _events().iloc[:1].copy()
    path = pd.DataFrame(
        {
            "event_id": ["e1", "e1", "e1", "e1"],
            "symbol": ["AAA", "AAA", "AAA", "AAA"],
            "trade_date": ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
            "bar_after_breakout": [1, 2, 3, 4],
            "open": [100.0, 101.0, 102.0, 103.0],
            "high": [101.0, 103.0, 104.0, 109.0],
            "low": [99.0, 100.0, 101.0, 102.0],
            "close": [100.5, 102.0, 103.0, 108.0],
        }
    )
    config = ExecutionConfig(
        strategy_id="delayed",
        target_multiple=0.46,
        stop_loss_pct=5.0,
        entry_delay_bars=4,
        min_pre_entry_close_return_pct=1.0,
        min_pre_entry_mfe_pct=3.0,
        max_pre_entry_mae_pct=2.0,
        min_pre_entry_positive_close_share=0.75,
        min_pre_entry_gain_capture_pct=70.0,
        min_pre_entry_continuation_score=80.0,
        commission_bps_per_side=0,
        slippage_bps_per_side=0,
        sell_tax_bps=0,
    )

    trade = build_signal_trades(events, path, config).iloc[0]

    assert trade["entry_date"] == "2024-01-05"
    assert trade["entry_delay_bars"] == 4
    assert trade["pre_entry_close_return_pct"] == 3.0
    assert trade["pre_entry_mfe_pct"] == 4.0
    assert trade["pre_entry_positive_close_share"] == 1.0
    assert trade["pre_entry_gain_capture_pct"] == 75.0
    assert trade["pre_entry_continuation_score"] == 92.5
    assert trade["holding_days"] == 1


def test_delayed_continuation_entry_rejects_weak_followthrough() -> None:
    events = _events().iloc[:1].copy()
    path = pd.DataFrame(
        {
            "event_id": ["e1", "e1", "e1", "e1"],
            "symbol": ["AAA", "AAA", "AAA", "AAA"],
            "trade_date": ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
            "bar_after_breakout": [1, 2, 3, 4],
            "open": [100.0, 100.0, 100.0, 100.0],
            "high": [101.0, 101.5, 101.8, 104.0],
            "low": [99.0, 99.0, 99.0, 99.0],
            "close": [100.0, 100.5, 100.8, 103.0],
        }
    )
    config = ExecutionConfig(
        strategy_id="delayed",
        target_multiple=0.46,
        stop_loss_pct=5.0,
        entry_delay_bars=4,
        min_pre_entry_mfe_pct=3.0,
        commission_bps_per_side=0,
        slippage_bps_per_side=0,
        sell_tax_bps=0,
    )

    trades = build_signal_trades(events, path, config)

    assert trades.empty


def test_staged_continuation_entry_rejects_poor_gain_capture() -> None:
    events = _events().iloc[:1].copy()
    path = pd.DataFrame(
        {
            "event_id": ["e1", "e1", "e1", "e1"],
            "symbol": ["AAA", "AAA", "AAA", "AAA"],
            "trade_date": ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
            "bar_after_breakout": [1, 2, 3, 4],
            "open": [100.0, 101.0, 101.0, 101.0],
            "high": [105.0, 105.0, 105.0, 106.0],
            "low": [99.5, 100.0, 100.0, 100.0],
            "close": [104.0, 101.0, 101.0, 104.0],
        }
    )
    config = ExecutionConfig(
        strategy_id="stage_confirm",
        target_multiple=0.46,
        stop_loss_pct=5.0,
        entry_delay_bars=4,
        min_pre_entry_gain_capture_pct=40.0,
        min_pre_entry_continuation_score=50.0,
        commission_bps_per_side=0,
        slippage_bps_per_side=0,
        sell_tax_bps=0,
    )

    trades = build_signal_trades(events, path, config)

    assert trades.empty


def test_delayed_entry_rejects_large_entry_gap() -> None:
    events = _events().iloc[:1].copy()
    path = pd.DataFrame(
        {
            "event_id": ["e1", "e1", "e1"],
            "symbol": ["AAA", "AAA", "AAA"],
            "trade_date": ["2024-01-02", "2024-01-03", "2024-01-04"],
            "bar_after_breakout": [1, 2, 3],
            "open": [100.0, 101.0, 104.0],
            "high": [101.0, 103.0, 105.0],
            "low": [99.0, 100.0, 103.0],
            "close": [100.5, 102.0, 104.0],
        }
    )
    config = ExecutionConfig(
        strategy_id="gap_guard",
        target_multiple=0.46,
        stop_loss_pct=5.0,
        entry_delay_bars=3,
        max_entry_gap_pct=2.5,
        commission_bps_per_side=0,
        slippage_bps_per_side=0,
        sell_tax_bps=0,
    )

    trades = build_signal_trades(events, path, config)

    assert trades.empty


def test_execution_filter_uses_setup_and_confirmation_only() -> None:
    events = pd.DataFrame(
        {
            "event_id": ["e1", "e2", "e3"],
            "symbol": ["AAA", "BBB", "CCC"],
            "breakout_date": ["2024-01-01"] * 3,
            "breakout_price": [100.0] * 3,
            "target_dist_pct": [10.0] * 3,
            "time_split": ["validation_20"] * 3,
            "setup_score": [72.0, 64.0, 75.0],
            "confirmation_score": [55.0, 80.0, 45.0],
        }
    )
    path = pd.DataFrame(
        {
            "event_id": ["e1", "e2", "e3"],
            "symbol": ["AAA", "BBB", "CCC"],
            "trade_date": ["2024-01-02"] * 3,
            "bar_after_breakout": [1, 1, 1],
            "open": [100.0] * 3,
            "high": [106.0] * 3,
            "low": [99.0] * 3,
            "close": [105.0] * 3,
        }
    )
    config = ExecutionConfig(strategy_id="filtered", min_setup_score=70.0, min_confirmation_score=50.0, commission_bps_per_side=0, slippage_bps_per_side=0, sell_tax_bps=0)

    trades = build_signal_trades(events, path, config)

    assert trades["event_id"].tolist() == ["e1"]


def test_event_scope_filters_events_and_path_before_chronological_evaluation() -> None:
    events = pd.DataFrame(
        {
            "event_id": ["old", "new"],
            "symbol": ["AAA", "BBB"],
            "breakout_date": ["2018-12-31", "2019-01-02"],
            "breakout_price": [100.0, 100.0],
            "target_dist_pct": [10.0, 10.0],
        }
    )
    path = pd.DataFrame(
        {
            "event_id": ["old", "new"],
            "symbol": ["AAA", "BBB"],
            "trade_date": ["2019-01-02", "2019-01-03"],
            "bar_after_breakout": [1, 1],
            "open": [100.0, 100.0],
            "high": [105.0, 105.0],
            "low": [99.0, 99.0],
            "close": [104.0, 104.0],
        }
    )
    config = ExecutionConfig(strategy_id="scoped", min_breakout_date="2019-01-01")

    scoped_events, scoped_path = apply_event_scope(events, path, config)

    assert scoped_events["event_id"].tolist() == ["new"]
    assert scoped_path["event_id"].tolist() == ["new"]


def test_context_guard_excludes_overextended_bear_high_liquidity_setups() -> None:
    events = pd.DataFrame(
        {
            "event_id": ["e1", "e2", "e3"],
            "symbol": ["AAA", "BBB", "CCC"],
            "breakout_date": ["2024-01-01"] * 3,
            "breakout_price": [100.0] * 3,
            "target_dist_pct": [10.0] * 3,
            "time_split": ["validation_20"] * 3,
            "setup_score": [82.0, 82.0, 82.0],
            "liquidity_bucket": ["high", "mid", "high"],
            "market_regime": ["bear", "bear", "bull"],
        }
    )
    path = pd.DataFrame(
        {
            "event_id": ["e1", "e2", "e3"],
            "symbol": ["AAA", "BBB", "CCC"],
            "trade_date": ["2024-01-02"] * 3,
            "bar_after_breakout": [1, 1, 1],
            "open": [100.0] * 3,
            "high": [106.0] * 3,
            "low": [99.0] * 3,
            "close": [105.0] * 3,
        }
    )
    config = ExecutionConfig(strategy_id="guarded", exclude_bear_high_liquidity_setup_score_min=80.0, commission_bps_per_side=0, slippage_bps_per_side=0, sell_tax_bps=0)

    trades = build_signal_trades(events, path, config)

    assert trades["event_id"].tolist() == ["e2", "e3"]


def test_portfolio_respects_max_positions_and_summarizes() -> None:
    trades = pd.DataFrame(
        {
            "strategy_id": ["s", "s"],
            "event_id": ["e1", "e2"],
            "symbol": ["AAA", "BBB"],
            "time_split": ["validation_20", "validation_20"],
            "entry_date": ["2024-01-02", "2024-01-02"],
            "exit_date": ["2024-01-05", "2024-01-05"],
            "net_return_pct": [10.0, 10.0],
            "holding_days": [3, 3],
            "exit_reason": ["target", "target"],
        }
    )
    config = ExecutionConfig(strategy_id="s", max_positions=1, position_size_pct=0.5, initial_equity=100.0)

    portfolio, curve = run_portfolio(trades, config)
    summary = summarize_trades(portfolio, curve)

    assert int(portfolio["executed"].sum()) == 1
    assert summary["skipped"] == 1
    assert summary["total_return_pct"] == 5.0


def test_capacity_guard_caps_position_by_adtv() -> None:
    trades = pd.DataFrame(
        {
            "strategy_id": ["s"],
            "event_id": ["e1"],
            "symbol": ["AAA"],
            "time_split": ["validation_20"],
            "entry_date": ["2024-01-02"],
            "exit_date": ["2024-01-05"],
            "net_return_pct": [10.0],
            "holding_days": [3],
            "exit_reason": ["target"],
            "adtv20_value": [1_000.0],
        }
    )
    config = ExecutionConfig(strategy_id="s", position_size_pct=0.5, initial_equity=100_000_000.0, max_adtv_participation_pct=5.0, adtv_unit_multiplier=1_000.0)

    portfolio, curve = run_portfolio(trades, config)

    assert bool(portfolio.iloc[0]["capacity_limited"]) is True
    assert portfolio.iloc[0]["position_notional"] == 50_000.0
    assert curve.iloc[-1]["equity"] == 100_005_000.0


def test_target_adtv_guard_caps_position_without_changing_hard_capacity() -> None:
    trades = pd.DataFrame(
        {
            "strategy_id": ["s"],
            "event_id": ["e1"],
            "symbol": ["AAA"],
            "time_split": ["validation_20"],
            "entry_date": ["2024-01-02"],
            "exit_date": ["2024-01-05"],
            "net_return_pct": [10.0],
            "holding_days": [3],
            "exit_reason": ["target"],
            "adtv20_value": [1_000.0],
        }
    )
    config = ExecutionConfig(
        strategy_id="s",
        position_size_pct=0.5,
        initial_equity=100_000_000.0,
        max_adtv_participation_pct=30.0,
        target_adtv_participation_pct=5.0,
        adtv_unit_multiplier=1_000.0,
    )

    portfolio, curve = run_portfolio(trades, config)
    summary = summarize_trades(portfolio, curve)

    assert portfolio.iloc[0]["position_notional"] == 50_000.0
    assert portfolio.iloc[0]["adtv_participation_pct"] == 5.0
    assert portfolio.iloc[0]["capacity_limit_reason"] == "target_adtv"
    assert summary["median_adtv_participation_pct"] == 5.0
    assert summary["target_adtv_limited_rate_pct"] == 100.0


def test_capacity_guard_caps_position_by_entry_bar_value() -> None:
    trades = pd.DataFrame(
        {
            "strategy_id": ["s"],
            "event_id": ["e1"],
            "symbol": ["AAA"],
            "time_split": ["validation_20"],
            "entry_date": ["2024-01-02"],
            "exit_date": ["2024-01-05"],
            "net_return_pct": [10.0],
            "holding_days": [3],
            "exit_reason": ["target"],
            "entry_trade_value": [1_000_000.0],
            "exit_trade_value": [2_000_000.0],
        }
    )
    config = ExecutionConfig(strategy_id="s", position_size_pct=0.5, initial_equity=100_000_000.0, max_adtv_participation_pct=0.0, max_entry_bar_participation_pct=10.0)

    portfolio, _ = run_portfolio(trades, config)

    assert portfolio.iloc[0]["position_notional"] == 100_000.0
    assert portfolio.iloc[0]["entry_bar_participation_pct"] == 10.0


def test_risk_sizing_reduces_position_for_stretched_delayed_entry() -> None:
    trades = pd.DataFrame(
        {
            "strategy_id": ["s"],
            "event_id": ["e1"],
            "symbol": ["AAA"],
            "time_split": ["validation_20"],
            "entry_date": ["2024-01-02"],
            "exit_date": ["2024-01-05"],
            "net_return_pct": [10.0],
            "holding_days": [3],
            "exit_reason": ["target"],
            "entry_gap_pct": [4.0],
            "pre_entry_mae_pct": [1.0],
        }
    )
    config = ExecutionConfig(
        strategy_id="s",
        position_size_pct=0.5,
        initial_equity=1_000.0,
        risk_sizing_enabled=True,
        risk_high_multiplier=0.5,
    )

    portfolio, _ = run_portfolio(trades, config)
    row = portfolio.iloc[0]

    assert row["base_position_notional"] == 500.0
    assert row["risk_adjusted_base_notional"] == 250.0
    assert row["position_notional"] == 250.0
    assert row["risk_size_reason"] == "risk_reduce_entry_gap"
    assert bool(row["risk_sizing_limited"]) is True


def test_risk_sizing_boosts_clean_delayed_entry_without_future_data() -> None:
    trades = pd.DataFrame(
        {
            "strategy_id": ["s"],
            "event_id": ["e1"],
            "symbol": ["AAA"],
            "time_split": ["validation_20"],
            "entry_date": ["2024-01-02"],
            "exit_date": ["2024-01-05"],
            "net_return_pct": [10.0],
            "holding_days": [3],
            "exit_reason": ["target"],
            "entry_gap_pct": [1.0],
            "pre_entry_mae_pct": [1.0],
        }
    )
    config = ExecutionConfig(
        strategy_id="s",
        position_size_pct=0.5,
        initial_equity=1_000.0,
        risk_sizing_enabled=True,
        risk_low_multiplier=1.2,
    )

    portfolio, curve = run_portfolio(trades, config)
    summary = summarize_trades(portfolio, curve)
    row = portfolio.iloc[0]

    assert row["risk_adjusted_base_notional"] == 600.0
    assert row["position_notional"] == 600.0
    assert row["risk_size_reason"] == "risk_boost_clean_entry"
    assert summary["risk_boosted_rate_pct"] == 100.0
    assert summary["median_risk_size_multiplier"] == 1.2


def test_risk_sizing_reduces_weak_pre_entry_continuation() -> None:
    trades = pd.DataFrame(
        {
            "strategy_id": ["s"],
            "event_id": ["e1"],
            "symbol": ["AAA"],
            "time_split": ["validation_20"],
            "entry_date": ["2024-01-02"],
            "exit_date": ["2024-01-05"],
            "net_return_pct": [10.0],
            "holding_days": [3],
            "exit_reason": ["target"],
            "entry_gap_pct": [1.0],
            "pre_entry_mae_pct": [1.0],
            "pre_entry_continuation_score": [40.0],
        }
    )
    config = ExecutionConfig(
        strategy_id="s",
        position_size_pct=0.5,
        initial_equity=1_000.0,
        risk_sizing_enabled=True,
        risk_high_continuation_score_threshold=45.0,
        risk_high_multiplier=0.35,
    )

    portfolio, _ = run_portfolio(trades, config)
    row = portfolio.iloc[0]

    assert row["risk_adjusted_base_notional"] == 175.0
    assert row["risk_size_reason"] == "risk_reduce_weak_pre_entry_continuation"


def test_select_strategy_uses_validation_gate() -> None:
    rows = [
        {"strategy_id": "bad", "validation_trades": 12, "holdout_trades": 12, "validation_total_return_pct": -1.0, "validation_max_drawdown_pct": -5.0, "median_adtv_participation_pct": 3.0},
        {
            "strategy_id": "good",
            "validation_trades": 12,
            "holdout_trades": 12,
            "validation_total_return_pct": 3.0,
            "holdout_total_return_pct": 2.0,
            "validation_max_drawdown_pct": -5.0,
            "median_adtv_participation_pct": 3.0,
        },
    ]

    selected = select_strategy(rows)

    assert selected["status"] == "selected_tradable_setup"
    assert selected["selected_strategy_id"] == "good"


def test_select_strategy_ranks_by_pre_holdout_stability_after_validation_gate() -> None:
    rows = [
        {
            "strategy_id": "validation_only",
            "validation_trades": 12,
            "validation_total_return_pct": 2.5,
            "validation_win_rate_pct": 60.0,
            "validation_profit_factor": 1.8,
            "validation_max_drawdown_pct": -2.0,
            "holdout_trades": 12,
            "median_adtv_participation_pct": 3.0,
            "train_trades": 30,
            "train_total_return_pct": 2.0,
            "train_win_rate_pct": 52.0,
            "train_profit_factor": 1.2,
            "train_max_drawdown_pct": -5.0,
        },
        {
            "strategy_id": "stable",
            "validation_trades": 12,
            "validation_total_return_pct": 2.0,
            "validation_win_rate_pct": 62.0,
            "validation_profit_factor": 1.8,
            "validation_max_drawdown_pct": -2.0,
            "holdout_trades": 12,
            "median_adtv_participation_pct": 3.0,
            "train_trades": 30,
            "train_total_return_pct": 8.0,
            "train_win_rate_pct": 68.0,
            "train_profit_factor": 2.4,
            "train_max_drawdown_pct": -2.0,
        },
    ]

    selected = select_strategy(rows)

    assert selected["selected_strategy_id"] == "stable"
    assert "pre_holdout" in selected["selection_basis"]


def test_walk_forward_selects_on_prior_events_only() -> None:
    events = pd.DataFrame(
        {
            "event_id": [f"e{i}" for i in range(1, 13)],
            "symbol": [f"S{i}" for i in range(1, 13)],
            "breakout_date": pd.date_range("2024-01-01", periods=12, freq="D").astype(str),
            "breakout_price": [100.0] * 12,
            "target_dist_pct": [10.0] * 12,
            "time_split": ["train_60"] * 12,
        }
    )
    path_rows = []
    for event_id in events["event_id"]:
        path_rows.append(
            {
                "event_id": event_id,
                "symbol": event_id,
                "trade_date": "2024-02-01",
                "bar_after_breakout": 1,
                "open": 100.0,
                "high": 110.0,
                "low": 99.0,
                "close": 109.0,
            }
        )
    path = pd.DataFrame(path_rows)
    configs = (
        ExecutionConfig(strategy_id="fast", target_multiple=0.46, stop_loss_pct=5.0, max_holding_days=5, commission_bps_per_side=0, slippage_bps_per_side=0, sell_tax_bps=0),
    )

    folds, trades, summary = run_walk_forward_validation(events, path, configs, min_train_events=6, test_events=3)

    assert len(folds) == 2
    assert summary["status"] == "walk_forward_complete"
    assert int(trades["executed"].sum()) == 6


def test_fixed_walk_forward_keeps_selected_strategy_constant() -> None:
    events = pd.DataFrame(
        {
            "event_id": [f"e{i}" for i in range(1, 13)],
            "symbol": [f"S{i}" for i in range(1, 13)],
            "breakout_date": pd.date_range("2024-01-01", periods=12, freq="D").astype(str),
            "breakout_price": [100.0] * 12,
            "target_dist_pct": [10.0] * 12,
            "time_split": ["train_60"] * 12,
        }
    )
    path = pd.DataFrame(
        {
            "event_id": events["event_id"].tolist(),
            "symbol": events["symbol"].tolist(),
            "trade_date": ["2024-02-01"] * 12,
            "bar_after_breakout": [1] * 12,
            "open": [100.0] * 12,
            "high": [110.0] * 12,
            "low": [99.0] * 12,
            "close": [109.0] * 12,
        }
    )
    config = ExecutionConfig(strategy_id="fixed", target_multiple=0.46, stop_loss_pct=5.0, commission_bps_per_side=0, slippage_bps_per_side=0, sell_tax_bps=0)

    folds, trades, summary = run_fixed_strategy_walk_forward(events, path, config, min_train_events=6, test_events=3)

    assert len(folds) == 2
    assert set(folds["strategy_id"]) == {"fixed"}
    assert summary["status"] == "fixed_walk_forward_complete"
    assert int(trades["executed"].sum()) == 6


def test_calendar_oos_reports_yearly_rows() -> None:
    events = pd.DataFrame(
        {
            "event_id": ["e1", "e2"],
            "symbol": ["AAA", "BBB"],
            "breakout_date": ["2023-01-01", "2024-01-01"],
            "breakout_price": [100.0, 100.0],
            "target_dist_pct": [10.0, 10.0],
            "time_split": ["train_60", "holdout_20"],
        }
    )
    path = pd.DataFrame(
        {
            "event_id": ["e1", "e2"],
            "symbol": ["AAA", "BBB"],
            "trade_date": ["2023-01-02", "2024-01-02"],
            "bar_after_breakout": [1, 1],
            "open": [100.0, 100.0],
            "high": [110.0, 110.0],
            "low": [99.0, 99.0],
            "close": [109.0, 109.0],
        }
    )
    config = ExecutionConfig(strategy_id="calendar", target_multiple=0.46, stop_loss_pct=5.0, commission_bps_per_side=0, slippage_bps_per_side=0, sell_tax_bps=0)

    table, summary = run_calendar_oos_validation(events, path, config)

    assert table["year"].tolist() == [2023, 2024]
    assert summary["years"] == 2


def test_daily_mark_to_market_curve_tracks_open_exposure() -> None:
    trades = pd.DataFrame(
        {
            "executed": [True],
            "event_id": ["e1"],
            "entry_date": ["2024-01-02"],
            "exit_date": ["2024-01-04"],
            "entry_price": [100.0],
            "position_notional": [100.0],
            "pnl": [10.0],
        }
    )
    path = pd.DataFrame(
        {
            "event_id": ["e1", "e1", "e1"],
            "trade_date": ["2024-01-02", "2024-01-03", "2024-01-04"],
            "close": [100.0, 105.0, 110.0],
        }
    )
    config = ExecutionConfig(strategy_id="mtm", initial_equity=1000.0)

    curve, summary = build_daily_mark_to_market_curve(trades, path, config)

    assert summary["status"] == "daily_mtm_complete"
    assert int(curve["open_positions"].max()) == 1
    assert curve.iloc[-1]["equity"] == 1010.0


def test_monte_carlo_reports_positive_probability() -> None:
    trades = pd.DataFrame(
        {
            "executed": [True, True, True],
            "net_return_pct": [5.0, 2.0, -1.0],
        }
    )
    config = ExecutionConfig(strategy_id="s", position_size_pct=0.1, initial_equity=100.0)

    sims, summary = monte_carlo_trade_sequence(trades, config, iterations=100, seed=1)

    assert len(sims) == 100
    assert summary["prob_positive_pct"] > 50.0


def test_monte_carlo_handles_profiles_without_executed_trades() -> None:
    trades = pd.DataFrame({"executed": [False], "skip_reason": ["filter"]})
    config = ExecutionConfig(strategy_id="s")

    sims, summary = monte_carlo_trade_sequence(trades, config, iterations=10, seed=1)

    assert sims.empty
    assert summary["status"] == "no_executed_trades"


def test_cost_stress_handles_profiles_without_executed_trades() -> None:
    events = pd.DataFrame(
        {
            "event_id": ["e1"],
            "symbol": ["AAA"],
            "breakout_date": ["2024-01-01"],
            "breakout_price": [100.0],
            "target_dist_pct": [10.0],
            "time_split": ["validation_20"],
            "setup_score": [10.0],
        }
    )
    path = pd.DataFrame(
        {
            "event_id": ["e1"],
            "symbol": ["AAA"],
            "trade_date": ["2024-01-02"],
            "bar_after_breakout": [1],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.0],
        }
    )
    config = ExecutionConfig(strategy_id="stress", min_setup_score=90.0)

    stress, summary = run_cost_stress(events, path, config)

    assert len(stress) == 7
    assert summary["status"] == "cost_stress_complete"
    assert summary["worst_scenario_return_pct"] is None


def test_scorecard_classifies_strong_diagnostics() -> None:
    selection = {
        "status": "selected_tradable_setup",
        "selected_metrics": {
            "validation_total_return_pct": 5.0,
            "validation_trades": 12,
            "validation_max_drawdown_pct": -2.0,
            "holdout_total_return_pct": 5.0,
            "holdout_trades": 12,
            "holdout_max_drawdown_pct": -2.0,
            "max_adtv_participation_pct": 20.0,
            "median_adtv_participation_pct": 3.0,
            "skipped": 0,
            "trades": 65,
        },
    }
    walk_forward = {"positive_fold_rate_pct": 100.0, "sum_fold_return_pct": 8.0, "test_trades": 40, "worst_fold_drawdown_pct": -2.0}
    stress = {"positive_scenario_rate_pct": 100.0, "worst_scenario_return_pct": 12.0, "worst_scenario_drawdown_pct": -3.0}
    monte_carlo = {"prob_positive_pct": 95.0, "total_return_p05_pct": 5.0, "total_return_p50_pct": 20.0}

    scorecard = score_tradable_setup(selection, walk_forward, stress, monte_carlo)

    assert scorecard["score"] >= 90
    assert scorecard["classification"] == "tradable-research-candidate"


def test_frozen_rule_contract_contains_context_guard() -> None:
    config = ExecutionConfig(
        strategy_id="guard",
        exclude_bear_high_liquidity_setup_score_min=80.0,
        risk_sizing_enabled=True,
        max_entry_gap_pct=2.5,
        min_pre_entry_continuation_score=55.0,
        target_adtv_participation_pct=5.0,
        min_breakout_date="2019-01-01",
        allowed_market_regimes=("bull", "bear"),
    )

    contract = frozen_rule_contract(config)

    assert contract["sizing"]["target_adtv_participation_pct"] == 5.0
    assert contract["execution_filters"]["min_breakout_date"] == "2019-01-01"
    assert contract["execution_filters"]["allowed_market_regimes"] == ("bull", "bear")
    assert contract["execution_filters"]["exclude_bear_high_liquidity_setup_score_min"] == 80.0
    assert contract["continuation_entry"]["max_entry_gap_pct"] == 2.5
    assert contract["continuation_entry"]["min_pre_entry_continuation_score"] == 55.0
    assert contract["risk_sizing"]["risk_sizing_enabled"] is True
    assert contract["risk_sizing"]["uses_entry_time_information_only"] is True
    assert contract["rule_version"].startswith("bull_flag_tradable_risk_sized_continuation@")


def test_robustness_normalizes_legacy_profile_scores() -> None:
    events = pd.DataFrame(
        {
            "detection_id": ["e1"],
            "symbol": ["AAA"],
            "breakout_direction": ["up"],
            "breakout_price": [100.0],
            "target_dist_pct": [10.0],
            "pole_move_pct": [12.0],
            "pole_slope_deg": [10.0],
            "flag_to_pole_pct": [40.0],
            "slope_gap_deg": [2.0],
            "pattern_height_pct": [6.0],
            "volume_confirmed": [True],
        }
    )
    path = pd.DataFrame(
        {
            "event_id": ["e1", "e1"],
            "bar_after_breakout": [1, 2],
            "signed_high_excursion_pct": [2.0, 6.0],
            "signed_low_excursion_pct": [-1.0, -2.0],
            "signed_close_return_pct": [1.0, 4.0],
        }
    )

    scored, info = normalize_profile_schema(events, path, source_dir=Path("__missing_source_dir__"))

    assert info["schema_status"] == "derived_v2_scores"
    assert {"setup_score", "confirmation_score", "followthrough_score"}.issubset(scored.columns)


def test_robustness_gate_fails_when_profile_pass_rate_is_low() -> None:
    gate = robustness_gate(
        {
            "eligible_profiles": 16,
            "pass_90_rate_pct": 12.5,
            "pass_95_rate_pct": 12.5,
            "incompatible_schema_profiles": 0,
        }
    )

    assert gate["status"] == "fail"
    assert "pass_90_rate_below_60pct" in gate["failures"]
