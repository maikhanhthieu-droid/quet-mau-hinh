"""Build After-the-Buy BUY-watchlist rules for Rectangles.

Rectangles are not a universal Vietnam long-cash setup.  The source chapter
contains BUY setups, but it also emphasizes busted behavior, throwbacks, nearby
resistance, and direction-specific use.  This artifact keeps Rectangle Bottoms in
the BUY-watchlist lane and explicitly blocks Rectangle Tops from BUY promotion.
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


RULESET_ID = "after_buy_rectangles_rules_v1"
DEFAULT_SOURCE_MAP = DEFAULT_AFTER_BUY_OUT_DIR / "after_buy_source_map.json"
DEFAULT_OUT_DIR = DEFAULT_AFTER_BUY_OUT_DIR / "rectangles"
DEFAULT_TRADABLE_DIR = Path("artifacts/scanner_v2/chapter_tradable_layer")
DEFAULT_GOVERNANCE_MATRIX = Path("artifacts/final_chapters/governance/chapter_governance_matrix.json")


REQUIRED_SOURCE_SECTIONS = (
    "Behavior at a Glance",
    "Identification",
    "Buy Setup 1",
    "Buy Setup 2",
    "Buy Setup 3",
    "Sell Setup",
    "Best Stop Locations",
    "Configuration Trading",
    "Measure Rule",
    "Trading",
    "Closing Position",
)


SOURCE_RULES: tuple[dict[str, Any], ...] = (
    {
        "rule_id": "atb.rect.direction_specific_breakout",
        "source_section": "Behavior at a Glance",
        "source_pages": [308],
        "source_paraphrase": "Rectangles can break in either direction; upward breakouts are a different setup from downward breakouts.",
        "local_buy_interpretation": "Vietnam BUY scoring must isolate up-breakout Rectangle Bottoms; aggregate up/down rows are not BUY evidence.",
    },
    {
        "rule_id": "atb.rect.throwback_common",
        "source_section": "Behavior at a Glance",
        "source_pages": [308],
        "source_paraphrase": "Upward rectangle breakouts often throw back to the breakout price within about a month.",
        "local_buy_interpretation": "Retest/throwback handling should be part of the entry layer, not an afterthought.",
    },
    {
        "rule_id": "atb.rect.busted_up_breakout_risk",
        "source_section": "Identification",
        "source_pages": [310, 322],
        "source_paraphrase": "A material share of upward breakouts bust and can fall sharply after failing.",
        "local_buy_interpretation": "Keep busted-pattern and failure gates; do not promote a rectangle only because initial breakout direction is up.",
    },
    {
        "rule_id": "atb.rect.busted_down_breakout_buy_setup",
        "source_section": "Buy Setup 1",
        "source_pages": [313],
        "source_paraphrase": "One bullish setup is a failed downward breakout that reverses and closes above the rectangle top.",
        "local_buy_interpretation": "A failed downside breakout can become a BUY-watchlist branch only after reclaiming the rectangle top.",
    },
    {
        "rule_id": "atb.rect.short_inbound_trend_preferred",
        "source_section": "Buy Setup 2",
        "source_pages": [315, 317, 319],
        "source_paraphrase": "Short inbound trends before the rectangle tend to be better than long inbound trends.",
        "local_buy_interpretation": "Use inbound-duration scoring; avoid treating stale long ranges as equivalent to fresh consolidation.",
    },
    {
        "rule_id": "atb.rect.overhead_resistance_filter",
        "source_section": "Buy Setup 3",
        "source_pages": [317, 319, 333, 339],
        "source_paraphrase": "Nearby overhead resistance can stop an upward breakout and reduce performance.",
        "local_buy_interpretation": "Require room to target or downgrade setups that break into obvious resistance/range top.",
    },
    {
        "rule_id": "atb.rect.buy_order_above_top",
        "source_section": "Buy Setup 3",
        "source_pages": [319],
        "source_paraphrase": "The chapter frames entry as buying above the top of the rectangle after confirmation.",
        "local_buy_interpretation": "Executable BUY tests should use confirmed top breakout, not midpoint or inside-range entries.",
    },
    {
        "rule_id": "atb.rect.stop_below_rectangle",
        "source_section": "Best Stop Locations",
        "source_pages": [322, 323],
        "source_paraphrase": "For upward breakouts, a stop below the bottom of the rectangle is structurally safer than a stop inside the box.",
        "local_buy_interpretation": "Compare local percentage stops with a structural stop below support; tight in-box stops should not be default.",
    },
    {
        "rule_id": "atb.rect.measure_rule_half_height_diagnostic",
        "source_section": "Measure Rule",
        "source_pages": [332, 333],
        "source_paraphrase": "Full-height targets are useful but half-height targets are easier to reach, especially for upward breakouts.",
        "local_buy_interpretation": "Use 0.5x height as base/diagnostic and keep 1.0x as source benchmark.",
    },
    {
        "rule_id": "atb.rect_rectangle_top_not_buy",
        "source_section": "Sell Setup",
        "source_pages": [319, 321],
        "source_paraphrase": "The source chapter separates sell/short material from bullish rectangle setups.",
        "local_buy_interpretation": "Rectangle Tops are avoid/exit evidence in Vietnam cash equities, not a BUY-layer candidate.",
    },
    {
        "rule_id": "atb.rect.watchlist_not_direct_signal",
        "source_section": "Closing Position",
        "source_pages": [339],
        "source_paraphrase": "The trade example weighs throwback, resistance, and actual post-breakout behavior rather than treating the box as a standalone signal.",
        "local_buy_interpretation": "Rectangle Bottoms remain BUY-watchlist until up-breakout branch passes fold/cost/capacity gates.",
    },
)


def _read_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _rectangles_outline(after_buy_pdf: Path) -> dict[str, Any]:
    reader = PdfReader(str(after_buy_pdf))
    outline = list(reader.outline)
    for idx, item in enumerate(outline):
        if isinstance(item, list):
            continue
        title = str(getattr(item, "title", item)).strip()
        if title == "Chapter 15 Rectangles":
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
                "source_chapter_no": 15,
                "source_title": "Rectangles",
                "outline_title": title,
                "pdf_page": reader.get_destination_page_number(item) + 1,
                "sections": sections,
            }
    raise RuntimeError("Could not find Chapter 15 Rectangles in After-the-Buy PDF outline.")


def _load_tradable_evidence(pattern_id: str, tradable_dir: Path) -> dict[str, Any]:
    chapter_dir = tradable_dir / pattern_id
    scorecard = _read_json(chapter_dir / "scorecard.json")
    release = _read_json(chapter_dir / "release_candidate.json")
    selected = _read_json(chapter_dir / "selected_strategy.json")
    source_scope = selected.get("source_scope") if isinstance(selected.get("source_scope"), Mapping) else {}
    return {
        "score": _float(scorecard.get("score")),
        "classification": scorecard.get("classification"),
        "release_status": release.get("release_status"),
        "selected_strategy_status": selected.get("status"),
        "selected_strategy_id": selected.get("selected_strategy_id"),
        "scope": source_scope.get("scope"),
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


def build_after_buy_rectangles_rules(
    *,
    after_buy_pdf: Path = DEFAULT_AFTER_BUY_PDF,
    source_map_path: Path = DEFAULT_SOURCE_MAP,
    tradable_dir: Path = DEFAULT_TRADABLE_DIR,
    governance_path: Path = DEFAULT_GOVERNANCE_MATRIX,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    if not source_map_path.exists():
        source_map = build_after_buy_source_map(after_buy_pdf=after_buy_pdf, out_dir=source_map_path.parent)
    else:
        source_map = _read_json(source_map_path)
    source = _rectangles_outline(after_buy_pdf)
    section_titles = {str(section.get("title")) for section in source["sections"]}
    missing_sections = [section for section in REQUIRED_SOURCE_SECTIONS if section not in section_titles]

    failures: list[str] = []
    patterns: list[dict[str, Any]] = []
    for pattern_id in ("rectangle_bottoms", "rectangle_tops"):
        tradable = _load_tradable_evidence(pattern_id, tradable_dir)
        governance = _load_governance_evidence(pattern_id, governance_path)
        if pattern_id == "rectangle_bottoms":
            allowed = assert_after_buy_buy_rule_allowed(pattern_id, source_map)
            if allowed.get("pattern_buy_role", {}).get("buy_layer_allowed") is not True:
                failures.append(f"{pattern_id}:not_buy_allowed")
        else:
            try:
                allowed = assert_after_buy_buy_rule_allowed(pattern_id, source_map)
                failures.append(f"{pattern_id}:unexpected_buy_allowed")
            except ValueError as exc:
                allowed = {"blocked_reason": str(exc), "pattern_buy_role": {"buy_layer_allowed": False, "buy_scope": "top_structure_exit_warning"}}
        patterns.append(
            {
                "pattern_id": pattern_id,
                "buy_role": allowed.get("pattern_buy_role"),
                "current_tradable": tradable,
                "governance_tradable": governance,
                "phase_b_action": _phase_b_action(pattern_id, governance),
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
        "patterns": patterns,
        "local_buy_contract": {
            "scope": "Rectangle Bottoms are BUY-watchlist on confirmed up-breakout/reclaim only; Rectangle Tops are avoid/exit.",
            "entry": "close above top of rectangle or reclaim after failed downside breakout; no inside-box entry.",
            "target_family": ["0.5x height diagnostic", "1.0x full source benchmark"],
            "stop_family": ["structural stop below rectangle support", "risk stop with capacity/cost stress"],
            "must_keep_metrics": [
                "up-breakout branch only",
                "throwback/retest behavior",
                "busted breakout rate",
                "overhead resistance",
                "walk-forward fold stability",
            ],
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "rectangles_after_buy_rules.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_markdown(out_dir / "rectangles_after_buy_rules.md", result)
    return result


def _phase_b_action(pattern_id: str, governance: Mapping[str, Any]) -> str:
    if pattern_id == "rectangle_tops":
        return "Keep as avoid/exit; do not promote to Vietnam long-cash BUY."
    score = governance.get("tradable_score")
    if score is not None and float(score) >= 95.0 and governance.get("tradable_release_status") == "PASS":
        return "Use as control; do not over-optimize."
    return "Rerun only on confirmed up-breakout/reclaim branch with throwback, resistance, and structural-stop gates."


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_markdown(path: Path, result: Mapping[str, Any]) -> None:
    lines = [
        "# Rectangles After-the-Buy Rules",
        "",
        f"- Ruleset: `{result['ruleset_id']}`",
        f"- Status: `{result['status']}`",
        f"- Source: `{result['source_chapter']['source_title']}`",
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
    parser = argparse.ArgumentParser(description="Build After-the-Buy rules for Rectangles.")
    parser.add_argument("--after-buy-pdf", type=Path, default=DEFAULT_AFTER_BUY_PDF)
    parser.add_argument("--source-map", type=Path, default=DEFAULT_SOURCE_MAP)
    parser.add_argument("--tradable-dir", type=Path, default=DEFAULT_TRADABLE_DIR)
    parser.add_argument("--governance", type=Path, default=DEFAULT_GOVERNANCE_MATRIX)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    result = build_after_buy_rectangles_rules(
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
