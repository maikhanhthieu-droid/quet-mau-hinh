"""Audit Triangle Family chapters against the local Bulkowski source PDF.

The goal is not to re-render chapters.  It produces a source-grounding report
that identifies which Triangle scanner/publication rules are source-aligned,
which are only local proxies, and which should be fixed before the next public
chapter rebuild.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PDF = ROOT / "references/encyclopedia-of-chart-patterns-2nbsped-9786468600-3175723993-9780471668268-0471668265_compress.pdf"
OUT_DIR = ROOT / "artifacts/scanner_v2/triangle_family_source_grounding"
FINAL_DIR = ROOT / "artifacts/final_chapters/triangle_family"
CORE_PATTERNS = ROOT / "scanner/v2/core_patterns.json"
TRIANGLE_FEATURES = ROOT / "scanner/v2/triangle_features.py"


@dataclass(frozen=True)
class AuditRule:
    rule_id: str
    pattern: str
    source_chapter: int
    source_pdf_pages: list[int]
    source_anchor: str
    source_paraphrase: str
    expected_implementation: str
    implementation_status: str
    publication_status: str
    evidence: str
    severity: str
    recommended_action: str


TRIANGLE_RULES: list[dict[str, Any]] = [
    {
        "rule_id": "triangle.shape.core_geometry",
        "patterns": ["ascending", "descending", "symmetrical"],
        "chapter": "47/48/49",
        "pages": [737, 757, 774],
        "anchor": "triangle shape",
        "source": "Mỗi biến thể tam giác được xác định bằng hai đường xu hướng tạo hình tam giác; Ascending có biên trên ngang và biên dưới dốc lên; Descending có biên dưới ngang và biên trên dốc xuống; Symmetrical có hai biên hội tụ.",
        "expected": "Scanner phải có geometry riêng cho từng biến thể, không dùng chung detector Flag/channel.",
    },
    {
        "rule_id": "triangle.touches.two_highs_two_lows",
        "patterns": ["ascending", "descending", "symmetrical"],
        "chapter": "47/48/49",
        "pages": [737, 757, 774],
        "anchor": "at least two",
        "source": "Nguồn yêu cầu ít nhất hai minor highs và hai minor lows chạm hoặc đến gần đường xu hướng tương ứng.",
        "expected": "Scanner phải yêu cầu tối thiểu hai pivot high và hai pivot low; tốt hơn nếu lưu touch counts rõ ràng.",
    },
    {
        "rule_id": "triangle.crossing.no_white_space",
        "patterns": ["ascending", "descending", "symmetrical"],
        "chapter": "47/48/49",
        "pages": [737, 759, 774, 777],
        "anchor": "white space",
        "source": "Nguồn nhấn mạnh giá phải qua lại trong mẫu nhiều lần; mẫu có quá nhiều khoảng trống ở giữa dễ là nhận diện sai.",
        "expected": "Scanner nên có crossing/white-space score hoặc alternating-touch rule; compression alone is not enough.",
    },
    {
        "rule_id": "triangle.breakout.close_outside_boundary",
        "patterns": ["ascending", "descending", "symmetrical"],
        "chapter": "47/48/49",
        "pages": [738, 750, 775],
        "anchor": "closes outside",
        "source": "Breakout được xác nhận khi giá đóng cửa ra ngoài biên mẫu hình; hướng phá vỡ không nên biết trước cho mọi trường hợp.",
        "expected": "Scanner phải dùng close-confirmed breakout outside boundary; Symmetrical phải tách up/down.",
    },
    {
        "rule_id": "triangle.volume.trend_and_breakout",
        "patterns": ["ascending", "descending", "symmetrical"],
        "chapter": "47/48/49",
        "pages": [738, 765, 783],
        "anchor": "volume",
        "source": "Nguồn mô tả volume thường giảm trong quá trình hình thành và breakout volume giúp hiệu năng, nhưng volume không luôn là hard gate.",
        "expected": "Event table nên lưu volume_trend_direction/slope và breakout_volume_ratio; publication nên diễn giải như context, không gate tuyệt đối.",
    },
    {
        "rule_id": "triangle.throwback_pullback",
        "patterns": ["ascending", "descending", "symmetrical"],
        "chapter": "47/48/49",
        "pages": [734, 758, 774],
        "anchor": "throwback",
        "source": "Nguồn báo throwback/pullback là hành vi hậu phá vỡ quan trọng và thường làm giảm hiệu năng.",
        "expected": "Path metrics nên đo retest breakout/formation boundary trong 30 phiên và đưa vào chapter.",
    },
    {
        "rule_id": "triangle.apex_progress",
        "patterns": ["ascending", "descending", "symmetrical"],
        "chapter": "47/48/49",
        "pages": [737, 770, 787],
        "anchor": "apex",
        "source": "Nguồn dùng vị trí breakout so với apex như một thống kê/tactic quan trọng; breakout thường xảy ra trước apex.",
        "expected": "Scanner nên tính apex_idx, apex_progress_pct, bars_to_apex; publication nên dùng như diagnostic, không chỉ chart decoration.",
    },
    {
        "rule_id": "triangle.target.ascending_formula",
        "patterns": ["ascending"],
        "chapter": 47,
        "pages": [748, 749],
        "anchor": "horizontal trend line",
        "source": "Với Ascending Triangle, measure rule upward dùng chiều cao mẫu cộng vào đường kháng cự ngang; downward subtract từ breakout price.",
        "expected": "Upward target nên là resistance + height_abs hoặc phải ghi rõ scanner dùng breakout_price + height_abs như local adjusted convention.",
    },
    {
        "rule_id": "triangle.target.descending_formula",
        "patterns": ["descending"],
        "chapter": 48,
        "pages": [766, 767],
        "anchor": "lower trend line",
        "source": "Với Descending Triangle, measure rule downward dùng chiều cao mẫu trừ từ đường hỗ trợ ngang; upward breakout cộng từ breakout price.",
        "expected": "Downward target nên là support - height_abs hoặc phải ghi rõ scanner dùng breakout_price - height_abs như local adjusted convention.",
    },
    {
        "rule_id": "triangle.target.symmetrical_formula",
        "patterns": ["symmetrical"],
        "chapter": 49,
        "pages": [783, 784, 785],
        "anchor": "formation height",
        "source": "Với Symmetrical Triangle, nguồn nêu measure rule bằng chiều cao mẫu cộng/trừ theo hướng breakout; cũng có biến thể half-staff.",
        "expected": "Scanner target breakout +/- height_abs is broadly aligned; half-staff should remain optional/contextual.",
    },
    {
        "rule_id": "triangle.duration.symmetrical_min",
        "patterns": ["symmetrical"],
        "chapter": 49,
        "pages": [774, 775],
        "anchor": "3 weeks",
        "source": "Symmetrical triangles thường dài hơn 3 tuần; ngắn hơn thường nghiêng về pennants.",
        "expected": "Symmetrical scanner should keep width_min around 15 trading bars or stricter.",
    },
    {
        "rule_id": "triangle.market_trend_context",
        "patterns": ["ascending", "descending", "symmetrical"],
        "chapter": "47/48/49",
        "pages": [752, 770, 787],
        "anchor": "market trend",
        "source": "Nguồn khuyến nghị đọc tam giác theo hướng thị trường và vị trí trong xu hướng; breakouts cùng market trend đáng chú ý hơn.",
        "expected": "Publication should include regime/market trend split as context, with no full point-in-time universe claim.",
    },
    {
        "rule_id": "triangle.yearly_position",
        "patterns": ["ascending", "descending", "symmetrical"],
        "chapter": "47/48/49",
        "pages": [752, 787],
        "anchor": "yearly",
        "source": "Nguồn dùng vị trí trong trading range năm như một lát cắt hiệu năng.",
        "expected": "Event table should include yearly_range_position_pct when enough prior data exists.",
    },
]


PATTERN_FILES = {
    "ascending": ROOT / "scanner/v2/ascending_triangles.py",
    "descending": ROOT / "scanner/v2/descending_triangles.py",
    "symmetrical": ROOT / "scanner/v2/symmetrical_triangles.py",
}

SOURCE_NOTES = {
    "ascending": ROOT / "artifacts/scanner_v2/triangle_family_public_chapters/ascending_triangle/ascending_triangle_source_notes.json",
    "descending": ROOT / "artifacts/scanner_v2/triangle_family_public_chapters/descending_triangle/descending_triangle_source_notes.json",
    "symmetrical": ROOT / "artifacts/scanner_v2/triangle_family_public_chapters/symmetrical_triangle/symmetrical_triangle_source_notes.json",
}

FINAL_PDFS = {
    "ascending": FINAL_DIR / "ascending_triangle_final.pdf",
    "descending": FINAL_DIR / "descending_triangle_final.pdf",
    "symmetrical": FINAL_DIR / "symmetrical_triangle_final.pdf",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _load_json(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _pdf_text(path: Path) -> str:
    if not path.exists():
        return ""
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _source_page_text(reader: PdfReader, pages: Iterable[int]) -> str:
    chunks: list[str] = []
    for page_no in pages:
        idx = int(page_no) - 1
        if 0 <= idx < len(reader.pages):
            chunks.append(reader.pages[idx].extract_text() or "")
    return "\n".join(chunks).lower()


def _all_pattern_code(patterns: Iterable[str]) -> str:
    return "\n".join([_read(TRIANGLE_FEATURES), *[_read(PATTERN_FILES[p]) for p in patterns]])


def _final_text(patterns: Iterable[str]) -> str:
    return "\n".join(_pdf_text(FINAL_PDFS[p]) for p in patterns).lower()


def _source_notes_count(pattern: str) -> int:
    notes = _load_json(SOURCE_NOTES[pattern])
    return len(notes.get("source_rules") or [])


def _core_rule_counts() -> dict[str, int]:
    registry = _load_json(CORE_PATTERNS)
    patterns = registry.get("patterns") if isinstance(registry.get("patterns"), Mapping) else {}
    key_map = {
        "ascending": "triangles_ascending",
        "descending": "triangles_descending",
        "symmetrical": "triangles_symmetrical",
    }
    counts: dict[str, int] = {}
    for short, key in key_map.items():
        pattern = patterns.get(key) if isinstance(patterns.get(key), Mapping) else {}
        counts[short] = len(pattern.get("rules") or [])
    return counts


def _has_any(text: str, needles: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(n.lower() in lowered for n in needles)


def _implementation_status(rule: Mapping[str, Any]) -> tuple[str, str]:
    patterns = list(rule["patterns"])
    code = _all_pattern_code(patterns)
    rid = str(rule["rule_id"])
    if rid == "triangle.shape.core_geometry":
        ok = all(
            token in code
            for token in [
                "compression_ratio",
                "height_min_pct",
                "height_max_pct",
            ]
        )
        return ("implemented", "Pattern-specific geometry configs and compression/height gates exist.") if ok else ("missing", "Core geometry gates not found.")
    if rid == "triangle.touches.two_highs_two_lows":
        ok = "len(highs) < 2" in code and "len(lows) < 2" in code
        return ("implemented", "Detectors require at least two highs and two lows.") if ok else ("missing", "Two-touch minimum not found.")
    if rid == "triangle.crossing.no_white_space":
        ok = _has_any(code, ["white_space", "crossing_score", "alternating"])
        return ("implemented", "Explicit crossing/white-space gate found.") if ok else ("proxy", "Only two-touch/compression proxies exist; no explicit white-space or alternating-touch score.")
    if rid == "triangle.breakout.close_outside_boundary":
        ok = "close >" in code or "close <" in code
        return ("implemented", "Breakout checks use close outside the relevant boundary.") if ok else ("missing", "Close-confirmed breakout not found.")
    if rid == "triangle.volume.trend_and_breakout":
        has_breakout_volume = "breakout_volume_ratio" in code
        has_volume_trend = _has_any(code, ["volume_trend", "volume_slope"])
        if has_breakout_volume and has_volume_trend:
            return "implemented", "Breakout volume and in-pattern volume trend are both present."
        if has_breakout_volume:
            return "proxy", "Breakout volume is present; in-pattern volume trend is not yet computed for Triangle."
        return "missing", "No Triangle volume diagnostics found."
    if rid == "triangle.throwback_pullback":
        ok = _has_any(code, ["throwback", "pullback", "return_to_breakout"])
        return ("implemented", "Triangle events include retest metrics.") if ok else ("missing", "Triangle path metrics do not include throwback/pullback retest fields.")
    if rid == "triangle.apex_progress":
        ok = _has_any(code, ["apex_idx", "apex_progress", "bars_to_apex"])
        return ("implemented", "Apex progress fields exist.") if ok else ("missing", "Triangle v2 scanners do not compute apex progress.")
    if rid == "triangle.target.ascending_formula":
        asc = _read(PATTERN_FILES["ascending"])
        if "target_price = float(breakout_price) + height_abs" in asc:
            return "needs_fix", "Ascending uses breakout_price + height_abs; source primary upward rule is resistance + height_abs."
        if "target_price = resistance + height_abs" in asc:
            return "implemented", "Ascending upward target uses resistance + height_abs."
        return "unknown", "Could not identify Ascending target formula."
    if rid == "triangle.target.descending_formula":
        desc = _read(PATTERN_FILES["descending"])
        if "target_price = float(breakout_price) - height_abs" in desc:
            return "needs_fix", "Descending uses breakout_price - height_abs; source primary downward rule is support - height_abs."
        if "target_price = support - height_abs" in desc:
            return "implemented", "Descending downward target uses support - height_abs."
        return "unknown", "Could not identify Descending target formula."
    if rid == "triangle.target.symmetrical_formula":
        sym = _read(PATTERN_FILES["symmetrical"])
        ok = "breakout_price) + height_abs" in sym and "breakout_price) - height_abs" in sym
        return ("implemented", "Symmetrical uses breakout +/- height_abs.") if ok else ("unknown", "Could not identify Symmetrical target formula.")
    if rid == "triangle.duration.symmetrical_min":
        sym = _read(PATTERN_FILES["symmetrical"])
        ok = re.search(r"width_min_bars:\s*int\s*=\s*(1[5-9]|[2-9][0-9])", sym) is not None
        return ("implemented", "Symmetrical width_min_bars is at least three trading weeks.") if ok else ("needs_fix", "Symmetrical minimum duration is below the source-guided pennant boundary.")
    if rid == "triangle.market_trend_context":
        ok = _has_any(code, ["market_regime", "regime_proxy_table", "classify_market_regimes"])
        return ("implemented", "Regime proxy fields/tables exist.") if ok else ("missing", "No regime context found.")
    if rid == "triangle.yearly_position":
        ok = _has_any(code, ["yearly_range_position_pct"])
        return ("implemented", "Yearly range position exists.") if ok else ("missing", "Triangle scanners do not compute yearly range position.")
    return "unknown", "No audit matcher for this rule."


def _publication_status(rule: Mapping[str, Any]) -> tuple[str, str]:
    patterns = list(rule["patterns"])
    text = _final_text(patterns)
    rid = str(rule["rule_id"])
    if rid in {"triangle.shape.core_geometry", "triangle.breakout.close_outside_boundary", "triangle.market_trend_context"}:
        ok = _has_any(text, ["kháng cự", "hỗ trợ", "phá vỡ", "thanh khoản", "trạng thái"])
        return ("present", "Public PDFs discuss geometry/breakout/context.") if ok else ("thin", "Public PDFs do not clearly discuss this rule.")
    if rid == "triangle.touches.two_highs_two_lows":
        ok = _has_any(text, ["hai lần", "hai đỉnh", "hai đáy", "ít nhất hai"])
        return ("present", "Touch-count language is present.") if ok else ("missing", "Public PDFs do not explain the two-touch requirement.")
    if rid == "triangle.crossing.no_white_space":
        ok = _has_any(text, ["khoảng trống", "qua lại", "white space"])
        return ("present", "White-space/crossing language is present.") if ok else ("missing", "Public PDFs do not explain the white-space/crossing failure mode.")
    if rid == "triangle.volume.trend_and_breakout":
        ok = _has_any(text, ["volume", "khối lượng", "breakout volume"])
        return ("present", "Volume context is discussed.") if ok else ("missing", "Public PDFs do not discuss Bulkowski's volume dimension.")
    if rid == "triangle.throwback_pullback":
        ok = _has_any(text, ["throwback", "pullback", "kiểm định lại", "về lại vùng phá vỡ"])
        return ("present", "Retest behavior is discussed.") if ok else ("missing", "Public PDFs do not discuss throwback/pullback.")
    if rid == "triangle.apex_progress":
        ok = _has_any(text, ["apex", "đỉnh tam giác", "điểm hội tụ"])
        return ("present", "Apex progress is discussed.") if ok else ("missing", "Public PDFs do not discuss breakout position relative to apex.")
    if rid.startswith("triangle.target"):
        ok = _has_any(text, ["measure rule", "mục tiêu", "chiều cao"])
        return ("partial", "Target/height language is present, but source formula differences are not fully disclosed.") if ok else ("missing", "Public PDFs do not explain target formula.")
    if rid == "triangle.duration.symmetrical_min":
        ok = _has_any(text, ["3 tuần", "ba tuần", "pennant", "cờ đuôi nheo"])
        return ("present", "Duration/pennant boundary is discussed.") if ok else ("missing", "Symmetrical PDF does not explain minimum duration vs pennant.")
    if rid == "triangle.yearly_position":
        ok = _has_any(
            text,
            [
                "biên năm",
                "yearly",
                "vùng giá năm",
                "vùng của năm",
                "đáy của năm",
                "đỉnh của năm",
                "bối cảnh rộng hơn",
            ],
        )
        return ("present", "Yearly position is discussed.") if ok else ("missing", "Public PDFs do not discuss yearly-range position.")
    return "unknown", "No publication matcher for this rule."


def _severity(implementation: str, publication: str, rule_id: str) -> str:
    if implementation == "needs_fix":
        return "high"
    if implementation == "missing" and publication == "missing":
        return "medium"
    if implementation == "proxy" or publication in {"missing", "thin"}:
        return "medium"
    if rule_id in {"triangle.volume.trend_and_breakout", "triangle.throwback_pullback", "triangle.apex_progress", "triangle.yearly_position"}:
        return "low"
    return "info"


def _recommendation(rule_id: str, implementation: str, publication: str) -> str:
    if rule_id == "triangle.target.ascending_formula" and implementation == "needs_fix":
        return "Change Ascending target_price to resistance + height_abs, or explicitly create a separate local_target_price field and stop calling breakout_price + height_abs the Bulkowski measure rule."
    if rule_id == "triangle.target.descending_formula" and implementation == "needs_fix":
        return "Change Descending target_price to support - height_abs, or explicitly create a separate local_target_price field and stop calling breakout_price - height_abs the Bulkowski measure rule."
    if rule_id == "triangle.crossing.no_white_space":
        if implementation != "implemented":
            return "Add alternating-touch/crossing score and a white-space penalty to Triangle publication-quality tiering."
        return "Expose crossing/white-space language in the regenerated public chapter."
    if rule_id == "triangle.volume.trend_and_breakout":
        if implementation != "implemented":
            return "Add in-pattern volume_trend_direction/slope to Triangle events; keep breakout_volume_ratio as confirmation context."
        return "Expose volume trend and breakout volume as context in the regenerated public chapter."
    if rule_id == "triangle.throwback_pullback":
        if implementation != "implemented":
            return "Add return-to-breakout/formation-boundary retest metrics within 30 sessions and expose them in post-breakout behavior tables."
        return "Expose return-to-breakout/formation-boundary retest metrics in the regenerated public chapter."
    if rule_id == "triangle.apex_progress":
        if implementation != "implemented":
            return "Compute trendline intersection and breakout progress to apex; use it as a diagnostic split."
        return "Expose apex progress as a diagnostic in the regenerated public chapter."
    if rule_id == "triangle.yearly_position":
        if implementation != "implemented":
            return "Add yearly_range_position_pct from available prior OHLCV and use it as a context split when coverage is enough."
        return "Expose yearly range position as a context split when coverage is enough."
    if publication in {"missing", "thin"}:
        return "Expand Triangle source notes and public narrative so this rule is visible to readers."
    return "No immediate change required."


def _required_next_actions(
    rules: Iterable[AuditRule],
    source_contract_expanded: bool,
    source_notes_are_thin: bool,
) -> list[str]:
    actions: list[str] = []
    for rule in rules:
        if rule.severity in {"high", "medium"} and rule.recommended_action != "No immediate change required.":
            actions.append(rule.recommended_action)
    if not source_contract_expanded:
        actions.append("Expand Triangle core_patterns from thin source contracts to the full source-grounded identification/tactic matrix.")
    if source_notes_are_thin:
        actions.append("Expand Triangle source_notes so each chapter carries the source-grounded rules used by the canonical publication factory.")

    unique_actions: list[str] = []
    seen: set[str] = set()
    for action in actions:
        if action not in seen:
            unique_actions.append(action)
            seen.add(action)
    if not unique_actions:
        return [
            "No high or medium Triangle source-grounding actions remain under the current available-data scope. Keep optional context diagnostics such as yearly range position in future scanner extensions only when coverage supports them."
        ]
    return unique_actions


def build_audit() -> dict[str, Any]:
    reader = PdfReader(str(SOURCE_PDF))
    rules: list[AuditRule] = []
    source_anchor_missing: list[str] = []
    for raw in TRIANGLE_RULES:
        pages = list(raw["pages"])
        source_text = _source_page_text(reader, pages)
        anchor = str(raw["anchor"]).lower()
        if anchor and anchor not in source_text:
            source_anchor_missing.append(str(raw["rule_id"]))
        impl_status, impl_evidence = _implementation_status(raw)
        pub_status, pub_evidence = _publication_status(raw)
        severity = _severity(impl_status, pub_status, str(raw["rule_id"]))
        rules.append(
            AuditRule(
                rule_id=str(raw["rule_id"]),
                pattern=", ".join(raw["patterns"]),
                source_chapter=raw["chapter"],
                source_pdf_pages=pages,
                source_anchor=str(raw["anchor"]),
                source_paraphrase=str(raw["source"]),
                expected_implementation=str(raw["expected"]),
                implementation_status=impl_status,
                publication_status=pub_status,
                evidence=f"{impl_evidence} {pub_evidence}",
                severity=severity,
                recommended_action=_recommendation(str(raw["rule_id"]), impl_status, pub_status),
            )
        )

    final_text_lengths = {name: len(_pdf_text(path)) for name, path in FINAL_PDFS.items()}
    source_note_counts = {name: _source_notes_count(name) for name in SOURCE_NOTES}
    core_rule_counts = _core_rule_counts()
    high = [r.rule_id for r in rules if r.severity == "high"]
    medium = [r.rule_id for r in rules if r.severity == "medium"]
    core_geometry_ok = all(
        r.implementation_status in {"implemented", "proxy"}
        for r in rules
        if r.rule_id
        in {
            "triangle.shape.core_geometry",
            "triangle.touches.two_highs_two_lows",
            "triangle.breakout.close_outside_boundary",
        }
    )
    source_contract_expanded = all(count >= 6 for count in core_rule_counts.values())
    source_notes_are_thin = any(count < 6 for count in source_note_counts.values())
    if not high and not medium and source_contract_expanded and not source_notes_are_thin:
        source_grounding_level = "publication_aligned"
        main_conclusion = (
            "Triangle implementation, source contract, source notes, and final PDFs are now aligned on the audited source-grounded rules. "
            "No high or medium source-grounding findings remain under the current available-data scope."
        )
    elif not high and source_contract_expanded:
        source_grounding_level = "implementation_aligned"
        main_conclusion = (
            "Triangle implementation and source contract are now aligned on core geometry, close-confirmed breakout, "
            "Ascending/Descending target anchors, and the added diagnostics. Remaining medium findings are publication-layer "
            "staleness from old PDFs/source_notes and should clear only after the next controlled Triangle render."
        )
    else:
        source_grounding_level = "partial"
        main_conclusion = (
            "Triangle scanners are grounded on core shape and close-confirmed breakout, "
            "but current source notes/public chapters are not yet grounded at Flag-level depth. "
            "The biggest technical mismatch is the Ascending/Descending measure-rule anchor."
        )
    required_next_actions = _required_next_actions(rules, source_contract_expanded, source_notes_are_thin)
    return {
        "audit_id": "triangle_family_source_grounding_audit_v1",
        "source_pdf": str(SOURCE_PDF.relative_to(ROOT)),
        "scope": "Triangle Family first: Ascending, Descending, Symmetrical final PDFs and v2 scanners.",
        "overall": {
            "source_grounding_level": source_grounding_level,
            "core_geometry_grounded": core_geometry_ok,
            "source_contract_expanded": source_contract_expanded,
            "source_notes_are_thin": source_notes_are_thin,
            "high_severity_count": len(high),
            "medium_severity_count": len(medium),
            "main_conclusion": main_conclusion,
        },
        "source_note_counts": source_note_counts,
        "core_rule_counts": core_rule_counts,
        "final_pdf_text_lengths": final_text_lengths,
        "source_anchor_missing": source_anchor_missing,
        "rules": [asdict(rule) for rule in rules],
        "required_next_actions": required_next_actions,
    }


def write_markdown(audit: Mapping[str, Any], path: Path) -> None:
    lines: list[str] = []
    lines.append("# Triangle Family Source-Grounding Audit")
    lines.append("")
    lines.append(f"- Audit ID: `{audit['audit_id']}`")
    lines.append(f"- Source PDF: `{audit['source_pdf']}`")
    lines.append(f"- Scope: {audit['scope']}")
    lines.append("")
    overall = audit["overall"]
    lines.append("## Kết luận")
    lines.append("")
    lines.append(str(overall["main_conclusion"]))
    lines.append("")
    lines.append(
        f"High severity: {overall['high_severity_count']}; medium severity: {overall['medium_severity_count']}; "
        f"source notes thin: {overall['source_notes_are_thin']}."
    )
    lines.append("")
    lines.append("## Rule Matrix")
    lines.append("")
    lines.append("| Rule | Pattern | Source pages | Implementation | Publication | Severity | Action |")
    lines.append("|---|---|---:|---|---|---|---|")
    for rule in audit["rules"]:
        pages = ",".join(str(p) for p in rule["source_pdf_pages"])
        lines.append(
            "| "
            + " | ".join(
                [
                    rule["rule_id"],
                    rule["pattern"],
                    pages,
                    rule["implementation_status"],
                    rule["publication_status"],
                    rule["severity"],
                    rule["recommended_action"],
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("## Việc cần làm tiếp theo")
    lines.append("")
    for item in audit["required_next_actions"]:
        lines.append(f"- {item}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    audit = build_audit()
    json_path = OUT_DIR / "triangle_family_source_grounding_audit.json"
    md_path = OUT_DIR / "triangle_family_source_grounding_audit.md"
    json_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(audit, md_path)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "overall": audit["overall"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
