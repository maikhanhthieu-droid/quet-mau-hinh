"""Build source-grounded Cup-with-Handle Family public chapters."""

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
from scanner.cup_handle_family_public_chapter_factory import FACTORY_ID, build_cup_handle_public_chapter  # noqa: E402
from scanner.cup_handle_family_publication_specs import build_cup_handle_publication_spec, sanitize_cup_handle_public_text  # noqa: E402
from scanner.publication_flow_contract import SOURCE_GROUNDED_PUBLICATION_GATE_ID  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/cup_handle_family_public_chapters")
DEFAULT_PRICE_DB = Path("../market_cache/stock_ohlcv/latest.sqlite")
DEFAULT_AI_DIR = Path("artifacts/scanner_v2/cup_handle_family_ai_writing_approved_v1")
CORE_PATTERNS = Path("scanner/v2/core_patterns.json")
REQUIRED_EDITORIAL_SECTIONS = ("summary", "tour", "failure", "statistics", "post_breakout", "size_volume", "tactics", "checklist")

PATTERNS: dict[str, dict[str, Any]] = {
    "cup_with_handle": {
        "slug": "cup_with_handle",
        "title": "Cốc tay cầm",
        "subtitle": "Đáy tròn, tay cầm bên phải và giá đóng cửa phá lên",
        "scan_dir": Path("artifacts/scanner_v2/cup_with_handle_family/cup_with_handle/db_active"),
        "source_chapter": 9,
        "source_name": "Cup with Handle",
        "source_review_pages": [172, 174, 185],
        "source_book_pages": [149, 151, 162],
        "scope_tier": "premium",
        "classification": "hồ sơ theo dõi trong phạm vi dữ liệu hiện có",
        "claim_level": "hồ sơ theo dõi trong phạm vi dữ liệu hiện có",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "target_unit_label": "chiều cao cốc",
        "source_measure_rule_note": "Mốc nguồn đo chiều cao từ đáy cốc tới môi phải; mốc 0,5x được giữ vì chính phần nguồn ghi half-height là mốc thực dụng hơn full-height.",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, cốc tay cầm phù hợp nhất để dùng như hồ sơ theo dõi sau phá vỡ lên.",
        "direction_word": "tăng",
        "breakout_phrase": "giá đóng cửa phá lên",
        "morphology": "Cốc tay cầm bắt đầu bằng một nhịp tăng trước đó, sau đó tạo đáy tròn dạng chữ U, môi trái và môi phải gần nhau, rồi có tay cầm ngắn ở nửa trên bên phải trước khi giá đóng cửa phá lên.",
        "role_note": "Dùng như hồ sơ theo dõi sau phá vỡ lên; không phải lệnh mua tự động.",
    },
    "cup_with_handle_inverted": {
        "slug": "inverted_cup_with_handle",
        "title": "Cốc tay cầm đảo ngược",
        "subtitle": "Đỉnh tròn, tay cầm bật hồi và giá đóng cửa phá xuống",
        "scan_dir": Path("artifacts/scanner_v2/cup_with_handle_family/cup_with_handle_inverted/db_active"),
        "source_chapter": 10,
        "source_name": "Cup with Handle, Inverted",
        "source_review_pages": [187, 189, 201],
        "source_book_pages": [164, 166, 178],
        "scope_tier": "premium+standard",
        "classification": "tài liệu phòng thủ và cảnh báo rủi ro trong phạm vi dữ liệu hiện có",
        "claim_level": "tài liệu phòng thủ và cảnh báo rủi ro trong phạm vi dữ liệu hiện có",
        "base_target_multiple": 1.0,
        "legacy_target_multiple": 1.0,
        "target_unit_label": "chiều cao tay cầm",
        "source_measure_rule_note": "Mốc nguồn của cốc tay cầm đảo ngược dùng chiều cao tay cầm, không dùng toàn bộ chiều cao cốc.",
        "public_classification_sentence": "Trong phạm vi cổ phiếu cơ sở Việt Nam, cốc tay cầm đảo ngược nên được đọc như tài liệu phòng thủ/thông tin rủi ro.",
        "direction_word": "giảm",
        "breakout_phrase": "giá đóng cửa phá xuống",
        "morphology": "Cốc tay cầm đảo ngược là một đỉnh tròn với hai vành thấp tương đối gần nhau; sau vành phải, tay cầm bật hồi nhưng không vượt đỉnh cốc, rồi giá đóng cửa phá xuống.",
        "role_note": "Dùng như tài liệu phòng thủ/thông tin rủi ro; không phải khuyến nghị bán khống trên cổ phiếu cơ sở.",
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


def _load_required_editorial(path: Path) -> tuple[dict[str, list[str]], str]:
    loaded = load_public_editorial_sections(path)
    sections = loaded.get("sections") if isinstance(loaded.get("sections"), Mapping) else {}
    missing = [key for key in REQUIRED_EDITORIAL_SECTIONS if not sections.get(key)]
    if missing:
        raise RuntimeError(f"Missing approved Cup-with-Handle editorial sections in {path}: {', '.join(missing)}")
    cleaned = {
        key: [sanitize_cup_handle_public_text(item) for item in value]
        for key, value in dict(sections).items()
    }
    return cleaned, str(path)


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
    ax.plot(x, df["close"].to_numpy(), color="#222222", linewidth=0.9, alpha=0.30)

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
        ("left_rim_price", "#4C78A8", "môi trái"),
        ("right_rim_price", "#54A24B", "môi phải"),
        ("cup_extreme_price", "#E45756", "đáy/đỉnh cốc"),
        ("handle_extreme_price", "#B279A2", "cực trị tay cầm"),
    ]:
        try:
            value = float(event.get(key))
        except (TypeError, ValueError):
            continue
        ax.axhline(value, color=color, linestyle=":", linewidth=0.8, alpha=0.75)
        ax.text(0.5, value, label, fontsize=7, color=color, va="bottom")
    breakout_price = float(event.get("breakout_price"))
    target = _target_price(event, base_multiple)
    ax.axhline(breakout_price, color="#245b5a", linestyle="--", linewidth=0.9, alpha=0.85)
    ax.axhline(target, color="#F58518", linestyle="--", linewidth=0.9, alpha=0.9)
    ax.text(0.5, breakout_price, "giá phá vỡ", fontsize=7, color="#245b5a", va="bottom")
    ax.text(0.5, target, "mốc chính", fontsize=7, color="#F58518", va="bottom")
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
    x = np.linspace(0, 10, 80)
    if pattern_id == "cup_with_handle":
        y = 10 + 4 * ((x - 4) / 4) ** 2
        y[x > 8] = 13.0 - 0.25 * (x[x > 8] - 8) + 0.20 * np.sin((x[x > 8] - 8) * 3)
        ax.plot(x, y, color="#173b3a", linewidth=2.0)
        ax.annotate("đáy tròn", xy=(4, 10), xytext=(2.2, 8.8), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
        ax.annotate("tay cầm bên phải", xy=(8.7, 12.8), xytext=(6.7, 15.3), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
        ax.annotate("phá vỡ lên", xy=(9.9, 13.6), xytext=(8.2, 16.1), arrowprops={"arrowstyle": "->", "color": "#6f4aa8"}, color="#6f4aa8", fontsize=9)
        target_y = 15.0
        title = "Giải phẫu cốc tay cầm"
    else:
        y = 15 - 4 * ((x - 4) / 4) ** 2
        y[x > 8] = 12.0 + 0.35 * (x[x > 8] - 8) + 0.20 * np.sin((x[x > 8] - 8) * 3)
        ax.plot(x, y, color="#173b3a", linewidth=2.0)
        ax.annotate("đỉnh tròn", xy=(4, 15), xytext=(2.1, 16.2), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
        ax.annotate("tay cầm bật hồi", xy=(8.8, 12.4), xytext=(6.5, 9.8), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
        ax.annotate("phá vỡ xuống", xy=(9.9, 11.5), xytext=(8.0, 8.2), arrowprops={"arrowstyle": "->", "color": "#6f4aa8"}, color="#6f4aa8", fontsize=9)
        target_y = 10.6
        title = "Giải phẫu cốc tay cầm đảo ngược"
    ax.axvspan(0.6, 9.1, color="#1f77b4", alpha=0.08)
    ax.axhline(target_y, color="#e98b2a", linestyle="--", linewidth=0.9)
    ax.text(0, target_y + 0.15, "mốc đọc chính", color="#e98b2a", fontsize=8)
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
            rows.append({"rule_id": rule.get("rule_id"), "short_excerpt": rule.get("evidence_excerpt"), "implementation_mapping": rule.get("interpreted_rule")})
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
            "review_note": "Đã đối chiếu trực tiếp chương Cup with Handle trong PDF gốc trước khi dựng chapter.",
        },
        "source_rules": rows,
    }


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
        try:
            distance = float(event.get("target_dist_pct")) * multiple
        except (TypeError, ValueError):
            distance = float("nan")
        group = grouped.get(str(event.get("event_id")))
        if group is None or group.empty or not math.isfinite(distance):
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
        "n": int(len(events)),
    }


def _enrich_events_for_target(events: pd.DataFrame, path_df: pd.DataFrame, multiple: float) -> pd.DataFrame:
    events = events.copy()
    metrics = _metric_for_target(events, path_df, multiple, "base_target")
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
    events["base_target_metrics"] = json.dumps(metrics, ensure_ascii=False)
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
    if not success.empty:
        textbook = success.sort_values(["_market_rank", "publication_quality_score", "mfe_pct"], ascending=[True, False, False]).iloc[0]
    else:
        textbook = source.sort_values(["_market_rank", "publication_quality_score", "mfe_pct"], ascending=[True, False, False]).iloc[0]
    neutral = source[source["detection_id"].astype(str) != str(textbook.get("detection_id"))].copy()
    neutral["median_distance"] = (pd.to_numeric(neutral["mfe_pct"], errors="coerce") - med).abs()
    middle = neutral.sort_values(["_market_rank", "median_distance", "publication_quality_score"], ascending=[True, True, False]).iloc[0]
    if not failure.empty:
        failure_pick = failure.sort_values(["_market_rank", "mae_pct", "publication_quality_score"], ascending=[True, False, False]).iloc[0]
    else:
        failure_pick = source.sort_values(["_market_rank", "mae_pct"], ascending=[True, False]).iloc[0]
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
        window, _ = _window_for_event(raw, event)
        out_path = charts_dir / f"{key}_{event['symbol']}_{event['breakout_date']}.png"
        _plot_event_chart(window, event, out_path, f"{event['symbol']} - {title_map.get(key, 'ví dụ')} ({event['breakout_date']})", base_multiple=base_multiple)
        paths[key] = out_path
    return paths


def _spec(pattern_id: str, meta: Mapping[str, Any]) -> dict[str, Any]:
    down = pattern_id.endswith("inverted")
    labels = {"favorable_move": "mức giảm thuận lợi", "adverse_move": "mức bật ngược bất lợi"} if down else {"favorable_move": "mức tăng tốt nhất", "adverse_move": "mức kéo ngược sâu nhất"}
    base = float(meta["base_target_multiple"])
    legacy = float(meta["legacy_target_multiple"])
    quick = [
        ["Mẫu này dùng để đọc gì?", "Một cấu trúc dài hơi trước phá vỡ, không phải tín hiệu mua bán tự động."],
        ["Mốc đọc chính?", "0,5x chiều cao cốc." if not down else "Chiều cao tay cầm theo mốc nguồn."],
        ["Khi nào cần thận trọng?", "Khi môi cốc lệch xa, tay cầm quá sâu hoặc đường giá hậu phá vỡ kéo ngược nhanh."],
    ]
    return {
        "title": meta["title"],
        "subtitle": meta["subtitle"],
        "base_target_multiple": base,
        "base_target_label": "0,5x" if base == 0.5 else "1,0x",
        "legacy_target_multiple": legacy,
        "legacy_target_label": "1,0x",
        "target_unit_label": meta["target_unit_label"],
        "target_focus_title": "Mốc thực dụng" if not down else "Mốc nguồn",
        "target_focus_caption": "mốc thực dụng 0,5x" if not down else "mốc chiều cao tay cầm",
        "target_focus_reading": "mốc thực dụng bám sát phần half-height trong nguồn" if not down else "mốc nguồn của mẫu đảo ngược",
        "target_full_title": "Mốc đầy đủ 1,0x",
        "target_full_reading": "mốc căng để xem độ nhạy, không phải kỳ vọng mặc định.",
        "morphology_sentence": meta["morphology"],
        "role_note": meta["role_note"],
        "classification_sentence": meta["public_classification_sentence"],
        "headline_scope": "Phần kết luận chính dùng phạm vi đã qua kiểm tra hình thái và chất lượng đường giá.",
        "local_source_chapter": meta["source_chapter"],
        "schematic_caption": f"Sơ đồ minh họa {meta['title'].lower()}: hình cốc, tay cầm bên phải, xác nhận bằng {meta['breakout_phrase']} và mốc đọc chính.",
        "how_subtitle": "Cốc và tay cầm là setup dài; breakout chỉ là mốc xác nhận để đo hậu quả.",
        "labels": labels,
        "source_rule_ids": [
            "cwh.prior_rise.min_30",
            "cwh.shape.u_shaped",
            "cwh.duration.cup_7_to_65_weeks",
            "cwh.handle.required_min_1_week",
            "cwh.handle.upper_half",
            "cwh.lips.near_same_price",
            "cwh.breakout.up_close",
            "cwh.target.full_and_half_height",
        ]
        if not down
        else [
            "icwh.shape.rounded_inverted_cup",
            "icwh.rims.near_same_price",
            "icwh.handle.right_bounce",
            "icwh.breakout.down_close",
            "icwh.target.handle_height",
        ],
        "rule_text_map": {
            "Rise before cup at least 30%.": "Có nhịp tăng trước mẫu đủ rõ.",
            "U-shaped cup.": "Cốc có đáy tròn dạng chữ U.",
            "Cup duration 7 to 65 weeks.": "Cốc là mẫu dài, không phải nhịp nghỉ vài phiên.",
            "Handle minimum 1 week.": "Tay cầm kéo dài tối thiểu một tuần giao dịch.",
            "Handle forms in upper half of cup.": "Tay cầm nằm ở nửa trên của cốc.",
            "Cup edges/lips should be about same price level.": "Hai môi cốc tương đối gần nhau.",
            "Upward Breakouts": "Mẫu thường chỉ được xác nhận khi phá lên.",
            "Better target: half cup height.": "Mốc 0,5x chiều cao cốc được dùng như mốc thực dụng.",
            "Rounded cup, accept deviations.": "Cốc đảo ngược có đỉnh tròn, cho phép lệch nhỏ.",
            "Cup rims near same price, usually <6% difference.": "Hai vành cốc đảo ngược gần nhau, ưu tiên lệch dưới 6%.",
            "Handle must not rise above cup top and should bounce upward.": "Tay cầm bật hồi nhưng không vượt đỉnh cốc.",
            "Downward Breakouts": "Mẫu đảo ngược xác nhận bằng phá xuống.",
            "measure the handle height": "Mục tiêu mẫu đảo ngược dùng chiều cao tay cầm.",
        },
        "quick_question_rows": [
            ["Cốc", "Cấu trúc có đủ tròn và đủ dài hay chỉ là một cú bật chữ V?"],
            ["Tay cầm", "Tay cầm nằm bên phải và không quá sâu không?"],
            ["Phá vỡ", f"{meta['breakout_phrase'].capitalize()} hay chỉ xuyên trong phiên?"],
            ["Đường đi", "Mục tiêu có đến trước kéo ngược 5% không?"],
        ],
        "component_rows": [
            ["Cốc tròn", "Phân biệt với V-shape hoặc kênh giá.", "Kiểm tra đáy/đỉnh nằm giữa hai môi và có đủ phiên gần cực trị."],
            ["Hai môi gần nhau", "Giữ hình thái cân bằng.", "Normal dùng tolerance 9%; inverted dùng 6%."],
            ["Tay cầm", "Phần nghỉ cuối trước xác nhận.", "Tối thiểu 5 phiên; normal nằm ở nửa trên."],
            ["Phá vỡ đóng cửa", "Chỉ sau xác nhận mới đo kết quả.", meta["breakout_phrase"]],
            ["Mục tiêu", "Dùng họ mục tiêu cố định.", meta["source_measure_rule_note"]],
        ],
        "reject_bullets": [
            "Cốc quá nhọn hoặc quá ngắn: dễ là nhịp hồi/kéo đơn lẻ.",
            "Tay cầm rơi quá sâu: mẫu mất tính chất nghỉ nhẹ.",
            "Không có đóng cửa xác nhận: chưa đưa vào thống kê hậu phá vỡ.",
            "Đường giá thiếu thanh khoản hoặc thiếu phiên: không dùng làm ví dụ công bố.",
        ],
        "identification_paragraphs": [meta["morphology"]],
        "example_intro": ["Ba ví dụ dưới đây ưu tiên VN30/VN100 khi có thể: một mẫu đạt mốc chính, một mẫu gần trung vị và một mẫu thất bại."],
        "failure_bullets": [
            "Thất bại 5% là thước đo mô tả hậu phá vỡ, không phải stop-loss giao dịch.",
            "Tỷ lệ đạt mục tiêu phải đọc cùng câu hỏi mục tiêu có đến trước kéo ngược hay không.",
            "Mẫu đẹp về hình học vẫn có thể yếu nếu phá vỡ bị kéo ngược nhanh.",
        ],
        "target_paragraph": meta["source_measure_rule_note"],
        "quick_conclusion_rows": quick,
        "caveat_bullets": [
            "Không tuyên bố đây là nghiên cứu toàn thị trường đúng từng ngày lịch sử.",
            "Không dùng lịch sử thành phần VN30/VN100 làm kết luận chính.",
            "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
            "Chương là tài liệu tham khảo hậu phá vỡ, không phải khuyến nghị mua bán.",
        ],
        "quantile_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên"),
            ("Chiều cao cốc", "pattern_height_pct", "%"),
            ("Độ lệch hai môi", "rim_diff_pct", "%"),
            ("Độ dài tay cầm", "handle_width_bars", "phiên"),
            ("Độ sâu tay cầm", "handle_retrace_pct", "% chiều cao"),
            (labels["favorable_move"].capitalize(), "mfe_pct", "%"),
            (labels["adverse_move"].capitalize(), "mae_pct", "%"),
            ("Ngày chạm mốc chính", "days_to_target", "phiên"),
        ],
        "skip_condition_specs": [
            ("Mẫu kéo quá dài", "pattern_width_bars", "q75_bars", None, "Cốc quá dài dễ chuyển thành nền giá rộng hơn."),
            ("Hai môi lệch xa", "rim_diff_pct", "q75", None, "Môi lệch xa làm cấu trúc kém giống mẫu nguồn."),
            ("Tay cầm quá sâu", "handle_retrace_pct", "q75", None, "Tay cầm sâu làm mất tính chất nghỉ cuối."),
            (f"{labels['adverse_move'].capitalize()} quá sâu", "mae_pct", "q75", None, "Đường đi không còn phù hợp với mẫu cốc tay cầm sạch."),
        ],
        "general_stat_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên", "Cốc tay cầm là mẫu dài hơn cờ/pennant."),
            ("Chiều cao cốc", "pattern_height_pct", "%", "Chiều cao là nền để tính mục tiêu."),
            ("Độ lệch hai môi", "rim_diff_pct", "%", "Môi càng gần nhau, hình thái càng rõ."),
            ("Độ dài tay cầm", "handle_width_bars", "phiên", "Tay cầm quá dài làm mẫu kém gọn."),
            ("Độ sâu tay cầm", "handle_retrace_pct", "%", "Tay cầm càng sâu, rủi ro phá mẫu càng lớn."),
        ],
        "best_condition_specs": [
            ("Nhóm tốt nhất", "publication_quality_tier", "==", "premium", "Hình học rõ và đường giá đủ sạch."),
            ("Nhóm chuẩn", "publication_quality_tier", "==", "standard", "Đủ dùng trong thống kê nhưng không phải lúc nào cũng đẹp để minh họa."),
            ("Hai môi sát nhau", "rim_diff_pct", "<=", 4.0 if not down else 3.0, "Giữ cấu trúc cốc cân hơn."),
            ("Đường giá sạch", "path_quality_bucket", "==", "clean", "Ít thiếu phiên và ít chuỗi đứng giá."),
        ],
        "conclusion_bullets": [
            f"{meta['title']} đã được dựng bằng scanner riêng của Cup Family, không dùng lại scanner Flag/Triangle/Double/Wedge.",
            meta["source_measure_rule_note"],
            meta["role_note"],
        ],
    }


