"""
Review `--pattern-set` definitions and metadata consistency.

This script does not scan OHLCV data. It inspects which scanners are loaded for
each pattern-set, and validates the mapping to:
  - digitized spec keys (when available)
  - canonical keys (for grouping chapter variants)
  - Bulkowski chapter/name metadata (where applicable)

Examples:
  python3 scanner/review_pattern_sets.py
  python3 scanner/review_pattern_sets.py --out-md scan_results/pattern_set_review.md
  python3 scanner/review_pattern_sets.py --pattern-sets digitized,bulkowski_53_strict
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional

# Allow running as a script (imports are local-module style in this folder)
SCANNER_DIR = os.path.dirname(__file__)
sys.path.insert(0, SCANNER_DIR)

from digitized_pattern_engine import DigitizedPatternLibrary  # noqa: E402
from pattern_scanner import PatternScanner  # noqa: E402
from pattern_set_metadata import build_pattern_metadata  # noqa: E402


KNOWN_PATTERN_SETS: List[str] = [
    "digitized",
    "bulkowski_53",
    "bulkowski_53_strict",
    "bulkowski_strict_ohlcv",
    "bulkowski_49_strict_ohlcv",  # deprecated alias
    "event_ohlcv",
    "bulkowski_55_ohlcv",
]

DEFAULT_PATTERN_SETS: List[str] = [
    "digitized",
    "bulkowski_53",
    "bulkowski_53_strict",
    "bulkowski_strict_ohlcv",
    "event_ohlcv",
    "bulkowski_55_ohlcv",
]


def _parse_csv_list(s: Optional[str]) -> List[str]:
    if not s:
        return []
    return [x.strip() for x in str(s).split(",") if x.strip()]


def _has_geom(meta: Dict[str, Any]) -> bool:
    return any(
        meta.get(k) is not None
        for k in ("width_min_bars", "width_max_bars", "height_min_pct", "height_max_pct")
    )


def _md_bool(v: Any) -> str:
    return "yes" if bool(v) else ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pattern-sets",
        default=",".join(DEFAULT_PATTERN_SETS),
        help=f"Comma-separated list of pattern sets (default: {','.join(DEFAULT_PATTERN_SETS)}).",
    )
    parser.add_argument("--out-md", default=None, help="Write Markdown review to this path.")
    args = parser.parse_args()

    pattern_sets = _parse_csv_list(args.pattern_sets) or list(KNOWN_PATTERN_SETS)
    unknown = [ps for ps in pattern_sets if ps not in KNOWN_PATTERN_SETS]
    if unknown:
        raise SystemExit(f"Unknown pattern sets: {unknown}. Known: {KNOWN_PATTERN_SETS}")

    lib = DigitizedPatternLibrary()
    spec_keys = set(lib.list_keys())

    lines: List[str] = []
    lines.append("# Pattern-set Review")
    lines.append("")
    lines.append("This report inspects scanner definitions and metadata mapping (no OHLCV scan).")
    lines.append("")
    lines.append(f"- digitized_specs: `{len(spec_keys)}` keys")
    lines.append("")

    for ps in pattern_sets:
        scanner = PatternScanner(pattern_set=ps)
        keys = sorted(scanner.scanners.keys())
        meta_payload = build_pattern_metadata(pattern_set=ps, scanners=scanner.scanners, patterns=keys)
        meta_map = meta_payload.get("patterns", {}) if isinstance(meta_payload, dict) else {}
        if not isinstance(meta_map, dict):
            meta_map = {}

        canonical_map: Dict[str, List[str]] = {}
        spec_map: Dict[str, List[str]] = {}

        proxy = 0
        with_spec_key = 0
        with_spec_file = 0
        missing_spec_file = 0
        with_geom = 0
        missing_chapter = 0
        for k in keys:
            m = meta_map.get(str(k), {})
            if not isinstance(m, dict):
                m = {}

            if bool(m.get("proxy")):
                proxy += 1

            sk = m.get("spec_key")
            if sk is not None:
                with_spec_key += 1
                if str(sk) in spec_keys:
                    with_spec_file += 1
                else:
                    missing_spec_file += 1

            ck = m.get("canonical_key")
            if ck:
                canonical_map.setdefault(str(ck), []).append(str(k))

            if sk:
                spec_map.setdefault(str(sk), []).append(str(k))

            if _has_geom(m):
                with_geom += 1

            if m.get("bulkowski_part") is not None and m.get("bulkowski_chapter") is None:
                missing_chapter += 1

        multi_canonical = {k: v for k, v in canonical_map.items() if len(v) > 1}
        multi_spec = {k: v for k, v in spec_map.items() if len(v) > 1}

        lines.append(f"## `{ps}`")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|---|---:|")
        lines.append(f"| patterns | {len(keys)} |")
        lines.append(f"| unique canonical_key | {len(canonical_map)} |")
        lines.append(f"| proxy (spec_key missing) | {proxy} |")
        lines.append(f"| spec_key present | {with_spec_key} |")
        lines.append(f"| spec_key exists in digitized_specs | {with_spec_file} |")
        if missing_spec_file:
            lines.append(f"| spec_key missing in digitized_specs | {missing_spec_file} |")
        lines.append(f"| geometry constraints present | {with_geom} |")
        if missing_chapter:
            lines.append(f"| missing Bulkowski chapter (metadata) | {missing_chapter} |")
        lines.append("")

        if missing_spec_file:
            lines.append("**Spec-key errors (missing digitized spec file):**")
            lines.append("")
            for k in keys:
                m = meta_map.get(str(k), {})
                if not isinstance(m, dict):
                    continue
                sk = m.get("spec_key")
                if sk is not None and str(sk) not in spec_keys:
                    lines.append(f"- `{k}` → spec_key=`{sk}` (missing `*_digitized.json`)")
            lines.append("")

        if multi_canonical:
            lines.append("**Canonical groups (chapter variants):**")
            lines.append("")
            for ck in sorted(multi_canonical):
                members = ", ".join(f"`{x}`" for x in sorted(multi_canonical[ck]))
                lines.append(f"- `{ck}`: {members}")
            lines.append("")

        if proxy:
            lines.append("**Proxy patterns (no digitized spec anchor):**")
            lines.append("")
            for k in keys:
                m = meta_map.get(str(k), {})
                if isinstance(m, dict) and bool(m.get("proxy")):
                    chap = m.get("bulkowski_chapter")
                    chap_s = str(int(chap)) if isinstance(chap, int) else ""
                    name = str(m.get("bulkowski_name") or "")
                    tail = f" (chap {chap_s}: {name})" if chap_s or name else ""
                    lines.append(f"- `{k}`{tail}")
            lines.append("")

        # Full mapping table
        lines.append("**Pattern mapping:**")
        lines.append("")
        lines.append("| pattern_key | canonical_key | spec_key | kind | part | chap | variant | proxy | geom | bulkowski_name |")
        lines.append("|---|---|---|---|---:|---:|---|---|---|---|")
        for k in keys:
            m = meta_map.get(str(k), {})
            if not isinstance(m, dict):
                m = {}
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`{k}`",
                        f"`{m.get('canonical_key')}`" if m.get("canonical_key") else "",
                        f"`{m.get('spec_key')}`" if m.get("spec_key") else "",
                        str(m.get("kind") or ""),
                        str(m.get("bulkowski_part") or ""),
                        str(m.get("bulkowski_chapter") or ""),
                        str(m.get("variant") or ""),
                        _md_bool(m.get("proxy")),
                        _md_bool(_has_geom(m)),
                        str(m.get("bulkowski_name") or ""),
                    ]
                )
                + " |"
            )
        lines.append("")

    md = "\n".join(lines)

    if args.out_md:
        out_md = os.path.abspath(args.out_md)
        os.makedirs(os.path.dirname(out_md), exist_ok=True)
        with open(out_md, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"Wrote Markdown: {out_md}")
        return

    print(md)


if __name__ == "__main__":
    main()
