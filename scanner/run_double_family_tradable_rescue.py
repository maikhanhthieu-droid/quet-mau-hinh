"""Family-level tradable rescue for Double Bottoms and Double Tops.

The individual Adam/Eve variants are often too thin for validation/holdout
trade-count gates. This audit asks a stricter and more useful question:
whether the Double Pattern family has a source-safe executable branch that can
carry tradable evidence, while keeping each variant as a reported subgroup
instead of pretending every variant has enough standalone depth.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.run_chapter_tradable_layer import (  # noqa: E402
    GenericExecutionConfig,
    _assign_time_splits,
    _attach_adtv,
    _attach_scores,
    _bool_series,
    _read_csv,
    evaluate_strategy,
    run_cost_stress,
    run_monte_carlo,
    run_walk_forward,
    score_tradable_setup,
)


AUDIT_ID = "double_family_tradable_rescue_v1"
NO_OVERLIFT_POLICY_ID = "double_family_no_overlift_guard_v1"
OUT_DIR = Path("artifacts/scanner_v2/double_family_tradable_rescue")
FAMILIES = ("double_bottoms", "double_tops")
CLASSIFIED_VARIANTS = ("AA", "AE", "EA", "EE")


@dataclass(frozen=True)
class BranchRule:
    branch_id: str
    description: str
    quality_scope: str
    predicate: Callable[[pd.DataFrame], pd.Series]


@dataclass(frozen=True)
class EntryRule:
    rule_id: str
    kind: str
    max_wait_bars: int = 10
    retest_tolerance_pct: float = 1.0
    max_close_through_breakout_pct: float = 1.0
    min_confirm_return_pct: float = 1.0
    confirm_after_bars: int = 2
    max_pre_entry_mae_pct: float = 7.0


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _score_between(value: Any, low: float, high: float) -> float:
    numeric = _as_float(value, default=low)
    if high == low:
        return 100.0 if numeric >= high else 0.0
    return max(0.0, min(100.0, (numeric - low) / (high - low) * 100.0))


def _num(frame: pd.DataFrame, column: str, default: float = np.nan) -> pd.Series:
    if column not in frame:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _cat(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series("", index=frame.index, dtype="object")
    return frame[column].astype(str)


def _liq(frame: pd.DataFrame, *buckets: str) -> pd.Series:
    return _cat(frame, "liquidity_bucket").isin(buckets)


def _regime(frame: pd.DataFrame, *regimes: str) -> pd.Series:
    return _cat(frame, "market_regime").isin(regimes)


def _direction(family: str) -> tuple[str, ...]:
    return ("up",) if family == "double_bottoms" else ("down",)


def _scope(family: str) -> str:
    return "long_cash_candidate" if family == "double_bottoms" else "defensive_informational"


def _events_path(family: str) -> Path:
    return Path(f"artifacts/scanner_v2/double_pattern_family/{family}/db_active/events.csv")


def _path_path(family: str) -> Path:
    return Path(f"artifacts/scanner_v2/double_pattern_family/{family}/db_active/post_breakout_path.csv")


def _quality_mask(events: pd.DataFrame, quality_scope: str) -> pd.Series:
    variants = _cat(events, "variant").isin(CLASSIFIED_VARIANTS)
    if quality_scope == "standard_premium":
        quality = _cat(events, "publication_quality_tier").isin(("standard", "premium"))
    elif quality_scope == "loose_plus":
        quality = _cat(events, "publication_quality_tier").isin(("standard", "premium", "loose"))
    elif quality_scope == "all_classified":
        quality = pd.Series(True, index=events.index)
    else:
        raise ValueError(f"Unsupported quality_scope: {quality_scope}")
    primary = _bool_series(events["is_primary_event_60d"]) if "is_primary_event_60d" in events.columns else pd.Series(True, index=events.index)
    return variants & quality & primary


def _load_family(family: str, quality_scope: str) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    events_raw = _read_csv(_events_path(family))
    path_raw = _read_csv(_path_path(family))
    if events_raw.empty or path_raw.empty:
        return pd.DataFrame(), pd.DataFrame(), {"status": "missing_events_or_path"}
    events = events_raw[_quality_mask(events_raw, quality_scope)].copy()
    for col in ("breakout_price", "target_dist_pct", "b_exec_price", "mfe_pct", "mae_pct"):
        if col in events.columns:
            events[col] = pd.to_numeric(events[col], errors="coerce")
    for col in ("bar_after_breakout", "open", "high", "low", "close", "volume"):
        if col in path_raw.columns:
            path_raw[col] = pd.to_numeric(path_raw[col], errors="coerce")
    events = _attach_scores(events)
    event_ids = set(events["event_id"].astype(str))
    path = path_raw[path_raw["event_id"].astype(str).isin(event_ids)].copy()
    events = _attach_adtv(events, path)
    events = _assign_time_splits(events)
    scoped_ids = set(events["event_id"].astype(str))
    path = path[path["event_id"].astype(str).isin(scoped_ids)].copy()
    return (
        events.reset_index(drop=True),
        path.reset_index(drop=True),
        {
            "status": "loaded",
            "family": family,
            "quality_scope": quality_scope,
            "events_raw": int(len(events_raw)),
            "events_scoped": int(len(events)),
            "path_rows": int(len(path)),
            "variant_counts": events["variant"].astype(str).value_counts().to_dict(),
            "split_counts": events["time_split"].astype(str).value_counts().to_dict(),
            "scope": _scope(family),
        },
    )


def build_branch_rules(family: str) -> list[BranchRule]:
    direction = _direction(family)[0]
    rules = [
        BranchRule("loose_plus_family", "Classified variants with loose-or-better quality.", "loose_plus", lambda f: pd.Series(True, index=f.index)),
        BranchRule("standard_premium_family", "Classified variants with standard/premium quality.", "standard_premium", lambda f: pd.Series(True, index=f.index)),
        BranchRule("non_aa_variants", "Non-AA variants grouped to recover depth.", "loose_plus", lambda f: _cat(f, "variant").isin(("AE", "EA", "EE"))),
        BranchRule("mid_high_liquidity", "Mid/high liquidity family branch.", "loose_plus", lambda f: _liq(f, "mid", "high")),
        BranchRule("high_liquidity", "High liquidity family branch.", "loose_plus", lambda f: _liq(f, "high")),
        BranchRule("balanced_extremes", "Balanced double pattern with close extreme symmetry.", "loose_plus", lambda f: _num(f, "balance_ratio").between(0.30, 0.80) & (_num(f, "extreme_spread_pct") <= 3.75)),
        BranchRule("clean_neckline", "Clear neckline break with moderate height.", "loose_plus", lambda f: _num(f, "pattern_height_pct").between(6.0, 24.0) & (_num(f, "breakout_clearance_pct") >= 1.0)),
        BranchRule("volume_confirmed", "Breakout volume confirmation.", "loose_plus", lambda f: _num(f, "breakout_volume_ratio", 0.0) >= 1.20),
    ]
    if family == "double_bottoms":
        rules.extend(
            [
                BranchRule("bottom_reversal_core", "Prior decline, balanced bottom, and mid/high liquidity.", "loose_plus", lambda f: (_num(f, "prior_trend_pct") >= 6.0) & _num(f, "balance_ratio").between(0.30, 0.80) & _liq(f, "mid", "high")),
                BranchRule("eve_mixed_reversal", "Any Eve-side bottom variant with mid/high liquidity.", "loose_plus", lambda f: _cat(f, "variant").isin(("AE", "EA", "EE")) & _liq(f, "mid", "high")),
                BranchRule("bull_clean_breakout", "Bull-regime clean double-bottom breakout.", "loose_plus", lambda f: _regime(f, "bull") & (_num(f, "breakout_clearance_pct") >= 1.0) & _cat(f, "breakout_direction").eq(direction)),
            ]
        )
    else:
        rules.extend(
            [
                BranchRule("top_defensive_core", "Prior rise, balanced top, and mid/high liquidity.", "loose_plus", lambda f: (_num(f, "prior_trend_pct") >= 6.0) & _num(f, "balance_ratio").between(0.30, 0.80) & _liq(f, "mid", "high")),
                BranchRule("bull_high_liq_breakdown", "Bull-regime high-liquidity breakdown.", "loose_plus", lambda f: _regime(f, "bull") & _liq(f, "high") & _cat(f, "breakout_direction").eq(direction)),
                BranchRule("upper_range_breakdown", "Breakdown from elevated yearly range.", "loose_plus", lambda f: _num(f, "yearly_range_position_pct", 50.0).between(45.0, 95.0) & _liq(f, "mid", "high")),
            ]
        )
    return rules


def build_entry_rules() -> list[EntryRule]:
    return [
        EntryRule("fixed_open_d1", "fixed", max_wait_bars=1),
        EntryRule("fixed_open_d3", "fixed", max_wait_bars=3),
        EntryRule("neckline_retest_10pct_10d", "retest", max_wait_bars=10, retest_tolerance_pct=1.0, max_pre_entry_mae_pct=7.0),
        EntryRule("neckline_retest_15pct_15d", "retest", max_wait_bars=15, retest_tolerance_pct=1.5, max_pre_entry_mae_pct=8.0),
        EntryRule("confirm_1pct_3d", "confirm", max_wait_bars=5, min_confirm_return_pct=1.0, confirm_after_bars=3, max_pre_entry_mae_pct=6.0),
        EntryRule("retest_reclaim_10d", "retest_reclaim", max_wait_bars=10, retest_tolerance_pct=1.0, min_confirm_return_pct=0.5, max_pre_entry_mae_pct=7.0),
    ]


def _pre_entry_mae_pct(group: pd.DataFrame, breakout_price: float, entry_bar: int, direction: str) -> float:
    pre = group[pd.to_numeric(group["bar_after_breakout"], errors="coerce") <= entry_bar]
    if pre.empty or breakout_price <= 0:
        return 999.0
    if direction == "up":
        return max(0.0, (breakout_price - float(pd.to_numeric(pre["low"], errors="coerce").min())) / breakout_price * 100.0)
    return max(0.0, (float(pd.to_numeric(pre["high"], errors="coerce").max()) - breakout_price) / breakout_price * 100.0)


def _find_entry_bar(event: Mapping[str, Any], group: pd.DataFrame, rule: EntryRule) -> int | None:
    breakout_price = _as_float(event.get("breakout_price"))
    direction = str(event.get("breakout_direction") or "").lower()
    if breakout_price <= 0 or group.empty or direction not in {"up", "down"}:
        return None
    work = group.copy()
    work["bar_after_breakout"] = pd.to_numeric(work["bar_after_breakout"], errors="coerce")
    work = work[(work["bar_after_breakout"] >= 1) & (work["bar_after_breakout"] <= int(rule.max_wait_bars))]
    if work.empty:
        return None
    if rule.kind == "fixed":
        return min(int(rule.max_wait_bars), int(work["bar_after_breakout"].min()))
    retested = False
    for _, row in work.sort_values("bar_after_breakout").iterrows():
        bar = int(row["bar_after_breakout"])
        if _pre_entry_mae_pct(group, breakout_price, bar, direction) > float(rule.max_pre_entry_mae_pct):
            continue
        high = _as_float(row.get("high"))
        low = _as_float(row.get("low"))
        close = _as_float(row.get("close"))
        if direction == "up":
            retest_ok = low <= breakout_price * (1.0 + float(rule.retest_tolerance_pct) / 100.0)
            reclaim_ok = close >= breakout_price * (1.0 - float(rule.max_close_through_breakout_pct) / 100.0)
            confirm_ok = bar >= int(rule.confirm_after_bars) and close >= breakout_price * (1.0 + float(rule.min_confirm_return_pct) / 100.0)
            reclaim_trigger = close >= breakout_price * (1.0 + float(rule.min_confirm_return_pct) / 100.0)
        else:
            retest_ok = high >= breakout_price * (1.0 - float(rule.retest_tolerance_pct) / 100.0)
            reclaim_ok = close <= breakout_price * (1.0 + float(rule.max_close_through_breakout_pct) / 100.0)
            confirm_ok = bar >= int(rule.confirm_after_bars) and close <= breakout_price * (1.0 - float(rule.min_confirm_return_pct) / 100.0)
            reclaim_trigger = close <= breakout_price * (1.0 - float(rule.min_confirm_return_pct) / 100.0)
        if rule.kind == "retest" and retest_ok and reclaim_ok:
            return bar
        if rule.kind == "confirm" and confirm_ok:
            return bar
        if rule.kind == "retest_reclaim":
            retested = retested or retest_ok
            if retested and reclaim_trigger:
                return bar
    return None


def prepare_entry_branch(events: pd.DataFrame, path: pd.DataFrame, rule: EntryRule) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if events.empty or path.empty:
        return pd.DataFrame(), pd.DataFrame(), {"entry_rule": rule.rule_id, "eligible_events": 0}
    groups = {str(event_id): group.sort_values("bar_after_breakout").copy() for event_id, group in path.groupby("event_id", dropna=False)}
    event_rows: list[dict[str, Any]] = []
    path_rows: list[dict[str, Any]] = []
    wait_bars: list[int] = []
    for _, event in events.iterrows():
        event_id = str(event.get("event_id"))
        group = groups.get(event_id, pd.DataFrame())
        entry_bar = _find_entry_bar(event.to_dict(), group, rule)
        if entry_bar is None:
            continue
        transformed = event.to_dict()
        transformed["entry_branch_rule"] = rule.rule_id
        transformed["dynamic_entry_wait_bars"] = int(entry_bar)
        event_rows.append(transformed)
        wait_bars.append(int(entry_bar))
        sub = group[pd.to_numeric(group["bar_after_breakout"], errors="coerce") >= int(entry_bar)].copy()
        sub["original_bar_after_breakout"] = sub["bar_after_breakout"]
        sub["bar_after_breakout"] = pd.to_numeric(sub["bar_after_breakout"], errors="coerce") - int(entry_bar) + 1
        path_rows.extend(sub.to_dict("records"))
    prepared_events = pd.DataFrame(event_rows)
    prepared_path = pd.DataFrame(path_rows)
    return (
        prepared_events,
        prepared_path,
        {
            "entry_rule": rule.rule_id,
            "kind": rule.kind,
            "source_events": int(len(events)),
            "eligible_events": int(len(prepared_events)),
            "eligibility_rate_pct": round(float(len(prepared_events) / len(events) * 100.0), 2) if len(events) else None,
            "median_entry_wait_bars": round(float(pd.Series(wait_bars).median()), 2) if wait_bars else None,
            "rule": asdict(rule),
        },
    )


def build_configs(family: str) -> list[GenericExecutionConfig]:
    direction = _direction(family)
    configs: list[GenericExecutionConfig] = []
    target_family = (0.50, 0.65, 0.75) if family == "double_bottoms" else (0.35, 0.50, 0.75)
    for target in target_family:
        for stop in (7.0, 10.0):
            for hold in (20, 60):
                for setup in (None, 65.0):
                    for position_size, max_positions in ((0.033, 30), (0.075, 12)):
                        configs.append(
                            GenericExecutionConfig(
                                strategy_id=(
                                    f"{family}__family_t{str(target).replace('.', '')}_s{int(stop)}"
                                    f"_h{hold}_q{int(setup or 0)}_p{str(position_size).replace('.', '')}_m{max_positions}"
                                ),
                                target_multiple=target,
                                stop_loss_pct=stop,
                                max_holding_days=hold,
                                entry_delay_bars=1,
                                min_setup_score=setup,
                                allowed_breakout_directions=direction,
                                position_size_pct=position_size,
                                max_positions=max_positions,
                                max_adtv_participation_pct=30.0,
                                target_adtv_participation_pct=5.0,
                            )
                        )
    return configs


def _utility(row: Mapping[str, Any], prefix: str = "") -> float:
    key = lambda name: f"{prefix}_{name}" if prefix else name
    return (
        0.28 * _score_between(row.get(key("total_return_pct")), 0.0, 8.0)
        + 0.18 * _score_between(row.get(key("max_drawdown_pct")), -10.0, -2.0)
        + 0.18 * _score_between(row.get(key("win_rate_pct")), 45.0, 68.0)
        + 0.16 * _score_between(row.get(key("trades")), 10.0, 45.0)
        + 0.10 * _score_between(row.get(key("profit_factor")), 1.0, 2.5)
        + 0.10 * _score_between(8.0 - _as_float(row.get("median_adtv_participation_pct"), default=8.0), 0.0, 8.0)
    )


def _candidate_score(row: Mapping[str, Any]) -> float:
    return 0.62 * _utility(row, "validation") + 0.28 * _utility(row, "train") + 0.10 * _score_between(row.get("eligible_events"), 35.0, 220.0)


def _branch_events(events_by_scope: Mapping[str, tuple[pd.DataFrame, pd.DataFrame, Mapping[str, Any]]], branch: BranchRule) -> tuple[pd.DataFrame, pd.DataFrame, Mapping[str, Any]]:
    events, path, source_scope = events_by_scope[branch.quality_scope]
    if events.empty:
        return pd.DataFrame(), pd.DataFrame(), source_scope
    mask = branch.predicate(events).reindex(events.index).fillna(False).astype(bool)
    scoped = events[mask].copy()
    scoped["double_family_branch_id"] = branch.branch_id
    event_ids = set(scoped["event_id"].astype(str))
    return scoped.reset_index(drop=True), path[path["event_id"].astype(str).isin(event_ids)].copy(), source_scope


def _first_pass(family: str, shortlist_size: int) -> tuple[list[dict[str, Any]], list[tuple[BranchRule, EntryRule, GenericExecutionConfig, Mapping[str, Any]]], dict[str, Any]]:
    events_by_scope = {scope: _load_family(family, scope) for scope in ("loose_plus", "standard_premium", "all_classified")}
    branches = build_branch_rules(family)
    entry_rules = build_entry_rules()
    configs = build_configs(family)
    quick_rows: list[dict[str, Any]] = []
    prepared_cache: dict[tuple[str, str], tuple[pd.DataFrame, pd.DataFrame, Mapping[str, Any], BranchRule, EntryRule]] = {}
    config_by_id = {config.strategy_id: config for config in configs}
    for branch in branches:
        branch_events, branch_path, _ = _branch_events(events_by_scope, branch)
        print(f"[double-family] {family}: branch={branch.branch_id} source_events={len(branch_events)}", flush=True)
        if len(branch_events) < 24:
            continue
        split_counts = branch_events.get("time_split", pd.Series("", index=branch_events.index)).value_counts().to_dict()
        if min(int(split_counts.get(split, 0)) for split in ("train_60", "validation_20", "holdout_20")) < 5:
            continue
        for entry_rule in entry_rules:
            prepared_events, prepared_path, entry_meta = prepare_entry_branch(branch_events, branch_path, entry_rule)
            print(
                f"[double-family] {family}: branch={branch.branch_id} entry={entry_rule.rule_id} eligible={len(prepared_events)}",
                flush=True,
            )
            prepared_cache[(branch.branch_id, entry_rule.rule_id)] = (prepared_events, prepared_path, entry_meta, branch, entry_rule)
            if len(prepared_events) < 24:
                continue
            split_counts = prepared_events.get("time_split", pd.Series("", index=prepared_events.index)).value_counts().to_dict()
            if min(int(split_counts.get(split, 0)) for split in ("train_60", "validation_20", "holdout_20")) < 5:
                continue
            for config in configs:
                summary, _, _ = evaluate_strategy(prepared_events, prepared_path, config)
                quick_rows.append(
                    summary
                    | {
                        "family": family,
                        "branch_id": branch.branch_id,
                        "branch_description": branch.description,
                        "quality_scope": branch.quality_scope,
                        "entry_rule": entry_rule.rule_id,
                        "entry_rule_kind": entry_rule.kind,
                        "eligible_events": entry_meta.get("eligible_events"),
                        "eligibility_rate_pct": entry_meta.get("eligibility_rate_pct"),
                        "median_entry_wait_bars": entry_meta.get("median_entry_wait_bars"),
                    }
                )
    passing = [
        row
        for row in quick_rows
        if _as_int(row.get("validation_trades")) >= 8
        and _as_int(row.get("holdout_trades")) >= 8
        and _as_float(row.get("validation_total_return_pct"), default=-999.0) > 0.0
        and _as_float(row.get("median_adtv_participation_pct"), default=999.0) <= 8.0
    ]
    pool = passing if passing else quick_rows
    ranked = sorted(pool, key=_candidate_score, reverse=True)
    selected: list[tuple[BranchRule, EntryRule, GenericExecutionConfig, Mapping[str, Any]]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in ranked:
        key = (str(row.get("branch_id")), str(row.get("entry_rule")), str(row.get("strategy_id")))
        if key in seen:
            continue
        prepared = prepared_cache.get((key[0], key[1]))
        config = config_by_id.get(key[2])
        if prepared is None or config is None:
            continue
        _, _, entry_meta, branch, entry_rule = prepared
        selected.append((branch, entry_rule, config, entry_meta))
        seen.add(key)
        if len(selected) >= shortlist_size:
            break
    meta = {
        "family": family,
        "branch_count": len(branches),
        "entry_rule_count": len(entry_rules),
        "config_count": len(configs),
        "first_pass_count": len(quick_rows),
        "first_pass_passing_count": len(passing),
        "source_scopes": {key: value[2] for key, value in events_by_scope.items()},
    }
    return quick_rows, selected, meta


def _variant_trade_stats(trades: pd.DataFrame, events: pd.DataFrame) -> dict[str, Any]:
    if trades.empty or events.empty:
        return {}
    variant_map = events.set_index(events["event_id"].astype(str))["variant"].astype(str).to_dict()
    working = trades[trades.get("executed", pd.Series(False, index=trades.index)) == True].copy()
    if working.empty:
        return {}
    working["variant"] = working["event_id"].astype(str).map(variant_map).fillna("unknown")
    out: dict[str, Any] = {}
    for variant, group in working.groupby("variant"):
        returns = pd.to_numeric(group["net_return_pct"], errors="coerce").dropna()
        out[str(variant)] = {
            "trades": int(len(group)),
            "avg_net_return_pct": round(float(returns.mean()), 2) if not returns.empty else None,
            "win_rate_pct": round(float((returns > 0).mean()) * 100.0, 2) if not returns.empty else None,
        }
    return out


def _evaluate_full_candidate(
    family: str,
    branch: BranchRule,
    entry_rule: EntryRule,
    config: GenericExecutionConfig,
) -> dict[str, Any]:
    events_by_scope = {branch.quality_scope: _load_family(family, branch.quality_scope)}
    branch_events, branch_path, source_scope = _branch_events(events_by_scope, branch)
    events, path, entry_meta = prepare_entry_branch(branch_events, branch_path, entry_rule)
    summary, trades, _ = evaluate_strategy(events, path, config)
    _, _, fixed_folds, fixed_summary = run_walk_forward(events, path, [config], config)
    _, cost_summary = run_cost_stress(events, path, config)
    _, mc_summary = run_monte_carlo(trades, config, iterations=500)
    selection = {
        "status": "selected_tradable_setup",
        "selection_basis": "Double Pattern family rescue; branch/entry chosen on train+validation shortlist; holdout/walk-forward are promotion evidence",
        "selected_strategy_id": f"{branch.branch_id}__{entry_rule.rule_id}__{config.strategy_id}",
        "selected_metrics": summary,
    }
    scorecard = score_tradable_setup(selection, fixed_summary, cost_summary, mc_summary)
    negative_folds = int((pd.to_numeric(fixed_folds.get("test_total_return_pct"), errors="coerce") < 0).sum()) if not fixed_folds.empty else None
    return {
        "family": family,
        "scope": _scope(family),
        "branch_id": branch.branch_id,
        "branch_description": branch.description,
        "quality_scope": branch.quality_scope,
        "entry_rule": entry_rule.rule_id,
        "entry_rule_kind": entry_rule.kind,
        "strategy_id": f"{branch.branch_id}__{entry_rule.rule_id}__{config.strategy_id}",
        "base_strategy_id": config.strategy_id,
        "eligible_events": entry_meta.get("eligible_events"),
        "eligibility_rate_pct": entry_meta.get("eligibility_rate_pct"),
        "median_entry_wait_bars": entry_meta.get("median_entry_wait_bars"),
        "score": scorecard.get("score"),
        "classification": scorecard.get("classification"),
        "promotion_blockers": ",".join(scorecard.get("promotion_blockers") or []),
        "trades": summary.get("trades"),
        "validation_trades": summary.get("validation_trades"),
        "validation_total_return_pct": summary.get("validation_total_return_pct"),
        "holdout_trades": summary.get("holdout_trades"),
        "holdout_total_return_pct": summary.get("holdout_total_return_pct"),
        "total_return_pct": summary.get("total_return_pct"),
        "max_drawdown_pct": summary.get("max_drawdown_pct"),
        "median_adtv_participation_pct": summary.get("median_adtv_participation_pct"),
        "walk_forward_positive_fold_rate_pct": fixed_summary.get("positive_fold_rate_pct"),
        "walk_forward_negative_folds": negative_folds,
        "walk_forward_sum_return_pct": fixed_summary.get("sum_fold_return_pct"),
        "walk_forward_worst_fold_return_pct": fixed_summary.get("worst_fold_return_pct"),
        "cost_positive_scenario_rate_pct": cost_summary.get("positive_scenario_rate_pct"),
        "cost_worst_scenario_return_pct": cost_summary.get("worst_scenario_return_pct"),
        "monte_carlo_prob_positive_pct": mc_summary.get("prob_positive_pct"),
        "scorecard_component_scores": scorecard.get("component_scores"),
        "variant_trade_stats": _variant_trade_stats(trades, events),
        "source_scope": source_scope,
        "selected_config": asdict(config),
    }


def _guard(best: Mapping[str, Any], family: str) -> dict[str, Any]:
    blockers = {item.strip() for item in str(best.get("promotion_blockers") or "").split(",") if item.strip()}
    if family == "double_tops":
        blockers.add("scope_not_direct_long_cash_equity")
    checks = [
        {"check": "score_threshold_95", "status": "fail" if _as_float(best.get("score")) < 95.0 else "pass", "observed": best.get("score"), "rule": "family rescue promotion requires score >= 95"},
        {"check": "promotion_blockers_clear", "status": "fail" if blockers else "pass", "observed": ",".join(sorted(blockers)) or "none", "rule": "family rescue must have no hard blocker"},
        {"check": "fixed_walk_forward_positive", "status": "fail" if _as_float(best.get("walk_forward_positive_fold_rate_pct")) < 100.0 else "pass", "observed": best.get("walk_forward_positive_fold_rate_pct"), "rule": "fixed walk-forward must have no negative fold"},
        {"check": "direct_long_cash_scope", "status": "fail" if family == "double_tops" else "pass", "observed": _scope(family), "rule": "downside family can only be defensive/informational on cash equities"},
    ]
    failures = [item["check"] for item in checks if item["status"] == "fail"]
    return {
        "policy_id": NO_OVERLIFT_POLICY_ID,
        "promotion_decision": "ELIGIBLE_FOR_FAMILY_PROMOTION_REVIEW" if not failures else "STOP_NO_PROMOTION_UNDER_NO_OVERLIFT_POLICY",
        "failures": failures,
        "remaining_tradable_blockers": sorted(blockers | ({"score_below_95"} if _as_float(best.get("score")) < 95.0 else set())),
        "checks": checks,
    }


def _variant_support_decision(guard: Mapping[str, Any], family: str) -> str:
    if family == "double_tops":
        return "DEFENSIVE_FAMILY_SUPPORT_ONLY"
    if guard.get("promotion_decision") == "ELIGIBLE_FOR_FAMILY_PROMOTION_REVIEW":
        return "FAMILY_PROMOTION_REVIEW_VARIANTS_REMAIN_SUBGROUPS"
    return "NO_FAMILY_PROMOTION_VARIANTS_REMAIN_STANDALONE_LIMITED"


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Double Family Tradable Rescue",
        "",
        f"Audit: `{AUDIT_ID}`",
        "",
        "| Family | Best score | Classification | Best branch | Entry | Decision | Variant support | Blockers |",
        "|---|---:|---|---|---|---|---|---|",
    ]
    for row in payload.get("families") or []:
        guard = row.get("no_overlift_guard") if isinstance(row.get("no_overlift_guard"), Mapping) else {}
        lines.append(
            f"| {row.get('family')} | {_as_float(row.get('best_score')):.2f} | {row.get('best_classification')} | "
            f"{row.get('best_branch_id')} | {row.get('best_entry_rule')} | {guard.get('promotion_decision')} | "
            f"{row.get('variant_support_decision')} | {', '.join(guard.get('remaining_tradable_blockers') or guard.get('failures') or [])} |"
        )
    lines.extend(["", "## Candidate Detail", ""])
    for family in payload.get("families") or []:
        lines.extend(
            [
                f"### {family.get('family')}",
                "",
                "| Branch | Entry | Score | Trades | Validation | Holdout | WF positive | WF sum | Variant stats |",
                "|---|---|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        for row in family.get("rows") or []:
            stats = row.get("variant_trade_stats") if isinstance(row.get("variant_trade_stats"), Mapping) else {}
            compact_stats = ", ".join(f"{key}:{value.get('trades')}" for key, value in stats.items())
            lines.append(
                f"| {row.get('branch_id')} | {row.get('entry_rule')} | {_as_float(row.get('score')):.2f} | {row.get('trades') or ''} | "
                f"{row.get('validation_total_return_pct') or ''} | {row.get('holdout_total_return_pct') or ''} | "
                f"{row.get('walk_forward_positive_fold_rate_pct') or ''} | {row.get('walk_forward_sum_return_pct') or ''} | {compact_stats} |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def run_family(family: str, out_dir: Path, shortlist_size: int) -> dict[str, Any]:
    family_dir = out_dir / family
    family_dir.mkdir(parents=True, exist_ok=True)
    quick_rows, shortlist, meta = _first_pass(family, shortlist_size)
    full_rows = [
        _evaluate_full_candidate(family, branch, entry_rule, config)
        for branch, entry_rule, config, _ in shortlist
    ]
    full_rows = sorted(full_rows, key=lambda row: _as_float(row.get("score")), reverse=True)
    best = full_rows[0] if full_rows else {}
    guard = _guard(best, family)
    payload = {
        "audit_id": AUDIT_ID,
        "family": family,
        "scope": _scope(family),
        "meta": meta,
        "best_score": best.get("score"),
        "best_classification": best.get("classification"),
        "best_strategy_id": best.get("strategy_id"),
        "best_branch_id": best.get("branch_id"),
        "best_entry_rule": best.get("entry_rule"),
        "best_variant_trade_stats": best.get("variant_trade_stats") if isinstance(best.get("variant_trade_stats"), Mapping) else {},
        "best_selected_config": best.get("selected_config") if isinstance(best.get("selected_config"), Mapping) else {},
        "no_overlift_guard": guard,
        "variant_support_decision": _variant_support_decision(guard, family),
        "rows": full_rows,
    }
    _write_json(family_dir / f"{family}_tradable_rescue.json", payload)
    _write_csv(family_dir / f"{family}_tradable_rescue_grid.csv", quick_rows)
    _write_csv(family_dir / f"{family}_tradable_rescue_candidates.csv", full_rows)
    (family_dir / f"{family}_tradable_rescue.md").write_text(render_markdown({"families": [payload]}), encoding="utf-8")
    return payload


def run_audit(*, out_dir: Path = OUT_DIR, families: Sequence[str] = FAMILIES, shortlist_size: int = 16) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    family_payloads = [run_family(family, out_dir, shortlist_size) for family in families]
    payload = {
        "audit_id": AUDIT_ID,
        "family_count": len(family_payloads),
        "families": family_payloads,
    }
    paths = {
        "json": out_dir / "double_family_tradable_rescue.json",
        "csv": out_dir / "double_family_tradable_rescue.csv",
        "md": out_dir / "double_family_tradable_rescue.md",
    }
    _write_json(paths["json"], payload)
    _write_csv(
        paths["csv"],
        [
            {
                "family": row.get("family"),
                "scope": row.get("scope"),
                "best_score": row.get("best_score"),
                "best_classification": row.get("best_classification"),
                "best_strategy_id": row.get("best_strategy_id"),
                "best_branch_id": row.get("best_branch_id"),
                "best_entry_rule": row.get("best_entry_rule"),
                "variant_support_decision": row.get("variant_support_decision"),
                "promotion_decision": (row.get("no_overlift_guard") or {}).get("promotion_decision"),
                "remaining_tradable_blockers": ",".join((row.get("no_overlift_guard") or {}).get("remaining_tradable_blockers") or []),
            }
            for row in family_payloads
        ],
    )
    paths["md"].write_text(render_markdown(payload), encoding="utf-8")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Double Family tradable rescue audit.")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--families", default=",".join(FAMILIES))
    parser.add_argument("--shortlist-size", type=int, default=16)
    args = parser.parse_args()
    families = tuple(item.strip() for item in str(args.families).split(",") if item.strip())
    paths = run_audit(out_dir=Path(args.out_dir), families=families, shortlist_size=int(args.shortlist_size))
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
