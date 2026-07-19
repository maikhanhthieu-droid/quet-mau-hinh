"""Rebuild final chapters through the source-guided refinement writing flow.

This script upgrades existing final chapters from the canonical PDF factory
flow to the newer Bull-Flag-derived writing flow:

1. source/style dossier
2. source-guided AI candidate
3. reader refinement AI pass
4. canonical publication chapter factory render
5. style-v3 PDF audit
6. manifest promotion

It intentionally uses the final manifest as the chapter inventory. Scanner and
statistics artifacts remain the source of facts; this script only refreshes the
public writing layer and PDF artifact.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.audit_publication_style_v3 import audit_publication_style_v3  # noqa: E402
from scanner.canonical_deepseek_editorial_adapter import (  # noqa: E402
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
    _call_deepseek_json,
    _editorial_guard_status,
    _spirit_score,
    load_dotenv,
    run_canonical_deepseek_editorial,
)
from scanner.canonical_chapter_content import prepare_canonical_chapter_content  # noqa: E402
from scanner.canonical_publication_chapter_factory import (  # noqa: E402
    CANONICAL_PUBLICATION_FACTORY_ID,
    CANONICAL_PUBLICATION_FLOW,
    CANONICAL_PUBLICATION_STYLE_VERSION,
    CANONICAL_READER_EXPERIENCE_GATE_ID,
    build_canonical_publication_chapter,
)
from scanner.canonical_chapter_content import CANONICAL_CONTENT_GENERATOR_ID  # noqa: E402
from scanner.canonical_editorial_layer import CANONICAL_AI_EDITORIAL_GATE_ID, CANONICAL_EDITORIAL_WORKFLOW_ID  # noqa: E402
from scanner.canonical_editorial_layer import REQUIRED_EDITORIAL_SECTIONS, validate_canonical_editorial_sections  # noqa: E402
from scanner.canonical_example_charts import (  # noqa: E402
    DEFAULT_PRICE_DB as DEFAULT_CANONICAL_CHART_PRICE_DB,
    build_canonical_example_charts,
)
from scanner.pattern_publication_core import PUBLICATION_CORE_ID  # noqa: E402
from scanner.promote_final_chapter import promote_final_chapters  # noqa: E402
from scanner.publication_flow_contract import CANONICAL_SOURCE_GUIDED_REFINEMENT_ID  # noqa: E402
from scanner.run_canonical_deepseek_bull_flag_editorial import BULKOWSKI_SOURCE_GUIDED_READER_PROFILE  # noqa: E402
from scanner.validate_final_chapters_manifest import DEFAULT_MANIFEST  # noqa: E402


DEFAULT_OUT_ROOT = Path("artifacts/scanner_v2/source_guided_refinement_final_v1")
DEFAULT_SOURCE_PDF = Path("references/encyclopedia-of-chart-patterns-2nbsped-9786468600-3175723993-9780471668268-0471668265_compress.pdf")
CORE_PATTERNS = Path("scanner/v2/core_patterns.json")
LIGHTWEIGHT_SECTION_REPAIR_ID = "edition11_lightweight_ai_section_repair_v1"
LIGHTWEIGHT_SECTION_REPAIR_ATTEMPTS = 3

EVENT_SOURCES: dict[str, tuple[Path, dict[str, str]]] = {
    "bull_flags": (Path("artifacts/scanner_v2/bull_flags_db_source_parity/db_active/events.csv"), {}),
    "bear_flags": (Path("artifacts/scanner_v2/bear_flags_db_source_parity/db_active/events.csv"), {}),
    "bull_pennants": (Path("artifacts/scanner_v2/pennants/events.csv"), {"variant": "bull_pennant"}),
    "bear_pennants": (Path("artifacts/scanner_v2/pennants/events.csv"), {"variant": "bear_pennant"}),
    "high_tight_flags": (Path("artifacts/scanner_v2/high_tight_flags/events.csv"), {"variant": "high_tight_flag"}),
    "triangles_ascending": (Path("artifacts/scanner_v2/ascending_triangles_db_source_parity/db_active/events.csv"), {}),
    "triangles_descending": (Path("artifacts/scanner_v2/descending_triangles_db_source_parity/db_active/events.csv"), {}),
    "triangles_symmetrical": (Path("artifacts/scanner_v2/symmetrical_triangles_db_source_parity/db_active/events.csv"), {}),
    "wedges_falling": (Path("artifacts/scanner_v2/wedge_family/falling_wedges/db_active/events.csv"), {}),
    "wedges_rising": (Path("artifacts/scanner_v2/wedge_family/rising_wedges/db_active/events.csv"), {}),
    "cup_with_handle": (Path("artifacts/scanner_v2/cup_with_handle_family/cup_with_handle/db_active/events.csv"), {}),
    "cup_with_handle_inverted": (Path("artifacts/scanner_v2/cup_with_handle_family/cup_with_handle_inverted/db_active/events.csv"), {}),
    "rectangle_bottoms": (Path("artifacts/scanner_v2/rectangle_family/rectangle_bottoms/db_active/events.csv"), {}),
    "rectangle_tops": (Path("artifacts/scanner_v2/rectangle_family/rectangle_tops/db_active/events.csv"), {}),
    "head_and_shoulders_bottoms": (Path("artifacts/scanner_v2/head_shoulders_family/head_and_shoulders_bottoms/db_active/events.csv"), {}),
    "head_and_shoulders_bottoms_complex": (Path("artifacts/scanner_v2/head_shoulders_family/head_and_shoulders_bottoms_complex/db_active/events.csv"), {}),
    "head_and_shoulders_tops": (Path("artifacts/scanner_v2/head_shoulders_family/head_and_shoulders_tops/db_active/events.csv"), {}),
    "head_and_shoulders_tops_complex": (Path("artifacts/scanner_v2/head_shoulders_family/head_and_shoulders_tops_complex/db_active/events.csv"), {}),
    "broadening_bottoms": (Path("artifacts/scanner_v2/broadening_family/broadening_bottoms/db_active/events.csv"), {}),
    "broadening_formations_right_angled_ascending": (Path("artifacts/scanner_v2/broadening_family/broadening_formations_right_angled_ascending/db_active/events.csv"), {}),
    "broadening_formations_right_angled_descending": (Path("artifacts/scanner_v2/broadening_family/broadening_formations_right_angled_descending/db_active/events.csv"), {}),
    "broadening_tops": (Path("artifacts/scanner_v2/broadening_family/broadening_tops/db_active/events.csv"), {}),
    "broadening_wedges_ascending": (Path("artifacts/scanner_v2/broadening_family/broadening_wedges_ascending/db_active/events.csv"), {}),
    "broadening_wedges_descending": (Path("artifacts/scanner_v2/broadening_family/broadening_wedges_descending/db_active/events.csv"), {}),
    "measured_move_up": (Path("artifacts/scanner_v2/measured_move_family/measured_move_up/db_active/events.csv"), {}),
    "measured_move_down": (Path("artifacts/scanner_v2/measured_move_family/measured_move_down/db_active/events.csv"), {}),
    "scallops_ascending": (Path("artifacts/scanner_v2/scallop_family/scallops_ascending/db_active/events.csv"), {}),
    "scallops_ascending_inverted": (Path("artifacts/scanner_v2/scallop_family/scallops_ascending_inverted/db_active/events.csv"), {}),
    "scallops_descending": (Path("artifacts/scanner_v2/scallop_family/scallops_descending/db_active/events.csv"), {}),
    "scallops_descending_inverted": (Path("artifacts/scanner_v2/scallop_family/scallops_descending_inverted/db_active/events.csv"), {}),
    "pipe_bottoms": (Path("artifacts/scanner_v2/pipe_family/pipe_bottoms/db_active/events.csv"), {}),
    "pipe_tops": (Path("artifacts/scanner_v2/pipe_family/pipe_tops/db_active/events.csv"), {}),
    "horn_bottoms": (Path("artifacts/scanner_v2/horn_family/horn_bottoms/db_active/events.csv"), {}),
    "horn_tops": (Path("artifacts/scanner_v2/horn_family/horn_tops/db_active/events.csv"), {}),
    "diamond_bottoms": (Path("artifacts/scanner_v2/diamond_family/diamond_bottoms/db_active/events.csv"), {}),
    "diamond_tops": (Path("artifacts/scanner_v2/diamond_family/diamond_tops/db_active/events.csv"), {}),
    "dead_cat_bounce": (Path("artifacts/scanner_v2/dead_cat_bounce_family/dead_cat_bounce/db_active/events.csv"), {}),
    "dead_cat_bounce_inverted": (Path("artifacts/scanner_v2/dead_cat_bounce_family/dead_cat_bounce_inverted/db_active/events.csv"), {}),
    "three_falling_peaks": (Path("artifacts/scanner_v2/three_peaks_valleys_family/three_falling_peaks/db_active/events.csv"), {}),
    "three_rising_valleys": (Path("artifacts/scanner_v2/three_peaks_valleys_family/three_rising_valleys/db_active/events.csv"), {}),
    "triple_tops": (Path("artifacts/scanner_v2/triple_family/triple_tops/db_active/events.csv"), {}),
    "triple_bottoms": (Path("artifacts/scanner_v2/triple_family/triple_bottoms/db_active/events.csv"), {}),
    "bump_and_run_reversal_bottoms": (Path("artifacts/scanner_v2/bump_and_run_family/bump_and_run_reversal_bottoms/db_active/events.csv"), {}),
    "bump_and_run_reversal_tops": (Path("artifacts/scanner_v2/bump_and_run_family/bump_and_run_reversal_tops/db_active/events.csv"), {}),
    "area_gaps": (Path("artifacts/scanner_v2/gap_family/area_gaps/db_active/events.csv"), {}),
    "breakaway_gaps": (Path("artifacts/scanner_v2/gap_family/breakaway_gaps/db_active/events.csv"), {}),
    "continuation_gaps": (Path("artifacts/scanner_v2/gap_family/continuation_gaps/db_active/events.csv"), {}),
    "exhaustion_gaps": (Path("artifacts/scanner_v2/gap_family/exhaustion_gaps/db_active/events.csv"), {}),
    "island_reversals": (Path("artifacts/scanner_v2/island_family/island_reversals/db_active/events.csv"), {}),
    "islands_long": (Path("artifacts/scanner_v2/island_family/islands_long/db_active/events.csv"), {}),
    "rounding_bottoms": (Path("artifacts/scanner_v2/rounding_family/rounding_bottoms/db_active/events.csv"), {}),
    "rounding_tops": (Path("artifacts/scanner_v2/rounding_family/rounding_tops/db_active/events.csv"), {}),
    "inside_day": (Path("artifacts/scanner_v2/inside_day_family/inside_day/db_active/events.csv"), {}),
    "rising_three_methods": (Path("artifacts/scanner_v2/three_methods_family/rising_three_methods/db_active/events.csv"), {}),
    "falling_three_methods": (Path("artifacts/scanner_v2/three_methods_family/falling_three_methods/db_active/events.csv"), {}),
}

DOUBLE_VARIANTS = {
    "double_bottoms_adam_adam": ("double_bottoms", "AA"),
    "double_bottoms_adam_eve": ("double_bottoms", "AE"),
    "double_bottoms_eve_adam": ("double_bottoms", "EA"),
    "double_bottoms_eve_eve": ("double_bottoms", "EE"),
    "double_tops_adam_adam": ("double_tops", "AA"),
    "double_tops_adam_eve": ("double_tops", "AE"),
    "double_tops_eve_adam": ("double_tops", "EA"),
    "double_tops_eve_eve": ("double_tops", "EE"),
}

CORE_PATTERN_MAP = {
    **{key: key for key in EVENT_SOURCES},
    **{key: base for key, (base, _) in DOUBLE_VARIANTS.items()},
    "head_and_shoulders_bottoms_complex": "head_and_shoulders_bottoms",
    "head_and_shoulders_tops_complex": "head_and_shoulders_tops",
}


def _read_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, Mapping) else {}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _failed_editorial_sections_from_error(message: str) -> list[str]:
    return [section for section in REQUIRED_EDITORIAL_SECTIONS if f"'section': '{section}'" in message]


def _coerce_section_repair(parsed: Any, failed_sections: list[str]) -> dict[str, list[str]]:
    if not isinstance(parsed, Mapping):
        raise RuntimeError("section repair returned non-object JSON")
    candidate = parsed.get("editorial_sections")
    if candidate is None:
        candidate = parsed.get("sections")
    if not isinstance(candidate, Mapping):
        direct = {section: parsed.get(section) for section in failed_sections if section in parsed}
        candidate = direct if direct else None
    if not isinstance(candidate, Mapping):
        raise RuntimeError("section repair returned no editorial_sections object")

    unexpected = sorted(str(key) for key in candidate if str(key) not in set(failed_sections))
    if unexpected:
        raise RuntimeError("section repair returned unexpected sections: " + ", ".join(unexpected))

    repaired: dict[str, list[str]] = {}
    for section in failed_sections:
        value = candidate.get(section)
        if isinstance(value, list):
            clean_value = [str(item).strip() for item in value if str(item).strip()]
        elif value is not None:
            clean_value = [str(value).strip()]
        else:
            clean_value = []
        if not clean_value:
            raise RuntimeError(f"section repair returned empty section {section}")
        repaired[section] = clean_value
    return repaired


def _repair_lightweight_sections(
    *,
    payload: Mapping[str, Any],
    approved_path: Path,
    failed_sections: list[str],
    gate_failure: str,
    chapter_meta: Mapping[str, Any],
    model: str,
    temperature: float,
    timeout_s: int,
    max_tokens: int,
    api_key: str,
) -> dict[str, Any]:
    """Ask AI to repair only failing public sections.

    This is intentionally not a fallback generator: it can only rewrite the
    sections that the canonical gate rejected, and the artifact must pass the
    same gate before rendering continues.
    """

    approved = _read_json(approved_path)
    sections = approved.get("editorial_sections") if isinstance(approved.get("editorial_sections"), Mapping) else {}
    if not sections:
        raise RuntimeError(f"Approved artifact has no editorial_sections: {approved_path}")
    out_dir = approved_path.parent
    prompt = {
        "task": "Repair only failing Vietnamese public editorial sections for Edition 1.1.",
        "repair_id": LIGHTWEIGHT_SECTION_REPAIR_ID,
        "chapter_meta": dict(chapter_meta),
        "schema_contract": {
            "only_valid_shape": {
                "editorial_sections": {section: ["paragraph 1", "paragraph 2", "paragraph 3"] for section in failed_sections}
            },
            "allowed_section_ids": failed_sections,
        },
        "failed_sections": failed_sections,
        "gate_failure": gate_failure,
        "hard_rules": [
            "Output valid JSON only.",
            "Return only key `editorial_sections` with exactly the failed section ids.",
            "Do not invent numbers, dates, tickers, examples, or outcomes.",
            "Use only locked payload facts and the current approved artifact.",
            "Make each repaired section reader-facing: chart behavior -> statistic if needed -> implication -> caution.",
            "Do not write buy/sell/short advice.",
            "Do not use internal terms: scanner, pipeline, proxy, setup, target-hit, target-first, validation, holdout, backtest, profit factor.",
        ],
        "locked_payload_facts": {
            "pattern_id": payload.get("pattern_id"),
            "pattern_name": payload.get("pattern_name"),
            "chapter_reference": payload.get("chapter_reference"),
            "target_calibration": payload.get("target_calibration"),
            "classification": payload.get("classification"),
            "publication_spec": payload.get("publication_spec"),
            "example_events": payload.get("example_events"),
        },
        "current_failed_sections": {section: sections.get(section) for section in failed_sections},
        "other_sections_for_style_only": {
            section: sections.get(section)
            for section in REQUIRED_EDITORIAL_SECTIONS
            if section not in failed_sections
        },
    }
    prompt_path = out_dir / "lightweight_section_repair_prompt.json"
    _write_json(prompt_path, prompt)
    schema_errors: list[str] = []
    result: Mapping[str, Any] | None = None
    repaired_sections: dict[str, list[str]] | None = None
    for attempt in range(1, LIGHTWEIGHT_SECTION_REPAIR_ATTEMPTS + 1):
        attempt_prompt = dict(prompt)
        attempt_prompt["attempt"] = attempt
        if schema_errors:
            attempt_prompt["previous_schema_errors"] = schema_errors
            attempt_prompt["repair_instruction"] = "Return exactly the schema_contract.only_valid_shape form and nothing else."
        result = _call_deepseek_json(
            api_key=api_key,
            base_url=DEFAULT_DEEPSEEK_BASE_URL,
            model=model,
            prompt=json.dumps(attempt_prompt, ensure_ascii=False, indent=2, default=str),
            temperature=min(float(temperature), 0.2),
            max_tokens=max_tokens,
            timeout_s=timeout_s,
        )
        (out_dir / f"lightweight_section_repair_attempt_{attempt}_raw.json").write_text(
            str(result.get("raw") or ""),
            encoding="utf-8",
        )
        (out_dir / f"lightweight_section_repair_attempt_{attempt}_parsed.json").write_text(
            json.dumps(result.get("parsed"), ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        try:
            repaired_sections = _coerce_section_repair(result.get("parsed"), failed_sections)
            break
        except RuntimeError as exc:
            schema_errors.append(str(exc))
    if result is None or repaired_sections is None:
        raise RuntimeError(f"AI section repair failed schema for {chapter_meta}: {schema_errors}")

    merged_sections = dict(sections)
    for section, value in repaired_sections.items():
        merged_sections[section] = value
    repaired_artifact = dict(approved)
    repaired_artifact["editorial_sections"] = merged_sections
    repairs = list(repaired_artifact.get("edition11_section_repairs") or [])
    repairs.append(
        {
            "repair_id": LIGHTWEIGHT_SECTION_REPAIR_ID,
            "failed_sections": failed_sections,
            "gate_failure": gate_failure,
            "prompt_path": str(prompt_path),
            "schema_attempts": len(schema_errors) + 1,
            "schema_errors": schema_errors,
            "usage": result.get("usage"),
        }
    )
    repaired_artifact["edition11_section_repairs"] = repairs
    _write_json(approved_path, repaired_artifact)
    return {
        "repair_id": LIGHTWEIGHT_SECTION_REPAIR_ID,
        "failed_sections": failed_sections,
        "usage": result.get("usage"),
        "schema_attempts": len(schema_errors) + 1,
    }


def _slug_from_entry(entry: Mapping[str, Any]) -> str:
    return Path(str(entry.get("pdf") or entry.get("source_pdf") or entry.get("pattern_id"))).stem.replace("_final", "")


def _load_core_patterns() -> Mapping[str, Any]:
    if not CORE_PATTERNS.exists():
        return {}
    data = _read_json(CORE_PATTERNS)
    return data.get("patterns") if isinstance(data.get("patterns"), Mapping) else {}


def _core_entry(pattern_id: str) -> Mapping[str, Any]:
    return _load_core_patterns().get(CORE_PATTERN_MAP.get(pattern_id, pattern_id), {})


def _extract_source_excerpt(pattern_id: str, out_dir: Path, source_pdf: Path) -> Path | None:
    core = _core_entry(pattern_id)
    chapters = core.get("book_chapters") if isinstance(core.get("book_chapters"), list) else []
    if not chapters or not source_pdf.exists() or shutil.which("pdftotext") is None:
        return None
    first_pages = [
        int(chapter.get("source_pdf_page_start"))
        for chapter in chapters
        if isinstance(chapter, Mapping) and str(chapter.get("source_pdf_page_start") or "").isdigit()
    ]
    if not first_pages:
        return None
    first = min(first_pages)
    last = min(max(first_pages) + 14, first + 30)
    out_path = out_dir / "source_excerpt.txt"
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["pdftotext", "-f", str(first), "-l", str(last), "-layout", str(source_pdf), str(out_path)],
        check=True,
    )
    return out_path


def build_source_style_dossier(
    *,
    entry: Mapping[str, Any],
    source_notes: Mapping[str, Any],
    publication_spec: Mapping[str, Any],
    out_dir: Path,
    source_pdf: Path = DEFAULT_SOURCE_PDF,
    edition11_context: Mapping[str, Any] | None = None,
) -> dict[str, Path | None]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern_id = str(entry.get("pattern_id"))
    family = str(entry.get("family") or "")
    core = _core_entry(pattern_id)
    rules = source_notes.get("source_rules") if isinstance(source_notes.get("source_rules"), list) else []
    chapters = core.get("book_chapters") if isinstance(core.get("book_chapters"), list) else []
    source_excerpt = _extract_source_excerpt(pattern_id, out_dir, source_pdf)
    lines = [
        f"# Source-Guided Style Dossier - {pattern_id}",
        "",
        "## Mục đích",
        "",
        "Artifact này dùng để hướng dẫn văn phong và kiến trúc chương theo tinh thần Bulkowski. Nó không phải nguồn số liệu cho thị trường Việt Nam. AI được phép học thứ tự triển khai, cách giải thích thất bại, cách nối bảng số với diễn giải, nhưng không được sao chép, dịch sát hoặc nhập số liệu từ tài liệu gốc vào chương Việt Nam.",
        "",
        "## Định danh chương",
        "",
        f"- Pattern: `{pattern_id}`",
        f"- Family: `{family}`",
        f"- Tiêu đề public hiện tại: {publication_spec.get('title') or entry.get('title') or pattern_id}",
        f"- Phân loại hiện tại: {publication_spec.get('classification') or publication_spec.get('claim_level') or 'n/a'}",
        "",
        "## Chương nguồn Bulkowski đã đối chiếu",
        "",
    ]
    if chapters:
        for chapter in chapters:
            if isinstance(chapter, Mapping):
                lines.append(
                    f"- Chapter {chapter.get('chapter')}: {chapter.get('name')} "
                    f"(book page {chapter.get('source_page_start')}, pdf page {chapter.get('source_pdf_page_start')})"
                )
    else:
        lines.append("- Không có core_patterns entry đầy đủ; dùng source_notes/publication_spec hiện có làm nền đối chiếu.")
    lines.extend(
        [
            "",
            "## Quy tắc hình thái đã khóa",
            "",
        ]
    )
    for rule in rules[:18]:
        if not isinstance(rule, Mapping):
            continue
        excerpt = rule.get("short_excerpt") or rule.get("evidence_excerpt") or ""
        meaning = rule.get("implementation_mapping") or rule.get("interpreted_rule") or ""
        lines.append(f"- `{rule.get('rule_id')}`: {meaning} Nguồn/ghi chú: {excerpt}")
    if not rules:
        lines.append("- Không có source_rules chi tiết trong artifact hiện tại; chỉ dùng payload số liệu và spec public.")
    lines.extend(
        [
            "",
            "## Writing policy cho AI",
            "",
            "- Bắt đầu từ hình thái mà người đọc nhìn thấy trên biểu đồ, sau đó mới đưa số liệu.",
            "- Mỗi con số chính phải có một câu chuyển nghĩa sang cách đọc biểu đồ.",
            "- Thất bại là một phần chính của chương, không phải ghi chú pháp lý.",
            "- Ví dụ biểu đồ phải đọc như case study nhỏ.",
            "- Phụ lục kỹ thuật phải tách khỏi nội dung chính và có lời dẫn, không đổ bảng số thô.",
            "- Không dùng ngôn ngữ khuyến nghị mua/bán/short.",
            "- Không sao chép, không dịch sát, không mô phỏng câu chữ từ sách gốc.",
            "",
        ]
    )
    context = edition11_context if isinstance(edition11_context, Mapping) else {}
    if context:
        role = context.get("edition11_role")
        role_guidance = context.get("role_guidance")
        after_buy = context.get("after_buy_coverage") if isinstance(context.get("after_buy_coverage"), Mapping) else {}
        metric_snapshot = context.get("metric_snapshot") if isinstance(context.get("metric_snapshot"), Mapping) else {}
        lines.extend(
            [
                "## Edition 1.1 role và After-the-Buy context",
                "",
                f"- Vai trò chương trong Edition 1.1: `{role or 'n/a'}`",
                f"- Hướng diễn giải vai trò: {role_guidance or 'Không có hướng dẫn vai trò riêng.'}",
                "- Dùng After-the-Buy để làm rõ đường đi sau xác nhận, bẫy thất bại và cách đọc thận trọng; không dùng nó để tự thêm số Việt Nam.",
                "",
                "### Metric snapshot khóa nhanh",
                "",
            ]
        )
        for key in (
            "events",
            "median_mfe_pct",
            "median_mae_pct",
            "failure_5pct_rate",
            "target_hit_rate",
            "target_first_before_adverse_5pct_rate",
            "selected_base_target_multiple",
            "preflight_status",
            "preflight_score",
            "tradable_status",
            "tradable_score",
            "tradable_blockers",
        ):
            if metric_snapshot.get(key) not in (None, "", []):
                lines.append(f"- `{key}`: {metric_snapshot.get(key)}")
        if after_buy:
            lines.extend(["", "### After-the-Buy coverage", ""])
            for key, value in list(after_buy.items())[:12]:
                if value not in (None, "", []):
                    lines.append(f"- `{key}`: {value}")
        lines.append("")
    if source_excerpt:
        lines.extend(
            [
                "## Source excerpt",
                "",
                f"Companion text extracted from source PDF: `{source_excerpt}`",
                "",
            ]
        )
    dossier = out_dir / "source_style_dossier.md"
    dossier.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return {"source_style_dossier": dossier, "source_excerpt": source_excerpt}


def _load_events(pattern_id: str) -> pd.DataFrame:
    if pattern_id in DOUBLE_VARIANTS:
        base, variant = DOUBLE_VARIANTS[pattern_id]
        path = Path(f"artifacts/scanner_v2/double_pattern_family/{base}/db_active/events.csv")
        filters = {"variant": variant}
    else:
        path, filters = EVENT_SOURCES.get(pattern_id, (Path(), {}))
    if not path.exists():
        raise FileNotFoundError(f"Cannot locate events for {pattern_id}: {path}")
    events = pd.read_csv(path, low_memory=False)
    for column, expected in filters.items():
        if column in events.columns:
            events = events[events[column].astype(str) == expected].copy()
    if events.empty:
        raise RuntimeError(f"No events left after filtering {pattern_id} from {path}")
    return events.reset_index(drop=True)


def _load_charts(source_pdf: Path, payload_path: Path, slug: str) -> dict[str, Path]:
    candidates = [source_pdf.parent / "charts", payload_path.parent / "charts"]
    if slug:
        candidates.extend(sorted(Path("artifacts/scanner_v2").glob(f"**/{slug}/charts")))
    existing_dirs = [path for path in candidates if path.exists()]
    chart_dir = next((path for path in existing_dirs if any("schematic" in png.name.lower() for png in path.glob("*.png"))), None)
    chart_dir = chart_dir or (existing_dirs[0] if existing_dirs else None)
    if chart_dir is None:
        raise FileNotFoundError(f"Missing charts directory near {source_pdf} or {payload_path}")
    pngs = sorted(chart_dir.glob("*.png"))
    if not pngs:
        raise FileNotFoundError(f"No chart PNGs in {chart_dir}")

    def first_contains(*terms: str) -> Path | None:
        lowered = [(path, path.name.lower()) for path in pngs]
        for path, name in lowered:
            if all(term in name for term in terms):
                return path
        return None

    schematic = next((path for path in pngs if "schematic" in path.name.lower()), None)
    charts: dict[str, Path] = {"schematic": schematic or pngs[0]}
    for key, terms in {
        "textbook_success": ("textbook_success",),
        "middle_case": ("middle_case",),
        "failure": ("failure",),
    }.items():
        match = first_contains(*terms)
        if match is not None:
            charts[key] = match
    return charts


def _load_publication_spec(entry: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    spec_value = str(entry.get("publication_spec") or "").strip()
    spec_path = Path(spec_value) if spec_value else None
    title = str(payload.get("pattern_name") or entry.get("title") or entry.get("pattern_id") or "Mẫu hình")
    family = str(entry.get("family") or "")
    pattern_id = str(entry.get("pattern_id") or "")
    if family == "flag_family":
        default_target_unit = "chiều cao cột cờ"
    elif family == "head_shoulders_family":
        default_target_unit = "chiều cao từ đầu tới đường cổ"
    elif family == "cup_handle_family":
        default_target_unit = "chiều cao cốc"
    elif family == "scallop_family":
        default_target_unit = "chiều cao scallop"
    elif family == "pipe_family":
        default_target_unit = "chiều cao pipe"
    elif family == "horn_family":
        default_target_unit = "chiều cao mẫu 3 tuần"
    elif family == "diamond_family":
        default_target_unit = "chiều cao diamond"
    elif family == "dead_cat_bounce_family":
        default_target_unit = "khoảng giveback/retest của sự kiện"
    elif family in {"three_peaks_valleys_family", "triple_family"}:
        default_target_unit = "chiều cao mẫu"
    elif family == "bump_and_run_family":
        default_target_unit = "khoảng cách từ cú bump tới đường xu hướng dẫn"
    elif family == "gap_family":
        default_target_unit = "kích thước gap"
    elif family == "inside_day_family":
        default_target_unit = "biên độ nến trong"
    elif family == "three_methods_family":
        default_target_unit = "biên độ nến đầu tiên"
    elif pattern_id.startswith("double_bottoms_"):
        default_target_unit = "chiều cao từ đáy tới neckline"
    elif pattern_id.startswith("double_tops_"):
        default_target_unit = "chiều cao từ đỉnh tới neckline"
    else:
        default_target_unit = "chiều cao mẫu"

    target = payload.get("target_calibration") if isinstance(payload.get("target_calibration"), Mapping) else {}
    base_target = target.get("base_target") if isinstance(target.get("base_target"), Mapping) else {}
    legacy_target = target.get("legacy_target") if isinstance(target.get("legacy_target"), Mapping) else {}
    target_family = target.get("target_family") if isinstance(target.get("target_family"), Mapping) else {}
    base_target_multiple = (
        target.get("selected_base_target_multiple")
        or base_target.get("target_multiple")
        or target_family.get("bulkowski_adjusted_base")
        or 1.0
    )
    legacy_target_multiple = (
        legacy_target.get("target_multiple")
        or target_family.get("legacy_full_pole")
        or 1.0
    )
    payload_spec = payload.get("publication_spec") if isinstance(payload.get("publication_spec"), Mapping) else {}

    def apply_payload_overrides(spec: dict[str, Any]) -> dict[str, Any]:
        for key, value in payload_spec.items():
            spec[key] = value
        for key in ("role_note", "reader_question_rows"):
            value = payload.get(key)
            if value not in (None, "", []):
                spec[key] = value
        return spec

    if spec_path and spec_path.exists() and spec_path.is_file():
        spec = dict(_read_json(spec_path))
        if not str(spec.get("title") or "").strip():
            spec["title"] = title.replace("_", " ").title()
        if not str(spec.get("subtitle") or "").strip():
            spec["subtitle"] = "Chương mẫu hình theo logic xuất bản chuẩn"
        if not str(spec.get("target_unit_label") or "").strip():
            spec["target_unit_label"] = default_target_unit
        spec.setdefault("base_target_multiple", base_target_multiple)
        spec.setdefault("legacy_target_multiple", legacy_target_multiple)
        return apply_payload_overrides(spec)
    return apply_payload_overrides({
        "title": title.replace("_", " ").title(),
        "subtitle": "Chương mẫu hình theo logic xuất bản chuẩn",
        "labels": {"favorable_move": "mức đi thuận lợi tốt nhất", "adverse_move": "mức kéo ngược sâu nhất"},
        "base_target_multiple": base_target_multiple,
        "legacy_target_multiple": legacy_target_multiple,
        "target_unit_label": default_target_unit,
        "schematic_caption": "Sơ đồ minh họa cấu trúc mẫu hình và vùng xác nhận.",
        "source_rule_ids": [],
        "identification_paragraphs": ["Phần nhận diện được đọc từ hình thái, xác nhận phá vỡ và đường đi sau xác nhận. Các quy tắc nguồn được giữ trong bảng để người đọc biết mẫu nào được chấp nhận và mẫu nào nên bị loại."],
        "reject_bullets": ["Không có hình thái đủ rõ.", "Xác nhận yếu hoặc chỉ xuyên trong phiên.", "Đường giá thiếu sạch hoặc thiếu dữ liệu hậu phá vỡ."],
        "failure_bullets": ["Thất bại là một phần của phân phối thật.", "Không dùng một ví dụ đẹp để thay thế thống kê toàn mẫu.", "Đọc mục tiêu cùng mức kéo ngược và thời gian đạt mục tiêu."],
        "example_intro": ["Các ví dụ được giữ như case study đọc biểu đồ: một trường hợp tốt, một trường hợp trung vị và một trường hợp thất bại."],
        "conclusion_bullets": ["Chương nên được dùng như tài liệu tham khảo mẫu hình trong phạm vi dữ liệu hiện có.", "Không diễn giải kết quả như khuyến nghị giao dịch tự động."],
    })


def _run_ai_stage(
    *,
    payload_path: Path,
    source_notes_path: Path,
    out_dir: Path,
    chapter_meta: Mapping[str, Any],
    style_dossier: Path,
    previous_candidate: Path | None,
    model: str,
    temperature: float,
    timeout_s: int,
    max_tokens: int,
    force: bool,
) -> Path:
    approved = out_dir / "approved_ai_sections.json"
    guard = out_dir / "approved_ai_sections_guard.json"
    if approved.exists() and guard.exists() and not force:
        status = _read_json(guard).get("status")
        if status == "PASS":
            return approved
    if previous_candidate is not None:
        return _run_lightweight_refinement(
            payload_path=payload_path,
            source_notes_path=source_notes_path,
            out_dir=out_dir,
            chapter_meta=chapter_meta,
            style_dossier=style_dossier,
            previous_candidate=previous_candidate,
            model=model,
            temperature=temperature,
            timeout_s=timeout_s,
            max_tokens=max_tokens,
            force=force,
        )
    extra_context = [style_dossier]
    run_canonical_deepseek_editorial(
        payload_path=payload_path,
        source_notes_path=source_notes_path,
        out_dir=out_dir,
        chapter_meta=chapter_meta,
        extra_context_paths=extra_context,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_s=timeout_s,
        style_profile=BULKOWSKI_SOURCE_GUIDED_READER_PROFILE,
    )
    if _read_json(guard).get("status") != "PASS":
        raise RuntimeError(f"AI editorial guard failed: {guard}")
    return approved


def _run_lightweight_refinement(
    *,
    payload_path: Path,
    source_notes_path: Path,
    out_dir: Path,
    chapter_meta: Mapping[str, Any],
    style_dossier: Path,
    previous_candidate: Path,
    model: str,
    temperature: float,
    timeout_s: int,
    max_tokens: int,
    force: bool,
) -> Path:
    approved = out_dir / "approved_ai_sections.json"
    guard_path = out_dir / "approved_ai_sections_guard.json"
    if approved.exists() and guard_path.exists() and not force:
        if _read_json(guard_path).get("status") == "PASS":
            return approved
    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("Missing DEEPSEEK_API_KEY")

    payload = _read_json(payload_path)
    source_notes = _read_json(source_notes_path)
    previous = _read_json(previous_candidate)
    style_text = style_dossier.read_text(encoding="utf-8", errors="replace")[:12000]
    prompt = {
        "task": "Refine an already approved Vietnamese public chart-pattern chapter. Keep schema identical.",
        "chapter_meta": dict(chapter_meta),
        "hard_rules": [
            "Output valid JSON only.",
            "Keep keys: canonical_editorial_workflow_id, editorial_sections, example_captions, claims_to_verify.",
            "Do not invent numbers, tickers, dates, examples, or outcomes.",
            "Use only locked payload facts and previous candidate content.",
            "Improve reader-facing prose: chart behavior -> statistic -> implication -> caution.",
            "Keep technical appendix style separate from main reader narrative.",
            "Do not copy or translate source text.",
            "Avoid buy/sell/short recommendation language.",
        ],
        "style_dossier_excerpt": style_text,
        "locked_facts_compact": {
            "chapter_reference": payload.get("chapter_reference"),
            "target_calibration": payload.get("target_calibration"),
            "classification": payload.get("classification"),
            "example_events": payload.get("example_events"),
        },
        "source_rule_count": len(source_notes.get("source_rules") or []),
        "previous_approved_candidate": previous,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = out_dir / "lightweight_refinement_prompt.json"
    prompt_path.write_text(json.dumps(prompt, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    result = _call_deepseek_json(
        api_key=api_key,
        base_url=DEFAULT_DEEPSEEK_BASE_URL,
        model=model,
        prompt=json.dumps(prompt, ensure_ascii=False, indent=2, default=str),
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_s=timeout_s,
    )
    raw_path = out_dir / "lightweight_refinement_raw.json"
    parsed_path = out_dir / "lightweight_refinement_parsed.json"
    raw_path.write_text(str(result.get("raw") or ""), encoding="utf-8")
    parsed = result.get("parsed")
    if not isinstance(parsed, Mapping):
        raise RuntimeError(f"Lightweight refinement returned non-object JSON for {chapter_meta}")
    previous_sections = previous.get("editorial_sections") if isinstance(previous.get("editorial_sections"), Mapping) else {}
    parsed_sections = parsed.get("editorial_sections") if isinstance(parsed.get("editorial_sections"), Mapping) else {}
    merged_sections: dict[str, Any] = {}
    for section in REQUIRED_EDITORIAL_SECTIONS:
        value = parsed_sections.get(section)
        if value is None or (isinstance(value, list) and not any(str(item).strip() for item in value)):
            value = previous_sections.get(section)
        merged_sections[section] = value
    for section, value in parsed_sections.items():
        merged_sections.setdefault(str(section), value)

    previous_captions = previous.get("example_captions") if isinstance(previous.get("example_captions"), Mapping) else {}
    parsed_captions = parsed.get("example_captions") if isinstance(parsed.get("example_captions"), Mapping) else {}
    merged_captions = {**previous_captions, **parsed_captions}

    refined = {
        "canonical_editorial_workflow_id": CANONICAL_EDITORIAL_WORKFLOW_ID,
        "deepseek_refinement_mode": "lightweight_source_guided_refinement_v1",
        "editorial_sections": merged_sections,
        "example_captions": merged_captions,
        "claims_to_verify": parsed.get("claims_to_verify") or [],
    }
    parsed_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    approved.write_text(json.dumps(refined, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    section_repair: dict[str, Any] | None = None
    try:
        prepared = prepare_canonical_chapter_content(payload, approved_sections_path=approved)
    except ValueError as exc:
        failure_message = str(exc)
        failed_sections = _failed_editorial_sections_from_error(failure_message)
        if not failed_sections:
            raise
        section_repair = _repair_lightweight_sections(
            payload=payload,
            approved_path=approved,
            failed_sections=failed_sections,
            gate_failure=failure_message,
            chapter_meta=chapter_meta,
            model=model,
            temperature=temperature,
            timeout_s=timeout_s,
            max_tokens=max_tokens,
            api_key=api_key,
        )
        prepared = prepare_canonical_chapter_content(payload, approved_sections_path=approved)
    editorial_report = validate_canonical_editorial_sections(prepared)
    spirit = _spirit_score(prepared, editorial_report)
    guard = {
        "status": _editorial_guard_status(editorial_report, spirit),
        "refinement_mode": "lightweight_source_guided_refinement_v1",
        "editorial_report": editorial_report,
        "bulkowski_spirit_score": spirit,
        "model": model,
        "temperature": temperature,
        "usage": result.get("usage"),
        "json_repaired": bool(result.get("json_repaired")),
        "section_repair": section_repair,
    }
    _write_json(guard_path, guard)
    _write_json(
        out_dir / "run_meta.json",
        {
            "mode": "lightweight_source_guided_refinement_v1",
            "model": model,
            "temperature": temperature,
            "payload_path": str(payload_path),
            "source_notes_path": str(source_notes_path),
            "previous_candidate": str(previous_candidate),
            "approved_ai_sections_path": str(approved),
            "guard_path": str(guard_path),
            "guard": guard,
        },
    )
    if guard["status"] != "PASS":
        raise RuntimeError(f"Lightweight refinement guard failed: {guard_path}")
    return approved


def rebuild_one(
    *,
    entry: Mapping[str, Any],
    out_root: Path,
    model: str,
    temperature: float,
    timeout_s: int,
    max_tokens: int,
    force_ai: bool,
    edition11_context_by_pattern: Mapping[str, Mapping[str, Any]] | None = None,
    edition11_style_guide: Mapping[str, Any] | None = None,
    edition11_lightweight_from_current: bool = False,
) -> Path:
    pattern_id = str(entry.get("pattern_id"))
    family = str(entry.get("family") or "uncategorized")
    slug = _slug_from_entry(entry)
    chapter_dir = out_root / family / slug
    ai_dir = chapter_dir / "ai"
    style_dir = chapter_dir / "source_style"
    render_dir = chapter_dir / "chapter"

    payload_path = Path(str(entry.get("payload")))
    source_notes_path = Path(str(entry.get("source_notes")))
    source_pdf = Path(str(entry.get("source_pdf") or entry.get("pdf")))
    payload = dict(_read_json(payload_path))
    source_notes = dict(_read_json(source_notes_path))
    spec = _load_publication_spec(entry, payload)
    style_paths = build_source_style_dossier(
        entry=entry,
        source_notes=source_notes,
        publication_spec=spec,
        out_dir=style_dir,
        edition11_context={
            **dict((edition11_context_by_pattern or {}).get(pattern_id, {})),
            "role_guidance": (
                (edition11_style_guide or {})
                .get("role_guidance", {})
                .get(str((edition11_context_by_pattern or {}).get(pattern_id, {}).get("edition11_role") or ""), "")
                if isinstance((edition11_style_guide or {}).get("role_guidance"), Mapping)
                else ""
            ),
        }
        if edition11_context_by_pattern is not None
        else None,
    )
    style_dossier = Path(style_paths["source_style_dossier"])  # type: ignore[arg-type]
    chapter_meta = {
        "pattern_id": pattern_id,
        "title": spec.get("title") or pattern_id,
        "family": family,
        "edition11_role": (edition11_context_by_pattern or {}).get(pattern_id, {}).get("edition11_role")
        if edition11_context_by_pattern
        else None,
    }
    if edition11_lightweight_from_current:
        current_refined_value = _mapping(entry.get("chapter_writing_stages")).get("refined_ai_sections")
        current_refined = Path(str(current_refined_value or payload.get("editorial_source_path") or ""))
        if not current_refined.exists():
            raise FileNotFoundError(f"Missing current refined AI sections for {pattern_id}: {current_refined}")
        source_guided = current_refined
    else:
        source_guided = _run_ai_stage(
            payload_path=payload_path,
            source_notes_path=source_notes_path,
            out_dir=ai_dir / "source_guided",
            chapter_meta=chapter_meta,
            style_dossier=style_dossier,
            previous_candidate=None,
            model=model,
            temperature=temperature,
            timeout_s=timeout_s,
            max_tokens=max_tokens,
            force=force_ai,
        )
    refined = _run_ai_stage(
        payload_path=payload_path,
        source_notes_path=source_notes_path,
        out_dir=ai_dir / "refined",
        chapter_meta=chapter_meta,
        style_dossier=style_dossier,
        previous_candidate=source_guided,
        model=model,
        temperature=0.3,
        timeout_s=timeout_s,
        max_tokens=max_tokens,
        force=force_ai,
    )

    events = _load_events(pattern_id)
    source_charts = _load_charts(source_pdf, payload_path, slug)
    charts, selected_examples, chart_report = build_canonical_example_charts(
        pattern_id=pattern_id,
        events=events,
        existing_examples=payload.get("example_events") if isinstance(payload.get("example_events"), Mapping) else {},
        out_dir=render_dir / "charts",
        price_db=DEFAULT_CANONICAL_CHART_PRICE_DB,
        schematic=source_charts.get("schematic"),
    )
    payload["example_events"] = {key: dict(value) for key, value in selected_examples.items()}
    payload["canonical_example_chart_report"] = chart_report
    if "schematic" not in charts and "schematic" in source_charts:
        charts["schematic"] = source_charts["schematic"]
    result = build_canonical_publication_chapter(
        payload=payload,
        source_notes=source_notes,
        events=events,
        path_df=pd.DataFrame(),
        charts=charts,
        spec=spec,
        out_dir=render_dir,
        pdf_filename=source_pdf.name,
        payload_filename=payload_path.name,
        manuscript_filename=Path(str(entry.get("manuscript") or f"{slug}_ai_editorial_manuscript.md")).name,
        notes_filename=Path(str(entry.get("notes") or f"{slug}_public_chapter_notes.md")).name,
        family_id=family,
        source_family_factory_id=payload.get("source_family_factory_id"),
        approved_sections_path=refined,
    )
    audit_path = render_dir / "style_v3_audit.json"
    audit = audit_publication_style_v3(Path(result["pdf"]), Path(result["payload"]))
    _write_json(audit_path, audit)
    if audit["status"] != "PASS":
        raise RuntimeError(f"style-v3 audit failed for {pattern_id}: {audit['failures']}")

    manifest_entry = dict(entry)
    manifest_entry.update(
        {
            "status": "final",
            "source_pdf": str(result["pdf"]),
            "payload": str(result["payload"]),
            "manuscript": str(result["manuscript"]),
            "notes": str(result["notes"]),
            "factory_id": CANONICAL_PUBLICATION_FACTORY_ID,
            "publication_core_id": PUBLICATION_CORE_ID,
            "publication_flow": CANONICAL_PUBLICATION_FLOW,
            "canonical_publication_factory_id": CANONICAL_PUBLICATION_FACTORY_ID,
            "canonical_reader_experience_gate_id": CANONICAL_READER_EXPERIENCE_GATE_ID,
            "canonical_publication_style_version": CANONICAL_PUBLICATION_STYLE_VERSION,
            "canonical_editorial_workflow_id": CANONICAL_EDITORIAL_WORKFLOW_ID,
            "canonical_ai_editorial_gate_id": CANONICAL_AI_EDITORIAL_GATE_ID,
            "canonical_content_generator_id": CANONICAL_CONTENT_GENERATOR_ID,
            "style_v3_audit": str(audit_path),
            "chapter_writing_policy_id": CANONICAL_SOURCE_GUIDED_REFINEMENT_ID,
            "chapter_writing_stages": {
                "source_style_dossier": str(style_dossier),
                "source_guided_ai_sections": str(source_guided),
                "refined_ai_sections": str(refined),
                "canonical_pdf": str(result["pdf"]),
                "style_v3_audit": str(audit_path),
            },
            "chapter_writing_notes": (
                "Logic viết mới: dùng source/style dossier làm tham chiếu phong cách, "
                "không sao chép/không dịch sát tài liệu gốc; sinh source-guided AI candidate, "
                "refinement pass, rồi render qua canonical publication factory."
            ),
            "edition11_editorial_pack_id": (edition11_style_guide or {}).get("style_guide_id")
            if edition11_style_guide
            else None,
            "edition11_role": (edition11_context_by_pattern or {}).get(pattern_id, {}).get("edition11_role")
            if edition11_context_by_pattern
            else None,
            "edition11_lightweight_from_current": bool(edition11_lightweight_from_current),
        }
    )
    entry_path = chapter_dir / f"{pattern_id}_final_manifest_entry.json"
    _write_json(entry_path, manifest_entry)
    return entry_path


def _select_entries(manifest: Mapping[str, Any], patterns: list[str], exclude_policy: bool) -> list[Mapping[str, Any]]:
    chapters = [chapter for chapter in manifest.get("chapters", []) if isinstance(chapter, Mapping)]
    if patterns:
        wanted = set(patterns)
        chapters = [chapter for chapter in chapters if chapter.get("pattern_id") in wanted]
    if exclude_policy:
        chapters = [
            chapter
            for chapter in chapters
            if chapter.get("chapter_writing_policy_id") != CANONICAL_SOURCE_GUIDED_REFINEMENT_ID
        ]
    return chapters


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild final chapters through source-guided refinement.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT))
    parser.add_argument("--pattern", action="append", default=[], help="Pattern id to rebuild; may be repeated.")
    parser.add_argument("--all-missing-policy", action="store_true", help="Rebuild all chapters not yet using the source-guided policy.")
    parser.add_argument("--model", default=DEFAULT_DEEPSEEK_MODEL)
    parser.add_argument("--temperature", type=float, default=0.35)
    parser.add_argument("--max-tokens", type=int, default=12000)
    parser.add_argument("--timeout-s", type=int, default=900)
    parser.add_argument("--force-ai", action="store_true")
    parser.add_argument("--promote", action="store_true")
    parser.add_argument(
        "--edition11-pack-dir",
        default="",
        help="Optional directory produced by scanner.build_edition11_editorial_pack.",
    )
    parser.add_argument(
        "--edition11-lightweight-from-current",
        action="store_true",
        help="Use the current approved/refined AI sections as the baseline and run only the Edition 1.1 refinement pass.",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    manifest = _read_json(manifest_path)
    entries = _select_entries(manifest, list(args.pattern), bool(args.all_missing_policy))
    if not entries:
        raise SystemExit("No chapters selected.")

    edition11_context_by_pattern: dict[str, Mapping[str, Any]] | None = None
    edition11_style_guide: Mapping[str, Any] | None = None
    if args.edition11_pack_dir:
        pack_dir = Path(args.edition11_pack_dir)
        inventory = _read_json(pack_dir / "editorial_inventory.json")
        edition11_style_guide = _read_json(pack_dir / "edition_1_1_style_guide.json")
        edition11_context_by_pattern = {
            str(row.get("pattern_id")): row
            for row in inventory.get("chapters", [])
            if isinstance(row, Mapping) and row.get("pattern_id")
        }
        missing_context = [str(entry.get("pattern_id")) for entry in entries if str(entry.get("pattern_id")) not in edition11_context_by_pattern]
        if missing_context:
            raise RuntimeError(f"Edition 1.1 inventory missing patterns: {missing_context}")

    entry_paths: list[Path] = []
    for index, entry in enumerate(entries, start=1):
        pattern_id = entry.get("pattern_id")
        print(f"[{index}/{len(entries)}] rebuilding {pattern_id}", flush=True)
        entry_paths.append(
            rebuild_one(
                entry=entry,
                out_root=Path(args.out_root),
                model=str(args.model),
                temperature=float(args.temperature),
                timeout_s=int(args.timeout_s),
                max_tokens=int(args.max_tokens),
                force_ai=bool(args.force_ai),
                edition11_context_by_pattern=edition11_context_by_pattern,
                edition11_style_guide=edition11_style_guide,
                edition11_lightweight_from_current=bool(args.edition11_lightweight_from_current),
            )
        )
    report: dict[str, Any] = {
        "status": "PASS",
        "rebuilt": [str(path) for path in entry_paths],
        "promoted": None,
    }
    if args.promote:
        report["promoted"] = promote_final_chapters(entry_paths=entry_paths, manifest_path=manifest_path)
        if report["promoted"]["status"] != "PASS":
            report["status"] = "FAIL"
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
