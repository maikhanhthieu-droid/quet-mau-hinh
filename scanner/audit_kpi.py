"""
Audit KPI consistency + scan quality for digitized patterns.

This script is intentionally lightweight: it reads digitized specs (width/height)
and summarizes how well the *results DB* complies, plus a few outcome KPIs.

Examples:
  python3 scanner/audit_kpi.py --results-db scan_results/databases/final/full_classic_1715_v2.sqlite
  python3 scanner/audit_kpi.py --results-db scan_results/databases/final/audit_kpi.sqlite --run-id scan_...
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

try:
    from .pattern_set_metadata import build_pattern_metadata  # type: ignore
except Exception:  # pragma: no cover
    from pattern_set_metadata import build_pattern_metadata  # type: ignore


def _safe_float(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except Exception:
        return None
    if v != v:  # NaN
        return None
    return v


def _safe_int(x: Any) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return None


@dataclass(frozen=True)
class SpecConstraints:
    width_min_bars: Optional[int]
    width_max_bars: Optional[int]
    height_min_pct: Optional[float]
    height_max_pct: Optional[float]


def _load_specs(spec_dir: str) -> Dict[str, SpecConstraints]:
    out: Dict[str, SpecConstraints] = {}
    for name in sorted(os.listdir(spec_dir)):
        if not name.endswith("_digitized.json"):
            continue
        key = name.replace("_digitized.json", "")
        path = os.path.join(spec_dir, name)
        with open(path, "r") as f:
            spec = json.load(f)

        geom = spec.get("geometry_constraints") or {}
        if not isinstance(geom, dict):
            geom = {}

        out[key] = SpecConstraints(
            width_min_bars=_safe_int(geom.get("width_min_bars")),
            width_max_bars=_safe_int(geom.get("width_max_bars")),
            height_min_pct=_safe_float(geom.get("height_ratio_min")),
            height_max_pct=_safe_float(geom.get("height_ratio_max")),
        )
    return out


def _latest_run_id(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT run_id FROM scanner_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        raise SystemExit("No runs found in scanner_runs.")
    return str(row[0])


def _load_run_config(conn: sqlite3.Connection, run_id: str) -> Dict[str, Any]:
    row = conn.execute("SELECT run_config_json FROM scanner_runs WHERE run_id = ?", (run_id,)).fetchone()
    if not row or not row[0]:
        return {}
    try:
        return json.loads(row[0])
    except Exception:
        return {}


def _scalar(conn: sqlite3.Connection, q: str, params: Tuple[Any, ...]) -> Any:
    row = conn.execute(q, params).fetchone()
    return row[0] if row else None


def _pct(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2:
        return float(s[mid])
    return (float(s[mid - 1]) + float(s[mid])) / 2.0


def main() -> None:
    try:
        from .legacy_guard import require_legacy_enabled  # type: ignore
    except Exception:  # pragma: no cover
        from legacy_guard import require_legacy_enabled  # type: ignore

    require_legacy_enabled("scanner/audit_kpi.py")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--results-db",
        default=os.path.join("scan_results", "pattern_scans.sqlite"),
        help="SQLite results DB produced by scanner/run_full_scan.py",
    )
    parser.add_argument("--run-id", default=None, help="run_id to audit (default: latest).")
    parser.add_argument(
        "--pattern-set-hint",
        choices=[
            "digitized",
            "bulkowski_53",
            "bulkowski_53_strict",
            "bulkowski_strict_ohlcv",
            "bulkowski_49_strict_ohlcv",
            "event_ohlcv",
            "bulkowski_55_ohlcv",
        ],
        default=None,
        help="Optional hint to reconstruct pattern metadata for older runs that lack persisted metadata.",
    )
    parser.add_argument(
        "--spec-dir",
        default=os.path.join("extraction_phase_1", "digitization", "patterns_digitized"),
        help="Directory containing *_digitized.json files.",
    )
    parser.add_argument(
        "--min-evals",
        type=int,
        default=50,
        help="Min eval rows needed to print outcome KPIs for a pattern.",
    )
    args = parser.parse_args()

    spec_dir = os.path.abspath(args.spec_dir)
    specs: Dict[str, SpecConstraints] = {}
    if os.path.isdir(spec_dir):
        specs = _load_specs(spec_dir)

    results_db = os.path.abspath(args.results_db)
    if not os.path.exists(results_db):
        raise SystemExit(f"Results DB not found: {results_db}")

    conn = sqlite3.connect(results_db)
    try:
        run_id = str(args.run_id or _latest_run_id(conn))
        run_cfg = _load_run_config(conn, run_id)
        meta_payload = run_cfg.get("pattern_metadata") if isinstance(run_cfg, dict) else None
        meta_map = {}
        if isinstance(meta_payload, dict):
            meta_map = meta_payload.get("patterns") if isinstance(meta_payload.get("patterns"), dict) else {}
        meta_map = meta_map or {}

        # Pattern list in this run (avoid printing specs that weren't scanned).
        run_patterns = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT pattern_name FROM pattern_detections WHERE run_id = ? ORDER BY pattern_name",
                (run_id,),
            ).fetchall()
        ]

        if (not meta_map) and args.pattern_set_hint:
            meta_payload = build_pattern_metadata(pattern_set=str(args.pattern_set_hint), scanners={}, patterns=run_patterns)
            meta_map = meta_payload.get("patterns") if isinstance(meta_payload.get("patterns"), dict) else {}
            meta_map = meta_map or {}

        print("=== KPI Audit ===")
        print(f"results_db: {results_db}")
        print(f"run_id:     {run_id}")
        print(f"patterns:   {len(run_patterns)}")
        if not specs:
            print(f"spec_dir:   (missing) {spec_dir}")

        # Overall KPI sanity
        invalid_width = _scalar(
            conn,
            "SELECT COUNT(*) FROM pattern_detections WHERE run_id = ? AND (pattern_width_bars IS NULL OR pattern_width_bars <= 0)",
            (run_id,),
        )
        invalid_height = _scalar(
            conn,
            "SELECT COUNT(*) FROM pattern_detections WHERE run_id = ? AND (pattern_height_pct IS NULL OR pattern_height_pct <= 0)",
            (run_id,),
        )
        invalid_conf = _scalar(
            conn,
            "SELECT COUNT(*) FROM pattern_detections WHERE run_id = ? AND (confidence_score IS NULL OR confidence_score < 0 OR confidence_score > 100)",
            (run_id,),
        )
        print(f"invalid_kpi: width={int(invalid_width or 0)} height={int(invalid_height or 0)} confidence={int(invalid_conf or 0)}")

        # Per-pattern compliance + outcomes
        rows: List[Dict[str, Any]] = []
        source_counts: Dict[str, int] = {"spec": 0, "mapped_spec": 0, "meta": 0, "none": 0}
        for pat in run_patterns:
            c = specs.get(pat)
            source = "none"
            if c is not None:
                source = "spec"
            else:
                mm = meta_map.get(pat) if isinstance(meta_map, dict) else None
                if isinstance(mm, dict):
                    sk = mm.get("spec_key")
                    if sk is not None and sk in specs:
                        c = specs.get(str(sk))
                        source = "mapped_spec"
                    else:
                        wmin = _safe_int(mm.get("width_min_bars"))
                        wmax = _safe_int(mm.get("width_max_bars"))
                        hmin = _safe_float(mm.get("height_min_pct"))
                        hmax = _safe_float(mm.get("height_max_pct"))
                        if any(v is not None for v in (wmin, wmax, hmin, hmax)):
                            c = SpecConstraints(wmin, wmax, hmin, hmax)
                            source = "meta"
            if c is None:
                c = SpecConstraints(None, None, None, None)
            source_counts[source] = int(source_counts.get(source, 0)) + 1

            total = int(
                _scalar(
                    conn,
                    "SELECT COUNT(*) FROM pattern_detections WHERE run_id = ? AND pattern_name = ?",
                    (run_id, pat),
                )
                or 0
            )
            confirmed = int(
                _scalar(
                    conn,
                    "SELECT COUNT(*) FROM pattern_detections "
                    "WHERE run_id = ? AND pattern_name = ? AND breakout_date IS NOT NULL AND breakout_price IS NOT NULL",
                    (run_id, pat),
                )
                or 0
            )
            evals = int(
                _scalar(
                    conn,
                    "SELECT COUNT(*) FROM post_breakout_results WHERE run_id = ? AND pattern_name = ?",
                    (run_id, pat),
                )
                or 0
            )

            width_out = 0
            if c.width_min_bars is not None and c.width_max_bars is not None and total:
                width_out = int(
                    _scalar(
                        conn,
                        "SELECT COUNT(*) FROM pattern_detections "
                        "WHERE run_id = ? AND pattern_name = ? AND (pattern_width_bars < ? OR pattern_width_bars > ?)",
                        (run_id, pat, int(c.width_min_bars), int(c.width_max_bars)),
                    )
                    or 0
                )
            height_out = 0
            if c.height_min_pct is not None and c.height_max_pct is not None and total:
                height_out = int(
                    _scalar(
                        conn,
                        "SELECT COUNT(*) FROM pattern_detections "
                        "WHERE run_id = ? AND pattern_name = ? AND (pattern_height_pct < ? OR pattern_height_pct > ?)",
                        (run_id, pat, float(c.height_min_pct), float(c.height_max_pct)),
                    )
                    or 0
                )

            row: Dict[str, Any] = {
                "pattern": pat,
                "detections": total,
                "confirmed": confirmed,
                "evals": evals,
                "width_out": width_out,
                "height_out": height_out,
                "wmin": c.width_min_bars,
                "wmax": c.width_max_bars,
                "hmin": c.height_min_pct,
                "hmax": c.height_max_pct,
            }

            if evals >= int(args.min_evals):
                # Load numeric eval series once for richer KPI checks.
                eval_rows = conn.execute(
                    "SELECT max_favorable_excursion_pct, days_to_ultimate, evaluation_window_bars, days_to_throwback_pullback "
                    "FROM post_breakout_results WHERE run_id = ? AND pattern_name = ?",
                    (run_id, pat),
                ).fetchall()

                moves = [_safe_float(r[0]) for r in eval_rows if _safe_float(r[0]) is not None]
                days_ult = [_safe_float(r[1]) for r in eval_rows if _safe_float(r[1]) is not None]
                win_bars = [_safe_float(r[2]) for r in eval_rows if _safe_float(r[2]) is not None]
                days_tb = [_safe_float(r[3]) for r in eval_rows if _safe_float(r[3]) is not None]

                bust5 = _pct(
                    _scalar(
                        conn,
                        "SELECT AVG(bust_failure_5pct) * 100.0 FROM post_breakout_results "
                        "WHERE run_id = ? AND pattern_name = ? AND bust_failure_5pct IS NOT NULL",
                        (run_id, pat),
                    )
                )
                boundary = _pct(
                    _scalar(
                        conn,
                        "SELECT AVG(boundary_invalidated) * 100.0 FROM post_breakout_results "
                        "WHERE run_id = ? AND pattern_name = ? AND boundary_invalidated IS NOT NULL",
                        (run_id, pat),
                    )
                )
                target = _pct(
                    _scalar(
                        conn,
                        "SELECT AVG(target_achieved_intraday) * 100.0 FROM post_breakout_results "
                        "WHERE run_id = ? AND pattern_name = ? AND target_achieved_intraday IS NOT NULL",
                        (run_id, pat),
                    )
                )
                tbpb = _pct(
                    _scalar(
                        conn,
                        "SELECT AVG(throwback_pullback_occurred) * 100.0 FROM post_breakout_results "
                        "WHERE run_id = ? AND pattern_name = ? AND throwback_pullback_occurred IS NOT NULL",
                        (run_id, pat),
                    )
                )

                row.update(
                    {
                        "bust5_pct": bust5,
                        "boundary_inval_pct": boundary,
                        "target_hit_pct": target,
                        "tbpb_pct": tbpb,
                    }
                )
                if moves:
                    row.update(
                        {
                            "median_move_pct": _median([float(x) for x in moves]),
                            "failure_rate_5pct": sum(1 for x in moves if float(x) < 5.0) / len(moves) * 100.0,
                            "failure_rate_10pct": sum(1 for x in moves if float(x) < 10.0) / len(moves) * 100.0,
                            "failure_rate_15pct": sum(1 for x in moves if float(x) < 15.0) / len(moves) * 100.0,
                        }
                    )
                if days_ult:
                    row["median_days_to_ultimate"] = _median([float(x) for x in days_ult])
                if days_tb:
                    row["median_days_to_tbpb"] = _median([float(x) for x in days_tb])
                if win_bars:
                    row["median_eval_window_bars"] = _median([float(x) for x in win_bars])

            rows.append(row)

        if meta_map:
            print(
                f"constraints_source: spec={source_counts.get('spec', 0)} "
                f"mapped_spec={source_counts.get('mapped_spec', 0)} "
                f"meta={source_counts.get('meta', 0)} none={source_counts.get('none', 0)}"
            )

        # Print the worst compliance issues first.
        bad = [r for r in rows if (r["width_out"] or r["height_out"])]
        bad.sort(key=lambda r: (-(r["width_out"] + r["height_out"]), -r["detections"], r["pattern"]))

        print("\n-- Spec compliance (width/height) --")
        if not bad:
            print("OK: no width/height out-of-spec rows found (based on geometry_constraints).")
        else:
            for r in bad[:20]:
                det = int(r["detections"] or 0) or 1
                w_pct = float(r["width_out"]) / det * 100.0
                h_pct = float(r["height_out"]) / det * 100.0
                print(
                    f"- {r['pattern']}: det={r['detections']} "
                    f"width_out={r['width_out']} ({w_pct:.2f}%) "
                    f"height_out={r['height_out']} ({h_pct:.2f}%)"
                )

        # Outcome KPI summary (only patterns with enough eval rows)
        print("\n-- Outcome KPIs (min_evals=%d) --" % int(args.min_evals))
        outcome = [r for r in rows if r.get("bust5_pct") is not None]
        outcome.sort(key=lambda r: (-(r["evals"]), r["pattern"]))
        if not outcome:
            print("No patterns meet min_evals; run evaluation or lower --min-evals.")
        else:
            for r in outcome[:20]:
                move = r.get("median_move_pct")
                move_s = f"{move:.2f}%" if isinstance(move, (int, float)) else "n/a"
                ult_days = r.get("median_days_to_ultimate")
                ult_days_s = f"{ult_days:.0f}d" if isinstance(ult_days, (int, float)) else "n/a"
                fail5 = r.get("failure_rate_5pct")
                fail5_s = f"{fail5:.2f}%" if isinstance(fail5, (int, float)) else "n/a"
                bust5 = r.get("bust5_pct")
                bust5_s = f"{bust5:.2f}%" if isinstance(bust5, (int, float)) else "n/a"
                boundary = r.get("boundary_inval_pct")
                boundary_s = f"{boundary:.2f}%" if isinstance(boundary, (int, float)) else "n/a"
                target = r.get("target_hit_pct")
                target_s = f"{target:.2f}%" if isinstance(target, (int, float)) else "n/a"
                tbpb = r.get("tbpb_pct")
                tbpb_s = f"{tbpb:.2f}%" if isinstance(tbpb, (int, float)) else "n/a"
                print(
                    f"- {r['pattern']}: evals={r['evals']}"
                    f", move_med={move_s}"
                    f", ult_med={ult_days_s}"
                    f", fail<5%={fail5_s}"
                    f", busted5={bust5_s}"
                    f", boundary={boundary_s}"
                    f", target_hit={target_s}"
                    f", tb/pb={tbpb_s}"
                )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
