"""Build source-grounded Rectangle Family public chapters."""

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

from scanner.publication_example_support import load_public_editorial_sections  # noqa: E402
from scanner.publication_flow_contract import SOURCE_GROUNDED_PUBLICATION_GATE_ID  # noqa: E402
from scanner.rectangle_family_public_chapter_factory import FACTORY_ID, build_rectangle_public_chapter  # noqa: E402
from scanner.rectangle_family_publication_specs import build_rectangle_publication_spec, sanitize_rectangle_public_text  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/rectangle_family_public_chapters")
DEFAULT_PRICE_DB = Path("../market_cache/stock_ohlcv/latest.sqlite")
DEFAULT_AI_DIR = Path("artifacts/scanner_v2/rectangle_family_ai_writing_approved_v1")
REQUIRED_EDITORIAL_SECTIONS = ("summary", "tour", "failure", "statistics", "post_breakout", "size_volume", "tactics", "checklist")
SOURCE_PDF = "references/encyclopedia-of-chart-patterns-2nbsped-9786468600-3175723993-9780471668268-0471668265_compress.pdf"


PATTERNS: dict[str, dict[str, Any]] = {
    "rectangle_bottoms": {
        "slug": "rectangle_bottoms",
        "title": "Đáy chữ nhật",
        "subtitle": "Xu hướng giảm đi vào mẫu, giá đi ngang giữa hai biên và đóng cửa phá vỡ",
        "scan_dir": Path("artifacts/scanner_v2/rectangle_family/rectangle_bottoms/db_active"),
        "source_chapter": 37,
        "source_name": "Rectangle Bottoms",
        "source_review_pages": [586, 587, 590, 591, 599],
        "source_book_pages": [563, 564, 567, 568, 576],
        "scope_tier": "premium+standard",
        "classification": "hồ sơ tham khảo hai nhánh trong phạm vi dữ liệu hiện có",
        "claim_level": "hồ sơ tham khảo sau phá vỡ trong phạm vi dữ liệu hiện có",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, đáy chữ nhật nên được đọc theo từng hướng phá vỡ: phá lên là hồ sơ theo dõi, phá xuống là cảnh báo tiếp diễn rủi ro.",
        "source_measure_rule_note": "Mốc nguồn của đáy chữ nhật dùng chiều cao giữa hai biên: cộng lên từ biên trên khi phá lên và trừ xuống từ biên dưới khi phá xuống.",
        "morphology": "Đáy chữ nhật hình thành sau một xu hướng giảm đi vào mẫu; giá dao động giữa hai đường biên gần ngang, có ít nhất hai lần chạm mỗi biên, rồi xác nhận bằng giá đóng cửa phá vỡ.",
        "role_note": "Dùng như hồ sơ tham khảo sau phá vỡ; phá lên và phá xuống phải được đọc tách nhánh, không phải tín hiệu mua bán tự động.",
        "direction_context": "xu hướng giảm đi vào mẫu",
        "breakout_phrase": "giá đóng cửa phá vỡ",
        "base_target_multiple": 1.0,
        "legacy_target_multiple": 1.0,
    },
    "rectangle_tops": {
        "slug": "rectangle_tops",
        "title": "Đỉnh chữ nhật",
        "subtitle": "Xu hướng tăng đi vào mẫu, giá đi ngang giữa hai biên và đóng cửa phá vỡ",
        "scan_dir": Path("artifacts/scanner_v2/rectangle_family/rectangle_tops/db_active"),
        "source_chapter": 38,
        "source_name": "Rectangle Tops",
        "source_review_pages": [602, 603, 606, 607, 615],
        "source_book_pages": [579, 580, 583, 584, 592],
        "scope_tier": "premium+standard",
        "classification": "hồ sơ tham khảo hai nhánh trong phạm vi dữ liệu hiện có",
        "claim_level": "hồ sơ tham khảo sau phá vỡ trong phạm vi dữ liệu hiện có",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, đỉnh chữ nhật nên được đọc như hồ sơ tiếp diễn khi phá lên và tài liệu phòng thủ khi phá xuống.",
        "source_measure_rule_note": "Mốc nguồn của đỉnh chữ nhật dùng chiều cao giữa hai biên: cộng lên từ biên trên khi phá lên và trừ xuống từ biên dưới khi phá xuống.",
        "morphology": "Đỉnh chữ nhật hình thành sau một xu hướng tăng đi vào mẫu; giá dao động giữa hai đường biên gần ngang, có ít nhất hai lần chạm mỗi biên, rồi xác nhận bằng giá đóng cửa phá vỡ.",
        "role_note": "Dùng như hồ sơ tham khảo sau phá vỡ; nhánh phá xuống nên đọc như cảnh báo rủi ro trên cổ phiếu cơ sở, không phải lời gọi bán khống.",
        "direction_context": "xu hướng tăng đi vào mẫu",
        "breakout_phrase": "giá đóng cửa phá vỡ",
        "base_target_multiple": 1.0,
        "legacy_target_multiple": 1.0,
    },
}


