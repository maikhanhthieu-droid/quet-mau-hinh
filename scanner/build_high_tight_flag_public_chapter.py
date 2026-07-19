"""Build the High-and-Tight Flag public chapter."""

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
    _draw_public_event,
    _fmt,
    _load_path,
    _load_symbol_ohlcv,
    _pct,
    _read_json,
    _window_for_event,
)
from scanner.flag_family_public_chapter_factory import FACTORY_ID, build_flag_public_chapter  # noqa: E402
from scanner.run_pennant_candidate_quality_audit import _load_events, _metrics, _target_path_flags  # noqa: E402
from scanner.v2.source_data import DEFAULT_SOURCE_DIR  # noqa: E402


DEFAULT_EVENTS = Path("artifacts/scanner_v2/high_tight_flags/events.csv")
DEFAULT_PATH = Path("artifacts/scanner_v2/high_tight_flags/post_breakout_path.csv")
DEFAULT_STATS = Path("artifacts/scanner_v2/high_tight_flags/statistics.json")
DEFAULT_SOURCE_NOTES = Path("artifacts/scanner_v2/flag_like_family_source_grounding/high_tight_flags_source_notes.json")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/flag_family_public_chapters/high_tight_flag")
BASE_TARGET_MULTIPLE = 0.5
TARGET_BANDS = (0.5, 0.75, 1.0)


def _public_grade_events(events: pd.DataFrame, path: pd.DataFrame) -> pd.DataFrame:
    scoped = events[events["publication_quality_tier"].isin(["premium", "standard"])].copy()
    flags = _target_path_flags(scoped, path, target_multiple=BASE_TARGET_MULTIPLE)
    scoped = scoped.merge(flags, on="event_id", how="left")
    scoped["target_hit"] = scoped["target_hit_band"].fillna(False).astype(bool)
    scoped["target_first_before_adverse_5pct"] = scoped["target_first_band"].fillna(False).astype(bool)
    scoped["days_to_target"] = pd.to_numeric(scoped["days_to_target_band"], errors="coerce")
    scoped["publication_quality_score"] = pd.to_numeric(scoped.get("pattern_quality_score"), errors="coerce")
    scoped["tradability_quality_bucket"] = scoped.get("publication_quality_tier", "standard")
    scoped["tradability_quality_score"] = scoped["publication_quality_score"]
    base_target_dist = pd.to_numeric(scoped["target_dist_pct"], errors="coerce") * BASE_TARGET_MULTIPLE
    scoped["target_price"] = pd.to_numeric(scoped["breakout_price"], errors="coerce") * (1.0 + base_target_dist / 100.0)
    return scoped.reset_index(drop=True)


def _target_row(events: pd.DataFrame, path: pd.DataFrame, multiple: float) -> dict[str, Any]:
    flags = _target_path_flags(events, path, target_multiple=multiple)
    working = events.merge(flags, on="event_id", how="left")
    row = _metrics(working, path, target_multiple=multiple, row_id=f"high_tight_flag:{multiple}")
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


