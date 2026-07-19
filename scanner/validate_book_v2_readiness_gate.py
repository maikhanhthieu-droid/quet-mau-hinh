from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from jsonschema import Draft202012Validator  # type: ignore
except Exception:  # pragma: no cover
    Draft202012Validator = None  # type: ignore

try:
    from .audit_book_v2_readiness import build_readiness, render_markdown  # type: ignore
    from .build_book_v2 import build_book_v2  # type: ignore
    from .build_pattern_monographs import build_monographs  # type: ignore
except Exception:  # pragma: no cover
    from audit_book_v2_readiness import build_readiness, render_markdown  # type: ignore
    from build_book_v2 import build_book_v2  # type: ignore
    from build_pattern_monographs import build_monographs  # type: ignore


EXPECTED_BULKOWSKI_53_COUNT = 53


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _validate_payload_schema(*, schema_path: Path, payload_paths: List[Path]) -> List[str]:
    if Draft202012Validator is None:
        return ["jsonschema is not installed; run `pip install -r requirements.txt` before this gate."]
    schema = _read_json(schema_path)
    validator = Draft202012Validator(schema)
    errors: List[str] = []
    for payload_path in payload_paths:
        payload = _read_json(payload_path)
        for error in sorted(validator.iter_errors(payload), key=lambda e: list(e.path)):
            loc = ".".join(str(part) for part in error.path) or "<root>"
            errors.append(f"{payload_path}: {loc}: {error.message}")
    return errors


def _compare_readiness(*, audit_payload: Dict[str, Any], monograph_dir: Path) -> Tuple[List[str], List[str]]:
    missing: List[str] = []
    mismatches: List[str] = []
    for row in audit_payload["patterns"]:
        key = str(row["pattern_key"])
        payload_path = monograph_dir / key / "chapter_payload.json"
        if not payload_path.exists():
            missing.append(key)
            continue
        payload = _read_json(payload_path)
        governance = payload.get("governance") or {}
        expected = (row.get("book_v2_readiness"), tuple(row.get("readiness_flags") or []))
        actual = (governance.get("book_v2_readiness"), tuple(governance.get("readiness_flags") or []))
        if expected != actual:
            mismatches.append(f"{key}: expected={expected} actual={actual}")
    return missing, mismatches


def _scan_active_v1_refs(root: Path) -> List[str]:
    needles = [
        "build_book_vi",
        "validate_book_vi",
        "review_book_v1_output",
        "book-v1",
        "Book V1",
        "Book v1",
        "BOOK_V1",
        "books/book-v1",
    ]
    roots = [root / name for name in ("README.md", "docs", "scanner", "tools", "tests", "requirements.txt")]
    skip = {Path(__file__).resolve()}
    out: List[str] = []
    for start in roots:
        if not start.exists():
            continue
        paths = [start] if start.is_file() else [p for p in start.rglob("*") if p.is_file()]
        for path in paths:
            if path.resolve() in skip or "__pycache__" in path.parts:
                continue
            if path.suffix not in {".md", ".py", ".txt", ".json", ".toml"} and path.name != "requirements.txt":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if any(needle in line for needle in needles):
                    out.append(f"{path.relative_to(root)}:{lineno}: {line.strip()}")
    return out


