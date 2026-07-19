"""Build the canonical Bull Flag publication chapter.

The descriptive chapter PDF and the release-gate PDF answer different
questions. This builder creates one canonical publication payload first, then
renders Markdown/PDF only from that payload so the chapter cannot drift away
from the release artifacts.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_STATS = Path("artifacts/scanner_v2/bull_flags/statistics.json")
DEFAULT_RELEASE = Path("artifacts/scanner_v2/bull_flags_release_candidate/bull_flag_release_candidate.json")
DEFAULT_SCORECARD = Path("artifacts/scanner_v2/bull_flags_tradable_setup/bull_flag_tradable_scorecard.json")
DEFAULT_SELECTED_STRATEGY = Path("artifacts/scanner_v2/bull_flags_tradable_setup/bull_flag_tradable_selected_strategy.json")
DEFAULT_SUPPORTING_ROBUSTNESS = Path("artifacts/scanner_v2/bull_flags_supporting_robustness/bull_flag_supporting_robustness.json")
DEFAULT_FRESH_GATE = Path("artifacts/scanner_v2/bull_flags_fresh_discovery/gate/bull_flag_wider_oos_gate.json")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bull_flags_publication_chapter")

BULKOWSKI_FLAGS_URL = "https://thepatternsite.com/flags.html"
BULKOWSKI_MEASURE_URL = "https://thepatternsite.com/measure.html"


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def _nested(mapping: Mapping[str, Any], *keys: str) -> Any:
    value: Any = mapping
    for key in keys:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _as_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _target_row(stats: Mapping[str, Any], multiple: float, label: str = "bull_flags") -> Dict[str, Any]:
    for row in stats.get("target_family_sensitivity") or []:
        if not isinstance(row, Mapping):
            continue
        if row.get("label") == label and _as_float(row.get("target_multiple")) == float(multiple):
            return dict(row)
    return {}


def _target_rows(stats: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for multiple in (0.46, 0.5, 0.75, 1.0):
        row = _target_row(stats, multiple)
        if row:
            rows.append(row)
    return rows


def _source_record(path: Path, role: str) -> Dict[str, Any]:
    return {
        "role": role,
        "path": str(path),
        "exists": path.exists(),
    }


def _required_paths(paths: Mapping[str, Path]) -> List[str]:
    return [str(path) for path in paths.values() if not path.exists()]


def build_publication_payload(
    *,
    stats_path: Path = DEFAULT_STATS,
    release_path: Path = DEFAULT_RELEASE,
    scorecard_path: Path = DEFAULT_SCORECARD,
    selected_strategy_path: Path = DEFAULT_SELECTED_STRATEGY,
    supporting_robustness_path: Path = DEFAULT_SUPPORTING_ROBUSTNESS,
    fresh_gate_path: Path = DEFAULT_FRESH_GATE,
) -> Dict[str, Any]:
    paths = {
        "chapter_statistics": stats_path,
        "release_candidate": release_path,
        "tradable_scorecard": scorecard_path,
        "selected_strategy": selected_strategy_path,
        "supporting_robustness": supporting_robustness_path,
        "fresh_gate": fresh_gate_path,
    }
    missing = _required_paths(paths)
    if missing:
        return {
            "publication_id": "bull_flag_publication_chapter_v1",
            "status": "BLOCK",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "failures": ["missing_required_artifacts"],
            "missing_artifacts": missing,
            "source_records": [_source_record(path, role) for role, path in paths.items()],
        }

    stats = _read_json(stats_path)
    release = _read_json(release_path)
    scorecard = _read_json(scorecard_path)
    selected = _read_json(selected_strategy_path)
    support = _read_json(supporting_robustness_path)
    fresh_gate = _read_json(fresh_gate_path)

    selected_metrics = selected.get("selected_metrics") if isinstance(selected.get("selected_metrics"), Mapping) else {}
    fresh_eval = fresh_gate.get("full_profile_evaluation") if isinstance(fresh_gate.get("full_profile_evaluation"), Mapping) else {}
    fresh_summary = fresh_eval.get("summary") if isinstance(fresh_eval.get("summary"), Mapping) else {}
    fresh_scorecard = fresh_eval.get("scorecard") if isinstance(fresh_eval.get("scorecard"), Mapping) else {}

    target_rows = _target_rows(stats)
    base_target = _target_row(stats, 0.46)
    legacy_target = _target_row(stats, 1.0)

    consistency_checks = [
        {
            "check_id": "release_pass",
            "status": "PASS" if release.get("release_status") == "PASS" else "FAIL",
            "detail": "Release-candidate gate must pass before publication rendering.",
        },
        {
            "check_id": "scorecard_consistent",
            "status": "PASS" if _as_float(release.get("conservative_score")) == _as_float(scorecard.get("score")) else "WARN",
            "detail": "Conservative release score is compared with the main scorecard. Fresh score may be higher.",
        },
        {
            "check_id": "base_target_present",
            "status": "PASS" if base_target else "FAIL",
            "detail": "Publication chapter requires the 0.46x Bull Flag target row.",
        },
        {
            "check_id": "supporting_robustness_pass",
            "status": "PASS" if support.get("status") == "PASS" and not support.get("failures") else "FAIL",
            "detail": "Supporting robustness must pass for release-candidate chapter.",
        },
        {
            "check_id": "fresh_candidate_present",
            "status": "PASS" if _nested(fresh_gate, "scope", "is_fresh_oos") is True else "WARN",
            "detail": "Fresh-source evidence should be present; scope caveats remain visible.",
        },
    ]
    failures = [row["check_id"] for row in consistency_checks if row["status"] == "FAIL"]

    payload: Dict[str, Any] = {
        "publication_id": "bull_flag_publication_chapter_v1",
        "status": "PASS" if not failures else "BLOCK",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "classification": release.get("classification"),
        "claim_level": release.get("claim_level"),
        "narrative_contract": {
            "headline_label": "Bull Flag Tradable Research Candidate 95+ under available-series scope",
            "primary_claim": "Bull Flag is a Vietnam-localized continuation setup with a Bulkowski-aligned 0.46x pole target and executable research evidence.",
            "reference_layer": "Describes post-breakout behavior, target calibration, MFE/MAE, target-first, failure, and splits.",
            "tradable_layer": "Adds entry delay, stop, max holding, costs, slippage, sizing, capacity, validation/holdout, walk-forward, and fresh-source checks.",
            "claim_boundary": "Research candidate only; not production trading and not personalized buy/sell advice.",
        },
        "report_structure": [
            "Cover and release snapshot",
            "Bull Flag rule anatomy and scanner contract",
            "Reference statistics and target calibration",
            "Execution setup: entry, exit, costs, sizing, capacity",
            "Validation, holdout, walk-forward and fresh-source evidence",
            "Robustness: overlap, liquidity, price-limit proxy",
            "Bulkowski alignment and Vietnam localization",
            "Data caveats, forbidden claims and next checks",
        ],
        "chapter_reference": {
            "symbols_scanned": stats.get("symbols_scanned"),
            "events": stats.get("detection_count"),
            "evaluated_events": stats.get("evaluated_count"),
            "median_mfe_pct": stats.get("median_mfe_pct"),
            "median_mae_pct": stats.get("median_mae_pct"),
            "mfe_mae_median_ratio": base_target.get("mfe_mae_median_ratio"),
            "failure_5pct_rate": stats.get("failure_5pct_rate"),
            "legacy_target_hit_rate": stats.get("target_hit_rate"),
            "legacy_target_first_before_adverse_5pct_rate": stats.get("target_first_before_adverse_5pct_rate"),
            "liquidity_proxy_table": stats.get("liquidity_proxy_table"),
            "regime_proxy_table": stats.get("regime_proxy_table"),
            "path_quality_audit": stats.get("path_quality_audit"),
        },
        "scanner_contract": {
            "detector_config": stats.get("detector_config"),
            "event_filter_config": stats.get("event_filter_config"),
            "setup_confirmation_followthrough": {
                "min_setup_score": selected_metrics.get("min_setup_score"),
                "min_confirmation_score": selected_metrics.get("min_confirmation_score"),
                "entry_delay_bars": selected_metrics.get("entry_delay_bars"),
                "min_breakout_date": selected_metrics.get("min_breakout_date"),
                "allowed_market_regimes": selected_metrics.get("allowed_market_regimes"),
                "exclude_bear_high_liquidity_setup_score_min": selected_metrics.get("exclude_bear_high_liquidity_setup_score_min"),
            },
            "anatomy": [
                "Flagpole: prior upward move with minimum pole change and slope.",
                "Flag body: short consolidation channel controlled by width, height, slope and flag-to-pole ratio.",
                "Confirmation: upward breakout after the flag, then an executable delayed-entry layer.",
                "Follow-through: measured separately with post-breakout path metrics; not used to select the event ex ante.",
            ],
        },
        "target_calibration": {
            "target_family": stats.get("target_family"),
            "selected_base_target_multiple": 0.46,
            "selected_base_target_role": "bulkowski_adjusted_base",
            "base_target": base_target,
            "legacy_target": legacy_target,
            "rows": target_rows,
            "interpretation": "0.46x pole is the publication headline target; 1.0x remains a legacy/full-pole stretch benchmark.",
        },
        "release_candidate": release,
        "tradable_setup": {
            "scorecard": scorecard,
            "selected_strategy_id": selected.get("selected_strategy_id"),
            "selection_basis": selected.get("selection_basis"),
            "selected_metrics": selected_metrics,
            "rule_contract": selected.get("frozen_rule_contract"),
            "walk_forward_summary": selected.get("walk_forward_summary"),
            "cost_stress_summary": selected.get("cost_stress_summary"),
            "monte_carlo_summary": selected.get("monte_carlo_summary"),
            "calendar_oos_summary": selected.get("calendar_oos_summary"),
        },
        "fresh_candidate": {
            "scope": fresh_gate.get("scope"),
            "source_manifest": fresh_gate.get("source_manifest"),
            "data_provenance_audit": fresh_gate.get("data_provenance_audit"),
            "scorecard": fresh_scorecard,
            "summary": fresh_summary,
            "walk_forward_summary": fresh_eval.get("walk_forward_summary"),
            "cost_stress_summary": fresh_eval.get("cost_stress_summary"),
            "monte_carlo_summary": fresh_eval.get("monte_carlo_summary"),
        },
        "supporting_robustness": support,
        "bulkowski_alignment": {
            "sources": {
                "flags": BULKOWSKI_FLAGS_URL,
                "measure_rule": BULKOWSKI_MEASURE_URL,
            },
            "bulkowski_flags_reference": {
                "pattern_type": "short-term continuation flag after a sharp flagpole",
                "upward_measure_rule_pct_of_pole": 46,
                "reported_average_rise_pct": 9,
                "reported_average_decline_pct": 8,
                "reported_break_even_failure_up_pct": 44,
                "reported_break_even_failure_down_pct": 45,
            },
            "vietnam_implementation": {
                "base_target_multiple": 0.46,
                "legacy_target_multiple": 1.0,
                "bull_flag_only": True,
                "bear_flag_handling": "defensive/informational reference for cash equities",
            },
            "alignment_summary": "The target calibration follows Bulkowski's adjusted Flags measure rule; the executable layer is an added Vietnam-specific research layer.",
        },
        "data_scope_and_caveats": {
            "available_series_scope": True,
            "closed_supporting_caveats": release.get("closed_supporting_caveats"),
            "remaining_caveats": release.get("remaining_caveats"),
            "forbidden_claims": release.get("forbidden_claims"),
        },
        "source_records": [_source_record(path, role) for role, path in paths.items()],
        "consistency_checks": consistency_checks,
        "failures": failures,
    }
    return payload


def _fmt(value: Any, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        text = f"{value:.2f}".rstrip("0").rstrip(".")
    else:
        text = str(value)
    return f"{text}{suffix}"


def _wrap(text: Any, width: int = 94) -> List[str]:
    return textwrap.wrap(str(text), width=width) or [""]


def _draw_lines(fig: Any, lines: Sequence[Any], *, x: float, y: float, width: int = 95, fontsize: float = 8.4, step: float = 0.020) -> float:
    for line in lines:
        for part in _wrap(line, width=width):
            fig.text(x, y, part, fontsize=fontsize, ha="left", va="top")
            y -= step
        y -= step * 0.35
    return y


def _draw_table(
    fig: Any,
    rows: Sequence[Sequence[Any]],
    *,
    x: float,
    y: float,
    col_x: Sequence[float],
    fontsize: float = 7.6,
    row_step: float = 0.028,
) -> float:
    for row_index, row in enumerate(rows):
        weight = "bold" if row_index == 0 else None
        for col_index, value in enumerate(row):
            fig.text(x + col_x[col_index], y, str(value), fontsize=fontsize, ha="left", va="top", weight=weight)
        y -= row_step
    return y


def _page(fig: Any, title: str) -> None:
    fig.patch.set_facecolor("#fffdf8")
    fig.text(0.08, 0.93, title, fontsize=16, weight="bold", ha="left", va="top", color="#171717")


def render_publication_markdown(payload: Mapping[str, Any]) -> str:
    ref = payload.get("chapter_reference") if isinstance(payload.get("chapter_reference"), Mapping) else {}
    target = payload.get("target_calibration") if isinstance(payload.get("target_calibration"), Mapping) else {}
    release = payload.get("release_candidate") if isinstance(payload.get("release_candidate"), Mapping) else {}
    tradable = payload.get("tradable_setup") if isinstance(payload.get("tradable_setup"), Mapping) else {}
    selected = tradable.get("selected_metrics") if isinstance(tradable.get("selected_metrics"), Mapping) else {}
    fresh = payload.get("fresh_candidate") if isinstance(payload.get("fresh_candidate"), Mapping) else {}
    fresh_summary = fresh.get("summary") if isinstance(fresh.get("summary"), Mapping) else {}

    lines = [
        "# Bull Flag Publication Chapter",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- Classification: `{payload.get('classification')}`",
        f"- Claim level: {payload.get('claim_level')}",
        "",
        "## Narrative Contract",
        "",
    ]
    contract = payload.get("narrative_contract") if isinstance(payload.get("narrative_contract"), Mapping) else {}
    for key in ("headline_label", "primary_claim", "reference_layer", "tradable_layer", "claim_boundary"):
        lines.append(f"- **{key}**: {contract.get(key)}")
    lines.extend(["", "## Report Structure", ""])
    for i, item in enumerate(payload.get("report_structure") or [], start=1):
        lines.append(f"{i}. {item}")
    lines.extend(
        [
            "",
            "## Scanner Contract",
            "",
        ]
    )
    scanner = payload.get("scanner_contract") if isinstance(payload.get("scanner_contract"), Mapping) else {}
    for item in scanner.get("anatomy") or []:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Reference Snapshot",
            "",
            f"- Events: `{ref.get('events')}` / evaluated `{ref.get('evaluated_events')}`",
            f"- Median MFE/MAE: `{ref.get('median_mfe_pct')}% / {ref.get('median_mae_pct')}%`",
            f"- Base target hit: `{_nested(target, 'base_target', 'target_hit_rate')}%`",
            f"- Legacy 1.0x hit: `{ref.get('legacy_target_hit_rate')}%`",
            f"- Failure 5%: `{ref.get('failure_5pct_rate')}%`",
            "",
            "## Tradable Release",
            "",
            f"- Release status: `{release.get('release_status')}`",
            f"- Conservative score: `{release.get('conservative_score')}`",
            f"- Main trades/return: `{selected.get('trades')}` / `{selected.get('total_return_pct')}%`",
            f"- Fresh trades/return: `{fresh_summary.get('trades')}` / `{fresh_summary.get('total_return_pct')}%`",
            "",
            "## Bulkowski Alignment",
            "",
            f"- Flags source: {BULKOWSKI_FLAGS_URL}",
            f"- Measure source: {BULKOWSKI_MEASURE_URL}",
            "- Base target `0.46x pole` is the publication target; `1.0x` is legacy/stretch.",
            "",
            "## Caveats",
            "",
        ]
    )
    caveats = payload.get("data_scope_and_caveats") if isinstance(payload.get("data_scope_and_caveats"), Mapping) else {}
    for caveat in caveats.get("remaining_caveats") or []:
        lines.append(f"- Remaining: `{caveat}`")
    for claim in caveats.get("forbidden_claims") or []:
        lines.append(f"- Forbidden claim: `{claim}`")
    return "\n".join(lines) + "\n"


def render_publication_pdf(payload: Mapping[str, Any], pdf_path: Path) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    ref = payload.get("chapter_reference") if isinstance(payload.get("chapter_reference"), Mapping) else {}
    target = payload.get("target_calibration") if isinstance(payload.get("target_calibration"), Mapping) else {}
    release = payload.get("release_candidate") if isinstance(payload.get("release_candidate"), Mapping) else {}
    tradable = payload.get("tradable_setup") if isinstance(payload.get("tradable_setup"), Mapping) else {}
    selected = tradable.get("selected_metrics") if isinstance(tradable.get("selected_metrics"), Mapping) else {}
    fresh = payload.get("fresh_candidate") if isinstance(payload.get("fresh_candidate"), Mapping) else {}
    fresh_summary = fresh.get("summary") if isinstance(fresh.get("summary"), Mapping) else {}
    support = payload.get("supporting_robustness") if isinstance(payload.get("supporting_robustness"), Mapping) else {}
    caveats = payload.get("data_scope_and_caveats") if isinstance(payload.get("data_scope_and_caveats"), Mapping) else {}
    contract = payload.get("narrative_contract") if isinstance(payload.get("narrative_contract"), Mapping) else {}

    with PdfPages(pdf_path) as pdf:
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.patch.set_facecolor("#fffdf8")
        fig.text(0.5, 0.92, "Bull Flag", ha="center", va="top", fontsize=24, weight="bold")
        fig.text(0.5, 0.885, "Vietnam Publication Chapter", ha="center", va="top", fontsize=12)
        y = 0.80
        rows = [
            ("Status", payload.get("status")),
            ("Classification", payload.get("classification")),
            ("Release score", release.get("conservative_score")),
            ("Main / fresh score", f"{_nested(release, 'main', 'score')} / {_nested(release, 'fresh', 'score')}"),
            ("Reference events", ref.get("events")),
            ("Tradable trades", selected.get("trades")),
            ("Fresh trades", fresh_summary.get("trades")),
            ("Base target", "0.46x pole"),
            ("Claim", "research candidate; not production trading"),
        ]
        for label, value in rows:
            fig.text(0.14, y, label, fontsize=10, weight="bold", ha="left", va="top")
            fig.text(0.50, y, str(value), fontsize=10, ha="left", va="top")
            y -= 0.038
        y -= 0.02
        _draw_lines(fig, [contract.get("primary_claim", ""), contract.get("claim_boundary", "")], x=0.12, y=y, fontsize=9.0, width=105)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        fig = plt.figure(figsize=(8.27, 11.69))
        _page(fig, "1. Chapter Contract And Structure")
        lines = [
            f"Headline label: {contract.get('headline_label')}",
            f"Reference layer: {contract.get('reference_layer')}",
            f"Tradable layer: {contract.get('tradable_layer')}",
        ]
        y = _draw_lines(fig, lines, x=0.08, y=0.87, fontsize=8.8, width=105)
        y -= 0.02
        structure_rows = [("No.", "Section")]
        structure_rows.extend((i, item) for i, item in enumerate(payload.get("report_structure") or [], start=1))
        _draw_table(fig, structure_rows, x=0.08, y=y, col_x=[0.0, 0.10], fontsize=7.8, row_step=0.030)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        fig = plt.figure(figsize=(8.27, 11.69))
        _page(fig, "2. Rule Anatomy And Scanner Contract")
        scanner = payload.get("scanner_contract") if isinstance(payload.get("scanner_contract"), Mapping) else {}
        detector = scanner.get("detector_config") if isinstance(scanner.get("detector_config"), Mapping) else {}
        layer = scanner.get("setup_confirmation_followthrough") if isinstance(scanner.get("setup_confirmation_followthrough"), Mapping) else {}
        y = _draw_lines(fig, scanner.get("anatomy") or [], x=0.08, y=0.87, fontsize=8.7, width=105)
        y -= 0.02
        detector_rows = [
            ("Detector field", "Value"),
            ("width_min/max_bars", f"{detector.get('width_min_bars')} / {detector.get('width_max_bars')}"),
            ("pole_lookback_bars", detector.get("pole_lookback_bars")),
            ("pole_min_change_pct", _fmt(detector.get("pole_min_change_pct"), "%")),
            ("pole_min_slope_deg", detector.get("pole_min_slope_deg")),
            ("flag_to_pole_max_pct", _fmt(detector.get("flag_to_pole_max_pct"), "%")),
            ("breakout_threshold", detector.get("breakout_threshold")),
            ("breakout_search_bars", detector.get("breakout_search_bars")),
            ("require_volume_confirmed", detector.get("require_volume_confirmed")),
        ]
        y = _draw_table(fig, detector_rows, x=0.08, y=y, col_x=[0.0, 0.40], fontsize=7.8, row_step=0.028)
        y -= 0.02
        layer_rows = [
            ("Layer field", "Value"),
            ("min_setup_score", layer.get("min_setup_score")),
            ("min_confirmation_score", layer.get("min_confirmation_score")),
            ("entry_delay_bars", layer.get("entry_delay_bars")),
            ("min_breakout_date", layer.get("min_breakout_date")),
            ("allowed_market_regimes", ", ".join(layer.get("allowed_market_regimes") or [])),
            ("bear/high-liquidity guard", layer.get("exclude_bear_high_liquidity_setup_score_min")),
        ]
        _draw_table(fig, layer_rows, x=0.08, y=y, col_x=[0.0, 0.40], fontsize=7.8, row_step=0.028)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        fig = plt.figure(figsize=(8.27, 11.69))
        _page(fig, "3. Reference Statistics And Target Calibration")
        stat_rows = [
            ("Metric", "Value"),
            ("Symbols scanned", ref.get("symbols_scanned")),
            ("Events / evaluated", f"{ref.get('events')} / {ref.get('evaluated_events')}"),
            ("Median MFE / MAE", f"{_fmt(ref.get('median_mfe_pct'), '%')} / {_fmt(ref.get('median_mae_pct'), '%')}"),
            ("MFE/MAE median ratio", ref.get("mfe_mae_median_ratio")),
            ("Failure 5%", _fmt(ref.get("failure_5pct_rate"), "%")),
            ("Legacy 1.0x target hit", _fmt(ref.get("legacy_target_hit_rate"), "%")),
        ]
        y = _draw_table(fig, stat_rows, x=0.08, y=0.87, col_x=[0.0, 0.42], fontsize=8.2, row_step=0.031)
        y -= 0.025
        target_rows = [("Target", "Role", "N", "Hit", "T-first", "Fail")]
        for row in target.get("rows") or []:
            if isinstance(row, Mapping):
                target_rows.append(
                    (
                        f"{row.get('target_multiple')}x",
                        row.get("target_role"),
                        row.get("n"),
                        _fmt(row.get("target_hit_rate"), "%"),
                        _fmt(row.get("target_first_before_adverse_5pct_rate"), "%"),
                        _fmt(row.get("failure_5pct_rate"), "%"),
                    )
                )
        _draw_table(fig, target_rows, x=0.08, y=y, col_x=[0.0, 0.13, 0.40, 0.49, 0.61, 0.76], fontsize=7.4, row_step=0.027)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        fig = plt.figure(figsize=(8.27, 11.69))
        _page(fig, "4. Execution Setup")
        exec_rows = [
            ("Metric", "Value"),
            ("Strategy", tradable.get("selected_strategy_id")),
            ("Target multiple", selected.get("target_multiple")),
            ("Stop loss", _fmt(selected.get("stop_loss_pct"), "%")),
            ("Entry delay bars", selected.get("entry_delay_bars")),
            ("Max holding days", selected.get("max_holding_days")),
            ("Position size", _fmt(selected.get("position_size_pct"), "")),
            ("Max positions", selected.get("max_positions")),
            ("Commission/slippage/sell tax bps", f"{selected.get('commission_bps_per_side')} / {selected.get('slippage_bps_per_side')} / {selected.get('sell_tax_bps')}"),
            ("Median ADTV participation", _fmt(selected.get("median_adtv_participation_pct"), "%")),
            ("Win rate / profit factor", f"{_fmt(selected.get('win_rate_pct'), '%')} / {selected.get('profit_factor')}"),
            ("Total return / max DD", f"{_fmt(selected.get('total_return_pct'), '%')} / {_fmt(selected.get('max_drawdown_pct'), '%')}"),
        ]
        _draw_table(fig, exec_rows, x=0.08, y=0.87, col_x=[0.0, 0.39], fontsize=7.9, row_step=0.030)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        fig = plt.figure(figsize=(8.27, 11.69))
        _page(fig, "5. OOS, Fresh Source And Robustness")
        wf = tradable.get("walk_forward_summary") if isinstance(tradable.get("walk_forward_summary"), Mapping) else {}
        fresh_wf = fresh.get("walk_forward_summary") if isinstance(fresh.get("walk_forward_summary"), Mapping) else {}
        oos_rows = [
            ("Scope", "Score", "Trades", "Total", "Validation", "Holdout", "Positive folds"),
            ("Main", release.get("conservative_score"), selected.get("trades"), _fmt(selected.get("total_return_pct"), "%"), _fmt(selected.get("validation_total_return_pct"), "%"), _fmt(selected.get("holdout_total_return_pct"), "%"), _fmt(wf.get("positive_fold_rate_pct"), "%")),
            ("Fresh", _nested(fresh, "scorecard", "score"), fresh_summary.get("trades"), _fmt(fresh_summary.get("total_return_pct"), "%"), _fmt(fresh_summary.get("validation_total_return_pct"), "%"), _fmt(fresh_summary.get("holdout_total_return_pct"), "%"), _fmt(fresh_wf.get("positive_fold_rate_pct"), "%")),
        ]
        y = _draw_table(fig, oos_rows, x=0.06, y=0.87, col_x=[0.0, 0.15, 0.27, 0.38, 0.50, 0.64, 0.77], fontsize=7.2, row_step=0.030)
        y -= 0.04
        robust_rows = [("Profile", "Status", "Events", "Overlap", "Liquidity", "Limit proxy")]
        for profile in support.get("profiles") or []:
            if isinstance(profile, Mapping):
                checks = profile.get("checks") if isinstance(profile.get("checks"), Mapping) else {}
                robust_rows.append((profile.get("profile_id"), profile.get("status"), profile.get("scoped_events"), checks.get("overlap_sensitivity"), checks.get("liquidity_bucket_robustness"), checks.get("price_limit_proxy_robustness")))
        _draw_table(fig, robust_rows, x=0.06, y=y, col_x=[0.0, 0.22, 0.33, 0.45, 0.59, 0.74], fontsize=7.0, row_step=0.027)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        fig = plt.figure(figsize=(8.27, 11.69))
        _page(fig, "6. Bulkowski Alignment And Vietnam Localization")
        align = payload.get("bulkowski_alignment") if isinstance(payload.get("bulkowski_alignment"), Mapping) else {}
        bulk = align.get("bulkowski_flags_reference") if isinstance(align.get("bulkowski_flags_reference"), Mapping) else {}
        viet = align.get("vietnam_implementation") if isinstance(align.get("vietnam_implementation"), Mapping) else {}
        align_lines = [
            f"Pattern type: Bulkowski treats Flags as a short-term continuation pattern after a sharp flagpole; this chapter implements Bull Flag as a bullish continuation setup.",
            f"Base target: Bulkowski adjusted Flags target is {bulk.get('upward_measure_rule_pct_of_pole')}% of the pole; Vietnam base target is {viet.get('base_target_multiple')}x pole.",
            f"Legacy target: the full {viet.get('legacy_target_multiple')}x pole target is kept only as stretch/reference.",
            f"Bearish handling: Bulkowski reports up/down flags separately; this Vietnam cash-equity release keeps Bear Flag as {viet.get('bear_flag_handling')}.",
        ]
        y = _draw_lines(fig, align_lines, x=0.08, y=0.87, fontsize=8.6, width=105)
        y -= 0.02
        _draw_lines(fig, [align.get("alignment_summary", ""), f"Sources: {BULKOWSKI_FLAGS_URL}; {BULKOWSKI_MEASURE_URL}"], x=0.08, y=y, fontsize=8.8, width=105)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        fig = plt.figure(figsize=(8.27, 11.69))
        _page(fig, "7. Data Caveats And Publication Boundaries")
        lines = ["Closed supporting caveats:"]
        lines.extend(f"- {item}" for item in caveats.get("closed_supporting_caveats") or [])
        lines.append("Remaining caveats:")
        lines.extend(f"- {item}" for item in caveats.get("remaining_caveats") or [])
        lines.append("Forbidden claims:")
        lines.extend(f"- {item}" for item in caveats.get("forbidden_claims") or [])
        _draw_lines(fig, lines, x=0.08, y=0.87, fontsize=8.4, width=105)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)


def write_publication_chapter(payload: Mapping[str, Any], out_dir: Path = DEFAULT_OUT_DIR) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "bull_flag_publication_payload.json"
    md_path = out_dir / "bull_flag_publication_chapter.md"
    pdf_path = out_dir / "bull_flag_publication_chapter.pdf"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_publication_markdown(payload), encoding="utf-8")
    render_publication_pdf(payload, pdf_path)
    return {"payload": json_path, "markdown": md_path, "pdf": pdf_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the canonical Bull Flag publication chapter payload and PDF.")
    parser.add_argument("--stats", default=str(DEFAULT_STATS))
    parser.add_argument("--release", default=str(DEFAULT_RELEASE))
    parser.add_argument("--scorecard", default=str(DEFAULT_SCORECARD))
    parser.add_argument("--selected-strategy", default=str(DEFAULT_SELECTED_STRATEGY))
    parser.add_argument("--supporting-robustness", default=str(DEFAULT_SUPPORTING_ROBUSTNESS))
    parser.add_argument("--fresh-gate", default=str(DEFAULT_FRESH_GATE))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    payload = build_publication_payload(
        stats_path=Path(args.stats),
        release_path=Path(args.release),
        scorecard_path=Path(args.scorecard),
        selected_strategy_path=Path(args.selected_strategy),
        supporting_robustness_path=Path(args.supporting_robustness),
        fresh_gate_path=Path(args.fresh_gate),
    )
    paths = write_publication_chapter(payload, Path(args.out_dir))
    for key, path in paths.items():
        print(f"{key}: {path}")
    if payload.get("status") != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
