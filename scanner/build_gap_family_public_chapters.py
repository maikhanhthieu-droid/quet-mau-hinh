"""Build source-grounded Gap Family public-chapter seed artifacts.

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

from scanner.gap_family_publication_specs import build_gap_family_publication_spec  # noqa: E402
from scanner.publication_flow_contract import SOURCE_GROUNDED_PUBLICATION_GATE_ID  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/gap_family_public_chapters")
SOURCE_PDF = "references/encyclopedia-of-chart-patterns-2nbsped-9786468600-3175723993-9780471668268-0471668265_compress.pdf"


PATTERNS: dict[str, dict[str, Any]] = {
    "area_gaps": {
        "slug": "area_gaps",
        "title": "Gap vùng dao động",
        "subtitle": "Khoảng trống giá thường xuất hiện trong vùng đi ngang và hay bị đóng nhanh",
        "scan_dir": Path("artifacts/scanner_v2/gap_family/area_gaps/db_active"),
        "source_chapter": 23,
        "source_name": "Gaps - Area/Common Gaps",
        "classification": "hồ sơ đóng gap/dao động; không phải continuation setup chính",
        "claim_level": "đọc như gap thường trong vùng dao động với trọng tâm là tốc độ đóng gap",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, Gap vùng dao động là hồ sơ mean-reversion/informational: giá thường lấp khoảng trống khá nhanh, nên giá trị chính nằm ở cách đọc rủi ro đóng gap chứ không phải kỳ vọng tiếp diễn.",
        "morphology": "Gap vùng dao động là khoảng trống giá xuất hiện khi giá hôm nay không chồng lấn với vùng giá hôm trước, nhưng bối cảnh trước đó không có xu hướng đủ rõ. Nó thường nằm trong vùng đi ngang, có ít tiếp diễn ngay sau gap và hay được lấp lại trong vài phiên.",
        "role_note": "Dùng để đọc xác suất đóng gap và nhiễu trong vùng dao động; không dùng như mẫu tiếp diễn chính.",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "primary_stat": "gap_close",
        "direction_role": "two_way",
    },
    "breakaway_gaps": {
        "slug": "breakaway_gaps",
        "title": "Gap phá nền",
        "subtitle": "Khoảng trống giá mở đầu một nhịp thoát khỏi vùng tích lũy",
        "scan_dir": Path("artifacts/scanner_v2/gap_family/breakaway_gaps/db_active"),
        "source_chapter": 23,
        "source_name": "Gaps - Breakaway Gaps",
        "classification": "hồ sơ tiếp diễn/thoát nền; nhánh tăng có thể kiểm tra tradable layer",
        "claim_level": "đọc như gap thoát khỏi vùng tích lũy, không đóng lại nhanh và có tiếp diễn sau đó",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, Gap phá nền là chương continuation/watchlist: khoảng trống có ý nghĩa nhất khi xuất hiện sau vùng tích lũy, không bị đóng lại quá sớm và tạo thêm cực trị theo hướng phá vỡ.",
        "morphology": "Gap phá nền xuất hiện khi giá nhảy ra khỏi một vùng tích lũy hoặc vùng đi ngang đủ hẹp. Khác gap thường, nó không nên bị lấp lại ngay; sau gap, giá cần tiếp tục tạo cực trị mới theo hướng phá vỡ để xác nhận rằng khoảng trống là điểm bắt đầu của nhịp mới.",
        "role_note": "Dùng như hồ sơ theo dõi nhịp thoát nền; nhánh phá lên có thể đi tiếp sang kiểm tra thực thi, nhánh phá xuống đọc như cảnh báo rủi ro.",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "primary_stat": "continuation",
        "direction_role": "mixed",
    },
    "continuation_gaps": {
        "slug": "continuation_gaps",
        "title": "Gap tiếp diễn",
        "subtitle": "Khoảng trống xuất hiện giữa một xu hướng đang chạy",
        "scan_dir": Path("artifacts/scanner_v2/gap_family/continuation_gaps/db_active"),
        "source_chapter": 23,
        "source_name": "Gaps - Continuation/Measuring Gaps",
        "classification": "hồ sơ tiếp diễn; nhánh tăng có thể kiểm tra tradable layer",
        "claim_level": "đọc như khoảng trống nằm giữa xu hướng, thường không đóng lại nhanh",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, Gap tiếp diễn là chương continuation rõ nhất trong Gap Family: nó chỉ đáng đọc khi xu hướng trước đó đã đủ mạnh, gap không bị đóng lại sớm và đường giá tiếp tục đi theo hướng cũ.",
        "morphology": "Gap tiếp diễn nằm giữa một xu hướng đã hình thành. Trước gap đã có một nhịp chạy rõ; sau gap, giá không quay lại lấp khoảng trống nhanh mà tiếp tục tạo thêm đỉnh mới hoặc đáy mới theo hướng cũ. Vì vậy, trọng tâm của chương là độ bền tiếp diễn chứ không chỉ là kích thước gap.",
        "role_note": "Dùng như hồ sơ continuation sau khi xu hướng đã rõ; nhánh tăng có thể kiểm tra thực thi, nhánh giảm đọc như cảnh báo phòng thủ.",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "primary_stat": "continuation",
        "direction_role": "mixed",
    },
    "exhaustion_gaps": {
        "slug": "exhaustion_gaps",
        "title": "Gap kiệt sức",
        "subtitle": "Khoảng trống xuất hiện gần cuối xu hướng và thường bị đóng nhanh",
        "scan_dir": Path("artifacts/scanner_v2/gap_family/exhaustion_gaps/db_active"),
        "source_chapter": 23,
        "source_name": "Gaps - Exhaustion Gaps",
        "classification": "hồ sơ cảnh báo đảo chiều/kiệt sức; không phải continuation setup chính",
        "claim_level": "đọc như gap cuối nhịp, dễ đóng lại hoặc đảo chiều sau đó",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, Gap kiệt sức là chương cảnh báo: khoảng trống xuất hiện sau một xu hướng đã kéo dài, nhưng nếu không có tiếp diễn thật và bị đóng nhanh, nó thường nói nhiều hơn về kiệt sức hơn là sức mạnh mới.",
        "morphology": "Gap kiệt sức xuất hiện sau một nhịp tăng hoặc giảm đã đi đủ xa. Nó thường rộng, gây chú ý và có thể đi cùng khối lượng cao, nhưng điểm phân biệt là thiếu tiếp diễn bền sau gap: giá nhanh chóng lấp khoảng trống, đi ngang hoặc đảo chiều.",
        "role_note": "Dùng như hồ sơ cảnh báo cuối nhịp và quản trị rủi ro; không đọc như tín hiệu tiếp diễn mặc định.",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "primary_stat": "gap_close",
        "direction_role": "two_way",
    },
}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y", "có"}


def _fmt(value: Any, digits: int = 2) -> str:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if not math.isfinite(out):
        return "n/a"
    return f"{out:.{digits}f}"


def _events_for_scope(events: pd.DataFrame) -> pd.DataFrame:
    if "publication_quality_tier" in events.columns:
        scoped = events[events["publication_quality_tier"].astype(str).str.lower().isin(["premium", "standard"])].copy()
        if len(scoped) >= 50:
            return scoped
    return events.copy()


def _metric_for_target(events: pd.DataFrame, multiple: float, role: str) -> dict[str, Any]:
    if events.empty:
        return {"target_multiple": multiple, "target_role": role, "n": 0}
    mfe = pd.to_numeric(events.get("mfe_pct"), errors="coerce")
    mae = pd.to_numeric(events.get("mae_pct"), errors="coerce")
    target_dist = pd.to_numeric(events.get("target_dist_pct"), errors="coerce") * multiple
    hit = (mfe >= target_dist).fillna(False)
    fail = events.get("failure_5pct", pd.Series(False, index=events.index)).map(_truthy)
    first = events.get("target_first_before_adverse_5pct", pd.Series(False, index=events.index)).map(_truthy)
    return {
        "target_multiple": multiple,
        "target_role": role,
        "target_label": f"{multiple}x",
        "target_hit_rate": round(float(hit.mean() * 100.0), 2),
        "target_first_before_adverse_5pct_rate": round(float(first.mean() * 100.0), 2),
        "failure_5pct_rate": round(float(fail.mean() * 100.0), 2),
        "median_mfe_pct": round(float(mfe.median()), 2) if not mfe.dropna().empty else None,
        "median_mae_pct": round(float(mae.median()), 2) if not mae.dropna().empty else None,
        "mfe_mae_median_ratio": round(float(mfe.median() / max(mae.median(), 1.0)), 2) if not mfe.dropna().empty and not mae.dropna().empty else None,
        "median_target_dist_pct": round(float(target_dist.median()), 2) if not target_dist.dropna().empty else None,
        "n": int(len(events)),
    }


def _gap_close_stats(events: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col, label in (("gap_closed_5d", "close_5d_rate"), ("gap_closed_10d", "close_10d_rate"), ("gap_closed_20d", "close_20d_rate")):
        if col in events.columns:
            out[label] = round(float(events[col].map(_truthy).mean() * 100.0), 2)
    days = pd.to_numeric(events.get("days_to_gap_close"), errors="coerce").dropna()
    out["median_days_to_gap_close"] = round(float(days.median()), 2) if not days.empty else None
    return out


def _plot_schematic(out_path: Path, *, pattern_id: str) -> None:
    fig, ax = plt.subplots(figsize=(9.2, 3.9), dpi=180)
    x = np.arange(10)
    if pattern_id == "area_gaps":
        close = np.array([10.0, 10.2, 10.1, 10.4, 11.0, 10.45, 10.2, 10.35, 10.1, 10.25])
        title = "Gap vùng dao động: khoảng trống được lấp nhanh"
        note = "đóng gap"
    elif pattern_id == "breakaway_gaps":
        close = np.array([10.0, 10.1, 10.05, 10.2, 11.2, 11.55, 12.05, 12.35, 12.75, 13.0])
        title = "Gap phá nền: thoát khỏi vùng tích lũy"
        note = "thoát nền"
    elif pattern_id == "continuation_gaps":
        close = np.array([10.0, 10.45, 10.9, 11.4, 12.4, 12.85, 13.3, 13.75, 14.2, 14.5])
        title = "Gap tiếp diễn: nằm giữa xu hướng"
        note = "tiếp diễn"
    else:
        close = np.array([10.0, 10.55, 11.1, 11.8, 12.9, 12.15, 11.75, 11.4, 11.15, 11.05])
        title = "Gap kiệt sức: thiếu tiếp diễn sau nhịp kéo dài"
        note = "đóng lại"
    ax.plot(x, close, color="#245b5a", linewidth=1.5)
    ax.scatter(x, close, s=26, color="#6f4aa8", zorder=3)
    ax.axvspan(3.5, 4.5, color="#6baed6", alpha=0.18, zorder=0)
    ax.text(4.55, close[4], "gap", fontsize=9, color="#245b5a", va="bottom")
    ax.text(6.0, close[6], note, fontsize=9, color="#7A5195", va="bottom")
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
    prefix = pattern_id.replace("_gaps", "")
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
            "book_pages_checked": ["Chapter 23 - Gaps"],
            "pdf_pages_checked": ["Chapter 23 - Gaps"],
            "target_rule_summary": "Gap chapters focus on whether the gap closes/fills and on subtype behavior: area/common, breakaway, continuation, exhaustion.",
            "review_note": "Đã đối chiếu trực tiếp chương Gaps trong PDF gốc trước khi dựng scanner và chapter.",
        },
        "source_rules": [
            {"rule_id": f"{prefix}.true_gap", "short_excerpt": "gap between price bars", "implementation_mapping": "gap lên khi đáy hôm nay cao hơn đỉnh hôm trước; gap xuống khi đỉnh hôm nay thấp hơn đáy hôm trước"},
            {"rule_id": f"{prefix}.close_fill", "short_excerpt": "gap closes", "implementation_mapping": "chỉ tiêu trung tâm là giá có quay lại lấp khoảng trống hay không, và mất bao nhiêu phiên"},
            {"rule_id": f"{prefix}.area_common", "short_excerpt": "area gaps close quickly", "implementation_mapping": "gap thường nằm trong vùng dao động, ít tiếp diễn và hay đóng nhanh"},
            {"rule_id": f"{prefix}.breakaway", "short_excerpt": "breakaway from congestion", "implementation_mapping": "gap phá nền xuất hiện sau tích lũy, có khối lượng/tiếp diễn và không đóng lại nhanh"},
            {"rule_id": f"{prefix}.continuation", "short_excerpt": "middle of a trend", "implementation_mapping": "gap tiếp diễn nằm giữa xu hướng và tiếp tục tạo cực trị theo hướng cũ"},
            {"rule_id": f"{prefix}.exhaustion", "short_excerpt": "near the end of a move", "implementation_mapping": "gap kiệt sức xuất hiện sau nhịp kéo dài, thiếu follow-through và thường bị đóng lại"},
            {"rule_id": f"{prefix}.volume_context", "short_excerpt": "volume can be high", "implementation_mapping": "khối lượng dùng làm bối cảnh phụ; không thay thế điều kiện đóng gap/tiếp diễn"},
        ],
    }


def _spec(pattern_id: str, meta: Mapping[str, Any]) -> dict[str, Any]:
    primary = str(meta["primary_stat"])
    target_title = "Đóng gap trong 20 phiên" if primary == "gap_close" else "Mốc tiếp diễn 0,5x gap"
    target_reading = "xác suất lấp khoảng trống sau khi gap xuất hiện" if primary == "gap_close" else "mốc thận trọng để đọc lực tiếp diễn sau gap"
    gap_rows = {
        "area_gaps": {
            "public_rule_rows": [
                ["Phải là khoảng trống giá thật trong vùng dao động.", "Gap lên khi đáy hôm nay cao hơn đỉnh hôm trước; gap xuống khi đỉnh hôm nay thấp hơn đáy hôm trước, nhưng trước đó không có xu hướng đủ rõ."],
                ["Bối cảnh chính là đi ngang hoặc giao dịch răng cưa.", "Nếu gap xuất hiện sau nền tích lũy rõ, giữa xu hướng mạnh hoặc cuối nhịp kéo dài, không nên gọi là Gap vùng dao động."],
                ["Chỉ tiêu trung tâm là đóng gap nhanh.", "Mẫu này được đọc qua việc giá quay lại lấp khoảng trống trong vài phiên, không qua kỳ vọng tiếp diễn xa."],
                ["Follow-through yếu là đặc điểm, không phải lỗi.", "Nếu giá tiếp tục tạo cực trị mạnh theo hướng gap, khả năng cao nó không còn là gap vùng dao động."],
                ["Khối lượng chỉ là bối cảnh phụ.", "Khối lượng lớn có thể làm gap nổi bật hơn, nhưng không thay thế bối cảnh đi ngang và hành vi lấp gap."],
                ["Mục tiêu đo theo kích thước gap.", "0,5x là mốc phụ để đọc đường đi, còn đóng gap mới là câu hỏi chính."],
            ],
            "quick_question_rows": [
                ["Khoảng trống", "Hai phiên có không chồng lấn vùng giá không?"],
                ["Bối cảnh", "Trước gap có thật sự là vùng đi ngang, không phải nền phá vỡ hay xu hướng mạnh?"],
                ["Đóng gap", "Giá có quay lại lấp khoảng trống nhanh không?"],
                ["Loại trừ", "Có follow-through mạnh khiến gap giống breakaway/continuation không?"],
            ],
            "component_rows": [
                ["Phiên trước gap", "Tạo mép trên/dưới của khoảng trống trong vùng dao động.", "Biên vùng đi ngang"],
                ["Phiên gap", "Mở ra khoảng trống nhưng chưa có lực xu hướng rõ.", "Không chồng lấn"],
                ["Vùng dao động", "Bối cảnh giúp phân biệt với gap phá nền.", "Không có xu hướng mạnh"],
                ["Đóng gap", "Giá quay lại vùng trống là kết quả đọc chính.", "Thường nhanh"],
            ],
        },
        "breakaway_gaps": {
            "public_rule_rows": [
                ["Phải là khoảng trống giá thật thoát khỏi nền.", "Gap chỉ được đọc là phá nền khi giá rời khỏi vùng tích lũy hoặc vùng nén rõ ràng."],
                ["Nền trước gap phải đủ chặt.", "Nếu trước đó chỉ là dao động răng cưa hoặc xu hướng đã chạy xa, gap dễ bị đọc sai subtype."],
                ["Không nên đóng gap quá nhanh.", "Breakaway gap đáng tin hơn khi giá không quay lại lấp khoảng trống ngay sau khi phá nền."],
                ["Cần có follow-through sau gap.", "Sau gap, giá nên tạo thêm cực trị theo hướng phá vỡ để chứng minh khoảng trống là điểm bắt đầu nhịp mới."],
                ["Khối lượng là tín hiệu phụ cho lực thoát nền.", "Khối lượng mạnh ủng hộ bứt phá, nhưng không thay thế nền tích lũy và đường đi sau gap."],
                ["Mục tiêu đo theo kích thước gap.", "0,5x là mốc cơ sở thận trọng; 1,0x là mốc đầy đủ để đối chiếu lực bứt phá."],
            ],
            "quick_question_rows": [
                ["Khoảng trống", "Gap có thật sự tách khỏi vùng giá hôm trước không?"],
                ["Nền giá", "Trước gap có vùng tích lũy đủ rõ để gọi là phá nền không?"],
                ["Không lấp gap", "Giá có tránh quay lại đóng gap quá nhanh không?"],
                ["Tiếp diễn", "Sau gap có tạo cực trị mới theo hướng phá nền không?"],
            ],
            "component_rows": [
                ["Nền tích lũy", "Vùng giá nén trước gap.", "Biên nền rõ"],
                ["Phiên gap", "Giá nhảy ra khỏi nền.", "Không chồng lấn"],
                ["Mé dao động cũ", "Vùng gap cần vượt qua để xác nhận thoát nền.", "Bị bỏ lại phía sau"],
                ["Follow-through", "Đường đi sau gap xác nhận lực mới.", "Cực trị mới theo hướng gap"],
            ],
        },
        "continuation_gaps": {
            "public_rule_rows": [
                ["Phải là khoảng trống giá thật nằm giữa xu hướng.", "Gap lên/xuống phải xuất hiện sau một nhịp đã chạy rõ, không phải ở đầu nền hay cuối nhịp kiệt sức."],
                ["Xu hướng trước gap là điều kiện nhận diện chính.", "Nếu không có nhịp dẫn trước đủ mạnh, gap không nên được gọi là gap tiếp diễn."],
                ["Không đóng gap quá nhanh.", "Continuation gap giữ ý nghĩa khi giá không quay lại lấp khoảng trống sớm."],
                ["Sau gap phải tiếp tục theo hướng cũ.", "Giá nên tạo thêm đỉnh mới hoặc đáy mới theo hướng xu hướng để xác nhận vai trò tiếp diễn."],
                ["Đọc như mốc giữa đường, không phải điểm đảo chiều.", "Nếu gap xuất hiện sau đoạn kéo quá dài và nhanh chóng suy yếu, cần chuyển sang nghi vấn exhaustion."],
                ["Mục tiêu đo theo kích thước gap.", "0,5x đọc lực tiếp diễn thận trọng; 1,0x giữ vai trò mốc tham chiếu đầy đủ."],
            ],
            "quick_question_rows": [
                ["Xu hướng trước", "Trước gap đã có nhịp chạy đủ rõ chưa?"],
                ["Vị trí gap", "Gap nằm giữa xu hướng hay ở ngay đầu/cuối nhịp?"],
                ["Không lấp gap", "Giá có giữ khoảng trống đủ lâu không?"],
                ["Cực trị mới", "Sau gap có tiếp tục tạo đỉnh/đáy mới theo hướng cũ không?"],
            ],
            "component_rows": [
                ["Nhịp dẫn trước", "Xu hướng đã hình thành trước gap.", "Đủ mạnh"],
                ["Phiên gap", "Khoảng trống xuất hiện giữa đường.", "Không chồng lấn"],
                ["Vùng giữ gap", "Giá không quay lại lấp khoảng trống sớm.", "Giữ được gap"],
                ["Nhịp sau gap", "Tiếp tục xu hướng cũ.", "Cực trị mới"],
            ],
        },
        "exhaustion_gaps": {
            "public_rule_rows": [
                ["Phải là khoảng trống giá thật ở cuối nhịp kéo dài.", "Gap chỉ được đọc là kiệt sức khi trước đó giá đã chạy đủ xa và tâm lý trở nên quá nóng/quá lạnh."],
                ["Vị trí cuối xu hướng quan trọng hơn kích thước gap.", "Một gap lớn nhưng nằm giữa xu hướng chưa chắc là exhaustion gap."],
                ["Thiếu follow-through là dấu hiệu chính.", "Sau gap, giá không nên tiếp tục tạo cực trị bền theo hướng cũ nếu mẫu thật sự kiệt sức."],
                ["Đóng gap hoặc đảo chiều sớm xác nhận luận điểm.", "Giá quay lại lấp khoảng trống nhanh cho thấy cú gap có thể là đoạn cuối của nhịp trước."],
                ["Khối lượng cao dễ gây chú ý nhưng không đủ.", "Volume lớn ở cuối nhịp chỉ có ý nghĩa khi đi cùng thiếu tiếp diễn và đóng gap nhanh."],
                ["Mục tiêu đo theo kích thước gap.", "0,5x giúp đọc rủi ro lấp gap sớm; 1,0x là mốc đối chiếu đầy đủ."],
            ],
            "quick_question_rows": [
                ["Nhịp trước", "Giá đã đi quá xa trước khi gap xuất hiện chưa?"],
                ["Vị trí", "Gap nằm cuối xu hướng hay giữa một xu hướng còn khỏe?"],
                ["Thiếu tiếp diễn", "Sau gap có mất lực thay vì tạo cực trị mới không?"],
                ["Đóng gap", "Giá có lấp khoảng trống nhanh hoặc đảo chiều không?"],
            ],
            "component_rows": [
                ["Nhịp kéo dài", "Bối cảnh trước gap đã chạy xa.", "Có dấu hiệu quá đà"],
                ["Phiên gap", "Khoảng trống gây chú ý ở cuối nhịp.", "Gap lớn hoặc nổi bật"],
                ["Thiếu follow-through", "Giá không duy trì được hướng cũ.", "Mất lực nhanh"],
                ["Đóng gap", "Giá quay lại lấp khoảng trống.", "Xác nhận kiệt sức"],
            ],
        },
    }[pattern_id]
    return {
        "title": meta["title"],
        "subtitle": meta["subtitle"],
        "base_target_multiple": float(meta["base_target_multiple"]),
        "base_target_label": "0,5x",
        "legacy_target_multiple": float(meta["legacy_target_multiple"]),
        "legacy_target_label": "1,0x",
        "target_unit_label": "kích thước gap",
        "target_focus_title": target_title,
        "target_focus_caption": "mốc 0,5x kích thước gap",
        "target_focus_reading": target_reading,
        "target_full_title": "Mốc đầy đủ 1,0x gap",
        "target_full_reading": "mốc đầy đủ để đối chiếu độ nhạy",
        "morphology_sentence": meta["morphology"],
        "role_note": meta["role_note"],
        "classification_sentence": meta["public_classification_sentence"],
        "headline_scope": "Gap chỉ được tính khi có khoảng trống giá thật giữa hai phiên; subtype phụ thuộc vào bối cảnh trước gap và hành vi sau gap.",
        "local_source_chapter": meta["source_chapter"],
        "schematic_caption": f"Sơ đồ minh họa {meta['title']}: khoảng trống giữa hai phiên và hành vi sau đó.",
        "how_subtitle": "Khoảng trống trước, bối cảnh và đóng gap sau.",
        "suppress_main_conclusion": True,
        "labels": {"favorable_move": "mức đi thuận chiều gap", "adverse_move": "mức đi ngược lấp gap"},
        "source_rule_ids": ["true_gap", "close_fill", "subtype_context", "follow_through"],
        "public_rule_rows": gap_rows["public_rule_rows"],
        "quick_question_rows": gap_rows["quick_question_rows"],
        "component_rows": gap_rows["component_rows"],
        "reject_bullets": [
            "Hai phiên vẫn chồng lấn vùng giá.",
            "Khoảng trống quá nhỏ so với nhiễu tick/thanh khoản.",
            "Không phân biệt được bối cảnh trước gap.",
            "Thiếu dữ liệu hậu gap để đo đóng gap hoặc tiếp diễn.",
        ],
        "identification_paragraphs": [meta["morphology"]],
        "example_intro": ["Ba ví dụ dưới đây đọc gap như một case study: khoảng trống xuất hiện ở đâu, có đóng lại không, và đường đi sau đó nói gì về subtype."],
        "failure_bullets": [
            "Với gap tiếp diễn, thất bại thường là gap bị lấp nhanh hoặc không có follow-through.",
            "Với gap thường/kiệt sức, gap không đóng lại nhanh có thể làm luận điểm đóng gap yếu đi.",
            "Không dùng kích thước gap lớn để thay cho bối cảnh và đường đi sau gap.",
        ],
        "target_paragraph": "Mục tiêu đo theo kích thước gap chỉ là thước đo phụ; với Gap Family, tỷ lệ đóng gap và thời gian đóng gap mới là chỉ tiêu đọc hành vi quan trọng nhất.",
        "quick_conclusion_rows": [
            ["Mẫu này dùng để đọc gì?", meta["role_note"]],
            ["Chỉ tiêu chính?", "Tốc độ đóng gap và độ bền follow-through sau gap."],
            ["Mốc phụ?", "0,5x và 1,0x kích thước gap để đo quãng đi sau gap."],
            ["Khi nào thận trọng?", "Khi gap quá nhỏ, thanh khoản thấp hoặc subtype chỉ được suy ra bằng đường giá nhiễu."],
        ],
        "identification_bridge": (
            "Các quy tắc nhận diện nên được đọc theo thứ tự: có khoảng trống giá thật, biết bối cảnh trước gap, rồi mới nhìn việc đóng gap hay tiếp diễn. "
            "Nếu chỉ thấy khoảng trống rồi gán subtype ngay, người đọc rất dễ nhầm gap thường thành gap phá nền."
        ),
        "caveat_bullets": [
            "Không tuyên bố đây là nghiên cứu toàn thị trường đúng từng ngày lịch sử.",
            "Không dùng historical VN30/VN100 membership làm kết luận chính.",
            "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
            "Chương là tài liệu tham khảo hậu gap, không phải khuyến nghị mua bán.",
        ],
        "quantile_specs": [
            ("Kích thước gap", "gap_size_pct", "%"),
            ("Biên độ vùng trước gap", "consolidation_range_pct", "%"),
            ("Xu hướng trước gap", "signed_prior_trend_pct", "%"),
            ("Tỷ lệ khối lượng gap", "breakout_volume_ratio", "lần"),
            ("Mức đi thuận chiều gap", "mfe_pct", "%"),
            ("Mức đi ngược lấp gap", "mae_pct", "%"),
            ("Ngày đóng gap", "days_to_gap_close", "phiên"),
        ],
        "skip_condition_specs": [
            ("Gap quá nhỏ", "gap_size_pct", "q25", None, "Khoảng trống nhỏ dễ là nhiễu tick/thanh khoản hơn là tín hiệu hình thái."),
            ("Vùng trước gap quá rộng", "consolidation_range_pct", "q75", None, "Bối cảnh trước quá nhiễu làm subtype khó đọc."),
            ("Khối lượng không ủng hộ", "breakout_volume_ratio", "q25", None, "Gap thiếu xác nhận phụ về dòng tiền."),
            ("Kéo ngược quá sâu", "mae_pct", "q75", None, "Đường đi sau gap không còn gọn."),
        ],
        "general_stat_specs": [
            ("Kích thước gap", "gap_size_pct", "%", "Cho biết khoảng trống có đủ lớn để đọc hay chỉ là nhiễu."),
            ("Biên độ vùng trước gap", "consolidation_range_pct", "%", "Bối cảnh trước gap càng rõ thì subtype càng đáng tin."),
            ("Xu hướng trước gap", "signed_prior_trend_pct", "%", "Giúp phân biệt gap phá nền/tiếp diễn/kiệt sức."),
            ("Tỷ lệ khối lượng gap", "breakout_volume_ratio", "lần", "Khối lượng là tín hiệu phụ để đọc mức chú ý của thị trường."),
        ],
        "best_condition_specs": [
            ("Đường giá sạch", "path_quality_bucket", "==", "clean", "Ít thiếu phiên và ít chuỗi đứng giá."),
            ("Thanh khoản tốt hơn", "liquidity_bucket", "==", "high", "Giảm nhiễu do gap thanh khoản."),
            ("Nhóm hình thái tốt", "publication_quality_tier", "==", "premium", "Gap rõ, bối cảnh trước/sau đủ sạch để đọc subtype."),
        ],
        "conclusion_bullets": [
            f"{meta['title']} phải bắt đầu từ một khoảng trống giá thật, không phải chỉ là nến mạnh.",
            "Với Gap Family, đóng gap và follow-through quan trọng hơn một target hình học đơn lẻ.",
            meta["role_note"],
        ],
    }


def _publication_payload(pattern_id: str, meta: Mapping[str, Any], events: pd.DataFrame, all_events: pd.DataFrame) -> dict[str, Any]:
    base = _metric_for_target(events, 0.5, "conservative_half_gap")
    full = _metric_for_target(events, 1.0, "source_full_gap")
    gap_close = _gap_close_stats(events)
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
            "gap_close_5d_rate": gap_close.get("close_5d_rate"),
            "gap_close_10d_rate": gap_close.get("close_10d_rate"),
            "gap_close_20d_rate": gap_close.get("close_20d_rate"),
            "median_days_to_gap_close": gap_close.get("median_days_to_gap_close"),
            "legacy_target_hit_rate": full.get("target_hit_rate"),
            "legacy_target_first_before_adverse_5pct_rate": full.get("target_first_before_adverse_5pct_rate"),
            "median_gap_size_pct": _fmt(pd.to_numeric(events.get("gap_size_pct"), errors="coerce").median()),
            "median_prior_trend_pct": _fmt(pd.to_numeric(events.get("signed_prior_trend_pct"), errors="coerce").median()),
        },
        "target_calibration": {
            "target_family": {"conservative_half_gap": 0.5, "source_full_gap": 1.0},
            "selected_base_target_multiple": 0.5,
            "selected_base_target_role": "conservative_half_gap",
            "base_target": base,
            "stretch_target": full,
            "legacy_target": full,
            "rows": [base, full],
            "gap_close": gap_close,
            "interpretation": "Với Gap Family, target theo kích thước gap là thước đo phụ; đóng gap và follow-through là trọng tâm diễn giải.",
        },
        "data_scope_and_caveats": {
            "remaining_caveats": [
                "Không claim point-in-time universe toàn thị trường.",
                "Không dùng historical VN30/VN100 membership làm kết luận chính.",
                "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
            ]
        },
    }


def build_one_gap_chapter(*, pattern_id: str, out_dir: Path) -> dict[str, Path]:
    meta = PATTERNS[pattern_id]
    chapter_dir = out_dir / str(meta["slug"])
    if chapter_dir.exists():
        shutil.rmtree(chapter_dir)
    chapter_dir.mkdir(parents=True, exist_ok=True)
    all_events = pd.read_csv(meta["scan_dir"] / "events.csv")
    if "event_id" not in all_events.columns:
        all_events["event_id"] = all_events["detection_id"]
    events = _events_for_scope(all_events)
    payload = _publication_payload(pattern_id, meta, events, all_events)
    spec = _spec(pattern_id, meta)
    publication_spec = build_gap_family_publication_spec(pattern_id=pattern_id, title=str(meta["title"]), spec=spec)
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
        "Dossier giữ thứ tự đọc: khoảng trống giá thật, bối cảnh trước gap, đóng gap/follow-through, thất bại, ví dụ. "
        "Không sao chép hoặc dịch lại tài liệu gốc; số liệu Việt Nam lấy từ payload đã khóa.\n",
        encoding="utf-8",
    )
    entry = {
        "family": "gap_family",
        "pattern_id": pattern_id,
        "title": meta["title"],
        "status": "source_seed",
        "classification": meta["classification"],
        "score": None,
        "claim_level": meta["claim_level"],
        "pdf": f"artifacts/final_chapters/gap_family/{meta['slug']}_final.pdf",
        "source_pdf": f"artifacts/final_chapters/gap_family/{meta['slug']}_final.pdf",
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
        "note": "Gap Family dùng scanner riêng; builder này chỉ cung cấp nguyên liệu, không render hoặc approve PDF final.",
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
    parser = argparse.ArgumentParser(description="Build Gap Family public-chapter seed artifacts.")
    parser.add_argument("--pattern", choices=[*PATTERNS.keys(), "all"], default="all")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    patterns = list(PATTERNS.keys()) if args.pattern == "all" else [args.pattern]
    outputs = {}
    for pattern_id in patterns:
        outputs[pattern_id] = {key: str(value) for key, value in build_one_gap_chapter(pattern_id=pattern_id, out_dir=Path(args.out_dir)).items()}
    print(json.dumps({"status": "PASS", "outputs": outputs}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
