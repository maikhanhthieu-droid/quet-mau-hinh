"""Canonical editorial workflow shared by every public chapter.

This module defines the *writing workflow* that sits between deterministic
research payloads and the canonical PDF factory. It is pattern-agnostic: pattern
modules may provide facts, source rules, examples, and classification, but they
do not get their own public-writing flow.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from scanner.canonical_editorial_layer import CANONICAL_EDITORIAL_WORKFLOW_ID, REQUIRED_EDITORIAL_SECTIONS


EDITORIAL_BLOCK_SEQUENCE = (
    "source_rule_grounding",
    "metrics_interpreter",
    "example_caption_writer",
    "public_chapter_writer",
    "critic_red_team",
    "deterministic_synthesizer",
)

SECTION_ROLES: dict[str, dict[str, Any]] = {
    "summary": {
        "reader_job": "Orient the reader: what this pattern is, what evidence exists, and what the chapter may and may not claim.",
        "must_answer": [
            "What is the pattern in plain Vietnamese?",
            "What is the main historical finding?",
            "How should a non-specialist investor use the chapter?",
        ],
    },
    "tour": {
        "reader_job": "Explain the pattern path before showing statistics.",
        "must_answer": [
            "What happens before, during, and at confirmation?",
            "What visual mistake would create a false pattern?",
        ],
    },
    "failure": {
        "reader_job": "Teach how the pattern fails and how failure changes interpretation.",
        "must_answer": [
            "What does failure look like on the price path?",
            "Which failure statistic matters most for this pattern?",
        ],
    },
    "statistics": {
        "reader_job": "Turn headline statistics into chart-reading implications.",
        "must_answer": [
            "What does the headline hit/failure/move profile imply?",
            "Which number should not be over-read?",
        ],
    },
    "post_breakout": {
        "reader_job": "Explain the after-confirmation path, not just final outcomes.",
        "must_answer": [
            "Does the pattern tend to move cleanly or with adverse noise?",
            "What does time-to-target or retest behavior change?",
        ],
    },
    "size_volume": {
        "reader_job": "Explain when geometry, volume, liquidity, or context makes the pattern more or less useful.",
        "must_answer": [
            "Which structural/context filters improve reading quality?",
            "Which conditions make the pattern noisier?",
        ],
    },
    "tactics": {
        "reader_job": "Translate the chapter into safe practical reading without issuing trade advice.",
        "must_answer": [
            "What should the reader check before acting on the pattern?",
            "Where is the boundary between reference and trading signal?",
        ],
    },
    "checklist": {
        "reader_job": "Give a short operational reading checklist.",
        "must_answer": [
            "What should be checked first?",
            "What should invalidate or downgrade the pattern?",
        ],
    },
}

PUBLIC_CHAPTER_STYLE_BLUEPRINT: dict[str, Any] = {
    "reader_experience_goal": (
        "A chapter should read like a practical chart-pattern reference entry: "
        "first help the reader see the pattern, then explain what the evidence says, "
        "then show how failure and context change interpretation."
    ),
    "paragraph_rhythm": [
        "Start from the chart, not from the table.",
        "Name the behavior in plain language.",
        "Introduce one or two key numbers only after the behavior is clear.",
        "Explain what the number changes for a chart reader.",
        "End with a boundary: when to trust less, or what not to overclaim.",
    ],
    "bulkowski_spirit_without_copying": [
        "important results are useful only when immediately interpreted",
        "identification guidelines should teach visual discrimination, not only list thresholds",
        "failures deserve main-body explanation, not appendix treatment",
        "examples should be read as teaching cases: success, typical case, and failure",
        "tactics should be practical but must not become personalized trading advice",
    ],
    "public_vietnamese_style": [
        "Use concrete Vietnamese chart-reading verbs: nhìn, đọc, kiểm tra, bỏ qua, giảm độ tin cậy.",
        "Prefer 'mẫu đáng chú ý hơn khi...' over abstract statistical phrasing.",
        "Prefer 'đường đi có gọn không' over internal research terms.",
        "Avoid newsletter tone, hype, certainty language, and direct buy/sell language.",
    ],
    "section_depth_target": {
        "summary": "4 paragraphs; a full reader orientation, not a short abstract",
        "tour": "4 paragraphs; walk the chart from prior move to confirmation and common mistakes",
        "failure": "3-4 paragraphs; describe anatomy of failure and what it teaches",
        "statistics": "4 paragraphs; every number gets a reader implication",
        "post_breakout": "3-4 paragraphs; explain path quality and timing",
        "size_volume": "3-4 paragraphs; explain conditions that sharpen or blur the pattern",
        "tactics": "3-4 paragraphs; practical reading workflow without trade advice",
        "checklist": "7-9 short checklist items",
    },
    "table_bridge_rule": (
        "Assume the renderer will place tables after some sections. Write prose that can stand before and after tables: "
        "a table should feel like evidence for a reading point, not like the chapter's main voice."
    ),
    "example_case_rule": (
        "Examples must be teaching cases. A caption should name what the reader should notice first, then cite only fields "
        "present in example_inventory, then explain the lesson: why this is a good, typical, or failed pattern."
    ),
    "anti_dry_report_rule": [
        "Avoid sentences that only compare values without interpretation.",
        "Avoid 'result showed' style unless followed by what it means on a chart.",
        "Use short explanatory turns such as 'nói bằng ngôn ngữ biểu đồ' and 'điểm đáng học ở đây là'.",
        "Do not let uncertainty caveats consume the voice of the chapter; place caveats after the reader understands the pattern.",
    ],
}

OUTPUT_SCHEMA = {
    "canonical_editorial_workflow_id": CANONICAL_EDITORIAL_WORKFLOW_ID,
    "editorial_sections": {section: ["..."] for section in REQUIRED_EDITORIAL_SECTIONS},
    "example_captions": {
        "schematic": "...",
        "textbook_success": "...",
        "middle_case": "...",
        "failure": "...",
    },
    "claims_to_verify": [
        {
            "section": "...",
            "claim": "...",
            "metric_path": "...",
            "risk": "low|medium|high",
        }
    ],
}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _compact(value: Any, max_items: int = 12) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _compact(v, max_items=max_items) for k, v in list(value.items())[:max_items]}
    if isinstance(value, list):
        return [_compact(item, max_items=max_items) for item in value[:max_items]]
    return value


def _source_rule_inventory(source_notes: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rule in source_notes.get("source_rules") or []:
        if not isinstance(rule, Mapping):
            continue
        out.append(
            {
                "rule_id": rule.get("rule_id"),
                "rule_type": rule.get("rule_type"),
                "source_section": rule.get("source_section"),
                "source_excerpt": rule.get("short_excerpt") or rule.get("source_excerpt"),
                "public_rule_meaning": rule.get("implementation_mapping") or rule.get("interpreted_rule"),
                "confidence": rule.get("confidence"),
                "notes": rule.get("notes"),
            }
        )
    return out


def build_canonical_editorial_dossier(
    *,
    payload: Mapping[str, Any],
    source_notes: Mapping[str, Any],
    chapter_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a pattern-agnostic dossier for an AI/human editorial pass."""

    meta = dict(chapter_meta or {})
    ref = _mapping(payload.get("chapter_reference"))
    target = _mapping(payload.get("target_calibration"))
    tradable = _mapping(payload.get("tradable_setup"))
    examples = _mapping(payload.get("example_events"))
    return {
        "canonical_editorial_workflow_id": CANONICAL_EDITORIAL_WORKFLOW_ID,
        "chapter_identity": {
            "pattern_id": payload.get("pattern_id") or payload.get("publication_id") or meta.get("pattern_id"),
            "title": meta.get("title") or payload.get("title") or payload.get("pattern_name"),
            "family": meta.get("family") or payload.get("family"),
            "classification": payload.get("classification") or payload.get("publication_classification"),
        },
        "workflow_blocks": list(EDITORIAL_BLOCK_SEQUENCE),
        "section_roles": SECTION_ROLES,
        "facts_locked": {
            "chapter_reference": _compact(ref),
            "target_calibration": _compact(target),
            "tradable_setup": _compact(tradable),
            "data_scope_and_caveats": _compact(_mapping(payload.get("data_scope_and_caveats"))),
            "governance": _compact(_mapping(payload.get("governance"))),
        },
        "source_grounding_context": _compact(
            {
                "source_grounding_level": source_notes.get("source_grounding_level"),
                "local_source": source_notes.get("local_source"),
                "direct_pdf_review": source_notes.get("direct_pdf_review"),
            }
        ),
        "source_rule_inventory": _source_rule_inventory(source_notes),
        "example_inventory": _compact(examples),
        "required_output_schema": OUTPUT_SCHEMA,
        "public_chapter_style_blueprint": PUBLIC_CHAPTER_STYLE_BLUEPRINT,
        "global_writing_rules": [
            "Write in Vietnamese for investors who read charts, not for internal auditors.",
            "Do not invent numbers; every numeric claim must come from facts_locked or source_rule_inventory.",
            "Every headline statistic must be followed by a chart-reading implication.",
            "Do not open a section by dumping a table result; open with what the chart looks like or how the reader should think.",
            "Write in teaching-case prose: chart behavior -> statistic -> implication -> caution.",
            "Do not merely say a result is high/low; say what a reader should do differently when seeing that result.",
            "Do not use English/internal terms in public body text.",
            "Use public Vietnamese terms: 'mức tăng tốt nhất' instead of MFE, 'mức kéo ngược sâu nhất' instead of MAE, and 'quay lại kiểm định vùng phá vỡ' instead of throwback.",
            "Avoid internal validation words in the public body: scanner, pipeline, proxy, setup, target-hit, target-first, validation, holdout, backtest, profit factor.",
            "Do not make the prose sound like an audit memo. Every table-like result must be converted into a reader-facing sentence before the next number appears.",
            "Examples must read like mini case studies, not chart labels. Use the actual example fields and never invent a volume ratio, number of days, or outcome.",
            "Do not turn reference statistics into buy/sell advice.",
            "Keep pattern-specific facts, but keep the writing workflow identical across chapters.",
            "The pattern geometry must come from source_rule_inventory and source_grounding_context, not from generic chart-pattern language.",
            "The `tour`, `source_rule_grounding`, and `checklist` sections must name the pattern's own visual anatomy, confirmation rule, and common visual traps.",
        ],
    }


