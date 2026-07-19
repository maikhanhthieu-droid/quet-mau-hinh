"""Build Edition 1 from the final publication chapters.

This builder creates a book-level PDF, not a pattern chapter. It keeps the
chapter PDFs as the source of truth, removes their technical appendices, and
adds book front matter plus a table of contents with absolute PDF pages.
"""

from __future__ import annotations

import json
from io import BytesIO
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
from pypdf import PageObject, PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as reportlab_canvas
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
FINAL_MANIFEST = ROOT / "artifacts" / "final_chapters" / "final_chapters_manifest.json"
RANKING_PDF = ROOT / "artifacts" / "book_level" / "bulkowski_style_rankings_final.pdf"
OUT_DIR = ROOT / "artifacts" / "book_level" / "edition_1"
EDITION_PDF = OUT_DIR / "bulkowski_vietnam_edition_1.pdf"
EDITION_MANIFEST = OUT_DIR / "bulkowski_vietnam_edition_1_manifest.json"
FRONT_MATTER_PDF = OUT_DIR / "edition_1_front_matter.pdf"
COVER_PDF = OUT_DIR / "edition_1_cover.pdf"
ASSETS_DIR = ROOT / "assets"
DEFAULT_BOOK_LOGO = ASSETS_DIR / "book_logo.png"

FONT_REGULAR_CANDIDATES = (
    Path("/opt/homebrew/Cellar/python-matplotlib/3.10.7/libexec/lib/python3.14/site-packages/matplotlib/mpl-data/fonts/ttf/DejaVuSans.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
)
FONT_BOLD_CANDIDATES = (
    Path("/opt/homebrew/Cellar/python-matplotlib/3.10.7/libexec/lib/python3.14/site-packages/matplotlib/mpl-data/fonts/ttf/DejaVuSans-Bold.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
)

FAMILY_ORDER = [
    "broadening_family",
    "bump_and_run_family",
    "cup_handle_family",
    "dead_cat_bounce_family",
    "diamond_family",
    "double_pattern_family",
    "flag_family",
    "gap_family",
    "head_shoulders_family",
    "horn_family",
    "inside_day_family",
    "island_family",
    "measured_move_family",
    "pipe_family",
    "rectangle_family",
    "rounding_family",
    "scallop_family",
    "three_methods_family",
    "three_peaks_valleys_family",
    "triangle_family",
    "triple_family",
    "wedge_family",
]

FAMILY_LABELS = {
    "broadening_family": "Broadening Family",
    "bump_and_run_family": "Bump-and-Run Family",
    "cup_handle_family": "Cup with Handle Family",
    "dead_cat_bounce_family": "Dead-Cat Bounce Family",
    "diamond_family": "Diamond Family",
    "double_pattern_family": "Double Pattern Family",
    "flag_family": "Flag Family",
    "gap_family": "Gap Family",
    "head_shoulders_family": "Head-and-Shoulders Family",
    "horn_family": "Horn Family",
    "inside_day_family": "Inside Day Family",
    "island_family": "Island Family",
    "measured_move_family": "Measured Move Family",
    "pipe_family": "Pipe Family",
    "rectangle_family": "Rectangle Family",
    "rounding_family": "Rounding Family",
    "scallop_family": "Scallop Family",
    "three_methods_family": "Three Methods Family",
    "three_peaks_valleys_family": "Three Peaks/Valleys Family",
    "triangle_family": "Triangle Family",
    "triple_family": "Triple Family",
    "wedge_family": "Wedge Family",
}


@dataclass
class BookItem:
    kind: str
    title: str
    family: str
    source_pdf: Path
    source_pages: int
    included_pages: int
    meta: dict[str, Any] | None = None
    source_start_index: int = 0
    source_body_pages: int = 0
    start_page: int = 0
    end_page: int = 0
    appendix_removed: bool = False


def _pick_font(candidates: tuple[Path, ...]) -> Path:
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError("No Vietnamese-capable TTF font found")


def _register_fonts() -> tuple[str, str]:
    regular = _pick_font(FONT_REGULAR_CANDIDATES)
    bold = _pick_font(FONT_BOLD_CANDIDATES)
    pdfmetrics.registerFont(TTFont("EditionVN", str(regular)))
    pdfmetrics.registerFont(TTFont("EditionVNBold", str(bold)))
    return "EditionVN", "EditionVNBold"


def _styles(font_regular: str, font_bold: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "Title": ParagraphStyle(
            "EditionTitle",
            parent=base["Title"],
            fontName=font_bold,
            fontSize=25,
            leading=31,
            alignment=1,
            textColor=colors.HexColor("#173b3a"),
            spaceAfter=14,
        ),
        "Subtitle": ParagraphStyle(
            "EditionSubtitle",
            parent=base["BodyText"],
            fontName=font_regular,
            fontSize=11.5,
            leading=16,
            alignment=1,
            textColor=colors.HexColor("#555555"),
            spaceAfter=14,
        ),
        "H1": ParagraphStyle(
            "EditionH1",
            parent=base["Heading1"],
            fontName=font_bold,
            fontSize=16,
            leading=20,
            textColor=colors.HexColor("#173b3a"),
            spaceBefore=10,
            spaceAfter=7,
        ),
        "H2": ParagraphStyle(
            "EditionH2",
            parent=base["Heading2"],
            fontName=font_bold,
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#245b5a"),
            spaceBefore=6,
            spaceAfter=4,
        ),
        "Body": ParagraphStyle(
            "EditionBody",
            parent=base["BodyText"],
            fontName=font_regular,
            fontSize=9.2,
            leading=13.2,
            textColor=colors.HexColor("#202020"),
            spaceAfter=6,
        ),
        "Small": ParagraphStyle(
            "EditionSmall",
            parent=base["BodyText"],
            fontName=font_regular,
            fontSize=7.8,
            leading=10.5,
            textColor=colors.HexColor("#555555"),
            spaceAfter=3,
        ),
        "TableHeader": ParagraphStyle(
            "EditionTableHeader",
            parent=base["BodyText"],
            fontName=font_bold,
            fontSize=7.4,
            leading=9.2,
            textColor=colors.HexColor("#173b3a"),
        ),
        "TableCell": ParagraphStyle(
            "EditionTableCell",
            parent=base["BodyText"],
            fontName=font_regular,
            fontSize=7.2,
            leading=9.4,
            textColor=colors.HexColor("#202020"),
        ),
    }


def _p(text: Any, style: ParagraphStyle) -> Paragraph:
    value = "" if text is None else str(text)
    return Paragraph(value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), style)


def _table(rows: list[list[Any]], widths: list[float], styles: dict[str, ParagraphStyle]) -> Table:
    data = [
        [_p(cell, styles["TableHeader" if row_index == 0 else "TableCell"]) for cell in row]
        for row_index, row in enumerate(rows)
    ]
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d9d4ca")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0ece3")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fbfaf7")]),
            ]
        )
    )
    return table


