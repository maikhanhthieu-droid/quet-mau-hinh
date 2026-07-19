"""Validate a Scanner V2 monograph payload against the P1-P5 release gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.v2.release_gate import enrich_payload_with_p1_p5_status, evaluate_release_gate


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a Scanner V2 monograph payload against the P1-P5 standard.")
    parser.add_argument("payload", help="Path to chapter_payload.json")
    parser.add_argument("--out", default=None, help="Optional JSON report path")
    parser.add_argument("--enriched-out", default=None, help="Optional enriched payload output path")
    parser.add_argument("--fail-on-hold", action="store_true", help="Exit non-zero when release status is Hold")
    args = parser.parse_args()

    payload_path = Path(args.payload)
    payload = _read_json(payload_path)
    report = evaluate_release_gate(payload)

    if args.out:
        _write_json(Path(args.out), report)
    if args.enriched_out:
        _write_json(Path(args.enriched_out), enrich_payload_with_p1_p5_status(payload))

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.fail_on_hold and report.get("publish_status") == "Hold":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
