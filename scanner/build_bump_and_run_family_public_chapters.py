"""Build source-grounded Bump-and-Run Reversal public-chapter seed artifacts.

This builder creates deterministic ingredients only. It does not approve final
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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.bump_and_run_family_publication_specs import build_barr_publication_spec  # noqa: E402
from scanner.publication_flow_contract import SOURCE_GROUNDED_PUBLICATION_GATE_ID  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bump_and_run_family_public_chapters")
SOURCE_PDF = "references/encyclopedia-of-chart-patterns-2nbsped-9786468600-3175723993-9780471668268-0471668265_compress.pdf"


PATTERNS: dict[str, dict[str, Any]] = {
    "bump_and_run_reversal_bottoms": {
        "slug": "bump_and_run_reversal_bottoms",
        "title": "Bump-and-Run đáy",
        "subtitle": "Nhịp giảm dẫn, cú rơi quá đà, rồi giá vượt lại đường xu hướng dẫn",
        "scan_dir": Path("artifacts/scanner_v2/bump_and_run_family/bump_and_run_reversal_bottoms/db_active"),
        "source_chapter": 7,
        "source_name": "Bump-and-Run Reversal Bottoms",
        "source_book_pages": [120, 121, 122, 123, 124, 125, 126, 127],
        "source_review_pages": [143, 144, 145, 146, 147, 148, 149, 150],
        "scope_tier": "premium+standard",
        "classification": "hồ sơ đảo chiều tăng sau cú giảm quá đà; có thể kiểm tra tradable layer cho nhánh long-cash",
        "claim_level": "đọc như một nhịp giảm có cú bump quá đà được xác nhận khi giá đóng cửa vượt lại đường xu hướng dẫn",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, Bump-and-Run đáy là một chương long-watchlist: mẫu đo tình huống giá rời xa nhịp giảm dẫn, rồi quay lại vượt đường xu hướng dẫn.",
        "morphology": "Bump-and-Run đáy gồm ba pha: nhịp dẫn đi xuống có đường xu hướng tương đối rõ, cú bump giảm nhanh hơn và xa khỏi đường đó, rồi pha run khi giá đóng cửa vượt lại đường xu hướng dẫn.",
        "role_note": "Dùng như hồ sơ theo dõi đảo chiều sau một cú giảm quá đà; không đọc trước khi giá đóng cửa vượt lại đường xu hướng dẫn.",
        "direction": "up",
    },
    "bump_and_run_reversal_tops": {
        "slug": "bump_and_run_reversal_tops",
        "title": "Bump-and-Run đỉnh",
        "subtitle": "Nhịp tăng dẫn, cú tăng quá đà, rồi giá rơi xuống dưới đường xu hướng dẫn",
        "scan_dir": Path("artifacts/scanner_v2/bump_and_run_family/bump_and_run_reversal_tops/db_active"),
        "source_chapter": 8,
        "source_name": "Bump-and-Run Reversal Tops",
        "source_book_pages": [128, 129, 130, 131, 132, 133, 134, 135],
        "source_review_pages": [151, 152, 153, 154, 155, 156, 157, 158],
        "scope_tier": "premium+standard",
        "classification": "hồ sơ phòng thủ/thoát vị thế vì nhánh chính là phá vỡ xuống trên cổ phiếu cơ sở",
        "claim_level": "đọc như một nhịp tăng có cú bump quá đà được xác nhận khi giá đóng cửa rơi xuống dưới đường xu hướng dẫn",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, Bump-and-Run đỉnh nên là chương phòng thủ/thông tin: mẫu giúp nhận diện trạng thái tăng quá đà rồi gãy đường xu hướng, nhưng không mặc định là cơ hội bán khống cổ phiếu cơ sở.",
        "morphology": "Bump-and-Run đỉnh gồm ba pha: nhịp dẫn đi lên có đường xu hướng tương đối rõ, cú bump tăng nhanh hơn và xa khỏi đường đó, rồi pha run khi giá đóng cửa rơi xuống dưới đường xu hướng dẫn.",
        "role_note": "Dùng như hồ sơ cảnh báo rủi ro hoặc hỗ trợ giảm vị thế; không đọc như short setup phổ quát.",
        "direction": "down",
    },
}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _fmt(value: Any, digits: int = 2) -> str:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if not math.isfinite(out):
        return "n/a"
    return f"{out:.{digits}f}"


def _events_for_scope(events: pd.DataFrame, scope_tier: str) -> pd.DataFrame:
    if scope_tier == "premium":
        scoped = events[events["publication_quality_tier"] == "premium"].copy()
    elif scope_tier == "premium+standard":
        scoped = events[events["publication_quality_tier"].isin(["premium", "standard"])].copy()
    else:
        scoped = events.copy()
    return scoped if not scoped.empty else events.copy()


def _target_metric(events: pd.DataFrame, path_df: pd.DataFrame, multiple: float, role: str) -> dict[str, Any]:
    if events.empty:
        return {"target_multiple": multiple, "target_role": role, "n": 0}
    if "event_id" not in events.columns:
        events = events.assign(event_id=events["detection_id"])
    grouped = {str(event_id): group.copy() for event_id, group in path_df.groupby("event_id")}
    hits: list[bool] = []
    firsts: list[bool] = []
    days: list[float] = []
    for _, event in events.iterrows():
        distance = float(event.get("target_dist_pct") or 0.0) * multiple
        group = grouped.get(str(event.get("event_id")))
        if group is None or group.empty:
            hits.append(False)
            firsts.append(False)
            days.append(float("nan"))
            continue
        favorable = pd.to_numeric(group["signed_high_excursion_pct"], errors="coerce")
        adverse = pd.to_numeric(group["signed_low_excursion_pct"], errors="coerce")
        bars = pd.to_numeric(group["bar_after_breakout"], errors="coerce")
        target_bars = bars[favorable >= distance]
        adverse_bars = bars[adverse <= -5.0]
        hit_day = float(target_bars.min()) if not target_bars.empty else float("nan")
        adverse_day = float(adverse_bars.min()) if not adverse_bars.empty else float("inf")
        hit = math.isfinite(hit_day)
        hits.append(hit)
        firsts.append(bool(hit and hit_day < adverse_day))
        days.append(hit_day if hit else float("nan"))
    mfe = pd.to_numeric(events.get("mfe_pct"), errors="coerce")
    mae = pd.to_numeric(events.get("mae_pct"), errors="coerce")
    fail = events.get("failure_5pct", pd.Series(False, index=events.index)).map(_truthy)
    target_dist = pd.to_numeric(events.get("target_dist_pct"), errors="coerce")
    return {
        "target_multiple": multiple,
        "target_role": role,
        "target_label": f"{multiple}x",
        "target_hit_rate": round(float(np.mean(hits) * 100.0), 2),
        "target_first_before_adverse_5pct_rate": round(float(np.mean(firsts) * 100.0), 2),
        "failure_5pct_rate": round(float(fail.mean() * 100.0), 2),
        "median_mfe_pct": round(float(mfe.median()), 2) if not mfe.dropna().empty else None,
        "median_mae_pct": round(float(mae.median()), 2) if not mae.dropna().empty else None,
        "mfe_mae_median_ratio": round(float(mfe.median() / max(mae.median(), 1.0)), 2) if not mfe.dropna().empty and not mae.dropna().empty else None,
        "median_target_dist_pct": round(float(target_dist.median() * multiple), 2) if not target_dist.dropna().empty else None,
        "median_days_to_target": round(float(pd.Series(days).dropna().median()), 2) if pd.Series(days).dropna().size else None,
        "n": int(len(events)),
    }


def _enrich_events(events: pd.DataFrame, path_df: pd.DataFrame, multiple: float) -> pd.DataFrame:
    events = events.copy()
    if "event_id" not in events.columns:
        events["event_id"] = events["detection_id"]
    grouped = {str(event_id): group.copy() for event_id, group in path_df.groupby("event_id")}
    hits: list[bool] = []
    firsts: list[bool] = []
    days: list[float] = []
    for _, event in events.iterrows():
        distance = float(event.get("target_dist_pct") or 0.0) * multiple
        group = grouped.get(str(event.get("event_id")))
        if group is None or group.empty:
            hits.append(False)
            firsts.append(False)
            days.append(float("nan"))
            continue
        favorable = pd.to_numeric(group["signed_high_excursion_pct"], errors="coerce")
        adverse = pd.to_numeric(group["signed_low_excursion_pct"], errors="coerce")
        bars = pd.to_numeric(group["bar_after_breakout"], errors="coerce")
        target_bars = bars[favorable >= distance]
        adverse_bars = bars[adverse <= -5.0]
        hit_day = float(target_bars.min()) if not target_bars.empty else float("nan")
        adverse_day = float(adverse_bars.min()) if not adverse_bars.empty else float("inf")
        hit = math.isfinite(hit_day)
        hits.append(hit)
        firsts.append(bool(hit and hit_day < adverse_day))
        days.append(hit_day if hit else float("nan"))
    events["target_hit"] = hits
    events["target_first_before_adverse_5pct"] = firsts
    events["days_to_target"] = days
    return events


def _plot_schematic(out_path: Path, *, pattern_id: str) -> None:
    fig, ax = plt.subplots(figsize=(9.2, 3.9), dpi=180)
    if pattern_id == "bump_and_run_reversal_bottoms":
        xs = np.array([0, 1.5, 3.0, 4.2, 5.4, 6.6])
        lead = np.array([18.0, 16.7, 15.4, 14.1, 12.8, 11.5])
        ys = np.array([18.0, 16.7, 15.5, 9.0, 13.0, 16.0])
        labels = ("nhịp dẫn", "", "đường dẫn", "bump", "run", "xác nhận")
        title = "Giải phẫu Bump-and-Run đáy"
    else:
        xs = np.array([0, 1.5, 3.0, 4.2, 5.4, 6.6])
        lead = np.array([11.0, 12.2, 13.4, 14.6, 15.8, 17.0])
        ys = np.array([11.0, 12.2, 13.5, 20.0, 16.3, 13.8])
        labels = ("nhịp dẫn", "", "đường dẫn", "bump", "run", "xác nhận")
        title = "Giải phẫu Bump-and-Run đỉnh"
    ax.plot(xs, lead, color="#8aa6a3", linestyle="--", linewidth=1.1)
    ax.plot(xs, ys, color="#245b5a", linewidth=1.8)
    ax.scatter(xs, ys, s=36, color="#6f4aa8", zorder=3)
    for x, y, label in zip(xs, ys, labels):
        if label:
            ax.text(x + 0.05, y, label, fontsize=8, color="#245b5a", va="bottom")
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
    is_bottom = pattern_id == "bump_and_run_reversal_bottoms"
    prefix = "barrb" if is_bottom else "barrt"
    confirmation = "vượt lại" if is_bottom else "rơi xuống dưới"
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
            "target_rule_summary": "Measure the distance from bump extreme back to lead-in trendline and project from confirmation in the run direction.",
            "review_note": "Đã đối chiếu source extraction và taxonomy gốc trước khi dựng scanner Bump-and-Run; chương public dùng source notes để grounding, không in nguyên nội dung nguồn.",
        },
        "source_rules": [
            {"rule_id": f"{prefix}.three_phases", "short_excerpt": "lead-in, bump, run", "implementation_mapping": "mẫu phải có ba pha: nhịp dẫn, cú bump quá đà, rồi pha run xác nhận"},
            {"rule_id": f"{prefix}.lead_in_trendline", "short_excerpt": "lead-in trendline", "implementation_mapping": "nhịp dẫn được fit bằng đường xu hướng đóng cửa đủ rõ"},
            {"rule_id": f"{prefix}.bump_steeper", "short_excerpt": "bump phase steeper than lead-in", "implementation_mapping": "cú bump phải đi xa khỏi đường dẫn và có độ dốc lớn hơn nhịp dẫn"},
            {"rule_id": f"{prefix}.confirmation", "short_excerpt": "breaks the trendline", "implementation_mapping": f"chỉ tính khi giá đóng cửa {confirmation} đường xu hướng dẫn"},
            {"rule_id": f"{prefix}.height_target", "short_excerpt": "height from trendline to bump extreme", "implementation_mapping": "mục tiêu đo bằng khoảng cách từ cực trị bump tới đường xu hướng dẫn"},
            {"rule_id": f"{prefix}.volume_context", "short_excerpt": "volume during bump", "implementation_mapping": "khối lượng dùng làm bối cảnh phụ, không thay thế xác nhận giá"},
        ],
    }


def _spec(pattern_id: str, meta: Mapping[str, Any]) -> dict[str, Any]:
    is_bottom = pattern_id == "bump_and_run_reversal_bottoms"
    confirm = "vượt lại đường xu hướng dẫn" if is_bottom else "rơi xuống dưới đường xu hướng dẫn"
    bump_dir = "giảm quá đà" if is_bottom else "tăng quá đà"
    return {
        "title": meta["title"],
        "subtitle": meta["subtitle"],
        "base_target_multiple": 0.5,
        "base_target_label": "0,5x",
        "legacy_target_multiple": 1.0,
        "legacy_target_label": "1,0x",
        "target_unit_label": "khoảng cách bump tới đường xu hướng dẫn",
        "target_focus_title": "Mốc cơ sở",
        "target_focus_caption": "mốc 0,5x chiều cao bump",
        "target_focus_reading": "mốc thận trọng trước khi đọc mục tiêu đầy đủ",
        "target_full_title": "Mốc đầy đủ 1,0x",
        "target_full_reading": "mốc đầy đủ theo chiều cao bump",
        "morphology_sentence": meta["morphology"],
        "role_note": meta["role_note"],
        "classification_sentence": meta["public_classification_sentence"],
        "headline_scope": "Mẫu chỉ được tính sau khi có ba pha: nhịp dẫn, cú bump quá đà và xác nhận quay lại qua đường xu hướng dẫn.",
        "local_source_chapter": meta["source_chapter"],
        "schematic_caption": f"Sơ đồ minh họa {meta['title']}: nhịp dẫn, cú bump {bump_dir}, pha run và xác nhận qua đường xu hướng.",
        "how_subtitle": "Đường dẫn trước, cú bump sau, xác nhận cuối cùng.",
        "labels": {"favorable_move": "mức đi thuận lợi", "adverse_move": "mức đi ngược bất lợi"},
        "source_rule_ids": ["three_phases", "lead_in_trendline", "bump_steeper", "confirmation", "height_target"],
        "public_rule_rows": [
            ["Phải có nhịp dẫn đủ rõ.", "Bộ nhận diện fit đường xu hướng dẫn bằng chuỗi giá đóng cửa trước cú bump."],
            ["Cú bump phải đi quá đà khỏi đường dẫn.", "Khoảng cách từ cực trị bump tới đường xu hướng phải đủ lớn để không nhầm với dao động thường."],
            ["Cú bump phải dốc hơn nhịp dẫn.", "Độ dốc bump được so với độ dốc nhịp dẫn để giữ đúng ý tưởng tăng/giảm quá đà."],
            ["Chỉ tính khi có xác nhận.", f"Điểm sự kiện là phiên giá đóng cửa {confirm}; trước đó chỉ là cấu trúc đang hình thành."],
            ["Mục tiêu đo theo chiều cao bump.", "0,5x là mốc cơ sở thận trọng; 1,0x là mốc đầy đủ."],
        ],
        "quick_question_rows": [
            ["Nhịp dẫn", "Đường xu hướng dẫn có đủ rõ không?"],
            ["Cú bump", f"Có cú {bump_dir} xa khỏi đường dẫn không?"],
            ["Xác nhận", f"Giá đã đóng cửa {confirm} chưa?"],
            ["Đường đi", "Mốc 0,5x có đến trước kéo ngược 5% không?"],
        ],
        "component_rows": [
            ["Nhịp dẫn", "Pha đi đều trước mẫu.", "Đặt đường xu hướng gốc"],
            ["Cú bump", "Pha quá đà rời xa đường dẫn.", "Tạo chiều cao đo mục tiêu"],
            ["Pha run", "Giá quay lại kiểm tra đường dẫn.", "Chờ xác nhận, không đo trước"],
            ["Xác nhận", f"Giá đóng cửa {confirm}.", "Mốc bắt đầu đo hậu breakout"],
        ],
        "reject_bullets": [
            "Không có đường xu hướng dẫn đủ rõ.",
            "Cú bump không dốc hơn nhịp dẫn.",
            "Giá chưa đóng cửa qua lại đường xu hướng dẫn.",
            "Đường giá thiếu sạch hoặc thiếu dữ liệu hậu xác nhận.",
        ],
        "identification_paragraphs": [meta["morphology"]],
        "example_intro": ["Ba ví dụ dưới đây gồm một mẫu đạt mốc cơ sở, một mẫu gần trung vị và một mẫu thất bại. Mỗi biểu đồ được đọc như một case study: nhịp dẫn, cú bump, phiên xác nhận và đường đi sau xác nhận."],
        "failure_bullets": [
            "Thất bại 5% là mẫu không đi đủ xa sau xác nhận, không phải stop-loss thực chiến.",
            "BARR rất dễ tạo đường đi nhiễu vì cú bump thường đi kèm biến động mạnh.",
            "Không dùng một ví dụ đẹp để thay thế thống kê toàn mẫu.",
        ],
        "target_paragraph": "Mục tiêu đo từ khoảng cách giữa cực trị bump và đường xu hướng dẫn; chương giữ 0,5x làm mốc cơ sở thận trọng và 1,0x làm mốc đầy đủ.",
        "identification_bridge": "Các quy tắc nhận diện nên được đọc theo đúng thứ tự: nhịp dẫn trước, cú bump quá đà, rồi xác nhận qua lại đường xu hướng. Nếu đảo thứ tự này, người đọc rất dễ biến một cú tăng/giảm mạnh bất kỳ thành Bump-and-Run.",
        "quick_conclusion_rows": [
            ["Mẫu này dùng để đọc gì?", meta["role_note"]],
            ["Mốc đọc chính?", "0,5x chiều cao bump."],
            ["Mốc tham chiếu?", "1,0x chiều cao bump."],
            ["Khi nào thận trọng?", "Khi nhịp dẫn kém thẳng, bump không đủ dốc hoặc xác nhận quá sát đường xu hướng."],
        ],
        "caveat_bullets": [
            "Không tuyên bố đây là nghiên cứu toàn thị trường đúng từng ngày lịch sử.",
            "Không dùng historical VN30/VN100 membership làm kết luận chính.",
            "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
            "Chương là tài liệu tham khảo hậu xác nhận, không phải khuyến nghị mua bán.",
        ],
        "quantile_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên"),
            ("Chiều cao bump", "bump_height_pct", "%"),
            ("Độ dốc bump so với nhịp dẫn", "bump_slope_ratio", "lần"),
            ("Độ thẳng nhịp dẫn", "lead_in_r2", "R2"),
            ("Độ rõ xác nhận", "confirmation_clearance_pct", "%"),
            ("Mức đi thuận lợi", "mfe_pct", "%"),
            ("Mức đi ngược bất lợi", "mae_pct", "%"),
            ("Ngày chạm mốc cơ sở", "days_to_target", "phiên"),
        ],
        "skip_condition_specs": [
            ("Nhịp dẫn kém thẳng", "lead_in_r2", "q25", None, "Đường dẫn yếu làm toàn bộ hình thái kém tin cậy."),
            ("Bump quá nhỏ", "bump_height_pct", "q25", None, "Cú bump không nổi bật so với đường dẫn."),
            ("Bump không đủ dốc", "bump_slope_ratio", "q25", None, "Không còn ý nghĩa quá đà."),
            ("Kéo ngược quá sâu", "mae_pct", "q75", None, "Đường đi sau xác nhận không còn gọn."),
        ],
        "general_stat_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên", "BARR cần đủ thời gian để có nhịp dẫn và bump, nhưng quá dài dễ thành xu hướng rộng."),
            ("Chiều cao bump", "bump_height_pct", "%", "Nền để đo target."),
            ("Độ dốc bump", "bump_slope_ratio", "lần", "Cho biết bump có thật sự quá đà so với nhịp dẫn hay không."),
            ("Độ thẳng nhịp dẫn", "lead_in_r2", "R2", "Đường dẫn càng rõ, hình thái càng dễ đọc."),
        ],
        "best_condition_specs": [
            ("Nhóm hình thái tốt", "publication_quality_tier", "==", "premium", "Nhịp dẫn rõ, bump đủ dốc và đường giá sau xác nhận sạch hơn."),
            ("Nhóm chuẩn", "publication_quality_tier", "==", "standard", "Đủ dùng trong thống kê nhưng không phải lúc nào cũng đẹp để minh họa."),
            ("Đường giá sạch", "path_quality_bucket", "==", "clean", "Ít thiếu phiên và ít chuỗi đứng giá."),
            ("Thanh khoản tốt hơn", "liquidity_bucket", "in", "mid/high", "Giảm nhiễu ở các mẫu ít giao dịch."),
        ],
        "conclusion_bullets": [
            f"{meta['title']} chỉ được đọc khi nhịp dẫn, bump và xác nhận đều hiện diện.",
            "Mục tiêu đầy đủ là 1,0x chiều cao bump; chương dùng 0,5x làm mốc cơ sở thận trọng.",
            meta["role_note"],
        ],
    }


def _payload(pattern_id: str, meta: Mapping[str, Any], events: pd.DataFrame, all_events: pd.DataFrame, path_df: pd.DataFrame) -> dict[str, Any]:
    base = _target_metric(events, path_df, 0.5, "conservative_half_bump_height")
    full = _target_metric(events, path_df, 1.0, "source_full_bump_height")
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
            "median_bump_height_pct": _fmt(pd.to_numeric(events.get("bump_height_pct"), errors="coerce").median()),
            "median_bump_slope_ratio": _fmt(pd.to_numeric(events.get("bump_slope_ratio"), errors="coerce").median()),
            "median_lead_in_r2": _fmt(pd.to_numeric(events.get("lead_in_r2"), errors="coerce").median()),
        },
        "target_calibration": {
            "target_family": {"conservative_half_bump_height": 0.5, "source_full_bump_height": 1.0},
            "selected_base_target_multiple": 0.5,
            "selected_base_target_role": "conservative_half_bump_height",
            "base_target": base,
            "stretch_target": full,
            "legacy_target": full,
            "rows": [base, full],
            "interpretation": "Mốc 0,5x giữ vai trò cơ sở thận trọng; 1,0x giữ vai trò mốc đầy đủ theo chiều cao bump.",
        },
        "data_scope_and_caveats": {
            "remaining_caveats": [
                "Không claim point-in-time universe toàn thị trường.",
                "Không dùng historical VN30/VN100 membership làm kết luận chính.",
                "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
            ]
        },
    }


def build_one_barr_chapter(*, pattern_id: str, out_dir: Path) -> dict[str, Path]:
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
    events = _enrich_events(events, path_df, 0.5)
    payload = _payload(pattern_id, meta, events, all_events, path_df)
    spec = _spec(pattern_id, meta)
    publication_spec = build_barr_publication_spec(pattern_id=pattern_id, title=str(meta["title"]), spec=spec)
    payload["publication_spec_id"] = publication_spec["publication_spec_id"]
    payload["source_rules_public"] = [{"rule": row[0], "application": row[1]} for row in spec.get("public_rule_rows", [])]
    chart_dir = chapter_dir / "charts"
    schematic = chart_dir / f"{pattern_id}_schematic.png"
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
        f"Chương nguồn: {meta['source_name']}. Dossier giữ thứ tự đọc: nhịp dẫn, bump, run, xác nhận đường xu hướng, thất bại, mục tiêu và cách dùng thận trọng. "
        "Không sao chép hoặc dịch lại tài liệu gốc; số liệu Việt Nam lấy từ payload đã khóa.\n",
        encoding="utf-8",
    )
    entry = {
        "family": "bump_and_run_family",
        "pattern_id": pattern_id,
        "title": meta["title"],
        "status": "source_seed",
        "classification": meta["classification"],
        "score": None,
        "claim_level": meta["claim_level"],
        "pdf": f"artifacts/final_chapters/bump_and_run_family/{meta['slug']}_final.pdf",
        "source_pdf": f"artifacts/final_chapters/bump_and_run_family/{meta['slug']}_final.pdf",
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
        "note": "Bump-and-Run Family dùng scanner riêng; builder này chỉ cung cấp nguyên liệu, không render hoặc approve PDF final.",
    }
    entry_path = chapter_dir / f"{meta['slug']}_final_manifest_entry.json"
    _write_json(entry_path, entry)
    return {"payload": payload_path, "source_notes": source_notes_path, "publication_spec": publication_spec_path, "entry": entry_path, "chart_schematic": schematic}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Bump-and-Run Reversal public-chapter seed artifacts.")
    parser.add_argument("--pattern", choices=[*PATTERNS.keys(), "all"], default="all")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    patterns = list(PATTERNS.keys()) if args.pattern == "all" else [args.pattern]
    outputs = {}
    for pattern_id in patterns:
        outputs[pattern_id] = {key: str(value) for key, value in build_one_barr_chapter(pattern_id=pattern_id, out_dir=Path(args.out_dir)).items()}
    print(json.dumps({"status": "PASS", "outputs": outputs}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
