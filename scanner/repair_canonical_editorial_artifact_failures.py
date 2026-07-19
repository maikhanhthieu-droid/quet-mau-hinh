"""Repair thin approved editorial artifacts through the canonical AI path.

This is deliberately narrow. It does not fabricate deterministic prose and it
does not render PDFs. It loads the approved AI/refinement artifact referenced by
the final payload, asks DeepSeek to rewrite only sections that fail the canonical
editorial gate, merges the result back into the same artifact, and records a
repair report next to that artifact.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from scanner.audit_canonical_editorial_artifacts import audit_manifest
from scanner.canonical_chapter_content import prepare_canonical_chapter_content
from scanner.canonical_deepseek_editorial_adapter import (
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
    _call_deepseek_json,
    load_dotenv,
)
from scanner.canonical_editorial_layer import REQUIRED_EDITORIAL_SECTIONS
from scanner.validate_final_chapters_manifest import DEFAULT_MANIFEST


REPAIR_ID = "canonical_editorial_artifact_ai_section_repair_v1"
MAX_SCHEMA_ATTEMPTS = 3


def _read_json(path: Path) -> Mapping[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, Mapping) else {}


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _failed_sections_from_exception(message: str) -> list[str]:
    return [section for section in REQUIRED_EDITORIAL_SECTIONS if f"'section': '{section}'" in message]


def _coerce_repaired_sections(parsed: Any, failed_sections: list[str]) -> dict[str, list[str]]:
    """Accept only a narrow public-editorial repair schema.

    The model occasionally returns a syntactically valid but unrelated JSON
    object. Treat that as a hard schema failure; never reinterpret unrelated
    keys as chapter prose.
    """

    if not isinstance(parsed, Mapping):
        raise RuntimeError("AI section repair returned a non-object JSON value")
    candidate = parsed.get("editorial_sections")
    if candidate is None:
        candidate = parsed.get("sections")
    if not isinstance(candidate, Mapping):
        direct = {section: parsed.get(section) for section in failed_sections if section in parsed}
        candidate = direct if direct else None
    if not isinstance(candidate, Mapping):
        raise RuntimeError("AI section repair returned no editorial_sections object")

    unexpected = sorted(str(key) for key in candidate if str(key) not in set(failed_sections))
    if unexpected:
        raise RuntimeError("AI section repair returned unexpected sections: " + ", ".join(unexpected))

    repaired: dict[str, list[str]] = {}
    for section in failed_sections:
        value = candidate.get(section)
        if isinstance(value, list):
            clean_value = [str(item).strip() for item in value if str(item).strip()]
        elif value is not None:
            clean_value = [str(value).strip()]
        else:
            clean_value = []
        if not clean_value:
            raise RuntimeError(f"AI section repair returned empty section {section}")
        repaired[section] = clean_value
    return repaired


def _resolve_project_path(value: Any, *, root: Path) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else root / path


def repair_one(
    *,
    pattern_id: str,
    manifest_path: Path,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout_s: int,
) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    manifest = _read_json(manifest_path)
    entry = next(
        (
            row
            for row in manifest.get("chapters", [])
            if isinstance(row, Mapping) and row.get("pattern_id") == pattern_id
        ),
        None,
    )
    if not isinstance(entry, Mapping):
        raise ValueError(f"Pattern not found in manifest: {pattern_id}")

    payload_path = _resolve_project_path(entry.get("payload"), root=root)
    payload = dict(_read_json(payload_path))
    approved_path = _resolve_project_path(payload.get("editorial_source_path"), root=root)
    approved = dict(_read_json(approved_path))

    try:
        prepare_canonical_chapter_content(payload, approved_sections_path=approved_path)
        return {"status": "SKIP", "pattern_id": pattern_id, "reason": "already_passes", "approved_path": str(approved_path)}
    except Exception as exc:  # noqa: BLE001 - this utility repairs gate failures
        failure_message = str(exc)

    failed_sections = _failed_sections_from_exception(failure_message)
    if not failed_sections:
        raise RuntimeError(f"Cannot infer failed sections for {pattern_id}: {failure_message}")

    sections = approved.get("editorial_sections")
    if not isinstance(sections, Mapping):
        raise ValueError(f"{approved_path} has no editorial_sections object")
    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("Missing DEEPSEEK_API_KEY")

    prompt = {
        "task": "Rewrite only failing public editorial sections for a Vietnamese chart-pattern chapter.",
        "repair_id": REPAIR_ID,
        "pattern_id": pattern_id,
        "schema_contract": {
            "only_valid_shape": {"editorial_sections": {section: ["paragraph 1", "paragraph 2", "paragraph 3"] for section in failed_sections}},
            "forbidden_shapes": [
                "Any object that does not contain editorial_sections.",
                "Any unrelated domain such as songs, products, users, examples unrelated to this chapter.",
                "Any extra section id outside failed_sections.",
            ],
        },
        "failed_sections": failed_sections,
        "gate_failure": failure_message,
        "hard_rules": [
            "Output valid JSON only.",
            "Return only key `editorial_sections` with exactly the failed section ids.",
            "Do not invent numbers, dates, tickers, examples, or outcomes.",
            "Use only locked payload facts and current approved artifact.",
            "Make each repaired section reader-facing: chart behavior -> statistic if needed -> implication -> caution.",
            "Do not write buy/sell/short advice.",
            "Do not use internal terms: scanner, pipeline, proxy, setup, target-hit, target-first, validation, holdout, backtest, profit factor.",
        ],
        "locked_payload_facts": {
            "pattern_id": payload.get("pattern_id"),
            "pattern_name": payload.get("pattern_name"),
            "chapter_reference": payload.get("chapter_reference"),
            "target_calibration": payload.get("target_calibration"),
            "classification": payload.get("classification"),
            "publication_spec": payload.get("publication_spec"),
        },
        "current_failed_sections": {section: sections.get(section) for section in failed_sections},
        "other_sections_for_style_only": {
            section: sections.get(section)
            for section in REQUIRED_EDITORIAL_SECTIONS
            if section not in failed_sections
        },
    }
    out_dir = approved_path.parent
    prompt_path = out_dir / "canonical_section_repair_prompt.json"
    _write_json(prompt_path, prompt)
    raw_path = out_dir / "canonical_section_repair_raw.json"
    parsed_path = out_dir / "canonical_section_repair_parsed.json"
    errors: list[str] = []
    result: dict[str, Any] | None = None
    repaired_sections: dict[str, list[str]] | None = None
    for attempt in range(1, MAX_SCHEMA_ATTEMPTS + 1):
        attempt_prompt = dict(prompt)
        attempt_prompt["attempt"] = attempt
        if errors:
            attempt_prompt["previous_schema_errors"] = errors
            attempt_prompt["repair_instruction"] = (
                "The previous response was rejected by the schema gate. "
                "Return exactly the `schema_contract.only_valid_shape` form and nothing else."
            )
        result = _call_deepseek_json(
            api_key=api_key,
            base_url=DEFAULT_DEEPSEEK_BASE_URL,
            model=model,
            prompt=json.dumps(attempt_prompt, ensure_ascii=False, indent=2, default=str),
            temperature=min(float(temperature), 0.2),
            max_tokens=max_tokens,
            timeout_s=timeout_s,
        )
        (out_dir / f"canonical_section_repair_attempt_{attempt}_raw.json").write_text(
            str(result.get("raw") or ""),
            encoding="utf-8",
        )
        (out_dir / f"canonical_section_repair_attempt_{attempt}_parsed.json").write_text(
            json.dumps(result.get("parsed"), ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        try:
            repaired_sections = _coerce_repaired_sections(result.get("parsed"), failed_sections)
            break
        except RuntimeError as exc:
            errors.append(str(exc))
    if result is None or repaired_sections is None:
        raise RuntimeError(f"AI section repair returned invalid schema for {pattern_id}: {errors}")
    raw_path.write_text(str(result.get("raw") or ""), encoding="utf-8")
    parsed = {"editorial_sections": repaired_sections}
    merged_sections = dict(sections)
    for section in failed_sections:
        merged_sections[section] = repaired_sections[section]

    repaired_artifact = dict(approved)
    repaired_artifact["editorial_sections"] = merged_sections
    repairs = list(repaired_artifact.get("canonical_section_repairs") or [])
    repairs.append(
        {
            "repair_id": REPAIR_ID,
            "created_at": _utc_now(),
            "model": model,
            "temperature": temperature,
            "failed_sections": failed_sections,
            "prompt_path": str(prompt_path),
            "raw_path": str(raw_path),
            "parsed_path": str(parsed_path),
            "schema_attempts": len(errors) + 1,
            "schema_errors": errors,
            "usage": result.get("usage"),
        }
    )
    repaired_artifact["canonical_section_repairs"] = repairs
    _write_json(parsed_path, parsed)
    _write_json(approved_path, repaired_artifact)

    prepared = prepare_canonical_chapter_content(payload, approved_sections_path=approved_path)
    report = prepared.get("canonical_content_generation_report", {}).get("editorial_gate_report", {})
    if report.get("status") != "PASS":
        raise RuntimeError(f"Repair did not pass canonical editorial gate for {pattern_id}: {report}")
    return {
        "status": "PASS",
        "pattern_id": pattern_id,
        "approved_path": str(approved_path),
        "failed_sections": failed_sections,
        "gate_report": report,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair failing canonical editorial artifacts with AI.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--pattern", action="append", default=[])
    parser.add_argument("--model", default=DEFAULT_DEEPSEEK_MODEL)
    parser.add_argument("--temperature", type=float, default=0.25)
    parser.add_argument("--max-tokens", type=int, default=8000)
    parser.add_argument("--timeout-s", type=int, default=600)
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    patterns = list(args.pattern)
    if not patterns:
        report = audit_manifest(manifest_path)
        patterns = [row["pattern_id"] for row in report.get("failures", [])]
    if not patterns:
        print(json.dumps({"status": "PASS", "repairs": [], "reason": "no_failures"}, ensure_ascii=False, indent=2))
        return
    repairs = [
        repair_one(
            pattern_id=pattern,
            manifest_path=manifest_path,
            model=str(args.model),
            temperature=float(args.temperature),
            max_tokens=int(args.max_tokens),
            timeout_s=int(args.timeout_s),
        )
        for pattern in patterns
    ]
    print(json.dumps({"status": "PASS", "repairs": repairs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
