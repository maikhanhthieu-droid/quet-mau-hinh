"""Audit Scanner V2 evidence excerpts against the claimed PDF pages."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scanner.v2.source_alignment import audit_source_alignment
except Exception:  # pragma: no cover
    from v2.source_alignment import audit_source_alignment  # type: ignore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pattern", action="append", default=None, help="Pattern key to audit; repeatable")
    parser.add_argument("--out", default=None, help="Optional JSON output path")
    args = parser.parse_args()

    result = audit_source_alignment(tuple(args.pattern) if args.pattern else ("bull_flags", "bear_flags"))
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
