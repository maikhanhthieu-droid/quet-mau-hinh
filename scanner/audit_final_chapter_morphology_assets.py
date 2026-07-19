"""Audit morphology diagrams and chart assets in final public chapters.

The regular PDF quality audit counts embedded images, but it cannot tell
whether the first instructional diagram is a real morphology schematic or a
fallback example chart. This gate checks the chapter-level chart assets and the
rendered PDF text anchors so a chapter cannot silently ship without a clear
shape diagram.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from PIL import Image
from pypdf import PdfReader

from scanner.rebuild_source_guided_final_chapters import _load_charts, _slug_from_entry


DEFAULT_MANIFEST = Path("artifacts/final_chapters/final_chapters_manifest.json")
DEFAULT_OUT_DIR = Path("artifacts/final_chapters/governance")
AUDIT_ID = "final_chapter_morphology_asset_audit_v1"
MIN_SCHEMATIC_WIDTH = 1000
MIN_SCHEMATIC_HEIGHT = 440
EXAMPLE_KEYS = ("textbook_success", "middle_case", "failure")


def _read_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return payload if isinstance(payload, Mapping) else {}


def _pdf_texts(pdf: Path) -> list[str]:
    reader = PdfReader(str(pdf))
    return [page.extract_text() or "" for page in reader.pages]


def _source_for_entry(entry: Mapping[str, Any], payload_path: Path) -> Path:
    source = Path(str(entry.get("source_pdf") or ""))
    if source.exists() and source.suffix.lower() == ".pdf":
        return source
    return payload_path


def _image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.width, image.height


def audit_manifest(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for entry in manifest.get("chapters", []):
        if not isinstance(entry, Mapping):
            continue
        pattern_id = str(entry.get("pattern_id") or "")
        family = str(entry.get("family") or "")
        pdf = Path(str(entry.get("pdf") or ""))
        payload = Path(str(entry.get("payload") or ""))
        row: dict[str, Any] = {
            "family": family,
            "pattern_id": pattern_id,
            "pdf": str(pdf),
            "payload": str(payload),
            "status": "PASS",
            "failures": [],
            "warnings": [],
        }

        try:
            charts = _load_charts(_source_for_entry(entry, payload), payload, _slug_from_entry(entry))
        except Exception as exc:  # pragma: no cover - defensive release audit
            row["status"] = "FAIL"
            row["failures"].append(f"cannot_load_charts: {exc}")
            rows.append(row)
            failures.append(row)
            continue

        schematic = charts.get("schematic")
        row["chart_keys"] = sorted(charts.keys())
        row["schematic"] = str(schematic) if schematic else None
        if schematic is None or not schematic.exists():
            row["status"] = "FAIL"
            row["failures"].append("missing_schematic_asset")
        elif "schematic" not in schematic.name.lower():
            row["status"] = "FAIL"
            row["failures"].append("schematic_is_fallback_not_named_schematic")
        else:
            width, height = _image_size(schematic)
            row["schematic_width"] = width
            row["schematic_height"] = height
            if width < MIN_SCHEMATIC_WIDTH or height < MIN_SCHEMATIC_HEIGHT:
                row["status"] = "FAIL"
                row["failures"].append(f"schematic_too_small:{width}x{height}")

        missing_examples = [key for key in EXAMPLE_KEYS if key not in charts]
        row["missing_example_chart_keys"] = missing_examples
        if missing_examples:
            row["warnings"].append("missing_example_chart_keys:" + ",".join(missing_examples))

        if not pdf.exists():
            row["status"] = "FAIL"
            row["failures"].append("missing_pdf")
        else:
            texts = _pdf_texts(pdf)
            morphology_pages = [
                idx + 1
                for idx, text in enumerate(texts)
                if "Sơ đồ" in text or "Mẫu hình hoạt động ra sao" in text
            ]
            row["morphology_pages"] = morphology_pages
            row["has_schematic_caption"] = any("Sơ đồ" in text for text in texts)
            if not row["has_schematic_caption"]:
                row["status"] = "FAIL"
                row["failures"].append("missing_schematic_caption_in_pdf")
            if not morphology_pages:
                row["status"] = "FAIL"
                row["failures"].append("missing_morphology_page_anchor")

        rows.append(row)
        if row["failures"]:
            failures.append(row)
        if row["warnings"]:
            warnings.append(row)

    return {
        "audit_id": AUDIT_ID,
        "status": "PASS" if not failures else "FAIL",
        "counts": {
            "chapters": len(rows),
            "pass": sum(1 for row in rows if row["status"] == "PASS"),
            "fail": len(failures),
            "warnings": len(warnings),
            "missing_example_chart_keys": sum(len(row.get("missing_example_chart_keys") or []) for row in rows),
        },
        "rows": rows,
        "failures": failures,
        "warnings": warnings,
    }


def write_report(report: Mapping[str, Any], out_dir: Path = DEFAULT_OUT_DIR) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "final_chapter_morphology_asset_audit.json"
    md_path = out_dir / "final_chapter_morphology_asset_audit.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    lines = [
        "# Final Chapter Morphology Asset Audit",
        "",
        f"Audit ID: `{report.get('audit_id')}`",
        f"Status: `{report.get('status')}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for key, value in (report.get("counts") or {}).items():
        lines.append(f"| {key} | {value} |")
    lines.extend(
        [
            "",
            "## Chapters",
            "",
            "| Family | Pattern | Status | Schematic | Missing example charts |",
            "|---|---|---|---|---|",
        ]
    )
    for row in report.get("rows", []):
        lines.append(
            "| {family} | {pattern} | {status} | {schematic} | {missing} |".format(
                family=row.get("family"),
                pattern=row.get("pattern_id"),
                status=row.get("status"),
                schematic=Path(str(row.get("schematic") or "")).name,
                missing=", ".join(row.get("missing_example_chart_keys") or []),
            )
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit final chapter morphology diagrams and chart assets.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    report = audit_manifest(Path(args.manifest))
    paths = write_report(report, Path(args.out_dir))
    print(json.dumps({"report": report, "paths": paths}, ensure_ascii=False, indent=2, default=str))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
