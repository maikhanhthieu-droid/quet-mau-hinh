"""Backfill curated public recognition-rule prose for final chapters.

This script fixes a specific publication-flow problem: the PDF renderer must
not invent reader-facing recognition rules from internal rule ids. It reads the
source-grounded rule inventory for each final chapter, asks the editorial model
to convert those rules into Vietnamese public prose, and stores the result as
`source_rules_public` on the chapter payload. The canonical publication core then
renders that approved prose instead of a heuristic fallback.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.canonical_deepseek_editorial_adapter import (  # noqa: E402
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
    _call_deepseek_json,
    load_dotenv,
)
from scanner.validate_final_chapters_manifest import DEFAULT_MANIFEST  # noqa: E402


OUT_DIR = ROOT / "artifacts/final_chapters/governance/public_rule_backfill"
BACKFILL_ID = "final_chapter_public_rule_backfill_v1"


def _read_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, Mapping) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _valid_rule_rows(value: Any) -> bool:
    return isinstance(value, list) and len(value) >= 3 and all(isinstance(item, Mapping) for item in value[:3])


def _existing_approved_paths(entry: Mapping[str, Any]) -> list[Path]:
    paths: list[Path] = []
    stages = entry.get("chapter_writing_stages") if isinstance(entry.get("chapter_writing_stages"), Mapping) else {}
    for key in ("refined_ai_sections", "source_guided_ai_sections"):
        value = stages.get(key)
        if value:
            path = Path(str(value))
            if path.exists():
                paths.append(path)
    return paths


def _prompt(*, entry: Mapping[str, Any], payload: Mapping[str, Any], source_notes: Mapping[str, Any]) -> str:
    source_rules = source_notes.get("source_rules") if isinstance(source_notes.get("source_rules"), list) else []
    compact_rules = []
    for rule in source_rules[:10]:
        if not isinstance(rule, Mapping):
            continue
        compact_rules.append(
            {
                "rule_id": rule.get("rule_id"),
                "rule_type": rule.get("rule_type"),
                "source_excerpt": rule.get("short_excerpt"),
                "implementation_mapping": rule.get("implementation_mapping"),
            }
        )
    context = {
        "task": "Convert source-grounded chart-pattern recognition rules into polished Vietnamese public prose.",
        "output_schema": {
            "source_rules_public": [
                {
                    "rule_id": "source rule id",
                    "rule": "short Vietnamese recognition rule for investor readers",
                    "application": "how to apply/read it on a chart, without internal scanner language",
                    "avoid": "one common recognition mistake to avoid",
                }
            ],
            "recognition_mistakes": ["reader-facing mistakes to avoid"],
        },
        "hard_constraints": [
            "Return JSON only.",
            "Use Vietnamese only.",
            "Do not mention scanner, pipeline, payload, params, thresholds, model, AI, or internal code.",
            "Do not add numbers unless they are present in the source rules or chapter facts.",
            "Do not make trade recommendations.",
            "Keep the prose source-grounded: geometry first, confirmation second, outcome later.",
            "Write like a public reference chapter, not like an engineering note.",
        ],
        "chapter": {
            "pattern_id": entry.get("pattern_id"),
            "title": payload.get("pattern_name") or entry.get("title"),
            "family": entry.get("family"),
            "classification": payload.get("classification") or entry.get("classification"),
        },
        "source_rules": compact_rules,
        "existing_tour_prose": (payload.get("editorial_sections") or {}).get("tour")
        if isinstance(payload.get("editorial_sections"), Mapping)
        else [],
    }
    return json.dumps(context, ensure_ascii=False, indent=2, default=str)


def _normalize_rules(parsed: Mapping[str, Any]) -> list[dict[str, str]]:
    raw = parsed.get("source_rules_public")
    if not isinstance(raw, list):
        raw = parsed.get("rules")
    out: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        rule = str(item.get("rule") or item.get("public_rule") or item.get("public_description") or "").strip()
        application = str(item.get("application") or item.get("how_to_apply") or item.get("importance") or "").strip()
        avoid = str(item.get("avoid") or item.get("common_mistake") or item.get("common_mistakes") or "").strip()
        if not rule or not application:
            continue
        row = {
            "rule_id": str(item.get("rule_id") or "").strip(),
            "rule": rule,
            "application": application,
        }
        if avoid:
            row["avoid"] = avoid
        out.append(row)
    return out[:8]


def backfill_one(
    entry: Mapping[str, Any],
    *,
    model: str,
    temperature: float,
    timeout_s: int,
    max_tokens: int,
    force: bool,
) -> dict[str, Any]:
    pattern_id = str(entry.get("pattern_id") or "")
    payload_path = ROOT / str(entry.get("payload") or "")
    source_notes_path = ROOT / str(entry.get("source_notes") or "")
    if not payload_path.exists() or not source_notes_path.exists():
        return {"pattern_id": pattern_id, "status": "SKIP", "reason": "missing payload or source_notes"}
    payload = dict(_read_json(payload_path))
    if _valid_rule_rows(payload.get("source_rules_public")) and not force:
        return {"pattern_id": pattern_id, "status": "SKIP", "reason": "already has source_rules_public"}
    source_notes = _read_json(source_notes_path)
    prompt = _prompt(entry=entry, payload=payload, source_notes=source_notes)
    chapter_dir = OUT_DIR / pattern_id
    chapter_dir.mkdir(parents=True, exist_ok=True)
    (chapter_dir / "prompt.json").write_text(prompt + "\n", encoding="utf-8")
    try:
        result = _call_deepseek_json(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url=DEFAULT_DEEPSEEK_BASE_URL,
            model=model,
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
        )
    except Exception as exc:  # noqa: BLE001
        return {"pattern_id": pattern_id, "status": "FAIL", "reason": f"model_call_or_parse_error: {exc}"}
    (chapter_dir / "raw.json").write_text(str(result.get("raw") or ""), encoding="utf-8")
    parsed = result.get("parsed")
    if not isinstance(parsed, Mapping):
        return {"pattern_id": pattern_id, "status": "FAIL", "reason": "model returned non-object JSON"}
    _write_json(chapter_dir / "parsed.json", parsed)
    rows = _normalize_rules(parsed)
    if len(rows) < 3:
        return {"pattern_id": pattern_id, "status": "FAIL", "reason": f"too few public rule rows: {len(rows)}"}
    payload["source_rules_public"] = rows
    payload["recognition_mistakes"] = parsed.get("recognition_mistakes") or payload.get("recognition_mistakes") or []
    payload["source_rules_public_provenance"] = {
        "backfill_id": BACKFILL_ID,
        "model": model,
        "temperature": temperature,
        "source_notes": str(source_notes_path.relative_to(ROOT)),
        "artifact": str((chapter_dir / "parsed.json").relative_to(ROOT)),
    }
    _write_json(payload_path, payload)
    for approved_path in _existing_approved_paths(entry):
        approved = dict(_read_json(ROOT / approved_path if not approved_path.is_absolute() else approved_path))
        approved["source_rules_public"] = rows
        approved["recognition_mistakes"] = payload["recognition_mistakes"]
        approved["source_rules_public_provenance"] = payload["source_rules_public_provenance"]
        _write_json(ROOT / approved_path if not approved_path.is_absolute() else approved_path, approved)
    return {"pattern_id": pattern_id, "status": "PASS", "rules": len(rows), "payload": str(payload_path.relative_to(ROOT))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--pattern", action="append", default=[])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--model", default=DEFAULT_DEEPSEEK_MODEL)
    parser.add_argument("--temperature", type=float, default=0.15)
    parser.add_argument("--timeout-s", type=int, default=900)
    parser.add_argument("--max-tokens", type=int, default=4000)
    args = parser.parse_args()

    load_dotenv()
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("Missing DEEPSEEK_API_KEY")
    manifest = _read_json(ROOT / args.manifest if not Path(args.manifest).is_absolute() else Path(args.manifest))
    wanted = set(args.pattern or [])
    entries = [entry for entry in manifest.get("chapters", []) if isinstance(entry, Mapping)]
    if wanted:
        entries = [entry for entry in entries if str(entry.get("pattern_id")) in wanted]
    rows = [
        backfill_one(
            entry,
            model=args.model,
            temperature=args.temperature,
            timeout_s=args.timeout_s,
            max_tokens=args.max_tokens,
            force=args.force,
        )
        for entry in entries
    ]
    report = {
        "backfill_id": BACKFILL_ID,
        "status": "PASS" if all(row["status"] in {"PASS", "SKIP"} for row in rows) else "FAIL",
        "model": args.model,
        "temperature": args.temperature,
        "rows": rows,
    }
    _write_json(OUT_DIR / "public_rule_backfill_report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
