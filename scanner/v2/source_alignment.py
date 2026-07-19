"""Source-document alignment checks for Scanner V2 provenance."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .contracts import CORE_PATTERN_KEYS, CORE_REGISTRY_PATH, load_core_registry


def normalize_source_text(text: str) -> str:
    text = str(text or "").lower()
    text = text.replace("’", "'").replace("‘", "'")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def source_pdf_path(registry: Mapping[str, Any], repo_root: Optional[Path] = None) -> Path:
    root = repo_root or _repo_root()
    ref = ((registry.get("source_document") or {}).get("local_reference")) if isinstance(registry, dict) else None
    if not ref:
        raise FileNotFoundError("registry.source_document.local_reference is required")
    return (root / str(ref)).resolve()


@lru_cache(maxsize=128)
def _extract_pdf_page_text(pdf_path: str, page_1_based: int) -> str:
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    index = int(page_1_based) - 1
    if index < 0 or index >= len(reader.pages):
        raise IndexError(f"PDF page {page_1_based} outside 1..{len(reader.pages)}")
    return reader.pages[index].extract_text() or ""


def verify_rule_source_alignment(
    rule: Mapping[str, Any],
    *,
    pdf_path: Path,
) -> Dict[str, Any]:
    rule_id = str(rule.get("rule_id") or "<missing_rule_id>")
    page = rule.get("source_pdf_page")
    excerpt = str(rule.get("evidence_excerpt") or "").strip()
    out: Dict[str, Any] = {
        "rule_id": rule_id,
        "source_pdf_page": page,
        "evidence_excerpt": excerpt,
        "aligned": False,
        "reason": "",
    }
    if not isinstance(page, int) or page <= 0:
        out["reason"] = "missing_source_pdf_page"
        return out
    if not excerpt:
        out["reason"] = "missing_evidence_excerpt"
        return out

    try:
        page_text = _extract_pdf_page_text(str(pdf_path), page)
    except Exception as exc:
        out["reason"] = f"pdf_extract_failed:{exc}"
        return out

    aligned = normalize_source_text(excerpt) in normalize_source_text(page_text)
    out["aligned"] = aligned
    out["reason"] = "found_on_claimed_pdf_page" if aligned else "excerpt_not_found_on_claimed_pdf_page"
    return out


def verify_pattern_source_alignment(
    pattern_key: str,
    *,
    registry: Optional[Mapping[str, Any]] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    registry = registry or load_core_registry()
    patterns = registry.get("patterns")
    if not isinstance(patterns, dict) or pattern_key not in patterns:
        return {
            "pattern_key": pattern_key,
            "aligned": False,
            "rule_checks": [],
            "errors": [f"{pattern_key}: missing pattern registry entry"],
        }
    pattern = patterns[pattern_key]
    if not isinstance(pattern, dict):
        return {
            "pattern_key": pattern_key,
            "aligned": False,
            "rule_checks": [],
            "errors": [f"{pattern_key}: pattern registry entry must be object"],
        }

    pdf = source_pdf_path(registry, repo_root=repo_root)
    checks = [
        verify_rule_source_alignment(rule, pdf_path=pdf)
        for rule in pattern.get("rules", [])
        if isinstance(rule, dict)
    ]
    errors = [
        f"{pattern_key}: {row['rule_id']} {row['reason']}"
        for row in checks
        if not row.get("aligned")
    ]
    return {
        "pattern_key": pattern_key,
        "source_pdf": str(pdf),
        "aligned": not errors,
        "rule_checks": checks,
        "errors": errors,
    }


def audit_source_alignment(
    pattern_keys: Sequence[str] = CORE_PATTERN_KEYS,
    *,
    registry: Optional[Mapping[str, Any]] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    registry = registry or load_core_registry()
    patterns = [
        verify_pattern_source_alignment(key, registry=registry, repo_root=repo_root)
        for key in pattern_keys
    ]
    return {
        "registry": str(CORE_REGISTRY_PATH),
        "patterns": patterns,
        "aligned": all(row.get("aligned") for row in patterns),
    }
