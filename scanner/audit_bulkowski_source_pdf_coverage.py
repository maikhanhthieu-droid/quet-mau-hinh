from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
CHART_PDF = ROOT / "references" / "encyclopedia-of-chart-patterns-2nbsped-9786468600-3175723993-9780471668268-0471668265_compress.pdf"
CANDLE_PDF = ROOT / "references" / "Thomas N. Bulkowski - Encyclopedia of Candlestick.pdf"
FINAL_MANIFEST = ROOT / "artifacts" / "final_chapters" / "final_chapters_manifest.json"
OUT_DIR = ROOT / "artifacts" / "final_chapters" / "governance"


CHART_COVERAGE: dict[int, dict[str, Any]] = {
    1: {"pattern_ids": ["broadening_bottoms"]},
    2: {"pattern_ids": ["broadening_formations_right_angled_ascending"]},
    3: {"pattern_ids": ["broadening_formations_right_angled_descending"]},
    4: {"pattern_ids": ["broadening_tops"]},
    5: {"pattern_ids": ["broadening_wedges_ascending"]},
    6: {"pattern_ids": ["broadening_wedges_descending"]},
    7: {"pattern_ids": ["bump_and_run_reversal_bottoms"]},
    8: {"pattern_ids": ["bump_and_run_reversal_tops"]},
    9: {"pattern_ids": ["cup_with_handle"]},
    10: {"pattern_ids": ["cup_with_handle_inverted"]},
    11: {"pattern_ids": ["diamond_bottoms"]},
    12: {"pattern_ids": ["diamond_tops"]},
    13: {"pattern_ids": ["double_bottoms_adam_adam"]},
    14: {"pattern_ids": ["double_bottoms_adam_eve"]},
    15: {"pattern_ids": ["double_bottoms_eve_adam"]},
    16: {"pattern_ids": ["double_bottoms_eve_eve"]},
    17: {"pattern_ids": ["double_tops_adam_adam"]},
    18: {"pattern_ids": ["double_tops_adam_eve"]},
    19: {"pattern_ids": ["double_tops_eve_adam"]},
    20: {"pattern_ids": ["double_tops_eve_eve"]},
    21: {"pattern_ids": ["bull_flags", "bear_flags"], "coverage_note": "Split into bullish and bearish flag chapters."},
    22: {"pattern_ids": ["high_tight_flags"]},
    23: {
        "pattern_ids": ["area_gaps", "breakaway_gaps", "continuation_gaps", "exhaustion_gaps"],
        "coverage_note": "Bulkowski's single Gaps chapter is split by gap type.",
    },
    24: {"pattern_ids": ["head_and_shoulders_bottoms"]},
    25: {"pattern_ids": ["head_and_shoulders_bottoms_complex"]},
    26: {"pattern_ids": ["head_and_shoulders_tops"]},
    27: {"pattern_ids": ["head_and_shoulders_tops_complex"]},
    28: {"pattern_ids": ["horn_bottoms"]},
    29: {"pattern_ids": ["horn_tops"]},
    30: {"pattern_ids": ["island_reversals"]},
    31: {"pattern_ids": ["islands_long"]},
    32: {"pattern_ids": ["measured_move_down"]},
    33: {"pattern_ids": ["measured_move_up"]},
    34: {"pattern_ids": ["bull_pennants", "bear_pennants"], "coverage_note": "Split into bullish and bearish pennant chapters."},
    35: {"pattern_ids": ["pipe_bottoms"]},
    36: {"pattern_ids": ["pipe_tops"]},
    37: {"pattern_ids": ["rectangle_bottoms"]},
    38: {"pattern_ids": ["rectangle_tops"]},
    39: {"pattern_ids": ["rounding_bottoms"]},
    40: {"pattern_ids": ["rounding_tops"]},
    41: {"pattern_ids": ["scallops_ascending"]},
    42: {"pattern_ids": ["scallops_ascending_inverted"]},
    43: {"pattern_ids": ["scallops_descending"]},
    44: {"pattern_ids": ["scallops_descending_inverted"]},
    45: {"pattern_ids": ["three_falling_peaks"]},
    46: {"pattern_ids": ["three_rising_valleys"]},
    47: {"pattern_ids": ["triangles_ascending"]},
    48: {"pattern_ids": ["triangles_descending"]},
    49: {"pattern_ids": ["triangles_symmetrical"]},
    50: {"pattern_ids": ["triple_bottoms"]},
    51: {"pattern_ids": ["triple_tops"]},
    52: {"pattern_ids": ["wedges_falling"]},
    53: {"pattern_ids": ["wedges_rising"]},
    54: {"pattern_ids": ["dead_cat_bounce"]},
    55: {"pattern_ids": ["dead_cat_bounce_inverted"]},
    56: {"missing_reason": "requires earnings-surprise event data"},
    57: {"missing_reason": "requires earnings-surprise event data"},
    58: {"missing_reason": "requires FDA drug approval event data"},
    59: {"missing_reason": "requires earnings-date flag event data"},
    60: {"missing_reason": "requires same-store-sales event data"},
    61: {"missing_reason": "requires same-store-sales event data"},
    62: {"missing_reason": "requires stock downgrade event data"},
    63: {"missing_reason": "requires stock upgrade event data"},
}