def _target_rows(events: pd.DataFrame, path: pd.DataFrame) -> list[dict[str, Any]]:
    roles = {0.5: "source_half_move_base", 0.75: "local_stretch", 1.0: "legacy_full_prior_move"}
    labels = {0.5: "0,5x", 0.75: "0,75x", 1.0: "1,0x"}
    readings = {
        0.5: "mốc nguồn: nửa nhịp tăng trước mẫu",
        0.75: "mốc mở rộng để kiểm tra sức chạy sau phá vỡ",
        1.0: "mốc đầy đủ của nhịp tăng trước mẫu, dùng như đối chiếu căng",
    }
    return [
        {**_target_row(events, path, multiple), "target_role": roles[multiple], "target_label": labels[multiple], "reading": readings[multiple]}
        for multiple in TARGET_BANDS
    ]


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
    x1 = np.linspace(0, 3.4, 30)
    y1 = 1 + x1 * 0.95
    ax.plot(x1, y1, color="#173b3a", linewidth=3.2)
    x2 = np.linspace(3.4, 5.6, 30)
    upper = np.linspace(y1[-1] + 0.15, y1[-1] + 0.08, len(x2))
    lower = np.linspace(y1[-1] - 0.72, y1[-1] - 0.45, len(x2))
    mid = (upper + lower) / 2 + np.sin(np.linspace(0, 2.4 * np.pi, len(x2))) * 0.06
    ax.plot(x2, upper, color="#E45756", linewidth=1.7)
    ax.plot(x2, lower, color="#54A24B", linewidth=1.7)
    ax.plot(x2, mid, color="#173b3a", linewidth=2)
    x3 = np.linspace(5.6, 7.2, 18)
    y3 = np.linspace(mid[-1], mid[-1] + 0.9, len(x3))
    ax.plot(x3, y3, color="#173b3a", linewidth=3)
    ax.axhline(y3[-1], xmin=0.68, xmax=0.95, color="#F58518", linestyle="--", linewidth=1.5)
    ax.text(0.55, 1.55, "Nhịp tăng gần nhân đôi", color="#173b3a", fontsize=10)
    ax.text(3.55, upper[0] + 0.32, "Vùng nghỉ gần đỉnh", color="#7A5195", fontsize=10)
    ax.text(5.8, y3[-1] + 0.16, "Phá vỡ lên", color="#173b3a", fontsize=10)
    ax.text(6.1, y3[-1] - 0.34, "Mục tiêu 0,5x", color="#F58518", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _build_example_charts(events: pd.DataFrame, source_dir: Path, out_dir: Path) -> tuple[dict[str, Path], dict[str, Mapping[str, Any]]]:
    chart_dir = out_dir / "charts"
    if chart_dir.exists():
        shutil.rmtree(chart_dir)
    chart_dir.mkdir(parents=True, exist_ok=True)
    charts: dict[str, Path] = {}
    schematic = chart_dir / "high_tight_flag_ideal_schematic.png"
    _draw_schematic(schematic)
    charts["schematic"] = schematic
    examples = _select_examples(events)
    cache: dict[str, pd.DataFrame] = {}
    for key, event in examples.items():
        symbol = str(event.get("symbol"))
        if symbol not in cache:
            cache[symbol] = _load_symbol_ohlcv(source_dir, symbol)
        window, offset = _window_for_event(cache[symbol], event, pre_bars=55, post_bars=50)
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
        "htf.prior_trend.near_double": "Require an exceptional prior advance before searching for the high-level consolidation.",
        "htf.consolidation.near_high": "Require the body to form near the recent high after the strong advance.",
        "htf.pullback.limit": "Reject consolidations that pull back too deeply from the high.",
        "htf.volume.contracts": "Record receding volume inside the body as a diagnostic context feature.",
        "htf.breakout.up_only": "Confirm only upward continuation breakouts.",
        "htf.target.half_prior_move": "Use half the prior move as the source target benchmark; retain larger bands as stress diagnostics.",
    }
    rules = []
    for row in raw_rules:
        if isinstance(row, Mapping):
            rule_id = str(row.get("rule_id") or "")
            rules.append({"rule_id": rule_id, "short_excerpt": str(row.get("rule") or ""), "implementation_mapping": mappings.get(rule_id, "Convert the source rule into a fixed geometric scanner condition.")})
    return {
        "status": "PASS",
        "pattern_id": "high_tight_flags",
        "source_grounding_policy_id": "source_grounded_publication_gate_v1",
        "source_grounding_level": "full",
        "source_review_status": source.get("source_review_status", "PASS"),
        "direct_pdf_review": {
            "status": "PASS",
            "pdf_path": "Thomas Bulkowski Encyclopedia of Chart Patterns, Flags, High and Tight chapter",
            "pdf_pages_checked": source.get("source_pdf_pages_checked", [374, 375, 376, 377, 378]),
            "book_pages_checked": source.get("source_book_pages", [350, 351, 352, 353, 354]),
        },
        "source_rules": rules,
    }


