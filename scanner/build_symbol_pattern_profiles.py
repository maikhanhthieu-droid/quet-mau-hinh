from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional

try:
    from .pattern_set_metadata import base_metadata_for_pattern_set  # type: ignore
except Exception:  # pragma: no cover
    from pattern_set_metadata import base_metadata_for_pattern_set  # type: ignore


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _safe_float(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except Exception:
        return None
    if v != v:
        return None
    return v


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def _latest_run_id(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT run_id FROM scanner_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        raise SystemExit("No scanner_runs found.")
    return str(row[0])


def _load_phase3_matrix(path: Path) -> Dict[str, Dict[str, Any]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {str(row["pattern_key"]): row for row in rows}


def _aggregate_split(
    db_path: Path,
    *,
    phase3: Dict[str, Dict[str, Any]],
    meta: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        run_id = _latest_run_id(conn)
        det_rows = conn.execute(
            """
            SELECT symbol, pattern_name
            FROM pattern_detections
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchall()
        eval_rows = conn.execute(
            """
            SELECT
                d.symbol,
                d.pattern_name,
                p.max_favorable_excursion_pct,
                p.target_achieved_intraday
            FROM pattern_detections d
            JOIN post_breakout_results p
              ON p.run_id = d.run_id AND p.pattern_id = d.pattern_id
            WHERE d.run_id = ?
            """,
            (run_id,),
        ).fetchall()
    finally:
        conn.close()

    by_symbol: Dict[str, Dict[str, Any]] = {}
    for row in det_rows:
        symbol = str(row["symbol"])
        pattern = str(row["pattern_name"])
        canonical = str(meta.get(pattern, {}).get("canonical_key") or pattern)
        cur = by_symbol.setdefault(
            symbol,
            {
                "detections": 0,
                "patterns": defaultdict(lambda: {"detections": 0, "evals": 0, "moves": [], "target": []}),
                "families": defaultdict(lambda: {"detections": 0, "evals": 0}),
            },
        )
        cur["detections"] += 1
        cur["patterns"][pattern]["detections"] += 1
        cur["families"][canonical]["detections"] += 1

    for row in eval_rows:
        symbol = str(row["symbol"])
        pattern = str(row["pattern_name"])
        canonical = str(meta.get(pattern, {}).get("canonical_key") or pattern)
        cur = by_symbol.setdefault(
            symbol,
            {
                "detections": 0,
                "patterns": defaultdict(lambda: {"detections": 0, "evals": 0, "moves": [], "target": []}),
                "families": defaultdict(lambda: {"detections": 0, "evals": 0}),
            },
        )
        pcur = cur["patterns"][pattern]
        pcur["evals"] += 1
        move = _safe_float(row["max_favorable_excursion_pct"])
        if move is not None:
            pcur["moves"].append(move)
        target = _safe_float(row["target_achieved_intraday"])
        if target is not None:
            pcur["target"].append(target)
        cur["families"][canonical]["evals"] += 1

    out: Dict[str, Any] = {"run_id": run_id, "symbols": {}}
    for symbol, bucket in by_symbol.items():
        pattern_rows: List[Dict[str, Any]] = []
        for pattern, prow in bucket["patterns"].items():
            moves = prow["moves"]
            target = prow["target"]
            pattern_rows.append(
                {
                    "pattern_key": pattern,
                    "canonical_key": str(meta.get(pattern, {}).get("canonical_key") or pattern),
                    "phase3_status": phase3.get(pattern, {}).get("phase3_status"),
                    "strategy_gate": phase3.get(pattern, {}).get("strategy_gate"),
                    "detections": int(prow["detections"]),
                    "evals": int(prow["evals"]),
                    "median_move_pct": float(median(moves)) if moves else None,
                    "target_hit_pct": (sum(target) / len(target) * 100.0) if target else None,
                }
            )
        pattern_rows.sort(key=lambda row: (-int(row["evals"]), -int(row["detections"]), str(row["pattern_key"])))

        family_rows: List[Dict[str, Any]] = []
        for family, frow in bucket["families"].items():
            family_rows.append(
                {
                    "canonical_key": family,
                    "detections": int(frow["detections"]),
                    "evals": int(frow["evals"]),
                }
            )
        family_rows.sort(key=lambda row: (-int(row["evals"]), -int(row["detections"]), str(row["canonical_key"])))

        non_gap_patterns = [row for row in pattern_rows if row["pattern_key"] != "gaps"]
        non_gap_families = [row for row in family_rows if row["canonical_key"] != "gaps"]

        out["symbols"][symbol] = {
            "detections": int(bucket["detections"]),
            "evals": sum(int(row["evals"]) for row in pattern_rows),
            "non_gap_detections": sum(int(row["detections"]) for row in non_gap_patterns),
            "non_gap_evals": sum(int(row["evals"]) for row in non_gap_patterns),
            "pattern_diversity_ex_gaps": len(non_gap_patterns),
            "family_diversity_ex_gaps": len(non_gap_families),
            "top_patterns": pattern_rows[:10],
            "top_patterns_ex_gaps": non_gap_patterns[:10],
            "top_families": family_rows[:10],
            "top_families_ex_gaps": non_gap_families[:10],
        }
    return out


def _combine_profiles(valid: Dict[str, Any], calib: Dict[str, Any]) -> List[Dict[str, Any]]:
    symbols = sorted(set(valid["symbols"]) | set(calib["symbols"]))
    rows: List[Dict[str, Any]] = []
    for symbol in symbols:
        v = valid["symbols"].get(symbol, {})
        c = calib["symbols"].get(symbol, {})
        row = {
            "symbol": symbol,
            "valid_detections": int(v.get("detections") or 0),
            "valid_evals": int(v.get("evals") or 0),
            "valid_non_gap_detections": int(v.get("non_gap_detections") or 0),
            "valid_non_gap_evals": int(v.get("non_gap_evals") or 0),
            "calib_detections": int(c.get("detections") or 0),
            "calib_evals": int(c.get("evals") or 0),
            "calib_non_gap_detections": int(c.get("non_gap_detections") or 0),
            "calib_non_gap_evals": int(c.get("non_gap_evals") or 0),
            "combined_detections": int(v.get("detections") or 0) + int(c.get("detections") or 0),
            "combined_evals": int(v.get("evals") or 0) + int(c.get("evals") or 0),
            "combined_non_gap_detections": int(v.get("non_gap_detections") or 0) + int(c.get("non_gap_detections") or 0),
            "combined_non_gap_evals": int(v.get("non_gap_evals") or 0) + int(c.get("non_gap_evals") or 0),
            "combined_pattern_diversity_ex_gaps": int(v.get("pattern_diversity_ex_gaps") or 0) + int(c.get("pattern_diversity_ex_gaps") or 0),
            "combined_family_diversity_ex_gaps": int(v.get("family_diversity_ex_gaps") or 0) + int(c.get("family_diversity_ex_gaps") or 0),
            "top_patterns_ex_gaps_valid": v.get("top_patterns_ex_gaps", [])[:5],
            "top_patterns_ex_gaps_calib": c.get("top_patterns_ex_gaps", [])[:5],
            "top_families_ex_gaps_valid": v.get("top_families_ex_gaps", [])[:5],
            "top_families_ex_gaps_calib": c.get("top_families_ex_gaps", [])[:5],
        }
        rows.append(row)
    rows.sort(
        key=lambda row: (
            -int(row["combined_non_gap_evals"]),
            -int(row["combined_non_gap_detections"]),
            -int(row["combined_family_diversity_ex_gaps"]),
            -int(row["combined_evals"]),
            str(row["symbol"]),
        )
    )
    return rows


def build_profiles(
    *,
    valid_db: Path,
    calib_db: Path,
    phase3_matrix: Path,
    out_dir: Path,
    top_n: int,
) -> Dict[str, Any]:
    meta = base_metadata_for_pattern_set("bulkowski_53_strict")
    phase3 = _load_phase3_matrix(phase3_matrix)
    valid = _aggregate_split(valid_db, phase3=phase3, meta=meta)
    calib = _aggregate_split(calib_db, phase3=phase3, meta=meta)
    combined = _combine_profiles(valid, calib)

    payload = {
        "summary": {
            "valid_run_id": valid["run_id"],
            "calib_run_id": calib["run_id"],
            "symbol_count": len(combined),
            "top_n": int(top_n),
        },
        "top_symbols": combined[:top_n],
        "all_symbols": combined,
        "valid_profiles": valid["symbols"],
        "calib_profiles": calib["symbols"],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "symbol_pattern_profiles.json", payload)
    _write_text(out_dir / "symbol_pattern_profiles.md", _render(payload))
    return payload


def _pattern_cell(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return ""
    parts = []
    for row in rows[:3]:
        parts.append(f"{row['pattern_key']} ({int(row['evals'])}/{int(row['detections'])})")
    return ", ".join(parts)


def _family_cell(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return ""
    parts = []
    for row in rows[:3]:
        parts.append(f"{row['canonical_key']} ({int(row['evals'])}/{int(row['detections'])})")
    return ", ".join(parts)


def _render(payload: Dict[str, Any]) -> str:
    lines: List[str] = []
    summary = payload["summary"]
    lines.append("# Symbol Pattern Profiles")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- valid_run_id: `{summary['valid_run_id']}`")
    lines.append(f"- calib_run_id: `{summary['calib_run_id']}`")
    lines.append(f"- symbol_count: `{summary['symbol_count']}`")
    lines.append("")
    lines.append("## Top Symbols")
    lines.append("")
    lines.append("| Symbol | Non-gap evals | Non-gap detections | Family diversity | Valid top patterns ex-gaps | Valid top families ex-gaps |")
    lines.append("|---|---:|---:|---:|---|---|")
    for row in payload["top_symbols"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["symbol"]),
                    str(int(row["combined_non_gap_evals"])),
                    str(int(row["combined_non_gap_detections"])),
                    str(int(row["combined_family_diversity_ex_gaps"])),
                    _pattern_cell(row["top_patterns_ex_gaps_valid"]),
                    _family_cell(row["top_families_ex_gaps_valid"]),
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    try:
        from .legacy_guard import require_legacy_enabled  # type: ignore
    except Exception:  # pragma: no cover
        from legacy_guard import require_legacy_enabled  # type: ignore

    require_legacy_enabled("scanner/build_symbol_pattern_profiles.py")
    parser = argparse.ArgumentParser()
    parser.add_argument("--valid-db", required=True)
    parser.add_argument("--calib-db", required=True)
    parser.add_argument("--phase3-pattern-matrix", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--top-n", type=int, default=50)
    args = parser.parse_args()

    payload = build_profiles(
        valid_db=Path(args.valid_db).resolve(),
        calib_db=Path(args.calib_db).resolve(),
        phase3_matrix=Path(args.phase3_pattern_matrix).resolve(),
        out_dir=Path(args.out_dir).resolve(),
        top_n=int(args.top_n),
    )
    print("=== Symbol Pattern Profiles ===")
    print(f"out_dir: {Path(args.out_dir).resolve()}")
    print(f"symbol_count: {payload['summary']['symbol_count']}")


if __name__ == "__main__":
    main()
