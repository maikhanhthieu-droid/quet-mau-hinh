"""Build After-the-Buy BUY/watchlist rules for Triangle branches."""

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


RULESET_ID = "after_buy_triangles_rules_v1"
DEFAULT_SOURCE_MAP = DEFAULT_AFTER_BUY_OUT_DIR / "after_buy_source_map.json"
DEFAULT_OUT_DIR = DEFAULT_AFTER_BUY_OUT_DIR / "triangles"
DEFAULT_GOVERNANCE_MATRIX = Path("artifacts/final_chapters/governance/chapter_governance_matrix.json")

SOURCE_NOTES = {
    "triangles_ascending": Path("artifacts/scanner_v2/triangle_family_public_chapters/ascending_triangle/ascending_triangle_source_notes.json"),
    "triangles_descending": Path("artifacts/scanner_v2/triangle_family_public_chapters/descending_triangle/descending_triangle_source_notes.json"),
    "triangles_symmetrical": Path("artifacts/scanner_v2/triangle_family_public_chapters/symmetrical_triangle/symmetrical_triangle_source_notes.json"),
}

TRADABLE_DIRS = {
    "triangles_ascending": Path("artifacts/scanner_v2/chapter_tradable_layer/triangles_ascending"),
    "triangles_descending": Path("artifacts/scanner_v2/chapter_tradable_layer/triangles_descending"),
    "triangles_symmetrical": Path("artifacts/scanner_v2/chapter_branch_optimization/triangles_symmetrical"),
}

SOURCE_CHAPTERS = {
    21: "Triangle Apex and Turning Points",
    22: "Triangles, Ascending",
    23: "Triangles, Descending",
    24: "Triangles, Symmetrical",
}

REQUIRED_SOURCE_SECTIONS = {
    21: ("Behavior at a Glance", "Identification", "The Numbers", "Trading", "Closing Position"),
    22: ("Behavior at a Glance", "Identification", "Buy Setup 1", "Best Stop Locations", "Measure Rule", "Trading", "Closing Position"),
    23: ("Behavior at a Glance", "Identification", "Buy Setup 1", "Sell Setup", "Best Stop Locations", "Measure Rule", "Trading", "Closing Position"),
    24: ("Behavior at a Glance", "Identification", "Buy Setup 1", "Sell Setup", "Best Stop Locations", "Measure Rule", "Trading", "Closing Position"),
}

SOURCE_RULES: tuple[dict[str, Any], ...] = (
    {
        "rule_id": "atb.tri.apex_timing_context",
        "source_origin": "after_buy_chapter_21",
        "source_section": "Triangle Apex and Turning Points",
        "source_paraphrase": "The position of a breakout relative to the triangle apex is a timing diagnostic.",
        "local_buy_interpretation": "Keep apex_progress and bars_to_apex as diagnostics; do not rank triangle branches without them.",
    },
    {
        "rule_id": "atb.tri.ascending_buy_core",
        "source_origin": "after_buy_chapter_22",
        "source_section": "Buy Setup / Trading",
        "source_paraphrase": "Ascending triangles have a direct bullish use when price confirms above resistance.",
        "local_buy_interpretation": "Ascending Triangle is the only Triangle Family member treated as full BUY-core in this layer.",
    },
    {
        "rule_id": "atb.tri.descending_up_branch_only",
        "source_origin": "after_buy_chapter_23",
        "source_section": "Buy Setup / Sell Setup",
        "source_paraphrase": "Descending triangles include both buy and sell material; direction matters.",
        "local_buy_interpretation": "Only the up-breakout/reversal branch can enter Vietnam BUY testing; breakdown rows are avoid/exit evidence.",
    },
    {
        "rule_id": "atb.tri.symmetrical_direction_split",
        "source_origin": "after_buy_chapter_24",
        "source_section": "Buy Setup / Sell Setup",
        "source_paraphrase": "Symmetrical triangles can resolve upward or downward, so the branch must be split.",
        "local_buy_interpretation": "Only upward branch can be BUY-watchlist; aggregate direction is not BUY evidence.",
    },
    {
        "rule_id": "atb.tri.retest_stop_not_headline_hit_rate",
        "source_origin": "after_buy_chapters_22_24",
        "source_section": "Best Stop Locations / Trading",
        "source_paraphrase": "Retests, throwbacks/pullbacks, and stop placement materially change the quality of a triangle breakout.",
        "local_buy_interpretation": "Use target-first, return-to-breakout, stop, and fold-stability gates; do not promote on hit-rate alone.",
    },
)


