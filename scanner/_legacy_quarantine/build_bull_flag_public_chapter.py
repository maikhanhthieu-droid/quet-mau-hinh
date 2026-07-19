"""Build a public-facing Vietnamese Bull Flag chapter.

This is intentionally different from release-gate PDFs. It follows the reading
shape of Bulkowski's Flags chapter, but the PDF itself is written as a public
Vietnamese chapter instead of a source-comparison memo.
"""

from __future__ import annotations

import argparse
import html
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.canonical_chapter_content import load_approved_editorial_sections  # noqa: E402
from scanner.legacy_guard import require_legacy_publication_builder_enabled  # noqa: E402


DEFAULT_EVENTS = Path("artifacts/scanner_v2/bull_flags/events.csv")
DEFAULT_PATH = Path("artifacts/scanner_v2/bull_flags/post_breakout_path.csv")
DEFAULT_PUBLICATION_PAYLOAD = Path("artifacts/scanner_v2/bull_flags_publication_chapter/bull_flag_publication_payload.json")
DEFAULT_SOURCE_NOTES = Path("artifacts/scanner_v2/bull_flags_source_grounding/bull_flag_source_notes.json")
DEFAULT_PRICE_DB = Path("vietnam_stocks.db")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bull_flags_public_chapter")
DEFAULT_AI_SECTIONS = Path("artifacts/scanner_v2/bull_flags_ai_writing_blocked_v4_flash/approved_ai_sections.json")

FONT_REGULAR_CANDIDATES = (
    Path("/opt/homebrew/Cellar/python-matplotlib/3.10.7/libexec/lib/python3.14/site-packages/matplotlib/mpl-data/fonts/ttf/DejaVuSans.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
)
FONT_BOLD_CANDIDATES = (
    Path("/opt/homebrew/Cellar/python-matplotlib/3.10.7/libexec/lib/python3.14/site-packages/matplotlib/mpl-data/fonts/ttf/DejaVuSans-Bold.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
)


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def _register_fonts() -> tuple[str, str]:
    regular = next((path for path in FONT_REGULAR_CANDIDATES if path.exists()), None)
    bold = next((path for path in FONT_BOLD_CANDIDATES if path.exists()), regular)
    if regular is None:
        return ("Helvetica", "Helvetica-Bold")
    pdfmetrics.registerFont(TTFont("PublicSans", str(regular)))
    pdfmetrics.registerFont(TTFont("PublicSansBold", str(bold)))
    return ("PublicSans", "PublicSansBold")


def _styles(font_regular: str, font_bold: str) -> Dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "Title": ParagraphStyle("Title", parent=base["Title"], fontName=font_bold, fontSize=24, leading=29, alignment=TA_CENTER, textColor=colors.HexColor("#173b3a"), spaceAfter=8),
        "Deck": ParagraphStyle("Deck", parent=base["Normal"], fontName=font_bold, fontSize=7.2, leading=9, alignment=TA_CENTER, textColor=colors.HexColor("#8a6f3d"), spaceAfter=4),
        "Subtitle": ParagraphStyle("Subtitle", parent=base["Normal"], fontName=font_regular, fontSize=10.2, leading=14, alignment=TA_CENTER, textColor=colors.HexColor("#555555"), spaceAfter=12),
        "H1": ParagraphStyle("H1", parent=base["Heading1"], fontName=font_bold, fontSize=15.2, leading=19, textColor=colors.HexColor("#173b3a"), spaceBefore=6, spaceAfter=5),
        "H2": ParagraphStyle("H2", parent=base["Heading2"], fontName=font_bold, fontSize=11.6, leading=14.4, textColor=colors.HexColor("#245b5a"), spaceBefore=5, spaceAfter=3),
        "SectionNo": ParagraphStyle("SectionNo", parent=base["BodyText"], fontName=font_bold, fontSize=17, leading=20, textColor=colors.white, alignment=TA_CENTER),
        "SectionTitle": ParagraphStyle("SectionTitle", parent=base["Heading1"], fontName=font_bold, fontSize=13.5, leading=16, textColor=colors.HexColor("#173b3a"), spaceAfter=0),
        "SectionSub": ParagraphStyle("SectionSub", parent=base["BodyText"], fontName=font_regular, fontSize=7.4, leading=9.6, textColor=colors.HexColor("#57504a"), spaceAfter=0),
        "Body": ParagraphStyle("Body", parent=base["BodyText"], fontName=font_regular, fontSize=8.9, leading=13.0, alignment=TA_LEFT, textColor=colors.HexColor("#202020"), spaceAfter=4.5),
        "Small": ParagraphStyle("Small", parent=base["BodyText"], fontName=font_regular, fontSize=7.6, leading=10.2, textColor=colors.HexColor("#555555"), spaceAfter=3),
        "Caption": ParagraphStyle("Caption", parent=base["BodyText"], fontName=font_regular, fontSize=7.25, leading=9.8, textColor=colors.HexColor("#555555"), alignment=TA_CENTER, spaceAfter=4),
        "TableCell": ParagraphStyle("TableCell", parent=base["BodyText"], fontName=font_regular, fontSize=7.4, leading=10.2, textColor=colors.HexColor("#202020")),
        "TableHeader": ParagraphStyle("TableHeader", parent=base["BodyText"], fontName=font_bold, fontSize=7.4, leading=10.2, textColor=colors.HexColor("#173b3a")),
        "CalloutTitle": ParagraphStyle("CalloutTitle", parent=base["BodyText"], fontName=font_bold, fontSize=8.1, leading=10.4, textColor=colors.HexColor("#173b3a"), spaceAfter=2),
        "CalloutBody": ParagraphStyle("CalloutBody", parent=base["BodyText"], fontName=font_regular, fontSize=7.4, leading=10.2, textColor=colors.HexColor("#2a2a2a"), spaceAfter=0),
        "MetricLabel": ParagraphStyle("MetricLabel", parent=base["BodyText"], fontName=font_bold, fontSize=7.2, leading=9.2, textColor=colors.HexColor("#555555"), alignment=TA_CENTER),
        "MetricValue": ParagraphStyle("MetricValue", parent=base["BodyText"], fontName=font_bold, fontSize=16, leading=19, textColor=colors.HexColor("#173b3a"), alignment=TA_CENTER),
        "MetricNote": ParagraphStyle("MetricNote", parent=base["BodyText"], fontName=font_regular, fontSize=6.5, leading=8.2, textColor=colors.HexColor("#666666"), alignment=TA_CENTER),
    }


_PUBLIC_TEXT_REPLACEMENTS = (
    ("MFE trung vị 60 ngày", "mức tăng tốt nhất trung vị 60 ngày"),
    ("MAE trung vị 60 ngày", "mức kéo ngược sâu nhất trung vị 60 ngày"),
    ("MFE", "mức tăng tốt nhất"),
    ("MAE", "mức kéo ngược sâu nhất"),
    ("Biên thuận lợi", "Mức tăng tốt nhất"),
    ("biên thuận lợi", "mức tăng tốt nhất"),
    ("Biên bất lợi", "Mức kéo ngược sâu nhất"),
    ("biên bất lợi", "mức kéo ngược sâu nhất"),
    ("biên lợi nhuận tối đa", "mức tăng tốt nhất"),
    ("Mục tiêu trước bất lợi", "Đạt mục tiêu trước kéo ngược"),
    ("mục tiêu trước bất lợi", "đạt mục tiêu trước kéo ngược"),
    ("target-first-before-adverse", "đạt mục tiêu trước khi bị kéo ngược mạnh"),
    ("target-first", "đạt mục tiêu trước kéo ngược"),
    ("target-hit", "đạt mục tiêu"),
    ("Target-hit", "Đạt mục tiêu"),
    ("Breakout", "Phá vỡ"),
    ("breakout", "phá vỡ"),
    ("half-staff", "nửa cột cờ"),
    ("swing", "dao động"),
    ("path dữ liệu", "chất lượng dữ liệu"),
    ("path-level", "theo đường giá"),
    ("path", "đường giá"),
    ("point-in-time", "theo từng thời điểm"),
    ("corporate-action", "sự kiện quyền và điều chỉnh giá"),
    ("available-series", "dữ liệu hiện có"),
    ("available", "dữ liệu hiện có"),
    ("research-only", "chỉ dùng cho nghiên cứu"),
    ("research", "nghiên cứu"),
    ("setup", "cấu hình"),
    ("proxy", "đại diện"),
    ("scanner", "bộ quét"),
    ("Scanner", "Bộ quét"),
    ("pipeline", "quy trình"),
    ("Chapter", "Chương"),
    ("chapter", "chương"),
    ("headline", "kết luận chính"),
    ("aggregate", "kết quả gộp"),
    ("low-liquidity", "thanh khoản thấp"),
    ("public-grade", "đủ chuẩn công bố"),
    ("premium+standard", "premium và standard"),
    ("data-limited", "thiếu dữ liệu"),
    ("data_limited", "thiếu dữ liệu"),
    ("loose", "lỏng"),
    ("sample", "mẫu"),
    ("watchlist-reference", "tham khảo theo dõi"),
    ("visual validation", "kiểm tra hình thái bằng mắt"),
    ("overclaim", "nói quá"),
    ("outcome", "kết quả"),
    ("dừng lỗ", "ngưỡng rủi ro"),
    ("Dừng lỗ", "Ngưỡng rủi ro"),
    ("hạ trọng số", "đọc thận trọng hơn"),
    ("Hạ trọng số", "Đọc thận trọng hơn"),
    ("Thống kê kết quả", "Kết quả sau phá vỡ"),
    ("Phân vị quan trọng", "Vùng thường gặp và vùng cực trị"),
    ("Thống kê tổng quát", "Bức tranh tổng quát"),
)


def _public_text(value: Any) -> str:
    text = str(value)
    for old, new in _PUBLIC_TEXT_REPLACEMENTS:
        text = text.replace(old, new)
    return (
        text.replace("dữ liệu hiện có-series", "dữ liệu hiện có")
        .replace("nghiên cứu candidate", "ứng viên nghiên cứu")
        .replace("cấu hình-quality", "chất lượng cấu hình")
        .replace("mức tăng tốt nhất / mức kéo ngược sâu nhất", "mức tăng tốt nhất / kéo ngược sâu nhất")
    )


def _esc(value: Any) -> str:
    return html.escape(_public_text(value))


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_esc(text), style)


def _bullet(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph("• " + _esc(text), style)


def _fmt(value: Any, digits: int = 2, suffix: str = "") -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "n/a"
    if isinstance(value, (int, np.integer)):
        return f"{value}{suffix}"
    if isinstance(value, (float, np.floating)):
        if digits <= 0:
            return f"{float(value):.0f}{suffix}"
        return f"{float(value):.{digits}f}".rstrip("0").rstrip(".") + suffix
    return str(value) + suffix


def _fmt_pair(value: Any, first_label: str = "up", second_label: str = "down") -> str:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) >= 2:
        return f"{first_label} {value[0]}% / {second_label} {value[1]}%"
    return "n/a"


def _vi_label(value: Any) -> str:
    mapping = {
        "bull": "thị trường lên",
        "bear": "thị trường xuống",
        "high": "thanh khoản cao",
        "mid": "thanh khoản trung bình",
        "low": "thanh khoản thấp",
        "VN30": "VN30",
        "VN100 ex VN30": "VN100 ngoài VN30",
        "Outside VN100": "ngoài VN100",
    }
    return mapping.get(str(value), str(value))


