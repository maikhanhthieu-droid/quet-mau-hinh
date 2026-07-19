from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from statistics import median
from typing import Any, Dict, List


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _safe_float(x: Any) -> float | None:
    try:
        return float(x)
    except Exception:
        return None


def _load_rows(db_path: Path, pattern_name: str) -> List[Dict[str, Any]]:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    rows = cur.execute(
        """
        select
            d.pattern_id,
            d.symbol,
            d.pattern_name,
            d.confidence_score,
            d.volume_confirmed,
            d.pattern_height_pct,
            d.pattern_width_bars,
            d.family_metrics_json,
            r.breakout_date,
            r.breakout_direction,
            r.breakout_price,
            r.max_favorable_excursion_pct,
            r.max_adverse_excursion_pct,
            r.bust_failure_5pct,
            r.boundary_invalidated,
            r.target_achieved_intraday,
            r.throwback_pullback_occurred,
            r.days_to_target,
            r.days_to_ultimate
        from pattern_detections d
        join post_breakout_results r on r.pattern_id = d.pattern_id
        where d.pattern_name = ?
        """,
        (pattern_name,),
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            item["family_metrics"] = json.loads(item.get("family_metrics_json") or "{}")
        except Exception:
            item["family_metrics"] = {}
        out.append(item)
    con.close()
    return out


def _summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {
            "evals": 0,
            "median_move_pct": None,
            "failure_rate_5pct": None,
            "boundary_invalidated_pct": None,
            "target_hit_pct": None,
            "tbpb_pct": None,
            "median_days_to_target": None,
            "median_days_to_ultimate": None,
            "confidence_median": None,
            "width_median": None,
            "height_median": None,
        }

    def _pct(key: str) -> float | None:
        vals = [int(bool(r.get(key))) for r in rows if r.get(key) is not None]
        return round(sum(vals) / len(vals) * 100.0, 2) if vals else None

    def _med(key: str) -> float | None:
        vals = [_safe_float(r.get(key)) for r in rows]
        vals = [v for v in vals if v is not None]
        return round(float(median(vals)), 2) if vals else None

    return {
        "evals": len(rows),
        "median_move_pct": _med("max_favorable_excursion_pct"),
        "failure_rate_5pct": _pct("bust_failure_5pct"),
        "boundary_invalidated_pct": _pct("boundary_invalidated"),
        "target_hit_pct": _pct("target_achieved_intraday"),
        "tbpb_pct": _pct("throwback_pullback_occurred"),
        "median_days_to_target": _med("days_to_target"),
        "median_days_to_ultimate": _med("days_to_ultimate"),
        "confidence_median": _med("confidence_score"),
        "width_median": _med("pattern_width_bars"),
        "height_median": _med("pattern_height_pct"),
    }


def _fmt_pct(x: Any) -> str:
    return "" if x is None else f"{float(x):.2f}%"


def _fmt_num(x: Any) -> str:
    return "" if x is None else f"{float(x):.2f}"


def _render(pattern_name: str, payload: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"# Candidate Strategy Report: {pattern_name}")
    lines.append("")
    lines.append("## Scope")
    lines.append("")
    lines.append(f"- valid_db: `{payload['valid_db']}`")
    lines.append(f"- calib_db: `{payload['calib_db']}`")
    lines.append(f"- pattern: `{pattern_name}`")
    lines.append("")
    lines.append("## Cohorts")
    lines.append("")
    lines.append("| Cohort | Split | Evals | Move | Fail<5 | Boundary | Target | TBPB | Median conf | Median width | Median height |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for cohort in payload["cohorts"]:
        for split in ("valid", "calib"):
            s = cohort[split]
            lines.append(
                "| " + " | ".join(
                    [
                        str(cohort["name"]),
                        split,
                        str(s["evals"]),
                        _fmt_pct(s["median_move_pct"]),
                        _fmt_pct(s["failure_rate_5pct"]),
                        _fmt_pct(s["boundary_invalidated_pct"]),
                        _fmt_pct(s["target_hit_pct"]),
                        _fmt_pct(s["tbpb_pct"]),
                        _fmt_num(s["confidence_median"]),
                        _fmt_num(s["width_median"]),
                        _fmt_num(s["height_median"]),
                    ]
                ) + " |"
            )
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- `all`: toàn bộ evals của pattern trên split tương ứng.")
    lines.append("- `high_confidence`: `confidence_score >= 80`.")
    lines.append("- `narrower_core`: `pattern_width_bars <= 120`.")
    lines.append("- `high_conf_plus_core`: giao của hai cohort trên.")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--valid-db", required=True)
    parser.add_argument("--calib-db", required=True)
    parser.add_argument("--pattern", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    valid_rows = _load_rows(Path(args.valid_db), args.pattern)
    calib_rows = _load_rows(Path(args.calib_db), args.pattern)

    cohorts = [
        ("all", lambda r: True),
        ("high_confidence", lambda r: int(r.get("confidence_score") or 0) >= 80),
        ("narrower_core", lambda r: int(r.get("pattern_width_bars") or 0) <= 120),
        (
            "high_conf_plus_core",
            lambda r: int(r.get("confidence_score") or 0) >= 80 and int(r.get("pattern_width_bars") or 0) <= 120,
        ),
    ]

    out_rows = []
    for name, keep in cohorts:
        v = [r for r in valid_rows if keep(r)]
        c = [r for r in calib_rows if keep(r)]
        out_rows.append({"name": name, "valid": _summary(v), "calib": _summary(c)})

    payload = {
        "pattern": args.pattern,
        "valid_db": str(Path(args.valid_db).resolve()),
        "calib_db": str(Path(args.calib_db).resolve()),
        "cohorts": out_rows,
    }

    out_dir = Path(args.out_dir)
    _write_json(out_dir / "candidate_strategy_summary.json", payload)
    _write_text(out_dir / "candidate_strategy_report.md", _render(args.pattern, payload))
    print(f"=== Candidate Strategy Report ===")
    print(f"out_dir: {out_dir.resolve()}")


if __name__ == "__main__":
    main()
