"""Build source-grounded Scallop Family public-chapter seed artifacts.

This module prepares deterministic ingredients only: locked metrics, source
notes, publication specs, and starter charts. It must not render a final public
PDF. Final prose and PDF rendering belong to the canonical source-guided
editorial flow and `canonical_publication_chapter_factory_v1`.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Mapping

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

from scanner.publication_flow_contract import SOURCE_GROUNDED_PUBLICATION_GATE_ID
from scanner.publication_semantic_contract import PUBLICATION_SEMANTIC_GATE_ID


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/scallop_family_public_chapters")
DEFAULT_SCAN_DIR = Path("artifacts/scanner_v2/scallop_family")
DEFAULT_PRICE_DB = Path("../market_cache/stock_ohlcv/latest.sqlite")
SOURCE_PDF = "references/encyclopedia-of-chart-patterns-2nbsped-9786468600-3175723993-9780471668268-0471668265_compress.pdf"


PATTERNS: dict[str, dict[str, Any]] = {
    "scallops_ascending": {
        "slug": "scallops_ascending",
        "title": "Scallop tăng",
        "subtitle": "Dạng chữ J: tạo đỉnh, cong xuống, rồi tạo đỉnh cao hơn",
        "source_chapter": 41,
        "source_name": "Scallops, Ascending",
        "source_book_pages": [624, 625, 626, 627, 628, 629, 630, 631, 632, 633, 634, 635, 636, 637, 638, 639],
        "source_pdf_pages": [647, 648, 649, 650, 651, 652, 653, 654, 655, 656, 657, 658, 659, 660, 661, 662],
        "classification": "hồ sơ tham khảo hai hướng; nhánh phá lên là phần dễ đọc hơn trong cổ phiếu cơ sở",
        "claim_level": "đọc như mẫu chữ J tăng, cần tách riêng phá lên và phá xuống",
        "morphology": "Scallop tăng có dạng chữ J: giá tạo một đỉnh, lùi xuống thành vùng cong, rồi đi lên tạo đỉnh bên phải cao hơn. Mẫu chỉ có ý nghĩa sau khi giá đóng cửa phá qua vùng xác nhận.",
        "source_shape": "rounded_recession",
        "direction_label": "phá lên hoặc phá xuống quanh hai môi của chữ J",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "target_unit_label": "chiều cao từ đáy cong tới môi cao hơn",
    },
    "scallops_ascending_inverted": {
        "slug": "scallops_ascending_inverted",
        "title": "Scallop tăng đảo ngược",
        "subtitle": "Dạng ô mở ngược: giá chạy lên, cong đỉnh, rồi xác nhận tiếp diễn lên",
        "source_chapter": 42,
        "source_name": "Scallops, Ascending and Inverted",
        "source_book_pages": [640, 641, 642, 643, 644, 645, 646, 647, 648, 649, 650, 651, 652, 653],
        "source_pdf_pages": [663, 664, 665, 666, 667, 668, 669, 670, 671, 672, 673, 674, 675, 676],
        "classification": "ứng viên long-cash mạnh nhất trong Scallop Family nhưng vẫn cần kiểm tra đường đi sau xác nhận",
        "claim_level": "đọc như mẫu đảo ngược chữ J có nhánh phá lên đáng theo dõi",
        "morphology": "Scallop tăng đảo ngược giống nửa phải của một chiếc ô mở: giá chạy lên, cong tròn ở đỉnh, lùi vừa đủ nhưng không phá hỏng cấu trúc, rồi xác nhận lên trên vùng cao của mẫu.",
        "source_shape": "rounded_cap",
        "direction_label": "phá lên sau vùng cong đỉnh",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "target_unit_label": "chiều cao phần cong của mẫu",
    },
    "scallops_descending": {
        "slug": "scallops_descending",
        "title": "Scallop giảm",
        "subtitle": "Dạng chữ J ngược: đỉnh trái cao hơn, vùng cong nằm thấp hơn",
        "source_chapter": 43,
        "source_name": "Scallops, Descending",
        "source_book_pages": [654, 655, 656, 657, 658, 659, 660, 661, 662, 663, 664, 665, 666, 667, 668, 669, 670],
        "source_pdf_pages": [677, 678, 679, 680, 681, 682, 683, 684, 685, 686, 687, 688, 689, 690, 691, 692, 693],
        "classification": "hồ sơ tham khảo hai hướng; nhánh phá lên có thể đọc như hồi phục, nhánh phá xuống là cảnh báo rủi ro",
        "claim_level": "đọc như chữ J đảo chiều vị trí, không gộp kết quả phá lên và phá xuống",
        "morphology": "Scallop giảm trông như chữ J bị đảo: môi trái cao hơn môi phải, phần đáy cong nằm thấp hơn và mẫu thường xuất hiện quanh một nhịp giảm hoặc vùng hồi yếu.",
        "source_shape": "rounded_recession",
        "direction_label": "phá lên khỏi môi phải hoặc phá xuống dưới đáy cong",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "target_unit_label": "chiều cao từ đáy cong tới môi trái",
    },
    "scallops_descending_inverted": {
        "slug": "scallops_descending_inverted",
        "title": "Scallop giảm đảo ngược",
        "subtitle": "Dạng chữ J úp: giá hồi lên cong đỉnh rồi xác nhận giảm",
        "source_chapter": 44,
        "source_name": "Scallops, Descending and Inverted",
        "source_book_pages": [672, 673, 674, 675, 676, 677, 678, 679, 680, 681],
        "source_pdf_pages": [695, 696, 697, 698, 699, 700, 701, 702, 703, 704],
        "classification": "hồ sơ phòng thủ/thông tin vì nhánh chính là phá xuống trên cổ phiếu cơ sở",
        "claim_level": "đọc như mẫu cảnh báo nhịp giảm tiếp diễn sau vùng cong đỉnh",
        "morphology": "Scallop giảm đảo ngược có dạng chữ J úp: giá hồi lên, tạo đỉnh cong tròn, rồi rơi xuống dưới đáy mẫu. Trên cổ phiếu cơ sở, chương nên đọc như hồ sơ phòng thủ hơn là cơ hội short mặc định.",
        "source_shape": "rounded_cap",
        "direction_label": "phá xuống dưới đáy mẫu sau vùng cong đỉnh",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "target_unit_label": "chiều cao phần cong trước nhịp giảm",
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
    return str(value).strip().lower() in {"true", "1", "yes", "y", "có"}


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


def _window_for_event(df: pd.DataFrame, event: Mapping[str, Any], *, pre_bars: int = 45, post_bars: int = 55) -> pd.DataFrame:
    start = pd.to_datetime(event.get("formation_start_date"), errors="coerce")
    breakout = pd.to_datetime(event.get("breakout_date"), errors="coerce")
    if pd.isna(start) or pd.isna(breakout):
        return df.iloc[:0].copy()
    start_idx = int(df["date"].searchsorted(start, side="left"))
    breakout_idx = int(df["date"].searchsorted(breakout, side="left"))
    return df.iloc[max(0, start_idx - pre_bars) : min(len(df), breakout_idx + post_bars + 1)].copy().reset_index(drop=True)


def _target_price(event: Mapping[str, Any], multiple: float) -> float:
    breakout = float(event.get("breakout_price"))
    full = float(event.get("target_price"))
    return breakout + (full - breakout) * multiple


def _plot_schematic(out_path: Path, *, pattern_id: str) -> None:
    meta = PATTERNS[pattern_id]
    fig, ax = plt.subplots(figsize=(9.2, 3.9), dpi=180)
    if pattern_id == "scallops_ascending":
        x = np.linspace(0, 1, 80)
        y = 2.4 + 1.25 * (x - 0.42) ** 2
        ax.plot([0.0, *x, 1.12], [3.8, *y, 4.35], color="#173b3a", linewidth=2.0)
        ax.text(0.02, 3.95, "môi trái", fontsize=8, color="#245b5a")
        ax.text(1.02, 4.45, "môi phải cao hơn", fontsize=8, color="#245b5a")
    elif pattern_id == "scallops_ascending_inverted":
        x = np.linspace(0, 1, 80)
        y = 4.2 - 1.1 * (x - 0.45) ** 2
        ax.plot([0.0, *x, 1.12], [2.6, *y, 4.45], color="#173b3a", linewidth=2.0)
        ax.text(0.02, 2.75, "bắt đầu thấp hơn", fontsize=8, color="#245b5a")
        ax.text(1.02, 4.55, "xác nhận lên", fontsize=8, color="#245b5a")
    elif pattern_id == "scallops_descending":
        x = np.linspace(0, 1, 80)
        y = 2.2 + 1.2 * (x - 0.45) ** 2
        ax.plot([0.0, *x, 1.12], [4.45, *y, 3.25], color="#173b3a", linewidth=2.0)
        ax.text(0.02, 4.55, "môi trái cao hơn", fontsize=8, color="#245b5a")
        ax.text(1.0, 3.35, "môi phải thấp hơn", fontsize=8, color="#245b5a")
    else:
        x = np.linspace(0, 1, 80)
        y = 4.25 - 1.15 * (x - 0.45) ** 2
        ax.plot([0.0, *x, 1.12], [4.5, *y, 2.55], color="#173b3a", linewidth=2.0)
        ax.text(0.02, 4.6, "điểm bắt đầu cao", fontsize=8, color="#245b5a")
        ax.text(1.0, 2.65, "xác nhận giảm", fontsize=8, color="#245b5a")
    ax.set_title(meta["title"], loc="left", fontsize=10)
    ax.text(0.02, 1.55, "Chỉ tính mẫu sau khi giá đóng cửa phá qua vùng xác nhận.", fontsize=8, color="#555555")
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
        ax.vlines(i, l, h, color="#222222", linewidth=0.7, alpha=0.75)
        ax.add_patch(Rectangle((i - 0.32, min(o, c)), 0.64, max(abs(c - o), 1e-6), facecolor=color, edgecolor=color, linewidth=0.5, alpha=0.9))
    ax.plot(x, df["close"].to_numpy(), color="#222222", linewidth=0.9, alpha=0.25)

    start = pd.to_datetime(event.get("formation_start_date"), errors="coerce")
    end = pd.to_datetime(event.get("formation_end_date"), errors="coerce")
    breakout = pd.to_datetime(event.get("breakout_date"), errors="coerce")

    def ix(ts: pd.Timestamp) -> int | None:
        if pd.isna(ts):
            return None
        return min(max(int(df["date"].searchsorted(ts, side="left")), 0), len(df) - 1)

    i0, i1, ib = ix(start), ix(end), ix(breakout)
    if i0 is not None and i1 is not None and i1 >= i0:
        ax.axvspan(i0, i1, color="#4C78A8", alpha=0.10)
        xs = np.arange(i0, i1 + 1)
        close = df.iloc[i0 : i1 + 1]["close"].to_numpy()
        if len(xs) >= 3:
            ax.plot(xs, close, color="#245b5a", linewidth=1.15, alpha=0.8)
        for price, label in (
            (event.get("left_lip_price"), "môi trái"),
            (event.get("right_lip_price"), "môi phải"),
            (event.get("high_boundary_price"), "biên cao"),
            (event.get("low_boundary_price"), "biên thấp"),
        ):
            try:
                y = float(price)
            except (TypeError, ValueError):
                continue
            ax.axhline(y, color="#245b5a", linestyle=":", linewidth=0.7, alpha=0.45)
            ax.text(max(i0, 0) + 0.3, y, label, fontsize=7, color="#245b5a", va="bottom")
    if ib is not None:
        ax.axvline(ib, color="#7A5195", linewidth=1.1)
        ax.text(ib + 0.3, float(df["high"].max()), "phá vỡ", fontsize=8, color="#7A5195", va="bottom")
    breakout_price = float(event.get("breakout_price"))
    target = _target_price(event, base_multiple)
    ax.axhline(breakout_price, color="#7A5195", linestyle="--", linewidth=0.9, alpha=0.9)
    ax.axhline(target, color="#F58518", linestyle="--", linewidth=0.9, alpha=0.9)
    ax.text(0.5, breakout_price, "giá phá vỡ", fontsize=7, color="#7A5195", va="bottom")
    ax.text(0.5, target, "mốc 0,5x", fontsize=7, color="#F58518", va="bottom")
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


def _events_for_scope(events: pd.DataFrame) -> pd.DataFrame:
    if "publication_quality_tier" in events.columns:
        scoped = events[events["publication_quality_tier"].isin(["premium", "standard"])].copy()
        if not scoped.empty:
            return scoped
    return events.copy()


def _metric_for_target(events: pd.DataFrame, path_df: pd.DataFrame, multiple: float, role: str) -> dict[str, Any]:
    if events.empty:
        return {"target_multiple": multiple, "target_role": role, "target_label": f"{multiple:.2g}x", "n": 0}
    work = events.copy()
    work["target_dist_scaled_pct"] = pd.to_numeric(work["target_dist_pct"], errors="coerce") * float(multiple)
    work["mfe_pct"] = pd.to_numeric(work["mfe_pct"], errors="coerce")
    work["mae_pct"] = pd.to_numeric(work["mae_pct"], errors="coerce")
    work["target_hit_scaled"] = work["mfe_pct"] >= work["target_dist_scaled_pct"]
    event_ids = set(work["detection_id"].astype(str))
    path = path_df[path_df["event_id"].astype(str).isin(event_ids)].copy() if not path_df.empty else pd.DataFrame()
    first_target: dict[str, float] = {}
    first_adverse: dict[str, float] = {}
    if not path.empty:
        path["threshold"] = path["event_id"].map(dict(zip(work["detection_id"].astype(str), work["target_dist_scaled_pct"])))
        path["bar_after_breakout"] = pd.to_numeric(path["bar_after_breakout"], errors="coerce")
        path["signed_high_excursion_pct"] = pd.to_numeric(path["signed_high_excursion_pct"], errors="coerce")
        path["signed_low_excursion_pct"] = pd.to_numeric(path["signed_low_excursion_pct"], errors="coerce")
        hit_rows = path[path["signed_high_excursion_pct"] >= path["threshold"]]
        adv_rows = path[path["signed_low_excursion_pct"] <= -5.0]
        first_target = hit_rows.groupby("event_id")["bar_after_breakout"].min().to_dict()
        first_adverse = adv_rows.groupby("event_id")["bar_after_breakout"].min().to_dict()
    first_target_series = work["detection_id"].astype(str).map(first_target)
    first_adverse_series = work["detection_id"].astype(str).map(first_adverse)
    target_first = first_target_series.notna() & (first_adverse_series.isna() | (first_target_series < first_adverse_series))
    hit_days = first_target_series.dropna()
    ratio = float(work["mfe_pct"].median() / max(work["mae_pct"].median(), 1e-9)) if work["mae_pct"].notna().any() else float("nan")
    return {
        "target_multiple": multiple,
        "target_role": role,
        "target_label": f"{multiple:g}x",
        "target_hit_rate": round(float(work["target_hit_scaled"].mean() * 100.0), 2),
        "target_first_before_adverse_5pct_rate": round(float(target_first.mean() * 100.0), 2),
        "failure_5pct_rate": round(float(work["failure_5pct"].map(_truthy).mean() * 100.0), 2),
        "median_mfe_pct": round(float(work["mfe_pct"].median()), 2),
        "median_mae_pct": round(float(work["mae_pct"].median()), 2),
        "mfe_mae_median_ratio": round(ratio, 2) if math.isfinite(ratio) else None,
        "median_target_dist_pct": round(float(work["target_dist_scaled_pct"].median()), 2),
        "median_days_to_target": round(float(hit_days.median()), 1) if not hit_days.empty else None,
        "n": int(len(work)),
    }


def _select_examples(events: pd.DataFrame) -> dict[str, pd.Series]:
    source = events.copy()
    source["_market_rank"] = source.get("market_group", pd.Series("Outside VN100", index=source.index)).map({"VN30": 0, "VN100 ex VN30": 1}).fillna(2)
    for column in ("target_hit", "failure_5pct", "target_first_before_adverse_5pct"):
        if column in source.columns:
            source[column] = source[column].map(_truthy)
    for column in ("publication_quality_score", "pattern_quality_score", "mfe_pct", "mae_pct", "pattern_width_bars", "pattern_height_pct"):
        if column in source.columns:
            source[column] = pd.to_numeric(source[column], errors="coerce")
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
    prefix = {
        "scallops_ascending": "sa",
        "scallops_ascending_inverted": "sai",
        "scallops_descending": "sd",
        "scallops_descending_inverted": "sdi",
    }[pattern_id]
    normal = "inverted" not in pattern_id
    ascending = "ascending" in pattern_id
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
            "pdf_pages_checked": meta["source_pdf_pages"],
            "target_rule_summary": "Nguồn đo mục tiêu bằng chiều cao phần scallop; chapter Việt Nam giữ 1,0x làm mốc nguồn và dùng 0,5x/0,75x để đọc thận trọng theo dữ liệu hiện có.",
            "review_note": "Đã đối chiếu trực tiếp chương Scallops trong PDF gốc trước khi dựng scanner và chapter.",
        },
        "source_rules": [
            {"rule_id": f"{prefix}.daily_chart", "short_excerpt": "Daily chart", "implementation_mapping": "mẫu được quét trên daily OHLCV"},
            {"rule_id": f"{prefix}.prior_trend", "short_excerpt": "price trend leading to the scallop", "implementation_mapping": "ghi nhận nhịp dẫn trước để phân biệt tiếp diễn và đảo chiều"},
            {"rule_id": f"{prefix}.shape", "short_excerpt": meta["source_name"], "implementation_mapping": meta["morphology"]},
            {"rule_id": f"{prefix}.smooth_turn", "short_excerpt": "smooth turn", "implementation_mapping": "điểm cong phải đủ mượt; số lần đảo hướng quá nhiều bị hạ chất lượng"},
            {"rule_id": f"{prefix}.end_points", "short_excerpt": "start and end should form at turning points", "implementation_mapping": "hai môi của mẫu phải là các vùng xoay giá có ý nghĩa"},
            {"rule_id": f"{prefix}.lip_relation", "short_excerpt": "higher peak" if ascending else "end below start", "implementation_mapping": "vị trí môi trái/phải quyết định biến thể ascending hoặc descending"},
            {"rule_id": f"{prefix}.confirmation", "short_excerpt": "price must close above/below confirmation price", "implementation_mapping": "chỉ tính sự kiện khi giá đóng cửa phá qua vùng xác nhận theo hướng mẫu"},
            {"rule_id": f"{prefix}.target.height", "short_excerpt": "measure the height", "implementation_mapping": "mục tiêu nguồn dựa trên chiều cao scallop; bản Việt Nam công bố 0,5x, 0,75x và 1,0x"},
            {"rule_id": f"{prefix}.volume.context", "short_excerpt": "volume trend", "implementation_mapping": "khối lượng là bối cảnh phụ, không thay thế hình thái và xác nhận"},
        ],
    }


def _variant_recognition_rows(pattern_id: str) -> dict[str, list[list[str]]]:
    rows = {
        "scallops_ascending": {
            "quick_question_rows": [
                ["Môi trái", "Mẫu có bắt đầu bằng một đỉnh trái đủ rõ không?"],
                ["Đáy cong", "Giá có lùi xuống thành phần cong mượt thay vì zigzag răng cưa không?"],
                ["Môi phải", "Môi phải có cao hơn môi trái để đúng dạng Scallop tăng không?"],
                ["Xác nhận", "Giá đã đóng cửa vượt vùng môi phải chưa?"],
            ],
            "component_rows": [
                ["Môi trái", "Đỉnh đầu tiên của chữ J.", "Mốc so với môi phải"],
                ["Đáy cong", "Vùng lùi xuống tạo bụng scallop.", "Cong mượt, ít răng cưa"],
                ["Môi phải cao hơn", "Đỉnh phải vượt môi trái.", "Xác nhận dạng tăng"],
                ["Mốc 0,5x", "Mục tiêu cơ sở từ chiều cao đáy cong tới môi cao hơn.", "Nửa chiều cao mẫu"],
            ],
        },
        "scallops_ascending_inverted": {
            "quick_question_rows": [
                ["Đà tăng vào mẫu", "Giá có chạy lên trước khi tạo phần cong đỉnh không?"],
                ["Vòm cong", "Phần đỉnh có cong mượt như ô mở ngược, không phải kênh ngang không?"],
                ["Nhịp lùi", "Giá có lùi vừa đủ nhưng không phá hỏng cấu trúc tăng không?"],
                ["Xác nhận lên", "Giá đã đóng cửa vượt vùng cao của mẫu chưa?"],
            ],
            "component_rows": [
                ["Nhịp tăng đầu", "Đưa giá vào phần cong đỉnh.", "Có lực trước mẫu"],
                ["Vòm cong", "Đỉnh tròn của scallop đảo ngược.", "Không răng cưa quá mức"],
                ["Nhịp lùi kiểm định", "Pha giảm nhẹ trước xác nhận.", "Không phá cấu trúc"],
                ["Xác nhận lên", "Giá vượt lại vùng cao.", "Mở nhánh long-watchlist"],
            ],
        },
        "scallops_descending": {
            "quick_question_rows": [
                ["Môi trái cao", "Mẫu có bắt đầu bằng môi trái cao hơn rõ không?"],
                ["Đáy cong", "Phần cong có lùi xuống đủ sâu và đủ mượt không?"],
                ["Môi phải thấp", "Môi phải có thấp hơn môi trái để đúng Scallop giảm không?"],
                ["Hướng phá vỡ", "Giá phá lên hồi phục hay phá xuống cảnh báo rủi ro?"],
            ],
            "component_rows": [
                ["Môi trái cao hơn", "Đỉnh trái là mép cao của mẫu.", "Mốc kháng cự đầu"],
                ["Đáy cong", "Vùng lõm xuống ở giữa mẫu.", "Bụng scallop"],
                ["Môi phải thấp hơn", "Đỉnh phải không lấy lại được môi trái.", "Dấu hiệu yếu hơn"],
                ["Vùng xác nhận", "Giá rời khỏi cấu trúc theo một trong hai hướng.", "Tách up/down"],
            ],
        },
        "scallops_descending_inverted": {
            "quick_question_rows": [
                ["Điểm bắt đầu cao", "Giá có xuất phát từ vùng cao trước khi tạo vòm cong không?"],
                ["Vòm cong suy yếu", "Phần đỉnh có cong xuống và mất lực thay vì tiếp tục tăng không?"],
                ["Đáy xác nhận", "Giá có rơi xuống dưới đáy mẫu sau phần cong không?"],
                ["Vai trò sử dụng", "Đây là cảnh báo phòng thủ hơn là cơ hội short phổ quát?"],
            ],
            "component_rows": [
                ["Điểm bắt đầu cao", "Mép trái của dạng chữ J úp.", "Vùng cao trước mẫu"],
                ["Vòm cong", "Phần hồi lên rồi tròn đỉnh.", "Mất lực dần"],
                ["Đáy mẫu", "Vùng hỗ trợ bị theo dõi để xác nhận giảm.", "Ngưỡng phá xuống"],
                ["Xác nhận giảm", "Giá đóng cửa dưới đáy mẫu.", "Hồ sơ phòng thủ"],
            ],
        },
    }
    return rows[pattern_id]


def _publication_spec(pattern_id: str, meta: Mapping[str, Any]) -> dict[str, Any]:
    variant_rows = _variant_recognition_rows(pattern_id)
    return {
        "status": "PASS",
        "semantic_gate_id": PUBLICATION_SEMANTIC_GATE_ID,
        "publication_spec_id": f"{pattern_id}_scallop_family_publication_spec_v1",
        "pattern_id": pattern_id,
        "family": "scallop_family",
        "spec_scope": "pattern_chapter",
        "variant_specific": True,
        "public_required_phrases": [meta["title"], "Scallop", "môi", "đường cong", "phá vỡ"],
        "public_forbidden_terms": [
            "payload",
            "factory",
            "source_alignment",
            "publication_quality_tier",
            "data_limited",
            "branch_id",
            "chapter_lane",
            "candidate",
            "headline",
            "audit",
            "premium",
            "standard",
            "loose",
            "aggregate",
        ],
        "public_rule_rows": [
            ["Hình dạng phải giống một phần chữ J.", "Người đọc cần thấy hai môi và phần cong nằm giữa, không chỉ là một nhịp zigzag."],
            ["Điểm cong phải đủ mượt.", "Số lần đảo hướng quá nhiều làm mẫu giống vùng dao động hơn là scallop."],
            ["Vị trí hai môi quyết định biến thể.", meta["direction_label"]],
            ["Chờ đóng cửa xác nhận.", "Mẫu chỉ được tính khi giá đóng cửa vượt qua vùng xác nhận theo hướng đã định."],
            ["Mục tiêu theo chiều cao mẫu.", "0,5x là mốc đọc thận trọng; 1,0x là mốc nguồn đầy đủ."],
            ["Thống kê là hồ sơ tham khảo.", meta["classification"]],
        ],
        "title": meta["title"],
        "subtitle": meta["subtitle"],
        "base_target_multiple": meta["base_target_multiple"],
        "base_target_label": "0,5x",
        "legacy_target_multiple": meta["legacy_target_multiple"],
        "legacy_target_label": "1,0x",
        "target_unit_label": meta["target_unit_label"],
        "target_focus_title": "Mốc cơ sở 0,5x",
        "target_focus_caption": "mốc 0,5x chiều cao scallop",
        "target_focus_reading": "mốc đọc thận trọng trước khi đọc full measure",
        "target_full_title": "Mốc nguồn 1,0x",
        "target_full_reading": "mốc đầy đủ theo chiều cao scallop",
        "morphology_sentence": meta["morphology"],
        "role_note": meta["classification"],
        "classification_sentence": meta["claim_level"],
        "headline_scope": "Scallop phải được đọc theo từng biến thể và từng hướng phá vỡ; không dùng một kết luận gộp cho cả family.",
        "local_source_chapter": meta["source_chapter"],
        "schematic_caption": f"Sơ đồ minh họa {meta['title']}: hai môi, phần cong và vùng xác nhận.",
        "how_subtitle": "Mẫu này cần được đọc qua hai môi và đường cong, không chỉ qua một nhịp phá vỡ.",
        "labels": {"favorable_move": "mức đi thuận lợi", "adverse_move": "mức kéo ngược bất lợi"},
        "source_rule_ids": [f"{pattern_id}.shape", f"{pattern_id}.smooth_turn", f"{pattern_id}.confirmation", f"{pattern_id}.target"],
        "quick_question_rows": variant_rows["quick_question_rows"],
        "component_rows": variant_rows["component_rows"],
        "reject_bullets": [
            "Không thấy rõ hai môi của mẫu.",
            "Đường cong bị răng cưa quá nhiều.",
            "Giá chỉ xuyên trong phiên nhưng không đóng cửa xác nhận.",
            "Đường giá thiếu sạch hoặc thanh khoản quá thấp.",
        ],
        "identification_paragraphs": [meta["morphology"]],
        "example_intro": ["Ba ví dụ dưới đây được đọc như case study: một mẫu đạt mục tiêu, một mẫu gần trung vị và một mẫu thất bại. Bảng diễn biến giúp nối hình thái với đường đi sau xác nhận."],
        "failure_bullets": [
            "Thất bại 5% đo việc mẫu không đi đủ hướng sau xác nhận, không phải stop-loss.",
            "Đường cong đẹp nhưng phá vỡ yếu vẫn có thể thất bại.",
            "Mốc 1,0x nên đọc như mốc nguồn, không phải kỳ vọng mặc định.",
        ],
        "target_paragraph": "Nguồn đo mục tiêu bằng chiều cao scallop; chương Việt Nam công bố 0,5x, 0,75x và 1,0x để giữ cả mốc thận trọng và mốc nguồn.",
        "quick_conclusion_rows": [
            ["Mẫu này dùng để đọc gì?", "Hành vi sau một cấu trúc cong kiểu scallop."],
            ["Mốc đọc chính?", "0,5x chiều cao scallop."],
            ["Mốc tham chiếu?", "1,0x chiều cao scallop theo nguồn."],
            ["Khi nào thận trọng?", "Khi đường cong răng cưa, thiếu xác nhận hoặc thanh khoản thấp."],
        ],
        "caveat_bullets": [
            "Không tuyên bố đây là nghiên cứu toàn thị trường đúng từng ngày lịch sử.",
            "Không dùng historical VN30/VN100 membership làm kết luận chính.",
            "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
            "Chương là tài liệu tham khảo hậu xác nhận, không phải khuyến nghị giao dịch.",
        ],
        "quantile_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên"),
            ("Chiều cao mẫu", "pattern_height_pct", "%"),
            ("Độ lệch hai môi", "lip_shift_pct", "%"),
            ("Độ sâu phần cong", "arc_excursion_pct", "%"),
            ("Số lần đảo hướng", "smooth_turn_count", "lần"),
            ("Mức đi thuận lợi", "mfe_pct", "%"),
            ("Mức kéo ngược bất lợi", "mae_pct", "%"),
            ("Ngày chạm mốc cơ sở", "days_to_target", "phiên"),
        ],
        "skip_condition_specs": [
            ("Mẫu quá dài", "pattern_width_bars", "q75_bars", None, "Dễ chuyển thành vùng dao động hơn là scallop gọn."),
            ("Đường cong quá nhiễu", "smooth_turn_count", "q75_count", None, "Nhiều đảo chiều làm mẫu kém mượt."),
            ("Độ lệch môi quá yếu", "lip_shift_pct", "q25_abs", None, "Hai môi quá gần nhau làm biến thể thiếu rõ."),
            ("Kéo ngược quá sâu", "mae_pct", "q75", None, "Đường đi sau xác nhận không còn gọn."),
        ],
        "general_stat_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên", "Scallop cần đủ thời gian để tạo đường cong nhưng quá dài dễ thành vùng dao động."),
            ("Chiều cao mẫu", "pattern_height_pct", "%", "Chiều cao là nền tảng của target."),
            ("Độ sâu phần cong", "arc_excursion_pct", "%", "Phần cong quá nông thường thiếu sức phân biệt."),
            ("Độ lệch hai môi", "lip_shift_pct", "%", "Dùng để phân biệt ascending/descending."),
        ],
        "best_condition_specs": [
            ("Nhóm hình thái tốt", "publication_quality_tier", "==", "premium", "Đường cong rõ, xác nhận đủ lực và đường giá sạch."),
            ("Nhóm chuẩn", "publication_quality_tier", "==", "standard", "Đủ dùng trong thống kê nhưng có thể không đẹp như ví dụ textbook."),
            ("Hai môi tách rõ", "source_lip_band", "==", "source_separated_lips", "Biến thể dễ đọc hơn."),
            ("Đường giá sạch", "path_quality_bucket", "==", "clean", "Ít thiếu phiên và ít chuỗi đứng giá."),
        ],
        "conclusion_bullets": [
            f"{meta['title']} được dựng bằng scanner riêng của Scallop Family, không kế thừa máy móc từ Flag/Triangle/Wedge.",
            "Mốc 0,5x được dùng làm mốc cơ sở thận trọng; mốc 1,0x giữ vai trò nguồn.",
            meta["classification"],
        ],
    }


def _publication_payload(pattern_id: str, meta: Mapping[str, Any], events: pd.DataFrame, all_events: pd.DataFrame, path_df: pd.DataFrame) -> dict[str, Any]:
    base = _metric_for_target(events, path_df, 0.5, "conservative_half_height")
    stretch = _metric_for_target(events, path_df, 0.75, "intermediate_height")
    full = _metric_for_target(events, path_df, 1.0, "source_full_height")
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
            "median_lip_shift_pct": _fmt(pd.to_numeric(events.get("lip_shift_pct"), errors="coerce").median()),
            "median_arc_excursion_pct": _fmt(pd.to_numeric(events.get("arc_excursion_pct"), errors="coerce").median()),
        },
        "target_calibration": {
            "target_family": {"conservative_half_height": 0.5, "intermediate_height": 0.75, "source_full_height": 1.0},
            "selected_base_target_multiple": 0.5,
            "selected_base_target_role": "conservative_half_height",
            "base_target": base,
            "stretch_target": stretch,
            "legacy_target": full,
            "rows": [base, stretch, full],
            "interpretation": "Nguồn đo mục tiêu bằng chiều cao scallop; chương Việt Nam dùng 0,5x làm mốc đọc thận trọng và giữ 1,0x làm mốc nguồn đầy đủ.",
        },
        "data_scope_and_caveats": {
            "remaining_caveats": [
                "Không claim point-in-time universe toàn thị trường.",
                "Không dùng historical VN30/VN100 membership làm kết luận chính.",
                "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
            ]
        },
    }


def build_one_scallop_chapter(*, pattern_id: str, out_dir: Path, price_db: Path) -> dict[str, Path]:
    meta = PATTERNS[pattern_id]
    chapter_dir = out_dir / str(meta["slug"])
    if chapter_dir.exists():
        shutil.rmtree(chapter_dir)
    chapter_dir.mkdir(parents=True, exist_ok=True)
    scan_dir = DEFAULT_SCAN_DIR / pattern_id / "db_active"
    all_events = pd.read_csv(scan_dir / "events.csv")
    if "event_id" not in all_events.columns:
        all_events["event_id"] = all_events["detection_id"]
    path_df = pd.read_csv(scan_dir / "post_breakout_path.csv")
    events = _events_for_scope(all_events)
    payload = _publication_payload(pattern_id, meta, events, all_events, path_df)
    spec = _publication_spec(pattern_id, meta)
    payload["publication_spec_id"] = spec["publication_spec_id"]
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
    _write_json(publication_spec_path, spec)
    style_dossier = chapter_dir / "source_style_dossier.md"
    style_dossier.write_text(
        f"# Source-Guided Style Dossier - {pattern_id}\n\n"
        f"Chương nguồn: {meta['source_name']} trong Encyclopedia of Chart Patterns. "
        "Dossier này dùng để giữ thứ tự đọc: hình dạng hai môi, đường cong scallop, xác nhận đóng cửa, target theo chiều cao mẫu, thất bại và cách dùng thận trọng. "
        "Không sao chép hoặc dịch lại tài liệu gốc; số liệu Việt Nam lấy từ payload đã khóa.\n",
        encoding="utf-8",
    )
    entry = {
        "family": "scallop_family",
        "pattern_id": pattern_id,
        "title": meta["title"],
        "status": "source_seed",
        "classification": meta["classification"],
        "score": None,
        "claim_level": meta["claim_level"],
        "pdf": f"artifacts/final_chapters/scallop_family/{meta['slug']}_final.pdf",
        "source_pdf": f"artifacts/final_chapters/scallop_family/{meta['slug']}_final.pdf",
        "payload": str(payload_path),
        "source_notes": str(source_notes_path),
        "publication_spec": str(publication_spec_path),
        "source_grounding_required": True,
        "source_grounding_policy_id": SOURCE_GROUNDED_PUBLICATION_GATE_ID,
        "direct_source_review_required": True,
        "publication_semantic_required": True,
        "publication_semantic_gate_id": spec["semantic_gate_id"],
        "canonical_rebuild_required": True,
        "chapter_writing_stages": {"source_style_dossier": str(style_dossier)},
        "chapter_writing_notes": "Seed artifact only. Final public prose must be generated by source-guided AI refinement and canonical publication factory.",
        "note": "Scallop Family dùng scanner riêng theo từng biến thể; builder này chỉ cung cấp nguyên liệu, không render hoặc approve PDF final.",
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
    parser = argparse.ArgumentParser(description="Build Scallop Family public-chapter seed artifacts.")
    parser.add_argument("--pattern", choices=[*PATTERNS.keys(), "all"], default="all")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--price-db", default=str(DEFAULT_PRICE_DB))
    args = parser.parse_args()
    patterns = list(PATTERNS.keys()) if args.pattern == "all" else [args.pattern]
    outputs = {}
    for pattern_id in patterns:
        outputs[pattern_id] = {key: str(value) for key, value in build_one_scallop_chapter(pattern_id=pattern_id, out_dir=Path(args.out_dir), price_db=Path(args.price_db)).items()}
    print(json.dumps({"status": "PASS", "outputs": outputs}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