def _vi_rule_mapping(text: Any) -> str:
    raw = str(text)
    replacements = {
        "Require a steep, quick advance before a Bull Flag formation.": "Yêu cầu một nhịp tăng nhanh và dốc trước khi thân cờ hình thành.",
        "Require the flag body to fit a short channel bounded by approximately parallel trendlines.": "Yêu cầu thân cờ nằm trong một kênh ngắn với hai đường biên gần song song.",
        "Reject formations that last longer than three trading weeks.": "Loại các thân cờ kéo dài quá khoảng ba tuần giao dịch.",
        "Confirm a Bull Flag only when price closes above the upper flag trendline.": "Chỉ xác nhận khi giá đóng cửa vượt lên trên đường biên trên của thân cờ.",
        "Record falling volume during the flag as a context feature, but do not make it a hard gate.": "Ghi nhận khối lượng giảm như một biến bối cảnh, nhưng không dùng làm điều kiện loại trực tiếp.",
        "Compute the legacy pole-height measure rule from the start of the prior advance to the flag formation, then keep fractional targets as Vietnam calibration bands.": "Đo chiều cao cột cờ từ điểm bắt đầu nhịp tăng tới vùng thân cờ, rồi dùng các mức mục tiêu phân đoạn cho thị trường Việt Nam.",
    }
    return replacements.get(raw, raw)


def _vi_bool(value: Any) -> str:
    return "có" if bool(value) else "không"


def _table(rows: Sequence[Sequence[Any]], widths: Sequence[float], *, font_size: float = 7.4) -> Table:
    data = [[Paragraph(_esc(cell), _STYLES["TableHeader" if r == 0 else "TableCell"]) for cell in row] for r, row in enumerate(rows)]
    table = Table(data, colWidths=list(widths), hAlign="LEFT", repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTNAME", (0, 0), (-1, -1), _FONT_REGULAR),
                ("FONTSIZE", (0, 0), (-1, -1), font_size),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d9d4ca")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0ece3")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fbfaf7")]),
            ]
        )
    )
    return table


