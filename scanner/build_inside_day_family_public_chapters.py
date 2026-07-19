"""Build source-grounded Inside Day Family public-chapter seed artifacts.

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
from scanner.inside_day_family_publication_specs import build_inside_day_publication_spec  # noqa: E402
from scanner.publication_flow_contract import SOURCE_GROUNDED_PUBLICATION_GATE_ID  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/inside_day_family_public_chapters")
SOURCE_PDF = "references/encyclopedia-of-chart-patterns-2nbsped-9786468600-3175723993-9780471668268-0471668265_compress.pdf"


PATTERNS: dict[str, dict[str, Any]] = {
    "inside_day": {
        "slug": "inside_day",
        "title": "Inside Day",
        "subtitle": "Nến nằm trong biên độ nến trước, chờ đóng cửa xác nhận",
        "scan_dir": Path("artifacts/scanner_v2/inside_day_family/inside_day/db_active"),
        "source_chapter": "Inside Day",
        "source_name": "Inside Day",
        "scope_tier": "premium+standard",
        "classification": "hồ sơ nén biên độ rất ngắn; tham khảo hai hướng sau xác nhận đóng cửa",
        "claim_level": "đọc như mẫu hai nến: nến thứ hai nằm trọn trong nến trước, sau đó chờ đóng cửa vượt biên trong một trong hai hướng",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, Inside Day là chương nén biên độ ngắn hạn: mẫu rất phổ biến, có thể tạo nhịp đi tiếp nhanh sau xác nhận, nhưng phải đọc cùng mức kéo ngược vì tín hiệu hai nến dễ nhiễu.",
        "morphology": "Inside Day gồm một nến mẹ và một nến trong: đỉnh của nến trong thấp hơn đỉnh nến trước, đáy của nến trong cao hơn đáy nến trước. Mẫu chỉ có hiệu lực khi giá đóng cửa vượt lên trên đỉnh nến trong hoặc đóng cửa xuống dưới đáy nến trong; trước thời điểm đó, nó chỉ là trạng thái nén biên độ.",
        "role_note": "Dùng như hồ sơ nén biên độ ngắn hạn sau xác nhận; không đoán hướng trước khi có đóng cửa vượt biên.",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
    },
}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _plot_schematic(out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9.2, 3.9), dpi=180)
    x = np.array([0, 1, 2, 3])
    opens = np.array([17.3, 16.4, 16.7, 17.1])
    closes = np.array([16.7, 16.9, 17.2, 17.8])
    lows = np.array([15.4, 16.0, 16.5, 16.8])
    highs = np.array([18.5, 17.8, 17.4, 18.2])
    labels = ["", "nến trong", "xác nhận lên", "đi sau xác nhận"]
    for i, (o, c, lo, hi) in enumerate(zip(opens, closes, lows, highs)):
        color = "#1b8a5a" if c >= o else "#c44e52"
        ax.vlines(x[i], lo, hi, color="#222222", linewidth=2.0)
        ax.add_patch(Rectangle((x[i] - 0.16, min(o, c)), 0.32, max(abs(c - o), 0.06), facecolor=color, edgecolor=color, alpha=0.9))
        if labels[i]:
            ax.text(x[i], hi + 0.18, labels[i], ha="center", fontsize=8, color="#245b5a")
    ax.axhline(highs[1], color="#7A5195", linestyle="--", linewidth=1.0)
    ax.axhline(lows[1], color="#7A5195", linestyle="--", linewidth=1.0)
    ax.text(0.08, highs[1] + 0.08, "biên trên nến trong", fontsize=8, color="#7A5195")
    ax.text(0.08, lows[1] - 0.28, "biên dưới nến trong", fontsize=8, color="#7A5195")
    ax.text(x[0], lows[0] - 0.35, "nến mẹ", ha="center", fontsize=8, color="#245b5a")
    ax.axhspan(lows[1], highs[1], xmin=0.23, xmax=0.48, color="#6baed6", alpha=0.14)
    ax.set_title("Giải phẫu Inside Day", loc="left", fontsize=10)
    ax.set_ylim(min(lows) - 0.65, max(highs) + 0.75)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)


def _source_notes(pattern_id: str, meta: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": "PASS",
        "source_grounding_policy_id": SOURCE_GROUNDED_PUBLICATION_GATE_ID,
        "source_grounding_level": "publication_aligned",
        "local_source": {"pattern_key": pattern_id, "chapter": meta["source_chapter"], "name": meta["source_name"]},
        "direct_pdf_review": {
            "status": "PASS",
            "review_id": "inside_day_source_extraction_review_v1",
            "pdf_path": SOURCE_PDF,
            "book_chapter": meta["source_chapter"],
            "book_pages_checked": [996],
            "pdf_pages_checked": [1019],
            "target_rule_summary": "Inside Day is treated as a short-term range-breakout pattern; local bands use 0.5x and 1.0x of the inside-day range.",
            "review_note": "PDF gốc ghi Inside Days trong Index of Chart and Event Patterns; quy tắc vận hành chi tiết được đối chiếu từ extraction/digitized source: high của nến trong thấp hơn high nến trước, low cao hơn low nến trước, và xác nhận bằng đóng cửa vượt biên nến trong.",
        },
        "source_rules": [
            {"rule_id": "id.strict_inside_range", "short_excerpt": "high is lower than the previous day's high and the low is higher than the previous day's low", "implementation_mapping": "nến trong phải nằm hoàn toàn trong biên độ nến trước; bằng nhau thì loại"},
            {"rule_id": "id.breakout_close", "short_excerpt": "breakout when price closes above the inside day's high or below its low", "implementation_mapping": "xác nhận chỉ tính khi giá đóng cửa vượt đỉnh hoặc thủng đáy nến trong"},
            {"rule_id": "id.short_pattern", "short_excerpt": "single day pattern, can repeat", "implementation_mapping": "mẫu chỉ dài hai nến; inside day liên tiếp được ghi như biến thể chất lượng riêng"},
            {"rule_id": "id.volume_decline", "short_excerpt": "often shows declining volume", "implementation_mapping": "khối lượng co lại giúp đọc nén biên độ, nhưng không thay thế điều kiện giá"},
            {"rule_id": "id.failure_5pct", "short_excerpt": "fails to move at least 5% in breakout direction", "implementation_mapping": "thất bại được đọc bằng ngưỡng đi thuận lợi dưới 5% theo hướng xác nhận"},
            {"rule_id": "id.mother_bar_context", "short_excerpt": "range completely contained", "implementation_mapping": "vượt cả biên nến mẹ là tín hiệu xác nhận mạnh hơn, nhưng chapter vẫn neo breakout vào biên nến trong theo nguồn extraction"},
        ],
    }


def _spec(meta: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "title": meta["title"],
        "subtitle": meta["subtitle"],
        "base_target_multiple": float(meta["base_target_multiple"]),
        "base_target_label": "0,5x",
        "legacy_target_multiple": float(meta["legacy_target_multiple"]),
        "legacy_target_label": "1,0x",
        "target_unit_label": "biên độ nến trong",
        "target_focus_title": "Mốc cơ sở 0,5x",
        "target_focus_caption": "mốc 0,5x biên độ nến trong",
        "target_focus_reading": "mốc thận trọng cho mẫu rất ngắn",
        "target_full_title": "Mốc đầy đủ 1,0x",
        "target_full_reading": "mốc đủ một biên độ nến trong",
        "morphology_sentence": meta["morphology"],
        "role_note": meta["role_note"],
        "classification_sentence": meta["public_classification_sentence"],
        "headline_scope": "Inside Day là mẫu hai nến, nên chương đọc nó như trạng thái nén ngắn hạn sau xác nhận đóng cửa, không như một cấu trúc hình học dài ngày.",
        "local_source_chapter": meta["source_chapter"],
        "schematic_caption": "Sơ đồ minh họa Inside Day: nến trong nằm trọn trong nến mẹ, sau đó chờ đóng cửa vượt một trong hai biên của nến trong.",
        "how_subtitle": "Nến mẹ, nến trong, rồi đóng cửa xác nhận.",
        "labels": {"favorable_move": "mức đi thuận lợi", "adverse_move": "mức kéo ngược bất lợi"},
        "source_rule_ids": ["id.strict_inside_range", "id.breakout_close", "id.short_pattern", "id.volume_decline", "id.failure_5pct"],
        "public_rule_rows": [
            ["Nến trong phải nằm trọn trong nến trước.", "Đỉnh nến trong thấp hơn đỉnh nến trước và đáy nến trong cao hơn đáy nến trước; trường hợp bằng nhau bị loại."],
            ["Mẫu chỉ được xác nhận bằng đóng cửa.", "Giá phải đóng cửa vượt đỉnh nến trong hoặc đóng cửa thủng đáy nến trong; xuyên trong phiên không đủ."],
            ["Không đoán hướng trước xác nhận.", "Inside Day là trạng thái nén; hướng đọc đến từ phiên phá vỡ lên hoặc xuống."],
            ["Inside Day liên tiếp là biến thể riêng.", "Nhiều nến trong liên tục được ghi nhận như nhóm nén chặt hơn, không gộp lẫn với inside day đơn."],
            ["Khối lượng co lại là tín hiệu phụ.", "Volume thấp hơn trung bình làm trạng thái nén đáng tin hơn, nhưng không thay thế hình học và đóng cửa xác nhận."],
            ["Mục tiêu theo biên độ nến trong.", "Mốc 0,5x dùng để đọc thận trọng; mốc 1,0x giữ vai trò đủ một biên độ nến trong."],
        ],
        "quick_question_rows": [
            ["Hình thái", "Nến trong có nằm hoàn toàn trong biên độ nến trước không?"],
            ["Xác nhận", "Giá có đóng cửa vượt đỉnh hoặc thủng đáy nến trong không?"],
            ["Bối cảnh", "Trước mẫu có xu hướng hoặc lực nén đủ rõ không?"],
            ["Đường đi sau đó", "Mốc 0,5x biên độ nến trong có đến trước kéo ngược 5% không?"],
        ],
        "component_rows": [
            ["Nến mẹ", "Nến trước tạo biên trên và biên dưới cho mẫu.", "Khung tham chiếu"],
            ["Nến trong", "Nến sau nằm trọn trong nến mẹ.", "Nén biên độ"],
            ["Phiên xác nhận", "Đóng cửa vượt một biên của nến trong.", "Không đoán trước hướng"],
            ["Đường đi sau đó", "Đo mức đi thuận lợi, kéo ngược và thời gian đạt mục tiêu.", "Kiểm chứng sau xác nhận"],
        ],
        "reject_bullets": [
            "High hoặc low của nến trong bằng biên nến trước.",
            "Chỉ xuyên biên trong phiên nhưng đóng cửa không vượt.",
            "Biên độ nến trong quá rộng, không còn là trạng thái nén.",
            "Không đủ dữ liệu hậu phá vỡ để đo đường đi sau xác nhận.",
        ],
        "identification_paragraphs": [meta["morphology"]],
        "example_intro": ["Ba ví dụ dưới đây minh họa Inside Day như một case study ngắn: một mẫu đạt mốc cơ sở, một mẫu gần trung vị và một mẫu thất bại. Điểm cần nhìn là nến mẹ, nến trong, đường đóng cửa xác nhận và đường đi sau đó."],
        "failure_bullets": [
            "Thất bại 5% là mẫu không đi đủ xa sau xác nhận, không phải stop-loss thực chiến.",
            "Vì Inside Day rất ngắn, tín hiệu sai thường đến nhanh nếu giá quay ngược trở lại vùng nén.",
            "Tỷ lệ đạt mục tiêu cao không đủ nếu đường đi sau đó kéo ngược sâu hoặc nhiễu mạnh.",
        ],
        "target_paragraph": "Mục tiêu được đo theo biên độ nến trong: 0,5x là mốc cơ sở thận trọng cho mẫu hai nến, 1,0x là mốc đầy đủ để so sánh toàn bộ chapter.",
        "quick_conclusion_rows": [
            ["Mẫu này dùng để đọc gì?", "Trạng thái nén biên độ ngắn hạn sau khi giá đóng cửa vượt biên."],
            ["Mốc đọc chính?", "0,5x biên độ nến trong."],
            ["Mốc tham chiếu?", "1,0x biên độ nến trong."],
            ["Khi nào thận trọng?", "Khi nến trong không đủ hẹp, không có nến đóng cửa xác nhận, hoặc kéo ngược sau xác nhận quá nhanh."],
        ],
        "identification_bridge": (
            "Các quy tắc nhận diện nên được đọc theo thứ tự rất chặt: trước hết nến trong phải nằm hoàn toàn trong nến mẹ, "
            "sau đó mới chờ đóng cửa vượt biên, rồi cuối cùng mới đo đường đi sau xác nhận. Nếu đảo thứ tự này, người đọc dễ biến một ngày dao động hẹp bình thường thành tín hiệu."
        ),
        "caveat_bullets": [
            "Không tuyên bố đây là nghiên cứu toàn thị trường đúng từng ngày lịch sử.",
            "Không dùng historical VN30/VN100 membership làm kết luận chính.",
            "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
            "Chương là tài liệu tham khảo hậu xác nhận, không phải khuyến nghị mua bán.",
        ],
        "quantile_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên"),
            ("Biên độ nến trong", "inside_range_pct", "%"),
            ("Tỷ lệ nến trong/nến mẹ", "range_ratio", "lần"),
            ("Biên độ nến mẹ", "mother_range_pct", "%"),
            ("Xu hướng trước mẫu", "prior_trend_pct", "%"),
            ("Mức đi thuận lợi", "mfe_pct", "%"),
            ("Mức kéo ngược bất lợi", "mae_pct", "%"),
            ("Ngày chạm mốc cơ sở", "days_to_target", "phiên"),
        ],
        "skip_condition_specs": [
            ("Nến trong quá rộng", "range_ratio", "q75", None, "Mẫu ít còn tính nén nếu biên độ gần bằng nến mẹ."),
            ("Xu hướng trước mẫu quá yếu", "prior_trend_pct", "q25_abs", None, "Thiếu lực trước mẫu làm phá vỡ dễ trở thành nhiễu."),
            ("Không vượt biên nến mẹ", "mother_bar_breakout", "==", False, "Đóng cửa chỉ vượt nến trong nhưng chưa vượt nến mẹ là xác nhận yếu hơn."),
            ("Kéo ngược quá sâu", "mae_pct", "q75", None, "Đường đi sau xác nhận không còn gọn."),
        ],
        "general_stat_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên", "Inside Day là mẫu hai nến."),
            ("Biên độ nến trong", "inside_range_pct", "%", "Biên độ này là thước đo target."),
            ("Tỷ lệ nến trong/nến mẹ", "range_ratio", "lần", "Càng thấp càng thể hiện nén rõ hơn."),
            ("Tỷ lệ co khối lượng", "volume_ratio_20", "lần", "Co volume giúp đọc trạng thái nén."),
        ],
        "best_condition_specs": [
            ("Nhóm hình thái tốt", "publication_quality_tier", "==", "premium", "Nến trong hẹp, có bối cảnh trước mẫu và xác nhận mạnh hơn."),
            ("Nhóm chuẩn", "publication_quality_tier", "==", "standard", "Đủ dùng trong thống kê nhưng không nhất thiết là ví dụ đẹp."),
            ("Đường giá sạch", "path_quality_bucket", "==", "clean", "Ít thiếu phiên và ít chuỗi đứng giá."),
            ("Thanh khoản tốt hơn", "liquidity_bucket", "in", "mid/high", "Giảm nhiễu ở các mẫu quá ngắn."),
        ],
        "conclusion_bullets": [
            "Inside Day là mẫu nén biên độ rất ngắn, không phải cấu trúc hình học dài.",
            "Mục tiêu theo biên độ nến trong; chương dùng 0,5x làm mốc cơ sở và 1,0x làm mốc đầy đủ.",
            meta["role_note"],
        ],
    }


def _publication_payload(pattern_id: str, meta: Mapping[str, Any], events: pd.DataFrame, all_events: pd.DataFrame, path_df: pd.DataFrame) -> dict[str, Any]:
    base = _metric_for_target(events, path_df, 0.5, "conservative_half_inside_range")
    full = _metric_for_target(events, path_df, 1.0, "full_inside_range")
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
            "median_range_ratio": _fmt(pd.to_numeric(events.get("range_ratio"), errors="coerce").median()),
            "median_inside_range_pct": _fmt(pd.to_numeric(events.get("inside_range_pct"), errors="coerce").median()),
            "variant_distribution": variants,
        },
        "target_calibration": {
            "target_family": {"conservative_half_inside_range": 0.5, "full_inside_range": 1.0},
            "selected_base_target_multiple": 0.5,
            "selected_base_target_role": "conservative_half_inside_range",
            "base_target": base,
            "stretch_target": full,
            "legacy_target": full,
            "rows": [base, full],
            "interpretation": "Mốc 0,5x giữ vai trò cơ sở thận trọng cho mẫu hai nến; 1,0x giữ vai trò đủ một biên độ nến trong.",
        },
        "data_scope_and_caveats": {
            "remaining_caveats": [
                "Không claim point-in-time universe toàn thị trường.",
                "Không dùng historical VN30/VN100 membership làm kết luận chính.",
                "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
            ]
        },
    }


def build_one_inside_day_chapter(*, pattern_id: str, out_dir: Path) -> dict[str, Path]:
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
    spec = _spec(meta)
    publication_spec = build_inside_day_publication_spec(pattern_id=pattern_id, title=str(meta["title"]), spec=spec)
    payload["publication_spec_id"] = publication_spec["publication_spec_id"]
    payload["source_rules_public"] = [{"rule": row[0], "application": row[1]} for row in spec.get("public_rule_rows", [])]
    selected_examples = _select_examples(events)
    payload["example_events"] = {role: {**event.to_dict(), "example_role": role} for role, event in selected_examples.items()}
    charts_dir = chapter_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    schematic = charts_dir / "inside_day_schematic.png"
    _plot_schematic(schematic)
    source_notes = _source_notes(pattern_id, meta)
    payload_path = chapter_dir / f"{meta['slug']}_public_chapter_payload.json"
    source_notes_path = chapter_dir / f"{meta['slug']}_source_notes.json"
    publication_spec_path = chapter_dir / f"{meta['slug']}_publication_spec.json"
    _write_json(payload_path, payload)
    _write_json(source_notes_path, source_notes)
    _write_json(publication_spec_path, publication_spec)
    style_dossier = chapter_dir / "source_style_dossier.md"
    style_dossier.write_text(
        "# Source-Guided Style Dossier - inside_day\n\n"
        "Inside Day là mẫu hai nến: nến sau nằm hoàn toàn trong biên độ nến trước, rồi chỉ có hiệu lực khi đóng cửa vượt một biên của nến trong. "
        "Dossier giữ thứ tự đọc: nến mẹ, nến trong, đóng cửa xác nhận, thất bại 5%, mục tiêu theo biên độ nến trong và cách dùng thận trọng. "
        "Không sao chép hoặc dịch lại tài liệu gốc; số liệu Việt Nam lấy từ payload đã khóa.\n",
        encoding="utf-8",
    )
    entry = {
        "family": "inside_day_family",
        "pattern_id": pattern_id,
        "title": meta["title"],
        "status": "source_seed",
        "classification": meta["classification"],
        "score": None,
        "claim_level": meta["claim_level"],
        "pdf": f"artifacts/final_chapters/inside_day_family/{meta['slug']}_final.pdf",
        "source_pdf": f"artifacts/final_chapters/inside_day_family/{meta['slug']}_final.pdf",
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
        "note": "Inside Day Family dùng scanner two-bar riêng; builder này chỉ cung cấp nguyên liệu, không render hoặc approve PDF final.",
    }
    entry_path = chapter_dir / f"{meta['slug']}_final_manifest_entry.json"
    _write_json(entry_path, entry)
    return {"payload": payload_path, "source_notes": source_notes_path, "publication_spec": publication_spec_path, "entry": entry_path, "chart_schematic": schematic}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Inside Day Family public-chapter seed artifacts.")
    parser.add_argument("--pattern", choices=sorted(PATTERNS), default="inside_day")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    result = build_one_inside_day_chapter(pattern_id=str(args.pattern), out_dir=Path(args.out_dir))
    print(json.dumps({key: str(value) for key, value in result.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
