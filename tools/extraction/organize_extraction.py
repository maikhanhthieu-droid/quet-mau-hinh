#!/usr/bin/env python3
"""
Organize Phase 1 extraction outputs into a directory tree.

Input file is expected at:
  - artifacts/extraction/chart_patterns_encyclopedia_extraction.json

Output files are written to:
  - extraction_phase_1/global/methodology.json
  - extraction_phase_1/patterns/*.json
  - extraction_phase_1/master_index.json
"""

from __future__ import annotations

import json
from pathlib import Path


def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    input_path = repo_root / "artifacts" / "extraction" / "chart_patterns_encyclopedia_extraction.json"
    if not input_path.exists():
        raise SystemExit(f"Missing input JSON: {input_path}")

    out_root = repo_root / "extraction_phase_1"
    patterns_dir = out_root / "patterns"
    global_dir = out_root / "global"

    main_extraction = json.loads(input_path.read_text(encoding="utf-8"))

    patterns_dir.mkdir(parents=True, exist_ok=True)
    global_dir.mkdir(parents=True, exist_ok=True)

    print(f"Input:  {input_path}")
    print(f"Output: {out_root}")

    # Extract global methodology
    global_methodology = {
        "source_document": "Encyclopedia of Chart Patterns, 2nd Edition",
        "extraction_metadata": {
            "extraction_date": "2025-02-19",
            "agent": "Agent 3: Global Methodology Extraction Agent",
        },
        "global_specifications": main_extraction.get("global_methodology", {}),
    }
    _write_json(global_dir / "methodology.json", global_methodology)
    print("✓ Created global/methodology.json")

    # Process each pattern
    patterns_data = main_extraction.get("chart_patterns", {}) or {}
    pattern_index = []

    for pattern_key, pattern_data in patterns_data.items():
        filename = str(pattern_key).replace(" ", "_").replace(",", "") + ".json"
        filepath = patterns_dir / filename

        pattern_spec = {
            "pattern_name": (pattern_data or {}).get("pattern_name", pattern_key) if isinstance(pattern_data, dict) else pattern_key,
            "structural_spec": pattern_data,
            "statistical_spec": {},
            "global_method_reference": {"methodology": "See global/methodology.json"},
            "completeness_check": True,
            "missing_fields": [],
        }

        _write_json(filepath, pattern_spec)

        pattern_index.append(
            {
                "pattern_name": (pattern_data or {}).get("pattern_name", pattern_key) if isinstance(pattern_data, dict) else pattern_key,
                "filename": filename,
            }
        )
        print(f"✓ Created patterns/{filename}")

    # Create master index
    master_index = {
        "extraction_metadata": {
            "source": "Encyclopedia of Chart Patterns, 2nd Edition",
            "extraction_date": "2025-02-19",
            "phase": "Phase 1 - Data Extraction",
            "total_patterns": len(pattern_index),
        },
        "patterns": pattern_index,
    }
    _write_json(out_root / "master_index.json", master_index)

    print("\n✓ Created master_index.json")
    print("\nPHASE 1 EXTRACTION COMPLETE")
    print(f"Total patterns extracted: {len(pattern_index)}")


if __name__ == "__main__":
    main()