def _footer(title: str, font_regular: str):
    def draw(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(font_regular, 7.2)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(doc.leftMargin, 0.72 * cm, title)
        canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 0.72 * cm, f"Trang {doc.page}")
        canvas.restoreState()

    return draw


def _resolve_book_logo() -> Path | None:
    override = os.environ.get("BOOK_LOGO_PATH")
    path = Path(override).expanduser() if override else DEFAULT_BOOK_LOGO
    if path.exists():
        return path
    for candidate in (
        ASSETS_DIR / "book_logo.jpg",
        ASSETS_DIR / "book_logo.jpeg",
    ):
        if candidate.exists():
            return candidate
    logo_candidates = sorted(
        p
        for p in ASSETS_DIR.glob("*")
        if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg"}
    )
    if len(logo_candidates) == 1:
        return logo_candidates[0]
    return None


def _draw_logo(pdf: reportlab_canvas.Canvas, logo_path: Path, x: float, y: float, box_size: float) -> None:
    image = ImageReader(str(logo_path))
    img_width, img_height = image.getSize()
    if img_width <= 0 or img_height <= 0:
        return
    scale = min(box_size / img_width, box_size / img_height)
    draw_width = img_width * scale
    draw_height = img_height * scale
    pdf.drawImage(
        image,
        x + (box_size - draw_width) / 2,
        y + (box_size - draw_height) / 2,
        width=draw_width,
        height=draw_height,
        mask="auto",
    )


