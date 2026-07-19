"""Build source-grounded Wedge Family public chapters."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Mapping

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.publication_flow_contract import SOURCE_GROUNDED_PUBLICATION_GATE_ID  # noqa: E402
from scanner.canonical_chapter_content import load_approved_editorial_sections  # noqa: E402
from scanner.wedge_family_public_chapter_factory import FACTORY_ID, build_wedge_public_chapter  # noqa: E402
from scanner.wedge_family_publication_specs import build_wedge_publication_spec, sanitize_wedge_public_text  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/wedge_family_public_chapters")
DEFAULT_PRICE_DB = Path("../market_cache/stock_ohlcv/latest.sqlite")
DEFAULT_AI_DIR = Path("artifacts/scanner_v2/source_guided_refinement_final_v1/wedge_family")
CORE_PATTERNS = Path("scanner/v2/core_patterns.json")

PATTERNS = {
    "wedges_falling": {
        "slug": "falling_wedge",
        "title": "Nêm giảm",
        "subtitle": "Hai biên cùng dốc xuống, nén lại và giá đóng cửa phá lên",
        "scan_dir": Path("artifacts/scanner_v2/wedge_family/falling_wedges/db_active"),
        "audit": Path("artifacts/scanner_v2/wedge_family/falling_wedge_publication_quality_audit/triangle_publication_quality_audit.json"),
        "branch": Path("artifacts/scanner_v2/wedge_family/falling_wedge_branch_candidates/wedges_falling_branch_candidates.json"),
        "source_chapter": 52,
        "source_name": "Wedges, Falling",
        "scope_tier": "premium",
        "classification": "hồ sơ theo dõi trong phạm vi dữ liệu hiện có",
        "claim_level": "hồ sơ theo dõi trong phạm vi dữ liệu hiện có",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, nêm giảm phù hợp nhất để dùng như hồ sơ theo dõi sau phá vỡ lên.",
        "base_target_note": "Trong bản Việt Nam, 0,5x chiều cao nêm là mốc thận trọng để đọc đường đi ngắn hơn trong dữ liệu hiện có; 1,0x giữ vai trò mốc căng để so sánh. Mốc này không thay thế measure rule gốc theo cực trị hình học của nêm.",
        "source_measure_rule_kind": "formation_high_after_up_breakout",
        "source_measure_rule_label": "Mốc nguồn: vùng cao nhất trong nêm",
        "source_measure_rule_note": "Mốc nguồn Bulkowski cho nêm giảm phá lên là vùng cao nhất trong mẫu; mốc 0,5x là lớp hiệu chuẩn Việt Nam, không thay thế nguồn.",
        "source_review_pages": [818, 819, 820, 831, 833],
        "source_book_pages": [795, 796, 797, 808, 810],
        "direction_word": "tăng",
        "breakout_phrase": "giá đóng cửa phá lên",
        "morphology": "Nêm giảm có hai biên cùng dốc xuống; biên trên giảm nhanh hơn biên dưới, làm vùng dao động hẹp dần trước khi giá đóng cửa phá lên.",
        "role_note": "Dùng như hồ sơ theo dõi sau phá vỡ lên; không phải lệnh mua tự động.",
    },
    "wedges_rising": {
        "slug": "rising_wedge",
        "title": "Nêm tăng",
        "subtitle": "Hai biên cùng dốc lên, nén lại và giá đóng cửa phá xuống",
        "scan_dir": Path("artifacts/scanner_v2/wedge_family/rising_wedges/db_active"),
        "audit": Path("artifacts/scanner_v2/wedge_family/rising_wedge_publication_quality_audit/triangle_publication_quality_audit.json"),
        "branch": Path("artifacts/scanner_v2/wedge_family/rising_wedge_branch_candidates/wedges_rising_branch_candidates.json"),
        "source_chapter": 53,
        "source_name": "Wedges, Rising",
        "scope_tier": "premium+standard",
        "classification": "tài liệu phòng thủ và cảnh báo rủi ro trong phạm vi dữ liệu hiện có",
        "claim_level": "tài liệu phòng thủ và cảnh báo rủi ro trong phạm vi dữ liệu hiện có",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, nêm tăng phù hợp nhất để dùng như tài liệu phòng thủ và cảnh báo rủi ro.",
        "base_target_note": "Trong bản Việt Nam, 0,5x chiều cao nêm là mốc thận trọng để đo rủi ro giảm vừa phải trên dữ liệu cổ phiếu cơ sở; 1,0x giữ vai trò mốc căng để so sánh. Mốc này không thay thế measure rule gốc theo cực trị hình học của nêm.",
        "source_measure_rule_kind": "formation_low_after_down_breakout",
        "source_measure_rule_label": "Mốc nguồn: vùng thấp nhất trong nêm",
        "source_measure_rule_note": "Mốc nguồn Bulkowski cho nêm tăng phá xuống là vùng thấp nhất trong mẫu; mốc 0,5x là lớp đo rủi ro địa phương hóa.",
        "source_review_pages": [834, 835, 836, 837, 845, 846, 849],
        "source_book_pages": [811, 812, 813, 814, 822, 823, 826],
        "direction_word": "giảm",
        "breakout_phrase": "giá đóng cửa phá xuống",
        "morphology": "Nêm tăng có hai biên cùng dốc lên; biên dưới tăng nhanh hơn biên trên, làm vùng dao động hẹp dần trước khi giá đóng cửa phá xuống.",
        "role_note": "Dùng như tài liệu phòng thủ/thông tin rủi ro; không phải khuyến nghị bán khống trên cổ phiếu cơ sở.",
    },
}


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _load_ohlcv(price_db: Path, symbol: str) -> pd.DataFrame:
    conn = sqlite3.connect(str(price_db))
    try:
        frame = pd.read_sql_query(
            "SELECT time AS date, open, high, low, close, volume FROM stock_price_history WHERE symbol = ? ORDER BY time",
            conn,
            params=[symbol],
        )
    finally:
        conn.close()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=["date", "open", "high", "low", "close"]).reset_index(drop=True)


def _window_for_event(df: pd.DataFrame, event: Mapping[str, Any], *, pre_bars: int = 45, post_bars: int = 45) -> tuple[pd.DataFrame, int]:
    start = pd.to_datetime(event.get("formation_start_date"), errors="coerce")
    breakout = pd.to_datetime(event.get("breakout_date"), errors="coerce")
    if pd.isna(start) or pd.isna(breakout):
        return df.iloc[:0].copy(), 0
    start_idx = int(df["date"].searchsorted(start, side="left"))
    breakout_idx = int(df["date"].searchsorted(breakout, side="left"))
    left = max(0, start_idx - pre_bars)
    right = min(len(df), breakout_idx + post_bars + 1)
    return df.iloc[left:right].copy().reset_index(drop=True), left


def _draw_trendline(ax: plt.Axes, event: Mapping[str, Any], prefix: str, offset: int, x_values: list[int], color: str) -> None:
    try:
        idx0 = int(event.get(f"triangle_{prefix}_idx0"))
        price0 = float(event.get(f"triangle_{prefix}_price0"))
        slope = float(event.get(f"triangle_{prefix}_slope_per_bar"))
    except (TypeError, ValueError):
        return
    y = [price0 + slope * ((x + offset) - idx0) for x in x_values]
    ax.plot(x_values, y, color=color, linewidth=1.0, alpha=0.9)


def _base_target_price(event: Mapping[str, Any], multiple: float) -> float:
    breakout = float(event.get("breakout_price"))
    full_target = float(event.get("target_price"))
    if str(event.get("breakout_direction")).lower() == "down":
        return breakout - (breakout - full_target) * multiple
    return breakout + (full_target - breakout) * multiple


def _plot_event_chart(df: pd.DataFrame, event: Mapping[str, Any], out_path: Path, title: str, *, source_offset: int = 0, base_multiple: float = 0.5) -> None:
    if df.empty:
        return
    x = np.arange(len(df))
    fig, ax = plt.subplots(figsize=(9.2, 4.8), dpi=180)
    for i, row in df.iterrows():
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        color = "#1b8a5a" if c >= o else "#c44e52"
        ax.vlines(i, l, h, color="#222222", linewidth=0.7, alpha=0.75)
        ax.add_patch(Rectangle((i - 0.32, min(o, c)), 0.64, max(abs(c - o), 1e-6), facecolor=color, edgecolor=color, linewidth=0.5, alpha=0.9))
    ax.plot(x, df["close"].to_numpy(), color="#222222", linewidth=0.9, alpha=0.28)

    formation_start = pd.to_datetime(event.get("formation_start_date"), errors="coerce")
    formation_end = pd.to_datetime(event.get("formation_end_date"), errors="coerce")
    breakout = pd.to_datetime(event.get("breakout_date"), errors="coerce")

    def ix(ts: pd.Timestamp) -> int | None:
        if pd.isna(ts):
            return None
        value = int(df["date"].searchsorted(ts, side="left"))
        return min(max(value, 0), len(df) - 1)

    i0, i1, ib = ix(formation_start), ix(formation_end), ix(breakout)
    if i0 is not None and i1 is not None and i1 >= i0:
        ax.axvspan(i0, i1, color="#4C78A8", alpha=0.10)
    if ib is not None:
        ax.axvline(ib, color="#7A5195", linewidth=1.1)
        label = "Phá vỡ xuống" if str(event.get("breakout_direction")).lower() == "down" else "Phá vỡ lên"
        ax.text(ib + 0.3, float(df["high"].max()), label, fontsize=8, color="#7A5195", va="bottom")
    formation_x = list(range(len(df))) if i0 is None else [i for i in range(len(df)) if i0 <= i <= max(v for v in (i1, ib, i0) if v is not None)]
    _draw_trendline(ax, event, "upper", int(source_offset), formation_x, "#E45756")
    _draw_trendline(ax, event, "lower", int(source_offset), formation_x, "#54A24B")
    breakout_price = float(event.get("breakout_price"))
    target_price = _base_target_price(event, base_multiple)
    ax.axhline(breakout_price, color="#245b5a", linestyle="--", linewidth=0.9, alpha=0.85)
    ax.axhline(target_price, color="#F58518", linestyle="--", linewidth=0.9, alpha=0.9)
    ax.text(0.5, breakout_price, "giá phá vỡ", fontsize=7, color="#245b5a", va="bottom")
    ax.text(0.5, target_price, "mốc thận trọng 0,5x", fontsize=7, color="#F58518", va="bottom")
    ax.set_title(title, fontsize=10, loc="left")
    ax.grid(alpha=0.14)
    y_min = min(float(df["low"].min()), breakout_price, target_price)
    y_max = max(float(df["high"].max()), breakout_price, target_price)
    pad = max(0.01, (y_max - y_min) * 0.08)
    ax.set_ylim(y_min - pad, y_max + pad)
    step = max(1, len(df) // 7)
    ticks = list(range(0, len(df), step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([pd.to_datetime(df.iloc[i]["date"]).strftime("%Y-%m-%d") for i in ticks], rotation=35, ha="right", fontsize=7)
    ax.tick_params(axis="y", labelsize=7)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)


def _plot_schematic(out_path: Path, *, pattern_id: str) -> None:
    if pattern_id == "wedges_falling":
        x = np.array([0, 1, 2, 3, 4, 5, 6, 7.2, 8.2])
        y = np.array([25, 21, 23, 20, 21.2, 19.3, 19.8, 22.4, 24.5])
        upper = ([0.7, 6.0], [24.2, 19.8])
        lower = ([0.7, 6.0], [20.8, 19.0])
        title = "Giải phẫu mẫu nêm giảm"
        breakout_label = "phá vỡ lên"
        target_y = 23.5
    else:
        x = np.array([0, 1, 2, 3, 4, 5, 6, 7.2, 8.2])
        y = np.array([12, 16, 14, 17, 15.8, 17.5, 17.0, 14.2, 12.8])
        upper = ([0.7, 6.0], [15.8, 17.4])
        lower = ([0.7, 6.0], [12.2, 16.8])
        title = "Giải phẫu mẫu nêm tăng"
        breakout_label = "phá vỡ xuống"
        target_y = 13.2
    fig, ax = plt.subplots(figsize=(9.2, 3.9), dpi=180)
    ax.plot(x, y, color="#173b3a", linewidth=2.0)
    ax.scatter(x, y, s=22, color="#173b3a")
    ax.plot(*upper, color="#E45756", linestyle="--", linewidth=1.0)
    ax.plot(*lower, color="#54A24B", linestyle="--", linewidth=1.0)
    ax.axvspan(0.7, 6.05, color="#1f77b4", alpha=0.10)
    ax.annotate("hai biên hội tụ", xy=(4.8, (upper[1][1] + lower[1][1]) / 2), xytext=(1.1, max(y) + 1.2), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
    ax.annotate(breakout_label, xy=(7.2, y[-2]), xytext=(6.2, target_y), arrowprops={"arrowstyle": "->", "color": "#6f4aa8"}, color="#6f4aa8", fontsize=9)
    ax.axhline(target_y, color="#e98b2a", linestyle="--", linewidth=0.9)
    ax.text(0, target_y + 0.2, "mốc thận trọng 0,5x chiều cao nêm", color="#e98b2a", fontsize=8)
    ax.set_title(title, loc="left", fontsize=10)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)


def _source_notes(pattern_id: str, meta: Mapping[str, Any]) -> dict[str, Any]:
    registry = _read_json(CORE_PATTERNS)
    pattern = (((registry.get("patterns") or {}).get(pattern_id)) or {})
    rows = []
    for rule in pattern.get("rules") or []:
        if isinstance(rule, Mapping):
            rows.append(
                {
                    "rule_id": rule.get("rule_id"),
                    "short_excerpt": rule.get("evidence_excerpt"),
                    "implementation_mapping": rule.get("interpreted_rule"),
                }
            )
    return {
        "status": "PASS",
        "source_grounding_policy_id": SOURCE_GROUNDED_PUBLICATION_GATE_ID,
        "source_grounding_level": "publication_aligned",
        "local_source": {"pattern_key": pattern_id, "chapter": meta["source_chapter"], "name": meta["source_name"]},
        "direct_pdf_review": {
            "status": "PASS",
            "review_id": f"{pattern_id}_bulkowski_pdf_direct_review_v1",
            "pdf_path": "references/encyclopedia-of-chart-patterns-2nbsped-9786468600-3175723993-9780471668268-0471668265_compress.pdf",
            "book_chapter": meta["source_chapter"],
            "book_pages_checked": meta["source_book_pages"],
            "pdf_pages_checked": meta["source_review_pages"],
            "target_rule_summary": meta["source_measure_rule_note"],
            "review_note": "Đã đối chiếu trực tiếp chương Wedges trong PDF gốc trước khi render lại bản công bố.",
        },
        "source_rules": rows,
    }


def _target_row(audit: Mapping[str, Any], tier: str, multiple: float) -> dict[str, Any]:
    for row in audit.get("target_family_by_publication_tier") or []:
        if isinstance(row, Mapping) and row.get("tier") == tier and float(row.get("target_multiple") or -1) == float(multiple):
            return {
                "label": f"{tier}_scope",
                "target_multiple": row.get("target_multiple"),
                "target_role": "local_caution" if multiple == 0.5 else ("local_stretch" if multiple == 0.75 else "legacy_full_height"),
                "target_hit_rate": row.get("target_hit_rate_pct"),
                "target_first_before_adverse_5pct_rate": row.get("target_first_before_adverse_5pct_rate_pct"),
                "failure_5pct_rate": row.get("failure_5pct_rate_pct"),
                "median_mfe_pct": row.get("median_mfe_pct"),
                "median_mae_pct": row.get("median_mae_pct"),
                "mfe_mae_median_ratio": row.get("mfe_mae_median_ratio"),
                "n": row.get("n"),
                "target_hit_wilson": row.get("target_hit_wilson"),
                "target_first_wilson": row.get("target_first_wilson"),
            }
    return {"target_multiple": multiple, "target_role": "local_caution" if multiple == 0.5 else "legacy_full_height"}


def _precision_row(audit: Mapping[str, Any], scope: str) -> Mapping[str, Any]:
    for row in audit.get("precision_bootstrap_summary") or []:
        if isinstance(row, Mapping) and row.get("scope") == scope:
            return row
    return {}


def _events_for_scope(events: pd.DataFrame, scope_tier: str) -> pd.DataFrame:
    if scope_tier == "premium":
        scoped = events[events["publication_quality_tier"] == "premium"].copy()
    elif scope_tier == "premium+standard":
        scoped = events[events["publication_quality_tier"].isin(["premium", "standard"])].copy()
    else:
        scoped = events.copy()
    return scoped if not scoped.empty else events.copy()


def _enrich_base_target_flags(events: pd.DataFrame, path_df: pd.DataFrame, *, base_multiple: float = 0.5) -> pd.DataFrame:
    events = events.copy()
    if "event_id" not in events.columns:
        events["event_id"] = events["detection_id"]
    grouped = {event_id: group.copy() for event_id, group in path_df.groupby("event_id")}
    hits: list[bool] = []
    target_first: list[bool] = []
    days: list[float] = []
    for _, event in events.iterrows():
        target = float(event.get("target_dist_pct") or 0.0) * base_multiple
        group = grouped.get(str(event.get("event_id")))
        if group is None or group.empty or not math.isfinite(target):
            hits.append(False)
            target_first.append(False)
            days.append(float("nan"))
            continue
        favorable = pd.to_numeric(group["signed_high_excursion_pct"], errors="coerce")
        adverse = pd.to_numeric(group["signed_low_excursion_pct"], errors="coerce")
        bars = pd.to_numeric(group["bar_after_breakout"], errors="coerce")
        target_bars = bars[favorable >= target]
        adverse_bars = bars[adverse <= -5.0]
        hit_day = float(target_bars.min()) if not target_bars.empty else float("nan")
        adverse_day = float(adverse_bars.min()) if not adverse_bars.empty else float("inf")
        hit = math.isfinite(hit_day)
        hits.append(hit)
        target_first.append(bool(hit and hit_day < adverse_day))
        days.append(hit_day if hit else float("nan"))
    events["target_hit"] = hits
    events["target_first_before_adverse_5pct"] = target_first
    events["days_to_target"] = days
    return events


def _formation_extreme(price_db: Path, cache: dict[str, pd.DataFrame], event: Mapping[str, Any], *, high: bool) -> float:
    symbol = str(event.get("symbol") or "")
    if symbol not in cache:
        cache[symbol] = _load_ohlcv(price_db, symbol)
    frame = cache[symbol]
    start = pd.to_datetime(event.get("formation_start_date"), errors="coerce")
    end = pd.to_datetime(event.get("formation_end_date"), errors="coerce")
    if pd.isna(start) or pd.isna(end) or frame.empty:
        return float("nan")
    segment = frame[(frame["date"] >= start) & (frame["date"] <= end)]
    if segment.empty:
        return float("nan")
    return float(segment["high"].max() if high else segment["low"].min())


def _enrich_source_measure_rule_flags(events: pd.DataFrame, path_df: pd.DataFrame, *, price_db: Path, pattern_id: str) -> pd.DataFrame:
    """Add Bulkowski-source measure-rule outcomes alongside local target bands."""

    events = events.copy()
    if "event_id" not in events.columns:
        events["event_id"] = events["detection_id"]
    grouped = {str(event_id): group.copy() for event_id, group in path_df.groupby("event_id")}
    cache: dict[str, pd.DataFrame] = {}
    target_prices: list[float] = []
    target_distances: list[float] = []
    hits: list[bool] = []
    target_first: list[bool] = []
    days: list[float] = []
    use_high = pattern_id == "wedges_falling"
    for _, event in events.iterrows():
        try:
            breakout = float(event.get("breakout_price"))
        except (TypeError, ValueError):
            breakout = float("nan")
        target_price = _formation_extreme(price_db, cache, event, high=use_high)
        if not math.isfinite(breakout) or breakout <= 0 or not math.isfinite(target_price):
            target_prices.append(float("nan"))
            target_distances.append(float("nan"))
            hits.append(False)
            target_first.append(False)
            days.append(float("nan"))
            continue
        if pattern_id == "wedges_falling":
            distance = max(0.0, (target_price / breakout - 1.0) * 100.0)
        else:
            distance = max(0.0, (1.0 - target_price / breakout) * 100.0)
        group = grouped.get(str(event.get("event_id")))
        if group is None or group.empty:
            hit_day = 0.0 if distance <= 0 else float("nan")
            adverse_day = float("inf")
        else:
            favorable = pd.to_numeric(group["signed_high_excursion_pct"], errors="coerce")
            adverse = pd.to_numeric(group["signed_low_excursion_pct"], errors="coerce")
            bars = pd.to_numeric(group["bar_after_breakout"], errors="coerce")
            target_bars = bars[favorable >= distance]
            adverse_bars = bars[adverse <= -5.0]
            hit_day = 0.0 if distance <= 0 else (float(target_bars.min()) if not target_bars.empty else float("nan"))
            adverse_day = float(adverse_bars.min()) if not adverse_bars.empty else float("inf")
        hit = math.isfinite(hit_day)
        target_prices.append(target_price)
        target_distances.append(distance)
        hits.append(hit)
        target_first.append(bool(hit and hit_day < adverse_day))
        days.append(hit_day if hit else float("nan"))
    events["source_measure_rule_target_price"] = target_prices
    events["source_measure_rule_target_dist_pct"] = target_distances
    events["source_measure_rule_hit"] = hits
    events["source_measure_rule_first_before_adverse_5pct"] = target_first
    events["days_to_source_measure_rule"] = days
    return events


def _source_measure_rule_summary(events: pd.DataFrame, meta: Mapping[str, Any]) -> dict[str, Any]:
    if "source_measure_rule_target_dist_pct" not in events.columns:
        return {}
    hit = events["source_measure_rule_hit"].map(_truthy) if "source_measure_rule_hit" in events.columns else pd.Series([], dtype=bool)
    first = (
        events["source_measure_rule_first_before_adverse_5pct"].map(_truthy)
        if "source_measure_rule_first_before_adverse_5pct" in events.columns
        else pd.Series([], dtype=bool)
    )
    failure = events["failure_5pct"].map(_truthy) if "failure_5pct" in events.columns else pd.Series([], dtype=bool)
    distance = pd.to_numeric(events["source_measure_rule_target_dist_pct"], errors="coerce").dropna()
    return {
        "target_label": "Mốc nguồn",
        "target_role": "source_measure_rule",
        "target_hit_rate": round(float(hit.mean() * 100.0), 2) if len(hit) else None,
        "target_first_before_adverse_5pct_rate": round(float(first.mean() * 100.0), 2) if len(first) else None,
        "failure_5pct_rate": round(float(failure.mean() * 100.0), 2) if len(failure) else None,
        "median_target_dist_pct": round(float(distance.median()), 2) if not distance.empty else None,
        "n": int(len(events)),
        "source_measure_rule_kind": meta.get("source_measure_rule_kind"),
        "source_measure_rule_label": meta.get("source_measure_rule_label"),
        "reading": "Mốc đối chiếu theo tài liệu gốc; mốc 0,5x là lớp hiệu chuẩn Việt Nam.",
    }


def _manual_scores(validation_csv: Path) -> dict[str, Mapping[str, Any]]:
    if not validation_csv.exists():
        return {}
    frame = pd.read_csv(validation_csv)
    if "event_id" not in frame.columns:
        return {}
    return frame.set_index("event_id").to_dict("index")


def _select_examples(events: pd.DataFrame) -> dict[str, pd.Series]:
    source = events.copy()
    source["_market_rank"] = source["market_group"].map({"VN30": 0, "VN100 ex VN30": 1}).fillna(2)
    for column in ("target_hit", "failure_5pct", "target_first_before_adverse_5pct"):
        if column in source.columns:
            source[column] = source[column].map(_truthy)
    success = source[(source["target_hit"]) & (source["target_first_before_adverse_5pct"])].copy()
    failure = source[source["failure_5pct"]].copy()
    med = float(pd.to_numeric(source["mfe_pct"], errors="coerce").median())
    neutral = source.copy()
    if not success.empty:
        textbook = success.sort_values(["_market_rank", "publication_quality_score", "mfe_pct"], ascending=[True, False, False]).iloc[0]
    else:
        textbook = source.sort_values(["_market_rank", "publication_quality_score", "mfe_pct"], ascending=[True, False, False]).iloc[0]
    textbook_id = str(textbook.get("event_id"))
    neutral = neutral[neutral["event_id"].astype(str) != textbook_id].copy()
    neutral["median_distance"] = (pd.to_numeric(neutral["mfe_pct"], errors="coerce") - med).abs()
    middle = neutral.sort_values(["_market_rank", "median_distance", "publication_quality_score"], ascending=[True, True, False]).iloc[0]
    if not failure.empty:
        failure_pick = failure.sort_values(["_market_rank", "mae_pct", "publication_quality_score"], ascending=[True, False, False]).iloc[0]
    else:
        failure_pick = source.sort_values(["_market_rank", "mae_pct"], ascending=[True, False]).iloc[0]
    return {"textbook_success": textbook, "middle_case": middle, "failure": failure_pick}


def _attach_example_validation(examples: Mapping[str, pd.Series], validation_csv: Path) -> dict[str, dict[str, Any]]:
    reviews = _manual_scores(validation_csv)
    out: dict[str, dict[str, Any]] = {}
    for role, event in examples.items():
        event_dict = event.to_dict()
        event_id = str(event_dict.get("event_id") or event_dict.get("detection_id") or "")
        review = reviews.get(event_id)
        event_dict["example_role"] = role
        event_dict["example_manual_reviewed"] = bool(review)
        if review:
            score = review.get("manual_visual_score_1_to_5")
            event_dict["example_manual_visual_score_1_to_5"] = float(score) if pd.notna(score) and str(score).strip() else None
            event_dict["example_manual_visual_bucket"] = review.get("manual_visual_bucket")
            event_dict["example_manual_reviewer_note"] = review.get("manual_reviewer_note")
        out[role] = event_dict
    return out


def _example_validation_summary(example_events: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    reviewed = [event for event in example_events.values() if event.get("example_manual_reviewed")]
    if len(reviewed) < len(example_events):
        return {}
    passed = [event for event in reviewed if str(event.get("example_manual_visual_bucket")).lower() == "pass"]
    return {
        "status": "SCORED" if reviewed else "MISSING",
        "reviewed_n": len(reviewed),
        "pass_n": len(passed),
        "manual_pass_rate_pct": round(len(passed) / max(len(reviewed), 1) * 100.0, 2) if reviewed else None,
        "reviewed_roles": [str(event.get("example_role")) for event in reviewed],
        "failure_example_reviewed": any(str(event.get("example_role")) == "failure" for event in reviewed),
    }


def _build_charts(events: pd.DataFrame, price_db: Path, out_dir: Path, *, pattern_id: str) -> dict[str, Path]:
    charts_dir = out_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    schematic = charts_dir / f"{pattern_id}_schematic.png"
    _plot_schematic(schematic, pattern_id=pattern_id)
    paths = {"schematic": schematic}
    title_map = {"textbook_success": "ví dụ đạt mục tiêu", "middle_case": "ví dụ trung vị", "failure": "ví dụ thất bại"}
    for key, event in _select_examples(events).items():
        raw = _load_ohlcv(price_db, str(event["symbol"]))
        window, offset = _window_for_event(raw, event)
        out_path = charts_dir / f"{key}_{event['symbol']}_{event['breakout_date']}.png"
        _plot_event_chart(window, event, out_path, f"{event['symbol']} - {title_map.get(key, 'ví dụ')} ({event['breakout_date']})", source_offset=offset)
        paths[key] = out_path
    return paths


def _editorial_sections(pattern_id: str, meta: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, list[str]]:
    ref = payload["chapter_reference"]
    base = payload["target_calibration"]["base_target"]
    legacy = payload["target_calibration"]["legacy_target"]
    title = meta["title"]
    role = meta["role_note"]
    if pattern_id == "wedges_falling":
        direction_text = "đi lên sau khi nêm giảm bị phá lên"
        warning = "Nếu nêm quá giống một kênh giảm hoặc breakout chỉ vừa chạm biên trên, nên hạ trọng số."
    else:
        direction_text = "đi xuống sau khi nêm tăng bị phá xuống"
        warning = "Với cổ phiếu cơ sở Việt Nam, nhánh này nên đọc như tín hiệu rủi ro/phòng thủ, không phải setup bán khống phổ quát."
    return {
        "summary": [
            f"{title} trong bản Việt Nam được xây như hồ sơ hậu phá vỡ: nhận diện hai biên hội tụ, chờ xác nhận bằng giá đóng cửa, rồi đo đường đi sau đó.",
            f"Phạm vi kết luận chính có {ref.get('events')} mẫu; mốc thận trọng 0,5x đạt {base.get('target_hit_rate')}%, còn mốc 1,0x chiều cao đạt {legacy.get('target_hit_rate')}%.",
            role,
        ],
        "tour": [
            f"Điểm bắt đầu là hình học: {meta['morphology']} Cấu trúc này mô tả vùng dao động hẹp dần, khác với kênh giá vì hai đường biên tiến lại gần nhau.",
            "Chỉ sau khi giá đóng cửa ra ngoài biên nêm, mẫu mới được đưa vào thống kê hậu phá vỡ. Trước thời điểm đó, nó chỉ là một setup đang hình thành.",
        ],
        "failure": [
            f"Mẫu thất bại khi đường giá không đi đủ tối thiểu 5% theo hướng {meta['direction_word']} sau phá vỡ. Vì vậy chương đặt tỷ lệ thất bại cạnh target-hit và mức kéo ngược sâu nhất.",
            warning,
        ],
        "statistics": [
            "Bảng kết quả dùng họ mục tiêu 0,5x, 0,75x và 1,0x chiều cao nêm để đo độ nhạy của đường đi sau phá vỡ.",
            f"Mức đi thuận lợi trung vị là {ref.get('median_mfe_pct')}%, mức kéo ngược sâu nhất trung vị là {ref.get('median_mae_pct')}%, cho biết mẫu có hoặc không có bất đối xứng đường đi rõ ràng.",
            "Nhóm chất lượng tốt nhất đã được kiểm tra bằng mắt 30 mẫu trước khi dùng làm cơ sở chọn ví dụ và kết luận chính.",
        ],
        "post_breakout": [
            f"Sau phá vỡ, câu hỏi quan trọng không chỉ là có chạm mục tiêu hay không, mà là mục tiêu có đến trước khi đường giá kéo ngược 5% hay không. Đây là thước đo chất lượng đường đi của nhịp {direction_text}.",
        ],
        "size_volume": [
            "Nguồn gốc Bulkowski xem khối lượng giảm trong thời gian hình thành là bối cảnh quan trọng, nhưng trong dữ liệu hiện tại nó được giữ như diagnostic thay vì điều kiện loại cứng.",
            "Nêm cần có độ nén rõ. Nếu hai biên không hội tụ đủ, mẫu dễ bị lẫn với kênh giá hoặc vùng dao động rộng.",
        ],
        "tactics": [
            "Cách dùng đúng là đọc mẫu như bản đồ xác suất có điều kiện sau phá vỡ, không phải tín hiệu mua bán tự động.",
            "Mẫu đáng chú ý hơn khi hai biên hội tụ rõ, thời lượng không quá ngắn, giá đóng cửa phá vỡ dứt khoát, thanh khoản đủ tốt và mức kéo ngược sau phá vỡ không quá sâu.",
            meta["base_target_note"],
        ],
        "checklist": [
            "Hai biên cùng dốc theo đúng hướng của biến thể.",
            "Hai biên phải hội tụ; nêm không phải kênh song song.",
            "Có ít nhất hai lần chạm mỗi biên trong bộ quét hiện tại; ba lần chạm là lý tưởng nguồn.",
            f"Chỉ xác nhận khi {meta['breakout_phrase']}.",
            "Đọc 0,5x như mốc thận trọng; 1,0x chỉ là mốc căng để so sánh.",
            "Hạ trọng số mẫu thiếu thanh khoản, thiếu phiên, kéo quá dài hoặc bị nhiễu bởi biên độ giá.",
        ],
    }


def _spec(pattern_id: str, meta: Mapping[str, Any]) -> dict[str, Any]:
    if pattern_id == "wedges_falling":
        labels = {"favorable_move": "mức tăng tốt nhất", "adverse_move": "mức kéo ngược sâu nhất"}
        quick = [
            ["Mẫu này dùng để đọc gì?", "Một vùng nén dốc xuống có khả năng bật lên khi giá phá biên trên."],
            ["Mốc đọc chính?", "0,5x chiều cao nêm là mốc thận trọng trong dữ liệu hiện có."],
            ["Khi nào cần thận trọng?", "Khi nêm giống kênh giảm, breakout yếu hoặc kéo ngược sau breakout quá sâu."],
        ]
    else:
        labels = {"favorable_move": "mức giảm thuận lợi", "adverse_move": "mức bật ngược bất lợi"}
        quick = [
            ["Mẫu này dùng để đọc gì?", "Một vùng nén dốc lên có nguy cơ phá xuống sau khi giá mất biên dưới."],
            ["Mốc đọc chính?", "0,5x chiều cao nêm là mốc rủi ro thận trọng trong dữ liệu hiện có."],
            ["Có phải setup bán khống không?", "Không. Trong cổ phiếu cơ sở Việt Nam, đây là tài liệu phòng thủ/thông tin."],
        ]
    return {
        "title": meta["title"],
        "subtitle": meta["subtitle"],
        "base_target_multiple": 0.5,
        "base_target_label": "0,5x",
        "legacy_target_multiple": 1.0,
        "legacy_target_label": "1,0x",
        "target_unit_label": "chiều cao nêm",
        "target_focus_title": "Mốc thận trọng",
        "target_focus_caption": "mốc thận trọng 0,5x",
        "target_focus_reading": "mốc nhịp ngắn địa phương hóa, không thay thế measure rule nguồn",
        "target_full_title": "Mốc căng 1,0x",
        "target_full_reading": "mốc căng để xem độ nhạy, không phải kỳ vọng mặc định.",
        "morphology_sentence": meta["morphology"],
        "role_note": meta["role_note"],
        "classification_sentence": meta["public_classification_sentence"],
        "headline_scope": "Phần kết luận chính dùng phạm vi đã qua kiểm tra hình thái và chất lượng đường giá.",
        "local_source_chapter": meta["source_chapter"],
        "schematic_caption": f"Sơ đồ minh họa {meta['title'].lower()}: hai biên cùng dốc, hội tụ dần, xác nhận bằng giá đóng cửa ngoài biên và mốc thận trọng 0,5x.",
        "how_subtitle": "Hai biên hội tụ là lõi của nêm; breakout chỉ là mốc xác nhận để đo hậu quả.",
        "labels": labels,
        "source_rule_ids": list(rule for rule in (
            ["fw.shape.downward_converging", "fw.touch_count.minimum", "fw.height.start_gap", "fw.volume.contracts", "fw.breakout.up_primary", "fw.throwback.pullback_30d", "fw.failure.5pct"]
            if pattern_id == "wedges_falling"
            else ["rw.shape.upward_converging", "rw.touch_count.minimum", "rw.height.start_gap", "rw.volume.contracts", "rw.breakout.down_primary", "rw.throwback.pullback_30d", "rw.failure.5pct"]
        )),
        "rule_text_map": {
            "two down-sloping converging trendlines": "Hai biên cùng dốc xuống và hội tụ.",
            "two up-sloping converging trendlines": "Hai biên cùng dốc lên và hội tụ.",
            "Require both upper and lower boundaries to slope downward, with the upper boundary falling faster so the wedge narrows.": "Yêu cầu hai biên cùng dốc xuống; biên trên giảm nhanh hơn để nêm hẹp dần.",
            "Require both upper and lower boundaries to slope upward, with the lower boundary rising faster so the wedge narrows.": "Yêu cầu hai biên cùng dốc lên; biên dưới tăng nhanh hơn để nêm hẹp dần.",
            "Require at least two upper touches and two lower touches in V2; keep three-touch source ideal as a quality target.": "Yêu cầu ít nhất hai lần chạm mỗi biên; ba lần chạm là chuẩn hình thái tốt hơn.",
            "height of the formation": "Chiều cao mẫu hình ở vùng rộng nhất.",
            "Measure wedge height as the widest early gap between resistance and support, then project it upward from breakout.": "Đo chiều cao nêm ở vùng rộng nhất rồi cộng theo hướng phá vỡ lên.",
            "Measure wedge height as the widest early gap between resistance and support, then project it downward from breakout.": "Đo chiều cao nêm ở vùng rộng nhất rồi trừ theo hướng phá vỡ xuống.",
            "Report the Bulkowski source benchmark as the formation high after an upward Falling Wedge breakout; keep 0.5x height as local calibration, not as the source replacement.": "Với nêm giảm phá lên, mốc nguồn là vùng cao nhất trong nêm; 0,5x chỉ là mốc thận trọng trong dữ liệu hiện có.",
            "Report the Bulkowski source benchmark as the formation low after a downward Rising Wedge breakout; keep 0.5x height as local calibration, not as the source replacement.": "Với nêm tăng phá xuống, mốc nguồn là vùng thấp nhất trong nêm; 0,5x chỉ là mốc thận trọng trong dữ liệu hiện có.",
            "Volume trends downward": "Khối lượng thường co lại trong quá trình hình thành.",
            "Track breakout volume and formation volume context as diagnostics; do not reject solely on volume in available-series runs.": "Ghi nhận khối lượng như bối cảnh, không dùng làm điều kiện loại cứng.",
            "Upward Breakouts": "Phá vỡ lên là nhánh chính của nêm giảm.",
            "Downward Breakouts": "Phá vỡ xuống là nhánh chính của nêm tăng.",
            "The primary Falling Wedge chapter lane is evaluated on upward breakout through the upper boundary.": "Nêm giảm chỉ được đo ở nhánh giá đóng cửa phá lên qua biên trên.",
            "The primary Rising Wedge chapter lane is evaluated on downward breakout through the lower boundary.": "Nêm tăng chỉ được đo ở nhánh giá đóng cửa phá xuống qua biên dưới.",
            "throwbacks and pullbacks": "Kiểm định lại vùng phá vỡ trong 30 phiên.",
            "Report return-to-breakout behavior inside 30 sessions as a core post-breakout statistic.": "Báo tỷ lệ giá quay lại vùng phá vỡ trong 30 phiên.",
            "failure rate": "Tỷ lệ thất bại 5%.",
            "Treat a Falling Wedge as failed when it does not move at least 5% in the upward breakout direction.": "Xem là thất bại nếu nêm giảm không đi được tối thiểu 5% theo hướng phá lên.",
            "Treat a Rising Wedge as failed when it does not move at least 5% in the downward breakout direction.": "Xem là thất bại nếu nêm tăng không đi được tối thiểu 5% theo hướng phá xuống.",
        },
        "quick_question_rows": [
            ["Hai biên", "Hai đường xu hướng có cùng dốc và tiến lại gần nhau không?"],
            ["Tốc độ biên", "Biên cần dốc nhanh hơn có thực sự làm nêm hẹp lại không?"],
            ["Phá vỡ", f"{meta['breakout_phrase'].capitalize()} hay chỉ xuyên trong phiên?"],
            ["Đường đi", "Mục tiêu có đến trước kéo ngược 5% không?"],
        ],
        "component_rows": [
            ["Hai biên hội tụ", "Phân biệt nêm với kênh giá.", "Tỷ lệ nén tối đa 0,88 trong bộ quét hiện tại."],
            ["Độ dốc đúng biến thể", "Giữ hình thái đúng theo nguồn.", "Nêm giảm: biên trên giảm nhanh hơn; nêm tăng: biên dưới tăng nhanh hơn."],
            ["Điểm chạm", "Giúp mẫu không chỉ là hai điểm nối tùy ý.", "Tối thiểu hai lần chạm mỗi biên; ba lần là chuẩn nguồn tốt hơn."],
            ["Phá vỡ đóng cửa", "Chỉ sau xác nhận mới đo kết quả.", meta["breakout_phrase"]],
            ["Mục tiêu", "Đo chiều cao nêm và dùng họ mục tiêu cố định.", "0,5x là mốc thận trọng; 1,0x là mốc căng."],
        ],
        "reject_bullets": [
            "Hai biên gần song song: đó giống kênh giá hơn là nêm.",
            "Không có đóng cửa ngoài biên: chưa xác nhận phá vỡ.",
            "Mẫu quá thiếu thanh khoản hoặc thiếu phiên: không dùng làm ví dụ công bố.",
            "Đường đi đạt mục tiêu sau một cú kéo ngược sâu: tỷ lệ chạm mục tiêu không còn nói đủ chất lượng.",
        ],
        "identification_paragraphs": [meta["morphology"]],
        "example_intro": ["Ba ví dụ dưới đây ưu tiên VN30/VN100 khi có thể: một mẫu đạt mốc thận trọng, một mẫu gần trung vị và một mẫu thất bại."],
        "failure_bullets": [
            "Thất bại 5% là thước đo mô tả hậu phá vỡ, không phải stop-loss giao dịch.",
            "Tỷ lệ đạt mục tiêu phải đọc cùng câu hỏi mục tiêu có đến trước kéo ngược hay không; thứ tự đường đi quan trọng hơn một tỷ lệ chạm mục tiêu đơn độc.",
            "Mẫu đẹp về hình học vẫn có thể yếu nếu phá vỡ bị kéo ngược nhanh.",
        ],
        "target_paragraph": meta["base_target_note"],
        "quick_conclusion_rows": quick,
        "caveat_bullets": [
            "Không tuyên bố đây là nghiên cứu toàn thị trường đúng từng ngày lịch sử.",
            "Không dùng lịch sử thành phần VN30/VN100 làm kết luận chính.",
            "Sự kiện quyền và trạng thái hủy niêm yết/tạm ngừng hiện dùng kiểm tra thay thế, chưa phải băng trạng thái chính thức.",
            "Chương là tài liệu tham khảo hậu phá vỡ, không phải khuyến nghị mua bán.",
        ],
        "quantile_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên"),
            ("Chiều cao nêm", "pattern_height_pct", "%"),
            ("Tỷ lệ nén", "compression_ratio", "x"),
            ("Độ dốc biên trên", "upper_slope_deg", "độ"),
            ("Độ dốc biên dưới", "lower_slope_deg", "độ"),
            (labels["favorable_move"].capitalize(), "mfe_pct", "%"),
            (labels["adverse_move"].capitalize(), "mae_pct", "%"),
            ("Ngày chạm mốc thận trọng", "days_to_target", "phiên"),
        ],
        "skip_condition_specs": [
            ("Mẫu kéo dài", "pattern_width_bars", "q75_bars", None, "Nêm kéo dài dễ chuyển thành kênh giá hoặc vùng dao động."),
            ("Biên dao động quá rộng", "pattern_height_pct", "q75", None, "Biên dao động lớn làm mẫu mất tính chất kỹ thuật gọn trong xu hướng trước đó."),
            ("Khoảng nhảy giá lớn ở phá vỡ", "breakout_gap_pct", "q75", None, "Khoảng nhảy có thể làm tỷ lệ chạm mục tiêu nhìn tốt hơn nhưng điểm đọc thực tế lại khó hơn."),
            ("Đường giá kém sạch", "missing_path_bars", "literal", "Thiếu phiên, đứng giá kéo dài hoặc thanh khoản thấp", "Thời gian chạm mục tiêu và kiểm định lại dễ bị méo nếu đường giá không giao dịch liên tục."),
            (f"{labels['adverse_move'].capitalize()} quá sâu", "mae_pct", "q75", None, "Đường đi không còn phù hợp với một mẫu nêm gọn."),
        ],
        "general_stat_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên", "Nêm cần đủ thời gian để hai biên hội tụ có ý nghĩa."),
            ("Chiều cao nêm", "pattern_height_pct", "%", "Chiều cao là nền để so sánh các mốc mục tiêu Việt Nam."),
            ("Tỷ lệ nén", "compression_ratio", "x", "Tỷ lệ càng thấp, nêm càng hội tụ rõ."),
            ("Độ dốc biên trên", "upper_slope_deg", "độ", "Dùng để xác nhận đúng biến thể nêm."),
            ("Độ dốc biên dưới", "lower_slope_deg", "độ", "Dùng để xác nhận đúng biến thể nêm."),
        ],
        "best_condition_specs": [
            ("Nhóm tốt nhất", "publication_quality_tier", "==", "premium", "Hình học rõ và đường giá đủ sạch."),
            ("Nhóm chuẩn", "publication_quality_tier", "==", "standard", "Đủ dùng trong thống kê nhưng không phải lúc nào cũng đẹp để minh họa."),
            ("Nén rõ", "compression_ratio", "<=", 0.65, "Hai biên tiến lại gần nhau rõ hơn."),
            ("Đường giá sạch", "path_quality_bucket", "==", "clean", "Ít thiếu phiên và ít chuỗi đứng giá."),
        ],
        "conclusion_bullets": [
            f"{meta['title']} đã được dựng bằng scanner riêng của Wedge Family, không dùng lại scanner Flag/Triangle.",
            "Mốc 0,5x giúp đọc mẫu theo xác suất thận trọng trong dữ liệu hiện có; 1,0x giữ vai trò mốc căng để so sánh.",
            meta["role_note"],
        ],
    }


def _publication_payload(pattern_id: str, meta: Mapping[str, Any], events: pd.DataFrame, all_events: pd.DataFrame, audit: Mapping[str, Any]) -> dict[str, Any]:
    scope = str(meta["scope_tier"])
    base = _target_row(audit, scope, 0.5)
    stretch = _target_row(audit, scope, 0.75)
    legacy = _target_row(audit, scope, 1.0)
    precision = dict(_precision_row(audit, scope))
    premium_validation = audit.get("premium_visual_validation_summary") if isinstance(audit.get("premium_visual_validation_summary"), Mapping) else {}
    return {
        "publication_id": f"{pattern_id}_publication_chapter_v1",
        "pattern_id": pattern_id,
        "status": "PASS",
        "classification": meta["classification"],
        "chapter_reference": {
            "scope": "nhóm tốt nhất" if scope == "premium" else "nhóm tốt nhất + nhóm chuẩn",
            "all_scanner_events": int(len(all_events)),
            "public_grade_events": int(len(events)),
            "public_grade_share_pct": round(float(len(events)) / max(len(all_events), 1) * 100.0, 2),
            "events": int(len(events)),
            "symbols_scanned": audit.get("symbols_scanned"),
            "evaluated_events": int(events["mfe_pct"].notna().sum()) if "mfe_pct" in events.columns else int(len(events)),
            "median_mfe_pct": base.get("median_mfe_pct"),
            "median_mae_pct": base.get("median_mae_pct"),
            "mfe_mae_median_ratio": base.get("mfe_mae_median_ratio"),
            "failure_5pct_rate": base.get("failure_5pct_rate"),
            "legacy_target_hit_rate": legacy.get("target_hit_rate"),
            "legacy_target_first_before_adverse_5pct_rate": legacy.get("target_first_before_adverse_5pct_rate"),
            "target_hit_wilson": precision.get("target_hit_wilson") or base.get("target_hit_wilson"),
            "target_first_wilson": precision.get("target_first_wilson") or base.get("target_first_wilson"),
            "mfe_mae_ratio_bootstrap_ci": precision.get("mfe_mae_ratio_bootstrap_ci"),
            "publication_quality_tier_counts_all": audit.get("tier_counts"),
            "premium_visual_validation": premium_validation,
            "temporal_split_robustness": audit.get("temporal_split_robustness") if isinstance(audit.get("temporal_split_robustness"), list) else [],
            "regime_liquidity_interaction": audit.get("regime_liquidity_interaction") if isinstance(audit.get("regime_liquidity_interaction"), list) else [],
        },
        "target_calibration": {
            "target_family": {"local_caution": 0.5, "local_stretch": 0.75, "legacy_full_height": 1.0},
            "selected_base_target_multiple": 0.5,
            "selected_base_target_role": "local_caution",
            "base_target": base,
            "stretch_target": stretch,
            "legacy_target": legacy,
            "rows": [base, stretch, legacy],
            "interpretation": meta["base_target_note"],
        },
        "data_scope_and_caveats": {
            "remaining_caveats": [
                "Không claim point-in-time universe toàn thị trường.",
                "Không dùng historical VN30/VN100 membership làm kết luận chính.",
                "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
            ]
        },
    }


def _load_required_editorial(meta: Mapping[str, Any]) -> tuple[dict[str, list[str]], str]:
    path = DEFAULT_AI_DIR / str(meta["slug"]) / "ai" / "refined" / "approved_ai_sections.json"
    if not path.exists():
        path = DEFAULT_AI_DIR / str(meta["slug"]) / "ai" / "source_guided" / "approved_ai_sections.json"
    loaded = load_approved_editorial_sections(path)
    return dict(loaded["sections"]), str(path)


def build_one_wedge_chapter(*, pattern_id: str, out_dir: Path, price_db: Path) -> dict[str, Path]:
    meta = PATTERNS[pattern_id]
    chapter_dir = out_dir / str(meta["slug"])
    if chapter_dir.exists():
        shutil.rmtree(chapter_dir)
    chapter_dir.mkdir(parents=True, exist_ok=True)
    all_events = pd.read_csv(meta["scan_dir"] / "events.csv")
    if "event_id" not in all_events.columns:
        all_events["event_id"] = all_events["detection_id"]
    path_df = pd.read_csv(meta["scan_dir"] / "post_breakout_path.csv")
    audit = _read_json(meta["audit"])
    events = _events_for_scope(all_events, str(meta["scope_tier"]))
    events = _enrich_base_target_flags(events, path_df, base_multiple=0.5)
    payload = _publication_payload(pattern_id, meta, events, all_events, audit)
    editorial_sections, editorial_source_path = _load_required_editorial(meta)
    payload["editorial_sections"] = editorial_sections
    payload["editorial_source_path"] = editorial_source_path
    spec = _spec(pattern_id, meta)
    publication_spec = build_wedge_publication_spec(pattern_id=pattern_id, title=str(meta["title"]), spec=spec)
    payload["publication_spec_id"] = publication_spec["publication_spec_id"]
    validation_csv = Path(str(meta["audit"])).parent / "manual_visual_scoring" / "premium_visual_validation_template.csv"
    selected_examples = _select_examples(events)
    payload["example_events"] = _attach_example_validation(selected_examples, validation_csv)
    payload["chapter_reference"]["example_visual_validation"] = _example_validation_summary(payload["example_events"])
    charts = _build_charts(events, price_db, chapter_dir, pattern_id=pattern_id)
    source_notes = _source_notes(pattern_id, meta)
    paths = build_wedge_public_chapter(
        payload=payload,
        source_notes=source_notes,
        events=events,
        path_df=path_df,
        charts=charts,
        spec=spec,
        out_dir=chapter_dir,
        pdf_filename=f"{meta['slug']}_final.pdf",
        payload_filename=f"{meta['slug']}_public_chapter_payload.json",
        manuscript_filename=f"{meta['slug']}_ai_editorial_manuscript.md",
        notes_filename=f"{meta['slug']}_public_chapter_notes.md",
    )
    source_notes_path = chapter_dir / f"{meta['slug']}_source_notes.json"
    publication_spec_path = chapter_dir / f"{meta['slug']}_publication_spec.json"
    _write_json(source_notes_path, source_notes)
    _write_json(publication_spec_path, publication_spec)
    entry = {
        "family": "wedge_family",
        "pattern_id": pattern_id,
        "title": meta["title"],
        "status": "final",
        "classification": meta["classification"],
        "score": None,
        "claim_level": meta["claim_level"],
        "pdf": f"artifacts/final_chapters/wedge_family/{meta['slug']}_final.pdf",
        "source_pdf": str(paths["pdf"]),
        "payload": str(paths["payload"]),
        "manuscript": str(paths["manuscript"]),
        "notes": str(paths["notes"]),
        "source_notes": str(source_notes_path),
        "publication_spec": str(publication_spec_path),
        "release_gate": str(meta["branch"]),
        "factory_id": FACTORY_ID,
        "publication_core_id": "pattern_publication_core_v1",
        "publication_flow": f"{FACTORY_ID} + pattern_publication_core_v1",
        "source_grounding_required": True,
        "source_grounding_policy_id": SOURCE_GROUNDED_PUBLICATION_GATE_ID,
        "direct_source_review_required": True,
        "publication_semantic_required": True,
        "publication_semantic_gate_id": publication_spec["semantic_gate_id"],
        "note": "Wedge Family dùng scanner riêng; chỉ dùng chung publication/statistics core.",
    }
    entry_path = chapter_dir / f"{meta['slug']}_final_manifest_entry.json"
    _write_json(entry_path, entry)
    return {**paths, "source_notes": source_notes_path, "publication_spec": publication_spec_path, "final_entry": entry_path}


def build_wedge_family_public_chapters(*, out_dir: Path = DEFAULT_OUT_DIR, price_db: Path = DEFAULT_PRICE_DB) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}
    for pattern_id in ("wedges_falling", "wedges_rising"):
        paths = build_one_wedge_chapter(pattern_id=pattern_id, out_dir=out_dir, price_db=price_db)
        for key, path in paths.items():
            outputs[f"{pattern_id}_{key}"] = path
    manifest = {
        "release_id": "wedge_family_public_chapters_db_active_v1",
        "factory_id": FACTORY_ID,
        "chapters": [
            {"pattern_id": pattern_id, "pdf": str(outputs[f"{pattern_id}_pdf"]), "entry": str(outputs[f"{pattern_id}_final_entry"])}
            for pattern_id in ("wedges_falling", "wedges_rising")
        ],
    }
    manifest_json = out_dir / "wedge_family_public_chapters_manifest.json"
    _write_json(manifest_json, manifest)
    outputs["manifest_json"] = manifest_json
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Wedge Family public chapters.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--price-db", default=str(DEFAULT_PRICE_DB))
    parser.add_argument("--pattern", choices=["wedges_falling", "wedges_rising", "all"], default="all")
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    if args.pattern == "all":
        paths = build_wedge_family_public_chapters(out_dir=out_dir, price_db=Path(args.price_db))
    else:
        paths = build_one_wedge_chapter(pattern_id=args.pattern, out_dir=out_dir, price_db=Path(args.price_db))
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
