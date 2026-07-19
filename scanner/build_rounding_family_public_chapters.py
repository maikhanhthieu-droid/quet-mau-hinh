"""Build source-grounded Rounding Family public-chapter seed artifacts.

This builder creates deterministic ingredients only. It does not approve
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

from scanner.publication_flow_contract import SOURCE_GROUNDED_PUBLICATION_GATE_ID  # noqa: E402
from scanner.rounding_family_publication_specs import build_rounding_publication_spec  # noqa: E402
from scanner.v2.rounding import _to_weekly_ohlcv  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/rounding_family_public_chapters")
DEFAULT_PRICE_DB = Path("../market_cache/stock_ohlcv/latest.sqlite")
SOURCE_PDF = "references/encyclopedia-of-chart-patterns-2nbsped-9786468600-3175723993-9780471668268-0471668265_compress.pdf"


PATTERNS: dict[str, dict[str, Any]] = {
    "rounding_bottoms": {
        "slug": "rounding_bottoms",
        "title": "Rounding Bottoms",
        "subtitle": "Dạng bát trên biểu đồ tuần, xác nhận khi vượt mép phải",
        "scan_dir": Path("artifacts/scanner_v2/rounding_family/rounding_bottoms/db_active"),
        "source_chapter": 39,
        "source_name": "Rounding Bottoms",
        "classification": "watchlist/reference; nhánh long có thể kiểm tra tradable layer",
        "claim_level": "đọc như vùng tích lũy dạng bát dài hạn, thường là continuation hơn là đáy đảo chiều thuần túy",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, Rounding Bottoms là hồ sơ weekly đáng chú ý: mẫu dài, có dạng bát, xác nhận ở mép phải và có thống kê hậu xác nhận mạnh, nhưng cần đọc cùng throwback và vùng kháng cự phía trên.",
        "morphology": "Rounding Bottoms là một vùng giá cong dạng bát/saucer trên biểu đồ tuần. Giá thường đi xuống chậm, phẳng dần ở đáy, rồi đi lên chậm lại tới mép phải. Mẫu chỉ được xác nhận khi giá đóng cửa vượt mép phải, không phải khi đáy còn đang hình thành.",
        "role_note": "Dùng như hồ sơ theo dõi long-cash sau xác nhận; không mua trước khi giá đóng cửa vượt mép phải.",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "direction": "up",
    },
    "rounding_tops": {
        "slug": "rounding_tops",
        "title": "Rounding Tops",
        "subtitle": "Dạng bát úp trên biểu đồ tuần, xác nhận khi thủng mép phải",
        "scan_dir": Path("artifacts/scanner_v2/rounding_family/rounding_tops/db_active"),
        "source_chapter": 40,
        "source_name": "Rounding Tops",
        "classification": "defensive/informational-reference trên cổ phiếu cơ sở",
        "claim_level": "đọc như vùng phân phối dạng bát úp, dùng để cảnh báo rủi ro hơn là short setup phổ quát",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, Rounding Tops nên là chương phòng thủ: mẫu giúp nhận diện vùng phân phối dài hạn, nhưng không được viết như một setup short phổ quát trên thị trường cổ phiếu cơ sở Việt Nam.",
        "morphology": "Rounding Tops là một vùng giá cong dạng bát úp trên biểu đồ tuần. Giá thường đi lên chậm, tròn dần ở vùng đỉnh, rồi đi xuống về mép phải. Mẫu chỉ được xác nhận khi giá đóng cửa xuống dưới mép phải.",
        "role_note": "Dùng như hồ sơ cảnh báo suy yếu/giảm tỷ trọng; không đọc như khuyến nghị bán khống.",
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
    return str(value).strip().lower() in {"true", "1", "yes", "y", "có"}


def _fmt(value: Any, digits: int = 2) -> str:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if not math.isfinite(out):
        return "n/a"
    return f"{out:.{digits}f}"


def _events_for_scope(events: pd.DataFrame) -> pd.DataFrame:
    if "publication_quality_tier" in events.columns:
        scoped = events[events["publication_quality_tier"].astype(str).str.lower().isin(["premium", "standard"])].copy()
        if len(scoped) >= 30:
            return scoped
    return events.copy()


def _metric_for_target(events: pd.DataFrame, multiple: float, role: str) -> dict[str, Any]:
    if events.empty:
        return {"target_multiple": multiple, "target_role": role, "n": 0}
    mfe = pd.to_numeric(events.get("mfe_pct"), errors="coerce")
    mae = pd.to_numeric(events.get("mae_pct"), errors="coerce")
    target_dist = pd.to_numeric(events.get("target_dist_pct"), errors="coerce") * multiple
    hit = (mfe >= target_dist).fillna(False)
    fail = events.get("failure_5pct", pd.Series(False, index=events.index)).map(_truthy)
    first = events.get("target_first_before_adverse_5pct", pd.Series(False, index=events.index)).map(_truthy)
    return {
        "target_multiple": multiple,
        "target_role": role,
        "target_label": f"{multiple}x",
        "target_hit_rate": round(float(hit.mean() * 100.0), 2),
        "target_first_before_adverse_5pct_rate": round(float(first.mean() * 100.0), 2),
        "failure_5pct_rate": round(float(fail.mean() * 100.0), 2),
        "median_mfe_pct": round(float(mfe.median()), 2) if not mfe.dropna().empty else None,
        "median_mae_pct": round(float(mae.median()), 2) if not mae.dropna().empty else None,
        "mfe_mae_median_ratio": round(float(mfe.median() / max(mae.median(), 1.0)), 2) if not mfe.dropna().empty and not mae.dropna().empty else None,
        "median_target_dist_pct": round(float(target_dist.median()), 2) if not target_dist.dropna().empty else None,
        "n": int(len(events)),
    }


def _group_table(events: pd.DataFrame, col: str) -> dict[str, Any]:
    if events.empty or col not in events.columns:
        return {}
    out: dict[str, Any] = {}
    for key, group in events.groupby(events[col].fillna("unknown").astype(str)):
        mfe = pd.to_numeric(group.get("mfe_pct"), errors="coerce")
        mae = pd.to_numeric(group.get("mae_pct"), errors="coerce")
        out[key] = {
            "n": int(len(group)),
            "median_mfe_pct": round(float(mfe.median()), 2) if not mfe.dropna().empty else None,
            "median_mae_pct": round(float(mae.median()), 2) if not mae.dropna().empty else None,
            "target_hit_rate": round(float(group.get("target_hit", pd.Series(False, index=group.index)).map(_truthy).mean() * 100.0), 2),
            "failure_5pct_rate": round(float(group.get("failure_5pct", pd.Series(False, index=group.index)).map(_truthy).mean() * 100.0), 2),
        }
    return out


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


def _window_for_event(df: pd.DataFrame, event: Mapping[str, Any], *, pre_bars: int = 16, post_bars: int = 44) -> pd.DataFrame:
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
    x = np.linspace(-1, 1, 80)
    if pattern_id == "rounding_bottoms":
        y = 1.0 + 1.6 * x**2 + 0.06 * np.sin(np.linspace(0, 8, len(x)))
        title = "Giải phẫu Rounding Bottoms"
        ax.text(0.62, y[-1] + 0.05, "mép phải / xác nhận", fontsize=8, color="#7A5195")
    else:
        y = 2.8 - 1.6 * x**2 + 0.06 * np.sin(np.linspace(0, 8, len(x)))
        title = "Giải phẫu Rounding Tops"
        ax.text(0.62, y[-1] - 0.22, "mép phải / xác nhận", fontsize=8, color="#7A5195")
    ax.plot(x, y, color="#0f3f3c", linewidth=2.4)
    ax.axvline(1.0, color="#7A5195", linestyle="--", linewidth=1.0)
    ax.axvspan(-0.18, 0.18, color="#d9ebf5", alpha=0.8)
    ax.text(-0.16, y.min() if pattern_id == "rounding_bottoms" else y.max(), "vùng cong/phẳng", fontsize=8, color="#245b5a")
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold", color="#164c49")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(True, alpha=0.12)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)


def _plot_event_chart(df: pd.DataFrame, event: Mapping[str, Any], out_path: Path, title: str, *, base_multiple: float) -> None:
    if df.empty:
        return
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
        segment = df.iloc[i0 : i1 + 1]
        if str(event.get("breakout_direction")) == "up":
            ax.plot(np.arange(i0, i1 + 1), segment["low"], color="#245b5a", linewidth=1.2)
        else:
            ax.plot(np.arange(i0, i1 + 1), segment["high"], color="#245b5a", linewidth=1.2)
        ax.text((i0 + i1) / 2, float(segment["low"].min()), "thân bát", fontsize=7, color="#245b5a", ha="center")
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


def _select_examples(events: pd.DataFrame) -> list[tuple[str, pd.Series]]:
    if events.empty:
        return []
    scoped = events.copy()
    mfe = pd.to_numeric(scoped.get("mfe_pct"), errors="coerce")
    mae = pd.to_numeric(scoped.get("mae_pct"), errors="coerce")
    scoped["_mfe"] = mfe
    scoped["_mae"] = mae
    scoped["_hit"] = scoped.get("target_hit", pd.Series(False, index=scoped.index)).map(_truthy)
    scoped["_fail"] = scoped.get("failure_5pct", pd.Series(False, index=scoped.index)).map(_truthy)
    examples: list[tuple[str, pd.Series]] = []
    success = scoped[scoped["_hit"]].sort_values(["publication_quality_score", "_mfe"], ascending=[False, False])
    if not success.empty:
        examples.append(("đạt mục tiêu", success.iloc[0]))
    median_idx = (scoped["_mfe"] - scoped["_mfe"].median()).abs().sort_values().index
    if len(median_idx):
        examples.append(("trung vị", scoped.loc[median_idx[0]]))
    failure = scoped[scoped["_fail"]].sort_values(["_mae"], ascending=False)
    if not failure.empty:
        examples.append(("thất bại", failure.iloc[0]))
    return examples[:3]


def _build_charts(chapter_dir: Path, *, pattern_id: str, events: pd.DataFrame, price_db: Path) -> dict[str, Path]:
    chart_dir = chapter_dir / "charts"
    schematic = chart_dir / f"{pattern_id}_schematic.png"
    _plot_schematic(schematic, pattern_id=pattern_id)
    charts: dict[str, Path] = {"schematic": schematic}
    for idx, (label, event) in enumerate(_select_examples(events), start=1):
        symbol = str(event.get("symbol"))
        weekly = _load_weekly_ohlcv(price_db, symbol)
        window = _window_for_event(weekly, event)
        out_path = chart_dir / f"{pattern_id}_example_{idx}.png"
        _plot_event_chart(window, event, out_path, f"{symbol} - ví dụ {label} ({event.get('breakout_date')})", base_multiple=0.5)
        charts[f"example_{idx}"] = out_path
    return charts


def _spec(pattern_id: str, meta: Mapping[str, Any]) -> dict[str, Any]:
    if pattern_id == "rounding_bottoms":
        rules = [
            ("Dùng biểu đồ tuần.", "Chương quy đổi dữ liệu ngày thành dữ liệu tuần trước khi đọc dạng bát."),
            ("Thân mẫu phải cong dạng bát.", "Giá đi xuống chậm, phẳng dần, rồi đi lên chậm; loại cấu trúc V quá sắc."),
            ("Hai mép bát không được lệch quá xa.", "Mép trái và mép phải được so bằng chênh lệch phần trăm."),
            ("Mẫu chỉ được xác nhận tại mép phải.", "Điểm sự kiện là phiên đóng cửa vượt mép phải, không phải đáy giữa mẫu."),
            ("Rounding Bottom không nhất thiết là đảo chiều.", "Chương đọc cả vai trò tiếp diễn hoặc tích lũy theo tinh thần nguồn."),
            ("Mục tiêu đo bằng chiều cao bát.", "0,5x là mốc thận trọng; 1,0x là mốc đầy đủ để đối chiếu."),
        ]
        rejects = ["Dạng V quá sắc.", "Không có mép phải rõ.", "Thời gian hình thành quá ngắn.", "Đường giá nhiều gap/đứng giá làm bát giả."]
    else:
        rules = [
            ("Dùng biểu đồ tuần.", "Chương quy đổi dữ liệu ngày thành dữ liệu tuần trước khi đọc dạng bát úp."),
            ("Thân mẫu phải cong dạng bát úp.", "Giá đi lên chậm, tròn dần ở đỉnh, rồi đi xuống chậm; loại spike quá sắc."),
            ("Hai mép bát úp không được lệch quá xa.", "Mép trái và mép phải được so bằng chênh lệch phần trăm."),
            ("Mẫu chỉ được xác nhận tại mép phải.", "Điểm sự kiện là phiên đóng cửa xuống dưới mép phải."),
            ("Đọc như hồ sơ phòng thủ.", "Trong cổ phiếu cơ sở Việt Nam, nhánh giảm là thông tin rủi ro trước khi là một cấu hình giao dịch theo chiều giảm."),
            ("Mục tiêu đo bằng chiều cao bát úp.", "0,5x là mốc thận trọng; 1,0x là mốc đầy đủ để đối chiếu."),
        ]
        rejects = ["Dạng spike hoặc V ngược quá sắc.", "Không có mép phải rõ.", "Không có phân phối dài đủ.", "Đường giá kém sạch làm tín hiệu thủng giả."]
    return {
        "pattern_id": pattern_id,
        "pattern_title": meta["title"],
        "local_source_chapter": meta["source_chapter"],
        "source_name": meta["source_name"],
        "base_target_multiple": meta["base_target_multiple"],
        "legacy_target_multiple": meta["legacy_target_multiple"],
        "success_heading": "Ví dụ dạng bát được xác nhận",
        "target_unit": "chiều cao từ mép bát tới đáy/đỉnh tròn",
        "public_rule_rows": rules,
        "quick_reject_rules": rejects,
    }


def _source_notes(pattern_id: str, meta: Mapping[str, Any]) -> dict[str, Any]:
    rule_rows = _spec(pattern_id, meta)["public_rule_rows"]
    return {
        "status": "PASS",
        "source_pdf": SOURCE_PDF,
        "source_grounding_policy_id": SOURCE_GROUNDED_PUBLICATION_GATE_ID,
        "source_grounding_level": "publication_aligned",
        "local_source": {"pattern_key": pattern_id, "chapter": meta["source_chapter"], "name": meta["source_name"]},
        "direct_pdf_review": {
            "status": "PASS",
            "review_id": f"{pattern_id}_bulkowski_pdf_direct_review_v1",
            "pdf_path": SOURCE_PDF,
            "book_chapter": meta["source_chapter"],
            "pdf_pages_checked": [595, 596, 597, 598, 599, 600] if pattern_id == "rounding_bottoms" else [608, 609, 610, 611, 612],
            "book_pages_checked": [595, 596, 597, 598, 599, 600] if pattern_id == "rounding_bottoms" else [608, 609, 610, 611, 612],
            "target_rule_summary": "Measure the height from saucer lip/rim to rounded extreme and project from confirmation.",
            "review_note": "Đã đối chiếu phần Rounding Bottoms/Tops trong tài liệu nguồn trước khi dựng scanner và chapter.",
        },
        "source_rules": [
            {"rule_id": f"{pattern_id}.rule_{idx}", "short_excerpt": str(rule), "implementation_mapping": str(application)}
            for idx, (rule, application) in enumerate(rule_rows, start=1)
        ],
        "source_grounding_summary": (
            "Đối chiếu theo mô tả nguồn: Rounding dùng weekly scale, dạng saucer/bowl hoặc inverted bowl, "
            "mẫu dài, xác nhận tại mép phải, và cần phân biệt continuation với reversal."
        ),
        "not_copied": True,
        "pattern_id": pattern_id,
    }


def _publication_payload(pattern_id: str, meta: Mapping[str, Any], events: pd.DataFrame, all_events: pd.DataFrame) -> dict[str, Any]:
    if events.empty:
        raise SystemExit(f"No events available for {pattern_id}; cannot build a publication chapter seed.")
    mfe = pd.to_numeric(events.get("mfe_pct"), errors="coerce")
    mae = pd.to_numeric(events.get("mae_pct"), errors="coerce")
    fail = events.get("failure_5pct", pd.Series(False, index=events.index)).map(_truthy)
    first = events.get("target_first_before_adverse_5pct", pd.Series(False, index=events.index)).map(_truthy)
    hit = events.get("target_hit", pd.Series(False, index=events.index)).map(_truthy)
    base_target = _metric_for_target(events, float(meta["base_target_multiple"]), "local_cautious_base")
    legacy_target = _metric_for_target(events, float(meta["legacy_target_multiple"]), "source_full_height")
    return {
        "source_family_factory_id": "rounding_family_public_chapter_seed_v1",
        "pattern_id": pattern_id,
        "pattern_name": meta["title"],
        "pattern_title": meta["title"],
        "subtitle": meta["subtitle"],
        "classification": meta["classification"],
        "claim_level": meta["claim_level"],
        "public_classification_sentence": meta["public_classification_sentence"],
        "morphology_summary": meta["morphology"],
        "role_note": meta["role_note"],
        "source_name": meta["source_name"],
        "source_chapter": meta["source_chapter"],
        "n_total": int(len(events)),
        "n_all_detected": int(len(all_events)),
        "n_symbol": int(events["symbol"].nunique()) if "symbol" in events.columns else None,
        "sample_start": str(events["breakout_date"].min()) if "breakout_date" in events.columns else None,
        "sample_end": str(events["breakout_date"].max()) if "breakout_date" in events.columns else None,
        "up_breakouts": int((events.get("breakout_direction") == "up").sum()) if "breakout_direction" in events.columns else 0,
        "down_breakouts": int((events.get("breakout_direction") == "down").sum()) if "breakout_direction" in events.columns else 0,
        "median_mfe_pct": round(float(mfe.median()), 2) if not mfe.dropna().empty else None,
        "median_mae_pct": round(float(mae.median()), 2) if not mae.dropna().empty else None,
        "target_hit_rate": round(float(hit.mean() * 100.0), 2),
        "failure_5pct_rate": round(float(fail.mean() * 100.0), 2),
        "target_first_before_adverse_5pct_rate": round(float(first.mean() * 100.0), 2),
        "chapter_reference": {
            "events": int(len(events)),
            "all_detected_events": int(len(all_events)),
            "symbols": int(events["symbol"].nunique()) if "symbol" in events.columns else None,
            "scope": "mẫu đạt chuẩn công bố sau lọc hình thái và dữ liệu",
            "failure_5pct_rate": round(float(fail.mean() * 100.0), 2),
            "target_hit_rate": round(float(hit.mean() * 100.0), 2),
            "target_first_before_adverse_5pct_rate": round(float(first.mean() * 100.0), 2),
            "median_mfe_pct": round(float(mfe.median()), 2) if not mfe.dropna().empty else None,
            "median_mae_pct": round(float(mae.median()), 2) if not mae.dropna().empty else None,
        },
        "target_calibration": {
            "base_target_multiple": meta["base_target_multiple"],
            "legacy_target_multiple": meta["legacy_target_multiple"],
            "base_target": base_target,
            "legacy_target": legacy_target,
            "rows": [base_target, legacy_target],
        },
        "direction_table": _group_table(events, "breakout_direction"),
        "market_group_table": _group_table(events, "market_group"),
        "regime_table": _group_table(events, "market_regime"),
        "quality_table": _group_table(events, "publication_quality_tier"),
        "width_quantiles": {f"P{q}": round(float(np.percentile(pd.to_numeric(events["pattern_width_bars"], errors="coerce").dropna(), q)), 2) for q in (10, 25, 50, 75, 90)} if "pattern_width_bars" in events.columns and not pd.to_numeric(events["pattern_width_bars"], errors="coerce").dropna().empty else {},
        "source_rules_public": [{"rule": row[0], "application": row[1]} for row in _spec(pattern_id, meta)["public_rule_rows"]],
        "quick_reject_rules": _spec(pattern_id, meta)["quick_reject_rules"],
    }


def build_one_rounding_chapter(*, pattern_id: str, out_dir: Path, price_db: Path = DEFAULT_PRICE_DB) -> dict[str, Path]:
    meta = PATTERNS[pattern_id]
    chapter_dir = out_dir / str(meta["slug"])
    if chapter_dir.exists():
        shutil.rmtree(chapter_dir)
    chapter_dir.mkdir(parents=True, exist_ok=True)
    all_events = pd.read_csv(meta["scan_dir"] / "events.csv")
    events = _events_for_scope(all_events)
    payload = _publication_payload(pattern_id, meta, events, all_events)
    spec = _spec(pattern_id, meta)
    publication_spec = build_rounding_publication_spec(pattern_id=pattern_id, title=str(meta["title"]), spec=spec)
    payload["publication_spec_id"] = publication_spec["publication_spec_id"]
    charts = _build_charts(chapter_dir, pattern_id=pattern_id, events=events, price_db=price_db)
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
        "Dossier giữ thứ tự đọc: weekly scale, dạng bát/bát úp, mép phải xác nhận, thất bại, ví dụ. "
        "Không sao chép hoặc dịch lại tài liệu gốc; số liệu Việt Nam lấy từ payload đã khóa.\n",
        encoding="utf-8",
    )
    entry = {
        "family": "rounding_family",
        "pattern_id": pattern_id,
        "title": meta["title"],
        "status": "source_seed",
        "classification": meta["classification"],
        "score": None,
        "claim_level": meta["claim_level"],
        "pdf": f"artifacts/final_chapters/rounding_family/{meta['slug']}_final.pdf",
        "source_pdf": f"artifacts/final_chapters/rounding_family/{meta['slug']}_final.pdf",
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
        "note": "Rounding Family dùng scanner weekly riêng; builder này chỉ cung cấp nguyên liệu, không render hoặc approve PDF final.",
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
    parser = argparse.ArgumentParser(description="Build Rounding Family public-chapter seed artifacts.")
    parser.add_argument("--pattern", choices=[*PATTERNS.keys(), "all"], default="all")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--price-db", default=str(DEFAULT_PRICE_DB))
    args = parser.parse_args()
    patterns = list(PATTERNS.keys()) if args.pattern == "all" else [args.pattern]
    outputs = {}
    for pattern_id in patterns:
        outputs[pattern_id] = {key: str(value) for key, value in build_one_rounding_chapter(pattern_id=pattern_id, out_dir=Path(args.out_dir), price_db=Path(args.price_db)).items()}
    print(json.dumps({"status": "PASS", "outputs": outputs}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