def _build_cover_pdf(output: Path, chapter_count: int, family_count: int) -> None:
    font_regular, font_bold = _register_fonts()
    pdf = reportlab_canvas.Canvas(str(output), pagesize=A4)
    logo_path = _resolve_book_logo()
    width, height = A4
    bg = colors.HexColor("#102f2d")
    ink = colors.HexColor("#f2ead8")
    muted = colors.HexColor("#b8c4bd")
    gold = colors.HexColor("#c5a45d")
    teal = colors.HexColor("#6ca7a1")

    pdf.setFillColor(bg)
    pdf.rect(0, 0, width, height, stroke=0, fill=1)
    pdf.setFillColor(colors.HexColor("#0a1d1b"))
    pdf.rect(0, 0, 2.2 * cm, height, stroke=0, fill=1)
    pdf.setStrokeColor(gold)
    pdf.setLineWidth(1.0)
    pdf.line(2.2 * cm, 1.2 * cm, 2.2 * cm, height - 1.2 * cm)

    pdf.setStrokeColor(colors.HexColor("#1e4541"))
    pdf.setLineWidth(0.25)
    for i in range(12):
        y = 3.0 * cm + i * 1.45 * cm
        pdf.line(3.0 * cm, y, width - 2.0 * cm, y)
    for i in range(9):
        x = 3.0 * cm + i * 1.65 * cm
        pdf.line(x, 2.6 * cm, x, height - 2.5 * cm)

    chart_points = [
        (3.0 * cm, 8.0 * cm),
        (4.2 * cm, 9.6 * cm),
        (5.4 * cm, 8.7 * cm),
        (6.6 * cm, 11.5 * cm),
        (7.8 * cm, 10.6 * cm),
        (9.2 * cm, 13.2 * cm),
        (10.6 * cm, 12.1 * cm),
        (12.0 * cm, 15.0 * cm),
        (13.4 * cm, 14.0 * cm),
        (15.1 * cm, 17.2 * cm),
        (17.1 * cm, 16.0 * cm),
    ]
    pdf.setStrokeColor(colors.Color(0.75, 0.87, 0.82, alpha=0.45))
    pdf.setLineWidth(1.1)
    path = pdf.beginPath()
    path.moveTo(*chart_points[0])
    for point in chart_points[1:]:
        path.lineTo(*point)
    pdf.drawPath(path, stroke=1, fill=0)

    for idx, (x, y) in enumerate(chart_points[1:-1], start=1):
        high = y + (0.55 + (idx % 3) * 0.18) * cm
        low = y - (0.45 + (idx % 2) * 0.16) * cm
        pdf.setStrokeColor(teal if idx % 2 else gold)
        pdf.setLineWidth(0.8)
        pdf.line(x, low, x, high)
        pdf.setFillColor(teal if idx % 2 else colors.HexColor("#d7ba73"))
        pdf.rect(x - 0.08 * cm, y - 0.22 * cm, 0.16 * cm, 0.44 * cm, stroke=0, fill=1)

    pdf.setFillColor(gold)
    pdf.setFont(font_bold, 8.5)
    pdf.drawString(3.1 * cm, height - 4.0 * cm, "ATLAS MẪU HÌNH GIÁ")
    pdf.setFillColor(ink)
    pdf.setFont(font_bold, 31)
    pdf.drawString(3.1 * cm, height - 5.35 * cm, "Bulkowski")
    pdf.drawString(3.1 * cm, height - 6.65 * cm, "Việt Nam")
    pdf.setFont(font_regular, 12)
    pdf.setFillColor(muted)
    pdf.drawString(3.15 * cm, height - 7.55 * cm, "Thị trường chứng khoán Việt Nam")
    pdf.setStrokeColor(gold)
    pdf.setLineWidth(1.2)
    pdf.line(3.15 * cm, height - 8.05 * cm, 10.8 * cm, height - 8.05 * cm)

    pdf.setFont(font_regular, 9.5)
    pdf.setFillColor(colors.HexColor("#d8ded7"))
    cover_copy = [
        "Một hồ sơ thực chứng về nhận diện, phá vỡ, thất bại và hành vi hậu mẫu hình.",
        "Không phải hệ thống khuyến nghị giao dịch; dùng như bản đồ xác suất và bối cảnh.",
    ]
    y = height - 9.0 * cm
    for line in cover_copy:
        pdf.drawString(3.15 * cm, y, line)
        y -= 0.55 * cm

    pdf.setFillColor(colors.Color(1, 1, 1, alpha=0.08))
    pdf.roundRect(3.1 * cm, 2.25 * cm, width - 5.2 * cm, 2.05 * cm, 6, stroke=0, fill=1)
    pdf.setFillColor(ink)
    pdf.setFont(font_bold, 11)
    pdf.drawString(3.55 * cm, 3.52 * cm, "Ấn bản 1")
    pdf.setFont(font_regular, 8.8)
    pdf.setFillColor(muted)
    pdf.drawString(3.55 * cm, 3.0 * cm, f"{chapter_count} chương mẫu hình | {family_count} nhóm mẫu hình | bản đọc liền mạch")
    pdf.drawString(3.55 * cm, 2.52 * cm, "Dữ liệu Việt Nam trong phạm vi nguồn hiện có")
    if logo_path:
        logo_size = 1.35 * cm
        logo_x = width - 3.75 * cm
        logo_y = 2.58 * cm
        pdf.setFillColor(colors.Color(1, 1, 1, alpha=0.12))
        pdf.roundRect(logo_x - 0.12 * cm, logo_y - 0.12 * cm, logo_size + 0.24 * cm, logo_size + 0.24 * cm, 5, stroke=0, fill=1)
        _draw_logo(pdf, logo_path, logo_x, logo_y, logo_size)

    pdf.setFillColor(gold)
    pdf.setFont(font_bold, 8)
    pdf.saveState()
    pdf.translate(1.08 * cm, height / 2)
    pdf.rotate(90)
    pdf.drawCentredString(0, 0, "BULKOWSKI VIỆT NAM")
    pdf.restoreState()

    pdf.setTitle("Bulkowski Việt Nam - Edition 1 Cover")
    pdf.save()


