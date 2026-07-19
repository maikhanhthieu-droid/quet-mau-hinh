"""Run the canonical DeepSeek editorial trial for Bull Flag."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scanner.canonical_deepseek_editorial_adapter import DEFAULT_DEEPSEEK_MODEL, run_canonical_deepseek_editorial


DEFAULT_PAYLOAD = Path("artifacts/scanner_v2/flag_family_public_chapters/bull_flag_publication_payload/bull_flag_publication_payload.json")
DEFAULT_SOURCE_NOTES = Path("artifacts/scanner_v2/bull_flags_source_grounding/bull_flag_source_notes.json")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bull_flags_ai_writing_canonical_v4_pro")
DEFAULT_EXTRA_CONTEXT = [
    Path("artifacts/scanner_v2/bull_flags_db_source_parity/db_active/statistics.json"),
    Path("artifacts/scanner_v2/flag_family_public_chapters/bull_flag/bull_flag_ai_editorial_manuscript.md"),
    Path("artifacts/scanner_v2/flag_family_public_chapters/flag_family_public_chapters_manifest.md"),
    Path("docs/project/bull-flag-editorial-workflow-v2.md"),
]
DEFAULT_BULKOWSKI_STYLE_CONTEXT = [
    Path("artifacts/scanner_v2/bulkowski_style_reference/flags/bulkowski_flags_style_dossier.md"),
    Path("artifacts/scanner_v2/bulkowski_style_reference/flags/bulkowski_flags_pages_358_372.txt"),
]
DEFAULT_BULKOWSKI_STYLE_DOSSIER_ONLY = [
    Path("artifacts/scanner_v2/bulkowski_style_reference/flags/bulkowski_flags_style_dossier.md"),
]

PRACTITIONER_CREATIVE_PROFILE = {
    "profile_id": "canonical_publication_practitioner_style_trial_v1",
    "purpose": "Make the public chapter read less like a statistics memo and more like a practical chart-pattern reference entry.",
    "creative_latitude": [
        "Use richer Vietnamese transitions and teaching prose.",
        "Open sections from what the reader sees on the chart before naming the metric.",
        "Turn each important number into a concrete chart-reading implication.",
        "Use short practitioner phrases such as 'nói bằng ngôn ngữ biểu đồ', 'điểm đáng học ở đây là', and 'mẫu này đáng đọc hơn khi'.",
        "Allow more varied paragraph rhythm than the strict baseline, but keep every claim anchored to locked facts.",
        "Prefer 'người đọc' or 'nhà đầu tư' over direct second-person commands.",
        "Prefer 'dấu hiệu đọc mẫu' and 'sự kiện xác nhận' over 'tín hiệu'.",
    ],
    "hard_bounds": [
        "Do not invent numbers, dates, examples, volume ratios, or outcomes.",
        "Do not issue buy/sell/short recommendations.",
        "Do not hide uncertainty or data-scope caveats.",
        "Do not use internal technical terms in public body text.",
        "Do not rewrite scanner logic or target calibration.",
        "Do not use direct action wording such as 'trước khi hành động', 'quyết định giao dịch', 'chấp nhận thua lỗ', or 'tín hiệu mua bán'.",
        "Do not make the tactics section sound like execution guidance; it must remain a reading workflow.",
    ],
}

BULKOWSKI_SOURCE_GUIDED_PROFILE = {
    "profile_id": "canonical_publication_bulkowski_source_guided_v1",
    "purpose": "Use the original Flags chapter as a style and chapter-architecture reference, while writing a Vietnam-specific public chapter from locked facts.",
    "style_reference_policy": [
        "The source text is a style reference only, not a source for Vietnam statistics.",
        "Learn section order, paragraph rhythm, practical table commentary, and how failures/tactics are explained.",
        "Do not copy, translate, or closely paraphrase source wording.",
        "Do not import source trading instructions unless the Vietnam payload supports them.",
    ],
    "creative_latitude": [
        "Make the chapter feel like a chart-pattern encyclopedia entry rather than a statistics explainer.",
        "Start each major section from what the reader sees on the chart.",
        "After each statistic, write one plain-language implication for reading the pattern.",
        "Use failure examples and caution language as teaching moments, not as legalistic caveats.",
        "Keep the main chapter practical and keep detailed robustness material in the technical appendix.",
    ],
    "hard_bounds": [
        "Use only locked Vietnam payload numbers.",
        "Do not invent examples, dates, volume ratios, or outcomes.",
        "Do not issue buy/sell/short recommendations.",
        "Do not use internal technical terms in public body text.",
        "Do not rewrite scanner logic or target calibration.",
        "Do not quote the source text in the generated chapter.",
    ],
}

BULKOWSKI_SOURCE_GUIDED_READER_PROFILE = {
    "profile_id": "canonical_publication_bulkowski_source_guided_reader_v2",
    "purpose": (
        "Use the original Flags chapter as a style and chapter-architecture reference, "
        "then write a fuller Vietnam-specific public chapter that feels like a chart-reading guide, "
        "not a statistical report."
    ),
    "style_reference_policy": [
        "The source text is a style reference only, not a source for Vietnam statistics.",
        "Learn how the source moves from identification, to important results, to failures, to practical usage.",
        "Do not copy, translate, or closely paraphrase source wording.",
        "Do not import source trading instructions unless the Vietnam payload supports them.",
    ],
    "chapter_experience_targets": [
        "The main body should answer what a reader sees, why it matters, what the historical evidence says, and when to trust it less.",
        "Every table-facing section needs prose before the table and prose after the table; numbers must not carry the section alone.",
        "Examples should read like mini case studies: what to notice first, what made the example representative, and what lesson it teaches.",
        "Failure should be explained as anatomy of the pattern, not as a legal caveat.",
        "The technical appendix should remain clearly separate from the main reader narrative.",
    ],
    "creative_latitude": [
        "Use a patient explanatory voice for investors who can read charts but do not live in statistics.",
        "Open major sections from chart behavior: pole, flag body, confirmation, pullback/noise, and follow-through.",
        "Use concrete Vietnamese phrases such as 'đọc từ trái sang phải', 'điểm cần nhìn trước', 'mẫu đáng tin hơn khi', and 'điểm làm giảm độ tin cậy'.",
        "Convert ratios into reader meaning: not just what is higher or lower, but what it changes when inspecting a chart.",
        "Let the chapter be moderately longer if needed for clarity; do not compress just to save pages.",
    ],
    "hard_bounds": [
        "Use only locked Vietnam payload numbers.",
        "Do not invent examples, dates, volume ratios, or outcomes.",
        "Do not issue buy/sell/short recommendations.",
        "Do not use internal technical terms in public body text.",
        "Do not use direct action language such as vào lệnh, cắt lỗ, dừng lỗ, tín hiệu mua, tín hiệu bán, or mua/cầm nắm.",
        "Do not rewrite scanner logic or target calibration.",
        "Do not quote the source text in the generated chapter.",
    ],
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run canonical DeepSeek V4 Pro editorial workflow for Bull Flag.")
    parser.add_argument("--payload", default=str(DEFAULT_PAYLOAD))
    parser.add_argument("--source-notes", default=str(DEFAULT_SOURCE_NOTES))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--model", default=DEFAULT_DEEPSEEK_MODEL)
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument(
        "--style-profile",
        choices=[
            "canonical_v3",
            "practitioner_creative_v1",
            "bulkowski_source_guided_v1",
            "bulkowski_source_guided_reader_v2",
            "bulkowski_source_guided_reader_v2_lite",
        ],
        default="canonical_v3",
    )
    parser.add_argument("--max-tokens", type=int, default=12000)
    parser.add_argument("--timeout-s", type=int, default=900)
    parser.add_argument(
        "--minimal-extra-context",
        action="store_true",
        help="Use only the locked payload/source notes plus selected style profile context.",
    )
    args = parser.parse_args()

    extra_context = [] if args.minimal_extra_context else list(DEFAULT_EXTRA_CONTEXT)
    style_profile = None
    if args.style_profile == "practitioner_creative_v1":
        style_profile = PRACTITIONER_CREATIVE_PROFILE
    elif args.style_profile == "bulkowski_source_guided_v1":
        style_profile = BULKOWSKI_SOURCE_GUIDED_PROFILE
        extra_context.extend(DEFAULT_BULKOWSKI_STYLE_CONTEXT)
    elif args.style_profile == "bulkowski_source_guided_reader_v2":
        style_profile = BULKOWSKI_SOURCE_GUIDED_READER_PROFILE
        extra_context.extend(DEFAULT_BULKOWSKI_STYLE_CONTEXT)
    elif args.style_profile == "bulkowski_source_guided_reader_v2_lite":
        style_profile = BULKOWSKI_SOURCE_GUIDED_READER_PROFILE
        extra_context.extend(DEFAULT_BULKOWSKI_STYLE_DOSSIER_ONLY)

    result = run_canonical_deepseek_editorial(
        payload_path=Path(args.payload),
        source_notes_path=Path(args.source_notes),
        out_dir=Path(args.out_dir),
        chapter_meta={"pattern_id": "bull_flags", "title": "Cờ tăng", "family": "flag_family"},
        extra_context_paths=extra_context,
        model=str(args.model),
        base_url=str(args.base_url),
        temperature=float(args.temperature),
        max_tokens=int(args.max_tokens),
        timeout_s=int(args.timeout_s),
        style_profile=style_profile,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
