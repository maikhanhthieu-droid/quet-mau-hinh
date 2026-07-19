from __future__ import annotations

import csv
import html
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
FINAL_MANIFEST = ROOT / "artifacts" / "final_chapters" / "final_chapters_manifest.json"
GOVERNANCE = ROOT / "artifacts" / "final_chapters" / "governance" / "chapter_governance_matrix.json"
DEFAULT_TRADABLE_PREFLIGHT_MATRIX = ROOT / "artifacts" / "final_chapters" / "governance" / "chapter_tradable_preflight_matrix.json"
COVERAGE_AUDIT = ROOT / "artifacts" / "final_chapters" / "governance" / "bulkowski_source_pdf_coverage_audit.json"
OUT_DIR = ROOT / "artifacts" / "final_chapters" / "book_level"
BOOK_LEVEL_PDF_DIR = ROOT / "artifacts" / "book_level"

FONT_REGULAR_CANDIDATES = (
    Path("/opt/homebrew/Cellar/python-matplotlib/3.10.7/libexec/lib/python3.14/site-packages/matplotlib/mpl-data/fonts/ttf/DejaVuSans.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
)
FONT_BOLD_CANDIDATES = (
    Path("/opt/homebrew/Cellar/python-matplotlib/3.10.7/libexec/lib/python3.14/site-packages/matplotlib/mpl-data/fonts/ttf/DejaVuSans-Bold.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
)


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


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _fmt_score(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.2f}"
    except Exception:
        return str(value)


def _fmt_int(value: Any) -> str:
    try:
        return f"{int(float(value)):,}".replace(",", ".")
    except Exception:
        return ""


def _fmt_pct(value: Any, digits: int = 1) -> str:
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except Exception:
        return ""


def _fmt_pct_points(value: Any, digits: int = 2) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.{digits}f}%"
    except Exception:
        return ""


def _score_value(row: dict[str, Any], *, missing: float = -1.0) -> float:
    value = row.get("tradable_score")
    return float(value) if isinstance(value, (int, float)) else missing


def _preflight_value(row: dict[str, Any], *, missing: float = -1.0) -> float:
    value = row.get("preflight_score")
    return float(value) if isinstance(value, (int, float)) else missing


def _recommended_use(row: dict[str, Any]) -> str:
    status = row.get("tradable_status") or ""
    blockers = str(row.get("tradable_blockers") or "")
    applicability = str(row.get("tradable_applicability") or "")
    preflight = str(row.get("tradable_preflight_status") or "")
    score = row.get("tradable_score")
    score_f = float(score) if isinstance(score, (int, float)) else None

    if status == "tradable_final_95":
        return "tradable-final candidate under stated data scope"
    if status == "not_tested":
        return "publication/reference only; tradable layer not available"
    if "scope_not_direct_long_cash_equity" in blockers or "defensive" in applicability:
        return "defensive/informational reference for risk or exit framing"
    if score_f is not None and score_f >= 90:
        return "watchlist/research candidate; promising but blocked by robustness"
    if preflight in {"preflight_strong", "preflight_candidate"}:
        return "investment-reference or watchlist reference, not executable signal"
    return "descriptive/informational reference"


def _next_action(row: dict[str, Any]) -> str:
    blockers = str(row.get("tradable_blockers") or "")
    status = row.get("tradable_status") or ""
    preflight = row.get("tradable_preflight_status") or ""
    if status == "tradable_final_95":
        return "Eligible for scanner/watchlist integration with risk labels."
    if status == "not_tested":
        return "Keep as publication chapter unless a dedicated executable setup is designed."
    if "thin_sample" in blockers or "trade_count_below" in blockers:
        return "Needs deeper/cleaner data before another tradable push."
    if "scope_not_direct_long_cash_equity" in blockers:
        return "Use as defensive/informational; do not force long-cash tradable promotion."
    if "walk_forward_has_negative_fold" in blockers or "walk_forward_sum_return_below_8pct" in blockers:
        return "Do not tune further without new data or a new setup hypothesis."
    if preflight in {"preflight_weak", "preflight_poor"}:
        return "Keep as descriptive chapter; revisit only with new data scope."
    return "No immediate chapter-building work; monitor in book-level governance."


def _markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    header = rows[0]
    sep = ["---"] * len(header)
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(sep) + " |"]
    for row in rows[1:]:
        escaped = [str(cell).replace("\n", " ").replace("|", "/") for cell in row]
        lines.append("| " + " | ".join(escaped) + " |")
    return "\n".join(lines)


def _register_pdf_fonts() -> tuple[str, str]:
    regular = next((path for path in FONT_REGULAR_CANDIDATES if path.exists()), None)
    bold = next((path for path in FONT_BOLD_CANDIDATES if path.exists()), regular)
    if regular is None:
        return ("Helvetica", "Helvetica-Bold")
    try:
        pdfmetrics.registerFont(TTFont("BookPublicSans", str(regular)))
        pdfmetrics.registerFont(TTFont("BookPublicSansBold", str(bold)))
    except Exception:
        pass
    return ("BookPublicSans", "BookPublicSansBold")


def _pdf_styles(font_regular: str, font_bold: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "Title": ParagraphStyle(
            "BookTitle",
            parent=base["Title"],
            fontName=font_bold,
            fontSize=21,
            leading=26,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#173b3a"),
            spaceAfter=6,
        ),
        "Subtitle": ParagraphStyle(
            "BookSubtitle",
            parent=base["BodyText"],
            fontName=font_regular,
            fontSize=9.2,
            leading=12.5,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#555555"),
            spaceAfter=10,
        ),
        "H1": ParagraphStyle(
            "BookH1",
            parent=base["Heading1"],
            fontName=font_bold,
            fontSize=13.4,
            leading=16.2,
            textColor=colors.HexColor("#173b3a"),
            spaceBefore=8,
            spaceAfter=5,
        ),
        "H2": ParagraphStyle(
            "BookH2",
            parent=base["Heading2"],
            fontName=font_bold,
            fontSize=10.4,
            leading=13,
            textColor=colors.HexColor("#245b5a"),
            spaceBefore=6,
            spaceAfter=3,
        ),
        "Body": ParagraphStyle(
            "BookBody",
            parent=base["BodyText"],
            fontName=font_regular,
            fontSize=8.4,
            leading=12,
            textColor=colors.HexColor("#202020"),
            spaceAfter=4,
        ),
        "Small": ParagraphStyle(
            "BookSmall",
            parent=base["BodyText"],
            fontName=font_regular,
            fontSize=7.2,
            leading=9.6,
            textColor=colors.HexColor("#555555"),
            spaceAfter=2,
        ),
        "TableHeader": ParagraphStyle(
            "BookTableHeader",
            parent=base["BodyText"],
            fontName=font_bold,
            fontSize=6.8,
            leading=8.7,
            textColor=colors.HexColor("#173b3a"),
        ),
        "TableCell": ParagraphStyle(
            "BookTableCell",
            parent=base["BodyText"],
            fontName=font_regular,
            fontSize=6.55,
            leading=8.6,
            textColor=colors.HexColor("#202020"),
        ),
        "Callout": ParagraphStyle(
            "BookCallout",
            parent=base["BodyText"],
            fontName=font_bold,
            fontSize=7.6,
            leading=10.2,
            textColor=colors.HexColor("#173b3a"),
            spaceAfter=0,
        ),
        "Footer": ParagraphStyle(
            "BookFooter",
            parent=base["BodyText"],
            fontName=font_regular,
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#777777"),
        ),
    }


def _pdf_esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _pdf_paragraph(value: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_pdf_esc(value), style)


def _pdf_table(rows: list[list[Any]], widths: list[float], styles: dict[str, ParagraphStyle]) -> Table:
    data = [
        [
            _pdf_paragraph(cell, styles["TableHeader" if row_index == 0 else "TableCell"])
            for cell in row
        ]
        for row_index, row in enumerate(rows)
    ]
    table = Table(data, colWidths=widths, hAlign="LEFT", repeatRows=1)
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


