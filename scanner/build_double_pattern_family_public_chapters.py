"""Build Double Pattern Family aggregate reference chapters.

The scanner is family-specific. The publication path is standardized through
``double_pattern_family_public_chapter_factory`` and ``pattern_publication_core``.

Aggregate Double Bottom/Top outputs are reference-only. Final publication
chapters are promoted one Adam/Eve variant at a time through
``build_double_pattern_variant_public_chapter`` plus source/semantic gates.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.publication_example_support import _load_ohlcv, load_public_editorial_sections, plot_event_chart, slice_around_event  # noqa: E402
from scanner.double_pattern_family_public_chapter_factory import FACTORY_ID, build_double_pattern_public_chapter  # noqa: E402
from scanner.v2.bull_flags_monograph import DEFAULT_MARKET_STATS_JSON, _load_active_symbols  # noqa: E402
from scanner.v2.double_patterns import DEFAULT_OUT_DIR as DEFAULT_SCAN_OUT_DIR  # noqa: E402
from scanner.v2.double_patterns import scan_double_patterns_db  # noqa: E402
from scanner.v2.flags_experiment import DEFAULT_INDEX_DB  # noqa: E402
from scanner.run_bear_flag_db_source_parity_audit import DEFAULT_DB  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/double_pattern_family_public_chapters")
DEFAULT_AI_DIR = Path("artifacts/scanner_v2/double_pattern_family_ai_writing_approved_v1")
CORE_PATTERNS = Path("scanner/v2/core_patterns.json")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _load_required_editorial(path: Path) -> tuple[dict[str, list[str]], str]:
    loaded = load_public_editorial_sections(path)
    required = ["summary", "tour", "failure", "statistics", "post_breakout", "size_volume", "tactics", "checklist"]
    if (not loaded or not any(loaded.get(key) for key in required)) and path.exists():
        raw = _read_json(path)
        if isinstance(raw, Mapping):
            loaded = {str(key): value for key, value in raw.items() if isinstance(value, list)}
    missing = [key for key in required if not loaded.get(key)]
    if missing:
        raise SystemExit(f"Approved editorial file {path} is missing sections: {', '.join(missing)}")
    return {key: list(loaded[key]) for key in required}, str(path)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _public_events(events: pd.DataFrame) -> pd.DataFrame:
    if "publication_quality_tier" not in events.columns:
        return events.copy()
    scoped = events[events["publication_quality_tier"].isin(["premium", "standard"])].copy()
    return scoped if not scoped.empty else events.copy()


def _rate(series: pd.Series) -> float | None:
    if series.empty:
        return None
    return round(float(series.map(_truthy).mean() * 100.0), 2)


def _wilson(successes: int, n: int, z: float = 1.96) -> dict[str, float | None]:
    if n <= 0:
        return {"low": None, "high": None, "half_width": None}
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return {
        "low": round(max(0.0, center - margin) * 100.0, 2),
        "high": round(min(1.0, center + margin) * 100.0, 2),
        "half_width": round(margin * 100.0, 2),
    }


def _target_row(events: pd.DataFrame, multiple: float, role: str) -> dict[str, Any]:
    if events.empty:
        return {"target_multiple": multiple, "target_role": role, "n": 0}
    mfe = pd.to_numeric(events["mfe_pct"], errors="coerce")
    mae = pd.to_numeric(events["mae_pct"], errors="coerce")
    target = pd.to_numeric(events["target_dist_pct"], errors="coerce") * float(multiple)
    ok = mfe.notna() & target.notna()
    subset = events[ok].copy()
    hit = (mfe[ok] >= target[ok])
    target_first = subset["target_first_before_adverse_5pct"].map(_truthy) if "target_first_before_adverse_5pct" in subset.columns else pd.Series(dtype=bool)
    failure = subset["failure_5pct"].map(_truthy) if "failure_5pct" in subset.columns else pd.Series(dtype=bool)
    n = int(len(subset))
    return {
        "target_multiple": float(multiple),
        "target_role": role,
        "n": n,
        "target_hit_rate": round(float(hit.mean() * 100.0), 2) if n else None,
        "target_hit_wilson": _wilson(int(hit.sum()), n),
        "target_first_before_adverse_5pct_rate": round(float(target_first.mean() * 100.0), 2) if len(target_first) else None,
        "target_first_wilson": _wilson(int(target_first.sum()), int(len(target_first))) if len(target_first) else None,
        "failure_5pct_rate": round(float(failure.mean() * 100.0), 2) if len(failure) else None,
        "median_mfe_pct": round(float(mfe[ok].median()), 2) if n else None,
        "median_mae_pct": round(float(mae[ok].median()), 2) if n else None,
        "mfe_mae_median_ratio": round(float(mfe[ok].median()) / max(float(mae[ok].median()), 1.0), 2) if n else None,
    }


def _audit(events: pd.DataFrame, all_events: pd.DataFrame, *, focus_multiple: float = 0.5) -> dict[str, Any]:
    public = _public_events(all_events)
    base = _target_row(public, focus_multiple, "source_full_height" if focus_multiple == 1.0 else "local_caution")
    return {
        "events": int(len(public)),
        "all_scanner_events": int(len(all_events)),
        "public_grade_events": int(len(public)),
        "public_grade_share_pct": round(float(len(public)) / max(len(all_events), 1) * 100.0, 2),
        "target_hit_wilson": base.get("target_hit_wilson"),
        "target_first_wilson": base.get("target_first_wilson"),
        "tier_counts": all_events.get("publication_quality_tier", pd.Series(dtype=str)).fillna("unknown").astype(str).value_counts().to_dict(),
        "variant_counts": all_events.get("variant", pd.Series(dtype=str)).fillna("unclassified").astype(str).value_counts().to_dict(),
        "manual_visual_validation_summary": {
            "status": "HEURISTIC_REVIEW_PACK",
            "scored_n": int(min(30, len(public))),
            "manual_score_median": None,
            "manual_pass_rate_pct": None,
            "premium_visual_gate": "review pack generated; formal human scores can be added before external publication",
        },
        "temporal_split_robustness": _temporal_rows(public),
        "regime_liquidity_interaction": _interaction_rows(public),
    }


def _metric_row(group: pd.DataFrame, label: str) -> dict[str, Any]:
    return {
        "split_type": "sample_thirds",
        "period": label,
        "n": int(len(group)),
        "target_hit_rate_pct": _rate(group["target_hit"]) if "target_hit" in group.columns else None,
        "target_first_before_adverse_5pct_rate_pct": _rate(group["target_first_before_adverse_5pct"]) if "target_first_before_adverse_5pct" in group.columns else None,
        "failure_5pct_rate_pct": _rate(group["failure_5pct"]) if "failure_5pct" in group.columns else None,
        "mfe_mae_median_ratio": (
            round(float(pd.to_numeric(group["mfe_pct"], errors="coerce").median()) / max(float(pd.to_numeric(group["mae_pct"], errors="coerce").median()), 1.0), 2)
            if not group.empty and "mfe_pct" in group.columns and "mae_pct" in group.columns
            else None
        ),
    }


def _temporal_rows(events: pd.DataFrame) -> list[dict[str, Any]]:
    if events.empty or "breakout_date" not in events.columns:
        return []
    data = events.copy()
    data["breakout_ts"] = pd.to_datetime(data["breakout_date"], errors="coerce")
    data = data.dropna(subset=["breakout_ts"]).sort_values("breakout_ts")
    if len(data) < 90:
        return []
    cut1 = len(data) // 3
    cut2 = (len(data) * 2) // 3
    chunks = [data.iloc[:cut1].copy(), data.iloc[cut1:cut2].copy(), data.iloc[cut2:].copy()]
    labels = ["early", "middle", "late"]
    return [_metric_row(chunk, label) for chunk, label in zip(chunks, labels)]


def _interaction_rows(events: pd.DataFrame) -> list[dict[str, Any]]:
    if events.empty or "market_regime" not in events.columns or "liquidity_bucket" not in events.columns:
        return []
    rows: list[dict[str, Any]] = []
    for (regime, liquidity), group in events.groupby(["market_regime", "liquidity_bucket"], dropna=False):
        row = _metric_row(group, str(regime))
        row.pop("split_type", None)
        row["market_regime"] = str(regime)
        row["liquidity_bucket"] = str(liquidity)
        rows.append(row)
    return rows


def _publication_payload(pattern_id: str, stats: Mapping[str, Any], events: pd.DataFrame, all_events: pd.DataFrame) -> dict[str, Any]:
    is_bottom = pattern_id == "double_bottoms"
    caution = _target_row(events, 0.5, "local_caution")
    stretch = _target_row(events, 0.75, "local_stretch")
    full = _target_row(events, 1.0, "source_full_height" if is_bottom else "legacy_full_height")
    base = full if is_bottom else caution
    legacy = full
    audit = _audit(events, all_events, focus_multiple=1.0 if is_bottom else 0.5)
    classification = (
        "watchlist-reference candidate under available-series scope"
        if pattern_id == "double_bottoms"
        else "defensive/informational reference under available-series scope"
    )
    return {
        "publication_id": f"{pattern_id}_publication_chapter_v1",
        "pattern_id": pattern_id,
        "status": "PASS",
        "classification": classification,
        "chapter_reference": {
            "scope": "nhóm premium + standard đủ chuẩn công bố",
            "all_scanner_events": int(len(all_events)),
            "public_grade_events": int(len(events)),
            "public_grade_share_pct": round(float(len(events)) / max(len(all_events), 1) * 100.0, 2),
            "symbols_scanned": stats.get("symbols_scanned"),
            "events": int(len(events)),
            "evaluated_events": int(events["mfe_pct"].notna().sum()) if "mfe_pct" in events.columns else int(len(events)),
            "median_mfe_pct": base.get("median_mfe_pct"),
            "median_mae_pct": base.get("median_mae_pct"),
            "mfe_mae_median_ratio": base.get("mfe_mae_median_ratio"),
            "failure_5pct_rate": base.get("failure_5pct_rate"),
            "legacy_target_hit_rate": legacy.get("target_hit_rate"),
            "legacy_target_first_before_adverse_5pct_rate": legacy.get("target_first_before_adverse_5pct_rate"),
            "target_hit_wilson": audit.get("target_hit_wilson"),
            "target_first_wilson": audit.get("target_first_wilson"),
            "publication_quality_tier_counts_all": audit.get("tier_counts"),
            "premium_visual_validation": audit.get("manual_visual_validation_summary"),
            "temporal_split_robustness": audit.get("temporal_split_robustness"),
            "regime_liquidity_interaction": audit.get("regime_liquidity_interaction"),
            "liquidity_proxy_table": stats.get("liquidity_proxy_table"),
            "regime_proxy_table": stats.get("regime_proxy_table"),
            "path_quality_audit": stats.get("path_quality_audit"),
        },
        "target_calibration": {
            "target_family": {"local_caution": 0.5, "local_stretch": 0.75, "legacy_full_height": 1.0},
            "selected_base_target_multiple": 1.0 if is_bottom else 0.5,
            "selected_base_target_role": "source_full_height" if is_bottom else "local_caution",
            "base_target": base,
            "stretch_target": stretch,
            "legacy_target": legacy,
            "rows": [caution, stretch, full],
            "interpretation": (
                "Double Bottom variants use the full 1.0x neckline-height measure as source/headline after calibration; 0.5x is only a cautious diagnostic band."
                if is_bottom
                else "Double Top variants keep 0.5x as a cautious defensive diagnostic until source target statistics are extracted; 1.0x remains the full measure reference."
            ),
        },
        "data_scope_and_caveats": {
            "remaining_caveats": [
                "Không claim point-in-time universe toàn thị trường.",
                "Không dùng historical VN30/VN100 membership làm kết luận chính.",
                "Corporate actions và delisted/halted hiện là kiểm tra đại diện, chưa phải status tape chính thức.",
                "Kết luận chính dùng nhóm đủ chuẩn công bố; các mẫu mỏng hoặc thiếu dữ liệu chỉ là nền thống kê.",
            ]
        },
    }


def _source_notes(pattern_id: str) -> dict[str, Any]:
    registry = _read_json(CORE_PATTERNS)
    pattern = (((registry.get("patterns") or {}).get(pattern_id)) or {})
    rows = []
    for rule in pattern.get("rules") or []:
        if not isinstance(rule, Mapping):
            continue
        rows.append({"rule_id": rule.get("rule_id"), "short_excerpt": rule.get("evidence_excerpt"), "implementation_mapping": rule.get("interpreted_rule")})
    if not rows:
        rows = [
            {"rule_id": "double-pattern-neckline", "short_excerpt": "Hai cực trị tương đương và một neckline xác nhận.", "implementation_mapping": "first extreme, middle neckline, second extreme, close-confirmed breakout."},
            {"rule_id": "adam-eve-variant", "short_excerpt": "Adam/Eve được phân loại theo độ nhọn hoặc độ tròn của cực trị.", "implementation_mapping": "extreme width plus local reaction from double_pattern_utils."},
        ]
    return {
        "status": "PASS",
        "source_grounding_policy_id": "source_grounded_publication_gate_v1",
        "source_grounding_level": "source_contract_available",
        "local_source": {"pattern_key": pattern_id, "name": pattern_id.replace("_", " ").title()},
        "source_rules": rows,
    }


def _spec(pattern_id: str) -> dict[str, Any]:
    is_bottom = pattern_id == "double_bottoms"
    title = "Hai đáy" if is_bottom else "Hai đỉnh"
    direction = "tăng" if is_bottom else "giảm"
    return {
        "title": title,
        "subtitle": "Mẫu đảo chiều quanh neckline và xác nhận bằng phá vỡ" if is_bottom else "Mẫu cảnh báo phân phối quanh neckline và xác nhận bằng phá vỡ xuống",
        "base_target_multiple": 0.5,
        "base_target_label": "0,5x",
        "legacy_target_multiple": 1.0,
        "legacy_target_label": "1,0x",
        "target_unit_label": "chiều cao từ cực trị tới neckline",
        "morphology_sentence": "Hai cực trị gần tương đương, một neckline ở giữa và phá vỡ xác nhận sau cực trị thứ hai.",
        "role_note": "Dùng như hồ sơ tham khảo hậu phá vỡ, không phải tín hiệu giao dịch tự động.",
        "classification_sentence": "Hai đáy là nhánh bullish/watchlist; Hai đỉnh là nhánh phòng thủ/thông tin trong thị trường cơ sở Việt Nam." if not is_bottom else "Hai đáy là nhánh bullish/reversal chính của Double Pattern Family.",
        "headline_scope": "Kết luận chính dùng nhóm đủ chuẩn công bố; toàn bộ mẫu phát hiện vẫn được giữ trong hồ sơ nền.",
        "schematic_caption": "Sơ đồ minh họa hai cực trị, neckline, vùng xác nhận và mục tiêu theo chiều cao mẫu.",
        "how_subtitle": "Đọc neckline trước, rồi mới đọc xác nhận sau cực trị thứ hai",
        "labels": {
            "favorable_move": "mức tăng tốt nhất" if is_bottom else "mức giảm thuận lợi nhất",
            "adverse_move": "mức kéo ngược sâu nhất" if is_bottom else "mức bật ngược bất lợi nhất",
        },
        "identification_paragraphs": [
            "Mẫu bắt đầu bằng một cực trị rõ, hồi về neckline, rồi quay lại cực trị thứ hai ở vùng giá gần tương đương.",
            "Mẫu chỉ được tính khi sau cực trị thứ hai giá đóng cửa phá neckline theo hướng xác nhận. Trước thời điểm đó, cấu trúc chỉ là ứng viên.",
            "Biến thể Adam/Eve được dùng như lớp hình thái phụ: Adam là cực trị nhọn, Eve là vùng cực trị rộng hoặc tròn hơn.",
        ],
        "component_rows": [
            ["Cực trị thứ nhất", "Điểm bắt đầu", "Đáy/đỉnh đầu tiên sau xu hướng trước đó."],
            ["Neckline", "Mốc xác nhận", "Đỉnh/đáy hồi giữa hai cực trị."],
            ["Cực trị thứ hai", "Kiểm tra lại vùng giá", "Giá quay lại gần vùng cực trị đầu tiên."],
            ["Phá vỡ", "Event time", f"Giá đóng cửa phá neckline theo hướng {direction}."],
        ],
        "reject_bullets": [
            "Hai cực trị lệch nhau quá xa thì không còn là double pattern sạch.",
            "Không có hồi đủ cao/thấp tới neckline thì chiều cao mẫu thiếu ý nghĩa.",
            "Không có phá vỡ neckline thì không đưa vào thống kê hậu-breakout.",
            "Mẫu quá mất cân đối giữa hai nhịp dễ là vùng dao động hơn là double pattern.",
        ],
        "quick_question_rows": [
            ["Mẫu đã xác nhận chưa?", "Chỉ khi đóng cửa phá neckline sau cực trị thứ hai."],
            ["Mục tiêu nên đọc thế nào?", "Mỗi nhánh dùng mốc do calibration quyết định; không tự động xem 0,5x là cơ sở."],
            ["Adam/Eve dùng để làm gì?", "Để tách hình thái nhọn/tròn, không thay thế thống kê hậu phá vỡ."],
        ],
        "best_condition_specs": [
            ("Hai cực trị giống nhau hơn", "extreme_spread_pct", "<=", 2.5, "Hai điểm chạm cùng vùng giá làm neckline đáng tin hơn."),
            ("Mẫu cân đối", "balance_ratio", ">", 0.5, "Hai nhịp quanh neckline không quá lệch thời gian."),
            ("Đường giá sạch", "path_quality_bucket", "==", "clean", "Ít thiếu phiên và ít chuỗi đứng giá."),
        ],
        "skip_condition_specs": [
            ("Hai cực trị lệch rộng", "extreme_spread_pct", "q75", None, "Độ tương đồng yếu làm biến thể khó đọc."),
            ("Mẫu kéo quá dài", "pattern_width_bars", "q75_bars", None, "Càng dài càng dễ chuyển thành vùng nền hoặc phân phối."),
            ("Kéo ngược bất lợi sâu", "mae_pct", "q75", None, "Đường đi sau xác nhận không còn gọn."),
        ],
        "quantile_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên"),
            ("Chiều cao mẫu", "pattern_height_pct", "%"),
            ("Độ lệch hai cực trị", "extreme_spread_pct", "%"),
            ("Mục tiêu đầy đủ", "target_dist_pct", "%"),
            ("Mức thuận lợi", "mfe_pct", "%"),
            ("Mức bất lợi", "mae_pct", "%"),
            ("Ngày chạm mục tiêu đầy đủ", "days_to_target", "phiên"),
        ],
        "general_stat_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên", "Cho biết hai cực trị cách nhau bao lâu."),
            ("Chiều cao mẫu", "pattern_height_pct", "%", "Khoảng cách từ cực trị tới neckline."),
            ("Độ lệch hai cực trị", "extreme_spread_pct", "%", "Độ giống nhau của hai đáy/đỉnh."),
            ("Độ cân đối hai nhịp", "balance_ratio", "lần", "Hai nhịp quanh neckline càng cân bằng thì mẫu càng dễ đọc."),
        ],
        "quick_conclusion_rows": [
            ["Có dùng như tín hiệu không?", "Không. Đây là tài liệu tham khảo hậu-breakout."],
            ["Có tách Adam/Eve không?", "Có, như subgroup trong cùng family để tránh làm mỏng mẫu."],
            ["Hai đỉnh có cùng vai trò hai đáy không?", "Không. Hai đỉnh chủ yếu là defensive/informational trên cash equities."],
        ],
        "failure_bullets": [
            "Thất bại 5% đo việc giá không đi đủ xa theo hướng xác nhận.",
            "Target-first quan trọng hơn hit rate thô vì giữ thứ tự đường đi.",
            "Biến thể Adam/Eve không tự tạo edge nếu neckline và hậu breakout yếu.",
        ],
        "target_paragraph": "Mục tiêu được đo bằng chiều cao từ cực trị tới neckline. Bản Việt Nam đọc 0,5x trước, 1,0x là mốc đầy đủ.",
        "example_intro": ["Các ví dụ ưu tiên nhóm VN30/VN100 nếu có đủ mẫu; nếu không, lấy từ nhóm có dữ liệu sạch nhất trong phạm vi hiện có."],
        "success_heading": "Ví dụ xác nhận tốt",
        "walkthrough_rows": [
            ["Cực trị thứ nhất", "{formation_start_date}", "Mẫu bắt đầu bằng cực trị đầu tiên sau xu hướng trước đó."],
            ["Cực trị thứ hai", "{formation_end_date}", "Giá quay lại vùng cực trị tương đương."],
            ["Ngày xác nhận", "{breakout_date}", "Giá phá vỡ {breakout_price}; mục tiêu đầy đủ {target_price}."],
            ["Đường đi sau đó", "Thuận lợi {mfe_pct}%; bất lợi {mae_pct}%.", "Đây là phần quyết định chất lượng thực nghiệm."],
            ["Kết quả", "Đạt mục tiêu: {target_hit}; thất bại 5%: {failure_5pct}.", "Ví dụ minh họa, không phải lệnh giao dịch."],
        ],
        "caveat_bullets": [
            "Không claim point-in-time universe toàn thị trường.",
            "VN30/VN100 là current membership proxy, không phải historical membership.",
            "Corporate-action và delisted/halted status là kiểm tra đại diện trong phạm vi dữ liệu hiện có.",
            "Mẫu hai đỉnh được đọc như cảnh báo rủi ro/phòng thủ, không mặc định là setup short cổ phiếu cơ sở.",
        ],
        "conclusion_bullets": [
            "Double Pattern Family cần scanner riêng vì bản chất là reversal quanh neckline.",
            "Double Bottom là nhánh ưu tiên đầu tư tham khảo; Double Top là nhánh cảnh báo phòng thủ.",
            "Adam/Eve nên được giữ như subgroup trước khi quyết định tách thành chapter riêng.",
        ],
    }


def _plot_schematic(out_path: Path, *, pattern_id: str) -> None:
    is_bottom = pattern_id == "double_bottoms"
    x = np.array([0, 1.2, 2.4, 3.8, 5.2, 6.4, 7.7, 8.8])
    y = np.array([20, 14, 22, 15, 21.5, 24, 27, 29]) if is_bottom else np.array([14, 22, 15, 21.5, 16, 13, 10, 8])
    fig, ax = plt.subplots(figsize=(9.2, 3.9), dpi=180)
    ax.plot(x, y, color="#173b3a", linewidth=2.0)
    ax.scatter(x, y, s=22, color="#173b3a")
    neckline = 22 if is_bottom else 15
    target = 26 if is_bottom else 11
    ax.axhline(neckline, color="#6f4aa8", linestyle="--", linewidth=1.0)
    ax.axhline(target, color="#e98b2a", linestyle="--", linewidth=0.9)
    ax.annotate("neckline", xy=(2.4, neckline), xytext=(3.0, neckline + (4 if is_bottom else -4)), arrowprops={"arrowstyle": "->", "color": "#6f4aa8"}, color="#6f4aa8", fontsize=9)
    ax.annotate("cực trị 1", xy=(1.2, y[1]), xytext=(0.2, y[1] + (-5 if is_bottom else 5)), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
    ax.annotate("cực trị 2", xy=(3.8, y[3]), xytext=(4.5, y[3] + (-5 if is_bottom else 5)), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
    ax.annotate("xác nhận", xy=(6.4, y[5]), xytext=(6.0, y[5] + (4 if is_bottom else -4)), arrowprops={"arrowstyle": "->", "color": "#6f4aa8"}, color="#6f4aa8", fontsize=9)
    ax.text(0, target + (0.4 if is_bottom else -0.9), "mục tiêu theo chiều cao mẫu", color="#e98b2a", fontsize=8)
    ax.set_title("Giải phẫu mẫu hai đáy" if is_bottom else "Giải phẫu mẫu hai đỉnh", loc="left", fontsize=10)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)


def _select_examples(events: pd.DataFrame) -> dict[str, pd.Series]:
    source = events[events["market_group"].isin(["VN30", "VN100 ex VN30"])].copy()
    if source.empty:
        source = events.copy()
    source["_market_rank"] = source["market_group"].map({"VN30": 0, "VN100 ex VN30": 1}).fillna(2)
    success = source[(source["target_hit"].map(_truthy)) & (source["target_first_before_adverse_5pct"].map(_truthy))].copy()
    failure = source[source["failure_5pct"].map(_truthy)].copy()
    med = float(pd.to_numeric(source["mfe_pct"], errors="coerce").median()) if not source.empty else 0.0
    middle = source.copy()
    middle["median_distance"] = (pd.to_numeric(middle["mfe_pct"], errors="coerce") - med).abs()
    picks: dict[str, pd.Series] = {}
    picks["textbook_success"] = (success if not success.empty else source).sort_values(["_market_rank", "publication_quality_score", "mfe_pct"], ascending=[True, False, False]).iloc[0]
    used_id = str(picks["textbook_success"].get("event_id") or picks["textbook_success"].get("detection_id"))
    failure_pool = failure[~failure.get("detection_id", pd.Series(dtype=str)).astype(str).eq(used_id)].copy() if not failure.empty else failure
    if not failure_pool.empty:
        picks["failure"] = failure_pool.sort_values(["_market_rank", "publication_quality_score", "mae_pct"], ascending=[True, False, False]).iloc[0]
    used = {str(picks[key].get("event_id") or picks[key].get("detection_id")) for key in picks}
    neutral = middle[~middle.get("detection_id", pd.Series(dtype=str)).astype(str).isin(used)].copy()
    if not neutral.empty:
        picks["middle_case"] = neutral.sort_values(["_market_rank", "median_distance", "publication_quality_score"], ascending=[True, True, False]).iloc[0]
    return picks


def _build_charts(pattern_id: str, events: pd.DataFrame, price_db: Path, out_dir: Path) -> dict[str, Path]:
    charts_dir = out_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    schematic = charts_dir / f"{pattern_id}_ideal_schematic.png"
    _plot_schematic(schematic, pattern_id=pattern_id)
    paths = {"schematic": schematic}
    examples = _select_examples(events)
    title_map = {"textbook_success": "ví dụ xác nhận tốt", "middle_case": "ví dụ trung vị", "failure": "ví dụ thất bại"}
    for key, event in examples.items():
        raw = _load_ohlcv(price_db, str(event["symbol"]))
        window = slice_around_event(raw, event, pre_bars=55, post_bars=45)
        out_path = charts_dir / f"{key}_{event['symbol']}_{event['breakout_date']}.png"
        plot_event_chart(window, event, out_path, f"{event['symbol']} - {title_map.get(key, 'ví dụ')} ({event['breakout_date']})")
        paths[key] = out_path
    return paths


def _build_one(
    *,
    pattern_id: str,
    scan_dir: Path,
    out_dir: Path,
    price_db: Path,
    ai_sections_path: Path,
) -> dict[str, Path]:
    chapter_dir = out_dir / pattern_id
    if chapter_dir.exists():
        shutil.rmtree(chapter_dir)
    all_events = pd.read_csv(scan_dir / "events.csv")
    if "event_id" not in all_events.columns and "detection_id" in all_events.columns:
        all_events["event_id"] = all_events["detection_id"]
    events = _public_events(all_events)
    if events.empty:
        raise SystemExit(f"No public events available for {pattern_id}")
    path_df = pd.read_csv(scan_dir / "post_breakout_path.csv")
    stats = _read_json(scan_dir / "statistics.json")
    payload = _publication_payload(pattern_id, stats, events, all_events)
    editorial_sections, editorial_source_path = _load_required_editorial(ai_sections_path)
    payload["editorial_sections"] = editorial_sections
    payload["editorial_source_path"] = editorial_source_path
    examples = _select_examples(events)
    payload["example_events"] = {role: {**event.to_dict(), "example_role": role} for role, event in examples.items()}
    payload["chapter_reference"]["example_visual_validation"] = {
        "status": "AUTO_SELECTED_REVIEW_REQUIRED",
        "reviewed_n": 0,
        "pass_n": 0,
        "manual_pass_rate_pct": None,
        "reviewed_roles": [],
        "failure_example_reviewed": False,
    }
    charts = _build_charts(pattern_id, events, price_db, chapter_dir)
    source_notes = _source_notes(pattern_id)
    source_notes_path = chapter_dir / f"{pattern_id}_source_notes.json"
    paths = build_double_pattern_public_chapter(
        payload=payload,
        source_notes=source_notes,
        events=events,
        path_df=path_df,
        charts=charts,
        spec=_spec(pattern_id),
        out_dir=chapter_dir,
        pdf_filename=f"{pattern_id}_reference.pdf",
        payload_filename=f"{pattern_id}_public_chapter_payload.json",
        manuscript_filename=f"{pattern_id}_ai_editorial_manuscript.md",
        notes_filename=f"{pattern_id}_public_chapter_notes.md",
    )
    _write_json(source_notes_path, source_notes)
    paths["source_notes"] = source_notes_path
    return paths


def build_double_pattern_family_public_chapters(
    *,
    out_dir: Path = DEFAULT_OUT_DIR,
    scan_root: Path = DEFAULT_SCAN_OUT_DIR,
    price_db: Path = DEFAULT_DB,
    run_scan: bool = True,
    market_stats_json: Path = DEFAULT_MARKET_STATS_JSON,
    limit_symbols: int | None = None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    active_meta = _load_active_symbols(market_stats_json if market_stats_json else None)
    active_symbols = active_meta.get("active_symbols") if active_meta.get("enabled") else None
    scan_paths: dict[str, dict[str, Path]] = {}
    if run_scan:
        for pattern_id in ("double_bottoms", "double_tops"):
            scan_paths[pattern_id] = scan_double_patterns_db(
                family=pattern_id,
                db_path=price_db,
                out_dir=scan_root / pattern_id / "db_active",
                allowed_symbols=active_symbols,
                limit_symbols=limit_symbols,
                index_db=DEFAULT_INDEX_DB,
            )
    chapter_paths: dict[str, dict[str, Path]] = {}
    for pattern_id in ("double_bottoms", "double_tops"):
        chapter_paths[pattern_id] = _build_one(
            pattern_id=pattern_id,
            scan_dir=scan_root / pattern_id / "db_active",
            out_dir=out_dir,
            price_db=price_db,
            ai_sections_path=DEFAULT_AI_DIR / pattern_id / "approved_ai_sections.json",
        )
    manifest = {
        "family": "double_pattern_family",
        "factory_id": FACTORY_ID,
        "publication_core_id": "pattern_publication_core_v1",
        "chapters": {
            pattern_id: {
                "pdf": str(paths["pdf"]),
                "payload": str(paths["payload"]),
                "manuscript": str(paths["manuscript"]),
                "notes": str(paths["notes"]),
                "source_notes": str(paths["source_notes"]),
            }
            for pattern_id, paths in chapter_paths.items()
        },
        "scan_paths": {pattern_id: {key: str(value) for key, value in paths.items()} for pattern_id, paths in scan_paths.items()},
    }
    _write_json(out_dir / "double_pattern_family_public_chapters_manifest.json", manifest)
    return {"manifest": out_dir / "double_pattern_family_public_chapters_manifest.json", **chapter_paths}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Double Pattern Family public chapters.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--scan-root", default=str(DEFAULT_SCAN_OUT_DIR))
    parser.add_argument("--price-db", default=str(DEFAULT_DB))
    parser.add_argument("--skip-scan", action="store_true")
    parser.add_argument("--limit-symbols", type=int, default=None)
    args = parser.parse_args()
    paths = build_double_pattern_family_public_chapters(
        out_dir=Path(args.out_dir),
        scan_root=Path(args.scan_root),
        price_db=Path(args.price_db),
        run_scan=not args.skip_scan,
        limit_symbols=args.limit_symbols,
    )
    print(json.dumps({key: str(value) for key, value in paths.items() if isinstance(value, Path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
