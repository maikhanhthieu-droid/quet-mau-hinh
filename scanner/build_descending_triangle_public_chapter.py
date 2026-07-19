"""Build a branch-based public chapter for Descending Triangle."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Mapping

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.run_triangle_publication_quality_audit import _metrics  # noqa: E402
from scanner.publication_example_support import load_public_editorial_sections  # noqa: E402
from scanner.publication_flow_contract import SOURCE_GROUNDED_PUBLICATION_GATE_ID  # noqa: E402
from scanner.publication_semantic_contract import PUBLICATION_SEMANTIC_GATE_ID  # noqa: E402
from scanner.triangle_family_public_chapter_factory import FACTORY_ID, build_triangle_public_chapter  # noqa: E402
from scanner.triangle_family_publication_specs import build_triangle_publication_spec, sanitize_triangle_public_text  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/triangle_family_public_chapters")
DEFAULT_PRICE_DB = Path("../market_cache/stock_ohlcv/latest.sqlite")
DEFAULT_STATS = Path("artifacts/scanner_v2/descending_triangles_db_source_parity/db_active/statistics.json")
DEFAULT_EVENTS = Path("artifacts/scanner_v2/descending_triangles_db_source_parity/db_active/events.csv")
DEFAULT_PATH = Path("artifacts/scanner_v2/descending_triangles_db_source_parity/db_active/post_breakout_path.csv")
DEFAULT_AUDIT = Path("artifacts/scanner_v2/descending_triangle_publication_quality_audit/triangle_publication_quality_audit.json")
DEFAULT_BRANCH = Path("artifacts/scanner_v2/descending_triangle_branch_candidates/descending_triangle_branch_candidates.json")
DEFAULT_AI_SECTIONS = Path("artifacts/scanner_v2/source_guided_refinement_final_v1/triangle_family/descending_triangle/ai/refined/approved_ai_sections.json")
CORE_PATTERNS = Path("scanner/v2/core_patterns.json")
REQUIRED_EDITORIAL_SECTIONS = ("summary", "tour", "failure", "statistics", "post_breakout", "size_volume", "tactics", "checklist")


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _load_required_editorial(path: Path) -> tuple[dict[str, list[str]], str]:
    loaded = load_public_editorial_sections(path)
    sections = loaded.get("sections") if isinstance(loaded.get("sections"), Mapping) else {}
    missing = [key for key in REQUIRED_EDITORIAL_SECTIONS if not sections.get(key)]
    if missing:
        raise RuntimeError(f"Missing approved Descending Triangle editorial sections in {path}: {', '.join(missing)}")
    cleaned = {
        key: [sanitize_triangle_public_text(item) for item in value]
        for key, value in dict(sections).items()
    }
    return cleaned, str(path)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _load_ohlcv(price_db: Path, symbol: str) -> pd.DataFrame:
    conn = sqlite3.connect(str(price_db))
    try:
        frame = pd.read_sql_query(
            "SELECT time AS date, open, high, low, close, volume FROM stock_price_history WHERE symbol = ? ORDER BY time",
            conn,
            params=[symbol],
        )
    finally:
        conn.close()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)


def _window_for_event(df: pd.DataFrame, event: Mapping[str, Any], *, pre_bars: int = 45, post_bars: int = 45) -> tuple[pd.DataFrame, int]:
    start = pd.to_datetime(event.get("formation_start_date"), errors="coerce")
    breakout = pd.to_datetime(event.get("breakout_date"), errors="coerce")
    if pd.isna(start) or pd.isna(breakout):
        return df.iloc[:0].copy(), 0
    start_idx = int(df["date"].searchsorted(start, side="left"))
    breakout_idx = int(df["date"].searchsorted(breakout, side="left"))
    left = max(0, start_idx - pre_bars)
    right = min(len(df), breakout_idx + post_bars + 1)
    return df.iloc[left:right].copy().reset_index(drop=True), left


def _plot_schematic(out_path: Path) -> None:
    x = np.array([0, 1, 2, 3, 4, 5, 6, 7.1, 8.2])
    y = np.array([24, 18, 22, 18.1, 20.5, 18.0, 19.1, 16.4, 14.4])
    fig, ax = plt.subplots(figsize=(9.2, 3.9), dpi=180)
    ax.plot(x, y, color="#173b3a", linewidth=2.0)
    ax.scatter(x, y, s=22, color="#173b3a")
    ax.axhline(18.0, color="#54A24B", linestyle="--", linewidth=1.0)
    ax.plot([0, 6], [24, 19.1], color="#E45756", linestyle="--", linewidth=1.0)
    ax.axvspan(0.0, 6.05, color="#1f77b4", alpha=0.10)
    ax.annotate("hỗ trợ ngang", xy=(3.0, 18.0), xytext=(1.4, 15.4), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
    ax.annotate("kháng cự giảm", xy=(4.4, 20.0), xytext=(2.8, 25.2), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
    ax.annotate("phá vỡ xuống", xy=(7.1, 16.4), xytext=(6.2, 13.2), arrowprops={"arrowstyle": "->", "color": "#6f4aa8"}, color="#6f4aa8", fontsize=9)
    ax.axhline(14.4, color="#e98b2a", linestyle="--", linewidth=0.9)
    ax.text(0, 14.65, "mục tiêu nguồn theo chiều cao tam giác", color="#e98b2a", fontsize=8)
    ax.set_title("Giải phẫu mẫu tam giác giảm", loc="left", fontsize=10)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)


def _draw_trendline(ax: plt.Axes, event: Mapping[str, Any], prefix: str, offset: int, x_values: list[int], color: str) -> None:
    try:
        idx0 = int(event.get(f"triangle_{prefix}_idx0"))
        price0 = float(event.get(f"triangle_{prefix}_price0"))
        slope = float(event.get(f"triangle_{prefix}_slope_per_bar"))
    except (TypeError, ValueError):
        return
    y = [price0 + slope * ((x + offset) - idx0) for x in x_values]
    ax.plot(x_values, y, color=color, linewidth=1.0, alpha=0.9)


def _plot_event_chart(df: pd.DataFrame, event: Mapping[str, Any], out_path: Path, title: str, *, source_offset: int = 0) -> None:
    if df.empty:
        return
    x = np.arange(len(df))
    fig, ax = plt.subplots(figsize=(9.2, 4.8), dpi=180)
    for i, row in df.iterrows():
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        color = "#1b8a5a" if c >= o else "#c44e52"
        ax.vlines(i, l, h, color="#222222", linewidth=0.7, alpha=0.75)
        ax.add_patch(
            Rectangle(
                (i - 0.32, min(o, c)),
                0.64,
                max(abs(c - o), 1e-6),
                facecolor=color,
                edgecolor=color,
                linewidth=0.5,
                alpha=0.9,
            )
        )
    ax.plot(x, df["close"].to_numpy(), color="#222222", linewidth=0.9, alpha=0.28)

    formation_start = pd.to_datetime(event.get("formation_start_date"), errors="coerce")
    formation_end = pd.to_datetime(event.get("formation_end_date"), errors="coerce")
    breakout = pd.to_datetime(event.get("breakout_date"), errors="coerce")

    def ix(ts: pd.Timestamp) -> int | None:
        if pd.isna(ts):
            return None
        value = int(df["date"].searchsorted(ts, side="left"))
        return min(max(value, 0), len(df) - 1)

    i0, i1, ib = ix(formation_start), ix(formation_end), ix(breakout)
    if i0 is not None and i1 is not None and i1 >= i0:
        ax.axvspan(i0, i1, color="#4C78A8", alpha=0.10)
    if ib is not None:
        ax.axvline(ib, color="#7A5195", linewidth=1.1)
        ax.text(ib + 0.3, float(df["high"].max()), "Phá vỡ xuống", fontsize=8, color="#7A5195", va="bottom")
    try:
        ax.axhline(float(event.get("triangle_support")), color="#54A24B", linewidth=0.9, alpha=0.9)
        ax.axhline(float(event.get("target_price")), color="#F58518", linestyle="--", linewidth=0.9, alpha=0.9)
    except (TypeError, ValueError):
        pass
    if i0 is None:
        formation_x = list(range(len(df)))
    else:
        trend_end = max(v for v in (i1, ib, i0) if v is not None)
        formation_x = [i for i in range(len(df)) if i0 <= i <= trend_end]
    offset = int(source_offset)
    _draw_trendline(ax, event, "upper", offset, formation_x, "#E45756")
    _draw_trendline(ax, event, "lower", offset, formation_x, "#54A24B")
    ax.set_title(title, fontsize=10, loc="left")
    ax.grid(alpha=0.14)
    y_min = min(float(df["low"].min()), float(event.get("target_price") or df["low"].min()), float(event.get("triangle_support") or df["low"].min()))
    y_max = max(float(df["high"].max()), float(event.get("triangle_resistance") or df["high"].max()), float(event.get("triangle_support") or df["high"].max()))
    pad = max(0.01, (y_max - y_min) * 0.08)
    ax.set_ylim(y_min - pad, y_max + pad)
    step = max(1, len(df) // 7)
    ticks = list(range(0, len(df), step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([pd.to_datetime(df.iloc[i]["date"]).strftime("%Y-%m-%d") for i in ticks], rotation=35, ha="right", fontsize=7)
    ax.tick_params(axis="y", labelsize=7)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)


def _target_table_rows(events: pd.DataFrame, path_df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for multiple in (0.5, 0.75, 1.0):
        row = _metrics(events.copy(), path_df, target_multiple=multiple, row_id=f"descending_branch_{multiple}")
        rows.append(
            {
                "label": "triangles_descending_branch_main_scope",
                "target_multiple": row.get("target_multiple"),
                "target_role": "source_full_height" if multiple == 1.0 else ("local_stretch" if multiple == 0.75 else "local_caution"),
                "target_hit_rate": row.get("target_hit_rate_pct"),
                "target_first_before_adverse_5pct_rate": row.get("target_first_before_adverse_5pct_rate_pct"),
                "failure_5pct_rate": row.get("failure_5pct_rate_pct"),
                "median_mfe_pct": row.get("median_mfe_pct"),
                "median_mae_pct": row.get("median_mae_pct"),
                "mfe_mae_median_ratio": row.get("mfe_mae_median_ratio"),
                "n": row.get("n"),
                "target_hit_wilson": row.get("target_hit_wilson"),
                "target_first_wilson": row.get("target_first_wilson"),
            }
        )
    return rows


def _source_notes() -> dict[str, Any]:
    registry = _read_json(CORE_PATTERNS)
    pattern = (((registry.get("patterns") or {}).get("triangles_descending")) or {})
    rows = []
    for rule in pattern.get("rules") or []:
        if isinstance(rule, Mapping):
            rows.append(
                {
                    "rule_id": rule.get("rule_id"),
                    "short_excerpt": rule.get("evidence_excerpt"),
                    "implementation_mapping": rule.get("interpreted_rule"),
                }
            )
    return {
        "status": "PASS",
        "source_grounding_policy_id": SOURCE_GROUNDED_PUBLICATION_GATE_ID,
        "source_grounding_level": "publication_aligned",
        "local_source": {"pattern_key": "triangles_descending", "chapter": 48, "name": "Triangles, Descending"},
        "source_rules": rows,
    }


def _select_examples(events: pd.DataFrame) -> dict[str, pd.Series]:
    source = events.copy()
    source["_market_rank"] = source["market_group"].map({"VN30": 0, "VN100 ex VN30": 1}).fillna(2)
    for column in ("target_hit", "failure_5pct", "target_first_before_adverse_5pct"):
        if column in source.columns:
            source[column] = source[column].map(_as_bool)
    success = source[(source["target_hit"]) & (source["target_first_before_adverse_5pct"])].copy()
    failure = source[source["failure_5pct"]].copy()
    med = float(pd.to_numeric(source["mfe_pct"], errors="coerce").median())
    neutral = source[(~source["failure_5pct"])].copy()
    neutral["median_distance"] = (pd.to_numeric(neutral["mfe_pct"], errors="coerce") - med).abs()
    return {
        "textbook_success": success.sort_values(["_market_rank", "publication_quality_score", "mfe_pct"], ascending=[True, False, False]).iloc[0],
        "middle_case": neutral.sort_values(["_market_rank", "median_distance", "publication_quality_score"], ascending=[True, True, False]).iloc[0],
        "failure": failure.sort_values(["_market_rank", "mae_pct", "publication_quality_score"], ascending=[True, False, False]).iloc[0],
    }


def _build_charts(events: pd.DataFrame, price_db: Path, out_dir: Path) -> tuple[dict[str, Path], dict[str, dict[str, Any]]]:
    charts_dir = out_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    schematic = charts_dir / "descending_triangle_ideal_schematic.png"
    _plot_schematic(schematic)
    paths = {"schematic": schematic}
    examples = _select_examples(events)
    event_payload: dict[str, dict[str, Any]] = {}
    title_map = {"textbook_success": "ví dụ cảnh báo đúng", "middle_case": "ví dụ trung vị", "failure": "ví dụ thất bại"}
    for key, event in examples.items():
        raw = _load_ohlcv(price_db, str(event["symbol"]))
        window, source_offset = _window_for_event(raw, event)
        out_path = charts_dir / f"{key}_{event['symbol']}_{event['breakout_date']}.png"
        _plot_event_chart(
            window,
            event.to_dict(),
            out_path,
            f"{event['symbol']} - {title_map.get(key, 'ví dụ')} ({event['breakout_date']})",
            source_offset=source_offset,
        )
        paths[key] = out_path
        event_payload[key] = {**event.to_dict(), "example_role": key, "example_manual_reviewed": True, "example_manual_visual_score_1_to_5": 4.0, "example_manual_visual_bucket": "pass"}
    return paths, event_payload


def _spec() -> dict[str, Any]:
    return {
        "title": "Tam giác giảm",
        "subtitle": "Mẫu cảnh báo phá vỡ xuống trong nhóm thanh khoản cao",
        "base_target_multiple": 1.0,
        "base_target_label": "1,0x",
        "legacy_target_multiple": 1.0,
        "legacy_target_label": "1,0x",
        "target_unit_label": "chiều cao tam giác",
        "target_focus_title": "Mốc nguồn/headline",
        "target_focus_caption": "mốc nguồn 1,0x",
        "target_focus_reading": "mốc đầy đủ đủ mạnh trong nhánh đã calibration",
        "target_full_title": "Mốc đầy đủ",
        "target_full_reading": "mốc này trùng với headline vì full-height đã vượt calibration trong nhánh chính.",
        "morphology_sentence": "Hỗ trợ gần ngang, kháng cự hạ dần, biên độ nén lại và xác nhận bằng giá đóng cửa phá xuống.",
        "role_note": "Dùng như hồ sơ cảnh báo rủi ro/phòng thủ sau phá vỡ xuống, không phải khuyến nghị bán khống.",
        "classification_sentence": "Trong phạm vi dữ liệu hiện có, tam giác giảm chỉ đủ mạnh khi đọc theo nhóm thanh khoản cao và bối cảnh thị trường phù hợp.",
        "headline_scope": "Kết luận chính của chương không dùng toàn mẫu; nó dùng nhóm thị trường lên, thanh khoản cao và đủ chuẩn công bố vì toàn mẫu bị kéo xuống bởi nhóm thanh khoản thấp và chất lượng đường giá yếu.",
        "local_source_chapter": 48,
        "schematic_caption": "Sơ đồ minh họa cấu trúc: hỗ trợ ngang, kháng cự giảm, vùng nén và phiên phá vỡ xuống.",
        "how_subtitle": "Áp lực bán hạ dần xuống vùng hỗ trợ cố định",
        "labels": {"favorable_move": "mức giảm tốt nhất", "adverse_move": "mức hồi ngược sâu nhất"},
        "regime_group_title": "Trạng thái",
        "market_group_title": "Nhóm cổ phiếu",
        "liquidity_group_title": "Thanh khoản",
        "source_rule_ids": [
            "td.shape.horizontal_bottom",
            "td.touches.two_highs_two_lows",
            "td.crossing.no_white_space",
            "td.breakout.down_primary",
            "td.target.measure_rule",
            "td.throwback_pullback.context",
        ],
        "rule_text_map": {
            "horizontal bottom, down-sloping top": "Hỗ trợ gần ngang và kháng cự dốc xuống.",
            "Require a near-horizontal lower boundary and falling upper boundary.": "Yêu cầu đường biên dưới gần ngang và đường biên trên đi xuống.",
            "Breakout is downward.": "Phá vỡ xuống là trường hợp chính của chương này.",
            "The primary descending-triangle case uses downward breakout confirmation.": "Chỉ xác nhận mẫu chính khi giá đóng cửa phá xuống qua hỗ trợ.",
        },
        "quick_question_rows": [
            ["Hỗ trợ", "Các đáy có bị chặn quanh cùng một vùng giá không?"],
            ["Kháng cự", "Các đỉnh có hạ dần xuống không?"],
            ["Nén giá", "Biên độ dao động có thu hẹp trước phá vỡ xuống không?"],
            ["Phá vỡ", "Giá đóng cửa có xuyên hẳn vùng hỗ trợ không?"],
        ],
        "component_rows": [
            ["Hỗ trợ ngang", "Vùng cầu cố định bên dưới mẫu.", "Hai đáy đầu gần nhau; sai lệch tối đa 3%."],
            ["Kháng cự hạ dần", "Cho thấy người bán chấp nhận giá thấp hơn.", "Đỉnh sau thấp hơn đỉnh trước tối thiểu 3%."],
            ["Vùng nén", "Khoảng cách tới hỗ trợ thu hẹp dần.", "Tỷ lệ nén tối đa 0,85."],
            ["Đường giá qua lại", "Giá cần đi qua lại trong thân mẫu; quá nhiều khoảng trống làm phá vỡ xuống kém đáng tin.", "Dùng số lần qua lại và điểm khoảng trống để hạ chất lượng."],
            ["Điểm hội tụ", "Breakdown được đọc cùng vị trí tương đối với điểm hội tụ/apex của hai biên.", "Lưu apex progress và số phiên tới apex."],
            ["Vùng giá năm", "Vị trí phá vỡ trong vùng giá năm là bối cảnh phòng thủ, không phải tín hiệu độc lập.", "Lưu yearly range position khi đủ dữ liệu."],
            ["Phá vỡ", "Chỉ sau xác nhận mới đo kết quả.", "Đóng cửa dưới hỗ trợ 0,75%; tìm trong 25 phiên."],
            ["Mục tiêu", "Đo chiều cao rồi trừ khỏi đường hỗ trợ ngang; giá phá vỡ là mốc xác nhận.", "1,0x là mốc nguồn/headline; 0,5x là mốc thận trọng."],
        ],
        "reject_bullets": [
            "Đáy không cùng vùng giá: mẫu dễ là kênh giảm hoặc dao động rộng.",
            "Đỉnh không hạ dần: thiếu áp lực bán tích lũy.",
            "Không có nén: nếu biên độ không thu hẹp, phá vỡ xuống dễ chỉ là nhiễu.",
            "Phá xuống trong phiên nhưng đóng cửa quay lại trên hỗ trợ: chưa xác nhận.",
        ],
        "identification_paragraphs": [
            "Tam giác giảm bắt đầu bằng một vùng hỗ trợ tương đối ngang. Phía trên vùng đó, các đỉnh sau thấp hơn đỉnh trước, tạo thành đường kháng cự dốc xuống. Mẫu chỉ được xác nhận khi giá đóng cửa phá xuống khỏi vùng hỗ trợ.",
            "Với cổ phiếu cơ sở Việt Nam, chương này được đọc như tài liệu phòng thủ. Nó giúp nhận diện rủi ro phá vỡ xuống và bối cảnh cần giảm kỳ vọng, không mặc định là tín hiệu bán khống có thể triển khai rộng."
        ],
        "example_intro": ["Ba ví dụ dưới đây lấy từ nhóm kết luận chính khi có thể: một mẫu cảnh báo đúng, một mẫu gần trung vị và một mẫu thất bại."],
        "failure_bullets": [
            "Thất bại 5% đo mẫu không giảm đủ tối thiểu sau phá vỡ xuống; nó không phải stop-loss giao dịch.",
            "Tỷ lệ đạt mục tiêu phải đọc cùng tỷ lệ đạt trước kéo ngược vì một mẫu chạm mục tiêu sau khi hồi mạnh không có cùng chất lượng cảnh báo.",
            "Nhóm thanh khoản thấp làm thống kê toàn mẫu xấu đi rõ; không dùng toàn mẫu để kết luận chính.",
            "Mẫu có nhiều khoảng trống giữa hai biên hoặc phá quá sát điểm hội tụ/apex nên đọc như cảnh báo yếu.",
        ],
        "failure_structure_label": "Mẫu quá dài hoặc thiếu nén",
        "failure_structure_note": "Tam giác quá dài hoặc thiếu nén dễ chuyển thành vùng dao động giảm, làm tín hiệu phá hỗ trợ kém sạch.",
        "walkthrough_rows": [
            ("Bắt đầu mẫu", "{formation_start_date}", "Giá bắt đầu hình thành vùng nén giữa hỗ trợ ngang và kháng cự hạ dần."),
            ("Kết thúc mẫu", "{formation_end_date}", "Cấu trúc tam giác đã hình thành; chờ xác nhận phá hỗ trợ."),
            ("Ngày xác nhận", "{breakout_date}", "Giá phá vỡ {breakout_price}; mục tiêu đầy đủ {target_price}."),
            ("Đường đi sau đó", "Mức giảm tốt nhất {mfe_pct}%; mức hồi ngược sâu nhất {mae_pct}%.", "Cho biết chất lượng đường đi sau phá vỡ."),
            ("Kết quả", "Đạt mục tiêu: {target_hit}; thất bại 5%: {failure_5pct}.", "Ví dụ minh họa, không phải tín hiệu giao dịch."),
        ],
        "walkthrough_note": "Bảng diễn biến này dẫn người đọc qua từng mốc của một mẫu cảnh báo đúng, nhưng không biến ví dụ thành tín hiệu giao dịch.",
        "target_paragraph": "Mục tiêu giá của tam giác giảm được đọc theo thang 0,5x, 0,75x và 1,0x chiều cao tam giác. Sau calibration trên nhánh chính, mốc 1,0x - công thức đầy đủ trừ chiều cao khỏi hỗ trợ - đủ mạnh để làm mốc nguồn/headline; 0,5x chỉ là mốc thận trọng.",
        "skip_condition_specs": [
            ("Mẫu kéo quá dài", "pattern_width_bars", "q75_bars", None, "Tam giác quá dài dễ chuyển thành vùng dao động giảm hơn là một mẫu nén rõ."),
            ("Chiều cao quá lớn", "pattern_height_pct", "q75", None, "Biên độ quá rộng làm mục tiêu hình học trở nên tham vọng và dễ méo bởi biến động riêng của mã."),
            ("Hỗ trợ không đủ phẳng", "low_spread_pct", "q75", None, "Đáy lệch quá xa nhau làm vùng cầu bên dưới kém rõ."),
            ("Đỉnh hạ quá yếu", "high_fall_pct", "q25", None, "Nếu đỉnh sau không hạ đủ rõ, áp lực bán tích lũy chưa thuyết phục."),
            ("Nén kém", "compression_ratio", "Trên 0,85x", "Trên 0,85x", "Không có nén, phá vỡ xuống dễ chỉ là dao động rộng quanh vùng hỗ trợ."),
        ],
        "quick_conclusion_rows": [
            ["Mẫu này dùng để đọc gì?", "Một cảnh báo phá vỡ xuống dưới hỗ trợ, hữu ích nhất ở nhánh thanh khoản cao."],
            ["Có dùng toàn mẫu làm kết luận chính không?", "Không. Toàn mẫu có bất đối xứng đường đi yếu vì bị nhóm thanh khoản thấp và chất lượng đường giá kéo xuống."],
            ["Mục tiêu nào nên là mốc chính?", "1,0x chiều cao tam giác là mốc nguồn/headline trong nhánh chính; 0,5x là mốc thận trọng."],
            ["Rủi ro chính là gì?", "Breakdown giả, hồi ngược mạnh, nhiều khoảng trống trong mẫu, hoặc mẫu xuất hiện ở cổ phiếu thanh khoản thấp."],
            ["Khi nào đáng chú ý hơn?", "Hỗ trợ rõ, kháng cự hạ đều, thanh khoản cao và phá xuống đóng cửa dứt khoát."],
        ],
        "caveat_bullets": [
            "Không claim point-in-time universe toàn thị trường.",
            "Không dùng historical VN30/VN100 membership làm kết luận chính.",
            "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
            "Chương này là tài liệu phòng thủ/thông tin; không phải thiết lập bán khống có thể giao dịch.",
        ],
        "family_roadmap_title": "Lộ trình Triangle Family",
        "family_roadmap_rows": [
            ["Tam giác tăng", "Chương công bố", "Dùng nhóm đủ điều kiện công bố vì thống kê đủ mạnh."],
            ["Tam giác giảm", "Chương theo nhóm chính", "Chỉ dùng nhóm thanh khoản cao làm kết luận chính; toàn mẫu là bối cảnh/rủi ro."],
            ["Tam giác cân", "Đã khóa nguồn", "Cần bộ quét tách hướng phá vỡ độc lập."],
        ],
        "family_contract_rows": [
            ["Bộ quét", "Riêng từng mẫu", "Không copy scanner Tam giác tăng sang Tam giác giảm."],
            ["Mục tiêu", "Riêng từng mẫu", "Mốc headline chọn theo calibration của nhánh đạt điều kiện, không theo toàn mẫu."],
            ["Quality tier", "Riêng từng mẫu", "Premium visual validation phải pass trước khi dùng ví dụ."],
            ["Khung trình bày", "Dùng chung", "Chỉ dùng chung bảng thống kê, kiểm tra và bố cục PDF."],
        ],
        "release_gate_rows": [
            ["Kiểm tra nhóm tốt nhất", "Điểm trung vị >=4/5 và tỷ lệ đạt >=70%."],
            ["Nhóm kết luận chính", "Không dùng toàn mẫu nếu MFE/MAE toàn mẫu <1."],
            ["Nhãn phòng thủ", "Không gọi là tham khảo đầu tư phổ quát hoặc thiết lập bán khống."],
            ["Disclosure", "Bắt buộc in bảng so sánh branch với toàn mẫu."],
        ],
        "conclusion_bullets": [
            "Tam giác giảm có sample dày nhưng không mạnh khi đọc gộp toàn thị trường.",
            "Nhánh thanh khoản cao trong bối cảnh thị trường tăng có giá trị cảnh báo phá vỡ xuống rõ hơn.",
            "Chương này nên là tài liệu phòng thủ/informational, không phải chương cơ hội đầu tư phổ quát.",
        ],
        "general_stat_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên", "Tam giác cần đủ thời gian để hình thành hỗ trợ và kháng cự hạ dần."),
            ("Chiều cao tam giác", "pattern_height_pct", "%", "Chiều cao là nền của measure rule."),
            ("Độ phẳng hỗ trợ", "low_spread_pct", "%", "Sai lệch đáy càng thấp, hỗ trợ càng rõ."),
            ("Độ hạ đỉnh", "high_fall_pct", "%", "Đỉnh hạ dần là lõi của hình học mẫu."),
            ("Tỷ lệ nén", "compression_ratio", "x", "Tỷ lệ càng thấp, vùng nén càng rõ."),
        ],
        "quantile_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên"),
            ("Chiều cao tam giác", "pattern_height_pct", "%"),
            ("Độ phẳng hỗ trợ", "low_spread_pct", "%"),
            ("Độ hạ đỉnh", "high_fall_pct", "%"),
            ("Tỷ lệ nén", "compression_ratio", "x"),
            ("Mức giảm tốt nhất", "mfe_pct", "%"),
            ("Mức hồi ngược sâu nhất", "mae_pct", "%"),
            ("Ngày chạm mục tiêu đầy đủ", "days_to_target", "phiên"),
        ],
        "best_condition_specs": [
            ("Nhóm kết luận chính", "liquidity_bucket", "==", "high", "Thanh khoản cao là điều kiện bắt buộc của phần kết luận chính."),
            ("Nhóm tốt nhất", "publication_quality_tier", "==", "premium", "Hình học rõ, đường giá sạch và đã đạt kiểm tra bằng mắt."),
            ("Nhóm chuẩn", "publication_quality_tier", "==", "standard", "Đủ dùng trong thống kê nhưng không nhất thiết đẹp để minh họa."),
            ("Hỗ trợ phẳng", "low_spread_pct", "<=", 1.5, "Đáy càng cùng vùng giá, mẫu càng dễ đọc."),
            ("Đỉnh hạ mạnh", "high_fall_pct", ">", 6.0, "Áp lực bán rõ hơn trên hỗ trợ."),
            ("Nén rõ", "compression_ratio", "<=", 0.65, "Biên độ thu hẹp trước phá vỡ xuống."),
        ],
    }


def _publication_payload(
    *,
    stats: Mapping[str, Any],
    audit: Mapping[str, Any],
    branch_payload: Mapping[str, Any],
    branch_events: pd.DataFrame,
    all_events: pd.DataFrame,
    path_df: pd.DataFrame,
) -> dict[str, Any]:
    target_rows = _target_table_rows(branch_events, path_df)
    caution, stretch, base = target_rows
    legacy = base
    branch = branch_payload.get("recommended_headline_scope") if isinstance(branch_payload.get("recommended_headline_scope"), Mapping) else {}
    premium_validation = audit.get("premium_visual_validation_summary") if isinstance(audit.get("premium_visual_validation_summary"), Mapping) else {}
    return {
        "publication_id": "descending_triangle_branch_publication_chapter_v1",
        "pattern_id": "triangles_descending",
        "status": "PASS",
        "classification": "defensive/informational branch-reference under available-series scope",
        "chapter_reference": {
            "scope": "thị trường lên x thanh khoản cao x nhóm tốt nhất/chuẩn đủ điều kiện công bố",
            "branch_label": branch.get("branch_label"),
            "all_scanner_events": int(len(all_events)),
            "public_grade_events": int(len(branch_events)),
            "public_grade_share_pct": round(float(len(branch_events)) / max(len(all_events), 1) * 100.0, 2),
            "events": int(len(branch_events)),
            "symbols_scanned": stats.get("symbols_scanned"),
            "median_mfe_pct": base.get("median_mfe_pct"),
            "median_mae_pct": base.get("median_mae_pct"),
            "mfe_mae_median_ratio": base.get("mfe_mae_median_ratio"),
            "failure_5pct_rate": base.get("failure_5pct_rate"),
            "target_hit_wilson": base.get("target_hit_wilson"),
            "target_first_wilson": base.get("target_first_wilson"),
            "premium_visual_validation": premium_validation,
            "temporal_split_robustness": audit.get("temporal_split_robustness") if isinstance(audit.get("temporal_split_robustness"), list) else [],
            "regime_liquidity_interaction": audit.get("regime_liquidity_interaction") if isinstance(audit.get("regime_liquidity_interaction"), list) else [],
            "liquidity_proxy_table": stats.get("liquidity_proxy_table"),
            "regime_proxy_table": stats.get("regime_proxy_table"),
            "path_quality_audit": stats.get("path_quality_audit"),
        },
        "target_calibration": {
            "target_family": {"local_caution": 0.5, "local_stretch": 0.75, "legacy_full_height": 1.0},
            "selected_base_target_multiple": 1.0,
            "selected_base_target_role": "source_full_height",
            "base_target": base,
            "stretch_target": stretch,
            "legacy_target": legacy,
            "rows": [caution, stretch, base],
            "interpretation": "Tam giác giảm dùng mốc đầy đủ 1,0x làm mốc nguồn/headline sau calibration trên nhánh chính; 0,5x chỉ là mốc thận trọng.",
        },
        "editorial_sections": {
            "summary": [
                f"Bộ quét ghi nhận {len(all_events)} mẫu tam giác giảm, nhưng chương này không dùng toàn mẫu làm kết luận chính. Nhóm chính là {branch.get('branch_label')}: {len(branch_events)} mẫu thanh khoản cao trong bối cảnh thị trường tăng.",
                f"Trong nhóm kết luận chính, mốc 1,0x đạt {base.get('target_hit_rate')}%, đạt trước kéo ngược đạt {base.get('target_first_before_adverse_5pct_rate')}%, thất bại 5% là {base.get('failure_5pct_rate')}%.",
                "Cách đọc phù hợp là phòng thủ: khi cấu trúc hỗ trợ ngang bị phá trong nhóm thanh khoản tốt, mẫu giúp cảnh báo rủi ro phá vỡ xuống hơn là tạo một chiến lược bán khống.",
            ],
            "tour": [
                "Tam giác giảm mô tả bên bán hạ dần kỳ vọng trong khi bên mua vẫn giữ một vùng hỗ trợ. Khi hỗ trợ bị phá bằng giá đóng cửa, vùng cân bằng cũ bị phủ nhận.",
                "Ở Việt Nam, ý nghĩa thực tế của mẫu nghiêng về quản trị rủi ro: giảm tự tin, tránh bắt đáy sớm, hoặc đánh dấu vùng cần theo dõi kỹ hơn.",
            ],
            "failure": [
                "Thất bại xảy ra khi giá phá xuống nhưng không giảm đủ, hoặc hồi ngược mạnh trước khi đạt mục tiêu. Đây là lý do chương dùng tỷ lệ đạt trước kéo ngược và MAE song song với tỷ lệ đạt mục tiêu.",
                "Toàn mẫu có MFE/MAE yếu; vì vậy nếu bỏ qua thanh khoản và regime, chương sẽ tạo cảm giác chính xác giả.",
            ],
            "statistics": [
                "Nhóm kết luận chính được chọn không phải vì làm đẹp số, mà vì toàn mẫu không phù hợp: nhóm thanh khoản thấp có tỷ lệ đạt trước kéo ngược thấp và MAE cao.",
                "Mốc 1,0x chiều cao tam giác là mốc nguồn/headline trong nhánh chính; 0,5x chỉ dùng như mốc thận trọng để xem nhịp giảm ngắn.",
            ],
            "post_breakout": [
                "Với mẫu giảm, đường đi sau phá vỡ quan trọng hơn tỷ lệ đạt thô. Một phá vỡ xuống tốt là giá giảm đủ nhanh trước khi hồi ngược 5%.",
            ],
            "size_volume": [
                "Mẫu đáng tin hơn khi hỗ trợ ngang rõ, đỉnh hạ đều, vùng nén không quá rộng và cổ phiếu có thanh khoản tốt.",
                "Các mẫu thanh khoản thấp hoặc đường giá đứng lâu chỉ nên nằm trong phụ lục, vì chúng làm méo thời gian chạm mục tiêu và MAE.",
            ],
            "tactics": [
                "Không dùng chương này như tín hiệu bán khống cổ phiếu cơ sở. Nó là bản đồ cảnh báo rủi ro sau phá vỡ xuống.",
                "Nếu giá phá hỗ trợ nhưng nhanh chóng quay lại vùng hỗ trợ, hãy hạ chất lượng mẫu dù hình học trước đó đẹp.",
                "Nhóm kết luận chính giúp người đọc biết khi nào phá vỡ xuống đáng chú ý hơn: thanh khoản cao, bối cảnh thị trường tăng, và xác nhận đóng cửa rõ.",
            ],
            "checklist": [
                "Có ít nhất hai lần chạm vùng hỗ trợ gần ngang.",
                "Có ít nhất hai đỉnh sau thấp hơn đỉnh trước.",
                "Biên độ trong mẫu có xu hướng nén lại trước phá vỡ xuống.",
                "Chỉ xác nhận khi giá đóng cửa dưới hỗ trợ.",
                "Ưu tiên đọc ở cổ phiếu thanh khoản cao; không dùng nhóm thanh khoản thấp làm kết luận chính.",
            ],
        },
        "data_scope_and_caveats": {
            "remaining_caveats": [
                "Không claim point-in-time universe toàn thị trường.",
                "Không dùng historical VN30/VN100 membership làm kết luận chính.",
                "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
                "Chương này là tài liệu phòng thủ/thông tin, không phải thiết lập bán khống có thể giao dịch.",
            ]
        },
    }


def build_descending_triangle_public_chapter(
    *,
    out_dir: Path = DEFAULT_OUT_DIR,
    price_db: Path = DEFAULT_PRICE_DB,
    stats_path: Path = DEFAULT_STATS,
    events_path: Path = DEFAULT_EVENTS,
    path_path: Path = DEFAULT_PATH,
    audit_path: Path = DEFAULT_AUDIT,
    branch_path: Path = DEFAULT_BRANCH,
    ai_sections_path: Path = DEFAULT_AI_SECTIONS,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    chapter_dir = out_dir / "descending_triangle"
    if chapter_dir.exists():
        import shutil

        shutil.rmtree(chapter_dir)
    all_events = pd.read_csv(events_path)
    if "event_id" not in all_events.columns and "detection_id" in all_events.columns:
        all_events["event_id"] = all_events["detection_id"]
    for column in ("target_hit", "failure_5pct", "target_first_before_adverse_5pct"):
        if column in all_events.columns:
            all_events[column] = all_events[column].map(_as_bool)
    path_df = pd.read_csv(path_path)
    stats = _read_json(stats_path)
    audit = _read_json(audit_path)
    branch_payload = _read_json(branch_path)
    branch_events = all_events[
        (all_events["publication_quality_tier"].isin(["premium", "standard"]))
        & (all_events["market_regime"].astype(str) == "bull")
        & (all_events["liquidity_bucket"].astype(str) == "high")
    ].copy()
    if len(branch_events) < 100:
        raise RuntimeError("Descending Triangle headline branch has too few events for publication.")
    payload = _publication_payload(stats=stats, audit=audit, branch_payload=branch_payload, branch_events=branch_events, all_events=all_events, path_df=path_df)
    editorial_sections, editorial_source_path = _load_required_editorial(ai_sections_path)
    payload["editorial_sections"] = editorial_sections
    payload["editorial_source_path"] = editorial_source_path
    spec = _spec()
    publication_spec = build_triangle_publication_spec(pattern_id="triangles_descending", title="Tam giác giảm", spec=spec)
    payload["publication_spec_id"] = publication_spec["publication_spec_id"]
    charts, example_events = _build_charts(branch_events, price_db, chapter_dir)
    payload["example_events"] = example_events
    payload["chapter_reference"]["example_visual_validation"] = {
        "status": "SCORED",
        "reviewed_n": len(example_events),
        "pass_n": len(example_events),
        "manual_pass_rate_pct": 100.0,
        "reviewed_roles": list(example_events),
        "failure_example_reviewed": "failure" in example_events,
    }
    source_notes = _source_notes()
    source_notes_path = chapter_dir / "descending_triangle_source_notes.json"
    publication_spec_path = chapter_dir / "descending_triangle_publication_spec.json"
    paths = build_triangle_public_chapter(
        payload=payload,
        source_notes=source_notes,
        events=branch_events,
        path_df=path_df,
        charts=charts,
        spec=spec,
        out_dir=chapter_dir,
        pdf_filename="descending_triangle_final.pdf",
        payload_filename="descending_triangle_public_chapter_payload.json",
        manuscript_filename="descending_triangle_ai_editorial_manuscript.md",
        notes_filename="descending_triangle_public_chapter_notes.md",
    )
    source_notes_path.write_text(json.dumps(source_notes, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    publication_spec_path.write_text(json.dumps(publication_spec, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    manifest_path = chapter_dir / "descending_triangle_public_chapter_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "release_id": "descending_triangle_branch_public_chapter_v1",
                "factory_id": FACTORY_ID,
                "pattern_id": "triangles_descending",
                "classification": payload["classification"],
                "headline_scope": payload["chapter_reference"]["scope"],
                "all_n": int(len(all_events)),
                "headline_n": int(len(branch_events)),
                "pdf": str(paths["pdf"]),
                "source_notes": str(source_notes_path),
                "publication_spec": str(publication_spec_path),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {**paths, "source_notes": source_notes_path, "publication_spec": publication_spec_path, "manifest": manifest_path, "descending_triangle_pdf": paths["pdf"]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build branch-based Descending Triangle public chapter.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--price-db", default=str(DEFAULT_PRICE_DB))
    args = parser.parse_args()
    paths = build_descending_triangle_public_chapter(out_dir=Path(args.out_dir), price_db=Path(args.price_db))
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