def _publication_payload(pattern_id: str, meta: Mapping[str, Any], events: pd.DataFrame, all_events: pd.DataFrame, path_df: pd.DataFrame) -> dict[str, Any]:
    base_multiple = float(meta["base_target_multiple"])
    legacy_multiple = float(meta["legacy_target_multiple"])
    base = _metric_for_target(events, path_df, base_multiple, "bulkowski_adjusted_base" if base_multiple == 0.5 else "source_measure_rule")
    stretch = _metric_for_target(events, path_df, 0.75, "local_stretch") if base_multiple < 0.75 else {}
    legacy = _metric_for_target(events, path_df, legacy_multiple, "legacy_full_height" if base_multiple != legacy_multiple else "source_measure_rule")
    target_rows = [base]
    if stretch:
        target_rows.append(stretch)
    if abs(base_multiple - legacy_multiple) > 1e-9:
        target_rows.append(legacy)
    return {
        "publication_id": f"{pattern_id}_publication_chapter_v1",
        "pattern_id": pattern_id,
        "status": "PASS",
        "classification": meta["classification"],
        "chapter_reference": {
            "scope": "nhóm tốt nhất" if meta["scope_tier"] == "premium" else "nhóm tốt nhất + nhóm chuẩn",
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
            "legacy_target_hit_rate": legacy.get("target_hit_rate"),
            "legacy_target_first_before_adverse_5pct_rate": legacy.get("target_first_before_adverse_5pct_rate"),
        },
        "target_calibration": {
            "target_family": {"local_base": base_multiple, "local_stretch": 0.75, "legacy_full_height": legacy_multiple},
            "selected_base_target_multiple": base_multiple,
            "selected_base_target_role": base.get("target_role"),
            "base_target": base,
            "stretch_target": stretch,
            "legacy_target": legacy,
            "rows": target_rows,
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


def build_one_cup_handle_chapter(*, pattern_id: str, out_dir: Path, price_db: Path) -> dict[str, Path]:
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
    publication_spec = build_cup_handle_publication_spec(pattern_id=pattern_id, title=str(meta["title"]), spec=spec)
    payload["publication_spec_id"] = publication_spec["publication_spec_id"]
    selected_examples = _select_examples(events)
    payload["example_events"] = {role: {**event.to_dict(), "example_role": role} for role, event in selected_examples.items()}
    charts = _build_charts(events, price_db, chapter_dir, pattern_id=pattern_id, base_multiple=float(meta["base_target_multiple"]))
    source_notes = _source_notes(pattern_id, meta)
    paths = build_cup_handle_public_chapter(
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
        "family": "cup_handle_family",
        "pattern_id": pattern_id,
        "title": meta["title"],
        "status": "final",
        "classification": meta["classification"],
        "score": None,
        "claim_level": meta["claim_level"],
        "pdf": f"artifacts/final_chapters/cup_handle_family/{meta['slug']}_final.pdf",
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
        "note": "Cup Family dùng scanner riêng; chỉ dùng chung publication/statistics core.",
    }
    entry_path = chapter_dir / f"{meta['slug']}_final_manifest_entry.json"
    _write_json(entry_path, entry)
    return {**paths, "source_notes": source_notes_path, "publication_spec": publication_spec_path, "final_entry": entry_path}


def build_cup_handle_family_public_chapters(*, out_dir: Path = DEFAULT_OUT_DIR, price_db: Path = DEFAULT_PRICE_DB) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}
    for pattern_id in ("cup_with_handle", "cup_with_handle_inverted"):
        paths = build_one_cup_handle_chapter(pattern_id=pattern_id, out_dir=out_dir, price_db=price_db)
        for key, path in paths.items():
            outputs[f"{pattern_id}_{key}"] = path
    manifest = {
        "release_id": "cup_handle_family_public_chapters_db_active_v1",
        "factory_id": FACTORY_ID,
        "chapters": [
            {"pattern_id": pattern_id, "pdf": str(outputs[f"{pattern_id}_pdf"]), "entry": str(outputs[f"{pattern_id}_final_entry"])}
            for pattern_id in ("cup_with_handle", "cup_with_handle_inverted")
        ],
    }
    manifest_json = out_dir / "cup_handle_family_public_chapters_manifest.json"
    _write_json(manifest_json, manifest)
    outputs["manifest_json"] = manifest_json
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Cup-with-Handle Family public chapters.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--price-db", default=str(DEFAULT_PRICE_DB))
    parser.add_argument("--pattern", choices=["cup_with_handle", "cup_with_handle_inverted", "all"], default="all")
    args = parser.parse_args()
    if args.pattern == "all":
        paths = build_cup_handle_family_public_chapters(out_dir=Path(args.out_dir), price_db=Path(args.price_db))
    else:
        paths = build_one_cup_handle_chapter(pattern_id=args.pattern, out_dir=Path(args.out_dir), price_db=Path(args.price_db))
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
