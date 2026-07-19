"""Build After-the-Buy BUY-watchlist rules for Broadening Bottoms."""

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


RULESET_ID = "after_buy_broadening_bottoms_rules_v1"
DEFAULT_SOURCE_MAP = DEFAULT_AFTER_BUY_OUT_DIR / "after_buy_source_map.json"
DEFAULT_OUT_DIR = DEFAULT_AFTER_BUY_OUT_DIR / "broadening_bottoms"
DEFAULT_SOURCE_NOTES = Path("artifacts/scanner_v2/broadening_family_public_chapters/broadening_bottoms/broadening_bottoms_source_notes.json")
DEFAULT_GENERIC_TRADABLE_DIR = Path("artifacts/scanner_v2/chapter_tradable_layer/broadening_bottoms")
DEFAULT_BRANCH_OPTIMIZATION = Path("artifacts/scanner_v2/chapter_branch_optimization/broadening_bottoms/branch_optimization_summary.json")
DEFAULT_GOVERNANCE_MATRIX = Path("artifacts/final_chapters/governance/chapter_governance_matrix.json")


REQUIRED_SOURCE_SECTIONS = (
    "Behavior at a Glance",
    "Identification",
    "Buy Setup 1",
    "Sell Setups by the Numbers",
    "Best Stop Locations",
    "Configuration Trading",
    "Sell Setups",
    "Measure Rule",
    "Trading",
    "Closing Position",
)

SOURCE_RULES: tuple[dict[str, Any], ...] = (
    {
        "rule_id": "atb.bb.two_sided_behavior",
        "source_origin": "after_buy_chapter_3",
        "source_section": "Behavior at a Glance",
        "source_paraphrase": "Broadening Bottoms have both buy and sell behavior; the branch and path matter.",
        "local_buy_interpretation": "Keep it as BUY-watchlist/reference unless the long branch passes fold and scope gates.",
    },
    {
        "rule_id": "atb.bb.buy_setup_not_aggregate",
        "source_origin": "after_buy_chapter_3",
        "source_section": "Buy Setup 1",
        "source_paraphrase": "The bullish use requires a defined buy setup, not merely any broadening formation.",
        "local_buy_interpretation": "Use confirmed up-branch/context filters and do not treat the mixed aggregate as direct BUY evidence.",
    },
    {
        "rule_id": "atb.bb.sell_setup_caveat",
        "source_origin": "after_buy_chapter_3",
        "source_section": "Sell Setups / Sell Setups by the Numbers",
        "source_paraphrase": "The same family contains sell-side behavior that must be separated from the bullish reading.",
        "local_buy_interpretation": "Downside rows become avoid/exit context in Vietnam cash equities, not BUY candidates.",
    },
    {
        "rule_id": "atb.bb.stop_and_configuration",
        "source_origin": "after_buy_chapter_3",
        "source_section": "Best Stop Locations / Configuration Trading",
        "source_paraphrase": "Stop placement and configuration strongly affect whether a broadening setup is tradable.",
        "local_buy_interpretation": "Keep MAE, stop-exit, capacity, and fold checks; wide paths cannot be papered over by MFE.",
    },
    {
        "rule_id": "atb.bb.measure_rule_full_height",
        "source_origin": "after_buy_chapter_3",
        "source_section": "Measure Rule",
        "source_paraphrase": "The broadening measure rule uses formation height, but target attainment varies.",
        "local_buy_interpretation": "Keep full-height target as source benchmark and use fractional diagnostics for Vietnam.",
    },
    {
        "rule_id": "bb.shape.megaphone",
        "source_origin": "broadening_source_notes",
        "source_section": "Broadening morphology",
        "source_paraphrase": "The pattern expands like a megaphone with higher highs and lower lows.",
        "local_buy_interpretation": "Detector quality must remain morphology-first; broad volatility alone is not enough.",
    },
    {
        "rule_id": "bb.breakout.close_confirmed",
        "source_origin": "broadening_source_notes",
        "source_section": "Breakout confirmation",
        "source_paraphrase": "The event confirms when price closes outside the pattern boundary.",
        "local_buy_interpretation": "BUY-watchlist rows must be close-confirmed and branch-tagged.",
    },
    {
        "rule_id": "bb.role.reference_not_trade_promise",
        "source_origin": "broadening_source_notes",
        "source_section": "Role",
        "source_paraphrase": "Statistics are a reference, not a trading commitment.",
        "local_buy_interpretation": "Current evidence supports reference/watchlist use, not tradable-final promotion.",
    },
)


