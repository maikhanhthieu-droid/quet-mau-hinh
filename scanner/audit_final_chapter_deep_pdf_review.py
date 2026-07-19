"""Deep PDF review for final public chapters.

This audit is intentionally reader-facing. It checks each final PDF for:

- public-token leaks such as n/a/None/TODO/debug;
- required canonical sections and their order;
- example-section image presence;
- duplicate or semantically inconsistent example charts/events;
- nearly blank pages that indicate layout breakage.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageChops
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.audit_final_chapter_pdf_quality import _page_image_counts  # noqa: E402
from scanner.rebuild_source_guided_final_chapters import _load_charts, _load_publication_spec, _read_json, _slug_from_entry  # noqa: E402
from scanner.validate_final_chapters_manifest import DEFAULT_MANIFEST  # noqa: E402


OUT_DIR = ROOT / "artifacts/final_chapters/governance/deep_pdf_review"
TMP_DIR = ROOT / "tmp/pdfs/deep_pdf_review"
PUBLIC_TOKEN_RE = re.compile(r"\b(n/a|nan|none|null|todo|placeholder|debug)\b", re.IGNORECASE)
PUBLIC_PLACEHOLDER_PHRASES = [
    "Quy tắc nguồn đã được chuyển thành",
    "điều kiện hình học trong bộ quét",
    "Quy tắc nguồn được tóm tắt trong bảng nhận diện của chương",
    "Tham số hiện tại:",
    "Bộ quét kiểm tra",
    "Bộ quét ưu tiên",
    "Thiếu bảng quy tắc đã duyệt",
    "không dùng suy diễn tự động",
]
REQUIRED_SECTIONS = [
    "Kết quả quan trọng",
    "Mẫu hình hoạt động ra sao",
    "Cách nhận diện",
    "Ví dụ minh họa",
    "Tập trung vào thất bại",
    "Cách đọc kết quả quan trọng",
    "Khi mẫu đáng chú ý hơn",
    "Cách sử dụng thực tế",
    "Phụ lục kỹ thuật",
]


def _pdf_pages_text(path: Path) -> list[str]:
    reader = PdfReader(str(path))
    return [page.extract_text() or "" for page in reader.pages]


def _render_page(path: Path, page_no: int, out_dir: Path) -> Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / f"{path.stem}_p{page_no:03d}"
    try:
        subprocess.run(
            ["pdftoppm", "-png", "-f", str(page_no), "-l", str(page_no), str(path), str(prefix)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    rendered = prefix.with_name(f"{prefix.name}-{page_no:02d}.png")
    if rendered.exists():
        return rendered
    matches = sorted(out_dir.glob(f"{prefix.name}-*.png"))
    return matches[0] if matches else None


def _content_ratio(image_path: Path) -> float:
    image = Image.open(image_path).convert("RGB")
    white = Image.new("RGB", image.size, "white")
    diff = ImageChops.difference(image, white).convert("L")
    bbox = diff.point(lambda x: 255 if x > 8 else 0).getbbox()
    if not bbox:
        return 0.0
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    return float((width * height) / (image.size[0] * image.size[1]))


def _chart_digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return str(path)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _example_event_issues(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    examples = payload.get("example_events") if isinstance(payload.get("example_events"), Mapping) else {}
    seen_ids: dict[str, str] = {}
    for label, raw_event in examples.items():
        if not isinstance(raw_event, Mapping):
            continue
        detection_id = str(raw_event.get("detection_id") or "")
        if detection_id:
            if detection_id in seen_ids:
                issues.append(
                    {
                        "severity": "warning",
                        "check": "duplicate_example_detection_id",
                        "label": label,
                        "duplicate_of": seen_ids[detection_id],
                        "detection_id": detection_id,
                    }
                )
            seen_ids[detection_id] = str(label)
        group = str(raw_event.get("market_group") or "")
        if group and "VN100" not in group and group != "VN30":
            issues.append(
                {
                    "severity": "warning",
                    "check": "example_not_vn100",
                    "label": label,
                    "symbol": raw_event.get("symbol"),
                    "market_group": group,
                }
            )
        target_hit = _as_bool(raw_event.get("target_hit"))
        failure_5pct = _as_bool(raw_event.get("failure_5pct"))
        if label == "textbook_success" and (not target_hit or failure_5pct):
            issues.append(
                {
                    "severity": "fail",
                    "check": "textbook_success_outcome_mismatch",
                    "label": label,
                    "symbol": raw_event.get("symbol"),
                    "target_hit": raw_event.get("target_hit"),
                    "failure_5pct": raw_event.get("failure_5pct"),
                }
            )
        if label == "failure" and target_hit and not failure_5pct:
            issues.append(
                {
                    "severity": "fail",
                    "check": "failure_example_outcome_mismatch",
                    "label": label,
                    "symbol": raw_event.get("symbol"),
                    "target_hit": raw_event.get("target_hit"),
                    "failure_5pct": raw_event.get("failure_5pct"),
                }
            )
    return issues


def _chart_issues(entry: Mapping[str, Any], payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    source_pdf = Path(str(entry.get("source_pdf") or entry.get("pdf")))
    try:
        charts = _load_charts(source_pdf, Path(str(entry.get("payload"))), _slug_from_entry(entry))
    except Exception as exc:  # noqa: BLE001
        return [{"severity": "fail", "check": "load_charts", "detail": str(exc)}]
    example_keys = ["textbook_success", "middle_case", "failure"]
    digests: dict[str, str] = {}
    for key in example_keys:
        chart = charts.get(key)
        if chart is None:
            continue
        digest = _chart_digest(chart)
        if digest in digests:
            issues.append(
                {
                    "severity": "warning",
                    "check": "duplicate_example_chart_file",
                    "label": key,
                    "duplicate_of": digests[digest],
                    "chart": str(chart),
                }
            )
        digests[digest] = key
    return issues


def _has_public_rule_rows(value: Any) -> bool:
    return isinstance(value, list) and any(isinstance(item, (Mapping, list, tuple)) for item in value)


def _rule_source_issues(entry: Mapping[str, Any], payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Final PDFs must not rely on publication-core heuristic rule prose."""

    if _has_public_rule_rows(payload.get("source_rules_public")):
        return []
    spec = _load_publication_spec(entry, payload)
    if _has_public_rule_rows(spec.get("public_rule_rows")):
        return []
    return [
        {
            "severity": "fail",
            "check": "missing_curated_public_rule_rows",
            "detail": "Final chapter must provide source_rules_public in the payload or explicit public_rule_rows in the publication spec.",
        }
    ]


