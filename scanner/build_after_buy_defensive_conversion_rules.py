"""Build the After-the-Buy defensive/avoid conversion gate.

This is a safety artifact for the BUY-first Vietnam workflow.  It deliberately
does not create short-selling setups.  It proves that bearish, top, and downside
chapters are converted into avoid/exit/risk filters instead of long-cash BUY
rules.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.after_buy_source_grounding import (  # noqa: E402
    DEFAULT_AFTER_BUY_PDF,
    DEFAULT_FINAL_MANIFEST,
    DEFAULT_OUT_DIR as DEFAULT_AFTER_BUY_OUT_DIR,
    assert_after_buy_buy_rule_allowed,
    build_after_buy_source_map,
)


RULESET_ID = "after_buy_defensive_conversion_rules_v1"
DEFAULT_SOURCE_MAP = DEFAULT_AFTER_BUY_OUT_DIR / "after_buy_source_map.json"
DEFAULT_OUT_DIR = DEFAULT_AFTER_BUY_OUT_DIR / "defensive_conversion"

SOURCE_MAPPED_DEFENSIVE_PATTERNS: tuple[str, ...] = (
    "bear_flags",
    "bear_pennants",
    "double_tops_adam_adam",
    "double_tops_adam_eve",
    "double_tops_eve_adam",
    "double_tops_eve_eve",
    "head_and_shoulders_tops",
    "head_and_shoulders_tops_complex",
    "measured_move_down",
    "rectangle_tops",
    "broadening_tops",
)

EDITION1_POLICY_DEFENSIVE_PATTERNS: tuple[str, ...] = (
    "pipe_tops",
    "triple_tops",
    "bump_and_run_reversal_tops",
    "rounding_tops",
    "horn_tops",
    "diamond_tops",
)


def _read_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _flatten_source_roles(source_map: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    roles: dict[str, dict[str, Any]] = {}
    for chapter in source_map.get("chapters") or []:
        if not isinstance(chapter, Mapping):
            continue
        for role in chapter.get("edition1_pattern_buy_roles") or []:
            if not isinstance(role, Mapping) or not role.get("pattern_id"):
                continue
            roles[str(role["pattern_id"])] = {
                "source_chapter_no": chapter.get("source_chapter_no"),
                "source_title": chapter.get("source_title"),
                "source_local_role": chapter.get("local_role"),
                "pattern_local_role": role.get("local_role"),
                "buy_layer_allowed": bool(role.get("buy_layer_allowed")),
                "buy_scope": role.get("buy_scope"),
                "reason": role.get("reason") or chapter.get("vietnam_use"),
            }
    return roles


def _manifest_pattern_ids(final_manifest: Path) -> set[str]:
    manifest = _read_json(final_manifest)
    chapters = manifest.get("chapters") if isinstance(manifest.get("chapters"), list) else []
    return {str(ch.get("pattern_id")) for ch in chapters if isinstance(ch, Mapping) and ch.get("pattern_id")}


def _defensive_row(pattern_id: str, roles: Mapping[str, Mapping[str, Any]], manifest_ids: set[str]) -> dict[str, Any]:
    source_role = roles.get(pattern_id)
    if source_role:
        try:
            # Defensive rows should be denied by the BUY gate.  If this call
            # succeeds, a critical policy leak exists.
            assert_after_buy_buy_rule_allowed(pattern_id, {"chapters": _roles_to_chapters_proxy(roles)})
            denied_by_buy_gate = False
            denial_message = ""
        except ValueError as exc:
            denied_by_buy_gate = True
            denial_message = str(exc)
        return {
            "pattern_id": pattern_id,
            "source_status": "after_buy_mapped_defensive",
            "manifest_present": pattern_id in manifest_ids,
            "source_chapter_no": source_role.get("source_chapter_no"),
            "source_title": source_role.get("source_title"),
            "local_role": source_role.get("pattern_local_role") or source_role.get("source_local_role"),
            "buy_layer_allowed": source_role.get("buy_layer_allowed"),
            "buy_gate_denies_long_cash_buy": denied_by_buy_gate,
            "denial_message": denial_message,
            "conversion": "avoid_exit_risk_filter",
            "allowed_use": "risk warning, avoid-buy context, exit review, or defensive watchlist",
            "forbidden_use": "long-cash BUY setup or default short-selling setup",
        }
    return {
        "pattern_id": pattern_id,
        "source_status": "edition1_policy_defensive_not_direct_after_buy",
        "manifest_present": pattern_id in manifest_ids,
        "source_chapter_no": None,
        "source_title": None,
        "local_role": "avoid_exit",
        "buy_layer_allowed": False,
        "buy_gate_denies_long_cash_buy": True,
        "denial_message": "Pattern is not mapped to a source-grounded After-the-Buy BUY chapter and is directionally defensive in Vietnam cash equities.",
        "conversion": "avoid_exit_risk_filter",
        "allowed_use": "risk warning, avoid-buy context, exit review, or defensive watchlist",
        "forbidden_use": "long-cash BUY setup or default short-selling setup",
    }


def _roles_to_chapters_proxy(roles: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Make a minimal source-map proxy for the existing BUY gate helper."""
    chapters: dict[tuple[Any, Any], dict[str, Any]] = {}
    for pattern_id, role in roles.items():
        key = (role.get("source_chapter_no"), role.get("source_title"))
        chapter = chapters.setdefault(
            key,
            {
                "source_chapter_no": role.get("source_chapter_no"),
                "source_title": role.get("source_title"),
                "local_role": role.get("source_local_role"),
                "edition1_available_pattern_ids": [],
                "edition1_pattern_buy_roles": [],
            },
        )
        chapter["edition1_available_pattern_ids"].append(pattern_id)
        chapter["edition1_pattern_buy_roles"].append(
            {
                "pattern_id": pattern_id,
                "local_role": role.get("pattern_local_role"),
                "buy_layer_allowed": role.get("buy_layer_allowed"),
                "buy_scope": role.get("buy_scope"),
                "reason": role.get("reason"),
            }
        )
    return list(chapters.values())