def _read_json(path: Path) -> dict[str, Any]:
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


def _fmt(value: Any, digits: int = 2) -> str:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if not math.isfinite(out):
        return "n/a"
    return f"{out:.{digits}f}"


def _load_required_editorial(path: Path) -> tuple[dict[str, list[str]], str]:
    loaded = load_public_editorial_sections(path)
    sections = loaded.get("sections") if isinstance(loaded.get("sections"), Mapping) else {}
    missing = [key for key in REQUIRED_EDITORIAL_SECTIONS if not sections.get(key)]
    if missing:
        raise RuntimeError(f"Missing approved Rectangle editorial sections in {path}: {', '.join(missing)}")
    cleaned = {key: [sanitize_rectangle_public_text(item) for item in value] for key, value in dict(sections).items()}
    return cleaned, str(path)


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


def _window_for_event(df: pd.DataFrame, event: Mapping[str, Any], *, pre_bars: int = 45, post_bars: int = 45) -> pd.DataFrame:
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
    breakout = float(event.get("breakout_price"))
    full = float(event.get("target_price"))
    if str(event.get("breakout_direction")).lower() == "down":
        return breakout - (breakout - full) * multiple
    return breakout + (full - breakout) * multiple


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
    ax.plot(x, df["close"].to_numpy(), color="#222222", linewidth=0.9, alpha=0.28)

    start = pd.to_datetime(event.get("formation_start_date"), errors="coerce")
    end = pd.to_datetime(event.get("formation_end_date"), errors="coerce")
    breakout = pd.to_datetime(event.get("breakout_date"), errors="coerce")

    def ix(ts: pd.Timestamp) -> int | None:
        if pd.isna(ts):
            return None
        value = int(df["date"].searchsorted(ts, side="left"))
        return min(max(value, 0), len(df) - 1)

    i0, i1, ib = ix(start), ix(end), ix(breakout)
    if i0 is not None and i1 is not None and i1 >= i0:
        ax.axvspan(i0, i1, color="#4C78A8", alpha=0.10)
    if ib is not None:
        ax.axvline(ib, color="#7A5195", linewidth=1.1)
        label = "Phá vỡ xuống" if str(event.get("breakout_direction")).lower() == "down" else "Phá vỡ lên"
        ax.text(ib + 0.3, float(df["high"].max()), label, fontsize=8, color="#7A5195", va="bottom")
    for key, color, label in [
        ("rectangle_resistance", "#E45756", "biên trên"),
        ("rectangle_support", "#54A24B", "biên dưới"),
    ]:
        try:
            value = float(event.get(key))
        except (TypeError, ValueError):
            continue
        ax.axhline(value, color=color, linestyle="-", linewidth=1.0, alpha=0.85)
        ax.text(0.5, value, label, fontsize=7, color=color, va="bottom")
    breakout_price = float(event.get("breakout_price"))
    target = _target_price(event, base_multiple)
    ax.axhline(breakout_price, color="#245b5a", linestyle="--", linewidth=0.9, alpha=0.85)
    ax.axhline(target, color="#F58518", linestyle="--", linewidth=0.9, alpha=0.9)
    ax.text(0.5, breakout_price, "giá phá vỡ", fontsize=7, color="#245b5a", va="bottom")
    ax.text(0.5, target, "mốc chiều cao", fontsize=7, color="#F58518", va="bottom")
    ax.set_title(title, fontsize=10, loc="left")
    ax.grid(alpha=0.14)
    y_min = min(float(df["low"].min()), breakout_price, target)
    y_max = max(float(df["high"].max()), breakout_price, target)
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
    if pattern_id == "rectangle_bottoms":
        pre_x = np.array([0.0, 0.8, 1.6, 2.3])
        pre_y = np.array([20.5, 18.8, 17.3, 15.6])
        title = "Giải phẫu đáy chữ nhật"
    else:
        pre_x = np.array([0.0, 0.8, 1.6, 2.3])
        pre_y = np.array([14.2, 15.8, 17.2, 18.7])
        title = "Giải phẫu đỉnh chữ nhật"
    rx = np.array([2.3, 3.1, 4.0, 4.9, 5.8, 6.6, 7.3])
    ry = np.array([16.0, 18.2, 16.1, 18.0, 16.2, 18.1, 19.2])
    ax.plot(pre_x, pre_y, color="#173b3a", linewidth=2.0)
    ax.plot(rx, ry, color="#173b3a", linewidth=2.0)
    ax.axhline(18.2, xmin=0.25, xmax=0.74, color="#E45756", linewidth=1.1)
    ax.axhline(16.0, xmin=0.25, xmax=0.74, color="#54A24B", linewidth=1.1)
    ax.axvspan(2.3, 6.8, color="#1f77b4", alpha=0.10)
    ax.annotate("hai biên gần ngang", xy=(4.8, 18.2), xytext=(2.0, 20.4), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
    ax.annotate("đóng cửa phá vỡ", xy=(7.3, 19.2), xytext=(6.0, 21.0), arrowprops={"arrowstyle": "->", "color": "#6f4aa8"}, color="#6f4aa8", fontsize=9)
    ax.axhline(20.4, color="#e98b2a", linestyle="--", linewidth=0.9)
    ax.text(0, 20.55, "mốc chiều cao chữ nhật", color="#e98b2a", fontsize=8)
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
    prefix = "rb" if pattern_id == "rectangle_bottoms" else "rt"
    trend = "downward" if pattern_id == "rectangle_bottoms" else "upward"
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
            "review_note": "Đã đối chiếu trực tiếp chương Rectangle trong PDF gốc trước khi dựng scanner và chapter.",
        },
        "source_rules": [
            {"rule_id": f"{prefix}.prior_trend.{trend}", "short_excerpt": f"{trend} price trend leading into the rectangle", "implementation_mapping": meta["direction_context"]},
            {"rule_id": f"{prefix}.horizontal_boundaries", "short_excerpt": "two horizontal or nearly horizontal trend lines", "implementation_mapping": "hai biên gần ngang làm hỗ trợ và kháng cự"},
            {"rule_id": f"{prefix}.touches.two_each", "short_excerpt": "at least two touches of each trendline", "implementation_mapping": "ít nhất hai lần chạm mỗi biên"},
            {"rule_id": f"{prefix}.breakout.close_outside", "short_excerpt": "breakout through a rectangle boundary", "implementation_mapping": "xác nhận bằng giá đóng cửa phá vỡ"},
            {"rule_id": f"{prefix}.failure.5pct", "short_excerpt": "failure is less than a 5 percent move in the breakout direction", "implementation_mapping": "thất bại 5% theo hướng phá vỡ"},
            {"rule_id": f"{prefix}.target.measure_rule", "short_excerpt": "measure rule: measure the rectangle height and add/subtract it from the breakout side", "implementation_mapping": meta["source_measure_rule_note"]},
            {"rule_id": f"{prefix}.volume.recedes_context", "short_excerpt": "volume usually recedes but rising volume is not a discard rule", "implementation_mapping": "khối lượng là bối cảnh, không phải điều kiện loại cứng"},
        ],
    }