def _read_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _broadening_bottoms_outline(after_buy_pdf: Path) -> dict[str, Any]:
    reader = PdfReader(str(after_buy_pdf))
    outline = list(reader.outline)
    for idx, item in enumerate(outline):
        if isinstance(item, list):
            continue
        title = str(getattr(item, "title", item)).strip()
        if title == "Chapter 3 Broadening Bottoms":
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
                "source_chapter_no": 3,
                "source_title": "Broadening Bottoms",
                "outline_title": title,
                "pdf_page": reader.get_destination_page_number(item) + 1,
                "sections": sections,
            }
    raise RuntimeError("Could not find Chapter 3 Broadening Bottoms in After-the-Buy PDF outline.")


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


def _load_tradable(path: Path) -> dict[str, Any]:
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
        "promotion_blockers": scorecard.get("promotion_blockers"),
        "selected_strategy_id": selected.get("selected_strategy_id"),
        "trades": metrics.get("trades"),
        "validation_total_return_pct": metrics.get("validation_total_return_pct"),
        "holdout_total_return_pct": metrics.get("holdout_total_return_pct"),
        "target_multiple": metrics.get("target_multiple"),
        "fixed_walk_forward_summary": selected.get("fixed_walk_forward_summary"),
        "adaptive_walk_forward_summary": selected.get("adaptive_walk_forward_summary"),
    }


def _load_branch(path: Path) -> dict[str, Any]:
    data = _read_json(path)
    metrics = data.get("selected_metrics") if isinstance(data.get("selected_metrics"), Mapping) else {}
    return {
        "path": str(path),
        "available": bool(data),
        "score": _float(data.get("score")),
        "classification": data.get("classification"),
        "release_status": data.get("release_status"),
        "promotion_blockers": data.get("promotion_blockers"),
        "selected_strategy_id": data.get("selected_strategy_id"),
        "trades": metrics.get("trades"),
        "validation_trades": metrics.get("validation_trades"),
        "holdout_trades": metrics.get("holdout_trades"),
        "fixed_walk_forward_summary": data.get("fixed_walk_forward_summary"),
        "adaptive_walk_forward_summary": data.get("adaptive_walk_forward_summary"),
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
                "tradable_applicability": row.get("tradable_applicability"),
                "publication_status": row.get("publication_status"),
            }
    return {"governance_path": str(governance_path), "tradable_score": None, "tradable_status": "not_in_governance_matrix"}