def _short_blocker(row: dict[str, Any]) -> str:
    blockers = str(row.get("tradable_blockers") or "")
    if row.get("tradable_status") == "tradable_final_95":
        return "Đã qua lớp thực thi trong phạm vi dữ liệu hiện có."
    if "scope_not_direct_long_cash_equity" in blockers or "cash_equity_downside_not_direct_tradable" in blockers:
        return "Vai trò chính là phòng thủ hoặc cảnh báo rủi ro."
    if "walk_forward_has_negative_fold" in blockers:
        return "Có giai đoạn kiểm tra ngoài mẫu còn âm."
    if "walk_forward_sum_return_below_8pct" in blockers:
        return "Tổng hiệu quả ngoài mẫu còn mỏng."
    if "trade_count_below" in blockers or "thin_sample" in blockers:
        return "Số mẫu giao dịch đủ chuẩn còn mỏng."
    if blockers:
        return blockers.split(",")[0].strip()
    return row.get("next_action") or "Dùng như tài liệu tham khảo."


def _reader_bucket(row: dict[str, Any]) -> str:
    recommended = str(row.get("recommended_use") or "")
    blockers = str(row.get("tradable_blockers") or "")
    status = str(row.get("tradable_status") or "")
    if status == "tradable_final_95":
        return "Ứng viên đầu tư"
    if "scope_not_direct_long_cash_equity" in blockers or "defensive" in recommended:
        return "Phòng thủ / cảnh báo"
    if "watchlist" in recommended or "investment-reference" in recommended:
        return "Theo dõi đầu tư"
    return "Tham khảo"


def _is_long_cash_candidate(row: dict[str, Any]) -> bool:
    if _reader_bucket(row) in {"Phòng thủ / cảnh báo", "Tham khảo"}:
        return False
    blockers = str(row.get("tradable_blockers") or "")
    return "cash_equity_downside_not_direct_tradable" not in blockers


def _investment_effectiveness_score(row: dict[str, Any]) -> float:
    """Reader-facing score from behavior metrics, not a governance score."""

    target_first = float(row.get("target_first_before_adverse_5pct_rate") or 0.0)
    target_hit = float(row.get("target_hit_rate") or 0.0)
    failure = float(row.get("failure_5pct_rate") or 0.0)
    ratio = min(float(row.get("mfe_mae_ratio") or 0.0), 3.0) / 3.0
    tradable = max(float(row.get("tradable_score") or 0.0), 0.0) / 100.0
    score = (
        34.0 * target_first
        + 20.0 * target_hit
        + 18.0 * max(0.0, 1.0 - failure)
        + 14.0 * ratio
        + 14.0 * tradable
    )
    return round(score, 2)


def _popularity_score(row: dict[str, Any]) -> float:
    n_events = float(row.get("n_events") or 0.0)
    n_symbols = float(row.get("n_symbols") or 0.0)
    quality = float(row.get("public_grade_share") or 0.0)
    return round(n_events + 0.25 * n_symbols + 100.0 * quality, 2)


