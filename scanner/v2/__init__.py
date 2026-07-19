"""Scanner V2 contract-first package."""

from .contracts import (
    CORE_PATTERN_KEYS,
    ContractError,
    ScannerV2Engine,
    build_rule_coverage,
    canonical_spec_hash,
    load_core_registry,
    load_taxonomy_lineage,
    validate_official_pattern,
    validate_pattern_provenance,
)
from .bull_flags import BearFlagV2Detector, BullFlagV2Detector, run_bear_flags_fixture, run_bull_flags_fixture
from .source_alignment import audit_source_alignment, verify_pattern_source_alignment
from .release_gate import enrich_payload_with_p1_p5_status, evaluate_release_gate
from .matrix import (
    MATRIX_EVENT_COLUMNS,
    MATRIX_EVENT_CONTRACT_VERSION,
    PatternScannerDefinition,
    ScannerMatrixRegistry,
    build_bull_flag_matrix_artifacts,
    build_flag_family_matrix_artifacts,
    default_scanner_matrix,
    normalize_bull_flag_events,
    validate_matrix_events,
)

__all__ = [
    "BearFlagV2Detector",
    "BullFlagV2Detector",
    "CORE_PATTERN_KEYS",
    "ContractError",
    "MATRIX_EVENT_COLUMNS",
    "MATRIX_EVENT_CONTRACT_VERSION",
    "PatternScannerDefinition",
    "ScannerV2Engine",
    "ScannerMatrixRegistry",
    "build_rule_coverage",
    "build_bull_flag_matrix_artifacts",
    "build_flag_family_matrix_artifacts",
    "canonical_spec_hash",
    "default_scanner_matrix",
    "load_core_registry",
    "load_taxonomy_lineage",
    "validate_official_pattern",
    "validate_pattern_provenance",
    "audit_source_alignment",
    "enrich_payload_with_p1_p5_status",
    "evaluate_release_gate",
    "normalize_bull_flag_events",
    "run_bear_flags_fixture",
    "run_bull_flags_fixture",
    "validate_matrix_events",
    "verify_pattern_source_alignment",
]
