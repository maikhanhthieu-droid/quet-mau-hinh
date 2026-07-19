from __future__ import annotations

import argparse
import json
import re
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


def _append_table_blocks(
    lines: List[str],
    *,
    header: str,
    divider: str,
    rows: List[str],
    chunk_size: int = 10,
) -> None:
    if not rows:
        lines.append(header)
        lines.append(divider)
        lines.append("")
        return
    for idx in range(0, len(rows), chunk_size):
        lines.append(header)
        lines.append(divider)
        lines.extend(rows[idx : idx + chunk_size])
        lines.append("")


def _count_evals(*buckets: List[float]) -> int:
    return max((len(bucket) for bucket in buckets), default=0)


_PHASE3_LABELS_VI = {
    "candidate_after_review": "ứng viên sau review",
    "research_only": "chỉ nghiên cứu",
    "recalibrate": "cần hiệu chỉnh",
    "retire_from_strategy": "loại khỏi chiến lược",
}

_PHASE3_SHORT_LABELS_VI = {
    "candidate_after_review": "ứng viên",
    "research_only": "nghiên cứu",
    "recalibrate": "hiệu chỉnh",
    "retire_from_strategy": "loại bỏ",
}

_STRATEGY_LABELS_VI = {
    "candidate": "ứng viên",
    "watchlist": "theo dõi",
    "blocked": "chặn",
}

_BENCHMARK_LABELS_VI = {
    "materially_weaker": "yếu hơn đáng kể",
    "mixed": "pha trộn",
    "no_benchmark": "không có benchmark",
    "roughly_aligned": "tương đối sát",
    "sparse": "mẫu thưa",
}

_BENCHMARK_SHORT_LABELS_VI = {
    "materially_weaker": "yếu",
    "mixed": "pha trộn",
    "no_benchmark": "không chuẩn",
    "roughly_aligned": "sát",
    "sparse": "thưa",
}


def _map_vi(value: Any, mapping: Dict[str, str]) -> str:
    key = str(value or "").strip()
    return mapping.get(key, key.replace("_", " "))


def _format_counts(d: Dict[str, Any], *, language: str) -> str:
    items = []
    for key, value in d.items():
        label = _map_vi(key, _PHASE3_LABELS_VI if "candidate" in key or "research" in key or "recalibrate" in key or "retire" in key else _BENCHMARK_LABELS_VI) if _is_vi(language) else key
        items.append(f"{label}: {value}")
    return "; ".join(items)


def _human_label(value: Any) -> str:
    text = str(value or "").strip().replace("_", " ")
    if not text:
        return ""
    return re.sub(r"\s+", " ", text)


def _variant_suffix(pattern_key: str, canonical_key: str) -> str:
    prefix = f"{canonical_key}_"
    if not pattern_key.startswith(prefix):
        return ""
    tail = pattern_key[len(prefix) :]
    if not tail:
        return ""
    parts = [p for p in tail.split("_") if p]
    mapped = []
    for part in parts:
        low = part.lower()
        if low == "adam":
            mapped.append("A")
        elif low == "eve":
            mapped.append("E")
        else:
            mapped.append(part.capitalize())
    if mapped and all(len(x) == 1 for x in mapped):
        return "".join(mapped)
    return " ".join(mapped)


def _display_pattern(row: Dict[str, Any], *, language: str) -> str:
    pattern_key = str(row.get("pattern_key") or "")
    canonical_key = str(row.get("canonical_key") or "")
    base = _human_label(row.get("bulkowski_name") or canonical_key or pattern_key)
    variant = _variant_suffix(pattern_key, canonical_key)
    if variant and variant not in base:
        return f"{base} {variant}"
    return base


def _display_family(row: Dict[str, Any], *, language: str) -> str:
    family = str(row.get("canonical_key") or row.get("family_label") or "")
    return _human_label(family)


def _short_phase3(value: Any, *, language: str) -> str:
    return _map_vi(value, _PHASE3_SHORT_LABELS_VI) if _is_vi(language) else str(value or "")


def _short_benchmark(value: Any, *, language: str) -> str:
    return _map_vi(value, _BENCHMARK_SHORT_LABELS_VI) if _is_vi(language) else str(value or "")


def _is_vi(language: str) -> bool:
    return str(language).strip().lower() == "vi"


