"""Build After-the-Buy BUY rules for Measured Move Up."""

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


RULESET_ID = "after_buy_measured_move_up_rules_v1"
DEFAULT_SOURCE_MAP = DEFAULT_AFTER_BUY_OUT_DIR / "after_buy_source_map.json"
DEFAULT_OUT_DIR = DEFAULT_AFTER_BUY_OUT_DIR / "measured_move_up"
DEFAULT_SOURCE_NOTES = Path("artifacts/scanner_v2/measured_move_family_public_chapters/measured_move_up/measured_move_up_source_notes.json")
DEFAULT_SCORECARD = Path("artifacts/scanner_v2/chapter_tradable_layer/measured_move_up/scorecard.json")
DEFAULT_SELECTED_STRATEGY = Path("artifacts/scanner_v2/chapter_tradable_layer/measured_move_up/selected_strategy.json")
DEFAULT_RELEASE_CANDIDATE = Path("artifacts/scanner_v2/chapter_tradable_layer/measured_move_up/release_candidate.json")
DEFAULT_GOVERNANCE_MATRIX = Path("artifacts/final_chapters/governance/chapter_governance_matrix.json")


REQUIRED_SOURCE_SECTIONS = (
    "Behavior at a Glance",
    "Identification",
    "Performance Details",
    "After the Measured Move Up",
    "The Measure Rule",
    "Closing Position",
)

SOURCE_RULES: tuple[dict[str, Any], ...] = (
    {
        "rule_id": "atb.mmu.three_part_behavior",
        "source_origin": "after_buy_chapter_12",
        "source_section": "Identification",
        "source_pages": [286, 287],
        "source_paraphrase": "Measured Move Up is read as an advance, a correction, and a second advance.",
        "local_buy_interpretation": "The scanner must keep the A-B-C structure; a generic breakout without retrace geometry is not enough.",
    },
    {
        "rule_id": "atb.mmu.after_pattern_second_leg",
        "source_origin": "after_buy_chapter_12",
        "source_section": "After the Measured Move Up",
        "source_pages": [289, 290],
        "source_paraphrase": "The useful post-buy question is whether the second leg develops after the corrective phase.",
        "local_buy_interpretation": "Tradable scoring uses continuation after point C, not only the existence of the first leg.",
    },
    {
        "rule_id": "atb.mmu.measure_rule_practical_target",
        "source_origin": "after_buy_chapter_12",
        "source_section": "The Measure Rule",
        "source_pages": [290, 291],
        "source_paraphrase": "The first leg provides the source target, but the target remains an estimate.",
        "local_buy_interpretation": "Vietnam keeps 0.5x as executable base target and 1.0x as source/full diagnostic.",
    },
    {
        "rule_id": "atb.mmu.close_position_not_endless_hold",
        "source_origin": "after_buy_chapter_12",
        "source_section": "Closing Position",
        "source_pages": [292],
        "source_paraphrase": "The chapter treats exit and target handling as part of the setup, not an indefinite hold.",
        "local_buy_interpretation": "The tradable layer keeps target, stop, and max-holding exits with cost/capacity checks.",
    },
    {
        "rule_id": "mmu.corrective.retrace",
        "source_origin": "measured_move_source_notes",
        "source_section": "Measured Move morphology",
        "source_paraphrase": "The corrective phase should sit around the 38-62 percent / 40-60 percent retrace zone.",
        "local_buy_interpretation": "The selected tradable strategy keeps the ideal 38-62 retrace band.",
    },
    {
        "rule_id": "mmu.first_leg.straight",
        "source_origin": "measured_move_source_notes",
        "source_section": "Measured Move morphology",
        "source_paraphrase": "The first leg should be straight enough to be a meaningful measured move.",
        "local_buy_interpretation": "The executable strategy requires first-leg linearity, currently R2 at least 0.8.",
    },
    {
        "rule_id": "mmu.avoid.sawtooth",
        "source_origin": "measured_move_source_notes",
        "source_section": "Measured Move quality",
        "source_paraphrase": "Avoid horizontal or saw-tooth consolidation regions.",
        "local_buy_interpretation": "The pattern is promoted only when the retrace is a clean correction, not a noisy range.",
    },
)


def _read_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _measured_move_up_outline(after_buy_pdf: Path) -> dict[str, Any]:
    reader = PdfReader(str(after_buy_pdf))
    outline = list(reader.outline)
    for idx, item in enumerate(outline):
        if isinstance(item, list):
            continue
        title = str(getattr(item, "title", item)).strip()
        if title == "Chapter 12 Measured Move Up":
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
                "source_chapter_no": 12,
                "source_title": "Measured Move Up",
                "outline_title": title,
                "pdf_page": reader.get_destination_page_number(item) + 1,
                "sections": sections,
            }
    raise RuntimeError("Could not find Chapter 12 Measured Move Up in After-the-Buy PDF outline.")


