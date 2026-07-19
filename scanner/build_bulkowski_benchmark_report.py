from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
PHASE3_MATRIX = ROOT / "scan_results" / "audits" / "spec-audit-20260306" / "phase3" / "phase3_pattern_matrix.json"
SPEC_DIR = ROOT / "extraction_phase_1" / "digitization" / "patterns_digitized"


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _latest_run_id(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT run_id FROM scanner_runs ORDER BY created_at DESC LIMIT 1").fetchone()
        if not row:
            raise SystemExit(f"No scanner_runs found in {db_path}")
        return str(row[0])
    finally:
        conn.close()


def _aggregate_metrics(db_path: Path) -> Dict[str, Dict[str, Any]]:
    run_id = _latest_run_id(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        det_rows = conn.execute(
            """
            SELECT pattern_name, COUNT(*) AS detections
            FROM pattern_detections
            WHERE run_id = ?
            GROUP BY pattern_name
            """,
            (run_id,),
        ).fetchall()
        eval_rows = conn.execute(
            """
            SELECT
                pattern_name,
                max_favorable_excursion_pct,
                bust_failure_5pct,
                boundary_invalidated,
                target_achieved_intraday,
                throwback_pullback_occurred
            FROM post_breakout_results
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchall()
    finally:
        conn.close()

    out: Dict[str, Dict[str, Any]] = {}
    for row in det_rows:
        out[str(row["pattern_name"])] = {"detections": int(row["detections"] or 0)}

    bucket: Dict[str, Dict[str, List[float]]] = {}
    for row in eval_rows:
        pat = str(row["pattern_name"])
        cur = bucket.setdefault(
            pat,
            {
                "move": [],
                "fail5": [],
                "boundary": [],
                "target": [],
                "tbpb": [],
            },
        )
        move = row["max_favorable_excursion_pct"]
        if move is not None:
            cur["move"].append(float(move))
        for key, col in (
            ("fail5", "bust_failure_5pct"),
            ("boundary", "boundary_invalidated"),
            ("target", "target_achieved_intraday"),
            ("tbpb", "throwback_pullback_occurred"),
        ):
            val = row[col]
            if val is not None:
                cur[key].append(float(val))

    for pat, vals in bucket.items():
        item = out.setdefault(pat, {})
        item["evals"] = len(vals["move"]) or max(len(vals["fail5"]), len(vals["target"]), len(vals["tbpb"]), len(vals["boundary"]))
        item["median_move_pct"] = median(vals["move"]) if vals["move"] else None
        item["failure_rate_5pct"] = (sum(vals["fail5"]) / len(vals["fail5"]) * 100.0) if vals["fail5"] else None
        item["boundary_pct"] = (sum(vals["boundary"]) / len(vals["boundary"]) * 100.0) if vals["boundary"] else None
        item["target_hit_pct"] = (sum(vals["target"]) / len(vals["target"]) * 100.0) if vals["target"] else None
        item["tbpb_pct"] = (sum(vals["tbpb"]) / len(vals["tbpb"]) * 100.0) if vals["tbpb"] else None

    return out


def _spec_path(spec_key: str) -> Path:
    return SPEC_DIR / f"{spec_key}_digitized.json"


def _match_triangle_stats(perf: Dict[str, Any], pattern_key: str) -> Optional[Dict[str, Any]]:
    key = str(pattern_key)
    if "ascending" in key:
        return perf.get("ascending_triangle")
    if "descending" in key:
        return perf.get("descending_triangle")
    if "symmetrical" in key:
        return perf.get("symmetrical_triangle")
    return None


def _extract_benchmark(pattern_key: str, spec_key: str) -> Dict[str, Any]:
    path = _spec_path(spec_key)
    if not path.exists():
        return {}
    data = _read_json(path)
    perf = data.get("performance_statistics") or {}
    if not isinstance(perf, dict):
        return {}

    scoped = perf
    triangle_stats = _match_triangle_stats(perf, pattern_key)
    if triangle_stats:
        scoped = triangle_stats

    benchmark: Dict[str, Any] = {}
    for src_key in ("median_rise_pct", "median_decline_pct", "average_rise_pct", "average_decline_pct"):
        if src_key in scoped:
            benchmark["median_move_pct"] = float(scoped[src_key])
            break
    for src_key in ("failure_rate_5pct", "failure_rate_pct"):
        if src_key in scoped:
            benchmark["failure_rate_5pct"] = float(scoped[src_key])
            break
    for src_key in ("pullback_rate_pct", "throwback_rate_pct", "throwback_pullback_rate_pct"):
        if src_key in scoped:
            benchmark["tbpb_pct"] = float(scoped[src_key])
            break
    benchmark["source_spec"] = str(path)
    return benchmark


def _delta(actual: Optional[float], benchmark: Optional[float]) -> Optional[float]:
    if actual is None or benchmark is None:
        return None
    return float(actual) - float(benchmark)


def _status(valid: Dict[str, Any], benchmark: Dict[str, Any]) -> str:
    evals = int(valid.get("evals") or 0)
    if evals < 5:
        return "sparse"

    move_delta = _delta(valid.get("median_move_pct"), benchmark.get("median_move_pct"))
    fail_delta = _delta(valid.get("failure_rate_5pct"), benchmark.get("failure_rate_5pct"))

    if move_delta is None and fail_delta is None:
        return "no_benchmark"
    if move_delta is not None and move_delta <= -10.0:
        return "materially_weaker"
    if fail_delta is not None and fail_delta >= 10.0:
        return "materially_weaker"
    if move_delta is not None and abs(move_delta) <= 5.0 and (fail_delta is None or abs(fail_delta) <= 5.0):
        return "roughly_aligned"
    return "mixed"


def build_report(*, valid_db: Path, calib_db: Path, out_dir: Path) -> Dict[str, Any]:
    rows = _read_json(PHASE3_MATRIX)
    valid_metrics = _aggregate_metrics(valid_db)
    calib_metrics = _aggregate_metrics(calib_db)

    pattern_rows: List[Dict[str, Any]] = []
    for row in rows:
        pattern_key = str(row["pattern_key"])
        spec_key = str(row["spec_key"])
        benchmark = _extract_benchmark(pattern_key, spec_key)
        valid = valid_metrics.get(pattern_key, {})
        calib = calib_metrics.get(pattern_key, {})
        pattern_rows.append(
            {
                "pattern_key": pattern_key,
                "bulkowski_name": row.get("bulkowski_name"),
                "canonical_key": row.get("canonical_key"),
                "spec_key": spec_key,
                "phase3_status": row.get("phase3_status"),
                "strategy_gate": row.get("strategy_gate"),
                "benchmark": benchmark,
                "valid": valid,
                "calib": calib,
                "valid_vs_benchmark": {
                    "median_move_delta": _delta(valid.get("median_move_pct"), benchmark.get("median_move_pct")),
                    "failure_rate_5pct_delta": _delta(valid.get("failure_rate_5pct"), benchmark.get("failure_rate_5pct")),
                    "tbpb_delta": _delta(valid.get("tbpb_pct"), benchmark.get("tbpb_pct")),
                },
                "benchmark_status": _status(valid, benchmark),
            }
        )

    summary = {
        "pattern_count": len(pattern_rows),
        "status_counts": {
            key: sum(1 for row in pattern_rows if row["benchmark_status"] == key)
            for key in sorted({str(row["benchmark_status"]) for row in pattern_rows})
        },
        "valid_db": str(valid_db.resolve()),
        "calib_db": str(calib_db.resolve()),
        "valid_run_id": _latest_run_id(valid_db),
        "calib_run_id": _latest_run_id(calib_db),
    }

    payload = {"summary": summary, "patterns": pattern_rows}
    _write_json(out_dir / "benchmark_summary.json", summary)
    _write_json(out_dir / "benchmark_pattern_matrix.json", pattern_rows)
    _write_text(out_dir / "benchmark_report.md", _render_report(payload))
    return payload


def _render_report(payload: Dict[str, Any]) -> str:
    summary = payload["summary"]
    rows = payload["patterns"]
    sort_rows = sorted(
        rows,
        key=lambda row: (
            0 if row["benchmark_status"] == "materially_weaker" else 1,
            0 if row["benchmark_status"] == "mixed" else 1,
            str(row["pattern_key"]),
        ),
    )

    lines: List[str] = []
    lines.append("# Bulkowski Benchmark Report")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- patterns: `{summary['pattern_count']}`")
    lines.append(f"- status_counts: `{summary['status_counts']}`")
    lines.append(f"- valid_run_id: `{summary['valid_run_id']}`")
    lines.append(f"- calib_run_id: `{summary['calib_run_id']}`")
    lines.append("")
    lines.append("## Pattern Matrix")
    lines.append("")
    lines.append("| Pattern | Benchmark status | Valid evals | Valid move | Ref move | dMove | Valid fail5 | Ref fail5 | dFail |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for row in sort_rows:
        valid = row.get("valid") or {}
        bench = row.get("benchmark") or {}
        delta = row.get("valid_vs_benchmark") or {}
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["pattern_key"]),
                    str(row["benchmark_status"]),
                    str(int(valid.get("evals") or 0)),
                    _fmt(valid.get("median_move_pct")),
                    _fmt(bench.get("median_move_pct")),
                    _fmt(delta.get("median_move_delta")),
                    _fmt(valid.get("failure_rate_5pct")),
                    _fmt(bench.get("failure_rate_5pct")),
                    _fmt(delta.get("failure_rate_5pct_delta")),
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--valid-db", required=True)
    parser.add_argument("--calib-db", required=True)
    parser.add_argument("--out-dir", default="scan_results/audits/spec-audit-20260306/benchmark/cycle-1")
    args = parser.parse_args()
    payload = build_report(
        valid_db=Path(args.valid_db).resolve(),
        calib_db=Path(args.calib_db).resolve(),
        out_dir=Path(args.out_dir).resolve(),
    )
    print("=== Bulkowski Benchmark Report ===")
    print(f"out_dir: {Path(args.out_dir).resolve()}")
    print(f"status_counts: {payload['summary']['status_counts']}")


if __name__ == "__main__":
    main()