def audit_one(entry: Mapping[str, Any]) -> dict[str, Any]:
    pdf = Path(str(entry.get("pdf")))
    payload_path = Path(str(entry.get("payload")))
    payload = _read_json(payload_path) if payload_path.exists() else {}
    pages = _pdf_pages_text(pdf)
    image_counts = _page_image_counts(pdf)
    issues: list[dict[str, Any]] = []

    full_text = "\n".join(pages)
    for page_no, text in enumerate(pages, start=1):
        for match in PUBLIC_TOKEN_RE.finditer(text):
            issues.append(
                {
                    "severity": "fail",
                    "check": "public_token_leak",
                    "page": page_no,
                    "token": match.group(0),
                    "context": text[max(0, match.start() - 60) : match.end() + 60].replace("\n", " "),
                }
            )
        for phrase in PUBLIC_PLACEHOLDER_PHRASES:
            if phrase in text:
                issues.append(
                    {
                        "severity": "fail",
                        "check": "public_placeholder_phrase",
                        "page": page_no,
                        "phrase": phrase,
                    }
                )

    positions = []
    for section in REQUIRED_SECTIONS:
        pos = full_text.find(section)
        if pos < 0:
            issues.append({"severity": "fail", "check": "missing_required_section", "section": section})
        positions.append(pos)
    ordered_positions = [pos for pos in positions if pos >= 0]
    if ordered_positions != sorted(ordered_positions):
        issues.append({"severity": "fail", "check": "section_order", "detail": "Required sections are not in canonical order."})

    example_pages = [idx + 1 for idx, text in enumerate(pages) if "Ví dụ minh họa" in text]
    if not example_pages:
        issues.append({"severity": "fail", "check": "missing_example_section"})
    for page_no in example_pages:
        nearby_images = sum(image_counts[max(0, page_no - 1) : min(len(image_counts), page_no + 1)])
        if nearby_images <= 0:
            issues.append({"severity": "fail", "check": "example_section_without_nearby_chart", "page": page_no})

    for page_no, text in enumerate(pages, start=1):
        if len(text.strip()) < 20 and (image_counts[page_no - 1] if page_no - 1 < len(image_counts) else 0) == 0:
            image = _render_page(pdf, page_no, TMP_DIR / pdf.stem)
            ratio = _content_ratio(image) if image else 0.0
            if ratio < 0.015:
                issues.append({"severity": "warning", "check": "nearly_blank_page", "page": page_no, "content_ratio": round(ratio, 4)})

    issues.extend(_example_event_issues(payload))
    issues.extend(_chart_issues(entry, payload))
    issues.extend(_rule_source_issues(entry, payload))
    fail_count = sum(1 for issue in issues if issue["severity"] == "fail")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    return {
        "pattern_id": entry.get("pattern_id"),
        "family": entry.get("family"),
        "pdf": str(pdf),
        "pages": len(pages),
        "status": "FAIL" if fail_count else "PASS",
        "fail_count": fail_count,
        "warning_count": warning_count,
        "issues": issues,
        "image_counts": image_counts,
    }


def build_audit(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    chapters = [chapter for chapter in manifest.get("chapters", []) if isinstance(chapter, Mapping)]
    rows = [audit_one(chapter) for chapter in chapters]
    return {
        "audit_id": "final_chapter_deep_pdf_review_v1",
        "status": "PASS" if all(row["status"] == "PASS" for row in rows) else "FAIL",
        "counts": {
            "chapters": len(rows),
            "fail": sum(1 for row in rows if row["status"] == "FAIL"),
            "warnings": sum(int(row["warning_count"]) for row in rows),
        },
        "chapters": rows,
    }


def write_markdown(audit: Mapping[str, Any], path: Path) -> None:
    lines = [
        "# Final Chapter Deep PDF Review",
        "",
        f"- Audit ID: `{audit['audit_id']}`",
        f"- Status: `{audit['status']}`",
        f"- Chapters: `{audit['counts']['chapters']}`",
        f"- Failed chapters: `{audit['counts']['fail']}`",
        f"- Warnings: `{audit['counts']['warnings']}`",
        "",
        "| Family | Pattern | Status | Fails | Warnings | Notes |",
        "|---|---|---|---:|---:|---|",
    ]
    for row in audit["chapters"]:
        notes = "; ".join(f"{issue['check']}@p{issue.get('page', '-')}" for issue in row["issues"][:4])
        lines.append(
            f"| {row['family']} | {row['pattern_id']} | {row['status']} | {row['fail_count']} | {row['warning_count']} | {notes} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    audit = build_audit()
    json_path = OUT_DIR / "final_chapter_deep_pdf_review.json"
    md_path = OUT_DIR / "final_chapter_deep_pdf_review.md"
    json_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    write_markdown(audit, md_path)
    print(json.dumps({"status": audit["status"], "counts": audit["counts"], "json": str(json_path), "markdown": str(md_path)}, ensure_ascii=False, indent=2))
    if audit["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
