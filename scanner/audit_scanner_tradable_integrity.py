"""Audit scanner and tradable-layer wiring for final chapters.

This gate is intentionally about provenance and wiring, not whether a pattern
deserves promotion.  It catches the class of mistakes where two chapters share
an event source without a variant filter, or a tradable artifact is attached to
the wrong pattern.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.run_chapter_tradable_layer import CHAPTER_SPECS, ChapterSpec  # noqa: E402


AUDIT_ID = "scanner_tradable_integrity_gate_v1"
DEFAULT_MANIFEST = Path("artifacts/final_chapters/final_chapters_manifest.json")
DEFAULT_PREFLIGHT_MATRIX = Path("artifacts/final_chapters/governance/chapter_tradable_preflight_matrix.json")
DEFAULT_GOVERNANCE_MATRIX = Path("artifacts/final_chapters/governance/chapter_governance_matrix.json")


@dataclass(frozen=True)
class VariantCount:
    exists: bool
    has_variant_column: bool
    matching_rows: int
    total_rows: int


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _count_variant_rows(path: Path, variant: str | None) -> VariantCount:
    if not path.exists():
        return VariantCount(False, False, 0, 0)
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        has_variant = bool(reader.fieldnames and "variant" in reader.fieldnames)
        total = 0
        matches = 0
        for row in reader:
            total += 1
            if variant is not None and has_variant and row.get("variant") == variant:
                matches += 1
        if variant is None:
            matches = total
        return VariantCount(True, has_variant, matches, total)


def _row_pattern_ids(payload: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    pattern_id = payload.get("pattern_id")
    if isinstance(pattern_id, str) and pattern_id:
        ids.add(pattern_id)
    source_scope = payload.get("source_scope")
    if isinstance(source_scope, Mapping):
        scoped_pattern = source_scope.get("pattern_id")
        if isinstance(scoped_pattern, str) and scoped_pattern:
            ids.add(scoped_pattern)
    return ids


def _strategy_ids(payload: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in ("selected_strategy_id", "best_strategy_id", "strategy_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            ids.add(value)
    selected_metrics = payload.get("selected_metrics")
    if isinstance(selected_metrics, Mapping):
        value = selected_metrics.get("strategy_id")
        if isinstance(value, str) and value:
            ids.add(value)
    return ids


def audit_chapter_specs(chapter_specs: Mapping[str, ChapterSpec] | None = None) -> dict[str, Any]:
    specs = CHAPTER_SPECS if chapter_specs is None else chapter_specs
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    source_groups: dict[tuple[str, str], list[tuple[str, ChapterSpec]]] = defaultdict(list)

    for key, spec in specs.items():
        if key != spec.pattern_id:
            failures.append(
                {
                    "check": "chapter_spec_key_pattern_mismatch",
                    "pattern_id": key,
                    "detail": f"spec.pattern_id={spec.pattern_id}",
                }
            )
        if not spec.events_path.exists():
            failures.append({"check": "chapter_spec_events_path_exists", "pattern_id": spec.pattern_id, "detail": str(spec.events_path)})
        if not spec.path_path.exists():
            failures.append({"check": "chapter_spec_path_path_exists", "pattern_id": spec.pattern_id, "detail": str(spec.path_path)})
        if spec.variant:
            counts = _count_variant_rows(spec.events_path, spec.variant)
            if counts.exists and not counts.has_variant_column:
                failures.append(
                    {
                        "check": "chapter_spec_variant_column",
                        "pattern_id": spec.pattern_id,
                        "detail": str(spec.events_path),
                    }
                )
            elif counts.exists and counts.matching_rows <= 0:
                failures.append(
                    {
                        "check": "chapter_spec_variant_rows",
                        "pattern_id": spec.pattern_id,
                        "detail": f"{spec.variant} has 0 rows in {spec.events_path}",
                    }
                )
        source_groups[(str(spec.events_path), str(spec.path_path))].append((spec.pattern_id, spec))

    for (events_path, path_path), items in source_groups.items():
        if len(items) <= 1:
            continue
        missing = [pattern_id for pattern_id, spec in items if not spec.variant]
        variants = [spec.variant for _, spec in items if spec.variant]
        duplicate_variants = sorted({variant for variant in variants if variants.count(variant) > 1})
        if missing:
            failures.append(
                {
                    "check": "shared_chapter_spec_source_missing_variant",
                    "pattern_id": ",".join(sorted(missing)),
                    "detail": f"{events_path} | {path_path}",
                }
            )
        if duplicate_variants:
            failures.append(
                {
                    "check": "shared_chapter_spec_duplicate_variant",
                    "pattern_id": ",".join(sorted(pattern_id for pattern_id, _ in items)),
                    "detail": f"{events_path}: {duplicate_variants}",
                }
            )
        warnings.append(
            {
                "check": "shared_chapter_spec_source",
                "pattern_id": ",".join(sorted(pattern_id for pattern_id, _ in items)),
                "detail": f"{events_path} | variants={sorted(variant for variant in variants if variant)}",
            }
        )

    return {
        "status": "PASS" if not failures else "FAIL",
        "counts": {
            "chapter_specs": len(specs),
            "shared_source_groups": sum(1 for items in source_groups.values() if len(items) > 1),
            "failures": len(failures),
            "warnings": len(warnings),
        },
        "failures": failures,
        "warnings": warnings,
    }


def audit_preflight_sources(preflight_path: Path = DEFAULT_PREFLIGHT_MATRIX) -> dict[str, Any]:
    payload = _read_json(preflight_path)
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    rows = payload.get("chapters") if isinstance(payload, Mapping) and isinstance(payload.get("chapters"), list) else []
    source_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)

    for row in rows:
        if not isinstance(row, Mapping):
            continue
        pattern_id = str(row.get("pattern_id") or "")
        if not bool(row.get("preflight_available")):
            continue
        events_raw = str(row.get("events_path") or "")
        if not events_raw:
            failures.append({"check": "preflight_events_path_declared", "pattern_id": pattern_id, "detail": "missing events_path"})
            continue
        events_path = Path(events_raw)
        if not events_path.exists():
            failures.append({"check": "preflight_events_path_exists", "pattern_id": pattern_id, "detail": str(events_path)})
            continue
        variant = row.get("variant_filter")
        variant_str = str(variant) if variant not in (None, "") else None
        if variant_str:
            counts = _count_variant_rows(events_path, variant_str)
            if not counts.has_variant_column:
                failures.append({"check": "preflight_variant_column", "pattern_id": pattern_id, "detail": str(events_path)})
            elif counts.matching_rows <= 0:
                failures.append(
                    {
                        "check": "preflight_variant_rows",
                        "pattern_id": pattern_id,
                        "detail": f"{variant_str} has 0 rows in {events_path}",
                    }
                )
        source_groups[str(events_path)].append(row)

    for events_path, grouped_rows in source_groups.items():
        if len(grouped_rows) <= 1:
            continue
        missing = [str(row.get("pattern_id") or "") for row in grouped_rows if row.get("variant_filter") in (None, "")]
        variants = [str(row.get("variant_filter")) for row in grouped_rows if row.get("variant_filter") not in (None, "")]
        duplicate_variants = sorted({variant for variant in variants if variants.count(variant) > 1})
        if missing:
            failures.append(
                {
                    "check": "shared_preflight_source_missing_variant",
                    "pattern_id": ",".join(sorted(missing)),
                    "detail": events_path,
                }
            )
        if duplicate_variants:
            failures.append(
                {
                    "check": "shared_preflight_source_duplicate_variant",
                    "pattern_id": ",".join(sorted(str(row.get("pattern_id") or "") for row in grouped_rows)),
                    "detail": f"{events_path}: {duplicate_variants}",
                }
            )
        warnings.append(
            {
                "check": "shared_preflight_source",
                "pattern_id": ",".join(sorted(str(row.get("pattern_id") or "") for row in grouped_rows)),
                "detail": f"{events_path} | variants={sorted(variants)}",
            }
        )

    return {
        "status": "PASS" if not failures else "FAIL",
        "preflight_path": str(preflight_path),
        "counts": {
            "rows": len(rows),
            "shared_source_groups": sum(1 for items in source_groups.values() if len(items) > 1),
            "failures": len(failures),
            "warnings": len(warnings),
        },
        "failures": failures,
        "warnings": warnings,
    }


def audit_tradable_governance(governance_path: Path = DEFAULT_GOVERNANCE_MATRIX) -> dict[str, Any]:
    payload = _read_json(governance_path)
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    rows = payload.get("chapters") if isinstance(payload, Mapping) and isinstance(payload.get("chapters"), list) else []
    strategy_id_to_patterns: dict[str, list[str]] = defaultdict(list)

    for row in rows:
        if not isinstance(row, Mapping):
            continue
        pattern_id = str(row.get("pattern_id") or "")
        selected_path_raw = str(row.get("tradable_selected_strategy") or "")
        if not selected_path_raw:
            continue
        selected_path = Path(selected_path_raw)
        if not selected_path.exists():
            failures.append({"check": "tradable_selected_strategy_exists", "pattern_id": pattern_id, "detail": selected_path_raw})
            continue
        selected = _read_json(selected_path)
        if not isinstance(selected, Mapping):
            failures.append({"check": "tradable_selected_strategy_json_object", "pattern_id": pattern_id, "detail": selected_path_raw})
            continue
        declared_pattern_ids = _row_pattern_ids(selected)
        wrong_ids = sorted(item for item in declared_pattern_ids if item != pattern_id)
        if wrong_ids:
            failures.append(
                {
                    "check": "tradable_selected_strategy_pattern_mismatch",
                    "pattern_id": pattern_id,
                    "detail": f"{selected_path}: {wrong_ids}",
                }
            )
        strategy_ids = _strategy_ids(selected)
        if not strategy_ids:
            warnings.append({"check": "tradable_selected_strategy_id_missing", "pattern_id": pattern_id, "detail": selected_path_raw})
        for strategy_id in strategy_ids:
            strategy_id_to_patterns[strategy_id].append(pattern_id)

    for strategy_id, pattern_ids in strategy_id_to_patterns.items():
        unique_patterns = sorted(set(pattern_ids))
        if len(unique_patterns) > 1:
            failures.append(
                {
                    "check": "tradable_selected_strategy_id_reused",
                    "pattern_id": ",".join(unique_patterns),
                    "detail": strategy_id,
                }
            )

    return {
        "status": "PASS" if not failures else "FAIL",
        "governance_path": str(governance_path),
        "counts": {
            "rows": len(rows),
            "selected_strategy_rows": sum(
                1 for row in rows if isinstance(row, Mapping) and bool(str(row.get("tradable_selected_strategy") or ""))
            ),
            "strategy_ids": len(strategy_id_to_patterns),
            "failures": len(failures),
            "warnings": len(warnings),
        },
        "failures": failures,
        "warnings": warnings,
    }


def audit_manifest(
    manifest_path: Path = DEFAULT_MANIFEST,
    *,
    preflight_path: Path = DEFAULT_PREFLIGHT_MATRIX,
    governance_path: Path = DEFAULT_GOVERNANCE_MATRIX,
    chapter_specs: Mapping[str, ChapterSpec] | None = None,
) -> dict[str, Any]:
    manifest_payload = _read_json(manifest_path)
    chapters = manifest_payload.get("chapters") if isinstance(manifest_payload, Mapping) and isinstance(manifest_payload.get("chapters"), list) else []
    manifest_ids = {
        str(row.get("pattern_id") or "")
        for row in chapters
        if isinstance(row, Mapping) and str(row.get("pattern_id") or "")
    }

    spec_report = audit_chapter_specs(chapter_specs)
    preflight_report = audit_preflight_sources(preflight_path)
    governance_report = audit_tradable_governance(governance_path)

    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for source, report in (
        ("chapter_specs", spec_report),
        ("preflight_sources", preflight_report),
        ("tradable_governance", governance_report),
    ):
        for failure in report["failures"]:
            failures.append({"source": source, **failure})
        for warning in report["warnings"]:
            warnings.append({"source": source, **warning})

    spec_ids = set((CHAPTER_SPECS if chapter_specs is None else chapter_specs).keys())
    missing_spec_ids = sorted(manifest_ids - spec_ids)
    warnings.append(
        {
            "source": "chapter_specs",
            "check": "manifest_without_generic_chapter_spec",
            "pattern_id": ",".join(missing_spec_ids),
            "detail": "patterns may use preflight or external tradable evidence instead of the generic layer",
        }
    ) if missing_spec_ids else None

    return {
        "audit_id": AUDIT_ID,
        "status": "PASS" if not failures else "FAIL",
        "manifest": str(manifest_path),
        "counts": {
            "manifest_chapters": len(manifest_ids),
            "chapter_specs": spec_report["counts"]["chapter_specs"],
            "preflight_rows": preflight_report["counts"]["rows"],
            "governance_rows": governance_report["counts"]["rows"],
            "failures": len(failures),
            "warnings": len(warnings),
        },
        "subreports": {
            "chapter_specs": spec_report,
            "preflight_sources": preflight_report,
            "tradable_governance": governance_report,
        },
        "failures": failures,
        "warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit scanner/tradable integrity for final chapters.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--preflight", default=str(DEFAULT_PREFLIGHT_MATRIX))
    parser.add_argument("--governance", default=str(DEFAULT_GOVERNANCE_MATRIX))
    parser.add_argument("--out")
    args = parser.parse_args()

    report = audit_manifest(Path(args.manifest), preflight_path=Path(args.preflight), governance_path=Path(args.governance))
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
