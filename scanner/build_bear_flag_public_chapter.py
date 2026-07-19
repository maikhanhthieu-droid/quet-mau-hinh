"""Build a public-facing Vietnamese Bear Flag chapter."""

from __future__ import annotations

import argparse
import html
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scanner.publication_rendering_primitives import (  # noqa: E402
    _FONT_REGULAR,
    _STYLES,
    _callout,
    _fmt,
    _image,
    _metric_card,
    _p,
    _section_title,
    _table,
)
from scanner.build_bear_flag_source_grounding import build_source_notes, write_source_notes  # noqa: E402


DEFAULT_EVENTS = Path("artifacts/scanner_v2/bear_flags/events.csv")
DEFAULT_PATH = Path("artifacts/scanner_v2/bear_flags/post_breakout_path.csv")
DEFAULT_STATS = Path("artifacts/scanner_v2/bear_flags/statistics.json")
DEFAULT_SOURCE_NOTES = Path("artifacts/scanner_v2/bear_flags_source_grounding/bear_flag_source_notes.json")
DEFAULT_PRICE_DB = Path("vietnam_stocks.db")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bear_flags_public_chapter")


def _read_json(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _esc(value: Any) -> str:
    return html.escape(str(value))


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _load_ohlcv(price_db: Path, symbol: str) -> pd.DataFrame:
    conn = sqlite3.connect(str(price_db))
    try:
        df = pd.read_sql_query(
            "SELECT time AS date, open, high, low, close, volume FROM stock_price_history WHERE symbol = ? ORDER BY time",
            conn,
            params=[symbol],
        )
    finally:
        conn.close()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["date", "open", "high", "low", "close"]).reset_index(drop=True)


def _slice_around_event(df: pd.DataFrame, event: Mapping[str, Any], pre_bars: int = 35, post_bars: int = 35) -> pd.DataFrame:
    fs = pd.to_datetime(event["formation_start_date"])
    bd = pd.to_datetime(event["breakout_date"])
    start_idx = int(df["date"].searchsorted(fs, side="left"))
    breakout_idx = int(df["date"].searchsorted(bd, side="left"))
    return df.iloc[max(0, start_idx - pre_bars) : min(len(df), breakout_idx + post_bars + 1)].copy().reset_index(drop=True)


def _plot_event_chart(df: pd.DataFrame, event: Mapping[str, Any], out_path: Path, title: str) -> None:
    fs = pd.to_datetime(event["formation_start_date"])
    fe = pd.to_datetime(event["formation_end_date"])
    bd = pd.to_datetime(event["breakout_date"])
    x = np.arange(len(df))
    fig, ax = plt.subplots(figsize=(9.2, 4.8), dpi=180)
    for i, row in df.iterrows():
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        color = "#1b8a5a" if c >= o else "#c44e52"
        ax.vlines(i, l, h, color="#222222", linewidth=0.7, alpha=0.75)
        ax.add_patch(Rectangle((i - 0.32, min(o, c)), 0.64, max(abs(c - o), 1e-6), facecolor=color, edgecolor=color, linewidth=0.5, alpha=0.9))
    ax.plot(x, df["close"], color="#222222", linewidth=0.9, alpha=0.28)

    def nearest(ts: pd.Timestamp) -> int:
        idx = int(df["date"].searchsorted(ts, side="left"))
        return max(0, min(idx, len(df) - 1))

    i0, i1, ib = nearest(fs), nearest(fe), nearest(bd)
    ax.axvspan(i0 - 0.5, i1 + 0.5, color="#1f77b4", alpha=0.10)
    ax.axvline(ib, color="#6f4aa8", linewidth=1.15)
    ax.text(ib + 0.3, float(df["high"].max()), "Phá vỡ xuống", fontsize=8, color="#6f4aa8", va="bottom")
    breakout_price = float(event["breakout_price"])
    target_price = float(event["target_price"])
    ax.axhline(breakout_price, color="#245b5a", linestyle="--", linewidth=0.9, alpha=0.85)
    ax.axhline(target_price, color="#e98b2a", linestyle="--", linewidth=0.9, alpha=0.9)
    ax.text(0.5, breakout_price, "giá phá vỡ", fontsize=7, color="#245b5a", va="bottom")
    ax.text(0.5, target_price, "mục tiêu", fontsize=7, color="#e98b2a", va="bottom")
    ax.set_title(title, fontsize=10, loc="left")
    ax.grid(True, alpha=0.14)
    y_min = min(float(df["low"].min()), breakout_price, target_price)
    y_max = max(float(df["high"].max()), breakout_price, target_price)
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