def _load_manifest() -> dict[str, Any]:
    return json.loads(FINAL_MANIFEST.read_text(encoding="utf-8"))


def _chapter_sort_key(chapter: dict[str, Any]) -> tuple[int, int, str]:
    family = str(chapter.get("family") or "")
    try:
        family_index = FAMILY_ORDER.index(family)
    except ValueError:
        family_index = len(FAMILY_ORDER)
    return family_index, int(chapter.get("_manifest_order") or 0), str(chapter.get("pattern_id") or "")


BOOK_BODY_CUTOFF_MARKERS = (
    "Phụ lục kỹ thuật",
    "Đánh giá hai trục",
    "Chương đã qua cổng xuất bản",
)


def _book_body_cutoff(reader: PdfReader) -> tuple[int, str]:
    for index, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        normalized = " ".join(text.split())
        for marker in BOOK_BODY_CUTOFF_MARKERS:
            if marker in normalized:
                return index, marker
    return len(reader.pages), ""


def _trim_sparse_terminal_page(reader: PdfReader, cutoff_index: int) -> int:
    if cutoff_index <= 1:
        return cutoff_index
    text = reader.pages[cutoff_index - 1].extract_text() or ""
    normalized = " ".join(text.split())
    if "Kết luận chương" in normalized and len(normalized) < 750:
        return cutoff_index - 1
    return cutoff_index


def _build_items() -> list[BookItem]:
    manifest = _load_manifest()
    raw_chapters = []
    for index, chapter in enumerate(manifest.get("chapters", [])):
        raw_chapter = dict(chapter)
        raw_chapter["_manifest_order"] = index
        raw_chapters.append(raw_chapter)
    chapters = sorted(raw_chapters, key=_chapter_sort_key)
    ranking_reader = PdfReader(str(RANKING_PDF))
    items = [
        BookItem(
            kind="ranking",
            title="Xếp hạng mẫu hình",
            family="book_level",
            source_pdf=RANKING_PDF,
            source_pages=len(ranking_reader.pages),
            included_pages=len(ranking_reader.pages),
        )
    ]
    for chapter in chapters:
        pdf = ROOT / str(chapter.get("pdf") or "")
        reader = PdfReader(str(pdf))
        cutoff_index, _cutoff_marker = _book_body_cutoff(reader)
        cutoff_index = _trim_sparse_terminal_page(reader, cutoff_index)
        source_body_pages = max(1, cutoff_index)
        included = source_body_pages
        items.append(
            BookItem(
                kind="chapter",
                title=str(chapter.get("title") or chapter.get("pattern_id") or pdf.stem),
                family=str(chapter.get("family") or ""),
                source_pdf=pdf,
                source_pages=len(reader.pages),
                included_pages=included,
                meta=chapter,
                source_start_index=0,
                source_body_pages=source_body_pages,
                appendix_removed=included < len(reader.pages),
            )
        )
    return items


def _assign_pages(items: list[BookItem], front_count: int) -> None:
    page = front_count + 1
    for item in items:
        item.start_page = page
        item.end_page = page + item.included_pages - 1
        page = item.end_page + 1