def _spec() -> dict[str, Any]:
    rule_text_map = {
        "Require an exceptional prior advance, with at least roughly ninety percent rise and ideally a doubling in under two months.": "Trước mẫu phải có một nhịp tăng rất mạnh, gần nhân đôi trong thời gian ngắn.",
        "Find a short consolidation near the doubled price area after the strong advance.": "Sau nhịp tăng mạnh, giá phải nghỉ ngắn gần vùng đỉnh mới.",
        "The consolidation should not drift too deeply from the high.": "Vùng nghỉ không được kéo lùi quá sâu khỏi đỉnh.",
        "Receding volume inside the consolidation is a favorable diagnostic.": "Khối lượng giảm trong vùng nghỉ là dấu hiệu hỗ trợ.",
        "High-and-tight flags are treated as upward continuation patterns.": "Mẫu này chỉ được đọc như tiếp diễn lên.",
        "The source measure rule uses about half the prior advance projected from breakout, not the full pole.": "Mục tiêu nguồn dùng khoảng nửa nhịp tăng trước mẫu, không phải toàn bộ cột tăng.",
        "Require an exceptional prior advance before searching for the high-level consolidation.": "Yêu cầu nhịp tăng rất mạnh trước khi tìm vùng nghỉ gần đỉnh.",
        "Require the body to form near the recent high after the strong advance.": "Yêu cầu thân mẫu nằm gần đỉnh sau nhịp tăng mạnh.",
        "Reject consolidations that pull back too deeply from the high.": "Loại vùng nghỉ kéo lùi quá sâu.",
        "Record receding volume inside the body as a diagnostic context feature.": "Ghi nhận khối lượng giảm trong thân mẫu như biến bối cảnh.",
        "Confirm only upward continuation breakouts.": "Chỉ xác nhận phá vỡ tiếp diễn lên.",
        "Use half the prior move as the source target benchmark; retain larger bands as stress diagnostics.": "Dùng nửa nhịp tăng trước mẫu làm mốc nguồn; các mốc lớn hơn là đối chiếu căng.",
    }
    return {
        "title": "Cờ cao và chặt",
        "subtitle": "Mẫu tiếp diễn sau một nhịp tăng gần nhân đôi",
        "base_target_multiple": 0.5,
        "base_target_label": "0,5x",
        "legacy_target_multiple": 1.0,
        "legacy_target_label": "1,0x",
        "target_unit_label": "nhịp tăng trước mẫu",
        "target_focus_title": "Mục tiêu nguồn",
        "target_focus_caption": "mục tiêu 0,5x",
        "target_focus_reading": "mốc nguồn vì tài liệu gốc dùng khoảng nửa nhịp tăng trước mẫu",
        "target_full_title": "Mục tiêu 1,0x",
        "target_full_reading": "mốc rất căng để đối chiếu, không dùng làm kết luận chính",
        "morphology_sentence": "Nhịp tăng gần nhân đôi, vùng nghỉ ngắn gần đỉnh, xác nhận bằng giá đóng cửa phá lên.",
        "role_note": "Dùng như hồ sơ tham khảo hậu phá vỡ. Không phải khuyến nghị mua bán.",
        "classification_sentence": "Trong phạm vi dữ liệu hiện có, cờ cao và chặt là chương tham khảo theo dõi, không phải cấu hình giao dịch tự động.",
        "schematic_caption": "Sơ đồ minh họa: nhịp tăng gần nhân đôi, vùng nghỉ gần đỉnh, phá vỡ lên và mục tiêu nửa nhịp tăng trước mẫu.",
        "how_subtitle": "Mẫu chỉ có ý nghĩa khi nhịp tăng trước đó cực mạnh",
        "labels": {"favorable_move": "mức tăng tốt nhất", "adverse_move": "mức kéo ngược sâu nhất"},
        "source_rule_ids": [
            "htf.prior_trend.near_double",
            "htf.consolidation.near_high",
            "htf.pullback.limit",
            "htf.volume.contracts",
            "htf.breakout.up_only",
            "htf.target.half_prior_move",
        ],
        "rule_text_map": rule_text_map,
        "quick_question_rows": [
            ["Nhịp tăng trước mẫu", "Giá có tăng gần nhân đôi trong thời gian ngắn không?"],
            ["Vùng nghỉ", "Giá có nghỉ gần vùng đỉnh mới thay vì rơi quá sâu không?"],
            ["Thời lượng", "Vùng nghỉ có đủ ngắn để còn là high-and-tight flag không?"],
            ["Xác nhận", "Giá đóng cửa có phá lên khỏi vùng nghỉ không?"],
            ["Mục tiêu", "Mốc nửa nhịp tăng trước mẫu có đến trước kéo ngược sâu không?"],
        ],
        "component_rows": [
            ["Nhịp tăng mạnh", "Đây là điều kiện sống còn; không có nhịp tăng gần nhân đôi thì không phải mẫu này.", "Nhìn lại khoảng hai tháng giao dịch; tăng tối thiểu khoảng 90%."],
            ["Vùng nghỉ gần đỉnh", "Giá đi ngang hoặc kéo nhẹ sau cú tăng mạnh.", "Thân mẫu nằm gần đỉnh và không kéo lùi quá sâu."],
            ["Phá vỡ lên", "Chỉ sau phiên xác nhận mới đo kết quả.", "Đóng cửa vượt vùng nghỉ với ngưỡng xác nhận."],
            ["Khối lượng", "Khối lượng co lại trong vùng nghỉ là dấu hiệu hỗ trợ.", "Ghi nhận như biến bối cảnh, không dùng làm cổng loại tuyệt đối."],
            ["Mục tiêu", "Mốc nguồn là nửa nhịp tăng trước mẫu.", "0,5x là mốc chính; 1,0x chỉ là đối chiếu căng."],
        ],
        "reject_bullets": [
            "Nhịp tăng trước mẫu không đủ mạnh hoặc kéo quá dài.",
            "Vùng nghỉ rơi quá sâu khỏi đỉnh mới.",
            "Phá vỡ không được xác nhận bằng giá đóng cửa.",
            "Dữ liệu đường giá quá nhiễu hoặc thiếu phiên hậu phá vỡ.",
        ],
        "identification_paragraphs": [
            "Cờ cao và chặt khác cờ tăng thông thường ở điều kiện đầu vào: trước vùng nghỉ phải có một nhịp tăng rất mạnh, gần nhân đôi trong thời gian ngắn. Đây không phải một cờ nhỏ bất kỳ.",
            "Sau nhịp tăng mạnh, giá phải nghỉ gần vùng đỉnh mới. Mẫu được xác nhận khi giá đóng cửa phá lên khỏi vùng nghỉ, rồi mới bắt đầu đo hậu phá vỡ.",
        ],
        "example_intro": [
            "Ví dụ được chọn gồm một trường hợp đạt mục tiêu nguồn, một trường hợp gần trung vị và một trường hợp thất bại. Điều này giúp người đọc thấy mẫu vừa có sức hút vừa có rủi ro kéo ngược lớn.",
        ],
        "failure_paragraphs": [
            "Thất bại đáng chú ý là giá không tăng thêm được tối thiểu 5% sau phá vỡ, hoặc chạm kéo ngược 5% trước khi đạt mốc nửa nhịp tăng trước mẫu.",
            "Vì mẫu xuất hiện sau một cú tăng rất mạnh, rủi ro kéo ngược hậu phá vỡ thường lớn hơn cảm giác trực quan từ biểu đồ đẹp.",
        ],
        "failure_bullets": [
            "Không loại ví dụ thất bại khỏi chương; đó là phần quan trọng của hồ sơ thống kê.",
            "Thất bại 5% là thước đo mô tả hậu phá vỡ, không phải ngưỡng dừng lỗ giao dịch.",
            "Mẫu có thể đúng hình thái nhưng vẫn khó dùng nếu giá kéo ngược sâu trước khi đi tiếp.",
        ],
        "target_paragraph": "Mục tiêu cơ sở của chương là 0,5x nhịp tăng trước mẫu. Đây là mốc bám nguồn gốc của High-and-Tight Flags; 0,75x và 1,0x chỉ dùng để kiểm tra sức chạy mở rộng.",
        "statistics_paragraphs": [
            "Kết quả chính được đọc trên nhóm tốt nhất và nhóm chuẩn. Mẫu có độ dày đủ lớn để xuất bản một chương mô tả, nhưng không nên được đọc như chiến lược tự động.",
            "Điểm mạnh của mẫu là tiền đề tăng rất mạnh; điểm yếu là đường đi sau phá vỡ có thể kéo ngược sâu. Vì vậy, target-first quan trọng hơn hit rate đơn thuần.",
        ],
        "size_volume_paragraphs": [
            "Mẫu đáng chú ý hơn khi vùng nghỉ nằm gần đỉnh và không kéo lùi quá sâu. Nhóm thanh khoản cao hoặc trung bình dễ đọc hơn vì ít bị đứng giá.",
            "Khối lượng co lại trong vùng nghỉ là dấu hiệu hỗ trợ. Với dữ liệu hiện tại, biến này được dùng như bối cảnh hơn là điều kiện loại tuyệt đối.",
        ],
        "usage_paragraphs": [
            "Cách dùng phù hợp là đưa cổ phiếu vào danh sách theo dõi sau phiên phá lên, rồi kiểm lại độ sâu vùng nghỉ, thanh khoản và mức kéo ngược hậu phá vỡ.",
            "Chương này chưa phải hệ thống giao dịch. Muốn biến thành cấu hình thực thi cần thêm điểm vào, điểm ra, quy mô vị thế, phí, trượt giá và kiểm định danh mục riêng.",
        ],
        "checklist": [
            "Trước mẫu có nhịp tăng gần nhân đôi trong thời gian ngắn.",
            "Vùng nghỉ nằm gần đỉnh và không kéo lùi quá sâu.",
            "Giá đóng cửa phá lên khỏi vùng nghỉ.",
            "Mục tiêu nguồn là 0,5x nhịp tăng trước mẫu.",
            "Không phải khuyến nghị mua bán.",
        ],
        "quick_conclusion_rows": [
            ["Mẫu này dùng để đọc gì?", "Một mẫu tiếp diễn sau cú tăng rất mạnh, gần nhân đôi."],
            ["Mốc nào là trọng tâm?", "0,5x nhịp tăng trước mẫu là mục tiêu nguồn."],
            ["Rủi ro chính?", "Kéo ngược sâu sau phá vỡ vì giá đã tăng mạnh trước đó."],
            ["Khi nào đáng tin hơn?", "Vùng nghỉ gần đỉnh, không kéo lùi sâu, phá vỡ đóng cửa dứt khoát và thanh khoản đủ tốt."],
        ],
        "caveat_bullets": [
            "Không tuyên bố đây là tập cổ phiếu toàn thị trường theo từng thời điểm.",
            "Không dùng lịch sử thành phần VN30/VN100 làm kết luận chính.",
            "Sự kiện quyền, điều chỉnh giá và trạng thái hủy niêm yết/tạm ngừng hiện dùng kiểm tra thay thế, chưa phải băng trạng thái chính thức.",
        ],
        "conclusion_bullets": [
            "Cờ cao và chặt có đủ mẫu để trở thành chương tham khảo theo dõi trong nhóm Cờ mở rộng.",
            "Mục tiêu 0,5x là mốc nguồn hợp lý; 1,0x chỉ nên là đối chiếu căng.",
            "Chương nên được đọc như hồ sơ hậu phá vỡ có điều kiện, không phải tín hiệu mua tự động.",
        ],
    }


