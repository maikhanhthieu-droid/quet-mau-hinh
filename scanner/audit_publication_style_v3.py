"""Audit a rendered public chapter against the canonical style-v3 reader gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.canonical_publication_chapter_factory import (  # noqa: E402
    CANONICAL_PUBLICATION_FACTORY_ID,
    CANONICAL_PUBLICATION_STYLE_VERSION,
    CANONICAL_READER_EXPERIENCE_GATE_ID,
    REQUIRED_READER_SECTIONS,
)
from scanner.canonical_editorial_layer import FORBIDDEN_PUBLIC_TERMS  # noqa: E402
from scanner.pattern_publication_core import PUBLICATION_CORE_ID  # noqa: E402


STYLE_V3_AUDIT_ID = "canonical_publication_style_v3_pdf_audit"
MIN_PAGES = 5
MIN_TOTAL_CHARS = 9000
MIN_PAGE_CHARS = 350
REQUIRED_V3_PHRASES = (
    "Cách dùng sau khi đọc phụ lục",
    "Điểm đóng chương",
)
EXTRA_FORBIDDEN_PDF_TERMS = (
    "Contract nhân rộng family",
    "Release gate trước khi chốt",
    "Scope headline",
    "interaction:bull:high",
    "branch_id",
    "data_limited",
    "low-liquidity",
    "P75 2 phiên",
    "approved_human_sections",
    "source_full_pipe",
    "Tham số hiện tại",
    "Dữ liệu ngày được gom",
    "mẫu quét lịch sử",
    "tổng mẫu quét",
    "Pipe Bottoms cần",
    "Pipe Tops cần",
    "double pattern rộng",
    "OHLCV",
    "scanner",
    "pipeline",
    "spike 1",
    "spike 2",
    "weekly spike",
)


def _read_json(path: Path | None) -> Mapping[str, Any]:
    if not path or not path.exists() or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, Mapping) else {}


def _pdf_pages(path: Path) -> list[str]:
    reader = PdfReader(str(path))
    return [page.extract_text() or "" for page in reader.pages]


def _contains(text: str, term: str) -> bool:
    return term.lower() in text.lower()


def audit_publication_style_v3(pdf_path: Path, payload_path: Path | None = None) -> dict[str, Any]:
    """Return a machine-checkable style-v3 audit for one rendered PDF."""

    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    def fail(check: str, detail: str) -> None:
        failures.append({"check": check, "detail": detail})

    def warn(check: str, detail: str) -> None:
        warnings.append({"check": check, "detail": detail})

    if not pdf_path.exists() or not pdf_path.is_file():
        fail("pdf_exists", str(pdf_path))
        return {
            "audit_id": STYLE_V3_AUDIT_ID,
            "status": "FAIL",
            "pdf": str(pdf_path),
            "payload": str(payload_path) if payload_path else "",
            "failures": failures,
            "warnings": warnings,
        }

    pages = _pdf_pages(pdf_path)
    full_text = "\n".join(pages)
    payload = _read_json(payload_path)

    if len(pages) < MIN_PAGES:
        fail("pdf_too_few_pages", f"expected at least {MIN_PAGES}, got {len(pages)}")
    if len(full_text) < MIN_TOTAL_CHARS:
        fail("pdf_too_short", f"expected at least {MIN_TOTAL_CHARS} chars, got {len(full_text)}")

    short_pages = [
        {"page": index + 1, "chars": len(text.strip())}
        for index, text in enumerate(pages)
        if len(text.strip()) < MIN_PAGE_CHARS
    ]
    if short_pages:
        fail("pdf_sparse_pages", json.dumps(short_pages, ensure_ascii=False))

    missing_sections = [section for section in REQUIRED_READER_SECTIONS if section not in full_text]
    if missing_sections:
        fail("pdf_missing_reader_sections", ", ".join(missing_sections))

    missing_v3 = [phrase for phrase in REQUIRED_V3_PHRASES if phrase not in full_text]
    if missing_v3:
        fail("pdf_missing_style_v3_closing_phrases", ", ".join(missing_v3))

    forbidden = tuple(dict.fromkeys(tuple(FORBIDDEN_PUBLIC_TERMS) + EXTRA_FORBIDDEN_PDF_TERMS))
    leaked = [term for term in forbidden if _contains(full_text, term)]
    if leaked:
        fail("pdf_forbidden_public_terms", ", ".join(sorted(leaked, key=str.lower)))

    if full_text.count("P75 20 phiên") > 1:
        warn("pdf_repeated_p75_20_phrase", f"count={full_text.count('P75 20 phiên')}")

    if not payload:
        fail("payload_missing_or_unreadable", str(payload_path or ""))
    else:
        if payload.get("factory_id") != CANONICAL_PUBLICATION_FACTORY_ID:
            fail("payload_factory_not_canonical", str(payload.get("factory_id")))
        if payload.get("publication_core_id") != PUBLICATION_CORE_ID:
            fail("payload_publication_core_not_current", str(payload.get("publication_core_id")))
        if payload.get("canonical_reader_experience_gate_id") != CANONICAL_READER_EXPERIENCE_GATE_ID:
            fail("payload_missing_reader_experience_gate", str(payload.get("canonical_reader_experience_gate_id")))
        if payload.get("canonical_publication_style_version") != CANONICAL_PUBLICATION_STYLE_VERSION:
            fail("payload_missing_style_v3", str(payload.get("canonical_publication_style_version")))

    return {
        "audit_id": STYLE_V3_AUDIT_ID,
        "status": "PASS" if not failures else "FAIL",
        "canonical_publication_style_version": CANONICAL_PUBLICATION_STYLE_VERSION,
        "pdf": str(pdf_path),
        "payload": str(payload_path) if payload_path else "",
        "pages": len(pages),
        "chars": len(full_text),
        "failures": failures,
        "warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit one public chapter PDF against canonical style v3.")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--payload")
    parser.add_argument("--out")
    args = parser.parse_args()

    report = audit_publication_style_v3(Path(args.pdf), Path(args.payload) if args.payload else None)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
