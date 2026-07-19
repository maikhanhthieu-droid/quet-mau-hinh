"""Build the Bull Flag control artifact for After-the-Buy localization.

Bull Flag is the benchmark chapter.  Before applying After-the-Buy logic to
weaker BUY candidates, this artifact proves that the source-grounded rule layer
is additive and does not replace or degrade the existing Bull Flag tradable
benchmark.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.after_buy_source_grounding import (  # noqa: E402
    DEFAULT_AFTER_BUY_PDF,
    DEFAULT_OUT_DIR as DEFAULT_AFTER_BUY_OUT_DIR,
    assert_after_buy_buy_rule_allowed,
    build_after_buy_source_map,
)


CONTROL_ID = "after_buy_bull_flag_control_v1"
DEFAULT_SOURCE_MAP = DEFAULT_AFTER_BUY_OUT_DIR / "after_buy_source_map.json"
DEFAULT_SCORECARD = Path("artifacts/scanner_v2/bull_flags_tradable_setup/bull_flag_tradable_scorecard.json")
DEFAULT_SELECTED_STRATEGY = Path("artifacts/scanner_v2/bull_flags_tradable_setup/bull_flag_tradable_selected_strategy.json")
DEFAULT_RELEASE_CANDIDATE = Path("artifacts/scanner_v2/bull_flags_release_candidate/bull_flag_release_candidate.json")
DEFAULT_OUT_DIR = DEFAULT_AFTER_BUY_OUT_DIR / "bull_flags_control"


REQUIRED_SOURCE_SECTIONS = (
    "Behavior at a Glance",
    "Identification",
    "Best Stop Locations",
    "Measure Rule",
    "Trading",
    "Focus on Failures",
    "Actual Trade",
    "Closing Position",
)


SOURCE_RULES: tuple[dict[str, Any], ...] = (
    {
        "rule_id": "atb.flags.flagpole_vigor",
        "source_section": "Identification",
        "source_pages": [204, 205, 206],
        "source_paraphrase": "A flag or pennant should rest on a brisk short-term price move; without a strong flagpole it is more likely ordinary congestion.",
        "local_buy_interpretation": "Bull Flag candidates must keep a clear prior up-move/setup score gate before any BUY test.",
    },
    {
        "rule_id": "atb.flags.duration_max_three_weeks",
        "source_section": "Identification",
        "source_pages": [206],
        "source_paraphrase": "Flags and pennants are short patterns; longer formations should be treated as another pattern family.",
        "local_buy_interpretation": "Do not rescue overlong flags with a trading branch; keep the short-rest requirement.",
    },
    {
        "rule_id": "atb.flags.breakout_close_outside_boundary",
        "source_section": "Identification",
        "source_pages": [206, 207],
        "source_paraphrase": "The event is confirmed by a close outside the flag or pennant boundary.",
        "local_buy_interpretation": "Vietnam BUY entry must be after confirmed close, not from an intraday poke through the boundary.",
    },
    {
        "rule_id": "atb.flags.volume_context_not_hard_gate",
        "source_section": "Identification",
        "source_pages": [206, 207],
        "source_paraphrase": "Volume often trends down during the formation, but unusual volume alone should not discard the setup.",
        "local_buy_interpretation": "Volume is kept as a context feature; it is not allowed to override weak geometry or weak confirmation.",
    },
    {
        "rule_id": "atb.flags.avoid_bottom_of_flag_naive_stop",
        "source_section": "Best Stop Locations",
        "source_pages": [213],
        "source_paraphrase": "A stop near the bottom of a bullish flag is often hit during throwbacks, so it can remove many otherwise valid trades.",
        "local_buy_interpretation": "The local layer uses explicit percentage/risk-sized stops and stress checks instead of blindly placing the stop at the flag bottom.",
    },
    {
        "rule_id": "atb.flags.measure_rule_is_guideline",
        "source_section": "Measure Rule",
        "source_pages": [213, 214],
        "source_paraphrase": "Flag targets are estimates; the measured move can undershoot or overshoot materially.",
        "local_buy_interpretation": "Keep 0.46x as the local base target and treat larger multiples as stretch diagnostics, not the default KPI.",
    },
    {
        "rule_id": "atb.flags.primary_uptrend_preferred",
        "source_section": "Trading",
        "source_pages": [215, 216],
        "source_paraphrase": "Upward flag breakouts work better when aligned with a rising primary trend rather than appearing as a retrace in a primary downtrend.",
        "local_buy_interpretation": "The Bull Flag benchmark keeps context guards and avoids overextended/downtrend retrace situations.",
    },
    {
        "rule_id": "atb.flags.continuation_not_reversal",
        "source_section": "Trading",
        "source_pages": [216],
        "source_paraphrase": "Flags and pennants should be traded as continuation patterns; reversal-like uses have poorer opportunity quality.",
        "local_buy_interpretation": "The BUY layer must preserve setup-confirmation-follow-through scoring instead of treating every breakout as equal.",
    },
    {
        "rule_id": "atb.flags.overhead_resistance_failure_filter",
        "source_section": "Focus on Failures",
        "source_pages": [217],
        "source_paraphrase": "Overhead resistance can sharply reduce the quality of a flag breakout.",
        "local_buy_interpretation": "Use resistance/price-extension context as an avoid or size-reduction filter in future V2 work.",
    },
    {
        "rule_id": "atb.flags.earnings_window_caution",
        "source_section": "Focus on Failures",
        "source_pages": [217, 218],
        "source_paraphrase": "Event-driven flags around earnings require extra caution; upcoming earnings can distort the setup.",
        "local_buy_interpretation": "Vietnam scanner should mark event/corporate-action windows as caveats before promoting a BUY candidate.",
    },
)


def _read_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _flags_outline(after_buy_pdf: Path) -> dict[str, Any]:
    reader = PdfReader(str(after_buy_pdf))
    outline = list(reader.outline)
    for idx, item in enumerate(outline):
        if isinstance(item, list):
            continue
        title = str(getattr(item, "title", item)).strip()
        if title == "Chapter 8 Flags and Pennants":
            sections: list[dict[str, Any]] = []
            if idx + 1 < len(outline) and isinstance(outline[idx + 1], list):
                for child in outline[idx + 1]:
                    if isinstance(child, list):
                        continue
                    try:
                        page = reader.get_destination_page_number(child) + 1
                    except Exception:
                        page = None
                    sections.append({"title": str(getattr(child, "title", child)).strip(), "pdf_page": page})
            return {
                "source_chapter_no": 8,
                "source_title": "Flags and Pennants",
                "outline_title": title,
                "pdf_page": reader.get_destination_page_number(item) + 1,
                "sections": sections,
            }
    raise RuntimeError("Could not find Chapter 8 Flags and Pennants in After-the-Buy PDF outline.")


def build_after_buy_bull_flag_control(
    *,
    after_buy_pdf: Path = DEFAULT_AFTER_BUY_PDF,
    source_map_path: Path = DEFAULT_SOURCE_MAP,
    scorecard_path: Path = DEFAULT_SCORECARD,
    selected_strategy_path: Path = DEFAULT_SELECTED_STRATEGY,
    release_candidate_path: Path = DEFAULT_RELEASE_CANDIDATE,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    if not source_map_path.exists():
        source_map = build_after_buy_source_map(after_buy_pdf=after_buy_pdf, out_dir=source_map_path.parent)
    else:
        source_map = _read_json(source_map_path)
    allowed = assert_after_buy_buy_rule_allowed("bull_flags", source_map)
    source = _flags_outline(after_buy_pdf)
    section_titles = {str(section.get("title")) for section in source["sections"]}
    missing_sections = [section for section in REQUIRED_SOURCE_SECTIONS if section not in section_titles]

    scorecard = _read_json(scorecard_path)
    selected = _read_json(selected_strategy_path)
    release = _read_json(release_candidate_path)
    benchmark_score = _float(scorecard.get("score"))
    release_status = str(release.get("release_status") or "")

    local_control = {
        "entry_rule": selected.get("selected_strategy_id"),
        "entry_basis": "confirmed close, delayed executable entry, long-only cash-equity scope",
        "target_rule": selected.get("frozen_rule_contract", {}).get("target_rule") if isinstance(selected.get("frozen_rule_contract"), Mapping) else None,
        "stop_rule": selected.get("frozen_rule_contract", {}).get("exit_rule") if isinstance(selected.get("frozen_rule_contract"), Mapping) else None,
        "benchmark_score": benchmark_score,
        "release_status": release_status,
        "benchmark_preserved": bool(benchmark_score is not None and benchmark_score >= 95.0 and release_status == "PASS"),
    }
    failures: list[str] = []
    if missing_sections:
        failures.append("missing_required_source_sections")
    if not local_control["benchmark_preserved"]:
        failures.append("bull_flag_benchmark_not_preserved")
    if allowed.get("pattern_buy_role", {}).get("buy_layer_allowed") is not True:
        failures.append("bull_flag_not_buy_allowed")

    result = {
        "control_id": CONTROL_ID,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "source_grounding_id": source_map.get("source_grounding_id"),
        "buy_first_policy_id": source_map.get("buy_first_policy_id"),
        "pattern_id": "bull_flags",
        "source_chapter": source,
        "source_rules": list(SOURCE_RULES),
        "local_buy_adaptation": {
            "policy": "Vietnam long-cash BUY control; no short-selling assumption.",
            "rule_count": len(SOURCE_RULES),
            "rules": [
                "Preserve flagpole/setup quality before entry.",
                "Enter only after close-confirmed breakout and executable delay.",
                "Use local 0.46x base target; do not promote full measured move as default.",
                "Use explicit risk-sized stop logic, not naive flag-bottom stop only.",
                "Keep context guards for primary trend/retrace/overhead resistance.",
                "Treat event/corporate-action windows as caveats.",
            ],
        },
        "benchmark_control": local_control,
        "source_allowed_mapping": {
            "source_title": allowed.get("source_title"),
            "pattern_buy_role": allowed.get("pattern_buy_role"),
        },
        "artifacts": {
            "scorecard": str(scorecard_path),
            "selected_strategy": str(selected_strategy_path),
            "release_candidate": str(release_candidate_path),
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "bull_flag_after_buy_control.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_markdown(out_dir / "bull_flag_after_buy_control.md", result)
    return result


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_markdown(path: Path, result: Mapping[str, Any]) -> None:
    benchmark = result.get("benchmark_control") if isinstance(result.get("benchmark_control"), Mapping) else {}
    lines = [
        "# Bull Flag After-the-Buy Control",
        "",
        f"- Control ID: `{result['control_id']}`",
        f"- Status: `{result['status']}`",
        f"- Source: `{result['source_chapter']['source_title']}`",
        f"- Benchmark score: `{benchmark.get('benchmark_score')}`",
        f"- Release status: `{benchmark.get('release_status')}`",
        f"- Benchmark preserved: `{benchmark.get('benchmark_preserved')}`",
        "",
        "## Source-Grounded Rules",
        "",
        "| Rule | Source section | Local BUY interpretation |",
        "|---|---|---|",
    ]
    for rule in result.get("source_rules") or []:
        lines.append(f"| `{rule['rule_id']}` | {rule['source_section']} | {rule['local_buy_interpretation']} |")
    lines.extend(
        [
            "",
            "## Local Adaptation",
            "",
        ]
    )
    for item in result.get("local_buy_adaptation", {}).get("rules", []):
        lines.append(f"- {item}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Bull Flag After-the-Buy control artifact.")
    parser.add_argument("--after-buy-pdf", type=Path, default=DEFAULT_AFTER_BUY_PDF)
    parser.add_argument("--source-map", type=Path, default=DEFAULT_SOURCE_MAP)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--selected-strategy", type=Path, default=DEFAULT_SELECTED_STRATEGY)
    parser.add_argument("--release-candidate", type=Path, default=DEFAULT_RELEASE_CANDIDATE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    result = build_after_buy_bull_flag_control(
        after_buy_pdf=args.after_buy_pdf,
        source_map_path=args.source_map,
        scorecard_path=args.scorecard,
        selected_strategy_path=args.selected_strategy,
        release_candidate_path=args.release_candidate,
        out_dir=args.out_dir,
    )
    print(json.dumps({"status": result["status"], "control_id": result["control_id"], "out_dir": str(args.out_dir)}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
