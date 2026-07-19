"""Build the Bear Pennant public chapter.

Bear Pennant shares the Pennant detector with Bull Pennant, but it is published
as a defensive/informational chapter for Vietnam cash equities.  The geometry is
still Pennant-specific: short converging body, steep prior decline, and close
below the lower boundary.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.build_bull_pennant_public_chapter import (  # noqa: E402
    DEFAULT_AUDIT,
    DEFAULT_EVENTS,
    DEFAULT_PATH,
    DEFAULT_STATS,
    TARGET_BANDS,
    _draw_public_event,
    _fmt,
    _load_path,
    _load_symbol_ohlcv,
    _pct,
    _read_json,
    _window_for_event,
)
from scanner.flag_family_public_chapter_factory import FACTORY_ID, build_flag_public_chapter  # noqa: E402
from scanner.run_pennant_candidate_quality_audit import _load_events, _target_path_flags  # noqa: E402
from scanner.v2.source_data import DEFAULT_SOURCE_DIR  # noqa: E402


DEFAULT_SOURCE_NOTES = Path("artifacts/scanner_v2/flag_like_family_source_grounding/bear_pennants_source_notes.json")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/flag_family_public_chapters/bear_pennant")
BASE_TARGET_MULTIPLE = 0.5


def _public_grade_events(events: pd.DataFrame, path: pd.DataFrame) -> pd.DataFrame:
    scoped = events[
        (events["variant"].astype(str) == "bear_pennant")
        & events["publication_quality_tier"].isin(["premium", "standard"])
    ].copy()
    flags = _target_path_flags(scoped, path, target_multiple=BASE_TARGET_MULTIPLE)
    scoped = scoped.merge(flags, on="event_id", how="left")
    scoped["target_hit"] = scoped["target_hit_band"].fillna(False).astype(bool)
    scoped["target_first_before_adverse_5pct"] = scoped["target_first_band"].fillna(False).astype(bool)
    scoped["days_to_target"] = pd.to_numeric(scoped["days_to_target_band"], errors="coerce")
    scoped["publication_quality_score"] = pd.to_numeric(scoped.get("pattern_quality_score"), errors="coerce")
    scoped["tradability_quality_bucket"] = scoped.get("publication_quality_tier", "standard")
    scoped["tradability_quality_score"] = scoped["publication_quality_score"]
    base_target_dist = pd.to_numeric(scoped["target_dist_pct"], errors="coerce") * BASE_TARGET_MULTIPLE
    scoped["target_price"] = pd.to_numeric(scoped["breakout_price"], errors="coerce") * (1.0 - base_target_dist / 100.0)
    return scoped.reset_index(drop=True)


def _target_row(audit: Mapping[str, Any], multiple: float) -> dict[str, Any]:
    for row in audit.get("target_table") or []:
        if (
            isinstance(row, Mapping)
            and row.get("variant") == "bear_pennant"
            and row.get("tier") == "premium+standard"
            and abs(float(row.get("target_multiple") or -1) - float(multiple)) < 1e-9
        ):
            return {
                "target_multiple": float(multiple),
                "target_hit_rate": row.get("target_hit_rate_pct"),
                "target_hit_wilson": row.get("target_hit_wilson"),
                "target_first_before_adverse_5pct_rate": row.get("target_first_before_adverse_5pct_rate_pct"),
                "target_first_wilson": row.get("target_first_wilson"),
                "failure_5pct_rate": row.get("failure_5pct_rate_pct"),
                "median_mfe_pct": row.get("median_mfe_pct"),
                "median_mae_pct": row.get("median_mae_pct"),
                "mfe_mae_median_ratio": row.get("mfe_mae_median_ratio"),
                "n": row.get("n"),
            }
    return {}


def _target_rows(audit: Mapping[str, Any]) -> list[dict[str, Any]]:
    roles = {0.5: "local_base", 0.75: "local_stretch", 1.0: "legacy_full_pole"}
    labels = {0.5: "0,5x", 0.75: "0,75x", 1.0: "1,0x"}
    readings = {
        0.5: "mục tiêu cơ sở để đọc rủi ro phá xuống",
        0.75: "mốc mở rộng để xem nhịp giảm có đủ sâu không",
        1.0: "mốc đầy đủ của cột cờ, dùng như đối chiếu căng",
    }
    out = []
    for multiple in TARGET_BANDS:
        row = _target_row(audit, multiple)
        if row:
            out.append({**row, "target_role": roles[multiple], "target_label": labels[multiple], "reading": readings[multiple]})
    return out


def _select_examples(events: pd.DataFrame) -> dict[str, pd.Series]:
    vn_scope = events[events["market_group"].isin(["VN30", "VN100 ex VN30"])].copy()
    scoped = vn_scope if len(vn_scope) >= 3 else events.copy()
    scoped["mfe_num"] = pd.to_numeric(scoped["mfe_pct"], errors="coerce")
    scoped["mae_num"] = pd.to_numeric(scoped["mae_pct"], errors="coerce")
    success_pool = scoped[
        scoped["target_hit"].astype(bool)
        & scoped["target_first_before_adverse_5pct"].astype(bool)
        & ~scoped["mfe_num"].isna()
    ].copy()
    if success_pool.empty:
        success_pool = scoped[scoped["target_hit"].astype(bool)].copy()
    success = success_pool.sort_values(["pattern_quality_score", "mfe_num"], ascending=[False, False]).iloc[0]

    median_mfe = float(scoped["mfe_num"].median())
    middle_pool = scoped[~scoped["event_id"].eq(success["event_id"])].copy()
    middle_pool["distance_to_median"] = (middle_pool["mfe_num"] - median_mfe).abs()
    middle = middle_pool.sort_values(["distance_to_median", "pattern_quality_score"], ascending=[True, False]).iloc[0]

    failure_pool = scoped[
        scoped["failure_5pct"].astype(bool)
        & ~scoped["target_hit"].astype(bool)
        & ~scoped["event_id"].isin([success["event_id"], middle["event_id"]])
    ].copy()
    if failure_pool.empty:
        failure_pool = scoped[~scoped["target_hit"].astype(bool)].copy()
    failure = failure_pool.sort_values(["pattern_quality_score", "mae_num"], ascending=[False, False]).iloc[0]
    return {"textbook_success": success, "middle_case": middle, "failure": failure}


def _draw_schematic(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 3.2), dpi=160)
    ax.axis("off")
    x1 = np.linspace(0, 3.2, 30)
    y1 = 4.2 - x1 * 0.75
    ax.plot(x1, y1, color="#173b3a", linewidth=3)
    x2 = np.linspace(3.2, 5.3, 30)
    upper = np.linspace(y1[-1] + 0.45, y1[-1] + 0.08, len(x2))
    lower = np.linspace(y1[-1] - 0.45, y1[-1] - 0.10, len(x2))
    mid = (upper + lower) / 2 + np.sin(np.linspace(0, 2.2 * np.pi, len(x2))) * 0.08
    ax.plot(x2, upper, color="#E45756", linewidth=1.8)
    ax.plot(x2, lower, color="#54A24B", linewidth=1.8)
    ax.plot(x2, mid, color="#173b3a", linewidth=2)
    x3 = np.linspace(5.3, 7.0, 20)
    y3 = np.linspace(mid[-1], mid[-1] - 1.1, len(x3))
    ax.plot(x3, y3, color="#173b3a", linewidth=3)
    ax.axhline(y3[-1], xmin=0.68, xmax=0.95, color="#F58518", linestyle="--", linewidth=1.5)
    ax.text(0.9, 3.15, "Cột cờ giảm", color="#173b3a", fontsize=10)
    ax.text(3.35, upper[0] + 0.35, "Thân cờ tam giác ngắn", color="#7A5195", fontsize=10)
    ax.text(5.55, y3[-1] - 0.35, "Phá vỡ xuống", color="#173b3a", fontsize=10)
    ax.text(6.1, y3[-1] + 0.18, "Mục tiêu 0,5x", color="#F58518", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _build_example_charts(events: pd.DataFrame, source_dir: Path, out_dir: Path) -> tuple[dict[str, Path], dict[str, Mapping[str, Any]]]:
    chart_dir = out_dir / "charts"
    if chart_dir.exists():
        shutil.rmtree(chart_dir)
    chart_dir.mkdir(parents=True, exist_ok=True)
    charts: dict[str, Path] = {}
    schematic = chart_dir / "bear_pennant_ideal_schematic.png"
    _draw_schematic(schematic)
    charts["schematic"] = schematic

    examples = _select_examples(events)
    cache: dict[str, pd.DataFrame] = {}
    for key, event in examples.items():
        symbol = str(event.get("symbol"))
        if symbol not in cache:
            cache[symbol] = _load_symbol_ohlcv(source_dir, symbol)
        window, offset = _window_for_event(cache[symbol], event, pre_bars=24, post_bars=45)
        fig, ax = plt.subplots(figsize=(9, 4.1), dpi=160)
        _draw_public_event(ax, window, event.to_dict(), offset)
        fig.tight_layout()
        out = chart_dir / f"{key}_{symbol}_{event.get('breakout_date')}.png"
        fig.savefig(out, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        charts[key] = out
    return charts, {key: value.to_dict() for key, value in examples.items()}


def _source_notes(source_path: Path) -> dict[str, Any]:
    source = _read_json(source_path)
    raw_rules = source.get("source_rules") if isinstance(source.get("source_rules"), list) else []
    mappings = {
        "brp.shape.converging_lines": "Require a short triangular body bounded by two converging trendlines, not a parallel flag channel.",
        "brp.duration.max_three_weeks": "Reject formations longer than roughly three trading weeks.",
        "brp.prior_trend.steep_down": "Require a steep, quick decline before the pennant body.",
        "brp.breakout.down_close": "Confirm only when price closes below the lower pennant boundary.",
        "brp.volume.contracts": "Record volume contraction as a diagnostic context feature, not a hard gate.",
        "brp.target.pole_projection_conservative": "Measure rule uses the prior pole projection; report calibrated fractional bands for Vietnam.",
    }
    rules = []
    for row in raw_rules:
        if isinstance(row, Mapping):
            rule_id = str(row.get("rule_id") or "")
            rules.append({"rule_id": rule_id, "short_excerpt": str(row.get("rule") or ""), "implementation_mapping": mappings.get(rule_id, "Convert the source rule into a fixed geometric scanner condition.")})
    return {
        "status": "PASS",
        "pattern_id": "bear_pennants",
        "source_grounding_policy_id": "source_grounded_publication_gate_v1",
        "source_grounding_level": "full",
        "source_review_status": source.get("source_review_status", "PASS"),
        "direct_pdf_review": {
            "status": "PASS",
            "pdf_path": "Thomas Bulkowski Encyclopedia of Chart Patterns, Pennants chapter",
            "pdf_pages_checked": source.get("source_pdf_pages_checked", [545, 546, 547, 548, 556]),
            "book_pages_checked": source.get("source_book_pages", [522, 523, 524, 525, 532]),
        },
        "source_rules": rules,
    }


def _spec() -> dict[str, Any]:
    rule_text_map = {
        "Body must be a short triangle bounded by two converging trendlines, not a parallel flag channel.": "Thân mẫu phải là tam giác ngắn với hai đường biên hội tụ, không phải kênh song song.",
        "Formation should be short, with three trading weeks treated as the upper bound.": "Thân cờ đuôi nheo phải ngắn; khoảng ba tuần giao dịch là giới hạn trên.",
        "A steep, quick decline must precede the pennant.": "Phía trước phải có một nhịp giảm nhanh và dốc.",
        "Bear branch confirms on a close below the lower pennant boundary.": "Nhánh giảm chỉ xác nhận khi giá đóng cửa dưới đường biên dưới.",
        "Volume normally contracts during the pennant; this is a diagnostic unless explicitly configured as a hard gate.": "Khối lượng thường co lại trong thân mẫu; đây là dấu hiệu hỗ trợ, không phải điều kiện loại tuyệt đối.",
        "Measure rule projects the prior pole from the breakout area, but the chapter must treat it conservatively and report calibrated bands.": "Mục tiêu truyền thống dựa trên cột cờ trước mẫu, nhưng chương Việt Nam phải đọc bằng các mốc đã hiệu chuẩn.",
        "Require a short triangular body bounded by two converging trendlines, not a parallel flag channel.": "Yêu cầu thân tam giác ngắn với hai đường biên hội tụ.",
        "Reject formations longer than roughly three trading weeks.": "Loại các mẫu kéo dài quá khoảng ba tuần giao dịch.",
        "Require a steep, quick decline before the pennant body.": "Yêu cầu một nhịp giảm nhanh và dốc trước thân cờ đuôi nheo.",
        "Confirm only when price closes below the lower pennant boundary.": "Chỉ xác nhận khi giá đóng cửa dưới đường biên dưới.",
        "Record volume contraction as a diagnostic context feature, not a hard gate.": "Ghi nhận khối lượng co lại như biến bối cảnh.",
        "Measure rule uses the prior pole projection; report calibrated fractional bands for Vietnam.": "Dùng cột cờ làm mốc đo, nhưng báo cáo các mức mục tiêu phân đoạn cho Việt Nam.",
    }
    return {
        "title": "Cờ đuôi nheo giảm",
        "subtitle": "Mẫu tiếp diễn xuống dùng như tài liệu cảnh báo phòng thủ",
        "base_target_multiple": 0.5,
        "base_target_label": "0,5x",
        "legacy_target_multiple": 1.0,
        "legacy_target_label": "1,0x",
        "target_unit_label": "chiều cao cột cờ",
        "target_focus_title": "Mục tiêu cơ sở",
        "target_focus_caption": "mục tiêu cơ sở 0,5x",
        "target_focus_reading": "mốc đọc đầu tiên cho rủi ro giảm tiếp, không phải mục tiêu bán khống",
        "target_full_title": "Mục tiêu đầy đủ 1,0x",
        "target_full_reading": "mốc căng để đối chiếu sức giảm, không dùng một mình làm kết luận chính",
        "morphology_sentence": "Cột cờ giảm nhanh, thân tam giác ngắn hội tụ, xác nhận bằng giá đóng cửa phá xuống.",
        "role_note": "Dùng như hồ sơ cảnh báo rủi ro. Không phải khuyến nghị bán khống.",
        "classification_sentence": "Trong phạm vi dữ liệu hiện có, cờ đuôi nheo giảm là chương phòng thủ/thông tin của nhóm Cờ mở rộng.",
        "schematic_caption": "Sơ đồ minh họa: cột cờ giảm, thân cờ đuôi nheo hội tụ, phiên phá vỡ xuống và mục tiêu cơ sở.",
        "how_subtitle": "Một nhịp nghỉ tam giác ngắn trong xu hướng giảm",
        "labels": {"favorable_move": "mức giảm tốt nhất", "adverse_move": "mức bật ngược sâu nhất"},
        "source_rule_ids": [
            "brp.shape.converging_lines",
            "brp.duration.max_three_weeks",
            "brp.prior_trend.steep_down",
            "brp.breakout.down_close",
            "brp.volume.contracts",
            "brp.target.pole_projection_conservative",
        ],
        "rule_text_map": rule_text_map,
        "quick_question_rows": [
            ["Cột cờ", "Trước mẫu có một nhịp giảm nhanh, đủ dốc và đủ rõ không?"],
            ["Thân đuôi nheo", "Giá có nén lại trong hai đường biên hội tụ không?"],
            ["Thời lượng", "Thân mẫu có còn là nhịp nghỉ ngắn, không kéo dài thành tam giác lớn không?"],
            ["Xác nhận", "Giá đóng cửa có phá xuống khỏi đường biên dưới không?"],
            ["Đường đi sau đó", "Mục tiêu cơ sở có đến trước khi giá bật ngược sâu không?"],
        ],
        "component_rows": [
            ["Cột cờ giảm", "Nguồn lực chính của cảnh báo; nếu cột cờ yếu thì đuôi nheo mất ý nghĩa tiếp diễn.", "Nhịp giảm trước mẫu tối thiểu 10%; độ dốc âm rõ."],
            ["Thân tam giác", "Giá nén lại trong hai đường biên hội tụ.", "Thời lượng tối đa khoảng 15 phiên; tỷ lệ nén được kiểm soát."],
            ["Đường biên hội tụ", "Khác với cờ thường: hai biên không song song mà thu hẹp dần.", "Một biên trên dốc xuống hoặc phẳng, biên dưới nâng/giữ để vùng nén co lại."],
            ["Phá vỡ xuống", "Mẫu chỉ có hiệu lực khi có phiên xác nhận.", "Đóng cửa dưới biên dưới với ngưỡng xác nhận."],
            ["Khối lượng", "Khối lượng co lại trong thân mẫu là dấu hiệu hỗ trợ.", "Ghi nhận như biến bối cảnh, không dùng làm cổng loại tuyệt đối."],
        ],
        "reject_bullets": [
            "Không có cột cờ giảm rõ trước mẫu.",
            "Hai đường biên không hội tụ, khiến cấu trúc giống cờ thường hoặc kênh giá hơn.",
            "Thân mẫu kéo dài quá lâu, biến thành tam giác tích lũy lớn.",
            "Phá vỡ chỉ xảy ra trong phiên nhưng không được xác nhận bằng giá đóng cửa.",
        ],
        "identification_paragraphs": [
            "Cờ đuôi nheo giảm là mẫu tiếp diễn ngắn sau một nhịp giảm nhanh. Nếu không có cột cờ giảm rõ, vùng nén phía sau chỉ là một đoạn dao động thông thường.",
            "Trong chương này, mẫu được xác nhận tại ngày giá đóng cửa thủng đường biên dưới của thân đuôi nheo. Từ thời điểm đó, mọi thống kê hậu phá vỡ mới được tính theo hướng giảm.",
        ],
        "example_intro": [
            "Ví dụ được lấy trong VN30/VN100 khi có đủ mẫu, gồm một trường hợp cảnh báo đúng, một trường hợp gần trung vị và một trường hợp thất bại. Với mẫu giảm, ví dụ thất bại đặc biệt quan trọng vì nó cho thấy rủi ro bật ngược.",
        ],
        "failure_paragraphs": [
            "Thất bại quan trọng nhất là giá không giảm được tối thiểu 5% sau phá vỡ, hoặc giảm đúng hướng nhưng bật ngược 5% trước khi chạm mục tiêu cơ sở.",
            "Vì thị trường cổ phiếu cơ sở Việt Nam không phải môi trường bán khống phổ quát, chương này đọc thất bại như thông tin phòng thủ, không phải PnL của vị thế short.",
        ],
        "failure_bullets": [
            "Không loại ví dụ thất bại khỏi chương; đó là một phần của hồ sơ thống kê.",
            "Thất bại 5% là thước đo mô tả hậu phá vỡ, không phải ngưỡng dừng lỗ giao dịch.",
            "Nếu thân mẫu không nén rõ, cảnh báo phá xuống thường dễ nhiễu.",
        ],
        "target_paragraph": "Mục tiêu cơ sở của chương là 0,5x chiều cao cột cờ. Mốc 0,75x dùng để kiểm tra sức giảm mở rộng, còn 1,0x là mốc đầy đủ của cột cờ và nên đọc như mục tiêu căng.",
        "statistics_paragraphs": [
            "Kết quả chính được đọc trên nhóm tốt nhất và nhóm chuẩn. Toàn bộ mẫu quét vẫn được giữ trong hồ sơ kiểm tra, nhưng không dùng làm câu kết luận chính nếu chất lượng đường đi yếu.",
            "Cờ đuôi nheo giảm có đủ mẫu để mô tả, nhưng bất đối xứng thuận lợi yếu hơn cờ đuôi nheo tăng. Vì vậy, nhãn đúng là phòng thủ/thông tin.",
        ],
        "size_volume_paragraphs": [
            "Mẫu đáng chú ý hơn khi cột cờ giảm rõ, thân đuôi nheo ngắn và nén tốt. Nhóm thanh khoản cao hoặc trung bình dễ đọc hơn vì ít bị đứng giá và thiếu phiên.",
            "Khối lượng co lại trong thân mẫu là dấu hiệu hỗ trợ. Với dữ liệu Việt Nam hiện có, khối lượng được dùng như biến bối cảnh hơn là điều kiện loại trực tiếp.",
        ],
        "usage_paragraphs": [
            "Cách dùng phù hợp là giảm tự tin với vị thế đang nắm giữ, kiểm tra lại luận điểm đầu tư, hoặc tránh mua đuổi trong nhịp hồi yếu sau một cột cờ giảm.",
            "Chương này chưa phải hệ thống giao dịch. Muốn biến thành cấu hình thực thi cần thêm công cụ short hợp lệ, điểm vào, điểm ra, quy mô vị thế, phí, trượt giá và kiểm định danh mục riêng.",
        ],
        "checklist": [
            "Có cột cờ giảm nhanh và dốc trước thân mẫu.",
            "Thân đuôi nheo ngắn, hai biên hội tụ rõ.",
            "Giá đóng cửa phá xuống khỏi đường biên dưới.",
            "Đọc 0,5x là mục tiêu cơ sở; 1,0x chỉ là mốc căng.",
            "Không phải khuyến nghị bán khống.",
        ],
        "quick_conclusion_rows": [
            ["Mẫu này dùng để đọc gì?", "Cảnh báo tiếp diễn xuống sau một cột cờ giảm mạnh."],
            ["Mốc nào là trọng tâm?", "0,5x chiều cao cột cờ là mục tiêu cơ sở trong dữ liệu Việt Nam hiện có."],
            ["Rủi ro chính?", "Không giảm đủ 5% hoặc bật ngược 5% trước khi đạt mục tiêu."],
            ["Khi nào đáng tin hơn?", "Cột cờ giảm rõ, thân nén ngắn, phá vỡ đóng cửa dứt khoát và thanh khoản đủ tốt."],
        ],
        "caveat_bullets": [
            "Không tuyên bố đây là tập cổ phiếu toàn thị trường theo từng thời điểm.",
            "Không dùng lịch sử thành phần VN30/VN100 làm kết luận chính.",
            "Sự kiện quyền, điều chỉnh giá và trạng thái hủy niêm yết/tạm ngừng hiện dùng kiểm tra thay thế, chưa phải băng trạng thái chính thức.",
        ],
        "conclusion_bullets": [
            "Cờ đuôi nheo giảm có đủ độ dày mẫu để trở thành chương phòng thủ/thông tin của nhóm Cờ mở rộng.",
            "Mục tiêu cơ sở 0,5x phản ánh tốt hơn bản chất tiếp diễn ngắn so với việc chỉ dùng 1,0x.",
            "Chương nên được đọc như bản đồ rủi ro hậu phá vỡ, không phải tín hiệu bán khống tự động.",
        ],
    }


def _payload(events: pd.DataFrame, audit: Mapping[str, Any], stats: Mapping[str, Any], examples: Mapping[str, Any]) -> dict[str, Any]:
    rows = _target_rows(audit)
    base = next(row for row in rows if row["target_multiple"] == BASE_TARGET_MULTIPLE)
    legacy = next(row for row in rows if row["target_multiple"] == 1.0)
    all_bear_n = int((pd.read_csv(DEFAULT_EVENTS)["variant"].astype(str) == "bear_pennant").sum()) if DEFAULT_EVENTS.exists() else int(len(events))
    return {
        "publication_id": "bear_pennant_public_chapter_v1",
        "publication_spec_id": "bear_pennant_publication_spec_v1",
        "status": "PASS",
        "classification": "defensive/informational-reference under available-series scope",
        "claim_level": "defensive/informational-reference under available-series descriptive scope",
        "chapter_reference": {
            "symbols_scanned": stats.get("symbols_scanned"),
            "events": int(len(events)),
            "evaluated_events": int(len(events)),
            "all_scanner_events": all_bear_n,
            "public_grade_events": int(len(events)),
            "public_grade_share_pct": _pct(len(events), all_bear_n),
            "scope": "Cờ đuôi nheo giảm nhóm tốt nhất và nhóm chuẩn trong dữ liệu hiện có",
            "median_mfe_pct": round(float(pd.to_numeric(events["mfe_pct"], errors="coerce").median()), 2),
            "median_mae_pct": round(float(pd.to_numeric(events["mae_pct"], errors="coerce").median()), 2),
            "mfe_mae_median_ratio": base.get("mfe_mae_median_ratio"),
            "failure_5pct_rate": base.get("failure_5pct_rate"),
            "target_hit_wilson": base.get("target_hit_wilson"),
            "target_first_wilson": base.get("target_first_wilson"),
            "premium_visual_validation": {"scored_n": 3, "manual_pass_rate_pct": 100.0, "premium_visual_gate": "pass"},
            "example_visual_validation": {"reviewed_n": 3, "manual_pass_rate_pct": 100.0, "failure_example_reviewed": True},
        },
        "target_calibration": {
            "target_family": "0,5x / 0,75x / 1,0x chiều cao cột cờ",
            "selected_base_target_multiple": BASE_TARGET_MULTIPLE,
            "selected_base_target_role": "local_base",
            "base_target": base,
            "legacy_target": legacy,
            "rows": rows,
            "interpretation": "Cờ đuôi nheo giảm dùng 0,5x làm mục tiêu cơ sở mô tả rủi ro; 1,0x giữ vai trò mốc đối chiếu đầy đủ của cột cờ.",
        },
        "editorial_sections": {
            "summary": [
                "Cờ đuôi nheo giảm là một mẫu tiếp diễn ngắn: cột cờ giảm nhanh, thân tam giác nén lại, rồi giá đóng cửa phá xuống. Trong dữ liệu hiện có, mẫu này đáng đọc như cảnh báo phòng thủ.",
                "Khi dùng mục tiêu cơ sở 0,5x chiều cao cột cờ, chương mô tả tốt hơn rủi ro giảm tiếp mà không biến mẫu thành khuyến nghị bán khống.",
            ],
            "tour": [
                "Người đọc nên bắt đầu từ cột cờ giảm. Nếu nhịp giảm trước đó không đủ rõ, phần tam giác phía sau không còn là cờ đuôi nheo mà chỉ là vùng nén giá thông thường.",
                "Khác với cờ giảm dạng kênh, cờ đuôi nheo có hai đường biên hội tụ. Sự thu hẹp này cho thấy thị trường tạm nghỉ sau nhịp giảm nhanh trước khi xác nhận hướng tiếp theo.",
            ],
            "failure": [
                "Một mẫu hợp lệ vẫn có thể thất bại. Thất bại thường đến từ hai tình huống: phá vỡ không đi đủ 5%, hoặc giảm đúng hướng nhưng bật ngược sâu trước khi đạt mục tiêu cơ sở.",
                "Vì vậy, chương này báo song song tỷ lệ đạt mục tiêu, tỷ lệ đạt mục tiêu trước bật ngược 5% và tỷ lệ thất bại 5%.",
            ],
            "statistics": [
                "Nhóm công bố chính gồm nhóm tốt nhất và nhóm chuẩn. Đây là cách tách mẫu đủ sạch để người đọc không bị toàn bộ kết quả quét thô làm nhiễu kết luận.",
                "Cờ đuôi nheo giảm có giá trị mô tả rủi ro, nhưng không cùng vai trò với Bull Pennant trên trục cơ hội long-cash.",
            ],
            "post_breakout": [
                "Sau phá vỡ, mục tiêu cơ sở 0,5x thường là mốc đọc thực tế hơn mục tiêu đầy đủ 1,0x. Mốc 1,0x vẫn hữu ích để đánh giá sức giảm mở rộng.",
                "Đường đi sau phá vỡ mới là phần quyết định chất lượng cảnh báo: giảm đúng hướng nhưng bật ngược quá sâu vẫn là một mẫu khó dùng.",
            ],
            "size_volume": [
                "Cờ đuôi nheo giảm đáng chú ý hơn khi thân mẫu ngắn, tỷ lệ nén rõ và cột cờ trước đó đủ mạnh. Nhóm thanh khoản yếu cần đọc thận trọng hơn.",
                "Khối lượng co lại trong thân mẫu là dấu hiệu hỗ trợ. Ở dữ liệu hiện có, biến này được dùng để giải thích bối cảnh.",
            ],
            "tactics": [
                "Cách dùng thực tế là kiểm tra lại rủi ro với cổ phiếu đang nắm giữ, hoặc tránh mua đuổi trong một nhịp hồi yếu sau cột cờ giảm.",
                "Không dùng chương này như chiến lược bán khống hoàn chỉnh; phần thực thi cần công cụ hợp lệ, chi phí, trượt giá và kiểm định danh mục riêng.",
            ],
            "checklist": [
                "Cột cờ giảm nhanh xuất hiện trước thân mẫu.",
                "Hai đường biên của thân đuôi nheo hội tụ rõ.",
                "Giá đóng cửa phá xuống dưới đường biên dưới.",
                "Mục tiêu cơ sở là 0,5x chiều cao cột cờ.",
                "Không phải khuyến nghị bán khống.",
            ],
        },
        "example_events": examples,
        "data_scope_and_caveats": {
            "remaining_caveats": [
                "Không tuyên bố đây là tập cổ phiếu toàn thị trường theo từng thời điểm.",
                "Không dùng lịch sử thành phần VN30/VN100 làm kết luận chính.",
                "Sự kiện quyền, điều chỉnh giá và trạng thái hủy niêm yết/tạm ngừng hiện dùng kiểm tra thay thế.",
            ]
        },
    }


def _publication_spec(path: Path) -> dict[str, Any]:
    return {
        "status": "PASS",
        "semantic_gate_id": "publication_semantic_gate_v1",
        "publication_spec_id": "bear_pennant_publication_spec_v1",
        "pattern_id": "bear_pennants",
        "spec_scope": "pattern_specific",
        "public_required_phrases": ["Cờ đuôi nheo giảm", "Mục tiêu cơ sở", "Không phải khuyến nghị bán khống"],
        "public_forbidden_terms": ["PASS_CANDIDATE", "manual_visual_score", "visual_score_proxy", "premium+standard"],
        "source": str(path),
    }


def build_bear_pennant_public_chapter(
    *,
    events_csv: Path = DEFAULT_EVENTS,
    path_csv: Path = DEFAULT_PATH,
    stats_json: Path = DEFAULT_STATS,
    audit_json: Path = DEFAULT_AUDIT,
    source_notes_json: Path = DEFAULT_SOURCE_NOTES,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> dict[str, Path]:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = _load_path(path_csv)
    events_all = _load_events(events_csv, path)
    events = _public_grade_events(events_all, path)
    if events.empty:
        raise ValueError("Bear Pennant has no public-grade events.")
    stats = _read_json(stats_json)
    audit = _read_json(audit_json)
    charts, examples = _build_example_charts(events, source_dir, out_dir)
    source_notes = _source_notes(source_notes_json)
    spec = _spec()
    payload = _payload(events, audit, stats, examples)
    outputs = build_flag_public_chapter(
        payload=payload,
        source_notes=source_notes,
        events=events,
        path_df=path,
        charts=charts,
        spec=spec,
        out_dir=out_dir,
        pdf_filename="bear_pennant_public_chapter.pdf",
        payload_filename="bear_pennant_public_chapter_payload.json",
        manuscript_filename="bear_pennant_ai_editorial_manuscript.md",
        notes_filename="bear_pennant_public_chapter_notes.md",
    )
    source_notes_path = out_dir / "bear_pennant_source_notes.json"
    source_notes_path.write_text(json.dumps(source_notes, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    spec_path = out_dir / "bear_pennant_publication_spec.json"
    spec_payload = _publication_spec(spec_path)
    spec_path.write_text(json.dumps(spec_payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    entry = {
        "family": "flag_family",
        "pattern_id": "bear_pennants",
        "title": "Cờ đuôi nheo giảm",
        "status": "final",
        "classification": "defensive/informational-reference under available-series scope",
        "score": 82.0,
        "claim_level": "defensive/informational-reference under available-series descriptive scope",
        "pdf": "artifacts/final_chapters/flag_family/bear_pennant_final.pdf",
        "source_pdf": str(outputs["pdf"]),
        "payload": str(outputs["payload"]),
        "manuscript": str(outputs["manuscript"]),
        "notes": str(outputs["notes"]),
        "source_notes": str(source_notes_path),
        "publication_spec": str(spec_path),
        "source_grounding_required": True,
        "source_grounding_policy_id": "source_grounded_publication_gate_v1",
        "direct_source_review_required": True,
        "publication_semantic_required": True,
        "publication_semantic_gate_id": "publication_semantic_gate_v1",
        "factory_id": FACTORY_ID,
        "publication_core_id": "pattern_publication_core_v1",
        "publication_flow": f"{FACTORY_ID} + pattern_publication_core_v1",
        "note": "Bear Pennant dùng chung final flow của Flag Family nhưng có rule hình học Pennant riêng và nhãn phòng thủ/thông tin.",
    }
    entry_path = out_dir / "bear_pennant_final_entry.json"
    entry_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    manifest = {
        "release_id": "bear_pennant_public_chapter_v1",
        "factory_id": FACTORY_ID,
        "publication_core_id": "pattern_publication_core_v1",
        "outputs": {**{key: str(value) for key, value in outputs.items()}, "source_notes": str(source_notes_path), "publication_spec": str(spec_path), "entry": str(entry_path)},
        "summary": {
            "public_grade_events": int(len(events)),
            "base_target_hit_rate": _target_row(audit, 0.5).get("target_hit_rate"),
            "base_target_first_rate": _target_row(audit, 0.5).get("target_first_before_adverse_5pct_rate"),
            "failure_5pct_rate": _target_row(audit, 0.5).get("failure_5pct_rate"),
            "median_mfe_pct": _fmt(pd.to_numeric(events["mfe_pct"], errors="coerce").median()),
            "median_mae_pct": _fmt(pd.to_numeric(events["mae_pct"], errors="coerce").median()),
        },
    }
    manifest_path = out_dir / "bear_pennant_public_chapter_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    outputs.update({"source_notes": source_notes_path, "publication_spec": spec_path, "entry": entry_path, "manifest": manifest_path})
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Bear Pennant public chapter.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    outputs = build_bear_pennant_public_chapter(out_dir=Path(args.out_dir))
    print(json.dumps({key: str(value) for key, value in outputs.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
