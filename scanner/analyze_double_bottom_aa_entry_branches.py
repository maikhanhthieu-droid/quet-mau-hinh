"""Test dynamic entry branches for Double Bottom variants.

The generic tradable layer only supports fixed entry delays after breakout.
Double bottoms often need a different question: should entry wait for a retest
of the neckline/breakout area, or for short follow-through confirmation?

This audit keeps the same no-overlift contract.  Holdout and walk-forward are
promotion evidence, not tuning targets.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.run_chapter_tradable_layer import (  # noqa: E402
    CHAPTER_SPECS,
    GenericExecutionConfig,
    evaluate_strategy,
    load_chapter_events_and_path,
    run_cost_stress,
    run_monte_carlo,
    run_walk_forward,
    score_tradable_setup,
)


DEFAULT_PATTERN_ID = "double_bottoms_adam_adam"
DOUBLE_BOTTOM_PATTERN_IDS = (
    "double_bottoms_adam_adam",
    "double_bottoms_adam_eve",
    "double_bottoms_eve_adam",
    "double_bottoms_eve_eve",
)
PATTERN_TITLES = {
    "double_bottoms_adam_adam": "Double Bottom Adam & Adam",
    "double_bottoms_adam_eve": "Double Bottom Adam & Eve",
    "double_bottoms_eve_adam": "Double Bottom Eve & Adam",
    "double_bottoms_eve_eve": "Double Bottom Eve & Eve",
}
OUT_ROOT = Path("artifacts/scanner_v2/double_bottom_entry_branch_audit")
NO_OVERLIFT_POLICY_ID = "tradable_no_overlift_guard_v1"


@dataclass(frozen=True)
class EntryRule:
    rule_id: str
    kind: str
    max_wait_bars: int = 10
    retest_tolerance_pct: float = 1.0
    max_close_under_breakout_pct: float = 1.0
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
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(default if value is None else value)
    except (TypeError, ValueError):
        return int(default)


def _score_between(value: Any, low: float, high: float) -> float:
    numeric = _as_float(value, default=low)
    if high == low:
        return 100.0 if numeric >= high else 0.0
    return max(0.0, min(100.0, (numeric - low) / (high - low) * 100.0))


def _utility(row: Mapping[str, Any], prefix: str = "") -> float:
    key = lambda name: f"{prefix}_{name}" if prefix else name
    return (
        0.26 * _score_between(row.get(key("total_return_pct")), 0.0, 8.0)
        + 0.18 * _score_between(row.get(key("max_drawdown_pct")), -10.0, -2.0)
        + 0.18 * _score_between(row.get(key("win_rate_pct")), 45.0, 68.0)
        + 0.16 * _score_between(row.get(key("trades")), 8.0, 35.0)
        + 0.12 * _score_between(row.get(key("profit_factor")), 1.0, 2.5)
        + 0.10 * _score_between(8.0 - _as_float(row.get("median_adtv_participation_pct"), default=8.0), 0.0, 8.0)
    )


def build_entry_rules() -> list[EntryRule]:
    return [
        EntryRule("fixed_open_d1", "fixed", max_wait_bars=1),
        EntryRule("neckline_retest_05pct_10d", "retest", max_wait_bars=10, retest_tolerance_pct=0.5, max_pre_entry_mae_pct=5.0),
        EntryRule("neckline_retest_10pct_10d", "retest", max_wait_bars=10, retest_tolerance_pct=1.0, max_pre_entry_mae_pct=7.0),
        EntryRule("confirm_1pct_3d", "confirm", max_wait_bars=5, min_confirm_return_pct=1.0, confirm_after_bars=3, max_pre_entry_mae_pct=5.0),
        EntryRule("confirm_2pct_5d", "confirm", max_wait_bars=7, min_confirm_return_pct=2.0, confirm_after_bars=5, max_pre_entry_mae_pct=7.0),
        EntryRule("retest_reclaim_10d", "retest_reclaim", max_wait_bars=10, retest_tolerance_pct=1.0, min_confirm_return_pct=0.5, max_pre_entry_mae_pct=7.0),
    ]


def _default_out_dir(pattern_id: str) -> Path:
    return OUT_ROOT / pattern_id


def _audit_id(pattern_id: str) -> str:
    return f"{pattern_id}_entry_branch_audit_v1"


def build_configs(rule: EntryRule, *, pattern_id: str) -> list[GenericExecutionConfig]:
    configs: list[GenericExecutionConfig] = []
    for target in (0.65, 0.75):
        for stop in (7.0, 10.0):
            for hold in (20, 60):
                for setup in (68.0, 70.0, 72.0, 75.0):
                    for confirm in (None, 60.0, 70.0):
                        for position_size, max_positions in ((0.033, 30), (0.075, 10), (0.10, 10)):
                            pos_id = str(position_size).replace(".", "")
                            configs.append(
                                GenericExecutionConfig(
                                    strategy_id=(
                                        f"{pattern_id}__{rule.rule_id}"
                                        f"_t{str(target).replace('.', '')}_s{int(stop)}_h{hold}"
                                        f"_q{int(setup)}_c{int(confirm or 0)}_p{pos_id}_m{max_positions}"
                                    ),
                                    target_multiple=target,
                                    stop_loss_pct=stop,
                                    max_holding_days=hold,
                                    entry_delay_bars=1,
                                    min_setup_score=setup,
                                    min_confirmation_score=confirm,
                                    allowed_breakout_directions=("up",),
                                    position_size_pct=position_size,
                                    max_positions=max_positions,
                                    max_adtv_participation_pct=30.0,
                                    target_adtv_participation_pct=5.0,
                                )
                            )
    return configs


def _pre_entry_mae_pct(group: pd.DataFrame, breakout_price: float, entry_bar: int) -> float:
    pre = group[pd.to_numeric(group["bar_after_breakout"], errors="coerce") <= entry_bar]
    if pre.empty or breakout_price <= 0:
        return 999.0
    return max(0.0, (breakout_price - float(pd.to_numeric(pre["low"], errors="coerce").min())) / breakout_price * 100.0)


def _find_entry_bar(event: Mapping[str, Any], group: pd.DataFrame, rule: EntryRule) -> int | None:
    breakout_price = _as_float(event.get("breakout_price"))
    if breakout_price <= 0 or group.empty:
        return None
    work = group.copy()
    work["bar_after_breakout"] = pd.to_numeric(work["bar_after_breakout"], errors="coerce")
    work = work[(work["bar_after_breakout"] >= 1) & (work["bar_after_breakout"] <= int(rule.max_wait_bars))]
    if work.empty:
        return None
    if rule.kind == "fixed":
        return 1
    retested = False
    for _, row in work.sort_values("bar_after_breakout").iterrows():
        bar = int(row["bar_after_breakout"])
        low = _as_float(row.get("low"))
        close = _as_float(row.get("close"))
        if _pre_entry_mae_pct(group, breakout_price, bar) > float(rule.max_pre_entry_mae_pct):
            continue
        retest_ok = low <= breakout_price * (1.0 + float(rule.retest_tolerance_pct) / 100.0)
        reclaim_ok = close >= breakout_price * (1.0 - float(rule.max_close_under_breakout_pct) / 100.0)
        confirm_ok = bar >= int(rule.confirm_after_bars) and close >= breakout_price * (1.0 + float(rule.min_confirm_return_pct) / 100.0)
        if rule.kind == "retest" and retest_ok and reclaim_ok:
            return bar
        if rule.kind == "confirm" and confirm_ok:
            return bar
        if rule.kind == "retest_reclaim":
            retested = retested or retest_ok
            if retested and close >= breakout_price * (1.0 + float(rule.min_confirm_return_pct) / 100.0):
                return bar
    return None


def prepare_entry_branch(events: pd.DataFrame, path: pd.DataFrame, rule: EntryRule) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if events.empty or path.empty:
        return pd.DataFrame(), pd.DataFrame(), {"entry_rule": rule.rule_id, "events": 0}
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
        transformed["dynamic_entry_original_bar"] = int(entry_bar)
        transformed["dynamic_entry_wait_bars"] = int(entry_bar)
        event_rows.append(transformed)
        wait_bars.append(int(entry_bar))
        sub = group[pd.to_numeric(group["bar_after_breakout"], errors="coerce") >= int(entry_bar)].copy()
        sub["original_bar_after_breakout"] = sub["bar_after_breakout"]
        sub["bar_after_breakout"] = pd.to_numeric(sub["bar_after_breakout"], errors="coerce") - int(entry_bar) + 1
        path_rows.extend(sub.to_dict("records"))
    prepared_events = pd.DataFrame(event_rows)
    prepared_path = pd.DataFrame(path_rows)
    meta = {
        "entry_rule": rule.rule_id,
        "kind": rule.kind,
        "source_events": int(len(events)),
        "eligible_events": int(len(prepared_events)),
        "eligibility_rate_pct": round(float(len(prepared_events) / len(events) * 100.0), 2) if len(events) else None,
        "median_entry_wait_bars": round(float(pd.Series(wait_bars).median()), 2) if wait_bars else None,
        "rule": asdict(rule),
    }
    return prepared_events, prepared_path, meta


def _guard(best: Mapping[str, Any]) -> dict[str, Any]:
    blockers = {item.strip() for item in str(best.get("promotion_blockers") or "").split(",") if item.strip()}
    checks = [
        {"check": "score_threshold", "status": "fail" if _as_float(best.get("score")) < 95.0 else "pass", "observed": best.get("score"), "rule": "best dynamic entry branch must score >= 95"},
        {"check": "promotion_blockers", "status": "fail" if blockers else "pass", "observed": ",".join(sorted(blockers)) or "none", "rule": "best dynamic entry branch must have no blocker"},
        {"check": "walk_forward_positive", "status": "fail" if _as_float(best.get("walk_forward_positive_fold_rate_pct")) < 100.0 else "pass", "observed": best.get("walk_forward_positive_fold_rate_pct"), "rule": "fixed walk-forward must have no negative fold"},
    ]
    failures = [item["check"] for item in checks if item["status"] == "fail"]
    return {
        "policy_id": NO_OVERLIFT_POLICY_ID,
        "promotion_decision": "STOP_NO_PROMOTION_UNDER_NO_OVERLIFT_POLICY" if failures else "ELIGIBLE_FOR_FORMAL_PROMOTION_REVIEW",
        "failures": failures,
        "checks": checks,
    }


def evaluate_full_candidate(
    events: pd.DataFrame,
    path: pd.DataFrame,
    config: GenericExecutionConfig,
    rule_meta: Mapping[str, Any],
    *,
    pattern_id: str,
) -> dict[str, Any]:
    summary, trades, _ = evaluate_strategy(events, path, config)
    _, _, fixed_folds, fixed_summary = run_walk_forward(events, path, [config], config)
    _, cost_stress_summary = run_cost_stress(events, path, config)
    _, monte_carlo_summary = run_monte_carlo(trades, config, iterations=500)
    selection = {
        "status": "selected_tradable_setup",
        "selection_basis": f"{pattern_id} dynamic entry branch; train+validation shortlist; holdout/walk-forward are promotion evidence",
        "selected_strategy_id": config.strategy_id,
        "selected_metrics": summary,
    }
    scorecard = score_tradable_setup(selection, fixed_summary, cost_stress_summary, monte_carlo_summary)
    negative_folds = int((pd.to_numeric(fixed_folds.get("test_total_return_pct"), errors="coerce") < 0).sum()) if not fixed_folds.empty else None
    return {
        "strategy_id": config.strategy_id,
        "entry_rule": rule_meta.get("entry_rule"),
        "entry_rule_kind": rule_meta.get("kind"),
        "eligible_events": rule_meta.get("eligible_events"),
        "eligibility_rate_pct": rule_meta.get("eligibility_rate_pct"),
        "median_entry_wait_bars": rule_meta.get("median_entry_wait_bars"),
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
        "cost_positive_scenario_rate_pct": cost_stress_summary.get("positive_scenario_rate_pct"),
        "cost_worst_scenario_return_pct": cost_stress_summary.get("worst_scenario_return_pct"),
        "monte_carlo_prob_positive_pct": monte_carlo_summary.get("prob_positive_pct"),
        "scorecard_component_scores": scorecard.get("component_scores"),
        "selected_config": asdict(config),
    }


def run_audit(
    *,
    pattern_id: str = DEFAULT_PATTERN_ID,
    out_dir: Path | None = None,
    shortlist_size: int = 8,
) -> dict[str, Path]:
    if pattern_id not in DOUBLE_BOTTOM_PATTERN_IDS:
        raise ValueError(f"Unsupported Double Bottom pattern_id: {pattern_id}")
    if pattern_id not in CHAPTER_SPECS:
        raise ValueError(f"Missing CHAPTER_SPECS entry for pattern_id: {pattern_id}")
    out_dir = out_dir or _default_out_dir(pattern_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    base_events, base_path, source_scope = load_chapter_events_and_path(CHAPTER_SPECS[pattern_id])
    quick_rows: list[dict[str, Any]] = []
    prepared_by_rule: dict[str, tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]] = {}
    config_by_id: dict[str, GenericExecutionConfig] = {}
    for rule in build_entry_rules():
        events, path, meta = prepare_entry_branch(base_events, base_path, rule)
        prepared_by_rule[rule.rule_id] = (events, path, meta)
        if events.empty or path.empty:
            continue
        for config in build_configs(rule, pattern_id=pattern_id):
            summary, _, _ = evaluate_strategy(events, path, config)
            summary["entry_rule"] = rule.rule_id
            summary["entry_rule_kind"] = rule.kind
            summary["eligible_events"] = meta.get("eligible_events")
            summary["eligibility_rate_pct"] = meta.get("eligibility_rate_pct")
            summary["median_entry_wait_bars"] = meta.get("median_entry_wait_bars")
            quick_rows.append(summary)
            config_by_id[config.strategy_id] = config
    passing = [
        row
        for row in quick_rows
        if _as_int(row.get("validation_trades")) >= 8
        and _as_float(row.get("validation_total_return_pct"), default=-999.0) > 0.0
        and _as_float(row.get("median_adtv_participation_pct"), default=999.0) <= 8.0
    ]
    pool = passing if passing else quick_rows
    shortlist = sorted(pool, key=lambda row: 0.62 * _utility(row, "validation") + 0.38 * _utility(row, "train"), reverse=True)[:shortlist_size]
    rows: list[dict[str, Any]] = []
    for row in shortlist:
        config = config_by_id.get(str(row.get("strategy_id")))
        rule_id = str(row.get("entry_rule"))
        prepared = prepared_by_rule.get(rule_id)
        if config is None or prepared is None:
            continue
        events, path, meta = prepared
        rows.append(evaluate_full_candidate(events, path, config, meta, pattern_id=pattern_id))
    rows = sorted(rows, key=lambda item: _as_float(item.get("score")), reverse=True)
    best = rows[0] if rows else {}
    rule_meta = [item[2] for item in prepared_by_rule.values()]
    payload = {
        "audit_id": _audit_id(pattern_id),
        "pattern_id": pattern_id,
        "pattern_title": PATTERN_TITLES.get(pattern_id, pattern_id),
        "scope": "long_cash_candidate",
        "source_scope": source_scope,
        "entry_rule_count": len(prepared_by_rule),
        "grid_count": len(quick_rows),
        "shortlist_size": len(rows),
        "best_score": best.get("score"),
        "best_strategy_id": best.get("strategy_id"),
        "no_overlift_guard": _guard(best),
        "entry_rule_meta": rule_meta,
        "rows": rows,
    }
    paths = {
        "json": out_dir / f"{pattern_id}_entry_branch_audit.json",
        "grid": out_dir / f"{pattern_id}_entry_branch_grid.csv",
        "candidates": out_dir / f"{pattern_id}_entry_branch_candidate_scores.csv",
        "md": out_dir / f"{pattern_id}_entry_branch_audit.md",
    }
    _write_json(paths["json"], payload)
    _write_csv(paths["grid"], quick_rows)
    _write_csv(paths["candidates"], rows)
    paths["md"].write_text(render_markdown(payload), encoding="utf-8")
    return paths


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        f"# {payload.get('pattern_title') or payload.get('pattern_id')} Entry Branch Audit",
        "",
        f"Audit: `{payload.get('audit_id')}`",
        "",
        f"- Best score: `{payload.get('best_score')}`",
        f"- Best strategy: `{payload.get('best_strategy_id')}`",
        f"- No-overlift decision: `{(payload.get('no_overlift_guard') or {}).get('promotion_decision')}`",
        "",
        "## Entry Rule Coverage",
        "",
        "| Rule | Eligible events | Eligibility | Median wait |",
        "|---|---:|---:|---:|",
    ]
    for meta in payload.get("entry_rule_meta") or []:
        lines.append(
            f"| {meta.get('entry_rule')} | {meta.get('eligible_events')} | {meta.get('eligibility_rate_pct')} | {meta.get('median_entry_wait_bars')} |"
        )
    lines.extend(
        [
            "",
            "## Full Candidate Scores",
            "",
            "| Strategy | Rule | Score | Blockers | Trades | Validation | Holdout | WF positive | WF sum |",
            "|---|---|---:|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in payload.get("rows") or []:
        lines.append(
            "| {strategy} | {rule} | {score:.2f} | {blockers} | {trades} | {validation} | {holdout} | {wf_pos} | {wf_sum} |".format(
                strategy=row.get("strategy_id"),
                rule=row.get("entry_rule"),
                score=_as_float(row.get("score")),
                blockers=row.get("promotion_blockers") or "",
                trades=row.get("trades") or "",
                validation=row.get("validation_total_return_pct") or "",
                holdout=row.get("holdout_total_return_pct") or "",
                wf_pos=row.get("walk_forward_positive_fold_rate_pct") or "",
                wf_sum=row.get("walk_forward_sum_return_pct") or "",
            )
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Double Bottom dynamic entry branch audit.")
    parser.add_argument("--pattern-id", default=DEFAULT_PATTERN_ID, choices=DOUBLE_BOTTOM_PATTERN_IDS)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--shortlist-size", type=int, default=8)
    args = parser.parse_args()
    for key, path in run_audit(
        pattern_id=str(args.pattern_id),
        out_dir=Path(args.out_dir) if args.out_dir else None,
        shortlist_size=int(args.shortlist_size),
    ).items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
