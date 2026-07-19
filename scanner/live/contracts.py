"""Runtime validation for live candidate payloads."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA = ROOT / "schemas" / "scanner_v2" / "eod_candidate.schema.json"


class CandidateContractError(ValueError):
    """Raised when a live candidate violates the causal output contract."""


def validate_candidates(
    candidates: Iterable[Mapping[str, Any]],
    *,
    schema_path: Path = DEFAULT_SCHEMA,
) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for index, candidate in enumerate(candidates):
        errors = sorted(
            validator.iter_errors(dict(candidate)), key=lambda item: list(item.path)
        )
        if errors:
            detail = "; ".join(error.message for error in errors[:5])
            raise CandidateContractError(f"Ứng viên #{index} sai contract: {detail}")
