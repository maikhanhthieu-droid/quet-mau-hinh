"""Run supporting robustness checks for the Bull Flag release candidate.

The release-candidate score already covers the core tradable contract. This
module closes the remaining available-series support tasks:

* overlap sensitivity,
* liquidity bucket robustness,
* OHLCV-derived price-limit proxy and stress.

It does not choose a new rule. It reuses the frozen execution rule and reports
diagnostics under the same post-2019 known-regime scope.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scanner.v2.bull_flag_tradable_setup import (  # noqa: E402
    DEFAULT_STRATEGY_GRID,
    FROZEN_STRATEGY_ID,
    ExecutionConfig,
    apply_event_scope,
    evaluate_strategy,
)


DEFAULT_MAIN_PROFILE_DIR = Path("artifacts/scanner_v2/bull_flags_adaptive_grid/scans/bull_flag_v2_split_stable_recovery")
DEFAULT_FRESH_PROFILE_DIR = Path("artifacts/scanner_v2/bull_flags_fresh_discovery/gate/profile")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bull_flags_supporting_robustness")
PRICE_LIMIT_PROXY_THRESHOLD_PCT = 6.5
MIN_ELIGIBLE_TRADES = 8
MAX_SUPPORT_DRAWDOWN_PCT = -5.0


def _frozen_config() -> ExecutionConfig:
    config = next((item for item in DEFAULT_STRATEGY_GRID if item.strategy_id == FROZEN_STRATEGY_ID), None)
    if config is None:
        raise RuntimeError(f"Frozen strategy not found: {FROZEN_STRATEGY_ID}")
    return config


def _records(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    if frame.empty:
        return []
    return json.loads(frame.to_json(orient="records"))


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_profile(profile_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    events = pd.read_csv(profile_dir / "events.csv")
    path = pd.read_csv(profile_dir / "post_breakout_path.csv")
    return events, path


def _filter_path_to_events(path: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    if path.empty or events.empty or "event_id" not in path.columns or "event_id" not in events.columns:
        return pd.DataFrame(columns=path.columns)
    event_ids = set(events["event_id"].astype(str))
    return path[path["event_id"].astype(str).isin(event_ids)].copy()


def _cooldown_events(events: pd.DataFrame, days: int) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    working = events.copy()
    working["_breakout_ts"] = pd.to_datetime(working.get("breakout_date"), errors="coerce")
    working = working.dropna(subset=["_breakout_ts"]).sort_values(["_breakout_ts", "symbol"]).copy()
    keep: List[int] = []
    last_by_symbol: Dict[str, pd.Timestamp] = {}
    for idx, row in working.iterrows():
        symbol = str(row.get("symbol") or "")
        breakout_ts = pd.Timestamp(row["_breakout_ts"])
        last = last_by_symbol.get(symbol)
        if last is None or (breakout_ts - last).days >= int(days):
            keep.append(idx)
            last_by_symbol[symbol] = breakout_ts
    return events.loc[keep].copy()


def _one_event_per_symbol(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    working = events.copy()
    working["_breakout_ts"] = pd.to_datetime(working.get("breakout_date"), errors="coerce")
    working = working.dropna(subset=["_breakout_ts"]).sort_values(["_breakout_ts", "symbol"]).copy()
    return working.drop_duplicates("symbol").drop(columns=["_breakout_ts"], errors="ignore").copy()


def _price_limit_proxy_event_ids(path: pd.DataFrame, *, threshold_pct: float = PRICE_LIMIT_PROXY_THRESHOLD_PCT, horizon_days: int = 60) -> Set[str]:
    if path.empty:
        return set()
    working = path.copy()
    working["bar_after_breakout"] = pd.to_numeric(working.get("bar_after_breakout"), errors="coerce")
    working = working[working["bar_after_breakout"].between(1, int(horizon_days), inclusive="both")].copy()
    for column in ("open", "high", "low", "close"):
        working[column] = pd.to_numeric(working.get(column), errors="coerce")
    close = working["close"].replace(0, pd.NA)
    open_ = working["open"].replace(0, pd.NA)
    working["range_pct"] = (working["high"] - working["low"]) / close * 100.0
    working["open_close_abs_pct"] = (working["close"] / open_ - 1.0).abs() * 100.0
    mask = (working["range_pct"] >= float(threshold_pct)) | (working["open_close_abs_pct"] >= float(threshold_pct))
    return set(working.loc[mask, "event_id"].astype(str))


def _price_limit_proxy_summary(events: pd.DataFrame, path: pd.DataFrame, *, threshold_pct: float = PRICE_LIMIT_PROXY_THRESHOLD_PCT) -> Dict[str, Any]:
    scoped_ids = set(events.get("event_id", pd.Series(dtype=str)).astype(str))
    flagged_ids = _price_limit_proxy_event_ids(path, threshold_pct=threshold_pct)
    flagged_in_scope = scoped_ids & flagged_ids
    return {
        "threshold_pct": float(threshold_pct),
        "scoped_events": int(len(scoped_ids)),
        "flagged_events": int(len(flagged_in_scope)),
        "flagged_event_rate_pct": round(float(len(flagged_in_scope)) / len(scoped_ids) * 100.0, 2) if scoped_ids else None,
    }


def _evaluate_subset(events: pd.DataFrame, path: pd.DataFrame, config: ExecutionConfig, *, row_id: str, row_type: str) -> Dict[str, Any]:
    summary, trades, _ = evaluate_strategy(events, path, config)
    scoped_events, _ = apply_event_scope(events, path, config)
    executed = trades[trades.get("executed", pd.Series(False, index=trades.index)) == True].copy() if not trades.empty else pd.DataFrame()
    return {
        "row_id": row_id,
        "row_type": row_type,
        "events": int(len(scoped_events)),
        "trades": summary.get("trades"),
        "total_return_pct": summary.get("total_return_pct"),
        "validation_total_return_pct": summary.get("validation_total_return_pct"),
        "holdout_total_return_pct": summary.get("holdout_total_return_pct"),
        "max_drawdown_pct": summary.get("max_drawdown_pct"),
        "win_rate_pct": summary.get("win_rate_pct"),
        "profit_factor": summary.get("profit_factor"),
        "median_adtv_participation_pct": summary.get("median_adtv_participation_pct"),
        "target_adtv_limited_rate_pct": summary.get("target_adtv_limited_rate_pct"),
        "target_exit_rate_pct": summary.get("target_exit_rate_pct"),
        "stop_exit_rate_pct": summary.get("stop_exit_rate_pct"),
        "entry_limit_proxy_rate_pct": _entry_exit_limit_rate(executed, "entry_bar_range_pct"),
        "exit_limit_proxy_rate_pct": _entry_exit_limit_rate(executed, "exit_bar_range_pct"),
    }


def _entry_exit_limit_rate(trades: pd.DataFrame, column: str, *, threshold_pct: float = PRICE_LIMIT_PROXY_THRESHOLD_PCT) -> Optional[float]:
    if trades.empty or column not in trades.columns:
        return None
    values = pd.to_numeric(trades[column], errors="coerce").dropna()
    if values.empty:
        return None
    return round(float((values >= float(threshold_pct)).mean()) * 100.0, 2)


def _eligible_pass(rows: Sequence[Mapping[str, Any]], *, min_trades: int = MIN_ELIGIBLE_TRADES, min_total_return_pct: float = 0.0) -> Dict[str, Any]:
    eligible = [row for row in rows if int(row.get("trades") or 0) >= int(min_trades)]
    failures = [
        row.get("row_id")
        for row in eligible
        if _as_float(row.get("total_return_pct"), default=-999.0) <= float(min_total_return_pct)
        or _as_float(row.get("max_drawdown_pct"), default=-999.0) < float(MAX_SUPPORT_DRAWDOWN_PCT)
    ]
    return {
        "status": "PASS" if not failures and eligible else "FAIL",
        "eligible_rows": int(len(eligible)),
        "failed_rows": failures,
        "min_total_return_pct": round(min((_as_float(row.get("total_return_pct")) for row in eligible), default=0.0), 2),
        "worst_drawdown_pct": round(min((_as_float(row.get("max_drawdown_pct")) for row in eligible), default=0.0), 2),
    }


def overlap_sensitivity(events: pd.DataFrame, path: pd.DataFrame, config: ExecutionConfig) -> Dict[str, Any]:
    scoped_events, scoped_path = apply_event_scope(events, path, config)
    variants = [
        ("base_scoped", scoped_events),
        ("primary_event_60d", scoped_events[scoped_events.get("is_primary_event_60d", pd.Series(True, index=scoped_events.index)).astype(bool)].copy()),
        ("cooldown_30d", _cooldown_events(scoped_events, 30)),
        ("cooldown_60d", _cooldown_events(scoped_events, 60)),
        ("cooldown_90d", _cooldown_events(scoped_events, 90)),
        ("one_event_per_symbol", _one_event_per_symbol(scoped_events)),
    ]
    rows = [_evaluate_subset(subset, scoped_path, config, row_id=row_id, row_type="overlap") for row_id, subset in variants]
    retention = [
        _as_float(row.get("events")) / len(scoped_events) * 100.0
        for row in rows
        if row.get("row_id") == "one_event_per_symbol" and len(scoped_events) > 0
    ]
    pass_summary = _eligible_pass(rows)
    retention_pass = not retention or retention[0] >= 80.0
    status = "PASS" if pass_summary["status"] == "PASS" and retention_pass else "FAIL"
    return {
        "status": status,
        "summary": pass_summary | {"one_event_per_symbol_retention_pct": round(retention[0], 2) if retention else None},
        "rows": rows,
    }


def liquidity_robustness(events: pd.DataFrame, path: pd.DataFrame, config: ExecutionConfig) -> Dict[str, Any]:
    scoped_events, scoped_path = apply_event_scope(events, path, config)
    rows: List[Dict[str, Any]] = []
    if "liquidity_bucket" not in scoped_events.columns:
        return {"status": "FAIL", "summary": {"reason": "missing_liquidity_bucket"}, "rows": rows}
    for bucket, group in scoped_events.groupby("liquidity_bucket", dropna=False):
        rows.append(_evaluate_subset(group.copy(), scoped_path, config, row_id=f"bucket_{bucket}", row_type="liquidity_bucket"))
    for bucket in sorted(scoped_events["liquidity_bucket"].dropna().astype(str).unique()):
        subset = scoped_events[scoped_events["liquidity_bucket"].astype(str) != bucket].copy()
        rows.append(_evaluate_subset(subset, scoped_path, config, row_id=f"exclude_{bucket}", row_type="liquidity_exclusion"))
    pass_summary = _eligible_pass(rows)
    capacity_warnings = [
        row.get("row_id")
        for row in rows
        if int(row.get("trades") or 0) >= MIN_ELIGIBLE_TRADES and _as_float(row.get("median_adtv_participation_pct"), default=0.0) > 5.0
    ]
    return {
        "status": pass_summary["status"],
        "summary": pass_summary | {"capacity_warning_rows": capacity_warnings},
        "rows": rows,
    }


def price_limit_proxy_robustness(events: pd.DataFrame, path: pd.DataFrame, config: ExecutionConfig) -> Dict[str, Any]:
    scoped_events, scoped_path = apply_event_scope(events, path, config)
    flagged_ids = _price_limit_proxy_event_ids(scoped_path)
    flagged_events = scoped_events[scoped_events["event_id"].astype(str).isin(flagged_ids)].copy()
    clean_events = scoped_events[~scoped_events["event_id"].astype(str).isin(flagged_ids)].copy()
    rows = [
        _evaluate_subset(flagged_events, scoped_path, config, row_id="limit_proxy_events", row_type="price_limit_proxy_subset"),
        _evaluate_subset(clean_events, scoped_path, config, row_id="no_limit_proxy_events", row_type="price_limit_proxy_subset"),
    ]
    for extra_bps in (30.0, 50.0, 75.0, 100.0):
        stress_config = replace(
            config,
            strategy_id=f"{config.strategy_id}__price_limit_proxy_{int(extra_bps)}bps",
            limit_extra_slippage_bps=float(extra_bps),
            gap_extra_slippage_bps=float(extra_bps),
        )
        rows.append(_evaluate_subset(scoped_events, scoped_path, stress_config, row_id=f"limit_gap_stress_{int(extra_bps)}bps", row_type="price_limit_proxy_stress"))
    pass_summary = _eligible_pass(rows)
    return {
        "status": pass_summary["status"],
        "summary": pass_summary | _price_limit_proxy_summary(scoped_events, scoped_path),
        "rows": rows,
    }


def run_profile_robustness(profile_id: str, profile_dir: Path, config: ExecutionConfig) -> Dict[str, Any]:
    events, path = _load_profile(profile_dir)
    scoped_events, scoped_path = apply_event_scope(events, path, config)
    overlap = overlap_sensitivity(events, path, config)
    liquidity = liquidity_robustness(events, path, config)
    price_limit = price_limit_proxy_robustness(events, path, config)
    checks = {
        "overlap_sensitivity": overlap["status"],
        "liquidity_bucket_robustness": liquidity["status"],
        "price_limit_proxy_robustness": price_limit["status"],
    }
    return {
        "profile_id": profile_id,
        "profile_dir": str(profile_dir),
        "scoped_events": int(len(scoped_events)),
        "scoped_path_rows": int(len(scoped_path)),
        "checks": checks,
        "status": "PASS" if all(value == "PASS" for value in checks.values()) else "FAIL",
        "overlap_sensitivity": overlap,
        "liquidity_bucket_robustness": liquidity,
        "price_limit_proxy_robustness": price_limit,
    }


def build_supporting_robustness(
    *,
    main_profile_dir: Path = DEFAULT_MAIN_PROFILE_DIR,
    fresh_profile_dir: Path = DEFAULT_FRESH_PROFILE_DIR,
    config: Optional[ExecutionConfig] = None,
) -> Dict[str, Any]:
    frozen = config or _frozen_config()
    profiles = [
        run_profile_robustness("main_artifact", main_profile_dir, frozen),
        run_profile_robustness("fresh_candidate", fresh_profile_dir, frozen),
    ]
    failures = [
        f"{profile['profile_id']}:{check_id}"
        for profile in profiles
        for check_id, status in (profile.get("checks") or {}).items()
        if status != "PASS"
    ]
    closed_partials = ["overlap_policy", "liquidity_proxy", "price_limit_microstructure"]
    return {
        "robustness_id": "bull_flag_supporting_robustness_v1",
        "status": "PASS" if not failures else "FAIL",
        "frozen_strategy_id": frozen.strategy_id,
        "scope": {
            "min_breakout_date": frozen.min_breakout_date,
            "allowed_market_regimes": list(frozen.allowed_market_regimes or []),
            "claim": "supporting robustness under available-series descriptive scope",
        },
        "closed_data_gate_partials": closed_partials if not failures else [],
        "failures": failures,
        "profiles": profiles,
    }


def render_supporting_robustness(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Bull Flag Supporting Robustness",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- Frozen strategy: `{payload.get('frozen_strategy_id')}`",
        f"- Failures: `{', '.join(payload.get('failures') or []) or 'none'}`",
        "",
        "| Profile | Scoped events | Overlap | Liquidity | Price-limit proxy |",
        "|---|---:|---|---|---|",
    ]
    for profile in payload.get("profiles", []):
        if not isinstance(profile, Mapping):
            continue
        checks = profile.get("checks") if isinstance(profile.get("checks"), Mapping) else {}
        lines.append(
            "| {profile} | {events} | {overlap} | {liq} | {limit} |".format(
                profile=profile.get("profile_id"),
                events=profile.get("scoped_events"),
                overlap=checks.get("overlap_sensitivity"),
                liq=checks.get("liquidity_bucket_robustness"),
                limit=checks.get("price_limit_proxy_robustness"),
            )
        )
    for profile in payload.get("profiles", []):
        if not isinstance(profile, Mapping):
            continue
        lines.extend(["", f"## {profile.get('profile_id')}", ""])
        for section_id in ("overlap_sensitivity", "liquidity_bucket_robustness", "price_limit_proxy_robustness"):
            section = profile.get(section_id) if isinstance(profile.get(section_id), Mapping) else {}
            summary = section.get("summary") if isinstance(section.get("summary"), Mapping) else {}
            lines.extend(
                [
                    f"### {section_id}",
                    "",
                    f"- Status: `{section.get('status')}`",
                    f"- Eligible rows: `{summary.get('eligible_rows')}`",
                    f"- Failed rows: `{', '.join(summary.get('failed_rows') or []) or 'none'}`",
                    f"- Min total return: `{summary.get('min_total_return_pct')}`",
                    f"- Worst drawdown: `{summary.get('worst_drawdown_pct')}`",
                    "",
                    "| Row | Type | Events | Trades | Total return | Max DD | Median ADTV |",
                    "|---|---|---:|---:|---:|---:|---:|",
                ]
            )
            for row in section.get("rows", []):
                if not isinstance(row, Mapping):
                    continue
                lines.append(
                    "| {row_id} | {row_type} | {events} | {trades} | {total} | {dd} | {adtv} |".format(
                        row_id=row.get("row_id"),
                        row_type=row.get("row_type"),
                        events=row.get("events"),
                        trades=row.get("trades"),
                        total=row.get("total_return_pct"),
                        dd=row.get("max_drawdown_pct"),
                        adtv=row.get("median_adtv_participation_pct"),
                    )
                )
    return "\n".join(lines) + "\n"


def write_supporting_robustness(payload: Mapping[str, Any], out_dir: Path = DEFAULT_OUT_DIR) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "bull_flag_supporting_robustness.json"
    md_path = out_dir / "bull_flag_supporting_robustness.md"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_supporting_robustness(payload), encoding="utf-8")
    return {"json": json_path, "report": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Bull Flag supporting robustness checks.")
    parser.add_argument("--main-profile-dir", default=str(DEFAULT_MAIN_PROFILE_DIR))
    parser.add_argument("--fresh-profile-dir", default=str(DEFAULT_FRESH_PROFILE_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    payload = build_supporting_robustness(main_profile_dir=Path(args.main_profile_dir), fresh_profile_dir=Path(args.fresh_profile_dir))
    paths = write_supporting_robustness(payload, Path(args.out_dir))
    for key, path in paths.items():
        print(f"{key}: {path}")
    if payload.get("status") != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