def _build_front_matter(items: list[BookItem], output: Path) -> int:
    font_regular, font_bold = _register_fonts()
    styles = _styles(font_regular, font_bold)
    body_pdf = output.with_name("edition_1_front_matter_body.pdf")
    doc = SimpleDocTemplate(
        str(body_pdf),
        pagesize=A4,
        leftMargin=1.45 * cm,
        rightMargin=1.45 * cm,
        topMargin=1.35 * cm,
        bottomMargin=1.25 * cm,
        title="Bulkowski Việt Nam - Edition 1",
        author="Bulkowski Việt Nam",
    )
    story: list[Any] = []
    story.append(_p("Thông tin ấn bản", styles["H1"]))
    for paragraph in [
        "Bulkowski Việt Nam là một atlas về mẫu hình giá trên thị trường chứng khoán Việt Nam. Cuốn sách đi từ hình thái trên biểu đồ tới hành vi sau xác nhận: mẫu được nhận diện như thế nào, phá vỡ ở đâu, đi tiếp hay thất bại ra sao, và người đọc nên hiểu các con số ấy trong bối cảnh nào.",
        "Tinh thần của ấn bản này là thực chứng. Mỗi chương được viết như một hồ sơ mẫu hình: có mô tả nhận diện, ví dụ biểu đồ, bảng kết quả, phần diễn giải và cảnh báo sử dụng. Các con số không đứng riêng lẻ; chúng được đặt cạnh đường đi giá, xác suất thất bại, mức kéo ngược và độ bền qua từng nhóm kiểm tra.",
        "Cuốn sách không phải khuyến nghị mua bán chứng khoán. Nó cung cấp một bản đồ xác suất để người đọc hiểu mẫu hình nào đáng quan sát, mẫu nào chỉ nên dùng để cảnh báo rủi ro, và mẫu nào cần được đọc thận trọng vì dữ liệu hoặc đường đi sau xác nhận chưa đủ vững.",
    ]:
        story.append(_p(paragraph, styles["Body"]))
    info_rows = [
        ["Tên sách", "Bulkowski Việt Nam - Atlas mẫu hình giá trên thị trường chứng khoán Việt Nam"],
        ["Ấn bản", "Ấn bản thứ nhất"],
        ["Ngày tạo", datetime.now().strftime("%Y-%m-%d")],
        ["Số chương", f"{sum(1 for item in items if item.kind == 'chapter')} chương mẫu hình"],
        ["Phạm vi", "Mẫu hình giá trên cổ phiếu Việt Nam trong phạm vi dữ liệu lịch sử đã thu thập."],
        ["Bản quyền", "Sản phẩm là bản quyền của Bloger Chim Cut."],
        ["Phát hành", "Sản phẩm miễn phí cho cộng đồng."],
        ["Cách đọc", "Tài liệu tham khảo xác suất; không phải hệ thống tín hiệu giao dịch cá nhân hóa."],
    ]
    story.append(_table(info_rows, [3.5 * cm, 12.0 * cm], styles))
    story.append(Spacer(1, 0.35 * cm))
    story.append(_p("Tuyên bố bản quyền", styles["H2"]))
    for paragraph in [
        "Sản phẩm là bản quyền của Bloger Chim Cut. Ấn bản này được biên soạn để chia sẻ kiến thức về mẫu hình giá và cách đọc dữ liệu lịch sử trên thị trường chứng khoán Việt Nam.",
        "Sản phẩm miễn phí cho cộng đồng. Người đọc có thể sử dụng như tài liệu học tập và tham khảo; vui lòng giữ nguyên nguồn khi trích dẫn, chia sẻ hoặc sử dụng lại một phần nội dung.",
    ]:
        story.append(_p(paragraph, styles["Body"]))
    story.append(Spacer(1, 0.25 * cm))
    story.append(_p("Về tinh thần phương pháp", styles["H2"]))
    for paragraph in [
        "Điểm khởi đầu luôn là hình học. Một mẫu hình chỉ được đưa vào sách khi có quy tắc nhận diện đủ rõ: thân mẫu nằm ở đâu, đường biên được hiểu thế nào, phá vỡ được xác nhận ra sao và mục tiêu được đo từ mốc nào. Sau đó, dữ liệu mới được dùng để trả lời câu hỏi kế tiếp: lịch sử đã thưởng hoặc phạt mẫu hình ấy như thế nào.",
        "Vì vậy, sách này không biến quá khứ thành lời hứa. Nó giúp người đọc có một thước đo trước khi diễn giải biểu đồ: mẫu có thường đi đúng hướng không, có hay kéo ngược sâu không, có đạt mục tiêu trước khi chịu bất lợi không, và trường hợp thất bại trông như thế nào.",
    ]:
        story.append(_p(paragraph, styles["Body"]))
    story.append(PageBreak())

    story.append(_p("Lời mở đầu", styles["H1"]))
    for paragraph in [
        "Biểu đồ giá có sức hấp dẫn vì nó biến dòng giao dịch hỗn độn thành hình dạng. Một lá cờ, một tam giác, một chiếc cốc tay cầm hay một vai đầu vai đều làm người đọc có cảm giác rằng thị trường đang kể một câu chuyện. Nhưng câu chuyện ấy chỉ có giá trị khi được đặt trước hai câu hỏi khó: mẫu có được nhận diện nhất quán không, và sau khi xác nhận thì giá thật sự hành xử ra sao.",
        "Ấn bản này được viết từ chính hai câu hỏi đó. Thay vì chọn vài biểu đồ đẹp để minh họa niềm tin, mỗi chương đi theo một lối đọc cố định: mô tả hình thái, xác định điểm xác nhận, chọn ví dụ, đo đường đi sau đó, rồi mới kết luận về sức mạnh hoặc giới hạn của mẫu hình. Cách làm này giữ cho phần diễn giải gần với dữ liệu hơn là với cảm giác.",
        "Người đọc sẽ thấy có mẫu hình rất hợp để theo dõi phía mua, có mẫu chủ yếu giúp nhận diện rủi ro, và có mẫu chỉ nên xem như ghi chú về trạng thái thị trường. Đây là một điểm quan trọng của sách: không phải mọi cấu trúc đẹp trên biểu đồ đều trở thành cơ hội đầu tư. Một số mẫu hình hữu ích nhất lại là những mẫu giúp ta biết khi nào không nên quá tự tin.",
        "Bulkowski Việt Nam vì thế nên được đọc như một bản đồ thực chứng. Bản đồ không quyết định thay người đi đường, nhưng nó cho biết địa hình từng được ghi nhận ra sao: đoạn nào hay có lực tiếp diễn, đoạn nào thường nhiều kéo ngược, đoạn nào chỉ đẹp trên hình nhưng không bền trong dữ liệu. Nếu đọc theo cách đó, cuốn sách hữu ích nhất khi nó làm người đọc chậm lại trước khi kết luận.",
    ]:
        story.append(_p(paragraph, styles["Body"]))
    story.append(Spacer(1, 0.25 * cm))
    story.append(_p("Cách dùng sách", styles["H1"]))
    for paragraph in [
        "Mỗi chương nên được đọc từ trái sang phải theo đúng hành trình của một mẫu hình. Trước hết hãy xem hình thái: mẫu có đủ các bộ phận chính hay chỉ là một vùng dao động được đặt tên cho giống mẫu. Sau đó hãy xem điểm xác nhận: trước khi có xác nhận, mẫu chỉ là khả năng; sau xác nhận, nó mới trở thành một sự kiện để đo.",
        "Phần ví dụ biểu đồ nằm ở giữa chương vì nó nối hình học với dữ liệu. Ví dụ tốt cho thấy mẫu khi hoạt động đúng; ví dụ trung vị cho thấy trường hợp bình thường hơn; ví dụ thất bại nhắc rằng một mẫu hợp lệ vẫn có thể đi sai hướng hoặc chịu kéo ngược sâu. Đọc đủ ba loại ví dụ giúp tránh cảm giác rằng sách chỉ chọn những biểu đồ đẹp.",
        "Khi sang phần kết quả, hãy đọc các chỉ số theo cụm chứ không đọc từng số rời rạc. Tỷ lệ đạt mục tiêu cần đi cùng tỷ lệ thất bại, mức tăng tốt nhất cần đi cùng mức kéo ngược sâu nhất, và kết quả trung vị cần đi cùng số mẫu. Một mẫu có mục tiêu dễ đạt nhưng thường kéo ngược mạnh có thể khó dùng hơn một mẫu đi chậm nhưng ổn định.",
        "Nhãn sử dụng ở đầu chương là lời nhắc về vai trò của mẫu hình. Có chương phù hợp để lập danh sách theo dõi phía mua; có chương chỉ nên dùng để đọc rủi ro hoặc phòng thủ; có chương chủ yếu mang giá trị tham khảo. Người đọc nên tôn trọng nhãn này, vì nó phản ánh cả hình thái, thống kê và giới hạn thực thi trên thị trường Việt Nam.",
    ]:
        story.append(_p(paragraph, styles["Body"]))
    usage_rows = [
        ["Khi đọc", "Điều cần tự hỏi"],
        ["Hình thái", "Mẫu có đủ cấu trúc nguồn, hay chỉ là một vùng dao động nhìn giống mẫu?"],
        ["Xác nhận", "Giá đã hoàn tất điểm xác nhận chưa, hay người đọc đang đoán trước?"],
        ["Đường đi sau đó", "Mẫu đạt mục tiêu bằng một đường đi sạch hay phải chịu kéo ngược sâu?"],
        ["Cách sử dụng", "Chương này phù hợp để tìm cơ hội, lập danh sách theo dõi, hay phòng thủ rủi ro?"],
    ]
    story.append(_table(usage_rows, [3.5 * cm, 12.0 * cm], styles))
    story.append(PageBreak())

    story.append(_p("Mục lục", styles["H1"]))
    toc_rows = [["Mục", "Trang"]]
    for item in items:
        if item.kind == "ranking":
            toc_rows.append([item.title, str(item.start_page)])
            continue
        label = FAMILY_LABELS.get(item.family, item.family)
        toc_rows.append([f"{label} - {item.title}", str(item.start_page)])
    story.append(_table(toc_rows, [13.6 * cm, 1.6 * cm], styles))
    story.append(PageBreak())

    story.append(_p("Ghi chú về dữ liệu và giới hạn sử dụng", styles["H1"]))
    for paragraph in [
        "Mọi thống kê trong sách đều là kết quả lịch sử, không phải định luật. Dữ liệu Việt Nam còn có những giới hạn tự nhiên về độ dài chuỗi, trạng thái niêm yết, thanh khoản, điều chỉnh giá và khả năng tái dựng toàn bộ bối cảnh tại từng thời điểm. Vì thế, các con số nên được xem là bằng chứng có điều kiện.",
        "Một mẫu hình phía giảm không tự động trở thành cơ hội giao dịch trên cổ phiếu cơ sở. Trong nhiều chương, giá trị thực tế của mẫu nằm ở việc nhận diện rủi ro, giảm tự tin với vị thế đang có, hoặc hiểu trạng thái thị trường. Ngược lại, một mẫu phía tăng có kết quả tốt vẫn cần được đặt cạnh thanh khoản, biến động và bối cảnh chung.",
        "Ấn bản này ưu tiên mạch đọc liền lạc. Các phụ lục kiểm định và dấu vết kỹ thuật được tách khỏi thân sách để người đọc không bị đứt mạch; khi cần đào sâu, có thể đối chiếu với bộ hồ sơ dữ liệu đi kèm. Trong bản sách, điều quan trọng nhất là hiểu đúng vai trò của từng mẫu hình trước khi dùng nó trong thực tế.",
    ]:
        story.append(_p(paragraph, styles["Body"]))

    footer = _footer("Bulkowski Việt Nam - Edition 1", font_regular)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    chapter_count = sum(1 for item in items if item.kind == "chapter")
    family_count = len({item.family for item in items if item.kind == "chapter"})
    _build_cover_pdf(COVER_PDF, chapter_count, family_count)
    writer = PdfWriter()
    for path in (COVER_PDF, body_pdf):
        reader = PdfReader(str(path))
        for page in reader.pages:
            writer.add_page(page)
    with output.open("wb") as fh:
        writer.write(fh)
    body_pdf.unlink(missing_ok=True)
    return len(PdfReader(str(output)).pages)


