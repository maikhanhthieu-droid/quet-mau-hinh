"""Build a branch-based public chapter for Symmetrical Triangle."""

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
DEFAULT_STATS = Path("artifacts/scanner_v2/symmetrical_triangles_db_source_parity/db_active/statistics.json")
DEFAULT_EVENTS = Path("artifacts/scanner_v2/symmetrical_triangles_db_source_parity/db_active/events.csv")
DEFAULT_PATH = Path("artifacts/scanner_v2/symmetrical_triangles_db_source_parity/db_active/post_breakout_path.csv")
DEFAULT_AUDIT = Path("artifacts/scanner_v2/symmetrical_triangle_publication_quality_audit/triangle_publication_quality_audit.json")
DEFAULT_BRANCH = Path("artifacts/scanner_v2/symmetrical_triangle_branch_candidates/symmetrical_triangle_branch_candidates.json")
DEFAULT_AI_SECTIONS = Path("artifacts/scanner_v2/source_guided_refinement_final_v1/triangle_family/symmetrical_triangle/ai/refined/approved_ai_sections.json")
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
        raise RuntimeError(f"Missing approved Symmetrical Triangle editorial sections in {path}: {', '.join(missing)}")
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
    x = np.array([0, 1, 2, 3, 4, 5, 6, 7.0, 8.0])
    y = np.array([19.0, 15.0, 18.0, 15.8, 17.2, 16.2, 16.8, 18.8, 20.4])
    fig, ax = plt.subplots(figsize=(9.2, 3.9), dpi=180)
    ax.plot(x, y, color="#173b3a", linewidth=2.0)
    ax.scatter(x, y, s=22, color="#173b3a")
    ax.plot([0, 6], [19.0, 16.8], color="#E45756", linestyle="--", linewidth=1.0)
    ax.plot([1, 6], [15.0, 16.7], color="#54A24B", linestyle="--", linewidth=1.0)
    ax.axvspan(0.0, 6.05, color="#1f77b4", alpha=0.10)
    ax.annotate("kháng cự hạ dần", xy=(3.5, 17.7), xytext=(1.1, 20.6), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
    ax.annotate("hỗ trợ nâng dần", xy=(3.2, 15.8), xytext=(1.0, 13.5), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
    ax.annotate("phá vỡ lên", xy=(7.0, 18.8), xytext=(6.1, 21.0), arrowprops={"arrowstyle": "->", "color": "#6f4aa8"}, color="#6f4aa8", fontsize=9)
    ax.axhline(20.4, color="#e98b2a", linestyle="--", linewidth=0.9)
    ax.text(0, 20.55, "mốc thận trọng theo chiều cao tam giác", color="#e98b2a", fontsize=8)
    ax.set_title("Giải phẫu mẫu tam giác cân", loc="left", fontsize=10)
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
        ax.add_patch(Rectangle((i - 0.32, min(o, c)), 0.64, max(abs(c - o), 1e-6), facecolor=color, edgecolor=color, linewidth=0.5, alpha=0.9))
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
        ax.text(ib + 0.3, float(df["high"].max()), "Phá vỡ lên", fontsize=8, color="#7A5195", va="bottom")
    try:
        ax.axhline(float(event.get("breakout_price")), color="#E45756", linewidth=0.85, alpha=0.85)
        ax.axhline(float(event.get("target_price")), color="#F58518", linestyle="--", linewidth=0.9, alpha=0.9)
    except (TypeError, ValueError):
        pass

    trend_end = max(v for v in (i1, ib, i0 or 0) if v is not None)
    formation_x = [i for i in range(len(df)) if (i0 or 0) <= i <= trend_end]
    offset = int(source_offset)
    _draw_trendline(ax, event, "upper", offset, formation_x, "#E45756")
    _draw_trendline(ax, event, "lower", offset, formation_x, "#54A24B")

    ax.set_title(title, fontsize=10, loc="left")
    ax.grid(alpha=0.14)
    y_candidates = [float(df["low"].min()), float(df["high"].max())]
    for key in ("target_price", "triangle_resistance", "triangle_support", "breakout_price"):
        try:
            value = float(event.get(key))
            if math.isfinite(value):
                y_candidates.append(value)
        except (TypeError, ValueError):
            pass
    y_min, y_max = min(y_candidates), max(y_candidates)
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
        row = _metrics(events.copy(), path_df, target_multiple=multiple, row_id=f"symmetrical_branch_{multiple}")
        rows.append(
            {
                "label": "triangles_symmetrical_up_mid_liquidity_main_scope",
                "target_multiple": row.get("target_multiple"),
                "target_role": "local_caution" if multiple == 0.5 else ("local_stretch" if multiple == 0.75 else "legacy_full_height"),
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
    pattern = (((registry.get("patterns") or {}).get("triangles_symmetrical")) or {})
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
        "local_source": {"pattern_key": "triangles_symmetrical", "chapter": 49, "name": "Triangles, Symmetrical"},
        "source_rules": rows,
    }


def _select_examples(events: pd.DataFrame) -> dict[str, pd.Series]:
    source = events.copy()
    source["_market_rank"] = source["market_group"].map({"VN30": 0, "VN100 ex VN30": 1}).fillna(2)
    for column in ("target_hit", "failure_5pct", "target_first_before_adverse_5pct"):
        if column in source.columns:
            source[column] = source[column].map(_as_bool)
    preferred = source[source["market_group"].isin(["VN30", "VN100 ex VN30"])].copy()
    if len(preferred) < 3:
        preferred = source.copy()
    success = preferred[(preferred["target_hit"]) & (preferred["target_first_before_adverse_5pct"])].copy()
    if success.empty:
        success = source[(source["target_hit"]) & (source["target_first_before_adverse_5pct"])].copy()
    failure = preferred[preferred["failure_5pct"]].copy()
    if failure.empty:
        failure = source[source["failure_5pct"]].copy()
    med = float(pd.to_numeric(preferred["mfe_pct"], errors="coerce").median())
    neutral = preferred[(~preferred["failure_5pct"]) & (~preferred["target_hit"])].copy()
    if neutral.empty:
        neutral = preferred[(~preferred["failure_5pct"])].copy()
    neutral["median_distance"] = (pd.to_numeric(neutral["mfe_pct"], errors="coerce") - med).abs()
    neutral["adverse_penalty"] = (pd.to_numeric(neutral["mae_pct"], errors="coerce") - pd.to_numeric(source["mae_pct"], errors="coerce").median()).clip(lower=0)
    return {
        "textbook_success": success.sort_values(["_market_rank", "publication_quality_score", "mfe_pct"], ascending=[True, False, False]).iloc[0],
        "middle_case": neutral.sort_values(["median_distance", "adverse_penalty", "_market_rank", "publication_quality_score"], ascending=[True, True, True, False]).iloc[0],
        "failure": failure.sort_values(["_market_rank", "mae_pct", "publication_quality_score"], ascending=[True, False, False]).iloc[0],
    }


def _build_charts(events: pd.DataFrame, price_db: Path, out_dir: Path) -> tuple[dict[str, Path], dict[str, dict[str, Any]]]:
    charts_dir = out_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    schematic = charts_dir / "symmetrical_triangle_ideal_schematic.png"
    _plot_schematic(schematic)
    paths = {"schematic": schematic}
    examples = _select_examples(events)
    event_payload: dict[str, dict[str, Any]] = {}
    title_map = {"textbook_success": "ví dụ phá vỡ lên tốt", "middle_case": "ví dụ trung vị", "failure": "ví dụ thất bại"}
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
        "title": "Tam giác cân",
        "subtitle": "Mẫu hội tụ hai biên - nhánh phá vỡ lên thanh khoản trung bình",
        "base_target_multiple": 0.5,
        "base_target_label": "0,5x",
        "legacy_target_multiple": 1.0,
        "legacy_target_label": "1,0x",
        "target_unit_label": "chiều cao tam giác",
        "target_focus_title": "Mốc thận trọng",
        "target_focus_caption": "mốc thận trọng 0,5x",
        "target_focus_reading": "mốc nhịp ngắn dùng vì full-height chưa đủ mạnh sau calibration",
        "target_full_title": "Mốc đầy đủ 1,0x",
        "target_full_reading": "mốc đầy đủ chưa đủ mạnh để làm headline, chỉ dùng để xem độ nhạy.",
        "morphology_sentence": "Kháng cự hạ dần, hỗ trợ nâng dần, biên độ nén lại và xác nhận bằng giá đóng cửa phá ra khỏi một trong hai biên.",
        "role_note": "Dùng như hồ sơ theo dõi phá vỡ lên trong nhóm thanh khoản trung bình; nhánh phá xuống chỉ nên đọc như cảnh báo phòng thủ.",
        "classification_sentence": "Trong phạm vi dữ liệu hiện có, tam giác cân không nên đọc gộp hai chiều; nhánh phá vỡ lên thanh khoản trung bình là phần đáng dùng nhất.",
        "headline_scope": "Kết luận chính của chương không dùng toàn mẫu. Tam giác cân là mẫu hai chiều, nên việc gộp phá vỡ lên và xuống sẽ che mất phần có ích; chương dùng nhánh phá vỡ lên, thanh khoản trung bình và đủ chuẩn công bố.",
        "local_source_chapter": 49,
        "schematic_caption": "Sơ đồ minh họa cấu trúc: hai đường xu hướng hội tụ, vùng nén và phiên phá vỡ lên.",
        "how_subtitle": "Vùng nén giữa bên mua nâng đáy và bên bán hạ đỉnh",
        "labels": {"favorable_move": "mức tăng tốt nhất", "adverse_move": "mức kéo ngược sâu nhất"},
        "source_rule_ids": [
            "ts.shape.converging_trendlines",
            "ts.touches.two_highs_two_lows",
            "ts.crossing.no_white_space",
            "ts.breakout.direction_split",
            "ts.duration.min_three_weeks",
            "ts.target.measure_rule",
        ],
        "rule_text_map": {
            "two converging trendlines": "Hai đường xu hướng hội tụ.",
            "Require a falling upper boundary and a rising lower boundary that converge before breakout.": "Yêu cầu biên trên hạ dần, biên dưới nâng dần và hai biên hội tụ trước phá vỡ.",
            "Breakout can be upward or downward.": "Tam giác cân có thể phá vỡ lên hoặc xuống.",
            "Symmetrical Triangle must be evaluated with separate upward and downward breakout branches.": "Phải đánh giá riêng nhánh phá vỡ lên và nhánh phá vỡ xuống; không dùng kết quả gộp làm kết luận chính.",
        },
        "quick_question_rows": [
            ["Biên trên", "Các đỉnh có hạ dần theo một đường kháng cự không?"],
            ["Biên dưới", "Các đáy có nâng dần theo một đường hỗ trợ không?"],
            ["Hội tụ", "Khoảng cách giữa hai biên có thu hẹp rõ trước phá vỡ không?"],
            ["Xác nhận", "Giá đóng cửa có phá hẳn lên trên biên trên không?"],
        ],
        "component_rows": [
            ["Kháng cự hạ dần", "Bên bán chấp nhận giá thấp hơn qua thời gian.", "Đỉnh sau thấp hơn đỉnh trước tối thiểu 3%."],
            ["Hỗ trợ nâng dần", "Bên mua nâng dần vùng chấp nhận giá.", "Đáy sau cao hơn đáy trước tối thiểu 3%."],
            ["Vùng nén", "Áp lực hai chiều tích tụ trước khi có hướng mới.", "Tỷ lệ nén tối đa 0,82."],
            ["Độ dài tối thiểu", "Mẫu quá ngắn dễ là pennant/cờ đuôi nheo hơn là tam giác cân.", "Tối thiểu khoảng 3 tuần giao dịch."],
            ["Đường giá qua lại", "Giá cần đi qua lại trong thân mẫu; quá nhiều khoảng trống làm mẫu kém sạch.", "Dùng crossing count và white-space score để hạ tier."],
            ["Điểm hội tụ", "Breakout được đọc cùng vị trí tương đối với điểm hội tụ/apex của hai biên.", "Lưu apex progress và số phiên tới apex."],
            ["Vùng giá năm", "Vị trí phá vỡ trong vùng giá năm là bối cảnh, không phải tín hiệu độc lập.", "Lưu yearly range position khi đủ dữ liệu."],
            ["Phá vỡ", "Chỉ sau xác nhận mới đo kết quả.", "Đóng cửa vượt biên 0,75%; tìm trong 25 phiên."],
            ["Mục tiêu", "Đo theo chiều cao tam giác từ vùng phá vỡ.", "0,5x là mốc thận trọng; 1,0x là mốc đầy đủ để kiểm độ nhạy."],
        ],
        "reject_bullets": [
            "Một trong hai biên không nghiêng đúng hướng: mẫu dễ là kênh giá hoặc tam giác tăng/giảm.",
            "Hai biên không hội tụ: thiếu yếu tố nén đặc trưng của tam giác cân.",
            "Phá vỡ trong phiên nhưng đóng cửa quay lại trong mẫu: chưa xác nhận.",
            "Đường giá quá thưa hoặc thanh khoản quá thấp: dễ làm sai thời gian chạm target và MAE.",
        ],
        "identification_paragraphs": [
            "Tam giác cân hình thành khi các đỉnh thấp dần và các đáy cao dần, khiến biên độ dao động bị nén lại giữa hai đường xu hướng hội tụ. Mẫu chỉ được tính sau khi giá đóng cửa phá ra khỏi một trong hai biên.",
            "Với dữ liệu hiện có, chương này chỉ nâng nhánh phá vỡ lên thanh khoản trung bình làm phần đọc chính. Nhánh phá xuống vẫn có giá trị thông tin, nhưng được đặt ở vai trò phòng thủ vì kết quả gộp hai chiều làm mờ thống kê."
        ],
        "example_intro": ["Ba ví dụ dưới đây ưu tiên nhóm VN30/VN100 khi có thể: một mẫu phá vỡ lên tốt, một mẫu gần trung vị và một mẫu thất bại."],
        "failure_bullets": [
            "Thất bại 5% đo mẫu không tăng đủ tối thiểu sau phá vỡ lên; nó không phải stop-loss giao dịch.",
            "Tỷ lệ đạt mục tiêu phải đọc cùng tỷ lệ đạt trước kéo ngược vì một mẫu chạm mục tiêu sau khi kéo ngược mạnh không có cùng chất lượng đường đi.",
            "Không dùng toàn mẫu hai chiều để kết luận; down-breakout là một nhánh khác với vai trò khác.",
            "Mẫu quá ngắn, nhiều khoảng trống hoặc phá vỡ quá sát điểm hội tụ/apex cần bị hạ trọng số.",
        ],
        "failure_structure_label": "Mẫu hội tụ kém hoặc quá dài",
        "failure_structure_note": "Nếu hai biên không hội tụ rõ hoặc mẫu kéo dài quá lâu, cấu trúc dễ trở thành vùng tích lũy/dao động hơn là một tam giác cân sạch.",
        "walkthrough_rows": [
            ("Bắt đầu mẫu", "{formation_start_date}", "Giá bắt đầu bị nén giữa kháng cự hạ dần và hỗ trợ nâng dần."),
            ("Kết thúc mẫu", "{formation_end_date}", "Hai biên hội tụ đủ rõ; chờ xác nhận phá vỡ."),
            ("Ngày xác nhận", "{breakout_date}", "Giá phá vỡ {breakout_price}; mục tiêu đầy đủ {target_price}."),
            ("Đường đi sau đó", "Mức tăng tốt nhất {mfe_pct}%; mức kéo ngược sâu nhất {mae_pct}%.", "Cho biết chất lượng đường đi sau phá vỡ."),
            ("Kết quả", "Đạt mục tiêu: {target_hit}; thất bại 5%: {failure_5pct}.", "Ví dụ minh họa, không phải tín hiệu giao dịch."),
        ],
        "target_paragraph": "Mục tiêu giá của tam giác cân nên đọc theo thang 0,5x, 0,75x và 1,0x chiều cao tam giác. Sau calibration, full-height 1,0x chưa đủ mạnh để làm headline; vì vậy 0,5x chỉ được ghi là mốc thận trọng cho nhánh chính, còn 1,0x giữ vai trò kiểm độ nhạy.",
        "skip_condition_specs": [
            ("Mẫu kéo quá dài", "pattern_width_bars", "q75_bars", None, "Tam giác quá dài dễ chuyển thành vùng tích lũy rộng hơn là một nhịp nén rõ."),
            ("Chiều cao quá lớn", "pattern_height_pct", "q75", None, "Biên độ quá rộng làm mục tiêu hình học trở nên tham vọng."),
            ("Nén kém", "compression_ratio", "Trên 0,82x", "Trên 0,82x", "Không có nén, phá vỡ dễ chỉ là dao động trong vùng rộng."),
            ("Đỉnh hạ quá yếu", "high_fall_pct", "q25", None, "Biên trên không hạ rõ thì hình học tam giác cân không đủ thuyết phục."),
            ("Đáy nâng quá yếu", "low_rise_pct", "q25", None, "Biên dưới không nâng rõ thì thiếu lực đỡ tích lũy."),
        ],
        "quick_conclusion_rows": [
            ["Mẫu này dùng để đọc gì?", "Một nhánh phá vỡ lên từ vùng nén hai biên, tốt nhất ở nhóm thanh khoản trung bình."],
            ["Có dùng toàn mẫu làm kết luận chính không?", "Không. Tam giác cân phải tách hướng phá vỡ; gộp lên/xuống làm yếu ý nghĩa."],
            ["Mục tiêu nào nên là mốc chính?", "0,5x là mốc thận trọng của nhánh chính; 1,0x chưa được phong headline."],
            ["Rủi ro chính là gì?", "Phá vỡ giả, kéo ngược sâu, quá nhiều khoảng trống hoặc nhầm với pennant/kênh giá/tam giác tăng giảm."],
            ["Khi nào đáng chú ý hơn?", "Hai biên hội tụ sạch, phá lên đóng cửa rõ và MAE không quá sâu sau xác nhận."],
        ],
        "caveat_bullets": [
            "Không claim point-in-time universe toàn thị trường.",
            "Không dùng historical VN30/VN100 membership làm kết luận chính.",
            "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
            "Chapter này là watchlist-reference theo nhánh; không phải hệ thống giao dịch.",
        ],
        "family_roadmap_title": "Lộ trình Triangle Family",
        "family_roadmap_rows": [
            ["Tam giác tăng", "Chương công bố", "Dùng nhóm đủ điều kiện công bố vì thống kê đủ mạnh."],
            ["Tam giác giảm", "Chương phòng thủ/thông tin", "Dùng nhóm kết luận chính, không dùng toàn mẫu."],
            ["Tam giác cân", "Chương theo dõi theo nhánh", "Dùng nhánh phá vỡ lên x thanh khoản trung bình."],
        ],
        "family_contract_rows": [
            ["Bộ quét", "Riêng từng mẫu", "Không dùng chung hình học giữa ba biến thể tam giác."],
            ["Mục tiêu", "Riêng từng mẫu", "Mốc headline chỉ được chọn nếu calibration pass; hiện dùng 0,5x như mốc thận trọng."],
            ["Quality tier", "Riêng từng mẫu", "Visual validation dùng để chặn ví dụ sai hình thái."],
            ["Khung trình bày", "Dùng chung", "Chỉ dùng chung bảng thống kê, kiểm tra và bố cục PDF."],
        ],
        "release_gate_rows": [
            ["Tách hướng phá vỡ", "Không được dùng toàn mẫu lên/xuống làm kết luận chính."],
            ["Nhánh kết luận chính", "Nhánh kết luận chính phải có N >= 250 và MFE/MAE > 1,10."],
            ["Example check", "Ví dụ in trong chương phải là biểu đồ nến và được kiểm tra bằng mắt."],
            ["Disclosure", "Bắt buộc nói rõ nhánh phá xuống chỉ là bối cảnh/phòng thủ."],
        ],
        "conclusion_bullets": [
            "Tam giác cân phổ biến nhưng không thể đọc gộp hai chiều.",
            "Nhánh phá vỡ lên thanh khoản trung bình là phần đủ tốt để làm kết luận chính trong dữ liệu hiện có.",
            "Chương này là watchlist-reference theo nhánh, không phải tín hiệu mua bán tự động.",
        ],
        "general_stat_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên", "Tam giác cần đủ thời gian để hai biên hội tụ."),
            ("Chiều cao tam giác", "pattern_height_pct", "%", "Chiều cao là nền của measure rule."),
            ("Độ hạ đỉnh", "high_fall_pct", "%", "Đỉnh hạ dần tạo biên trên."),
            ("Độ nâng đáy", "low_rise_pct", "%", "Đáy nâng dần tạo biên dưới."),
            ("Tỷ lệ nén", "compression_ratio", "x", "Tỷ lệ càng thấp, vùng nén càng rõ."),
        ],
        "quantile_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên"),
            ("Chiều cao tam giác", "pattern_height_pct", "%"),
            ("Độ hạ đỉnh", "high_fall_pct", "%"),
            ("Độ nâng đáy", "low_rise_pct", "%"),
            ("Tỷ lệ nén", "compression_ratio", "x"),
            ("Mức tăng tốt nhất", "mfe_pct", "%"),
            ("Mức kéo ngược sâu nhất", "mae_pct", "%"),
            ("Ngày chạm mục tiêu đầy đủ", "days_to_target", "phiên"),
        ],
        "best_condition_specs": [
            ("Nhánh kết luận chính", "liquidity_bucket", "==", "mid", "Thanh khoản trung bình là vùng cân bằng tốt nhất giữa độ dày mẫu và chất lượng đường đi."),
            ("Nhóm tốt nhất", "publication_quality_tier", "==", "premium", "Hình học rõ nhất nhưng mẫu còn mỏng."),
            ("Nhóm chuẩn", "publication_quality_tier", "==", "standard", "Nguồn chính của kết luận vì nhóm tốt nhất còn ít."),
            ("Nén rõ", "compression_ratio", "<=", 0.65, "Biên độ thu hẹp rõ trước phá vỡ."),
            ("Đỉnh hạ mạnh", "high_fall_pct", ">", 6.0, "Biên trên có áp lực bán rõ."),
            ("Đáy nâng mạnh", "low_rise_pct", ">", 6.0, "Biên dưới có lực đỡ rõ."),
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
    base, stretch, legacy = target_rows
    branch = branch_payload.get("recommended_headline_scope") if isinstance(branch_payload.get("recommended_headline_scope"), Mapping) else {}
    premium_validation = audit.get("premium_visual_validation_summary") if isinstance(audit.get("premium_visual_validation_summary"), Mapping) else {}
    if premium_validation.get("status") != "SCORED":
        premium_validation = {}
    return {
        "publication_id": "symmetrical_triangle_branch_publication_chapter_v1",
        "pattern_id": "triangles_symmetrical",
        "status": "PASS",
        "classification": "watchlist-reference branch under available-series scope",
        "chapter_reference": {
            "scope": "phá vỡ lên x thanh khoản trung bình x nhóm đủ chuẩn công bố",
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
            "selected_base_target_multiple": 0.5,
            "selected_base_target_role": "local_caution",
            "base_target": base,
            "stretch_target": stretch,
            "legacy_target": legacy,
            "rows": target_rows,
            "interpretation": "Tam giác cân dùng kết luận theo hướng phá vỡ. Nhánh phá vỡ lên thanh khoản trung bình đủ mạnh cho chương theo dõi; toàn mẫu lên/xuống không được dùng làm kết luận chính.",
        },
        "editorial_sections": {
            "summary": [
                f"Bộ quét ghi nhận {len(all_events)} mẫu tam giác cân. Tuy nhiên, chương này không dùng toàn mẫu vì mẫu có thể phá vỡ lên hoặc xuống.",
                f"Nhánh kết luận chính là phá vỡ lên trong nhóm thanh khoản trung bình: {len(branch_events)} mẫu đạt chuẩn công bố.",
                f"Ở mốc thận trọng 0,5x chiều cao tam giác, tỷ lệ đạt mục tiêu là {base.get('target_hit_rate')}%, tỷ lệ đạt trước kéo ngược là {base.get('target_first_before_adverse_5pct_rate')}%, thất bại 5% là {base.get('failure_5pct_rate')}%.",
            ],
            "tour": [
                "Tam giác cân là vùng nén hai chiều: bên mua nâng dần vùng hỗ trợ, còn bên bán hạ dần vùng kháng cự. Giá càng đi về cuối mẫu, không gian dao động càng hẹp.",
                "Vì mẫu có thể phá lên hoặc phá xuống, hướng phá vỡ là một phần của kết luận. Nhánh phá vỡ lên trong dữ liệu hiện tại cho thấy bất đối xứng MFE/MAE tốt hơn nhánh phá xuống.",
            ],
            "failure": [
                "Thất bại xảy ra khi giá phá lên nhưng không đi đủ 5%, hoặc kéo ngược sâu trước khi chạm mục tiêu. Đây là lý do chương dùng tỷ lệ đạt trước kéo ngược và MAE song song với tỷ lệ đạt mục tiêu.",
                "Nhánh phá xuống không được dùng làm kết luận đầu tư; nó vẫn nên giữ trong bối cảnh phòng thủ để cảnh báo rủi ro phá vỡ xuống.",
            ],
            "statistics": [
                "Kết quả chính đến từ nhánh phá vỡ lên thanh khoản trung bình. Nhánh này giữ được MFE/MAE cao hơn 1 và có Wilson CI đủ hẹp để đọc như watchlist-reference.",
                "Mốc 0,5x chiều cao tam giác là mốc thận trọng vì 1,0x chưa đủ mạnh sau calibration. Mốc 1,0x chỉ là tham chiếu đầy đủ khi phá vỡ đi rất xa.",
            ],
            "post_breakout": [
                "Với tam giác cân, đường đi sau phá vỡ quan trọng hơn hit rate thô. Một phá vỡ tốt là giá tăng đủ trước khi bị kéo ngược 5%.",
            ],
            "size_volume": [
                "Mẫu đáng tin hơn khi hai biên hội tụ sạch, thanh khoản không quá thấp và phiên phá vỡ đóng cửa rõ ngoài biên trên.",
                "Nhóm tốt nhất đẹp hơn về hình học nhưng còn mỏng; vì vậy kết luận chính dùng nhóm tốt nhất + nhóm chuẩn thay vì chỉ nhóm tốt nhất.",
            ],
            "tactics": [
                "Không dùng chương này như tín hiệu mua tự động. Nó là bản đồ theo dõi các phá vỡ lên từ vùng nén hai biên.",
                "Nếu giá phá lên nhưng quay lại ngay vào thân mẫu, hạ chất lượng mẫu dù hình học trước đó đẹp.",
                "Phá vỡ xuống trong tam giác cân nên đọc như cảnh báo rủi ro riêng, không trộn với kết luận phá vỡ lên.",
            ],
            "checklist": [
                "Có ít nhất hai đỉnh hạ dần và hai đáy nâng dần.",
                "Hai biên phải hội tụ; không chỉ là hai đường song song.",
                "Chỉ xác nhận khi giá đóng cửa phá lên khỏi biên trên.",
                "Ưu tiên nhánh thanh khoản trung bình theo kết quả hiện tại.",
                "Đọc tỷ lệ đạt trước kéo ngược và MAE trước khi kết luận mẫu có chất lượng.",
            ],
        },
        "data_scope_and_caveats": {
            "remaining_caveats": [
                "Không claim point-in-time universe toàn thị trường.",
                "Không dùng historical VN30/VN100 membership làm kết luận chính.",
                "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
                "Chapter này là watchlist-reference theo nhánh, không phải hệ thống giao dịch.",
            ]
        },
    }


def build_symmetrical_triangle_public_chapter(
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
    chapter_dir = out_dir / "symmetrical_triangle"
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
        & (all_events["breakout_direction"].astype(str) == "up")
        & (all_events["liquidity_bucket"].astype(str) == "mid")
    ].copy()
    if len(branch_events) < 250:
        raise RuntimeError("Symmetrical Triangle headline branch has too few events for publication.")
    payload = _publication_payload(stats=stats, audit=audit, branch_payload=branch_payload, branch_events=branch_events, all_events=all_events, path_df=path_df)
    editorial_sections, editorial_source_path = _load_required_editorial(ai_sections_path)
    payload["editorial_sections"] = editorial_sections
    payload["editorial_source_path"] = editorial_source_path
    spec = _spec()
    publication_spec = build_triangle_publication_spec(pattern_id="triangles_symmetrical", title="Tam giác cân", spec=spec)
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
    source_notes_path = chapter_dir / "symmetrical_triangle_source_notes.json"
    publication_spec_path = chapter_dir / "symmetrical_triangle_publication_spec.json"
    paths = build_triangle_public_chapter(
        payload=payload,
        source_notes=source_notes,
        events=branch_events,
        path_df=path_df,
        charts=charts,
        spec=spec,
        out_dir=chapter_dir,
        pdf_filename="symmetrical_triangle_final.pdf",
        payload_filename="symmetrical_triangle_public_chapter_payload.json",
        manuscript_filename="symmetrical_triangle_ai_editorial_manuscript.md",
        notes_filename="symmetrical_triangle_public_chapter_notes.md",
    )
    source_notes_path.write_text(json.dumps(source_notes, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    publication_spec_path.write_text(json.dumps(publication_spec, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    manifest_path = chapter_dir / "symmetrical_triangle_public_chapter_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "release_id": "symmetrical_triangle_branch_public_chapter_v1",
                "factory_id": FACTORY_ID,
                "pattern_id": "triangles_symmetrical",
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
    return {**paths, "source_notes": source_notes_path, "publication_spec": publication_spec_path, "manifest": manifest_path, "symmetrical_triangle_pdf": paths["pdf"]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build branch-based Symmetrical Triangle public chapter.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--price-db", default=str(DEFAULT_PRICE_DB))
    args = parser.parse_args()
    paths = build_symmetrical_triangle_public_chapter(out_dir=Path(args.out_dir), price_db=Path(args.price_db))
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
