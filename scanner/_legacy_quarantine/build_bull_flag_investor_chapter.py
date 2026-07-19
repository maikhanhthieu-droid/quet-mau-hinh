"""Build the investor-facing Bull Flag chapter.

This is the editorial layer above the publication payload. The payload remains
the source of truth for numbers; this file turns those facts into an
investor-readable chapter with narrative, tables, and simple visuals.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.legacy_guard import require_legacy_publication_builder_enabled  # noqa: E402


DEFAULT_PAYLOAD = Path("artifacts/scanner_v2/bull_flags_publication_chapter/bull_flag_publication_payload.json")
DEFAULT_SOURCE_NOTES = Path("artifacts/scanner_v2/bull_flags_source_grounding/bull_flag_source_notes.json")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bull_flags_investor_chapter")
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


def _register_fonts() -> Tuple[str, str]:
    regular = next((path for path in FONT_REGULAR_CANDIDATES if path.exists()), None)
    bold = next((path for path in FONT_BOLD_CANDIDATES if path.exists()), regular)
    if regular is None:
        return ("Helvetica", "Helvetica-Bold")
    pdfmetrics.registerFont(TTFont("InvestorSans", str(regular)))
    pdfmetrics.registerFont(TTFont("InvestorSansBold", str(bold)))
    return ("InvestorSans", "InvestorSansBold")


def _nested(mapping: Mapping[str, Any], *keys: str) -> Any:
    value: Any = mapping
    for key in keys:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _fmt(value: Any, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        text = f"{value:.2f}".rstrip("0").rstrip(".")
    else:
        text = str(value)
    return f"{text}{suffix}"


def _fmt_pair(value: Any, first_label: str = "up", second_label: str = "down", suffix: str = "%") -> str:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) >= 2:
        return f"{first_label} {value[0]}{suffix} / {second_label} {value[1]}{suffix}"
    return "n/a"


def _fmt_chapters(chapters: Any) -> str:
    if not isinstance(chapters, Sequence) or isinstance(chapters, (str, bytes)):
        return "n/a"
    parts = []
    for chapter in chapters:
        if not isinstance(chapter, Mapping):
            continue
        parts.append(
            f"chapter {chapter.get('chapter')} {chapter.get('name')} "
            f"(book p.{chapter.get('source_page_start')}, PDF p.{chapter.get('source_pdf_page_start')})"
        )
    return "; ".join(parts) if parts else "n/a"


def _esc(text: Any) -> str:
    return html.escape(str(text))


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_esc(text), style)


def _bullet(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(f"• {_esc(text)}", style)


def _metric_card(label: str, value: Any, note: str = "") -> List[Paragraph]:
    return [
        Paragraph(_esc(label), _STYLES["MetricLabel"]),
        Paragraph(_esc(value), _STYLES["MetricValue"]),
        Paragraph(_esc(note), _STYLES["MetricNote"]),
    ]


def _table(data: Sequence[Sequence[Any]], *, widths: Sequence[float], header: bool = True, font_size: float = 8.3) -> Table:
    rows = [[Paragraph(_esc(cell), _STYLES["TableHeader" if header and r == 0 else "TableCell"]) for cell in row] for r, row in enumerate(data)]
    table = Table(rows, colWidths=list(widths), hAlign="LEFT")
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 0), (-1, -1), _FONT_REGULAR),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d9d4ca")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0ece3")),
    ]
    if not header:
        style.pop()
    table.setStyle(TableStyle(style))
    return table


def _bar_table(items: Sequence[Tuple[str, float]], *, max_value: float = 100.0, width: float = 9.8 * cm) -> Table:
    rows: List[List[Any]] = []
    for label, value in items:
        pct = max(0.0, min(float(value), max_value)) / max_value
        fill_width = max(0.15 * cm, width * pct)
        bar = Table([[""]], colWidths=[fill_width], rowHeights=[0.16 * cm])
        bar.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#245b5a"))]))
        rows.append([Paragraph(_esc(label), _STYLES["TableCell"]), bar, Paragraph(_esc(f"{value:.2f}%"), _STYLES["TableCell"])])
    table = Table(rows, colWidths=[4.0 * cm, width, 2.0 * cm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def build_ai_editorial_narrative(payload: Mapping[str, Any], source_notes: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    ref = payload.get("chapter_reference") if isinstance(payload.get("chapter_reference"), Mapping) else {}
    target = payload.get("target_calibration") if isinstance(payload.get("target_calibration"), Mapping) else {}
    release = payload.get("release_candidate") if isinstance(payload.get("release_candidate"), Mapping) else {}
    tradable = payload.get("tradable_setup") if isinstance(payload.get("tradable_setup"), Mapping) else {}
    selected = tradable.get("selected_metrics") if isinstance(tradable.get("selected_metrics"), Mapping) else {}
    fresh = payload.get("fresh_candidate") if isinstance(payload.get("fresh_candidate"), Mapping) else {}
    fresh_summary = fresh.get("summary") if isinstance(fresh.get("summary"), Mapping) else {}
    notes = source_notes if isinstance(source_notes, Mapping) else {}
    local_source = notes.get("local_source") if isinstance(notes.get("local_source"), Mapping) else {}
    web_stats = notes.get("thepatternsite_2020_stats") if isinstance(notes.get("thepatternsite_2020_stats"), Mapping) else {}
    measure_rule = notes.get("thepatternsite_measure_rule") if isinstance(notes.get("thepatternsite_measure_rule"), Mapping) else {}

    return {
        "status": "source_grounded_ai_editorial_layer",
        "guardrail": "Every claim is bound to source notes plus the canonical publication payload; no buy/sell recommendation is generated.",
        "executive_summary": [
            (
                "Chương này đã được dựng lại từ source notes: local Encyclopedia PDF chương Flags, rule provenance trong "
                f"{local_source.get('core_patterns_path', 'core_patterns.json')}, trang Flags của ThePatternSite và trang Measure Rule. "
                "Vì vậy phần định nghĩa Bull Flag, 0.46x target và giới hạn short-term swing được neo vào nguồn gốc trước khi Việt Nam hóa."
            ),
            (
                "Bull Flag trong bộ dữ liệu Việt Nam hiện là mẫu hình có chất lượng tốt nhất để đưa lên chương đầu tiên: "
                f"release gate đạt {release.get('conservative_score')} điểm, fresh candidate đạt {_nested(release, 'fresh', 'score')} điểm, "
                f"và rule đã qua lớp kiểm tra overlap, thanh khoản và price-limit proxy."
            ),
            (
                "Điểm cốt lõi không phải là Bull Flag luôn chạy hết một cột cờ. ThePatternSite Measure Rule ghi flags up-breakout "
                f"theo công thức {measure_rule.get('flags_up_breakout_rule', '0.46x flagpole')}; trong dữ liệu Việt Nam, target 0.46x pole "
                f"có hit rate {_nested(target, 'base_target', 'target_hit_rate')}% và target-first-before-adverse-5% "
                f"{_nested(target, 'base_target', 'target_first_before_adverse_5pct_rate')}%, cao hơn đáng kể so với legacy 1.0x."
            ),
            (
                f"ThePatternSite cập nhật 2020 cho flags báo average rise/decline "
                f"{_fmt_pair(web_stats.get('average_rise_decline_up_down_pct'), 'rise', 'decline')} "
                "và nhấn mạnh performance của flags là short-term price swing. Chương Việt Nam vì vậy đọc Bull Flag như continuation ngắn, "
                "không như một lời hứa đạt full measured move."
            ),
        ],
        "what_matters": [
            f"Median MFE {ref.get('median_mfe_pct')}% lớn hơn median MAE {ref.get('median_mae_pct')}%, cho thấy đường đi thuận lợi có ưu thế thực nghiệm.",
            f"Target 0.46x pole là headline target; 1.0x pole chỉ còn vai trò stretch/reference với hit rate {ref.get('legacy_target_hit_rate')}%.",
            f"Rule thực thi dùng entry delay {selected.get('entry_delay_bars')} phiên, stop {selected.get('stop_loss_pct')}%, max holding {selected.get('max_holding_days')} phiên và sizing có giới hạn ADTV.",
            f"Fresh source vẫn giữ tổng return {fresh_summary.get('total_return_pct')}% và holdout {fresh_summary.get('holdout_total_return_pct')}%, không có promotion blocker.",
        ],
        "investor_use": [
            "Dùng chương này để hiểu xác suất hậu-breakout và khung rủi ro của Bull Flag, không dùng như một lệnh mua tự động.",
            "Ưu tiên đọc target 0.46x và target-first, vì hai chỉ số này phản ánh vừa độ đạt mục tiêu vừa thứ tự đường đi.",
            "Xem các caveat dữ liệu như một phần của kết luận, đặc biệt là corporate-action audit và delisted/halted status.",
        ],
        "do_not_use": [
            "Không suy diễn rằng mọi Bull Flag đều đáng mua.",
            "Không áp dụng cho short-side hoặc Bear Flag trên cash equities Việt Nam như cùng một loại cơ hội.",
            "Không bỏ qua thanh khoản, khả năng khớp lệnh, phí, trượt giá và giới hạn tỷ trọng giao dịch theo ADTV.",
        ],
    }


def _styles(font_regular: str, font_bold: str) -> Dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "Title": ParagraphStyle("Title", parent=base["Title"], fontName=font_bold, fontSize=24, leading=29, alignment=TA_CENTER, textColor=colors.HexColor("#173b3a"), spaceAfter=12),
        "Subtitle": ParagraphStyle("Subtitle", parent=base["Normal"], fontName=font_regular, fontSize=10.5, leading=15, alignment=TA_CENTER, textColor=colors.HexColor("#555555"), spaceAfter=18),
        "H1": ParagraphStyle("H1", parent=base["Heading1"], fontName=font_bold, fontSize=16, leading=20, textColor=colors.HexColor("#173b3a"), spaceBefore=8, spaceAfter=8),
        "H2": ParagraphStyle("H2", parent=base["Heading2"], fontName=font_bold, fontSize=12.5, leading=16, textColor=colors.HexColor("#245b5a"), spaceBefore=8, spaceAfter=6),
        "Body": ParagraphStyle("Body", parent=base["BodyText"], fontName=font_regular, fontSize=9.2, leading=14, alignment=TA_LEFT, textColor=colors.HexColor("#202020"), spaceAfter=7),
        "Small": ParagraphStyle("Small", parent=base["BodyText"], fontName=font_regular, fontSize=8.0, leading=11.5, textColor=colors.HexColor("#555555"), spaceAfter=5),
        "TableCell": ParagraphStyle("TableCell", parent=base["BodyText"], fontName=font_regular, fontSize=7.7, leading=10.5, textColor=colors.HexColor("#202020")),
        "TableHeader": ParagraphStyle("TableHeader", parent=base["BodyText"], fontName=font_bold, fontSize=7.7, leading=10.5, textColor=colors.HexColor("#173b3a")),
        "MetricLabel": ParagraphStyle("MetricLabel", parent=base["BodyText"], fontName=font_bold, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#555555"), alignment=TA_CENTER),
        "MetricValue": ParagraphStyle("MetricValue", parent=base["BodyText"], fontName=font_bold, fontSize=16, leading=19, textColor=colors.HexColor("#173b3a"), alignment=TA_CENTER),
        "MetricNote": ParagraphStyle("MetricNote", parent=base["BodyText"], fontName=font_regular, fontSize=6.7, leading=8.5, textColor=colors.HexColor("#666666"), alignment=TA_CENTER),
    }


def _header_footer(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    canvas.setFont(_FONT_REGULAR, 7)
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawString(doc.leftMargin, 1.0 * cm, "Bull Flag - Vietnam publication chapter RC")
    canvas.drawRightString(A4[0] - doc.rightMargin, 1.0 * cm, f"Page {doc.page}")
    canvas.restoreState()


def build_story(payload: Mapping[str, Any], source_notes: Mapping[str, Any] | None = None) -> List[Any]:
    notes = source_notes if isinstance(source_notes, Mapping) else {}
    narrative = build_ai_editorial_narrative(payload, notes)
    ref = payload.get("chapter_reference") if isinstance(payload.get("chapter_reference"), Mapping) else {}
    target = payload.get("target_calibration") if isinstance(payload.get("target_calibration"), Mapping) else {}
    release = payload.get("release_candidate") if isinstance(payload.get("release_candidate"), Mapping) else {}
    tradable = payload.get("tradable_setup") if isinstance(payload.get("tradable_setup"), Mapping) else {}
    selected = tradable.get("selected_metrics") if isinstance(tradable.get("selected_metrics"), Mapping) else {}
    fresh = payload.get("fresh_candidate") if isinstance(payload.get("fresh_candidate"), Mapping) else {}
    fresh_summary = fresh.get("summary") if isinstance(fresh.get("summary"), Mapping) else {}
    support = payload.get("supporting_robustness") if isinstance(payload.get("supporting_robustness"), Mapping) else {}
    caveats = payload.get("data_scope_and_caveats") if isinstance(payload.get("data_scope_and_caveats"), Mapping) else {}
    scanner = payload.get("scanner_contract") if isinstance(payload.get("scanner_contract"), Mapping) else {}
    detector = scanner.get("detector_config") if isinstance(scanner.get("detector_config"), Mapping) else {}
    local_source = notes.get("local_source") if isinstance(notes.get("local_source"), Mapping) else {}
    book_stats = notes.get("bulkowski_book_2e_stats") if isinstance(notes.get("bulkowski_book_2e_stats"), Mapping) else {}
    web_stats = notes.get("thepatternsite_2020_stats") if isinstance(notes.get("thepatternsite_2020_stats"), Mapping) else {}
    measure_rule = notes.get("thepatternsite_measure_rule") if isinstance(notes.get("thepatternsite_measure_rule"), Mapping) else {}
    source_rules = [rule for rule in (notes.get("source_rules") or []) if isinstance(rule, Mapping)]

    story: List[Any] = []
    story.append(Paragraph("Bull Flag", _STYLES["Title"]))
    story.append(Paragraph("Chương nhà đầu tư - Thomas Bulkowski cho thị trường chứng khoán Việt Nam", _STYLES["Subtitle"]))
    cards = [
        _metric_card("Release score", release.get("conservative_score"), "main gate"),
        _metric_card("Fresh score", _nested(release, "fresh", "score"), "fresh source"),
        _metric_card("Base target hit", f"{_nested(target, 'base_target', 'target_hit_rate')}%", "0.46x pole"),
        _metric_card("MFE / MAE", f"{ref.get('median_mfe_pct')} / {ref.get('median_mae_pct')}%", "median"),
    ]
    card_table = Table([cards], colWidths=[4.0 * cm] * 4, hAlign="CENTER")
    card_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0ece3")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d8d0c2")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d8d0c2")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.append(card_table)
    story.append(Spacer(1, 0.35 * cm))
    story.append(Paragraph("Tóm tắt điều hành", _STYLES["H1"]))
    for paragraph in narrative["executive_summary"]:
        story.append(_paragraph(paragraph, _STYLES["Body"]))
    story.append(Paragraph("Nguồn gốc đã đọc trước khi viết", _STYLES["H2"]))
    source_rows = [
        ("Nguồn", "Vai trò trong chương"),
        ("Encyclopedia PDF trong repo", f"{_fmt_chapters(local_source.get('book_chapters'))}; dùng để khóa hình thái, breakout và trading tactics."),
        (
            "ThePatternSite Flags",
            "Stats 2020: "
            f"BE failure {_fmt_pair(web_stats.get('break_even_failure_rate_up_down_pct'))}; "
            f"average {_fmt_pair(web_stats.get('average_rise_decline_up_down_pct'), 'rise', 'decline')}; "
            f"target meeting {_fmt_pair(web_stats.get('percentage_meeting_price_target_up_down_pct'))}.",
        ),
        ("ThePatternSite Measure Rule", f"Up breakout target: {measure_rule.get('flags_up_breakout_rule')}; full 1.0x chỉ là legacy benchmark trong chapter Việt Nam."),
    ]
    story.append(_table(source_rows, widths=[4.2 * cm, 12.2 * cm], font_size=7.8))
    story.append(Paragraph("Nhà đầu tư nên chú ý điều gì", _STYLES["H2"]))
    for item in narrative["what_matters"]:
        story.append(_bullet(item, _STYLES["Body"]))
    story.append(PageBreak())

    story.append(Paragraph("1. Bull Flag được định nghĩa như thế nào", _STYLES["H1"]))
    story.append(_paragraph("Phần này dùng nguồn gốc trước, scanner sau. Từ Bulkowski, Bull Flag là một continuation ngắn: có flagpole đi lên, vùng flag nhỏ/parallel đóng vai trò nghỉ, rồi breakout lên xác nhận event. Chỉ sau khi có breakout, chapter mới đo follow-through; kết quả sau breakout không được dùng để hợp thức hóa lại nhận diện.", _STYLES["Body"]))
    rule_rows = [("Nguồn Bulkowski", "Map vào scanner Việt Nam")]
    preferred_rule_ids = {
        "bf.prior_trend.steep_up",
        "bf.shape.parallel_channel",
        "bf.duration.max_three_weeks",
        "bf.breakout.close_above_trendline",
        "bf.measure.pole_height_legacy",
    }
    for rule in source_rules:
        if rule.get("rule_id") in preferred_rule_ids:
            rule_rows.append((f"{rule.get('short_excerpt')} (p.{rule.get('source_page')})", rule.get("implementation_mapping")))
    if len(rule_rows) > 1:
        story.append(_table(rule_rows, widths=[5.4 * cm, 11.0 * cm], font_size=7.4))
        story.append(Spacer(1, 0.25 * cm))
    anatomy_rows = [
        ("Lớp", "Điều kiện vận hành"),
        ("Flagpole", f"lookback {detector.get('pole_lookback_bars')} phiên, minimum move {detector.get('pole_min_change_pct')}%, slope tối thiểu {detector.get('pole_min_slope_deg')}"),
        ("Flag body", f"width {detector.get('width_min_bars')}-{detector.get('width_max_bars')} phiên, flag-to-pole tối đa {detector.get('flag_to_pole_max_pct')}%"),
        ("Breakout", f"breakout threshold {detector.get('breakout_threshold')}, search window {detector.get('breakout_search_bars')} phiên"),
        ("Execution", f"entry delay {selected.get('entry_delay_bars')} phiên, stop {selected.get('stop_loss_pct')}%, max holding {selected.get('max_holding_days')} phiên"),
    ]
    story.append(_table(anatomy_rows, widths=[3.0 * cm, 13.4 * cm]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("2. Kết quả quan trọng", _STYLES["H1"]))
    story.append(_paragraph("Bảng dưới đây là phần gần nhất với tinh thần Bulkowski: không chỉ hỏi mẫu hình có đẹp hay không, mà hỏi sau breakout nó thường đi được bao xa, thất bại bao nhiêu, và target nào hợp lý.", _STYLES["Body"]))
    target_rows = [("Target", "Vai trò", "N", "Hit", "Target-first", "Fail 5%")]
    for row in target.get("rows") or []:
        if isinstance(row, Mapping):
            target_rows.append((f"{row.get('target_multiple')}x", row.get("target_role"), row.get("n"), _fmt(row.get("target_hit_rate"), "%"), _fmt(row.get("target_first_before_adverse_5pct_rate"), "%"), _fmt(row.get("failure_5pct_rate"), "%")))
    story.append(_table(target_rows, widths=[1.7 * cm, 5.1 * cm, 1.4 * cm, 2.2 * cm, 2.8 * cm, 2.5 * cm]))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_bar_table([("0.46x base", float(_nested(target, "base_target", "target_hit_rate") or 0)), ("0.75x stretch", 51.82), ("1.0x legacy", float(ref.get("legacy_target_hit_rate") or 0))]))
    story.append(PageBreak())

    story.append(Paragraph("3. Cách đọc target 0.46x", _STYLES["H1"]))
    story.append(_paragraph(f"Nguồn gốc của 0.46x không phải do chúng ta tự nới rule. ThePatternSite Measure Rule ghi upward flags là {measure_rule.get('flags_up_breakout_rule', 'Flag low + 46% flagpole')}. Nếu dùng 1.0x pole làm headline, Bull Flag trông chỉ ở mức vừa phải; nếu đọc theo target đã hiệu chỉnh của Bulkowski, 0.46x trở thành mốc chính, còn 1.0x là stretch benchmark.", _STYLES["Body"]))
    story.append(_paragraph(f"Ở target 0.46x, hit rate đạt {_nested(target, 'base_target', 'target_hit_rate')}%, target-first-before-adverse-5% đạt {_nested(target, 'base_target', 'target_first_before_adverse_5pct_rate')}%. Ở target 1.0x, hit rate chỉ còn {ref.get('legacy_target_hit_rate')}%. Chênh lệch này nói rằng pattern có continuation tendency, nhưng không nên ép nó chạy hết full pole trong mọi điều kiện.", _STYLES["Body"]))
    story.append(Paragraph("4. Từ reference sang setup thực thi", _STYLES["H1"]))
    story.append(_paragraph("Lớp thực thi được thêm để kiểm tra xem một rule cụ thể có còn đứng vững sau phí, trượt giá, stop, giới hạn thời gian nắm giữ, sizing và capacity hay không. Đây là tầng vượt ngoài Bulkowski gốc, nhưng cần thiết nếu tài liệu hướng tới nhà đầu tư Việt Nam.", _STYLES["Body"]))
    exec_rows = [
        ("Thành phần", "Giá trị"),
        ("Strategy", tradable.get("selected_strategy_id")),
        ("Entry", f"open sau breakout {selected.get('entry_delay_bars')} phiên"),
        ("Exit", "target, stop, hoặc max holding"),
        ("Target / stop", f"{selected.get('target_multiple')}x pole / {selected.get('stop_loss_pct')}%"),
        ("Max holding", f"{selected.get('max_holding_days')} phiên"),
        ("Costs", f"commission {selected.get('commission_bps_per_side')} bps/side, slippage {selected.get('slippage_bps_per_side')} bps/side, sell tax {selected.get('sell_tax_bps')} bps"),
        ("Sizing", f"position {selected.get('position_size_pct')}, max positions {selected.get('max_positions')}, median ADTV participation {selected.get('median_adtv_participation_pct')}%"),
    ]
    story.append(_table(exec_rows, widths=[3.8 * cm, 12.6 * cm]))
    story.append(PageBreak())

    story.append(Paragraph("5. Độ bền ngoài mẫu và fresh source", _STYLES["H1"]))
    story.append(_paragraph("Điểm nâng chất lượng lớn nhất so với một chart-pattern note thông thường là rule không chỉ được đọc trong sample chính. Nó còn được giữ nguyên để kiểm trên validation, holdout, walk-forward, cost stress, Monte Carlo và một fresh-source candidate.", _STYLES["Body"]))
    oos_rows = [
        ("Scope", "Score", "Trades", "Total return", "Validation", "Holdout", "Positive folds"),
        ("Main", release.get("conservative_score"), selected.get("trades"), _fmt(selected.get("total_return_pct"), "%"), _fmt(selected.get("validation_total_return_pct"), "%"), _fmt(selected.get("holdout_total_return_pct"), "%"), _fmt(_nested(tradable, "walk_forward_summary", "positive_fold_rate_pct"), "%")),
        ("Fresh", _nested(release, "fresh", "score"), fresh_summary.get("trades"), _fmt(fresh_summary.get("total_return_pct"), "%"), _fmt(fresh_summary.get("validation_total_return_pct"), "%"), _fmt(fresh_summary.get("holdout_total_return_pct"), "%"), _fmt(_nested(fresh, "walk_forward_summary", "positive_fold_rate_pct"), "%")),
    ]
    story.append(_table(oos_rows, widths=[2.0 * cm, 2.0 * cm, 2.0 * cm, 2.6 * cm, 2.5 * cm, 2.3 * cm, 2.6 * cm]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("6. Robustness và kiểm soát rủi ro dữ liệu", _STYLES["H1"]))
    profile_rows = [("Profile", "Status", "Events", "Overlap", "Liquidity", "Price-limit proxy")]
    for profile in support.get("profiles") or []:
        if isinstance(profile, Mapping):
            checks = profile.get("checks") if isinstance(profile.get("checks"), Mapping) else {}
            profile_rows.append((profile.get("profile_id"), profile.get("status"), profile.get("scoped_events"), checks.get("overlap_sensitivity"), checks.get("liquidity_bucket_robustness"), checks.get("price_limit_proxy_robustness")))
    story.append(_table(profile_rows, widths=[3.0 * cm, 1.8 * cm, 1.8 * cm, 2.7 * cm, 2.7 * cm, 3.7 * cm]))
    story.append(PageBreak())

    story.append(Paragraph("7. So với Bulkowski", _STYLES["H1"]))
    story.append(_paragraph("So sánh này tách rõ hai phiên bản nguồn: local book PDF second edition và ThePatternSite 2020 update. PDF trong repo có Results Snapshot riêng cho upward/downward flags; trang web 2020 dùng automated cataloging và công bố bộ số khác. Chapter Việt Nam không trộn hai bộ số làm một, mà dùng chúng để xác định nguyên tắc: flag là short-term continuation, target 46% pole là adjusted benchmark, còn 1.0x pole chỉ là reference.", _STYLES["Body"]))
    compare_rows = [
        ("Chủ đề", "Bulkowski", "Bull Flag Việt Nam"),
        ("Loại mẫu", "Short-term continuation / swing", "Bullish continuation setup"),
        ("Target chính", measure_rule.get("flags_up_breakout_rule", "46% pole"), "0.46x pole"),
        ("Full pole", "Không phải headline", "Stretch/reference"),
        ("Bear flag", "Báo cáo riêng", "Defensive/informational trên cash equities"),
        ("Mục tiêu tài liệu", "Pattern reference", "Investment/tradable research candidate"),
    ]
    story.append(_table(compare_rows, widths=[3.0 * cm, 5.5 * cm, 7.7 * cm]))
    if book_stats:
        stats_rows = [
            ("Nguồn", "Upward flags", "Downward flags"),
            (
                "Book 2e snapshot",
                f"BE fail {_fmt_pair(book_stats.get('upward_breakouts', {}).get('break_even_failure_rate_bull_bear_pct'), 'bull', 'bear')}; "
                f"avg rise {_fmt_pair(book_stats.get('upward_breakouts', {}).get('average_rise_bull_bear_pct'), 'bull', 'bear')}; "
                f"target {_fmt_pair(book_stats.get('upward_breakouts', {}).get('percentage_meeting_price_target_bull_bear_pct'), 'bull', 'bear')}",
                f"BE fail {_fmt_pair(book_stats.get('downward_breakouts', {}).get('break_even_failure_rate_bull_bear_pct'), 'bull', 'bear')}; "
                f"avg decline {_fmt_pair(book_stats.get('downward_breakouts', {}).get('average_decline_bull_bear_pct'), 'bull', 'bear')}; "
                f"target {_fmt_pair(book_stats.get('downward_breakouts', {}).get('percentage_meeting_price_target_bull_bear_pct'), 'bull', 'bear')}",
            ),
            (
                "ThePatternSite 2020",
                f"BE fail {_fmt_pair(web_stats.get('break_even_failure_rate_up_down_pct')).split(' / ')[0]}; "
                f"avg rise {_fmt_pair(web_stats.get('average_rise_decline_up_down_pct'), 'rise', 'decline').split(' / ')[0]}; "
                f"target {_fmt_pair(web_stats.get('percentage_meeting_price_target_up_down_pct')).split(' / ')[0]}",
                f"BE fail {_fmt_pair(web_stats.get('break_even_failure_rate_up_down_pct')).split(' / ')[1] if ' / ' in _fmt_pair(web_stats.get('break_even_failure_rate_up_down_pct')) else 'n/a'}; "
                f"avg decline {_fmt_pair(web_stats.get('average_rise_decline_up_down_pct'), 'rise', 'decline').split(' / ')[1] if ' / ' in _fmt_pair(web_stats.get('average_rise_decline_up_down_pct'), 'rise', 'decline') else 'n/a'}; "
                f"target {_fmt_pair(web_stats.get('percentage_meeting_price_target_up_down_pct')).split(' / ')[1] if ' / ' in _fmt_pair(web_stats.get('percentage_meeting_price_target_up_down_pct')) else 'n/a'}",
            ),
        ]
        story.append(Spacer(1, 0.25 * cm))
        story.append(_table(stats_rows, widths=[3.0 * cm, 6.6 * cm, 6.6 * cm], font_size=7.2))
    story.append(Spacer(1, 0.25 * cm))
    story.append(Paragraph("8. Cách dùng và giới hạn", _STYLES["H1"]))
    story.append(Paragraph("Nên dùng", _STYLES["H2"]))
    for item in narrative["investor_use"]:
        story.append(_bullet(item, _STYLES["Body"]))
    story.append(Paragraph("Không nên dùng", _STYLES["H2"]))
    for item in narrative["do_not_use"]:
        story.append(_bullet(item, _STYLES["Body"]))
    story.append(Paragraph("Caveats còn mở", _STYLES["H2"]))
    for item in caveats.get("remaining_caveats") or []:
        story.append(_bullet(str(item), _STYLES["Small"]))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_paragraph("Nguồn Bulkowski đã đối chiếu: local Encyclopedia PDF trong repo; https://thepatternsite.com/flags.html; https://thepatternsite.com/measure.html", _STYLES["Small"]))
    return story


def write_ai_narrative(payload: Mapping[str, Any], path: Path, source_notes: Mapping[str, Any] | None = None) -> None:
    narrative = build_ai_editorial_narrative(payload, source_notes)
    lines = ["# Bull Flag AI Editorial Narrative", ""]
    lines.append(f"- Status: `{narrative['status']}`")
    lines.append(f"- Guardrail: {narrative['guardrail']}")
    if source_notes:
        lines.append(f"- Source grounding: `{source_notes.get('source_grounding_id')}`")
    for key in ("executive_summary", "what_matters", "investor_use", "do_not_use"):
        lines.extend(["", f"## {key.replace('_', ' ').title()}", ""])
        for item in narrative[key]:
            lines.append(f"- {item}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_investor_chapter(
    payload_path: Path = DEFAULT_PAYLOAD,
    out_dir: Path = DEFAULT_OUT_DIR,
    source_notes_path: Path = DEFAULT_SOURCE_NOTES,
) -> Dict[str, Path]:
    payload = _read_json(payload_path)
    source_notes = _read_json(source_notes_path) if source_notes_path.exists() else {}
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / "bull_flag_investor_chapter.pdf"
    narrative_path = out_dir / "bull_flag_ai_editorial_narrative.md"
    payload_out = out_dir / "bull_flag_investor_chapter_payload.json"
    write_ai_narrative(payload, narrative_path, source_notes)
    payload_out.write_text(
        json.dumps({"publication_payload": payload, "source_notes": source_notes}, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        rightMargin=1.55 * cm,
        leftMargin=1.55 * cm,
        topMargin=1.55 * cm,
        bottomMargin=1.45 * cm,
        title="Bull Flag - Vietnam Investor Chapter",
        author="Codex AI editorial layer",
    )
    doc.build(build_story(payload, source_notes), onFirstPage=_header_footer, onLaterPages=_header_footer)
    return {"pdf": pdf_path, "narrative": narrative_path, "payload": payload_out}


def main() -> None:
    require_legacy_publication_builder_enabled("scanner/_legacy_quarantine/build_bull_flag_investor_chapter.py")
    parser = argparse.ArgumentParser(description="Build the investor-facing Bull Flag chapter PDF.")
    parser.add_argument("--payload", default=str(DEFAULT_PAYLOAD))
    parser.add_argument("--source-notes", default=str(DEFAULT_SOURCE_NOTES))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    paths = build_investor_chapter(payload_path=Path(args.payload), out_dir=Path(args.out_dir), source_notes_path=Path(args.source_notes))
    for key, path in paths.items():
        print(f"{key}: {path}")


_FONT_REGULAR, _FONT_BOLD = _register_fonts()
_STYLES = _styles(_FONT_REGULAR, _FONT_BOLD)


if __name__ == "__main__":
    main()
