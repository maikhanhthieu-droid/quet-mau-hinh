"""Audit Scanner V2 provenance, lineage, and official-readiness gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

try:
    from scanner.v2 import CORE_PATTERN_KEYS, ScannerV2Engine, validate_official_pattern
except Exception:  # pragma: no cover
    from v2 import CORE_PATTERN_KEYS, ScannerV2Engine, validate_official_pattern  # type: ignore


def audit() -> Dict[str, Any]:
    engine = ScannerV2Engine()
    compiled = engine.compile_core_patterns(require_official=False)
    rows: List[Dict[str, Any]] = []
    for key in CORE_PATTERN_KEYS:
        official_errors = validate_official_pattern(key, engine.registry, engine.lineage)
        rows.append(
            {
                "pattern_key": key,
                "compiled": key in compiled,
                "official_ready": not official_errors,
                "official_blockers": official_errors,
                "result_metadata": compiled[key].result_metadata(),
            }
        )
    return {
        "scanner_version": "v2_contract_first",
        "core_patterns": list(CORE_PATTERN_KEYS),
        "patterns": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None, help="Optional JSON output path")
    args = parser.parse_args()

    result = audit()
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