def _section_title(number: str, title: str, subtitle: str = "") -> Table:
    content = [Paragraph(_esc(title), _STYLES["SectionTitle"])]
    if subtitle:
        content.append(Paragraph(_esc(subtitle), _STYLES["SectionSub"]))
    table = Table(
        [[Paragraph(_esc(number), _STYLES["SectionNo"]), content]],
        colWidths=[1.05 * cm, 15.35 * cm],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#245b5a")),
                ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#f4f1ea")),
                ("BOX", (0, 0), (-1, -1), 0.35, colors.HexColor("#d8d0c2")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 0),
                ("LEFTPADDING", (1, 0), (1, 0), 8),
                ("RIGHTPADDING", (1, 0), (1, 0), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _callout(title: str, rows: Sequence[str]) -> Table:
    body = [Paragraph(_esc(title), _STYLES["CalloutTitle"])]
    body.extend(Paragraph("• " + _esc(row), _STYLES["CalloutBody"]) for row in rows)
    table = Table([[body]], colWidths=[16.4 * cm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7f4ee")),
                ("BOX", (0, 0), (-1, -1), 0.35, colors.HexColor("#d8d0c2")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _metric_card(label: str, value: str, note: str = "") -> list[Paragraph]:
    return [
        Paragraph(_esc(label), _STYLES["MetricLabel"]),
        Paragraph(_esc(value), _STYLES["MetricValue"]),
        Paragraph(_esc(note), _STYLES["MetricNote"]),
    ]


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
    lo = max(0, start_idx - pre_bars)
    hi = min(len(df), breakout_idx + post_bars + 1)
    return df.iloc[lo:hi].copy().reset_index(drop=True)


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
    ax.text(ib + 0.3, float(df["high"].max()), "Phá vỡ", fontsize=8, color="#6f4aa8", va="bottom")

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
    x = np.array([0, 1, 2, 3, 4, 5, 6, 7.5, 8.5])
    y = np.array([10, 14, 20, 28, 26, 27, 25.5, 29, 32])
    fig, ax = plt.subplots(figsize=(9.2, 3.9), dpi=180)
    ax.plot(x, y, color="#173b3a", linewidth=2.0)
    ax.scatter(x, y, s=22, color="#173b3a")
    ax.axvspan(3.85, 6.15, color="#1f77b4", alpha=0.11)
    ax.annotate("cột cờ", xy=(2.2, 22), xytext=(0.7, 27), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
    ax.annotate("thân cờ ngắn", xy=(5.1, 26), xytext=(4.4, 21), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
    ax.annotate("phá vỡ", xy=(7.5, 29), xytext=(6.8, 33), arrowprops={"arrowstyle": "->", "color": "#6f4aa8"}, color="#6f4aa8", fontsize=9)
    ax.axhline(29, color="#6f4aa8", linestyle="--", linewidth=0.9)
    ax.axhline(32, color="#e98b2a", linestyle="--", linewidth=0.9)
    ax.text(0, 32.2, "mục tiêu cơ sở 0,46 lần chiều cao cột cờ", color="#e98b2a", fontsize=8)
    ax.set_title("Giải phẫu mẫu cờ tăng", loc="left", fontsize=10)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)


def _select_examples(events: pd.DataFrame) -> Dict[str, pd.Series]:
    vn100 = events[events["market_group"].isin(["VN30", "VN100 ex VN30"])].copy()
    source = vn100 if not vn100.empty else events.copy()
    source["_market_rank"] = source["market_group"].map({"VN30": 0, "VN100 ex VN30": 1}).fillna(2)
    success = source[(source["target_hit"] == True) & (source["target_first_before_adverse_5pct"] == True)].copy()
    failure = source[(source["failure_5pct"] == True)].copy()
    neutral = source[(source["target_hit"] == False) & (source["failure_5pct"] == False)].copy()
    med = float(source["mfe_pct"].median())
    neutral["median_distance"] = (neutral["mfe_pct"] - med).abs()
    return {
        "textbook_success": success.sort_values(["_market_rank", "pattern_quality_score", "mfe_pct"], ascending=[True, False, False]).iloc[0],
        "failure": failure.sort_values(["_market_rank", "pattern_quality_score", "mae_pct"], ascending=[True, False, False]).iloc[0],
        "middle_case": neutral.sort_values(["_market_rank", "median_distance", "pattern_quality_score"], ascending=[True, True, False]).iloc[0],
    }


def _build_example_charts(events: pd.DataFrame, price_db: Path, out_dir: Path) -> Dict[str, Path]:
    charts_dir = out_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    _plot_ideal_schematic(charts_dir / "bull_flag_ideal_schematic.png")
    paths = {"schematic": charts_dir / "bull_flag_ideal_schematic.png"}
    examples = _select_examples(events)
    for key, event in examples.items():
        raw = _load_ohlcv(price_db, str(event["symbol"]))
        window = _slice_around_event(raw, event)
        title_map = {
            "textbook_success": "ví dụ đạt mục tiêu",
            "middle_case": "ví dụ trung vị",
            "failure": "ví dụ thất bại",
        }
        title = f"{event['symbol']} - {title_map.get(key, 'ví dụ')} ({event['breakout_date']})"
        out_path = charts_dir / f"{key}_{event['symbol']}_{event['breakout_date']}.png"
        _plot_event_chart(window, event, out_path, title)
        paths[key] = out_path
    return paths


def _summary_rows(stats: Mapping[str, Any], target_rows: Sequence[Mapping[str, Any]]) -> list[list[Any]]:
    return [
        ["Chỉ tiêu", "Mẫu cờ tăng tại Việt Nam", "Cách đọc"],
        ["Số mẫu", _fmt(stats.get("events"), 0), "Mẫu tham chiếu theo dữ liệu hiện có, không phải tuyên bố bao phủ toàn thị trường theo từng thời điểm."],
        ["Mức tăng tốt nhất / kéo ngược sâu nhất", f"{_fmt(stats.get('median_mfe_pct'))}% / {_fmt(stats.get('median_mae_pct'))}%", "Ở trường hợp trung vị, quãng đi đúng hướng lớn hơn quãng kéo ngược sâu nhất."],
        ["Thất bại 5%", f"{_fmt(stats.get('failure_5pct_rate'))}%", "Tỷ lệ mẫu không đi được tối thiểu 5% theo hướng phá vỡ."],
        ["Đạt mục tiêu 1,0 lần cột cờ", f"{_fmt(stats.get('legacy_target_hit_rate'))}%", "Mục tiêu đầy đủ được giữ làm mốc tham chiếu căng."],
        ["Đạt mục tiêu 0,46 lần cột cờ", f"{_fmt(next((r.get('target_hit_rate') for r in target_rows if r.get('target_multiple') == 0.46), None))}%", "Mục tiêu cơ sở cho chương Việt Nam."],
    ]


def _results_snapshot_rows(stats: Mapping[str, Any], target: Mapping[str, Any], events: pd.DataFrame) -> list[list[Any]]:
    base = target.get("base_target") if isinstance(target.get("base_target"), Mapping) else {}
    legacy = target.get("legacy_target") if isinstance(target.get("legacy_target"), Mapping) else {}
    vn100 = int(events[events["market_group"].isin(["VN30", "VN100 ex VN30"])].shape[0])
    return [
        ["Mục", "Kết quả chính"],
        ["Diện mạo", "Mẫu tiếp diễn ngắn: cột cờ tăng mạnh, thân cờ nghỉ hẹp, xác nhận bằng giá đóng cửa phá lên."],
        ["Phạm vi ví dụ", f"{vn100} mẫu thuộc VN30/VN100; biểu đồ minh họa lấy trong nhóm này."],
        ["Số mẫu đo được", f"{_fmt(stats.get('events'), 0)} mẫu / {_fmt(events['symbol'].nunique(), 0)} mã."],
        ["Mục tiêu cơ sở", f"0,46 lần chiều cao cột cờ; tỷ lệ đạt {_fmt(base.get('target_hit_rate'))}%."],
        ["Mốc đầy đủ", f"1,0 lần chiều cao cột cờ; tỷ lệ đạt {_fmt(legacy.get('target_hit_rate'))}%."],
        ["Thất bại 5%", f"{_fmt(stats.get('failure_5pct_rate'))}% mẫu không đi được tối thiểu 5% theo hướng phá vỡ."],
        ["Kiểm định lại", "Đo hai lớp: quay lại đường biên thân cờ và quay lại vùng giá phá vỡ trong 30 phiên."],
        ["Cách dùng", "Dùng như hồ sơ tham khảo hậu phá vỡ, không phải tín hiệu mua tự động."],
    ]


def _notable_findings(stats: Mapping[str, Any], target: Mapping[str, Any], events: pd.DataFrame) -> list[str]:
    base = target.get("base_target") if isinstance(target.get("base_target"), Mapping) else {}
    legacy = target.get("legacy_target") if isinstance(target.get("legacy_target"), Mapping) else {}
    high_body = events[events["pattern_height_pct"] > float(events["pattern_height_pct"].median())]
    yearly_high = events[pd.to_numeric(events["yearly_range_position_pct"], errors="coerce") > 66.67]
    no_gap = events[pd.to_numeric(events["breakout_gap_pct"], errors="coerce").abs() <= 0.5]
    return [
        f"Mục tiêu cơ sở 0,46x đạt {_fmt(base.get('target_hit_rate'))}%, cao hơn rõ so với mốc đầy đủ 1,0x ở {_fmt(legacy.get('target_hit_rate'))}%.",
        f"Thân cờ cao hơn trung vị có tỷ lệ đạt mục tiêu {high_body['target_hit'].mean() * 100:.2f}% và thất bại 5% {high_body['failure_5pct'].mean() * 100:.2f}%.",
        f"Mẫu phá vỡ ở vùng cao trong biên năm có mức tăng tốt nhất trung vị {yearly_high['mfe_pct'].median():.2f}% và mức kéo ngược sâu nhất trung vị {yearly_high['mae_pct'].median():.2f}%.",
        f"Nhóm phá vỡ không có khoảng nhảy giá lớn có mức kéo ngược sâu nhất trung vị {no_gap['mae_pct'].median():.2f}%, thấp hơn nhóm có khoảng nhảy giá lớn trong dữ liệu hiện có.",
    ]


def _sample_walkthrough_rows(event: Mapping[str, Any]) -> list[list[Any]]:
    return [
        ["Mốc đọc mẫu", "Dữ kiện", "Ý nghĩa"],
        ["Bắt đầu mẫu", str(event.get("formation_start_date")), "Sau nhịp tăng trước đó, giá bắt đầu đi vào thân cờ."],
        ["Kết thúc thân cờ", str(event.get("formation_end_date")), "Vùng nghỉ kết thúc; chờ xác nhận bằng giá đóng cửa phá lên."],
        ["Ngày xác nhận", str(event.get("breakout_date")), f"Giá phá vỡ {_fmt(event.get('breakout_price'))}; mục tiêu đầy đủ {_fmt(event.get('target_price'))}."],
        ["Đường đi sau đó", f"Mức tăng tốt nhất {_fmt(event.get('mfe_pct'))}%; mức kéo ngược sâu nhất {_fmt(event.get('mae_pct'))}%.", "Cho biết mẫu đi đúng hướng bao xa và từng kéo ngược sâu tới đâu."],
        ["Kết quả", f"Đạt mục tiêu: {_vi_bool(event.get('target_hit'))}; thất bại 5%: {_vi_bool(event.get('failure_5pct'))}.", "Đây là ví dụ diễn biến, không phải lời khuyên giao dịch."],
    ]


def _best_conditions_rows(events: pd.DataFrame) -> list[list[Any]]:
    height_med = float(events["pattern_height_pct"].median())
    gap = pd.to_numeric(events["breakout_gap_pct"], errors="coerce").abs()
    pos = pd.to_numeric(events["yearly_range_position_pct"], errors="coerce")
    specs = [
        ("Thân cờ cao hơn trung vị", events["pattern_height_pct"] > height_med, "Trong dữ liệu hiện có, nhóm này có tỷ lệ đạt mục tiêu và mức tăng tốt nhất cao hơn nhóm thân cờ thấp."),
        ("Phá vỡ không có khoảng nhảy giá lớn", gap <= 0.5, "Đường đi sau phá vỡ ít bị kéo giãn ngay từ phiên xác nhận; mức kéo ngược sâu nhất trung vị thấp hơn."),
        ("Vùng cao trong biên năm", pos > 66.67, "Phù hợp tính chất tiếp diễn: mẫu xuất hiện gần vùng giá mạnh thay vì vùng yếu kéo dài."),
        ("Nhóm VN30/VN100", events["market_group"].isin(["VN30", "VN100 ex VN30"]), "Ví dụ trong chương lấy từ nhóm này để tăng khả năng đọc và giảm nhiễu thanh khoản."),
        ("Đường giá sạch", events["path_quality_bucket"].astype(str) == "clean", "Ít thiếu phiên, ít chuỗi đứng giá; phù hợp hơn cho việc đọc thời gian chạm mục tiêu và kiểm định lại."),
    ]
    rows = [["Điều kiện", "Số mẫu", "Đạt mục tiêu", "Đạt trước kéo ngược", "Thất bại 5%", "Cách đọc"]]
    for label, mask, note in specs:
        group = events[mask.fillna(False) if hasattr(mask, "fillna") else mask]
        if group.empty:
            continue
        rows.append(
            [
                label,
                _fmt(len(group), 0),
                _fmt(float(group["target_hit"].mean() * 100.0), suffix="%"),
                _fmt(float(group["target_first_before_adverse_5pct"].mean() * 100.0), suffix="%"),
                _fmt(float(group["failure_5pct"].mean() * 100.0), suffix="%"),
                note,
            ]
        )
    return rows


def _skip_conditions_rows(events: pd.DataFrame) -> list[list[Any]]:
    width_q75 = float(events["pattern_width_bars"].quantile(0.75))
    height_q75 = float(events["pattern_height_pct"].quantile(0.75))
    adverse_q75 = float(events["mae_pct"].quantile(0.75))
    return [
        ["Tình huống", "Ngưỡng tham chiếu", "Lý do đọc thận trọng"],
        ["Thân cờ kéo dài", f"Trên Q75: {width_q75:.0f} phiên", "Cờ tăng là mẫu nghỉ ngắn; thân cờ quá dài dễ chuyển thành kênh giá hoặc nền tích lũy."],
        ["Thân cờ quá rộng", f"Trên Q75: {_fmt(height_q75)}%", "Biên độ lớn làm yếu ý nghĩa hấp thụ cung trong vùng hẹp."],
        ["Đường giá kém sạch", "Thiếu phiên, đứng giá kéo dài hoặc không có khối lượng", "Thời gian chạm mục tiêu và kiểm định lại có thể bị méo."],
        ["Sự kiện quyền gần mẫu", "Có sự kiện quyền trong hoặc sát vùng phá vỡ", "Hình thái và biên đo hậu phá vỡ có thể chịu ảnh hưởng điều chỉnh giá."],
        ["Kéo ngược quá sâu", f"Trên Q75: {_fmt(adverse_q75)}%", "Mẫu có thể vẫn đi đúng hướng nhưng đường đi không còn gọn."],
    ]


def _quantile_rows(events: pd.DataFrame) -> list[list[Any]]:
    specs = [
        ("Độ dài thân cờ", "pattern_width_bars", "phiên"),
        ("Chiều cao thân cờ", "pattern_height_pct", "%"),
        ("Cột cờ trước mẫu", "pole_move_pct", "%"),
        ("Mục tiêu đầy đủ", "target_dist_pct", "%"),
        ("Mức tăng tốt nhất", "mfe_pct", "%"),
        ("Mức kéo ngược sâu nhất", "mae_pct", "%"),
        ("Ngày chạm mục tiêu đầy đủ", "days_to_target", "phiên"),
    ]
    rows = [["Biến", "Q10", "Q25", "Q50", "Q75", "Q90", "Đơn vị"]]
    for label, col, unit in specs:
        if col not in events.columns:
            continue
        series = pd.to_numeric(events[col], errors="coerce").dropna()
        if series.empty:
            continue
        rows.append(
            [
                label,
                _fmt(float(series.quantile(0.10))),
                _fmt(float(series.quantile(0.25))),
                _fmt(float(series.quantile(0.50))),
                _fmt(float(series.quantile(0.75))),
                _fmt(float(series.quantile(0.90))),
                unit,
            ]
        )
    return rows


def _quick_conclusion_rows(events: pd.DataFrame, target: Mapping[str, Any], ref: Mapping[str, Any]) -> list[list[Any]]:
    base = target.get("base_target") if isinstance(target.get("base_target"), Mapping) else {}
    legacy = target.get("legacy_target") if isinstance(target.get("legacy_target"), Mapping) else {}
    return [
        ["Câu hỏi", "Câu trả lời trong dữ liệu hiện có"],
        ["Mẫu này thường dùng để đọc gì?", "Một nhịp tiếp diễn ngắn sau cột cờ tăng mạnh, không phải một nền tích lũy dài."],
        ["Mục tiêu nào nên là mốc chính?", f"0,46 lần chiều cao cột cờ, với tỷ lệ đạt {_fmt(base.get('target_hit_rate'))}%."],
        ["Mốc 1,0 lần có vai trò gì?", f"Mốc đầy đủ để tham chiếu; tỷ lệ đạt {_fmt(legacy.get('target_hit_rate'))}%, thấp hơn rõ so với mục tiêu cơ sở."],
        ["Rủi ro chính là gì?", f"Thất bại 5% ở {_fmt(ref.get('failure_5pct_rate'))}% và mức kéo ngược sâu nhất trung vị {_fmt(float(events['mae_pct'].median()))}%."],
        ["Khi nào mẫu đáng chú ý hơn?", "Khi có cột cờ rõ, thân cờ gọn, đường giá sạch, mục tiêu không quá xa và bối cảnh không chống lại mẫu."],
        ["Khi nào nên đọc thận trọng hơn?", "Khi thân cờ kéo dài, biên độ lớn, đường giá kém sạch, hoặc sự kiện quyền nằm gần vùng xác nhận."],
    ]


def _context_rows(table: Mapping[str, Mapping[str, Any]], label: str) -> list[list[Any]]:
    rows = [[label, "Số mẫu", "Đạt mục tiêu", "Đạt trước kéo ngược", "Thất bại 5%", "Mức tăng tốt nhất", "Kéo ngược sâu nhất"]]
    for key, row in table.items():
        if key == "unknown" or not isinstance(row, Mapping):
            continue
        rows.append(
            [
                _vi_label(key),
                _fmt(row.get("n") or row.get("detection_count"), 0),
                _fmt(row.get("target_hit_rate"), suffix="%"),
                _fmt(row.get("target_first_before_adverse_5pct_rate"), suffix="%"),
                _fmt(row.get("failure_5pct_rate"), suffix="%"),
                _fmt(row.get("median_mfe_pct"), suffix="%"),
                _fmt(row.get("median_mae_pct"), suffix="%"),
            ]
        )
    return rows


def _context_rows_from_events(events: pd.DataFrame, group_col: str, label: str) -> list[list[Any]]:
    rows = [[label, "Số mẫu", "Đạt mục tiêu 1,0x", "Đạt trước kéo ngược", "Thất bại 5%", "Mức tăng tốt nhất", "Kéo ngược sâu nhất"]]
    if group_col not in events.columns:
        return rows
    for key, group in events.groupby(group_col, dropna=False):
        rows.append(
            [
                _vi_label(key),
                _fmt(len(group), 0),
                _fmt(float(group["target_hit"].mean() * 100.0), suffix="%"),
                _fmt(float(group["target_first_before_adverse_5pct"].mean() * 100.0), suffix="%"),
                _fmt(float(group["failure_5pct"].mean() * 100.0), suffix="%"),
                _fmt(float(group["mfe_pct"].median()), suffix="%"),
                _fmt(float(group["mae_pct"].median()), suffix="%"),
            ]
        )
    return rows


def _pct_rate(series: pd.Series) -> float:
    if series.empty:
        return float("nan")
    return float(series.astype(bool).mean() * 100.0)


def _basic_group_stats(group: pd.DataFrame) -> list[str]:
    return [
        _fmt(len(group), 0),
        _fmt(_pct_rate(group["target_hit"]), suffix="%"),
        _fmt(_pct_rate(group["target_first_before_adverse_5pct"]), suffix="%"),
        _fmt(_pct_rate(group["failure_5pct"]), suffix="%"),
        _fmt(float(group["mfe_pct"].median()), suffix="%"),
        _fmt(float(group["mae_pct"].median()), suffix="%"),
    ]


def _size_volume_rows(events: pd.DataFrame) -> list[list[Any]]:
    rows = [["Nhóm", "Số mẫu", "Đạt mục tiêu", "Đạt trước kéo ngược", "Thất bại 5%", "Mức tăng tốt nhất", "Kéo ngược sâu nhất"]]
    width_med = float(events["pattern_width_bars"].median())
    height_med = float(events["pattern_height_pct"].median())
    specs = [
        (f"Thân cờ ngắn (≤ {width_med:.0f} phiên)", events["pattern_width_bars"] <= width_med),
        (f"Thân cờ dài (> {width_med:.0f} phiên)", events["pattern_width_bars"] > width_med),
        (f"Thân cờ thấp (≤ {_fmt(height_med)}%)", events["pattern_height_pct"] <= height_med),
        (f"Thân cờ cao (> {_fmt(height_med)}%)", events["pattern_height_pct"] > height_med),
        ("Khối lượng xác nhận", events["volume_confirmed"] == True),
        ("Không có xác nhận khối lượng", events["volume_confirmed"] == False),
    ]
    for label, mask in specs:
        group = events[mask].copy()
        if group.empty:
            continue
        rows.append([label, *_basic_group_stats(group)])
    return rows


def _breakout_context_rows(events: pd.DataFrame) -> list[list[Any]]:
    rows = [["Nhóm", "Số mẫu", "Đạt mục tiêu", "Đạt trước kéo ngược", "Thất bại 5%", "Mức tăng tốt nhất", "Kéo ngược sâu nhất"]]
    specs: list[tuple[str, pd.Series]] = []
    if "volume_trend_direction" in events.columns:
        for direction, label in [("down", "Khối lượng trong thân cờ giảm"), ("flat", "Khối lượng đi ngang"), ("up", "Khối lượng tăng")]:
            specs.append((label, events["volume_trend_direction"].astype(str) == direction))
    if "breakout_gap_pct" in events.columns:
        gap = pd.to_numeric(events["breakout_gap_pct"], errors="coerce").abs()
        specs.extend([("Phá vỡ có gap > 0,5%", gap > 0.5), ("Phá vỡ không có gap đáng kể", gap <= 0.5)])
    if "yearly_range_position_pct" in events.columns:
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
        if col in events.columns:
            hit = events[col].astype(bool)
            days = pd.to_numeric(events.loc[hit, day_col], errors="coerce").dropna() if day_col in events.columns else pd.Series(dtype=float)
            rows.append([f"Chạm ngưỡng rủi ro {stop}%", f"{_fmt(float(hit.mean() * 100.0))}% / ngày trung vị {_fmt(float(days.median()), 0) if not days.empty else 'n/a'}", "Tần suất đường đi bất lợi chạm ngưỡng trước hoặc trong cửa sổ 60 phiên."])
    if "busted_pattern_flag" in events.columns:
        busted = events["busted_pattern_flag"].astype(bool)
        days = pd.to_numeric(events.loc[busted, "days_to_bust"], errors="coerce").dropna() if "days_to_bust" in events.columns else pd.Series(dtype=float)
        rows.append(["Mẫu phá ngược", f"{_fmt(float(busted.mean() * 100.0))}% / ngày trung vị {_fmt(float(days.median()), 0) if not days.empty else 'n/a'}", "Mẫu đi thuận lợi dưới 10% rồi phá ngược xuống dưới vùng thân cờ trong 60 phiên."])
    return rows


def _data_quality_rows(events: pd.DataFrame) -> list[list[Any]]:
    rows = [["Lớp kiểm tra", "Kết quả", "Cách đọc"]]
    n = max(1, len(events))
    if "tradability_quality_bucket" in events.columns:
        counts = events["tradability_quality_bucket"].fillna("không rõ").astype(str).value_counts().to_dict()
        score = pd.to_numeric(events.get("tradability_quality_score"), errors="coerce").median()
        label = " / ".join(f"{key}: {value}" for key, value in sorted(counts.items()))
        rows.append(["Chất lượng giao dịch", f"điểm trung vị {_fmt(float(score))}; {label}", "Tổng hợp tỷ lệ thiếu phiên, phiên không có khối lượng, chuỗi giá đứng yên, dấu hiệu biên độ giá và sự kiện quyền quanh mẫu."])
    if "corp_action_overlap_flag" in events.columns:
        rows.append(["Sự kiện quyền trong thân cờ", f"{_fmt(float(events['corp_action_overlap_flag'].astype(bool).mean() * 100.0))}%", "Có sự kiện quyền nằm trong thời gian hình thành mẫu; cần đọc hình thái thận trọng hơn."])
    if "corp_action_near_breakout_flag" in events.columns:
        rows.append(["Sự kiện quyền gần phá vỡ", f"{_fmt(float(events['corp_action_near_breakout_flag'].astype(bool).mean() * 100.0))}%", "Sự kiện quyền trong vùng ±5 ngày quanh phá vỡ; đây là nhóm nhạy nhất với sai lệch giá điều chỉnh."])
    if "corp_action_in_forward_window_flag" in events.columns:
        rows.append(["Sự kiện quyền sau phá vỡ", f"{_fmt(float(events['corp_action_in_forward_window_flag'].astype(bool).mean() * 100.0))}%", "Sự kiện quyền trong cửa sổ hậu phá vỡ; có thể ảnh hưởng mức tăng tốt nhất và mức kéo ngược sâu nhất nếu chuỗi điều chỉnh không nhất quán."])
    if "price_limit_proxy_rate_60d" in events.columns:
        rows.append(["Dấu hiệu biên độ giá", f"trung vị {_fmt(float(pd.to_numeric(events['price_limit_proxy_rate_60d'], errors='coerce').median()))}% phiên", "Tỷ lệ phiên có biên dao động hoặc chênh lệch mở cửa-đóng cửa lớn, dùng để nhận diện đường đi chịu ảnh hưởng biên độ giá."])
    if "missing_bar_rate_60d" in events.columns:
        rows.append(["Thiếu dữ liệu hậu phá vỡ", f"trung vị {_fmt(float(pd.to_numeric(events['missing_bar_rate_60d'], errors='coerce').median()))}%", "Nếu thiếu phiên trong 60 phiên sau phá vỡ, thời gian chạm mục tiêu và chạm ngưỡng rủi ro phải đọc thận trọng."])
    return rows


def _post_breakout_rows(events: pd.DataFrame, path_df: pd.DataFrame) -> list[list[Any]]:
    rows = [["Chỉ tiêu", "Giá trị", "Cách đọc"]]
    hit_days = pd.to_numeric(events.loc[events["target_hit"] == True, "days_to_target"], errors="coerce").dropna()
    if not hit_days.empty:
        rows.append(["Thời gian chạm mục tiêu đầy đủ", f"P25 {hit_days.quantile(0.25):.0f} / P50 {hit_days.median():.0f} / P75 {hit_days.quantile(0.75):.0f} phiên", "Chỉ tính các mẫu đã chạm mục tiêu 1,0x; các mẫu chưa chạm vẫn phải đọc cùng tỷ lệ chưa hoàn tất trong cửa sổ đo."])
    if "throwback_exact_30d" in events.columns:
        tb = events["throwback_exact_30d"].astype(bool)
        tb_days = pd.to_numeric(events.loc[tb, "days_to_throwback_exact"], errors="coerce").dropna() if "days_to_throwback_exact" in events.columns else pd.Series(dtype=float)
        rows.append(["Kiểm định lại đường biên trong 30 phiên", f"{_fmt(float(tb.mean() * 100.0))}% / ngày trung vị {_fmt(float(tb_days.median()), 0) if not tb_days.empty else 'n/a'}", "Giá bật lên sau phá vỡ rồi quay lại chạm vùng đường biên trên của thân cờ đã kéo dài."])
    if "throwback_to_breakout_30d" in events.columns:
        tb = events["throwback_to_breakout_30d"].astype(bool)
        tb_days = pd.to_numeric(events.loc[tb, "days_to_throwback_to_breakout"], errors="coerce").dropna() if "days_to_throwback_to_breakout" in events.columns else pd.Series(dtype=float)
        rows.append(["Quay lại giá phá vỡ trong 30 phiên", f"{_fmt(float(tb.mean() * 100.0))}% / ngày trung vị {_fmt(float(tb_days.median()), 0) if not tb_days.empty else 'n/a'}", "Thước đo gần với giá phá vỡ, hữu ích để đọc chiến thuật chờ kiểm định lại vùng phá vỡ."])
    elif not path_df.empty:
        scoped = path_df[pd.to_numeric(path_df["bar_after_breakout"], errors="coerce") <= 30].copy()
        retest_count = 0
        retest_days: list[int] = []
        total = 0
        for _, group in scoped.groupby("event_id"):
            total += 1
            group = group.sort_values("bar_after_breakout")
            first_lift = group[group["signed_high_excursion_pct"] >= 2.0]
            if first_lift.empty:
                continue
            first_bar = int(first_lift["bar_after_breakout"].iloc[0])
            later = group[group["bar_after_breakout"] > first_bar]
            retest = later[later["signed_low_excursion_pct"] <= 0.5]
            if not retest.empty:
                retest_count += 1
                retest_days.append(int(retest["bar_after_breakout"].iloc[0]))
        rate = (retest_count / total * 100.0) if total else float("nan")
        median_day = float(pd.Series(retest_days).median()) if retest_days else float("nan")
        rows.append(["Dấu hiệu kiểm định lại trong 30 phiên", f"{_fmt(rate)}% / trung vị ngày {_fmt(median_day, 0)}", "Giá đã bật ít nhất 2% rồi quay lại gần vùng phá vỡ."])
    if "days_to_trend_end" in events.columns:
        days = pd.to_numeric(events["days_to_trend_end"], errors="coerce").dropna()
        move = pd.to_numeric(events["post_flag_trend_move_pct"], errors="coerce").dropna() if "post_flag_trend_move_pct" in events.columns else pd.Series(dtype=float)
        cens = events["trend_end_censored"].astype(bool).mean() * 100.0 if "trend_end_censored" in events.columns else float("nan")
        rows.append(["Kết thúc nhịp sau cờ", f"ngày trung vị {_fmt(float(days.median()), 0)} / biên trung vị {_fmt(float(move.median()))}% / chưa kết thúc {_fmt(float(cens))}%", "Cực trị thuận lợi trước khi có đảo chiều 20% hoặc hết cửa sổ đo."])
    rows.append(["Mức tăng tốt nhất / kéo ngược sâu nhất trung vị 60 phiên", f"{_fmt(float(events['mfe_pct'].median()))}% / {_fmt(float(events['mae_pct'].median()))}%", "Dùng để đọc quãng đi đúng hướng và quãng kéo ngược sau phá vỡ."])
    rows.append(["Tỷ lệ đường giá sạch", f"{_fmt(float((events['path_quality_bucket'] == 'clean').mean() * 100.0))}%", "Nếu đường giá không sạch, thời gian chạm mục tiêu và kiểm định lại phải được đọc thận trọng hơn."])
    return rows


def _general_statistics_rows(events: pd.DataFrame, ref: Mapping[str, Any]) -> list[list[Any]]:
    return [
        ["Chỉ tiêu", "Giá trị", "Ý nghĩa"],
        ["Số mẫu / số mã", f"{_fmt(ref.get('events'), 0)} / {_fmt(events['symbol'].nunique(), 0)}", "Cỡ mẫu đủ để viết chương cờ tăng trong phạm vi dữ liệu hiện có, nhưng không phải tuyên bố bao phủ toàn thị trường theo từng thời điểm."],
        ["Độ dài thân cờ", f"P25 {events['pattern_width_bars'].quantile(0.25):.0f} / P50 {events['pattern_width_bars'].median():.0f} / P75 {events['pattern_width_bars'].quantile(0.75):.0f} phiên", "Cờ tăng là mẫu ngắn; các thân cờ dài phải đọc thận trọng vì dễ gần hình chữ nhật hoặc kênh giá."],
        ["Chiều cao thân cờ", f"P25 {_fmt(float(events['pattern_height_pct'].quantile(0.25)))}% / P50 {_fmt(float(events['pattern_height_pct'].median()))}% / P75 {_fmt(float(events['pattern_height_pct'].quantile(0.75)))}%", "Thân cờ quá rộng làm suy yếu ý nghĩa 'nghỉ ngắn' của mẫu."],
        ["Cột cờ trước mẫu", f"P50 {_fmt(float(events['pole_move_pct'].median()))}%", "Nhịp tăng trước mẫu là nguồn gốc của quy tắc đo mục tiêu."],
        ["Tỷ lệ cờ/cột cờ", f"P50 {_fmt(float(events['flag_to_pole_pct'].median()))}%", "Nếu thân cờ quá lớn so với cột cờ, mẫu dễ mất tính tiếp diễn ngắn."],
    ]


def build_content_parity_audit(out_dir: Path) -> tuple[Path, Path]:
    rows = [
        ("Kết quả quan trọng", "Đã bổ sung sâu", "Mở chương bằng bảng snapshot, số mẫu, mục tiêu cơ sở, thất bại, kiểm định lại và phát hiện đáng chú ý."),
        ("Tour mẫu hình", "Đã bổ sung", "Tách thành mục riêng để giải thích cột cờ, thân cờ, phá vỡ và ý tưởng nửa cột cờ bằng tiếng Việt."),
        ("Cách nhận diện", "Đã có", "Bảng quy tắc nhận diện, tham số scanner và các điều kiện loại."),
        ("Điều kiện đọc thận trọng", "Đã bổ sung", "Có bảng đọc thận trọng hơn khi thân cờ dài/rộng, dữ liệu kém sạch, sự kiện quyền hoặc kéo ngược sâu."),
        ("Focus on failures", "Đã bổ sung sâu", "Có ví dụ thất bại, thất bại 5%, target-first và cảnh báo cờ quá dài/quá rộng."),
        ("Thống kê tổng quát", "Đã bổ sung", "Có số mẫu, số mã, độ dài, chiều cao, cột cờ và tỷ lệ cờ/cột cờ."),
        ("Vùng phân bố kết quả", "Đã bổ sung", "Có Q10/Q25/Q50/Q75/Q90 cho độ dài, chiều cao, cột cờ, mục tiêu, mức tăng tốt nhất, mức kéo ngược sâu nhất và thời gian."),
        ("Hành vi sau phá vỡ", "Đã bổ sung", "Có thời gian chạm mục tiêu, dấu hiệu kiểm định lại, mức tăng tốt nhất, mức kéo ngược sâu nhất và chất lượng đường giá."),
        ("Kích thước và khối lượng", "Đã bổ sung", "Có bảng thân cờ ngắn/dài, thấp/cao và volume_confirmed."),
        ("Chiến thuật giao dịch", "Đã có và mở rộng", "Có cách chờ phá vỡ, mục tiêu cơ sở, dừng lỗ, chi phí và checklist."),
        ("Sample trade", "Đã Việt hóa", "Thay bằng ba ví dụ VN100 và bảng diễn biến mẫu hoàn chỉnh."),
        ("For best performance", "Đã Việt hóa", "Thêm mục 'Khi mẫu đáng chú ý hơn' dựa trên chiều cao thân cờ, gap, vùng giá năm, nhóm cổ phiếu và chất lượng đường giá."),
        ("Tóm tắt thực hành", "Đã bổ sung", "Có bảng kết luận cuối chương, trả lời mẫu dùng để đọc gì, mục tiêu nào chính và khi nào đọc thận trọng hơn."),
        ("Tóm tắt cuối chương", "Đã bổ sung", "Có checklist đọc mẫu và giới hạn dữ liệu."),
    ]
    audit = {
        "purpose": "Audit nội bộ về độ phủ nội dung chương Flags gốc. Không in trực tiếp vào PDF public.",
        "status": [{"source_section": a, "coverage": b, "implementation_note": c} for a, b, c in rows],
    }
    json_path = out_dir / "bull_flag_content_parity_audit.json"
    md_path = out_dir / "bull_flag_content_parity_audit.md"
    json_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Audit độ phủ nội dung chương Bull Flag", "", "Tài liệu này dùng nội bộ để kiểm tra PDF public đã có đủ các mảnh nội dung kiểu chương Flags hay chưa.", "", "| Mục nội dung | Trạng thái | Ghi chú |", "|---|---|---|"]
    lines.extend(f"| {a} | {b} | {c} |" for a, b, c in rows)
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def _header_footer(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    canvas.setFont(_FONT_REGULAR, 7)
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawString(doc.leftMargin, 1.0 * cm, "Cờ tăng - bản chương xuất bản")
    canvas.drawRightString(A4[0] - doc.rightMargin, 1.0 * cm, f"Trang {doc.page}")
    canvas.restoreState()


def _image(path: Path, width_cm: float) -> Image:
    img = Image(str(path), width=width_cm * cm, height=0)
    iw, ih = img.imageWidth, img.imageHeight
    img.drawWidth = width_cm * cm
    img.drawHeight = img.drawWidth * ih / iw
    return img


def build_ai_editorial_sections(payload: Mapping[str, Any], events: pd.DataFrame) -> Dict[str, list[str]]:
    ref = payload.get("chapter_reference") if isinstance(payload.get("chapter_reference"), Mapping) else {}
    target = payload.get("target_calibration") if isinstance(payload.get("target_calibration"), Mapping) else {}
    tradable = payload.get("tradable_setup") if isinstance(payload.get("tradable_setup"), Mapping) else {}
    selected = tradable.get("selected_metrics") if isinstance(tradable.get("selected_metrics"), Mapping) else {}
    vn100_n = int(events[events["market_group"].isin(["VN30", "VN100 ex VN30"])].shape[0])
    return {
        "summary": [
            (
                "Mẫu cờ tăng là một mẫu tiếp diễn ngắn: giá tăng nhanh tạo thành cột cờ, sau đó tạm nghỉ trong một vùng hẹp, "
                "rồi xác nhận bằng phiên phá vỡ lên. Điều quan trọng là không xem mọi vùng đi ngang sau một nhịp tăng là cờ tăng; "
                "nếu nhịp tăng trước đó yếu hoặc thân cờ quá dài, mẫu dễ chuyển thành một cấu trúc khác."
            ),
            (
                f"Trong dữ liệu hiện có, chương ghi nhận {ref.get('events')} mẫu, trong đó {vn100_n} mẫu thuộc VN100 hoặc VN30. "
                f"Mức tăng tốt nhất trung vị là {_fmt(ref.get('median_mfe_pct'))}%, còn mức kéo ngược sâu nhất trung vị là {_fmt(ref.get('median_mae_pct'))}%. "
                "Điều này cho thấy mẫu có thiên hướng tiếp diễn, nhưng thiên hướng đó chỉ có ý nghĩa khi đọc cùng mục tiêu và rủi ro đường đi."
            ),
            (
                f"Mốc 0,46 lần chiều cao cột cờ được dùng làm mục tiêu cơ sở. Ở mốc này, tỷ lệ đạt mục tiêu là "
                f"{_fmt(target.get('base_target', {}).get('target_hit_rate'))}%, trong khi mốc 1,0 lần cột cờ chỉ đạt "
                f"{_fmt(ref.get('legacy_target_hit_rate'))}%. Vì vậy chương này không trình bày cờ tăng như một mẫu luôn chạy hết cột cờ."
            ),
        ],
        "failure": [
            (
                "Thất bại thường không đến từ việc hình vẽ trông sai ngay từ đầu. Nhiều mẫu có cột cờ và thân cờ nhìn hợp lệ nhưng sau phá vỡ "
                "không tạo được lực kéo tiếp diễn. Với loại mẫu này, câu hỏi quan trọng không chỉ là 'có chạm mục tiêu không', mà là "
                "'mục tiêu có đến trước khi giá đi ngược đủ sâu hay không'."
            ),
            (
                f"Tỷ lệ thất bại 5% của mẫu hiện là {_fmt(ref.get('failure_5pct_rate'))}%. Đây là lý do chương phải có ví dụ thất bại và "
                "không được chỉ chọn các biểu đồ đẹp. Một mẫu cờ tăng dùng được trong tài liệu tham khảo phải mô tả cả trường hợp đúng, "
                "trường hợp trung vị và trường hợp sai."
            ),
        ],
        "tour": [
            (
                "Cờ tăng nên được đọc như một đoạn nghỉ giữa đường của một nhịp tăng, không phải một nền tích lũy dài. "
                "Cột cờ cho biết lực đẩy ban đầu, thân cờ cho biết giai đoạn hấp thụ cung ngắn, còn phiên phá vỡ là thời điểm mẫu được xác nhận."
            ),
            (
                "Ý tưởng nửa cột cờ giúp đặt kỳ vọng đúng mức: mẫu thường nằm ở khoảng giữa của một nhịp di chuyển, nhưng phần sau thân cờ "
                "không nhất thiết lặp lại toàn bộ chiều cao cột cờ. Vì vậy chương này dùng một họ mục tiêu 0,46x, 0,5x, 0,75x và 1,0x thay vì ép mọi mẫu vào một mốc duy nhất."
            ),
        ],
        "statistics": [
            (
                "Kết quả của cờ tăng phải được đọc như một nhịp dao động ngắn hạn. Việc so sánh trực tiếp với các mẫu đảo chiều hoặc mẫu nền dài sẽ dễ sai, "
                "vì cờ tăng được thiết kế để đo một đoạn tiếp diễn ngắn sau phá vỡ."
            ),
            (
                "Các bảng trong chương vì vậy tập trung vào chiều dài thân cờ, chiều cao thân cờ, cột cờ trước mẫu, mục tiêu, mức tăng tốt nhất, mức kéo ngược sâu nhất, thời gian chạm mục tiêu và kiểm định lại vùng phá vỡ. "
                "Những biến này giúp người đọc hiểu mẫu hoạt động ra sao, thay vì chỉ biết một tỷ lệ thắng đơn lẻ."
            ),
        ],
        "post_breakout": [
            (
                "Sau phá vỡ, cờ tăng thường cần được theo dõi bằng cả độ xa và tốc độ. Một mẫu có thể đi đúng hướng nhưng quá chậm, hoặc đi đúng hướng sau khi đã quay lại kiểm định vùng phá vỡ; hai trường hợp này khác nhau về giá trị sử dụng."
            ),
            (
                "Kiểm định lại hiện được đo bằng hai lớp: một lớp theo đường biên thân cờ đã kéo dài, và một lớp theo vùng giá phá vỡ. Cách đo hai lớp này gần hơn với cấu trúc mẫu hình so với việc chỉ nhìn đỉnh/đáy tổng hợp sau phá vỡ."
            ),
        ],
        "size_volume": [
            (
                "Kích thước và khối lượng là phần cần có trong một chương cờ tăng. Thân cờ cao, thân cờ dài hoặc khối lượng không co lại đều có thể làm thay đổi chất lượng mẫu, "
                "vì chúng cho thấy giai đoạn nghỉ không còn gọn và sạch như lý tưởng."
            ),
            (
                "Trong phiên bản Việt Nam, các biến này chưa nên dùng để loại trực tiếp toàn bộ mẫu. Chúng được báo cáo như lớp bối cảnh để tìm xem nhóm nào giữ được xác suất đạt mục tiêu và kiểm soát thất bại tốt hơn."
            ),
        ],
        "tactics": [
            (
                "Cách dùng thận trọng là đợi phiên phá vỡ, sau đó kiểm tra độ mạnh của phiên xác nhận, thanh khoản và khoảng cách tới mục tiêu. "
                "Nếu giá đã đi quá xa ngay trong ngày phá vỡ, lợi thế thống kê có thể đã bị tiêu thụ trước khi nhà đầu tư kịp thực hiện."
            ),
            (
                f"Nếu thử đưa vào thực tế, cấu hình hiện dùng vào lệnh sau {selected.get('entry_delay_bars')} phiên, ngưỡng rủi ro {selected.get('stop_loss_pct')}%, "
                f"và thời gian nắm giữ tối đa {selected.get('max_holding_days')} phiên. Các giả định này không biến chương thành lời khuyên mua, "
                "nhưng giúp người đọc hiểu thống kê mô tả có còn hợp lý khi thêm ma sát giao dịch hay không."
            ),
        ],
        "checklist": [
            "Chỉ đọc là cờ tăng khi có cột cờ rõ trước thân cờ.",
            "Thân cờ phải ngắn, tương đối hẹp và nằm trong hai đường biên gần song song.",
            "Không đo kết quả trước khi có phiên đóng cửa phá vỡ lên.",
            "Dùng 0,46x-0,5x cột cờ làm mục tiêu cơ sở; xem 1,0x là mốc tham chiếu căng.",
            "Luôn kiểm tra thất bại 5%, mức kéo ngược sâu nhất và kiểm định lại thay vì chỉ nhìn tỷ lệ đạt mục tiêu.",
            "Ưu tiên mẫu trong nhóm thanh khoản đủ tốt và có chất lượng đường giá sạch.",
        ],
    }


def _load_ai_editorial_sections(path: Path | None) -> Dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return load_approved_editorial_sections(path)


def build_story(payload: Mapping[str, Any], source_notes: Mapping[str, Any], events: pd.DataFrame, path_df: pd.DataFrame, charts: Mapping[str, Path], ai_sections_path: Path | None = None) -> list[Any]:
    ref = payload.get("chapter_reference") if isinstance(payload.get("chapter_reference"), Mapping) else {}
    target = payload.get("target_calibration") if isinstance(payload.get("target_calibration"), Mapping) else {}
    target_rows = [r for r in target.get("rows", []) if isinstance(r, Mapping)]
    tradable = payload.get("tradable_setup") if isinstance(payload.get("tradable_setup"), Mapping) else {}
    selected = tradable.get("selected_metrics") if isinstance(tradable.get("selected_metrics"), Mapping) else {}
    source_rules = [r for r in source_notes.get("source_rules", []) if isinstance(r, Mapping)]
    ai = build_ai_editorial_sections(payload, events)
    ai_external = _load_ai_editorial_sections(ai_sections_path)
    ai.update(ai_external.get("sections", {}))
    ai_captions = ai_external.get("captions", {}) if isinstance(ai_external.get("captions"), Mapping) else {}

    story: list[Any] = []
    story.append(Paragraph("CHƯƠNG MẪU HÌNH GIÁ", _STYLES["Deck"]))
    story.append(Paragraph("Cờ tăng", _STYLES["Title"]))
    story.append(Paragraph("Mẫu tiếp diễn ngắn sau một nhịp tăng mạnh", _STYLES["Subtitle"]))
    cards = [
        _metric_card("Số mẫu", _fmt(ref.get("events"), 0), "mẫu đã kiểm tra"),
        _metric_card("Mục tiêu cơ sở", "0,46x", "chiều cao cột cờ"),
        _metric_card("Tỷ lệ đạt", f"{_fmt(target.get('base_target', {}).get('target_hit_rate'))}%", "mục tiêu cơ sở"),
        _metric_card("Thất bại 5%", f"{_fmt(ref.get('failure_5pct_rate'))}%", "không đi đủ 5%"),
    ]
    cards_table = Table([cards], colWidths=[4.0 * cm] * 4, hAlign="CENTER")
    cards_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0ece3")), ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d8d0c2")), ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d8d0c2")), ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9)]))
    story.append(cards_table)
    story.append(Spacer(1, 0.35 * cm))
    story.append(Paragraph("Kết quả quan trọng", _STYLES["H1"]))
    story.append(_table(_results_snapshot_rows(ref, target, events), [4.0 * cm, 12.3 * cm]))
    story.append(
        _callout(
            "Điểm đáng chú ý",
            _notable_findings(ref, target, events),
        )
    )
    for paragraph in ai["summary"]:
        story.append(_p(paragraph, _STYLES["Body"]))
    story.append(_image(charts["schematic"], 16.2))
    story.append(_p(str(ai_captions.get("schematic") or "Sơ đồ minh họa cấu trúc: cột cờ đi lên, thân cờ ngắn, phiên phá vỡ và mục tiêu cơ sở. Các ví dụ thực tế trong chương đều lấy từ VN100 hoặc VN30."), _STYLES["Caption"]))
    story.append(Spacer(1, 0.18 * cm))

    story.append(_section_title("1", "Mẫu hình hoạt động ra sao", "Tour ngắn trước khi đi vào quy tắc nhận diện"))
    for paragraph in ai["tour"]:
        story.append(_p(paragraph, _STYLES["Body"]))
    story.append(
        _table(
            [
                ["Bước đọc", "Câu hỏi cần trả lời"],
                ["Cột cờ", "Nhịp tăng trước đó có đủ nhanh, đủ dốc và đủ rõ không?"],
                ["Thân cờ", "Giá có nghỉ trong một kênh ngắn, hẹp và không phá cấu trúc tăng không?"],
                ["Phá vỡ", "Giá đóng cửa có vượt lên khỏi thân cờ không?"],
                ["Đường đi sau đó", "Mục tiêu có đến trước khi giá kéo ngược sâu không, và giá có kiểm định lại vùng phá vỡ không?"],
            ],
            [4.0 * cm, 12.3 * cm],
        )
    )
    story.append(_p("Cách đọc này giữ đúng tinh thần một chương mẫu hình: trước hết mô tả hình thái, sau đó mới đo kết quả. Nếu đảo ngược trình tự và chọn hình theo kết quả đã biết, toàn bộ con số phía sau sẽ mất ý nghĩa.", _STYLES["Body"]))

    story.append(_section_title("2", "Cách nhận diện", "Quy tắc hình học trước, kết quả phía sau"))
    story.append(_p("Cờ tăng chỉ có ý nghĩa khi xuất hiện sau một nhịp tăng nhanh. Phần thân cờ là đoạn nghỉ ngắn, thường hơi nghiêng xuống hoặc đi ngang, nằm trong hai đường biên tương đối song song. Mẫu chỉ được xác nhận khi giá đóng cửa vượt ra khỏi biên trên của thân cờ.", _STYLES["Body"]))
    story.append(Paragraph("Các quy tắc nhận diện được dùng", _STYLES["H2"]))
    rule_rows = [["Quy tắc", "Cách áp dụng trong dữ liệu Việt Nam"]]
    wanted = {"bf.prior_trend.steep_up", "bf.shape.parallel_channel", "bf.duration.max_three_weeks", "bf.breakout.close_above_trendline", "bf.volume.downward_context", "bf.measure.pole_height_legacy"}
    for rule in source_rules:
        if rule.get("rule_id") in wanted:
            rule_rows.append([str(rule.get("short_excerpt")).replace("Steep, quick price trend", "Xu hướng giá nhanh và dốc").replace("Price action bounded by two parallel trend lines.", "Giá nằm trong hai đường xu hướng song song.").replace("Flags are short, from a few days to 3 weeks.", "Thân cờ ngắn, từ vài ngày đến khoảng ba tuần.").replace("price closes outside the flag trend line", "Giá đóng cửa ra ngoài đường xu hướng của thân cờ.").replace("Volume usually trends downward throughout the formation.", "Khối lượng thường giảm trong thời gian hình thành mẫu.").replace("Calculate the price difference between the start of the trend and the formation.", "Đo chiều cao cột cờ từ điểm bắt đầu xu hướng tới vùng hình thành thân cờ."), _vi_rule_mapping(rule.get("implementation_mapping"))])
    story.append(_table(rule_rows, [5.8 * cm, 10.5 * cm]))
    story.append(
        _table(
            [
                ["Thành phần", "Ý nghĩa thực tế", "Tham số hiện tại"],
                ["Cột cờ", "Nhịp tăng nhanh trước vùng nghỉ; đây là phần quan trọng nhất.", "Nhìn lại 40 phiên; tăng tối thiểu 10%; độ dốc tối thiểu 8 độ."],
                ["Thân cờ", "Vùng nghỉ ngắn, thường nghiêng nhẹ ngược hướng tăng trước đó.", "Dài 5-25 phiên; cao 3-15%; thân cờ không quá 55% cột cờ."],
                ["Hai đường biên", "Giá nằm trong kênh tương đối song song.", "Sai lệch độ dốc tối đa 4 độ."],
                ["Phá vỡ", "Chỉ sau phiên xác nhận mới đo kết quả.", "Đóng cửa vượt biên trên với ngưỡng 0,75%; tìm trong 12 phiên."],
                ["Khối lượng", "Khối lượng giảm là dấu hiệu hỗ trợ, không phải điều kiện bắt buộc.", "Ghi nhận riêng, không dùng làm cổng loại trực tiếp."],
            ],
            [3.0 * cm, 7.0 * cm, 6.3 * cm],
        )
    )
    story.append(
        _callout(
            "Điểm loại nhanh",
            [
                "Không có cột cờ rõ: nếu nhịp tăng trước đó yếu, mẫu chỉ là vùng đi ngang sau nhiễu giá.",
                "Thân cờ quá dài: cờ tăng là mẫu nghỉ ngắn; kéo dài quá lâu dễ chuyển thành kênh giá hoặc nền tích lũy.",
                "Phá vỡ không bằng giá đóng cửa: chỉ xuyên biên trong phiên nhưng đóng cửa yếu chưa đủ để xác nhận sự kiện.",
                "Khối lượng và đường giá bẩn: phiên không có khối lượng, thiếu phiên hoặc sự kiện quyền gần phá vỡ khiến mẫu khó tin hơn.",
            ],
        )
    )
    story.append(Paragraph("Khi nên đọc thận trọng", _STYLES["H2"]))
    story.append(_table(_skip_conditions_rows(events), [4.0 * cm, 3.5 * cm, 8.8 * cm]))
    story.append(_section_title("3", "Ví dụ minh họa", "Một ví dụ đẹp, một ví dụ trung vị và một ví dụ thất bại"))
    examples = _select_examples(events)
    example_specs = [
        ("textbook_success", "Ví dụ đạt mục tiêu", "Trường hợp này đi đúng hướng và chạm mục tiêu trước khi xuất hiện bất lợi 5%. Đây là hình ảnh điển hình của một cờ tăng hoạt động tốt."),
        ("middle_case", "Ví dụ trung vị", "Trường hợp này gần trung vị của mẫu: giá có đi thuận lợi, nhưng không đủ xa để hoàn thành mục tiêu đầy đủ. Đây là kiểu ví dụ quan trọng hơn các biểu đồ quá đẹp."),
        ("failure", "Ví dụ thất bại", "Trường hợp này thất bại theo ngưỡng 5%. Nó nhắc rằng hình thái hợp lệ không đồng nghĩa với bảo đảm tiếp diễn."),
    ]
    for key, title, caption in example_specs:
        event = examples[key]
        story.append(
            KeepTogether(
                [
                    Paragraph(title, _STYLES["H2"]),
                    _image(charts[key], 16.0),
                    _p(
                        str(ai_captions.get(key) or f"{caption} Mã {event['symbol']}, ngày phá vỡ {event['breakout_date']}, mức tăng tốt nhất {_fmt(event['mfe_pct'])}%, mức kéo ngược sâu nhất {_fmt(event['mae_pct'])}%, đạt mục tiêu: {_vi_bool(event['target_hit'])}, thất bại 5%: {_vi_bool(event['failure_5pct'])}."),
                        _STYLES["Caption"],
                    ),
                ]
            )
        )

    story.append(Paragraph("Diễn biến mẫu hoàn chỉnh", _STYLES["H2"]))
    story.append(_table(_sample_walkthrough_rows(examples["textbook_success"]), [3.5 * cm, 5.0 * cm, 7.8 * cm]))
    story.append(_p("Bảng diễn biến này thay cho kiểu 'giao dịch mẫu': nó dẫn người đọc qua từng mốc của một mẫu thành công, nhưng không biến ví dụ thành chỉ dẫn mua bán.", _STYLES["Body"]))

    story.append(_section_title("4", "Tập trung vào thất bại", "Thất bại là một phần của hồ sơ mẫu hình, không phải phụ lục"))
    for paragraph in ai["failure"]:
        story.append(_p(paragraph, _STYLES["Body"]))
    story.append(
        _table(
            [
                ["Dạng thất bại", "Dấu hiệu trong dữ liệu", "Cách xử lý khi đọc chương"],
                ["Không đi đủ 5%", f"{_fmt(ref.get('failure_5pct_rate'))}% mẫu không đạt ngưỡng tăng tối thiểu.", "Không xem hình thái đẹp là đủ; phải kiểm tra mức tăng sau phá vỡ."],
                ["Kéo ngược sâu trước mục tiêu", f"Tỷ lệ đạt mục tiêu trước khi bị kéo ngược mạnh ở mục tiêu cơ sở là {_fmt(target.get('base_target', {}).get('target_first_before_adverse_5pct_rate'))}%.", "Ưu tiên thứ tự đường đi, không chỉ tỷ lệ đạt mục tiêu cuối kỳ."],
                ["Thân cờ dài hoặc rộng", f"Độ dài trung vị {events['pattern_width_bars'].median():.0f} phiên; chiều cao trung vị {_fmt(float(events['pattern_height_pct'].median()))}%.", "Cờ quá dài dễ gần kênh giá hoặc hình chữ nhật hơn là mẫu tiếp diễn ngắn."],
                ["Kiểm định lại sâu sau phá vỡ", "Được đo ở phần hành vi sau phá vỡ bằng dấu hiệu kiểm định lại.", "Kiểm định lại không tự động xấu, nhưng cần đọc cùng mức kéo ngược sâu nhất và thời gian đạt mục tiêu."],
            ],
            [4.1 * cm, 5.6 * cm, 6.6 * cm],
        )
    )
    story.append(
        _callout(
            "Quy tắc đọc thất bại",
            [
                "Ví dụ thất bại không bị loại khỏi chương: nó là một phần của phân phối thật và giúp tránh thiên lệch chỉ chọn biểu đồ đẹp.",
                "Thất bại 5% khác ngưỡng rủi ro: thất bại 5% đo việc không đi đủ thuận lợi; ngưỡng rủi ro đo đường đi bất lợi theo giả định thực tế.",
                "Mẫu hợp lệ vẫn có thể xấu: hình thái chỉ là điều kiện nhận diện; chất lượng nằm ở xác nhận, đường đi và bối cảnh.",
            ],
        )
    )
    story.append(_section_title("5", "Cách đọc kết quả quan trọng", "Biến số liệu thành quyết định đọc biểu đồ"))
    story.append(_p("Một chương mẫu hình tốt không bắt người đọc tự bơi trong bảng số. Với cờ tăng, ba con số cần nhớ là: mục tiêu cơ sở 0,46x, thất bại 5%, và mức kéo ngược sâu nhất. Ba con số này trả lời ba câu hỏi khác nhau: mẫu thường đi được bao xa, mẫu sai bao nhiêu, và đường đi có gọn hay không.", _STYLES["Body"]))
    for paragraph in ai["statistics"]:
        story.append(_p(paragraph, _STYLES["Body"]))
    story.append(
        _table(
            [
                ["Câu hỏi của người đọc", "Con số cần nhìn", "Cách đọc thực tế"],
                ["Mẫu có đi tiếp không?", f"0,46x đạt {_fmt(target.get('base_target', {}).get('target_hit_rate'))}%", "Mốc cơ sở cho thấy nhịp tiếp diễn vừa phải có xuất hiện khá thường xuyên."],
                ["Mốc đầy đủ có nên là kỳ vọng chính?", f"1,0x đạt {_fmt(target.get('legacy_target', {}).get('target_hit_rate'))}%", "Không. Đây là mốc tham chiếu căng, dùng để biết mẫu chạy xa tới đâu khi rất thuận lợi."],
                ["Đường đi có dễ chịu không?", f"Mức kéo ngược sâu nhất trung vị {_fmt(ref.get('median_mae_pct'))}%", "Cần đọc cùng mức tăng tốt nhất; mẫu tốt là mẫu đi tiếp mà không kéo ngược quá sâu."],
                ["Mẫu sai bao nhiêu?", f"Thất bại 5% {_fmt(ref.get('failure_5pct_rate'))}%", "Đây là lý do không được chỉ chọn ví dụ đẹp hoặc chỉ nhìn tỷ lệ đạt mục tiêu."],
            ],
            [4.2 * cm, 4.2 * cm, 7.9 * cm],
        )
    )
    story.append(Paragraph("Mục tiêu giá", _STYLES["H2"]))
    target_table = [["Mục tiêu", "Vai trò", "Tỷ lệ đạt", "Đạt trước kéo ngược", "Cách đọc"]]
    for row in target_rows:
        role = {
            "bulkowski_adjusted_base": "cơ sở",
            "rounded_local_base": "cơ sở làm tròn",
            "local_stretch": "mục tiêu mở rộng",
            "legacy_full_pole": "mốc đầy đủ",
        }.get(str(row.get("target_role")), row.get("target_role"))
        reading = "mốc nên đọc đầu tiên" if row.get("target_multiple") == 0.46 else ("mốc căng, không dùng một mình" if row.get("target_multiple") == 1.0 else "mốc trung gian để so độ nhạy")
        target_table.append([f"{row.get('target_multiple')}x", role, f"{_fmt(row.get('target_hit_rate'))}%", f"{_fmt(row.get('target_first_before_adverse_5pct_rate'))}%", reading])
    story.append(_table(target_table, [1.6 * cm, 3.2 * cm, 2.2 * cm, 2.7 * cm, 6.6 * cm]))
    story.append(_p("Diễn giải: nếu chỉ dùng mốc 1,0x, cờ tăng trông yếu hơn thực tế; nếu chỉ dùng mốc 0,46x, người đọc có thể dễ dãi quá mức. Cách đọc đúng là dùng 0,46x làm mốc cơ sở và giữ 1,0x như mốc chạy xa.", _STYLES["Body"]))

    story.append(_section_title("6", "Sau phá vỡ nên nhìn gì", "Không chỉ đi bao xa, mà còn đi như thế nào"))
    for paragraph in ai["post_breakout"]:
        story.append(_p(paragraph, _STYLES["Body"]))
    story.append(
        _table(
            [
                ["Dấu hiệu sau phá vỡ", "Cách đọc"],
                ["Giá đi tiếp nhanh", "Mẫu đang giữ đúng tính chất tiếp diễn ngắn."],
                ["Giá quay lại kiểm định vùng phá vỡ", "Không tự động xấu; cần xem quay lại nhẹ hay kéo ngược sâu."],
                ["Kéo ngược sâu trước mục tiêu", "Chất lượng đường đi giảm, dù sau đó giá có thể vẫn đạt mục tiêu."],
                ["Không đi được 5%", "Đưa mẫu vào nhóm thất bại, không dùng làm ví dụ thành công."],
            ],
            [5.2 * cm, 11.1 * cm],
        )
    )
    story.append(_p("Vì vậy, câu hỏi sau phá vỡ không phải chỉ là giá có tăng hay không. Câu hỏi đúng hơn là: giá tăng có đủ sớm, đủ gọn và ít kéo ngược để giữ được ý nghĩa của một mẫu tiếp diễn ngắn không.", _STYLES["Body"]))

    story.append(_section_title("7", "Khi mẫu đáng chú ý hơn", "Các điều kiện làm cờ tăng dễ đọc hơn"))
    for paragraph in ai["size_volume"]:
        story.append(_p(paragraph, _STYLES["Body"]))
    story.append(_table(_best_conditions_rows(events), [4.0 * cm, 1.4 * cm, 2.0 * cm, 2.4 * cm, 2.0 * cm, 4.5 * cm]))
    story.append(_p("Các điều kiện trên không phải bộ lọc cứng. Chúng là thứ tự ưu tiên khi đọc biểu đồ: cột cờ rõ, thân cờ gọn, đường giá sạch và bối cảnh không chống lại mẫu.", _STYLES["Body"]))

    story.append(_section_title("8", "Cách sử dụng thực tế", "Giữ ranh giới giữa tài liệu tham khảo và tín hiệu mua bán"))
    for paragraph in ai["tactics"]:
        story.append(_p(paragraph, _STYLES["Body"]))
    story.append(Paragraph("Checklist đọc mẫu", _STYLES["H2"]))
    for item in ai["checklist"]:
        story.append(_bullet(item, _STYLES["Body"]))
    story.append(
        _callout(
            "Tóm tắt thực hành",
            [
                "Đọc cờ tăng như một mẫu tiếp diễn ngắn, không như một nền tích lũy dài.",
                "Ưu tiên mục tiêu 0,46x-0,50x; xem 1,00x là mốc chạy xa.",
                "Không bỏ qua thất bại 5% và mức kéo ngược sâu nhất.",
                "Ví dụ thành công, ví dụ trung vị và ví dụ thất bại đều cần có trong cùng chương.",
            ],
        )
    )
    story.append(_table(_quick_conclusion_rows(events, target, ref), [4.0 * cm, 12.3 * cm]))

    story.append(PageBreak())
    story.append(_section_title("A", "Phụ lục kỹ thuật", "Các bảng chi tiết để kiểm tra lại số liệu"))
    story.append(_p("Phần chính phía trên được viết cho người đọc biểu đồ. Các bảng dưới đây giữ lại lớp kiểm tra chi tiết: phân bố, bối cảnh, chất lượng dữ liệu và giả định thử nghiệm. Chúng giúp audit chương, nhưng không nên là cách đọc đầu tiên.", _STYLES["Body"]))
    story.append(Paragraph("Bức tranh tổng quát", _STYLES["H2"]))
    story.append(_table(_general_statistics_rows(events, ref), [4.1 * cm, 5.2 * cm, 7.0 * cm]))
    story.append(Paragraph("Vùng thường gặp và vùng cực trị", _STYLES["H2"]))
    story.append(_table(_quantile_rows(events), [4.0 * cm, 1.8 * cm, 1.8 * cm, 1.8 * cm, 1.8 * cm, 1.8 * cm, 2.1 * cm]))
    story.append(Paragraph("Hành vi sau phá vỡ", _STYLES["H2"]))
    story.append(_table(_post_breakout_rows(events, path_df), [4.4 * cm, 4.6 * cm, 7.3 * cm]))
    story.append(Paragraph("Khi giá kéo ngược và phá hỏng mẫu", _STYLES["H2"]))
    story.append(_table(_stop_and_bust_rows(events), [4.4 * cm, 4.6 * cm, 7.3 * cm]))

    story.append(_section_title("B", "Phụ lục bối cảnh", "Kích thước, khối lượng, trạng thái thị trường và nhóm cổ phiếu"))
    story.append(Paragraph("Kích thước và khối lượng", _STYLES["H2"]))
    story.append(_table(_size_volume_rows(events), [4.3 * cm, 1.4 * cm, 2.2 * cm, 2.4 * cm, 2.2 * cm, 2.0 * cm, 2.0 * cm]))
    story.append(Paragraph("Phá vỡ, xu hướng khối lượng và vị trí trong năm", _STYLES["H2"]))
    story.append(_table(_breakout_context_rows(events), [4.3 * cm, 1.4 * cm, 2.2 * cm, 2.4 * cm, 2.2 * cm, 2.0 * cm, 2.0 * cm]))
    story.append(Paragraph("Bối cảnh thị trường", _STYLES["H2"]))
    story.append(_table(_context_rows(ref.get("regime_proxy_table", {}), "Trạng thái"), [3.2 * cm, 1.4 * cm, 2.2 * cm, 2.4 * cm, 2.2 * cm, 2.2 * cm, 2.2 * cm]))
    story.append(Paragraph("Theo thanh khoản", _STYLES["H2"]))
    story.append(_table(_context_rows(ref.get("liquidity_proxy_table", {}), "Thanh khoản"), [3.2 * cm, 1.4 * cm, 2.2 * cm, 2.4 * cm, 2.2 * cm, 2.2 * cm, 2.2 * cm]))
    story.append(Paragraph("Theo nhóm cổ phiếu", _STYLES["H2"]))
    story.append(_table(_context_rows_from_events(events, "market_group", "Nhóm"), [3.2 * cm, 1.4 * cm, 2.2 * cm, 2.4 * cm, 2.2 * cm, 2.2 * cm, 2.2 * cm]))

    story.append(_section_title("C", "Phụ lục kiểm tra thực tế", "Ma sát giao dịch và giới hạn dữ liệu"))
    story.append(_p("Nếu thử đưa mẫu vào thực tế, cần thêm giả định vào lệnh, thoát lệnh, chi phí, trượt giá, thuế bán, quy mô vị thế và thời gian giữ. Phần này chỉ kiểm tra độ hợp lý của số liệu, không biến chương thành khuyến nghị giao dịch.", _STYLES["Body"]))
    story.append(
        _table(
            [
                ["Thành phần", "Giả định kiểm tra"],
                ["Vào lệnh", f"Giá mở cửa sau phiên phá vỡ {selected.get('entry_delay_bars')} phiên."],
                ["Thoát lệnh", "Chạm mục tiêu 0,46 lần cột cờ, chạm ngưỡng rủi ro, hoặc hết thời gian nắm giữ."],
                ["Ngưỡng rủi ro / thời gian", f"Ngưỡng rủi ro {selected.get('stop_loss_pct')}%; nắm giữ tối đa {selected.get('max_holding_days')} phiên."],
                ["Chi phí", f"Phí {selected.get('commission_bps_per_side')} điểm cơ bản mỗi chiều; trượt giá {selected.get('slippage_bps_per_side')} điểm cơ bản mỗi chiều; thuế bán {selected.get('sell_tax_bps')} điểm cơ bản."],
                ["Quy mô vị thế", f"Mỗi vị thế {selected.get('position_size_pct')}; tối đa {selected.get('max_positions')} vị thế; tỷ lệ tham gia ADTV trung vị {selected.get('median_adtv_participation_pct')}%."],
                ["Kiểm tra ngoài mẫu", f"Lợi suất tập xác nhận {selected.get('validation_total_return_pct')}%; tập giữ lại {selected.get('holdout_total_return_pct')}%; tỷ lệ lát kiểm định dương {tradable.get('walk_forward_summary', {}).get('positive_fold_rate_pct')}%."],
            ],
            [4.0 * cm, 12.3 * cm],
        )
    )
    story.append(Paragraph("Chất lượng dữ liệu", _STYLES["H2"]))
    story.append(_table(_data_quality_rows(events), [4.2 * cm, 4.8 * cm, 7.3 * cm]))
    story.append(Paragraph("Giới hạn phải ghi rõ", _STYLES["H2"]))
    story.append(_p("Chương này được viết cho phạm vi dữ liệu hiện có. Nó đủ để làm tài liệu tham khảo có điều kiện cho mẫu cờ tăng, nhưng chưa được phép đọc như một bản bao phủ lịch sử theo từng thời điểm của toàn thị trường Việt Nam.", _STYLES["Body"]))
    for item in payload.get("data_scope_and_caveats", {}).get("remaining_caveats", []):
        vi = str(item).replace("corporate_action_audit", "kiểm tra điều chỉnh giá và quyền chưa đầy đủ").replace("delisted_halted_status", "trạng thái hủy niêm yết/tạm ngừng chưa đầy đủ").replace("membership_history_db", "lịch sử thành phần chỉ số chưa đầy đủ").replace("membership_not_point_in_time", "nhóm VN30/VN100 chưa theo từng thời điểm").replace("point_in_time_universe", "danh sách toàn thị trường chưa theo từng thời điểm")
        story.append(_bullet(vi, _STYLES["Body"]))
    story.append(
        _callout(
            "Kết luận chương",
            [
                "Cờ tăng là mẫu tiếp diễn ngắn có giá trị đọc hậu phá vỡ tốt nhất khi mục tiêu được hiệu chuẩn theo 0,46 lần chiều cao cột cờ.",
                "Mẫu không nên được đánh giá bằng một tỷ lệ đạt mục tiêu duy nhất; cần đọc cùng thất bại 5%, mức kéo ngược sâu nhất, kiểm định lại và chất lượng đường giá.",
                "Trong phạm vi dữ liệu hiện có, cờ tăng đã đủ làm chương mẫu đầu tiên cho khung Việt Nam; phần chưa thể nâng tiếp nằm ở dữ liệu theo từng thời điểm và audit chính thức.",
            ],
        )
    )
    return story


def build_public_chapter(
    events_path: Path = DEFAULT_EVENTS,
    path_path: Path = DEFAULT_PATH,
    publication_payload_path: Path = DEFAULT_PUBLICATION_PAYLOAD,
    source_notes_path: Path = DEFAULT_SOURCE_NOTES,
    price_db: Path = DEFAULT_PRICE_DB,
    out_dir: Path = DEFAULT_OUT_DIR,
    ai_sections_path: Path | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    events = pd.read_csv(events_path)
    path_df = pd.read_csv(path_path)
    payload = _read_json(publication_payload_path)
    source_notes = _read_json(source_notes_path)
    charts = _build_example_charts(events, price_db, out_dir)
    audit_json_path, audit_md_path = build_content_parity_audit(out_dir)

    pdf_path = out_dir / "bull_flag_public_chapter.pdf"
    notes_path = out_dir / "bull_flag_public_chapter_notes.md"
    manuscript_path = out_dir / "bull_flag_ai_editorial_manuscript.md"
    payload_path = out_dir / "bull_flag_public_chapter_payload.json"

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=1.45 * cm,
        rightMargin=1.45 * cm,
        topMargin=1.35 * cm,
        bottomMargin=1.25 * cm,
        title="Cờ tăng - Chương xuất bản",
        author="Codex",
    )
    doc.build(build_story(payload, source_notes, events, path_df, charts, ai_sections_path=ai_sections_path), onFirstPage=_header_footer, onLaterPages=_header_footer)

    notes_path.write_text(
        "\n".join(
            [
                "# Ghi chú chương cờ tăng",
                "",
                "Bản này được dựng như một chương đọc cho nhà đầu tư, không phải tài liệu release-gate nội bộ.",
                "",
                "Cấu trúc chương: tóm tắt, cách nhận diện, tour mẫu hình, ví dụ trong VN100, thất bại, thống kê, hậu phá vỡ, kích thước/khối lượng, bối cảnh, cách sử dụng, giới hạn.",
                "",
                f"PDF: `{pdf_path}`",
                f"Biểu đồ: `{out_dir / 'charts'}`",
                f"Audit nội bộ: `{audit_md_path}`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    ai_sections = build_ai_editorial_sections(payload, events)
    external_ai = _load_ai_editorial_sections(ai_sections_path)
    if external_ai.get("sections"):
        ai_sections.update(external_ai["sections"])
    manuscript_lines = ["# Bản thảo diễn giải AI cho chương cờ tăng", ""]
    for title, paragraphs in [
        ("Tóm tắt", ai_sections["summary"]),
        ("Mẫu hình hoạt động ra sao", ai_sections["tour"]),
        ("Thất bại", ai_sections["failure"]),
        ("Thống kê", ai_sections["statistics"]),
        ("Hành vi sau phá vỡ", ai_sections["post_breakout"]),
        ("Kích thước và khối lượng", ai_sections["size_volume"]),
        ("Cách sử dụng", ai_sections["tactics"]),
        ("Checklist", ai_sections["checklist"]),
    ]:
        manuscript_lines.extend([f"## {title}", ""])
        for paragraph in paragraphs:
            manuscript_lines.extend([paragraph, ""])
    manuscript_path.write_text("\n".join(manuscript_lines).strip() + "\n", encoding="utf-8")
    payload_path.write_text(
        json.dumps(
            {
                "source_notes": source_notes,
                "publication_payload": payload,
                "ai_editorial_sections": ai_sections,
                "ai_sections_source": str(ai_sections_path) if ai_sections_path else None,
                "example_events": {key: dict(value) for key, value in _select_examples(events).items()},
                "charts": {key: str(value) for key, value in charts.items()},
                "content_parity_audit": str(audit_json_path),
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "pdf": pdf_path,
        "notes": notes_path,
        "manuscript": manuscript_path,
        "payload": payload_path,
        "content_parity_audit_json": audit_json_path,
        "content_parity_audit_md": audit_md_path,
        **{f"chart_{key}": path for key, path in charts.items()},
    }


def main() -> None:
    require_legacy_publication_builder_enabled("scanner/_legacy_quarantine/build_bull_flag_public_chapter.py")
    parser = argparse.ArgumentParser(description="Build the public-facing Bull Flag chapter.")
    parser.add_argument("--events", default=str(DEFAULT_EVENTS))
    parser.add_argument("--path", default=str(DEFAULT_PATH))
    parser.add_argument("--publication-payload", default=str(DEFAULT_PUBLICATION_PAYLOAD))
    parser.add_argument("--source-notes", default=str(DEFAULT_SOURCE_NOTES))
    parser.add_argument("--price-db", default=str(DEFAULT_PRICE_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--ai-sections", default=None)
    args = parser.parse_args()
    paths = build_public_chapter(
        events_path=Path(args.events),
        path_path=Path(args.path),
        publication_payload_path=Path(args.publication_payload),
        source_notes_path=Path(args.source_notes),
        price_db=Path(args.price_db),
        out_dir=Path(args.out_dir),
        ai_sections_path=Path(args.ai_sections) if args.ai_sections else None,
    )
    for key, path in paths.items():
        print(f"{key}: {path}")


_FONT_REGULAR, _FONT_BOLD = _register_fonts()
_STYLES = _styles(_FONT_REGULAR, _FONT_BOLD)


if __name__ == "__main__":
    main()
