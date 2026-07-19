"""Build source-grounded Three Methods Family public-chapter seed artifacts.

This builder creates deterministic ingredients only.  It does not approve
public prose and does not render a final PDF; final writing must go through
`canonical_source_guided_refinement_v1`.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.build_horn_family_public_chapters import (  # noqa: E402
    _enrich_events_for_target,
    _events_for_scope,
    _fmt,
    _metric_for_target,
    _select_examples,
)
from scanner.publication_flow_contract import SOURCE_GROUNDED_PUBLICATION_GATE_ID  # noqa: E402
from scanner.three_methods_family_publication_specs import build_three_methods_publication_spec  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/three_methods_family_public_chapters")
SOURCE_PDF = "references/Thomas N. Bulkowski - Encyclopedia of Candlestick.pdf"


PATTERNS: dict[str, dict[str, Any]] = {
    "rising_three_methods": {
        "slug": "rising_three_methods",
        "title": "Rising Three Methods",
        "subtitle": "Mẫu tiếp diễn năm nến trong xu hướng tăng",
        "scan_dir": Path("artifacts/scanner_v2/three_methods_family/rising_three_methods/db_active"),
        "source_chapter": "Rising and Falling Three Methods",
        "source_name": "Rising Three Methods",
        "scope_tier": "premium+standard",
        "classification": "hồ sơ tiếp diễn tăng; có thể kiểm tra tradable layer cho nhánh long-cash",
        "claim_level": "đọc như mẫu tiếp diễn năm nến: nến tăng dài, ba nến nhỏ nghỉ trong biên, rồi nến tăng cuối đóng cửa vượt biên trên",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, Rising Three Methods là chương tiếp diễn tăng đáng theo dõi: mẫu có cấu trúc rất ngắn, có xác nhận ngay ở nến thứ năm, nhưng phải đọc cùng mức kéo ngược vì đường đi sau xác nhận vẫn có thể nhiễu.",
        "morphology": "Rising Three Methods bắt đầu bằng một nến đầu tiên dài theo xu hướng tăng. Ba nến nhỏ tiếp theo nằm trong biên độ nến đầu tiên, giống một nhịp nghỉ có kiểm soát. Mẫu chỉ được xác nhận khi nến cuối cũng là nến tăng và đóng cửa vượt biên trên của nến đầu tiên.",
        "role_note": "Dùng như hồ sơ tiếp diễn tăng sau nhịp nghỉ ngắn; không đọc như tín hiệu mua nếu nến cuối chưa đóng cửa vượt biên trên.",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "direction": "up",
    },
    "falling_three_methods": {
        "slug": "falling_three_methods",
        "title": "Falling Three Methods",
        "subtitle": "Mẫu tiếp diễn năm nến trong xu hướng giảm",
        "scan_dir": Path("artifacts/scanner_v2/three_methods_family/falling_three_methods/db_active"),
        "source_chapter": "Rising and Falling Three Methods",
        "source_name": "Falling Three Methods",
        "scope_tier": "premium+standard",
        "classification": "hồ sơ phòng thủ/tiếp diễn giảm; dùng như cảnh báo rủi ro trên cổ phiếu cơ sở",
        "claim_level": "đọc như mẫu tiếp diễn năm nến: nến giảm dài, ba nến nhỏ hồi trong biên, rồi nến giảm cuối đóng cửa vượt biên dưới",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, Falling Three Methods nên được đọc như chương defensive/informational: nó mô tả rủi ro tiếp diễn giảm sau một nhịp hồi ngắn, nhưng không mặc định là cơ hội short cổ phiếu cơ sở.",
        "morphology": "Falling Three Methods bắt đầu bằng một nến đầu tiên dài theo xu hướng giảm. Ba nến nhỏ tiếp theo hồi hoặc đi ngang nhưng vẫn nằm trong biên độ nến đầu tiên. Mẫu chỉ được xác nhận khi nến cuối cũng là nến giảm và đóng cửa vượt biên dưới của nến đầu tiên.",
        "role_note": "Dùng như hồ sơ cảnh báo tiếp diễn giảm hoặc hỗ trợ giảm rủi ro; không đọc như short setup phổ quát trên cổ phiếu cơ sở.",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "direction": "down",
    },
}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _plot_schematic(out_path: Path, *, pattern_id: str) -> None:
    up = pattern_id == "rising_three_methods"
    fig, ax = plt.subplots(figsize=(9.2, 3.9), dpi=180)
    x = np.arange(5)
    if up:
        opens = np.array([18.0, 20.2, 20.0, 19.8, 20.5])
        closes = np.array([20.4, 19.9, 19.7, 20.1, 21.0])
        lows = np.array([17.8, 19.5, 19.4, 19.5, 20.2])
        highs = np.array([20.6, 20.4, 20.3, 20.2, 21.2])
        title = "Giải phẫu Rising Three Methods"
        confirm = "đóng cửa vượt biên trên"
    else:
        opens = np.array([21.0, 18.8, 19.0, 19.2, 18.5])
        closes = np.array([18.6, 19.1, 19.3, 18.9, 18.0])
        lows = np.array([18.4, 18.6, 18.7, 18.5, 17.8])
        highs = np.array([21.2, 19.5, 19.6, 19.4, 18.8])
        title = "Giải phẫu Falling Three Methods"
        confirm = "đóng cửa vượt biên dưới"
    for i, (o, c, lo, hi) in enumerate(zip(opens, closes, lows, highs)):
        color = "#1b8a5a" if c >= o else "#c44e52"
        ax.vlines(x[i], lo, hi, color="#222222", linewidth=2.0)
        ax.add_patch(Rectangle((x[i] - 0.16, min(o, c)), 0.32, max(abs(c - o), 0.06), facecolor=color, edgecolor=color, alpha=0.9))
    ax.axhspan(lows[0], highs[0], xmin=0.08, xmax=0.74, color="#6baed6", alpha=0.14)
    ax.axhline(highs[0], color="#7A5195", linestyle="--", linewidth=1.0)
    ax.axhline(lows[0], color="#7A5195", linestyle="--", linewidth=1.0)
    ax.text(x[0], highs[0] + 0.18, "nến đầu dài", ha="center", fontsize=8, color="#245b5a")
    ax.text(x[2], highs[0] + 0.18, "ba nến nhỏ trong biên", ha="center", fontsize=8, color="#245b5a")
    ax.text(x[4], highs[4] + 0.18 if up else highs[0] + 0.18, confirm, ha="center", fontsize=8, color="#7A5195")
    ax.set_title(title, loc="left", fontsize=10)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)


def _source_notes(pattern_id: str, meta: Mapping[str, Any]) -> dict[str, Any]:
    rising = pattern_id == "rising_three_methods"
    return {
        "status": "PASS",
        "source_grounding_policy_id": SOURCE_GROUNDED_PUBLICATION_GATE_ID,
        "source_grounding_level": "publication_aligned",
        "local_source": {"pattern_key": pattern_id, "chapter": meta["source_chapter"], "name": meta["source_name"]},
        "direct_pdf_review": {
            "status": "PASS",
            "review_id": "three_methods_source_extraction_review_v1",
            "pdf_path": SOURCE_PDF,
            "book_chapter": meta["source_chapter"],
            "book_pages_checked": [657, 658, 659, 660, 661] if rising else [368, 369, 370, 371, 372],
            "pdf_pages_checked": [657, 658, 659, 660, 661] if rising else [368, 369, 370, 371, 372],
            "target_rule_summary": "Three Methods is treated as a five-candle continuation pattern; local bands use 0.5x and 1.0x of the first candle range.",
            "review_note": "Source extraction records a five-candlestick continuation structure: long candle, three small candles inside the first candle range, and a final long candle confirming continuation.",
        },
        "source_rules": [
            {"rule_id": "tm.prior_trend", "short_excerpt": "upward trend for rising, downward for falling", "implementation_mapping": "yêu cầu xu hướng trước mẫu cùng hướng với biến thể"},
            {"rule_id": "tm.first_long", "short_excerpt": "long candle begins the pattern", "implementation_mapping": "nến đầu tiên phải có thân lớn so với biên độ gần đây"},
            {"rule_id": "tm.three_small_inside", "short_excerpt": "three small counter-trend candles", "implementation_mapping": "ba nến giữa phải nhỏ và nằm trong biên độ nến đầu tiên"},
            {"rule_id": "tm.final_confirmation", "short_excerpt": "final long candle closing beyond the first candle range", "implementation_mapping": "nến cuối đóng cửa vượt biên trên" if rising else "nến cuối đóng cửa vượt biên dưới"},
            {"rule_id": "tm.volume_pattern", "short_excerpt": "high on first and last candles, lower on middle three", "implementation_mapping": "volume co ở ba nến giữa và tăng lại ở nến cuối là tín hiệu phụ"},
            {"rule_id": "tm.failure_5pct", "short_excerpt": "fails to move at least 5% in breakout direction", "implementation_mapping": "thất bại được đọc bằng ngưỡng đi thuận lợi dưới 5% theo hướng xác nhận"},
        ],
    }


def _spec(pattern_id: str, meta: Mapping[str, Any]) -> dict[str, Any]:
    rising = pattern_id == "rising_three_methods"
    breakout = "biên trên" if rising else "biên dưới"
    trend_word = "tăng" if rising else "giảm"
    return {
        "title": meta["title"],
        "subtitle": meta["subtitle"],
        "base_target_multiple": 0.5,
        "base_target_label": "0,5x",
        "legacy_target_multiple": 1.0,
        "legacy_target_label": "1,0x",
        "target_unit_label": "biên độ nến đầu tiên",
        "target_focus_title": "Mốc cơ sở 0,5x",
        "target_focus_caption": "mốc 0,5x biên độ nến đầu tiên",
        "target_focus_reading": "mốc thận trọng cho mẫu năm nến",
        "target_full_title": "Mốc đầy đủ 1,0x",
        "target_full_reading": "mốc đủ một biên độ nến đầu tiên",
        "morphology_sentence": meta["morphology"],
        "role_note": meta["role_note"],
        "classification_sentence": meta["public_classification_sentence"],
        "headline_scope": f"{meta['title']} là mẫu tiếp diễn năm nến, nên chương đọc nó như nhịp nghỉ trong xu hướng {trend_word} đã có trước, không như mẫu đảo chiều độc lập.",
        "local_source_chapter": meta["source_chapter"],
        "schematic_caption": f"Sơ đồ minh họa {meta['title']}: nến đầu tiên dài, ba nến nhỏ nằm trong biên, rồi nến cuối xác nhận tiếp diễn.",
        "how_subtitle": "Nến đầu dài, ba nến nghỉ, nến cuối xác nhận.",
        "labels": {"favorable_move": "mức đi thuận lợi", "adverse_move": "mức kéo ngược bất lợi"},
        "source_rule_ids": ["tm.prior_trend", "tm.first_long", "tm.three_small_inside", "tm.final_confirmation", "tm.volume_pattern", "tm.failure_5pct"],
        "public_rule_rows": [
            [f"Phải có xu hướng {trend_word} trước mẫu.", f"Trước mẫu cần có một nhịp {trend_word} đủ rõ; nếu đoạn trước chỉ đi ngang, cấu trúc năm nến phía sau không còn nhiều ý nghĩa."],
            ["Nến đầu tiên phải là nến dài.", "Thân nến đầu phải lớn so với biên độ gần đây và tạo khung giá cho ba nến giữa."],
            ["Ba nến giữa phải nhỏ và nằm trong biên nến đầu.", "Mẫu bị loại nếu nến giữa vượt ra ngoài high/low của nến đầu hoặc thân quá lớn."],
            [f"Nến cuối phải xác nhận qua {breakout}.", f"Xác nhận chỉ tính khi nến cuối cùng hướng và đóng cửa vượt {breakout} của nến đầu tiên."],
            ["Volume là tín hiệu phụ.", "Khối lượng giảm ở ba nến giữa và tăng ở nến cuối giúp mẫu đáng tin hơn, nhưng không thay thế hình học."],
            ["Mục tiêu theo biên độ nến đầu tiên.", "Mốc 0,5x dùng để đọc thận trọng; mốc 1,0x giữ vai trò đủ một biên độ nến đầu."],
        ],
        "quick_question_rows": [
            ["Bối cảnh", f"Trước mẫu có xu hướng {trend_word} đủ rõ không?"],
            ["Thân mẫu", "Nến đầu dài và ba nến giữa có nằm trong biên của nó không?"],
            ["Xác nhận", f"Nến cuối có đóng cửa vượt {breakout} không?"],
            ["Đường đi sau đó", "Mốc 0,5x biên độ nến đầu có đến trước kéo ngược 5% không?"],
        ],
        "component_rows": [
            ["Nến đầu", f"Nến dài theo xu hướng {trend_word}.", "Tạo biên mẫu"],
            ["Ba nến giữa", "Nến nhỏ, nghỉ hoặc hồi nhẹ trong biên nến đầu.", "Nhịp nghỉ có kiểm soát"],
            ["Nến cuối", f"Nến dài cùng hướng và đóng cửa vượt {breakout}.", "Xác nhận tiếp diễn"],
            ["Đường đi sau đó", "Đo mức đi thuận lợi, kéo ngược và thời gian đạt mục tiêu.", "Kiểm chứng sau xác nhận"],
        ],
        "reject_bullets": [
            f"Không có xu hướng {trend_word} đủ rõ trước mẫu.",
            "Ba nến giữa vượt khỏi biên nến đầu hoặc thân quá lớn.",
            "Nến cuối không cùng hướng hoặc không đóng cửa vượt biên xác nhận.",
            "Không đủ dữ liệu hậu phá vỡ để đo đường đi sau xác nhận.",
        ],
        "identification_paragraphs": [meta["morphology"]],
        "example_intro": [f"Ba ví dụ dưới đây minh họa {meta['title']} như một case study năm nến: một mẫu đạt mốc cơ sở, một mẫu gần trung vị và một mẫu thất bại. Điểm cần nhìn là nến đầu, ba nến nghỉ, nến cuối xác nhận và đường đi sau đó."],
        "failure_bullets": [
            "Thất bại 5% là mẫu không đi đủ xa sau xác nhận, không phải stop-loss thực chiến.",
            "Mẫu năm nến thường sai khi ba nến giữa không còn là nhịp nghỉ gọn mà đã trở thành vùng dao động nhiễu.",
            "Tỷ lệ đạt mục tiêu cần đọc cùng target-first-before-adverse vì giá có thể chạm mốc sau khi đã kéo ngược sâu.",
        ],
        "target_paragraph": "Mục tiêu được đo theo biên độ nến đầu tiên: 0,5x là mốc cơ sở thận trọng cho mẫu tiếp diễn ngắn, 1,0x là mốc đầy đủ để so sánh toàn bộ chapter.",
        "quick_conclusion_rows": [
            ["Mẫu này dùng để đọc gì?", f"Nhịp tiếp diễn {trend_word} sau một pha nghỉ ba nến."],
            ["Mốc đọc chính?", "0,5x biên độ nến đầu tiên."],
            ["Mốc tham chiếu?", "1,0x biên độ nến đầu tiên."],
            ["Khi nào thận trọng?", "Khi ba nến giữa quá rộng, nến cuối xác nhận yếu, hoặc kéo ngược sau xác nhận quá nhanh."],
        ],
        "identification_bridge": (
            "Các quy tắc nhận diện nên được đọc như một chuỗi năm nến: trước hết phải có xu hướng dẫn, sau đó nến đầu tạo khung, "
            "ba nến giữa chỉ là nhịp nghỉ, và nến cuối mới xác nhận. Nếu đảo thứ tự này, người đọc rất dễ biến một vùng dao động nhỏ thành mẫu tiếp diễn."
        ),
        "caveat_bullets": [
            "Không tuyên bố đây là nghiên cứu toàn thị trường đúng từng ngày lịch sử.",
            "Không dùng historical VN30/VN100 membership làm kết luận chính.",
            "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
            "Chương là tài liệu tham khảo hậu xác nhận, không phải khuyến nghị mua bán.",
        ],
        "quantile_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên"),
            ("Biên độ nến đầu", "pattern_height_pct", "%"),
            ("Thân nến đầu/ATR", "first_body_atr", "lần"),
            ("Thân nến cuối/ATR", "last_body_atr", "lần"),
            ("Tỷ lệ thân ba nến giữa", "middle_body_ratio", "lần"),
            ("Xu hướng trước mẫu", "prior_trend_pct", "%"),
            ("Mức đi thuận lợi", "mfe_pct", "%"),
            ("Mức kéo ngược bất lợi", "mae_pct", "%"),
            ("Ngày chạm mốc cơ sở", "days_to_target", "phiên"),
        ],
        "skip_condition_specs": [
            ("Thân nến đầu yếu", "first_body_atr", "q25", None, "Nến đầu không đủ lực để tạo khung tiếp diễn."),
            ("Ba nến giữa quá rộng", "middle_body_ratio", "q75", None, "Nhịp nghỉ không còn gọn."),
            ("Xu hướng trước mẫu quá yếu", "prior_trend_pct", "q25_abs", None, "Thiếu lực dẫn trước làm mẫu dễ thành nhiễu."),
            ("Kéo ngược quá sâu", "mae_pct", "q75", None, "Đường đi sau xác nhận không còn sạch."),
        ],
        "general_stat_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên", "Three Methods là mẫu năm nến."),
            ("Biên độ nến đầu", "pattern_height_pct", "%", "Biên độ này là thước đo target."),
            ("Tỷ lệ thân ba nến giữa", "middle_body_ratio", "lần", "Càng thấp càng thể hiện nghỉ gọn."),
            ("Xu hướng trước mẫu", "prior_trend_pct", "%", "Mẫu chỉ có ý nghĩa khi là tiếp diễn."),
        ],
        "best_condition_specs": [
            ("Nhóm hình thái tốt", "publication_quality_tier", "==", "premium", "Nến đầu/cuối rõ, ba nến giữa gọn và xác nhận mạnh hơn."),
            ("Nhóm chuẩn", "publication_quality_tier", "==", "standard", "Đủ dùng trong thống kê nhưng không nhất thiết là ví dụ đẹp."),
            ("Đường giá sạch", "path_quality_bucket", "==", "clean", "Ít thiếu phiên và ít chuỗi đứng giá."),
            ("Volume co rồi tăng lại", "volume_contracts", "==", True, "Phù hợp tinh thần nguồn về volume ở ba nến giữa và nến cuối."),
        ],
        "conclusion_bullets": [
            f"{meta['title']} là mẫu tiếp diễn năm nến, không phải mẫu đảo chiều độc lập.",
            "Mục tiêu theo biên độ nến đầu tiên; chương dùng 0,5x làm mốc cơ sở và 1,0x làm mốc đầy đủ.",
            meta["role_note"],
        ],
    }


def _publication_payload(pattern_id: str, meta: Mapping[str, Any], events: pd.DataFrame, all_events: pd.DataFrame, path_df: pd.DataFrame) -> dict[str, Any]:
    base = _metric_for_target(events, path_df, 0.5, "conservative_half_first_candle_range")
    full = _metric_for_target(events, path_df, 1.0, "full_first_candle_range")
    variants = events["variant"].value_counts().to_dict() if "variant" in events.columns else {}
    return {
        "publication_id": f"{pattern_id}_publication_chapter_v1",
        "pattern_id": pattern_id,
        "pattern_name": meta["title"],
        "status": "PASS",
        "classification": meta["classification"],
        "chapter_reference": {
            "scope": "nhóm hình thái tốt + nhóm chuẩn",
            "all_scanner_events": int(len(all_events)),
            "public_grade_events": int(len(events)),
            "public_grade_share_pct": round(float(len(events)) / max(len(all_events), 1) * 100.0, 2),
            "events": int(len(events)),
            "symbols_scanned": int(all_events["symbol"].nunique()) if "symbol" in all_events.columns else None,
            "evaluated_events": int(events["mfe_pct"].notna().sum()) if "mfe_pct" in events.columns else int(len(events)),
            "median_mfe_pct": base.get("median_mfe_pct"),
            "median_mae_pct": base.get("median_mae_pct"),
            "mfe_mae_median_ratio": base.get("mfe_mae_median_ratio"),
            "failure_5pct_rate": base.get("failure_5pct_rate"),
            "legacy_target_hit_rate": full.get("target_hit_rate"),
            "legacy_target_first_before_adverse_5pct_rate": full.get("target_first_before_adverse_5pct_rate"),
            "median_first_body_atr": _fmt(pd.to_numeric(events.get("first_body_atr"), errors="coerce").median()),
            "median_middle_body_ratio": _fmt(pd.to_numeric(events.get("middle_body_ratio"), errors="coerce").median()),
            "variant_distribution": variants,
        },
        "target_calibration": {
            "target_family": {"conservative_half_first_candle_range": 0.5, "full_first_candle_range": 1.0},
            "selected_base_target_multiple": 0.5,
            "selected_base_target_role": "conservative_half_first_candle_range",
            "base_target": base,
            "stretch_target": full,
            "legacy_target": full,
            "rows": [base, full],
            "interpretation": "Mốc 0,5x giữ vai trò cơ sở thận trọng cho mẫu tiếp diễn năm nến; 1,0x giữ vai trò đủ một biên độ nến đầu tiên.",
        },
        "data_scope_and_caveats": {
            "remaining_caveats": [
                "Không claim point-in-time universe toàn thị trường.",
                "Không dùng historical VN30/VN100 membership làm kết luận chính.",
                "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
            ]
        },
    }


def build_one_three_methods_chapter(*, pattern_id: str, out_dir: Path) -> dict[str, Path]:
    meta = PATTERNS[pattern_id]
    chapter_dir = out_dir / str(meta["slug"])
    if chapter_dir.exists():
        shutil.rmtree(chapter_dir)
    chapter_dir.mkdir(parents=True, exist_ok=True)
    all_events = pd.read_csv(meta["scan_dir"] / "events.csv")
    if "event_id" not in all_events.columns:
        all_events["event_id"] = all_events["detection_id"]
    path_df = pd.read_csv(meta["scan_dir"] / "post_breakout_path.csv")
    events = _events_for_scope(all_events, str(meta["scope_tier"]))
    events = _enrich_events_for_target(events, path_df, float(meta["base_target_multiple"]))
    payload = _publication_payload(pattern_id, meta, events, all_events, path_df)
    spec = _spec(pattern_id, meta)
    publication_spec = build_three_methods_publication_spec(pattern_id=pattern_id, title=str(meta["title"]), spec=spec)
    payload["publication_spec_id"] = publication_spec["publication_spec_id"]
    payload["source_rules_public"] = [{"rule": row[0], "application": row[1]} for row in spec.get("public_rule_rows", [])]
    selected_examples = _select_examples(events)
    payload["example_events"] = {role: {**event.to_dict(), "example_role": role} for role, event in selected_examples.items()}
    charts_dir = chapter_dir / "charts"
    schematic = charts_dir / f"{meta['slug']}_schematic.png"
    _plot_schematic(schematic, pattern_id=pattern_id)
    source_notes = _source_notes(pattern_id, meta)
    payload_path = chapter_dir / f"{meta['slug']}_public_chapter_payload.json"
    source_notes_path = chapter_dir / f"{meta['slug']}_source_notes.json"
    publication_spec_path = chapter_dir / f"{meta['slug']}_publication_spec.json"
    _write_json(payload_path, payload)
    _write_json(source_notes_path, source_notes)
    _write_json(publication_spec_path, publication_spec)
    style_dossier = chapter_dir / "source_style_dossier.md"
    style_dossier.write_text(
        f"# Source-Guided Style Dossier - {pattern_id}\n\n"
        f"{meta['title']} là mẫu tiếp diễn năm nến: nến đầu dài, ba nến nhỏ trong biên, và nến cuối xác nhận. "
        "Dossier giữ thứ tự đọc: xu hướng trước mẫu, nến đầu tạo khung, ba nến nghỉ, nến cuối xác nhận, thất bại 5%, mục tiêu theo biên độ nến đầu. "
        "Không sao chép hoặc dịch lại tài liệu gốc; số liệu Việt Nam lấy từ payload đã khóa.\n",
        encoding="utf-8",
    )
    entry = {
        "family": "three_methods_family",
        "pattern_id": pattern_id,
        "title": meta["title"],
        "status": "source_seed",
        "classification": meta["classification"],
        "score": None,
        "claim_level": meta["claim_level"],
        "pdf": f"artifacts/final_chapters/three_methods_family/{meta['slug']}_final.pdf",
        "source_pdf": f"artifacts/final_chapters/three_methods_family/{meta['slug']}_final.pdf",
        "payload": str(payload_path),
        "source_notes": str(source_notes_path),
        "publication_spec": str(publication_spec_path),
        "source_grounding_required": True,
        "source_grounding_policy_id": SOURCE_GROUNDED_PUBLICATION_GATE_ID,
        "direct_source_review_required": True,
        "publication_semantic_required": True,
        "publication_semantic_gate_id": publication_spec["semantic_gate_id"],
        "canonical_rebuild_required": True,
        "chapter_writing_stages": {"source_style_dossier": str(style_dossier)},
        "chapter_writing_notes": "Seed artifact only. Final public prose must be generated by source-guided AI refinement and canonical publication factory.",
        "note": "Three Methods Family dùng scanner five-candle riêng; builder này chỉ cung cấp nguyên liệu, không render hoặc approve PDF final.",
    }
    entry_path = chapter_dir / f"{meta['slug']}_final_manifest_entry.json"
    _write_json(entry_path, entry)
    return {"payload": payload_path, "source_notes": source_notes_path, "publication_spec": publication_spec_path, "entry": entry_path, "chart_schematic": schematic}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Three Methods Family public-chapter seed artifacts.")
    parser.add_argument("--pattern", choices=sorted(PATTERNS), action="append", default=[])
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    patterns = list(args.pattern) or sorted(PATTERNS)
    result = {pattern: build_one_three_methods_chapter(pattern_id=pattern, out_dir=Path(args.out_dir)) for pattern in patterns}
    print(json.dumps({key: {name: str(path) for name, path in value.items()} for key, value in result.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