def _source_notes_summary(path: Path) -> dict[str, Any]:
    notes = _read_json(path)
    rules = notes.get("source_rules") if isinstance(notes.get("source_rules"), list) else []
    return {
        "path": str(path),
        "available": bool(notes),
        "source_review_status": notes.get("status") or notes.get("source_review_status"),
        "source_grounding_level": notes.get("source_grounding_level"),
        "rule_count": len(rules),
        "rule_ids": [rule.get("rule_id") for rule in rules if isinstance(rule, Mapping)],
    }


def _tradable_evidence(scorecard_path: Path, selected_path: Path, release_path: Path, governance_path: Path) -> dict[str, Any]:
    scorecard = _read_json(scorecard_path)
    selected = _read_json(selected_path)
    release = _read_json(release_path)
    metrics = selected.get("selected_metrics") if isinstance(selected.get("selected_metrics"), Mapping) else {}
    return {
        "scorecard": {
            "path": str(scorecard_path),
            "score": _float(scorecard.get("score")),
            "classification": scorecard.get("classification"),
            "promotion_blockers": scorecard.get("promotion_blockers"),
            "component_scores": scorecard.get("component_scores"),
        },
        "selected_strategy": {
            "path": str(selected_path),
            "selected_strategy_id": selected.get("selected_strategy_id"),
            "status": selected.get("status"),
            "trades": metrics.get("trades"),
            "validation_trades": metrics.get("validation_trades"),
            "holdout_trades": metrics.get("holdout_trades"),
            "target_multiple": metrics.get("target_multiple"),
            "allowed_source_retrace_bands": metrics.get("allowed_source_retrace_bands"),
            "min_first_leg_linearity_r2": metrics.get("min_first_leg_linearity_r2"),
            "fixed_walk_forward_summary": selected.get("fixed_walk_forward_summary"),
            "adaptive_walk_forward_summary": selected.get("adaptive_walk_forward_summary"),
        },
        "release_candidate": {
            "path": str(release_path),
            "release_status": release.get("release_status"),
            "score": _float(release.get("score")),
            "classification": release.get("classification"),
        },
        "governance": _load_governance("measured_move_up", governance_path),
    }


def _load_governance(pattern_id: str, governance_path: Path) -> dict[str, Any]:
    matrix = _read_json(governance_path)
    rows = matrix.get("chapters") if isinstance(matrix.get("chapters"), list) else []
    for row in rows:
        if isinstance(row, Mapping) and str(row.get("pattern_id")) == pattern_id:
            return {
                "governance_path": str(governance_path),
                "tradable_score": _float(row.get("tradable_score")),
                "tradable_status": row.get("tradable_status"),
                "tradable_release_status": row.get("tradable_release_status"),
                "tradable_evidence_id": row.get("tradable_evidence_id"),
                "tradable_blockers": row.get("tradable_blockers"),
                "publication_status": row.get("publication_status"),
            }
    return {"governance_path": str(governance_path), "tradable_score": None, "tradable_status": "not_in_governance_matrix"}


