"""Scanner matrix contracts and Flag Family reference adapters.

The matrix layer keeps pattern detection independent while forcing every
scanner to emit the same event contract. Flag Family is the reference family:
other patterns should match this output shape, not reuse flag geometry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from .contracts import CompiledPattern, ContractError, ScannerV2Engine


MATRIX_EVENT_CONTRACT_VERSION = "scanner_matrix_event_v1"

MATRIX_EVENT_COLUMNS: tuple[str, ...] = (
    "event_id",
    "pattern_id",
    "pattern_name",
    "scanner_pattern_key",
    "scanner_version",
    "scanner_branch_id",
    "scanner_branch_lane",
    "spec_hash",
    "source_chapters",
    "symbol",
    "market_group",
    "formation_start",
    "formation_end",
    "confirmation_date",
    "direction",
    "confirmation_price",
    "execution_anchor_price",
    "target_price",
    "target_family",
    "status",
    "setup_score",
    "confirmation_score",
    "followthrough_score",
    "context_score",
    "quality_tier",
    "market_regime",
    "liquidity_bucket",
    "path_quality",
    "data_quality_bucket",
    "invalidation_reasons",
)

REQUIRED_MATRIX_EVENT_COLUMNS: tuple[str, ...] = (
    "event_id",
    "pattern_id",
    "scanner_pattern_key",
    "symbol",
    "formation_start",
    "formation_end",
    "confirmation_date",
    "direction",
    "confirmation_price",
    "target_price",
    "status",
)


@dataclass(frozen=True)
class PatternScannerDefinition:
    pattern_id: str
    pattern_name: str
    scanner_pattern_key: str
    module: str
    role: str
    status: str
    event_contract_version: str = MATRIX_EVENT_CONTRACT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "pattern_name": self.pattern_name,
            "scanner_pattern_key": self.scanner_pattern_key,
            "module": self.module,
            "role": self.role,
            "status": self.status,
            "event_contract_version": self.event_contract_version,
        }


class ScannerMatrixRegistry:
    """Registry of independent pattern scanners that share one output contract."""

    def __init__(self, definitions: Optional[Iterable[PatternScannerDefinition]] = None) -> None:
        self._definitions: dict[str, PatternScannerDefinition] = {}
        for definition in definitions or ():
            self.register(definition)

    def register(self, definition: PatternScannerDefinition) -> None:
        if definition.pattern_id in self._definitions:
            raise ContractError(f"{definition.pattern_id}: duplicate scanner matrix definition")
        if definition.event_contract_version != MATRIX_EVENT_CONTRACT_VERSION:
            raise ContractError(f"{definition.pattern_id}: unsupported event contract version")
        self._definitions[definition.pattern_id] = definition

    def get(self, pattern_id: str) -> PatternScannerDefinition:
        try:
            return self._definitions[pattern_id]
        except KeyError as exc:
            raise ContractError(f"{pattern_id}: scanner is not registered in matrix") from exc

    def active(self) -> list[PatternScannerDefinition]:
        return [definition for definition in self._definitions.values() if definition.status == "active"]

    def manifest(self) -> Dict[str, Any]:
        return {
            "event_contract_version": MATRIX_EVENT_CONTRACT_VERSION,
            "required_columns": list(REQUIRED_MATRIX_EVENT_COLUMNS),
            "columns": list(MATRIX_EVENT_COLUMNS),
            "scanners": [definition.to_dict() for definition in self._definitions.values()],
        }


def default_scanner_matrix(engine: Optional[ScannerV2Engine] = None) -> ScannerMatrixRegistry:
    engine = engine or ScannerV2Engine()
    # Matrix builds should not require PDF source extraction at runtime. The
    # official source-alignment gate is enforced separately by contract tests.
    bull_flag = engine.compile_pattern("bull_flags", require_official=False)
    bear_flag = engine.compile_pattern("bear_flags", require_official=False)
    ascending_triangle = engine.compile_pattern("triangles_ascending", require_official=False)
    descending_triangle = engine.compile_pattern("triangles_descending", require_official=False)
    symmetrical_triangle = engine.compile_pattern("triangles_symmetrical", require_official=False)
    falling_wedge = engine.compile_pattern("wedges_falling", require_official=False)
    rising_wedge = engine.compile_pattern("wedges_rising", require_official=False)
    return ScannerMatrixRegistry(
        [
            PatternScannerDefinition(
                pattern_id="bull_flags",
                pattern_name="Cờ tăng",
                scanner_pattern_key=bull_flag.scanner_pattern_key,
                module="scanner.v2.bull_flags",
                role="reference_scanner",
                status="active",
            ),
            PatternScannerDefinition(
                pattern_id="bear_flags",
                pattern_name="Cờ giảm",
                scanner_pattern_key=bear_flag.scanner_pattern_key,
                module="scanner.v2.bear_flags_monograph",
                role="reference_scanner",
                status="active",
            ),
            PatternScannerDefinition(
                pattern_id="triangles_ascending",
                pattern_name="Tam giác tăng",
                scanner_pattern_key=ascending_triangle.scanner_pattern_key,
                module="scanner.v2.ascending_triangles",
                role="chapter_scanner",
                status="active",
            ),
            PatternScannerDefinition(
                pattern_id="triangles_descending",
                pattern_name="Tam giác giảm",
                scanner_pattern_key=descending_triangle.scanner_pattern_key,
                module="scanner.v2.descending_triangles",
                role="chapter_scanner",
                status="active",
            ),
            PatternScannerDefinition(
                pattern_id="triangles_symmetrical",
                pattern_name="Tam giác cân",
                scanner_pattern_key=symmetrical_triangle.scanner_pattern_key,
                module="scanner.v2.symmetrical_triangles",
                role="chapter_scanner",
                status="active",
            ),
            PatternScannerDefinition(
                pattern_id="wedges_falling",
                pattern_name="Nêm giảm",
                scanner_pattern_key=falling_wedge.scanner_pattern_key,
                module="scanner.v2.falling_wedges",
                role="chapter_scanner",
                status="active",
            ),
            PatternScannerDefinition(
                pattern_id="wedges_rising",
                pattern_name="Nêm tăng",
                scanner_pattern_key=rising_wedge.scanner_pattern_key,
                module="scanner.v2.rising_wedges",
                role="chapter_scanner",
                status="active",
            ),
        ]
    )


def _clean(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    if pd.isna(value):
        return None
    return value


def _as_float(value: Any, default: float = 0.0) -> float:
    value = _clean(value)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clip_score(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)


def _confirmation_score(row: Mapping[str, Any]) -> float:
    """Transparent confirmation score from fields available in Bull Flag events."""

    score = 50.0
    close_location = _as_float(row.get("breakout_close_location"), 0.5)
    body_to_range = _as_float(row.get("breakout_body_to_range"), 0.0)
    volume_ratio = _as_float(row.get("breakout_volume_ratio_20"), 1.0)
    gap_pct = abs(_as_float(row.get("breakout_gap_pct"), 0.0))
    score += (close_location - 0.5) * 40.0
    score += min(20.0, max(0.0, body_to_range * 20.0))
    score += min(15.0, max(-10.0, (volume_ratio - 1.0) * 8.0))
    if gap_pct > 3.0:
        score -= min(15.0, (gap_pct - 3.0) * 2.0)
    return _clip_score(score)


def _followthrough_score(row: Mapping[str, Any]) -> float:
    mfe = _as_float(row.get("mfe_pct"), 0.0)
    mae = _as_float(row.get("mae_pct"), 0.0)
    target_hit = bool(row.get("target_hit"))
    target_first = bool(row.get("target_first_before_adverse_5pct"))
    failure = bool(row.get("failure_5pct"))
    ratio = mfe / max(mae, 1.0)
    score = 45.0 + min(25.0, ratio * 10.0)
    if target_hit:
        score += 12.0
    if target_first:
        score += 13.0
    if failure:
        score -= 25.0
    return _clip_score(score)


def _quality_tier(setup: float, confirmation: float, followthrough: float, data_quality: str) -> str:
    if data_quality in {"impaired", "short_path", "zero_and_stale"}:
        return "data_limited"
    composite = setup * 0.45 + confirmation * 0.25 + followthrough * 0.30
    if composite >= 80:
        return "premium"
    if composite >= 65:
        return "standard"
    if composite >= 50:
        return "watchlist"
    return "weak"


def _flag_target_family() -> str:
    return json.dumps(
        {
            "base": 0.46,
            "rounded_base": 0.50,
            "stretch": 0.75,
            "legacy_full": 1.00,
            "unit": "pole_height",
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _source_chapters(compiled: CompiledPattern) -> str:
    return json.dumps(list(compiled.source_chapters), ensure_ascii=True)


def normalize_bull_flag_events(
    events: pd.DataFrame,
    *,
    engine: Optional[ScannerV2Engine] = None,
    pattern_id: str = "bull_flags",
    pattern_name: str = "Cờ tăng",
) -> pd.DataFrame:
    """Normalize Flag Family detector output into the scanner matrix event schema."""

    engine = engine or ScannerV2Engine()
    compiled = engine.compile_pattern(pattern_id, require_official=False)
    rows: list[dict[str, Any]] = []
    target_family = _flag_target_family()
    source_chapters = _source_chapters(compiled)

    for _, row in events.iterrows():
        raw = row.to_dict()
        setup = _clip_score(_as_float(raw.get("pattern_quality_score"), 0.0))
        confirmation = _confirmation_score(raw)
        followthrough = _followthrough_score(raw)
        data_quality = str(_clean(raw.get("path_quality_bucket")) or _clean(raw.get("tradability_quality_bucket")) or "unknown")
        reasons: list[str] = []
        if bool(raw.get("corp_action_near_breakout_flag")):
            reasons.append("corp_action_near_confirmation")
        if data_quality not in {"clean", "usable", "unknown"}:
            reasons.append(f"data_quality:{data_quality}")
        if bool(raw.get("failure_5pct")):
            reasons.append("failure_5pct")

        rows.append(
            {
                "event_id": str(raw.get("detection_id") or f"{pattern_id}:{raw.get('symbol')}:{raw.get('breakout_date')}"),
                "pattern_id": pattern_id,
                "pattern_name": pattern_name,
                "scanner_pattern_key": compiled.scanner_pattern_key,
                "scanner_version": "scanner_matrix_v1",
                "scanner_branch_id": _clean(raw.get("bear_branch_id")) or _clean(raw.get("scanner_branch_id")),
                "scanner_branch_lane": _clean(raw.get("bear_branch_lane")) or _clean(raw.get("scanner_branch_lane")),
                "spec_hash": compiled.spec_hash,
                "source_chapters": source_chapters,
                "symbol": str(raw.get("symbol")),
                "market_group": _clean(raw.get("market_group")),
                "formation_start": _clean(raw.get("formation_start_date")),
                "formation_end": _clean(raw.get("formation_end_date")),
                "confirmation_date": _clean(raw.get("breakout_date")),
                "direction": str(raw.get("breakout_direction") or "up"),
                "confirmation_price": _clean(raw.get("breakout_price")),
                "execution_anchor_price": _clean(raw.get("b_exec_price")),
                "target_price": _clean(raw.get("target_price")),
                "target_family": target_family,
                "status": "confirmed",
                "setup_score": setup,
                "confirmation_score": confirmation,
                "followthrough_score": followthrough,
                "context_score": _clip_score(_as_float(raw.get("tradability_quality_score"), 50.0)),
                "quality_tier": _quality_tier(setup, confirmation, followthrough, data_quality),
                "market_regime": _clean(raw.get("market_regime")),
                "liquidity_bucket": _clean(raw.get("liquidity_bucket")),
                "path_quality": _clean(raw.get("path_quality_bucket")),
                "data_quality_bucket": _clean(raw.get("tradability_quality_bucket")),
                "invalidation_reasons": json.dumps(reasons, ensure_ascii=False),
            }
        )

    normalized = pd.DataFrame(rows)
    for column in MATRIX_EVENT_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = None
    return normalized.loc[:, MATRIX_EVENT_COLUMNS].copy()


def validate_matrix_events(events: pd.DataFrame, registry: ScannerMatrixRegistry) -> list[str]:
    errors: list[str] = []
    missing = [column for column in MATRIX_EVENT_COLUMNS if column not in events.columns]
    if missing:
        errors.append(f"missing columns: {', '.join(missing)}")
        return errors

    for column in REQUIRED_MATRIX_EVENT_COLUMNS:
        if events[column].isna().any() or (events[column].astype(str).str.len() == 0).any():
            errors.append(f"{column}: contains empty values")

    registered = {definition.pattern_id: definition for definition in registry.active()}
    unknown_patterns = set(events["pattern_id"].dropna().astype(str)) - set(registered)
    if unknown_patterns:
        errors.append(f"unregistered active pattern ids: {sorted(unknown_patterns)}")

    for pattern_id, group in events.groupby("pattern_id"):
        if pattern_id not in registered:
            continue
        expected_key = registered[str(pattern_id)].scanner_pattern_key
        keys = set(group["scanner_pattern_key"].dropna().astype(str))
        if keys != {expected_key}:
            errors.append(f"{pattern_id}: scanner_pattern_key mismatch {sorted(keys)} expected {expected_key}")

    allowed_status = {"candidate", "confirmed", "invalidated", "post_confirmation"}
    bad_status = set(events["status"].dropna().astype(str)) - allowed_status
    if bad_status:
        errors.append(f"unsupported event status: {sorted(bad_status)}")

    for score_col in ("setup_score", "confirmation_score", "followthrough_score", "context_score"):
        scores = pd.to_numeric(events[score_col], errors="coerce")
        if scores.isna().any() or ((scores < 0) | (scores > 100)).any():
            errors.append(f"{score_col}: must be numeric 0..100")

    return errors


def build_bull_flag_matrix_artifacts(
    events_path: Path,
    out_dir: Path,
    *,
    engine: Optional[ScannerV2Engine] = None,
) -> Dict[str, Path]:
    engine = engine or ScannerV2Engine()
    registry = default_scanner_matrix(engine)
    events = pd.read_csv(events_path)
    normalized = normalize_bull_flag_events(events, engine=engine)
    errors = validate_matrix_events(normalized, registry)
    if errors:
        raise ContractError("; ".join(errors))

    out_dir.mkdir(parents=True, exist_ok=True)
    events_out = out_dir / "scanner_matrix_events.csv"
    manifest_out = out_dir / "scanner_matrix_manifest.json"
    normalized.to_csv(events_out, index=False)
    manifest_out.write_text(json.dumps(registry.manifest(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"events": events_out, "manifest": manifest_out}


def build_flag_family_matrix_artifacts(
    event_sources: Mapping[str, Path],
    out_dir: Path,
    *,
    engine: Optional[ScannerV2Engine] = None,
) -> Dict[str, Path]:
    engine = engine or ScannerV2Engine()
    registry = default_scanner_matrix(engine)
    frames: list[pd.DataFrame] = []
    names = {"bull_flags": "Cờ tăng", "bear_flags": "Cờ giảm"}
    for pattern_id, events_path in event_sources.items():
        events = pd.read_csv(events_path)
        frames.append(
            normalize_bull_flag_events(
                events,
                engine=engine,
                pattern_id=pattern_id,
                pattern_name=names.get(pattern_id, pattern_id),
            )
        )
    normalized = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=MATRIX_EVENT_COLUMNS)
    errors = validate_matrix_events(normalized, registry)
    if errors:
        raise ContractError("; ".join(errors))

    out_dir.mkdir(parents=True, exist_ok=True)
    events_out = out_dir / "scanner_matrix_events.csv"
    manifest_out = out_dir / "scanner_matrix_manifest.json"
    normalized.to_csv(events_out, index=False)
    manifest_out.write_text(json.dumps(registry.manifest(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"events": events_out, "manifest": manifest_out}
