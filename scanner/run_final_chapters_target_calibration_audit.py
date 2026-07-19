"""Audit target bands across final chapters before promoting a base target.

This script is intentionally read-only for chapter artifacts. It compares the
published target rows with source-grounded target provenance when available, so
we do not label 0.5x as a true base target just because it is convenient.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Mapping


DEFAULT_MANIFEST = Path("artifacts/final_chapters/final_chapters_manifest.json")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/final_chapters_target_calibration_audit")


def _read_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, Mapping) else {}


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def _target_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    target = payload.get("target_calibration") if isinstance(payload.get("target_calibration"), Mapping) else {}
    rows = target.get("rows") if isinstance(target.get("rows"), list) else []
    return [row for row in rows if isinstance(row, Mapping) and _num(row.get("target_multiple")) is not None]


def _source_profile(pattern_id: str, source_notes: Mapping[str, Any]) -> dict[str, Any]:
    """Return source benchmark metadata.

    `source_multiple` is only filled when the source rule is comparable to the
    local height/pole multiple used in target rows. Wedge source measure rules
    use formation extremes, so they are intentionally marked as not comparable.
    """

    rules = source_notes.get("source_rules") if isinstance(source_notes.get("source_rules"), list) else []
    text = " ".join(
        f"{rule.get('rule_id', '')} {rule.get('short_excerpt', '')} {rule.get('implementation_mapping', '')}"
        for rule in rules
        if isinstance(rule, Mapping)
    ).lower()
    profile: dict[str, Any] = {
        "source_target_kind": "unknown",
        "source_multiple": None,
        "source_hit_low": None,
        "source_hit_high": None,
        "source_note": "source target benchmark not extracted",
    }

    if pattern_id == "high_tight_flags" or "htf.target.half_prior_move" in text or "half the prior advance" in text:
        profile.update(
            {
                "source_target_kind": "adjusted_fractional_prior_move",
                "source_multiple": 0.5,
                "source_note": "High-and-Tight Flags source measure rule uses about half the prior advance.",
            }
        )
        return profile

    measure = source_notes.get("thepatternsite_measure_rule")
    if isinstance(measure, Mapping) and ("flags" in pattern_id):
        profile.update(
            {
                "source_target_kind": "adjusted_fractional_pole",
                "source_multiple": 0.46,
                "source_note": "ThePatternSite measure rule uses 46% of flagpole.",
            }
        )
        stats = source_notes.get("bulkowski_book_2e_stats") if isinstance(source_notes.get("bulkowski_book_2e_stats"), Mapping) else {}
        key = "upward_breakouts" if pattern_id == "bull_flags" else "downward_breakouts"
        row = stats.get(key) if isinstance(stats.get(key), Mapping) else {}
        values = row.get("percentage_meeting_price_target_bull_bear_pct")
        if isinstance(values, list) and values:
            nums = [float(v) for v in values if _num(v) is not None]
            if nums:
                profile["source_hit_low"] = min(nums)
                profile["source_hit_high"] = max(nums)
        return profile

    if "wedge" in pattern_id and ("formation high" in text or "formation low" in text):
        profile.update(
            {
                "source_target_kind": "formation_extreme_not_multiple",
                "source_note": "Source measure rule uses formation high/low, not a fixed height multiple.",
            }
        )
        return profile

    if pattern_id == "cup_with_handle" and ("half cup height" in text or "half-height" in text or "0.5" in text):
        profile.update(
            {
                "source_target_kind": "adjusted_fractional_cup_height",
                "source_multiple": 0.5,
                "source_note": "Cup-with-Handle source keeps full cup height as benchmark but explicitly notes half cup height as the more practical target.",
            }
        )
        return profile

    if pattern_id == "cup_with_handle_inverted" and ("handle height" in text or "chiều cao tay cầm" in text):
        profile.update(
            {
                "source_target_kind": "handle_height_measure_rule",
                "source_multiple": 1.0,
                "source_note": "Inverted Cup-with-Handle source target is handle height, not full cup height.",
            }
        )
        return profile

    if pattern_id in {"measured_move_up", "measured_move_down"}:
        profile.update(
            {
                "source_target_kind": "full_first_leg_with_half_leg_calibration",
                "source_multiple": 1.0,
                "source_note": "Measured Move source rule projects the first leg from the correction extreme; the chapter keeps 0.5x as conservative/local base and 1.0x as the full source benchmark.",
            }
        )
        return profile

    if pattern_id.startswith("scallops_"):
        profile.update(
            {
                "source_target_kind": "full_height_measure_rule",
                "source_multiple": 1.0,
                "source_note": "Scallop source measure rules use pattern height as the full benchmark; local fractional bands are calibration diagnostics.",
            }
        )
        return profile

    if pattern_id in {"three_falling_peaks", "three_rising_valleys"}:
        profile.update(
            {
                "source_target_kind": "full_height_measure_rule",
                "source_multiple": 1.0,
                "source_note": "Three Peaks/Valleys source target is a full pattern-height projection; local 0.5x band is a conservative Vietnam calibration diagnostic.",
            }
        )
        return profile

    if pattern_id in {"triple_tops", "triple_bottoms"}:
        profile.update(
            {
                "source_target_kind": "full_height_measure_rule",
                "source_multiple": 1.0,
                "source_note": "Triple Tops/Bottoms source target is a full pattern-height projection from the confirmation boundary; local 0.5x band is a conservative Vietnam calibration diagnostic.",
            }
        )
        return profile

    if pattern_id in {"bump_and_run_reversal_bottoms", "bump_and_run_reversal_tops"}:
        profile.update(
            {
                "source_target_kind": "trendline_to_bump_height_measure_rule",
                "source_multiple": 1.0,
                "source_note": "Bump-and-Run source target projects the distance from the bump extreme back to the lead-in trendline; local 0.5x and 0.75x bands are Vietnam calibration diagnostics.",
            }
        )
        return profile

    if pattern_id in {"area_gaps", "breakaway_gaps", "continuation_gaps", "exhaustion_gaps"}:
        profile.update(
            {
                "source_target_kind": "gap_close_and_gap_size_diagnostic",
                "source_multiple": 1.0,
                "source_note": "Gap source chapters primarily benchmark gap closure/fill behavior by subtype. The local 0.5x and 1.0x gap-size rows are diagnostic secondary targets, not the main source statistic.",
            }
        )
        return profile

    if pattern_id == "inside_day":
        profile.update(
            {
                "source_target_kind": "inside_range_short_term_benchmark",
                "source_multiple": 1.0,
                "source_note": "Inside Day source defines a short-term breakout from the inside-day high/low; local 0.5x and 1.0x inside-range rows are diagnostic target bands.",
            }
        )
        return profile

    if pattern_id in {"rising_three_methods", "falling_three_methods"}:
        profile.update(
            {
                "source_target_kind": "first_candle_range_continuation_benchmark",
                "source_multiple": 1.0,
                "source_note": "Three Methods source defines a five-candle continuation structure. Local 0.5x and 1.0x rows use the first candle range as the compact continuation benchmark.",
            }
        )
        return profile

    if pattern_id in {"broadening_wedges_ascending", "broadening_wedges_descending"}:
        profile.update(
            {
                "source_target_kind": "formation_extreme_not_multiple",
                "source_note": "Broadening wedge source measure rules use formation extremes for the primary breakout side; fractional bands are local diagnostics.",
            }
        )
        return profile

    if pattern_id.startswith("broadening_"):
        profile.update(
            {
                "source_target_kind": "full_height_measure_rule",
                "source_multiple": 1.0,
                "source_note": "Broadening source measure rules use formation height or right-angled formation height as the full benchmark.",
            }
        )
        return profile

    if "target.measure_rule" in text or "measure-rule target" in text or "measure rule" in text or "formation height" in text:
        profile.update(
            {
                "source_target_kind": "full_height_measure_rule",
                "source_multiple": 1.0,
                "source_note": "Source rule is a full-height projection; local fractional bands are calibration diagnostics.",
            }
        )
        return profile

    return profile


def _pick_rows(rows: list[Mapping[str, Any]], source_multiple: float | None) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
    if not rows:
        return None, None
    if source_multiple is None:
        source_row = None
    else:
        source_row = min(rows, key=lambda row: abs(float(row.get("target_multiple")) - source_multiple))
    selected = max(
        rows,
        key=lambda row: (
            float(row.get("target_first_before_adverse_5pct_rate") or -1),
            float(row.get("target_hit_rate") or -1),
            float(row.get("target_multiple") or -1),
        ),
    )
    return source_row, selected


def _classify(row: Mapping[str, Any] | None, source_profile: Mapping[str, Any]) -> str:
    if row is None:
        if source_profile.get("source_target_kind") == "formation_extreme_not_multiple":
            return "NEEDS_GEOMETRY_SPECIFIC_CALIBRATION"
        return "NEEDS_SOURCE_EXTRACTION"
    hit = _num(row.get("target_hit_rate"))
    first = _num(row.get("target_first_before_adverse_5pct_rate"))
    source_low = _num(source_profile.get("source_hit_low"))
    source_high = _num(source_profile.get("source_hit_high"))
    if source_low is not None and source_high is not None and hit is not None:
        if source_low <= hit <= source_high:
            return "SOURCE_HIT_ALIGNED"
        if hit > source_high:
            return "VIETNAM_HIT_HIGHER_THAN_SOURCE_RANGE"
        return "VIETNAM_HIT_LOWER_THAN_SOURCE_RANGE"
    if hit is not None and first is not None:
        if source_profile.get("source_target_kind") == "full_height_measure_rule" and hit >= 65 and first >= 35:
            return "SOURCE_FULL_HEIGHT_STRONG"
        if source_profile.get("source_target_kind") == "full_height_measure_rule" and hit >= 55:
            return "SOURCE_FULL_HEIGHT_USABLE"
        if hit >= 70 and first >= 35:
            return "LOCAL_BAND_STRONG_BUT_SOURCE_HIT_UNKNOWN"
        if hit >= 55:
            return "LOCAL_BAND_USABLE_BUT_SOURCE_HIT_UNKNOWN"
    return "WEAK_OR_UNPROVEN_BASE"


def _recommend(row: Mapping[str, Any] | None, path_pick: Mapping[str, Any] | None, source_profile: Mapping[str, Any], status: str) -> str:
    kind = str(source_profile.get("source_target_kind") or "")
    if kind == "adjusted_fractional_pole":
        return "Giữ mốc nguồn 0,46x làm base; 0,5x chỉ là bản làm tròn/phụ."
    if kind == "adjusted_fractional_prior_move":
        return "Giữ mốc nguồn 0,5x nhịp tăng trước làm base; các mốc cao hơn chỉ là đối chiếu căng."
    if kind == "full_first_leg_with_half_leg_calibration":
        return "Giữ 0,5x nhịp đầu làm mốc cơ sở thận trọng; 1,0x là mốc nguồn đầy đủ để đối chiếu sức chạy."
    if kind == "full_height_measure_rule":
        if status == "LOCAL_BAND_STRONG_WITH_WEAK_SOURCE_FULL_HEIGHT":
            return "Không phong 1,0x; dùng mốc địa phương đã hiệu chuẩn làm base và giữ 1,0x làm đối chiếu căng."
        if status == "SOURCE_FULL_HEIGHT_STRONG":
            return "Có thể nâng 1,0x thành mốc nguồn/headline; giữ 0,5x làm mốc thận trọng."
        if status == "SOURCE_FULL_HEIGHT_USABLE":
            return "1,0x dùng được nhưng cần caveat; 0,5x vẫn là mốc thận trọng."
        return "Không nên phong 1,0x; dùng target sensitivity và kiểm thêm robustness."
    if kind == "formation_extreme_not_multiple":
        return "Không quyết định bằng 0,5x; cần calibration riêng theo mốc cực trị hình học."
    return "Cần trích measure rule/target stats từ nguồn gốc trước khi chọn base."


def audit_final_chapter_targets(*, manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows_out: list[dict[str, Any]] = []
    band_rows_out: list[dict[str, Any]] = []

    for chapter in manifest.get("chapters") or []:
        if not isinstance(chapter, Mapping):
            continue
        pattern_id = str(chapter.get("pattern_id") or "")
        payload_path = Path(str(chapter.get("payload") or ""))
        source_notes_path = Path(str(chapter.get("source_notes") or ""))
        if not payload_path.exists():
            continue
        payload = _read_json(payload_path)
        source_notes = _read_json(source_notes_path) if source_notes_path.exists() else {}
        target_rows = _target_rows(payload)
        source = _source_profile(pattern_id, source_notes)
        source_row, path_pick = _pick_rows(target_rows, _num(source.get("source_multiple")))
        selected_multiple = _num((payload.get("target_calibration") or {}).get("selected_base_target_multiple")) if isinstance(payload.get("target_calibration"), Mapping) else None

        for row in target_rows:
            band_rows_out.append(
                {
                    "pattern_id": pattern_id,
                    "family": chapter.get("family"),
                    "target_multiple": row.get("target_multiple"),
                    "target_role": row.get("target_role"),
                    "n": row.get("n"),
                    "target_hit_rate": row.get("target_hit_rate"),
                    "target_first_before_adverse_5pct_rate": row.get("target_first_before_adverse_5pct_rate"),
                    "failure_5pct_rate": row.get("failure_5pct_rate"),
                    "mfe_mae_median_ratio": row.get("mfe_mae_median_ratio"),
                }
            )

        if source_row:
            source_multiple_gap = abs(float(source_row.get("target_multiple")) - float(source.get("source_multiple")))
        else:
            source_multiple_gap = None
        status = _classify(source_row or path_pick, source)
        if (
            status == "WEAK_OR_UNPROVEN_BASE"
            and source.get("source_target_kind") == "full_height_measure_rule"
            and path_pick is not None
            and _num(path_pick.get("target_hit_rate")) is not None
            and _num(path_pick.get("target_first_before_adverse_5pct_rate")) is not None
            and float(path_pick.get("target_hit_rate")) >= 65
            and float(path_pick.get("target_first_before_adverse_5pct_rate")) >= 35
        ):
            status = "LOCAL_BAND_STRONG_WITH_WEAK_SOURCE_FULL_HEIGHT"
        rows_out.append(
            {
                "pattern_id": pattern_id,
                "family": chapter.get("family"),
                "classification": chapter.get("classification"),
                "source_target_kind": source.get("source_target_kind"),
                "source_multiple": source.get("source_multiple"),
                "source_hit_low": source.get("source_hit_low"),
                "source_hit_high": source.get("source_hit_high"),
                "selected_base_target_multiple": selected_multiple,
                "nearest_source_band": source_row.get("target_multiple") if source_row else None,
                "nearest_source_band_hit_rate": source_row.get("target_hit_rate") if source_row else None,
                "nearest_source_band_target_first": source_row.get("target_first_before_adverse_5pct_rate") if source_row else None,
                "source_multiple_gap": source_multiple_gap,
                "best_path_band": path_pick.get("target_multiple") if path_pick else None,
                "best_path_band_hit_rate": path_pick.get("target_hit_rate") if path_pick else None,
                "best_path_band_target_first": path_pick.get("target_first_before_adverse_5pct_rate") if path_pick else None,
                "status": status,
                "recommended_action": _recommend(source_row, path_pick, source, status),
                "source_note": source.get("source_note"),
            }
        )

    summary = {
        "audit_id": "final_chapters_target_calibration_audit_v1",
        "status": "PASS",
        "chapter_count": len(rows_out),
        "source_comparable_count": sum(1 for row in rows_out if row["source_multiple"] is not None),
        "formation_extreme_count": sum(1 for row in rows_out if row["source_target_kind"] == "formation_extreme_not_multiple"),
        "needs_source_extraction_count": sum(1 for row in rows_out if row["status"] == "NEEDS_SOURCE_EXTRACTION"),
        "rows": rows_out,
    }

    def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
        if not rows:
            path.write_text("", encoding="utf-8")
            return
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    write_csv(out_dir / "chapter_target_calibration_summary.csv", rows_out)
    write_csv(out_dir / "chapter_target_band_rows.csv", band_rows_out)
    (out_dir / "chapter_target_calibration_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    md_lines = [
        "# Final chapters target calibration audit",
        "",
        "This is a read-only audit. It does not promote a base target.",
        "",
        "| Pattern | Source kind | Source multiple | Selected | Nearest source band | Source-band hit | Best path band | Status | Recommendation |",
        "|---|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in rows_out:
        md_lines.append(
            "| {pattern_id} | {source_target_kind} | {source_multiple} | {selected_base_target_multiple} | {nearest_source_band} | {nearest_source_band_hit_rate} | {best_path_band} | {status} | {recommended_action} |".format(
                **{key: ("" if value is None else value) for key, value in row.items()}
            )
        )
    (out_dir / "chapter_target_calibration_summary.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit final chapter target calibration against source benchmarks.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    summary = audit_final_chapter_targets(manifest_path=Path(args.manifest), out_dir=Path(args.out_dir))
    print(json.dumps({key: summary[key] for key in ("status", "chapter_count", "source_comparable_count", "formation_extreme_count", "needs_source_extraction_count")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