def build_after_buy_measured_move_up_rules(
    *,
    after_buy_pdf: Path = DEFAULT_AFTER_BUY_PDF,
    source_map_path: Path = DEFAULT_SOURCE_MAP,
    source_notes_path: Path = DEFAULT_SOURCE_NOTES,
    scorecard_path: Path = DEFAULT_SCORECARD,
    selected_strategy_path: Path = DEFAULT_SELECTED_STRATEGY,
    release_candidate_path: Path = DEFAULT_RELEASE_CANDIDATE,
    governance_path: Path = DEFAULT_GOVERNANCE_MATRIX,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    if not source_map_path.exists():
        source_map = build_after_buy_source_map(after_buy_pdf=after_buy_pdf, out_dir=source_map_path.parent)
    else:
        source_map = _read_json(source_map_path)
    allowed = assert_after_buy_buy_rule_allowed("measured_move_up", source_map)
    source = _measured_move_up_outline(after_buy_pdf)
    section_titles = {str(section.get("title")) for section in source["sections"]}
    missing_sections = [section for section in REQUIRED_SOURCE_SECTIONS if section not in section_titles]
    source_notes = _source_notes_summary(source_notes_path)
    evidence = _tradable_evidence(scorecard_path, selected_strategy_path, release_candidate_path, governance_path)

    failures: list[str] = []
    if allowed.get("pattern_buy_role", {}).get("buy_layer_allowed") is not True:
        failures.append("measured_move_up:not_buy_allowed")
    if missing_sections:
        failures.append("missing_required_source_sections")
    if not source_notes["available"] or source_notes.get("source_review_status") != "PASS":
        failures.append("missing_or_failed_measured_move_source_notes")
    if evidence["scorecard"]["score"] is None:
        failures.append("missing_tradable_evidence")

    score = evidence["scorecard"]["score"]
    blockers = evidence["scorecard"]["promotion_blockers"] or []
    tradable_final = bool(score is not None and score >= 95 and not blockers and evidence["release_candidate"]["release_status"] == "PASS")
    result = {
        "ruleset_id": RULESET_ID,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "source_grounding_id": source_map.get("source_grounding_id"),
        "buy_first_policy_id": source_map.get("buy_first_policy_id"),
        "pattern_id": "measured_move_up",
        "source_relationship": {
            "after_buy_source_used": "Chapter 12 Measured Move Up",
            "pattern_specific_source_used": str(source_notes_path),
            "interpretation": "After-the-Buy directly supports the long Measured Move Up setup; the Vietnam layer keeps 0.5x as executable base target.",
        },
        "source_chapter": source,
        "required_sections": list(REQUIRED_SOURCE_SECTIONS),
        "source_notes": source_notes,
        "source_rules": list(SOURCE_RULES),
        "pattern_buy_role": allowed.get("pattern_buy_role"),
        "local_buy_contract": {
            "scope": "Vietnam long-cash BUY core.",
            "entry": "post-confirmation long after A-B-C measured-move structure, ideal retrace, and first-leg linearity gate",
            "target_family": ["0.5x first-leg executable base", "1.0x source/full-leg diagnostic"],
            "stop_family": ["7% selected risk stop", "same-bar stop-first policy", "20-session max holding in selected strategy"],
            "must_keep_metrics": [
                "fixed walk-forward positive folds",
                "adaptive walk-forward summary",
                "cost stress",
                "capacity participation",
                "validation/holdout totals",
            ],
            "tradable_final_95_supported": tradable_final,
        },
        "current_evidence": evidence,
        "phase_b_action": "No further lift required; preserve contract and use as BUY-core tradable-final reference." if tradable_final else "Retest only with preregistered source rules; do not weaken execution contract.",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "measured_move_up_after_buy_rules.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_markdown(out_dir / "measured_move_up_after_buy_rules.md", result)
    return result


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_markdown(path: Path, result: Mapping[str, Any]) -> None:
    evidence = result.get("current_evidence") if isinstance(result.get("current_evidence"), Mapping) else {}
    scorecard = evidence.get("scorecard") if isinstance(evidence.get("scorecard"), Mapping) else {}
    lines = [
        "# Measured Move Up After-the-Buy Rules",
        "",
        f"- Ruleset ID: `{result['ruleset_id']}`",
        f"- Status: `{result['status']}`",
        f"- Pattern: `{result['pattern_id']}`",
        f"- Source: `{result['source_relationship']['after_buy_source_used']}`",
        f"- Tradable score: `{scorecard.get('score')}`",
        f"- Tradable-final supported: `{result['local_buy_contract']['tradable_final_95_supported']}`",
        f"- Phase action: {result.get('phase_b_action')}",
        "",
        "## Source-Grounded Rules",
        "",
        "| Rule | Origin | Local BUY interpretation |",
        "|---|---|---|",
    ]
    for rule in result.get("source_rules") or []:
        if isinstance(rule, Mapping):
            lines.append(
                f"| `{rule.get('rule_id')}` | {rule.get('source_origin')} / {rule.get('source_section')} | {rule.get('local_buy_interpretation')} |"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build After-the-Buy Measured Move Up BUY rules.")
    parser.add_argument("--after-buy-pdf", type=Path, default=DEFAULT_AFTER_BUY_PDF)
    parser.add_argument("--source-map", type=Path, default=DEFAULT_SOURCE_MAP)
    parser.add_argument("--source-notes", type=Path, default=DEFAULT_SOURCE_NOTES)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--selected-strategy", type=Path, default=DEFAULT_SELECTED_STRATEGY)
    parser.add_argument("--release-candidate", type=Path, default=DEFAULT_RELEASE_CANDIDATE)
    parser.add_argument("--governance", type=Path, default=DEFAULT_GOVERNANCE_MATRIX)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    result = build_after_buy_measured_move_up_rules(
        after_buy_pdf=args.after_buy_pdf,
        source_map_path=args.source_map,
        source_notes_path=args.source_notes,
        scorecard_path=args.scorecard,
        selected_strategy_path=args.selected_strategy,
        release_candidate_path=args.release_candidate,
        governance_path=args.governance,
        out_dir=args.out_dir,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "pattern_id": result["pattern_id"],
                "score": result["current_evidence"]["scorecard"]["score"],
                "tradable_final_95_supported": result["local_buy_contract"]["tradable_final_95_supported"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
