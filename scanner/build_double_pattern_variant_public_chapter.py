"""Build one Double Pattern Adam/Eve variant chapter candidate.

Variant chapters are reviewed one-by-one before promotion to final. They reuse
the Double Pattern Family scanner output and the same public chapter factory,
but filter the event set to one Adam/Eve variant.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.build_double_pattern_family_public_chapters import (  # noqa: E402
    DEFAULT_AI_DIR,
    DEFAULT_OUT_DIR as DEFAULT_FAMILY_OUT_DIR,
    _build_charts,
    _load_required_editorial,
    _publication_payload,
    _source_notes,
    _spec,
    _write_json,
)
from scanner.double_pattern_family_public_chapter_factory import build_double_pattern_public_chapter  # noqa: E402
from scanner.double_pattern_variant_publication_specs import (  # noqa: E402
    build_double_bottom_variant_publication_spec,
    build_double_top_variant_publication_spec,
)
from scanner.run_bear_flag_db_source_parity_audit import DEFAULT_DB  # noqa: E402
from scanner.v2.double_patterns import DEFAULT_OUT_DIR as DEFAULT_SCAN_OUT_DIR  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/double_pattern_variant_public_chapters")
VARIANT_APPROVED_AI_DIR = Path("artifacts/scanner_v2/source_guided_refinement_final_v1/double_pattern_family")
VARIANT_LABELS = {
    "AA": "Adam & Adam",
    "AE": "Adam & Eve",
    "EA": "Eve & Adam",
    "EE": "Eve & Eve",
}
DOUBLE_BOTTOM_VARIANT_SOURCE = {
    "AA": {
        "chapter": 13,
        "source_page": 213,
        "source_pdf_page": 236,
        "order_rule": "left Adam, right Adam",
        "source_name": "Double Bottoms, Adam & Adam",
    },
    "AE": {
        "chapter": 14,
        "source_page": 229,
        "source_pdf_page": 252,
        "order_rule": "left Adam, right Eve",
        "source_name": "Double Bottoms, Adam & Eve",
    },
    "EA": {
        "chapter": 15,
        "source_page": 244,
        "source_pdf_page": 267,
        "order_rule": "left Eve, right Adam",
        "source_name": "Double Bottoms, Eve & Adam",
    },
    "EE": {
        "chapter": 16,
        "source_page": 259,
        "source_pdf_page": 282,
        "order_rule": "left Eve, right Eve",
        "source_name": "Double Bottoms, Eve & Eve",
    },
}
DOUBLE_TOP_VARIANT_SOURCE = {
    "AA": {
        "chapter": 17,
        "source_page": 277,
        "source_pdf_page": None,
        "order_rule": "left Adam, right Adam",
        "source_name": "Double Tops, Adam & Adam",
    },
    "AE": {
        "chapter": 18,
        "source_page": 292,
        "source_pdf_page": None,
        "order_rule": "left Adam, right Eve",
        "source_name": "Double Tops, Adam & Eve",
    },
    "EA": {
        "chapter": 19,
        "source_page": 306,
        "source_pdf_page": None,
        "order_rule": "left Eve, right Adam",
        "source_name": "Double Tops, Eve & Adam",
    },
    "EE": {
        "chapter": 20,
        "source_page": 320,
        "source_pdf_page": None,
        "order_rule": "left Eve, right Eve",
        "source_name": "Double Tops, Eve & Eve",
    },
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _variant_pattern_id(base_pattern: str, variant: str) -> str:
    suffix = {
        "AA": "adam_adam",
        "AE": "adam_eve",
        "EA": "eve_adam",
        "EE": "eve_eve",
    }[variant]
    return f"{base_pattern}_{suffix}"


def _variant_title(base_pattern: str, variant: str) -> str:
    base_title = "Hai đáy" if base_pattern == "double_bottoms" else "Hai đỉnh"
    return f"{base_title} {VARIANT_LABELS[variant]}"


def _variant_spec(base_pattern: str, variant: str, n_events: int) -> dict[str, Any]:
    spec = _spec(base_pattern)
    label = VARIANT_LABELS[variant]
    spec["title"] = _variant_title(base_pattern, variant)
    spec["subtitle"] = (
        f"Biến thể {label}: hai cực trị được phân loại riêng theo độ nhọn/tròn"
    )
    spec["classification_sentence"] = (
        f"Đây là chương biến thể {label} trong Double Pattern Family; kết luận chỉ dựa trên {n_events} mẫu đủ chuẩn công bố của biến thể này."
    )
    spec["headline_scope"] = (
        f"Kết luận chính lọc riêng biến thể {label}; chapter tổng hợp Double Pattern Family giữ vai trò so sánh nền."
    )
    spec["rule_first_note"] = (
        "Bản biến thể này bám sát checklist hình thái của tài liệu gốc: cực trị Adam hẹp/nhọn, "
        "rise-to-neckline đủ lớn, hai cực trị là minor lows/tops riêng biệt và chỉ xác nhận bằng close phá neckline."
    )
    spec["quick_question_rows"] = [
        ["Đây là chapter gì?", f"Biến thể {label}, không phải toàn bộ family."],
        ["Có so sánh với biến thể khác không?", "Có thể dùng family overview làm nền; chapter này chỉ chấm riêng biến thể."],
        ["Có được nâng claim theo family không?", "Không. Claim phụ thuộc sample và chất lượng riêng của biến thể này."],
    ]
    spec["conclusion_bullets"] = [
        f"Biến thể {label} cần được đọc riêng vì hình thái Adam/Eve có thể thay đổi đường đi hậu breakout.",
        "Nếu mẫu mỏng, chapter vẫn có thể final về xuất bản nhưng claim phải hạ xuống descriptive/watchlist.",
        "Việc duyệt bằng mắt là cổng bắt buộc trước khi nhân rộng sang biến thể tiếp theo.",
    ]
    return spec


def _variant_editorial_from_spec(spec: Mapping[str, Any], *, variant_label: str, n_events: int) -> dict[str, list[str]]:
    return {
        "summary": list(spec.get("summary_paragraphs") or []),
        "tour": list(spec.get("tour_paragraphs") or []),
        "failure": [
            f"Với {variant_label}, thất bại quan trọng nhất không phải là hình thái xấu, mà là giá không đi được tối thiểu 5% theo hướng xác nhận sau khi đã phá neckline.",
            "Do đó chương luôn đọc song song ba lớp: tỷ lệ đạt mục tiêu, tỷ lệ đạt mục tiêu trước biến động bất lợi 5%, và tỷ lệ thất bại 5%.",
        ],
        "statistics": [
            f"Các bảng trong chương chỉ dùng {n_events} mẫu đúng biến thể, đã xác nhận bằng neckline và đủ dữ liệu đường giá.",
            str(spec.get("target_paragraph") or "Các mốc mục tiêu được đọc theo kết quả calibration riêng của biến thể, không tự động lấy 0,5x làm cơ sở."),
        ],
        "post_breakout": [
            "Sau neckline, đường đi giá mới quyết định giá trị tham khảo của mẫu. Một mẫu tốt là mẫu đi đủ xa theo hướng xác nhận mà không đảo chiều bất lợi quá sâu trước đó.",
            "Nếu giá quay lại neckline, người đọc cần xem đó là hành vi kiểm định lại vùng phá vỡ, không phải tự động là tín hiệu hành động.",
        ],
        "size_volume": [
            "Chiều cao từ cực trị tới neckline càng rõ thì mẫu càng dễ đọc. Tuy nhiên mẫu quá dài hoặc hai cực trị quá lệch nhau sẽ làm ý nghĩa đảo chiều yếu đi.",
            "Khối lượng quanh hai cực trị được ghi nhận như bối cảnh, nhưng không được dùng một mình để nâng hoặc hạ kết luận.",
        ],
        "tactics": [
            "Cách dùng phù hợp là xem chương như hồ sơ tham khảo: mẫu nào đáng chú ý, mẫu nào nên đọc thận trọng, và sau xác nhận thường đi như thế nào.",
            "Chương này không đưa quy tắc vào lệnh, thoát lệnh, tỷ trọng, phí, trượt giá hoặc quản trị danh mục.",
        ],
        "checklist": [
            "Có xu hướng trước mẫu phù hợp với loại hình: giảm trước Hai đáy, tăng trước Hai đỉnh.",
            "Hai cực trị đúng biến thể Adam/Eve của chương.",
            "Nhịp quay về neckline đủ rõ, tối thiểu theo source contract.",
            "Giá đóng cửa phá neckline theo hướng xác nhận trước khi đo kết quả.",
            "Đọc target, failure và biến động bất lợi cùng nhau; không chỉ nhìn một tỷ lệ đạt mục tiêu.",
        ],
    }


def _public_text(text: str) -> str:
    return (
        str(text)
        .replace("audit nền", "hồ sơ nền")
        .replace("audit", "kiểm tra dữ liệu")
        .replace("headline", "kết luận chính")
        .replace("premium và standard", "đủ chuẩn công bố")
        .replace("loose và data-limited", "mỏng hoặc thiếu dữ liệu")
    )


def _plot_variant_schematic(out_path: Path, *, variant: str, base_pattern: str = "double_bottoms") -> None:
    fig, ax = plt.subplots(figsize=(9.2, 3.9), dpi=180)
    x = [0.0, 0.9, 1.25, 1.55, 2.8, 4.0, 4.6, 5.2, 6.2, 7.2, 8.3]
    is_top = base_pattern == "double_tops"
    if variant == "AA":
        y = [23, 18, 12, 18, 24, 19, 13, 19, 23, 27, 30]
        labels = [("Adam", 1.25, 12), ("Adam", 4.6, 13)]
        title = "Giải phẫu Hai đáy Adam & Adam"
    elif variant == "AE":
        y = [23, 18, 12, 18, 24, 17, 13.4, 13.2, 18, 24, 29]
        labels = [("Adam", 1.25, 12), ("Eve", 4.8, 13.25)]
        title = "Giải phẫu Hai đáy Adam & Eve"
        if not is_top:
            ax.add_patch(Rectangle((4.05, 12.4), 1.45, 1.8, facecolor="#f1e6cf", edgecolor="#bd9a5f", linewidth=0.9, alpha=0.85))
    elif variant == "EA":
        y = [23, 18, 13.2, 13.0, 20, 23, 18, 12, 18, 25, 30]
        labels = [("Eve", 1.7, 13.1), ("Adam", 7.0, 12)]
        title = "Giải phẫu Hai đáy Eve & Adam"
        if not is_top:
            ax.add_patch(Rectangle((0.95, 12.25), 1.45, 1.8, facecolor="#f1e6cf", edgecolor="#bd9a5f", linewidth=0.9, alpha=0.85))
    else:
        y = [23, 18, 13.2, 13.0, 20, 23, 17, 13.3, 13.2, 22, 29]
        labels = [("Eve", 1.7, 13.1), ("Eve", 7.3, 13.25)]
        title = "Giải phẫu Hai đáy Eve & Eve"
        if not is_top:
            ax.add_patch(Rectangle((0.95, 12.25), 1.45, 1.8, facecolor="#f1e6cf", edgecolor="#bd9a5f", linewidth=0.9, alpha=0.85))
            ax.add_patch(Rectangle((6.65, 12.5), 1.45, 1.8, facecolor="#f1e6cf", edgecolor="#bd9a5f", linewidth=0.9, alpha=0.85))
    if is_top:
        y = [42 - value for value in y]
        labels = [(label, lx, 42 - ly) for label, lx, ly in labels]
        title = title.replace("Hai đáy", "Hai đỉnh")
        if variant == "AE":
            ax.add_patch(Rectangle((4.05, 27.8), 1.45, 1.8, facecolor="#f1e6cf", edgecolor="#bd9a5f", linewidth=0.9, alpha=0.85))
        if variant == "EA":
            ax.add_patch(Rectangle((0.95, 27.95), 1.45, 1.8, facecolor="#f1e6cf", edgecolor="#bd9a5f", linewidth=0.9, alpha=0.85))
        if variant == "EE":
            ax.add_patch(Rectangle((0.95, 27.95), 1.45, 1.8, facecolor="#f1e6cf", edgecolor="#bd9a5f", linewidth=0.9, alpha=0.85))
            ax.add_patch(Rectangle((6.65, 27.7), 1.45, 1.8, facecolor="#f1e6cf", edgecolor="#bd9a5f", linewidth=0.9, alpha=0.85))
    ax.plot(x, y, color="#173b3a", linewidth=2.0)
    ax.scatter(x, y, s=20, color="#173b3a")
    neckline = 24.0 if not is_top else 18.0
    target = 30.0 if not is_top else 12.0
    ax.axhline(neckline, color="#6f4aa8", linestyle="--", linewidth=1.0)
    ax.axhline(target, color="#e98b2a", linestyle="--", linewidth=0.9)
    ax.annotate("neckline", xy=(2.8, neckline), xytext=(3.15, neckline + (2.5 if not is_top else -2.5)), arrowprops={"arrowstyle": "->", "color": "#6f4aa8"}, color="#6f4aa8", fontsize=9)
    ax.annotate("xác nhận", xy=(7.2, 27 if not is_top else 15), xytext=(6.35, 30.2 if not is_top else 11.8), arrowprops={"arrowstyle": "->", "color": "#6f4aa8"}, color="#6f4aa8", fontsize=9)
    ax.text(0.0, target + (0.5 if not is_top else -1.0), "mục tiêu theo chiều cao mẫu", color="#e98b2a", fontsize=8)
    for label, lx, ly in labels:
        ax.annotate(label, xy=(lx, ly), xytext=(lx - 0.45, ly + (-4.0 if not is_top else 4.0)), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
    ax.set_title(title, loc="left", fontsize=10)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)


def _variant_editorial(base_pattern: str, variant: str, base_sections: Mapping[str, list[str]], n_events: int) -> dict[str, list[str]]:
    label = VARIANT_LABELS[variant]
    out = {key: [_public_text(item) for item in value] for key, value in base_sections.items()}
    prefix = (
        f"Chương này chỉ xét biến thể {label} với {n_events} mẫu đủ chuẩn công bố. "
        "Các kết luận không được tự động suy rộng sang những biến thể Adam/Eve khác trong cùng family."
    )
    out["summary"] = [prefix, *out.get("summary", [])]
    out["statistics"] = [
        f"Mọi bảng trong chương đã được lọc riêng cho biến thể {label}. Family overview chỉ dùng làm nền so sánh, không dùng để nâng claim cho biến thể này.",
        *out.get("statistics", []),
    ]
    out["checklist"] = [
        f"Xác nhận đúng biến thể {label} trước khi đọc thống kê.",
        *out.get("checklist", []),
        "Nếu hình thái biến thể không rõ bằng mắt, không dùng mẫu đó làm ví dụ công bố.",
    ]
    return out


def _source_notes_for_variant(base_pattern: str, variant_pattern_id: str, variant: str) -> dict[str, Any]:
    notes = _source_notes(base_pattern)
    meta = (
        DOUBLE_BOTTOM_VARIANT_SOURCE.get(variant, {})
        if base_pattern == "double_bottoms"
        else DOUBLE_TOP_VARIANT_SOURCE.get(variant, {})
    )
    source_rules = list(notes.get("source_rules") or [])
    if base_pattern == "double_bottoms" and variant != "AE":
        source_rules = [rule for rule in source_rules if not str(rule.get("rule_id")).endswith("adam_eve_order")]
    notes["local_source"] = {
        "pattern_key": variant_pattern_id,
        "name": _variant_title(base_pattern, variant),
        "base_pattern": base_pattern,
        "variant": variant,
        "source_chapter": meta.get("chapter"),
        "source_name": meta.get("source_name"),
        "source_pdf_page_start": meta.get("source_pdf_page"),
    }
    notes["source_grounding_policy_id"] = "source_grounded_publication_gate_v1"
    notes["source_grounding_level"] = "variant_source_contract"
    notes["source_rules"] = source_rules
    for rule in notes["source_rules"]:
        if isinstance(rule, dict):
            mapping = str(rule.get("implementation_mapping") or "")
            rule["implementation_mapping"] = mapping.replace(
                "Require a downward trend into the first bottom before accepting a Double Bottom candidate.",
                "Yêu cầu xu hướng giảm đi vào đáy thứ nhất trước khi chấp nhận mẫu Hai đáy.",
            ).replace(
                "Require an upward trend into the first top before accepting a Double Top candidate.",
                "Yêu cầu xu hướng tăng đi vào đỉnh thứ nhất trước khi chấp nhận mẫu Hai đỉnh.",
            )
    notes["source_rules"].append(
        {
            "rule_id": "variant-filter",
            "short_excerpt": f"Biến thể {VARIANT_LABELS[variant]} chỉ giữ đúng thứ tự hình thái: {meta.get('order_rule', variant)}.",
            "implementation_mapping": "Lọc events.variant theo biến thể đã chọn trước khi dựng thống kê và ví dụ.",
        }
    )
    return notes


def _source_aligned_variant_events(base_pattern: str, variant: str, events: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    if events.empty:
        return events, {"enabled": False, "reason": "empty_events"}
    data = events.copy()
    if "publication_quality_tier" in data.columns:
        data = data[~data["publication_quality_tier"].astype(str).eq("data_limited")].copy()
    if "tradability_quality_bucket" in data.columns:
        data = data[~data["tradability_quality_bucket"].astype(str).eq("impaired")].copy()
    separation = pd.to_numeric(data.get("left_spacing_bars"), errors="coerce") + pd.to_numeric(data.get("right_spacing_bars"), errors="coerce")
    height = pd.to_numeric(data.get("pattern_height_pct"), errors="coerce")
    confidence = pd.to_numeric(data.get("variant_confidence"), errors="coerce")
    if base_pattern == "double_tops":
        strict_sep_min, strict_sep_max = 10, 35
        expanded_height_min = 6.0
        sample_depth_height_min = 5.0
        sample_depth_confidence_min = 64.0
        source_exception = (
            "Bulkowski identification text says the neckline valley depth usually falls near 10-20%, but allows exceptions; "
            "expanded scope keeps confirmation, top separation, data-quality and variant-confidence gates."
        )
    else:
        strict_sep_min, strict_sep_max = 15, 56
        expanded_height_min = 6.0
        sample_depth_height_min = 6.0
        sample_depth_confidence_min = 70.0
        source_exception = (
            "Bulkowski identification text says the neckline rise/valley depth usually falls near 10-20%, but allows exceptions; "
            "expanded scope keeps confirmation, separation, data-quality and variant-confidence gates."
        )
    strict_filters = {
        "variant": variant,
        "pattern_height_pct_min": 10.0,
        "extreme_separation_bars_min": strict_sep_min,
        "extreme_separation_bars_max": strict_sep_max,
        "variant_confidence_min": 70.0,
        "confirmation": "close-confirmed neckline breakout",
        "data_quality": "exclude data_limited and impaired tradability before source alignment",
    }
    strict_mask = (height >= 10.0) & separation.between(strict_sep_min, strict_sep_max) & (confidence >= 70.0)
    strict_aligned = data[strict_mask].copy()
    expanded_filters = {
        **strict_filters,
        "pattern_height_pct_min": expanded_height_min,
        "source_exception_basis": source_exception,
    }
    expanded_mask = (height >= expanded_height_min) & separation.between(strict_sep_min, strict_sep_max) & (confidence >= 70.0)
    expanded_aligned = data[expanded_mask].copy()
    sample_depth_filters = {
        **strict_filters,
        "pattern_height_pct_min": sample_depth_height_min,
        "variant_confidence_min": sample_depth_confidence_min,
        "source_exception_basis": (
            "Available-series sample-depth exception. This is only allowed for Double Top variants when strict/expanded filters are below N=30; "
            "it keeps source separation, neckline confirmation and data-quality gates while accepting the scanner's lower-but-classified variant-confidence tier."
        ),
    }
    sample_depth_mask = (
        (height >= sample_depth_height_min)
        & separation.between(strict_sep_min, strict_sep_max)
        & (confidence >= sample_depth_confidence_min)
    )
    sample_depth_aligned = data[sample_depth_mask].copy()

    if len(strict_aligned) >= 30:
        aligned = strict_aligned
        reason = "bulkowski_shape_alignment"
        alignment_level = "strict_source_aligned"
        filters = strict_filters
    elif len(expanded_aligned) >= 30:
        aligned = expanded_aligned
        reason = "bulkowski_source_exception_expanded"
        alignment_level = "source_compatible_exception"
        filters = {
            "strict": strict_filters,
            "expanded": expanded_filters,
        }
    elif base_pattern == "double_tops" and len(sample_depth_aligned) >= 30:
        aligned = sample_depth_aligned
        reason = "available_series_source_compatible_sample_depth"
        alignment_level = "source_compatible_sample_depth_exception"
        filters = {
            "strict": strict_filters,
            "expanded": expanded_filters,
            "sample_depth": sample_depth_filters,
        }
    else:
        aligned = strict_aligned
        reason = "too_few_source_aligned_events"
        alignment_level = "insufficient_sample_depth"
        filters = {
            "strict": strict_filters,
            "expanded": expanded_filters,
            "sample_depth": sample_depth_filters if base_pattern == "double_tops" else None,
        }

    if len(aligned) >= 30:
        chapter = (
            DOUBLE_BOTTOM_VARIANT_SOURCE.get(variant, {}).get("chapter", 13)
            if base_pattern == "double_bottoms"
            else DOUBLE_TOP_VARIANT_SOURCE.get(variant, {}).get("chapter", 17)
        )
        source_basis = (
            f"Chapter {chapter} source alignment: downward trend, meaningful rise to neckline, distinct minor lows, "
            f"close-confirmed breakout, and {VARIANT_LABELS[variant]} shape order."
            if base_pattern == "double_bottoms"
            else f"Chapter {chapter} source alignment: upward trend, meaningful valley depth to neckline, distinct minor highs, close-confirmed downward breakout, and {VARIANT_LABELS[variant]} shape order."
        )
        return aligned, {
            "enabled": True,
            "reason": reason,
            "alignment_level": alignment_level,
            "source_basis": source_basis,
            "filters": filters,
            "input_n": int(len(events)),
            "quality_eligible_n": int(len(data)),
            "strict_aligned_n": int(len(strict_aligned)),
            "expanded_aligned_n": int(len(expanded_aligned)),
            "sample_depth_aligned_n": int(len(sample_depth_aligned)),
            "aligned_n": int(len(aligned)),
        }
    return data, {
        "enabled": False,
        "reason": reason,
        "alignment_level": alignment_level,
        "filters": filters,
        "input_n": int(len(events)),
        "quality_eligible_n": int(len(data)),
        "strict_aligned_n": int(len(strict_aligned)),
        "expanded_aligned_n": int(len(expanded_aligned)),
        "sample_depth_aligned_n": int(len(sample_depth_aligned)),
        "aligned_n": int(len(aligned)),
    }


def build_double_pattern_variant_public_chapter(
    *,
    base_pattern: str,
    variant: str,
    scan_root: Path = DEFAULT_SCAN_OUT_DIR,
    out_dir: Path = DEFAULT_OUT_DIR,
    price_db: Path = DEFAULT_DB,
    final: bool = False,
) -> dict[str, Path]:
    if base_pattern not in {"double_bottoms", "double_tops"}:
        raise ValueError("base_pattern must be double_bottoms or double_tops")
    if variant not in VARIANT_LABELS:
        raise ValueError("variant must be AA, AE, EA, or EE")

    scan_dir = scan_root / base_pattern / "db_active"
    all_events = pd.read_csv(scan_dir / "events.csv")
    if "event_id" not in all_events.columns and "detection_id" in all_events.columns:
        all_events["event_id"] = all_events["detection_id"]
    variant_all = all_events[all_events["variant"].astype(str) == variant].copy()
    if variant_all.empty:
        raise SystemExit(f"No events for {base_pattern} {variant}")
    events, source_alignment = _source_aligned_variant_events(base_pattern, variant, variant_all.copy())
    if source_alignment.get("enabled") is not True and "publication_quality_tier" in variant_all.columns:
        candidate_events = variant_all[variant_all["publication_quality_tier"].isin(["premium", "standard"])].copy()
        if not candidate_events.empty:
            events = candidate_events
            source_alignment["fallback_scope"] = "premium_standard_publication_quality"
    elif events.empty:
        events = variant_all.copy()
        source_alignment = {"enabled": False, "reason": "fallback_to_all_variant_events", "input_n": int(len(variant_all)), "aligned_n": 0}
    path_df = pd.read_csv(scan_dir / "post_breakout_path.csv")
    if "event_id" in path_df.columns:
        ids = set(events["event_id"].astype(str))
        path_df = path_df[path_df["event_id"].astype(str).isin(ids)].copy()
    stats = _read_json(scan_dir / "statistics.json")
    variant_pattern_id = _variant_pattern_id(base_pattern, variant)
    chapter_dir = out_dir / variant_pattern_id

    payload = _publication_payload(base_pattern, stats, events, variant_all)
    publication_spec = (
        build_double_bottom_variant_publication_spec(variant, n_events=len(events))
        if base_pattern == "double_bottoms"
        else build_double_top_variant_publication_spec(variant, n_events=len(events))
    )
    if events.empty:
        raise SystemExit(f"No publishable events for {base_pattern} {variant}")
    source_aligned_final = bool(source_alignment.get("enabled") is True)
    ceiling_final = bool(
        final
        and publication_spec is not None
        and not events.empty
        and source_alignment.get("fallback_scope") == "premium_standard_publication_quality"
    )
    if ceiling_final and not source_aligned_final:
        source_alignment["technical_ceiling_final"] = True
        source_alignment["technical_ceiling_reason"] = (
            "source-aligned sample is too thin, so the final chapter is published as a limited "
            "variant reference using premium/standard quality events rather than as a source-aligned tradable claim"
        )
    effective_final = bool(final and publication_spec is not None and (source_aligned_final or ceiling_final))
    story_spec = dict(publication_spec["story_spec"]) if publication_spec else _variant_spec(base_pattern, variant, len(events))
    payload["publication_id"] = f"{variant_pattern_id}_publication_chapter_v1"
    payload["pattern_id"] = variant_pattern_id
    if publication_spec:
        payload["publication_spec_id"] = publication_spec["publication_spec_id"]
    payload["classification"] = (
        "variant watchlist-reference under available-series scope"
        if base_pattern == "double_bottoms"
        else "variant defensive/informational reference under available-series scope"
    )
    scanner_provenance = {
        "scan_root": str(scan_root),
        "scan_dir": str(scan_dir),
        "detector_config": stats.get("detector_config"),
        "db_source_meta": stats.get("db_source_meta"),
        "source": stats.get("source"),
    }
    payload["scanner_provenance"] = scanner_provenance
    payload["chapter_reference"]["scope"] = "nhóm bám sát nguồn gốc và đủ dữ liệu đường giá"
    payload["chapter_reference"]["source_alignment"] = source_alignment
    payload["chapter_reference"]["scanner_provenance"] = scanner_provenance
    variant_approved_ai = VARIANT_APPROVED_AI_DIR / variant_pattern_id / "ai" / "refined" / "approved_ai_sections.json"
    if publication_spec and variant_approved_ai.exists():
        payload.pop("editorial_sections", None)
        payload["editorial_source_path"] = str(variant_approved_ai)
    elif publication_spec:
        payload["editorial_sections"] = _variant_editorial_from_spec(story_spec, variant_label=VARIANT_LABELS[variant], n_events=len(events))
        payload.pop("editorial_source_path", None)
    else:
        base_sections, editorial_source_path = _load_required_editorial(DEFAULT_AI_DIR / base_pattern / "approved_ai_sections.json")
        payload["editorial_sections"] = _variant_editorial(base_pattern, variant, base_sections, len(events))
        payload["editorial_source_path"] = editorial_source_path

    if chapter_dir.exists():
        shutil.rmtree(chapter_dir)
    charts = _build_charts(base_pattern, events, price_db, chapter_dir)
    schematic = chapter_dir / "charts" / f"{variant_pattern_id}_schematic.png"
    _plot_variant_schematic(schematic, variant=variant, base_pattern=base_pattern)
    charts["schematic"] = schematic
    from scanner.build_double_pattern_family_public_chapters import _select_examples

    examples = _select_examples(events)
    payload["example_events"] = {role: {**event.to_dict(), "example_role": role} for role, event in examples.items()}
    payload["chapter_reference"]["example_visual_validation"] = {
        "status": "VARIANT_REVIEW_REQUIRED",
        "reviewed_n": 0,
        "pass_n": 0,
        "manual_pass_rate_pct": None,
        "reviewed_roles": [],
        "failure_example_reviewed": False,
    }

    source_notes = _source_notes_for_variant(base_pattern, variant_pattern_id, variant)
    source_notes_path = chapter_dir / f"{variant_pattern_id}_source_notes.json"
    publication_spec_path = chapter_dir / f"{variant_pattern_id}_publication_spec.json"
    if publication_spec:
        _write_json(publication_spec_path, publication_spec)
    paths = build_double_pattern_public_chapter(
        payload=payload,
        source_notes=source_notes,
        events=events,
        path_df=path_df,
        charts=charts,
        spec=story_spec,
        out_dir=chapter_dir,
        pdf_filename=f"{variant_pattern_id}_{'final' if effective_final else 'candidate'}.pdf",
        payload_filename=f"{variant_pattern_id}_public_chapter_payload.json",
        manuscript_filename=f"{variant_pattern_id}_ai_editorial_manuscript.md",
        notes_filename=f"{variant_pattern_id}_public_chapter_notes.md",
    )
    _write_json(source_notes_path, source_notes)
    paths["source_notes"] = source_notes_path
    if publication_spec:
        paths["publication_spec"] = publication_spec_path
    review_manifest = {
        "status": "FINAL_READY" if effective_final else "CANDIDATE_REVIEW_REQUIRED",
        "final_basis": "source_aligned" if source_aligned_final else ("technical_ceiling" if ceiling_final else "candidate_only"),
        "requested_final": bool(final),
        "base_pattern": base_pattern,
        "variant": variant,
        "variant_pattern_id": variant_pattern_id,
        "all_variant_events": int(len(variant_all)),
        "public_variant_events": int(len(events)),
        "source_alignment": source_alignment,
        "pdf": str(paths["pdf"]),
        "payload": str(paths["payload"]),
        "publication_spec": str(publication_spec_path) if publication_spec else None,
    }
    _write_json(chapter_dir / f"{variant_pattern_id}_candidate_manifest.json", review_manifest)
    paths["candidate_manifest"] = chapter_dir / f"{variant_pattern_id}_candidate_manifest.json"
    if effective_final and publication_spec:
        final_entry = {
            "family": "double_pattern_family",
            "pattern_id": variant_pattern_id,
            "title": story_spec.get("title"),
            "status": "final",
            "classification": payload.get("classification"),
            "score": None,
            "claim_level": payload.get("classification"),
            "pdf": f"artifacts/final_chapters/double_pattern_family/{variant_pattern_id}_final.pdf",
            "source_pdf": str(paths["pdf"]),
            "payload": str(paths["payload"]),
            "manuscript": str(paths["manuscript"]),
            "notes": str(paths["notes"]),
            "source_notes": str(paths["source_notes"]),
            "publication_spec": str(publication_spec_path),
            "release_gate": "artifacts/scanner_v2/double_pattern_source_grounding/" f"{variant_pattern_id}_source_grounding_audit.json",
            "factory_id": "double_pattern_family_public_chapter_factory_v1",
            "publication_core_id": "pattern_publication_core_v1",
            "publication_flow": "double_pattern_family_public_chapter_factory_v1 + pattern_publication_core_v1",
            "scanner_provenance": scanner_provenance,
            "source_grounding_required": True,
            "source_grounding_policy_id": "source_grounded_publication_gate_v1",
            "publication_semantic_required": True,
            "publication_semantic_gate_id": "publication_semantic_gate_v1",
            "note": f"{story_spec.get('title')} dùng publication spec riêng cho biến thể {VARIANT_LABELS[variant]}.",
        }
        entry_path = chapter_dir / f"{variant_pattern_id}_final_manifest_entry.json"
        _write_json(entry_path, final_entry)
        paths["final_manifest_entry"] = entry_path
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Build one Double Pattern variant public chapter candidate.")
    parser.add_argument("--base-pattern", choices=["double_bottoms", "double_tops"], required=True)
    parser.add_argument("--variant", choices=sorted(VARIANT_LABELS), required=True)
    parser.add_argument("--scan-root", default=str(DEFAULT_SCAN_OUT_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--price-db", default=str(DEFAULT_DB))
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args()
    paths = build_double_pattern_variant_public_chapter(
        base_pattern=args.base_pattern,
        variant=args.variant,
        scan_root=Path(args.scan_root),
        out_dir=Path(args.out_dir),
        price_db=Path(args.price_db),
        final=bool(args.final),
    )
    print(json.dumps({key: str(value) for key, value in paths.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