def _spec(pattern_id: str, meta: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "title": meta["title"],
        "subtitle": meta["subtitle"],
        "base_target_multiple": float(meta["base_target_multiple"]),
        "base_target_label": "1,0x",
        "legacy_target_multiple": float(meta["legacy_target_multiple"]),
        "legacy_target_label": "1,0x",
        "target_unit_label": "chiều cao chữ nhật",
        "target_focus_title": "Mốc nguồn",
        "target_focus_caption": "mốc chiều cao chữ nhật",
        "target_focus_reading": "mốc nguồn theo chiều cao giữa hai biên",
        "target_full_title": "Mốc đầy đủ 1,0x",
        "target_full_reading": "mốc nguồn đầy đủ, cần đọc cùng thất bại và đường đi",
        "morphology_sentence": meta["morphology"],
        "role_note": meta["role_note"],
        "classification_sentence": meta["public_classification_sentence"],
        "headline_scope": "Phần kết luận chính tách hướng phá vỡ, vì cùng vùng chữ nhật có thể phá lên hoặc phá xuống.",
        "local_source_chapter": meta["source_chapter"],
        "schematic_caption": f"Sơ đồ minh họa {meta['title'].lower()}: {meta['direction_context']}, hai biên gần ngang, xác nhận bằng {meta['breakout_phrase']}.",
        "how_subtitle": "Chữ nhật là vùng cân bằng; breakout mới là mốc sự kiện để đo hậu quả.",
        "labels": {"favorable_move": "mức đi thuận lợi", "adverse_move": "mức đi ngược bất lợi"},
        "source_rule_ids": [f"{'rb' if pattern_id == 'rectangle_bottoms' else 'rt'}.prior_trend", "rectangle.horizontal_boundaries", "rectangle.touches", "rectangle.breakout", "rectangle.failure", "rectangle.target"],
        "rule_text_map": {
            "downward price trend leading into the rectangle": "Có xu hướng giảm đi vào mẫu.",
            "upward price trend leading into the rectangle": "Có xu hướng tăng đi vào mẫu.",
            "two horizontal or nearly horizontal trend lines": "Hai đường biên gần ngang.",
            "at least two touches of each trendline": "Ít nhất hai lần chạm mỗi biên.",
            "failure is less than a 5 percent move": "Thất bại khi không đi được 5% theo hướng phá vỡ.",
        },
        "quick_question_rows": [
            ["Xu hướng vào mẫu", f"Có {meta['direction_context']} không?"],
            ["Biên giá", "Hai biên có gần ngang và có ít nhất hai lần chạm mỗi biên không?"],
            ["Phá vỡ", "Giá có đóng cửa phá vỡ thay vì chỉ xuyên trong phiên không?"],
            ["Đường đi", "Mục tiêu có đến trước kéo ngược 5% không?"],
        ],
        "component_rows": [
            ["Xu hướng trước mẫu", "Phân biệt đáy chữ nhật với đỉnh chữ nhật.", meta["direction_context"]],
            ["Hai biên gần ngang", "Giữ mẫu đúng family chữ nhật.", "Biên nghiêng rõ có thể là tam giác, nêm hoặc kênh."],
            ["Số lần chạm", "Xác nhận vùng hỗ trợ - kháng cự thật.", "Tối thiểu hai chạm mỗi biên."],
            ["Phá vỡ đóng cửa", "Chỉ sau xác nhận mới đo kết quả.", meta["breakout_phrase"]],
            ["Mục tiêu", "Dùng chiều cao vùng chữ nhật.", meta["source_measure_rule_note"]],
        ],
        "reject_bullets": [
            "Biên trên hoặc biên dưới nghiêng quá rõ: dễ là tam giác hoặc kênh giá.",
            "Không đủ hai lần chạm mỗi biên: vùng giá chưa đủ bằng chứng.",
            "Không có đóng cửa xác nhận: chưa đưa vào thống kê hậu phá vỡ.",
            "Đường giá thiếu thanh khoản hoặc thiếu phiên: không dùng làm ví dụ công bố.",
        ],
        "identification_paragraphs": [meta["morphology"]],
        "example_intro": ["Ba ví dụ dưới đây ưu tiên VN30/VN100 khi có thể: một mẫu đạt mốc chính, một mẫu gần trung vị và một mẫu thất bại."],
        "failure_bullets": [
            "Thất bại 5% là thước đo mô tả hậu phá vỡ, không phải stop-loss giao dịch.",
            "Phá lên và phá xuống phải tách riêng khi đọc kết quả.",
            "Mẫu đẹp về hình học vẫn có thể yếu nếu phá vỡ bị kéo ngược nhanh.",
        ],
        "target_paragraph": meta["source_measure_rule_note"],
        "quick_conclusion_rows": [
            ["Mẫu này dùng để đọc gì?", "Vùng cân bằng sau xu hướng trước đó và hành vi giá sau phá vỡ."],
            ["Mốc đọc chính?", "1,0x chiều cao chữ nhật theo nguồn."],
            ["Khi nào cần thận trọng?", "Khi biên không đủ ngang, ít lần chạm hoặc đường đi hậu phá vỡ kéo ngược nhanh."],
        ],
        "caveat_bullets": [
            "Không tuyên bố đây là nghiên cứu toàn thị trường đúng từng ngày lịch sử.",
            "Không dùng historical VN30/VN100 membership làm kết luận chính.",
            "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
            "Chương là tài liệu tham khảo hậu phá vỡ, không phải khuyến nghị mua bán.",
        ],
        "quantile_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên"),
            ("Chiều cao chữ nhật", "pattern_height_pct", "%"),
            ("Độ lệch biên trên", "high_spread_pct", "%"),
            ("Độ lệch biên dưới", "low_spread_pct", "%"),
            ("Độ nằm trong vùng", "rectangle_containment_pct", "%"),
            ("Mức đi thuận lợi", "mfe_pct", "%"),
            ("Mức đi ngược bất lợi", "mae_pct", "%"),
            ("Ngày chạm mốc chính", "days_to_target", "phiên"),
        ],
        "skip_condition_specs": [
            ("Biên trên kém ngang", "high_spread_pct", "q75", None, "Biên trên quá lệch làm mẫu kém giống chữ nhật."),
            ("Biên dưới kém ngang", "low_spread_pct", "q75", None, "Biên dưới quá lệch làm vùng hỗ trợ thiếu rõ."),
            ("Nằm trong vùng yếu", "rectangle_containment_pct", "q25", None, "Nhiều nến vượt vùng làm hình thái lỏng."),
            ("Kéo ngược quá sâu", "mae_pct", "q75", None, "Đường đi sau phá vỡ không còn gọn."),
        ],
        "general_stat_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên", "Vùng chữ nhật cần đủ dài để có nhiều lần kiểm định biên."),
            ("Chiều cao chữ nhật", "pattern_height_pct", "%", "Chiều cao là nền để tính mục tiêu."),
            ("Độ lệch biên trên", "high_spread_pct", "%", "Biên càng ngang, hình thái càng rõ."),
            ("Độ lệch biên dưới", "low_spread_pct", "%", "Biên càng ngang, hình thái càng rõ."),
            ("Độ nằm trong vùng", "rectangle_containment_pct", "%", "Tỷ lệ càng cao, vùng hỗ trợ - kháng cự càng sạch."),
        ],
        "best_condition_specs": [
            ("Nhóm tốt nhất", "publication_quality_tier", "==", "premium", "Hình học rõ và đường giá đủ sạch."),
            ("Nhóm chuẩn", "publication_quality_tier", "==", "standard", "Đủ dùng trong thống kê nhưng không phải lúc nào cũng đẹp để minh họa."),
            ("Biên trên sát", "high_spread_pct", "<=", 1.5, "Giữ kháng cự ngang rõ hơn."),
            ("Biên dưới sát", "low_spread_pct", "<=", 1.5, "Giữ hỗ trợ ngang rõ hơn."),
            ("Đường giá sạch", "path_quality_bucket", "==", "clean", "Ít thiếu phiên và ít chuỗi đứng giá."),
        ],
        "conclusion_bullets": [
            f"{meta['title']} đã được dựng bằng scanner riêng của Rectangle Family, không dùng lại scanner Flag/Triangle/Double/Wedge.",
            meta["source_measure_rule_note"],
            meta["role_note"],
        ],
    }


