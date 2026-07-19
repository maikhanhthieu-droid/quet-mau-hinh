"""Build After-the-Buy BUY rules for Double Bottoms.

The After-the-Buy chapter treats Double Bottoms as one BUY family.  Edition 1
publishes Adam/Eve variants, but the tradable layer must not force each thin
variant into a standalone 95+ setup when family-level evidence is stronger.
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


RULESET_ID = "after_buy_double_bottoms_rules_v1"
DEFAULT_SOURCE_MAP = DEFAULT_AFTER_BUY_OUT_DIR / "after_buy_source_map.json"
DEFAULT_OUT_DIR = DEFAULT_AFTER_BUY_OUT_DIR / "double_bottoms"
DEFAULT_TRADABLE_DIR = Path("artifacts/scanner_v2/chapter_tradable_layer")
DEFAULT_GOVERNANCE_MATRIX = Path("artifacts/final_chapters/governance/chapter_governance_matrix.json")
DEFAULT_RESCUE = Path("artifacts/scanner_v2/double_family_tradable_rescue/double_bottoms/double_bottoms_tradable_rescue.json")
DOUBLE_BOTTOM_VARIANTS = (
    "double_bottoms_adam_adam",
    "double_bottoms_adam_eve",
    "double_bottoms_eve_adam",
    "double_bottoms_eve_eve",
)


REQUIRED_SOURCE_SECTIONS = (
    "Behavior at a Glance",
    "Identification",
    "Buy Setups",
    "Sell Setup",
    "Best Stop Locations",
    "Configuration Trading",
    "Measure Rule",
    "Trading",
    "Closing Position",
)


SOURCE_RULES: tuple[dict[str, Any], ...] = (
    {
        "rule_id": "atb.db.wait_for_confirmation",
        "source_section": "Behavior at a Glance",
        "source_pages": [136, 140, 160],
        "source_paraphrase": "Twin valleys are not a double bottom until price closes above the intervening peak.",
        "local_buy_interpretation": "No Vietnam BUY test may enter before close-confirmed breakout above the pattern top.",
    },
    {
        "rule_id": "atb.db.unconfirmed_failure_risk",
        "source_section": "Behavior at a Glance",
        "source_pages": [136],
        "source_paraphrase": "A large share of unconfirmed twin bottoms fail by closing below the lower valley.",
        "local_buy_interpretation": "Scanner outputs should keep pre-confirmation twins out of tradable scoring; they are watchlist candidates only.",
    },
    {
        "rule_id": "atb.db.valley_separation_and_height",
        "source_section": "Identification",
        "source_pages": [138, 140],
        "source_paraphrase": "The two valleys need meaningful separation and a proportional rise between them.",
        "local_buy_interpretation": "Keep morphology gates for valley separation and center-peak height before applying execution rules.",
    },
    {
        "rule_id": "atb.db.breakout_volume_secondary",
        "source_section": "Identification",
        "source_pages": [140],
        "source_paraphrase": "A high-volume breakout is not required and did not improve performance in the source study.",
        "local_buy_interpretation": "Volume remains a context feature; it must not become a hard BUY gate or rescue weak geometry.",
    },
    {
        "rule_id": "atb.db.busted_pattern_is_sell_or_avoid",
        "source_section": "Sell Setup",
        "source_pages": [146],
        "source_paraphrase": "A busted double bottom breaks out upward, fails to travel far, then closes below the lower bottom.",
        "local_buy_interpretation": "Busted behavior is an exit/avoid flag in Vietnam cash equities, not a short-selling BUY-layer promotion.",
    },
    {
        "rule_id": "atb.db.stop_below_lower_bottom",
        "source_section": "Best Stop Locations",
        "source_pages": [148],
        "source_paraphrase": "A stop below the lower bottom is structurally safer than a stop inside the pattern, though the loss can be larger.",
        "local_buy_interpretation": "Compare local percentage stops with a structural lower-bottom stop; avoid tight stops inside the base as default.",
    },
    {
        "rule_id": "atb.db.retest_reclaim_entry",
        "source_section": "Trading",
        "source_pages": [155, 160],
        "source_paraphrase": "The chapter's trading logic waits for confirmation and then reads whether price can continue beyond resistance.",
        "local_buy_interpretation": "Family-level rescue can use retest/reclaim entry after breakout, provided confirmation remains intact.",
    },
    {
        "rule_id": "atb.db.configuration_weekly_context",
        "source_section": "Configuration Trading",
        "source_pages": [148],
        "source_paraphrase": "Configuration checks are read on the weekly scale after identifying the daily double bottom.",
        "local_buy_interpretation": "Prefer family/context filters over over-tight Adam/Eve variant filters when variant sample is thin.",
    },
    {
        "rule_id": "atb.db.flat_base_failure",
        "source_section": "Configuration Trading",
        "source_pages": [154],
        "source_paraphrase": "A double bottom after a long flat base can run into overhead resistance and fail.",
        "local_buy_interpretation": "Mark flat-base/range-top resistance as an avoid or size-reduction condition.",
    },
    {
        "rule_id": "atb.db.measure_rule_half_height_diagnostic",
        "source_section": "Measure Rule",
        "source_pages": [154, 155],
        "source_paraphrase": "The full height target is useful but the half-height target is much easier to reach.",
        "local_buy_interpretation": "Use 0.5x as local base/diagnostic and keep 1.0x as source benchmark; do not require full target for base score.",
    },
    {
        "rule_id": "atb.db.variant_as_subgroup_not_overfit_unit",
        "source_section": "Closing Position",
        "source_pages": [160],
        "source_paraphrase": "The chapter emphasizes confirmation and configuration over treating every look-alike valley pair as a trade.",
        "local_buy_interpretation": "Adam/Eve variants can remain published subgroups; promotion should use family evidence if variant fold depth is too thin.",
    },
)


def _read_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _double_bottoms_outline(after_buy_pdf: Path) -> dict[str, Any]:
    reader = PdfReader(str(after_buy_pdf))
    outline = list(reader.outline)
    for idx, item in enumerate(outline):
        if isinstance(item, list):
            continue
        title = str(getattr(item, "title", item)).strip()
        if title == "Chapter 5 Double Bottoms":
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
                "source_chapter_no": 5,
                "source_title": "Double Bottoms",
                "outline_title": title,
                "pdf_page": reader.get_destination_page_number(item) + 1,
                "sections": sections,
            }
    raise RuntimeError("Could not find Chapter 5 Double Bottoms in After-the-Buy PDF outline.")


def _load_tradable_evidence(pattern_id: str, tradable_dir: Path) -> dict[str, Any]:
    chapter_dir = tradable_dir / pattern_id
    scorecard = _read_json(chapter_dir / "scorecard.json")
    release = _read_json(chapter_dir / "release_candidate.json")
    selected = _read_json(chapter_dir / "selected_strategy.json")
    source_scope = selected.get("source_scope") if isinstance(selected.get("source_scope"), Mapping) else {}
    return {
        "scorecard_path": str(chapter_dir / "scorecard.json") if scorecard else None,
        "release_candidate_path": str(chapter_dir / "release_candidate.json") if release else None,
        "selected_strategy_path": str(chapter_dir / "selected_strategy.json") if selected else None,
        "score": _float(scorecard.get("score")),
        "classification": scorecard.get("classification"),
        "release_status": release.get("release_status"),
        "selected_strategy_status": selected.get("status"),
        "selected_strategy_id": selected.get("selected_strategy_id"),
        "events_scoped": source_scope.get("events_scoped"),
        "trades": (selected.get("selected_metrics") or {}).get("trades") if isinstance(selected.get("selected_metrics"), Mapping) else None,
    }


def _load_governance_evidence(pattern_id: str, governance_path: Path) -> dict[str, Any]:
    matrix = _read_json(governance_path)
    rows = matrix.get("chapters") if isinstance(matrix.get("chapters"), list) else []
    for row in rows:
        if not isinstance(row, Mapping) or str(row.get("pattern_id")) != pattern_id:
            continue
        return {
            "governance_path": str(governance_path),
            "tradable_score": _float(row.get("tradable_score")),
            "tradable_status": row.get("tradable_status"),
            "tradable_release_status": row.get("tradable_release_status"),
            "tradable_evidence_id": row.get("tradable_evidence_id"),
            "tradable_blockers": row.get("tradable_blockers"),
        }
    return {"governance_path": str(governance_path), "tradable_score": None, "tradable_status": "not_in_governance_matrix"}


def build_after_buy_double_bottoms_rules(
    *,
    after_buy_pdf: Path = DEFAULT_AFTER_BUY_PDF,
    source_map_path: Path = DEFAULT_SOURCE_MAP,
    tradable_dir: Path = DEFAULT_TRADABLE_DIR,
    governance_path: Path = DEFAULT_GOVERNANCE_MATRIX,
    rescue_path: Path = DEFAULT_RESCUE,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    if not source_map_path.exists():
        source_map = build_after_buy_source_map(after_buy_pdf=after_buy_pdf, out_dir=source_map_path.parent)
    else:
        source_map = _read_json(source_map_path)
    source = _double_bottoms_outline(after_buy_pdf)
    section_titles = {str(section.get("title")) for section in source["sections"]}
    missing_sections = [section for section in REQUIRED_SOURCE_SECTIONS if section not in section_titles]
    rescue = _read_json(rescue_path)

    failures: list[str] = []
    pattern_rows: list[dict[str, Any]] = []
    for pattern_id in DOUBLE_BOTTOM_VARIANTS:
        allowed = assert_after_buy_buy_rule_allowed(pattern_id, source_map)
        if allowed.get("pattern_buy_role", {}).get("buy_layer_allowed") is not True:
            failures.append(f"{pattern_id}:not_buy_allowed")
        tradable = _load_tradable_evidence(pattern_id, tradable_dir)
        governance = _load_governance_evidence(pattern_id, governance_path)
        pattern_rows.append(
            {
                "pattern_id": pattern_id,
                "buy_role": allowed.get("pattern_buy_role"),
                "current_tradable": tradable,
                "governance_tradable": governance,
                "phase_b_action": _phase_b_action(pattern_id, governance, rescue),
            }
        )

    if missing_sections:
        failures.append("missing_required_source_sections")
    if rescue and float(rescue.get("best_score") or 0) >= 95.0:
        family_decision = "family_tradable_evidence_is_stronger_than_thin_variant_evidence"
    else:
        family_decision = "family_rescue_missing_or_not_passed"
        failures.append("family_rescue_missing_or_not_passed")

    result = {
        "ruleset_id": RULESET_ID,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "source_grounding_id": source_map.get("source_grounding_id"),
        "buy_first_policy_id": source_map.get("buy_first_policy_id"),
        "source_chapter": source,
        "required_sections": list(REQUIRED_SOURCE_SECTIONS),
        "source_rules": list(SOURCE_RULES),
        "patterns": pattern_rows,
        "family_rescue": {
            "path": str(rescue_path),
            "best_score": rescue.get("best_score"),
            "best_strategy_id": rescue.get("best_strategy_id"),
            "best_branch_id": rescue.get("best_branch_id"),
            "best_entry_rule": rescue.get("best_entry_rule"),
            "variant_support_decision": rescue.get("variant_support_decision"),
            "best_variant_trade_stats": rescue.get("best_variant_trade_stats"),
            "decision": family_decision,
        },
        "local_buy_contract": {
            "scope": "Vietnam long-cash BUY family; variants are reported subgroups unless they independently pass depth and walk-forward gates.",
            "entry": "close-confirmed breakout above the center peak; family rescue may use retest/reclaim after confirmation.",
            "target_family": ["0.5x height diagnostic", "0.75x family rescue target", "1.0x source benchmark"],
            "stop_family": ["structural stop below lower bottom", "percentage/risk stop", "avoid tight in-pattern stop as default"],
            "must_keep_metrics": [
                "confirmation-only entry",
                "busted-pattern exit/avoid",
                "variant trade depth",
                "family-level walk-forward",
                "capacity and cost stress",
            ],
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "double_bottoms_after_buy_rules.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_markdown(out_dir / "double_bottoms_after_buy_rules.md", result)
    return result


def _phase_b_action(pattern_id: str, governance: Mapping[str, Any], rescue: Mapping[str, Any]) -> str:
    score = governance.get("tradable_score")
    status = governance.get("tradable_status")
    if score is not None and float(score) >= 95.0 and status == "tradable_final_95":
        return "Use as a strong variant/control; do not over-optimize."
    if rescue and float(rescue.get("best_score") or 0) >= 95.0:
        return "Keep as published subgroup under family-level tradable evidence; variant-alone sample is too thin for forced 95."
    return "Rerun only after adding confirmation/retest/structural-stop rules; record blocker if fold depth remains thin."


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_markdown(path: Path, result: Mapping[str, Any]) -> None:
    rescue = result.get("family_rescue") if isinstance(result.get("family_rescue"), Mapping) else {}
    lines = [
        "# Double Bottoms After-the-Buy Rules",
        "",
        f"- Ruleset: `{result['ruleset_id']}`",
        f"- Status: `{result['status']}`",
        f"- Source: `{result['source_chapter']['source_title']}`",
        f"- Family rescue score: `{rescue.get('best_score')}`",
        f"- Family decision: `{rescue.get('decision')}`",
        "",
        "## Pattern Status",
        "",
        "| Pattern | BUY scope | Governance score | Status | Action |",
        "|---|---|---:|---|---|",
    ]
    for row in result.get("patterns") or []:
        governance = row.get("governance_tradable") if isinstance(row.get("governance_tradable"), Mapping) else {}
        role = row.get("buy_role") if isinstance(row.get("buy_role"), Mapping) else {}
        score = "" if governance.get("tradable_score") is None else f"{float(governance['tradable_score']):.2f}"
        lines.append(
            "| {pattern} | {scope} | {score} | {status} | {action} |".format(
                pattern=row.get("pattern_id"),
                scope=role.get("buy_scope"),
                score=score,
                status=governance.get("tradable_status") or "",
                action=row.get("phase_b_action"),
            )
        )
    lines.extend(
        [
            "",
            "## Source-Grounded Rules",
            "",
            "| Rule | Source section | Local BUY interpretation |",
            "|---|---|---|",
        ]
    )
    for rule in result.get("source_rules") or []:
        lines.append(f"| `{rule['rule_id']}` | {rule['source_section']} | {rule['local_buy_interpretation']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build After-the-Buy rules for Double Bottoms.")
    parser.add_argument("--after-buy-pdf", type=Path, default=DEFAULT_AFTER_BUY_PDF)
    parser.add_argument("--source-map", type=Path, default=DEFAULT_SOURCE_MAP)
    parser.add_argument("--tradable-dir", type=Path, default=DEFAULT_TRADABLE_DIR)
    parser.add_argument("--governance", type=Path, default=DEFAULT_GOVERNANCE_MATRIX)
    parser.add_argument("--rescue", type=Path, default=DEFAULT_RESCUE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    result = build_after_buy_double_bottoms_rules(
        after_buy_pdf=args.after_buy_pdf,
        source_map_path=args.source_map,
        tradable_dir=args.tradable_dir,
        governance_path=args.governance,
        rescue_path=args.rescue,
        out_dir=args.out_dir,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "ruleset_id": result["ruleset_id"],
                "out_dir": str(args.out_dir),
                "rule_count": len(result["source_rules"]),
                "family_rescue_score": result["family_rescue"]["best_score"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
