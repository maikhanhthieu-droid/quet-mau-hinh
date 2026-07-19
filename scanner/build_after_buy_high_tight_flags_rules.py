"""Build After-the-Buy BUY rules for High-and-Tight Flags.

After-the-Buy does not contain a dedicated High-and-Tight Flag chapter.  This
artifact records that fact explicitly: post-buy behavior, stop, and failure
logic can inherit from Chapter 8 Flags and Pennants, while the High-and-Tight
geometry and half-prior-move target stay anchored to the existing source notes.
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


RULESET_ID = "after_buy_high_tight_flags_rules_v1"
DEFAULT_SOURCE_MAP = DEFAULT_AFTER_BUY_OUT_DIR / "after_buy_source_map.json"
DEFAULT_OUT_DIR = DEFAULT_AFTER_BUY_OUT_DIR / "high_tight_flags"
DEFAULT_SOURCE_NOTES = Path("artifacts/scanner_v2/flag_like_family_source_grounding/high_tight_flags_source_notes.json")
DEFAULT_BRANCH_OPTIMIZATION = Path("artifacts/scanner_v2/chapter_branch_optimization/high_tight_flags/branch_optimization_summary.json")
DEFAULT_GENERIC_TRADABLE_DIR = Path("artifacts/scanner_v2/chapter_tradable_layer/high_tight_flags")
DEFAULT_GOVERNANCE_MATRIX = Path("artifacts/final_chapters/governance/chapter_governance_matrix.json")


REQUIRED_SOURCE_SECTIONS = (
    "Behavior at a Glance",
    "Identification",
    "Best Stop Locations",
    "Measure Rule",
    "Trading",
    "Focus on Failures",
    "Closing Position",
)

DIRECT_HIGH_TIGHT_SEARCH_TERMS = (
    "high and tight",
    "high-and-tight",
    "tight flag",
)

SOURCE_RULES: tuple[dict[str, Any], ...] = (
    {
        "rule_id": "atb.htf.indirect_after_buy_source",
        "source_origin": "after_buy_chapter_8",
        "source_section": "source relationship",
        "source_paraphrase": "After-the-Buy groups ordinary flags and pennants in Chapter 8 and does not provide a separate High-and-Tight Flag chapter.",
        "local_buy_interpretation": "Use Chapter 8 only for post-breakout behavior, stops, failures, and trade handling; keep High-and-Tight geometry pattern-specific.",
    },
    {
        "rule_id": "atb.htf.flagpole_vigor",
        "source_origin": "after_buy_chapter_8",
        "source_section": "Identification",
        "source_pages": [204, 205, 206],
        "source_paraphrase": "A flag setup needs a strong prior price run before the resting formation matters.",
        "local_buy_interpretation": "For High-and-Tight, the strong-run gate is stricter than ordinary flags: the detector keeps the exceptional prior advance requirement.",
    },
    {
        "rule_id": "atb.htf.short_rest_not_stale_base",
        "source_origin": "after_buy_chapter_8",
        "source_section": "Identification",
        "source_pages": [206],
        "source_paraphrase": "Flags are short resting patterns; stale bases belong to another family.",
        "local_buy_interpretation": "Do not rescue long high-level ranges as High-and-Tight Flags just because the prior advance was large.",
    },
    {
        "rule_id": "atb.htf.confirmed_up_breakout_close",
        "source_origin": "after_buy_chapter_8",
        "source_section": "Identification",
        "source_pages": [206, 207],
        "source_paraphrase": "The pattern confirms when price closes outside the flag or pennant boundary.",
        "local_buy_interpretation": "Vietnam BUY testing remains close-confirmed and up-breakout only; no pre-breakout anticipation branch.",
    },
    {
        "rule_id": "atb.htf.stop_not_naive_body_low",
        "source_origin": "after_buy_chapter_8",
        "source_section": "Best Stop Locations",
        "source_pages": [213],
        "source_paraphrase": "Naive stops around the flag body can be hit by normal throwback/retest behavior.",
        "local_buy_interpretation": "Use explicit risk, liquidity, and same-bar policies; the fold blocker cannot be fixed by a cosmetic stop after seeing holdout.",
    },
    {
        "rule_id": "atb.htf.failure_context_resistance",
        "source_origin": "after_buy_chapter_8",
        "source_section": "Focus on Failures",
        "source_pages": [217, 218],
        "source_paraphrase": "Resistance and event-like distortions can turn an otherwise valid continuation into a failure.",
        "local_buy_interpretation": "Keep bull-regime/liquidity/context branches as diagnostics, but do not promote until walk-forward folds are stable.",
    },
    {
        "rule_id": "htf.prior_trend.near_double",
        "source_origin": "high_tight_source_notes",
        "source_section": "High-and-Tight morphology",
        "source_paraphrase": "Require an exceptional prior advance, with at least roughly ninety percent rise and ideally a doubling in under two months.",
        "local_buy_interpretation": "This is the defining gate that separates High-and-Tight from ordinary Bull Flags.",
    },
    {
        "rule_id": "htf.consolidation.near_high",
        "source_origin": "high_tight_source_notes",
        "source_section": "High-and-Tight morphology",
        "source_paraphrase": "Find a short consolidation near the doubled price area after the strong advance.",
        "local_buy_interpretation": "The body must stay near the high; deep pullbacks are not promoted as premium setups.",
    },
    {
        "rule_id": "htf.pullback.limit",
        "source_origin": "high_tight_source_notes",
        "source_section": "High-and-Tight morphology",
        "source_paraphrase": "The consolidation should not drift too deeply from the high.",
        "local_buy_interpretation": "Use compact high consolidation as a quality branch; wide giveback is a downgrade.",
    },
    {
        "rule_id": "htf.volume.contracts",
        "source_origin": "high_tight_source_notes",
        "source_section": "High-and-Tight diagnostics",
        "source_paraphrase": "Receding volume inside the consolidation is a favorable diagnostic.",
        "local_buy_interpretation": "Volume contraction can support quality but cannot override weak path or fold evidence.",
    },
    {
        "rule_id": "htf.target.half_prior_move",
        "source_origin": "high_tight_source_notes",
        "source_section": "High-and-Tight measure rule",
        "source_paraphrase": "The source measure rule uses about half the prior advance projected from breakout, not the full pole.",
        "local_buy_interpretation": "Keep 0.5x prior advance as the source-aligned base; larger bands remain stress diagnostics.",
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


def _find_direct_high_tight_references(after_buy_pdf: Path) -> dict[str, Any]:
    reader = PdfReader(str(after_buy_pdf))
    matches: list[dict[str, Any]] = []
    for page_no, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        lowered = text.lower()
        for term in DIRECT_HIGH_TIGHT_SEARCH_TERMS:
            if term.lower() in lowered:
                matches.append({"pdf_page": page_no, "term": term})
    return {
        "available": bool(matches),
        "search_terms": list(DIRECT_HIGH_TIGHT_SEARCH_TERMS),
        "matches": matches,
        "match_count": len(matches),
    }


def _source_notes_summary(path: Path) -> dict[str, Any]:
    notes = _read_json(path)
    rules = notes.get("source_rules") if isinstance(notes.get("source_rules"), list) else []
    return {
        "path": str(path),
        "available": bool(notes),
        "source_review_status": notes.get("source_review_status"),
        "source_chapter": notes.get("source_chapter"),
        "source_book_pages": notes.get("source_book_pages"),
        "source_pdf_pages_checked": notes.get("source_pdf_pages_checked"),
        "rule_count": len(rules),
        "rule_ids": [rule.get("rule_id") for rule in rules if isinstance(rule, Mapping)],
    }


def _load_branch_evidence(path: Path) -> dict[str, Any]:
    data = _read_json(path)
    metrics = data.get("selected_metrics") if isinstance(data.get("selected_metrics"), Mapping) else {}
    return {
        "path": str(path),
        "available": bool(data),
        "score": _float(data.get("score")),
        "classification": data.get("classification"),
        "release_status": data.get("release_status"),
        "selected_strategy_id": data.get("selected_strategy_id"),
        "promotion_blockers": data.get("promotion_blockers"),
        "trades": metrics.get("trades"),
        "validation_trades": metrics.get("validation_trades"),
        "holdout_trades": metrics.get("holdout_trades"),
        "fixed_walk_forward_summary": data.get("fixed_walk_forward_summary"),
        "adaptive_walk_forward_summary": data.get("adaptive_walk_forward_summary"),
    }


def _load_generic_tradable(path: Path) -> dict[str, Any]:
    scorecard = _read_json(path / "scorecard.json")
    release = _read_json(path / "release_candidate.json")
    selected = _read_json(path / "selected_strategy.json")
    metrics = selected.get("selected_metrics") if isinstance(selected.get("selected_metrics"), Mapping) else {}
    return {
        "path": str(path),
        "available": bool(scorecard or selected or release),
        "score": _float(scorecard.get("score")),
        "classification": scorecard.get("classification"),
        "release_status": release.get("release_status"),
        "selected_strategy_id": selected.get("selected_strategy_id"),
        "selected_strategy_status": selected.get("status"),
        "promotion_blockers": scorecard.get("promotion_blockers"),
        "trades": metrics.get("trades"),
        "validation_trades": metrics.get("validation_trades"),
        "holdout_trades": metrics.get("holdout_trades"),
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
                "publication_claim_level": row.get("publication_claim_level"),
            }
    return {"governance_path": str(governance_path), "tradable_score": None, "tradable_status": "not_in_governance_matrix"}


def build_after_buy_high_tight_flags_rules(
    *,
    after_buy_pdf: Path = DEFAULT_AFTER_BUY_PDF,
    source_map_path: Path = DEFAULT_SOURCE_MAP,
    source_notes_path: Path = DEFAULT_SOURCE_NOTES,
    branch_optimization_path: Path = DEFAULT_BRANCH_OPTIMIZATION,
    generic_tradable_dir: Path = DEFAULT_GENERIC_TRADABLE_DIR,
    governance_path: Path = DEFAULT_GOVERNANCE_MATRIX,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    if not source_map_path.exists():
        source_map = build_after_buy_source_map(after_buy_pdf=after_buy_pdf, out_dir=source_map_path.parent)
    else:
        source_map = _read_json(source_map_path)

    allowed = assert_after_buy_buy_rule_allowed("high_tight_flags", source_map)
    source = _flags_outline(after_buy_pdf)
    direct_reference = _find_direct_high_tight_references(after_buy_pdf)
    section_titles = {str(section.get("title")) for section in source["sections"]}
    missing_sections = [section for section in REQUIRED_SOURCE_SECTIONS if section not in section_titles]
    source_notes = _source_notes_summary(source_notes_path)
    branch_evidence = _load_branch_evidence(branch_optimization_path)
    generic_evidence = _load_generic_tradable(generic_tradable_dir)
    governance = _load_governance("high_tight_flags", governance_path)

    failures: list[str] = []
    if allowed.get("pattern_buy_role", {}).get("buy_layer_allowed") is not True:
        failures.append("high_tight_flags:not_buy_allowed")
    if missing_sections:
        failures.append("missing_required_source_sections")
    if not source_notes["available"] or source_notes.get("source_review_status") != "PASS":
        failures.append("missing_or_failed_high_tight_source_notes")
    if direct_reference["available"]:
        failures.append("unexpected_direct_after_buy_high_tight_reference")

    result = {
        "ruleset_id": RULESET_ID,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "source_grounding_id": source_map.get("source_grounding_id"),
        "buy_first_policy_id": source_map.get("buy_first_policy_id"),
        "pattern_id": "high_tight_flags",
        "source_relationship": {
            "direct_after_buy_chapter_available": False,
            "after_buy_source_used": "Chapter 8 Flags and Pennants",
            "pattern_specific_source_used": str(source_notes_path),
            "interpretation": "After-the-Buy behavior/stops/failures are inherited from Flags and Pennants; High-and-Tight morphology and target remain pattern-specific.",
        },
        "direct_after_buy_reference_audit": direct_reference,
        "source_chapter": source,
        "required_sections": list(REQUIRED_SOURCE_SECTIONS),
        "source_notes": source_notes,
        "source_rules": list(SOURCE_RULES),
        "pattern_buy_role": allowed.get("pattern_buy_role"),
        "local_buy_contract": {
            "scope": "Vietnam long-cash BUY core, but currently not tradable-final because fold stability is not sufficient.",
            "entry": "close-confirmed upward breakout after exceptional prior advance and compact high-level consolidation",
            "target_family": ["0.5x prior advance source-aligned base", "0.65x/0.75x stress diagnostics", "1.0x full-pole diagnostic only"],
            "stop_family": ["explicit percentage/risk stop", "same-bar stop-first policy", "liquidity/capacity stress"],
            "must_keep_metrics": [
                "target-first-before-adverse",
                "walk-forward fold returns",
                "stop-exit rate",
                "capacity-limited rate",
                "validation and holdout trade depth",
            ],
            "do_not_do": [
                "Do not claim a direct After-the-Buy High-and-Tight chapter.",
                "Do not promote to tradable-final-95 while walk-forward has negative folds.",
                "Do not merge High-and-Tight with ordinary Bull Flags; shared family logic is statistical only.",
            ],
        },
        "current_evidence": {
            "generic_tradable_layer": generic_evidence,
            "branch_optimization_layer": branch_evidence,
            "governance": governance,
        },
        "phase_b_action": _phase_b_action(branch_evidence, governance),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "high_tight_flags_after_buy_rules.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_markdown(out_dir / "high_tight_flags_after_buy_rules.md", result)
    return result


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _phase_b_action(branch_evidence: Mapping[str, Any], governance: Mapping[str, Any]) -> str:
    blockers = ",".join(str(item) for item in branch_evidence.get("promotion_blockers") or [])
    if "walk_forward_has_negative_fold" in blockers or "walk_forward_has_negative_fold" in str(governance.get("tradable_blockers") or ""):
        return "Keep as BUY-core research/watchlist; source-aligned branch optimization was tested, but negative walk-forward folds block tradable-final promotion."
    score = _float(branch_evidence.get("score"))
    if score is not None and score >= 95:
        return "Eligible for tradable-final review if governance and publication gates also pass."
    return "Run source-aligned branch optimization before any promotion claim."


def _write_markdown(path: Path, result: Mapping[str, Any]) -> None:
    relationship = result.get("source_relationship") if isinstance(result.get("source_relationship"), Mapping) else {}
    branch = ((result.get("current_evidence") or {}).get("branch_optimization_layer") or {}) if isinstance(result.get("current_evidence"), Mapping) else {}
    lines = [
        "# High-and-Tight Flags After-the-Buy Rules",
        "",
        f"- Ruleset ID: `{result['ruleset_id']}`",
        f"- Status: `{result['status']}`",
        f"- Pattern: `{result['pattern_id']}`",
        f"- After-the-Buy source used: `{relationship.get('after_buy_source_used')}`",
        f"- Direct After-the-Buy High-and-Tight chapter: `{relationship.get('direct_after_buy_chapter_available')}`",
        f"- Branch optimization score: `{branch.get('score')}`",
        f"- Branch release status: `{branch.get('release_status')}`",
        f"- Phase action: {result.get('phase_b_action')}",
        "",
        "## Source Relationship",
        "",
        str(relationship.get("interpretation") or ""),
        "",
        "## Source-Grounded Rules",
        "",
        "| Rule | Origin | Local BUY interpretation |",
        "|---|---|---|",
    ]
    for rule in result.get("source_rules") or []:
        if not isinstance(rule, Mapping):
            continue
        lines.append(
            f"| `{rule.get('rule_id')}` | {rule.get('source_origin')} / {rule.get('source_section')} | {rule.get('local_buy_interpretation')} |"
        )
    lines.extend(
        [
            "",
            "## Current Evidence",
            "",
            "| Layer | Score | Release | Blockers |",
            "|---|---:|---|---|",
        ]
    )
    evidence = result.get("current_evidence") if isinstance(result.get("current_evidence"), Mapping) else {}
    for name in ("generic_tradable_layer", "branch_optimization_layer"):
        row = evidence.get(name) if isinstance(evidence.get(name), Mapping) else {}
        blockers = row.get("promotion_blockers")
        lines.append(f"| `{name}` | {row.get('score')} | {row.get('release_status')} | {blockers} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build After-the-Buy High-and-Tight Flag BUY rules.")
    parser.add_argument("--after-buy-pdf", type=Path, default=DEFAULT_AFTER_BUY_PDF)
    parser.add_argument("--source-map", type=Path, default=DEFAULT_SOURCE_MAP)
    parser.add_argument("--source-notes", type=Path, default=DEFAULT_SOURCE_NOTES)
    parser.add_argument("--branch-optimization", type=Path, default=DEFAULT_BRANCH_OPTIMIZATION)
    parser.add_argument("--generic-tradable-dir", type=Path, default=DEFAULT_GENERIC_TRADABLE_DIR)
    parser.add_argument("--governance", type=Path, default=DEFAULT_GOVERNANCE_MATRIX)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    result = build_after_buy_high_tight_flags_rules(
        after_buy_pdf=args.after_buy_pdf,
        source_map_path=args.source_map,
        source_notes_path=args.source_notes,
        branch_optimization_path=args.branch_optimization,
        generic_tradable_dir=args.generic_tradable_dir,
        governance_path=args.governance,
        out_dir=args.out_dir,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "pattern_id": result["pattern_id"],
                "direct_after_buy_chapter_available": result["source_relationship"]["direct_after_buy_chapter_available"],
                "branch_score": result["current_evidence"]["branch_optimization_layer"]["score"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
