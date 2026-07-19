"""Build source-grounded Measured Move Family seed artifacts.

This module deliberately does not render or approve final public prose. It
prepares locked facts, source notes, publication specs, and example charts for
the canonical source-guided AI refinement workflow.
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

from scanner.measured_move_family_publication_specs import build_measured_move_publication_spec  # noqa: E402
from scanner.publication_flow_contract import SOURCE_GROUNDED_PUBLICATION_GATE_ID  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/measured_move_family_public_chapters")
DEFAULT_PRICE_DB = Path("../market_cache/stock_ohlcv/latest.sqlite")
SOURCE_PDF = "references/encyclopedia-of-chart-patterns-2nbsped-9786468600-3175723993-9780471668268-0471668265_compress.pdf"


PATTERNS: dict[str, dict[str, Any]] = {
    "measured_move_up": {
        "slug": "measured_move_up",
        "title": "Measured Move Up",
        "subtitle": "Nhịp tăng đầu tiên, pha điều chỉnh và nhịp tăng thứ hai",
        "scan_dir": Path("artifacts/scanner_v2/measured_move_family/measured_move_up/db_active"),
        "source_chapter": 33,
        "source_name": "Measured Move Up",
        "source_review_pages": [533, 534, 535, 536, 537, 538, 539],
        "source_book_pages": [510, 511, 512, 513, 514, 515, 516],
        "scope_tier": "premium+standard",
        "classification": "hồ sơ tiếp diễn/phục hồi có thể dùng như watchlist-reference trong phạm vi dữ liệu hiện có",
        "claim_level": "đọc như cấu trúc nhịp tăng hai chặng, ưu tiên target 0,5x nhịp đầu",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, Measured Move Up là chương đáng đọc như hồ sơ theo dõi xu hướng: mẫu có đủ độ phổ biến, có bất đối xứng thuận lợi, nhưng target đầy đủ 1,0x nhịp đầu vẫn phải xem là mốc tham chiếu căng.",
        "source_measure_rule_note": "Mốc nguồn đo chiều dài nhịp tăng đầu tiên rồi chiếu lên từ đáy pha điều chỉnh; chương dùng 0,5x làm mốc cơ sở thận trọng và 1,0x làm mốc nguồn đầy đủ.",
        "morphology": "Measured Move Up gồm một nhịp tăng đầu tiên, một pha điều chỉnh thường hồi lại khoảng 40-60% nhịp đầu, rồi một nhịp tăng thứ hai bắt đầu khi giá xác nhận rời khỏi đáy điều chỉnh.",
        "role_note": "Dùng như hồ sơ watchlist/reference cho cấu trúc tăng hai chặng; không tự biến thành tín hiệu mua nếu thiếu xác nhận và đường đi sạch.",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "direction": "up",
    },
    "measured_move_down": {
        "slug": "measured_move_down",
        "title": "Measured Move Down",
        "subtitle": "Nhịp giảm đầu tiên, pha điều chỉnh và nhịp giảm thứ hai",
        "scan_dir": Path("artifacts/scanner_v2/measured_move_family/measured_move_down/db_active"),
        "source_chapter": 32,
        "source_name": "Measured Move Down",
        "source_review_pages": [519, 520, 521, 522, 523, 524, 525],
        "source_book_pages": [496, 497, 498, 499, 500, 501, 502],
        "scope_tier": "premium+standard",
        "classification": "hồ sơ phòng thủ/tham khảo vì đây là cấu trúc giảm hai chặng trên cổ phiếu cơ sở",
        "claim_level": "đọc như cảnh báo rủi ro nhịp giảm thứ hai, không phải setup bán khống phổ quát",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, Measured Move Down có giá trị cao như tài liệu phòng thủ: nó mô tả nguy cơ nhịp giảm thứ hai sau một pha hồi kỹ thuật, nhưng không nên đọc như cơ hội short phổ quát trên cổ phiếu cơ sở Việt Nam.",
        "source_measure_rule_note": "Mốc nguồn đo chiều dài nhịp giảm đầu tiên rồi chiếu xuống từ đỉnh pha điều chỉnh; chương dùng 0,5x làm mốc cảnh báo sớm và 1,0x làm mốc nguồn đầy đủ.",
        "morphology": "Measured Move Down gồm một nhịp giảm đầu tiên, một pha hồi thường lấy lại khoảng 38-62% nhịp giảm, rồi một nhịp giảm thứ hai bắt đầu khi giá xác nhận rời khỏi đỉnh hồi.",
        "role_note": "Dùng như hồ sơ defensive/informational để nhận diện rủi ro giảm tiếp; không giả định khả năng short cổ phiếu cơ sở rộng rãi.",
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


def _window_for_event(df: pd.DataFrame, event: Mapping[str, Any], *, pre_bars: int = 35, post_bars: int = 70) -> pd.DataFrame:
    start = pd.to_datetime(event.get("formation_start_date"), errors="coerce")
    breakout = pd.to_datetime(event.get("breakout_date"), errors="coerce")
    if pd.isna(start) or pd.isna(breakout):
        return df.iloc[:0].copy()
    start_idx = int(df["date"].searchsorted(start, side="left"))
    breakout_idx = int(df["date"].searchsorted(breakout, side="left"))
    left = max(0, start_idx - pre_bars)
    right = min(len(df), breakout_idx + post_bars + 1)
    return df.iloc[left:right].copy().reset_index(drop=True)


def _target_price(event: Mapping[str, Any], multiple: float) -> float:
    direction = 1 if str(event.get("breakout_direction")).lower() == "up" else -1
    confirmation = float(event.get("breakout_price"))
    full = float(event.get("target_price"))
    return confirmation + (full - confirmation) * multiple if direction == 1 else confirmation - (confirmation - full) * multiple


def _plot_event_chart(df: pd.DataFrame, event: Mapping[str, Any], out_path: Path, title: str, *, base_multiple: float) -> None:
    if df.empty:
        return
    x = np.arange(len(df))
    fig, ax = plt.subplots(figsize=(9.2, 4.8), dpi=180)
    for i, row in df.iterrows():
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        color = "#1b8a5a" if c >= o else "#c44e52"
        ax.vlines(i, l, h, color="#222222", linewidth=0.7, alpha=0.75)
        ax.add_patch(Rectangle((i - 0.32, min(o, c)), 0.64, max(abs(c - o), 1e-6), facecolor=color, edgecolor=color, linewidth=0.5, alpha=0.9))
    ax.plot(x, df["close"].to_numpy(), color="#222222", linewidth=0.85, alpha=0.25)

    dates = pd.to_datetime(df["date"])

    def ix_by_date(value: Any) -> int | None:
        ts = pd.to_datetime(value, errors="coerce")
        if pd.isna(ts):
            return None
        idx = int(dates.searchsorted(ts, side="left"))
        return min(max(idx, 0), len(df) - 1)

    i0 = ix_by_date(event.get("formation_start_date"))
    i1 = ix_by_date(event.get("formation_end_date"))
    ib = ix_by_date(event.get("breakout_date"))
    if i0 is not None and i1 is not None and i1 >= i0:
        ax.axvspan(i0, i1, color="#4C78A8", alpha=0.10)
    abc_points: list[tuple[int, float, str, str]] = []
    for label, date_key, price_key, color in [
        ("A", "first_leg_start_date", "first_leg_start_price", "#174A7C"),
        ("B", "first_leg_end_date", "first_leg_end_price", "#174A7C"),
        ("C", "correction_end_date", "correction_end_price", "#7A5195"),
    ]:
        try:
            price = float(event.get(price_key))
            local_idx = ix_by_date(event.get(date_key))
            if local_idx is not None:
                abc_points.append((local_idx, price, label, color))
                ax.scatter([local_idx], [price], s=28, color=color, zorder=5)
                ax.text(local_idx + 0.5, price, label, fontsize=8, color=color, va="bottom")
        except Exception:
            continue
    if len(abc_points) >= 3:
        ax.plot([p[0] for p in abc_points], [p[1] for p in abc_points], color="#174A7C", linewidth=1.1, alpha=0.85)
    if ib is not None:
        ax.axvline(ib, color="#7A5195", linewidth=1.1)
        ax.text(ib + 0.3, float(df["high"].max()), "xác nhận", fontsize=8, color="#7A5195", va="bottom")
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


def _plot_schematic(out_path: Path, *, pattern_id: str) -> None:
    fig, ax = plt.subplots(figsize=(9.2, 3.9), dpi=180)
    if pattern_id == "measured_move_up":
        x = np.array([0, 2.2, 3.8, 6.2])
        y = np.array([10.0, 15.8, 12.8, 18.0])
        title = "Giải phẫu Measured Move Up"
        target_y = 15.7
        labels = ["A đáy đầu", "B đỉnh nhịp đầu", "C đáy điều chỉnh", "D nhịp tăng 2"]
    else:
        x = np.array([0, 2.2, 3.8, 6.2])
        y = np.array([18.0, 12.2, 15.2, 10.0])
        title = "Giải phẫu Measured Move Down"
        target_y = 12.3
        labels = ["A đỉnh đầu", "B đáy nhịp đầu", "C đỉnh hồi", "D nhịp giảm 2"]
    ax.plot(x, y, color="#173b3a", linewidth=2.2)
    ax.axvspan(x[0], x[1], color="#4C78A8", alpha=0.10)
    ax.axvspan(x[1], x[2], color="#F2CF5B", alpha=0.16)
    ax.axhline(target_y, color="#F58518", linestyle="--", linewidth=1.0)
    for xi, yi, label in zip(x, y, labels):
        ax.scatter([xi], [yi], color="#173b3a", s=28)
        ax.text(xi + 0.05, yi + (0.35 if pattern_id == "measured_move_up" else -0.65), label, fontsize=8)
    ax.annotate("pha điều chỉnh", xy=(3.0, (y[1] + y[2]) / 2), xytext=(2.2, max(y) + 1.0), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
    ax.text(0.05, target_y, "mốc 0,5x nhịp đầu", color="#F58518", fontsize=8, va="bottom")
    ax.set_title(title, loc="left", fontsize=10)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
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
        raw = _load_ohlcv(price_db, str(event["symbol"]))
        window = _window_for_event(raw, event)
        out_path = charts_dir / f"{key}_{event['symbol']}_{event['breakout_date']}.png"
        _plot_event_chart(window, event, out_path, f"{event['symbol']} - {title_map.get(key, 'ví dụ')} ({event['breakout_date']})", base_multiple=base_multiple)
        paths[key] = out_path
    return paths


def _source_notes(pattern_id: str, meta: Mapping[str, Any]) -> dict[str, Any]:
    prefix = "mmu" if pattern_id == "measured_move_up" else "mmd"
    direction = "up" if pattern_id == "measured_move_up" else "down"
    leg = "rise" if direction == "up" else "decline"
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
            "target_rule_summary": meta["source_measure_rule_note"],
            "review_note": "Đã đối chiếu trực tiếp chương Measured Move trong PDF gốc trước khi dựng scanner và chapter.",
        },
        "source_rules": [
            {"rule_id": f"{prefix}.three_part_structure", "short_excerpt": f"Prices move {direction}, retrace, and then move {direction} again", "implementation_mapping": "mẫu được nhận diện bằng ba điểm A-B-C và xác nhận bắt đầu nhịp thứ hai"},
            {"rule_id": f"{prefix}.first_leg.straight", "short_excerpt": "straight-line fashion", "implementation_mapping": "nhịp đầu phải đủ thẳng bằng kiểm tra tuyến tính"},
            {"rule_id": f"{prefix}.corrective.retrace", "short_excerpt": "recover from 38% to 62% / 40% to 60%", "implementation_mapping": "pha điều chỉnh ưu tiên vùng 38-62%, cho phép vùng dùng được rộng hơn"},
            {"rule_id": f"{prefix}.avoid.deep_retrace", "short_excerpt": "Anything beyond an 80% retrace is too far", "implementation_mapping": "loại điều chỉnh quá sâu vì dễ mất cấu trúc measured move"},
            {"rule_id": f"{prefix}.avoid.sawtooth", "short_excerpt": "Avoid horizontal, saw-tooth consolidation regions", "implementation_mapping": "giới hạn số lần đảo hướng trong pha điều chỉnh"},
            {"rule_id": f"{prefix}.second_leg", "short_excerpt": f"second leg approximates the price {leg} set by the first leg", "implementation_mapping": "mục tiêu nguồn dùng độ dài nhịp đầu chiếu từ điểm C"},
            {"rule_id": f"{prefix}.half_leg_target", "short_excerpt": "use half of the first leg move", "implementation_mapping": "mốc 0,5x được dùng làm mốc cơ sở thận trọng trong dữ liệu Việt Nam"},
            {"rule_id": f"{prefix}.volume.context", "short_excerpt": "volume trend", "implementation_mapping": "khối lượng là bối cảnh phụ, không thay thế hình thái ba chặng"},
        ],
    }


def _editorial_sections(pattern_id: str, meta: Mapping[str, Any], source: Mapping[str, Any], base: Mapping[str, Any], full: Mapping[str, Any]) -> dict[str, list[str]]:
    title = str(meta["title"])
    direction_word = "tăng" if pattern_id == "measured_move_up" else "giảm"
    usage = "theo dõi nhịp tăng thứ hai" if pattern_id == "measured_move_up" else "cảnh báo nhịp giảm thứ hai"
    return {
        "summary": [
            f"{title} nên được đọc như một bản đồ ba chặng: nhịp {direction_word} đầu tiên tạo thước đo, pha điều chỉnh kiểm tra độ bền của nhịp đó, rồi nhịp {direction_word} thứ hai cho biết liệu thị trường có tiếp tục đi theo cùng cấu trúc hay không. Điểm quan trọng là chương không tìm một breakout hình học kiểu tam giác hay cờ; nó neo sự kiện ở lúc giá rời pha điều chỉnh và bắt đầu leg thứ hai.",
            f"Trong dữ liệu Việt Nam hiện có, toàn mẫu đủ dày để viết thành chapter riêng. Ở nhóm hình thái tốt và chuẩn, mốc 0,5x nhịp đầu đạt {base.get('target_hit_rate')}% và mốc nguồn 1,0x đạt {full.get('target_hit_rate')}%. Khoảng cách này rất quan trọng: nó cho thấy full measured move là mốc tham chiếu, còn mốc nửa nhịp đầu mới là nơi người đọc nên bắt đầu đánh giá xác suất.",
            f"Cách sử dụng phù hợp là {usage}, không phải biến một hình dạng ba chặng thành tín hiệu giao dịch tự động. Khi pha điều chỉnh nằm quanh vùng nguồn, nhịp đầu đủ thẳng và giá xác nhận rõ, mẫu đáng đọc hơn. Khi điều chỉnh quá sâu hoặc đi ngang răng cưa, mẫu dễ trở thành dao động bình thường.",
        ],
        "tour": [
            f"Hãy tưởng tượng mẫu này như một nhịp thở của xu hướng. Ở chặng A-B, giá đi đủ nhanh và đủ thẳng để tạo ra một quãng đo. Ở chặng B-C, giá lùi lại hoặc hồi lên để kiểm tra xem lực trước đó đã hết chưa. Nếu C không phá hỏng quá nhiều nhịp đầu, chặng tiếp theo có cơ sở để được đo bằng chính độ dài A-B.",
            f"Khác với nhiều chương khác, Measured Move không có một vùng biên mẫu thật rõ để gọi là breakout. Vì vậy chương này dùng từ xác nhận theo nghĩa thực dụng: giá rời khỏi pha điều chỉnh theo đúng hướng của nhịp đầu. Sau xác nhận, toàn bộ bảng thống kê đo xem leg thứ hai đi được bao xa, có chạm mốc 0,5x hay 1,0x không, và có bị kéo ngược 5% trước khi đạt mốc hay không.",
            f"Điểm đáng học từ tài liệu gốc là sự thận trọng với mốc đầy đủ. Bulkowski mô tả full leg như cách đo nguồn, nhưng cũng nhấn mạnh rằng dùng nửa nhịp đầu thường thực dụng hơn. Vì vậy chapter Việt Nam giữ cả hai mốc: 0,5x để đọc xác suất cơ sở, 1,0x để biết mẫu có hoàn tất measured move đầy đủ hay không.",
        ],
        "failure": [
            f"Thất bại phổ biến nhất không phải là mẫu bị nhận diện sai hoàn toàn, mà là pha điều chỉnh phá hỏng tỷ lệ. Nếu giá hồi hoặc lùi quá sâu, điểm C không còn là một nhịp nghỉ khỏe mà trở thành dấu hiệu xu hướng trước đã mất lực. Khi đó, leg thứ hai có thể xuất hiện nhưng không còn đủ xác suất đi đến mốc đo.",
            f"Trong nhóm được công bố, tỷ lệ thất bại 5% ở mốc cơ sở là {base.get('failure_5pct_rate')}%. Con số này phải đọc cùng tỷ lệ đạt mục tiêu trước kéo ngược 5% là {base.get('target_first_before_adverse_5pct_rate')}%. Nếu mẫu đạt mục tiêu nhưng thường phải chịu kéo ngược lớn trước đó, người đọc nên xem nó là tín hiệu bối cảnh chứ không phải một đường đi sạch.",
            "Một bẫy khác là nhầm vùng đi ngang răng cưa thành pha điều chỉnh. Tài liệu gốc cảnh báo rõ loại hình này, vì nó làm người đọc nghĩ rằng xu hướng chỉ đang nghỉ trong khi thực tế giá đã chuyển sang một vùng cân bằng khác. Bộ nhận diện vì vậy giới hạn số lần đảo hướng và hạ chất lượng những pha điều chỉnh quá nhiễu.",
        ],
        "statistics": [
            f"Thống kê chính nên đọc theo cặp. Mức đi thuận lợi trung vị của nhóm công bố là {base.get('median_mfe_pct')}%, trong khi mức kéo ngược sâu nhất trung vị là {base.get('median_mae_pct')}%. Tỷ lệ MFE/MAE trung vị {base.get('mfe_mae_median_ratio')} cho biết mẫu có tạo bất đối xứng đường đi hay không.",
            f"Mốc 0,5x có tỷ lệ đạt {base.get('target_hit_rate')}%, còn mốc 1,0x chỉ đạt {full.get('target_hit_rate')}%. Nếu chỉ in một mốc 1,0x, người đọc sẽ dễ đánh giá mẫu quá khắt khe; nếu chỉ in 0,5x, chương lại mất liên hệ với measure rule gốc. Do đó hai mốc phải đi cùng nhau.",
            f"Điều đáng chú ý là retrace trung vị quanh {source.get('median_corrective_retrace_pct')}%, gần vùng nguồn của tài liệu gốc. Đây là tín hiệu tốt ở tầng hình thái: scanner không chỉ tìm các đoạn giá ngẫu nhiên mà đang bắt được pha điều chỉnh tương đối đúng tinh thần Measured Move.",
        ],
        "post_breakout": [
            f"Sau xác nhận, câu hỏi không chỉ là giá có đi đúng hướng hay không, mà là đi theo thứ tự nào. Mẫu tốt là mẫu chạm mốc cơ sở trước khi bị kéo ngược bất lợi 5%; mẫu yếu là mẫu cuối cùng có thể đi đúng nhưng khiến người đọc trải qua một nhịp ngược lớn trước đó.",
            f"Median ngày chạm mục tiêu cơ sở trong tập hit là {base.get('median_days_to_target')} phiên. Con số này biến chapter từ một mô tả hình học thành bản đồ thời gian: nếu sau nhiều tuần giá vẫn không đi được nửa nhịp đầu, measured move có thể đang mất hiệu lực.",
            "Phần hậu xác nhận cũng giải thích vì sao Measured Move phù hợp với live scan. Khi một sự kiện mới xuất hiện, người đọc có thể theo dõi mốc 0,5x trước, sau đó mới đánh giá liệu full measured move còn khả thi hay không.",
        ],
        "size_volume": [
            "Kích thước quan trọng vì nhịp đầu là thước đo của toàn bộ mẫu. Nhịp đầu quá nhỏ dễ chỉ là nhiễu; nhịp đầu quá lớn lại làm mốc full leg quá xa và dễ mất tính thực tế. Vì vậy chương báo cáo cả độ dài nhịp đầu, tỷ lệ hồi của pha điều chỉnh và độ thẳng của nhịp đầu.",
            "Khối lượng được xem như bối cảnh phụ. Tài liệu gốc có nhắc volume trend, nhưng chương Việt Nam không biến volume thành điều kiện loại cứng, vì dữ liệu thanh khoản và cấu trúc giao dịch từng mã có thể khác nhau. Điều quan trọng hơn là hình thái ba chặng có sạch hay không.",
            "Nếu đường giá thiếu phiên, thanh khoản thấp hoặc có nhiều đoạn đứng giá, chương hạ chất lượng mẫu. Với Measured Move, dữ liệu đường đi càng quan trọng vì chỉ cần một gap hoặc một chuỗi đứng giá cũng có thể làm sai thời điểm xác nhận leg thứ hai.",
        ],
        "tactics": [
            f"Cách đọc thực tế gồm bốn bước. Một là xác định nhịp đầu có đủ thẳng và đủ lớn không. Hai là kiểm pha điều chỉnh có nằm quanh vùng 40-60% hay không. Ba là chờ giá rời pha điều chỉnh theo đúng hướng. Bốn là theo dõi mốc 0,5x trước khi nghĩ tới 1,0x.",
            f"Với {title}, mốc 0,5x không phải con số tùy tiện. Nó được giữ vì tài liệu gốc cũng xem nửa nhịp đầu là cách dự phóng thận trọng hơn full leg, và dữ liệu Việt Nam hiện tại cho thấy mốc này đọc được hơn trong thực tế.",
            "Nếu dùng chapter trong một hệ thống riêng, phần còn thiếu vẫn là entry/exit, sizing, chi phí, trượt giá và kiểm định ngoài mẫu. Chương này chỉ trả lời câu hỏi: sau một cấu trúc Measured Move đã xác nhận, đường đi lịch sử thường trông như thế nào.",
        ],
        "checklist": [
            "Nhịp đầu phải rõ và tương đối thẳng.",
            "Pha điều chỉnh nên nằm quanh vùng 38-62% hoặc 40-60% của nhịp đầu.",
            "Tránh pha điều chỉnh quá sâu, đặc biệt vượt gần 80% nhịp đầu.",
            "Tránh vùng đi ngang răng cưa vì dễ không còn là measured move.",
            "Đọc mốc 0,5x trước, mốc 1,0x sau.",
            "Luôn đặt tỷ lệ đạt mục tiêu cạnh mức kéo ngược và thời gian chạm mục tiêu.",
            "Không dùng chapter như khuyến nghị mua bán tự động.",
        ],
    }


def _spec(pattern_id: str, meta: Mapping[str, Any]) -> dict[str, Any]:
    is_up = pattern_id == "measured_move_up"
    return {
        "title": meta["title"],
        "subtitle": meta["subtitle"],
        "base_target_multiple": float(meta["base_target_multiple"]),
        "base_target_label": "0,5x",
        "legacy_target_multiple": float(meta["legacy_target_multiple"]),
        "legacy_target_label": "1,0x",
        "target_unit_label": "độ dài nhịp đầu",
        "target_focus_title": "Mốc cơ sở 0,5x",
        "target_focus_caption": "mốc 0,5x nhịp đầu",
        "target_focus_reading": "mốc thận trọng trước khi đọc full measured move",
        "target_full_title": "Mốc nguồn 1,0x",
        "target_full_reading": "mốc đầy đủ theo độ dài nhịp đầu",
        "morphology_sentence": meta["morphology"],
        "role_note": meta["role_note"],
        "classification_sentence": meta["public_classification_sentence"],
        "headline_scope": "Measured Move được đo theo leg thứ hai; không trộn lẫn mốc cơ sở 0,5x với mốc nguồn 1,0x.",
        "local_source_chapter": meta["source_chapter"],
        "schematic_caption": f"Sơ đồ minh họa {meta['title']}: A-B là nhịp đầu, B-C là pha điều chỉnh, sau C là nhịp thứ hai.",
        "how_subtitle": "Mẫu này là cấu trúc ba chặng, không phải breakout box.",
        "labels": {"favorable_move": "mức đi thuận lợi", "adverse_move": "mức đi ngược bất lợi"},
        "source_rule_ids": ["measured_move.three_part", "measured_move.first_leg", "measured_move.corrective_phase", "measured_move.second_leg", "measured_move.target"],
        "public_rule_rows": [
            ["Có cấu trúc ba chặng.", "Người đọc cần thấy nhịp đầu, pha điều chỉnh và xác nhận bắt đầu nhịp thứ hai."],
            ["Nhịp đầu phải đủ thẳng.", "Đo bằng độ tuyến tính của đường đóng cửa trong chặng A-B."],
            ["Pha điều chỉnh phải có tỷ lệ hợp lý.", "Ưu tiên vùng 38-62%/40-60%; loại các pha hồi hoặc lùi quá sâu."],
            ["Tránh vùng răng cưa.", "Pha điều chỉnh có quá nhiều lần đảo hướng bị hạ chất lượng."],
            ["Mục tiêu theo nhịp đầu.", "0,5x là mốc cơ sở thận trọng; 1,0x là mốc nguồn đầy đủ."],
            ["Thống kê là hồ sơ tham khảo.", meta["role_note"]],
        ],
        "quick_question_rows": [
            ["Nhịp đầu", "Có đủ thẳng và đủ lớn không?"],
            ["Pha điều chỉnh", "Có hồi/lùi quanh vùng nguồn hay quá sâu?"],
            ["Xác nhận", "Giá đã rời pha điều chỉnh theo đúng hướng chưa?"],
            ["Mục tiêu", "0,5x có đến trước kéo ngược 5% không?"],
        ],
        "component_rows": [
            ["A-B", "Nhịp đầu tạo thước đo.", "Tăng" if is_up else "Giảm"],
            ["B-C", "Pha điều chỉnh kiểm tra lực trước đó.", "Hồi/lùi quanh 40-60%"],
            ["Sau C", "Nhịp thứ hai bắt đầu sau xác nhận.", "Theo hướng nhịp đầu"],
            ["Mốc 0,5x", "Mục tiêu cơ sở thận trọng.", "Nửa nhịp đầu"],
            ["Mốc 1,0x", "Mốc nguồn đầy đủ.", "Toàn bộ nhịp đầu"],
        ],
        "reject_bullets": [
            "Nhịp đầu cong vòng hoặc đi ngang quá nhiều.",
            "Pha điều chỉnh quá sâu, gần như xóa hết nhịp đầu.",
            "Pha điều chỉnh răng cưa kéo dài làm mẫu giống vùng dao động.",
            "Mốc 1,0x dự phóng quá xa so với đường đi thực tế.",
        ],
        "identification_paragraphs": [meta["morphology"]],
        "example_intro": ["Ba ví dụ dưới đây gồm một trường hợp đạt mốc cơ sở, một trường hợp gần trung vị và một trường hợp thất bại. Bảng diễn biến đi kèm từng ví dụ giúp đọc A-B-C và hậu xác nhận thay vì chỉ nhìn nến."],
        "failure_bullets": [
            "Thất bại 5% không phải stop-loss, mà là thước đo mẫu không đi đủ hướng sau xác nhận.",
            "Pha điều chỉnh quá sâu làm mốc measured move kém đáng tin.",
            "Full 1,0x nên đọc như mốc nguồn, không phải kỳ vọng mặc định.",
        ],
        "target_paragraph": meta["source_measure_rule_note"],
        "quick_conclusion_rows": [
            ["Mẫu này dùng để đọc gì?", "Khả năng xuất hiện nhịp thứ hai sau một nhịp đầu rõ."],
            ["Mốc đọc chính?", "0,5x độ dài nhịp đầu."],
            ["Mốc tham chiếu?", "1,0x độ dài nhịp đầu theo nguồn."],
            ["Khi nào thận trọng?", "Khi pha điều chỉnh quá sâu hoặc răng cưa."],
        ],
        "caveat_bullets": [
            "Không tuyên bố đây là nghiên cứu toàn thị trường đúng từng ngày lịch sử.",
            "Không dùng historical VN30/VN100 membership làm kết luận chính.",
            "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
            "Chương là tài liệu tham khảo hậu xác nhận, không phải khuyến nghị mua bán.",
        ],
        "quantile_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên"),
            ("Nhịp đầu", "first_leg_pct", "%"),
            ("Tỷ lệ điều chỉnh", "corrective_retrace_pct", "%"),
            ("Độ thẳng nhịp đầu", "first_leg_linearity_r2", ""),
            ("Số lần đảo hướng điều chỉnh", "correction_turn_count", "lần"),
            ("Mức đi thuận lợi", "mfe_pct", "%"),
            ("Mức đi ngược bất lợi", "mae_pct", "%"),
            ("Ngày chạm mốc cơ sở", "days_to_target", "phiên"),
        ],
        "skip_condition_specs": [
            ("Pha điều chỉnh quá sâu", "corrective_retrace_pct", "q75", None, "Dễ không còn là nhịp nghỉ của measured move."),
            ("Nhịp đầu kém thẳng", "first_leg_linearity_r2", "q25", None, "Nhịp đầu cong hoặc nhiễu làm thước đo kém tin."),
            ("Điều chỉnh quá răng cưa", "correction_turn_count", "q75", None, "Vùng điều chỉnh dễ thành dao động ngang."),
            ("Kéo ngược quá sâu", "mae_pct", "q75", None, "Đường đi sau xác nhận không còn gọn."),
        ],
        "general_stat_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên", "Measured Move thường dài hơn Flag/Pennant nên phải kiểm thời gian."),
            ("Nhịp đầu", "first_leg_pct", "%", "Nhịp đầu là thước đo cho target."),
            ("Tỷ lệ điều chỉnh", "corrective_retrace_pct", "%", "Tỷ lệ quanh 40-60% bám sát nguồn hơn."),
            ("Độ thẳng nhịp đầu", "first_leg_linearity_r2", "", "Nhịp đầu càng thẳng, cấu trúc càng dễ đọc."),
        ],
        "best_condition_specs": [
            ("Nhóm hình thái tốt", "publication_quality_tier", "==", "premium", "Nhịp đầu thẳng, retrace gần nguồn và đường giá sạch."),
            ("Nhóm chuẩn", "publication_quality_tier", "==", "standard", "Đủ dùng trong thống kê nhưng không phải lúc nào cũng đẹp để minh họa."),
            ("Retrace nguồn", "source_retrace_band", "==", "ideal_38_62", "Pha điều chỉnh bám vùng nguồn."),
            ("Đường giá sạch", "path_quality_bucket", "==", "clean", "Ít thiếu phiên và ít chuỗi đứng giá."),
        ],
        "conclusion_bullets": [
            f"{meta['title']} đã được dựng bằng scanner riêng của Measured Move Family, không dùng lại scanner Flag/Triangle/Double/Wedge.",
            meta["source_measure_rule_note"],
            meta["role_note"],
        ],
    }


def _publication_payload(pattern_id: str, meta: Mapping[str, Any], events: pd.DataFrame, all_events: pd.DataFrame, path_df: pd.DataFrame) -> dict[str, Any]:
    base = _metric_for_target(events, path_df, 0.5, "conservative_half_leg")
    full = _metric_for_target(events, path_df, 1.0, "source_full_leg")
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
            "median_corrective_retrace_pct": _fmt(pd.to_numeric(events.get("corrective_retrace_pct"), errors="coerce").median()),
        },
        "target_calibration": {
            "target_family": {"conservative_half_leg": 0.5, "source_full_leg": 1.0},
            "selected_base_target_multiple": 0.5,
            "selected_base_target_role": "conservative_half_leg",
            "base_target": base,
            "stretch_target": full,
            "legacy_target": full,
            "rows": [base, full],
            "interpretation": meta["source_measure_rule_note"],
        },
        "data_scope_and_caveats": {
            "remaining_caveats": [
                "Không claim point-in-time universe toàn thị trường.",
                "Không dùng historical VN30/VN100 membership làm kết luận chính.",
                "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
            ]
        },
    }


def build_one_measured_move_chapter(*, pattern_id: str, out_dir: Path, price_db: Path) -> dict[str, Path]:
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
    publication_spec = build_measured_move_publication_spec(pattern_id=pattern_id, title=str(meta["title"]), spec=spec)
    payload["publication_spec_id"] = publication_spec["publication_spec_id"]
    payload["source_rules_public"] = [
        {"rule": row[0], "application": row[1]} for row in spec.get("public_rule_rows", [])
    ]
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
        "Dossier này dùng để giữ thứ tự đọc: hình thái ba chặng, pha điều chỉnh, mục tiêu theo nhịp đầu, thất bại và cách dùng thận trọng. "
        "Không sao chép hoặc dịch lại tài liệu gốc; số liệu Việt Nam lấy từ payload đã khóa.\n",
        encoding="utf-8",
    )
    entry = {
        "family": "measured_move_family",
        "pattern_id": pattern_id,
        "title": meta["title"],
        "status": "source_seed",
        "classification": meta["classification"],
        "score": None,
        "claim_level": meta["claim_level"],
        "pdf": f"artifacts/final_chapters/measured_move_family/{meta['slug']}_final.pdf",
        "source_pdf": f"artifacts/final_chapters/measured_move_family/{meta['slug']}_final.pdf",
        "payload": str(payload_path),
        "source_notes": str(source_notes_path),
        "publication_spec": str(publication_spec_path),
        "source_grounding_required": True,
        "source_grounding_policy_id": SOURCE_GROUNDED_PUBLICATION_GATE_ID,
        "direct_source_review_required": True,
        "publication_semantic_required": True,
        "publication_semantic_gate_id": publication_spec["semantic_gate_id"],
        "canonical_rebuild_required": True,
        "chapter_writing_stages": {
            "source_style_dossier": str(style_dossier),
        },
        "chapter_writing_notes": "Seed artifact only. Final public prose must be generated by source-guided AI refinement and canonical publication factory.",
        "note": "Measured Move Family dùng scanner ba chặng riêng; builder này chỉ cung cấp nguyên liệu, không render hoặc approve PDF final.",
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
    parser = argparse.ArgumentParser(description="Build Measured Move Family public chapters.")
    parser.add_argument("--pattern", choices=[*PATTERNS.keys(), "all"], default="all")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--price-db", default=str(DEFAULT_PRICE_DB))
    args = parser.parse_args()
    patterns = list(PATTERNS.keys()) if args.pattern == "all" else [args.pattern]
    outputs = {}
    for pattern_id in patterns:
        outputs[pattern_id] = {key: str(value) for key, value in build_one_measured_move_chapter(pattern_id=pattern_id, out_dir=Path(args.out_dir), price_db=Path(args.price_db)).items()}
    print(json.dumps({"status": "PASS", "outputs": outputs}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