def _find_trade_metrics(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if "total_return_pct" in value and "trades" in value:
            return value
        selected = value.get("selected_metrics")
        if isinstance(selected, dict) and "total_return_pct" in selected and "trades" in selected:
            return selected
        best = value.get("best_metrics")
        if isinstance(best, dict) and "total_return_pct" in best and "trades" in best:
            return best
        for child in value.values():
            found = _find_trade_metrics(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_trade_metrics(child)
            if found:
                return found
    return None


def _load_trade_metrics(path_value: Any) -> dict[str, Any]:
    if not path_value:
        return {}
    path = ROOT / str(path_value)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return _find_trade_metrics(data) or {}


def _render_footer(title: str, font_regular: str):
    def _footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(font_regular, 7)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(doc.leftMargin, 0.68 * cm, title)
        canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 0.68 * cm, f"Trang {doc.page}")
        canvas.restoreState()

    return _footer


def build_catalog(manifest: dict[str, Any], governance: dict[str, Any]) -> list[dict[str, Any]]:
    by_pattern = {row["pattern_id"]: row for row in governance["chapters"]}
    rows = []
    for item in manifest["chapters"]:
        pattern_id = item["pattern_id"]
        gov = by_pattern.get(pattern_id, {})
        row = {
            "family": item["family"],
            "family_label": FAMILY_LABELS.get(item["family"], item["family"]),
            "pattern_id": pattern_id,
            "title": item.get("title", ""),
            "pdf": item.get("pdf", ""),
            "publication_status": gov.get("publication_status") or item.get("status"),
            "publication_classification": gov.get("publication_classification") or item.get("classification", ""),
            "publication_claim_level": gov.get("publication_claim_level") or item.get("claim_level", ""),
            "tradable_status": gov.get("tradable_status", ""),
            "tradable_score": gov.get("tradable_score"),
            "tradable_release_status": gov.get("tradable_release_status", ""),
            "tradable_applicability": gov.get("tradable_applicability", ""),
            "tradable_evidence_id": gov.get("tradable_evidence_id", ""),
            "tradable_blockers": gov.get("tradable_blockers", ""),
            "tradable_selected_strategy": gov.get("tradable_selected_strategy", ""),
            "preflight_status": gov.get("tradable_preflight_status", ""),
            "preflight_score": gov.get("tradable_preflight_score"),
            "preflight_warnings": gov.get("tradable_preflight_warnings", ""),
        }
        row["recommended_use"] = _recommended_use(row)
        row["next_action"] = _next_action(row)
        rows.append(row)
    return rows


def write_catalog(rows: list[dict[str, Any]]) -> None:
    csv_path = OUT_DIR / "book_level_chapter_catalog.csv"
    json_path = OUT_DIR / "book_level_chapter_catalog.json"
    md_path = OUT_DIR / "book_level_chapter_catalog.md"
    fields = [
        "family",
        "pattern_id",
        "title",
        "pdf",
        "publication_status",
        "publication_classification",
        "tradable_status",
        "tradable_score",
        "preflight_status",
        "preflight_score",
        "recommended_use",
        "tradable_blockers",
        "next_action",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_family[row["family"]].append(row)
    lines = [
        "# Book-Level Chapter Catalog",
        "",
        "This catalog is generated from the final chapter manifest and governance matrix.",
        "",
    ]
    for family in sorted(by_family):
        family_rows = sorted(by_family[family], key=lambda x: x["pattern_id"])
        lines.extend([f"## {FAMILY_LABELS.get(family, family)}", ""])
        table = [["Pattern", "Title", "Tradable", "Score", "Use", "Next action"]]
        for row in family_rows:
            table.append(
                [
                    row["pattern_id"],
                    row["title"],
                    row["tradable_status"],
                    _fmt_score(row["tradable_score"]),
                    row["recommended_use"],
                    row["next_action"],
                ]
            )
        lines.append(_markdown_table(table))
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")


def write_executive_summary(rows: list[dict[str, Any]], governance: dict[str, Any], coverage: dict[str, Any]) -> None:
    family_counts = Counter(row["family"] for row in rows)
    tradable_counts = Counter(row["tradable_status"] for row in rows)
    use_counts = Counter(row["recommended_use"] for row in rows)
    top_scores = sorted(
        [row for row in rows if isinstance(row.get("tradable_score"), (int, float))],
        key=lambda row: float(row["tradable_score"]),
        reverse=True,
    )[:12]
    event_missing = coverage.get("missing_event_data_chapters", [])

    lines = [
        "# Bulkowski Vietnam Book-Level Finalization Pack",
        "",
        f"Generated: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`",
        "",
        "## Executive Summary",
        "",
        "The per-pattern chapter build phase is complete for price-pattern chapters that can be studied from the available OHLCV/path data. The remaining unmatched chapters in the primary Bulkowski chart-pattern source are event-data chapters, not ordinary price-shape scanners.",
        "",
        "## Current Scope",
        "",
        f"- Final publication chapters: `{len(rows)}`",
        f"- Families represented: `{len(family_counts)}`",
        f"- Source coverage status: `{coverage.get('status')}`",
        f"- Primary chart-source chapters covered: `{coverage.get('summary', {}).get('source_chart_chapters_covered')}`",
        f"- Primary chart-source chapters requiring external event data: `{coverage.get('summary', {}).get('source_chart_chapters_not_covered_event_data_required')}`",
        f"- Mapping failures against source PDF: `{coverage.get('summary', {}).get('source_chart_chapter_mapping_failures')}`",
        "",
        "## Dual-Axis Status",
        "",
        f"- Publication-final chapters: `{governance.get('counts', {}).get('publication_final')}`",
        f"- Tradable-final-95 chapters: `{governance.get('counts', {}).get('tradable_final_95')}`",
        f"- Tradable research candidates but blocked: `{governance.get('counts', {}).get('tradable_research_candidate_blocked')}`",
        f"- Tradable tested but blocked: `{governance.get('counts', {}).get('tradable_tested_blocked')}`",
        f"- Tradable not tested: `{governance.get('counts', {}).get('not_tested')}`",
        "",
        "## Recommended Use Buckets",
        "",
    ]
    bucket_table = [["Use bucket", "Chapters"]]
    for bucket, count in use_counts.most_common():
        bucket_table.append([bucket, str(count)])
    lines.extend([_markdown_table(bucket_table), ""])

    lines.extend(["## Highest Tradable Scores", ""])
    top_table = [["Pattern", "Title", "Score", "Tradable status", "Recommended use"]]
    for row in top_scores:
        top_table.append(
            [
                row["pattern_id"],
                row["title"],
                _fmt_score(row["tradable_score"]),
                row["tradable_status"],
                row["recommended_use"],
            ]
        )
    lines.extend([_markdown_table(top_table), ""])

    lines.extend(["## Event-Data Chapters Not Built", ""])
    event_table = [["Source chapter", "Title", "Reason"]]
    for row in event_missing:
        event_table.append([str(row["chapter"]), row["title"], row.get("missing_reason", "")])
    lines.extend([_markdown_table(event_table), ""])

    lines.extend(
        [
            "## Decision",
            "",
            "Stop building new per-pattern OHLCV chapters for the current Bulkowski chart-pattern scope. Move to book-level consolidation, final QA, reader guidance, and operational scanner/watchlist infrastructure.",
            "",
        ]
    )
    (OUT_DIR / "executive_summary.md").write_text("\n".join(lines), encoding="utf-8")


def write_limitations_appendix(rows: list[dict[str, Any]], coverage: dict[str, Any]) -> None:
    blocker_counts = Counter()
    for row in rows:
        for blocker in str(row.get("tradable_blockers") or "").split(","):
            blocker = blocker.strip()
            if blocker:
                blocker_counts[blocker] += 1

    lines = [
        "# Usage and Limitations Appendix",
        "",
        "This appendix defines how to read the finished chapters without confusing a statistical reference with a trading system.",
        "",
        "## Reading Labels",
        "",
        "- `publication-final`: the chapter is suitable as a public reference chapter under the available-series data scope.",
        "- `tradable-final-95`: the pattern also passed an executable entry/exit/cost/sizing/OOS layer with score >= 95 and no promotion blocker.",
        "- `tradable-research-candidate-blocked`: the setup is promising, but at least one robustness or scope gate still blocks promotion.",
        "- `tradable-tested-blocked`: the setup was tested and should not be promoted as an executable strategy under current data.",
        "- `not-tested`: the chapter remains a reference chapter only.",
        "",
        "## Main Remaining Blockers",
        "",
    ]
    table = [["Blocker", "Chapter count", "Interpretation"]]
    interpretations = {
        "score_below_95": "Tradable layer did not reach promotion threshold.",
        "walk_forward_has_negative_fold": "At least one time split failed; do not treat aggregate performance as durable.",
        "walk_forward_sum_return_below_8pct": "Walk-forward return was too small for a tradable-final claim.",
        "scope_not_direct_long_cash_equity": "The chapter is defensive, downside, or mixed-direction under Vietnam cash-equity constraints.",
        "cash_equity_downside_not_direct_tradable": "Useful for risk/exit framing, not direct long-cash implementation.",
        "thin_sample": "Sample depth is not enough to rescue by tuning.",
        "validation_trade_count_below_12": "Validation set has too few trades.",
        "holdout_trade_count_below_12": "Holdout set has too few trades.",
        "median_adtv_participation_above_5pct": "Capacity/liquidity gate is weak.",
        "median_mfe_below_median_mae": "Forward path is not favorable enough.",
        "target_first_not_above_failure": "Target-first behavior is not strong enough relative to failure.",
    }
    for blocker, count in blocker_counts.most_common():
        table.append([blocker, str(count), interpretations.get(blocker, "Governance blocker; inspect chapter scorecard.")])
    lines.extend([_markdown_table(table), ""])

    lines.extend(
        [
            "## Data Boundaries",
            "",
            "- The project does not claim a perfect point-in-time reconstruction of the full Vietnam market.",
            "- Current chapters use available OHLCV/path data and the accepted data scope, with explicit labels for defensive, informational, and tradable uses.",
            "- Event-data chapters from the source PDF are not implemented because they require earnings, FDA approval, same-store sales, analyst downgrade, or analyst upgrade datasets.",
            "- A chapter can be statistically useful without becoming a tradable setup.",
            "",
            "## Event-Data Scope Not Implemented",
            "",
        ]
    )
    event_table = [["Source chapter", "Title", "Required data"]]
    for row in coverage.get("missing_event_data_chapters", []):
        event_table.append([str(row["chapter"]), row["title"], row.get("missing_reason", "")])
    lines.extend([_markdown_table(event_table), ""])
    (OUT_DIR / "usage_and_limitations_appendix.md").write_text("\n".join(lines), encoding="utf-8")


def write_scanner_roadmap(rows: list[dict[str, Any]]) -> None:
    tradable = [row for row in rows if row["tradable_status"] == "tradable_final_95"]
    watchlist = [
        row
        for row in rows
        if row["tradable_status"] == "tradable_research_candidate_blocked"
        or (isinstance(row.get("tradable_score"), (int, float)) and float(row["tradable_score"]) >= 90)
    ]
    defensive = [row for row in rows if "defensive" in row["recommended_use"]]

    lines = [
        "# Scanner Operations Roadmap",
        "",
        "The next phase should convert the finished book into an operational scanner/watchlist stack. This is separate from writing more chapters.",
        "",
        "## Phase 1: Matrix Scanner",
        "",
        "- Run all final pattern scanners on the current data feed.",
        "- Emit one normalized event schema across families: pattern id, family, date, symbol, direction, target family, quality tier, liquidity tag, and risk labels.",
        "- Keep family-specific geometry in scanner modules; share only statistics, governance, and output contracts.",
        "",
        "## Phase 2: Watchlist Views",
        "",
        "- Tradable-final candidates: use for actionable watchlist candidates, still with risk controls.",
        "- Watchlist/research candidates: show separately as setups needing confirmation.",
        "- Defensive/informational chapters: show in risk-monitoring panels, not in long-entry panels.",
        "",
        "## Tradable-Final Candidates",
        "",
    ]
    table = [["Pattern", "Title", "Score", "Use"]]
    for row in sorted(tradable, key=lambda x: float(x.get("tradable_score") or 0), reverse=True):
        table.append([row["pattern_id"], row["title"], _fmt_score(row["tradable_score"]), row["recommended_use"]])
    lines.extend([_markdown_table(table), ""])

    lines.extend(["## Watchlist / Research Candidates", ""])
    table = [["Pattern", "Title", "Score", "Blocker summary"]]
    for row in sorted(watchlist, key=lambda x: float(x.get("tradable_score") or 0), reverse=True):
        if row["tradable_status"] == "tradable_final_95":
            continue
        table.append([row["pattern_id"], row["title"], _fmt_score(row["tradable_score"]), row.get("tradable_blockers", "")])
    lines.extend([_markdown_table(table), ""])

    lines.extend(["## Defensive / Informational Panels", ""])
    table = [["Pattern", "Title", "Reason"]]
    for row in defensive:
        table.append([row["pattern_id"], row["title"], row.get("tradable_blockers", "") or row["recommended_use"]])
    lines.extend([_markdown_table(table), ""])

    lines.extend(
        [
            "## Phase 3: Governance Before Realtime Use",
            "",
            "- Run final manifest validation before publishing scanner outputs.",
            "- Run scanner/tradable integrity audit before deploying updated logic.",
            "- Preserve the source-PDF coverage audit as the book-level boundary: new event-data chapters require new datasets, not OHLCV scanner tweaks.",
            "- Realtime outputs must state whether each hit is `tradable-final`, `watchlist`, `defensive`, or `reference-only`.",
            "",
        ]
    )
    (OUT_DIR / "scanner_operations_roadmap.md").write_text("\n".join(lines), encoding="utf-8")


def write_chapter_usage_guide(rows: list[dict[str, Any]]) -> None:
    """Write the reader-facing appendix requested after chapter completion."""

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[row["recommended_use"]].append(row)

    order = [
        "tradable-final candidate under stated data scope",
        "watchlist/research candidate; promising but blocked by robustness",
        "investment-reference or watchlist reference, not executable signal",
        "defensive/informational reference for risk or exit framing",
        "publication/reference only; tradable layer not available",
        "descriptive/informational reference",
    ]
    lines = [
        "# Chapter Usage Guide",
        "",
        "This guide is the practical reading layer for the finished book. It states what each chapter can and cannot be used for.",
        "",
        "## Why Not Every Pattern Is Tradable",
        "",
        "A pattern can be useful as a statistical reference without passing an executable strategy gate. The publication layer asks whether the chapter explains the historical behavior clearly. The tradable layer asks a harder question: whether a concrete entry, exit, cost, sizing, capacity and OOS protocol survives robustness checks.",
        "",
        "The most common reason for non-promotion is not that the PDF is weak. It is that the executable setup fails at least one of these gates: negative walk-forward fold, weak walk-forward sum return, too few validation/holdout trades, downside scope in cash equities, or liquidity/capacity limits.",
        "",
    ]
    for bucket in order:
        chapter_rows = buckets.get(bucket, [])
        if not chapter_rows:
            continue
        lines.extend([f"## {bucket}", ""])
        table = [["Family", "Pattern", "Title", "Tradable score", "Main blocker / reason"]]
        for row in sorted(chapter_rows, key=lambda r: (r["family"], r["pattern_id"])):
            reason = row.get("tradable_blockers") or row.get("publication_classification") or row["next_action"]
            table.append([row["family_label"], row["pattern_id"], row["title"], _fmt_score(row["tradable_score"]), reason])
        lines.extend([_markdown_table(table), ""])

    (OUT_DIR / "chapter_usage_guide.md").write_text("\n".join(lines), encoding="utf-8")


def write_aggregate_rankings(rows: list[dict[str, Any]]) -> None:
    """Rank chapters by practical use, not by a single raw score."""

    def score(row: dict[str, Any]) -> float:
        return _score_value(row)

    groups = {
        "tradable_final_95": [row for row in rows if row["tradable_status"] == "tradable_final_95"],
        "long_cash_watchlist": [
            row
            for row in rows
            if row["tradable_status"] != "tradable_final_95"
            and "scope_not_direct_long_cash_equity" not in str(row.get("tradable_blockers") or "")
            and "defensive" not in row["recommended_use"]
            and score(row) >= 85.0
        ],
        "defensive_informational": [row for row in rows if "defensive" in row["recommended_use"]],
        "research_only_or_descriptive": [
            row
            for row in rows
            if row["recommended_use"] in {"descriptive/informational reference", "publication/reference only; tradable layer not available"}
        ],
    }

    json_payload = {
        "ranking_id": "book_level_practical_ranking_v1",
        "rule": "Rank by practical use bucket first, then tradable score where available. Do not compare defensive and long-cash patterns as if they share the same use case.",
        "groups": {},
    }
    lines = [
        "# Aggregate Practical Rankings",
        "",
        "The book should not be read as one absolute leaderboard. A defensive chapter and a long-cash setup solve different problems. These rankings group chapters by intended use first, then sort by score.",
        "",
    ]
    group_titles = {
        "tradable_final_95": "Tradable-Final 95",
        "long_cash_watchlist": "Long-Cash Watchlist Candidates",
        "defensive_informational": "Defensive / Informational References",
        "research_only_or_descriptive": "Research-Only / Descriptive References",
    }
    for key, group_rows in groups.items():
        sorted_rows = sorted(group_rows, key=score, reverse=True)
        json_payload["groups"][key] = sorted_rows
        lines.extend([f"## {group_titles[key]}", ""])
        table = [["Rank", "Pattern", "Title", "Family", "Score", "Use", "Blockers"]]
        for index, row in enumerate(sorted_rows, start=1):
            table.append(
                [
                    str(index),
                    row["pattern_id"],
                    row["title"],
                    row["family_label"],
                    _fmt_score(row["tradable_score"]),
                    row["recommended_use"],
                    row.get("tradable_blockers", ""),
                ]
            )
        lines.extend([_markdown_table(table), ""])

    (OUT_DIR / "aggregate_practical_rankings.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT_DIR / "aggregate_practical_rankings.json").write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _merge_reader_rows(rows: list[dict[str, Any]], preflight_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    catalog_by_id = {row["pattern_id"]: row for row in rows}
    merged: list[dict[str, Any]] = []
    for preflight in preflight_rows:
        base = catalog_by_id.get(preflight.get("pattern_id"), {})
        row = {**base, **preflight}
        row["family_label"] = base.get("family_label") or FAMILY_LABELS.get(str(row.get("family") or ""), str(row.get("family") or ""))
        row["recommended_use"] = base.get("recommended_use", "")
        row["tradable_status"] = base.get("tradable_status", "")
        row["tradable_score"] = base.get("tradable_score")
        row["tradable_blockers"] = base.get("tradable_blockers", "")
        row["trade_metrics"] = _load_trade_metrics(base.get("tradable_selected_strategy"))
        metrics = row["trade_metrics"]
        row["profit_total_return_pct"] = metrics.get("total_return_pct")
        row["profit_validation_return_pct"] = metrics.get("validation_total_return_pct")
        row["profit_holdout_return_pct"] = metrics.get("holdout_total_return_pct")
        row["profit_trades"] = metrics.get("trades")
        row["profit_win_rate_pct"] = metrics.get("win_rate_pct")
        row["profit_drawdown_pct"] = metrics.get("max_drawdown_pct")
        row["profit_factor"] = metrics.get("profit_factor")
        row["reader_bucket"] = _reader_bucket(row)
        row["investment_effectiveness_score"] = _investment_effectiveness_score(row)
        row["popularity_score"] = _popularity_score(row)
        merged.append(row)
    return merged


def write_bulkowski_style_rankings(rows: list[dict[str, Any]], preflight_rows: list[dict[str, Any]]) -> None:
    """Create a reader-facing ranking section inspired by Bulkowski's ranking pages.

    This is intentionally separate from governance rankings. It presents chapter
    performance in practical buckets and keeps defensive/reference patterns out of
    long-cash opportunity tables.
    """

    def sort_key(row: dict[str, Any]) -> tuple[float, float, str]:
        return (_score_value(row), _preflight_value(row), row["pattern_id"])

    tradable_final = [row for row in rows if row["tradable_status"] == "tradable_final_95"]
    long_cash_candidates = [
        row
        for row in rows
        if row["tradable_status"] != "tradable_final_95"
        and "scope_not_direct_long_cash_equity" not in str(row.get("tradable_blockers") or "")
        and "defensive" not in row["recommended_use"]
        and _score_value(row) >= 80.0
    ]
    defensive = [row for row in rows if "defensive" in row["recommended_use"]]
    caution = [
        row
        for row in rows
        if row["tradable_status"] != "tradable_final_95"
        and (
            _score_value(row) < 60.0
            or "trade_count_below" in str(row.get("tradable_blockers") or "")
            or row["tradable_status"] == "not_tested"
        )
    ]

    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_family[row["family"]].append(row)

    family_rankings: list[dict[str, Any]] = []
    for family, family_rows in by_family.items():
        scores = [_score_value(row, missing=0.0) for row in family_rows if _score_value(row) >= 0.0]
        preflight_scores = [_preflight_value(row, missing=0.0) for row in family_rows if _preflight_value(row) >= 0.0]
        tradable_count = sum(1 for row in family_rows if row["tradable_status"] == "tradable_final_95")
        watchlist_count = sum(1 for row in family_rows if "watchlist" in row["recommended_use"])
        defensive_count = sum(1 for row in family_rows if "defensive" in row["recommended_use"])
        max_score = max(scores) if scores else None
        median_score = sorted(scores)[len(scores) // 2] if scores else None
        median_preflight = sorted(preflight_scores)[len(preflight_scores) // 2] if preflight_scores else None
        family_rank = (
            30.0 * tradable_count
            + 8.0 * watchlist_count
            + (float(max_score or 0.0) * 0.45)
            + (float(median_score or 0.0) * 0.25)
            + (float(median_preflight or 0.0) * 0.15)
        )
        family_rankings.append(
            {
                "family": family,
                "family_label": FAMILY_LABELS.get(family, family),
                "chapters": len(family_rows),
                "tradable_final": tradable_count,
                "watchlist": watchlist_count,
                "defensive": defensive_count,
                "max_score": max_score,
                "median_score": median_score,
                "median_preflight": median_preflight,
                "family_rank_score": round(family_rank, 2),
            }
        )

    def table_for(section_rows: list[dict[str, Any]], *, limit: int = 20) -> list[list[str]]:
        table = [["Rank", "Pattern", "Title", "Family", "Score", "Preflight", "Use", "Why not higher"]]
        for index, row in enumerate(sorted(section_rows, key=sort_key, reverse=True)[:limit], start=1):
            table.append(
                [
                    str(index),
                    row["pattern_id"],
                    row["title"],
                    row["family_label"],
                    _fmt_score(row["tradable_score"]),
                    _fmt_score(row["preflight_score"]),
                    row["recommended_use"],
                    row.get("tradable_blockers") or row["next_action"],
                ]
            )
        return table

    lines = [
        "# Book-Level Ranking Section",
        "",
        "Phần này là lớp xếp hạng đọc được ở cấp sách, lấy cảm hứng từ cách Bulkowski luôn đặt mẫu hình vào bảng so sánh. Điểm quan trọng là rank không được đọc như khuyến nghị mua bán. Một mẫu defensive tốt và một mẫu long-cash tốt trả lời hai câu hỏi khác nhau.",
        "",
        "## Cách xếp hạng",
        "",
        "- `Tradable-final 95`: mẫu đã qua lớp entry/exit/cost/sizing/OOS trong phạm vi dữ liệu hiện có.",
        "- `Watchlist`: mẫu có thống kê đáng theo dõi nhưng chưa đủ bền để gọi là setup giao dịch.",
        "- `Defensive/informational`: mẫu hữu ích để đọc rủi ro, né tránh, hoặc quản trị vị thế; không nên ép thành long-cash signal.",
        "- `Reference/research-only`: mẫu có giá trị mô tả hoặc giáo dục, nhưng chưa đủ điều kiện thực thi.",
        "",
        "Cách đọc đúng: xem rank như bản đồ ưu tiên nghiên cứu và sử dụng, không phải danh sách lệnh. Nếu cần triển khai thật, phải đi qua dashboard/watchlist và rule thực thi riêng.",
        "",
        "## Bảng 1 - Nhóm có thể đưa vào watchlist giao dịch trước",
        "",
        _markdown_table(table_for(tradable_final, limit=20)),
        "",
        "## Bảng 2 - Nhóm long-cash đáng theo dõi nhưng chưa đủ bền",
        "",
        _markdown_table(table_for(long_cash_candidates, limit=20)),
        "",
        "## Bảng 3 - Nhóm phòng thủ và cảnh báo rủi ro",
        "",
        _markdown_table(table_for(defensive, limit=30)),
        "",
        "## Bảng 4 - Nhóm cần đọc thận trọng trước khi triển khai",
        "",
        _markdown_table(table_for(caution, limit=30)),
        "",
        "## Family Ranking",
        "",
        "Family rank ưu tiên family có ít nhất một chapter tradable-final, sau đó mới xét điểm tối đa, điểm trung vị và độ phủ preflight. Đây là ranking cấp sản phẩm, không phải ranking thống kê thuần.",
        "",
    ]
    family_table = [["Rank", "Family", "Chapters", "Tradable-final", "Watchlist", "Defensive", "Max score", "Median score", "Family rank"]]
    for index, row in enumerate(sorted(family_rankings, key=lambda x: x["family_rank_score"], reverse=True), start=1):
        family_table.append(
            [
                str(index),
                row["family_label"],
                str(row["chapters"]),
                str(row["tradable_final"]),
                str(row["watchlist"]),
                str(row["defensive"]),
                _fmt_score(row["max_score"]),
                _fmt_score(row["median_score"]),
                _fmt_score(row["family_rank_score"]),
            ]
        )
    lines.extend([_markdown_table(family_table), ""])
    lines.extend(
        [
            "## Ghi chú diễn giải",
            "",
            "- Rank cao trong nhóm defensive không làm mẫu đó trở thành cơ hội mua trên cổ phiếu cơ sở.",
            "- Rank thấp không có nghĩa chapter vô ích; nhiều chapter thấp vẫn quan trọng để nhận diện bối cảnh rủi ro hoặc làm tư liệu đào tạo.",
            "- Những mẫu có sample mỏng hoặc walk-forward âm không nên được nâng hạng bằng cách siết branch quá mức.",
            "- Khi chuyển sang scanner realtime, mỗi tín hiệu phải mang theo `use_bucket` để người dùng biết đó là cơ hội, watchlist, cảnh báo, hay quan sát tham khảo.",
            "",
        ]
    )

    public_rows = _merge_reader_rows(rows, preflight_rows)
    popularity_rows = sorted(public_rows, key=lambda row: (row["n_events"], row["n_symbols"]), reverse=True)
    long_effectiveness_rows = sorted(
        [row for row in public_rows if _is_long_cash_candidate(row)],
        key=lambda row: (
            row["investment_effectiveness_score"],
            float(row.get("target_first_before_adverse_5pct_rate") or 0.0),
            float(row.get("n_events") or 0.0),
        ),
        reverse=True,
    )
    profit_rows = sorted(
        [row for row in public_rows if isinstance(row.get("profit_total_return_pct"), (int, float))],
        key=lambda row: (
            float(row.get("profit_total_return_pct") or -999.0),
            float(row.get("profit_holdout_return_pct") or -999.0),
            float(row.get("profit_trades") or 0.0),
        ),
        reverse=True,
    )
    defensive_rows = sorted(
        [row for row in public_rows if row["reader_bucket"] == "Phòng thủ / cảnh báo"],
        key=lambda row: (
            row["investment_effectiveness_score"],
            float(row.get("target_first_before_adverse_5pct_rate") or 0.0),
            float(row.get("n_events") or 0.0),
        ),
        reverse=True,
    )
    balanced_rows = sorted(
        public_rows,
        key=lambda row: (
            min(float(row.get("n_events") or 0.0) / 800.0, 1.0) * 35.0
            + row["investment_effectiveness_score"] * 0.65
        ),
        reverse=True,
    )

    payload = {
        "ranking_id": "bulkowski_style_book_ranking_v1",
        "method": "Reader-facing rankings inspired by Bulkowski-style comparative tables. Public sections answer two primary questions: which patterns are most common and which patterns produced the strongest historical simulated profit.",
        "sections": {
            "tradable_final": sorted(tradable_final, key=sort_key, reverse=True),
            "long_cash_watchlist": sorted(long_cash_candidates, key=sort_key, reverse=True),
            "defensive_informational": sorted(defensive, key=sort_key, reverse=True),
            "caution_reference": sorted(caution, key=sort_key, reverse=True),
            "family_ranking": sorted(family_rankings, key=lambda x: x["family_rank_score"], reverse=True),
            "reader_popularity": popularity_rows,
            "reader_long_effectiveness": long_effectiveness_rows,
            "reader_profit": profit_rows,
            "reader_defensive_effectiveness": defensive_rows,
            "reader_balanced": balanced_rows,
        },
    }
    (OUT_DIR / "bulkowski_style_rankings.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT_DIR / "bulkowski_style_rankings.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_bulkowski_style_rankings_pdf(payload)


def write_bulkowski_style_rankings_pdf(payload: dict[str, Any]) -> None:
    """Render the book-level ranking section as a polished standalone PDF."""

    font_regular, font_bold = _register_pdf_fonts()
    styles = _pdf_styles(font_regular, font_bold)
    BOOK_LEVEL_PDF_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = BOOK_LEVEL_PDF_DIR / "bulkowski_style_rankings_final.pdf"
    page_size = A4
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=page_size,
        rightMargin=1.25 * cm,
        leftMargin=1.25 * cm,
        topMargin=1.05 * cm,
        bottomMargin=1.15 * cm,
        title="Xếp hạng mẫu hình - Bulkowski Việt Nam",
        author="Bulkowski Việt Nam",
    )

    def _popularity_table(section_rows: list[dict[str, Any]], *, limit: int) -> Table:
        table_rows = [["#", "Mẫu hình", "Nhóm", "Số mẫu", "Số mã", "Cách đọc"]]
        for index, row in enumerate(section_rows[:limit], start=1):
            table_rows.append(
                [
                    str(index),
                    row.get("title") or row.get("pattern_id"),
                    row.get("family_label", ""),
                    _fmt_int(row.get("n_events")),
                    _fmt_int(row.get("n_symbols")),
                    row.get("reader_bucket", ""),
                ]
            )
        return _pdf_table(table_rows, [0.65 * cm, 4.3 * cm, 3.15 * cm, 1.55 * cm, 1.3 * cm, 3.85 * cm], styles)

    def _quick_popularity_table(section_rows: list[dict[str, Any]], *, limit: int) -> Table:
        table_rows = [["#", "Mẫu hình phổ biến nhất", "Nhóm", "Số mẫu", "Số mã"]]
        for index, row in enumerate(section_rows[:limit], start=1):
            table_rows.append(
                [
                    str(index),
                    row.get("title") or row.get("pattern_id"),
                    row.get("family_label", ""),
                    _fmt_int(row.get("n_events")),
                    _fmt_int(row.get("n_symbols")),
                ]
            )
        return _pdf_table(table_rows, [0.65 * cm, 5.05 * cm, 3.2 * cm, 1.55 * cm, 1.25 * cm], styles)

    def _effectiveness_table(section_rows: list[dict[str, Any]], *, limit: int) -> Table:
        table_rows = [["#", "Mẫu hình", "N", "Hiệu quả", "Mục tiêu trước rủi ro", "Đạt mục tiêu", "Thất bại 5%", "Tốt/xấu"]]
        for index, row in enumerate(section_rows[:limit], start=1):
            table_rows.append(
                [
                    str(index),
                    row.get("title") or row.get("pattern_id"),
                    _fmt_int(row.get("n_events")),
                    _fmt_score(row.get("investment_effectiveness_score")),
                    _fmt_pct(row.get("target_first_before_adverse_5pct_rate"), 1),
                    _fmt_pct(row.get("target_hit_rate"), 1),
                    _fmt_pct(row.get("failure_5pct_rate"), 1),
                    _fmt_score(row.get("mfe_mae_ratio")),
                ]
            )
        return _pdf_table(table_rows, [0.65 * cm, 4.2 * cm, 1.35 * cm, 1.45 * cm, 2.5 * cm, 1.75 * cm, 1.7 * cm, 1.25 * cm], styles)

    def _profit_table(section_rows: list[dict[str, Any]], *, limit: int) -> Table:
        table_rows = [["#", "Mẫu hình", "Lợi nhuận lịch sử", "Số lệnh", "Tỷ lệ thắng", "Kiểm tra", "Giữ lại", "Sụt giảm"]]
        for index, row in enumerate(section_rows[:limit], start=1):
            table_rows.append(
                [
                    str(index),
                    row.get("title") or row.get("pattern_id"),
                    _fmt_pct_points(row.get("profit_total_return_pct")),
                    _fmt_int(row.get("profit_trades")),
                    _fmt_pct_points(row.get("profit_win_rate_pct")),
                    _fmt_pct_points(row.get("profit_validation_return_pct")),
                    _fmt_pct_points(row.get("profit_holdout_return_pct")),
                    _fmt_pct_points(row.get("profit_drawdown_pct")),
                ]
            )
        return _pdf_table(table_rows, [0.65 * cm, 4.05 * cm, 1.85 * cm, 1.35 * cm, 1.55 * cm, 1.45 * cm, 1.45 * cm, 1.45 * cm], styles)

    def _quick_profit_table(section_rows: list[dict[str, Any]], *, limit: int) -> Table:
        table_rows = [["#", "Mẫu hình tạo lợi nhuận cao nhất", "Cách đọc", "Lợi nhuận lịch sử", "Số lệnh", "Giai đoạn giữ lại"]]
        for index, row in enumerate(section_rows[:limit], start=1):
            table_rows.append(
                [
                    str(index),
                    row.get("title") or row.get("pattern_id"),
                    row.get("reader_bucket", ""),
                    _fmt_pct_points(row.get("profit_total_return_pct")),
                    _fmt_int(row.get("profit_trades")),
                    _fmt_pct_points(row.get("profit_holdout_return_pct")),
                ]
            )
        return _pdf_table(table_rows, [0.65 * cm, 5.0 * cm, 2.55 * cm, 1.75 * cm, 1.3 * cm, 1.55 * cm], styles)

    def _balanced_table(section_rows: list[dict[str, Any]], *, limit: int) -> Table:
        table_rows = [["#", "Mẫu hình", "Mẫu", "Hiệu quả", "Cách dùng", "Điểm cần nhớ"]]
        for index, row in enumerate(section_rows[:limit], start=1):
            note = "Phù hợp ưu tiên nghiên cứu và theo dõi" if _is_long_cash_candidate(row) else _short_blocker(row)
            table_rows.append(
                [
                    str(index),
                    row.get("title") or row.get("pattern_id"),
                    _fmt_int(row.get("n_events")),
                    _fmt_score(row.get("investment_effectiveness_score")),
                    row.get("reader_bucket", ""),
                    note,
                ]
            )
        return _pdf_table(table_rows, [0.65 * cm, 4.2 * cm, 1.45 * cm, 1.35 * cm, 2.75 * cm, 5.55 * cm], styles)

    story: list[Any] = []
    sections = payload["sections"]
    story.append(_pdf_paragraph("Xếp hạng mẫu hình", styles["Title"]))
    story.append(
        _pdf_paragraph(
            "Bản này trả lời hai câu hỏi trước tiên: mẫu nào xuất hiện nhiều nhất, và mẫu nào tạo lợi nhuận lịch sử cao nhất trong mô phỏng đã tính phí và trượt giá.",
            styles["Subtitle"],
        )
    )
    story.append(_pdf_paragraph("Câu trả lời nhanh", styles["H1"]))
    story.append(
        _pdf_paragraph(
            "Hai bảng đầu là phần người đọc cần xem trước. Bảng phổ biến cho biết mẫu nào đủ dày để theo dõi thường xuyên. Bảng lợi nhuận cho biết mẫu nào tạo kết quả lịch sử cao hơn trong mô phỏng; đây không phải cam kết cho tương lai.",
            styles["Body"],
        )
    )
    story.append(_pdf_paragraph("Mẫu hình phổ biến nhất", styles["H2"]))
    story.append(_quick_popularity_table(sections["reader_popularity"], limit=10))
    story.append(Spacer(1, 0.18 * cm))
    story.append(_pdf_paragraph("Mẫu hình tạo lợi nhuận lịch sử cao nhất", styles["H2"]))
    story.append(_quick_profit_table(sections["reader_profit"], limit=10))
    story.append(Spacer(1, 0.18 * cm))
    story.append(
        _pdf_paragraph(
            "Ghi chú: mẫu phổ biến không tự động là mẫu sinh lợi tốt; mẫu có lợi nhuận lịch sử cao vẫn cần đọc cùng số lệnh, giai đoạn giữ lại và nhãn sử dụng.",
            styles["Small"],
        )
    )

    story.append(PageBreak())
    story.append(_pdf_paragraph("1. Xếp hạng theo mức độ phổ biến", styles["H1"]))
    story.append(
        _pdf_paragraph(
            "Bảng này xếp từ mẫu xuất hiện nhiều nhất xuống thấp nhất. Đây là bảng dùng để biết mẫu nào có nhiều dữ liệu nhất và đáng được ưu tiên khi xây bộ quét rộng.",
            styles["Body"],
        )
    )
    story.append(_popularity_table(sections["reader_popularity"], limit=15))

    story.append(PageBreak())
    story.append(_pdf_paragraph("2. Xếp hạng theo lợi nhuận kiểm định", styles["H1"]))
    story.append(
        _pdf_paragraph(
            "Bảng này xếp từ lợi nhuận lịch sử cao xuống thấp trong mô phỏng có phí, trượt giá và quy mô vị thế. Khi đọc, không chỉ nhìn cột lợi nhuận; số lệnh và giai đoạn giữ lại cho biết kết quả có dày và bền hay không.",
            styles["Body"],
        )
    )
    story.append(_profit_table(sections["reader_profit"], limit=15))

    story.append(PageBreak())
    story.append(_pdf_paragraph("3. Xếp hạng theo hiệu quả đầu tư", styles["H1"]))
    story.append(
        _pdf_paragraph(
            "Bảng này chỉ xét các mẫu có ý nghĩa mua hoặc theo dõi phía mua. Nó không xếp theo lợi nhuận tuyệt đối, mà theo chất lượng đường đi sau xác nhận: đi tới mục tiêu trước rủi ro, đạt mục tiêu, ít thất bại, và biên thuận lợi tốt hơn biên bất lợi.",
            styles["Body"],
        )
    )
    story.append(_effectiveness_table(sections["reader_long_effectiveness"], limit=15))

    story.append(PageBreak())
    story.append(_pdf_paragraph("4. Xếp hạng cân bằng: vừa phổ biến vừa đáng theo dõi", styles["H1"]))
    story.append(
        _pdf_paragraph(
            "Bảng cân bằng tránh hai cực đoan: một mẫu rất phổ biến nhưng đường đi yếu, hoặc một mẫu rất đẹp nhưng quá ít dữ liệu. Đây là bảng nên dùng để chọn ưu tiên phát triển hệ thống theo dõi.",
            styles["Body"],
        )
    )
    story.append(_balanced_table(sections["reader_balanced"], limit=18))

    story.append(PageBreak())
    story.append(_pdf_paragraph("5. Nhóm phòng thủ và cảnh báo rủi ro", styles["H1"]))
    story.append(
        _pdf_paragraph(
            "Một số mẫu có hiệu quả tốt trong việc mô tả rủi ro, breakdown hoặc trạng thái yếu, nhưng không nên đọc như cơ hội mua cổ phiếu cơ sở. Phần này tách riêng để tránh hiểu sai công dụng.",
            styles["Body"],
        )
    )
    story.append(_effectiveness_table(sections["reader_defensive_effectiveness"], limit=18))

    story.append(PageBreak())
    story.append(_pdf_paragraph("6. Xếp hạng theo family", styles["H1"]))
    story.append(
        _pdf_paragraph(
            "Bảng này cho biết nhóm mẫu hình nào đáng ưu tiên trước khi xây bộ theo dõi. Nhóm đứng cao thường có ít nhất một mẫu sử dụng được rõ ràng, điểm tốt nhất cao và chất lượng các chương trong nhóm không quá lệch.",
            styles["Body"],
        )
    )
    family_rows = [["#", "Nhóm", "Số chương", "Thực thi", "Theo dõi", "Phòng thủ", "Cao nhất", "Trung vị", "Điểm nhóm"]]
    for index, row in enumerate(sections["family_ranking"], start=1):
        family_rows.append(
            [
                str(index),
                row["family_label"],
                str(row["chapters"]),
                str(row["tradable_final"]),
                str(row["watchlist"]),
                str(row["defensive"]),
                _fmt_score(row["max_score"]),
                _fmt_score(row["median_score"]),
                _fmt_score(row["family_rank_score"]),
            ]
        )
    story.append(_pdf_table(family_rows, [0.65 * cm, 4.25 * cm, 1.45 * cm, 1.45 * cm, 1.45 * cm, 1.45 * cm, 1.25 * cm, 1.25 * cm, 1.45 * cm], styles))
    story.append(Spacer(1, 0.2 * cm))
    story.append(
        _pdf_paragraph(
            "Kết luận vận hành: dùng bảng này để biết nhóm mẫu hình nào nên ưu tiên trong bảng theo dõi thực tế. Khi một tín hiệu xuất hiện, nó phải đi kèm nhãn sử dụng: ứng viên giao dịch, theo dõi, phòng thủ hoặc tham khảo.",
            styles["Body"],
        )
    )

    footer = _render_footer("Xếp hạng mẫu hình - Bulkowski Việt Nam", font_regular)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def write_standard_workflow_doc() -> None:
    lines = [
        "# Standard Chapter Workflow",
        "",
        "This is the locked workflow for any future chapter or event-pattern extension. It exists to prevent legacy builders, fallback prose, or self-invented PDF logic from re-entering the project.",
        "",
        "## Canonical Flow",
        "",
        "```mermaid",
        "flowchart TD",
        "  A[Source audit against Bulkowski PDF] --> B[Family or pattern source contract]",
        "  B --> C[Pattern-specific scanner, not copied geometry]",
        "  C --> D[Publication gate and event payload]",
        "  D --> E[Tradable layer if applicable]",
        "  E --> F[AI editorial/refinement artifacts]",
        "  F --> G[canonical_publication_chapter_factory_v1]",
        "  G --> H[pattern_publication_core_v1 render primitives]",
        "  H --> I[Final PDF manifest]",
        "  I --> J[Book-level governance and scanner/watchlist outputs]",
        "```",
        "",
        "## Hard Rules",
        "",
        "- Read the source PDF before defining scanner geometry.",
        "- Share statistics/rendering contracts; do not share morphology rules across families unless the source explicitly supports it.",
        "- Every final PDF must pass through `canonical_publication_chapter_factory_v1` and `pattern_publication_core_v1`.",
        "- AI prose must come from the canonical editorial workflow; technical fallback prose must not be promoted to final PDF.",
        "- Publication-final and tradable-final are separate gates.",
        "- Defensive/downside patterns are not forced into long-cash tradable claims.",
        "- Event-data chapters require event datasets; they must not be approximated by OHLCV-only scanners.",
        "",
        "## Required Gates",
        "",
        "| Gate | Required artifact | Purpose |",
        "|---|---|---|",
        "| Source coverage | `bulkowski_source_pdf_coverage_audit.json` | Confirms source chapter mapping and explicit omissions. |",
        "| Manifest validation | `validate_final_chapters_manifest` | Confirms final PDFs and quarantine state. |",
        "| PDF quality | `final_chapter_pdf_quality_audit.json` | Catches leaked internal terms, missing examples, missing images. |",
        "| Morphology asset audit | `final_chapter_morphology_asset_audit.json` | Confirms schematic and example chart assets. |",
        "| Deep PDF review | `final_chapter_deep_pdf_review.json` | Checks repeated content and example consistency. |",
        "| Scanner/tradable integrity | `scanner_tradable_integrity_audit.json` | Confirms scanner/tradable source integrity. |",
        "| Book-level pack | `book_level_finalization_pack.json` | Handoff from chapters to book/scanner operations. |",
        "",
        "## Stop Conditions",
        "",
        "- Stop per-pattern chapter work when source coverage is complete for OHLCV-compatible chart patterns.",
        "- Stop tradable optimization when additional branch tuning does not improve walk-forward robustness without overfitting.",
        "- Move to scanner operations when publication coverage is complete and remaining source chapters need external event data.",
        "",
    ]
    (OUT_DIR / "standard_chapter_workflow.md").write_text("\n".join(lines), encoding="utf-8")


def write_operational_scanner_spec(rows: list[dict[str, Any]]) -> None:
    tradable_final = [row["pattern_id"] for row in rows if row["tradable_status"] == "tradable_final_95"]
    watchlist = [
        row["pattern_id"]
        for row in rows
        if row["tradable_status"] != "tradable_final_95"
        and "defensive" not in row["recommended_use"]
        and isinstance(row.get("tradable_score"), (int, float))
        and float(row["tradable_score"]) >= 85.0
    ]
    defensive = [row["pattern_id"] for row in rows if "defensive" in row["recommended_use"]]
    reference_only = [
        row["pattern_id"]
        for row in rows
        if row["pattern_id"] not in set(tradable_final + watchlist + defensive)
    ]
    spec = {
        "spec_id": "bulkowski_vietnam_operational_scanner_spec_v1",
        "purpose": "Convert final book chapters into scanner/watchlist outputs without confusing reference labels with tradable signals.",
        "output_schema": {
            "symbol": "Ticker",
            "trade_date": "Detection or breakout date",
            "family": "Pattern family",
            "pattern_id": "Chapter pattern id",
            "direction": "up/down/mixed/defensive",
            "use_bucket": "tradable_final/watchlist/defensive/reference_only",
            "quality_tier": "publication quality tier where available",
            "liquidity_bucket": "liquidity bucket where available",
            "target_family": "calibrated target band where available",
            "risk_flags": "walk-forward, liquidity, scope, sample-depth warnings",
            "source_pdf_chapter": "Bulkowski source chapter mapping",
        },
        "use_buckets": {
            "tradable_final": tradable_final,
            "watchlist": watchlist,
            "defensive": defensive,
            "reference_only": reference_only,
        },
        "gates_before_deploy": [
            "validate_final_chapters_manifest",
            "audit_scanner_tradable_integrity",
            "audit_final_chapter_crosscheck",
            "bulkowski_source_pdf_coverage_audit",
        ],
        "ui_panels": [
            "Today tradable-final candidates",
            "Watchlist confirmations",
            "Defensive risk patterns",
            "Reference-only observations",
            "Book coverage and data limitation notes",
        ],
    }
    (OUT_DIR / "operational_scanner_spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Operational Scanner Specification",
        "",
        "This document converts the finished book into an implementation target for realtime scan outputs.",
        "",
        "## Output Buckets",
        "",
        f"- Tradable-final: `{len(tradable_final)}` patterns",
        f"- Watchlist: `{len(watchlist)}` patterns",
        f"- Defensive: `{len(defensive)}` patterns",
        f"- Reference-only: `{len(reference_only)}` patterns",
        "",
        "## Required Event Schema",
        "",
        _markdown_table([["Field", "Meaning"]] + [[k, v] for k, v in spec["output_schema"].items()]),
        "",
        "## UI Panels",
        "",
    ]
    for panel in spec["ui_panels"]:
        lines.append(f"- {panel}")
    lines.extend(["", "## Deployment Gates", ""])
    for gate in spec["gates_before_deploy"]:
        lines.append(f"- `{gate}`")
    (OUT_DIR / "operational_scanner_spec.md").write_text("\n".join(lines), encoding="utf-8")


def write_pack_index(rows: list[dict[str, Any]], governance: dict[str, Any], coverage: dict[str, Any]) -> None:
    family_counts = Counter(row["family"] for row in rows)
    payload = {
        "pack_id": "book_level_finalization_pack_v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "inputs": {
            "final_manifest": str(FINAL_MANIFEST.relative_to(ROOT)),
            "governance_matrix": str(GOVERNANCE.relative_to(ROOT)),
            "coverage_audit": str(COVERAGE_AUDIT.relative_to(ROOT)),
        },
        "summary": {
            "final_chapters": len(rows),
            "families": len(family_counts),
            "governance_counts": governance.get("counts", {}),
            "coverage_summary": coverage.get("summary", {}),
        },
        "outputs": {
            "executive_summary": str((OUT_DIR / "executive_summary.md").relative_to(ROOT)),
            "chapter_usage_guide": str((OUT_DIR / "chapter_usage_guide.md").relative_to(ROOT)),
            "aggregate_practical_rankings": str((OUT_DIR / "aggregate_practical_rankings.md").relative_to(ROOT)),
            "bulkowski_style_rankings": str((OUT_DIR / "bulkowski_style_rankings.md").relative_to(ROOT)),
            "bulkowski_style_rankings_pdf": str((BOOK_LEVEL_PDF_DIR / "bulkowski_style_rankings_final.pdf").relative_to(ROOT)),
            "chapter_catalog_md": str((OUT_DIR / "book_level_chapter_catalog.md").relative_to(ROOT)),
            "chapter_catalog_csv": str((OUT_DIR / "book_level_chapter_catalog.csv").relative_to(ROOT)),
            "usage_appendix": str((OUT_DIR / "usage_and_limitations_appendix.md").relative_to(ROOT)),
            "scanner_roadmap": str((OUT_DIR / "scanner_operations_roadmap.md").relative_to(ROOT)),
            "standard_workflow": str((OUT_DIR / "standard_chapter_workflow.md").relative_to(ROOT)),
            "operational_scanner_spec": str((OUT_DIR / "operational_scanner_spec.md").relative_to(ROOT)),
        },
    }
    (OUT_DIR / "book_level_finalization_pack.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Book-Level Finalization Pack",
        "",
        "This folder is the handoff from per-pattern chapter building to book-level consolidation and scanner operations.",
        "",
        "## Artifacts",
        "",
        "- [Executive summary](executive_summary.md)",
        "- [Chapter usage guide](chapter_usage_guide.md)",
        "- [Aggregate practical rankings](aggregate_practical_rankings.md)",
        "- [Bulkowski-style ranking section](bulkowski_style_rankings.md)",
        "- [Bulkowski-style ranking PDF](../../book_level/bulkowski_style_rankings_final.pdf)",
        "- [Chapter catalog](book_level_chapter_catalog.md)",
        "- [Chapter catalog CSV](book_level_chapter_catalog.csv)",
        "- [Usage and limitations appendix](usage_and_limitations_appendix.md)",
        "- [Scanner operations roadmap](scanner_operations_roadmap.md)",
        "- [Standard chapter workflow](standard_chapter_workflow.md)",
        "- [Operational scanner specification](operational_scanner_spec.md)",
        "- [Machine-readable pack manifest](book_level_finalization_pack.json)",
        "",
        "## Boundary Decision",
        "",
        "Per-pattern OHLCV chapter implementation is complete for the current Bulkowski chart-pattern scope. Future work should focus on whole-book QA, reader packaging, scanner/watchlist infrastructure, and optional event-data chapters only if the required event datasets are added.",
        "",
    ]
    (OUT_DIR / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = _read_json(FINAL_MANIFEST)
    governance = _read_json(GOVERNANCE)
    coverage = _read_json(COVERAGE_AUDIT)
    preflight = _read_json(DEFAULT_TRADABLE_PREFLIGHT_MATRIX)
    rows = build_catalog(manifest, governance)
    write_catalog(rows)
    write_executive_summary(rows, governance, coverage)
    write_limitations_appendix(rows, coverage)
    write_chapter_usage_guide(rows)
    write_aggregate_rankings(rows)
    write_bulkowski_style_rankings(rows, list(preflight.get("chapters", [])))
    write_scanner_roadmap(rows)
    write_standard_workflow_doc()
    write_operational_scanner_spec(rows)
    write_pack_index(rows, governance, coverage)
    print(
        json.dumps(
            {
                "status": "PASS",
                "out_dir": str(OUT_DIR),
                "chapters": len(rows),
                "families": len({row["family"] for row in rows}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
