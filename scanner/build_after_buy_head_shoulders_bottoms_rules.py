"""Build After-the-Buy BUY rules for Head-and-Shoulders Bottoms.

This is a Phase-B source artifact.  It translates the After-the-Buy chapter into
local rule constraints before any further tradable optimization is attempted.
The goal is to prevent branch mining from replacing source-grounded setup,
stop, and configuration logic.
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


RULESET_ID = "after_buy_head_shoulders_bottoms_rules_v1"
DEFAULT_SOURCE_MAP = DEFAULT_AFTER_BUY_OUT_DIR / "after_buy_source_map.json"
DEFAULT_OUT_DIR = DEFAULT_AFTER_BUY_OUT_DIR / "head_shoulders_bottoms"
DEFAULT_PUBLICATION_PAYLOADS = {
    "head_and_shoulders_bottoms": Path(
        "artifacts/scanner_v2/head_shoulders_family_public_chapters/head_and_shoulders_bottoms/"
        "head_and_shoulders_bottoms_public_chapter_payload.json"
    ),
    "head_and_shoulders_bottoms_complex": Path(
        "artifacts/scanner_v2/head_shoulders_family_public_chapters/head_and_shoulders_bottoms_complex/"
        "head_and_shoulders_bottoms_complex_public_chapter_payload.json"
    ),
}
DEFAULT_TRADABLE_DIR = Path("artifacts/scanner_v2/chapter_tradable_layer")
DEFAULT_GOVERNANCE_MATRIX = Path("artifacts/final_chapters/governance/chapter_governance_matrix.json")


REQUIRED_SOURCE_SECTIONS = (
    "Behavior at a Glance",
    "Identification",
    "Buy Setup 1",
    "Buy Setup 2",
    "Buy Setup 3",
    "Best Stop Locations",
    "Configuration Trading",
    "Measure Rule",
    "Trading",
    "Closing Position",
)


SOURCE_RULES: tuple[dict[str, Any], ...] = (
    {
        "rule_id": "atb.hsb.confirmed_neckline_breakout",
        "source_section": "Identification",
        "source_pages": [224, 225],
        "source_paraphrase": "The pattern is not actionable until price confirms by breaking the neckline.",
        "local_buy_interpretation": "Long-cash tests must enter only after close-confirmed neckline breakout, never from an unconfirmed shoulder/head shape.",
    },
    {
        "rule_id": "atb.hsb.short_inbound_trend_preferred",
        "source_section": "Trading",
        "source_pages": [242],
        "source_paraphrase": "Shorter inbound declines tend to perform better than long inbound declines.",
        "local_buy_interpretation": "Add an inbound-duration gate or score; do not rescue very old downtrends with a tight branch.",
    },
    {
        "rule_id": "atb.hsb.reversal_not_continuation",
        "source_section": "Buy Setup 3",
        "source_pages": [230, 231, 242],
        "source_paraphrase": "The strongest BUY reading treats the bottom as a reversal of a prior decline, not a continuation setup.",
        "local_buy_interpretation": "Require or reward a prior downtrend into the pattern and demote setups that form after an already extended advance.",
    },
    {
        "rule_id": "atb.hsb.overhead_resistance_filter",
        "source_section": "Buy Setup 2",
        "source_pages": [228, 229, 242],
        "source_paraphrase": "Nearby overhead resistance can stop an otherwise valid breakout.",
        "local_buy_interpretation": "Use resistance distance as an avoid/size-reduction context, especially when target is close to prior supply.",
    },
    {
        "rule_id": "atb.hsb.reclaim_high_setup",
        "source_section": "Buy Setup 1",
        "source_pages": [226, 227],
        "source_paraphrase": "A powerful setup can occur when the breakout pushes back toward or above prior high territory.",
        "local_buy_interpretation": "Score breakouts higher when they have room to reclaim prior high zones rather than immediately colliding with resistance.",
    },
    {
        "rule_id": "atb.hsb.stop_below_head_reference",
        "source_section": "Best Stop Locations",
        "source_pages": [235, 236],
        "source_paraphrase": "Stops placed too close to the breakout are frequently hit; a deeper structural stop below the head is more durable but costs more when wrong.",
        "local_buy_interpretation": "Compare local percentage stops with structural head/shoulder stops; do not use a naive penny-below-breakout stop as the default.",
    },
    {
        "rule_id": "atb.hsb.avoid_abc_correction",
        "source_section": "Configuration Trading",
        "source_pages": [236, 237],
        "source_paraphrase": "A bottom that appears inside the middle of an ABC correction can fail when the next down wave resumes.",
        "local_buy_interpretation": "Add a configuration warning for straight-line prior drops followed by a shallow rebound pattern; wait for stronger confirmation.",
    },
    {
        "rule_id": "atb.hsb.avoid_nothing_to_reverse",
        "source_section": "Configuration Trading",
        "source_pages": [244],
        "source_paraphrase": "Some formations do not have enough prior decline to reverse and therefore make poor bottom candidates.",
        "local_buy_interpretation": "Require meaningful pre-pattern decline or classify the setup as weak/continuation-like.",
    },
    {
        "rule_id": "atb.hsb.avoid_range_bound_breakout",
        "source_section": "Configuration Trading",
        "source_pages": [241],
        "source_paraphrase": "A breakout inside a broad trading range may stall near the range top.",
        "local_buy_interpretation": "If the whole pattern sits inside a horizontal range, require a close above range resistance before promoting the BUY branch.",
    },
    {
        "rule_id": "atb.hsb.measure_rule_half_height_diagnostic",
        "source_section": "Measure Rule",
        "source_pages": [241, 242],
        "source_paraphrase": "The full head-to-neckline target is useful but imperfect; a half-height target is a more attainable diagnostic.",
        "local_buy_interpretation": "Keep 1.0x as source benchmark and add 0.5x as local base/diagnostic target before asking for full measure.",
    },
    {
        "rule_id": "atb.hsb.throwback_limits_gains",
        "source_section": "Closing Position",
        "source_pages": [244],
        "source_paraphrase": "Some ultimate highs occur during the throwback, so apparent upside can be capped quickly after confirmation.",
        "local_buy_interpretation": "Track throwback and target-first-before-adverse; do not score a setup only on eventual MFE.",
    },
    {
        "rule_id": "atb.hsb.busted_pattern_caveat",
        "source_section": "Behavior at a Glance",
        "source_pages": [224, 244],
        "source_paraphrase": "Head-and-shoulders bottoms can bust, so failure behavior is part of the setup contract.",
        "local_buy_interpretation": "Every local rerun must keep failure and fold-stability gates; no promotion from hit-rate alone.",
    },
)


def _read_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _head_shoulders_bottoms_outline(after_buy_pdf: Path) -> dict[str, Any]:
    reader = PdfReader(str(after_buy_pdf))
    outline = list(reader.outline)
    for idx, item in enumerate(outline):
        if isinstance(item, list):
            continue
        title = str(getattr(item, "title", item)).strip()
        if title == "Chapter 9 Head-and-Shoulders Bottoms":
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
                "source_chapter_no": 9,
                "source_title": "Head-and-Shoulders Bottoms",
                "outline_title": title,
                "pdf_page": reader.get_destination_page_number(item) + 1,
                "sections": sections,
            }
    raise RuntimeError("Could not find Chapter 9 Head-and-Shoulders Bottoms in After-the-Buy PDF outline.")


def _load_tradable_evidence(pattern_id: str, tradable_dir: Path) -> dict[str, Any]:
    chapter_dir = tradable_dir / pattern_id
    scorecard = _read_json(chapter_dir / "scorecard.json")
    release = _read_json(chapter_dir / "release_candidate.json")
    selected = _read_json(chapter_dir / "selected_strategy.json")
    return {
        "scorecard_path": str(chapter_dir / "scorecard.json") if scorecard else None,
        "release_candidate_path": str(chapter_dir / "release_candidate.json") if release else None,
        "selected_strategy_path": str(chapter_dir / "selected_strategy.json") if selected else None,
        "score": _float(scorecard.get("score")),
        "classification": scorecard.get("classification"),
        "release_status": release.get("release_status"),
        "selected_strategy_status": selected.get("status"),
        "candidate_count": selected.get("candidate_count"),
        "passing_count": selected.get("passing_count"),
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
            "tradable_scorecard": row.get("tradable_scorecard"),
            "tradable_release_candidate": row.get("tradable_release_candidate"),
        }
    return {"governance_path": str(governance_path), "tradable_score": None, "tradable_status": "not_in_governance_matrix"}


def build_after_buy_head_shoulders_bottoms_rules(
    *,
    after_buy_pdf: Path = DEFAULT_AFTER_BUY_PDF,
    source_map_path: Path = DEFAULT_SOURCE_MAP,
    publication_payloads: Mapping[str, Path] = DEFAULT_PUBLICATION_PAYLOADS,
    tradable_dir: Path = DEFAULT_TRADABLE_DIR,
    governance_path: Path = DEFAULT_GOVERNANCE_MATRIX,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    if not source_map_path.exists():
        source_map = build_after_buy_source_map(after_buy_pdf=after_buy_pdf, out_dir=source_map_path.parent)
    else:
        source_map = _read_json(source_map_path)
    source = _head_shoulders_bottoms_outline(after_buy_pdf)
    section_titles = {str(section.get("title")) for section in source["sections"]}
    missing_sections = [section for section in REQUIRED_SOURCE_SECTIONS if section not in section_titles]

    pattern_rows: list[dict[str, Any]] = []
    failures: list[str] = []
    for pattern_id in ("head_and_shoulders_bottoms", "head_and_shoulders_bottoms_complex"):
        allowed = assert_after_buy_buy_rule_allowed(pattern_id, source_map)
        payload_path = publication_payloads.get(pattern_id)
        payload = _read_json(payload_path) if payload_path else {}
        tradable = _load_tradable_evidence(pattern_id, tradable_dir)
        governance = _load_governance_evidence(pattern_id, governance_path)
        if allowed.get("pattern_buy_role", {}).get("buy_layer_allowed") is not True:
            failures.append(f"{pattern_id}:not_buy_allowed")
        if not payload:
            failures.append(f"{pattern_id}:missing_publication_payload")
        pattern_rows.append(
            {
                "pattern_id": pattern_id,
                "publication_payload": str(payload_path) if payload_path else None,
                "publication_status": payload.get("status"),
                "buy_role": allowed.get("pattern_buy_role"),
                "current_tradable": tradable,
                "governance_tradable": governance,
                "phase_b_action": _phase_b_action(pattern_id, tradable, governance),
            }
        )

    if missing_sections:
        failures.append("missing_required_source_sections")

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
        "local_buy_contract": {
            "scope": "Vietnam long-cash BUY only.",
            "entry": "close-confirmed neckline breakout, with executable entry delay in tradable tests.",
            "target_family": ["0.5x head-to-neckline diagnostic", "1.0x full source benchmark"],
            "stop_family": ["percentage/risk stop", "right-shoulder structural stop", "head structural stop"],
            "must_keep_metrics": [
                "target-first-before-adverse",
                "throwback/retest",
                "failure rate",
                "walk-forward fold stability",
                "sample/trade depth",
            ],
            "avoid_configurations": [
                "ABC correction risk",
                "nothing meaningful to reverse",
                "range-bound breakout below range top",
                "nearby overhead resistance",
            ],
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "head_shoulders_bottoms_after_buy_rules.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_markdown(out_dir / "head_shoulders_bottoms_after_buy_rules.md", result)
    return result


def _phase_b_action(pattern_id: str, tradable: Mapping[str, Any], governance: Mapping[str, Any]) -> str:
    score = governance.get("tradable_score")
    release_status = governance.get("tradable_release_status")
    if score is None:
        score = tradable.get("score")
        release_status = tradable.get("release_status")
    if score is None:
        return "Build first executable long-cash tradable layer from After-the-Buy setup/stop rules."
    score = float(score)
    if score >= 95.0 and release_status == "PASS":
        return "Use as a control; do not over-optimize."
    return "Rerun with source-grounded inbound-trend, resistance, structural-stop, and throwback/failure gates."


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_markdown(path: Path, result: Mapping[str, Any]) -> None:
    lines = [
        "# Head-and-Shoulders Bottoms After-the-Buy Rules",
        "",
        f"- Ruleset: `{result['ruleset_id']}`",
        f"- Status: `{result['status']}`",
        f"- Source: `{result['source_chapter']['source_title']}`",
        f"- Rule count: `{len(result['source_rules'])}`",
        "",
        "## Pattern Status",
        "",
        "| Pattern | BUY scope | Current score | Release | Phase-B action |",
        "|---|---|---:|---|---|",
    ]
    for row in result.get("patterns") or []:
        tradable = row.get("current_tradable") if isinstance(row.get("current_tradable"), Mapping) else {}
        governance = row.get("governance_tradable") if isinstance(row.get("governance_tradable"), Mapping) else {}
        role = row.get("buy_role") if isinstance(row.get("buy_role"), Mapping) else {}
        score_value = governance.get("tradable_score")
        if score_value is None:
            score_value = tradable.get("score")
        score = "" if score_value is None else f"{float(score_value):.2f}"
        release_status = governance.get("tradable_release_status") or tradable.get("release_status") or ""
        lines.append(
            "| {pattern} | {scope} | {score} | {release} | {action} |".format(
                pattern=row.get("pattern_id"),
                scope=role.get("buy_scope"),
                score=score,
                release=release_status,
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
    parser = argparse.ArgumentParser(description="Build After-the-Buy rules for Head-and-Shoulders Bottoms.")
    parser.add_argument("--after-buy-pdf", type=Path, default=DEFAULT_AFTER_BUY_PDF)
    parser.add_argument("--source-map", type=Path, default=DEFAULT_SOURCE_MAP)
    parser.add_argument("--tradable-dir", type=Path, default=DEFAULT_TRADABLE_DIR)
    parser.add_argument("--governance", type=Path, default=DEFAULT_GOVERNANCE_MATRIX)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    result = build_after_buy_head_shoulders_bottoms_rules(
        after_buy_pdf=args.after_buy_pdf,
        source_map_path=args.source_map,
        tradable_dir=args.tradable_dir,
        governance_path=args.governance,
        out_dir=args.out_dir,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "ruleset_id": result["ruleset_id"],
                "out_dir": str(args.out_dir),
                "rule_count": len(result["source_rules"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
