"""Audit Wedge Family source grounding before final publication."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


CORE_PATTERNS = Path("scanner/v2/core_patterns.json")
WEDGE_FILES = {
    "wedges_falling": Path("scanner/v2/falling_wedges.py"),
    "wedges_rising": Path("scanner/v2/rising_wedges.py"),
}
REQUIRED_RULES = {
    "wedges_falling": {
        "fw.shape.downward_converging",
        "fw.touch_count.minimum",
        "fw.height.start_gap",
        "fw.target.source_measure_up",
        "fw.volume.contracts",
        "fw.breakout.up_primary",
        "fw.throwback.pullback_30d",
        "fw.failure.5pct",
    },
    "wedges_rising": {
        "rw.shape.upward_converging",
        "rw.touch_count.minimum",
        "rw.height.start_gap",
        "rw.target.source_measure_down",
        "rw.volume.contracts",
        "rw.breakout.down_primary",
        "rw.throwback.pullback_30d",
        "rw.failure.5pct",
    },
}


def _read_json(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, Mapping) else {}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def audit_wedge_family_source_grounding(*, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    registry = _read_json(CORE_PATTERNS)
    patterns = registry.get("patterns") if isinstance(registry.get("patterns"), Mapping) else {}
    results = []
    failures = []
    for pattern_id, required in REQUIRED_RULES.items():
        pattern = patterns.get(pattern_id) if isinstance(patterns.get(pattern_id), Mapping) else {}
        rule_ids = {str(rule.get("rule_id")) for rule in pattern.get("rules") or [] if isinstance(rule, Mapping)}
        code = _read(WEDGE_FILES[pattern_id])
        missing_rules = sorted(required - rule_ids)
        code_checks = {
            "has_close_breakout": "close" in code and "breakout" in code,
            "has_height_projection": "target_price" in code and "height_abs" in code,
            "has_publication_tier_without_outcome_leakage": "post_breakout_quality_label" in code and "publication_quality_tier" in code,
        }
        if missing_rules:
            failures.append({"pattern_id": pattern_id, "check": "required_source_rules", "detail": missing_rules})
        if not all(code_checks.values()):
            failures.append({"pattern_id": pattern_id, "check": "implementation_markers", "detail": code_checks})
        results.append(
            {
                "pattern_id": pattern_id,
                "rule_count": len(rule_ids),
                "required_rule_count": len(required),
                "missing_rules": missing_rules,
                "code_checks": code_checks,
            }
        )
    payload = {
        "audit_id": "wedge_family_source_grounding_audit_v1",
        "status": "PASS" if not failures else "FAIL",
        "results": results,
        "failures": failures,
    }
    (out_dir / "wedge_family_source_grounding_audit.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    (out_dir / "wedge_family_source_grounding_audit.md").write_text(
        "\n".join(
            [
                "# Wedge Family source-grounding audit",
                "",
                f"**Status:** {payload['status']}",
                "",
                *[
                    f"- {item['pattern_id']}: {item['rule_count']} source rules, missing={item['missing_rules'] or 'none'}"
                    for item in results
                ],
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Wedge Family source grounding.")
    parser.add_argument("--out-dir", default="artifacts/scanner_v2/wedge_family_source_grounding")
    args = parser.parse_args()
    payload = audit_wedge_family_source_grounding(out_dir=Path(args.out_dir))
    print(json.dumps({"status": payload["status"], "failures": payload["failures"]}, ensure_ascii=False, indent=2))
    if payload["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