def _latest_run_id(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT run_id FROM scanner_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        raise SystemExit("No scanner_runs found.")
    return str(row[0])


def _load_phase3_matrix(path: Path) -> Dict[str, Dict[str, Any]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {str(row["pattern_key"]): row for row in rows}


def _load_benchmark_matrix(path: Path) -> Dict[str, Dict[str, Any]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {str(row["pattern_key"]): row for row in rows}


def _pattern_metrics(db_path: Path) -> Dict[str, Dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        run_id = _latest_run_id(conn)
        det_rows = conn.execute(
            """
            SELECT pattern_name, symbol, COALESCE(variant_code, '<null>') AS variant_code
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
                p.boundary_invalidated,
                p.target_achieved_intraday,
                p.throwback_pullback_occurred
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
    symbols_by_pattern: Dict[str, set[str]] = defaultdict(set)
    for row in det_rows:
        pat = str(row["pattern_name"])
        cur = out.setdefault(pat, {"detections": 0})
        cur["detections"] = int(cur["detections"]) + 1
        symbols_by_pattern[pat].add(str(row["symbol"]))

    buckets: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: {"move": [], "boundary": [], "target": [], "tbpb": []})
    eval_symbols: Dict[str, set[str]] = defaultdict(set)
    for row in eval_rows:
        pat = str(row["pattern_name"])
        eval_symbols[pat].add(str(row["symbol"]))
        move = _safe_float(row["max_favorable_excursion_pct"])
        if move is not None:
            buckets[pat]["move"].append(move)
        for col, key in (
            ("boundary_invalidated", "boundary"),
            ("target_achieved_intraday", "target"),
            ("throwback_pullback_occurred", "tbpb"),
        ):
            val = _safe_float(row[col])
            if val is not None:
                buckets[pat][key].append(val)

    for pat in set(out) | set(buckets):
        cur = out.setdefault(pat, {"detections": 0})
        cur["symbol_count"] = len(symbols_by_pattern.get(pat, set()))
        cur["eval_symbol_count"] = len(eval_symbols.get(pat, set()))
        moves = buckets.get(pat, {}).get("move", [])
        boundary = buckets.get(pat, {}).get("boundary", [])
        target = buckets.get(pat, {}).get("target", [])
        tbpb = buckets.get(pat, {}).get("tbpb", [])
        cur["evals"] = _count_evals(moves, boundary, target, tbpb)
        cur["median_move_pct"] = float(median(moves)) if moves else None
        cur["failure_rate_5pct"] = (sum(1.0 for x in moves if float(x) < 5.0) / len(moves) * 100.0) if moves else None
        cur["boundary_pct"] = (sum(boundary) / len(boundary) * 100.0) if boundary else None
        cur["target_hit_pct"] = (sum(target) / len(target) * 100.0) if target else None
        cur["tbpb_pct"] = (sum(tbpb) / len(tbpb) * 100.0) if tbpb else None
    return out


def _family_aggregate(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    family_map: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        key = str(row["canonical_key"])
        valid = row.get("valid") or {}
        calib = row.get("calib") or {}
        cur = family_map.setdefault(
            key,
            {
                "canonical_key": key,
                "family_label": str(row["family_label"]),
                "pattern_count": 0,
                "valid_detections": 0,
                "valid_evals": 0,
                "calib_detections": 0,
                "calib_evals": 0,
                "valid_symbols": 0,
            },
        )
        cur["pattern_count"] += 1
        cur["valid_detections"] += int(valid.get("detections") or 0)
        cur["valid_evals"] += int(valid.get("evals") or 0)
        cur["calib_detections"] += int(calib.get("detections") or 0)
        cur["calib_evals"] += int(calib.get("evals") or 0)
        cur["valid_symbols"] += int(valid.get("symbol_count") or 0)
    return sorted(family_map.values(), key=lambda x: (-int(x["valid_evals"]), -int(x["valid_detections"]), str(x["canonical_key"])))


def build_report(
    *,
    valid_db: Path,
    calib_db: Path,
    phase3_matrix: Path,
    benchmark_matrix: Path,
    out_dir: Path,
    language: str,
) -> Dict[str, Any]:
    meta = base_metadata_for_pattern_set("bulkowski_53_strict")
    phase3 = _load_phase3_matrix(phase3_matrix)
    benchmark = _load_benchmark_matrix(benchmark_matrix)
    valid = _pattern_metrics(valid_db)
    calib = _pattern_metrics(calib_db)

    rows: List[Dict[str, Any]] = []
    for pattern_key, pattern_meta in sorted(meta.items()):
        p3 = phase3.get(pattern_key, {})
        bm = benchmark.get(pattern_key, {})
        valid_row = valid.get(pattern_key, {})
        calib_row = calib.get(pattern_key, {})
        rows.append(
            {
                "pattern_key": pattern_key,
                "bulkowski_name": pattern_meta.get("bulkowski_name"),
                "canonical_key": pattern_meta.get("canonical_key"),
                "family_label": pattern_meta.get("canonical_key"),
                "chapter": pattern_meta.get("bulkowski_chapter"),
                "phase3_status": p3.get("phase3_status"),
                "strategy_gate": p3.get("strategy_gate"),
                "benchmark_status": bm.get("benchmark_status"),
                "valid": valid_row,
                "calib": calib_row,
            }
        )

    families = _family_aggregate(rows)
    rows_by_valid_evals = sorted(rows, key=lambda row: (-int((row["valid"] or {}).get("evals") or 0), -int((row["valid"] or {}).get("detections") or 0), str(row["pattern_key"])))
    rows_by_valid_symbols = sorted(rows, key=lambda row: (-int((row["valid"] or {}).get("symbol_count") or 0), -int((row["valid"] or {}).get("detections") or 0), str(row["pattern_key"])))
    rows_ex_gaps = [row for row in rows if str(row["pattern_key"]) != "gaps"]
    rows_by_strength = sorted(
        [row for row in rows_ex_gaps if int((row["valid"] or {}).get("evals") or 0) >= 20],
        key=lambda row: (
            -float((row["valid"] or {}).get("median_move_pct") or -1e9),
            float((row["valid"] or {}).get("failure_rate_5pct") or 1e9),
            -int((row["valid"] or {}).get("evals") or 0),
        ),
    )

    payload = {
        "summary": {
            "valid_db": str(valid_db.resolve()),
            "calib_db": str(calib_db.resolve()),
            "language": language,
            "pattern_count": len(rows),
            "family_count": len(families),
            "phase3_status_counts": {
                key: sum(1 for row in rows if str(row.get("phase3_status")) == key)
                for key in sorted({str(row.get("phase3_status")) for row in rows})
            },
            "benchmark_status_counts": {
                key: sum(1 for row in rows if str(row.get("benchmark_status")) == key)
                for key in sorted({str(row.get("benchmark_status")) for row in rows})
            },
        },
        "top_patterns_by_valid_evals": rows_by_valid_evals[:20],
        "top_patterns_by_symbol_count": rows_by_valid_symbols[:20],
        "top_patterns_by_strength_ex_gaps": rows_by_strength[:20],
        "family_prevalence": families[:20],
        "candidate_and_watchlist": [row for row in rows if str(row.get("strategy_gate")) in {"candidate", "watchlist"}],
        "pattern_matrix": rows,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "vietnam_research_report.json", payload)
    _write_text(out_dir / "vietnam_research_report.md", _render(payload, language=language))
    return payload


def _render(payload: Dict[str, Any], *, language: str) -> str:
    lines: List[str] = []
    summary = payload["summary"]
    vi = _is_vi(language)
    lines.append("# Báo cáo nghiên cứu mẫu hình tại Việt Nam" if vi else "# Vietnam Pattern Research Report")
    lines.append("")
    lines.append("## Tóm tắt" if vi else "## Summary")
    lines.append("")
    lines.append(f"- pattern_count: `{summary['pattern_count']}`")
    lines.append(f"- family_count: `{summary['family_count']}`")
    lines.append(f"- phase3_status_counts: `{_format_counts(summary['phase3_status_counts'], language=language)}`")
    lines.append(f"- benchmark_status_counts: `{_format_counts(summary['benchmark_status_counts'], language=language)}`")
    lines.append(f"- language: `{language}`")
    lines.append("")

    lines.append("## Candidate / Watchlist" if not vi else "## Candidate / Watchlist")
    lines.append("")
    header = (
        "| Pattern | Phase 3 | Strategy | Valid evals | Valid move | Target |"
        if not vi
        else "| Pattern | Phase 3 | Strategy | Valid evals | Median move | Target |"
    )
    divider = "|---|---|---|---:|---:|---:|"
    table_rows: List[str] = []
    for row in payload["candidate_and_watchlist"]:
        valid = row["valid"]
        table_rows.append(
            "| "
            + " | ".join(
                [
                    _display_pattern(row, language=language),
                    _short_phase3(row["phase3_status"], language=language) if vi else str(row["phase3_status"]),
                    _map_vi(row["strategy_gate"], _STRATEGY_LABELS_VI) if vi else str(row["strategy_gate"]),
                    str(int(valid.get("evals") or 0)),
                    _fmt(valid.get("median_move_pct")),
                    _fmt(valid.get("target_hit_pct")),
                ]
            )
            + " |"
        )
    _append_table_blocks(lines, header=header, divider=divider, rows=table_rows, chunk_size=8)

    lines.append("## Các pattern phổ biến tại Việt Nam (theo valid evals)" if vi else "## Common Patterns In Vietnam (By Valid Evals)")
    lines.append("")
    header = (
        "| Pattern | Valid evals | Symbols | Move | Benchmark |"
        if not vi
        else "| Pattern | Valid evals | Số mã | Median move | Benchmark |"
    )
    divider = "|---|---:|---:|---:|---|"
    table_rows = []
    for row in payload["top_patterns_by_valid_evals"]:
        valid = row["valid"]
        table_rows.append(
            "| "
            + " | ".join(
                [
                    _display_pattern(row, language=language),
                    str(int(valid.get("evals") or 0)),
                    str(int(valid.get("eval_symbol_count") or 0)),
                    _fmt(valid.get("median_move_pct")),
                    _short_benchmark(row.get("benchmark_status"), language=language) if vi else str(row.get("benchmark_status")),
                ]
            )
            + " |"
        )
    _append_table_blocks(lines, header=header, divider=divider, rows=table_rows, chunk_size=10)

    lines.append("## Các pattern phổ biến tại Việt Nam (theo độ phủ mã)" if vi else "## Common Patterns In Vietnam (By Symbol Coverage)")
    lines.append("")
    header = (
        "| Pattern | Symbols | Detections | Valid evals | Move |"
        if not vi
        else "| Pattern | Số mã | Số phát hiện | Valid evals | Median move |"
    )
    divider = "|---|---:|---:|---:|---:|"
    table_rows = []
    for row in payload["top_patterns_by_symbol_count"]:
        valid = row["valid"]
        table_rows.append(
            "| "
            + " | ".join(
                [
                    _display_pattern(row, language=language),
                    str(int(valid.get("symbol_count") or 0)),
                    str(int(valid.get("detections") or 0)),
                    str(int(valid.get("evals") or 0)),
                    _fmt(valid.get("median_move_pct")),
                ]
            )
            + " |"
        )
    _append_table_blocks(lines, header=header, divider=divider, rows=table_rows, chunk_size=10)

    lines.append("## Các pattern mạnh hơn khi bỏ gaps" if vi else "## Stronger Patterns Excluding Gaps")
    lines.append("")
    header = (
        "| Pattern | Valid evals | Move | Target | Strategy |"
        if not vi
        else "| Pattern | Valid evals | Median move | Target | Strategy |"
    )
    divider = "|---|---:|---:|---:|---|"
    table_rows = []
    for row in payload["top_patterns_by_strength_ex_gaps"]:
        valid = row["valid"]
        table_rows.append(
            "| "
            + " | ".join(
                [
                    _display_pattern(row, language=language),
                    str(int(valid.get("evals") or 0)),
                    _fmt(valid.get("median_move_pct")),
                    _fmt(valid.get("target_hit_pct")),
                    _map_vi(row.get("strategy_gate"), _STRATEGY_LABELS_VI) if vi else str(row.get("strategy_gate")),
                ]
            )
            + " |"
        )
    _append_table_blocks(lines, header=header, divider=divider, rows=table_rows, chunk_size=10)

    lines.append("## Mức độ phổ biến theo family" if vi else "## Family Prevalence")
    lines.append("")
    header = (
        "| Family | Pattern count | Valid evals | Calib evals |"
        if not vi
        else "| Family | Số pattern | Valid evals | Calib evals |"
    )
    divider = "|---|---:|---:|---:|"
    table_rows = []
    for row in payload["family_prevalence"]:
        table_rows.append(
            "| "
            + " | ".join(
                [
                    _display_family(row, language=language),
                    str(int(row["pattern_count"])),
                    str(int(row["valid_evals"])),
                    str(int(row["calib_evals"])),
                ]
            )
            + " |"
        )
    _append_table_blocks(lines, header=header, divider=divider, rows=table_rows, chunk_size=10)
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    try:
        from .legacy_guard import require_legacy_enabled  # type: ignore
    except Exception:  # pragma: no cover
        from legacy_guard import require_legacy_enabled  # type: ignore

    require_legacy_enabled("scanner/build_vietnam_research_report.py")
    parser = argparse.ArgumentParser()
    parser.add_argument("--valid-db", required=True)
    parser.add_argument("--calib-db", required=True)
    parser.add_argument("--phase3-pattern-matrix", required=True)
    parser.add_argument("--benchmark-pattern-matrix", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--language", default="en", choices=["en", "vi"])
    args = parser.parse_args()

    payload = build_report(
        valid_db=Path(args.valid_db).resolve(),
        calib_db=Path(args.calib_db).resolve(),
        phase3_matrix=Path(args.phase3_pattern_matrix).resolve(),
        benchmark_matrix=Path(args.benchmark_pattern_matrix).resolve(),
        out_dir=Path(args.out_dir).resolve(),
        language=str(args.language),
    )
    print("=== Vietnam Pattern Research Report ===")
    print(f"out_dir: {Path(args.out_dir).resolve()}")
    print(f"phase3_status_counts: {payload['summary']['phase3_status_counts']}")
    print(f"benchmark_status_counts: {payload['summary']['benchmark_status_counts']}")


if __name__ == "__main__":
    main()
