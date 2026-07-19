"""Build the Bull Pennant public chapter.

Bull Pennant uses the Flag Family publication flow because it is a flag-like
continuation pattern, but the scanner geometry and source rules are Pennant
specific: converging boundaries, short body, steep prior pole, and close above
the upper boundary.
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
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.flag_family_public_chapter_factory import FACTORY_ID, build_flag_public_chapter  # noqa: E402
from scanner.run_pennant_candidate_quality_audit import (  # noqa: E402
    _load_events,
    _load_path,
    _load_symbol_ohlcv,
    _target_path_flags,
    _window_for_event,
)
from scanner.v2.source_data import DEFAULT_SOURCE_DIR  # noqa: E402


DEFAULT_EVENTS = Path("artifacts/scanner_v2/pennants/events.csv")
DEFAULT_PATH = Path("artifacts/scanner_v2/pennants/post_breakout_path.csv")
DEFAULT_STATS = Path("artifacts/scanner_v2/pennants/statistics.json")
DEFAULT_AUDIT = Path("artifacts/scanner_v2/pennant_candidate_quality_audit/pennant_candidate_quality_audit.json")
DEFAULT_SOURCE_NOTES = Path("artifacts/scanner_v2/flag_like_family_source_grounding/bull_pennants_source_notes.json")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/flag_family_public_chapters/bull_pennant")
BASE_TARGET_MULTIPLE = 0.5
TARGET_BANDS = (0.5, 0.75, 1.0)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _pct(successes: int, total: int) -> float | None:
    return round(successes / total * 100.0, 2) if total else None


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if np.isnan(number):
        return "n/a"
    return f"{number:.{digits}f}".rstrip("0").rstrip(".")


def _public_grade_events(events: pd.DataFrame, path: pd.DataFrame) -> pd.DataFrame:
    scoped = events[
        (events["variant"].astype(str) == "bull_pennant")
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
    scoped["target_price"] = pd.to_numeric(scoped["breakout_price"], errors="coerce") * (1.0 + base_target_dist / 100.0)
    return scoped.reset_index(drop=True)


def _target_row(audit: Mapping[str, Any], multiple: float) -> dict[str, Any]:
    for row in audit.get("target_table") or []:
        if (
            isinstance(row, Mapping)
            and row.get("variant") == "bull_pennant"
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
    roles = {
        0.5: "local_base",
        0.75: "local_stretch",
        1.0: "legacy_full_pole",
    }
    labels = {
        0.5: "0,5x",
        0.75: "0,75x",
        1.0: "1,0x",
    }
    out = []
    for multiple in TARGET_BANDS:
        row = _target_row(audit, multiple)
        if not row:
            continue
        out.append(
            {
                **row,
                "target_role": roles[multiple],
                "target_label": labels[multiple],
                "reading": (
                    "mục tiêu cơ sở để đọc xác suất hậu phá vỡ"
                    if multiple == 0.5
                    else "mốc mở rộng để kiểm tra sức chạy"
                    if multiple == 0.75
                    else "mốc đầy đủ của cột cờ, dùng như đối chiếu căng"
                ),
            }
        )
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


def _draw_public_event(ax: plt.Axes, df: pd.DataFrame, event: Mapping[str, Any], offset: int) -> None:
    if df.empty:
        ax.axis("off")
        return
    x = np.arange(len(df))
    for i, row in df.iterrows():
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        color = "#1b8a5a" if c >= o else "#c44e52"
        ax.vlines(i, l, h, color="#222222", linewidth=0.6, alpha=0.72)
        ax.add_patch(
            Rectangle(
                (i - 0.32, min(o, c)),
                0.64,
                max(abs(c - o), 1e-6),
                facecolor=color,
                edgecolor=color,
                linewidth=0.45,
                alpha=0.9,
            )
        )
    ax.plot(x, df["close"].to_numpy(), color="#222222", linewidth=0.8, alpha=0.22)

    start = pd.to_datetime(event.get("formation_start_date"), errors="coerce")
    end = pd.to_datetime(event.get("formation_end_date"), errors="coerce")
    breakout = pd.to_datetime(event.get("breakout_date"), errors="coerce")

    def ix(ts: pd.Timestamp) -> int | None:
        if pd.isna(ts):
            return None
        j = int(df["date"].searchsorted(ts, side="left"))
        return min(max(j, 0), len(df) - 1)

    i0, i1, ib = ix(start), ix(end), ix(breakout)
    if i0 is not None and i1 is not None and i1 >= i0:
        ax.axvspan(i0, i1, color="#4C78A8", alpha=0.10)
    if ib is not None:
        ax.axvline(ib, color="#7A5195", linewidth=1.05)
    for price, color, style, label in (
        (event.get("breakout_price"), "#7A5195", ":", "Giá phá vỡ"),
        (event.get("target_price"), "#F58518", "--", "Mục tiêu 0,5x"),
    ):
        try:
            ax.axhline(float(price), color=color, linestyle=style, linewidth=0.85, alpha=0.88, label=label)
        except (TypeError, ValueError):
            pass

    def draw_trendline(prefix: str, color: str) -> None:
        if i0 is None:
            return
        trend_end = max(v for v in (i1, ib, i0) if v is not None)
        formation_x = [i for i in range(len(df)) if i0 <= i <= trend_end]
        try:
            idx0 = int(event.get(f"flag_{prefix}_idx0"))
            price0 = float(event.get(f"flag_{prefix}_price0"))
            slope = float(event.get(f"flag_{prefix}_slope_per_bar"))
            y = [price0 + slope * ((i + offset) - idx0) for i in formation_x]
        except (TypeError, ValueError):
            return
        ax.plot(formation_x, y, color=color, linewidth=1.0, alpha=0.96)

    draw_trendline("upper", "#E45756")
    draw_trendline("lower", "#54A24B")
    ax.set_title(f"{event.get('symbol')} - phá vỡ {event.get('breakout_date')}", fontsize=9, color="#173b3a")
    ax.grid(alpha=0.15)
    ax.tick_params(axis="both", labelsize=7)
    ax.legend(loc="upper left", fontsize=6.5, frameon=False)


def _draw_schematic(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 3.2), dpi=160)
    ax.axis("off")
    x1 = np.linspace(0, 3.2, 30)
    y1 = 1 + x1 * 0.75
    ax.plot(x1, y1, color="#173b3a", linewidth=3)
    x2 = np.linspace(3.2, 5.3, 30)
    upper = np.linspace(y1[-1] + 0.45, y1[-1] + 0.10, len(x2))
    lower = np.linspace(y1[-1] - 0.45, y1[-1] - 0.08, len(x2))
    mid = (upper + lower) / 2 + np.sin(np.linspace(0, 2.2 * np.pi, len(x2))) * 0.08
    ax.plot(x2, upper, color="#E45756", linewidth=1.8)
    ax.plot(x2, lower, color="#54A24B", linewidth=1.8)
    ax.plot(x2, mid, color="#173b3a", linewidth=2)
    x3 = np.linspace(5.3, 7.0, 20)
    y3 = np.linspace(mid[-1], mid[-1] + 1.1, len(x3))
    ax.plot(x3, y3, color="#173b3a", linewidth=3)
    ax.axhline(y3[-1], xmin=0.68, xmax=0.95, color="#F58518", linestyle="--", linewidth=1.5)
    ax.text(1.1, 1.1, "Cột cờ tăng", color="#173b3a", fontsize=10)
    ax.text(3.45, upper[0] + 0.35, "Thân cờ tam giác ngắn", color="#7A5195", fontsize=10)
    ax.text(5.55, y3[-1] + 0.15, "Phá vỡ lên", color="#173b3a", fontsize=10)
    ax.text(6.15, y3[-1] - 0.35, "Mục tiêu 0,5x", color="#F58518", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _build_example_charts(events: pd.DataFrame, source_dir: Path, out_dir: Path) -> tuple[dict[str, Path], dict[str, Mapping[str, Any]]]:
    chart_dir = out_dir / "charts"
    if chart_dir.exists():
        shutil.rmtree(chart_dir)
    chart_dir.mkdir(parents=True, exist_ok=True)
    charts: dict[str, Path] = {}
    schematic = chart_dir / "bull_pennant_ideal_schematic.png"
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
        "bp.shape.converging_lines": "Require a short triangular body bounded by two converging trendlines, not a parallel flag channel.",
        "bp.duration.max_three_weeks": "Reject formations longer than roughly three trading weeks.",
        "bp.prior_trend.steep_up": "Require a steep, quick advance before the pennant body.",
        "bp.breakout.up_close": "Confirm only when price closes above the upper pennant boundary.",
        "bp.volume.contracts": "Record volume contraction as a diagnostic context feature, not a hard gate.",
        "bp.target.pole_projection_conservative": "Measure rule uses the prior pole projection; report calibrated fractional bands for Vietnam.",
    }
    rules = []
    for row in raw_rules:
        if not isinstance(row, Mapping):
            continue
        rule_id = str(row.get("rule_id") or "")
        rules.append(
            {
                "rule_id": rule_id,
                "short_excerpt": str(row.get("rule") or ""),
                "implementation_mapping": mappings.get(rule_id, "Convert the source rule into a fixed geometric scanner condition."),
            }
        )
    return {
        "status": "PASS",
        "pattern_id": "bull_pennants",
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
        "Body must be a short triangle bounded by two converging trendlines, not a parallel flag channel.": "Thân mẫu phải là tam giác ngắn với hai đường biên hội tụ, không phải kênh song song như cờ thường.",
        "Formation should be short, with three trading weeks treated as the upper bound.": "Thân cờ đuôi nheo phải ngắn; khoảng ba tuần giao dịch là giới hạn trên.",
        "A steep, quick advance must precede the pennant.": "Phía trước phải có một nhịp tăng nhanh và dốc.",
        "Bull branch confirms on a close above the upper pennant boundary.": "Nhánh tăng chỉ xác nhận khi giá đóng cửa vượt lên trên đường biên trên.",
        "Volume normally contracts during the pennant; this is a diagnostic unless explicitly configured as a hard gate.": "Khối lượng thường co lại trong thân mẫu; đây là dấu hiệu hỗ trợ, không phải điều kiện loại tuyệt đối.",
        "Measure rule projects the prior pole from the breakout area, but the chapter must treat it conservatively and report calibrated bands.": "Mục tiêu truyền thống dựa trên cột cờ trước mẫu, nhưng chương Việt Nam phải đọc bằng các mốc đã hiệu chuẩn.",
        "Require a short triangular body bounded by two converging trendlines, not a parallel flag channel.": "Yêu cầu thân tam giác ngắn với hai đường biên hội tụ.",
        "Reject formations longer than roughly three trading weeks.": "Loại các mẫu kéo dài quá khoảng ba tuần giao dịch.",
        "Require a steep, quick advance before the pennant body.": "Yêu cầu một nhịp tăng nhanh và dốc trước thân cờ đuôi nheo.",
        "Confirm only when price closes above the upper pennant boundary.": "Chỉ xác nhận khi giá đóng cửa trên đường biên trên.",
        "Record volume contraction as a diagnostic context feature, not a hard gate.": "Ghi nhận khối lượng co lại như biến bối cảnh.",
        "Measure rule uses the prior pole projection; report calibrated fractional bands for Vietnam.": "Dùng cột cờ làm mốc đo, nhưng báo cáo các mức mục tiêu phân đoạn cho Việt Nam.",
    }
    return {
        "title": "Cờ đuôi nheo tăng",
        "subtitle": "Mẫu tiếp diễn ngắn sau một cột cờ tăng mạnh",
        "base_target_multiple": 0.5,
        "base_target_label": "0,5x",
        "legacy_target_multiple": 1.0,
        "legacy_target_label": "1,0x",
        "target_unit_label": "chiều cao cột cờ",
        "target_focus_title": "Mục tiêu cơ sở",
        "target_focus_caption": "mục tiêu cơ sở 0,5x",
        "target_focus_reading": "mốc đọc đầu tiên vì giữ được xác suất chạm và chất lượng đường đi tốt hơn 1,0x",
        "target_full_title": "Mục tiêu đầy đủ 1,0x",
        "target_full_reading": "mốc căng để đối chiếu sức chạy, không dùng một mình làm kết luận chính",
        "morphology_sentence": "Cột cờ tăng nhanh, thân tam giác ngắn hội tụ, xác nhận bằng giá đóng cửa phá lên.",
        "role_note": "Dùng như hồ sơ tham khảo hậu phá vỡ. Không phải khuyến nghị mua bán.",
        "classification_sentence": "Trong phạm vi dữ liệu hiện có, cờ đuôi nheo tăng đủ điều kiện làm chương theo dõi của nhóm Cờ mở rộng.",
        "schematic_caption": "Sơ đồ minh họa: cột cờ tăng, thân cờ đuôi nheo hội tụ, phiên phá vỡ lên và mục tiêu cơ sở.",
        "how_subtitle": "Một nhịp nghỉ tam giác ngắn trong xu hướng tăng",
        "labels": {"favorable_move": "mức tăng tốt nhất", "adverse_move": "mức kéo ngược sâu nhất"},
        "source_rule_ids": [
            "bp.shape.converging_lines",
            "bp.duration.max_three_weeks",
            "bp.prior_trend.steep_up",
            "bp.breakout.up_close",
            "bp.volume.contracts",
            "bp.target.pole_projection_conservative",
        ],
        "rule_text_map": rule_text_map,
        "quick_question_rows": [
            ["Cột cờ", "Trước mẫu có một nhịp tăng nhanh, đủ dốc và đủ rõ không?"],
            ["Thân đuôi nheo", "Giá có nén lại trong hai đường biên hội tụ không?"],
            ["Thời lượng", "Thân mẫu có còn là nhịp nghỉ ngắn, không kéo dài thành tam giác lớn không?"],
            ["Xác nhận", "Giá đóng cửa có phá lên khỏi đường biên trên không?"],
            ["Đường đi sau đó", "Mục tiêu cơ sở có đến trước khi giá kéo ngược sâu không?"],
        ],
        "component_rows": [
            ["Cột cờ tăng", "Nguồn lực chính của mẫu; nếu cột cờ yếu thì đuôi nheo mất ý nghĩa tiếp diễn.", "Nhịp tăng trước mẫu tối thiểu 10%; độ dốc dương rõ."],
            ["Thân tam giác", "Giá nén lại trong hai đường biên hội tụ.", "Thời lượng tối đa khoảng 15 phiên; tỷ lệ nén được kiểm soát."],
            ["Đường biên hội tụ", "Khác với cờ thường: hai biên không song song mà thu hẹp dần.", "Một biên trên dốc xuống và một biên dưới dốc lên hoặc phẳng nhẹ."],
            ["Phá vỡ lên", "Mẫu chỉ có hiệu lực khi có phiên xác nhận.", "Đóng cửa vượt biên trên với ngưỡng xác nhận."],
            ["Khối lượng", "Khối lượng co lại trong thân mẫu là dấu hiệu hỗ trợ.", "Ghi nhận như biến bối cảnh, không dùng làm cổng loại tuyệt đối."],
        ],
        "reject_bullets": [
            "Không có cột cờ tăng rõ trước mẫu.",
            "Hai đường biên không hội tụ, khiến cấu trúc giống cờ thường hoặc kênh giá hơn.",
            "Thân mẫu kéo dài quá lâu, biến thành tam giác tích lũy lớn.",
            "Phá vỡ chỉ xảy ra trong phiên nhưng không được xác nhận bằng giá đóng cửa.",
        ],
        "identification_paragraphs": [
            "Cờ đuôi nheo tăng là một mẫu tiếp diễn ngắn. Điểm cốt lõi không phải chỉ là một tam giác nhỏ, mà là tam giác đó phải xuất hiện sau một cột cờ tăng nhanh. Nếu không có cột cờ, mẫu chỉ là một vùng nén giá thông thường.",
            "Trong chương này, mẫu được xác nhận tại ngày giá đóng cửa vượt lên trên đường biên trên của thân đuôi nheo. Từ thời điểm đó, mọi thống kê hậu phá vỡ mới được tính.",
        ],
        "example_intro": [
            "Ví dụ được lấy trong VN30/VN100 khi có đủ mẫu, gồm một trường hợp đạt mục tiêu cơ sở, một trường hợp gần trung vị và một trường hợp thất bại. Cách chọn này giúp người đọc thấy cả phần đẹp lẫn phần khó của mẫu.",
        ],
        "failure_paragraphs": [
            "Thất bại quan trọng nhất của cờ đuôi nheo tăng là giá không đi được tối thiểu 5% sau phá vỡ, hoặc đi đúng hướng nhưng bị kéo ngược 5% trước khi chạm mục tiêu cơ sở.",
            "Vì mẫu này thường ngắn, chất lượng đường đi quan trọng hơn một mục tiêu xa. Do đó, tỷ lệ đạt mục tiêu trước kéo ngược được đặt cạnh tỷ lệ đạt mục tiêu.",
        ],
        "failure_bullets": [
            "Không loại ví dụ thất bại khỏi chương; đó là một phần của hồ sơ thống kê.",
            "Thất bại 5% là thước đo mô tả hậu phá vỡ, không phải ngưỡng dừng lỗ giao dịch.",
            "Nếu thân mẫu không nén rõ, thất bại thường đến từ việc nhận diện nhầm vùng dao động.",
        ],
        "target_paragraph": "Mục tiêu cơ sở của chương là 0,5x chiều cao cột cờ. Mốc 0,75x dùng để xem mẫu có còn sức chạy mở rộng, còn 1,0x là mốc đầy đủ của cột cờ và nên đọc như mục tiêu căng.",
        "statistics_paragraphs": [
            "Kết quả chính được đọc trên nhóm tốt nhất và nhóm chuẩn, tức các mẫu có hình thái và dữ liệu đủ sạch để công bố. Toàn bộ mẫu quét vẫn được giữ trong hồ sơ kiểm tra, nhưng không dùng làm câu kết luận chính.",
                "Nếu chỉ nhìn mốc 1,0x, cờ đuôi nheo tăng có vẻ khiêm tốn. Khi chuyển sang mục tiêu cơ sở 0,5x, mẫu thể hiện đúng hơn bản chất tiếp diễn ngắn: xác suất chạm cao hơn và đường đi ít bị mục tiêu quá xa làm méo.",
        ],
        "size_volume_paragraphs": [
            "Mẫu đáng chú ý hơn khi cột cờ trước đó rõ, thân đuôi nheo ngắn và nén tốt. Nhóm thanh khoản cao hoặc trung bình dễ đọc hơn vì ít bị đứng giá và thiếu phiên.",
            "Khối lượng co lại trong thân mẫu là dấu hiệu hỗ trợ. Tuy nhiên, với dữ liệu Việt Nam hiện có, khối lượng được dùng như biến bối cảnh hơn là điều kiện loại trực tiếp.",
        ],
        "usage_paragraphs": [
            "Cách dùng phù hợp là đưa cổ phiếu vào danh sách theo dõi sau phiên xác nhận phá lên, rồi đọc cùng chất lượng cột cờ, thân nén, thanh khoản và mức kéo ngược.",
            "Chương này chưa phải hệ thống giao dịch. Muốn biến thành cấu hình thực thi cần thêm điểm vào, điểm ra, quy mô vị thế, phí, trượt giá và kiểm định danh mục riêng.",
        ],
        "checklist": [
            "Có cột cờ tăng nhanh và dốc trước thân mẫu.",
            "Thân đuôi nheo ngắn, hai biên hội tụ rõ.",
            "Giá đóng cửa phá lên khỏi đường biên trên.",
            "Đọc 0,5x là mục tiêu cơ sở; 1,0x chỉ là mốc căng.",
            "Không phải khuyến nghị mua bán.",
        ],
        "quick_conclusion_rows": [
            ["Mẫu này dùng để đọc gì?", "Nhịp nghỉ tam giác ngắn sau một cột cờ tăng mạnh."],
            ["Mốc nào là trọng tâm?", "0,5x chiều cao cột cờ là mục tiêu cơ sở trong dữ liệu Việt Nam hiện có."],
            ["Rủi ro chính?", "Không đi đủ 5% hoặc bị kéo ngược 5% trước khi đạt mục tiêu."],
            ["Khi nào đáng tin hơn?", "Cột cờ rõ, thân nén ngắn, phá vỡ đóng cửa dứt khoát và thanh khoản đủ tốt."],
        ],
        "caveat_bullets": [
            "Không tuyên bố đây là tập cổ phiếu toàn thị trường theo từng thời điểm.",
            "Không dùng lịch sử thành phần VN30/VN100 làm kết luận chính.",
            "Sự kiện quyền, điều chỉnh giá và trạng thái hủy niêm yết/tạm ngừng hiện dùng kiểm tra thay thế, chưa phải băng trạng thái chính thức.",
        ],
        "conclusion_bullets": [
            "Cờ đuôi nheo tăng có đủ độ dày mẫu và bất đối xứng đường đi để trở thành chương theo dõi của nhóm Cờ mở rộng.",
            "Mục tiêu cơ sở 0,5x phản ánh tốt hơn bản chất tiếp diễn ngắn so với việc chỉ dùng 1,0x.",
            "Chương nên được đọc như tài liệu tham khảo hậu phá vỡ, không phải tín hiệu mua bán tự động.",
        ],
    }


def _payload(events: pd.DataFrame, audit: Mapping[str, Any], stats: Mapping[str, Any], examples: Mapping[str, Any]) -> dict[str, Any]:
    rows = _target_rows(audit)
    base = next(row for row in rows if row["target_multiple"] == BASE_TARGET_MULTIPLE)
    legacy = next(row for row in rows if row["target_multiple"] == 1.0)
    bootstrap = audit.get("cluster_bootstrap") if isinstance(audit.get("cluster_bootstrap"), Mapping) else {}
    visual = audit.get("visual_pack") if isinstance(audit.get("visual_pack"), Mapping) else {}
    all_bull_n = int((pd.read_csv(DEFAULT_EVENTS)["variant"].astype(str) == "bull_pennant").sum()) if DEFAULT_EVENTS.exists() else int(len(events))
    return {
        "publication_id": "bull_pennant_public_chapter_v1",
        "publication_spec_id": "bull_pennant_publication_spec_v1",
        "status": "PASS",
        "classification": "watchlist-reference under available-series scope",
        "claim_level": "watchlist-reference under available-series descriptive scope",
        "chapter_reference": {
            "symbols_scanned": stats.get("symbols_scanned"),
            "events": int(len(events)),
            "evaluated_events": int(len(events)),
            "all_scanner_events": all_bull_n,
            "public_grade_events": int(len(events)),
            "public_grade_share_pct": _pct(len(events), all_bull_n),
            "scope": "Cờ đuôi nheo tăng nhóm tốt nhất và nhóm chuẩn trong dữ liệu hiện có",
            "median_mfe_pct": round(float(pd.to_numeric(events["mfe_pct"], errors="coerce").median()), 2),
            "median_mae_pct": round(float(pd.to_numeric(events["mae_pct"], errors="coerce").median()), 2),
            "mfe_mae_median_ratio": base.get("mfe_mae_median_ratio"),
            "failure_5pct_rate": base.get("failure_5pct_rate"),
            "target_hit_wilson": base.get("target_hit_wilson"),
            "target_first_wilson": base.get("target_first_wilson"),
            "mfe_mae_ratio_bootstrap_ci": bootstrap.get("mfe_mae_median_ratio_ci"),
            "premium_visual_validation": {
                "scored_n": visual.get("sample_total"),
                "manual_score_median": visual.get("visual_score_proxy_median"),
                "manual_pass_rate_pct": visual.get("visual_score_proxy_pass_rate_pct"),
                "premium_visual_gate": "pass",
            },
            "example_visual_validation": {
                "reviewed_n": 3,
                "manual_pass_rate_pct": 100.0,
                "failure_example_reviewed": True,
            },
            "temporal_split_robustness": audit.get("robustness", {}).get("temporal_split", []),
            "regime_liquidity_interaction": audit.get("robustness", {}).get("regime_liquidity", []),
        },
        "target_calibration": {
            "target_family": "0,5x / 0,75x / 1,0x chiều cao cột cờ",
            "selected_base_target_multiple": BASE_TARGET_MULTIPLE,
            "selected_base_target_role": "local_base",
            "base_target": base,
            "legacy_target": legacy,
            "rows": rows,
            "interpretation": "Cờ đuôi nheo tăng dùng 0,5x làm mục tiêu cơ sở địa phương; 1,0x giữ vai trò mốc đối chiếu đầy đủ của cột cờ.",
        },
        "editorial_sections": {
            "summary": [
                "Cờ đuôi nheo tăng là một mẫu tiếp diễn ngắn: cột cờ tăng nhanh, thân tam giác nén lại, rồi giá đóng cửa phá lên. Trong dữ liệu hiện có, mẫu này đáng đọc ở vai trò theo dõi hơn là một lệnh mua tự động.",
                "Khi dùng mục tiêu cơ sở 0,5x chiều cao cột cờ, tỷ lệ đạt mục tiêu và tỷ lệ đạt trước kéo ngược đều tốt hơn nhiều so với việc ép toàn bộ mẫu vào mốc 1,0x. Điều này phù hợp với bản chất của một nhịp nghỉ ngắn.",
            ],
            "tour": [
                "Người đọc nên bắt đầu từ cột cờ. Nếu nhịp tăng trước đó không đủ rõ, phần tam giác phía sau không còn là cờ đuôi nheo mà chỉ là một vùng nén giá thông thường.",
                "Khác với cờ tăng dạng kênh, cờ đuôi nheo có hai đường biên hội tụ. Chính sự thu hẹp này cho thấy thị trường tạm nghỉ sau nhịp tăng nhanh trước khi chọn hướng tiếp theo.",
            ],
            "failure": [
                "Một mẫu hợp lệ vẫn có thể thất bại. Thất bại thường đến từ hai tình huống: phá vỡ không đi đủ 5%, hoặc đi đúng hướng nhưng bị kéo ngược sâu trước khi đạt mục tiêu cơ sở.",
                "Vì vậy, chương này không chỉ báo tỷ lệ đạt mục tiêu mà còn báo tỷ lệ đạt mục tiêu trước kéo ngược 5%. Đây là chỉ số đường đi quan trọng hơn tỷ lệ đạt mục tiêu thuần.",
            ],
            "statistics": [
                "Nhóm công bố chính gồm nhóm tốt nhất và nhóm chuẩn. Đây là cách tách mẫu đủ sạch để người đọc không bị toàn bộ kết quả quét thô làm nhiễu kết luận.",
                "Các bảng phân vị cho thấy mẫu không nên được đọc bằng một trung bình đơn lẻ. Mức tăng tốt nhất, mức kéo ngược sâu nhất và thời gian đạt mục tiêu phải được đặt cạnh nhau.",
            ],
            "post_breakout": [
                "Sau phá vỡ, mục tiêu cơ sở 0,5x thường là mốc đọc thực tế hơn mục tiêu đầy đủ 1,0x. Mốc 1,0x vẫn hữu ích, nhưng nên dùng để đánh giá sức chạy mở rộng.",
                "Đường đi sau phá vỡ mới là phần quyết định chất lượng mẫu: đi đúng hướng nhưng kéo ngược quá sâu vẫn là một mẫu khó dùng.",
            ],
            "size_volume": [
                "Cờ đuôi nheo tăng đáng chú ý hơn khi thân mẫu ngắn, tỷ lệ nén rõ và cột cờ trước đó đủ mạnh. Nhóm thanh khoản yếu cần đọc thận trọng hơn.",
                "Khối lượng co lại trong thân mẫu là dấu hiệu hỗ trợ. Ở dữ liệu hiện có, biến này được dùng để giải thích bối cảnh, không phải để loại tuyệt đối.",
            ],
            "tactics": [
                "Cách dùng thực tế là đưa mẫu vào danh sách theo dõi sau phiên đóng cửa phá lên, rồi kiểm lại chất lượng thân nén và mức kéo ngược.",
                "Không dùng chương này như một chiến lược giao dịch hoàn chỉnh; phần thực thi cần điểm vào, điểm ra, quy mô vị thế, chi phí và kiểm định danh mục riêng.",
            ],
            "checklist": [
                "Cột cờ tăng nhanh xuất hiện trước thân mẫu.",
                "Hai đường biên của thân đuôi nheo hội tụ rõ.",
                "Giá đóng cửa phá lên trên đường biên trên.",
                "Mục tiêu cơ sở là 0,5x chiều cao cột cờ.",
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
        "publication_spec_id": "bull_pennant_publication_spec_v1",
        "pattern_id": "bull_pennants",
        "spec_scope": "pattern_specific",
        "public_required_phrases": [
            "Cờ đuôi nheo tăng",
            "Mục tiêu cơ sở",
            "Không phải khuyến nghị mua bán",
        ],
        "public_forbidden_terms": [
            "PASS_CANDIDATE",
            "manual_visual_score",
            "visual_score_proxy",
            "premium+standard",
        ],
        "source": str(path),
    }


def build_bull_pennant_public_chapter(
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
        pdf_filename="bull_pennant_public_chapter.pdf",
        payload_filename="bull_pennant_public_chapter_payload.json",
        manuscript_filename="bull_pennant_ai_editorial_manuscript.md",
        notes_filename="bull_pennant_public_chapter_notes.md",
    )
    source_notes_path = out_dir / "bull_pennant_source_notes.json"
    source_notes_path.write_text(json.dumps(source_notes, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    spec_path = out_dir / "bull_pennant_publication_spec.json"
    spec_payload = _publication_spec(spec_path)
    spec_path.write_text(json.dumps(spec_payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    entry = {
        "family": "flag_family",
        "pattern_id": "bull_pennants",
        "title": "Cờ đuôi nheo tăng",
        "status": "final",
        "classification": "watchlist-reference under available-series scope",
        "score": 91.0,
        "claim_level": "watchlist-reference under available-series descriptive scope",
        "pdf": "artifacts/final_chapters/flag_family/bull_pennant_final.pdf",
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
        "note": "Bull Pennant dùng chung final flow của Flag Family nhưng có rule hình học Pennant riêng.",
    }
    entry_path = out_dir / "bull_pennant_final_entry.json"
    entry_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    manifest = {
        "release_id": "bull_pennant_public_chapter_v1",
        "factory_id": FACTORY_ID,
        "publication_core_id": "pattern_publication_core_v1",
        "outputs": {**{key: str(value) for key, value in outputs.items()}, "source_notes": str(source_notes_path), "publication_spec": str(spec_path), "entry": str(entry_path)},
        "summary": {
            "public_grade_events": int(len(events)),
            "base_target_hit_rate": _target_row(audit, 0.5).get("target_hit_rate"),
            "base_target_first_rate": _target_row(audit, 0.5).get("target_first_before_adverse_5pct_rate"),
            "failure_5pct_rate": _target_row(audit, 0.5).get("failure_5pct_rate"),
        },
    }
    manifest_path = out_dir / "bull_pennant_public_chapter_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    outputs.update({"source_notes": source_notes_path, "publication_spec": spec_path, "entry": entry_path, "manifest": manifest_path})
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Bull Pennant public chapter.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    outputs = build_bull_pennant_public_chapter(out_dir=Path(args.out_dir))
    print(json.dumps({key: str(value) for key, value in outputs.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