def _build_stable_front_matter(items: list[BookItem]) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    front_count = 4
    for _ in range(4):
        _assign_pages(items, front_count)
        new_count = _build_front_matter(items, FRONT_MATTER_PDF)
        if new_count == front_count:
            _assign_pages(items, new_count)
            return new_count
        front_count = new_count
    _assign_pages(items, front_count)
    return front_count


def _book_footer_overlay(width: float, height: float, title: str, book_page: int, logo_path: Path | None = None) -> PageObject:
    packet = BytesIO()
    pdf = reportlab_canvas.Canvas(packet, pagesize=(width, height))
    footer_h = 1.8 * cm
    pdf.setFillColor(colors.white)
    pdf.rect(0, 0, width, footer_h, stroke=0, fill=1)
    pdf.setFillColor(colors.HexColor("#777777"))
    pdf.setFont("EditionVN", 6.8)
    left_x = 1.45 * cm
    if logo_path:
        logo_size = 0.58 * cm
        _draw_logo(pdf, logo_path, left_x, 0.43 * cm, logo_size)
        left_x += logo_size + 0.22 * cm
    pdf.drawString(left_x, 0.7 * cm, "Bulkowski Việt Nam")
    pdf.drawCentredString(width / 2, 0.7 * cm, title)
    pdf.drawRightString(width - 1.45 * cm, 0.7 * cm, f"Trang {book_page}")
    pdf.save()
    packet.seek(0)
    return PdfReader(packet).pages[0]


