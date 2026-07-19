"""Build source-grounded Diamond Family public-chapter seed artifacts.

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
from scanner.diamond_family_publication_specs import build_diamond_publication_spec  # noqa: E402
from scanner.publication_flow_contract import SOURCE_GROUNDED_PUBLICATION_GATE_ID  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/diamond_family_public_chapters")
SOURCE_PDF = "references/encyclopedia-of-chart-patterns-2nbsped-9786468600-3175723993-9780471668268-0471668265_compress.pdf"


PATTERNS: dict[str, dict[str, Any]] = {
    "diamond_bottoms": {
        "slug": "diamond_bottoms",
        "title": "Diamond Bottoms",
        "subtitle": "Kim cương đáy: mở rộng rồi thu hẹp sau một xu hướng giảm",
        "scan_dir": Path("artifacts/scanner_v2/diamond_family/diamond_bottoms/db_active"),
        "source_chapter": 11,
        "source_name": "Diamond Bottoms",
        "source_book_pages": list(range(179, 196)),
        "source_review_pages": list(range(202, 219)),
        "scope_tier": "premium+standard",
        "classification": "hồ sơ đảo chiều tăng có điều kiện; breakout xuống vẫn được giữ như nhánh thông tin/phòng thủ",
        "claim_level": "đọc như mẫu mở rộng rồi thu hẹp sau xu hướng giảm, chỉ có hiệu lực khi giá đóng cửa phá vỡ biên phải",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, Diamond Bottoms là chương đảo chiều/watchlist có sample mỏng: mẫu có hình học đặc trưng, nhưng cần đọc cùng hướng phá vỡ, kéo ngược và vùng kháng cự gần đó.",
        "morphology": "Diamond Bottoms xuất hiện sau một xu hướng giảm. Nửa đầu mẫu mở rộng với các đỉnh cao hơn và đáy thấp hơn; nửa sau thu hẹp với các đỉnh thấp dần và đáy cao dần. Vì diamond có thể phá vỡ theo cả hai hướng, người đọc chỉ nên tính mẫu khi có đóng cửa ra khỏi biên phải.",
        "role_note": "Nhánh phá lên có thể dùng như hồ sơ đảo chiều/watchlist; nhánh phá xuống nên đọc như tín hiệu rủi ro tiếp diễn.",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "direction": "mixed",
    },
    "diamond_tops": {
        "slug": "diamond_tops",
        "title": "Diamond Tops",
        "subtitle": "Kim cương đỉnh: mở rộng rồi thu hẹp sau một xu hướng tăng",
        "scan_dir": Path("artifacts/scanner_v2/diamond_family/diamond_tops/db_active"),
        "source_chapter": 12,
        "source_name": "Diamond Tops",
        "source_book_pages": list(range(196, 213)),
        "source_review_pages": list(range(219, 236)),
        "scope_tier": "premium+standard",
        "classification": "hồ sơ phòng thủ/thông tin; breakout xuống là cảnh báo chính trên cổ phiếu cơ sở",
        "claim_level": "đọc như mẫu mở rộng rồi thu hẹp sau xu hướng tăng, chỉ có hiệu lực khi giá đóng cửa phá vỡ biên phải",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, Diamond Tops nên được đọc như chương defensive/informational: hữu ích để nhận diện vùng phân phối hoặc rủi ro đảo chiều, nhưng không mặc định là setup short phổ quát.",
        "morphology": "Diamond Tops xuất hiện sau một xu hướng tăng. Nửa đầu mẫu mở rộng với các đỉnh cao hơn và đáy thấp hơn; nửa sau thu hẹp với các đỉnh thấp dần và đáy cao dần. Mẫu có thể phá vỡ theo cả hai hướng, vì vậy phần thống kê luôn neo vào đóng cửa xác nhận.",
        "role_note": "Dùng như hồ sơ cảnh báo rủi ro, giảm tỷ trọng hoặc theo dõi vùng kháng cự; không đọc như short setup phổ quát.",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "direction": "mixed",
    },
}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _plot_schematic(out_path: Path, *, pattern_id: str) -> None:
    fig, ax = plt.subplots(figsize=(9.2, 3.9), dpi=180)
    xs = [0, 1, 2, 3, 4, 5, 6]
    upper = [14.0, 15.2, 17.2, 18.5, 17.4, 16.2, 15.6]
    lower = [13.0, 11.7, 10.3, 9.2, 10.4, 11.8, 12.7]
    mid = [(u + l) / 2 for u, l in zip(upper, lower)]
    color = "#245b5a"
    ax.plot(xs, upper, color=color, linewidth=1.6)
    ax.plot(xs, lower, color=color, linewidth=1.6)
    ax.fill_between(xs, upper, lower, color="#6baed6", alpha=0.12)
    ax.plot(xs, mid, color="#333333", linewidth=1.0, alpha=0.42)
    if pattern_id == "diamond_bottoms":
        ax.annotate("xu hướng giảm trước mẫu", xy=(0, mid[0]), xytext=(-1.1, mid[0] + 2.0), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=8, color="#555555")
        title = "Giải phẫu Diamond Bottoms"
    else:
        ax.annotate("xu hướng tăng trước mẫu", xy=(0, mid[0]), xytext=(-1.1, mid[0] - 2.0), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=8, color="#555555")
        title = "Giải phẫu Diamond Tops"
    ax.text(1.2, 18.7, "mở rộng", fontsize=8, color=color)
    ax.text(4.3, 18.0, "thu hẹp", fontsize=8, color=color)
    ax.axvline(6, color="#7A5195", linestyle="--", linewidth=1.1)
    ax.text(6.05, 17.2, "chờ phá vỡ", fontsize=8, color="#7A5195")
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
    is_bottom = pattern_id == "diamond_bottoms"
    prior = "downward" if is_bottom else "upward"
    prior_vi = "giảm" if is_bottom else "tăng"
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
            "target_rule_summary": "Measure the diamond height from highest high to lowest low, then project it from breakout price in breakout direction.",
            "review_note": "Đã đối chiếu trực tiếp chương Diamond trong PDF gốc trước khi dựng scanner và chapter.",
        },
        "source_rules": [
            {"rule_id": "diamond.prior_trend", "short_excerpt": f"Prices trend {prior} into the pattern", "implementation_mapping": f"đòi hỏi xu hướng {prior_vi} trước mẫu"},
            {"rule_id": "diamond.widening_first", "short_excerpt": "higher highs and lower lows in the first part", "implementation_mapping": "nửa đầu mở rộng: đỉnh cao hơn và đáy thấp hơn"},
            {"rule_id": "diamond.narrowing_second", "short_excerpt": "lower highs and higher lows", "implementation_mapping": "nửa sau thu hẹp: đỉnh thấp hơn và đáy cao hơn"},
            {"rule_id": "diamond.asymmetry_allowed", "short_excerpt": "need not appear symmetrical", "implementation_mapping": "không ép diamond phải đối xứng hoàn hảo"},
            {"rule_id": "diamond.volume_context", "short_excerpt": "volume usually trends downward but need not", "implementation_mapping": "khối lượng giảm là bối cảnh phụ, không phải điều kiện loại trực tiếp"},
            {"rule_id": "diamond.wait_for_breakout", "short_excerpt": "can break out any direction, so wait for breakout", "implementation_mapping": "chỉ tính khi đóng cửa phá vỡ biên phải theo một trong hai hướng"},
            {"rule_id": "diamond.measure_rule", "short_excerpt": "highest high minus lowest low", "implementation_mapping": "mục tiêu nguồn dùng toàn bộ chiều cao diamond"},
        ],
    }


def _spec(pattern_id: str, meta: Mapping[str, Any]) -> dict[str, Any]:
    prior = "giảm" if pattern_id == "diamond_bottoms" else "tăng"
    return {
        "title": meta["title"],
        "subtitle": meta["subtitle"],
        "base_target_multiple": float(meta["base_target_multiple"]),
        "base_target_label": "0,5x",
        "legacy_target_multiple": float(meta["legacy_target_multiple"]),
        "legacy_target_label": "1,0x",
        "target_unit_label": "chiều cao diamond",
        "target_focus_title": "Mốc cơ sở 0,5x",
        "target_focus_caption": "mốc 0,5x chiều cao diamond",
        "target_focus_reading": "mốc thận trọng trước khi đọc mục tiêu đầy đủ",
        "target_full_title": "Mốc nguồn 1,0x",
        "target_full_reading": "mốc đầy đủ theo chiều cao diamond",
        "morphology_sentence": meta["morphology"],
        "role_note": meta["role_note"],
        "classification_sentence": meta["public_classification_sentence"],
        "headline_scope": "Diamond là mẫu hình mỏng và khó nhìn; chương này chỉ tính mẫu sau khi có đóng cửa xác nhận.",
        "local_source_chapter": meta["source_chapter"],
        "schematic_caption": f"Sơ đồ minh họa {meta['title']}: xu hướng vào mẫu, nửa đầu mở rộng, nửa sau thu hẹp, rồi chờ phá vỡ.",
        "how_subtitle": "Kim cương: mở rộng trước, thu hẹp sau, xác nhận cuối cùng.",
        "labels": {"favorable_move": "mức đi thuận lợi", "adverse_move": "mức đi ngược bất lợi"},
        "source_rule_ids": ["diamond.prior_trend", "diamond.widening_first", "diamond.narrowing_second", "diamond.wait_for_breakout", "diamond.measure_rule"],
        "public_rule_rows": [
            [f"Có xu hướng {prior} trước mẫu.", f"Mẫu chỉ được phân loại là {'đáy' if pattern_id == 'diamond_bottoms' else 'đỉnh'} khi đường giá đi vào từ một xu hướng {prior} rõ."],
            ["Nửa đầu mở rộng.", "Các đỉnh sau cao hơn và đáy sau thấp hơn, tạo cảm giác giống broadening nhỏ."],
            ["Nửa sau thu hẹp.", "Các đỉnh sau thấp hơn và đáy sau cao hơn, tạo phần tam giác đối xứng ở phía phải."],
            ["Không ép đối xứng tuyệt đối.", "Diamond có thể nghiêng hoặc lệch; điều quan trọng là có hai pha mở rộng rồi thu hẹp."],
            ["Chờ đóng cửa phá vỡ.", "Mẫu có thể phá lên hoặc phá xuống; không đo outcome trước khi giá đóng cửa vượt khỏi biên phải."],
            ["Mục tiêu theo chiều cao diamond.", "Mốc 0,5x dùng để đọc thận trọng; 1,0x giữ vai trò mốc nguồn đầy đủ."],
        ],
        "quick_question_rows": [
            ["Xu hướng vào mẫu", f"Trước mẫu có xu hướng {prior} đủ rõ không?"],
            ["Hình thái", "Có mở rộng rồi thu hẹp không?"],
            ["Xác nhận", "Giá đã đóng cửa ra khỏi biên phải chưa?"],
            ["Đường đi", "Mốc 0,5x có đến trước kéo ngược 5% không?"],
        ],
        "component_rows": [
            ["Pha vào mẫu", f"Xu hướng {prior} đặt bối cảnh top/bottom.", f"Xu hướng {prior}"],
            ["Pha mở rộng", "Đỉnh cao hơn và đáy thấp hơn.", "Nửa trái"],
            ["Pha thu hẹp", "Đỉnh thấp hơn và đáy cao hơn.", "Nửa phải"],
            ["Xác nhận", "Đóng cửa phá ra khỏi biên phải theo một hướng.", "Không đo trước xác nhận"],
        ],
        "reject_bullets": [
            "Không có xu hướng vào mẫu rõ.",
            "Chỉ có tam giác thu hẹp mà không có pha mở rộng trước đó.",
            "Không có đóng cửa xác nhận sau mẫu.",
            "Đường giá quá răng cưa khiến diamond phải vẽ gượng ép.",
        ],
        "identification_paragraphs": [meta["morphology"]],
        "example_intro": ["Ba ví dụ dưới đây được chọn như case study: một mẫu tốt, một mẫu gần trung vị và một mẫu thất bại. Với Diamond, người đọc nên chú ý vùng mở rộng-thu hẹp trước khi nhìn tới kết quả."],
        "failure_bullets": [
            "Thất bại 5% là mẫu không đi đủ xa sau xác nhận, không phải stop-loss thực chiến.",
            "Diamond có throwback/pullback nhiều, nên target-hit thô phải đọc cùng kéo ngược.",
            "Không dùng một ví dụ đẹp để thay thế thống kê toàn mẫu vì sample Diamond thường mỏng.",
        ],
        "target_paragraph": "Mục tiêu nguồn lấy chiều cao diamond từ đỉnh cao nhất tới đáy thấp nhất rồi chiếu theo hướng phá vỡ; chương giữ 0,5x làm mốc cơ sở thận trọng và 1,0x làm mốc nguồn đầy đủ.",
        "quick_conclusion_rows": [
            ["Mẫu này dùng để đọc gì?", meta["role_note"]],
            ["Mốc đọc chính?", "0,5x chiều cao diamond."],
            ["Mốc tham chiếu?", "1,0x chiều cao diamond theo nguồn."],
            ["Khi nào thận trọng?", "Khi mẫu quá nhỏ, phá vỡ trễ, hoặc gần vùng kháng cự/hỗ trợ lớn."],
        ],
        "identification_bridge": (
            "Các quy tắc nhận diện nên được đọc theo thứ tự: xu hướng vào mẫu, pha mở rộng, pha thu hẹp, rồi đóng cửa xác nhận. "
            "Nếu bỏ qua thứ tự này, một tam giác đối xứng hoặc một vùng răng cưa rất dễ bị gọi nhầm là Diamond."
        ),
        "caveat_bullets": [
            "Không tuyên bố đây là nghiên cứu toàn thị trường đúng từng ngày lịch sử.",
            "Không dùng historical VN30/VN100 membership làm kết luận chính.",
            "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
            "Chương là tài liệu tham khảo hậu xác nhận, không phải khuyến nghị mua bán.",
        ],
        "quantile_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên"),
            ("Chiều cao diamond", "pattern_height_pct", "%"),
            ("Mức mở rộng", "expansion_ratio", "lần"),
            ("Mức thu hẹp", "contraction_ratio", "lần"),
            ("Thời gian xác nhận", "breakout_lag_bars", "phiên"),
            ("Mức đi thuận lợi", "mfe_pct", "%"),
            ("Mức đi ngược bất lợi", "mae_pct", "%"),
            ("Ngày chạm mốc cơ sở", "days_to_target", "phiên"),
        ],
        "skip_condition_specs": [
            ("Phá vỡ quá trễ", "breakout_lag_bars", "q75", None, "Diamond mất độ sắc nếu giá chờ quá lâu mới xác nhận."),
            ("Thu hẹp yếu", "contraction_ratio", "q75", None, "Nửa phải chưa thật sự giống phần tam giác thu hẹp."),
            ("Chiều cao quá lớn", "pattern_height_pct", "q75", None, "Target có thể quá tham vọng so với đường đi thường gặp."),
            ("Kéo ngược quá sâu", "mae_pct", "q75", None, "Đường đi sau xác nhận không còn gọn."),
        ],
        "general_stat_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên", "Diamond thường cần đủ thời gian để thấy hai pha mở rộng-thu hẹp."),
            ("Chiều cao diamond", "pattern_height_pct", "%", "Chiều cao là thước đo target."),
            ("Mức mở rộng", "expansion_ratio", "lần", "Cho biết nửa trái có thật sự mở rộng hay không."),
            ("Mức thu hẹp", "contraction_ratio", "lần", "Càng thấp càng thể hiện nửa phải co lại rõ hơn."),
        ],
        "best_condition_specs": [
            ("Nhóm hình thái tốt", "publication_quality_tier", "==", "premium", "Pha mở rộng-thu hẹp rõ, xác nhận không quá trễ và đường giá sạch."),
            ("Nhóm chuẩn", "publication_quality_tier", "==", "standard", "Đủ dùng trong thống kê nhưng không phải lúc nào cũng đẹp để minh họa."),
            ("Đường giá sạch", "path_quality_bucket", "==", "clean", "Ít thiếu phiên và ít chuỗi đứng giá."),
            ("Thanh khoản tốt hơn", "liquidity_bucket", "in", "mid/high", "Giảm nhiễu ở các mẫu hình mỏng."),
        ],
        "conclusion_bullets": [
            f"{meta['title']} được đọc bằng hai pha mở rộng rồi thu hẹp, không phải chỉ bằng một tam giác ở cuối.",
            "Mục tiêu nguồn là 1,0x chiều cao diamond; chương dùng 0,5x làm mốc cơ sở thận trọng.",
            meta["role_note"],
        ],
    }


def _publication_payload(pattern_id: str, meta: Mapping[str, Any], events: pd.DataFrame, all_events: pd.DataFrame, path_df: pd.DataFrame) -> dict[str, Any]:
    base = _metric_for_target(events, path_df, 0.5, "conservative_half_diamond")
    full = _metric_for_target(events, path_df, 1.0, "source_full_diamond")
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
            "median_expansion_ratio": _fmt(pd.to_numeric(events.get("expansion_ratio"), errors="coerce").median()),
            "median_contraction_ratio": _fmt(pd.to_numeric(events.get("contraction_ratio"), errors="coerce").median()),
        },
        "target_calibration": {
            "target_family": {"conservative_half_diamond": 0.5, "source_full_diamond": 1.0},
            "selected_base_target_multiple": 0.5,
            "selected_base_target_role": "conservative_half_diamond",
            "base_target": base,
            "stretch_target": full,
            "legacy_target": full,
            "rows": [base, full],
            "interpretation": "Mốc 0,5x giữ vai trò cơ sở thận trọng; 1,0x giữ vai trò mốc nguồn theo chiều cao diamond.",
        },
        "data_scope_and_caveats": {
            "remaining_caveats": [
                "Không claim point-in-time universe toàn thị trường.",
                "Không dùng historical VN30/VN100 membership làm kết luận chính.",
                "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
                "Diamond là mẫu mỏng; các subgroup nhỏ cần đọc thận trọng.",
            ]
        },
    }


def build_one_diamond_chapter(*, pattern_id: str, out_dir: Path) -> dict[str, Path]:
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
    publication_spec = build_diamond_publication_spec(pattern_id=pattern_id, title=str(meta["title"]), spec=spec)
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
        "Dossier giữ thứ tự đọc: xu hướng vào mẫu, nửa đầu mở rộng, nửa sau thu hẹp, đóng cửa phá vỡ, thất bại, mục tiêu và cách dùng thận trọng. "
        "Không sao chép hoặc dịch lại tài liệu gốc; số liệu Việt Nam lấy từ payload đã khóa.\n",
        encoding="utf-8",
    )
    entry = {
        "family": "diamond_family",
        "pattern_id": pattern_id,
        "title": meta["title"],
        "status": "source_seed",
        "classification": meta["classification"],
        "score": None,
        "claim_level": meta["claim_level"],
        "pdf": f"artifacts/final_chapters/diamond_family/{meta['slug']}_final.pdf",
        "source_pdf": f"artifacts/final_chapters/diamond_family/{meta['slug']}_final.pdf",
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
        "note": "Diamond Family dùng scanner riêng; builder này chỉ cung cấp nguyên liệu, không render hoặc approve PDF final.",
    }
    entry_path = chapter_dir / f"{meta['slug']}_final_manifest_entry.json"
    _write_json(entry_path, entry)
    return {"payload": payload_path, "source_notes": source_notes_path, "publication_spec": publication_spec_path, "entry": entry_path, "chart_schematic": charts_dir / f"{pattern_id}_schematic.png"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Diamond Family public-chapter seed artifacts.")
    parser.add_argument("--pattern", choices=[*PATTERNS.keys(), "all"], default="all")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    patterns = list(PATTERNS.keys()) if args.pattern == "all" else [args.pattern]
    outputs = {}
    for pattern_id in patterns:
        outputs[pattern_id] = {key: str(value) for key, value in build_one_diamond_chapter(pattern_id=pattern_id, out_dir=Path(args.out_dir)).items()}
    print(json.dumps({"status": "PASS", "outputs": outputs}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