CANDLE_AUXILIARY_COVERAGE = {
    39: {"pattern_ids": ["falling_three_methods"]},
    73: {"pattern_ids": ["rising_three_methods"]},
    85: {"pattern_ids": ["inside_day"], "coverage_note": "Covered as a simplified inside-day family rather than exact Three Inside Down candlestick chapter."},
    86: {"pattern_ids": ["inside_day"], "coverage_note": "Covered as a simplified inside-day family rather than exact Three Inside Up candlestick chapter."},
}


def _extract_chapters(pdf_path: Path) -> list[dict[str, Any]]:
    reader = PdfReader(str(pdf_path))
    rows: list[dict[str, Any]] = []

    def walk(items: list[Any]) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item)
                continue
            title = getattr(item, "title", str(item))
            match = re.match(r"^Chapter\s+(\d+):\s+(.+)$", title)
            if not match:
                continue
            try:
                page = reader.get_destination_page_number(item) + 1
            except Exception:
                page = None
            rows.append({"chapter": int(match.group(1)), "title": match.group(2), "page": page})

    walk(reader.outline)
    return sorted(rows, key=lambda row: row["chapter"])


def main() -> None:
    manifest = json.loads(FINAL_MANIFEST.read_text())
    final_chapters = manifest["chapters"]
    final_by_pattern = {row["pattern_id"]: row for row in final_chapters}

    chart_rows = []
    for row in _extract_chapters(CHART_PDF):
        chapter = int(row["chapter"])
        coverage = CHART_COVERAGE.get(chapter, {})
        pattern_ids = list(coverage.get("pattern_ids") or [])
        present = [pid for pid in pattern_ids if pid in final_by_pattern]
        missing = [pid for pid in pattern_ids if pid not in final_by_pattern]
        if present and not missing:
            status = "covered"
        elif coverage.get("missing_reason"):
            status = "not_covered_event_data_required"
        elif missing:
            status = "mapping_missing_from_final_manifest"
        else:
            status = "unmapped"
        chart_rows.append(
            row
            | {
                "source": "Encyclopedia of Chart Patterns",
                "status": status,
                "pattern_ids": pattern_ids,
                "present_pattern_ids": present,
                "missing_pattern_ids": missing,
                "coverage_note": coverage.get("coverage_note"),
                "missing_reason": coverage.get("missing_reason"),
            }
        )

    candle_rows = []
    for row in _extract_chapters(CANDLE_PDF):
        chapter = int(row["chapter"])
        coverage = CANDLE_AUXILIARY_COVERAGE.get(chapter)
        if not coverage:
            continue
        pattern_ids = list(coverage.get("pattern_ids") or [])
        present = [pid for pid in pattern_ids if pid in final_by_pattern]
        candle_rows.append(
            row
            | {
                "source": "Encyclopedia of Candlestick Charts",
                "status": "auxiliary_covered" if present else "auxiliary_mapping_missing",
                "pattern_ids": pattern_ids,
                "present_pattern_ids": present,
                "coverage_note": coverage.get("coverage_note"),
            }
        )

    covered_chart = [row for row in chart_rows if row["status"] == "covered"]
    missing_event = [row for row in chart_rows if row["status"] == "not_covered_event_data_required"]
    failures = [row for row in chart_rows if row["status"] in {"mapping_missing_from_final_manifest", "unmapped"}]
    final_from_chart = sorted({pid for row in covered_chart for pid in row["present_pattern_ids"]})
    auxiliary = sorted({pid for row in candle_rows for pid in row["present_pattern_ids"]})

    payload = {
        "audit_id": "bulkowski_source_pdf_coverage_audit_v1",
        "status": "PASS" if not failures else "FAIL",
        "primary_source": str(CHART_PDF.relative_to(ROOT)),
        "auxiliary_source": str(CANDLE_PDF.relative_to(ROOT)),
        "summary": {
            "source_chart_chapters": len(chart_rows),
            "source_chart_chapters_covered": len(covered_chart),
            "source_chart_chapters_not_covered_event_data_required": len(missing_event),
            "source_chart_chapter_mapping_failures": len(failures),
            "final_manifest_chapters": len(final_chapters),
            "final_chapters_derived_from_chart_source": len(final_from_chart),
            "final_chapters_auxiliary_candlestick_source": len(auxiliary),
            "families_in_final_manifest": len({row["family"] for row in final_chapters}),
        },
        "chart_rows": chart_rows,
        "candlestick_auxiliary_rows": candle_rows,
        "failures": failures,
        "missing_event_data_chapters": missing_event,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "bulkowski_source_pdf_coverage_audit.json"
    md_path = OUT_DIR / "bulkowski_source_pdf_coverage_audit.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Bulkowski Source PDF Coverage Audit",
        "",
        f"Audit ID: `{payload['audit_id']}`",
        f"Status: `{payload['status']}`",
        "",
        "## Summary",
        "",
        f"- Primary source chart chapters: `{len(chart_rows)}`",
        f"- Covered chart chapters: `{len(covered_chart)}`",
        f"- Not covered because event data is required: `{len(missing_event)}`",
        f"- Mapping failures: `{len(failures)}`",
        f"- Final manifest chapters: `{len(final_chapters)}`",
        f"- Final chapters derived from chart source: `{len(final_from_chart)}`",
        f"- Auxiliary candlestick-derived chapters: `{len(auxiliary)}`",
        f"- Families in final manifest: `{payload['summary']['families_in_final_manifest']}`",
        "",
        "## Missing From Primary Chart PDF Coverage",
        "",
        "| Chapter | Source title | Reason |",
        "|---:|---|---|",
    ]
    for row in missing_event:
        lines.append(f"| {row['chapter']} | {row['title']} | {row['missing_reason']} |")
    if not missing_event:
        lines.append("| - | - | - |")

    lines.extend(
        [
            "",
            "## Covered Chart Chapters",
            "",
            "| Chapter | Source title | Final pattern ids | Note |",
            "|---:|---|---|---|",
        ]
    )
    for row in chart_rows:
        if row["status"] != "covered":
            continue
        lines.append(
            f"| {row['chapter']} | {row['title']} | {', '.join(row['present_pattern_ids'])} | {row.get('coverage_note') or ''} |"
        )

    lines.extend(
        [
            "",
            "## Auxiliary Candlestick Coverage",
            "",
            "| Chapter | Source title | Final pattern ids | Note |",
            "|---:|---|---|---|",
        ]
    )
    for row in candle_rows:
        lines.append(
            f"| {row['chapter']} | {row['title']} | {', '.join(row['present_pattern_ids'])} | {row.get('coverage_note') or ''} |"
        )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "json": str(json_path), "md": str(md_path), "summary": payload["summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