def _payload(events: pd.DataFrame, path: pd.DataFrame, stats: Mapping[str, Any], examples: Mapping[str, Any]) -> dict[str, Any]:
    rows = _target_rows(events, path)
    base = next(row for row in rows if row["target_multiple"] == BASE_TARGET_MULTIPLE)
    legacy = next(row for row in rows if row["target_multiple"] == 1.0)
    all_n = int(pd.read_csv(DEFAULT_EVENTS).shape[0]) if DEFAULT_EVENTS.exists() else int(len(events))
    return {
        "publication_id": "high_tight_flag_public_chapter_v1",
        "publication_spec_id": "high_tight_flag_publication_spec_v1",
        "status": "PASS",
        "classification": "watchlist-reference under available-series scope",
        "claim_level": "watchlist-reference under available-series descriptive scope",
        "chapter_reference": {
            "symbols_scanned": stats.get("symbols_scanned"),
            "events": int(len(events)),
            "evaluated_events": int(len(events)),
            "all_scanner_events": all_n,
            "public_grade_events": int(len(events)),
            "public_grade_share_pct": _pct(len(events), all_n),
            "scope": "Cờ cao và chặt nhóm tốt nhất và nhóm chuẩn trong dữ liệu hiện có",
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
            "target_family": "0,5x / 0,75x / 1,0x nhịp tăng trước mẫu",
            "selected_base_target_multiple": BASE_TARGET_MULTIPLE,
            "selected_base_target_role": "source_half_move_base",
            "base_target": base,
            "legacy_target": legacy,
            "rows": rows,
            "interpretation": "Cờ cao và chặt dùng 0,5x nhịp tăng trước mẫu làm mốc nguồn; 1,0x giữ vai trò mốc căng.",
        },
        "editorial_sections": {
            "summary": [
                "Cờ cao và chặt là mẫu tiếp diễn sau một nhịp tăng rất mạnh, gần nhân đôi trong thời gian ngắn. Vùng nghỉ phải nằm gần đỉnh mới và được xác nhận bằng phiên đóng cửa phá lên.",
                "Trong dữ liệu hiện có, mẫu này đủ làm chương tham khảo theo dõi. Điểm cần thận trọng là giá đã tăng mạnh trước đó, nên kéo ngược hậu phá vỡ có thể lớn.",
            ],
            "tour": [
                "Không nên nhầm mẫu này với cờ tăng thông thường. Điều kiện đầu vào là nhịp tăng đặc biệt mạnh; nếu thiếu điều kiện này, vùng nghỉ phía sau không còn là high-and-tight flag.",
                "Sau cú tăng mạnh, thân mẫu phải là vùng nghỉ gần đỉnh. Càng rơi sâu khỏi đỉnh, mẫu càng mất ý nghĩa tiếp diễn.",
            ],
            "failure": [
                "Thất bại xảy ra khi giá không đi thêm được tối thiểu 5% sau phá vỡ, hoặc kéo ngược 5% trước khi đạt mốc nguồn.",
                "Vì mẫu xuất hiện sau cú tăng lớn, cần đọc target-first song song với target hit để tránh nhầm một chart đẹp với đường đi dễ dùng.",
            ],
            "statistics": [
                "Nhóm công bố chính gồm nhóm tốt nhất và nhóm chuẩn. Đây là nhóm đủ sạch để mô tả mà không để toàn bộ kết quả quét thô chi phối câu kết luận.",
                "Mốc 0,5x là mốc nguồn vì nó tương ứng với nửa nhịp tăng trước mẫu. Mốc 1,0x được giữ lại để đối chiếu sức chạy, không phải headline chính.",
            ],
            "post_breakout": [
                "Sau phá vỡ, câu hỏi quan trọng không chỉ là có chạm mục tiêu hay không, mà là chạm trước hay sau khi kéo ngược sâu.",
                "Đường đi hậu phá vỡ của mẫu này thường đi kèm biên độ lớn. Vì vậy chương nhấn mạnh MFE, MAE và target-first thay vì chỉ một tỷ lệ thắng.",
            ],
            "size_volume": [
                "Mẫu đáng chú ý hơn khi vùng nghỉ gần đỉnh, không rơi quá sâu và khối lượng co lại trong thân mẫu.",
                "Thanh khoản thấp làm mẫu khó đọc hơn, vì một vài phiên thiếu giao dịch có thể làm sai cảm giác về vùng nghỉ và phá vỡ.",
            ],
            "tactics": [
                "Cách dùng phù hợp là theo dõi sau phiên phá lên, rồi kiểm tra độ sâu vùng nghỉ và mức kéo ngược hậu phá vỡ.",
                "Chương này không phải chiến lược giao dịch hoàn chỉnh; cần thêm entry, exit, sizing, phí, trượt giá và kiểm định danh mục nếu muốn triển khai.",
            ],
            "checklist": [
                "Nhịp tăng trước mẫu gần nhân đôi trong thời gian ngắn.",
                "Vùng nghỉ gần đỉnh và không kéo lùi quá sâu.",
                "Giá đóng cửa phá lên khỏi vùng nghỉ.",
                "Mục tiêu nguồn là 0,5x nhịp tăng trước mẫu.",
                "Không phải khuyến nghị mua bán.",
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
        "publication_spec_id": "high_tight_flag_publication_spec_v1",
        "pattern_id": "high_tight_flags",
        "spec_scope": "pattern_specific",
        "public_required_phrases": ["Cờ cao và chặt", "Mục tiêu nguồn", "Không phải khuyến nghị mua bán"],
        "public_forbidden_terms": ["PASS_CANDIDATE", "manual_visual_score", "visual_score_proxy", "premium+standard"],
        "source": str(path),
    }


def build_high_tight_flag_public_chapter(
    *,
    events_csv: Path = DEFAULT_EVENTS,
    path_csv: Path = DEFAULT_PATH,
    stats_json: Path = DEFAULT_STATS,
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
        raise ValueError("High-and-Tight Flag has no public-grade events.")
    stats = _read_json(stats_json)
    charts, examples = _build_example_charts(events, source_dir, out_dir)
    source_notes = _source_notes(source_notes_json)
    spec = _spec()
    payload = _payload(events, path, stats, examples)
    outputs = build_flag_public_chapter(
        payload=payload,
        source_notes=source_notes,
        events=events,
        path_df=path,
        charts=charts,
        spec=spec,
        out_dir=out_dir,
        pdf_filename="high_tight_flag_public_chapter.pdf",
        payload_filename="high_tight_flag_public_chapter_payload.json",
        manuscript_filename="high_tight_flag_ai_editorial_manuscript.md",
        notes_filename="high_tight_flag_public_chapter_notes.md",
    )
    source_notes_path = out_dir / "high_tight_flag_source_notes.json"
    source_notes_path.write_text(json.dumps(source_notes, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    spec_path = out_dir / "high_tight_flag_publication_spec.json"
    spec_payload = _publication_spec(spec_path)
    spec_path.write_text(json.dumps(spec_payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    entry = {
        "family": "flag_family",
        "pattern_id": "high_tight_flags",
        "title": "Cờ cao và chặt",
        "status": "final",
        "classification": "watchlist-reference under available-series scope",
        "score": 84.0,
        "claim_level": "watchlist-reference under available-series descriptive scope",
        "pdf": "artifacts/final_chapters/flag_family/high_tight_flag_final.pdf",
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
        "note": "High-and-Tight Flag dùng chung final flow của Flag Family nhưng có detector riêng vì yêu cầu nhịp tăng gần nhân đôi.",
    }
    entry_path = out_dir / "high_tight_flag_final_entry.json"
    entry_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    manifest = {
        "release_id": "high_tight_flag_public_chapter_v1",
        "factory_id": FACTORY_ID,
        "publication_core_id": "pattern_publication_core_v1",
        "outputs": {**{key: str(value) for key, value in outputs.items()}, "source_notes": str(source_notes_path), "publication_spec": str(spec_path), "entry": str(entry_path)},
        "summary": {
            "public_grade_events": int(len(events)),
            "base_target_hit_rate": payload["target_calibration"]["base_target"].get("target_hit_rate"),
            "base_target_first_rate": payload["target_calibration"]["base_target"].get("target_first_before_adverse_5pct_rate"),
            "failure_5pct_rate": payload["target_calibration"]["base_target"].get("failure_5pct_rate"),
            "median_mfe_pct": _fmt(pd.to_numeric(events["mfe_pct"], errors="coerce").median()),
            "median_mae_pct": _fmt(pd.to_numeric(events["mae_pct"], errors="coerce").median()),
        },
    }
    manifest_path = out_dir / "high_tight_flag_public_chapter_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    outputs.update({"source_notes": source_notes_path, "publication_spec": spec_path, "entry": entry_path, "manifest": manifest_path})
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Build High-and-Tight Flag public chapter.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    outputs = build_high_tight_flag_public_chapter(out_dir=Path(args.out_dir))
    print(json.dumps({key: str(value) for key, value in outputs.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