def _plot_ideal_schematic(out_path: Path) -> None:
    x = np.array([0, 1, 2, 3, 4, 5, 6, 7.4, 8.4])
    y = np.array([32, 29, 24, 17, 19, 18, 20, 15, 12])
    fig, ax = plt.subplots(figsize=(9.2, 3.9), dpi=180)
    ax.plot(x, y, color="#173b3a", linewidth=2.0)
    ax.scatter(x, y, s=22, color="#173b3a")
    ax.axvspan(3.85, 6.15, color="#1f77b4", alpha=0.11)
    ax.annotate("cột cờ giảm", xy=(2.2, 22), xytext=(0.7, 18), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
    ax.annotate("thân cờ hồi ngắn", xy=(5.0, 19), xytext=(4.3, 25), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
    ax.annotate("phá vỡ xuống", xy=(7.4, 15), xytext=(6.5, 10), arrowprops={"arrowstyle": "->", "color": "#6f4aa8"}, color="#6f4aa8", fontsize=9)
    ax.axhline(15, color="#6f4aa8", linestyle="--", linewidth=0.9)
    ax.axhline(12, color="#e98b2a", linestyle="--", linewidth=0.9)
    ax.text(0, 11.2, "mục tiêu cơ sở 0,46 lần chiều cao cột cờ", color="#e98b2a", fontsize=8)
    ax.set_title("Giải phẫu mẫu cờ giảm", loc="left", fontsize=10)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)


def _select_examples(events: pd.DataFrame) -> Dict[str, pd.Series]:
    source = events[events["market_group"].isin(["VN30", "VN100 ex VN30"])].copy()
    if source.empty:
        source = events.copy()
    source["_market_rank"] = source["market_group"].map({"VN30": 0, "VN100 ex VN30": 1}).fillna(2)
    for col in ["target_hit", "failure_5pct", "target_first_before_adverse_5pct"]:
        source[col] = source[col].map(_bool)
    success = source[(source["target_hit"]) & (source["target_first_before_adverse_5pct"])].copy()
    failure = source[source["failure_5pct"]].copy()
    neutral = source[(~source["target_hit"]) & (~source["failure_5pct"])].copy()
    med = float(source["mfe_pct"].median())
    neutral["median_distance"] = (pd.to_numeric(neutral["mfe_pct"], errors="coerce") - med).abs()
    failure_mae_med = float(pd.to_numeric(failure["mae_pct"], errors="coerce").median()) if not failure.empty else 0.0
    failure["failure_mae_distance"] = (pd.to_numeric(failure["mae_pct"], errors="coerce") - failure_mae_med).abs()
    return {
        "textbook_success": success.sort_values(["_market_rank", "pattern_quality_score", "mfe_pct"], ascending=[True, False, False]).iloc[0],
        "failure": failure.sort_values(["_market_rank", "failure_mae_distance", "pattern_quality_score"], ascending=[True, True, False]).iloc[0],
        "middle_case": neutral.sort_values(["_market_rank", "median_distance", "pattern_quality_score"], ascending=[True, True, False]).iloc[0],
    }


def _build_example_charts(events: pd.DataFrame, price_db: Path, out_dir: Path) -> Dict[str, Path]:
    charts_dir = out_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    schematic = charts_dir / "bear_flag_ideal_schematic.png"
    _plot_ideal_schematic(schematic)
    paths = {"schematic": schematic}
    examples = _select_examples(events)
    for key, event in examples.items():
        raw = _load_ohlcv(price_db, str(event["symbol"]))
        window = _slice_around_event(raw, event)
        title_map = {"textbook_success": "ví dụ cảnh báo đúng", "middle_case": "ví dụ trung vị", "failure": "ví dụ thất bại"}
        out_path = charts_dir / f"{key}_{event['symbol']}_{event['breakout_date']}.png"
        _plot_event_chart(window, event, out_path, f"{event['symbol']} - {title_map[key]} ({event['breakout_date']})")
        paths[key] = out_path
    return paths


def _target_row(stats: Mapping[str, Any], multiple: float) -> Mapping[str, Any]:
    for row in stats.get("target_family_sensitivity") or []:
        if row.get("label") == "bear_flags" and float(row.get("target_multiple") or -1) == multiple:
            return row
    return {}


def _headline_scope_id(branch: Mapping[str, Any]) -> str:
    return str(branch.get("branch_id") or branch.get("aggregate_id") or "n/a")


def _summary_rows(stats: Mapping[str, Any], events: pd.DataFrame) -> list[list[Any]]:
    base = _target_row(stats, 0.46)
    legacy = _target_row(stats, 1.0)
    branch = stats.get("bear_branch_headline") if isinstance(stats.get("bear_branch_headline"), Mapping) else {}
    headline_id = _headline_scope_id(branch)
    vn100 = int(events[events["market_group"].isin(["VN30", "VN100 ex VN30"])].shape[0])
    return [
        ["Mục", "Kết quả chính"],
        ["Diện mạo", "Mẫu tiếp diễn xuống: cột cờ giảm mạnh, thân cờ hồi ngắn, xác nhận bằng giá đóng cửa phá xuống."],
        ["Phạm vi ví dụ", f"{vn100} mẫu thuộc VN30/VN100; biểu đồ minh họa ưu tiên nhóm này."],
        ["Số mẫu đo được", f"{_fmt(stats.get('detection_count'), 0)} mẫu / {_fmt(events['symbol'].nunique(), 0)} mã."],
        ["Nhánh chính", f"{headline_id}: {_fmt(branch.get('n'), 0)} mẫu, đạt 0,46x {_fmt(branch.get('base_target_hit_rate'))}%, thất bại {_fmt(branch.get('failure_5pct_rate'))}%."],
        ["Toàn mẫu", f"0,46 lần chiều cao cột cờ đạt {_fmt(base.get('target_hit_rate'))}%; mốc đầy đủ 1,0x đạt {_fmt(legacy.get('target_hit_rate'))}%."],
        ["Thất bại 5%", f"{_fmt(stats.get('failure_5pct_rate'))}% mẫu không đi được tối thiểu 5% theo hướng giảm."],
        ["Cách dùng", "Dùng như hồ sơ cảnh báo rủi ro sau phá vỡ xuống, không phải khuyến nghị bán khống."],
    ]


def _important_findings(stats: Mapping[str, Any], events: pd.DataFrame) -> list[str]:
    base = _target_row(stats, 0.46)
    legacy = _target_row(stats, 1.0)
    branch = stats.get("bear_branch_headline") if isinstance(stats.get("bear_branch_headline"), Mapping) else {}
    headline_id = _headline_scope_id(branch)
    high_liq = events[events["liquidity_bucket"].astype(str) == "high"]
    return [
        f"Headline mới dùng nhánh {headline_id}: đạt 0,46x {_fmt(branch.get('base_target_hit_rate'))}%, target-first {_fmt(branch.get('base_target_first_before_adverse_5pct_rate'))}%, thất bại {_fmt(branch.get('failure_5pct_rate'))}%.",
        f"Mục tiêu cơ sở 0,46x đạt {_fmt(base.get('target_hit_rate'))}%, trong khi mốc đầy đủ 1,0x chỉ đạt {_fmt(legacy.get('target_hit_rate'))}%.",
        f"Mức giảm tốt nhất trung vị là {_fmt(stats.get('median_mfe_pct'))}%, thấp hơn mức bật ngược sâu nhất trung vị {_fmt(stats.get('median_mae_pct'))}%.",
        f"Nhóm thanh khoản cao có mức giảm tốt nhất trung vị {_fmt(float(high_liq['mfe_pct'].median()) if not high_liq.empty else None)}% và thất bại 5% {_fmt(float(high_liq['failure_5pct'].map(_bool).mean()*100) if not high_liq.empty else None)}%.",
        "Kết quả tổng thể yếu hơn Bull Flag, nên chương này được phân loại là tài liệu phòng thủ/thông tin.",
    ]


def _rule_rows(source_notes: Mapping[str, Any]) -> list[list[Any]]:
    rows = [["Quy tắc", "Cách Việt hóa"]]
    priority_rule_ids = {
        "bear_flag_prior_decline",
        "bear_flag_parallel_channel",
        "bear_flag_short_duration",
        "bear_flag_body_direction",
        "bear_flag_down_breakout",
        "bear_flag_volume_context",
    }
    selected = []
    for rule in source_notes.get("source_rules") or []:
        if not isinstance(rule, Mapping):
            continue
        if str(rule.get("rule_id")) in priority_rule_ids:
            selected.append(rule)
    if not selected:
        selected = [rule for rule in source_notes.get("source_rules") or [] if isinstance(rule, Mapping)][:6]
    for rule in selected[:6]:
        rows.append([_vi_rule_text(rule.get("short_excerpt")), _vi_rule_text(rule.get("implementation_mapping"))])
    return rows


def _vi_rule_text(value: Any) -> str:
    raw = str(value)
    replacements = {
        "Steep, quick price trend": "Xu hướng giá nhanh và dốc",
        "Price action bounded by two parallel trend lines.": "Giá nằm trong hai đường xu hướng gần song song.",
        "Flags are short, from a few days to 3 weeks.": "Cờ là mẫu ngắn, từ vài ngày đến khoảng ba tuần.",
        "They rise in a down-trend and fall in an uptrend": "Cờ giảm thường hồi lên hoặc đi ngang trong một xu hướng giảm.",
        "price closes outside the flag trend line": "Giá đóng cửa ra ngoài đường xu hướng của thân cờ.",
        "Volume usually trends downward throughout the formation.": "Khối lượng thường giảm trong quá trình hình thành mẫu.",
        "Calculate the price difference between the start of the trend and the formation.": "Đo chênh lệch giá giữa điểm bắt đầu xu hướng giảm và vùng hình thành thân cờ.",
        "If you do not have a strong advance or decline leading to the chart pattern, ignore the flag.": "Nếu không có nhịp tăng hoặc giảm mạnh dẫn vào mẫu, hãy bỏ qua cờ.",
        "Require a steep, quick decline before a Bear Flag formation.": "Yêu cầu một nhịp giảm nhanh và dốc trước khi thân cờ hình thành.",
        "Require the bear flag body to fit a short channel bounded by approximately parallel trendlines.": "Yêu cầu thân cờ giảm nằm trong một kênh ngắn với hai đường biên gần song song.",
        "Reject bear flag formations that last longer than three trading weeks.": "Loại các thân cờ giảm kéo dài quá khoảng ba tuần giao dịch.",
        "For Bear Flags, the flag body should drift sideways to upward against the prior decline.": "Với cờ giảm, thân cờ nên hồi ngang hoặc nghiêng lên nhẹ, ngược hướng với nhịp giảm trước đó.",
        "Confirm a Bear Flag only when price closes below the lower flag trendline.": "Chỉ xác nhận cờ giảm khi giá đóng cửa dưới đường biên dưới của thân cờ.",
        "Record falling volume during the bear flag as a context feature, but do not make it a hard gate.": "Ghi nhận khối lượng giảm như một biến bối cảnh, nhưng không dùng làm điều kiện loại trực tiếp.",
        "Compute the legacy pole-height measure rule from the start of the prior decline to the flag formation, then keep fractional targets as Vietnam calibration bands.": "Đo chiều cao cột cờ từ điểm bắt đầu nhịp giảm tới vùng thân cờ, rồi dùng các mức mục tiêu phân đoạn cho thị trường Việt Nam.",
        "Invalidate Bear Flag candidates that do not follow a strong decline.": "Loại ứng viên cờ giảm nếu phía trước không có nhịp giảm đủ mạnh.",
    }
    return replacements.get(raw, raw)


def _vi_lane(value: Any) -> str:
    mapping = {
        "defensive-core": "phòng thủ lõi",
        "defensive-core-plus-watchlist": "lõi + theo dõi",
        "defensive-watchlist": "theo dõi phòng thủ",
        "informational": "thông tin",
        "high-liquidity-diagnostic": "thanh khoản cao",
        "defensive-core-strict": "lõi chặt",
    }
    return mapping.get(str(value), str(value))


def _target_rows(stats: Mapping[str, Any]) -> list[list[Any]]:
    rows = [["Mốc", "Vai trò", "Số mẫu", "Đạt mục tiêu", "Đạt trước bật ngược", "Thất bại 5%"]]
    for row in stats.get("target_family_sensitivity") or []:
        if row.get("label") != "bear_flags":
            continue
        rows.append([
            f"{row.get('target_multiple')}x",
            row.get("target_role"),
            row.get("n"),
            f"{_fmt(row.get('target_hit_rate'))}%",
            f"{_fmt(row.get('target_first_before_adverse_5pct_rate'))}%",
            f"{_fmt(row.get('failure_5pct_rate'))}%",
        ])
    return rows


def _branch_rows(stats: Mapping[str, Any]) -> list[list[Any]]:
    rows = [["Nhánh", "Vai trò", "Số mẫu", "Đạt 0,46x", "Đạt trước bật ngược", "Thất bại 5%", "MFE/MAE"]]
    for row in stats.get("bear_branch_table") or []:
        rows.append([
            row.get("branch_id"),
            _vi_lane(row.get("lane")),
            _fmt(row.get("n"), 0),
            f"{_fmt(row.get('base_target_hit_rate'))}%",
            f"{_fmt(row.get('base_target_first_before_adverse_5pct_rate'))}%",
            f"{_fmt(row.get('failure_5pct_rate'))}%",
            _fmt(row.get("mfe_mae_median_ratio")),
        ])
    return rows


def _headline_candidate_rows(stats: Mapping[str, Any]) -> list[list[Any]]:
    rows = [["Phạm vi chính", "Vai trò", "Số mẫu", "Đạt 0,46x", "Đạt trước bật ngược", "Thất bại 5%", "MFE/MAE"]]
    for row in stats.get("bear_branch_headline_candidates") or []:
        label = row.get("aggregate_id") or row.get("branch_id")
        if row.get("selected_headline"):
            label = f"{label} (được chọn)"
        rows.append([
            label,
            _vi_lane(row.get("lane")),
            _fmt(row.get("n"), 0),
            f"{_fmt(row.get('base_target_hit_rate'))}%",
            f"{_fmt(row.get('base_target_first_before_adverse_5pct_rate'))}%",
            f"{_fmt(row.get('failure_5pct_rate'))}%",
            _fmt(row.get("mfe_mae_median_ratio")),
        ])
    return rows


def _quantile_rows(events: pd.DataFrame) -> list[list[Any]]:
    specs = [
        ("Độ dài thân cờ", "pattern_width_bars", "phiên"),
        ("Chiều cao thân cờ", "pattern_height_pct", "%"),
        ("Cột cờ giảm trước mẫu", "pole_move_pct", "%"),
        ("Mục tiêu đầy đủ", "target_dist_pct", "%"),
        ("Mức giảm tốt nhất", "mfe_pct", "%"),
        ("Mức bật ngược sâu nhất", "mae_pct", "%"),
        ("Ngày chạm mục tiêu đầy đủ", "days_to_target", "phiên"),
    ]
    rows = [["Biến", "Q10", "Q25", "Q50", "Q75", "Q90", "Đơn vị"]]
    for label, col, unit in specs:
        series = pd.to_numeric(events.get(col), errors="coerce").dropna()
        if series.empty:
            continue
        rows.append([label, _fmt(series.quantile(0.10)), _fmt(series.quantile(0.25)), _fmt(series.quantile(0.50)), _fmt(series.quantile(0.75)), _fmt(series.quantile(0.90)), unit])
    return rows


def _group_rows(events: pd.DataFrame, group_col: str, title: str) -> list[list[Any]]:
    rows = [[title, "Số mẫu", "Đạt mục tiêu", "Đạt trước bật ngược", "Thất bại 5%", "Mức giảm tốt nhất", "Bật ngược sâu nhất"]]
    if group_col not in events.columns:
        return rows
    for key, group in events.groupby(group_col, dropna=False):
        rows.append([
            str(key),
            _fmt(len(group), 0),
            f"{_fmt(float(group['target_hit'].map(_bool).mean()*100))}%",
            f"{_fmt(float(group['target_first_before_adverse_5pct'].map(_bool).mean()*100))}%",
            f"{_fmt(float(group['failure_5pct'].map(_bool).mean()*100))}%",
            f"{_fmt(float(pd.to_numeric(group['mfe_pct'], errors='coerce').median()))}%",
            f"{_fmt(float(pd.to_numeric(group['mae_pct'], errors='coerce').median()))}%",
        ])
    return rows


def _post_rows(events: pd.DataFrame) -> list[list[Any]]:
    rows = [["Chỉ tiêu", "Giá trị", "Cách đọc"]]
    hits = events[events["target_hit"].map(_bool)]
    hit_days = pd.to_numeric(hits.get("days_to_target"), errors="coerce").dropna()
    rows.append(["Thời gian chạm mục tiêu đầy đủ", f"P50 {_fmt(float(hit_days.median()), 0) if not hit_days.empty else 'n/a'} phiên", "Chỉ tính mẫu đã chạm mục tiêu 1,0x."])
    if "throwback_to_breakout_30d" in events.columns:
        pb = events["throwback_to_breakout_30d"].map(_bool)
        days = pd.to_numeric(events.loc[pb, "days_to_throwback_to_breakout"], errors="coerce").dropna()
        rows.append(["Pullback về giá phá vỡ trong 30 phiên", f"{_fmt(float(pb.mean()*100))}% / ngày trung vị {_fmt(float(days.median()), 0) if not days.empty else 'n/a'}", "Giá giảm rồi hồi lại vùng phá vỡ; đây là rủi ro bật ngược cần theo dõi."])
    rows.append(["Mức giảm tốt nhất / bật ngược sâu nhất", f"{_fmt(float(events['mfe_pct'].median()))}% / {_fmt(float(events['mae_pct'].median()))}%", "So sánh quãng đi đúng hướng xuống với quãng bật ngược bất lợi."])
    if "busted_pattern_flag" in events.columns:
        busted = events["busted_pattern_flag"].map(_bool)
        rows.append(["Mẫu phá ngược", f"{_fmt(float(busted.mean()*100))}%", "Giá giảm chưa đủ 10% rồi phá ngược lên trên vùng thân cờ."])
    return rows


def _example_rows(event: Mapping[str, Any]) -> list[list[Any]]:
    return [
        ["Mốc đọc mẫu", "Dữ kiện", "Ý nghĩa"],
        ["Bắt đầu mẫu", event.get("formation_start_date"), "Sau nhịp giảm trước đó, giá bắt đầu hồi kỹ thuật trong thân cờ."],
        ["Kết thúc thân cờ", event.get("formation_end_date"), "Vùng hồi ngắn kết thúc; chờ xác nhận phá xuống."],
        ["Ngày xác nhận", event.get("breakout_date"), f"Giá phá vỡ {_fmt(event.get('breakout_price'))}; mục tiêu đầy đủ {_fmt(event.get('target_price'))}."],
        ["Đường đi sau đó", f"Mức giảm tốt nhất {_fmt(event.get('mfe_pct'))}%; bật ngược sâu nhất {_fmt(event.get('mae_pct'))}%.", "Cho biết rủi ro giảm tiếp và khả năng bật ngược."],
        ["Kết quả", f"Đạt mục tiêu: {'có' if _bool(event.get('target_hit')) else 'không'}; thất bại 5%: {'có' if _bool(event.get('failure_5pct')) else 'không'}.", "Ví dụ minh họa, không phải tín hiệu giao dịch."],
    ]


def _pct_bool(series: pd.Series) -> float:
    if series.empty:
        return float("nan")
    return float(series.map(_bool).mean() * 100.0)


def _base_target_hit_rate(group: pd.DataFrame, multiple: float = 0.46) -> float:
    if group.empty:
        return float("nan")
    mfe = pd.to_numeric(group["mfe_pct"], errors="coerce")
    target = pd.to_numeric(group["target_dist_pct"], errors="coerce") * multiple
    return float((mfe >= target).mean() * 100.0)


def _basic_group_stats(group: pd.DataFrame) -> list[str]:
    return [
        _fmt(len(group), 0),
        f"{_fmt(_base_target_hit_rate(group))}%",
        f"{_fmt(_pct_bool(group['target_hit']))}%",
        f"{_fmt(_pct_bool(group['target_first_before_adverse_5pct']))}%",
        f"{_fmt(_pct_bool(group['failure_5pct']))}%",
        f"{_fmt(float(pd.to_numeric(group['mfe_pct'], errors='coerce').median()))}%",
        f"{_fmt(float(pd.to_numeric(group['mae_pct'], errors='coerce').median()))}%",
    ]


def _skip_conditions_rows(events: pd.DataFrame) -> list[list[Any]]:
    width_q75 = float(pd.to_numeric(events["pattern_width_bars"], errors="coerce").quantile(0.75))
    height_q75 = float(pd.to_numeric(events["pattern_height_pct"], errors="coerce").quantile(0.75))
    mae_q75 = float(pd.to_numeric(events["mae_pct"], errors="coerce").quantile(0.75))
    gap_q75 = float(pd.to_numeric(events["breakout_gap_pct"], errors="coerce").abs().quantile(0.75))
    return [
        ["Tình huống", "Ngưỡng tham chiếu", "Lý do đọc thận trọng"],
        ["Thân cờ kéo dài", f"Trên Q75: {width_q75:.0f} phiên", "Cờ giảm là mẫu nghỉ ngắn; thân cờ quá dài dễ chuyển thành kênh hồi hoặc nền đi ngang, làm tín hiệu phá xuống kém sắc nét."],
        ["Thân cờ quá rộng", f"Trên Q75: {_fmt(height_q75)}%", "Biên dao động lớn nghĩa là lực bật ngược đã mạnh; mẫu mất tính chất hồi kỹ thuật gọn trong xu hướng giảm."],
        ["Khoảng nhảy giá lớn ở phá vỡ", f"Trên Q75: {_fmt(gap_q75)}%", "Gap có thể làm target-hit nhìn tốt hơn nhưng điểm đọc thực tế lại khó hơn, nhất là khi giá đã đi xa trước khi có thể hành động."],
        ["Đường giá kém sạch", "Thiếu phiên, đứng giá kéo dài hoặc thanh khoản rất thấp", "Time-to-target, pullback và MAE dễ bị méo nếu đường giá không giao dịch liên tục."],
        ["Bật ngược sâu sau phá vỡ", f"Trên Q75: {_fmt(mae_q75)}%", "Mẫu có thể vẫn giảm tiếp, nhưng đường đi không còn phù hợp với một cảnh báo phòng thủ gọn."],
    ]


def _best_conditions_rows(events: pd.DataFrame) -> list[list[Any]]:
    height_med = float(pd.to_numeric(events["pattern_height_pct"], errors="coerce").median())
    width_med = float(pd.to_numeric(events["pattern_width_bars"], errors="coerce").median())
    gap = pd.to_numeric(events["breakout_gap_pct"], errors="coerce").abs()
    pos = pd.to_numeric(events["yearly_range_position_pct"], errors="coerce")
    specs = [
        ("Thân cờ ngắn hơn trung vị", pd.to_numeric(events["pattern_width_bars"], errors="coerce") <= width_med, "Giữ đúng bản chất nhịp nghỉ ngắn sau một đoạn giảm mạnh."),
        ("Thân cờ rộng hơn trung vị", pd.to_numeric(events["pattern_height_pct"], errors="coerce") > height_med, "Cho biết mẫu có đủ biên đo, nhưng cũng cần kiểm tra bật ngược sâu nhất."),
        ("Phá vỡ không có gap quá lớn", gap <= 0.5, "Giảm nguy cơ target-hit chỉ đến từ một phiên nhảy giá khó khai thác."),
        ("Vùng thấp trong biên năm", pos < 33.33, "Phù hợp vai trò cảnh báo: cổ phiếu đã yếu sẵn và tiếp tục phá xuống."),
        ("Đường giá sạch", events["path_quality_bucket"].astype(str) == "clean", "Ít thiếu phiên và ít chuỗi đứng giá, phù hợp hơn để đọc đường đi hậu phá vỡ."),
        ("Nhóm VN30/VN100", events["market_group"].isin(["VN30", "VN100 ex VN30"]), "Ví dụ chương lấy từ nhóm này để tăng khả năng đọc và giảm nhiễu do mã quá nhỏ."),
    ]
    rows = [["Điều kiện", "Số mẫu", "Đạt 0,46x", "Đạt 1,0x", "Đạt trước bật ngược", "Thất bại 5%", "Cách đọc"]]
    for label, mask, note in specs:
        group = events[mask.fillna(False) if hasattr(mask, "fillna") else mask].copy()
        if group.empty:
            continue
        rows.append([label, *_basic_group_stats(group)[:5], note])
    return rows


def _size_volume_rows(events: pd.DataFrame) -> list[list[Any]]:
    rows = [["Nhóm", "Số mẫu", "Đạt 0,46x", "Đạt 1,0x", "Đạt trước bật ngược", "Thất bại 5%", "Mức giảm tốt nhất", "Bật ngược sâu nhất"]]
    width_med = float(pd.to_numeric(events["pattern_width_bars"], errors="coerce").median())
    height_med = float(pd.to_numeric(events["pattern_height_pct"], errors="coerce").median())
    specs = [
        (f"Thân cờ ngắn (≤ {width_med:.0f} phiên)", pd.to_numeric(events["pattern_width_bars"], errors="coerce") <= width_med),
        (f"Thân cờ dài (> {width_med:.0f} phiên)", pd.to_numeric(events["pattern_width_bars"], errors="coerce") > width_med),
        (f"Thân cờ thấp (≤ {_fmt(height_med)}%)", pd.to_numeric(events["pattern_height_pct"], errors="coerce") <= height_med),
        (f"Thân cờ cao (> {_fmt(height_med)}%)", pd.to_numeric(events["pattern_height_pct"], errors="coerce") > height_med),
        ("Khối lượng xác nhận", events["volume_confirmed"].map(_bool)),
        ("Không có xác nhận khối lượng", ~events["volume_confirmed"].map(_bool)),
    ]
    for label, mask in specs:
        group = events[mask.fillna(False)].copy()
        if group.empty:
            continue
        rows.append([label, *_basic_group_stats(group)])
    return rows


def _breakout_context_rows(events: pd.DataFrame) -> list[list[Any]]:
    rows = [["Nhóm", "Số mẫu", "Đạt 0,46x", "Đạt 1,0x", "Đạt trước bật ngược", "Thất bại 5%", "Mức giảm tốt nhất", "Bật ngược sâu nhất"]]
    specs: list[tuple[str, pd.Series]] = []
    for direction, label in [("down", "Khối lượng trong thân cờ giảm"), ("flat", "Khối lượng đi ngang"), ("up", "Khối lượng tăng")]:
        specs.append((label, events["volume_trend_direction"].astype(str) == direction))
    gap = pd.to_numeric(events["breakout_gap_pct"], errors="coerce").abs()
    specs.extend([("Phá vỡ có gap > 0,5%", gap > 0.5), ("Phá vỡ không có gap đáng kể", gap <= 0.5)])
    pos = pd.to_numeric(events["yearly_range_position_pct"], errors="coerce")
    specs.extend([("Vùng thấp trong biên năm", pos < 33.33), ("Vùng giữa trong biên năm", pos.between(33.33, 66.67)), ("Vùng cao trong biên năm", pos > 66.67)])
    for label, mask in specs:
        group = events[mask.fillna(False)].copy()
        if group.empty:
            continue
        rows.append([label, *_basic_group_stats(group)])
    return rows


def _stop_and_bust_rows(events: pd.DataFrame) -> list[list[Any]]:
    rows = [["Chỉ tiêu", "Giá trị", "Cách đọc"]]
    for stop in [5, 7, 10]:
        col = f"stop_hit_{stop}pct"
        day_col = f"days_to_stop_{stop}pct"
        if col not in events.columns:
            continue
        hit = events[col].map(_bool)
        days = pd.to_numeric(events.loc[hit, day_col], errors="coerce").dropna() if day_col in events.columns else pd.Series(dtype=float)
        rows.append([f"Bật ngược bất lợi {stop}%", f"{_fmt(float(hit.mean() * 100.0))}% / ngày trung vị {_fmt(float(days.median()), 0) if not days.empty else 'n/a'}", "Tần suất giá bật ngược đủ mạnh để làm suy yếu cảnh báo giảm sau phá vỡ."])
    if "busted_pattern_flag" in events.columns:
        busted = events["busted_pattern_flag"].map(_bool)
        days = pd.to_numeric(events.loc[busted, "days_to_bust"], errors="coerce").dropna() if "days_to_bust" in events.columns else pd.Series(dtype=float)
        rows.append(["Mẫu phá ngược", f"{_fmt(float(busted.mean() * 100.0))}% / ngày trung vị {_fmt(float(days.median()), 0) if not days.empty else 'n/a'}", "Giá giảm chưa đủ sâu rồi phá ngược lên trên vùng thân cờ trong cửa sổ đo."])
    return rows


def _data_quality_rows(events: pd.DataFrame) -> list[list[Any]]:
    rows = [["Lớp kiểm tra", "Kết quả", "Cách đọc"]]
    if "tradability_quality_bucket" in events.columns:
        counts = events["tradability_quality_bucket"].fillna("không rõ").astype(str).value_counts().to_dict()
        score = pd.to_numeric(events.get("tradability_quality_score"), errors="coerce").median()
        label = " / ".join(f"{key}: {value}" for key, value in sorted(counts.items()))
        rows.append(["Chất lượng giao dịch", f"điểm trung vị {_fmt(float(score))}; {label}", "Tổng hợp thiếu phiên, phiên không có khối lượng, chuỗi giá đứng yên, dấu hiệu biên độ giá và sự kiện quyền quanh mẫu."])
    if "corp_action_near_breakout_flag" in events.columns:
        rows.append(["Sự kiện quyền gần phá vỡ", f"{_fmt(_pct_bool(events['corp_action_near_breakout_flag']))}%", "Nhóm này cần đọc thận trọng vì hình thái và hậu quả sau phá vỡ có thể chịu tác động điều chỉnh giá."])
    if "corp_action_in_forward_window_flag" in events.columns:
        rows.append(["Sự kiện quyền sau phá vỡ", f"{_fmt(_pct_bool(events['corp_action_in_forward_window_flag']))}%", "Có thể ảnh hưởng MFE/MAE và thời gian chạm mục tiêu nếu chuỗi điều chỉnh không đồng nhất."])
    if "price_limit_proxy_rate_60d" in events.columns:
        rows.append(["Dấu hiệu biên độ giá", f"trung vị {_fmt(float(pd.to_numeric(events['price_limit_proxy_rate_60d'], errors='coerce').median()))}% phiên", "Proxy cho các đường đi bị chi phối bởi biên độ dao động hoặc phiên biến động bất thường."])
    if "missing_bar_rate_60d" in events.columns:
        rows.append(["Thiếu dữ liệu hậu phá vỡ", f"trung vị {_fmt(float(pd.to_numeric(events['missing_bar_rate_60d'], errors='coerce').median()))}%", "Nếu thiếu phiên, time-to-target và pullback phải đọc như ước lượng có điều kiện."])
    return rows


def _general_statistics_rows(events: pd.DataFrame, stats: Mapping[str, Any]) -> list[list[Any]]:
    return [
        ["Chỉ tiêu", "Giá trị", "Ý nghĩa"],
        ["Số mẫu / số mã", f"{_fmt(stats.get('detection_count'), 0)} / {_fmt(events['symbol'].nunique(), 0)}", "Cỡ mẫu đủ để viết một chương phòng thủ, nhưng chưa đủ để xem là pattern cốt lõi mạnh như Bull Flag."],
        ["Độ dài thân cờ", f"P25 {events['pattern_width_bars'].quantile(0.25):.0f} / P50 {events['pattern_width_bars'].median():.0f} / P75 {events['pattern_width_bars'].quantile(0.75):.0f} phiên", "Cờ giảm là mẫu ngắn; thân cờ dài dễ trở thành kênh hồi."],
        ["Chiều cao thân cờ", f"P25 {_fmt(float(events['pattern_height_pct'].quantile(0.25)))}% / P50 {_fmt(float(events['pattern_height_pct'].median()))}% / P75 {_fmt(float(events['pattern_height_pct'].quantile(0.75)))}%", "Thân cờ rộng cho thấy lực bật ngược đáng kể trước phá vỡ."],
        ["Cột cờ trước mẫu", f"P50 {_fmt(float(events['pole_move_pct'].median()))}%", "Nhịp giảm trước mẫu là cơ sở của target family."],
        ["Tỷ lệ cờ/cột cờ", f"P50 {_fmt(float(events['flag_to_pole_pct'].median()))}%", "Nếu thân cờ quá lớn so với cột cờ, mẫu mất tính tiếp diễn ngắn."],
    ]


def _quick_conclusion_rows(stats: Mapping[str, Any], events: pd.DataFrame) -> list[list[Any]]:
    base = _target_row(stats, 0.46)
    legacy = _target_row(stats, 1.0)
    branch = stats.get("bear_branch_headline") if isinstance(stats.get("bear_branch_headline"), Mapping) else {}
    return [
        ["Câu hỏi", "Câu trả lời trong dữ liệu hiện có"],
        ["Mẫu này dùng để đọc gì?", "Một cảnh báo phòng thủ sau nhịp giảm mạnh: giá hồi ngắn rồi phá xuống, nhưng không phải một setup bán khống mặc định."],
        ["Mục tiêu nào nên là mốc chính?", f"Với toàn mẫu là 0,46x đạt {_fmt(base.get('target_hit_rate'))}%; với headline branch là {_fmt(branch.get('base_target_hit_rate'))}%."],
        ["Mốc 1,0 lần có vai trò gì?", f"Mốc đầy đủ để tham chiếu; tỷ lệ đạt {_fmt(legacy.get('target_hit_rate'))}%, thấp hơn nhiều so với mục tiêu cơ sở."],
        ["Rủi ro chính là gì?", f"Thất bại 5% ở {_fmt(stats.get('failure_5pct_rate'))}% và bật ngược sâu nhất trung vị {_fmt(float(events['mae_pct'].median()))}%."],
        ["Khi nào mẫu đáng chú ý hơn?", "Khi cột cờ giảm rõ, thân cờ ngắn, phá vỡ đóng cửa dứt khoát, đường giá sạch và bối cảnh thị trường không chống lại tín hiệu giảm."],
        ["Khi nào nên đọc thận trọng hơn?", "Khi thân cờ kéo dài, gap phá vỡ quá lớn, thanh khoản mỏng, sự kiện quyền gần mẫu hoặc cổ phiếu bật ngược sâu ngay sau phá vỡ."],
    ]


def build_content_parity_audit(out_dir: Path) -> tuple[Path, Path]:
    rows = [
        ("Kết quả quan trọng", "Đã bổ sung sâu", "Mở chương bằng snapshot số liệu, phân loại defensive và target family."),
        ("Tour mẫu hình", "Đã bổ sung", "Giải thích cột cờ giảm, thân cờ hồi ngắn, xác nhận phá xuống và lý do không đọc như short setup."),
        ("Cách nhận diện", "Đã có", "Bảng quy tắc có provenance từ chương Flags."),
        ("Điều kiện đọc thận trọng", "Đã bổ sung", "Có bảng thân cờ dài/rộng, gap lớn, đường giá kém sạch và bật ngược sâu."),
        ("Focus on failures", "Đã bổ sung sâu", "Có failure 5%, ví dụ thất bại, target-first và mẫu phá ngược."),
        ("Mục tiêu giá", "Đã bổ sung", "Có target family 0,46x/0,5x/0,75x/1,0x và cách đọc từng mốc."),
        ("Thống kê tổng quát", "Đã bổ sung", "Có số mẫu, số mã, độ dài, chiều cao, cột cờ và tỷ lệ cờ/cột cờ."),
        ("Vùng phân bố kết quả", "Đã có", "Có Q10/Q25/Q50/Q75/Q90 cho biến chính."),
        ("Hành vi sau phá vỡ", "Đã bổ sung sâu", "Có mục tiêu, pullback, mức giảm tốt nhất, bật ngược sâu nhất, stop proxy và busted pattern."),
        ("Kích thước và khối lượng", "Đã bổ sung", "Có độ dài, chiều cao, cột cờ, khối lượng, gap, vị trí năm và thanh khoản."),
        ("For best performance", "Đã Việt hóa", "Thêm mục 'Khi mẫu đáng chú ý hơn' nhưng giữ nhãn phòng thủ/thông tin."),
        ("Phụ lục bối cảnh", "Đã bổ sung", "Tách riêng size/volume, breakout context, regime, liquidity, group và data quality."),
        ("Tóm tắt thực hành", "Đã bổ sung", "Có bảng kết luận cuối chương và checklist phòng thủ."),
    ]
    audit = {"purpose": "Audit nội bộ độ phủ nội dung chương Bear Flag.", "status": [{"source_section": a, "coverage": b, "implementation_note": c} for a, b, c in rows]}
    json_path = out_dir / "bear_flag_content_parity_audit.json"
    md_path = out_dir / "bear_flag_content_parity_audit.md"
    json_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text("\n".join(["# Audit độ phủ nội dung chương Bear Flag", "", "| Mục nội dung | Trạng thái | Ghi chú |", "|---|---|---|", *[f"| {a} | {b} | {c} |" for a, b, c in rows]]) + "\n", encoding="utf-8")
    return json_path, md_path


def _header_footer(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    canvas.setFont(_FONT_REGULAR, 7)
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawString(doc.leftMargin, 1.0 * cm, "Cờ giảm - bản chương xuất bản")
    canvas.drawRightString(A4[0] - doc.rightMargin, 1.0 * cm, f"Trang {doc.page}")
    canvas.restoreState()


def _build_story(stats: Mapping[str, Any], source_notes: Mapping[str, Any], events: pd.DataFrame, charts: Mapping[str, Path]) -> list[Any]:
    base = _target_row(stats, 0.46)
    branch = stats.get("bear_branch_headline") if isinstance(stats.get("bear_branch_headline"), Mapping) else {}
    story: list[Any] = []
    story.append(Paragraph("CHƯƠNG MẪU HÌNH GIÁ", _STYLES["Deck"]))
    story.append(Paragraph("Cờ giảm", _STYLES["Title"]))
    story.append(Paragraph("Mẫu tiếp diễn xuống dùng như tài liệu cảnh báo rủi ro", _STYLES["Subtitle"]))
    cards = [
        _metric_card("Số mẫu", _fmt(stats.get("detection_count"), 0), "mẫu đã kiểm tra"),
        _metric_card("Nhánh chính", _fmt(branch.get("n"), 0), "mẫu phòng thủ"),
        _metric_card("Tỷ lệ đạt", f"{_fmt(branch.get('base_target_hit_rate'))}%", "mục tiêu 0,46x"),
        _metric_card("Thất bại nhánh", f"{_fmt(branch.get('failure_5pct_rate'))}%", "không giảm đủ 5%"),
    ]
    table = Table([cards], colWidths=[4.0 * cm] * 4, hAlign="CENTER")
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0ece3")), ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d8d0c2")), ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d8d0c2")), ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9)]))
    story.append(table)
    story.append(Spacer(1, 0.35 * cm))
    story.append(Paragraph("Kết quả quan trọng", _STYLES["H1"]))
    story.append(_table(_summary_rows(stats, events), [4.0 * cm, 12.3 * cm]))
    story.append(_callout("Điểm cần nhớ", _important_findings(stats, events)))
    story.append(_p("Cờ giảm trong dữ liệu Việt Nam không nên được đọc như một cơ hội bán khống mặc định. Giá trị chính của chương này là nhận diện tình huống rủi ro: sau một nhịp giảm mạnh, cổ phiếu hồi ngắn trong thân cờ rồi phá xuống. Nếu mẫu tiếp diễn, nhà đầu tư đang nắm giữ cổ phiếu cần hiểu xác suất giảm tiếp, mức bật ngược và khả năng thất bại.", _STYLES["Body"]))
    story.append(_p("Chương này giữ cùng cấu trúc đọc với cờ tăng: trước hết mô tả hình học mẫu, sau đó đo kết quả hậu phá vỡ, rồi mới nói cách sử dụng. Khác biệt nằm ở vai trò: cờ giảm là bản đồ phòng thủ, không phải một tín hiệu bán khống mặc định trên cổ phiếu cơ sở.", _STYLES["Body"]))
    story.append(_image(charts["schematic"], 16.2))
    story.append(_p("Sơ đồ minh họa cấu trúc: cột cờ giảm, thân cờ hồi ngắn, phiên phá vỡ xuống và mục tiêu cơ sở. Các ví dụ thực tế ưu tiên VN100/VN30.", _STYLES["Caption"]))

    story.append(_section_title("1", "Mẫu hình hoạt động ra sao", "Cờ giảm là nhịp nghỉ ngắn trong một xu hướng giảm"))
    story.append(_p("Mẫu bắt đầu bằng một cột cờ giảm nhanh. Sau đó giá hồi hoặc đi ngang trong một kênh ngắn, thường nghiêng lên nhẹ. Sự kiện chỉ được xác nhận khi giá đóng cửa phá xuống dưới biên dưới của thân cờ. Kết quả sau phá vỡ được đo riêng, không dùng để hợp thức hóa lại hình vẽ.", _STYLES["Body"]))
    story.append(_p("Một lỗi phổ biến là xem mọi đoạn hồi sau giảm là cờ giảm. Cách đọc chặt hơn là hỏi liệu nhịp hồi có đủ ngắn, đủ hẹp và đủ giống một đoạn nghỉ hay không. Nếu thân cờ quá dài, quá rộng hoặc thiếu cột cờ giảm rõ phía trước, mẫu nên bị hạ cấp thành kênh hồi hoặc vùng dao động, không được đưa vào nhóm cờ giảm chuẩn.", _STYLES["Body"]))
    story.append(_table([["Bước đọc", "Câu hỏi"], ["Cột cờ", "Nhịp giảm trước đó có đủ nhanh và rõ không?"], ["Thân cờ", "Giá có hồi ngắn trong hai đường biên gần song song không?"], ["Phá vỡ", "Giá đóng cửa có phá xuống dưới thân cờ không?"], ["Sau phá vỡ", "Giá giảm tiếp hay bật ngược đủ mạnh để phủ nhận cảnh báo?" ]], [4.0 * cm, 12.3 * cm]))
    story.append(Paragraph("Nhánh đọc chính", _STYLES["H2"]))
    story.append(_p("Sau kiểm tra dữ liệu, chương không dùng một con số toàn mẫu làm kết luận chính cho mọi cờ giảm. Nhánh chính được chọn từ các điều kiện biết trước tại thời điểm phá vỡ: thanh khoản, khoảng nhảy giá, vị trí trong biên năm, lực nến phá vỡ và nhóm cổ phiếu. Bảng audit chi tiết được chuyển xuống phụ lục để phần đọc chính không biến thành báo cáo vận hành.", _STYLES["Body"]))
    story.append(_table([["Lớp đọc", "Cách dùng"], ["Toàn mẫu", "Giữ trong atlas để biết bức tranh rủi ro rộng."], ["Nhánh chính", f"{_headline_scope_id(branch)}: {_fmt(branch.get('n'), 0)} mẫu; đạt 0,46x {_fmt(branch.get('base_target_hit_rate'))}%; thất bại {_fmt(branch.get('failure_5pct_rate'))}%."], ["Phụ lục branch", "Dùng để audit scanner, không phải phần diễn giải đầu tiên cho nhà đầu tư."]], [4.0 * cm, 12.3 * cm]))
    story.append(Paragraph("Cách nhận diện", _STYLES["H2"]))
    story.append(_table(_rule_rows(source_notes), [5.2 * cm, 11.1 * cm]))
    story.append(_table([["Thành phần", "Ý nghĩa thực tế", "Tham số hiện tại"], ["Cột cờ giảm", "Nhịp giảm nhanh trước vùng hồi; đây là nguồn gốc của target family.", "Nhìn lại 40 phiên; giảm tối thiểu theo rule detector; độ dốc âm rõ."], ["Thân cờ hồi", "Vùng nghỉ ngắn, thường hồi lên hoặc đi ngang sau cú giảm.", "Dài 5-25 phiên; biên độ được giới hạn so với cột cờ."], ["Hai đường biên", "Giá nằm trong kênh tương đối song song.", "Sai lệch độ dốc bị giới hạn để tránh bắt nhầm kênh rộng."], ["Phá vỡ", "Chỉ sau phiên xác nhận mới đo outcome.", "Đóng cửa phá xuống dưới biên dưới; không dùng giá tương lai để xác nhận."], ["Khối lượng", "Khối lượng là bối cảnh hỗ trợ, không phải cổng loại tuyệt đối.", "Ghi nhận breakout volume và xu hướng volume trong thân cờ."]], [3.0 * cm, 7.0 * cm, 6.3 * cm]))
    story.append(_callout("Điểm loại nhanh", ["Không có cột cờ giảm rõ: mẫu chỉ là nhiễu hoặc kênh giảm chậm.", "Thân cờ hồi quá dài: mẫu không còn là nhịp nghỉ ngắn.", "Phá vỡ không bằng giá đóng cửa: xuyên biên trong phiên nhưng đóng cửa yếu chưa đủ xác nhận.", "Đường giá kém sạch: thiếu phiên, thanh khoản mỏng hoặc sự kiện quyền gần phá vỡ khiến outcome khó đọc."]))
    story.append(Paragraph("Khi nên đọc thận trọng", _STYLES["H2"]))
    story.append(_table(_skip_conditions_rows(events), [4.0 * cm, 3.5 * cm, 8.8 * cm]))

    story.append(Paragraph("Ví dụ minh họa", _STYLES["H1"]))
    story.append(_p("Ba ví dụ dưới đây không được chọn để làm đẹp chương. Chúng đại diện cho một mẫu cảnh báo đúng, một mẫu trung vị và một mẫu thất bại. Cách chọn này giữ tinh thần của một tài liệu tham khảo: người đọc cần thấy cả mặt đúng lẫn mặt sai.", _STYLES["Body"]))
    story.append(_p("Với cờ giảm, ví dụ thất bại quan trọng ngang ví dụ thành công. Nếu chỉ nhìn những mẫu đi thẳng xuống sau phá vỡ, người đọc sẽ đánh giá quá cao sức mạnh của mẫu. Chương này cố ý đặt ví dụ trung vị và thất bại cạnh ví dụ đẹp để mô tả phân phối thật, không dựng một câu chuyện một chiều.", _STYLES["Body"]))
    examples = _select_examples(events)
    for key, title in [("textbook_success", "Ví dụ cảnh báo đúng"), ("middle_case", "Ví dụ trung vị"), ("failure", "Ví dụ thất bại")]:
        story.append(Paragraph(title, _STYLES["H2"]))
        story.append(_image(charts[key], 16.1))
        event = examples[key]
        story.append(_p(f"{event['symbol']} ngày {event['breakout_date']}: mức giảm tốt nhất {_fmt(event['mfe_pct'])}%, bật ngược sâu nhất {_fmt(event['mae_pct'])}%, đạt mục tiêu {'có' if _bool(event['target_hit']) else 'không'}.", _STYLES["Caption"]))
    story.append(Paragraph("Diễn biến mẫu hoàn chỉnh", _STYLES["H2"]))
    story.append(_table(_example_rows(examples["textbook_success"]), [3.5 * cm, 5.1 * cm, 7.7 * cm]))
    story.append(_p("Bảng diễn biến này thay cho kiểu 'giao dịch mẫu'. Nó dẫn người đọc qua các mốc hình thành và phá vỡ, nhưng không biến ví dụ thành một lệnh bán cụ thể. Với cổ phiếu cơ sở Việt Nam, ranh giới này đặc biệt quan trọng.", _STYLES["Body"]))

    story.append(PageBreak())
    story.append(Paragraph("Tập trung vào thất bại", _STYLES["H1"]))
    story.append(_p("Với cờ giảm, thất bại có hai lớp: giá không giảm đủ 5% theo hướng phá vỡ, hoặc giá giảm một đoạn rồi bật ngược quá mạnh. Vì nhà đầu tư cơ sở thường không triển khai short trực tiếp, lớp thất bại này nên được đọc như rủi ro cảnh báo sai hoặc cảnh báo đến quá muộn.", _STYLES["Body"]))
    story.append(_p("Điểm cần đọc không phải chỉ là 'có giảm tiếp không'. Câu hỏi thực dụng hơn là giá có giảm đủ nhanh và đủ xa trước khi bật ngược gây nhiễu hay không. Do đó target-first-before-adverse được đặt cạnh target-hit: nó giữ lại thứ tự đường đi, thứ mà một tỷ lệ hit cuối kỳ không thể hiện được.", _STYLES["Body"]))
    story.append(_table([["Dạng thất bại", "Dấu hiệu trong dữ liệu", "Cách xử lý khi đọc chương"], ["Không đi đủ 5%", f"{_fmt(stats.get('failure_5pct_rate'))}% mẫu không đạt ngưỡng giảm tối thiểu.", "Không xem hình thái hợp lệ là đủ; phải kiểm tra hậu quả sau phá vỡ."], ["Bật ngược sâu trước mục tiêu", f"Mức bật ngược sâu nhất trung vị {_fmt(stats.get('median_mae_pct'))}%.", "Nếu bật ngược lớn hơn quãng giảm thuận lợi, cảnh báo phòng thủ yếu đi."], ["Mục tiêu quá tham", "Mốc 1,0x đạt thấp hơn nhiều so với 0,46x.", "Không dùng full pole-height làm kỳ vọng chính cho Việt Nam."], ["Mẫu phá ngược", "Được đo bằng busted pattern và các ngưỡng stop proxy.", "Giúp phân biệt mẫu chậm với mẫu bị phủ nhận."]], [4.1 * cm, 5.6 * cm, 6.6 * cm]))
    story.append(_callout("Quy tắc đọc thất bại", ["Ví dụ thất bại không bị loại khỏi chương; nó là một phần của phân phối thật.", "Thất bại 5% khác stop-loss thực chiến: nó đo việc không giảm đủ, không đo PnL.", "Cờ giảm hợp lệ vẫn có thể là cảnh báo sai nếu giá bật ngược nhanh sau phá vỡ."]))

    story.append(Paragraph("Mục tiêu giá", _STYLES["H2"]))
    story.append(_p("Mục tiêu giá của cờ giảm không nên bị ép vào 1,0 lần chiều cao cột cờ. Theo tinh thần Bulkowski, measure rule nên được đọc cùng tỷ lệ đạt thực nghiệm. Vì vậy chương này giữ 1,0x làm mốc đầy đủ để đối chiếu, nhưng đặt 0,46x làm mục tiêu cơ sở cho việc đọc dữ liệu Việt Nam.", _STYLES["Body"]))
    story.append(_table(_target_rows(stats), [1.7 * cm, 4.2 * cm, 1.6 * cm, 2.5 * cm, 3.0 * cm, 2.3 * cm]))
    story.append(_p("Cách đọc đúng là theo thang mục tiêu. Nếu 0,46x cũng thất bại, mẫu cảnh báo yếu. Nếu 0,46x đạt nhưng 1,0x không đạt, mẫu vẫn có giá trị phòng thủ nhưng không đủ mạnh để nói về một nhịp giảm dài. Nếu 1,0x đạt, đó là nhóm chạy xa, nên được xem như tail thuận lợi chứ không phải kỳ vọng mặc định.", _STYLES["Body"]))

    story.append(Paragraph("Hành vi sau phá vỡ", _STYLES["H2"]))
    story.append(_p("Sau phá vỡ, cờ giảm phải được đọc bằng đường đi chứ không chỉ bằng cực trị. Một mẫu có thể chạm mục tiêu nhưng trước đó đã bật ngược sâu; một mẫu khác có thể không chạm 1,0x nhưng vẫn đưa ra cảnh báo hữu ích vì giảm đủ nhanh ở mục tiêu cơ sở. Vì vậy bảng này tách thời gian chạm mục tiêu, pullback, MFE/MAE và mẫu phá ngược.", _STYLES["Body"]))
    story.append(_table(_post_rows(events), [4.5 * cm, 4.2 * cm, 7.6 * cm]))
    story.append(Paragraph("Khi giá bật ngược và phá hỏng mẫu", _STYLES["H2"]))
    story.append(_table(_stop_and_bust_rows(events), [4.4 * cm, 4.6 * cm, 7.3 * cm]))

    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("Cách đọc kết quả quan trọng", _STYLES["H1"]))
    story.append(_p("Một chương mẫu hình tốt không bắt người đọc tự bơi trong bảng số. Với cờ giảm, bốn con số cần nhớ là mục tiêu cơ sở 0,46x, mốc đầy đủ 1,0x, thất bại 5% và mức bật ngược sâu nhất. Bốn con số này trả lời bốn câu hỏi khác nhau: mẫu thường giảm được bao xa, mốc căng có thực tế không, mẫu sai bao nhiêu và đường đi có gây nhiễu không.", _STYLES["Body"]))
    story.append(_table([["Câu hỏi của người đọc", "Con số cần nhìn", "Cách đọc thực tế"], ["Mẫu có cảnh báo được rủi ro giảm không?", f"0,46x đạt {_fmt(base.get('target_hit_rate'))}%", "Mốc cơ sở cho biết nhịp giảm vừa phải có xuất hiện hay không."], ["Mốc đầy đủ có nên là kỳ vọng chính?", f"1,0x đạt {_fmt(_target_row(stats, 1.0).get('target_hit_rate'))}%", "Không. Đây là mốc tail để biết mẫu chạy xa tới đâu khi rất thuận lợi."], ["Đường đi có gọn không?", f"Bật ngược sâu nhất trung vị {_fmt(stats.get('median_mae_pct'))}%", "Nếu MAE lớn hơn MFE, mẫu nghiêng về cảnh báo yếu hoặc nhiễu."], ["Mẫu sai bao nhiêu?", f"Thất bại 5% {_fmt(stats.get('failure_5pct_rate'))}%", "Đây là lý do phải có ví dụ thất bại và không chỉ chọn biểu đồ đẹp."]], [4.2 * cm, 4.2 * cm, 7.9 * cm]))

    story.append(Paragraph("Vùng thường gặp và vùng cực trị", _STYLES["H1"]))
    story.append(_p("Bảng phân vị giúp tránh đọc quá tay từ một vài ví dụ mạnh. Cờ giảm hiện có phân phối bất lợi: mức bật ngược sâu nhất trung vị lớn hơn mức giảm tốt nhất trung vị, nên chương giữ phân loại phòng thủ/thông tin.", _STYLES["Body"]))
    story.append(_table(_quantile_rows(events), [4.3 * cm, 1.6 * cm, 1.6 * cm, 1.6 * cm, 1.6 * cm, 1.6 * cm, 1.8 * cm]))
    story.append(Paragraph("Bức tranh tổng quát", _STYLES["H2"]))
    story.append(_table(_general_statistics_rows(events, stats), [4.1 * cm, 5.2 * cm, 7.0 * cm]))
    story.append(Paragraph("Kích thước và khối lượng", _STYLES["H2"]))
    story.append(_p("Cờ giảm là mẫu hình nhạy với kích thước thân cờ và khối lượng. Thân cờ càng rộng, nguy cơ bật ngược càng lớn; khối lượng không xác nhận có thể làm phiên phá vỡ kém tin cậy. Các bảng dưới đây không dùng để chọn lại mẫu sau khi biết kết quả, mà để mô tả nơi mẫu dễ đọc hơn hoặc khó đọc hơn.", _STYLES["Body"]))
    story.append(_table(_size_volume_rows(events), [4.3 * cm, 1.25 * cm, 1.65 * cm, 1.65 * cm, 2.05 * cm, 1.8 * cm, 1.8 * cm, 1.8 * cm]))
    story.append(Paragraph("Phá vỡ, khối lượng và vị trí trong năm", _STYLES["H2"]))
    story.append(_table(_breakout_context_rows(events), [4.3 * cm, 1.25 * cm, 1.65 * cm, 1.65 * cm, 2.05 * cm, 1.8 * cm, 1.8 * cm, 1.8 * cm]))

    story.append(PageBreak())
    story.append(Paragraph("Bối cảnh thị trường", _STYLES["H1"]))
    story.append(_p("Các lát cắt không dùng để chọn lại mẫu sau khi biết kết quả. Chúng cho biết cờ giảm nhạy với thanh khoản, regime và chất lượng đường giá như thế nào.", _STYLES["Body"]))
    story.append(_p("Với cờ giảm, bối cảnh quan trọng hơn ở cờ tăng vì vai trò của mẫu là cảnh báo. Một phá vỡ xuống trong nhóm thanh khoản thấp có thể nhìn rất mạnh trên chart nhưng khó dùng làm thông tin đáng tin nếu đường giá thiếu liên tục. Ngược lại, một phá vỡ xuống ở cổ phiếu thanh khoản cao có thể không tạo ra target-hit lớn nhưng vẫn có giá trị quản trị rủi ro vì nó đến từ một chuỗi giá đọc được hơn.", _STYLES["Body"]))
    story.append(Paragraph("Theo thanh khoản", _STYLES["H2"]))
    story.append(_table(_group_rows(events, "liquidity_bucket", "Thanh khoản"), [3.2 * cm, 1.5 * cm, 2.1 * cm, 2.4 * cm, 2.0 * cm, 2.1 * cm, 2.1 * cm]))
    story.append(Paragraph("Theo regime", _STYLES["H2"]))
    story.append(_table(_group_rows(events, "market_regime", "Regime"), [3.2 * cm, 1.5 * cm, 2.1 * cm, 2.4 * cm, 2.0 * cm, 2.1 * cm, 2.1 * cm]))
    story.append(Paragraph("Theo nhóm cổ phiếu", _STYLES["H2"]))
    story.append(_table(_group_rows(events, "market_group", "Nhóm"), [3.2 * cm, 1.5 * cm, 2.1 * cm, 2.4 * cm, 2.0 * cm, 2.1 * cm, 2.1 * cm]))
    story.append(Paragraph("Khi mẫu đáng chú ý hơn", _STYLES["H2"]))
    story.append(_p("Các điều kiện dưới đây không phải bộ lọc để tối ưu kết quả. Chúng là cách đọc ưu tiên khi nhà đầu tư gặp một mẫu cờ giảm trên chart: ưu tiên mẫu gọn, có cột cờ rõ, phá vỡ không bị gap quá đà và có đường giá đủ sạch để phân biệt giảm tiếp với bật ngược nhiễu.", _STYLES["Body"]))
    story.append(_table(_best_conditions_rows(events), [4.0 * cm, 1.25 * cm, 1.65 * cm, 1.65 * cm, 2.1 * cm, 1.7 * cm, 4.0 * cm]))

    story.append(PageBreak())
    story.append(Paragraph("Cách sử dụng thực tế", _STYLES["H1"]))
    story.append(_p("Cách dùng phù hợp nhất là phòng thủ: giảm tự tin với vị thế đang nắm giữ, kiểm tra lại luận điểm đầu tư, hoặc theo dõi rủi ro thủng vùng hỗ trợ. Không nên viết chương này như một hệ thống bán khống vì dữ liệu hiện tại không chứng minh được lớp thực thi short trên cổ phiếu cơ sở Việt Nam.", _STYLES["Body"]))
    story.append(_p("Nếu đang nắm giữ cổ phiếu, cờ giảm hợp lệ đặt ra một câu hỏi quản trị rủi ro: luận điểm mua còn đủ mạnh để chịu một phá vỡ xuống hay không. Nếu chưa nắm giữ, mẫu có thể giúp tránh mua đuổi trong một nhịp hồi yếu. Hai cách dùng này phù hợp hơn nhiều so với việc biến cờ giảm thành một lệnh bán khống trực tiếp.", _STYLES["Body"]))
    story.append(_callout("Checklist đọc mẫu", ["Có cột cờ giảm đủ rõ trước thân cờ.", "Thân cờ hồi ngắn, không quá rộng và không kéo dài.", "Chỉ xác nhận khi giá đóng cửa phá xuống.", "Đọc 0,46x-0,5x là mục tiêu cơ sở; 1,0x là mốc căng.", "Luôn kiểm tra bật ngược sâu nhất, pullback và thất bại 5%.", "Không diễn giải thành khuyến nghị bán khống nếu chưa có lớp thực thi riêng."]))
    story.append(Paragraph("Tóm tắt thực hành", _STYLES["H2"]))
    story.append(_table(_quick_conclusion_rows(stats, events), [4.0 * cm, 12.3 * cm]))
    story.append(_callout("Kết luận chương", ["Cờ giảm là tài liệu phòng thủ/thông tin: hữu ích để đọc rủi ro sau một nhịp hồi yếu.", "Mục tiêu cơ sở nên là 0,46x-0,50x chiều cao cột cờ; 1,00x chỉ là mốc chạy xa.", "Chương không được đọc như khuyến nghị bán khống trên cổ phiếu cơ sở Việt Nam.", "Chất lượng mẫu nằm ở ba lớp: setup giảm rõ, xác nhận phá xuống, và follow-through không bật ngược quá sâu."]))

    story.append(PageBreak())
    story.append(Paragraph("Phụ lục kỹ thuật", _STYLES["H1"]))
    story.append(_p("Phạm vi hiện tại là dữ liệu active-series có trong Market Stats. Chương không claim point-in-time universe toàn thị trường, không claim historical VN30/VN100 membership đầy đủ, và không dùng kết quả này làm lời khuyên giao dịch cá nhân.", _STYLES["Body"]))
    story.append(_table([["Cổng dữ liệu", "Trạng thái"], ["Nguồn quy tắc", "Đã có provenance từ chương Flags"], ["Dữ liệu sự kiện", "Có events.csv và post_breakout_path.csv"], ["Corporate actions", "Dùng proxy audit, chưa có factor log chính thức"], ["Delisted/halted", "Dùng active-series scope, không claim toàn lịch sử"], ["Diễn giải", "Defensive/informational reference"]], [5.0 * cm, 11.3 * cm]))
    story.append(Paragraph("Chất lượng dữ liệu", _STYLES["H2"]))
    story.append(_table(_data_quality_rows(events), [4.2 * cm, 4.8 * cm, 7.3 * cm]))
    story.append(Paragraph("Audit nhánh scanner", _STYLES["H2"]))
    story.append(_p("Các bảng dưới đây được giữ ở phụ lục vì chúng phục vụ kiểm tra scanner, không phải phần đọc chính của chương. Chúng cho thấy cách nhánh chính được chọn từ các điều kiện biết trước tại thời điểm phá vỡ, rồi mới đo kết quả sau đó.", _STYLES["Body"]))
    story.append(_table(_headline_candidate_rows(stats), [4.0 * cm, 2.4 * cm, 1.25 * cm, 1.7 * cm, 2.1 * cm, 1.7 * cm, 1.4 * cm]))
    story.append(_table(_branch_rows(stats), [4.0 * cm, 2.4 * cm, 1.25 * cm, 1.7 * cm, 2.1 * cm, 1.7 * cm, 1.4 * cm]))
    story.append(Paragraph("Giới hạn phải ghi rõ", _STYLES["H2"]))
    story.append(_p("Các giới hạn này không làm chương vô dụng; chúng quyết định nhãn sử dụng. Trong phạm vi dữ liệu hiện có, cờ giảm đã đủ để làm tài liệu phòng thủ/thông tin. Để nâng lên cấp investment-reference mạnh hơn, cần có lịch sử trạng thái niêm yết/hủy niêm yết và factor log corporate actions chính thức hơn.", _STYLES["Body"]))
    story.append(_callout("Giới hạn dữ liệu", ["Không claim point-in-time universe toàn thị trường.", "Không dùng historical VN30/VN100 membership làm kết luận chính.", "Corporate actions và delisted/halted hiện là proxy audit, chưa phải status tape chính thức.", "Kết quả bearish không được diễn giải như khả năng short single-stock đại trà."]))
    story.append(Paragraph("Phụ lục bối cảnh", _STYLES["H1"]))
    story.append(_p("Phụ lục này giữ lại các lát cắt để người đọc kiểm tra độ ổn định của kết quả theo thanh khoản, regime, nhóm cổ phiếu và chất lượng đường giá. Đây là phần giúp chương tránh trở thành một câu chuyện dựa trên vài ví dụ riêng lẻ.", _STYLES["Body"]))
    story.append(Paragraph("Theo chất lượng đường giá", _STYLES["H2"]))
    story.append(_table(_group_rows(events, "path_quality_bucket", "Đường giá"), [3.2 * cm, 1.5 * cm, 2.1 * cm, 2.4 * cm, 2.0 * cm, 2.1 * cm, 2.1 * cm]))
    story.append(Paragraph("Theo khả năng giao dịch", _STYLES["H2"]))
    story.append(_table(_group_rows(events, "tradability_quality_bucket", "Giao dịch"), [3.2 * cm, 1.5 * cm, 2.1 * cm, 2.4 * cm, 2.0 * cm, 2.1 * cm, 2.1 * cm]))
    story.append(_p("Nếu một lát cắt chỉ có rất ít mẫu, không nên dùng nó để kết luận mạnh. Vai trò của phụ lục là cho thấy nơi kết quả ổn định hơn, nơi dữ liệu mỏng hơn và nơi cần đọc cờ giảm như cảnh báo định tính thay vì con số xác suất chắc chắn.", _STYLES["Body"]))
    story.append(_p("Tóm lại, Bear Flag đã đạt mức sản phẩm tương đương Bull Flag về cấu trúc chương, ví dụ, bảng và diễn giải. Điểm khác nhau còn lại là bản chất dữ liệu: Bull Flag mạnh hơn về hướng sử dụng, còn Bear Flag nên được giữ ở vai trò phòng thủ cho đến khi có lớp thực thi downside và dữ liệu trạng thái chính thức hơn.", _STYLES["Body"]))
    story.append(_table([["Nội dung cần nhớ", "Kết luận cuối"], ["Chức năng của mẫu", "Cảnh báo phòng thủ sau nhịp hồi yếu trong xu hướng giảm."], ["Mục tiêu nên đọc", "0,46x-0,50x là mốc cơ sở; 1,00x là mốc tham chiếu căng."], ["Điểm yếu chính", "MFE trung vị thấp hơn MAE trung vị; nhiều mẫu bật ngược trước khi giảm đủ xa."], ["Điều kiện cần để nâng hạng", "Cần thêm dữ liệu trạng thái chính thức và lớp thực thi downside nếu muốn chuyển từ informational sang investment-reference."], ["Trạng thái release", "Đủ làm end product Flag Family cùng Bull Flag, nhưng phải giữ nhãn defensive/informational."]], [4.3 * cm, 12.0 * cm]))
    return story


