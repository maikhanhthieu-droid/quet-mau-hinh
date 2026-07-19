from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from .book_v2_readiness import chapter_readiness  # type: ignore
    from .pattern_set_metadata import base_metadata_for_pattern_set  # type: ignore
    from .review_plot_helpers import _load_symbol_ohlcv, _plot_candles, _slice_window  # type: ignore
except Exception:  # pragma: no cover
    from book_v2_readiness import chapter_readiness  # type: ignore
    from pattern_set_metadata import base_metadata_for_pattern_set  # type: ignore
    from review_plot_helpers import _load_symbol_ohlcv, _plot_candles, _slice_window  # type: ignore


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_vi(language: str) -> bool:
    return str(language).strip().lower() == "vi"


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


_PATTERN_TYPE_LABELS_VI = {
    "reversal_bullish": "đảo chiều tăng",
    "reversal_bearish": "đảo chiều giảm",
    "continuation_bullish": "tiếp diễn tăng",
    "continuation_bearish": "tiếp diễn giảm",
    "continuation_both": "tiếp diễn hai chiều",
    "indeterminate": "không xác định",
}

_BREAKOUT_DIRECTION_LABELS_VI = {
    "up": "tăng",
    "down": "giảm",
    "both": "hai chiều",
    "varies": "phụ thuộc bối cảnh",
    "depends_on_prior_trend": "phụ thuộc xu hướng trước mẫu",
}

_BENCHMARK_STATUS_LABELS_VI = {
    "roughly_aligned": "tương đối sát mốc tham chiếu",
    "mixed": "kết quả pha trộn",
    "materially_weaker": "yếu hơn đáng kể so với tham chiếu",
    "sparse": "mẫu còn thưa",
    "no_benchmark": "chưa có benchmark đối chiếu trực tiếp",
}

_PHASE3_STATUS_LABELS_VI = {
    "candidate_after_review": "ứng viên sau review",
    "research_only": "chỉ dùng cho nghiên cứu",
    "recalibrate": "cần hiệu chỉnh thêm",
    "retire_from_strategy": "loại khỏi lớp chiến lược",
}

_STRATEGY_GATE_LABELS_VI = {
    "candidate": "ứng viên chiến lược",
    "watchlist": "theo dõi thêm",
    "blocked": "chưa mở cho chiến lược",
    "retired": "đã loại khỏi chiến lược",
}

_RESEARCH_LANE_LABELS_VI = {
    "benchmark_candidate": "ứng viên benchmark/strategy",
    "active_research": "đang trong lớp nghiên cứu hoạt động",
    "recalibration_backlog": "nằm trong backlog hiệu chỉnh",
    "reference_only": "chỉ giữ làm tham chiếu",
}

_BOOK_V2_READINESS_LABELS_VI = {
    "core_research_chapter": "chương nghiên cứu lõi",
    "thin_research_chapter": "chương nghiên cứu mỏng, cần caveat",
    "strategy_appendix": "phụ lục chiến lược",
    "reference_only": "chỉ giữ làm tham chiếu",
}

_READINESS_FLAG_LABELS_VI = {
    "no_valid_evals": "không có eval ở valid",
    "thin_valid_evals": "valid còn mỏng",
    "no_calib_evals": "không có eval ở calib",
    "thin_calib_evals": "calib còn mỏng",
    "sparse_benchmark": "benchmark còn thưa",
    "materially_weaker_than_reference": "yếu hơn đáng kể so với tham chiếu",
    "needs_recalibration": "cần hiệu chỉnh lại",
    "reference_only_governance": "governance chỉ cho phép tham chiếu",
}

_VARIANT_LABELS_VI = {
    "standard": "chuẩn",
    "extended": "mở rộng",
    "five_point": "năm điểm",
    "ascending_triangle": "tam giác tăng",
    "descending_triangle": "tam giác giảm",
    "symmetrical_triangle": "tam giác cân",
    "common_gap": "gap thường",
    "continuation_gap": "gap tiếp diễn",
    "exhaustion_gap": "gap kiệt sức",
    "breakaway_gap": "gap phá vỡ",
    "common_gap_up": "gap thường tăng",
    "common_gap_down": "gap thường giảm",
    "continuation_gap_up": "gap tiếp diễn tăng",
    "continuation_gap_down": "gap tiếp diễn giảm",
    "exhaustion_gap_up": "gap kiệt sức tăng",
    "exhaustion_gap_down": "gap kiệt sức giảm",
    "breakaway_gap_up": "gap phá vỡ tăng",
    "breakaway_gap_down": "gap phá vỡ giảm",
}

_PRIOR_DESC_LABELS_VI = {
    "Must have prior downtrend before pattern formation": "cần có xu hướng giảm trước khi mẫu hình hình thành",
    "Must have prior uptrend before pattern formation": "cần có xu hướng tăng trước khi mẫu hình hình thành",
    "Must have downtrend of at least 2 months with 15%+ decline": "cần có xu hướng giảm ít nhất 2 tháng với mức giảm từ 15% trở lên",
    "Must have uptrend of at least 2 months with 15%+ advance": "cần có xu hướng tăng ít nhất 2 tháng với mức tăng từ 15% trở lên",
    "Prior trend can be up or down": "xu hướng trước mẫu có thể tăng hoặc giảm",
    "Prior trend determines expected breakout direction but not strictly required": "xu hướng trước mẫu giúp định hướng breakout kỳ vọng nhưng không bắt buộc tuyệt đối",
    "Prior trend requirements vary significantly by gap type": "yêu cầu xu hướng trước mẫu thay đổi theo từng loại gap",
}

_BASELINE_METRIC_LABELS_VI = {
    "median_move_pct": "Move TB",
    "average_rise_pct": "Rise TB",
    "failure_rate_5pct": "Fail<5",
    "tbpb_pct": "TB/PB",
    "pullback_rate_pct": "Pullback",
}

_CASE_LABELS_VI = {
    "best_case": "tốt nhất",
    "typical_case": "điển hình",
    "stress_case": "stress",
    "calib_reference": "đối chiếu calib",
}

