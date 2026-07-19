"""Apply the After-the-Buy deep integration pack to project workflows.

This builder is the first application layer after source extraction.  It does
not claim a new backtest score unless a real rerun exists.  Instead, it turns
the V2 rule pack into operational artifacts:

- scope for all 63 chapters,
- priority-pattern rule notes,
- data support checks,
- scanner/stat/trade before-after tables,
- defensive runtime signals,
- publication pilot payload for the "Hành vi sau phá vỡ" section.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.rebuild_source_guided_final_chapters import DOUBLE_VARIANTS, EVENT_SOURCES  # noqa: E402


APPLICATION_ID = "after_buy_vietnam_application_layer_v1"
DEFAULT_AFTER_BUY_V2_DIR = Path("artifacts/scanner_v2/after_buy_vietnam_v2")
DEFAULT_OUT_DIR = DEFAULT_AFTER_BUY_V2_DIR / "application"

PRIORITY_PATTERNS: tuple[str, ...] = (
    "bull_pennants",
    "triangles_ascending",
    "triangles_descending",
    "triangles_symmetrical",
    "broadening_bottoms",
    "rectangle_bottoms",
    "head_and_shoulders_bottoms",
    "head_and_shoulders_bottoms_complex",
    "double_bottoms_adam_eve",
    "double_bottoms_eve_adam",
    "double_bottoms_eve_eve",
    "double_bottoms_adam_adam",
)

PILOT_PUBLICATION_PATTERNS: tuple[str, ...] = (
    "bull_pennants",
    "broadening_bottoms",
    "triangles_ascending",
    "rectangle_bottoms",
    "head_and_shoulders_bottoms",
)

METRIC_SUPPORT_COLUMNS: dict[str, tuple[str, ...]] = {
    "target_first_before_stop": ("target_first_before_adverse_5pct", "target_first", "failure_5pct"),
    "stop_hit_before_target": ("failure_5pct", "mae_pct", "target_first_before_adverse_5pct"),
    "time_to_target": ("time_to_target", "target_hit_days", "bars_to_target"),
    "time_to_stop": ("time_to_stop", "bars_to_failure", "failure_5pct"),
    "retest_success_rate": ("throwback", "pullback", "retest", "return_to_breakout"),
    "path_discomfort_score": ("mae_pct", "mfe_pct", "target_first_before_adverse_5pct"),
    "fold_level_robustness": ("market_regime", "liquidity_bucket", "market_group"),
}


def _read_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_json(path: Path, data: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _load_v2(v2_dir: Path) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]], list[Mapping[str, Any]]]:
    config = _read_json(v2_dir / "after_buy_scanner_stat_trade_config.json")
    coverage = _read_json(v2_dir / "after_buy_chapter_coverage_matrix.json")
    deep_rules = _read_json(v2_dir / "after_buy_deep_rules.json")
    config_by_pattern = {
        str(row.get("pattern_id")): row
        for row in config.get("patterns", [])
        if isinstance(row, Mapping) and row.get("pattern_id")
    }
    coverage_by_pattern = {
        str(row.get("pattern_id")): row
        for row in coverage.get("chapters", [])
        if isinstance(row, Mapping) and row.get("pattern_id")
    }
    rule_rows = [row for row in deep_rules.get("rules", []) if isinstance(row, Mapping)]
    return config_by_pattern, coverage_by_pattern, rule_rows


def _rules_by_pattern(rule_rows: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rule_rows:
        grouped[str(row.get("pattern_id"))].append(row)
    return grouped


def _event_source_for_pattern(pattern_id: str) -> Path | None:
    if pattern_id in EVENT_SOURCES:
        return EVENT_SOURCES[pattern_id][0]
    if pattern_id in DOUBLE_VARIANTS:
        family, _variant = DOUBLE_VARIANTS[pattern_id]
        return Path("artifacts/scanner_v2/double_pattern_family_adam_eve_branch") / family / "db_active/events.csv"
    return None


def _event_artifact_profile(pattern_id: str) -> dict[str, Any]:
    source = _event_source_for_pattern(pattern_id)
    if source is None or not source.exists():
        return {
            "pattern_id": pattern_id,
            "event_source": str(source) if source else "",
            "event_source_exists": False,
            "event_count": 0,
            "column_count": 0,
            "available_columns": [],
            "metric_support": {metric: False for metric in METRIC_SUPPORT_COLUMNS},
        }
    df = pd.read_csv(source, low_memory=False)
    columns = set(df.columns)
    metric_support = {
        metric: any(token in columns or any(token in column for column in columns) for token in candidates)
        for metric, candidates in METRIC_SUPPORT_COLUMNS.items()
    }
    latest_date = None
    for date_column in ("confirmation_date", "breakout_date", "pattern_end", "formation_end"):
        if date_column in df.columns:
            dates = pd.to_datetime(df[date_column], errors="coerce")
            if dates.notna().any():
                latest_date = dates.max().date().isoformat()
            break
    return {
        "pattern_id": pattern_id,
        "event_source": str(source),
        "event_source_exists": True,
        "event_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "latest_event_date": latest_date,
        "available_columns": sorted(df.columns),
        "metric_support": metric_support,
    }


def _scope_rows(
    config_by_pattern: Mapping[str, Mapping[str, Any]],
    coverage_by_pattern: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pattern_id, config in sorted(config_by_pattern.items()):
        coverage = coverage_by_pattern.get(pattern_id, {})
        buy_allowed = bool(config.get("buy_layer_allowed"))
        trade_mode = str(config.get("trade_layer_mode") or "")
        if buy_allowed and trade_mode == "preserve_tradable_final":
            group = "buy_pass"
        elif buy_allowed and config.get("no_overfit_gate", {}).get("currently_blocked"):
            group = "buy_or_watchlist_blocked"
        elif buy_allowed:
            group = "buy_watchlist_eligible"
        elif any(token in pattern_id for token in ("top", "bear", "down")):
            group = "defensive"
        else:
            group = "reference_or_unmapped"
        rows.append(
            {
                "pattern_id": pattern_id,
                "scope_group": group,
                "buy_layer_allowed": buy_allowed,
                "local_role": config.get("local_role"),
                "buy_scope": config.get("buy_scope"),
                "trade_layer_mode": trade_mode,
                "tradable_score": coverage.get("tradable_score"),
                "tradable_release_status": coverage.get("tradable_release_status"),
                "tradable_blockers": coverage.get("tradable_blockers"),
                "recommended_action": coverage.get("recommended_after_buy_action"),
            }
        )
    return rows


def _accepted_rejected_rules(pattern_id: str, rules: Sequence[Mapping[str, Any]], profile: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    available_columns = set(profile.get("available_columns") or [])
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for rule in rules:
        layers = set(rule.get("layers") or [])
        needs_path_or_event = bool(layers & {"scanner_rule", "stat_metric", "trade_layer_rule"})
        supported = bool(profile.get("event_source_exists")) and (not needs_path_or_event or bool(available_columns))
        row = {
            "pattern_id": pattern_id,
            "rule_id": rule.get("rule_id"),
            "layers": rule.get("layers"),
            "source_section": rule.get("source_section"),
            "local_interpretation": rule.get("local_interpretation"),
            "data_supported": supported,
            "decision": "accepted_for_application" if supported else "rejected_until_data_available",
        }
        if supported:
            accepted.append(row)
        else:
            rejected.append(row)
    return accepted, rejected


def _scanner_before_after_rows(
    priority_patterns: Sequence[str],
    config_by_pattern: Mapping[str, Mapping[str, Any]],
    profiles: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pattern_id in priority_patterns:
        config = config_by_pattern[pattern_id]
        profile = profiles[pattern_id]
        rule_count = len(config.get("scanner_quality_rule_ids") or [])
        rows.append(
            {
                "pattern_id": pattern_id,
                "before_scanner_state": "base_pattern_event_artifact",
                "after_scanner_state": "after_buy_quality_overlay" if rule_count else "unchanged_no_after_buy_scanner_rule",
                "event_count_before": profile.get("event_count"),
                "event_count_after_overlay": profile.get("event_count"),
                "scanner_rule_count": rule_count,
                "data_supported": profile.get("event_source_exists"),
                "sample_depth_policy": "non_destructive_overlay_first",
            }
        )
    return rows


def _statistics_rows(priority_patterns: Sequence[str], config_by_pattern: Mapping[str, Mapping[str, Any]], profiles: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pattern_id in priority_patterns:
        support = profiles[pattern_id].get("metric_support", {})
        for metric_name, supported in support.items():
            rows.append(
                {
                    "pattern_id": pattern_id,
                    "metric_name": metric_name,
                    "before": "not_source_indexed_in_after_buy_layer",
                    "after": "source_indexed_metric_candidate" if supported else "documented_data_gap",
                    "data_supported": supported,
                    "stat_rule_count": len(config_by_pattern[pattern_id].get("required_stat_rule_ids") or []),
                }
            )
    return rows


def _tradable_rows(priority_patterns: Sequence[str], config_by_pattern: Mapping[str, Mapping[str, Any]], coverage_by_pattern: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pattern_id in priority_patterns:
        config = config_by_pattern[pattern_id]
        coverage = coverage_by_pattern[pattern_id]
        no_overfit = config.get("no_overfit_gate") if isinstance(config.get("no_overfit_gate"), Mapping) else {}
        before_score = coverage.get("tradable_score")
        rows.append(
            {
                "pattern_id": pattern_id,
                "before_score": before_score,
                "after_score": before_score,
                "score_delta": 0,
                "before_decision": coverage.get("tradable_status"),
                "after_decision": config.get("trade_layer_mode"),
                "trade_rule_count": len(config.get("trade_layer_rule_ids") or []),
                "no_overfit_blocked": bool(no_overfit.get("currently_blocked")),
                "blockers": coverage.get("tradable_blockers"),
                "interpretation": "logic_and_governance_improved_score_not_recomputed" if before_score is not None else "needs_real_tradable_rerun",
            }
        )
    return rows


def _publication_payload(
    pilot_patterns: Sequence[str],
    config_by_pattern: Mapping[str, Mapping[str, Any]],
    coverage_by_pattern: Mapping[str, Mapping[str, Any]],
    rules_by_pattern: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for pattern_id in pilot_patterns:
        config = config_by_pattern[pattern_id]
        coverage = coverage_by_pattern[pattern_id]
        rules = list(rules_by_pattern.get(pattern_id, []))
        scanner_rules = [rule.get("local_interpretation") for rule in rules if "scanner_rule" in (rule.get("layers") or [])][:3]
        stat_rules = [rule.get("local_interpretation") for rule in rules if "stat_metric" in (rule.get("layers") or [])][:3]
        trade_rules = [rule.get("local_interpretation") for rule in rules if "trade_layer_rule" in (rule.get("layers") or [])][:3]
        mode = config.get("publication_after_buy_section", {}).get("mode")
        payload.append(
            {
                "pattern_id": pattern_id,
                "section_title": "Hành vi sau phá vỡ",
                "section_mode": mode,
                "opening": (
                    "Phần này đọc mẫu hình sau khi đã xác nhận, tập trung vào đường đi, mục tiêu, thất bại và cách sử dụng thực tế."
                ),
                "scanner_points": scanner_rules,
                "stat_points": stat_rules,
                "trade_points": trade_rules,
                "classification": config.get("trade_layer_mode"),
                "tradable_score": coverage.get("tradable_score"),
                "blockers": coverage.get("tradable_blockers"),
                "writing_guardrail": "Không viết như khuyến nghị mua bán; dùng như diễn giải hậu phá vỡ có điều kiện.",
            }
        )
    return payload


def _defensive_signals(scope_rows: Sequence[Mapping[str, Any]], config_by_pattern: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in scope_rows:
        if row["buy_layer_allowed"]:
            continue
        pattern_id = str(row["pattern_id"])
        config = config_by_pattern[pattern_id]
        rows.append(
            {
                "pattern_id": pattern_id,
                "signal_type": "risk_context_signal",
                "allowed_use": "avoid_buy_or_exit_warning",
                "forbidden_use": "long_cash_buy_setup",
                "publication_mode": config.get("publication_after_buy_section", {}).get("mode"),
            }
        )
    return rows


def build_after_buy_application_layer(
    *,
    after_buy_v2_dir: Path = DEFAULT_AFTER_BUY_V2_DIR,
    out_dir: Path = DEFAULT_OUT_DIR,
    priority_patterns: Sequence[str] = PRIORITY_PATTERNS,
) -> dict[str, Any]:
    config_by_pattern, coverage_by_pattern, rule_rows = _load_v2(after_buy_v2_dir)
    rules_by_pattern = _rules_by_pattern(rule_rows)
    scope = _scope_rows(config_by_pattern, coverage_by_pattern)
    profiles = {pattern_id: _event_artifact_profile(pattern_id) for pattern_id in priority_patterns}
    scanner_rows = _scanner_before_after_rows(priority_patterns, config_by_pattern, profiles)
    stat_rows = _statistics_rows(priority_patterns, config_by_pattern, profiles)
    tradable_rows = _tradable_rows(priority_patterns, config_by_pattern, coverage_by_pattern)
    defensive = _defensive_signals(scope, config_by_pattern)
    publication_payload = _publication_payload(PILOT_PUBLICATION_PATTERNS, config_by_pattern, coverage_by_pattern, rules_by_pattern)

    for pattern_id in priority_patterns:
        pattern_dir = out_dir / "priority_patterns" / pattern_id
        accepted, rejected = _accepted_rejected_rules(pattern_id, rules_by_pattern.get(pattern_id, []), profiles[pattern_id])
        notes = {
            "pattern_id": pattern_id,
            "source_rule_count": len(rules_by_pattern.get(pattern_id, [])),
            "accepted_rule_count": len(accepted),
            "rejected_rule_count": len(rejected),
            "event_profile": profiles[pattern_id],
            "trade_layer_mode": config_by_pattern[pattern_id].get("trade_layer_mode"),
            "recommended_action": coverage_by_pattern[pattern_id].get("recommended_after_buy_action"),
        }
        _write_json(pattern_dir / "after_buy_application_notes.json", notes)
        _write_json(pattern_dir / "candidate_rules.json", list(rules_by_pattern.get(pattern_id, [])))
        _write_json(pattern_dir / "accepted_rules.json", accepted)
        _write_json(pattern_dir / "rejected_rules.json", rejected)
        _write_blocker_summary(pattern_dir / "blocker_summary.md", pattern_id, coverage_by_pattern[pattern_id], config_by_pattern[pattern_id], accepted, rejected)

    scope_doc = {
        "application_id": APPLICATION_ID,
        "source_config": str(after_buy_v2_dir / "after_buy_scanner_stat_trade_config.json"),
        "chapter_count": len(scope),
        "priority_patterns": list(priority_patterns),
        "groups": {
            "buy_pass": sum(1 for row in scope if row["scope_group"] == "buy_pass"),
            "buy_or_watchlist_blocked": sum(1 for row in scope if row["scope_group"] == "buy_or_watchlist_blocked"),
            "defensive": sum(1 for row in scope if row["scope_group"] == "defensive"),
            "reference_or_unmapped": sum(1 for row in scope if row["scope_group"] == "reference_or_unmapped"),
        },
        "chapters": scope,
    }
    report = _report(scope_doc, scanner_rows, stat_rows, tradable_rows, defensive, publication_payload)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "after_buy_application_scope.json", scope_doc)
    _write_csv(out_dir / "scanner_before_after.csv", scanner_rows)
    _write_json(out_dir / "scanner_before_after.json", scanner_rows)
    _write_csv(out_dir / "statistics_metric_plan.csv", stat_rows)
    _write_json(out_dir / "statistics_metric_plan.json", stat_rows)
    _write_csv(out_dir / "tradable_before_after.csv", tradable_rows)
    _write_json(out_dir / "tradable_before_after.json", tradable_rows)
    _write_json(out_dir / "defensive_runtime_signals.json", defensive)
    _write_json(out_dir / "publication_pilot_payload.json", publication_payload)
    _write_json(out_dir / "after_buy_application_report.json", report)
    _write_report_md(out_dir / "after_buy_application_report.md", report)

    failures: list[str] = []
    if len(scope) != 63:
        failures.append(f"expected_63_scope_rows_found_{len(scope)}")
    if not any(row["after_scanner_state"] == "after_buy_quality_overlay" for row in scanner_rows):
        failures.append("missing_scanner_overlay")
    if not any(row["data_supported"] for row in stat_rows):
        failures.append("missing_supported_stat_metrics")
    if not tradable_rows:
        failures.append("missing_tradable_before_after")
    if not publication_payload:
        failures.append("missing_publication_pilot_payload")
    return {
        "application_id": APPLICATION_ID,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "out_dir": str(out_dir),
        "summary": report["summary"],
    }


def _write_blocker_summary(
    path: Path,
    pattern_id: str,
    coverage: Mapping[str, Any],
    config: Mapping[str, Any],
    accepted: Sequence[Mapping[str, Any]],
    rejected: Sequence[Mapping[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {pattern_id} After-the-Buy Blocker Summary",
        "",
        f"- Trade layer mode: `{config.get('trade_layer_mode')}`",
        f"- Tradable score: `{coverage.get('tradable_score')}`",
        f"- Release status: `{coverage.get('tradable_release_status')}`",
        f"- Blockers: `{coverage.get('tradable_blockers')}`",
        f"- Accepted rules: `{len(accepted)}`",
        f"- Rejected rules: `{len(rejected)}`",
        "",
        "Decision: apply source-grounded rules as overlay or watchlist logic first; do not promote if no-overfit gate remains blocked.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _report(
    scope_doc: Mapping[str, Any],
    scanner_rows: Sequence[Mapping[str, Any]],
    stat_rows: Sequence[Mapping[str, Any]],
    tradable_rows: Sequence[Mapping[str, Any]],
    defensive: Sequence[Mapping[str, Any]],
    publication_payload: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "application_id": APPLICATION_ID,
        "summary": {
            "chapter_count": scope_doc["chapter_count"],
            "priority_pattern_count": len(scope_doc["priority_patterns"]),
            "scanner_overlay_patterns": sum(1 for row in scanner_rows if row["after_scanner_state"] == "after_buy_quality_overlay"),
            "supported_stat_metric_rows": sum(1 for row in stat_rows if row["data_supported"]),
            "tradable_before_after_rows": len(tradable_rows),
            "defensive_signal_count": len(defensive),
            "publication_pilot_count": len(publication_payload),
        },
        "before_after": {
            "scanner": "from base artifact only to After-the-Buy quality overlay",
            "statistics": "from generic metrics to source-indexed candidate metrics",
            "trade_layer": "from scattered scorecards to no-overfit before/after decision table",
            "publication": "from no systematic after-buy section to pilot payload for five chapters",
        },
        "kpi": {
            "source_usage": "PASS",
            "scanner": "PASS" if any(row["after_scanner_state"] == "after_buy_quality_overlay" for row in scanner_rows) else "FAIL",
            "statistics": "PASS" if any(row["data_supported"] for row in stat_rows) else "FAIL",
            "trade_layer": "PASS" if tradable_rows else "FAIL",
            "defensive_safety": "PASS" if defensive else "FAIL",
            "publication": "PASS" if publication_payload else "FAIL",
            "report": "PASS",
        },
    }


def _write_report_md(path: Path, report: Mapping[str, Any]) -> None:
    lines = [
        "# After-the-Buy Application Layer Report",
        "",
        f"- Application ID: `{report['application_id']}`",
        "",
        "## KPI",
        "",
        "| KPI | Status |",
        "|---|---|",
    ]
    for key, status in report["kpi"].items():
        lines.append(f"| `{key}` | `{status}` |")
    lines.extend(
        [
            "",
            "## Before / After",
            "",
            "| Layer | Change |",
            "|---|---|",
        ]
    )
    for key, change in report["before_after"].items():
        lines.append(f"| `{key}` | {change} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build After-the-Buy application layer artifacts.")
    parser.add_argument("--after-buy-v2-dir", type=Path, default=DEFAULT_AFTER_BUY_V2_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    result = build_after_buy_application_layer(after_buy_v2_dir=args.after_buy_v2_dir, out_dir=args.out_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