def _append_pdf_pages(
    writer: PdfWriter,
    source_pdf: Path,
    page_count: int,
    *,
    footer_title: str | None = None,
    start_index: int = 0,
) -> None:
    reader = PdfReader(str(source_pdf))
    for index in range(start_index, start_index + page_count):
        page = reader.pages[index]
        if footer_title:
            book_page = len(writer.pages) + 1
            page = PageObject.create_blank_page(width=float(page.mediabox.width), height=float(page.mediabox.height))
            source_page = reader.pages[index]
            page.merge_page(source_page)
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
            page.merge_page(_book_footer_overlay(width, height, footer_title, book_page))
        writer.add_page(page)


def _title_for_page(book_page: int, front_count: int, items: list[BookItem]) -> str:
    if book_page <= front_count:
        return "Bulkowski Việt Nam - Edition 1"
    for item in items:
        if item.start_page <= book_page <= item.end_page:
            return item.title
    return "Bulkowski Việt Nam"


def _redact_footer_band(input_pdf: Path, output_pdf: Path) -> None:
    footer_h = 1.95 * cm
    internal_markers = (
        "Chương mẫu hình theo logic xuất bản chuẩn",
        "bản chương xuất bản",
    )
    doc = fitz.open(str(input_pdf))
    for index, page in enumerate(doc):
        if index == 0:
            continue
        rect = page.rect
        footer_rect = fitz.Rect(0, rect.height - footer_h, rect.width, rect.height)
        page.add_redact_annot(footer_rect, fill=(1, 1, 1))
        for marker in internal_markers:
            for hit in page.search_for(marker):
                expanded = fitz.Rect(hit.x0 - 3, hit.y0 - 2, hit.x1 + 3, hit.y1 + 2)
                page.add_redact_annot(expanded, fill=(1, 1, 1))
        page.apply_redactions()
    doc.save(str(output_pdf), garbage=4, deflate=True)
    doc.close()


