"""Build After-the-Buy BUY rules for Bull Pennants.

Bull Pennant is already a strong tradable research candidate, but its current
ceiling audit blocks promotion because walk-forward still contains negative
folds.  This artifact anchors the decision to the source rules and the
no-overlift guard so later work does not keep re-mining the same branch space.
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


RULESET_ID = "after_buy_bull_pennants_rules_v1"
DEFAULT_SOURCE_MAP = DEFAULT_AFTER_BUY_OUT_DIR / "after_buy_source_map.json"
DEFAULT_OUT_DIR = DEFAULT_AFTER_BUY_OUT_DIR / "bull_pennants"
DEFAULT_SOURCE_NOTES = Path("artifacts/scanner_v2/flag_like_family_source_grounding/bull_pennants_source_notes.json")
DEFAULT_SCORECARD = Path("artifacts/scanner_v2/bull_pennants_tradable_setup/bull_pennant_tradable_scorecard.json")
DEFAULT_SELECTED_STRATEGY = Path("artifacts/scanner_v2/bull_pennants_tradable_setup/bull_pennant_tradable_selected_strategy.json")
DEFAULT_RELEASE_CANDIDATE = Path("artifacts/scanner_v2/bull_pennants_release_candidate/bull_pennant_release_candidate.json")
DEFAULT_CEILING_AUDIT = Path("artifacts/scanner_v2/bull_pennants_tradable_setup/bull_pennant_tradable_ceiling_audit/bull_pennant_tradable_ceiling_audit.json")
DEFAULT_GOVERNANCE_MATRIX = Path("artifacts/final_chapters/governance/chapter_governance_matrix.json")


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
        "rule_id": "atb.bp.flagpole_vigor",
        "source_origin": "after_buy_chapter_8",
        "source_section": "Identification",
        "source_pages": [204, 205, 206],
        "source_paraphrase": "A pennant should follow a steep short-term price run; without the pole it is just a small triangle.",
        "local_buy_interpretation": "Bull Pennant keeps the prior-pole/setup-score gate before any BUY test.",
    },
    {
        "rule_id": "atb.bp.short_duration",
        "source_origin": "after_buy_chapter_8",
        "source_section": "Identification",
        "source_pages": [206],
        "source_paraphrase": "Flags and pennants are short formations and should not be confused with longer triangles.",
        "local_buy_interpretation": "Do not widen duration to gain sample; stale bodies move the pattern into Triangle Family logic.",
    },
    {
        "rule_id": "atb.bp.confirmed_close_breakout",
        "source_origin": "after_buy_chapter_8",
        "source_section": "Identification",
        "source_pages": [206, 207],
        "source_paraphrase": "The actionable event is a close outside the pattern boundary.",
        "local_buy_interpretation": "BUY tests use close-confirmed upward breakout and delayed executable entry.",
    },
    {
        "rule_id": "atb.bp.short_term_trade",
        "source_origin": "after_buy_chapter_8",
        "source_section": "Trading",
        "source_pages": [215, 216],
        "source_paraphrase": "Pennants are continuation tools rather than broad reversal bets.",
        "local_buy_interpretation": "Keep continuation-window, target-first, and fold-stability diagnostics in the release gate.",
    },
    {
        "rule_id": "atb.bp.stop_and_failure_context",
        "source_origin": "after_buy_chapter_8",
        "source_section": "Best Stop Locations / Focus on Failures",
        "source_pages": [213, 217, 218],
        "source_paraphrase": "Stops and failures must account for normal pullbacks, overhead resistance, and event distortions.",
        "local_buy_interpretation": "Use explicit stop/cost/liquidity policies; a negative fold cannot be hidden by a prettier headline return.",
    },
    {
        "rule_id": "bp.shape.converging_lines",
        "source_origin": "pennant_source_notes",
        "source_section": "Pennant morphology",
        "source_paraphrase": "Body must be a short triangle bounded by two converging trendlines, not a parallel flag channel.",
        "local_buy_interpretation": "Bull Pennant remains separate from Bull Flag; shared family statistics do not merge geometry.",
    },
    {
        "rule_id": "bp.prior_trend.steep_up",
        "source_origin": "pennant_source_notes",
        "source_section": "Pennant morphology",
        "source_paraphrase": "A steep, quick advance must precede the pennant.",
        "local_buy_interpretation": "The pole is required, but very extended/exhausted poles are filtered by the execution contract.",
    },
    {
        "rule_id": "bp.volume.contracts",
        "source_origin": "pennant_source_notes",
        "source_section": "Pennant diagnostics",
        "source_paraphrase": "Volume normally contracts during the pennant; this is diagnostic unless configured as a hard gate.",
        "local_buy_interpretation": "Volume can support the setup but cannot rescue negative walk-forward evidence.",
    },
    {
        "rule_id": "bp.target.pole_projection_conservative",
        "source_origin": "pennant_source_notes",
        "source_section": "Pennant measure rule",
        "source_paraphrase": "The pole projection is useful but should be reported with calibrated fractional bands.",
        "local_buy_interpretation": "The current selected contract uses 0.75x as stretch/local target, while 0.5x remains the conservative preflight anchor.",
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


def _score_evidence(scorecard_path: Path, selected_path: Path, release_path: Path, ceiling_path: Path, governance_path: Path) -> dict[str, Any]:
    scorecard = _read_json(scorecard_path)
    selected = _read_json(selected_path)
    release = _read_json(release_path)
    ceiling = _read_json(ceiling_path)
    selected_metrics = selected.get("selected_metrics") if isinstance(selected.get("selected_metrics"), Mapping) else {}
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
            "trades": selected_metrics.get("trades"),
            "validation_trades": selected_metrics.get("validation_trades"),
            "holdout_trades": selected_metrics.get("holdout_trades"),
            "target_multiple": selected_metrics.get("target_multiple"),
            "stop_loss_pct": selected_metrics.get("stop_loss_pct"),
        },
        "release_candidate": {
            "path": str(release_path),
            "release_status": release.get("release_status"),
            "score": _float(release.get("score")),
            "claim_level": release.get("claim_level"),
            "walk_forward": release.get("walk_forward"),
            "adaptive_walk_forward": release.get("adaptive_walk_forward"),
        },
        "ceiling_audit": {
            "path": str(ceiling_path),
            "audit_id": ceiling.get("audit_id"),
            "best_score": _float(ceiling.get("best_score")),
            "best_strategy_id": ceiling.get("best_strategy_id"),
            "main_blocker": ceiling.get("main_blocker"),
            "ceiling_verdict": ceiling.get("ceiling_verdict"),
            "no_overlift_guard": ceiling.get("no_overlift_guard"),
        },
        "governance": _load_governance("bull_pennants", governance_path),
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


def build_after_buy_bull_pennants_rules(
    *,
    after_buy_pdf: Path = DEFAULT_AFTER_BUY_PDF,
    source_map_path: Path = DEFAULT_SOURCE_MAP,
    source_notes_path: Path = DEFAULT_SOURCE_NOTES,
    scorecard_path: Path = DEFAULT_SCORECARD,
    selected_strategy_path: Path = DEFAULT_SELECTED_STRATEGY,
    release_candidate_path: Path = DEFAULT_RELEASE_CANDIDATE,
    ceiling_audit_path: Path = DEFAULT_CEILING_AUDIT,
    governance_path: Path = DEFAULT_GOVERNANCE_MATRIX,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    if not source_map_path.exists():
        source_map = build_after_buy_source_map(after_buy_pdf=after_buy_pdf, out_dir=source_map_path.parent)
    else:
        source_map = _read_json(source_map_path)

    allowed = assert_after_buy_buy_rule_allowed("bull_pennants", source_map)
    source = _flags_outline(after_buy_pdf)
    section_titles = {str(section.get("title")) for section in source["sections"]}
    missing_sections = [section for section in REQUIRED_SOURCE_SECTIONS if section not in section_titles]
    source_notes = _source_notes_summary(source_notes_path)
    evidence = _score_evidence(scorecard_path, selected_strategy_path, release_candidate_path, ceiling_audit_path, governance_path)

    failures: list[str] = []
    if allowed.get("pattern_buy_role", {}).get("buy_layer_allowed") is not True:
        failures.append("bull_pennants:not_buy_allowed")
    if missing_sections:
        failures.append("missing_required_source_sections")
    if not source_notes["available"] or source_notes.get("source_review_status") != "PASS":
        failures.append("missing_or_failed_bull_pennant_source_notes")
    if evidence["scorecard"]["score"] is None or evidence["ceiling_audit"]["best_score"] is None:
        failures.append("missing_tradable_or_ceiling_evidence")

    result = {
        "ruleset_id": RULESET_ID,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "source_grounding_id": source_map.get("source_grounding_id"),
        "buy_first_policy_id": source_map.get("buy_first_policy_id"),
        "pattern_id": "bull_pennants",
        "source_relationship": {
            "after_buy_source_used": "Chapter 8 Flags and Pennants",
            "pattern_specific_source_used": str(source_notes_path),
            "interpretation": "After-the-Buy directly supports the Pennant family for post-buy behavior; Bull Pennant geometry remains pattern-specific.",
        },
        "source_chapter": source,
        "required_sections": list(REQUIRED_SOURCE_SECTIONS),
        "source_notes": source_notes,
        "source_rules": list(SOURCE_RULES),
        "pattern_buy_role": allowed.get("pattern_buy_role"),
        "local_buy_contract": {
            "scope": "Vietnam long-cash BUY core, currently research-candidate blocked rather than tradable-final.",
            "entry": "close-confirmed upward breakout after steep prior advance and converging pennant body",
            "target_family": ["0.5x pole conservative reference", "0.75x selected local stretch target", "1.0x full-pole diagnostic only"],
            "stop_family": ["8% selected risk stop", "same-bar stop-first policy", "liquidity/capacity stress"],
            "must_keep_metrics": [
                "walk-forward fold returns",
                "fixed and adaptive walk-forward summaries",
                "cost stress",
                "capacity participation",
                "validation/holdout totals",
            ],
            "no_overlift_decision": "Do not promote while best ceiling score remains below 95 and walk-forward negative folds remain.",
        },
        "current_evidence": evidence,
        "phase_b_action": _phase_b_action(evidence),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "bull_pennants_after_buy_rules.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_markdown(out_dir / "bull_pennants_after_buy_rules.md", result)
    return result


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _phase_b_action(evidence: Mapping[str, Any]) -> str:
    ceiling = evidence.get("ceiling_audit") if isinstance(evidence.get("ceiling_audit"), Mapping) else {}
    best_score = _float(ceiling.get("best_score"))
    blocker = str(ceiling.get("main_blocker") or "")
    verdict = str(ceiling.get("ceiling_verdict") or "")
    if best_score is not None and best_score < 95 and "walk_forward" in blocker:
        return "Stop optimization under no-overlift guard; Bull Pennant is near-threshold but remains blocked by negative walk-forward folds."
    if verdict:
        return verdict
    return "Run ceiling audit before any promotion decision."


def _write_markdown(path: Path, result: Mapping[str, Any]) -> None:
    evidence = result.get("current_evidence") if isinstance(result.get("current_evidence"), Mapping) else {}
    scorecard = evidence.get("scorecard") if isinstance(evidence.get("scorecard"), Mapping) else {}
    ceiling = evidence.get("ceiling_audit") if isinstance(evidence.get("ceiling_audit"), Mapping) else {}
    lines = [
        "# Bull Pennants After-the-Buy Rules",
        "",
        f"- Ruleset ID: `{result['ruleset_id']}`",
        f"- Status: `{result['status']}`",
        f"- Pattern: `{result['pattern_id']}`",
        f"- Source: `{result['source_relationship']['after_buy_source_used']}`",
        f"- Scorecard score: `{scorecard.get('score')}`",
        f"- Ceiling best score: `{ceiling.get('best_score')}`",
        f"- Ceiling blocker: `{ceiling.get('main_blocker')}`",
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
    lines.extend(
        [
            "",
            "## No-Overlift Decision",
            "",
            str(result.get("local_buy_contract", {}).get("no_overlift_decision") if isinstance(result.get("local_buy_contract"), Mapping) else ""),
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build After-the-Buy Bull Pennant BUY rules.")
    parser.add_argument("--after-buy-pdf", type=Path, default=DEFAULT_AFTER_BUY_PDF)
    parser.add_argument("--source-map", type=Path, default=DEFAULT_SOURCE_MAP)
    parser.add_argument("--source-notes", type=Path, default=DEFAULT_SOURCE_NOTES)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--selected-strategy", type=Path, default=DEFAULT_SELECTED_STRATEGY)
    parser.add_argument("--release-candidate", type=Path, default=DEFAULT_RELEASE_CANDIDATE)
    parser.add_argument("--ceiling-audit", type=Path, default=DEFAULT_CEILING_AUDIT)
    parser.add_argument("--governance", type=Path, default=DEFAULT_GOVERNANCE_MATRIX)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    result = build_after_buy_bull_pennants_rules(
        after_buy_pdf=args.after_buy_pdf,
        source_map_path=args.source_map,
        source_notes_path=args.source_notes,
        scorecard_path=args.scorecard,
        selected_strategy_path=args.selected_strategy,
        release_candidate_path=args.release_candidate,
        ceiling_audit_path=args.ceiling_audit,
        governance_path=args.governance,
        out_dir=args.out_dir,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "pattern_id": result["pattern_id"],
                "score": result["current_evidence"]["scorecard"]["score"],
                "ceiling_best_score": result["current_evidence"]["ceiling_audit"]["best_score"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
