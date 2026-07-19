"""Build source-grounding notes for the Bear Flag chapter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping


DEFAULT_CORE = Path("scanner/v2/core_patterns.json")
DEFAULT_PDF = Path("references/encyclopedia-of-chart-patterns-2nbsped-9786468600-3175723993-9780471668268-0471668265_compress.pdf")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bear_flags_source_grounding")


def _read_json(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _extract_pdf_page_summary(pdf_path: Path, pdf_pages_1_based: Iterable[int]) -> Dict[str, Any]:
    summaries: Dict[str, Any] = {}
    try:
        from pypdf import PdfReader
    except Exception as exc:  # pragma: no cover
        return {"status": "pypdf_unavailable", "error": str(exc), "pages": summaries}
    if not pdf_path.exists():
        return {"status": "source_pdf_missing", "error": str(pdf_path), "pages": summaries}
    reader = PdfReader(str(pdf_path))
    for page_number in pdf_pages_1_based:
        page_index = int(page_number) - 1
        if page_index < 0 or page_index >= len(reader.pages):
            continue
        text = (reader.pages[page_index].extract_text() or "").replace("\n", " ")
        lowered = text.lower()
        summaries[str(page_number)] = {
            "extracted_chars": len(text),
            "detected_terms": {
                "flags": "flags" in lowered,
                "breakout": "breakout" in lowered,
                "measure_rule": "measure rule" in lowered,
                "pullback": "pullback" in lowered,
                "downward": "downward" in lowered or "decline" in lowered,
                "three_weeks": "3 weeks" in lowered or "three-week" in lowered,
            },
        }
    return {"status": "extracted", "page_count": len(reader.pages), "pages": summaries}


def _source_rules(pattern: Mapping[str, Any]) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    for rule in pattern.get("rules") or []:
        if not isinstance(rule, Mapping):
            continue
        rows.append(
            {
                "rule_id": rule.get("rule_id"),
                "rule_type": rule.get("rule_type"),
                "book_chapter": rule.get("book_chapter"),
                "source_page": rule.get("source_page"),
                "source_pdf_page": rule.get("source_pdf_page"),
                "source_section": rule.get("source_section"),
                "short_excerpt": rule.get("evidence_excerpt"),
                "implementation_mapping": rule.get("interpreted_rule"),
                "scanner_threshold": rule.get("numeric_threshold"),
                "confidence": rule.get("confidence"),
                "notes": rule.get("notes_when_ambiguous"),
            }
        )
    return rows


def build_source_notes(core_path: Path = DEFAULT_CORE, pdf_path: Path = DEFAULT_PDF) -> Dict[str, Any]:
    core = _read_json(core_path)
    patterns = core.get("patterns") if isinstance(core.get("patterns"), Mapping) else {}
    pattern = patterns.get("bear_flags") if isinstance(patterns.get("bear_flags"), Mapping) else {}
    chapters = pattern.get("book_chapters") if isinstance(pattern.get("book_chapters"), list) else []
    source_pdf_pages = sorted(
        {
            int(rule.get("source_pdf_page"))
            for rule in pattern.get("rules", [])
            if isinstance(rule, Mapping) and str(rule.get("source_pdf_page", "")).isdigit()
        }
    )
    if chapters and isinstance(chapters[0], Mapping):
        start = int(chapters[0].get("source_pdf_page_start") or 0)
        source_pdf_pages.extend([start, start + 1])
    source_pdf_pages = sorted(set(page for page in source_pdf_pages if page > 0))
    return {
        "source_grounding_id": "bear_flag_bulkowski_source_grounding_v1",
        "status": "PASS",
        "local_source": {
            "core_patterns_path": str(core_path),
            "pdf_path": str(pdf_path),
            "source_document": core.get("source_document"),
            "pattern_key": pattern.get("pattern_key"),
            "display_name": pattern.get("display_name"),
            "book_chapters": chapters,
            "pdf_pages_checked": source_pdf_pages,
        },
        "pdf_text_audit": _extract_pdf_page_summary(pdf_path, source_pdf_pages),
        "source_rules": _source_rules(pattern),
        "bulkowski_book_2e_stats": {
            "source": "Local Encyclopedia of Chart Patterns Second Edition PDF, Flags chapter results snapshot",
            "downward_breakouts": {
                "source_pdf_page": 359,
                "break_even_failure_rate_bull_bear_pct": [2, 0],
                "average_decline_bull_bear_pct": [16, 25],
                "pullbacks_bull_bear_pct": [46, 44],
                "percentage_meeting_price_target_bull_bear_pct": [47, 54],
            },
            "upward_breakouts": {
                "source_pdf_page": 358,
                "break_even_failure_rate_bull_bear_pct": [4, 3],
                "average_rise_bull_bear_pct": [23, 17],
                "throwbacks_bull_bear_pct": [43, 53],
                "percentage_meeting_price_target_bull_bear_pct": [64, 55],
                "note": "Included only for family context; Bear Flag chapter uses downward-breakout interpretation.",
            },
        },
        "thepatternsite_2020_stats": {
            "source": "Official ThePatternSite Flags page, statistics updated 2020-08-27",
            "url": "https://thepatternsite.com/flags.html",
            "break_even_failure_rate_up_down_pct": [44, 45],
            "average_rise_decline_up_down_pct": [9, 8],
            "percentage_meeting_price_target_up_down_pct": [46, 46],
            "measurement_note": "The page states flag performance is based on short-term price swing, not ultimate high/low as in most chart patterns.",
        },
        "thepatternsite_measure_rule": {
            "source": "Official ThePatternSite Measure Rule page, statistics updated 2020-09-14",
            "url": "https://thepatternsite.com/measure.html",
            "flags_down_breakout_rule": "Flag high - ((Flagpole height) * 46%)",
            "flags_up_breakout_rule": "Flag low + ((Flagpole height) * 46%)",
            "method_note": "The page recommends multiplying pattern height by empirical percentage meeting price target instead of blindly using full height.",
        },
        "alignment_constraints": {
            "strong_or_quick_prior_decline_required": True,
            "short_flag_max_about_three_weeks": True,
            "parallel_or_near_parallel_trendlines": True,
            "close_outside_flag_trendline_confirms_breakout": True,
            "base_target_multiple": 0.46,
            "legacy_target_multiple": 1.0,
            "localization_boundary": "Bear Flag is a defensive/informational cash-equity reference unless execution research proves short-side implementation.",
        },
        "editorial_guardrail": "Bear Flag chapter must separate downside information value from short-sale implementation claims.",
    }


def write_source_notes(notes: Mapping[str, Any], out_dir: Path = DEFAULT_OUT_DIR) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "bear_flag_source_notes.json"
    md_path = out_dir / "bear_flag_source_notes.md"
    json_path.write_text(json.dumps(notes, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    lines = [
        "# Bear Flag Source Notes",
        "",
        f"- Status: `{notes.get('status')}`",
        f"- Source grounding ID: `{notes.get('source_grounding_id')}`",
        "",
        "## Original Rule Anchors",
        "",
    ]
    for rule in notes.get("source_rules") or []:
        if not isinstance(rule, Mapping):
            continue
        lines.append(
            f"- `{rule.get('rule_id')}`: {rule.get('short_excerpt')} -> {rule.get('implementation_mapping')} "
            f"(source page {rule.get('source_page')}, PDF page {rule.get('source_pdf_page')})"
        )
    lines.extend(
        [
            "",
            "## Official Web Anchors",
            "",
            f"- Flags: {notes['thepatternsite_2020_stats']['url']}",
            f"- Measure rule: {notes['thepatternsite_measure_rule']['url']}",
            "",
            "## Editorial Guardrail",
            "",
            str(notes.get("editorial_guardrail")),
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Bear Flag source-grounding notes.")
    parser.add_argument("--core", default=str(DEFAULT_CORE))
    parser.add_argument("--pdf", default=str(DEFAULT_PDF))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    paths = write_source_notes(build_source_notes(Path(args.core), Path(args.pdf)), Path(args.out_dir))
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
