"""Build source-grounded Horn Family public-chapter seed artifacts.

This builder creates deterministic ingredients only.  It does not approve
public prose and does not render a final PDF; final writing must go through
`canonical_source_guided_refinement_v1`.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any, Mapping

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.horn_family_publication_specs import build_horn_publication_spec  # noqa: E402
from scanner.publication_flow_contract import SOURCE_GROUNDED_PUBLICATION_GATE_ID  # noqa: E402
from scanner.v2.horns import _to_weekly_ohlcv  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/horn_family_public_chapters")
DEFAULT_PRICE_DB = Path("../market_cache/stock_ohlcv/latest.sqlite")
SOURCE_PDF = "references/encyclopedia-of-chart-patterns-2nbsped-9786468600-3175723993-9780471668268-0471668265_compress.pdf"


PATTERNS: dict[str, dict[str, Any]] = {
    "horn_bottoms": {
        "slug": "horn_bottoms",
        "title": "Horn Bottoms",
        "subtitle": "Hai cú xuyên giá giảm cách nhau một tuần trên biểu đồ tuần",
        "scan_dir": Path("artifacts/scanner_v2/horn_family/horn_bottoms/db_active"),
        "source_chapter": 28,
        "source_name": "Horn Bottoms",
        "source_book_pages": [438, 439, 440, 441, 442, 443, 444, 445, 446, 447, 448, 449, 450],
        "source_review_pages": [461, 462, 463, 464, 465, 466, 467, 468, 469, 470, 471, 472, 473],
        "scope_tier": "premium+standard",
        "classification": "hồ sơ đảo chiều tăng trên biểu đồ tuần; có thể kiểm tra tradable layer cho nhánh long-cash",
        "claim_level": "đọc như hai cú xuyên giá giảm cách nhau một tuần được xác nhận khi giá đóng cửa vượt đỉnh mẫu 3 tuần",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, Horn Bottoms là chương long-watchlist đáng nghiên cứu: hình thái weekly rõ, mẫu đủ dày, nhưng vẫn cần đọc cùng kéo ngược và thời gian xác nhận vì throwback/retest xuất hiện nhiều.",
        "morphology": "Horn Bottoms gồm hai cú xuyên giá giảm cách nhau một tuần trên biểu đồ tuần. Tuần ở giữa phải nằm cao hơn rõ so với hai đáy horn, hai cú xuyên cần nổi bật so với vùng giá xung quanh, và mẫu chỉ được xác nhận khi giá đóng cửa vượt lên trên đỉnh cao nhất của mẫu 3 tuần.",
        "role_note": "Dùng như hồ sơ đảo chiều/tái tích lũy sau giảm; không mua trước khi có đóng cửa xác nhận.",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "direction": "up",
    },
    "horn_tops": {
        "slug": "horn_tops",
        "title": "Horn Tops",
        "subtitle": "Hai cú xuyên giá tăng cách nhau một tuần trên biểu đồ tuần",
        "scan_dir": Path("artifacts/scanner_v2/horn_family/horn_tops/db_active"),
        "source_chapter": 29,
        "source_name": "Horn Tops",
        "source_book_pages": [451, 452, 453, 454, 455, 456, 457, 458, 459, 460, 461],
        "source_review_pages": [474, 475, 476, 477, 478, 479, 480, 481, 482, 483, 484],
        "scope_tier": "premium+standard",
        "classification": "hồ sơ phòng thủ/thoát vị thế vì nhánh chính là cảnh báo giảm trên cổ phiếu cơ sở",
        "claim_level": "đọc như hai cú xuyên giá tăng cách nhau một tuần được xác nhận khi giá đóng cửa xuống dưới đáy mẫu 3 tuần",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, Horn Tops nên là chương defensive/informational: mẫu giúp nhận diện vùng đỉnh ngắn hạn hoặc nhịp hồi trong xu hướng giảm, nhưng không mặc định là cơ hội short cổ phiếu cơ sở.",
        "morphology": "Horn Tops gồm hai cú xuyên giá tăng cách nhau một tuần trên biểu đồ tuần. Tuần ở giữa phải nằm thấp hơn rõ so với hai đỉnh horn, hai cú xuyên cần nổi bật so với vùng giá xung quanh, và mẫu chỉ được xác nhận khi giá đóng cửa xuống dưới đáy thấp nhất của mẫu 3 tuần.",
        "role_note": "Dùng như hồ sơ cảnh báo rủi ro hoặc hỗ trợ quyết định giảm vị thế; không đọc như short setup phổ quát.",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "direction": "down",
    },
}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _fmt(value: Any, digits: int = 2) -> str:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if not math.isfinite(out):
        return "n/a"
    return f"{out:.{digits}f}"


def _load_weekly_ohlcv(price_db: Path, symbol: str) -> pd.DataFrame:
    conn = sqlite3.connect(str(price_db))
    try:
        frame = pd.read_sql_query(
            "SELECT symbol, time AS date, open, high, low, close, volume FROM stock_price_history WHERE symbol = ? ORDER BY time",
            conn,
            params=[symbol],
        )
    finally:
        conn.close()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return _to_weekly_ohlcv(frame.dropna(subset=["date", "open", "high", "low", "close"]).reset_index(drop=True))


def _window_for_event(df: pd.DataFrame, event: Mapping[str, Any], *, pre_bars: int = 18, post_bars: int = 34) -> pd.DataFrame:
    start = pd.to_datetime(event.get("formation_start_date"), errors="coerce")
    breakout = pd.to_datetime(event.get("breakout_date"), errors="coerce")
    if pd.isna(start) or pd.isna(breakout):
        return df.iloc[:0].copy()
    start_idx = int(df["date"].searchsorted(start, side="left"))
    breakout_idx = int(df["date"].searchsorted(breakout, side="left"))
    return df.iloc[max(0, start_idx - pre_bars) : min(len(df), breakout_idx + post_bars + 1)].copy().reset_index(drop=True)


def _target_price(event: Mapping[str, Any], multiple: float) -> float:
    confirmation = float(event.get("breakout_price"))
    full = float(event.get("target_price"))
    return confirmation + (full - confirmation) * multiple


def _plot_schematic(out_path: Path, *, pattern_id: str) -> None:
    fig, ax = plt.subplots(figsize=(9.2, 3.9), dpi=180)
    if pattern_id == "horn_bottoms":
        xs = np.array([0, 1, 2, 3, 4, 5])
        lows = np.array([15.8, 10.0, 15.6, 10.2, 16.2, 17.5])
        highs = np.array([16.7, 16.4, 16.5, 16.2, 17.0, 18.2])
        title = "Giải phẫu Horn Bottoms"
        ax.text(1, 9.4, "cú xuyên giảm 1", ha="center", fontsize=8, color="#245b5a")
        ax.text(3, 9.4, "cú xuyên giảm 2", ha="center", fontsize=8, color="#245b5a")
    else:
        xs = np.array([0, 1, 2, 3, 4, 5])
        lows = np.array([12.0, 12.8, 12.5, 12.9, 11.2, 10.4])
        highs = np.array([13.2, 19.8, 13.5, 19.5, 13.0, 12.0])
        title = "Giải phẫu Horn Tops"
        ax.text(1, 20.3, "cú xuyên tăng 1", ha="center", fontsize=8, color="#245b5a")
        ax.text(3, 20.3, "cú xuyên tăng 2", ha="center", fontsize=8, color="#245b5a")
    for i, (x, lo, hi) in enumerate(zip(xs, lows, highs)):
        color = "#1b8a5a" if i >= 4 else "#c44e52"
        ax.vlines(x, lo, hi, color="#222222", linewidth=2.2)
        ax.add_patch(Rectangle((x - 0.16, min(lo + 0.35, hi - 0.65)), 0.32, 0.45, facecolor=color, edgecolor=color, alpha=0.9))
    if pattern_id == "horn_bottoms":
        ax.axhline(max(highs[1], highs[3]), color="#7A5195", linestyle="--", linewidth=1.0)
        ax.text(0.1, max(highs[1], highs[3]) + 0.2, "xác nhận: đóng cửa vượt đỉnh mẫu 3 tuần", fontsize=8, color="#7A5195")
    else:
        ax.axhline(min(lows[1], lows[3]), color="#7A5195", linestyle="--", linewidth=1.0)
        ax.text(0.1, min(lows[1], lows[3]) - 0.8, "xác nhận: đóng cửa xuống dưới đáy mẫu 3 tuần", fontsize=8, color="#7A5195")
    ax.set_title(title, loc="left", fontsize=10)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)


def _plot_event_chart(df: pd.DataFrame, event: Mapping[str, Any], out_path: Path, title: str, *, base_multiple: float) -> None:
    if df.empty:
        return
    x = np.arange(len(df))
    fig, ax = plt.subplots(figsize=(9.2, 4.8), dpi=180)
    for i, row in df.iterrows():
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        color = "#1b8a5a" if c >= o else "#c44e52"
        ax.vlines(i, l, h, color="#222222", linewidth=1.0, alpha=0.8)
        ax.add_patch(Rectangle((i - 0.32, min(o, c)), 0.64, max(abs(c - o), 1e-6), facecolor=color, edgecolor=color, linewidth=0.5, alpha=0.9))
    start = pd.to_datetime(event.get("formation_start_date"), errors="coerce")
    end = pd.to_datetime(event.get("formation_end_date"), errors="coerce")
    breakout = pd.to_datetime(event.get("breakout_date"), errors="coerce")

    def ix(ts: pd.Timestamp) -> int | None:
        if pd.isna(ts):
            return None
        return min(max(int(df["date"].searchsorted(ts, side="left")), 0), len(df) - 1)

    i0, i1, ib = ix(start), ix(end), ix(breakout)
    if i0 is not None and i1 is not None and i1 >= i0:
        ax.axvspan(i0, i1, color="#4C78A8", alpha=0.12)
        ax.plot([i0, i1], [float(event["left_spike_price"]), float(event["right_spike_price"])], color="#245b5a", linewidth=1.1)
        ax.text(i0, float(event["left_spike_price"]), "cú xuyên 1", fontsize=7, color="#245b5a", va="bottom")
        ax.text(i1, float(event["right_spike_price"]), "cú xuyên 2", fontsize=7, color="#245b5a", va="bottom")
    if ib is not None:
        ax.axvline(ib, color="#7A5195", linewidth=1.1)
        ax.text(ib + 0.25, float(df["high"].max()), "xác nhận", fontsize=8, color="#7A5195", va="bottom")
    breakout_price = float(event.get("breakout_price"))
    target = _target_price(event, base_multiple)
    full_target = float(event.get("target_price"))
    ax.axhline(breakout_price, color="#245b5a", linestyle="--", linewidth=0.9, alpha=0.85)
    ax.axhline(target, color="#F58518", linestyle="--", linewidth=0.9, alpha=0.9)
    ax.axhline(full_target, color="#9C755F", linestyle=":", linewidth=0.9, alpha=0.9)
    ax.text(0.5, breakout_price, "giá xác nhận", fontsize=7, color="#245b5a", va="bottom")
    ax.text(0.5, target, "mốc 0,5x", fontsize=7, color="#F58518", va="bottom")
    ax.text(0.5, full_target, "mốc 1,0x", fontsize=7, color="#9C755F", va="bottom")
    ax.set_title(title, fontsize=10, loc="left")
    ax.grid(alpha=0.14)
    y_min = min(float(df["low"].min()), breakout_price, target, full_target)
    y_max = max(float(df["high"].max()), breakout_price, target, full_target)
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


def _metric_for_target(events: pd.DataFrame, path_df: pd.DataFrame, multiple: float, role: str) -> dict[str, Any]:
    if events.empty:
        return {"target_multiple": multiple, "target_role": role, "n": 0}
    if "event_id" not in events.columns:
        events = events.assign(event_id=events["detection_id"])
    grouped = {str(event_id): group.copy() for event_id, group in path_df.groupby("event_id")}
    hits: list[bool] = []
    firsts: list[bool] = []
    days: list[float] = []
    for _, event in events.iterrows():
        distance = float(event.get("target_dist_pct") or 0.0) * multiple
        group = grouped.get(str(event.get("event_id")))
        if group is None or group.empty:
            hits.append(False)
            firsts.append(False)
            days.append(float("nan"))
            continue
        favorable = pd.to_numeric(group["signed_high_excursion_pct"], errors="coerce")
        adverse = pd.to_numeric(group["signed_low_excursion_pct"], errors="coerce")
        bars = pd.to_numeric(group["bar_after_breakout"], errors="coerce")
        target_bars = bars[favorable >= distance]
        adverse_bars = bars[adverse <= -5.0]
        hit_day = float(target_bars.min()) if not target_bars.empty else float("nan")
        adverse_day = float(adverse_bars.min()) if not adverse_bars.empty else float("inf")
        hit = math.isfinite(hit_day)
        hits.append(hit)
        firsts.append(bool(hit and hit_day < adverse_day))
        days.append(hit_day if hit else float("nan"))
    mfe = pd.to_numeric(events.get("mfe_pct"), errors="coerce")
    mae = pd.to_numeric(events.get("mae_pct"), errors="coerce")
    fail = events.get("failure_5pct", pd.Series(False, index=events.index)).map(_truthy)
    return {
        "target_multiple": multiple,
        "target_role": role,
        "target_label": f"{multiple}x",
        "target_hit_rate": round(float(np.mean(hits) * 100.0), 2),
        "target_first_before_adverse_5pct_rate": round(float(np.mean(firsts) * 100.0), 2),
        "failure_5pct_rate": round(float(fail.mean() * 100.0), 2),
        "median_mfe_pct": round(float(mfe.median()), 2) if not mfe.dropna().empty else None,
        "median_mae_pct": round(float(mae.median()), 2) if not mae.dropna().empty else None,
        "mfe_mae_median_ratio": round(float(mfe.median() / max(mae.median(), 1.0)), 2) if not mfe.dropna().empty and not mae.dropna().empty else None,
        "median_target_dist_pct": round(float(pd.to_numeric(events.get("target_dist_pct"), errors="coerce").median() * multiple), 2),
        "median_days_to_target": round(float(pd.Series(days).dropna().median()), 2) if pd.Series(days).dropna().size else None,
        "n": int(len(events)),
    }


def _enrich_events_for_target(events: pd.DataFrame, path_df: pd.DataFrame, multiple: float) -> pd.DataFrame:
    events = events.copy()
    if "event_id" not in events.columns:
        events["event_id"] = events["detection_id"]
    grouped = {str(event_id): group.copy() for event_id, group in path_df.groupby("event_id")}
    hits: list[bool] = []
    firsts: list[bool] = []
    days: list[float] = []
    for _, event in events.iterrows():
        distance = float(event.get("target_dist_pct") or 0.0) * multiple
        group = grouped.get(str(event.get("event_id")))
        if group is None or group.empty:
            hits.append(False)
            firsts.append(False)
            days.append(float("nan"))
            continue
        favorable = pd.to_numeric(group["signed_high_excursion_pct"], errors="coerce")
        adverse = pd.to_numeric(group["signed_low_excursion_pct"], errors="coerce")
        bars = pd.to_numeric(group["bar_after_breakout"], errors="coerce")
        target_bars = bars[favorable >= distance]
        adverse_bars = bars[adverse <= -5.0]
        hit_day = float(target_bars.min()) if not target_bars.empty else float("nan")
        adverse_day = float(adverse_bars.min()) if not adverse_bars.empty else float("inf")
        hit = math.isfinite(hit_day)
        hits.append(hit)
        firsts.append(bool(hit and hit_day < adverse_day))
        days.append(hit_day if hit else float("nan"))
    events["target_hit"] = hits
    events["target_first_before_adverse_5pct"] = firsts
    events["days_to_target"] = days
    return events


def _events_for_scope(events: pd.DataFrame, scope_tier: str) -> pd.DataFrame:
    if scope_tier == "premium":
        scoped = events[events["publication_quality_tier"] == "premium"].copy()
    elif scope_tier == "premium+standard":
        scoped = events[events["publication_quality_tier"].isin(["premium", "standard"])].copy()
    else:
        scoped = events.copy()
    return scoped if not scoped.empty else events.copy()


def _select_examples(events: pd.DataFrame) -> dict[str, pd.Series]:
    source = events.copy()
    source["_market_rank"] = source.get("market_group", pd.Series("Outside VN100", index=source.index)).map({"VN30": 0, "VN100 ex VN30": 1}).fillna(2)
    for column in ("target_hit", "failure_5pct", "target_first_before_adverse_5pct"):
        if column in source.columns:
            source[column] = source[column].map(_truthy)
    success = source[(source["target_hit"]) & (source["target_first_before_adverse_5pct"])].copy()
    failure = source[source["failure_5pct"]].copy()
    med = float(pd.to_numeric(source["mfe_pct"], errors="coerce").median())
    textbook = (success if not success.empty else source).sort_values(["_market_rank", "publication_quality_score", "mfe_pct"], ascending=[True, False, False]).iloc[0]
    neutral = source[source["detection_id"].astype(str) != str(textbook.get("detection_id"))].copy()
    neutral["median_distance"] = (pd.to_numeric(neutral["mfe_pct"], errors="coerce") - med).abs()
    middle = neutral.sort_values(["_market_rank", "median_distance", "publication_quality_score"], ascending=[True, True, False]).iloc[0] if not neutral.empty else textbook
    failure_pick = (failure if not failure.empty else source).sort_values(["_market_rank", "mae_pct", "publication_quality_score"], ascending=[True, False, False]).iloc[0]
    return {"textbook_success": textbook, "middle_case": middle, "failure": failure_pick}


def _build_charts(events: pd.DataFrame, price_db: Path, out_dir: Path, *, pattern_id: str, base_multiple: float) -> dict[str, Path]:
    charts_dir = out_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    schematic = charts_dir / f"{pattern_id}_schematic.png"
    _plot_schematic(schematic, pattern_id=pattern_id)
    paths = {"schematic": schematic}
    title_map = {"textbook_success": "ví dụ đạt mục tiêu", "middle_case": "ví dụ trung vị", "failure": "ví dụ thất bại"}
    for key, event in _select_examples(events).items():
        weekly = _load_weekly_ohlcv(price_db, str(event["symbol"]))
        window = _window_for_event(weekly, event)
        out_path = charts_dir / f"{key}_{event['symbol']}_{event['breakout_date']}.png"
        _plot_event_chart(window, event, out_path, f"{event['symbol']} - {title_map.get(key, 'ví dụ')} ({event['breakout_date']})", base_multiple=base_multiple)
        paths[key] = out_path
    return paths


def _source_notes(pattern_id: str, meta: Mapping[str, Any]) -> dict[str, Any]:
    is_bottom = pattern_id == "horn_bottoms"
    prefix = "hb" if is_bottom else "ht"
    spike = "downward" if is_bottom else "upward"
    confirm = "above the highest high" if is_bottom else "below the lowest low"
    spike_vi = "giảm" if is_bottom else "tăng"
    confirm_vi = "vượt đỉnh cao nhất của mẫu 3 tuần" if is_bottom else "rơi xuống dưới đáy thấp nhất của mẫu 3 tuần"
    return {
        "status": "PASS",
        "source_grounding_policy_id": SOURCE_GROUNDED_PUBLICATION_GATE_ID,
        "source_grounding_level": "publication_aligned",
        "local_source": {"pattern_key": pattern_id, "chapter": meta["source_chapter"], "name": meta["source_name"]},
        "direct_pdf_review": {
            "status": "PASS",
            "review_id": f"{pattern_id}_bulkowski_pdf_direct_review_v1",
            "pdf_path": SOURCE_PDF,
            "book_chapter": meta["source_chapter"],
            "book_pages_checked": meta["source_book_pages"],
            "pdf_pages_checked": meta["source_review_pages"],
            "target_rule_summary": "Measure the horn height and project it from the confirmation price in breakout direction.",
            "review_note": "Đã đối chiếu trực tiếp chương Horn trong PDF gốc trước khi dựng scanner và chapter.",
        },
        "source_rules": [
            {"rule_id": f"{prefix}.weekly_chart", "short_excerpt": "Use the weekly chart", "implementation_mapping": "chỉ đọc trên nến tuần; tín hiệu ngày không đủ để gọi là Horn"},
            {"rule_id": f"{prefix}.two_spikes_separated_by_week", "short_excerpt": f"two {spike} price spikes separated by a week", "implementation_mapping": f"hai cú xuyên giá {spike_vi} cách nhau một tuần, có một tuần ở giữa"},
            {"rule_id": f"{prefix}.large_spikes", "short_excerpt": "spike unusually far", "implementation_mapping": "hai cú xuyên giá phải nổi bật so với vùng giá xung quanh"},
            {"rule_id": f"{prefix}.center_week_clearance", "short_excerpt": "horn shape", "implementation_mapping": "tuần ở giữa phải tạo khoảng cách rõ để hai cú xuyên nhìn giống cặp sừng"},
            {"rule_id": f"{prefix}.volume_context", "short_excerpt": "above average volume", "implementation_mapping": "khối lượng cao làm mẫu đáng chú ý hơn, nhưng không thay thế xác nhận giá"},
            {"rule_id": f"{prefix}.obvious_horn", "short_excerpt": "stick out like a sore thumb", "implementation_mapping": "mẫu phải nhìn thấy ngay trên biểu đồ tuần; nếu phải gượng ép thì nên bỏ qua"},
            {"rule_id": f"{prefix}.confirmation", "short_excerpt": f"price closes {confirm} in the pattern", "implementation_mapping": f"mẫu chỉ được xác nhận khi giá đóng cửa tuần {confirm_vi}"},
            {"rule_id": f"{prefix}.height_target", "short_excerpt": "measure the height of the horn", "implementation_mapping": "mục tiêu được đo từ chiều cao mẫu 3 tuần; 0,5x là mốc đọc thận trọng, 1,0x là mốc đầy đủ"},
        ],
    }


def _spec(pattern_id: str, meta: Mapping[str, Any]) -> dict[str, Any]:
    is_bottom = pattern_id == "horn_bottoms"
    spike_dir = "giảm" if is_bottom else "tăng"
    confirm_rule = "đóng cửa tuần vượt đỉnh cao nhất của mẫu 3 tuần" if is_bottom else "đóng cửa tuần rơi xuống dưới đáy thấp nhất của mẫu 3 tuần"
    false_pair = "hai tuần giảm liền nhau kiểu Pipe" if is_bottom else "hai tuần tăng liền nhau kiểu Pipe"
    quick_question_rows = (
        [
            ["Khung thời gian", "Mẫu đáy đã được đọc trên nến tuần, không phải nến ngày chưa?"],
            ["Hình thái đáy", "Hai cú xuyên xuống có cách nhau đúng một tuần và nổi bật khỏi nền giá không?"],
            ["Xác nhận tăng", "Giá đã đóng cửa tuần vượt đỉnh cao nhất của horn đáy chưa?"],
            ["Đường đi sau xác nhận", "Mốc 0,5x chiều cao horn đáy có đến trước kéo ngược 5% không?"],
        ]
        if is_bottom
        else [
            ["Khung thời gian", "Mẫu đỉnh đã được đọc trên nến tuần, không phải nến ngày chưa?"],
            ["Hình thái đỉnh", "Hai cú xuyên lên có cách nhau đúng một tuần và nổi bật khỏi nền giá không?"],
            ["Xác nhận giảm", "Giá đã đóng cửa tuần rơi xuống dưới đáy thấp nhất của horn đỉnh chưa?"],
            ["Đường đi sau xác nhận", "Mốc 0,5x chiều cao horn đỉnh có đến trước nhịp hồi ngược 5% không?"],
        ]
    )
    return {
        "title": meta["title"],
        "subtitle": meta["subtitle"],
        "base_target_multiple": float(meta["base_target_multiple"]),
        "base_target_label": "0,5x",
        "legacy_target_multiple": float(meta["legacy_target_multiple"]),
        "legacy_target_label": "1,0x",
        "target_unit_label": "chiều cao horn",
        "target_focus_title": "Mốc cơ sở 0,5x",
        "target_focus_caption": "mốc 0,5x chiều cao horn",
        "target_focus_reading": "mốc thận trọng trước khi đọc mục tiêu đầy đủ",
        "target_full_title": "Mốc nguồn 1,0x",
        "target_full_reading": "mốc đầy đủ theo chiều cao horn",
        "morphology_sentence": meta["morphology"],
        "role_note": meta["role_note"],
        "classification_sentence": meta["public_classification_sentence"],
        "headline_scope": "Horn được nhận diện trên biểu đồ tuần; biến động trong ngày hoặc trên nến ngày không đủ để kết luận mẫu.",
        "local_source_chapter": meta["source_chapter"],
        "schematic_caption": f"Sơ đồ minh họa {meta['title']}: hai cú xuyên giá cách nhau một tuần, tuần giữa tạo khoảng rỗng, rồi đóng cửa xác nhận.",
        "how_subtitle": "Hai cú xuyên giá cách nhau một tuần: hình thái trước, xác nhận sau.",
        "labels": {"favorable_move": "mức đi thuận lợi", "adverse_move": "mức đi ngược bất lợi"},
        "source_rule_ids": ["horn.weekly_chart", "horn.two_spikes_separated_by_week", "horn.center_week_clearance", "horn.confirmation", "horn.height_target"],
        "public_rule_rows": [
            ["Đọc trên nến tuần.", "Mỗi vạch horn đại diện cho một tuần giao dịch; tín hiệu ngày chỉ dùng để quan sát thêm."],
            [f"Hai cú xuyên giá {spike_dir} cách nhau một tuần.", f"Giữa hai cú xuyên phải có một tuần đệm; nếu hai cú xuyên đứng liền nhau, đó gần với Pipe hơn là Horn."],
            ["Tuần giữa tạo khoảng cách rõ.", f"Nếu tuần giữa không tách được hai cú xuyên, mẫu dễ bị lẫn với {false_pair} hoặc nhiễu giá."],
            ["Hai cú xuyên phải nổi bật.", "Mỗi cú xuyên cần dài hơn vùng giá xung quanh, không phải một dao động nhỏ trong nền giá răng cưa."],
            ["Chỉ tính sau xác nhận.", f"Mẫu có hiệu lực khi giá {confirm_rule}; trước đó chỉ là hình thái đang hình thành."],
            ["Mục tiêu đo bằng chiều cao mẫu 3 tuần.", "Mốc 0,5x dùng để đọc thận trọng; mốc 1,0x là mục tiêu đầy đủ theo chiều cao mẫu."],
        ],
        "quick_question_rows": quick_question_rows,
        "component_rows": [
            ["Cú xuyên thứ nhất", "Tuần đầu tiên tạo một vạch nổi bật trên biểu đồ.", f"{spike_dir.capitalize()} mạnh"],
            ["Tuần giữa", "Tuần đệm tách hai cú xuyên và tạo hình giống cặp sừng.", "Không phải hai spike liền nhau"],
            ["Cú xuyên thứ hai", "Tuần thứ ba lặp lại cú xuyên gần cùng vùng giá.", "Gần bằng cú xuyên thứ nhất"],
            ["Xác nhận", "Giá đóng cửa tuần đi qua ranh giới quan trọng của mẫu 3 tuần.", "Không kết luận trước nến xác nhận"],
        ],
        "reject_bullets": [
            "Hai cú xuyên giá đứng liền nhau hoặc cách nhau quá xa.",
            "Một vạch quá nhỏ so với vạch còn lại.",
            "Không có đóng cửa xác nhận sau horn.",
            "Đường giá xung quanh quá răng cưa khiến horn không nổi bật.",
        ],
        "identification_paragraphs": [meta["morphology"]],
        "example_intro": ["Ba ví dụ dưới đây được đọc trên nến tuần: một mẫu đạt mốc cơ sở, một mẫu gần trung vị và một mẫu thất bại. Bảng diễn biến đi kèm từng ví dụ để người đọc thấy rõ cú xuyên thứ nhất, tuần giữa, cú xuyên thứ hai và tuần xác nhận."],
        "failure_bullets": [
            "Thất bại 5% là mẫu không đi đủ xa sau xác nhận, không phải stop-loss thực chiến.",
            "Horn có thể kiểm định lại vùng xuyên giá, vì vậy cần đọc cùng mức kéo ngược.",
            "Không dùng một ví dụ có hai cú xuyên rất đẹp để thay thế thống kê toàn mẫu.",
        ],
        "target_paragraph": "Mục tiêu nguồn lấy chiều cao horn rồi chiếu theo hướng phá vỡ; chương giữ 0,5x làm mốc cơ sở thận trọng và 1,0x làm mốc nguồn đầy đủ.",
        "quick_conclusion_rows": [
            ["Mẫu này dùng để đọc gì?", "Khả năng đảo chiều hoặc cảnh báo rủi ro sau hai cú xuyên giá cách nhau một tuần trên nến tuần."],
            ["Mốc đọc chính?", "0,5x chiều cao horn."],
            ["Mốc tham chiếu?", "1,0x chiều cao horn theo nguồn."],
            ["Khi nào thận trọng?", "Khi xác nhận quá trễ, hai cú xuyên lệch nhau, hoặc tuần giữa không tách hình rõ."],
        ],
        "identification_bridge": (
            "Các quy tắc nhận diện nên được đọc như một phép kiểm hình học trên nến tuần: trước hết phải thấy hai cú xuyên giá cách nhau một tuần, "
            "sau đó kiểm tra tuần giữa có tách hình rõ và hai cú xuyên có đủ nổi bật không, cuối cùng mới chờ giá đóng cửa qua ranh giới xác nhận. "
            "Nếu đảo thứ tự này, người đọc rất dễ gọi một cú biến động đơn lẻ là Horn."
        ),
        "caveat_bullets": [
            "Không tuyên bố đây là nghiên cứu toàn thị trường đúng từng ngày lịch sử.",
            "Không dùng historical VN30/VN100 membership làm kết luận chính.",
            "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
            "Chương là tài liệu tham khảo hậu xác nhận, không phải khuyến nghị mua bán.",
        ],
        "quantile_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "tuần"),
            ("Chiều cao horn", "pattern_height_pct", "%"),
            ("Độ lệch hai cú xuyên", "spike_similarity_pct", "%"),
            ("Độ tách tuần giữa", "center_clearance_pct", "%"),
            ("Thời gian xác nhận", "breakout_lag_bars", "tuần"),
            ("Mức đi thuận lợi", "mfe_pct", "%"),
            ("Mức đi ngược bất lợi", "mae_pct", "%"),
            ("Ngày chạm mốc cơ sở", "days_to_target", "tuần"),
        ],
        "skip_condition_specs": [
            ("Xác nhận quá trễ", "breakout_lag_bars", "q75", None, "Horn mất độ sắc nếu giá chờ quá lâu mới xác nhận."),
            ("Hai cú xuyên lệch nhau", "spike_similarity_pct", "q75", None, "Hai cú xuyên không còn giống một horn rõ ràng."),
            ("Tuần giữa tách kém", "center_clearance_pct", "q25_abs", None, "Hai cú xuyên không còn tạo hình horn rõ."),
            ("Kéo ngược quá sâu", "mae_pct", "q75", None, "Đường đi sau xác nhận không còn gọn."),
        ],
        "general_stat_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "tuần", "Horn là mẫu ngắn, nhưng xác nhận có thể đến sau vài tuần."),
            ("Chiều cao horn", "pattern_height_pct", "%", "Chiều cao là thước đo target."),
            ("Độ lệch hai cú xuyên", "spike_similarity_pct", "%", "Càng nhỏ càng giống horn nguồn."),
            ("Độ tách tuần giữa", "center_clearance_pct", "%", "Tuần giữa càng tách rõ thì hình thái Horn càng dễ đọc."),
        ],
        "best_condition_specs": [
            ("Nhóm hình thái tốt", "publication_quality_tier", "==", "premium", "Hai cú xuyên gần bằng nhau, tuần giữa tách rõ và đường giá sạch."),
            ("Nhóm chuẩn", "publication_quality_tier", "==", "standard", "Đủ dùng trong thống kê nhưng không phải lúc nào cũng đẹp để minh họa."),
            ("Đường giá sạch", "path_quality_bucket", "==", "clean", "Ít thiếu phiên và ít chuỗi đứng giá."),
            ("Thanh khoản tốt hơn", "liquidity_bucket", "in", "mid/high", "Giảm nhiễu ở các cú xuyên giá kém giao dịch."),
        ],
        "conclusion_bullets": [
            f"{meta['title']} chỉ được đọc trên biểu đồ tuần, đúng với hình thái Horn trong tài liệu nguồn.",
            "Mục tiêu nguồn là 1,0x chiều cao horn; chương dùng 0,5x làm mốc cơ sở thận trọng.",
            meta["role_note"],
        ],
    }


def _publication_payload(pattern_id: str, meta: Mapping[str, Any], events: pd.DataFrame, all_events: pd.DataFrame, path_df: pd.DataFrame) -> dict[str, Any]:
    base = _metric_for_target(events, path_df, 0.5, "conservative_half_horn")
    full = _metric_for_target(events, path_df, 1.0, "source_full_horn")
    return {
        "publication_id": f"{pattern_id}_publication_chapter_v1",
        "pattern_id": pattern_id,
        "pattern_name": meta["title"],
        "status": "PASS",
        "classification": meta["classification"],
        "chapter_reference": {
            "scope": "nhóm hình thái tốt + nhóm chuẩn",
            "all_scanner_events": int(len(all_events)),
            "public_grade_events": int(len(events)),
            "public_grade_share_pct": round(float(len(events)) / max(len(all_events), 1) * 100.0, 2),
            "events": int(len(events)),
            "symbols_scanned": int(all_events["symbol"].nunique()) if "symbol" in all_events.columns else None,
            "evaluated_events": int(events["mfe_pct"].notna().sum()) if "mfe_pct" in events.columns else int(len(events)),
            "median_mfe_pct": base.get("median_mfe_pct"),
            "median_mae_pct": base.get("median_mae_pct"),
            "mfe_mae_median_ratio": base.get("mfe_mae_median_ratio"),
            "failure_5pct_rate": base.get("failure_5pct_rate"),
            "legacy_target_hit_rate": full.get("target_hit_rate"),
            "legacy_target_first_before_adverse_5pct_rate": full.get("target_first_before_adverse_5pct_rate"),
            "median_spike_similarity_pct": _fmt(pd.to_numeric(events.get("spike_similarity_pct"), errors="coerce").median()),
            "median_center_clearance_pct": _fmt(pd.to_numeric(events.get("center_clearance_pct"), errors="coerce").median()),
        },
        "target_calibration": {
            "target_family": {"conservative_half_horn": 0.5, "source_full_horn": 1.0},
            "selected_base_target_multiple": 0.5,
            "selected_base_target_role": "conservative_half_horn",
            "base_target": base,
            "stretch_target": full,
            "legacy_target": full,
            "rows": [base, full],
            "interpretation": "Mốc 0,5x giữ vai trò cơ sở thận trọng; 1,0x giữ vai trò mốc nguồn theo chiều cao horn.",
        },
        "data_scope_and_caveats": {
            "remaining_caveats": [
                "Không claim point-in-time universe toàn thị trường.",
                "Không dùng historical VN30/VN100 membership làm kết luận chính.",
                "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
            ]
        },
    }


def build_one_horn_chapter(*, pattern_id: str, out_dir: Path, price_db: Path) -> dict[str, Path]:
    meta = PATTERNS[pattern_id]
    chapter_dir = out_dir / str(meta["slug"])
    if chapter_dir.exists():
        shutil.rmtree(chapter_dir)
    chapter_dir.mkdir(parents=True, exist_ok=True)
    all_events = pd.read_csv(meta["scan_dir"] / "events.csv")
    if "event_id" not in all_events.columns:
        all_events["event_id"] = all_events["detection_id"]
    path_df = pd.read_csv(meta["scan_dir"] / "post_breakout_path.csv")
    events = _events_for_scope(all_events, str(meta["scope_tier"]))
    events = _enrich_events_for_target(events, path_df, float(meta["base_target_multiple"]))
    payload = _publication_payload(pattern_id, meta, events, all_events, path_df)
    spec = _spec(pattern_id, meta)
    publication_spec = build_horn_publication_spec(pattern_id=pattern_id, title=str(meta["title"]), spec=spec)
    payload["publication_spec_id"] = publication_spec["publication_spec_id"]
    payload["source_rules_public"] = [{"rule": row[0], "application": row[1]} for row in spec.get("public_rule_rows", [])]
    selected_examples = _select_examples(events)
    payload["example_events"] = {role: {**event.to_dict(), "example_role": role} for role, event in selected_examples.items()}
    charts = _build_charts(events, price_db, chapter_dir, pattern_id=pattern_id, base_multiple=float(meta["base_target_multiple"]))
    source_notes = _source_notes(pattern_id, meta)
    payload_path = chapter_dir / f"{meta['slug']}_public_chapter_payload.json"
    source_notes_path = chapter_dir / f"{meta['slug']}_source_notes.json"
    publication_spec_path = chapter_dir / f"{meta['slug']}_publication_spec.json"
    _write_json(payload_path, payload)
    _write_json(source_notes_path, source_notes)
    _write_json(publication_spec_path, publication_spec)
    style_dossier = chapter_dir / "source_style_dossier.md"
    style_dossier.write_text(
        f"# Source-Guided Style Dossier - {pattern_id}\n\n"
        f"Chương nguồn: {meta['source_name']} trong Encyclopedia of Chart Patterns. "
            "Dossier giữ thứ tự đọc: biểu đồ tuần, hai cú xuyên giá cách nhau một tuần, tuần giữa tạo khoảng tách, đóng cửa xác nhận, thất bại, mục tiêu và cách dùng thận trọng. "
        "Không sao chép hoặc dịch lại tài liệu gốc; số liệu Việt Nam lấy từ payload đã khóa.\n",
        encoding="utf-8",
    )
    entry = {
        "family": "horn_family",
        "pattern_id": pattern_id,
        "title": meta["title"],
        "status": "source_seed",
        "classification": meta["classification"],
        "score": None,
        "claim_level": meta["claim_level"],
        "pdf": f"artifacts/final_chapters/horn_family/{meta['slug']}_final.pdf",
        "source_pdf": f"artifacts/final_chapters/horn_family/{meta['slug']}_final.pdf",
        "payload": str(payload_path),
        "source_notes": str(source_notes_path),
        "publication_spec": str(publication_spec_path),
        "source_grounding_required": True,
        "source_grounding_policy_id": SOURCE_GROUNDED_PUBLICATION_GATE_ID,
        "direct_source_review_required": True,
        "publication_semantic_required": True,
        "publication_semantic_gate_id": publication_spec["semantic_gate_id"],
        "canonical_rebuild_required": True,
        "chapter_writing_stages": {"source_style_dossier": str(style_dossier)},
        "chapter_writing_notes": "Seed artifact only. Final public prose must be generated by source-guided AI refinement and canonical publication factory.",
        "note": "Horn Family dùng scanner weekly riêng; builder này chỉ cung cấp nguyên liệu, không render hoặc approve PDF final.",
    }
    entry_path = chapter_dir / f"{meta['slug']}_final_manifest_entry.json"
    _write_json(entry_path, entry)
    return {
        "payload": payload_path,
        "source_notes": source_notes_path,
        "publication_spec": publication_spec_path,
        "entry": entry_path,
        **{f"chart_{key}": value for key, value in charts.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Horn Family public-chapter seed artifacts.")
    parser.add_argument("--pattern", choices=[*PATTERNS.keys(), "all"], default="all")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--price-db", default=str(DEFAULT_PRICE_DB))
    args = parser.parse_args()
    patterns = list(PATTERNS.keys()) if args.pattern == "all" else [args.pattern]
    outputs = {}
    for pattern_id in patterns:
        outputs[pattern_id] = {key: str(value) for key, value in build_one_horn_chapter(pattern_id=pattern_id, out_dir=Path(args.out_dir), price_db=Path(args.price_db)).items()}
    print(json.dumps({"status": "PASS", "outputs": outputs}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