_CASE_LABELS_EN = {
    "best_case": "best",
    "typical_case": "typical",
    "stress_case": "stress",
    "calib_reference": "calib ref",
}


def _count_evals(*buckets: List[float]) -> int:
    return max((len(bucket) for bucket in buckets), default=0)


def _map_vi(value: Any, mapping: Dict[str, str]) -> str:
    key = str(value or "").strip()
    return mapping.get(key, key.replace("_", " "))


def _human_label(value: Any) -> str:
    text = str(value or "").strip().replace("_", " ")
    return " ".join(part for part in text.split())


def _format_variant_scope(scope: Sequence[str], *, language: str) -> str:
    items = [str(item) for item in scope if str(item).strip()]
    if not items:
        return "standard" if not _is_vi(language) else "chuẩn"
    if _is_vi(language):
        return ", ".join(_map_vi(item, _VARIANT_LABELS_VI) for item in items)
    return ", ".join(items)


def _display_variant(value: Any, *, language: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return _map_vi(text, _VARIANT_LABELS_VI) if _is_vi(language) else text.replace("_", " ")


def _display_case_label(value: Any, *, language: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if _is_vi(language):
        return _CASE_LABELS_VI.get(text, text.replace("_", " "))
    return _CASE_LABELS_EN.get(text, text.replace("_", " "))


def _prior_description_vi(description: Optional[str]) -> str:
    if not description:
        return "có điều kiện xu hướng trước mẫu theo spec digitized"
    desc = str(description).strip()
    return _PRIOR_DESC_LABELS_VI.get(desc, "có điều kiện xu hướng trước mẫu theo spec digitized")


def _latest_run_id(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT run_id FROM scanner_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        raise SystemExit("No scanner_runs found.")
    return str(row[0])


def _load_matrix(path: Path) -> Dict[str, Dict[str, Any]]:
    rows = _read_json(path)
    return {str(row["pattern_key"]): row for row in rows if isinstance(row, dict) and row.get("pattern_key") is not None}


def _load_digitized_spec(spec_key: Optional[str]) -> Optional[Dict[str, Any]]:
    if not spec_key:
        return None
    path = Path("extraction_phase_1") / "digitization" / "patterns_digitized" / f"{spec_key}_digitized.json"
    if not path.exists():
        return None
    try:
        payload = _read_json(path)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _variant_scope(pattern_key: str, meta: Dict[str, Any], all_meta: Dict[str, Dict[str, Any]], spec: Optional[Dict[str, Any]]) -> List[str]:
    explicit_variant = meta.get("variant")
    if explicit_variant:
        return [str(explicit_variant)]

    canonical_key = str(meta.get("canonical_key") or pattern_key)
    sibling_variants = sorted(
        {
            str(m.get("variant"))
            for m in all_meta.values()
            if str(m.get("canonical_key") or "") == canonical_key and m.get("variant") is not None
        }
    )
    if sibling_variants:
        return sibling_variants

    variants = []
    if isinstance(spec, dict):
        variant_handling = spec.get("variant_handling")
        if isinstance(variant_handling, dict):
            for row in variant_handling.get("variants", []):
                if isinstance(row, dict) and row.get("name"):
                    variants.append(str(row["name"]))
    return variants or ["standard"]


def _describe_reference(meta: Dict[str, Any], spec: Optional[Dict[str, Any]], *, language: str) -> str:
    parts: List[str] = []
    chapter = meta.get("bulkowski_chapter")
    bulkowski_name = str(meta.get("bulkowski_name") or meta.get("pattern_key") or "")
    vi = _is_vi(language)
    if chapter is not None:
        if vi:
            parts.append(f"{bulkowski_name} (chương {chapter} theo Bulkowski)")
        else:
            parts.append(f"{bulkowski_name} (Bulkowski chapter {chapter})")
    else:
        parts.append(bulkowski_name)

    if isinstance(spec, dict):
        pattern_type = spec.get("pattern_type")
        sig = spec.get("detection_signature") or {}
        prior = spec.get("prior_trend_requirements") or {}
        breakout = spec.get("breakout_confirmation") or {}
        seq = sig.get("sequence_description")
        if pattern_type:
            parts.append(
                f"thuộc nhóm `{_map_vi(pattern_type, _PATTERN_TYPE_LABELS_VI)}`"
                if vi
                else f"digitized type: `{pattern_type}`"
            )
        if seq:
            parts.append(
                "được mô tả bằng chuỗi pivot trong spec digitized của mẫu này"
                if vi
                else f"sequence: `{seq}`"
            )
        if prior.get("description"):
            parts.append(
                f"xu hướng trước mẫu: {_prior_description_vi(prior.get('description'))}"
                if vi
                else f"prior trend: {prior.get('description')}"
            )
        if breakout.get("breakout_direction"):
            parts.append(
                f"hướng breakout kỳ vọng: `{_map_vi(breakout.get('breakout_direction'), _BREAKOUT_DIRECTION_LABELS_VI)}`"
                if vi
                else f"expected breakout direction: `{breakout.get('breakout_direction')}`"
            )
    else:
        parts.append(
            "được ánh xạ thông qua metadata scanner nội bộ, không có payload spec digitized trực tiếp"
            if vi
            else "mapped through internal scanner metadata without a digitized spec payload"
        )

    head = parts[0].strip().rstrip(".")
    tail = [part.strip().rstrip(".") for part in parts[1:] if part]
    if not tail:
        return head + "."
    return f"{head}: " + "; ".join(tail) + "."


def _describe_detector(pattern_key: str, meta: Dict[str, Any], spec: Optional[Dict[str, Any]], *, language: str) -> str:
    canonical = str(meta.get("canonical_key") or pattern_key)
    spec_key = meta.get("spec_key")
    vi = _is_vi(language)
    parts = [
        f"Dự án này ánh xạ mẫu hình này vào family chuẩn `{_human_label(canonical)}`"
        if vi
        else f"This project maps `{pattern_key}` to canonical family `{canonical}`"
    ]
    if spec_key:
        parts.append("được triển khai bằng spec digitized tương ứng của family này" if vi else f"spec: `{spec_key}`")
    if meta.get("variant") is not None:
        parts.append(f"biến thể: `{_map_vi(meta.get('variant'), _VARIANT_LABELS_VI)}`" if vi else f"variant: `{meta.get('variant')}`")

    if isinstance(spec, dict):
        geom = spec.get("geometry_constraints") or {}
        breakout = spec.get("breakout_confirmation") or {}
        width_min = geom.get("width_min_bars")
        width_max = geom.get("width_max_bars")
        height_min = geom.get("height_ratio_min")
        height_max = geom.get("height_ratio_max")
        if width_min is not None or width_max is not None:
            parts.append(
                f"độ rộng điển hình `{width_min}`-`{width_max}` bar"
                if vi
                else f"typical width `{width_min}`-`{width_max}` bars"
            )
        if height_min is not None or height_max is not None:
            parts.append(
                f"biên độ chiều cao `{height_min}`-`{height_max}` phần trăm"
                if vi
                else f"height envelope `{height_min}`-`{height_max}` percent"
            )
        if breakout.get("breakout_direction"):
            volume_required = breakout.get("volume_required")
            if vi:
                volume_text = "có yêu cầu xác nhận khối lượng" if volume_required else "không bắt buộc xác nhận khối lượng"
                parts.append(f"hướng breakout `{_map_vi(breakout.get('breakout_direction'), _BREAKOUT_DIRECTION_LABELS_VI)}` {volume_text}")
            else:
                volume_text = "with volume confirmation required" if volume_required else "without mandatory volume confirmation"
                parts.append(f"breakout direction `{breakout.get('breakout_direction')}` {volume_text}")
    head = parts[0].strip().rstrip(".")
    tail = [part.strip().rstrip(".") for part in parts[1:] if part]
    if not tail:
        return head + "."
    return f"{head}: " + "; ".join(tail) + "."


class SplitView:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.run_id = _latest_run_id(self.conn)

    def close(self) -> None:
        self.conn.close()

    def pattern_rows(self, pattern_key: str) -> List[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT
                d.symbol,
                d.pattern_id,
                d.formation_start,
                d.formation_end,
                d.breakout_date,
                d.breakout_direction,
                d.breakout_price,
                d.target_price,
                d.stop_loss_price,
                d.confidence_score,
                d.pattern_height_pct,
                d.pattern_width_bars,
                d.pivot_indices_json,
                d.variant_code,
                d.variant_confidence,
                d.variant_evidence_json,
                d.family_metrics_json,
                p.max_favorable_excursion_pct,
                p.max_adverse_excursion_pct,
                p.target_achieved_intraday,
                p.boundary_invalidated,
                p.throwback_pullback_occurred
            FROM pattern_detections d
            LEFT JOIN post_breakout_results p
              ON p.run_id = d.run_id AND p.pattern_id = d.pattern_id
            WHERE d.run_id = ? AND d.pattern_name = ?
            """,
            (self.run_id, pattern_key),
        ).fetchall()

    def metrics(self, pattern_key: str) -> Dict[str, Any]:
        det_rows = self.conn.execute(
            """
            SELECT symbol
            FROM pattern_detections
            WHERE run_id = ? AND pattern_name = ?
            """,
            (self.run_id, pattern_key),
        ).fetchall()
        eval_rows = self.conn.execute(
            """
            SELECT
                d.symbol,
                p.max_favorable_excursion_pct,
                p.boundary_invalidated,
                p.target_achieved_intraday,
                p.throwback_pullback_occurred
            FROM pattern_detections d
            JOIN post_breakout_results p
              ON p.run_id = d.run_id AND p.pattern_id = d.pattern_id
            WHERE d.run_id = ? AND d.pattern_name = ?
            """,
            (self.run_id, pattern_key),
        ).fetchall()

        symbols = {str(row["symbol"]) for row in det_rows}
        eval_symbols = {str(row["symbol"]) for row in eval_rows}
        moves: List[float] = []
        boundary: List[float] = []
        target: List[float] = []
        tbpb: List[float] = []
        for row in eval_rows:
            move = _safe_float(row["max_favorable_excursion_pct"])
            if move is not None:
                moves.append(move)
            for src, bucket in (
                ("boundary_invalidated", boundary),
                ("target_achieved_intraday", target),
                ("throwback_pullback_occurred", tbpb),
            ):
                val = _safe_float(row[src])
                if val is not None:
                    bucket.append(val)
        return {
            "detections": len(det_rows),
            "evals": _count_evals(moves, boundary, target, tbpb),
            "symbol_count": len(symbols),
            "eval_symbol_count": len(eval_symbols),
            "median_move_pct": float(median(moves)) if moves else None,
            "failure_rate_5pct": (sum(1.0 for x in moves if x < 5.0) / len(moves) * 100.0) if moves else None,
            "boundary_pct": (sum(boundary) / len(boundary) * 100.0) if boundary else None,
            "target_hit_pct": (sum(target) / len(target) * 100.0) if target else None,
            "tbpb_pct": (sum(tbpb) / len(tbpb) * 100.0) if tbpb else None,
        }

    def symbol_tendencies(self, pattern_key: str) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT
                d.symbol,
                COUNT(*) AS detections,
                COUNT(p.pattern_id) AS evals,
                AVG(p.target_achieved_intraday) * 100.0 AS target_hit_pct
            FROM pattern_detections d
            LEFT JOIN post_breakout_results p
              ON p.run_id = d.run_id AND p.pattern_id = d.pattern_id
            WHERE d.run_id = ? AND d.pattern_name = ?
            GROUP BY d.symbol
            """,
            (self.run_id, pattern_key),
        ).fetchall()

        move_rows = self.conn.execute(
            """
            SELECT d.symbol, p.max_favorable_excursion_pct
            FROM pattern_detections d
            JOIN post_breakout_results p
              ON p.run_id = d.run_id AND p.pattern_id = d.pattern_id
            WHERE d.run_id = ? AND d.pattern_name = ?
            """,
            (self.run_id, pattern_key),
        ).fetchall()
        moves_by_symbol: Dict[str, List[float]] = defaultdict(list)
        for row in move_rows:
            move = _safe_float(row["max_favorable_excursion_pct"])
            if move is not None:
                moves_by_symbol[str(row["symbol"])].append(move)

        out: List[Dict[str, Any]] = []
        for row in rows:
            symbol = str(row["symbol"])
            out.append(
                {
                    "symbol": symbol,
                    "detections": int(row["detections"] or 0),
                    "evals": int(row["evals"] or 0),
                    "median_move_pct": float(median(moves_by_symbol[symbol])) if moves_by_symbol[symbol] else None,
                    "target_hit_pct": _safe_float(row["target_hit_pct"]),
                }
            )
        out.sort(key=lambda item: (-int(item["evals"]), -int(item["detections"]), str(item["symbol"])))
        return out


def _delta_notes(
    benchmark_row: Dict[str, Any],
    valid_metrics: Dict[str, Any],
    calib_metrics: Dict[str, Any],
    *,
    language: str,
) -> List[str]:
    notes: List[str] = []
    benchmark = benchmark_row.get("benchmark")
    vi = _is_vi(language)
    if not isinstance(benchmark, dict):
        notes.append("Không có baseline benchmark cho pattern này." if vi else "No benchmark baseline is available for this pattern.")
        return notes

    b_move = _safe_float(benchmark.get("median_move_pct") or benchmark.get("average_rise_pct"))
    b_fail = _safe_float(benchmark.get("failure_rate_5pct"))
    b_tbpb = _safe_float(benchmark.get("tbpb_pct") or benchmark.get("pullback_rate_pct"))
    v_move = _safe_float(valid_metrics.get("median_move_pct"))
    v_fail = _safe_float(valid_metrics.get("failure_rate_5pct"))
    v_tbpb = _safe_float(valid_metrics.get("tbpb_pct"))
    if b_move is not None and v_move is not None:
        notes.append(
            f"Median move của split valid là `{v_move:.2f}%`, so với baseline Bulkowski `{b_move:.2f}%`."
            if vi
            else f"Valid median move is `{v_move:.2f}%` versus Bulkowski baseline `{b_move:.2f}%`."
        )
    if b_fail is not None and v_fail is not None:
        notes.append(
            f"Tỷ lệ fail-under-5 của split valid là `{v_fail:.2f}%`, so với baseline `{b_fail:.2f}%`."
            if vi
            else f"Valid fail-under-5 rate is `{v_fail:.2f}%` versus baseline `{b_fail:.2f}%`."
        )
    if b_tbpb is not None and v_tbpb is not None:
        notes.append(
            f"Tỷ lệ throwback/pullback của split valid là `{v_tbpb:.2f}%`, so với baseline `{b_tbpb:.2f}%`."
            if vi
            else f"Valid throwback/pullback rate is `{v_tbpb:.2f}%` versus baseline `{b_tbpb:.2f}%`."
        )
    if int(calib_metrics.get("evals") or 0) == 0:
        notes.append(
            "Split calibration hiện không có case evaluated trong final snapshot."
            if vi
            else "Calibration split has no evaluated cases in the current final snapshot."
        )
    elif int(valid_metrics.get("evals") or 0) == 0:
        notes.append(
            "Split validation hiện không có case evaluated trong final snapshot."
            if vi
            else "Validation split has no evaluated cases in the current final snapshot."
        )
    return notes


def _case_note(row: Dict[str, Any], *, language: str) -> str:
    parts: List[str] = []
    vi = _is_vi(language)
    if row.get("target_achieved_intraday") == 1:
        parts.append("đạt target" if vi else "target hit")
    if row.get("boundary_invalidated") == 1:
        parts.append("vi phạm boundary" if vi else "boundary break")
    move = _safe_float(row.get("max_favorable_excursion_pct"))
    if move is not None:
        parts.append(f"MFE `{move:.2f}%`")
    adverse = _safe_float(row.get("max_adverse_excursion_pct"))
    if adverse is not None:
        parts.append(f"MAE `{adverse:.2f}%`")
    return "; ".join(parts)


def _case_outcome(row: Dict[str, Any], *, language: str) -> str:
    vi = _is_vi(language)
    flags: List[str] = []
    if row.get("target_achieved_intraday") == 1:
        flags.append("target" if vi else "target")
    if row.get("boundary_invalidated") == 1:
        flags.append("boundary" if vi else "boundary")
    return "/".join(flags)


def _pick_case(
    rows: Sequence[Dict[str, Any]],
    *,
    used_ids: set[str],
    label: str,
    rule: str,
    language: str,
) -> Optional[Dict[str, Any]]:
    if not rows:
        return None
    for row in rows:
        pid = str(row["pattern_id"])
        if pid in used_ids:
            continue
        used_ids.add(pid)
        return {
            "pattern_id": str(row["pattern_id"]),
            "symbol": str(row["symbol"]),
            "split": str(row["split"]),
            "breakout_date": row.get("breakout_date"),
            "pattern_variant": row.get("variant_code"),
            "quality_label": label,
            "note": _case_note(row, language=language),
            "outcome": _case_outcome(row, language=language),
            "mfe_pct": _safe_float(row.get("max_favorable_excursion_pct")),
            "mae_pct": _safe_float(row.get("max_adverse_excursion_pct")),
            "formation_start": row.get("formation_start"),
            "formation_end": row.get("formation_end"),
            "breakout_direction": row.get("breakout_direction"),
            "target_price": _safe_float(row.get("target_price")),
            "stop_loss_price": _safe_float(row.get("stop_loss_price")),
            "pivot_indices": row.get("pivot_indices") or [],
            "image_path": None,
        }
    return None


def _select_cases(valid_rows: List[Dict[str, Any]], calib_rows: List[Dict[str, Any]], *, language: str) -> List[Dict[str, Any]]:
    used: set[str] = set()
    out: List[Dict[str, Any]] = []
    vi = _is_vi(language)

    best_valid = sorted(
        [
            row for row in valid_rows
            if _safe_float(row.get("max_favorable_excursion_pct")) is not None
            and int(row.get("target_achieved_intraday") or 0) == 1
            and int(row.get("boundary_invalidated") or 0) == 0
        ],
        key=lambda row: (
            -float(_safe_float(row.get("max_favorable_excursion_pct")) or -1e9),
            float(_safe_float(row.get("max_adverse_excursion_pct")) or 1e9),
        ),
    )
    picked = _pick_case(
        best_valid,
        used_ids=used,
        label="best_case",
        rule=(
            "Mẫu valid chất lượng cao nhất với target hit và không vi phạm boundary"
            if vi
            else "Highest-quality valid survivor with target hit and no boundary invalidation"
        ),
        language=language,
    )
    if picked is not None:
        out.append(picked)

    valid_moves = [_safe_float(row.get("max_favorable_excursion_pct")) for row in valid_rows]
    valid_moves = [row for row in valid_moves if row is not None]
    if valid_moves:
        med = float(median(valid_moves))
        typical_valid = sorted(
            [row for row in valid_rows if _safe_float(row.get("max_favorable_excursion_pct")) is not None],
            key=lambda row: (
                abs(float(_safe_float(row.get("max_favorable_excursion_pct")) or 0.0) - med)
                + (5.0 if int(row.get("boundary_invalidated") or 0) == 1 else 0.0)
                + (2.0 if int(row.get("target_achieved_intraday") or 0) == 0 else 0.0),
                int(row.get("boundary_invalidated") or 0),
                -int(row.get("target_achieved_intraday") or 0),
            ),
        )
        picked = _pick_case(
            typical_valid,
            used_ids=used,
            label="typical_case",
            rule="Mẫu valid gần median move nhất" if vi else "Valid case closest to median move",
            language=language,
        )
        if picked is not None:
            out.append(picked)

    stress_valid = sorted(
        [
            row for row in valid_rows
            if int(row.get("boundary_invalidated") or 0) == 1
            or int(row.get("target_achieved_intraday") or 0) == 0
            or float(_safe_float(row.get("max_adverse_excursion_pct")) or 0.0) >= 10.0
        ],
        key=lambda row: (
            -int(row.get("boundary_invalidated") or 0),
            -(float(_safe_float(row.get("max_adverse_excursion_pct")) or 0.0)),
            float(_safe_float(row.get("max_favorable_excursion_pct")) or 0.0),
        ),
    )
    picked = _pick_case(
        stress_valid,
        used_ids=used,
        label="stress_case",
        rule=(
            "Mẫu valid stress thể hiện invalidation hoặc adverse excursion cao"
            if vi
            else "Valid stress case showing invalidation or elevated adverse excursion"
        ),
        language=language,
    )
    if picked is not None:
        out.append(picked)

    calib_reference = sorted(
        [row for row in calib_rows if _safe_float(row.get("max_favorable_excursion_pct")) is not None],
        key=lambda row: (
            -int(row.get("target_achieved_intraday") or 0),
            int(row.get("boundary_invalidated") or 0),
            -float(_safe_float(row.get("max_favorable_excursion_pct")) or -1e9),
        ),
    )
    picked = _pick_case(
        calib_reference,
        used_ids=used,
        label="calib_reference",
        rule="Mẫu tham chiếu calibration để so với split valid" if vi else "Calibration reference case for split comparison",
        language=language,
    )
    if picked is not None:
        out.append(picked)

    return out


def _rows_as_dicts(rows: Sequence[sqlite3.Row], *, split: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        pivots = d.get("pivot_indices_json")
        if isinstance(pivots, str) and pivots:
            try:
                parsed = json.loads(pivots)
                d["pivot_indices"] = parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                d["pivot_indices"] = []
        else:
            d["pivot_indices"] = []
        d["split"] = split
        out.append(d)
    return out


def _merge_symbol_tendencies(valid_rows: List[Dict[str, Any]], calib_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for row in list(valid_rows) + list(calib_rows):
        symbol = str(row["symbol"])
        cur = merged.setdefault(symbol, {"symbol": symbol, "detections": 0, "evals": 0, "moves": [], "targets": []})
        cur["detections"] += int(row.get("detections") or 0)
        cur["evals"] += int(row.get("evals") or 0)
        move = _safe_float(row.get("median_move_pct"))
        if move is not None:
            cur["moves"].append(move)
        target = _safe_float(row.get("target_hit_pct"))
        if target is not None:
            cur["targets"].append(target)

    out: List[Dict[str, Any]] = []
    for symbol, row in merged.items():
        out.append(
            {
                "symbol": symbol,
                "detections": int(row["detections"]),
                "evals": int(row["evals"]),
                "median_move_pct": float(median(row["moves"])) if row["moves"] else None,
                "target_hit_pct": float(median(row["targets"])) if row["targets"] else None,
            }
        )
    out.sort(key=lambda row: (-int(row["evals"]), -int(row["detections"]), str(row["symbol"])))
    return out


def _render_case_figures(
    *,
    price_db: Optional[Path],
    pattern_dir: Path,
    bulkowski_name: str,
    cases: List[Dict[str, Any]],
    language: str,
    pre_bars: int = 30,
    post_bars: int = 30,
    max_figures: int = 3,
) -> List[Dict[str, Any]]:
    if price_db is None or not price_db.exists():
        return cases

    figures_dir = pattern_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    symbol_cache: Dict[str, Any] = {}
    rendered = 0

    for case in cases:
        if rendered >= max_figures:
            break
        symbol = str(case.get("symbol") or "")
        formation_start = case.get("formation_start")
        formation_end = case.get("formation_end")
        if not symbol or not formation_start or not formation_end:
            continue
        try:
            if symbol not in symbol_cache:
                symbol_cache[symbol] = _load_symbol_ohlcv(str(price_db), symbol)
            df = symbol_cache[symbol]
            if df is None or getattr(df, "empty", True):
                continue
            window_df, fs, fe, bd, offset = _slice_window(
                df,
                formation_start=str(formation_start),
                formation_end=str(formation_end),
                breakout_date=case.get("breakout_date"),
                pre_bars=int(pre_bars),
                post_bars=int(post_bars),
            )
            if window_df is None or getattr(window_df, "empty", True):
                continue
            pivots = [int(i) - int(offset) for i in (case.get("pivot_indices") or []) if isinstance(i, (int, float))]
            safe_name = (
                f"{case.get('quality_label')}_{case.get('split')}_{symbol}_{case.get('breakout_date') or 'na'}"
                .replace("/", "-")
                .replace(" ", "_")
            )
            out_png = figures_dir / f"{safe_name}.png"
            _plot_candles(
                window_df,
                formation_start=fs,
                formation_end=fe,
                breakout_date=bd,
                breakout_direction=case.get("breakout_direction"),
                target_price=case.get("target_price"),
                stop_loss_price=case.get("stop_loss_price"),
                pivot_local_indices=pivots,
                title=f"{bulkowski_name} | {symbol} | {_display_case_label(case.get('quality_label'), language=language)}",
                out_png=str(out_png),
            )
            case["image_path"] = f"figures/{out_png.name}"
            rendered += 1
        except Exception:
            continue
    return cases


def _render_core(payload: Dict[str, Any], *, language: str) -> str:
    summary = payload["summary"]
    reference = payload["reference"]
    governance = payload["governance"]
    benchmark = payload["benchmark"]
    prevalence = payload["vietnam_prevalence"]
    outcomes = payload["vietnam_outcomes"]
    cases = payload["representative_cases"]
    symbols = payload["symbol_tendencies"]
    vi = _is_vi(language)
    benchmark_label = _map_vi(benchmark["benchmark_status"], _BENCHMARK_STATUS_LABELS_VI) if vi else benchmark["benchmark_status"]
    phase3_label = _map_vi(governance["phase3_status"], _PHASE3_STATUS_LABELS_VI) if vi else governance["phase3_status"]
    strategy_label = _map_vi(governance["strategy_gate"], _STRATEGY_GATE_LABELS_VI) if vi else governance["strategy_gate"]
    readiness = governance.get("book_v2_readiness") or "reference_only"
    readiness_label = _map_vi(readiness, _BOOK_V2_READINESS_LABELS_VI) if vi else readiness
    readiness_flags = [str(flag) for flag in governance.get("readiness_flags") or []]
    readiness_flag_labels = [
        _map_vi(flag, _READINESS_FLAG_LABELS_VI) if vi else flag
        for flag in readiness_flags
    ]
    family_action = governance.get("family_action")
    family_action_label = _map_vi(family_action, _RESEARCH_LANE_LABELS_VI) if (vi and family_action) else family_action

    lines: List[str] = []
    lines.append(f"# {summary['bulkowski_name'] or summary['pattern_key']}")
    lines.append("")
    if vi:
        lines.append(
            f"*Chương `{summary.get('bulkowski_chapter')}`, family `{_human_label(summary['canonical_key'])}`, "
            f"trạng thái nghiên cứu `{phase3_label}`, cửa chiến lược `{strategy_label}`, "
            f"mức benchmark `{benchmark_label}`, readiness `{readiness_label}`.*"
        )
    else:
        lines.append(
            f"*Chapter `{summary.get('bulkowski_chapter')}`, family `{summary['canonical_key']}`, "
            f"research status `{phase3_label}`, strategy gate `{strategy_label}`, "
            f"benchmark status `{benchmark_label}`, readiness `{readiness_label}`.*"
        )
    lines.append("")

    lines.append("## Định nghĩa mẫu hình" if vi else "## Pattern Definition")
    lines.append("")
    lines.append(reference["bulkowski_reference"])
    lines.append("")
    lines.append(reference["detector_interpretation"])
    lines.append("")
    lines.append(
        f"- phạm vi biến thể: `{_format_variant_scope(reference['variant_scope'], language=language)}`"
        if vi
        else f"- variant_scope: `{_format_variant_scope(reference['variant_scope'], language=language)}`"
    )
    lines.append("")

    lines.append("## Mức độ phổ biến tại Việt Nam" if vi else "## Vietnam Prevalence")
    lines.append("")
    lines.append("| Split | Detect | Eval | Symbols |" if not vi else "| Split | Phát hiện | Eval | Mã |")
    lines.append("|---|---:|---:|---:|")
    for split in ("valid", "calib"):
        row = prevalence[split]
        lines.append(f"| {split} | {int(row['detections'])} | {int(row['evals'])} | {int(row['symbol_count'])} |")
    lines.append("")

    lines.append("## Hồ sơ kết quả tại Việt Nam" if vi else "## Vietnam Outcome Profile")
    lines.append("")
    lines.append(
        "| Split | Median move | Fail<5 | Boundary | Target | TB/PB |"
        if not vi
        else "| Split | Median move | Fail<5 | Boundary | Target | TB/PB |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|")
    for split in ("valid", "calib"):
        row = outcomes[split]
        lines.append(
            f"| {split} | {_fmt(row.get('median_move_pct'))} | {_fmt(row.get('failure_rate_5pct'))} | "
            f"{_fmt(row.get('boundary_pct'))} | {_fmt(row.get('target_hit_pct'))} | {_fmt(row.get('tbpb_pct'))} |"
        )
    lines.append("")

    lines.append("## So với benchmark Bulkowski" if vi else "## Benchmark Versus Bulkowski")
    lines.append("")
    lines.append(f"- mức benchmark hiện tại: `{benchmark_label}`" if vi else f"- benchmark_status: `{benchmark_label}`")
    baseline = benchmark.get("bulkowski_baseline") or {}
    baseline_rows: List[Tuple[str, str]] = []
    if isinstance(baseline, dict) and baseline:
        for key in ("median_move_pct", "average_rise_pct", "failure_rate_5pct", "tbpb_pct", "pullback_rate_pct"):
            if baseline.get(key) is not None:
                label = _BASELINE_METRIC_LABELS_VI.get(key, key) if vi else key
                baseline_rows.append((label, _fmt(_safe_float(baseline.get(key)))))
    if baseline_rows:
        lines.append("")
        lines.append("| Chỉ số baseline | Giá trị |" if vi else "| Baseline metric | Value |")
        lines.append("|---|---:|")
        for key, value in baseline_rows:
            lines.append(f"| {key} | {value} |")
        lines.append("")
    elif vi and benchmark["benchmark_status"] == "no_benchmark":
        lines.append("- chưa có benchmark số liệu trực tiếp để đối chiếu cho mẫu này")
        lines.append("")
    for note in benchmark.get("delta_notes", []):
        lines.append(f"- {note}")
    lines.append("")

    lines.append("## Mẫu đại diện" if vi else "## Representative Cases")
    lines.append("")
    if cases:
        lines.append(
            "| Nhãn | Split | Mã | Ngày | KQ | MFE | MAE |"
            if vi
            else "| Label | Split | Symbol | Date | Outcome | MFE | MAE |"
        )
        lines.append("|---|---|---|---|---|---:|---:|")
        for row in cases:
            lines.append(
                f"| {_display_case_label(row.get('quality_label'), language=language)} | {row.get('split') or ''} | {row.get('symbol') or ''} | "
                f"{row.get('breakout_date') or ''} | {row.get('outcome') or ''} | {_fmt(row.get('mfe_pct'))} | {_fmt(row.get('mae_pct'))} |"
            )
    else:
        lines.append("Không tìm thấy mẫu evaluated đại diện trong final snapshot." if vi else "No representative evaluated cases were found in the final snapshot.")
    lines.append("")
    figure_cases = [row for row in cases if row.get("image_path")]
    if figure_cases:
        lines.append("### Hình minh họa" if vi else "### Figures")
        lines.append("")
        for row in figure_cases:
            caption = f"{_display_case_label(row.get('quality_label'), language=language).capitalize()} | {row.get('split')} | {row.get('symbol')} | {row.get('breakout_date') or ''}"
            lines.append(f"*{caption}*")
            lines.append("")
            lines.append(f"![]({row['image_path']})")
            lines.append("")

    lines.append("## Xu hướng theo mã cổ phiếu" if vi else "## Symbol Tendencies")
    lines.append("")
    if symbols:
        lines.append(
            "| Mã | Eval | Median move | Target |"
            if vi
            else "| Symbol | Evals | Median move | Target |"
        )
        lines.append("|---|---:|---:|---:|")
        for row in symbols[:10]:
            lines.append(
                f"| {row['symbol']} | {int(row['evals'])} | "
                f"{_fmt(row.get('median_move_pct'))} | {_fmt(row.get('target_hit_pct'))} |"
            )
    else:
        lines.append("Không có thống kê xu hướng theo mã." if vi else "No symbol tendencies were available.")
    lines.append("")

    lines.append("## Trạng thái nghiên cứu hiện tại" if vi else "## Current Research Status")
    lines.append("")
    lines.append(f"- readiness Book v2: `{readiness_label}`" if vi else f"- book_v2_readiness: `{readiness_label}`")
    lines.append(f"- trạng thái phase 3: `{phase3_label}`" if vi else f"- phase3_status: `{phase3_label}`")
    lines.append(f"- cửa chiến lược: `{strategy_label}`" if vi else f"- strategy_gate: `{strategy_label}`")
    if family_action_label:
        lines.append(f"- lớp nghiên cứu: `{family_action_label}`" if vi else f"- research_lane: `{family_action_label}`")
    if readiness_flag_labels:
        flags_text = ", ".join(f"`{flag}`" for flag in readiness_flag_labels)
        lines.append(f"- cờ caveat: {flags_text}" if vi else f"- readiness_flags: {flags_text}")
    lines.append("")

    return "\n".join(lines).strip() + "\n"


def build_monographs(
    *,
    valid_db: Path,
    calib_db: Path,
    phase3_matrix: Path,
    benchmark_matrix: Path,
    out_dir: Path,
    price_db: Optional[Path],
    patterns: Optional[List[str]],
    language: str,
) -> Dict[str, Any]:
    meta = base_metadata_for_pattern_set("bulkowski_53_strict")
    phase3 = _load_matrix(phase3_matrix)
    benchmark = _load_matrix(benchmark_matrix)

    selected = patterns or sorted(meta.keys(), key=lambda key: (int(meta[key].get("bulkowski_chapter") or 10**9), key))
    valid_view = SplitView(valid_db)
    calib_view = SplitView(calib_db)
    try:
        index_rows: List[Dict[str, Any]] = []
        for pattern_key in selected:
            pattern_meta = dict(meta.get(pattern_key, {}))
            pattern_meta["pattern_key"] = pattern_key
            spec = _load_digitized_spec(pattern_meta.get("spec_key"))
            valid_metrics = valid_view.metrics(pattern_key)
            calib_metrics = calib_view.metrics(pattern_key)
            valid_case_rows = _rows_as_dicts(valid_view.pattern_rows(pattern_key), split="valid")
            calib_case_rows = _rows_as_dicts(calib_view.pattern_rows(pattern_key), split="calib")
            cases = _select_cases(valid_case_rows, calib_case_rows, language=language)
            pattern_dir = out_dir / pattern_key
            cases = _render_case_figures(
                price_db=price_db,
                pattern_dir=pattern_dir,
                bulkowski_name=str(pattern_meta.get("bulkowski_name") or pattern_key),
                cases=cases,
                language=language,
            )
            symbol_rows = _merge_symbol_tendencies(
                valid_view.symbol_tendencies(pattern_key),
                calib_view.symbol_tendencies(pattern_key),
            )[:10]
            phase3_row = phase3.get(pattern_key, {})
            benchmark_row = benchmark.get(pattern_key, {})
            readiness, readiness_flags = chapter_readiness(
                valid_metrics=valid_metrics,
                calib_metrics=calib_metrics,
                phase3_row=phase3_row,
                benchmark_row=benchmark_row,
            )

            payload = {
                "summary": {
                    "pattern_key": pattern_key,
                    "canonical_key": str(pattern_meta.get("canonical_key") or pattern_key),
                    "bulkowski_name": pattern_meta.get("bulkowski_name"),
                    "bulkowski_chapter": pattern_meta.get("bulkowski_chapter"),
                    "generated_at": _utc_now_iso(),
                    "language": language,
                },
                "reference": {
                    "bulkowski_reference": _describe_reference(pattern_meta, spec, language=language),
                    "detector_interpretation": _describe_detector(pattern_key, pattern_meta, spec, language=language),
                    "variant_scope": _variant_scope(pattern_key, pattern_meta, meta, spec),
                },
                "governance": {
                    "phase3_status": str(phase3_row.get("phase3_status") or "unknown"),
                    "strategy_gate": str(phase3_row.get("strategy_gate") or "blocked"),
                    "family_action": phase3_row.get("research_lane"),
                    "book_v2_readiness": readiness,
                    "readiness_flags": readiness_flags,
                },
                "benchmark": {
                    "benchmark_status": str(benchmark_row.get("benchmark_status") or "no_benchmark"),
                    "bulkowski_baseline": benchmark_row.get("benchmark"),
                    "vietnam_observed": {
                        "valid": valid_metrics,
                        "calib": calib_metrics,
                    },
                    "delta_notes": _delta_notes(benchmark_row, valid_metrics, calib_metrics, language=language),
                },
                "vietnam_prevalence": {
                    "valid": {
                        "detections": int(valid_metrics.get("detections") or 0),
                        "evals": int(valid_metrics.get("evals") or 0),
                        "symbol_count": int(valid_metrics.get("symbol_count") or 0),
                    },
                    "calib": {
                        "detections": int(calib_metrics.get("detections") or 0),
                        "evals": int(calib_metrics.get("evals") or 0),
                        "symbol_count": int(calib_metrics.get("symbol_count") or 0),
                    },
                },
                "vietnam_outcomes": {
                    "valid": {
                        "median_move_pct": valid_metrics.get("median_move_pct"),
                        "failure_rate_5pct": valid_metrics.get("failure_rate_5pct"),
                        "boundary_pct": valid_metrics.get("boundary_pct"),
                        "target_hit_pct": valid_metrics.get("target_hit_pct"),
                        "tbpb_pct": valid_metrics.get("tbpb_pct"),
                    },
                    "calib": {
                        "median_move_pct": calib_metrics.get("median_move_pct"),
                        "failure_rate_5pct": calib_metrics.get("failure_rate_5pct"),
                        "boundary_pct": calib_metrics.get("boundary_pct"),
                        "target_hit_pct": calib_metrics.get("target_hit_pct"),
                        "tbpb_pct": calib_metrics.get("tbpb_pct"),
                    },
                },
                "representative_cases": cases,
                "symbol_tendencies": symbol_rows,
            }

            _write_json(pattern_dir / "chapter_payload.json", payload)
            _write_text(pattern_dir / "chapter_core.md", _render_core(payload, language=language))
            index_rows.append(
                {
                    "pattern_key": pattern_key,
                    "bulkowski_name": pattern_meta.get("bulkowski_name"),
                    "canonical_key": pattern_meta.get("canonical_key"),
                    "bulkowski_chapter": pattern_meta.get("bulkowski_chapter"),
                    "phase3_status": payload["governance"]["phase3_status"],
                    "strategy_gate": payload["governance"]["strategy_gate"],
                    "book_v2_readiness": payload["governance"]["book_v2_readiness"],
                    "benchmark_status": payload["benchmark"]["benchmark_status"],
                    "payload_path": str((pattern_dir / "chapter_payload.json").resolve()),
                    "chapter_core_path": str((pattern_dir / "chapter_core.md").resolve()),
                }
            )
    finally:
        valid_view.close()
        calib_view.close()

    index_payload = {
        "generated_at": _utc_now_iso(),
        "language": language,
        "pattern_count": len(index_rows),
        "patterns": index_rows,
    }
    _write_json(out_dir / "index.json", index_payload)
    lines = [
        "# Chỉ mục monograph deterministic của Book V2" if _is_vi(language) else "# Book V2 Deterministic Monograph Index",
        "",
        f"- pattern_count: `{len(index_rows)}`",
        f"- language: `{language}`",
        "",
        "| Chương | Pattern | Family | Readiness | Phase 3 | Strategy | Benchmark |"
        if _is_vi(language)
        else "| Chapter | Pattern | Family | Readiness | Phase 3 | Strategy | Benchmark |",
        "|---:|---|---|---|---|---|---|",
    ]
    for row in index_rows:
        lines.append(
            f"| {row.get('bulkowski_chapter') or ''} | {row['pattern_key']} | {row.get('canonical_key') or ''} | "
            f"{row['book_v2_readiness']} | {row['phase3_status']} | {row['strategy_gate']} | {row['benchmark_status']} |"
        )
    lines.append("")
    _write_text(out_dir / "index.md", "\n".join(lines))
    return index_payload


def main() -> None:
    try:
        from .legacy_guard import require_legacy_enabled  # type: ignore
    except Exception:  # pragma: no cover
        from legacy_guard import require_legacy_enabled  # type: ignore

    require_legacy_enabled("scanner/build_pattern_monographs.py")
    parser = argparse.ArgumentParser(description="Build deterministic Book v2 monograph payloads and core chapters.")
    parser.add_argument("--valid-db", required=True, help="Final unified valid results DB")
    parser.add_argument("--calib-db", required=True, help="Final unified calib results DB")
    parser.add_argument("--phase3-pattern-matrix", required=True, help="Final phase3 pattern matrix JSON")
    parser.add_argument("--benchmark-pattern-matrix", required=True, help="Final benchmark pattern matrix JSON")
    parser.add_argument("--out-dir", required=True, help="Output directory for deterministic monographs")
    parser.add_argument("--price-db", help="Optional OHLCV SQLite DB for chapter figure rendering")
    parser.add_argument(
        "--patterns",
        default=None,
        help="Optional comma-separated pattern list. Defaults to all bulkowski_53_strict patterns.",
    )
    parser.add_argument("--language", default="en", choices=["en", "vi"], help="Output language for the chapter core renderer")
    args = parser.parse_args()

    patterns = None
    if args.patterns:
        patterns = [part.strip() for part in str(args.patterns).split(",") if part.strip()]

    build_monographs(
        valid_db=Path(args.valid_db),
        calib_db=Path(args.calib_db),
        phase3_matrix=Path(args.phase3_pattern_matrix),
        benchmark_matrix=Path(args.benchmark_pattern_matrix),
        out_dir=Path(args.out_dir),
        price_db=Path(args.price_db).resolve() if args.price_db else None,
        patterns=patterns,
        language=str(args.language),
    )


if __name__ == "__main__":
    main()