def _render_gate_report(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    status = "PASS" if report["passed"] else "FAIL"
    lines.append(f"# Book V2 Step 3 Readiness Gate: {status}")
    lines.append("")
    lines.append(f"- pattern_count: `{report['pattern_count']}`")
    lines.append(f"- payload_count: `{report['payload_count']}`")
    lines.append(f"- chapter_core_count: `{report['chapter_core_count']}`")
    lines.append(f"- book_pattern_count: `{report['book_pattern_count']}`")
    lines.append(f"- readiness_counts: `{report['readiness_counts']}`")
    lines.append(f"- readiness_mentions_in_book: `{report['readiness_mentions_in_book']}`")
    lines.append("")
    if report["errors"]:
        lines.append("## Errors")
        lines.append("")
        for error in report["errors"]:
            lines.append(f"- {error}")
        lines.append("")
    else:
        lines.append("No gate errors found.")
        lines.append("")
    return "\n".join(lines)


def run_gate(
    *,
    valid_db: Path,
    calib_db: Path,
    phase3_matrix: Path,
    benchmark_matrix: Path,
    out_dir: Path,
    price_db: Optional[Path],
    style_guide: Path,
    market_report_md: Optional[Path],
    language: str,
) -> Dict[str, Any]:
    root = _repo_root()
    out_dir.mkdir(parents=True, exist_ok=True)
    monograph_dir = out_dir / "monographs"
    book_dir = out_dir / "book-v2"

    audit_payload = build_readiness(
        valid_db=valid_db,
        calib_db=calib_db,
        phase3_matrix=phase3_matrix,
        benchmark_matrix=benchmark_matrix,
    )
    _write_json(out_dir / "book_v2_readiness.json", audit_payload)
    _write_text(out_dir / "book_v2_readiness.md", render_markdown(audit_payload))

    monograph_index = build_monographs(
        valid_db=valid_db,
        calib_db=calib_db,
        phase3_matrix=phase3_matrix,
        benchmark_matrix=benchmark_matrix,
        out_dir=monograph_dir,
        price_db=price_db,
        patterns=None,
        language=language,
    )

    book_meta = build_book_v2(
        monograph_dir=monograph_dir,
        out_dir=book_dir,
        market_report_md=market_report_md,
        style_guide_path=style_guide,
        patterns=None,
        skip_ai=True,
        deepseek_api_key=None,
        deepseek_base_url="https://api.deepseek.com",
        deepseek_model="deepseek-v4-flash",
        timeout_s=120,
        skip_pdf=True,
        pdf_mainfont=None,
        language=language,
    )

    payload_paths = sorted(monograph_dir.glob("*/chapter_payload.json"))
    core_paths = sorted(monograph_dir.glob("*/chapter_core.md"))
    schema_errors = _validate_payload_schema(
        schema_path=root / "schemas" / "book_v2" / "pattern_monograph.schema.json",
        payload_paths=payload_paths,
    )
    missing, mismatches = _compare_readiness(audit_payload=audit_payload, monograph_dir=monograph_dir)
    legacy_refs = _scan_active_v1_refs(root)

    book_text = (book_dir / "book_v2.md").read_text(encoding="utf-8") if (book_dir / "book_v2.md").exists() else ""
    readiness_mentions = len(re.findall(r"readiness Book v2|book_v2_readiness", book_text))

    errors: List[str] = []
    if int(audit_payload["summary"].get("pattern_count") or 0) != EXPECTED_BULKOWSKI_53_COUNT:
        errors.append("Readiness audit did not cover all 53 Bulkowski patterns.")
    if int(monograph_index.get("pattern_count") or 0) != EXPECTED_BULKOWSKI_53_COUNT:
        errors.append("Monograph builder did not produce all 53 patterns in index.json.")
    if len(payload_paths) != EXPECTED_BULKOWSKI_53_COUNT:
        errors.append(f"Expected 53 chapter_payload.json files, found {len(payload_paths)}.")
    if len(core_paths) != EXPECTED_BULKOWSKI_53_COUNT:
        errors.append(f"Expected 53 chapter_core.md files, found {len(core_paths)}.")
    if int(book_meta.get("pattern_count") or 0) != EXPECTED_BULKOWSKI_53_COUNT:
        errors.append("Book v2 assembly did not include all 53 patterns.")
    if readiness_mentions < EXPECTED_BULKOWSKI_53_COUNT:
        errors.append("Book v2 output does not expose readiness in every chapter.")
    errors.extend(f"Schema: {error}" for error in schema_errors)
    errors.extend(f"Missing monograph payload: {key}" for key in missing)
    errors.extend(f"Readiness mismatch: {item}" for item in mismatches)
    errors.extend(f"Active V1 reference: {item}" for item in legacy_refs)

    report = {
        "passed": not errors,
        "pattern_count": int(audit_payload["summary"].get("pattern_count") or 0),
        "payload_count": len(payload_paths),
        "chapter_core_count": len(core_paths),
        "book_pattern_count": int(book_meta.get("pattern_count") or 0),
        "readiness_counts": audit_payload["summary"].get("readiness_counts") or {},
        "readiness_mentions_in_book": readiness_mentions,
        "errors": errors,
        "outputs": {
            "audit_json": str((out_dir / "book_v2_readiness.json").resolve()),
            "audit_md": str((out_dir / "book_v2_readiness.md").resolve()),
            "monograph_dir": str(monograph_dir.resolve()),
            "book_dir": str(book_dir.resolve()),
        },
    }
    _write_json(out_dir / "step3_gate_report.json", report)
    _write_text(out_dir / "step3_gate_report.md", _render_gate_report(report))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the reproducible Book v2 Step 3 readiness gate.")
    parser.add_argument("--valid-db", required=True)
    parser.add_argument("--calib-db", required=True)
    parser.add_argument("--phase3-pattern-matrix", required=True)
    parser.add_argument("--benchmark-pattern-matrix", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--price-db", default=None)
    parser.add_argument("--style-guide", default="docs/publication/book-v2/commentary-style-guide.md")
    parser.add_argument("--market-report-md", default=None)
    parser.add_argument("--language", default="vi", choices=["en", "vi"])
    args = parser.parse_args()

    report = run_gate(
        valid_db=Path(args.valid_db),
        calib_db=Path(args.calib_db),
        phase3_matrix=Path(args.phase3_pattern_matrix),
        benchmark_matrix=Path(args.benchmark_pattern_matrix),
        out_dir=Path(args.out_dir),
        price_db=Path(args.price_db) if args.price_db else None,
        style_guide=Path(args.style_guide),
        market_report_md=Path(args.market_report_md) if args.market_report_md else None,
        language=str(args.language),
    )
    print(f"Book V2 Step 3 readiness gate: {'PASS' if report['passed'] else 'FAIL'}")
    print(f"Report: {Path(args.out_dir, 'step3_gate_report.md').resolve()}")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
