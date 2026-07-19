"""Audit final chapter PDFs for reader-facing defects.

The canonical flow audit proves that a chapter went through the right factory.
This audit checks what the reader actually sees: leaked internal terms, stale
family vocabulary, missing example charts, sparse pages, and placeholder values.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.rebuild_source_guided_final_chapters import _load_charts  # noqa: E402


DEFAULT_MANIFEST = Path("artifacts/final_chapters/final_chapters_manifest.json")
DEFAULT_OUT_DIR = Path("artifacts/final_chapters/governance")
AUDIT_ID = "final_chapter_pdf_quality_audit_v1"

GLOBAL_FORBIDDEN_PATTERNS = {
    "placeholder_na": re.compile(r"\bn/a\b", re.IGNORECASE),
    "placeholder_na_percent": re.compile(r"chưa đủ dữ liệu\s*%", re.IGNORECASE),
    "english_payload": re.compile(r"\bpayload\b", re.IGNORECASE),
    "english_chapter": re.compile(r"\bchapter\b", re.IGNORECASE),
    "english_public": re.compile(r"\bpublic\b", re.IGNORECASE),
    "english_scanner": re.compile(r"\bscanner\b", re.IGNORECASE),
    "english_pipeline": re.compile(r"\bpipeline\b", re.IGNORECASE),
    "english_setup": re.compile(r"\bsetup\b", re.IGNORECASE),
    "english_backtest": re.compile(r"\bbacktest\b", re.IGNORECASE),
    "internal_branch": re.compile(r"\bbranch_id\b|\bdata_limited\b|publication_quality_tier", re.IGNORECASE),
    "internal_review_pack": re.compile(r"formal human|external publication|review pack generated", re.IGNORECASE),
    "internal_contract": re.compile(r"Contract nhân rộng|Release gate|Scope headline", re.IGNORECASE),
    "no_executable_english": re.compile(r"No executable entry/exit/cost/sizing/OOS", re.IGNORECASE),
}

NON_FLAG_FORBIDDEN_PATTERNS = {
    "flag_body_leak": re.compile(r"thân cờ|cột cờ", re.IGNORECASE),
}


def _read_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return payload if isinstance(payload, Mapping) else {}


def _pdf_text(path: Path) -> str:
    if shutil.which("pdftotext"):
        return subprocess.check_output(["pdftotext", str(path), "-"], text=True, errors="replace")
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _pdf_pages(path: Path) -> list[str]:
    reader = PdfReader(str(path))
    return [page.extract_text() or "" for page in reader.pages]


def _pdf_image_count(path: Path) -> int | None:
    if not shutil.which("pdfimages"):
        return None
    out = subprocess.check_output(["pdfimages", "-list", str(path)], text=True, errors="replace")
    return sum(1 for line in out.splitlines() if " image " in line and " smask " not in line)


def _page_image_counts(path: Path) -> list[int]:
    reader = PdfReader(str(path))

    def count_xobjects(obj: Any) -> int:
        try:
            obj = obj.get_object()
        except AttributeError:
            pass
        if not hasattr(obj, "get"):
            return 0
        subtype = obj.get("/Subtype")
        if subtype == "/Image":
            return 1
        total = 0
        resources = obj.get("/Resources")
        if resources:
            try:
                resources = resources.get_object()
            except AttributeError:
                pass
            xobjects = resources.get("/XObject") if hasattr(resources, "get") else None
            if xobjects:
                try:
                    xobjects = xobjects.get_object()
                except AttributeError:
                    pass
                for child in xobjects.values():
                    total += count_xobjects(child)
        return total

    counts: list[int] = []
    for page in reader.pages:
        resources = page.get("/Resources")
        total = 0
        if resources:
            try:
                resources = resources.get_object()
            except AttributeError:
                pass
            xobjects = resources.get("/XObject") if hasattr(resources, "get") else None
            if xobjects:
                try:
                    xobjects = xobjects.get_object()
                except AttributeError:
                    pass
                for child in xobjects.values():
                    total += count_xobjects(child)
        counts.append(total)
    return counts


def _chart_digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return str(path.resolve())


def _unique_expected_chart_count(charts: Mapping[str, Path]) -> int:
    digests: set[str] = set()
    total = 0
    for key, path in charts.items():
        digest = _chart_digest(Path(path))
        if key != "schematic" and digest in digests:
            continue
        digests.add(digest)
        total += 1
    return total


def _slug(chapter: Mapping[str, Any]) -> str:
    pdf = Path(str(chapter.get("pdf") or chapter.get("source_pdf") or chapter.get("pattern_id") or ""))
    return pdf.stem.replace("_final", "")


def audit_chapter(chapter: Mapping[str, Any]) -> dict[str, Any]:
    pattern_id = str(chapter.get("pattern_id") or "")
    family = str(chapter.get("family") or "")
    pdf = Path(str(chapter.get("pdf") or ""))
    payload = Path(str(chapter.get("payload") or ""))
    source_pdf = Path(str(chapter.get("source_pdf") or chapter.get("pdf") or ""))
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    def fail(check: str, detail: str) -> None:
        failures.append({"check": check, "detail": detail})

    def warn(check: str, detail: str) -> None:
        warnings.append({"check": check, "detail": detail})

    if not pdf.exists():
        fail("pdf_missing", str(pdf))
        return {"pattern_id": pattern_id, "family": family, "status": "FAIL", "failures": failures, "warnings": warnings}

    text = _pdf_text(pdf)
    pages = _pdf_pages(pdf)
    for check, pattern in GLOBAL_FORBIDDEN_PATTERNS.items():
        if pattern.search(text):
            fail(check, pattern.search(text).group(0))

    if family != "flag_family":
        for check, pattern in NON_FLAG_FORBIDDEN_PATTERNS.items():
            if pattern.search(text):
                fail(check, pattern.search(text).group(0))

    sparse = [
        {"page": index + 1, "chars": len(page.strip())}
        for index, page in enumerate(pages)
        if len(page.strip()) < 250
    ]
    if sparse:
        warn("sparse_pages", json.dumps(sparse, ensure_ascii=False))

    if "Ví dụ minh họa" not in text:
        fail("missing_example_section", "Ví dụ minh họa")

    try:
        charts = _load_charts(source_pdf, payload, _slug(chapter))
    except Exception as exc:  # noqa: BLE001
        fail("expected_chart_load_failed", str(exc))
        charts = {}

    page_image_counts = _page_image_counts(pdf)
    image_count = _pdf_image_count(pdf)
    if image_count is None:
        warn("pdfimages_unavailable", "cannot count embedded images")
    elif charts:
        expected_unique = _unique_expected_chart_count(charts)
        if image_count < expected_unique:
            fail("missing_embedded_chart_images", f"embedded={image_count}; expected_at_least={expected_unique}")

    example_pages = [index for index, page in enumerate(pages) if "Ví dụ minh họa" in page]
    if not example_pages:
        fail("missing_example_section_page", "Ví dụ minh họa")
    elif not any(
        any(0 <= candidate < len(page_image_counts) and page_image_counts[candidate] > 0 for candidate in (index, index + 1))
        for index in example_pages
    ):
        fail("example_section_without_chart_nearby", f"pages={[index + 1 for index in example_pages]}")

    if charts and "schematic" not in charts:
        fail("missing_schematic_chart", "schematic")
    example_keys = {"textbook_success", "middle_case", "failure"} & set(charts)
    if not example_keys:
        fail("missing_example_charts", "No rendered example chart was found.")

    return {
        "pattern_id": pattern_id,
        "family": family,
        "status": "PASS" if not failures else "FAIL",
        "failure_count": len(failures),
        "warning_count": len(warnings),
        "failures": failures,
        "warnings": warnings,
        "pdf": str(pdf),
        "payload": str(payload),
        "embedded_image_count": image_count,
        "page_image_counts": page_image_counts,
        "expected_chart_count": len(charts),
        "expected_unique_chart_count": _unique_expected_chart_count(charts) if charts else 0,
    }


def audit_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    chapters = manifest.get("chapters") if isinstance(manifest.get("chapters"), list) else []
    rows = [audit_chapter(chapter) for chapter in chapters if isinstance(chapter, Mapping)]
    failures = [row for row in rows if row["status"] != "PASS"]
    return {
        "audit_id": AUDIT_ID,
        "status": "PASS" if not failures and rows else "FAIL",
        "manifest": str(manifest_path),
        "counts": {
            "chapters": len(rows),
            "pass": len(rows) - len(failures),
            "fail": len(failures),
            "warnings": sum(int(row.get("warning_count") or 0) for row in rows),
        },
        "chapters": rows,
    }


def write_report(report: Mapping[str, Any], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "final_chapter_pdf_quality_audit.json"
    md_path = out_dir / "final_chapter_pdf_quality_audit.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    lines = [
        "# Final Chapter PDF Quality Audit",
        "",
        f"Audit ID: `{report.get('audit_id')}`",
        f"Status: `{report.get('status')}`",
        "",
        "| Family | Pattern | Status | Failures | Warnings |",
        "|---|---|---|---|---|",
    ]
    for row in report.get("chapters", []):
        failures = "; ".join(f"{item.get('check')}={item.get('detail')}" for item in row.get("failures", []))
        warnings = "; ".join(f"{item.get('check')}={item.get('detail')}" for item in row.get("warnings", []))
        lines.append(f"| {row.get('family')} | {row.get('pattern_id')} | {row.get('status')} | {failures} | {warnings} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit final PDFs for reader-facing quality defects.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    report = audit_manifest(Path(args.manifest))
    paths = write_report(report, Path(args.out_dir))
    print(json.dumps({"report": report, "paths": paths}, ensure_ascii=False, indent=2))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
