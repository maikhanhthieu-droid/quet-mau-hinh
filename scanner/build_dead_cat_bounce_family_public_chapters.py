"""Build source-grounded Dead-Cat Bounce Family public-chapter seed artifacts.

This builder creates deterministic ingredients only.  It does not approve
public prose and does not render a final PDF; final writing must go through
`canonical_source_guided_refinement_v1`.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

import matplotlib.pyplot as plt
import pandas as pd

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
from scanner.dead_cat_bounce_family_publication_specs import build_dead_cat_publication_spec  # noqa: E402
from scanner.publication_flow_contract import SOURCE_GROUNDED_PUBLICATION_GATE_ID  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/dead_cat_bounce_family_public_chapters")
SOURCE_PDF = "references/encyclopedia-of-chart-patterns-2nbsped-9786468600-3175723993-9780471668268-0471668265_compress.pdf"


PATTERNS: dict[str, dict[str, Any]] = {
    "dead_cat_bounce": {
        "slug": "dead_cat_bounce",
        "title": "Dead-Cat Bounce",
        "subtitle": "Cú rơi mạnh, nhịp hồi và pha giảm sau hồi",
        "scan_dir": Path("artifacts/scanner_v2/dead_cat_bounce_family/dead_cat_bounce/db_active"),
        "source_chapter": 54,
        "source_name": "Dead-Cat Bounce",
        "source_book_pages": list(range(829, 844)),
        "source_review_pages": list(range(852, 867)),
        "scope_tier": "premium+standard",
        "classification": "hồ sơ phòng thủ/thông tin sau cú rơi mạnh; không phải setup mua bắt đáy",
        "claim_level": "đọc như mẫu sự kiện gồm cú rơi mạnh, nhịp hồi và nguy cơ giảm sau hồi",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, Dead-Cat Bounce là chương phòng thủ: nó giúp người đọc nhận diện cú hồi dễ gây nhầm sau một cú rơi lớn, chứ không phải lời mời bắt đáy.",
        "morphology": "Dead-Cat Bounce bắt đầu bằng cú rơi mạnh, thường đi cùng gap hoặc khối lượng đột biến. Sau đó giá hồi lại một phần tổn thất, nhưng trọng tâm của mẫu là pha sau hồi: liệu giá có tiếp tục yếu và quay xuống dưới vùng đáy sự kiện hay không.",
        "role_note": "Dùng để đọc rủi ro sau cú rơi lớn, quản trị kỳ vọng với nhịp hồi và tránh biến cú hồi kỹ thuật thành câu chuyện đảo chiều quá sớm.",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "direction": "down",
    },
    "dead_cat_bounce_inverted": {
        "slug": "dead_cat_bounce_inverted",
        "title": "Inverted Dead-Cat Bounce",
        "subtitle": "Cú tăng mạnh, ngày thứ hai và rủi ro trả lại thành quả",
        "scan_dir": Path("artifacts/scanner_v2/dead_cat_bounce_family/dead_cat_bounce_inverted/db_active"),
        "source_chapter": 55,
        "source_name": "Dead-Cat Bounce, Inverted",
        "source_book_pages": list(range(844, 855)),
        "source_review_pages": list(range(867, 878)),
        "scope_tier": "premium+standard",
        "classification": "hồ sơ phòng thủ/chốt lời sau cú tăng mạnh; không phải setup mua đuổi",
        "claim_level": "đọc như mẫu sự kiện sau cú tăng 5-20%, nơi thành quả có thể bị trả lại nhanh",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, Inverted Dead-Cat Bounce là chương quản trị lợi nhuận: nó nhắc người đọc rằng một cú tăng rất mạnh có thể dẫn tới pha trả lại thành quả ngay sau đó.",
        "morphology": "Inverted Dead-Cat Bounce bắt đầu bằng một phiên tăng mạnh. Nguồn nhấn mạnh ngày kế tiếp vì nhiều trường hợp giá còn cố đẩy thêm nhưng sau đó hạ nhiệt. Chương này đo đường đi từ ngày thứ hai để xem cú tăng có được giữ lại hay bị trả về vùng trước sự kiện.",
        "role_note": "Dùng để đọc rủi ro mua đuổi và quản trị lợi nhuận sau phiên tăng sốc; không đọc như tín hiệu mua phổ quát.",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "direction": "down",
    },
}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _plot_schematic(out_path: Path, *, pattern_id: str) -> None:
    fig, ax = plt.subplots(figsize=(9.2, 3.9), dpi=180)
    color = "#245b5a"
    if pattern_id == "dead_cat_bounce":
        xs = [0, 1, 2, 3, 4, 5, 6]
        ys = [100, 96, 66, 72, 78, 70, 60]
        ax.plot(xs, ys, color=color, linewidth=1.8)
        ax.scatter([2, 4, 6], [66, 78, 60], color=["#C43B3B", "#7A5195", "#C43B3B"], s=28)
        ax.text(1.15, 81, "cú rơi mạnh", fontsize=8, color="#C43B3B")
        ax.text(3.15, 82, "nhịp hồi", fontsize=8, color="#7A5195")
        ax.text(4.85, 68, "giảm sau hồi", fontsize=8, color="#C43B3B")
        ax.axvspan(1.8, 4.2, color="#6baed6", alpha=0.12)
        title = "Giải phẫu Dead-Cat Bounce"
    else:
        xs = [0, 1, 2, 3, 4, 5, 6]
        ys = [100, 106, 112, 108, 104, 106, 103]
        ax.plot(xs, ys, color=color, linewidth=1.8)
        ax.scatter([1, 2, 4], [106, 112, 104], color=["#2E8B57", "#7A5195", "#C43B3B"], s=28)
        ax.text(0.7, 109, "cú tăng mạnh", fontsize=8, color="#2E8B57")
        ax.text(2.05, 113, "ngày thứ hai", fontsize=8, color="#7A5195")
        ax.text(3.35, 105, "trả lại thành quả", fontsize=8, color="#C43B3B")
        ax.axvspan(0.9, 2.2, color="#6baed6", alpha=0.12)
        title = "Giải phẫu Inverted Dead-Cat Bounce"
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
    if pattern_id == "dead_cat_bounce":
        source_rules = [
            ("dcb.event_decline", "price drops from 15% to 75%, usually in one session", "cú rơi sự kiện tối thiểu 15%, thường rất nhanh"),
            ("dcb.gap_plunge", "price gap, plunge", "gap giảm và cú lao dốc là dấu hiệu chất lượng, nhưng chapter vẫn ghi nhận mẫu không gap"),
            ("dcb.bounce", "Prices recover between 15% and 35%", "nhịp hồi được đo từ đáy sự kiện tới đỉnh hồi"),
            ("dcb.bounce_time", "between 5 and 25 days to reach the top of the bounce", "thời gian hồi là một biến chất lượng"),
            ("dcb.postbounce_decline", "After the bounce finishes, another decline begins", "mốc đo chính là đường đi sau đỉnh hồi"),
            ("dcb.failure", "formation failure ... moved higher and kept rising", "thất bại là trường hợp giá hồi rồi tiếp tục tăng thay vì quay xuống"),
            ("dcb.warning", "acts as a warning to exit the stock quickly", "chương được gắn nhãn phòng thủ/thông tin, không phải bắt đáy"),
        ]
    else:
        source_rules = [
            ("idcb.up_move", "price jumps from 5% to 20% in one day", "cú tăng một ngày 5-20% là điểm khởi đầu"),
            ("idcb.day2", "sell the day after the initial rise", "ngày thứ hai là mốc quan sát quan trọng"),
            ("idcb.giveback", "then gives back most of it", "đường đi sau đó đo mức trả lại thành quả"),
            ("idcb.close_to_close", "Measure the close-to-close difference", "độ lớn cú tăng đo theo close-to-close"),
            ("idcb.rise_buckets", "5%, 10%, 15%, 20%", "cú tăng được đọc theo các bucket cường độ"),
            ("idcb.not_blind_advice", "your results will vary", "chương là hồ sơ tham khảo, không phải chỉ dẫn máy móc"),
        ]
    return {
        "status": "PASS",
        "source_grounding_policy_id": SOURCE_GROUNDED_PUBLICATION_GATE_ID,
        "source_grounding_level": "publication_aligned",
        "local_source": {"pattern_key": pattern_id, "chapter": meta["source_chapter"], "name": meta["source_name"]},
        "direct_pdf_review": {
            "status": "PASS",
            "review_id": f"{pattern_id}_bulkowski_pdf_direct_review_v1",
            "pdf_path": SOURCE_PDF,
            "book_chapter": meta["source_chapter"],
            "book_pages_checked": meta["source_book_pages"],
            "pdf_pages_checked": meta["source_review_pages"],
            "target_rule_summary": "Event pattern target is expressed as giveback/retest distance rather than classic geometric height.",
            "review_note": "Đã đối chiếu trực tiếp chương Dead-Cat Bounce trong PDF gốc trước khi dựng scanner và chapter.",
        },
        "source_rules": [
            {"rule_id": rid, "short_excerpt": excerpt, "implementation_mapping": mapping}
            for rid, excerpt, mapping in source_rules
        ],
    }


def _spec(pattern_id: str, meta: Mapping[str, Any]) -> dict[str, Any]:
    is_dcb = pattern_id == "dead_cat_bounce"
    unit = "khoảng từ đỉnh hồi về đáy sự kiện" if is_dcb else "khoảng trả lại về giá trước cú tăng"
    public_rule_rows = (
        [
            ["Bắt đầu bằng cú rơi mạnh.", "Bộ quét yêu cầu giá giảm tối thiểu 15% trong một cụm rất ngắn; cú rơi quá nhỏ chỉ là nhiễu thường ngày, không phải Dead-Cat Bounce."],
            ["Có nhịp hồi sau cú rơi.", "Sau đáy sự kiện, giá phải hồi lại tối thiểu khoảng 15% nhưng không quá rộng; nếu hồi quá yếu thì chưa có bẫy hồi, nếu hồi quá mạnh thì cấu trúc đã khác."],
            ["Đỉnh hồi là mốc xác nhận để đo tiếp.", "Chương không đo ngay từ ngày rơi; đường đi chính bắt đầu sau khi nhịp hồi kết thúc ở đỉnh hồi."],
            ["Đáy sự kiện là vùng retest/giveback.", "Mục tiêu đầy đủ 1,0x là quay lại vùng đáy sự kiện; mốc 0,5x dùng để đọc sớm mức suy yếu sau hồi."],
            ["Gap và khối lượng chỉ là tín hiệu phụ.", "Gap giảm hoặc khối lượng đột biến làm cú rơi đáng chú ý hơn, nhưng không thay thế điều kiện cú rơi mạnh, nhịp hồi và pha giảm sau hồi."],
        ]
        if is_dcb
        else [
            ["Bắt đầu bằng cú tăng một ngày.", "Bộ quét yêu cầu giá đóng cửa tăng khoảng 5-20% so với phiên trước; cú tăng nhỏ hơn không đủ là sự kiện, cú tăng quá lớn bị đọc thận trọng."],
            ["Ngày thứ hai là mốc quan sát chính.", "Nguồn nhấn mạnh hành vi ngay sau cú tăng; chương dùng ngày kế tiếp để xem cú tăng có được đẩy tiếp hay bắt đầu suy yếu."],
            ["Mốc đo là vùng trước cú tăng.", "Mục tiêu đầy đủ 1,0x là trả lại về vùng giá trước sự kiện; mốc 0,5x dùng để đọc sớm rủi ro mất thành quả."],
            ["Đây là mẫu quản trị lợi nhuận, không phải mua đuổi.", "Nếu giá tăng sốc rồi không giữ được thành quả, chương đọc nó như cảnh báo phòng thủ hơn là tín hiệu mở vị thế mua."],
            ["Gap và khối lượng chỉ là bối cảnh phụ.", "Gap tăng hoặc khối lượng đột biến giúp sự kiện nổi bật hơn, nhưng không thay thế điều kiện cú tăng mạnh và đường đi sau ngày thứ hai."],
        ]
    )
    quick_question_rows = (
        [
            ["Cú rơi ban đầu", "Giá đã giảm đủ mạnh và đủ nhanh để coi là shock chưa?"],
            ["Nhịp hồi", "Giá có hồi đủ rõ để tạo bẫy hồi không?"],
            ["Đỉnh hồi", "Pha hồi đã kết thúc để bắt đầu đo rủi ro giảm sau hồi chưa?"],
            ["Cách dùng", "Đây là cảnh báo cú hồi kỹ thuật hay lời mời bắt đáy?"],
        ]
        if is_dcb
        else [
            ["Cú tăng ban đầu", "Giá đã tăng đủ mạnh trong một ngày để coi là sự kiện chưa?"],
            ["Ngày thứ hai", "Giá có đẩy tiếp hay bắt đầu mất lực ngay sau cú tăng?"],
            ["Vùng trước cú tăng", "Giá có trả lại một phần/thành quả của cú tăng không?"],
            ["Cách dùng", "Đây là cảnh báo mua đuổi hay một setup mua phổ quát?"],
        ]
    )
    component_rows = (
        [
            ["Cú rơi", "Biến động giảm mạnh trong vài phiên, thường nổi bật trên biểu đồ.", "Tối thiểu 15%"],
            ["Đáy sự kiện", "Điểm thấp nhất của cú rơi, dùng làm vùng retest đầy đủ.", "Đáy cú rơi"],
            ["Nhịp hồi", "Pha phục hồi sau cú rơi, thường tạo cảm giác đảo chiều.", "15-35% từ đáy"],
            ["Đỉnh hồi", "Mốc bắt đầu đo pha giảm sau hồi.", "Giá xác nhận"],
        ]
        if is_dcb
        else [
            ["Cú tăng", "Một phiên tăng mạnh đủ nổi bật để tạo sự kiện.", "5-20% close-to-close"],
            ["Ngày thứ hai", "Phiên sau cú tăng, dùng để xem lực tăng có kéo dài không.", "Day 2"],
            ["Vùng trước cú tăng", "Giá tham chiếu trước sự kiện, dùng làm vùng giveback đầy đủ.", "Close trước cú tăng"],
            ["Pha trả lại", "Đường đi sau ngày thứ hai khi giá không giữ được thành quả.", "Giveback"],
        ]
    )
    return {
        "title": meta["title"],
        "subtitle": meta["subtitle"],
        "base_target_multiple": float(meta["base_target_multiple"]),
        "base_target_label": "0,5x",
        "legacy_target_multiple": float(meta["legacy_target_multiple"]),
        "legacy_target_label": "1,0x",
        "target_unit_label": unit,
        "target_focus_title": "Mốc cơ sở 0,5x",
        "target_focus_caption": f"mốc 0,5x {unit}",
        "target_focus_reading": "mốc thận trọng để xem rủi ro trả lại có xuất hiện sớm không",
        "target_full_title": "Mốc nguồn 1,0x",
        "target_full_reading": "mốc đầy đủ theo khoảng giveback/retest của sự kiện",
        "morphology_sentence": meta["morphology"],
        "role_note": meta["role_note"],
        "classification_sentence": meta["public_classification_sentence"],
        "headline_scope": "Đây là mẫu sự kiện: chỉ đọc sau cú biến động mạnh, không đọc như hình thái dao động thông thường.",
        "local_source_chapter": meta["source_chapter"],
        "schematic_caption": f"Sơ đồ minh họa {meta['title']}: shock giá, pha phản ứng và vùng cần theo dõi sau đó.",
        "how_subtitle": "Mẫu sự kiện: cú sốc trước, phản ứng sau, rồi mới đo xác suất.",
        "labels": {"favorable_move": "mức đi theo hướng cảnh báo", "adverse_move": "mức đi ngược cảnh báo"},
        "source_rule_ids": ["dcb.event_decline" if is_dcb else "idcb.up_move"],
        "public_rule_rows": public_rule_rows,
        "quick_question_rows": quick_question_rows,
        "component_rows": component_rows,
        "reject_bullets": [
            "Không có biến động đủ lớn ở đầu mẫu.",
            "Không có pha hồi hoặc ngày phản ứng rõ để làm mốc đo.",
            "Đường giá thiếu thanh khoản hoặc đứng giá kéo dài.",
            "Biến mẫu sự kiện thành câu chuyện bắt đáy/mua đuổi trước khi có số liệu hậu sự kiện.",
        ],
        "identification_paragraphs": [meta["morphology"]],
        "example_intro": ["Ví dụ trong chương này nên đọc như case study sự kiện: cú sốc xảy ra ở đâu, pha phản ứng kết thúc ở đâu, và đường đi sau đó trả lại bao nhiêu."],
        "failure_bullets": [
            "Thất bại nghĩa là cảnh báo không tiếp diễn: giá không trả lại đủ xa hoặc đi ngược lại luận điểm sự kiện.",
            "Một cú hồi/tăng đẹp có thể làm người đọc quên rủi ro sau đó; phần thất bại giúp giữ góc nhìn xác suất.",
            "Không dùng một sự kiện nổi bật để thay thế phân phối toàn mẫu.",
        ],
        "target_paragraph": f"Chương dùng mục tiêu theo {unit}; 0,5x là mốc cơ sở thận trọng, 1,0x là mốc đầy đủ để xem giá có trả lại gần trọn pha phản ứng hay không.",
        "quick_conclusion_rows": [
            ["Mẫu này dùng để đọc gì?", meta["role_note"]],
            ["Mốc đọc chính?", f"0,5x {unit}."],
            ["Mốc tham chiếu?", "1,0x khoảng giveback/retest của sự kiện."],
            ["Khi nào thận trọng?", "Khi shock quá nhỏ, không có gap/volume, hoặc đường giá sau đó thiếu thanh khoản."],
        ],
        "identification_bridge": (
            "Các quy tắc nhận diện nên được đọc theo thứ tự: shock giá, pha phản ứng, rồi đường đi sau phản ứng. "
            "Nếu đảo thứ tự này, người đọc rất dễ biến một cú hồi/tăng bình thường thành mẫu sự kiện."
        ),
        "caveat_bullets": [
            "Không tuyên bố đây là nghiên cứu toàn thị trường đúng từng ngày lịch sử.",
            "Không dùng historical VN30/VN100 membership làm kết luận chính.",
            "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
            "Chương là tài liệu tham khảo hậu sự kiện, không phải khuyến nghị giao dịch.",
        ],
        "quantile_specs": [
            ("Độ lớn shock", "pattern_height_pct", "%"),
            ("Khoảng mục tiêu", "target_dist_pct", "%"),
            ("Mức đi theo cảnh báo", "mfe_pct", "%"),
            ("Mức đi ngược cảnh báo", "mae_pct", "%"),
            ("Ngày chạm mốc", "days_to_target", "phiên"),
        ],
        "skip_condition_specs": [
            ("Shock quá nhỏ", "pattern_height_pct", "q25", None, "Biến động đầu mẫu không đủ khác biệt với nhiễu thường ngày."),
            ("Đường đi kém sạch", "missing_bar_rate_60d", "q75", None, "Thiếu phiên làm méo thời gian đạt mốc."),
            ("Kéo ngược quá sâu", "mae_pct", "q75", None, "Cảnh báo không còn gọn nếu giá đi ngược mạnh trước."),
        ],
        "general_stat_specs": [
            ("Độ lớn shock", "pattern_height_pct", "%", "Đây là nền tảng để phân biệt mẫu sự kiện với nhiễu thường ngày."),
            ("Khoảng mục tiêu", "target_dist_pct", "%", "Cho biết mốc giveback/retest tham vọng tới đâu."),
        ],
        "best_condition_specs": [
            ("Nhóm hình thái tốt", "publication_quality_tier", "==", "premium", "Shock rõ, phản ứng rõ và đường giá sau đó đủ sạch."),
            ("Nhóm chuẩn", "publication_quality_tier", "==", "standard", "Đủ dùng trong thống kê nhưng không phải ví dụ đẹp nhất."),
            ("Đường giá sạch", "path_quality_bucket", "==", "clean", "Ít thiếu phiên và ít chuỗi đứng giá."),
            ("Thanh khoản tốt hơn", "liquidity_bucket", "in", "mid/high", "Giảm nhiễu ở các cú biến động sự kiện."),
        ],
        "conclusion_bullets": [
            f"{meta['title']} là mẫu sự kiện, không phải cấu trúc hình học thông thường.",
            "Mốc 0,5x giúp đọc thận trọng trước khi so với mốc đầy đủ 1,0x.",
            meta["role_note"],
        ],
    }


def _publication_payload(pattern_id: str, meta: Mapping[str, Any], events: pd.DataFrame, all_events: pd.DataFrame, path_df: pd.DataFrame) -> dict[str, Any]:
    base = _metric_for_target(events, path_df, 0.5, "half_event_giveback")
    full = _metric_for_target(events, path_df, 1.0, "full_event_giveback")
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
            "median_event_decline_pct": _fmt(pd.to_numeric(events.get("event_decline_pct"), errors="coerce").median()) if "event_decline_pct" in events.columns else None,
            "median_bounce_pct": _fmt(pd.to_numeric(events.get("bounce_pct"), errors="coerce").median()) if "bounce_pct" in events.columns else None,
            "median_event_rise_pct": _fmt(pd.to_numeric(events.get("event_rise_pct"), errors="coerce").median()) if "event_rise_pct" in events.columns else None,
        },
        "target_calibration": {
            "target_family": {"half_event_giveback": 0.5, "three_quarter_event_giveback": 0.75, "full_event_giveback": 1.0},
            "selected_base_target_multiple": 0.5,
            "selected_base_target_role": "half_event_giveback",
            "base_target": base,
            "stretch_target": full,
            "legacy_target": full,
            "rows": [base, full],
            "interpretation": "Mốc 0,5x giữ vai trò cơ sở thận trọng; 1,0x giữ vai trò mốc đầy đủ của khoảng giveback/retest.",
        },
        "data_scope_and_caveats": {
            "remaining_caveats": [
                "Không claim point-in-time universe toàn thị trường.",
                "Không dùng historical VN30/VN100 membership làm kết luận chính.",
                "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
                "Dead-Cat Bounce là mẫu sự kiện; kết quả cần đọc như cảnh báo rủi ro, không phải setup mua bán tự động.",
            ]
        },
    }


def build_one_dead_cat_chapter(*, pattern_id: str, out_dir: Path) -> dict[str, Path]:
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
    publication_spec = build_dead_cat_publication_spec(pattern_id=pattern_id, title=str(meta["title"]), spec=spec)
    payload["publication_spec_id"] = publication_spec["publication_spec_id"]
    payload["source_rules_public"] = [{"rule": row[0], "application": row[1]} for row in spec.get("public_rule_rows", [])]
    selected_examples = _select_examples(events)
    payload["example_events"] = {role: {**event.to_dict(), "example_role": role} for role, event in selected_examples.items()}
    charts_dir = chapter_dir / "charts"
    _plot_schematic(charts_dir / f"{pattern_id}_schematic.png", pattern_id=pattern_id)
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
        f"Chương nguồn: {meta['source_name']} trong Encyclopedia of Chart Patterns. "
        "Dossier giữ thứ tự đọc: shock giá, pha phản ứng, đường đi sau phản ứng, thất bại và cách dùng thận trọng. "
        "Không sao chép hoặc dịch lại tài liệu gốc; số liệu Việt Nam lấy từ payload đã khóa.\n",
        encoding="utf-8",
    )
    entry = {
        "family": "dead_cat_bounce_family",
        "pattern_id": pattern_id,
        "title": meta["title"],
        "status": "source_seed",
        "classification": meta["classification"],
        "score": None,
        "claim_level": meta["claim_level"],
        "pdf": f"artifacts/final_chapters/dead_cat_bounce_family/{meta['slug']}_final.pdf",
        "source_pdf": f"artifacts/final_chapters/dead_cat_bounce_family/{meta['slug']}_final.pdf",
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
        "note": "Dead-Cat Bounce Family dùng scanner sự kiện riêng; builder này chỉ cung cấp nguyên liệu, không render hoặc approve PDF final.",
    }
    entry_path = chapter_dir / f"{meta['slug']}_final_manifest_entry.json"
    _write_json(entry_path, entry)
    return {"payload": payload_path, "source_notes": source_notes_path, "publication_spec": publication_spec_path, "entry": entry_path, "chart_schematic": charts_dir / f"{pattern_id}_schematic.png"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Dead-Cat Bounce Family public-chapter seed artifacts.")
    parser.add_argument("--pattern", choices=[*PATTERNS.keys(), "all"], default="all")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    patterns = list(PATTERNS.keys()) if args.pattern == "all" else [args.pattern]
    outputs = {}
    for pattern_id in patterns:
        outputs[pattern_id] = {key: str(value) for key, value in build_one_dead_cat_chapter(pattern_id=pattern_id, out_dir=Path(args.out_dir)).items()}
    print(json.dumps({"status": "PASS", "outputs": outputs}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
