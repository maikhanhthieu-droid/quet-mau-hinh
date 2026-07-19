"""Build the deep After-the-Buy integration pack.

The first After-the-Buy pass created source maps and several pattern-level rule
artifacts.  This builder turns those separate artifacts into a book-wide
engineering pack:

- section-level source evidence from the After-the-Buy PDF,
- a normalized rule table,
- scanner/stat/trade/publication layer mapping,
- a 63-chapter coverage matrix,
- a before/after impact report for governance.

It does not render publication PDFs and it does not try to overfit low-scoring
chapters into tradable-final status.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.after_buy_source_grounding import (  # noqa: E402
    DEFAULT_AFTER_BUY_PDF,
    DEFAULT_FINAL_MANIFEST,
    DEFAULT_OUT_DIR as DEFAULT_AFTER_BUY_OUT_DIR,
    build_after_buy_source_map,
)


PACK_ID = "after_buy_vietnam_deep_integration_v1"
DEFAULT_SOURCE_MAP = DEFAULT_AFTER_BUY_OUT_DIR / "after_buy_source_map.json"
DEFAULT_GOVERNANCE_MATRIX = Path("artifacts/final_chapters/governance/chapter_governance_matrix.json")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/after_buy_vietnam_v2")

RULE_ARTIFACT_GLOB = "*/*.json"

LAYER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "scanner_rule": (
        "identification",
        "identify",
        "morphology",
        "shape",
        "breakout",
        "confirmation",
        "confirmed",
        "close",
        "apex",
        "trend",
        "branch",
        "setup",
        "configuration",
        "retest",
        "throwback",
        "pullback",
        "gap",
        "volume",
        "pole",
        "neckline",
        "rectangle",
        "triangle",
    ),
    "stat_metric": (
        "target",
        "failure",
        "busted",
        "throwback",
        "pullback",
        "time",
        "mae",
        "mfe",
        "fold",
        "walk-forward",
        "walk_forward",
        "stop-exit",
        "stop hit",
        "performance",
        "attainment",
        "path",
    ),
    "trade_layer_rule": (
        "buy",
        "entry",
        "stop",
        "target",
        "exit",
        "sell",
        "closing position",
        "position",
        "risk",
        "configuration trading",
        "tradable",
        "strategy",
    ),
    "publication_interpretation": (),
}

CONCEPT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "setup": ("buy setup", "setup", "configuration"),
    "stop": ("stop", "best stop", "protective"),
    "target": ("measure rule", "target", "price target"),
    "failure": ("failure", "busted", "throwback", "pullback"),
    "exit": ("sell setup", "sell", "closing position", "exit"),
    "timing": ("apex", "turning point", "time", "trend"),
}


def _read_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_json(path: Path, data: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _normalize_text(*parts: Any) -> str:
    return " ".join(str(part or "").lower().replace("_", " ").replace("-", " ") for part in parts)


def _classify_rule(rule: Mapping[str, Any]) -> list[str]:
    haystack = _normalize_text(
        rule.get("rule_id"),
        rule.get("source_section"),
        rule.get("source_paraphrase"),
        rule.get("local_buy_interpretation"),
    )
    layers: list[str] = []
    for layer, keywords in LAYER_KEYWORDS.items():
        if layer == "publication_interpretation" or any(keyword in haystack for keyword in keywords):
            layers.append(layer)
    return layers


def _concept_hits(text: str) -> list[str]:
    low = text.lower()
    return sorted(concept for concept, keywords in CONCEPT_KEYWORDS.items() if any(keyword in low for keyword in keywords))


def _extract_pdf_section_evidence(after_buy_pdf: Path, source_map: Mapping[str, Any]) -> list[dict[str, Any]]:
    reader = PdfReader(str(after_buy_pdf))
    page_count = len(reader.pages)
    rows: list[dict[str, Any]] = []
    for chapter in source_map.get("chapters") or []:
        if not isinstance(chapter, Mapping):
            continue
        sections = chapter.get("source_sections") if isinstance(chapter.get("source_sections"), list) else []
        section_pages = [int(sec["pdf_page"]) for sec in sections if isinstance(sec, Mapping) and sec.get("pdf_page")]
        for idx, section in enumerate(sections):
            if not isinstance(section, Mapping):
                continue
            page = section.get("pdf_page")
            if not page:
                rows.append(
                    {
                        "source_chapter_no": chapter.get("source_chapter_no"),
                        "source_title": chapter.get("source_title"),
                        "section_title": section.get("title"),
                        "pdf_page": None,
                        "text_chars": 0,
                        "detected_concepts": _concept_hits(str(section.get("title") or "")),
                    }
                )
                continue
            start = max(1, int(page))
            next_pages = [p for p in section_pages if p > start]
            end = min((min(next_pages) - 1) if next_pages else start, page_count)
            # Keep extraction bounded; section titles and first page are enough
            # for grounding the engineering rule artifact without bloating it.
            text_parts: list[str] = []
            for page_no in range(start, min(end, start + 1) + 1):
                try:
                    text_parts.append(reader.pages[page_no - 1].extract_text() or "")
                except Exception:
                    pass
            text = "\n".join(text_parts)
            rows.append(
                {
                    "source_chapter_no": chapter.get("source_chapter_no"),
                    "source_title": chapter.get("source_title"),
                    "section_title": section.get("title"),
                    "pdf_page": start,
                    "text_chars": len(text),
                    "detected_concepts": sorted(set(_concept_hits(str(section.get("title") or "")) + _concept_hits(text))),
                }
            )
    return rows


def _iter_rule_artifacts(after_buy_dir: Path) -> Iterable[tuple[Path, Mapping[str, Any]]]:
    for path in sorted(after_buy_dir.glob(RULE_ARTIFACT_GLOB)):
        if path.name in {"after_buy_source_map.json", "after_buy_tradable_priority.json"}:
            continue
        data = _read_json(path)
        if isinstance(data, Mapping) and (data.get("source_rules") or data.get("patterns") or data.get("kpi_evidence")):
            yield path, data


def _artifact_pattern_ids(data: Mapping[str, Any]) -> list[str]:
    pattern_id = data.get("pattern_id")
    if pattern_id:
        return [str(pattern_id)]
    rows = data.get("patterns")
    if isinstance(rows, list):
        ids = [str(row.get("pattern_id")) for row in rows if isinstance(row, Mapping) and row.get("pattern_id")]
        return sorted(set(ids))
    return []


def _normalize_rule_rows(after_buy_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for artifact_path, data in _iter_rule_artifacts(after_buy_dir):
        pattern_ids = _artifact_pattern_ids(data)
        source_rules = data.get("source_rules") if isinstance(data.get("source_rules"), list) else []
        for rule in source_rules:
            if not isinstance(rule, Mapping):
                continue
            layers = _classify_rule(rule)
            for pattern_id in pattern_ids or ["family_level"]:
                rows.append(
                    {
                        "pattern_id": pattern_id,
                        "artifact_path": str(artifact_path),
                        "rule_id": str(rule.get("rule_id")),
                        "source_origin": rule.get("source_origin"),
                        "source_section": rule.get("source_section"),
                        "source_paraphrase": rule.get("source_paraphrase"),
                        "local_interpretation": rule.get("local_buy_interpretation") or rule.get("local_interpretation"),
                        "layers": layers,
                    }
                )
    return rows


def _source_roles(source_map: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    roles: dict[str, dict[str, Any]] = {}
    for chapter in source_map.get("chapters") or []:
        if not isinstance(chapter, Mapping):
            continue
        for role in chapter.get("edition1_pattern_buy_roles") or []:
            if isinstance(role, Mapping) and role.get("pattern_id"):
                roles[str(role["pattern_id"])] = {
                    "source_chapter_no": chapter.get("source_chapter_no"),
                    "source_title": chapter.get("source_title"),
                    "source_local_role": chapter.get("local_role"),
                    "local_role": role.get("local_role"),
                    "buy_layer_allowed": bool(role.get("buy_layer_allowed")),
                    "buy_scope": role.get("buy_scope"),
                    "reason": role.get("reason") or chapter.get("vietnam_use"),
                }
    return roles


def _governance_rows(governance_path: Path) -> dict[str, Mapping[str, Any]]:
    data = _read_json(governance_path)
    rows = data.get("chapters") if isinstance(data.get("chapters"), list) else []
    return {str(row.get("pattern_id")): row for row in rows if isinstance(row, Mapping) and row.get("pattern_id")}


def _manifest_rows(final_manifest: Path) -> list[Mapping[str, Any]]:
    data = _read_json(final_manifest)
    rows = data.get("chapters") if isinstance(data.get("chapters"), list) else []
    return [row for row in rows if isinstance(row, Mapping) and row.get("pattern_id")]


def _rules_by_pattern(rule_rows: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rule_rows:
        grouped[str(row.get("pattern_id"))].append(row)
    return grouped


def _recommended_action(
    *,
    pattern_id: str,
    source_role: Mapping[str, Any] | None,
    governance: Mapping[str, Any] | None,
    rule_count: int,
) -> str:
    if source_role and source_role.get("buy_layer_allowed") is False:
        return "Convert to avoid/exit/risk filter; never promote as Vietnam long-cash BUY."
    if source_role is None:
        if any(token in pattern_id for token in ("top", "bear", "down")):
            return "Policy defensive/reference only; no direct After-the-Buy BUY source."
        return "No direct After-the-Buy rule yet; keep existing chapter until source-specific pass exists."
    score = _float((governance or {}).get("tradable_score"))
    blockers = str((governance or {}).get("tradable_blockers") or "")
    if source_role.get("buy_layer_allowed") and score is not None and score >= 95:
        return "Preserve as BUY/tradable-final candidate; use After-the-Buy section in publication."
    if source_role.get("buy_layer_allowed") and rule_count > 0 and ("walk_forward_has_negative_fold" in blockers or (score is not None and score < 95)):
        return "Retain source-grounded watchlist/research role; do not overfit remaining gap."
    if source_role.get("buy_layer_allowed"):
        return "Eligible for source-guided rerun if data depth supports it."
    return "Keep as reference/context."


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coverage_matrix(
    *,
    manifest: Sequence[Mapping[str, Any]],
    roles: Mapping[str, Mapping[str, Any]],
    governance: Mapping[str, Mapping[str, Any]],
    rules_by_pattern: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for chapter in manifest:
        pattern_id = str(chapter.get("pattern_id"))
        source_role = roles.get(pattern_id)
        gov = governance.get(pattern_id, {})
        pattern_rules = list(rules_by_pattern.get(pattern_id, []))
        layer_counts = {
            layer: sum(1 for rule in pattern_rules if layer in (rule.get("layers") or []))
            for layer in LAYER_KEYWORDS
        }
        rows.append(
            {
                "pattern_id": pattern_id,
                "title": chapter.get("title"),
                "family": chapter.get("family"),
                "after_buy_source_status": "mapped" if source_role else "not_directly_mapped",
                "after_buy_source_title": (source_role or {}).get("source_title"),
                "local_role": (source_role or {}).get("local_role") or ("avoid_exit" if any(t in pattern_id for t in ("top", "bear", "down")) else "unmapped_reference"),
                "buy_layer_allowed": bool((source_role or {}).get("buy_layer_allowed")),
                "buy_scope": (source_role or {}).get("buy_scope") or "not_buy_eligible_or_unmapped",
                "source_rule_count": len(pattern_rules),
                "scanner_rule_count": layer_counts["scanner_rule"],
                "stat_metric_count": layer_counts["stat_metric"],
                "trade_layer_rule_count": layer_counts["trade_layer_rule"],
                "publication_interpretation_count": layer_counts["publication_interpretation"],
                "tradable_score": _float(gov.get("tradable_score")),
                "tradable_status": gov.get("tradable_status"),
                "tradable_release_status": gov.get("tradable_release_status"),
                "tradable_blockers": gov.get("tradable_blockers"),
                "recommended_after_buy_action": _recommended_action(
                    pattern_id=pattern_id,
                    source_role=source_role,
                    governance=gov,
                    rule_count=len(pattern_rules),
                ),
            }
        )
    return rows


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _layer_mapping(rule_rows: Sequence[Mapping[str, Any]], coverage_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_layer: dict[str, list[dict[str, Any]]] = {layer: [] for layer in LAYER_KEYWORDS}
    for row in rule_rows:
        for layer in row.get("layers") or []:
            by_layer[layer].append(
                {
                    "pattern_id": row.get("pattern_id"),
                    "rule_id": row.get("rule_id"),
                    "source_section": row.get("source_section"),
                    "artifact_path": row.get("artifact_path"),
                }
            )
    return {
        "layer_mapping_id": "after_buy_rule_layer_mapping_v1",
        "layer_counts": {layer: len(rows) for layer, rows in by_layer.items()},
        "layers": by_layer,
        "coverage_summary": {
            "normalized_rule_rows": len(rule_rows),
            "chapter_count": len(coverage_rows),
            "mapped_chapter_count": sum(1 for row in coverage_rows if row["after_buy_source_status"] == "mapped"),
            "buy_allowed_chapter_count": sum(1 for row in coverage_rows if row["buy_layer_allowed"]),
            "chapters_with_rules": sum(1 for row in coverage_rows if int(row["source_rule_count"]) > 0),
            "defensive_or_unmapped_count": sum(1 for row in coverage_rows if not row["buy_layer_allowed"]),
        },
    }


def _impact_report(coverage_rows: Sequence[Mapping[str, Any]], layer_mapping: Mapping[str, Any]) -> dict[str, Any]:
    pass_tradable = [row for row in coverage_rows if row.get("tradable_release_status") == "PASS"]
    blocked_buy = [
        row
        for row in coverage_rows
        if row.get("buy_layer_allowed")
        and row.get("tradable_release_status") != "PASS"
        and int(row.get("source_rule_count") or 0) > 0
    ]
    defensive = [row for row in coverage_rows if not row.get("buy_layer_allowed")]
    return {
        "report_id": "after_buy_before_after_impact_v1",
        "before": {
            "state": "Pattern atlas and tradable layer existed, but After-the-Buy rules were scattered across pattern artifacts.",
            "main_risk": "Hard to see book-wide coverage, defensive leakage risk, and which rule improves scanner/stat/trade/publication layers.",
        },
        "after": {
            "state": "After-the-Buy has a normalized rule table, layer mapping, coverage matrix, and no-overfit recommendations.",
            "source_grounded_rule_rows": layer_mapping.get("coverage_summary", {}).get("normalized_rule_rows"),
            "chapters_with_after_buy_rules": layer_mapping.get("coverage_summary", {}).get("chapters_with_rules"),
            "buy_allowed_chapters": layer_mapping.get("coverage_summary", {}).get("buy_allowed_chapter_count"),
            "tradable_pass_chapters": len(pass_tradable),
            "source_grounded_but_blocked_buy_chapters": len(blocked_buy),
            "defensive_or_unmapped_chapters": len(defensive),
        },
        "decision": {
            "scanner": "Use scanner_rule rows as pattern/family-specific quality gates, not global thresholds.",
            "statistics": "Use stat_metric rows to add path/failure/target-first/retest metrics where data supports them.",
            "trade_layer": "Use trade_layer_rule rows for entry/stop/target/time-exit reruns, while preserving no-overfit blockers.",
            "publication": "Use publication_interpretation rows to add a 'Hành vi sau phá vỡ' section per chapter.",
        },
        "priority_next": [
            row["pattern_id"]
            for row in blocked_buy
            if any(name in row["pattern_id"] for name in ("pennant", "triangle", "rectangle", "broadening", "head_and_shoulders", "high_tight"))
        ][:12],
    }


def _runtime_config(coverage_rows: Sequence[Mapping[str, Any]], rule_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rules_by_pattern = _rules_by_pattern(rule_rows)
    patterns: list[dict[str, Any]] = []
    for row in coverage_rows:
        pattern_id = str(row["pattern_id"])
        pattern_rules = list(rules_by_pattern.get(pattern_id, []))
        scanner_rule_ids = [str(rule.get("rule_id")) for rule in pattern_rules if "scanner_rule" in (rule.get("layers") or [])]
        stat_rule_ids = [str(rule.get("rule_id")) for rule in pattern_rules if "stat_metric" in (rule.get("layers") or [])]
        trade_rule_ids = [str(rule.get("rule_id")) for rule in pattern_rules if "trade_layer_rule" in (rule.get("layers") or [])]
        blockers = str(row.get("tradable_blockers") or "")
        score = _float(row.get("tradable_score"))
        buy_allowed = bool(row.get("buy_layer_allowed"))
        if not buy_allowed:
            trade_mode = "defensive_or_reference_filter"
        elif row.get("tradable_release_status") == "PASS":
            trade_mode = "preserve_tradable_final"
        elif pattern_rules:
            trade_mode = "source_guided_watchlist_or_rerun_blocked"
        else:
            trade_mode = "needs_source_rule_before_rerun"
        patterns.append(
            {
                "pattern_id": pattern_id,
                "local_role": row.get("local_role"),
                "buy_layer_allowed": buy_allowed,
                "buy_scope": row.get("buy_scope"),
                "scanner_quality_rule_ids": scanner_rule_ids,
                "required_stat_rule_ids": stat_rule_ids,
                "trade_layer_rule_ids": trade_rule_ids,
                "trade_layer_mode": trade_mode,
                "no_overfit_gate": {
                    "enabled": True,
                    "block_promotion_if": [
                        "walk_forward_has_negative_fold",
                        "score_below_95",
                        "validation_or_holdout_trade_depth_too_low",
                        "scope_not_direct_long_cash_equity",
                    ],
                    "currently_blocked": bool(
                        "walk_forward_has_negative_fold" in blockers
                        or "score_below_95" in blockers
                        or "scope_not_direct_long_cash_equity" in blockers
                        or (buy_allowed and score is not None and score < 95 and row.get("tradable_release_status") != "PASS")
                    ),
                },
                "publication_after_buy_section": {
                    "include": bool(pattern_rules or not buy_allowed),
                    "mode": "hành_vi_sau_phá_vỡ" if buy_allowed else "cảnh_báo_rủi_ro_sau_phá_vỡ",
                    "source_rule_count": len(pattern_rules),
                },
            }
        )
    return {
        "config_id": "after_buy_scanner_stat_trade_config_v1",
        "purpose": "Machine-readable bridge from After-the-Buy source rules to scanner, statistics, trade layer, and publication.",
        "patterns": patterns,
        "summary": {
            "pattern_count": len(patterns),
            "buy_allowed_count": sum(1 for pattern in patterns if pattern["buy_layer_allowed"]),
            "defensive_or_reference_count": sum(1 for pattern in patterns if not pattern["buy_layer_allowed"]),
            "patterns_with_scanner_rules": sum(1 for pattern in patterns if pattern["scanner_quality_rule_ids"]),
            "patterns_with_stat_rules": sum(1 for pattern in patterns if pattern["required_stat_rule_ids"]),
            "patterns_with_trade_rules": sum(1 for pattern in patterns if pattern["trade_layer_rule_ids"]),
            "currently_blocked_buy_patterns": sum(
                1 for pattern in patterns if pattern["buy_layer_allowed"] and pattern["no_overfit_gate"]["currently_blocked"]
            ),
        },
    }


def build_after_buy_deep_integration(
    *,
    after_buy_pdf: Path = DEFAULT_AFTER_BUY_PDF,
    source_map_path: Path = DEFAULT_SOURCE_MAP,
    final_manifest: Path = DEFAULT_FINAL_MANIFEST,
    governance_path: Path = DEFAULT_GOVERNANCE_MATRIX,
    after_buy_v1_dir: Path = DEFAULT_AFTER_BUY_OUT_DIR,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    if not source_map_path.exists():
        source_map = build_after_buy_source_map(after_buy_pdf=after_buy_pdf, final_manifest=final_manifest, out_dir=source_map_path.parent)
    else:
        source_map = _read_json(source_map_path)
    manifest = _manifest_rows(final_manifest)
    governance = _governance_rows(governance_path)
    roles = _source_roles(source_map)
    section_evidence = _extract_pdf_section_evidence(after_buy_pdf, source_map)
    rule_rows = _normalize_rule_rows(after_buy_v1_dir)
    by_pattern = _rules_by_pattern(rule_rows)
    coverage_rows = _coverage_matrix(manifest=manifest, roles=roles, governance=governance, rules_by_pattern=by_pattern)
    layer_mapping = _layer_mapping(rule_rows, coverage_rows)
    impact = _impact_report(coverage_rows, layer_mapping)
    runtime_config = _runtime_config(coverage_rows, rule_rows)

    failures: list[str] = []
    if len(manifest) != 63:
        failures.append(f"expected_63_manifest_chapters_found_{len(manifest)}")
    if not section_evidence:
        failures.append("missing_pdf_section_evidence")
    if not rule_rows:
        failures.append("missing_normalized_rule_rows")
    if layer_mapping["coverage_summary"]["mapped_chapter_count"] < 20:
        failures.append("too_few_after_buy_mapped_chapters")
    if layer_mapping["coverage_summary"]["chapters_with_rules"] < 10:
        failures.append("too_few_chapters_with_deep_rules")

    pack = {
        "pack_id": PACK_ID,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "source_grounding_id": source_map.get("source_grounding_id"),
        "buy_first_policy_id": source_map.get("buy_first_policy_id"),
        "after_buy_pdf": str(after_buy_pdf),
        "outputs": {
            "deep_rules": str(out_dir / "after_buy_deep_rules.json"),
            "coverage_matrix_json": str(out_dir / "after_buy_chapter_coverage_matrix.json"),
            "coverage_matrix_csv": str(out_dir / "after_buy_chapter_coverage_matrix.csv"),
            "layer_mapping": str(out_dir / "after_buy_rule_layer_mapping.json"),
            "scanner_stat_trade_config": str(out_dir / "after_buy_scanner_stat_trade_config.json"),
            "impact_report": str(out_dir / "after_buy_before_after_impact_report.json"),
        },
        "summary": {
            "source_chapters": source_map.get("source_chapter_count"),
            "manifest_chapters": len(manifest),
            "section_evidence_rows": len(section_evidence),
            "normalized_rule_rows": len(rule_rows),
            **layer_mapping["coverage_summary"],
        },
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "after_buy_deep_rules.json", {"pack_id": PACK_ID, "section_evidence": section_evidence, "rules": rule_rows})
    _write_json(out_dir / "after_buy_chapter_coverage_matrix.json", {"pack_id": PACK_ID, "chapters": coverage_rows})
    _write_csv(out_dir / "after_buy_chapter_coverage_matrix.csv", coverage_rows)
    _write_json(out_dir / "after_buy_rule_layer_mapping.json", layer_mapping)
    _write_json(out_dir / "after_buy_scanner_stat_trade_config.json", runtime_config)
    _write_json(out_dir / "after_buy_before_after_impact_report.json", impact)
    _write_json(out_dir / "after_buy_deep_integration_pack.json", pack)
    _write_markdown(out_dir / "after_buy_deep_integration_pack.md", pack, impact, coverage_rows, layer_mapping)
    return pack


def _write_markdown(
    path: Path,
    pack: Mapping[str, Any],
    impact: Mapping[str, Any],
    coverage_rows: Sequence[Mapping[str, Any]],
    layer_mapping: Mapping[str, Any],
) -> None:
    lines = [
        "# After-the-Buy Deep Integration Pack",
        "",
        f"- Pack ID: `{pack['pack_id']}`",
        f"- Status: `{pack['status']}`",
        f"- Manifest chapters: `{pack['summary']['manifest_chapters']}`",
        f"- Chapters with After-the-Buy rules: `{pack['summary']['chapters_with_rules']}`",
        f"- BUY-allowed chapters: `{pack['summary']['buy_allowed_chapter_count']}`",
        f"- Normalized rule rows: `{pack['summary']['normalized_rule_rows']}`",
        "",
        "## Before / After",
        "",
        "| Layer | Before | After |",
        "|---|---|---|",
        "| Source | Rules scattered across individual artifacts | Section evidence, normalized rules, coverage matrix |",
        "| Scanner | Pattern scanners had limited After-the-Buy visibility | `scanner_rule` rows identify candidate quality gates |",
        "| Statistics | Existing MFE/MAE/target metrics lacked a book-wide rule map | `stat_metric` rows point to failure, target, retest, stop, and path metrics |",
        "| Trade layer | Reruns existed pattern-by-pattern | `trade_layer_rule` rows plus no-overfit recommendations show where rerun is justified |",
        "| Publication | Atlas chapters did not systematically include After-the-Buy | `publication_interpretation` rows can feed 'Hành vi sau phá vỡ' sections |",
        "",
        "## Layer Counts",
        "",
        "| Layer | Rule rows |",
        "|---|---:|",
    ]
    for layer, count in layer_mapping.get("layer_counts", {}).items():
        lines.append(f"| `{layer}` | {count} |")
    lines.extend(
        [
            "",
            "## Highest-Priority Blocked BUY/Watchlist Chapters",
            "",
            "| Pattern | Score | Blockers | Recommended action |",
            "|---|---:|---|---|",
        ]
    )
    candidates = [
        row
        for row in coverage_rows
        if row.get("buy_layer_allowed")
        and row.get("tradable_release_status") != "PASS"
        and int(row.get("source_rule_count") or 0) > 0
    ][:15]
    for row in candidates:
        score = "" if row.get("tradable_score") is None else f"{row.get('tradable_score'):.2f}"
        lines.append(f"| `{row['pattern_id']}` | {score} | {row.get('tradable_blockers') or ''} | {row.get('recommended_after_buy_action')} |")
    lines.extend(
        [
            "",
            "## Decision",
            "",
            f"- Scanner: {impact['decision']['scanner']}",
            f"- Statistics: {impact['decision']['statistics']}",
            f"- Trade layer: {impact['decision']['trade_layer']}",
            f"- Publication: {impact['decision']['publication']}",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build After-the-Buy deep integration artifacts.")
    parser.add_argument("--after-buy-pdf", type=Path, default=DEFAULT_AFTER_BUY_PDF)
    parser.add_argument("--source-map", type=Path, default=DEFAULT_SOURCE_MAP)
    parser.add_argument("--final-manifest", type=Path, default=DEFAULT_FINAL_MANIFEST)
    parser.add_argument("--governance", type=Path, default=DEFAULT_GOVERNANCE_MATRIX)
    parser.add_argument("--after-buy-v1-dir", type=Path, default=DEFAULT_AFTER_BUY_OUT_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    result = build_after_buy_deep_integration(
        after_buy_pdf=args.after_buy_pdf,
        source_map_path=args.source_map,
        final_manifest=args.final_manifest,
        governance_path=args.governance,
        after_buy_v1_dir=args.after_buy_v1_dir,
        out_dir=args.out_dir,
    )
    print(json.dumps({"status": result["status"], "summary": result["summary"], "out_dir": str(args.out_dir)}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