def build_after_buy_broadening_bottoms_rules(
    *,
    after_buy_pdf: Path = DEFAULT_AFTER_BUY_PDF,
    source_map_path: Path = DEFAULT_SOURCE_MAP,
    source_notes_path: Path = DEFAULT_SOURCE_NOTES,
    generic_tradable_dir: Path = DEFAULT_GENERIC_TRADABLE_DIR,
    branch_optimization_path: Path = DEFAULT_BRANCH_OPTIMIZATION,
    governance_path: Path = DEFAULT_GOVERNANCE_MATRIX,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    if not source_map_path.exists():
        source_map = build_after_buy_source_map(after_buy_pdf=after_buy_pdf, out_dir=source_map_path.parent)
    else:
        source_map = _read_json(source_map_path)
    allowed = assert_after_buy_buy_rule_allowed("broadening_bottoms", source_map)
    source = _broadening_bottoms_outline(after_buy_pdf)
    section_titles = {str(section.get("title")) for section in source["sections"]}
    missing_sections = [section for section in REQUIRED_SOURCE_SECTIONS if section not in section_titles]
    source_notes = _source_notes_summary(source_notes_path)
    generic = _load_tradable(generic_tradable_dir)
    branch = _load_branch(branch_optimization_path)
    governance = _load_governance("broadening_bottoms", governance_path)

    failures: list[str] = []
    if allowed.get("pattern_buy_role", {}).get("buy_layer_allowed") is not True:
        failures.append("broadening_bottoms:not_buy_allowed")
    if missing_sections:
        failures.append("missing_required_source_sections")
    if not source_notes["available"] or source_notes.get("source_review_status") != "PASS":
        failures.append("missing_or_failed_broadening_source_notes")
    if branch["score"] is None and generic["score"] is None:
        failures.append("missing_tradable_evidence")

    result = {
        "ruleset_id": RULESET_ID,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "source_grounding_id": source_map.get("source_grounding_id"),
        "buy_first_policy_id": source_map.get("buy_first_policy_id"),
        "pattern_id": "broadening_bottoms",
        "source_relationship": {
            "after_buy_source_used": "Chapter 3 Broadening Bottoms",
            "pattern_specific_source_used": str(source_notes_path),
            "interpretation": "After-the-Buy supports bullish broadening-bottom use, but the family remains two-sided and path-wide.",
        },
        "source_chapter": source,
        "required_sections": list(REQUIRED_SOURCE_SECTIONS),
        "source_notes": source_notes,
        "source_rules": list(SOURCE_RULES),
        "pattern_buy_role": allowed.get("pattern_buy_role"),
        "local_buy_contract": {
            "scope": "Vietnam BUY-watchlist/reference; not tradable-final under current mixed-direction/fold evidence.",
            "entry": "close-confirmed bullish branch only after broadening-bottom morphology and context filters",
            "target_family": ["fractional height diagnostics", "1.0x full-height source benchmark"],
            "stop_family": ["explicit risk stop", "path-wide MAE/stop-exit checks", "capacity and liquidity stress"],
            "must_keep_metrics": [
                "branch direction",
                "target-first-before-adverse",
                "MAE and stop-exit rate",
                "walk-forward fold returns",
                "scope/mixed-direction warning",
            ],
            "no_overlift_decision": "Do not promote while best evidence is below 95 and still carries mixed-scope plus negative-fold blockers.",
        },
        "current_evidence": {
            "generic_tradable_layer": generic,
            "branch_optimization_layer": branch,
            "governance": governance,
        },
        "phase_c_action": "Keep as BUY-watchlist/reference; current best branch is near 90 but blocked by scope and negative walk-forward folds.",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "broadening_bottoms_after_buy_rules.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_markdown(out_dir / "broadening_bottoms_after_buy_rules.md", result)
    return result


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_markdown(path: Path, result: Mapping[str, Any]) -> None:
    evidence = result.get("current_evidence") if isinstance(result.get("current_evidence"), Mapping) else {}
    branch = evidence.get("branch_optimization_layer") if isinstance(evidence.get("branch_optimization_layer"), Mapping) else {}
    lines = [
        "# Broadening Bottoms After-the-Buy Rules",
        "",
        f"- Ruleset ID: `{result['ruleset_id']}`",
        f"- Status: `{result['status']}`",
        f"- Pattern: `{result['pattern_id']}`",
        f"- Source: `{result['source_relationship']['after_buy_source_used']}`",
        f"- Best branch score: `{branch.get('score')}`",
        f"- Branch release status: `{branch.get('release_status')}`",
        f"- Phase action: {result.get('phase_c_action')}",
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
    parser = argparse.ArgumentParser(description="Build After-the-Buy Broadening Bottoms BUY-watchlist rules.")
    parser.add_argument("--after-buy-pdf", type=Path, default=DEFAULT_AFTER_BUY_PDF)
    parser.add_argument("--source-map", type=Path, default=DEFAULT_SOURCE_MAP)
    parser.add_argument("--source-notes", type=Path, default=DEFAULT_SOURCE_NOTES)
    parser.add_argument("--generic-tradable-dir", type=Path, default=DEFAULT_GENERIC_TRADABLE_DIR)
    parser.add_argument("--branch-optimization", type=Path, default=DEFAULT_BRANCH_OPTIMIZATION)
    parser.add_argument("--governance", type=Path, default=DEFAULT_GOVERNANCE_MATRIX)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    result = build_after_buy_broadening_bottoms_rules(
        after_buy_pdf=args.after_buy_pdf,
        source_map_path=args.source_map,
        source_notes_path=args.source_notes,
        generic_tradable_dir=args.generic_tradable_dir,
        branch_optimization_path=args.branch_optimization,
        governance_path=args.governance,
        out_dir=args.out_dir,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "pattern_id": result["pattern_id"],
                "branch_score": result["current_evidence"]["branch_optimization_layer"]["score"],
                "phase_c_action": result["phase_c_action"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
