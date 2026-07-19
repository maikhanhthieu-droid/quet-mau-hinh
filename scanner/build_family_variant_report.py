from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from statistics import median
from typing import Any, Dict, List


def _latest_run_id(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT run_id FROM scanner_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        raise SystemExit("No scanner_runs found")
    return str(row[0])


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def _aggregate(db_path: Path, patterns: List[str]) -> Dict[str, Any]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        run_id = _latest_run_id(conn)
        placeholders = ",".join("?" for _ in patterns)
        params = [run_id, *patterns]

        det_rows = conn.execute(
            f"""
            SELECT
                pattern_name,
                COALESCE(variant_code, '<null>') AS variant_code,
                COUNT(*) AS detections
            FROM pattern_detections
            WHERE run_id = ? AND pattern_name IN ({placeholders})
            GROUP BY pattern_name, COALESCE(variant_code, '<null>')
            ORDER BY pattern_name, detections DESC, variant_code
            """,
            params,
        ).fetchall()

        eval_rows = conn.execute(
            f"""
            SELECT
                d.pattern_name,
                COALESCE(d.variant_code, '<null>') AS variant_code,
                p.max_favorable_excursion_pct,
                p.bust_failure_5pct,
                p.boundary_invalidated,
                p.target_achieved_intraday,
                p.throwback_pullback_occurred
            FROM pattern_detections d
            JOIN post_breakout_results p
              ON p.run_id = d.run_id
             AND p.pattern_id = d.pattern_id
            WHERE d.run_id = ? AND d.pattern_name IN ({placeholders})
            ORDER BY d.pattern_name, variant_code
            """,
            params,
        ).fetchall()
    finally:
        conn.close()

    by_key: Dict[tuple[str, str], Dict[str, Any]] = {}
    for row in det_rows:
        key = (str(row["pattern_name"]), str(row["variant_code"]))
        by_key[key] = {
            "pattern_name": key[0],
            "variant_code": key[1],
            "detections": int(row["detections"] or 0),
            "move": [],
            "fail5": [],
            "boundary": [],
            "target": [],
            "tbpb": [],
        }

    for row in eval_rows:
        key = (str(row["pattern_name"]), str(row["variant_code"]))
        bucket = by_key.setdefault(
            key,
            {
                "pattern_name": key[0],
                "variant_code": key[1],
                "detections": 0,
                "move": [],
                "fail5": [],
                "boundary": [],
                "target": [],
                "tbpb": [],
            },
        )
        if row["max_favorable_excursion_pct"] is not None:
            bucket["move"].append(float(row["max_favorable_excursion_pct"]))
        for col, out_key in (
            ("bust_failure_5pct", "fail5"),
            ("boundary_invalidated", "boundary"),
            ("target_achieved_intraday", "target"),
            ("throwback_pullback_occurred", "tbpb"),
        ):
            if row[col] is not None:
                bucket[out_key].append(float(row[col]))

    rows: List[Dict[str, Any]] = []
    for key in sorted(by_key):
        bucket = by_key[key]
        moves = bucket.pop("move")
        fail5 = bucket.pop("fail5")
        boundary = bucket.pop("boundary")
        target = bucket.pop("target")
        tbpb = bucket.pop("tbpb")
        bucket["evals"] = len(moves) or max(len(fail5), len(boundary), len(target), len(tbpb))
        bucket["median_move_pct"] = median(moves) if moves else None
        bucket["failure_rate_5pct"] = (sum(fail5) / len(fail5) * 100.0) if fail5 else None
        bucket["boundary_pct"] = (sum(boundary) / len(boundary) * 100.0) if boundary else None
        bucket["target_hit_pct"] = (sum(target) / len(target) * 100.0) if target else None
        bucket["tbpb_pct"] = (sum(tbpb) / len(tbpb) * 100.0) if tbpb else None
        rows.append(bucket)

    return {
        "db_path": str(db_path.resolve()),
        "run_id": run_id,
        "patterns": patterns,
        "rows": rows,
    }


def build_report(*, valid_db: Path, calib_db: Path, patterns: List[str], out_dir: Path, title: str) -> Dict[str, Any]:
    valid = _aggregate(valid_db, patterns)
    calib = _aggregate(calib_db, patterns)
    payload = {
        "title": title,
        "patterns": patterns,
        "valid": valid,
        "calib": calib,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "variant_report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "variant_report.md").write_text(_render(payload), encoding="utf-8")
    return payload


def _render(payload: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"# {payload['title']}")
    lines.append("")
    lines.append(f"- patterns: `{payload['patterns']}`")
    lines.append(f"- valid_run_id: `{payload['valid']['run_id']}`")
    lines.append(f"- calib_run_id: `{payload['calib']['run_id']}`")
    lines.append("")
    for split_name in ("valid", "calib"):
        split = payload[split_name]
        lines.append(f"## {split_name.title()}")
        lines.append("")
        lines.append("| Pattern | Variant | Detections | Evals | Median move | Fail<5 | Boundary | Target hit | TB/PB |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
        for row in split["rows"]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row["pattern_name"]),
                        str(row["variant_code"]),
                        str(int(row["detections"] or 0)),
                        str(int(row["evals"] or 0)),
                        _fmt(row["median_move_pct"]),
                        _fmt(row["failure_rate_5pct"]),
                        _fmt(row["boundary_pct"]),
                        _fmt(row["target_hit_pct"]),
                        _fmt(row["tbpb_pct"]),
                    ]
                )
                + " |"
            )
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--valid-db", required=True)
    parser.add_argument("--calib-db", required=True)
    parser.add_argument("--patterns", required=True, help="Comma-separated pattern names")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--title", default="Family Variant Report")
    args = parser.parse_args()

    patterns = [p.strip() for p in args.patterns.split(",") if p.strip()]
    payload = build_report(
        valid_db=Path(args.valid_db).resolve(),
        calib_db=Path(args.calib_db).resolve(),
        patterns=patterns,
        out_dir=Path(args.out_dir).resolve(),
        title=str(args.title),
    )
    print("=== Family Variant Report ===")
    print(f"out_dir: {Path(args.out_dir).resolve()}")
    print(f"valid_run_id: {payload['valid']['run_id']}")
    print(f"calib_run_id: {payload['calib']['run_id']}")


if __name__ == "__main__":
    main()