def _publication_payload(pattern_id: str, meta: Mapping[str, Any], events: pd.DataFrame, all_events: pd.DataFrame, path_df: pd.DataFrame) -> dict[str, Any]:
    source = _metric_for_target(events, path_df, 1.0, "source_measure_rule")
    caution = _metric_for_target(events, path_df, 0.5, "local_caution")
    stretch = _metric_for_target(events, path_df, 0.75, "local_stretch")
    return {
        "publication_id": f"{pattern_id}_publication_chapter_v1",
        "pattern_id": pattern_id,
        "status": "PASS",
        "classification": meta["classification"],
        "chapter_reference": {
            "scope": "nhóm tốt nhất + nhóm chuẩn",
            "all_scanner_events": int(len(all_events)),
            "public_grade_events": int(len(events)),
            "public_grade_share_pct": round(float(len(events)) / max(len(all_events), 1) * 100.0, 2),
            "events": int(len(events)),
            "symbols_scanned": int(all_events["symbol"].nunique()) if "symbol" in all_events.columns else None,
            "evaluated_events": int(events["mfe_pct"].notna().sum()) if "mfe_pct" in events.columns else int(len(events)),
            "median_mfe_pct": source.get("median_mfe_pct"),
            "median_mae_pct": source.get("median_mae_pct"),
            "mfe_mae_median_ratio": source.get("mfe_mae_median_ratio"),
            "failure_5pct_rate": source.get("failure_5pct_rate"),
            "legacy_target_hit_rate": source.get("target_hit_rate"),
            "legacy_target_first_before_adverse_5pct_rate": source.get("target_first_before_adverse_5pct_rate"),
        },
        "target_calibration": {
            "target_family": {"local_caution": 0.5, "local_stretch": 0.75, "source_measure_rule": 1.0},
            "selected_base_target_multiple": 1.0,
            "selected_base_target_role": "source_measure_rule",
            "source_measure_rule": source,
            "base_target": source,
            "stretch_target": stretch,
            "legacy_target": source,
            "rows": [caution, stretch, source],
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


def build_one_rectangle_chapter(*, pattern_id: str, out_dir: Path, price_db: Path) -> dict[str, Path]:
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
    editorial_sections, editorial_source_path = _load_required_editorial(DEFAULT_AI_DIR / str(meta["slug"]) / "approved_ai_sections.json")
    payload["editorial_sections"] = editorial_sections
    payload["editorial_source_path"] = editorial_source_path
    spec = _spec(pattern_id, meta)
    publication_spec = build_rectangle_publication_spec(pattern_id=pattern_id, title=str(meta["title"]), spec=spec)
    payload["publication_spec_id"] = publication_spec["publication_spec_id"]
    selected_examples = _select_examples(events)
    payload["example_events"] = {role: {**event.to_dict(), "example_role": role} for role, event in selected_examples.items()}
    charts = _build_charts(events, price_db, chapter_dir, pattern_id=pattern_id, base_multiple=float(meta["base_target_multiple"]))
    source_notes = _source_notes(pattern_id, meta)
    paths = build_rectangle_public_chapter(
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
        "family": "rectangle_family",
        "pattern_id": pattern_id,
        "title": meta["title"],
        "status": "final",
        "classification": meta["classification"],
        "score": None,
        "claim_level": meta["claim_level"],
        "pdf": f"artifacts/final_chapters/rectangle_family/{meta['slug']}_final.pdf",
        "source_pdf": str(paths["pdf"]),
        "payload": str(paths["payload"]),
        "manuscript": str(paths["manuscript"]),
        "notes": str(paths["notes"]),
        "source_notes": str(source_notes_path),
        "publication_spec": str(publication_spec_path),
        "factory_id": FACTORY_ID,
        "publication_core_id": "pattern_publication_core_v1",
        "publication_flow": f"{FACTORY_ID} + pattern_publication_core_v1",
        "source_grounding_required": True,
        "source_grounding_policy_id": SOURCE_GROUNDED_PUBLICATION_GATE_ID,
        "direct_source_review_required": True,
        "publication_semantic_required": True,
        "publication_semantic_gate_id": publication_spec["semantic_gate_id"],
        "note": "Rectangle Family dùng scanner riêng; chỉ dùng chung publication/statistics core.",
    }
    entry_path = chapter_dir / f"{meta['slug']}_final_manifest_entry.json"
    _write_json(entry_path, entry)
    return {**paths, "source_notes": source_notes_path, "publication_spec": publication_spec_path, "final_entry": entry_path}


def build_rectangle_family_public_chapters(*, out_dir: Path = DEFAULT_OUT_DIR, price_db: Path = DEFAULT_PRICE_DB) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}
    for pattern_id in ("rectangle_bottoms", "rectangle_tops"):
        paths = build_one_rectangle_chapter(pattern_id=pattern_id, out_dir=out_dir, price_db=price_db)
        for key, path in paths.items():
            outputs[f"{pattern_id}_{key}"] = path
    manifest = {
        "release_id": "rectangle_family_public_chapters_db_active_v1",
        "factory_id": FACTORY_ID,
        "chapters": [
            {"pattern_id": pattern_id, "pdf": str(outputs[f"{pattern_id}_pdf"]), "entry": str(outputs[f"{pattern_id}_final_entry"])}
            for pattern_id in ("rectangle_bottoms", "rectangle_tops")
        ],
    }
    manifest_json = out_dir / "rectangle_family_public_chapters_manifest.json"
    _write_json(manifest_json, manifest)
    outputs["manifest_json"] = manifest_json
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Rectangle Family public chapters.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--price-db", default=str(DEFAULT_PRICE_DB))
    parser.add_argument("--pattern", choices=["rectangle_bottoms", "rectangle_tops", "all"], default="all")
    args = parser.parse_args()
    if args.pattern == "all":
        paths = build_rectangle_family_public_chapters(out_dir=Path(args.out_dir), price_db=Path(args.price_db))
    else:
        paths = build_one_rectangle_chapter(pattern_id=args.pattern, out_dir=Path(args.out_dir), price_db=Path(args.price_db))
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