def build_after_buy_defensive_conversion_rules(
    *,
    after_buy_pdf: Path = DEFAULT_AFTER_BUY_PDF,
    final_manifest: Path = DEFAULT_FINAL_MANIFEST,
    source_map_path: Path = DEFAULT_SOURCE_MAP,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    if not source_map_path.exists():
        source_map = build_after_buy_source_map(after_buy_pdf=after_buy_pdf, final_manifest=final_manifest, out_dir=source_map_path.parent)
    else:
        source_map = _read_json(source_map_path)

    roles = _flatten_source_roles(source_map)
    manifest_ids = _manifest_pattern_ids(final_manifest)
    rows = [
        _defensive_row(pattern_id, roles, manifest_ids)
        for pattern_id in (*SOURCE_MAPPED_DEFENSIVE_PATTERNS, *EDITION1_POLICY_DEFENSIVE_PATTERNS)
    ]

    failures: list[str] = []
    for pattern_id in SOURCE_MAPPED_DEFENSIVE_PATTERNS:
        row = next(row for row in rows if row["pattern_id"] == pattern_id)
        if row["source_status"] != "after_buy_mapped_defensive":
            failures.append(f"{pattern_id}:missing_after_buy_defensive_mapping")
        if row["buy_layer_allowed"] is not False:
            failures.append(f"{pattern_id}:buy_layer_allowed_policy_leak")
        if row["buy_gate_denies_long_cash_buy"] is not True:
            failures.append(f"{pattern_id}:buy_gate_does_not_deny")
    for row in rows:
        if row["manifest_present"] is not True:
            failures.append(f"{row['pattern_id']}:missing_final_manifest_pattern")

    result = {
        "ruleset_id": RULESET_ID,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "source_grounding_id": source_map.get("source_grounding_id"),
        "buy_first_policy_id": source_map.get("buy_first_policy_id"),
        "conversion_policy": {
            "scope": "Vietnam cash-equity BUY-first scanner",
            "rule": "Bearish, top, and downside chapters may become avoid/exit/risk filters but not default long-cash BUY rules.",
            "short_selling_assumption": "No single-stock short-selling availability is assumed.",
        },
        "source_mapped_defensive_patterns": list(SOURCE_MAPPED_DEFENSIVE_PATTERNS),
        "edition1_policy_defensive_patterns": list(EDITION1_POLICY_DEFENSIVE_PATTERNS),
        "patterns": rows,
        "kpi_evidence": {
            "defensive_pattern_count": len(rows),
            "after_buy_mapped_defensive_count": sum(1 for row in rows if row["source_status"] == "after_buy_mapped_defensive"),
            "policy_defensive_not_direct_after_buy_count": sum(1 for row in rows if row["source_status"] == "edition1_policy_defensive_not_direct_after_buy"),
            "all_denied_as_long_cash_buy": all(row["buy_gate_denies_long_cash_buy"] and row["buy_layer_allowed"] is False for row in rows),
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "defensive_conversion_rules.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_markdown(out_dir / "defensive_conversion_rules.md", result)
    return result


def _write_markdown(path: Path, result: Mapping[str, Any]) -> None:
    lines = [
        "# After-the-Buy Defensive Conversion Rules",
        "",
        f"- Ruleset ID: `{result['ruleset_id']}`",
        f"- Status: `{result['status']}`",
        f"- Defensive patterns: `{result['kpi_evidence']['defensive_pattern_count']}`",
        f"- All denied as long-cash BUY: `{result['kpi_evidence']['all_denied_as_long_cash_buy']}`",
        "",
        "## Conversion Table",
        "",
        "| Pattern | Source status | Source chapter | Allowed use | Forbidden use |",
        "|---|---|---|---|---|",
    ]
    for row in result.get("patterns") or []:
        if isinstance(row, Mapping):
            source = row.get("source_title") or "policy defensive"
            lines.append(
                f"| `{row.get('pattern_id')}` | `{row.get('source_status')}` | {source} | {row.get('allowed_use')} | {row.get('forbidden_use')} |"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build After-the-Buy defensive/avoid conversion rules.")
    parser.add_argument("--after-buy-pdf", type=Path, default=DEFAULT_AFTER_BUY_PDF)
    parser.add_argument("--final-manifest", type=Path, default=DEFAULT_FINAL_MANIFEST)
    parser.add_argument("--source-map", type=Path, default=DEFAULT_SOURCE_MAP)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    result = build_after_buy_defensive_conversion_rules(
        after_buy_pdf=args.after_buy_pdf,
        final_manifest=args.final_manifest,
        source_map_path=args.source_map,
        out_dir=args.out_dir,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "defensive_pattern_count": result["kpi_evidence"]["defensive_pattern_count"],
                "all_denied_as_long_cash_buy": result["kpi_evidence"]["all_denied_as_long_cash_buy"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