def build_canonical_editorial_prompt(dossier: Mapping[str, Any], block_name: str) -> str:
    """Return the shared prompt for one editorial block.

    The prompt is intentionally generic. Pattern-specific facts appear only in
    the dossier JSON, not in the task wording.
    """

    if block_name not in EDITORIAL_BLOCK_SEQUENCE:
        raise ValueError(f"Unknown canonical editorial block: {block_name}")
    prompt_dossier = dict(dossier)
    if block_name != "public_chapter_writer":
        prompt_dossier["required_output_schema"] = {
            "note": "This non-writer block must follow BLOCK_OUTPUT_RULE, not the full chapter schema."
        }
    dossier_json = json.dumps(prompt_dossier, ensure_ascii=False, indent=2, default=str)
    common = (
        "Bạn là biên tập viên chương mẫu hình giá cho nhà đầu tư Việt Nam.\n"
        "Dữ liệu trong DOSSIER là nguồn sự thật duy nhất. Không tự thêm số liệu.\n"
        "Nhiệm vụ không phải tối ưu từng mẫu hình, mà áp dụng cùng một quy trình viết cho mọi chapter.\n"
        "Thân bài public không được dùng thuật ngữ nội bộ như MFE, MAE, scanner, pipeline, proxy, setup, target-hit, target-first, validation, holdout, backtest, profit factor.\n"
        "Văn phong cần giống một chương tham khảo mẫu hình giá: nhìn thấy hình trước, hiểu số sau, rồi biết khi nào phải thận trọng.\n"
        "Không viết như báo cáo kỹ thuật nội bộ. Không để bảng số làm thay phần diễn giải.\n"
        "Nếu DOSSIER có editorial_style_profile, hãy áp dụng profile đó như hướng dẫn văn phong bổ sung, nhưng không được phá facts_locked, source_rule_inventory, hoặc các rule chống overclaim.\n"
        "Mỗi đoạn nên có nhịp: mô tả hành vi giá -> nêu bằng chứng nếu cần -> giải thích hàm ý đọc biểu đồ -> chặn diễn giải quá mức.\n"
        "Mỗi phần phải có câu diễn giải kiểu 'Điều này cho thấy...', 'Vì vậy...', 'Người đọc nên hiểu...', hoặc 'Cách đọc...' để chuyển số liệu thành ý nghĩa đọc biểu đồ.\n"
        "Output phải là JSON hợp lệ, không markdown fence.\n"
    )
    block_output_rules = {
        "source_rule_grounding": (
            "Output riêng cho block này phải ngắn: chỉ trả về JSON với keys "
            "`canonical_editorial_workflow_id`, `source_rules_public`, `recognition_mistakes`, `section_hints`. "
            "Không được viết `editorial_sections` và không được viết chapter hoàn chỉnh."
        ),
        "metrics_interpreter": (
            "Output riêng cho block này phải là inventory, không phải chapter: chỉ trả về JSON với keys "
            "`canonical_editorial_workflow_id`, `metric_readings`, `reader_implications`, `numbers_to_handle_carefully`. "
            "Không được viết `editorial_sections`."
        ),
        "example_caption_writer": (
            "Output riêng cho block này chỉ trả về JSON với keys "
            "`canonical_editorial_workflow_id`, `captions`, `example_lessons`, `caption_warnings`. "
            "Không được viết chapter hoàn chỉnh."
        ),
        "critic_red_team": (
            "Output riêng cho block này chỉ trả về JSON với keys "
            "`canonical_editorial_workflow_id`, `status`, `failures`, `warnings`, `required_repairs`. "
            "Không được viết lại chapter."
        ),
        "public_chapter_writer": (
            "Output riêng cho block này phải viết chapter: trả về đúng `required_output_schema`, "
            "bao gồm `editorial_sections`, `example_captions`, và `claims_to_verify`. "
            "Bắt buộc `editorial_sections` phải có đủ và đúng chính xác 8 keys: "
            "`summary`, `tour`, `failure`, `statistics`, `post_breakout`, `size_volume`, `tactics`, `checklist`. "
            "Không được bỏ `tactics` hoặc `checklist` dù nội dung dài; nếu cần, rút ngắn các phần trước để vẫn trả đủ 8 keys."
        ),
        "deterministic_synthesizer": (
            "Output riêng cho block này chỉ trả về danh sách sửa deterministic, không viết lại chapter."
        ),
    }
    tasks = {
        "source_rule_grounding": (
            "Hãy chuyển source_rule_inventory thành ngôn ngữ nhận diện hình học dễ đọc. "
            "Không trích dài nguồn; chỉ nêu quy tắc công khai, lý do quy tắc quan trọng, và lỗi nhận diện thường gặp. "
            "Bắt buộc dùng đúng từ vựng hình thái riêng của mẫu trong source_excerpt/public_rule_meaning; không được thay bằng ngôn ngữ chung chung."
        ),
        "metrics_interpreter": (
            "Hãy diễn giải facts_locked thành inventory: metric, value, safe_reading, unsafe_reading, "
            "so_what_for_chart_reader. Mỗi safe_reading phải nói rõ người đọc biểu đồ nên hiểu gì khác đi. Không viết chapter hoàn chỉnh."
        ),
        "example_caption_writer": (
            "Hãy viết caption cho các ví dụ trong example_inventory. Caption phải khớp dữ liệu event, không nói đạt mục tiêu nếu event không đạt, "
            "và phải rút ra bài học đọc biểu đồ từ từng ví dụ. Không được tự thêm tỷ lệ khối lượng, số ngày, mức tăng, hoặc outcome nếu trường đó không có trong example_inventory. "
            "Mỗi caption phải có 3 nhịp: điều cần nhìn trên biểu đồ -> dữ kiện event thật -> bài học đọc mẫu."
        ),
        "public_chapter_writer": (
            "Hãy viết editorial_sections theo required_output_schema. Mỗi section phải dùng section_roles và public_chapter_style_blueprint "
            "để trả lời đúng reader_job, must_answer và section_depth_target. Viết thành đoạn văn giàu diễn giải, không viết như danh sách số liệu. "
            "Trước khi trả lời, tự kiểm rằng đủ 8 section bắt buộc; `checklist` là danh sách 7-9 câu ngắn, còn `tactics` là 3-4 đoạn văn về cách đọc thận trọng. "
            "Riêng phần mô tả hình học phải bám sát source_rule_inventory: nêu rõ cấu trúc mẫu, khung thời gian, điều kiện xác nhận, điều kiện loại trừ và bẫy nhìn nhầm."
        ),
        "critic_red_team": (
            "Hãy review output public_chapter_writer. Fail nếu có số liệu không có nguồn, đoạn chỉ liệt kê số, thuật ngữ nội bộ, câu giống khuyến nghị giao dịch, "
            "hoặc section đọc giống báo cáo kỹ thuật thay vì chương tham khảo mẫu hình."
        ),
        "deterministic_synthesizer": (
            "Hãy mô tả các sửa chữa deterministic cần làm. Không viết lại toàn bộ chapter; chỉ trả về danh sách sửa và output fields đã được chấp thuận."
        ),
    }
    return f"{common}\n<BLOCK_OUTPUT_RULE>{block_output_rules[block_name]}</BLOCK_OUTPUT_RULE>\n<TASK>{tasks[block_name]}</TASK>\n<DOSSIER>\n{dossier_json}\n</DOSSIER>"
