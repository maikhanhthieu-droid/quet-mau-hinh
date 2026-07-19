"""Audit final chapters for duplicated recognition-critical content.

The publication factory may share typography, section order, and statistical
tables across chapters. It must not share the actual recognition rules inside a
family unless the chapters are intentionally the same pattern. This audit fails
exact duplicates in the source/spec fields that feed the public "Cách nhận
diện" section.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping


DEFAULT_MANIFEST = Path("artifacts/final_chapters/final_chapters_manifest.json")
AUDIT_ID = "final_exact_recognition_payload_duplicate_audit_v1"

PAYLOAD_FIELDS = (
    "source_rules_public",
    "quick_reject_rules",
)
SPEC_FIELDS = (
    "public_rule_rows",
    "component_rows",
    "quick_question_rows",
    "quick_reject_rules",
)


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def _is_meaningful(value: Any) -> bool:
    if value is None:
        return False
    if value == "":
        return False
    if isinstance(value, (list, tuple, dict)) and len(value) == 0:
        return False
    return True


def _fingerprint(value: Any) -> tuple[str, str]:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest(), encoded


def _chapter_field_values(chapter: Mapping[str, Any]) -> Iterable[tuple[str, str, Any]]:
    payload_raw = str(chapter.get("payload") or "")
    payload_path = Path(payload_raw) if payload_raw else None
    payload = _read_json(payload_path) if payload_path else {}
    for field in PAYLOAD_FIELDS:
        value = payload.get(field)
        if _is_meaningful(value):
            yield "payload", field, value

    spec_raw = str(chapter.get("publication_spec") or chapter.get("spec") or "")
    spec_path = Path(spec_raw) if spec_raw else None
    spec = _read_json(spec_path) if spec_path else {}
    for field in SPEC_FIELDS:
        value = spec.get(field)
        if _is_meaningful(value):
            yield "spec", field, value


def audit_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest = _read_json(path)
    chapters = manifest.get("chapters") if isinstance(manifest.get("chapters"), list) else []
    buckets: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    missing_specs: list[dict[str, Any]] = []

    for chapter in chapters:
        if not isinstance(chapter, Mapping):
            continue
        family = str(chapter.get("family") or "")
        pattern_id = str(chapter.get("pattern_id") or "")
        spec_raw = str(chapter.get("publication_spec") or chapter.get("spec") or "")
        spec_path = Path(spec_raw) if spec_raw else None
        if spec_path and not spec_path.exists():
            missing_specs.append({"pattern_id": pattern_id, "family": family, "path": str(spec_path)})
        for source, field, value in _chapter_field_values(chapter):
            digest, encoded = _fingerprint(value)
            buckets[(family, source, field, digest)].append(
                {
                    "pattern_id": pattern_id,
                    "path": str(chapter.get("payload") if source == "payload" else spec_path),
                    "preview": encoded[:360],
                }
            )

    findings: list[dict[str, Any]] = []
    for (family, source, field, digest), rows in sorted(buckets.items()):
        patterns = sorted({row["pattern_id"] for row in rows})
        if len(patterns) <= 1:
            continue
        findings.append(
            {
                "check": "exact_duplicate_recognition_content",
                "family": family,
                "source": source,
                "field": field,
                "digest": digest,
                "pattern_ids": patterns,
                "paths": sorted({row["path"] for row in rows}),
                "preview": rows[0]["preview"],
            }
        )

    failures = findings + [
        {
            "check": "publication_spec_missing",
            "family": item["family"],
            "pattern_id": item["pattern_id"],
            "detail": item["path"],
        }
        for item in missing_specs
    ]
    return {
        "audit_id": AUDIT_ID,
        "status": "PASS" if not failures else "FAIL",
        "manifest": str(path),
        "counts": {
            "chapters": len(chapters),
            "duplicate_findings": len(findings),
            "missing_specs": len(missing_specs),
            "failures": len(failures),
        },
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit final chapter recognition fields for exact duplicates.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    report = audit_manifest(Path(args.manifest))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text)
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
