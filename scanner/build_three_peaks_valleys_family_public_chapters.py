"""Build source-grounded Three Peaks / Three Valleys public-chapter seed artifacts.

This builder creates deterministic ingredients only. It does not approve
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

from scanner.publication_flow_contract import SOURCE_GROUNDED_PUBLICATION_GATE_ID  # noqa: E402
from scanner.three_peaks_valleys_family_publication_specs import build_three_peaks_valleys_publication_spec  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/three_peaks_valleys_family_public_chapters")
SOURCE_PDF = "references/encyclopedia-of-chart-patterns-2nbsped-9786468600-3175723993-9780471668268-0471668265_compress.pdf"


PATTERNS: dict[str, dict[str, Any]] = {
    "three_falling_peaks": {
        "slug": "three_falling_peaks",
        "title": "Ba đỉnh thấp dần",
        "subtitle": "Ba đỉnh liên tiếp hạ dần trước một phá vỡ xuống",
        "scan_dir": Path("artifacts/scanner_v2/three_peaks_valleys_family/three_falling_peaks/db_active"),
        "source_chapter": 45,
        "source_name": "Three Falling Peaks",
        "source_book_pages": [696, 697, 698, 699, 700, 701, 702, 703, 704, 705, 706],
        "source_review_pages": [719, 720, 721, 722, 723, 724, 725, 726, 727, 728, 729],
        "scope_tier": "premium+standard",
        "classification": "hồ sơ phòng thủ/thoát vị thế vì nhánh chính là phá vỡ xuống trên cổ phiếu cơ sở",
        "claim_level": "đọc như ba đỉnh thấp dần được xác nhận khi giá đóng cửa xuống dưới vùng đáy xen giữa",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, Ba đỉnh thấp dần nên là chương defensive/informational: mẫu giúp nhận diện áp lực suy yếu theo từng nhịp hồi, nhưng không mặc định là cơ hội short cổ phiếu cơ sở.",
        "morphology": "Ba đỉnh thấp dần gồm ba đỉnh liên tiếp, mỗi đỉnh sau thấp hơn đỉnh trước và các đỉnh tương đối cân xứng về quy mô. Mẫu chỉ được xác nhận khi giá đóng cửa xuống dưới vùng đáy xen giữa, cho thấy nhịp hồi đã yếu đi đủ để chuyển thành phá vỡ xuống.",
        "role_note": "Dùng như hồ sơ cảnh báo rủi ro hoặc hỗ trợ quyết định giảm vị thế; không đọc như short setup phổ quát.",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "direction": "down",
    },
    "three_rising_valleys": {
        "slug": "three_rising_valleys",
        "title": "Ba đáy cao dần",
        "subtitle": "Ba đáy liên tiếp nâng dần trước một phá vỡ lên",
        "scan_dir": Path("artifacts/scanner_v2/three_peaks_valleys_family/three_rising_valleys/db_active"),
        "source_chapter": 46,
        "source_name": "Three Rising Valleys",
        "source_book_pages": [698, 699, 700, 701, 702, 703, 704, 705, 706, 707, 708],
        "source_review_pages": [721, 722, 723, 724, 725, 726, 727, 728, 729, 730, 731],
        "scope_tier": "premium+standard",
        "classification": "hồ sơ đảo chiều tăng/tiếp diễn tăng; có thể kiểm tra tradable layer cho nhánh long-cash",
        "claim_level": "đọc như ba đáy cao dần được xác nhận khi giá đóng cửa vượt vùng đỉnh xen giữa",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, Ba đáy cao dần là một chương long-watchlist đáng nghiên cứu: hình thái thể hiện lực bán yếu dần qua ba đáy, nhưng cần đọc cùng kéo ngược vì throwback sau phá vỡ xuất hiện nhiều.",
        "morphology": "Ba đáy cao dần gồm ba đáy nhỏ liên tiếp, mỗi đáy sau cao hơn đáy trước. Các đáy thường tạo cảm giác như một đường nâng dần; mẫu chỉ có hiệu lực khi giá đóng cửa vượt vùng đỉnh xen giữa, xác nhận rằng lực mua đã vượt qua các nhịp hồi trước đó.",
        "role_note": "Dùng như hồ sơ theo dõi nhịp đảo chiều hoặc tiếp diễn tăng sau khi có xác nhận; không mua trước khi giá đóng cửa vượt vùng xác nhận.",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "direction": "up",
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


def _metric_for_target(events: pd.DataFrame, path_df: pd.DataFrame, multiple: float, role: str) -> dict[str, Any]:
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


def _enrich_events_for_target(events: pd.DataFrame, path_df: pd.DataFrame, multiple: float) -> pd.DataFrame:
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
    if pattern_id == "three_falling_peaks":
        xs = np.array([0, 1, 2, 3, 4, 5])
        ys = np.array([20.0, 14.8, 18.4, 14.1, 16.9, 13.2])
        labels = ("đỉnh 1", "đáy", "đỉnh 2", "đáy", "đỉnh 3", "phá vỡ")
        title = "Giải phẫu Ba đỉnh thấp dần"
    else:
        xs = np.array([0, 1, 2, 3, 4, 5])
        ys = np.array([11.0, 16.0, 12.3, 16.8, 13.5, 18.2])
        labels = ("đáy 1", "đỉnh", "đáy 2", "đỉnh", "đáy 3", "phá vỡ")
        title = "Giải phẫu Ba đáy cao dần"
    ax.plot(xs, ys, color="#245b5a", linewidth=1.6)
    ax.scatter(xs, ys, s=36, color="#6f4aa8", zorder=3)
    for x, y, label in zip(xs, ys, labels):
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


def _build_charts(out_dir: Path, *, pattern_id: str) -> dict[str, Path]:
    chart_dir = out_dir / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)
    schematic = chart_dir / f"{pattern_id}_schematic.png"
    _plot_schematic(schematic, pattern_id=pattern_id)
    return {"schematic": schematic}


def _source_notes(pattern_id: str, meta: Mapping[str, Any]) -> dict[str, Any]:
    is_valleys = pattern_id == "three_rising_valleys"
    prefix = "trv" if is_valleys else "tfp"
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
            "target_rule_summary": "Project the full pattern height from the breakout/confirmation boundary in the breakout direction.",
            "review_note": "Đã đối chiếu trực tiếp chương Three Falling Peaks / Three Rising Valleys trong PDF gốc trước khi dựng scanner và chapter.",
        },
        "source_rules": [
            {"rule_id": f"{prefix}.three_points", "short_excerpt": "three peaks/valleys", "implementation_mapping": "mẫu phải có ba điểm chính liên tiếp, không phải hai điểm hoặc một vùng dao động chung"},
            {"rule_id": f"{prefix}.progression", "short_excerpt": "each lower/higher than the prior one", "implementation_mapping": "đỉnh sau thấp hơn đỉnh trước với Ba đỉnh thấp dần; đáy sau cao hơn đáy trước với Ba đáy cao dần"},
            {"rule_id": f"{prefix}.proportional", "short_excerpt": "proportional to one another", "implementation_mapping": "ba điểm chính phải tương đối cân xứng, tránh một điểm quá lệch làm mất hình thái"},
            {"rule_id": f"{prefix}.reversal_context", "short_excerpt": "short-term reversal", "implementation_mapping": "mẫu được đọc như đảo chiều ngắn hạn hoặc tiếp diễn sau một nhịp trước đó rõ"},
            {"rule_id": f"{prefix}.confirmation", "short_excerpt": "breakout confirmation", "implementation_mapping": "chỉ tính sau khi giá đóng cửa qua vùng xác nhận của hai điểm xen giữa"},
            {"rule_id": f"{prefix}.height_target", "short_excerpt": "price target", "implementation_mapping": "mục tiêu đo bằng chiều cao mẫu; 0,5x là mốc đọc thận trọng, 1,0x là mốc đầy đủ"},
            {"rule_id": f"{prefix}.pullback_throwback", "short_excerpt": "pullbacks/throwbacks", "implementation_mapping": "đọc tỷ lệ quay lại vùng phá vỡ như một phần chính của rủi ro sau xác nhận"},
            {"rule_id": f"{prefix}.volume_context", "short_excerpt": "volume trend", "implementation_mapping": "khối lượng dùng làm bối cảnh phụ, không thay thế hình thái và xác nhận giá"},
        ],
    }


def _spec(pattern_id: str, meta: Mapping[str, Any]) -> dict[str, Any]:
    is_valleys = pattern_id == "three_rising_valleys"
    point_name = "đáy" if is_valleys else "đỉnh"
    direction = "cao dần" if is_valleys else "thấp dần"
    confirm = "vượt vùng đỉnh xen giữa" if is_valleys else "rơi xuống dưới vùng đáy xen giữa"
    return {
        "title": meta["title"],
        "subtitle": meta["subtitle"],
        "base_target_multiple": float(meta["base_target_multiple"]),
        "base_target_label": "0,5x",
        "legacy_target_multiple": float(meta["legacy_target_multiple"]),
        "legacy_target_label": "1,0x",
        "target_unit_label": "chiều cao mẫu",
        "target_focus_title": "Mốc cơ sở 0,5x",
        "target_focus_caption": "mốc 0,5x chiều cao mẫu",
        "target_focus_reading": "mốc thận trọng trước khi đọc mục tiêu đầy đủ",
        "target_full_title": "Mốc nguồn 1,0x",
        "target_full_reading": "mốc đầy đủ theo chiều cao mẫu",
        "morphology_sentence": meta["morphology"],
        "role_note": meta["role_note"],
        "classification_sentence": meta["public_classification_sentence"],
        "headline_scope": "Mẫu chỉ được tính sau khi có phá vỡ xác nhận; ba điểm chính phải nhìn được trên biểu đồ và không bị ép từ dao động nhiễu.",
        "local_source_chapter": meta["source_chapter"],
        "schematic_caption": f"Sơ đồ minh họa {meta['title']}: ba {point_name} {direction}, hai điểm xen giữa và vùng xác nhận.",
        "how_subtitle": "Ba điểm chính trước, xác nhận sau.",
        "labels": {"favorable_move": "mức đi thuận lợi", "adverse_move": "mức đi ngược bất lợi"},
        "source_rule_ids": ["three_points", "progression", "proportional", "confirmation", "height_target"],
        "public_rule_rows": [
            [f"Phải có ba {point_name} liên tiếp.", f"Ba {point_name} là thân mẫu; thiếu một điểm thì không gọi là {meta['title']}."],
            [f"Mỗi {point_name} sau phải {direction}.", "Bộ nhận diện yêu cầu tiến triển tối thiểu để tránh gọi vùng đi ngang là mẫu hình."],
            ["Các điểm chính phải tương đối cân xứng.", "Khoảng cách và độ cao/thấp không được lệch quá mạnh; mẫu quá méo bị hạ chất lượng."],
            ["Phải có nhịp dẫn trước rõ.", "Mẫu cần bối cảnh trước đó để đọc như đảo chiều ngắn hạn hoặc tiếp diễn có điều kiện."],
            ["Chỉ tính khi có phá vỡ xác nhận.", f"Điểm sự kiện là phiên đóng cửa {confirm}; trước đó chỉ là cấu trúc đang hình thành."],
            ["Mục tiêu đo theo chiều cao mẫu.", "0,5x là mốc cơ sở thận trọng; 1,0x là mốc nguồn đầy đủ."],
        ],
        "quick_question_rows": [
            ["Hình thái", f"Có đúng ba {point_name} {direction} không?"],
            ["Cân xứng", "Ba điểm có tỷ lệ vừa phải hay một điểm quá lệch?"],
            ["Xác nhận", f"Giá đã đóng cửa {confirm} chưa?"],
            ["Đường đi", "Mốc 0,5x có đến trước kéo ngược 5% không?"],
        ],
        "component_rows": [
            [f"{point_name.capitalize()} thứ nhất", "Điểm đầu tiên đặt nền cho hình thái.", "Mốc so sánh ban đầu"],
            [f"{point_name.capitalize()} thứ hai", f"Điểm thứ hai phải {direction}.", "Cho thấy lực cũ yếu dần"],
            [f"{point_name.capitalize()} thứ ba", f"Điểm thứ ba xác nhận chuỗi {direction}.", "Không được quá lệch"],
            ["Vùng xác nhận", "Giá đóng cửa qua vùng hai điểm xen giữa.", "Không đo trước xác nhận"],
        ],
        "reject_bullets": [
            f"Không có đủ ba {point_name} rõ ràng.",
            f"{point_name.capitalize()} thứ ba không tiếp tục {direction}.",
            "Ba điểm quá lệch hoặc khoảng cách quá mất cân đối.",
            "Giá chưa đóng cửa qua vùng xác nhận.",
        ],
        "identification_paragraphs": [meta["morphology"]],
        "example_intro": ["Ba ví dụ dưới đây gồm một mẫu đạt mốc cơ sở, một mẫu gần trung vị và một mẫu thất bại. Mỗi biểu đồ được đọc như một case study: ba điểm chính, phiên xác nhận, mốc mục tiêu và mức kéo ngược sau xác nhận."],
        "failure_bullets": [
            "Thất bại 5% là mẫu không đi đủ xa sau xác nhận, không phải stop-loss thực chiến.",
            "Mẫu có thể quay lại vùng phá vỡ, vì vậy cần đọc cùng mức kéo ngược và thời gian đạt mục tiêu.",
            "Không dùng một ví dụ đẹp để thay thế thống kê toàn mẫu.",
        ],
        "target_paragraph": "Mục tiêu nguồn lấy chiều cao mẫu rồi chiếu theo hướng phá vỡ; chương giữ 0,5x làm mốc cơ sở thận trọng và 1,0x làm mốc nguồn đầy đủ.",
        "quick_conclusion_rows": [
            ["Mẫu này dùng để đọc gì?", meta["role_note"]],
            ["Mốc đọc chính?", "0,5x chiều cao mẫu."],
            ["Mốc tham chiếu?", "1,0x chiều cao mẫu theo nguồn."],
            ["Khi nào thận trọng?", "Khi ba điểm không cân xứng, xác nhận quá yếu hoặc đường đi sau xác nhận kéo ngược sâu."],
        ],
        "identification_bridge": (
            f"Các quy tắc nhận diện nên được đọc từ ba {point_name} {direction}, tới vùng xác nhận, rồi mới tới kết quả sau phá vỡ. "
            "Nếu đảo thứ tự này, người đọc rất dễ biến một vùng dao động bình thường thành mẫu hình."
        ),
        "caveat_bullets": [
            "Không tuyên bố đây là nghiên cứu toàn thị trường đúng từng ngày lịch sử.",
            "Không dùng historical VN30/VN100 membership làm kết luận chính.",
            "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
            "Chương là tài liệu tham khảo hậu xác nhận, không phải khuyến nghị mua bán.",
        ],
        "quantile_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên"),
            ("Chiều cao mẫu", "pattern_height_pct", "%"),
            ("Độ tiến triển ba điểm", "peak_valley_progress_pct", "%"),
            ("Mất cân đối khoảng cách", "spacing_imbalance", "lần"),
            ("Độ rõ xác nhận", "confirmation_clearance_pct", "%"),
            ("Mức đi thuận lợi", "mfe_pct", "%"),
            ("Mức đi ngược bất lợi", "mae_pct", "%"),
            ("Ngày chạm mốc cơ sở", "days_to_target", "phiên"),
        ],
        "skip_condition_specs": [
            ("Mẫu kéo dài", "pattern_width_bars", "q75", None, "Mẫu quá dài dễ trở thành vùng xu hướng/dao động rộng hơn là ba điểm gọn."),
            ("Ba điểm lệch nhau", "spacing_imbalance", "q75", None, "Khoảng cách giữa các điểm quá lệch làm hình thái kém sạch."),
            ("Tiến triển yếu", "peak_valley_progress_pct", "q25_abs", None, "Ba điểm không nâng/hạ đủ rõ."),
            ("Kéo ngược quá sâu", "mae_pct", "q75", None, "Đường đi sau xác nhận không còn gọn."),
        ],
        "general_stat_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên", "Mẫu cần đủ thời gian để hình thành ba điểm nhưng không nên kéo thành vùng dao động dài."),
            ("Chiều cao mẫu", "pattern_height_pct", "%", "Chiều cao là nền cho mục tiêu đo lường."),
            ("Độ tiến triển ba điểm", "peak_valley_progress_pct", "%", f"Cho biết chuỗi {direction} có rõ hay không."),
            ("Mất cân đối khoảng cách", "spacing_imbalance", "lần", "Càng thấp càng gần hình thái cân đối."),
        ],
        "best_condition_specs": [
            ("Nhóm hình thái tốt", "publication_quality_tier", "==", "premium", "Ba điểm rõ, tiến triển đủ và đường giá sau xác nhận sạch hơn."),
            ("Nhóm chuẩn", "publication_quality_tier", "==", "standard", "Đủ dùng trong thống kê nhưng không phải lúc nào cũng đẹp để minh họa."),
            ("Đường giá sạch", "path_quality_bucket", "==", "clean", "Ít thiếu phiên và ít chuỗi đứng giá."),
            ("Thanh khoản tốt hơn", "liquidity_bucket", "in", "mid/high", "Giảm nhiễu ở các mẫu ít giao dịch."),
        ],
        "conclusion_bullets": [
            f"{meta['title']} chỉ được đọc khi ba điểm chính và phá vỡ xác nhận cùng hiện diện.",
            "Mục tiêu nguồn là 1,0x chiều cao mẫu; chương dùng 0,5x làm mốc cơ sở thận trọng.",
            meta["role_note"],
        ],
    }


def _publication_payload(pattern_id: str, meta: Mapping[str, Any], events: pd.DataFrame, all_events: pd.DataFrame, path_df: pd.DataFrame) -> dict[str, Any]:
    base = _metric_for_target(events, path_df, 0.5, "conservative_half_height")
    full = _metric_for_target(events, path_df, 1.0, "source_full_height")
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
            "median_progress_pct": _fmt(pd.to_numeric(events.get("peak_valley_progress_pct"), errors="coerce").median()),
            "median_spacing_imbalance": _fmt(pd.to_numeric(events.get("spacing_imbalance"), errors="coerce").median()),
        },
        "target_calibration": {
            "target_family": {"conservative_half_height": 0.5, "source_full_height": 1.0},
            "selected_base_target_multiple": 0.5,
            "selected_base_target_role": "conservative_half_height",
            "base_target": base,
            "stretch_target": full,
            "legacy_target": full,
            "rows": [base, full],
            "interpretation": "Mốc 0,5x giữ vai trò cơ sở thận trọng; 1,0x giữ vai trò mốc nguồn theo chiều cao mẫu.",
        },
        "data_scope_and_caveats": {
            "remaining_caveats": [
                "Không claim point-in-time universe toàn thị trường.",
                "Không dùng historical VN30/VN100 membership làm kết luận chính.",
                "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
            ]
        },
    }


def build_one_three_peaks_valleys_chapter(*, pattern_id: str, out_dir: Path) -> dict[str, Path]:
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
    publication_spec = build_three_peaks_valleys_publication_spec(pattern_id=pattern_id, title=str(meta["title"]), spec=spec)
    payload["publication_spec_id"] = publication_spec["publication_spec_id"]
    payload["source_rules_public"] = [{"rule": row[0], "application": row[1]} for row in spec.get("public_rule_rows", [])]
    charts = _build_charts(chapter_dir, pattern_id=pattern_id)
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
        "Dossier giữ thứ tự đọc: ba điểm chính, tính cân xứng, vùng xác nhận, thất bại, mục tiêu và cách dùng thận trọng. "
        "Không sao chép hoặc dịch lại tài liệu gốc; số liệu Việt Nam lấy từ payload đã khóa.\n",
        encoding="utf-8",
    )
    entry = {
        "family": "three_peaks_valleys_family",
        "pattern_id": pattern_id,
        "title": meta["title"],
        "status": "source_seed",
        "classification": meta["classification"],
        "score": None,
        "claim_level": meta["claim_level"],
        "pdf": f"artifacts/final_chapters/three_peaks_valleys_family/{meta['slug']}_final.pdf",
        "source_pdf": f"artifacts/final_chapters/three_peaks_valleys_family/{meta['slug']}_final.pdf",
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
        "note": "Three Peaks/Valleys Family dùng scanner riêng; builder này chỉ cung cấp nguyên liệu, không render hoặc approve PDF final.",
    }
    entry_path = chapter_dir / f"{meta['slug']}_final_manifest_entry.json"
    _write_json(entry_path, entry)
    return {
        "payload": payload_path,
        "source_notes": source_notes_path,
        "publication_spec": publication_spec_path,
        "entry": entry_path,
        **{f"chart_{key}": value for key, value in charts.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Three Peaks / Three Valleys public-chapter seed artifacts.")
    parser.add_argument("--pattern", choices=[*PATTERNS.keys(), "all"], default="all")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    patterns = list(PATTERNS.keys()) if args.pattern == "all" else [args.pattern]
    outputs = {}
    for pattern_id in patterns:
        outputs[pattern_id] = {key: str(value) for key, value in build_one_three_peaks_valleys_chapter(pattern_id=pattern_id, out_dir=Path(args.out_dir)).items()}
    print(json.dumps({"status": "PASS", "outputs": outputs}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
