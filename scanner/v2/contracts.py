"""Contract-first Scanner V2 foundation.

This module is intentionally stricter than the legacy digitized scanner:
missing provenance, unsupported rule types, and incomplete lineage are
contract errors. V2 should not silently scan a pattern that cannot be traced
back to the source book.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


PACKAGE_DIR = Path(__file__).resolve().parent
CORE_REGISTRY_PATH = PACKAGE_DIR / "core_patterns.json"
TAXONOMY_LINEAGE_PATH = PACKAGE_DIR / "taxonomy_lineage.json"

CORE_PATTERN_KEYS: Tuple[str, ...] = (
    "bull_flags",
    "bear_flags",
    "double_bottoms",
    "double_tops",
    "head_and_shoulders_bottoms",
    "head_and_shoulders_tops",
    "triangles_ascending",
    "triangles_descending",
    "triangles_symmetrical",
    "wedges_falling",
    "wedges_rising",
    "cup_with_handle",
)

REQUIRED_RULE_FIELDS: Tuple[str, ...] = (
    "book_chapter",
    "source_page",
    "source_section",
    "evidence_excerpt",
    "interpreted_rule",
    "numeric_threshold",
    "confidence",
    "notes_when_ambiguous",
)

SUPPORTED_RULE_TYPES: Dict[str, str] = {
    "prior_trend": "trend",
    "trend_context": "trend",
    "pivot_sequence": "pattern_structure",
    "trendline_geometry": "pattern_structure",
    "shape_geometry": "pattern_structure",
    "shape": "pattern_structure",
    "touch_count": "pattern_structure",
    "path_quality": "pattern_structure",
    "time_geometry": "pattern_structure",
    "position_context": "pattern_context",
    "duration": "pattern_context",
    "height": "pattern_geometry",
    "breakout": "breakout",
    "measurement": "post_breakout_measurement",
    "target": "post_breakout_measurement",
    "target_measure_rule": "post_breakout_measurement",
    "post_breakout_behavior": "post_breakout_measurement",
    "volume": "volume",
    "volume_context": "volume",
    "variant_shape": "variant_geometry",
    "invalidation": "invalidation",
}


class ContractError(ValueError):
    """Raised when a Scanner V2 pattern violates the source-to-scanner contract."""


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise ContractError(f"{path} must contain a JSON object")
    return obj


def load_core_registry(path: Path = CORE_REGISTRY_PATH) -> Dict[str, Any]:
    return _read_json(path)


def load_taxonomy_lineage(path: Path = TAXONOMY_LINEAGE_PATH) -> Dict[str, Any]:
    return _read_json(path)


def canonical_spec_hash(obj: Mapping[str, Any]) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _require(condition: bool, message: str, errors: List[str]) -> None:
    if not condition:
        errors.append(message)


def _validate_numeric_threshold(rule_id: str, value: Any, errors: List[str]) -> None:
    _require(isinstance(value, dict), f"{rule_id}: numeric_threshold must be an object", errors)
    if not isinstance(value, dict):
        return
    for field in ("operator", "value", "unit"):
        _require(field in value, f"{rule_id}: numeric_threshold.{field} is required", errors)


def validate_rule_provenance(rule: Mapping[str, Any], *, pattern_key: str) -> List[str]:
    rule_id = str(rule.get("rule_id") or "<missing_rule_id>")
    errors: List[str] = []

    _require(bool(rule.get("rule_id")), f"{pattern_key}: rule_id is required", errors)
    _require(bool(rule.get("rule_type")), f"{rule_id}: rule_type is required", errors)

    for field in REQUIRED_RULE_FIELDS:
        _require(field in rule, f"{rule_id}: {field} is required", errors)

    chapter = rule.get("book_chapter")
    _require(isinstance(chapter, int) and chapter > 0, f"{rule_id}: book_chapter must be positive int", errors)

    page = rule.get("source_page")
    _require(isinstance(page, int) and page > 0, f"{rule_id}: source_page must be positive int", errors)

    evidence = str(rule.get("evidence_excerpt") or "").strip()
    _require(bool(evidence), f"{rule_id}: evidence_excerpt must not be empty", errors)
    _require(len(evidence) <= 180, f"{rule_id}: evidence_excerpt must stay short", errors)

    interpreted = str(rule.get("interpreted_rule") or "").strip()
    _require(bool(interpreted), f"{rule_id}: interpreted_rule must not be empty", errors)

    _validate_numeric_threshold(rule_id, rule.get("numeric_threshold"), errors)

    confidence = rule.get("confidence")
    _require(isinstance(confidence, (int, float)) and 0.0 <= float(confidence) <= 1.0, f"{rule_id}: confidence must be 0..1", errors)

    _require(isinstance(rule.get("notes_when_ambiguous"), str), f"{rule_id}: notes_when_ambiguous must be a string", errors)
    return errors


def validate_pattern_provenance(pattern_key: str, pattern: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    _require(str(pattern.get("pattern_key") or "") == pattern_key, f"{pattern_key}: pattern_key mismatch", errors)
    rules = pattern.get("rules")
    _require(isinstance(rules, list) and bool(rules), f"{pattern_key}: rules must be non-empty list", errors)
    if isinstance(rules, list):
        seen: set[str] = set()
        for rule in rules:
            if not isinstance(rule, dict):
                errors.append(f"{pattern_key}: every rule must be an object")
                continue
            rule_id = str(rule.get("rule_id") or "")
            if rule_id in seen:
                errors.append(f"{pattern_key}: duplicate rule_id {rule_id}")
            if rule_id:
                seen.add(rule_id)
            errors.extend(validate_rule_provenance(rule, pattern_key=pattern_key))
    return errors


def _lineage_for(lineage: Mapping[str, Any], pattern_key: str) -> Mapping[str, Any]:
    items = lineage.get("lineage")
    if not isinstance(items, dict):
        raise ContractError("taxonomy_lineage.json must contain lineage object")
    item = items.get(pattern_key)
    if not isinstance(item, dict):
        raise ContractError(f"{pattern_key}: missing taxonomy lineage")
    return item


def validate_lineage(pattern_key: str, pattern: Mapping[str, Any], lineage: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    try:
        item = _lineage_for(lineage, pattern_key)
    except ContractError as exc:
        return [str(exc)]

    _require(bool(item.get("bulkowski_chapters")), f"{pattern_key}: bulkowski_chapters is required", errors)
    _require(bool(item.get("source_patterns")), f"{pattern_key}: source_patterns is required", errors)
    _require(bool(item.get("normalized_rule_spec")), f"{pattern_key}: normalized_rule_spec is required", errors)
    _require(bool(item.get("scanner_pattern_key")), f"{pattern_key}: scanner_pattern_key is required", errors)
    _require(bool(item.get("result_payload_contract")), f"{pattern_key}: result_payload_contract is required", errors)
    _require(bool(item.get("book_v2_chapters")), f"{pattern_key}: book_v2_chapters is required", errors)

    expected = f"v2:{pattern_key}"
    _require(str(item.get("scanner_pattern_key")) == expected, f"{pattern_key}: scanner_pattern_key must be {expected}", errors)

    pattern_chapters = {
        int(ch["chapter"])
        for ch in pattern.get("book_chapters", [])
        if isinstance(ch, dict) and isinstance(ch.get("chapter"), int)
    }
    lineage_chapters = {int(x) for x in item.get("bulkowski_chapters", []) if isinstance(x, int)}
    _require(bool(pattern_chapters & lineage_chapters), f"{pattern_key}: lineage chapters do not match provenance chapters", errors)
    return errors


@dataclass(frozen=True)
class RuleCoverageRow:
    rule_id: str
    rule_type: str
    module: Optional[str]
    status: str
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_type": self.rule_type,
            "module": self.module,
            "status": self.status,
            "reason": self.reason,
        }


def build_rule_coverage(pattern: Mapping[str, Any]) -> List[RuleCoverageRow]:
    rows: List[RuleCoverageRow] = []
    for rule in pattern.get("rules", []):
        if not isinstance(rule, dict):
            rows.append(RuleCoverageRow("<invalid>", "<invalid>", None, "error", "rule is not an object"))
            continue
        rule_id = str(rule.get("rule_id") or "<missing_rule_id>")
        rule_type = str(rule.get("rule_type") or "<missing_rule_type>")
        module = SUPPORTED_RULE_TYPES.get(rule_type)
        if module is None:
            rows.append(RuleCoverageRow(rule_id, rule_type, None, "unimplemented", "unsupported rule_type"))
        else:
            rows.append(RuleCoverageRow(rule_id, rule_type, module, "implemented", "mapped to V2 module"))
    return rows


def _coverage_errors(pattern_key: str, coverage: Sequence[RuleCoverageRow]) -> List[str]:
    return [
        f"{pattern_key}: {row.rule_id} has unimplemented rule_type {row.rule_type}"
        for row in coverage
        if row.status != "implemented"
    ]


def _detector_rule_errors(pattern_key: str, pattern: Mapping[str, Any]) -> List[str]:
    if pattern_key == "bull_flags":
        from .bull_flags import BULL_FLAGS_SUPPORTED_RULE_IDS

        supported = BULL_FLAGS_SUPPORTED_RULE_IDS
    elif pattern_key == "bear_flags":
        from .bull_flags import BEAR_FLAGS_SUPPORTED_RULE_IDS

        supported = BEAR_FLAGS_SUPPORTED_RULE_IDS
    else:
        return []

    errors: List[str] = []
    for rule in pattern.get("rules", []):
        if not isinstance(rule, dict):
            continue
        rule_id = str(rule.get("rule_id") or "")
        if rule_id not in supported:
            errors.append(f"{pattern_key}: {rule_id} is not implemented by the V2 detector")
    return errors


def _fixture_errors(pattern_key: str, pattern: Mapping[str, Any]) -> List[str]:
    fixtures = pattern.get("golden_fixtures")
    if not isinstance(fixtures, list):
        return [f"{pattern_key}: golden_fixtures must be a list"]
    if pattern_key == "bull_flags":
        from .bull_flags import run_bull_flags_fixture

        runner = run_bull_flags_fixture
    elif pattern_key == "bear_flags":
        from .bull_flags import run_bear_flags_fixture

        runner = run_bear_flags_fixture
    else:
        return []

    errors: List[str] = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            errors.append(f"{pattern_key}: every golden fixture must be an object")
            continue
        fixture_id = str(fixture.get("fixture_id") or "<missing_fixture_id>")
        if not fixture.get("fixture_id"):
            errors.append(f"{pattern_key}: fixture_id is required")
        expected = fixture.get("expected_match")
        if not isinstance(expected, bool):
            errors.append(f"{pattern_key}: {fixture_id} expected_match must be boolean")
            continue
        result = runner(fixture)
        if result.matched != expected:
            errors.append(
                f"{pattern_key}: {fixture_id} expected_match={expected} got {result.matched} reasons={list(result.reasons)}"
            )
        expected_direction = fixture.get("expected_breakout_direction")
        if expected and result.breakout_direction != expected_direction:
            errors.append(
                f"{pattern_key}: {fixture_id} expected_breakout_direction={expected_direction} got {result.breakout_direction}"
            )
    return errors


def validate_official_pattern(
    pattern_key: str,
    registry: Optional[Mapping[str, Any]] = None,
    lineage: Optional[Mapping[str, Any]] = None,
) -> List[str]:
    registry = registry or load_core_registry()
    lineage = lineage or load_taxonomy_lineage()
    patterns = registry.get("patterns")
    if not isinstance(patterns, dict) or pattern_key not in patterns:
        return [f"{pattern_key}: missing from registry"]
    pattern = patterns[pattern_key]
    if not isinstance(pattern, dict):
        return [f"{pattern_key}: registry pattern must be object"]

    errors: List[str] = []
    errors.extend(validate_pattern_provenance(pattern_key, pattern))
    errors.extend(validate_lineage(pattern_key, pattern, lineage))
    coverage = build_rule_coverage(pattern)
    errors.extend(_coverage_errors(pattern_key, coverage))
    errors.extend(_detector_rule_errors(pattern_key, pattern))

    fixtures = pattern.get("golden_fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        errors.append(f"{pattern_key}: golden_fixtures required before official scanner activation")
    else:
        errors.extend(_fixture_errors(pattern_key, pattern))
    if pattern.get("official_candidate") is not True:
        errors.append(f"{pattern_key}: official_candidate must be true before activation")
    else:
        from .source_alignment import verify_pattern_source_alignment

        alignment = verify_pattern_source_alignment(pattern_key, registry=registry)
        if not alignment.get("aligned"):
            errors.extend(str(err) for err in alignment.get("errors", []))
    return errors


@dataclass(frozen=True)
class CompiledPattern:
    pattern_key: str
    scanner_pattern_key: str
    spec_hash: str
    source_chapters: Tuple[int, ...]
    coverage: Tuple[RuleCoverageRow, ...]
    official_ready: bool

    def result_metadata(self) -> Dict[str, Any]:
        return {
            "scanner_version": "v2_contract_first",
            "pattern_key": self.pattern_key,
            "scanner_pattern_key": self.scanner_pattern_key,
            "spec_hash": self.spec_hash,
            "source_chapters": list(self.source_chapters),
            "coverage": [row.to_dict() for row in self.coverage],
            "official_ready": self.official_ready,
        }


class ScannerV2Engine:
    """Rule-driven V2 compiler gate.

    The current class compiles validated pattern specs into traceable metadata.
    Actual signal generation should be added only after a pattern has golden
    fixtures and module-specific rule coverage.
    """

    def __init__(
        self,
        registry: Optional[Mapping[str, Any]] = None,
        lineage: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.registry = copy.deepcopy(dict(registry or load_core_registry()))
        self.lineage = copy.deepcopy(dict(lineage or load_taxonomy_lineage()))

    def pattern(self, pattern_key: str) -> Dict[str, Any]:
        patterns = self.registry.get("patterns")
        if not isinstance(patterns, dict):
            raise ContractError("registry must contain patterns object")
        pattern = patterns.get(pattern_key)
        if not isinstance(pattern, dict):
            raise ContractError(f"{pattern_key}: missing pattern spec")
        return pattern

    def compile_pattern(self, pattern_key: str, *, require_official: bool = False) -> CompiledPattern:
        pattern = self.pattern(pattern_key)
        errors = validate_pattern_provenance(pattern_key, pattern)
        errors.extend(validate_lineage(pattern_key, pattern, self.lineage))
        coverage = build_rule_coverage(pattern)
        errors.extend(_coverage_errors(pattern_key, coverage))
        if errors:
            raise ContractError("; ".join(errors))

        official_errors = validate_official_pattern(pattern_key, self.registry, self.lineage)
        official_ready = not official_errors
        if require_official and official_errors:
            raise ContractError("; ".join(official_errors))

        item = _lineage_for(self.lineage, pattern_key)
        chapters = tuple(int(x) for x in item.get("bulkowski_chapters", []) if isinstance(x, int))
        return CompiledPattern(
            pattern_key=pattern_key,
            scanner_pattern_key=str(item["scanner_pattern_key"]),
            spec_hash=canonical_spec_hash(pattern),
            source_chapters=chapters,
            coverage=tuple(coverage),
            official_ready=official_ready,
        )

    def compile_core_patterns(self, *, require_official: bool = False) -> Dict[str, CompiledPattern]:
        return {
            key: self.compile_pattern(key, require_official=require_official)
            for key in CORE_PATTERN_KEYS
        }
