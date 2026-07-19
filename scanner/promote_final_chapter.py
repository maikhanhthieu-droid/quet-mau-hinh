"""Promote a chapter to the final manifest only after all publication gates pass."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.audit_publication_style_v3 import audit_publication_style_v3  # noqa: E402
from scanner.publication_flow_contract import validate_publication_contract  # noqa: E402
from scanner.publication_semantic_contract import semantic_required, validate_publication_semantic_contract  # noqa: E402
from scanner.validate_final_chapters_manifest import DEFAULT_MANIFEST, validate_final_manifest  # noqa: E402


def _read_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


@contextmanager
def _manifest_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f"{path.name}.lock")
    with lock_path.open("w", encoding="utf-8") as lock_file:
        try:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        except ImportError:
            fcntl = None  # type: ignore[assignment]
        try:
            yield
        finally:
            if "fcntl" in locals() and fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _validate_entry(entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    contract = validate_publication_contract(entry)
    if contract["status"] != "PASS":
        failures.extend(contract["failures"])
    if semantic_required(entry):
        semantic = validate_publication_semantic_contract(entry)
        if semantic["status"] != "PASS":
            failures.extend(semantic["failures"])
    pdf_path = Path(str(entry.get("pdf") or ""))
    payload_path = Path(str(entry.get("payload") or ""))
    style = audit_publication_style_v3(pdf_path, payload_path)
    if style["status"] != "PASS":
        failures.extend(style["failures"])
    return failures


def promote_final_chapter(*, entry_path: Path, manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    entry = dict(_read_json(entry_path))
    if str(entry.get("status") or "") != "final":
        entry["status"] = "final"

    with _manifest_lock(manifest_path):
        source_pdf = Path(str(entry.get("source_pdf") or entry.get("pdf") or ""))
        final_pdf = Path(str(entry.get("pdf") or ""))
        copied_pdf = False
        previous_pdf = final_pdf.read_bytes() if final_pdf.exists() and final_pdf.is_file() else None
        if source_pdf and final_pdf and source_pdf != final_pdf:
            if not source_pdf.exists():
                return {"status": "FAIL", "failures": [{"check": "source_pdf_exists", "detail": str(source_pdf)}]}
            final_pdf.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_pdf, final_pdf)
            copied_pdf = True

        failures = _validate_entry(entry)
        if failures:
            if copied_pdf and previous_pdf is None and final_pdf.exists():
                final_pdf.unlink()
            elif copied_pdf and previous_pdf is not None:
                final_pdf.write_bytes(previous_pdf)
            return {"status": "FAIL", "failures": failures, "entry": str(entry_path)}

        manifest = dict(_read_json(manifest_path))
        chapters = manifest.get("chapters") if isinstance(manifest.get("chapters"), list) else []
        chapters = [
            chapter
            for chapter in chapters
            if not (isinstance(chapter, Mapping) and chapter.get("pattern_id") == entry.get("pattern_id"))
        ]
        chapters.append(entry)
        manifest["chapters"] = chapters

        previous = manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else ""
        _write_json(manifest_path, manifest)
        report = validate_final_manifest(manifest_path)
        if report["status"] != "PASS":
            if previous:
                manifest_path.write_text(previous, encoding="utf-8")
            if copied_pdf and previous_pdf is None and final_pdf.exists():
                final_pdf.unlink()
            elif copied_pdf and previous_pdf is not None:
                final_pdf.write_bytes(previous_pdf)
            return {"status": "FAIL", "failures": report["failures"], "entry": str(entry_path), "rolled_back": True}
        return {"status": "PASS", "entry": str(entry_path), "manifest": str(manifest_path), "pattern_id": entry.get("pattern_id")}


def promote_final_chapters(*, entry_paths: list[Path], manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    """Promote multiple final chapters in one manifest transaction."""

    entries = []
    for entry_path in entry_paths:
        entry = dict(_read_json(entry_path))
        if str(entry.get("status") or "") != "final":
            entry["status"] = "final"
        entries.append((entry_path, entry))

    with _manifest_lock(manifest_path):
        copied: list[tuple[Path, bytes | None]] = []
        for entry_path, entry in entries:
            source_pdf = Path(str(entry.get("source_pdf") or entry.get("pdf") or ""))
            final_pdf = Path(str(entry.get("pdf") or ""))
            if source_pdf and final_pdf and source_pdf != final_pdf:
                if not source_pdf.exists():
                    return {"status": "FAIL", "failures": [{"check": "source_pdf_exists", "detail": str(source_pdf)}], "entry": str(entry_path)}
                previous_pdf = final_pdf.read_bytes() if final_pdf.exists() and final_pdf.is_file() else None
                final_pdf.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_pdf, final_pdf)
                copied.append((final_pdf, previous_pdf))

        failures: list[dict[str, Any]] = []
        for entry_path, entry in entries:
            entry_failures = _validate_entry(entry)
            for failure in entry_failures:
                failure.setdefault("entry", str(entry_path))
            failures.extend(entry_failures)
        if failures:
            for final_pdf, previous_pdf in copied:
                if previous_pdf is None and final_pdf.exists():
                    final_pdf.unlink()
                elif previous_pdf is not None:
                    final_pdf.write_bytes(previous_pdf)
            return {"status": "FAIL", "failures": failures, "entries": [str(path) for path, _ in entries]}

        manifest = dict(_read_json(manifest_path))
        chapters = manifest.get("chapters") if isinstance(manifest.get("chapters"), list) else []
        pattern_ids = {entry.get("pattern_id") for _, entry in entries}
        chapters = [
            chapter
            for chapter in chapters
            if not (isinstance(chapter, Mapping) and chapter.get("pattern_id") in pattern_ids)
        ]
        chapters.extend(entry for _, entry in entries)
        manifest["chapters"] = chapters

        previous_manifest = manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else ""
        _write_json(manifest_path, manifest)
        report = validate_final_manifest(manifest_path)
        if report["status"] != "PASS":
            if previous_manifest:
                manifest_path.write_text(previous_manifest, encoding="utf-8")
            for final_pdf, previous_pdf in copied:
                if previous_pdf is None and final_pdf.exists():
                    final_pdf.unlink()
                elif previous_pdf is not None:
                    final_pdf.write_bytes(previous_pdf)
            return {
                "status": "FAIL",
                "failures": report["failures"],
                "entries": [str(path) for path, _ in entries],
                "rolled_back": True,
            }
        return {
            "status": "PASS",
            "entries": [str(path) for path, _ in entries],
            "manifest": str(manifest_path),
            "pattern_ids": [entry.get("pattern_id") for _, entry in entries],
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote a chapter to final after publication gates pass.")
    parser.add_argument("--entry", required=True, nargs="+", help="Path(s) to JSON final-manifest chapter entries.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    args = parser.parse_args()
    entry_paths = [Path(item) for item in args.entry]
    if len(entry_paths) == 1:
        report = promote_final_chapter(entry_path=entry_paths[0], manifest_path=Path(args.manifest))
    else:
        report = promote_final_chapters(entry_paths=entry_paths, manifest_path=Path(args.manifest))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