def _read_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _chapter_outline(after_buy_pdf: Path, chapter_no: int, title_suffix: str) -> dict[str, Any]:
    reader = PdfReader(str(after_buy_pdf))
    outline = list(reader.outline)
    wanted = f"Chapter {chapter_no} {title_suffix}"
    for idx, item in enumerate(outline):
        if isinstance(item, list):
            continue
        title = str(getattr(item, "title", item)).strip()
        if title == wanted:
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
                "source_chapter_no": chapter_no,
                "source_title": title_suffix,
                "outline_title": title,
                "pdf_page": reader.get_destination_page_number(item) + 1,
                "sections": sections,
            }
    raise RuntimeError(f"Could not find {wanted} in After-the-Buy PDF outline.")


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
    summary = _read_json(path / "branch_optimization_summary.json")
    metrics = selected.get("selected_metrics") if isinstance(selected.get("selected_metrics"), Mapping) else {}
    return {
        "path": str(path),
        "available": bool(scorecard or selected or release or summary),
        "score": _float(scorecard.get("score") or summary.get("score")),
        "classification": scorecard.get("classification") or summary.get("classification"),
        "release_status": release.get("release_status") or summary.get("release_status"),
        "promotion_blockers": scorecard.get("promotion_blockers") or summary.get("promotion_blockers"),
        "selected_strategy_id": selected.get("selected_strategy_id") or summary.get("selected_strategy_id"),
        "trades": metrics.get("trades"),
        "validation_total_return_pct": metrics.get("validation_total_return_pct"),
        "holdout_total_return_pct": metrics.get("holdout_total_return_pct"),
        "target_multiple": metrics.get("target_multiple"),
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


def build_after_buy_triangles_rules(
    *,
    after_buy_pdf: Path = DEFAULT_AFTER_BUY_PDF,
    source_map_path: Path = DEFAULT_SOURCE_MAP,
    governance_path: Path = DEFAULT_GOVERNANCE_MATRIX,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    if not source_map_path.exists():
        source_map = build_after_buy_source_map(after_buy_pdf=after_buy_pdf, out_dir=source_map_path.parent)
    else:
        source_map = _read_json(source_map_path)

    outlines = {chapter_no: _chapter_outline(after_buy_pdf, chapter_no, title) for chapter_no, title in SOURCE_CHAPTERS.items()}
    failures: list[str] = []
    for chapter_no, required in REQUIRED_SOURCE_SECTIONS.items():
        section_titles = {str(section.get("title")) for section in outlines[chapter_no]["sections"]}
        missing = [section for section in required if section not in section_titles]
        if missing:
            failures.append(f"chapter_{chapter_no}:missing_sections:{','.join(missing)}")

    patterns: list[dict[str, Any]] = []
    for pattern_id in ("triangles_ascending", "triangles_descending", "triangles_symmetrical"):
        allowed = assert_after_buy_buy_rule_allowed(pattern_id, source_map)
        source_notes = _source_notes_summary(SOURCE_NOTES[pattern_id])
        tradable = _load_tradable(TRADABLE_DIRS[pattern_id])
        governance = _load_governance(pattern_id, governance_path)
        if allowed.get("pattern_buy_role", {}).get("buy_layer_allowed") is not True:
            failures.append(f"{pattern_id}:not_buy_allowed")
        if not source_notes["available"] or source_notes.get("source_review_status") != "PASS":
            failures.append(f"{pattern_id}:missing_or_failed_source_notes")
        patterns.append(
            {
                "pattern_id": pattern_id,
                "source_chapter_no": _pattern_source_chapter(pattern_id),
                "buy_role": allowed.get("pattern_buy_role"),
                "source_notes": source_notes,
                "current_tradable": tradable,
                "governance_tradable": governance,
                "phase_c_action": _phase_c_action(pattern_id, allowed.get("pattern_buy_role") or {}, governance),
            }
        )

    result = {
        "ruleset_id": RULESET_ID,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "source_grounding_id": source_map.get("source_grounding_id"),
        "buy_first_policy_id": source_map.get("buy_first_policy_id"),
        "source_chapters": outlines,
        "required_sections": {str(key): list(value) for key, value in REQUIRED_SOURCE_SECTIONS.items()},
        "source_rules": list(SOURCE_RULES),
        "patterns": patterns,
        "local_buy_contract": {
            "scope": "Triangle BUY layer is branch-aware: Ascending full up-breakout, Descending/Symmetrical upward branch only.",
            "entry": "close-confirmed breakout in the allowed BUY direction; no aggregate up/down promotion.",
            "target_family": ["0.5x/0.75x local diagnostics", "1.0x source full-height benchmark"],
            "stop_family": ["structural boundary/retest-aware stop", "risk stop with fold/cost/capacity checks"],
            "must_keep_metrics": [
                "apex progress",
                "return-to-breakout/throwback-pullback",
                "target-first-before-adverse",
                "walk-forward fold returns",
                "branch-specific sample depth",
            ],
            "forbidden_promotions": [
                "Do not use descending breakdowns as Vietnam BUY setups.",
                "Do not use symmetrical aggregate direction as BUY evidence.",
                "Do not promote any triangle while walk-forward fold blockers remain.",
            ],
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "triangles_after_buy_rules.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_markdown(out_dir / "triangles_after_buy_rules.md", result)
    return result


def _pattern_source_chapter(pattern_id: str) -> int:
    return {
        "triangles_ascending": 22,
        "triangles_descending": 23,
        "triangles_symmetrical": 24,
    }[pattern_id]


def _phase_c_action(pattern_id: str, buy_role: Mapping[str, Any], governance: Mapping[str, Any]) -> str:
    scope = str(buy_role.get("buy_scope") or "")
    blockers = str(governance.get("tradable_blockers") or "")
    score = _float(governance.get("tradable_score"))
    if scope == "up_breakout_branch_only":
        prefix = "Keep only upward breakout branch for BUY; breakdown rows are defensive/avoid."
    elif pattern_id == "triangles_ascending":
        prefix = "Keep as direct BUY-core candidate with apex/retest/stop diagnostics."
    else:
        prefix = "Keep branch-aware watchlist only."
    if score is not None and score < 95 and "walk_forward_has_negative_fold" in blockers:
        return f"{prefix} Current best evidence remains blocked below 95 by walk-forward instability."
    return prefix


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_markdown(path: Path, result: Mapping[str, Any]) -> None:
    lines = [
        "# Triangles After-the-Buy Rules",
        "",
        f"- Ruleset ID: `{result['ruleset_id']}`",
        f"- Status: `{result['status']}`",
        f"- Scope: {result['local_buy_contract']['scope']}",
        "",
        "## Pattern Decisions",
        "",
        "| Pattern | BUY scope | Governance score | Action |",
        "|---|---|---:|---|",
    ]
    for row in result.get("patterns") or []:
        if not isinstance(row, Mapping):
            continue
        role = row.get("buy_role") if isinstance(row.get("buy_role"), Mapping) else {}
        gov = row.get("governance_tradable") if isinstance(row.get("governance_tradable"), Mapping) else {}
        lines.append(f"| `{row.get('pattern_id')}` | `{role.get('buy_scope')}` | {gov.get('tradable_score')} | {row.get('phase_c_action')} |")
    lines.extend(
        [
            "",
            "## Source-Grounded Rules",
            "",
            "| Rule | Origin | Local BUY interpretation |",
            "|---|---|---|",
        ]
    )
    for rule in result.get("source_rules") or []:
        if isinstance(rule, Mapping):
            lines.append(
                f"| `{rule.get('rule_id')}` | {rule.get('source_origin')} / {rule.get('source_section')} | {rule.get('local_buy_interpretation')} |"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build After-the-Buy Triangle branch BUY rules.")
    parser.add_argument("--after-buy-pdf", type=Path, default=DEFAULT_AFTER_BUY_PDF)
    parser.add_argument("--source-map", type=Path, default=DEFAULT_SOURCE_MAP)
    parser.add_argument("--governance", type=Path, default=DEFAULT_GOVERNANCE_MATRIX)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    result = build_after_buy_triangles_rules(
        after_buy_pdf=args.after_buy_pdf,
        source_map_path=args.source_map,
        governance_path=args.governance,
        out_dir=args.out_dir,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "pattern_count": len(result["patterns"]),
                "buy_scopes": {row["pattern_id"]: row["buy_role"]["buy_scope"] for row in result["patterns"]},
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