def build_public_chapter(
    *,
    events_path: Path = DEFAULT_EVENTS,
    path_path: Path = DEFAULT_PATH,
    stats_path: Path = DEFAULT_STATS,
    source_notes_path: Path = DEFAULT_SOURCE_NOTES,
    price_db: Path = DEFAULT_PRICE_DB,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> Dict[str, Path]:
    # Bear Flag must not render through its legacy standalone story anymore.
    # The canonical publication artifact is the Flag Family factory output, so
    # direct calls delegate there and expose the Bear paths for backward
    # compatibility with scripts/tests that import this function.
    from scanner.build_flag_family_public_chapters import build_flag_family_public_chapters

    paths = build_flag_family_public_chapters(
        out_dir=out_dir,
        price_db=price_db,
        bear_stats=stats_path,
        bear_events=events_path,
        bear_path=path_path,
        bear_source_notes=source_notes_path,
    )
    bear_dir = out_dir / "bear_flag"
    charts_dir = bear_dir / "charts"
    payload_path = bear_dir / "bear_flag_public_chapter_payload.json"
    manuscript_path = bear_dir / "bear_flag_ai_editorial_manuscript.md"
    notes_path = bear_dir / "bear_flag_public_chapter_notes.md"
    pdf_path = paths["bear_pdf"]

    def _one(pattern: str) -> Path:
        matches = sorted(charts_dir.glob(pattern))
        return matches[0] if matches else charts_dir / pattern.replace("*", "")

    return {
        "pdf": pdf_path,
        "payload": payload_path,
        "manuscript": manuscript_path,
        "notes": notes_path,
        "manifest_json": paths["manifest_json"],
        "manifest_md": paths["manifest_md"],
        "chart_schematic": charts_dir / "bear_flag_ideal_schematic.png",
        "chart_textbook_success": _one("textbook_success_*.png"),
        "chart_middle_case": _one("middle_case_*.png"),
        "chart_failure": _one("failure_*.png"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the public-facing Bear Flag chapter PDF.")
    parser.add_argument("--events", default=str(DEFAULT_EVENTS))
    parser.add_argument("--path", default=str(DEFAULT_PATH))
    parser.add_argument("--stats", default=str(DEFAULT_STATS))
    parser.add_argument("--source-notes", default=str(DEFAULT_SOURCE_NOTES))
    parser.add_argument("--price-db", default=str(DEFAULT_PRICE_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    paths = build_public_chapter(
        events_path=Path(args.events),
        path_path=Path(args.path),
        stats_path=Path(args.stats),
        source_notes_path=Path(args.source_notes),
        price_db=Path(args.price_db),
        out_dir=Path(args.out_dir),
    )
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
