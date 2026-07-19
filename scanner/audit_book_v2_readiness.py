from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional

try:
    from .book_v2_readiness import chapter_readiness  # type: ignore
    from .pattern_set_metadata import base_metadata_for_pattern_set  # type: ignore
except Exception:  # pragma: no cover
    from book_v2_readiness import chapter_readiness  # type: ignore
    from pattern_set_metadata import base_metadata_for_pattern_set  # type: ignore


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_run_id(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT run_id FROM scanner_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        raise SystemExit("No scanner_runs found.")
    return str(row[0])


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


def _load_matrix(path: Path) -> Dict[str, Dict[str, Any]]:
    rows = _read_json(path)
    return {str(row["pattern_key"]): row for row in rows}


def _split_metrics(db_path: Path) -> Dict[str, Dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        run_id = _latest_run_id(conn)
        det_rows = conn.execute(
            """
            SELECT pattern_name, symbol
            FROM pattern_detections
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchall()
        eval_rows = conn.execute(
            """
            SELECT
                d.pattern_name,
                d.symbol,
                p.max_favorable_excursion_pct,
                p.bust_failure_5pct,
                p.boundary_invalidated,
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

    out: Dict[str, Dict[str, Any]] = {}
    det_symbols: Dict[str, set[str]] = {}
    for row in det_rows:
        pat = str(row["pattern_name"])
        cur = out.setdefault(pat, {"detections": 0})
        cur["detections"] = int(cur.get("detections") or 0) + 1
        det_symbols.setdefault(pat, set()).add(str(row["symbol"]))

    eval_symbols: Dict[str, set[str]] = {}
    moves: Dict[str, List[float]] = {}
    fail5: Dict[str, List[float]] = {}
    boundary: Dict[str, List[float]] = {}
    target: Dict[str, List[float]] = {}
    for row in eval_rows:
        pat = str(row["pattern_name"])
        eval_symbols.setdefault(pat, set()).add(str(row["symbol"]))
        for col, bucket in (
            ("max_favorable_excursion_pct", moves),
            ("bust_failure_5pct", fail5),
            ("boundary_invalidated", boundary),
            ("target_achieved_intraday", target),
        ):
            val = _safe_float(row[col])
            if val is not None:
                bucket.setdefault(pat, []).append(val)

    for pat in set(out) | set(moves) | set(fail5) | set(boundary) | set(target):
        cur = out.setdefault(pat, {"detections": 0})
        cur["symbol_count"] = len(det_symbols.get(pat, set()))
        cur["eval_symbol_count"] = len(eval_symbols.get(pat, set()))
        cur["evals"] = max(
            len(moves.get(pat, [])),
            len(fail5.get(pat, [])),
            len(boundary.get(pat, [])),
            len(target.get(pat, [])),
        )
        cur["median_move_pct"] = float(median(moves[pat])) if moves.get(pat) else None
        cur["failure_rate_5pct"] = (sum(fail5[pat]) / len(fail5[pat]) * 100.0) if fail5.get(pat) else None
        cur["boundary_pct"] = (sum(boundary[pat]) / len(boundary[pat]) * 100.0) if boundary.get(pat) else None
        cur["target_hit_pct"] = (sum(target[pat]) / len(target[pat]) * 100.0) if target.get(pat) else None
    return {"run_id": run_id, "patterns": out}


def build_readiness(
    *,
    valid_db: Path,
    calib_db: Path,
    phase3_matrix: Path,
    benchmark_matrix: Path,
) -> Dict[str, Any]:
    meta = base_metadata_for_pattern_set("bulkowski_53_strict")
    phase3 = _load_matrix(phase3_matrix)
    benchmark = _load_matrix(benchmark_matrix)
    valid = _split_metrics(valid_db)
    calib = _split_metrics(calib_db)

    rows: List[Dict[str, Any]] = []
    for key in sorted(meta.keys(), key=lambda k: (int(meta[k].get("bulkowski_chapter") or 10**9), k)):
        phase = phase3.get(key, {})
        bench = benchmark.get(key, {})
        row: Dict[str, Any] = {
            "pattern_key": key,
            "bulkowski_chapter": meta[key].get("bulkowski_chapter"),
            "bulkowski_name": meta[key].get("bulkowski_name"),
            "canonical_key": meta[key].get("canonical_key"),
            "phase3_status": phase.get("phase3_status"),
            "strategy_gate": phase.get("strategy_gate"),
            "benchmark_status": bench.get("benchmark_status"),
            "valid": valid["patterns"].get(key, {"detections": 0, "evals": 0, "symbol_count": 0}),
            "calib": calib["patterns"].get(key, {"detections": 0, "evals": 0, "symbol_count": 0}),
        }
        readiness, flags = chapter_readiness(
            valid_metrics=row["valid"],
            calib_metrics=row["calib"],
            phase3_row=phase,
            benchmark_row=bench,
        )
        row["book_v2_readiness"] = readiness
        row["readiness_flags"] = flags
        rows.append(row)

    readiness_counts = Counter(str(row["book_v2_readiness"]) for row in rows)
    flag_counts = Counter(flag for row in rows for flag in row["readiness_flags"])
    return {
        "summary": {
            "valid_run_id": valid["run_id"],
            "calib_run_id": calib["run_id"],
            "pattern_count": len(rows),
            "readiness_counts": dict(sorted(readiness_counts.items())),
            "flag_counts": dict(sorted(flag_counts.items())),
        },
        "patterns": rows,
    }


def render_markdown(payload: Dict[str, Any]) -> str:
    lines: List[str] = []
    summary = payload["summary"]
    rows = payload["patterns"]

    lines.append("# Book V2 Readiness Audit")
    lines.append("")
    lines.append("This audit decides how each Bulkowski 53 pattern should appear in the Vietnam research publication.")
    lines.append("")
    lines.append(f"- valid_run_id: `{summary['valid_run_id']}`")
    lines.append(f"- calib_run_id: `{summary['calib_run_id']}`")
    lines.append(f"- pattern_count: `{summary['pattern_count']}`")
    lines.append(f"- readiness_counts: `{summary['readiness_counts']}`")
    lines.append(f"- flag_counts: `{summary['flag_counts']}`")
    lines.append("")
    lines.append("## Readiness Policy")
    lines.append("")
    lines.append("- `core_research_chapter`: enough valid and calibration evidence for a full empirical chapter.")
    lines.append("- `thin_research_chapter`: usable for publication, but caveats must be visible.")
    lines.append("- `strategy_appendix`: candidate/watchlist; keep research facts separate from any strategy claim.")
    lines.append("- `reference_only`: keep taxonomy/reference coverage, but do not imply Vietnam evidence is strong.")
    lines.append("")

    for readiness in ("strategy_appendix", "core_research_chapter", "thin_research_chapter", "reference_only"):
        bucket = [row for row in rows if row["book_v2_readiness"] == readiness]
        lines.append(f"## `{readiness}`")
        lines.append("")
        lines.append("| Chap | Pattern | Valid evals | Calib evals | Valid move | Benchmark | Phase 3 | Strategy | Flags |")
        lines.append("|---:|---|---:|---:|---:|---|---|---|---|")
        for row in bucket:
            valid = row.get("valid") or {}
            calib = row.get("calib") or {}
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row.get("bulkowski_chapter") or ""),
                        str(row.get("pattern_key") or ""),
                        str(int(valid.get("evals") or 0)),
                        str(int(calib.get("evals") or 0)),
                        _fmt(_safe_float(valid.get("median_move_pct"))),
                        str(row.get("benchmark_status") or ""),
                        str(row.get("phase3_status") or ""),
                        str(row.get("strategy_gate") or ""),
                        ", ".join(row.get("readiness_flags") or []),
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

    require_legacy_enabled("scanner/audit_book_v2_readiness.py")
    parser = argparse.ArgumentParser(description="Audit Book v2 readiness for Bulkowski 53 pattern chapters.")
    parser.add_argument("--valid-db", required=True)
    parser.add_argument("--calib-db", required=True)
    parser.add_argument("--phase3-pattern-matrix", required=True)
    parser.add_argument("--benchmark-pattern-matrix", required=True)
    parser.add_argument("--out-md", required=True)
    parser.add_argument("--out-json", default=None)
    args = parser.parse_args()

    payload = build_readiness(
        valid_db=Path(args.valid_db),
        calib_db=Path(args.calib_db),
        phase3_matrix=Path(args.phase3_pattern_matrix),
        benchmark_matrix=Path(args.benchmark_pattern_matrix),
    )
    out_md = Path(args.out_md)
    _write_text(out_md, render_markdown(payload))
    if args.out_json:
        _write_json(Path(args.out_json), payload)
    print(f"Wrote readiness audit: {out_md.resolve()}")


if __name__ == "__main__":
    main()