def _restamp_book_footers(input_pdf: Path, output_pdf: Path, front_count: int, items: list[BookItem]) -> None:
    reader = PdfReader(str(input_pdf))
    writer = PdfWriter()
    logo_path = _resolve_book_logo()
    for index, source_page in enumerate(reader.pages):
        if index == 0:
            writer.add_page(source_page)
            continue
        width = float(source_page.mediabox.width)
        height = float(source_page.mediabox.height)
        page = PageObject.create_blank_page(width=width, height=height)
        page.merge_page(source_page)
        book_page = index + 1
        page.merge_page(_book_footer_overlay(width, height, _title_for_page(book_page, front_count, items), book_page, logo_path))
        writer.add_page(page)
    writer.add_outline_item("Bìa", 0)
    if front_count >= 2:
        writer.add_outline_item("Thông tin ấn bản", 1)
    if front_count >= 3:
        writer.add_outline_item("Lời mở đầu và cách dùng sách", 2)
    if front_count >= 4:
        writer.add_outline_item("Mục lục", 3)
    if front_count >= 6:
        writer.add_outline_item("Ghi chú dữ liệu và giới hạn sử dụng", 5)
    for item in items:
        writer.add_outline_item(item.title, max(0, item.start_page - 1))
    writer.add_metadata(
        {
            "/Title": "Bulkowski Việt Nam - Edition 1",
            "/Author": "Bloger Chim Cut",
            "/Creator": "Bulkowski Việt Nam canonical publication book builder",
            "/Subject": "Atlas mẫu hình giá trên thị trường chứng khoán Việt Nam",
            "/Keywords": "Bulkowski Việt Nam, mẫu hình giá, chứng khoán Việt Nam, technical analysis, Bloger Chim Cut",
        }
    )
    with output_pdf.open("wb") as fh:
        writer.write(fh)


def _stamp_book_page_numbers(writer: PdfWriter, *, start_index: int) -> None:
    for index in range(start_index, len(writer.pages)):
        page = writer.pages[index]
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        packet = BytesIO()
        pdf = reportlab_canvas.Canvas(packet, pagesize=(width, height))
        pdf.setFont("EditionVN", 6.6)
        pdf.setFillColor(colors.HexColor("#8a8a8a"))
        pdf.drawCentredString(width / 2, 0.72 * cm, f"Trang sách {index + 1}")
        pdf.save()
        packet.seek(0)
        overlay = PdfReader(packet)
        page.merge_page(overlay.pages[0])


def build_edition() -> dict[str, Any]:
    items = _build_items()
    front_count = _build_stable_front_matter(items)
    writer = PdfWriter()
    _append_pdf_pages(writer, FRONT_MATTER_PDF, front_count)
    for item in items:
        outline_page_index = len(writer.pages)
        writer.add_outline_item(item.title, outline_page_index)
        _append_pdf_pages(
            writer,
            item.source_pdf,
            item.included_pages,
            footer_title=item.title,
            start_index=item.source_start_index,
        )
    writer.add_metadata(
        {
            "/Title": "Bulkowski Việt Nam - Edition 1",
            "/Author": "Bulkowski Việt Nam",
            "/Subject": "Atlas mẫu hình giá Việt Nam",
        }
    )
    raw_pdf = OUT_DIR / "bulkowski_vietnam_edition_1_publication_draft.raw.pdf"
    redacted_pdf = OUT_DIR / "bulkowski_vietnam_edition_1_publication_draft.redacted.pdf"
    with raw_pdf.open("wb") as fh:
        writer.write(fh)
    _redact_footer_band(raw_pdf, redacted_pdf)
    _restamp_book_footers(redacted_pdf, EDITION_PDF, front_count, items)
    raw_pdf.unlink(missing_ok=True)
    redacted_pdf.unlink(missing_ok=True)

    manifest = {
        "edition_id": "bulkowski_vietnam_edition_1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "pdf": str(EDITION_PDF.relative_to(ROOT)),
        "front_matter_pdf": str(FRONT_MATTER_PDF.relative_to(ROOT)),
        "front_matter_pages": front_count,
        "total_pages": len(PdfReader(str(EDITION_PDF)).pages),
        "chapter_count": sum(1 for item in items if item.kind == "chapter"),
        "ranking_pages": items[0].included_pages if items and items[0].kind == "ranking" else 0,
        "appendix_policy": "Technical appendices and internal publication-gate assessment sections are omitted from the merged Edition 1 PDF.",
        "book_logo": str(_resolve_book_logo().relative_to(ROOT)) if _resolve_book_logo() else None,
        "items": [
            {
                "kind": item.kind,
                "title": item.title,
                "family": item.family,
                "source_pdf": str(item.source_pdf.relative_to(ROOT)),
                "source_pages": item.source_pages,
                "included_pages": item.included_pages,
                "start_page": item.start_page,
                "end_page": item.end_page,
                "appendix_removed": item.appendix_removed,
            }
            for item in items
        ],
    }
    EDITION_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    manifest = build_edition()
    print(
        json.dumps(
            {
                "status": "PASS",
                "pdf": manifest["pdf"],
                "total_pages": manifest["total_pages"],
                "chapters": manifest["chapter_count"],
                "appendices_removed": sum(1 for item in manifest["items"] if item.get("appendix_removed")),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
