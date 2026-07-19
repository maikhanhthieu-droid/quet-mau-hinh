"""Shared primitives for canonical public chapter rendering.

This module is intentionally small and contains only presentational helpers:
styles, text escaping, public formatting, tables, callouts, metric cards, and
image sizing. It exists so the canonical publication core does not import any
legacy chapter builder for UI primitives.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, Table, TableStyle


FONT_REGULAR_CANDIDATES = (
    Path("/opt/homebrew/Cellar/python-matplotlib/3.10.7/libexec/lib/python3.14/site-packages/matplotlib/mpl-data/fonts/ttf/DejaVuSans.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
)
FONT_BOLD_CANDIDATES = (
    Path("/opt/homebrew/Cellar/python-matplotlib/3.10.7/libexec/lib/python3.14/site-packages/matplotlib/mpl-data/fonts/ttf/DejaVuSans-Bold.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
)


def _register_fonts() -> tuple[str, str]:
    regular = next((path for path in FONT_REGULAR_CANDIDATES if path.exists()), None)
    bold = next((path for path in FONT_BOLD_CANDIDATES if path.exists()), regular)
    if regular is None:
        return ("Helvetica", "Helvetica-Bold")
    pdfmetrics.registerFont(TTFont("PublicSans", str(regular)))
    pdfmetrics.registerFont(TTFont("PublicSansBold", str(bold)))
    return ("PublicSans", "PublicSansBold")


def _styles(font_regular: str, font_bold: str) -> dict[str, ParagraphStyle]:
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


PUBLIC_TEXT_REPLACEMENTS = (
    ("tổng mẫu quét lịch sử", "tổng mẫu lịch sử"),
    ("Tổng mẫu quét lịch sử", "Tổng mẫu lịch sử"),
    ("mẫu quét lịch sử", "mẫu lịch sử"),
    ("Mẫu quét lịch sử", "Mẫu lịch sử"),
    ("tổng mẫu quét", "tổng mẫu lịch sử"),
    ("Tổng mẫu quét", "Tổng mẫu lịch sử"),
    ("mẫu quét", "mẫu lịch sử"),
    ("Mẫu quét", "Mẫu lịch sử"),
    ("approved_human_sections", "nội dung biên tập đã duyệt"),
    ("source_full_pipe", "mốc đầy đủ"),
    ("Tham số hiện tại", "Dấu hiệu cần thấy"),
    ("Spike", "Cú xuyên giá"),
    ("spike", "cú xuyên giá"),
    ("Overlap", "Vùng chồng lấn"),
    ("overlap", "vùng chồng lấn"),
    ("MFE trung vị 60 ngày", "mức tăng tốt nhất trung vị 60 ngày"),
    ("MAE trung vị 60 ngày", "mức kéo ngược sâu nhất trung vị 60 ngày"),
    ("MFE", "mức tăng tốt nhất"),
    ("MAE", "mức kéo ngược sâu nhất"),
    ("Biên thuận lợi", "Mức tăng tốt nhất"),
    ("biên thuận lợi", "mức tăng tốt nhất"),
    ("Biên bất lợi", "Mức kéo ngược sâu nhất"),
    ("biên bất lợi", "mức kéo ngược sâu nhất"),
    ("target-first-before-adverse", "đạt mục tiêu trước khi bị kéo ngược mạnh"),
    ("target-first", "đạt mục tiêu trước kéo ngược"),
    ("target-hit", "đạt mục tiêu"),
    ("Target-hit", "Đạt mục tiêu"),
    ("Breakout", "Phá vỡ"),
    ("breakout", "phá vỡ"),
    ("half-staff", "nửa cột cờ"),
    ("path-level", "theo đường giá"),
    ("point-in-time", "theo từng thời điểm"),
    ("corporate-action", "sự kiện quyền và điều chỉnh giá"),
    ("available-series", "dữ liệu hiện có"),
    ("research-only", "chỉ dùng cho nghiên cứu"),
    ("setup", "cấu hình"),
    ("proxy", "đại diện"),
    ("scanner", "bộ quét"),
    ("Scanner", "Bộ quét"),
    ("pipeline", "quy trình"),
    ("payload", "bộ dữ liệu chương"),
    ("factory", "bộ dựng chương"),
    ("low-liquidity", "thanh khoản thấp"),
    ("data_limited", "thiếu dữ liệu"),
    ("data-limited", "thiếu dữ liệu"),
    ("watchlist-reference", "tham khảo theo dõi"),
    ("visual validation", "kiểm tra hình thái bằng mắt"),
    ("overclaim", "nói quá"),
    ("outcome", "kết quả"),
    ("dừng lỗ", "ngưỡng rủi ro"),
    ("Dừng lỗ", "Ngưỡng rủi ro"),
)


def _public_text(value: Any) -> str:
    text = str(value)
    for old, new in PUBLIC_TEXT_REPLACEMENTS:
        text = text.replace(old, new)
    return (
        text.replace("dữ liệu hiện có-series", "dữ liệu hiện có")
        .replace("nghiên cứu candidate", "ứng viên nghiên cứu")
        .replace("cấu hình-quality", "chất lượng cấu hình")
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
    table = Table([[Paragraph(_esc(number), _STYLES["SectionNo"]), content]], colWidths=[1.05 * cm, 15.35 * cm], hAlign="LEFT")
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


def _image(path: Path, width_cm: float) -> Image:
    img = Image(str(path), width=width_cm * cm, height=0)
    iw, ih = img.imageWidth, img.imageHeight
    img.drawWidth = width_cm * cm
    img.drawHeight = img.drawWidth * ih / iw
    return img


_FONT_REGULAR, _FONT_BOLD = _register_fonts()
_STYLES = _styles(_FONT_REGULAR, _FONT_BOLD)
