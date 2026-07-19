"""Data-gate audit helpers for Scanner V2 chapters."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd


GATE_STANDARD_VERSION = "scanner_v2_data_gates_v2"


@dataclass(frozen=True)
class DataGateResult:
    gate_id: str
    label: str
    status: str
    severity: str
    blocks_investment_reference: bool
    detail: str
    evidence: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "label": self.label,
            "status": self.status,
            "severity": self.severity,
            "blocks_investment_reference": self.blocks_investment_reference,
            "detail": self.detail,
            "evidence": self.evidence,
        }


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _status(blocks: bool, *, partial: bool = False) -> str:
    if blocks:
        return "FAIL"
    return "PARTIAL" if partial else "PASS"


def _gate(
    gate_id: str,
    label: str,
    *,
    blocks: bool,
    detail: str,
    evidence: Optional[Mapping[str, Any]] = None,
    severity: str = "High",
    partial: bool = False,
) -> DataGateResult:
    return DataGateResult(
        gate_id=gate_id,
        label=label,
        status=_status(blocks, partial=partial),
        severity=severity,
        blocks_investment_reference=bool(blocks),
        detail=detail,
        evidence=dict(evidence or {}),
    )


def _metadata_gate(metadata: Mapping[str, Any], events: pd.DataFrame, *, universe_scope: str) -> List[DataGateResult]:
    data_basis = metadata.get("data_basis") if isinstance(metadata.get("data_basis"), Mapping) else {}
    membership = metadata.get("membership_version") if isinstance(metadata.get("membership_version"), Mapping) else {}
    sources = metadata.get("sources") if isinstance(metadata.get("sources"), Mapping) else {}

    pit_ready = bool(membership.get("point_in_time_ready"))
    available_series_scope = universe_scope == "available_series_descriptive"
    adjustment = str(data_basis.get("adjustment") or "")
    has_factor_audit = "without_factor_audit" not in adjustment and "audit" in adjustment
    has_proxy = "corp_action_proxy_flag" in events.columns
    proxy_flag_rate = None
    if has_proxy and len(events):
        proxy_flags = events["corp_action_proxy_flag"].map(lambda value: str(value).strip().lower() in {"true", "1", "yes"})
        proxy_flag_rate = round(float(proxy_flags.mean()) * 100.0, 2)
    return [
        _gate(
            "point_in_time_universe",
            "Point-in-time universe and membership",
            blocks=not pit_ready and not available_series_scope,
            detail=(
                "Market Stats metadata is point-in-time ready."
                if pit_ready
                else "Scope is available-series descriptive, so point-in-time universe is disclosed as a limitation, not used as a promotion blocker."
                if available_series_scope
                else "Market Stats metadata says membership is not point-in-time ready."
            ),
            evidence={
                "membership_mode": membership.get("mode"),
                "point_in_time_ready": membership.get("point_in_time_ready"),
                "history_maturity": membership.get("history_maturity"),
                "guardrail": membership.get("guardrail"),
                "source": (sources.get("membership_history") or {}) if isinstance(sources.get("membership_history"), Mapping) else None,
            },
            severity="Critical",
            partial=available_series_scope and not pit_ready,
        ),
        _gate(
            "corporate_action_audit",
            "Corporate-action adjusted OHLCV audit",
            blocks=not has_factor_audit and not (available_series_scope and has_proxy),
            detail=(
                "Adjustment metadata includes an auditable factor source."
                if has_factor_audit
                else "Available-series scope uses event-level corporate-action proxy flags; full factor audit is still missing."
                if available_series_scope and has_proxy
                else "OHLCV is provider-adjusted, but metadata does not include an auditable adjustment factor log."
            ),
            evidence={
                "price_basis": data_basis.get("price"),
                "adjustment": data_basis.get("adjustment"),
                "adjustment_guardrail": data_basis.get("adjustment_guardrail"),
                "event_level_proxy_available": has_proxy,
                "event_level_proxy_flag_rate_pct": proxy_flag_rate,
            },
            severity="Critical",
            partial=available_series_scope and has_proxy and not has_factor_audit,
        ),
    ]


def _membership_db_gate(history_db: Path, event_dates: pd.Series, *, use_historical_membership: bool) -> DataGateResult:
    if not use_historical_membership:
        return _gate(
            "membership_history_db",
            "Historical VN30/VN100 membership coverage",
            blocks=False,
            partial=True,
            detail="Historical VN30/VN100 membership is not used for headline claims in this scope; market_group fields are diagnostic only.",
            evidence={"used_for_headline_claims": False},
            severity="High",
        )
    if not history_db.exists():
        return _gate(
            "membership_history_db",
            "Membership history DB coverage",
            blocks=True,
            detail="Membership history DB is missing.",
            evidence={"path": str(history_db)},
            severity="High",
        )
    con = sqlite3.connect(history_db)
    try:
        rows = con.execute(
            "select min(effective_from), max(coalesce(effective_to, effective_from)), count(*), count(distinct index_code) from index_membership_history"
        ).fetchone()
    finally:
        con.close()
    min_from, max_to, count, index_count = rows
    min_event = str(pd.to_datetime(event_dates).min().date()) if not event_dates.empty else None
    max_event = str(pd.to_datetime(event_dates).max().date()) if not event_dates.empty else None
    covers_events = bool(min_from and min_event and str(min_from) <= min_event)
    return _gate(
        "membership_history_db",
        "Membership history DB coverage",
        blocks=not covers_events,
        detail=(
            "Membership DB covers the event date range."
            if covers_events
            else "Membership DB exists but starts after the Bull Flag event range, so historical VN30/VN100 labels remain snapshot-biased."
        ),
        evidence={
            "path": str(history_db),
            "row_count": int(count or 0),
            "index_count": int(index_count or 0),
            "effective_from_min": min_from,
            "effective_to_max": max_to,
            "event_start": min_event,
            "event_end": max_event,
        },
        severity="High",
    )


def _active_universe_gate(metadata: Mapping[str, Any], events: pd.DataFrame, *, universe_scope: str) -> DataGateResult:
    stocks = metadata.get("stocks")
    sources = metadata.get("sources") if isinstance(metadata.get("sources"), Mapping) else {}
    stock_ohlcv = sources.get("stock_ohlcv") if isinstance(sources.get("stock_ohlcv"), Mapping) else {}
    available_series_scope = universe_scope == "available_series_descriptive"
    if not isinstance(stocks, list) or not stocks:
        return _gate(
            "active_universe_coverage",
            "Market Stats active universe coverage",
            blocks=available_series_scope,
            partial=not available_series_scope,
            detail=(
                "Available-series scope requires a current active Market Stats stock list, but metadata has no stocks list."
                if available_series_scope
                else "Current active Market Stats stock list is unavailable; this gate is diagnostic outside available-series scope."
            ),
            evidence={
                "active_universe_source": "Market Stats V1 stocks",
                "active_symbol_count": 0,
                "event_symbol_count": int(events["symbol"].nunique()) if "symbol" in events.columns else 0,
            },
            severity="Critical" if available_series_scope else "High",
        )
    active_symbols = {
        str(row.get("symbol") or "").strip().upper()
        for row in stocks
        if isinstance(row, Mapping) and str(row.get("symbol") or "").strip()
    }
    event_symbols = (
        set(events["symbol"].dropna().astype(str).str.strip().str.upper())
        if "symbol" in events.columns
        else set()
    )
    missing_symbols = sorted(symbol for symbol in event_symbols if symbol not in active_symbols)
    blocks = available_series_scope and bool(missing_symbols)
    return _gate(
        "active_universe_coverage",
        "Market Stats active universe coverage",
        blocks=blocks,
        partial=not available_series_scope,
        detail=(
            "All event symbols are present in the current active Market Stats V1 universe; delisted symbols excluded by Market Stats are outside this chapter scope."
            if not missing_symbols and available_series_scope
            else "Some event symbols are missing from the current active Market Stats V1 universe."
            if missing_symbols
            else "Active-universe coverage is diagnostic only because this scope requires full point-in-time universe evidence."
        ),
        evidence={
            "active_universe_source": "Market Stats V1 stocks",
            "active_symbol_count": int(len(active_symbols)),
            "market_stats_symbol_count": stock_ohlcv.get("symbol_count"),
            "market_stats_stock_series_count": stock_ohlcv.get("stock_series_count"),
            "market_stats_excluded_symbol_count": stock_ohlcv.get("excluded_symbol_count"),
            "event_symbol_count": int(len(event_symbols)),
            "event_symbols_in_active_universe": int(len(event_symbols) - len(missing_symbols)),
            "missing_event_symbols": missing_symbols[:50],
            "missing_event_symbol_count": int(len(missing_symbols)),
            "scope_note": "This chapter intentionally studies only currently available/active symbols.",
        },
        severity="Critical" if available_series_scope else "High",
    )


def _event_artifact_gate(events: pd.DataFrame, path: pd.DataFrame, horizon_days: int) -> DataGateResult:
    required_event_cols = {"detection_id", "symbol", "breakout_date", "target_dist_pct", "mfe_pct", "mae_pct"}
    required_path_cols = {"event_id", "bar_after_breakout", "signed_high_excursion_pct", "signed_low_excursion_pct"}
    missing_events = sorted(required_event_cols - set(events.columns))
    missing_path = sorted(required_path_cols - set(path.columns))
    if missing_events or missing_path or events.empty or path.empty:
        return _gate(
            "event_path_artifacts",
            "Event/path artifacts",
            blocks=True,
            detail="Required event/path artifacts are incomplete.",
            evidence={"missing_event_columns": missing_events, "missing_path_columns": missing_path, "events": len(events), "path_rows": len(path)},
            severity="Critical",
        )
    counts = path.groupby("event_id")["bar_after_breakout"].max()
    coverage = events["detection_id"].astype(str).map(counts).fillna(0)
    enough = coverage >= int(horizon_days)
    return _gate(
        "event_path_artifacts",
        "Event/path artifacts",
        blocks=False,
        partial=not bool(enough.all()),
        detail="Event and path artifacts exist; some events may have censored post-breakout paths." if not bool(enough.all()) else "Event and path artifacts cover the configured horizon.",
        evidence={
            "events": int(len(events)),
            "path_rows": int(len(path)),
            "horizon_days": int(horizon_days),
            "events_with_horizon": int(enough.sum()),
            "coverage_rate_pct": round(float(enough.mean()) * 100.0, 2) if len(enough) else 0.0,
        },
        severity="Critical",
    )


def _overlap_gate(events: pd.DataFrame, cooldown_days: int) -> DataGateResult:
    if events.empty or not {"symbol", "breakout_date"}.issubset(events.columns):
        return _gate("overlap_policy", "Overlap/cooldown policy", blocks=True, detail="Cannot audit overlap without symbol and breakout_date.", severity="High")
    if "is_primary_event_60d" in events.columns:
        primary = events["is_primary_event_60d"].map(lambda value: str(value).strip().lower() in {"true", "1", "yes"})
        return _gate(
            "overlap_policy",
            "Overlap/cooldown policy",
            blocks=False,
            partial=True,
            detail="Primary-event cooldown flag is present; ranking still needs sensitivity reporting before investment-reference.",
            evidence={
                "cooldown_days": 60,
                "primary_events": int(primary.sum()),
                "repeat_events": int((~primary).sum()),
                "primary_rate_pct": round(float(primary.mean()) * 100.0, 2) if len(primary) else 0.0,
            },
            severity="High",
        )
    df = events[["symbol", "breakout_date", "detection_id"]].copy()
    df["breakout_date"] = pd.to_datetime(df["breakout_date"], errors="coerce")
    overlap_count = 0
    for _, group in df.dropna(subset=["breakout_date"]).sort_values(["symbol", "breakout_date"]).groupby("symbol"):
        diffs = group["breakout_date"].diff().dt.days
        overlap_count += int((diffs <= cooldown_days).sum())
    rate = overlap_count / len(df) if len(df) else 0.0
    return _gate(
        "overlap_policy",
        "Overlap/cooldown policy",
        blocks=False,
        partial=overlap_count > 0,
        detail="Overlap can be audited from events; close repeat events should be sensitivity-tested." if overlap_count else "No close repeat events found under the configured cooldown.",
        evidence={"cooldown_days": int(cooldown_days), "overlap_count": int(overlap_count), "overlap_rate_pct": round(rate * 100.0, 2)},
        severity="High",
    )


def _liquidity_gate(events: pd.DataFrame, stock_series_dir: Path, *, lookback: int = 20, min_adtv: float = 1_000_000) -> DataGateResult:
    if events.empty:
        return _gate("liquidity_proxy", "Liquidity proxy", blocks=True, detail="No events to audit liquidity.", severity="High")
    if {"adtv20_value", "liquidity_bucket"}.issubset(events.columns):
        values = pd.to_numeric(events["adtv20_value"], errors="coerce").dropna()
        bucket_counts = events["liquidity_bucket"].fillna("unknown").astype(str).value_counts().to_dict()
        if values.empty:
            return _gate("liquidity_proxy", "Liquidity proxy", blocks=True, detail="Liquidity fields exist but contain no usable values.", severity="High")
        pass_rate = float((values >= min_adtv).mean())
        return _gate(
            "liquidity_proxy",
            "Liquidity proxy",
            blocks=False,
            partial=True,
            detail="Event-level ADTV proxy and liquidity buckets are present; still not a full point-in-time liquidity policy.",
            evidence={
                "lookback_days": int(lookback),
                "min_adtv_value_units": int(min_adtv),
                "value_unit_note": "Market Stats value is estimated close times volume; with prices in thousand VND this approximates thousand-VND traded value.",
                "events_with_adtv": int(values.shape[0]),
                "missing_events": int(len(events) - values.shape[0]),
                "median_adtv_value_units": round(float(values.median()), 0),
                "p25_adtv_value_units": round(float(values.quantile(0.25)), 0),
                "pass_rate_pct": round(pass_rate * 100.0, 2),
                "bucket_counts": bucket_counts,
            },
            severity="High",
        )
    symbol_paths = {p.stem.split()[0].upper(): p for p in stock_series_dir.glob("*.json")}
    adtvs: List[float] = []
    missing = 0
    for row in events.to_dict("records"):
        symbol = str(row.get("symbol") or "").upper()
        breakout = pd.to_datetime(row.get("breakout_date"), errors="coerce")
        path = symbol_paths.get(symbol)
        if path is None or pd.isna(breakout):
            missing += 1
            continue
        series = pd.DataFrame(_read_json(path))
        if series.empty or "date" not in series.columns or "value" not in series.columns:
            missing += 1
            continue
        series["date"] = pd.to_datetime(series["date"], errors="coerce")
        before = series[series["date"] < breakout].tail(lookback)
        if before.empty:
            missing += 1
            continue
        adtv = pd.to_numeric(before["value"], errors="coerce").dropna().mean()
        if pd.notna(adtv):
            adtvs.append(float(adtv))
        else:
            missing += 1
    arr = np.array(adtvs, dtype=float)
    if arr.size == 0:
        return _gate(
            "liquidity_proxy",
            "Liquidity proxy",
            blocks=True,
            detail="No usable value field was available for ADTV proxy.",
            evidence={"missing_events": int(missing)},
            severity="High",
        )
    pass_rate = float((arr >= min_adtv).mean())
    return _gate(
        "liquidity_proxy",
        "Liquidity proxy",
        blocks=pass_rate < 0.8,
        partial=True,
        detail="ADTV proxy is available from value field, but this is not a full point-in-time liquidity policy.",
        evidence={
            "lookback_days": int(lookback),
            "min_adtv_value_units": int(min_adtv),
            "value_unit_note": "Market Stats value is estimated close times volume; with prices in thousand VND this approximates thousand-VND traded value.",
            "events_with_adtv": int(arr.size),
            "missing_events": int(missing),
            "median_adtv_value_units": round(float(np.median(arr)), 0),
            "p25_adtv_value_units": round(float(np.percentile(arr, 25)), 0),
            "pass_rate_pct": round(pass_rate * 100.0, 2),
        },
        severity="High",
    )


def _delisted_status_gate(events: pd.DataFrame, *, universe_scope: str) -> DataGateResult:
    has_proxy = "halted_delisted_proxy_flag" in events.columns
    if universe_scope == "available_series_descriptive" and has_proxy:
        flags = events["halted_delisted_proxy_flag"].map(lambda value: str(value).strip().lower() in {"true", "1", "yes"})
        return _gate(
            "delisted_halted_status",
            "Delisted/halted/suspended status tape",
            blocks=False,
            partial=True,
            detail=(
                "Official historical delisted/halted tape is out of scope because this chapter is restricted to current active Market Stats V1 symbols; "
                "event-level path-quality proxy remains used for censoring and risk notes."
            ),
            evidence={
                "official_status_tape_available": False,
                "active_universe_restriction": True,
                "event_level_proxy_available": True,
                "proxy_flagged_events": int(flags.sum()),
                "proxy_flag_rate_pct": round(float(flags.mean()) * 100.0, 2) if len(flags) else 0.0,
            },
            severity="Critical",
        )
    return _gate(
        "delisted_halted_status",
        "Delisted/halted/suspended status tape",
        blocks=True,
        detail="Current artifacts do not include a point-in-time listing status tape for delisted, halted, or suspended symbols.",
        evidence={"available_in_events": False, "available_in_market_stats_metadata": False},
        severity="Critical",
    )


def _price_limit_gate() -> DataGateResult:
    return _gate(
        "price_limit_microstructure",
        "Price-limit and microstructure encoding",
        blocks=False,
        partial=True,
        detail="OHLCV path exists, but price-limit, tick-size, lot-size, and settlement states are not encoded as event-level fields.",
        evidence={"ohlcv_path_available": True, "price_limit_state_available": False},
        severity="Medium",
    )


def audit_chapter_data_gates(
    *,
    pattern_key: str,
    events_csv: Path,
    path_csv: Path,
    market_stats_json: Path,
    membership_db: Path,
    stock_series_dir: Path,
    horizon_days: int = 60,
    cooldown_days: int = 15,
    universe_scope: str = "full_point_in_time",
    use_historical_membership: bool = True,
) -> Dict[str, Any]:
    events = pd.read_csv(events_csv)
    path = pd.read_csv(path_csv)
    metadata = _read_json(market_stats_json)
    gates: List[DataGateResult] = []
    gates.extend(_metadata_gate(metadata if isinstance(metadata, Mapping) else {}, events, universe_scope=universe_scope))
    gates.append(_active_universe_gate(metadata if isinstance(metadata, Mapping) else {}, events, universe_scope=universe_scope))
    gates.append(
        _membership_db_gate(
            membership_db,
            pd.to_datetime(events.get("breakout_date", pd.Series(dtype=str)), errors="coerce").dropna(),
            use_historical_membership=bool(use_historical_membership),
        )
    )
    gates.append(_event_artifact_gate(events, path, horizon_days))
    gates.append(_overlap_gate(events, cooldown_days))
    gates.append(_liquidity_gate(events, stock_series_dir))
    gates.append(_delisted_status_gate(events, universe_scope=universe_scope))
    gates.append(_price_limit_gate())
    high_blocks = [gate.gate_id for gate in gates if gate.blocks_investment_reference and gate.severity in {"High", "Critical"}]
    return {
        "standard_version": GATE_STANDARD_VERSION,
        "pattern_key": pattern_key,
        "universe_scope": universe_scope,
        "use_historical_membership": bool(use_historical_membership),
        "horizon_days": int(horizon_days),
        "investment_reference_data_gates_pass": not high_blocks,
        "blocked_by": high_blocks,
        "summary": {
            "pass": sum(1 for gate in gates if gate.status == "PASS"),
            "partial": sum(1 for gate in gates if gate.status == "PARTIAL"),
            "fail": sum(1 for gate in gates if gate.status == "FAIL"),
        },
        "gates": [gate.to_dict() for gate in gates],
    }


def render_data_gate_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        f"# Data Gate Audit: {report.get('pattern_key')}",
        "",
        f"- standard: `{report.get('standard_version')}`",
        f"- universe_scope: `{report.get('universe_scope')}`",
        f"- use_historical_membership: `{report.get('use_historical_membership')}`",
        f"- investment_reference_data_gates_pass: `{report.get('investment_reference_data_gates_pass')}`",
        f"- blocked_by: `{', '.join(report.get('blocked_by') or []) or 'none'}`",
        "",
        "| Gate | Status | Severity | Blocks investment-reference | Detail |",
        "|---|---|---|---:|---|",
    ]
    for gate in report.get("gates", []):
        lines.append(
            "| {gate} | {status} | {severity} | {blocks} | {detail} |".format(
                gate=gate.get("label"),
                status=gate.get("status"),
                severity=gate.get("severity"),
                blocks="yes" if gate.get("blocks_investment_reference") else "no",
                detail=str(gate.get("detail") or "").replace("|", "/"),
            )
        )
    return "\n".join(lines) + "\n"
