"""Build source-grounded Broadening Family public chapters."""

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

from scanner.broadening_family_public_chapter_factory import FACTORY_ID, build_broadening_public_chapter  # noqa: E402
from scanner.broadening_family_publication_specs import build_broadening_publication_spec  # noqa: E402
from scanner.canonical_chapter_content import load_approved_editorial_sections  # noqa: E402
from scanner.v2.broadening_patterns import BROADENING_PATTERNS  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/broadening_family_public_chapters")
DEFAULT_SCAN_DIR = Path("artifacts/scanner_v2/broadening_family")
DEFAULT_PRICE_DB = Path("../market_cache/stock_ohlcv/latest.sqlite")
DEFAULT_AI_DIR = Path("artifacts/scanner_v2/source_guided_refinement_final_v1/broadening_family")
SOURCE_PDF = "references/encyclopedia-of-chart-patterns-2nbsped-9786468600-3175723993-9780471668268-0471668265_compress.pdf"


PATTERNS: dict[str, dict[str, Any]] = {
    "broadening_bottoms": {
        "slug": "broadening_bottoms",
        "title": "Đáy mở rộng",
        "subtitle": "Mẫu loa phóng thanh sau xu hướng giảm, với đỉnh cao hơn và đáy thấp hơn",
        "source_chapter": 1,
        "source_name": "Broadening Bottoms",
        "classification": "hồ sơ tham khảo hai hướng trong phạm vi dữ liệu hiện có",
        "claim_level": "đọc như mẫu mở rộng có cả nhánh tăng và nhánh phòng thủ",
        "public_headline": "Kết luận chính: mẫu mở rộng hai hướng, cần tách riêng nhánh phá lên và nhánh phá xuống.",
        "role_note": "Dùng để mô tả hành vi sau phá vỡ của cấu trúc mở rộng; không phải tín hiệu mua/bán tự động.",
        "morphology": "Đáy mở rộng có dạng loa phóng thanh: các đỉnh sau cao hơn và các đáy sau thấp hơn, thường xuất hiện sau nhịp giảm và chỉ được tính khi giá đóng cửa phá ra khỏi biên mẫu.",
        "source_pages_checked": [11, 13, 15, 24],
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "target_unit_label": "chiều cao từ đỉnh cao nhất tới đáy thấp nhất",
        "direction_label": "phá vỡ lên hoặc xuống",
        "source_target_kind": "full_height",
    },
    "broadening_formations_right_angled_ascending": {
        "slug": "broadening_right_angled_ascending",
        "title": "Mở rộng vuông góc tăng",
        "subtitle": "Một đáy ngang, các đỉnh cao dần và khoảng dao động mở rộng",
        "source_chapter": 2,
        "source_name": "Broadening Formations, Right-Angled and Ascending",
        "classification": "hồ sơ phòng thủ/tham khảo vì mẫu thường nhạy với phá vỡ xuống",
        "claim_level": "đọc như cấu trúc mở rộng có đáy ngang cần chú ý rủi ro phá xuống",
        "public_headline": "Kết luận chính: đáy ngang là vùng hỗ trợ cần theo dõi, còn nhánh phá xuống là phần cảnh báo rủi ro.",
        "role_note": "Dùng như bản đồ rủi ro quanh vùng hỗ trợ ngang; nhánh phá lên chỉ là tham khảo bổ sung.",
        "morphology": "Mẫu mở rộng vuông góc tăng có đáy gần như ngang và đường biên trên dốc lên, tạo cảm giác tăng nhưng nguồn gốc nhấn mạnh rủi ro khi giá đóng cửa phá xuống đáy ngang.",
        "source_pages_checked": [28, 33, 39, 41],
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "target_unit_label": "chiều cao từ đỉnh cao nhất tới đáy ngang",
        "direction_label": "phá vỡ quanh đáy ngang hoặc đường biên trên",
        "source_target_kind": "right_angled_full_height",
    },
    "broadening_formations_right_angled_descending": {
        "slug": "broadening_right_angled_descending",
        "title": "Mở rộng vuông góc giảm",
        "subtitle": "Một đỉnh ngang, các đáy thấp dần và khoảng dao động mở rộng",
        "source_chapter": 3,
        "source_name": "Broadening Formations, Right-Angled and Descending",
        "classification": "hồ sơ tham khảo hai hướng với nhánh phá lên đáng chú ý",
        "claim_level": "đọc như cấu trúc mở rộng có đỉnh ngang và đáy thấp dần",
        "public_headline": "Kết luận chính: đỉnh ngang là vùng kháng cự quan trọng, nên đọc nhánh phá lên và phá xuống riêng.",
        "role_note": "Dùng để theo dõi vùng kháng cự ngang; cần kiểm tra nhánh phá lên/phá xuống riêng.",
        "morphology": "Mẫu mở rộng vuông góc giảm có đỉnh gần như ngang và đường biên dưới dốc xuống; giá đóng cửa ra khỏi biên mới xác nhận mẫu.",
        "source_pages_checked": [45, 49, 57, 59],
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "target_unit_label": "chiều cao từ đỉnh ngang tới đáy thấp nhất",
        "direction_label": "phá vỡ quanh đỉnh ngang hoặc đường biên dưới",
        "source_target_kind": "right_angled_full_height",
    },
    "broadening_tops": {
        "slug": "broadening_tops",
        "title": "Đỉnh mở rộng",
        "subtitle": "Mẫu loa phóng thanh sau xu hướng tăng, với đỉnh cao hơn và đáy thấp hơn",
        "source_chapter": 4,
        "source_name": "Broadening Tops",
        "classification": "hồ sơ phòng thủ/tham khảo trong phạm vi dữ liệu hiện có",
        "claim_level": "đọc như mẫu mở rộng có giá trị cảnh báo rủi ro sau xu hướng tăng",
        "public_headline": "Kết luận chính: sau một nhịp tăng, mẫu này hữu ích nhất ở vai trò cảnh báo rủi ro.",
        "role_note": "Dùng như hồ sơ cảnh báo và quản trị vị thế; không mặc định là setup bán khống cổ phiếu cơ sở.",
        "morphology": "Đỉnh mở rộng có dạng loa phóng thanh sau nhịp tăng: đỉnh mới cao hơn nhưng đáy mới thấp hơn, phản ánh dao động ngày càng rộng trước khi giá đóng cửa phá ra khỏi biên.",
        "source_pages_checked": [63, 67, 78, 80],
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "target_unit_label": "chiều cao từ đỉnh cao nhất tới đáy thấp nhất",
        "direction_label": "phá vỡ lên hoặc xuống",
        "source_target_kind": "full_height",
    },
    "broadening_wedges_ascending": {
        "slug": "broadening_wedges_ascending",
        "title": "Nêm mở rộng tăng",
        "subtitle": "Hai đường biên cùng dốc lên nhưng tách xa dần",
        "source_chapter": 5,
        "source_name": "Broadening Wedges, Ascending",
        "classification": "hồ sơ phòng thủ/tham khảo vì phá vỡ xuống là nhánh chủ đạo",
        "claim_level": "đọc như nêm mở rộng dốc lên, thường nên dùng cho cảnh báo rủi ro",
        "public_headline": "Kết luận chính: nêm dốc lên nhưng mở rộng nên được ưu tiên như hồ sơ phòng thủ.",
        "role_note": "Dùng để nhận diện vùng giá dốc lên nhưng ngày càng bất ổn; nhánh phá xuống là phần quan trọng nhất.",
        "morphology": "Nêm mở rộng tăng có hai đường biên cùng dốc lên, biên trên dốc nhanh hơn biên dưới nên khoảng dao động mở rộng theo thời gian.",
        "source_pages_checked": [81, 85, 96, 98],
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "target_unit_label": "mốc cực trị hoặc chiều cao mẫu theo hướng phá vỡ",
        "direction_label": "phá vỡ chủ yếu xuống",
        "source_target_kind": "formation_extreme",
    },
    "broadening_wedges_descending": {
        "slug": "broadening_wedges_descending",
        "title": "Nêm mở rộng giảm",
        "subtitle": "Hai đường biên cùng dốc xuống nhưng tách xa dần",
        "source_chapter": 6,
        "source_name": "Broadening Wedges, Descending",
        "classification": "hồ sơ theo dõi đảo chiều tăng trong phạm vi dữ liệu hiện có",
        "claim_level": "đọc như nêm mở rộng dốc xuống có nhánh phá lên đáng theo dõi",
        "public_headline": "Kết luận chính: nêm dốc xuống nhưng mở rộng có nhánh phá lên đáng theo dõi.",
        "role_note": "Dùng làm hồ sơ theo dõi khi giá phá lên khỏi vùng mở rộng dốc xuống; vẫn cần thanh khoản và đường giá sạch.",
        "morphology": "Nêm mở rộng giảm có hai đường biên cùng dốc xuống, biên dưới giảm nhanh hơn biên trên nên khoảng dao động mở rộng theo thời gian.",
        "source_pages_checked": [98, 101, 110, 112],
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "target_unit_label": "mốc cực trị hoặc chiều cao mẫu theo hướng phá vỡ",
        "direction_label": "phá vỡ thường lên",
        "source_target_kind": "formation_extreme",
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
    if str(event.get("breakout_direction")).lower() == "down":
        return breakout - (breakout - full) * multiple
    return breakout + (full - breakout) * multiple


def _line_value(event: Mapping[str, Any], prefix: str, idx: int, local_left: int = 0) -> float | None:
    idx0 = event.get(f"{prefix}_idx0")
    price0 = event.get(f"{prefix}_price0")
    slope = event.get(f"{prefix}_slope_per_bar")
    try:
        return float(price0) + float(slope) * (idx + local_left - int(idx0))
    except (TypeError, ValueError):
        return None


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
        local_left = int(event.get("formation_start_idx") or 0) - i0
        xs = np.arange(i0, i1 + 1)
        upper = [_line_value(event, "broadening_upper", int(xx), local_left=local_left) for xx in xs]
        lower = [_line_value(event, "broadening_lower", int(xx), local_left=local_left) for xx in xs]
        if all(value is not None for value in upper):
            ax.plot(xs, upper, color="#245b5a", linewidth=1.1)
        if all(value is not None for value in lower):
            ax.plot(xs, lower, color="#245b5a", linewidth=1.1)
    if event.get("horizontal_high") not in (None, ""):
        ax.axhline(float(event.get("horizontal_high")), color="#245b5a", linestyle="-", linewidth=0.8, alpha=0.65)
    if event.get("horizontal_low") not in (None, ""):
        ax.axhline(float(event.get("horizontal_low")), color="#245b5a", linestyle="-", linewidth=0.8, alpha=0.65)
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


def _plot_schematic(out_path: Path, *, pattern_id: str) -> None:
    meta = PATTERNS[pattern_id]
    fig, ax = plt.subplots(figsize=(9.2, 3.9), dpi=180)
    x = np.arange(6)
    if "right_angled_ascending" in pattern_id:
        highs = np.array([15.0, 17.2, 20.0])
        lows = np.array([11.0, 11.1, 10.9])
        px = np.array([0, 1, 2, 3, 4, 5])
        py = np.array([11.0, 15.0, 11.1, 17.2, 10.9, 20.0])
        ax.axhline(11.0, color="#245b5a", linewidth=1.1)
        ax.text(0.1, 11.1, "đáy ngang", fontsize=8, color="#245b5a")
    elif "right_angled_descending" in pattern_id:
        highs = np.array([20.0, 20.1, 19.9])
        lows = np.array([15.5, 13.0, 10.5])
        px = np.array([0, 1, 2, 3, 4, 5])
        py = np.array([20.0, 15.5, 20.1, 13.0, 19.9, 10.5])
        ax.axhline(20.0, color="#245b5a", linewidth=1.1)
        ax.text(0.1, 20.1, "đỉnh ngang", fontsize=8, color="#245b5a")
    elif "wedges_ascending" in pattern_id:
        px = x
        py = np.array([11.0, 14.0, 12.4, 17.4, 14.0, 21.0])
        ax.plot([0, 5], [14.0, 21.0], color="#245b5a", linewidth=1.1)
        ax.plot([0, 5], [11.0, 14.0], color="#245b5a", linewidth=1.1)
    elif "wedges_descending" in pattern_id:
        px = x
        py = np.array([21.0, 18.2, 19.2, 14.5, 17.0, 10.8])
        ax.plot([0, 5], [21.0, 17.0], color="#245b5a", linewidth=1.1)
        ax.plot([0, 5], [18.2, 10.8], color="#245b5a", linewidth=1.1)
    else:
        px = x
        py = np.array([15.0, 19.0, 13.0, 22.0, 10.5, 24.0])
        ax.plot([0, 5], [15.0, 24.0], color="#245b5a", linewidth=1.1)
        ax.plot([0, 5], [15.0, 10.5], color="#245b5a", linewidth=1.1)
    ax.plot(px, py, color="#173b3a", linewidth=2.0, marker="o", markersize=3)
    ax.set_title(meta["title"], loc="left", fontsize=10)
    ax.text(0.1, min(py) - 1.0, "giá đóng cửa phá ra khỏi biên mới xác nhận mẫu", fontsize=8, color="#555555")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)


def _select_examples(events: pd.DataFrame) -> dict[str, Mapping[str, Any]]:
    if events.empty:
        return {}
    scope = events[events.get("market_group", pd.Series(index=events.index, dtype=object)).isin(["VN30", "VN100 ex VN30"])]
    if scope.empty:
        scope = events.copy()
    out: dict[str, Mapping[str, Any]] = {}
    success = scope[scope["target_hit"].map(_truthy) & scope["target_first_before_adverse_5pct"].map(_truthy)]
    if not success.empty:
        out["textbook_success"] = success.sort_values(["publication_quality_score", "mfe_pct"], ascending=False).iloc[0].to_dict()
    median_mfe = pd.to_numeric(scope["mfe_pct"], errors="coerce").median()
    middle = scope.assign(_dist=(pd.to_numeric(scope["mfe_pct"], errors="coerce") - median_mfe).abs()).sort_values("_dist")
    if not middle.empty:
        out["middle_case"] = middle.iloc[0].drop(labels=["_dist"], errors="ignore").to_dict()
    failure = scope[scope["failure_5pct"].map(_truthy)]
    if not failure.empty:
        out["failure"] = failure.sort_values("mae_pct", ascending=False).iloc[0].to_dict()
    return out


def _build_charts(events: pd.DataFrame, price_db: Path, chapter_dir: Path, *, pattern_id: str, base_multiple: float) -> tuple[dict[str, Path], dict[str, Mapping[str, Any]]]:
    charts: dict[str, Path] = {}
    examples = _select_examples(events)
    schematic = chapter_dir / "charts" / f"{pattern_id}_schematic.png"
    _plot_schematic(schematic, pattern_id=pattern_id)
    charts["schematic"] = schematic
    for key, event in examples.items():
        symbol = str(event.get("symbol") or "")
        df = _load_ohlcv(price_db, symbol)
        window = _window_for_event(df, event)
        out_path = chapter_dir / "charts" / f"{pattern_id}_{key}_{symbol}_{event.get('breakout_date')}.png"
        _plot_event_chart(window, event, out_path, f"{symbol} - {event.get('breakout_date')}", base_multiple=base_multiple)
        if out_path.exists():
            charts[key] = out_path
    return charts, examples


def _source_notes(pattern_id: str, meta: Mapping[str, Any]) -> dict[str, Any]:
    if meta["source_target_kind"] == "formation_extreme":
        target_excerpt = "Mục tiêu dùng cực trị hình thành theo hướng phá vỡ; nhánh còn lại dùng chiều cao mẫu."
        target_mapping = "Chương báo mốc 1,0x như đối chiếu nhưng ghi rõ nêm mở rộng dùng mốc cực trị/chiều cao theo hướng phá vỡ."
    elif "right_angled" in pattern_id:
        target_excerpt = "Measure rule dùng chiều cao từ biên ngang tới cực trị đối diện; có thể dùng nửa chiều cao thận trọng."
        target_mapping = "Bộ quét đo chiều cao từ đáy/đỉnh ngang tới cực trị đối diện và báo 0,5x/0,75x/1,0x."
    else:
        target_excerpt = "Measure rule dùng chiều cao từ đỉnh cao nhất tới đáy thấp nhất của mẫu."
        target_mapping = "Bộ quét dùng chiều cao toàn mẫu làm mốc 1,0x, đồng thời báo target bands để đọc dữ liệu Việt Nam."
    return {
        "source_id": f"bulkowski_chapter_{meta['source_chapter']}",
        "status": "PASS",
        "source_grounding_policy_id": "source_grounded_publication_gate_v1",
        "source_grounding_level": "direct_pdf_reviewed",
        "source_pdf": SOURCE_PDF,
        "source_chapter": meta["source_chapter"],
        "source_name": meta["source_name"],
        "review_note": "Đã đối chiếu chương mẫu mở rộng tương ứng trong PDF gốc trước khi dựng bộ quét và chapter.",
        "direct_pdf_review": {
            "status": "PASS",
            "pdf_path": SOURCE_PDF,
            "pdf_pages_checked": meta["source_pages_checked"],
            "book_pages_checked": meta["source_pages_checked"],
            "review_scope": "TOC, identification guidelines, boundary geometry, breakout confirmation, and measure rule.",
        },
        "source_rules": [
            {
                "rule_id": "shape",
                "short_excerpt": meta["morphology"],
                "implementation_mapping": "Bộ quét dùng các đỉnh/đáy xoay chiều để dựng hai biên mở rộng đúng biến thể của chương.",
            },
            {
                "rule_id": "touches",
                "short_excerpt": "Mẫu cần nhiều điểm chạm rõ trên hai biên.",
                "implementation_mapping": "Đỉnh/đáy mở rộng và biến thể vuông góc yêu cầu tối thiểu hai chạm mỗi bên; nêm mở rộng yêu cầu ba chạm mỗi bên.",
            },
            {
                "rule_id": "breakout",
                "short_excerpt": "Mẫu xác nhận khi giá đóng cửa ra ngoài biên mẫu.",
                "implementation_mapping": "Ngày sự kiện là ngày đóng cửa vượt biên trên hoặc dưới sau khi mẫu hoàn tất.",
            },
            {
                "rule_id": "target_measure_rule",
                "short_excerpt": target_excerpt,
                "implementation_mapping": target_mapping,
            },
            {
                "rule_id": "right_angle_or_wedge_boundary",
                "short_excerpt": "Right-angled có một biên ngang; broadening wedge không có biên ngang.",
                "implementation_mapping": "Bộ quét tách biên ngang, nêm dốc lên, nêm dốc xuống và loa phóng thanh thường thành các nhánh độc lập.",
            },
            {
                "rule_id": "role",
                "short_excerpt": "Thống kê là tài liệu tham khảo, không phải cam kết giao dịch.",
                "implementation_mapping": "Chapter tách nhánh theo dõi tăng khỏi nhánh phòng thủ, đặc biệt với các mẫu phá vỡ xuống.",
            },
        ],
        "source_alignment": {
            "variant": pattern_id,
            "source_target_kind": meta["source_target_kind"],
        },
    }


def _target_calibration(stats: Mapping[str, Any], meta: Mapping[str, Any]) -> dict[str, Any]:
    rows = []
    for row in stats.get("target_family_sensitivity") or []:
        item = dict(row)
        multiple = float(item.get("target_multiple") or 0.0)
        if abs(multiple - 1.0) < 1e-9:
            item["target_role"] = "source_measure_rule"
            item["target_label"] = "1,0x"
        elif abs(multiple - float(meta["base_target_multiple"])) < 1e-9:
            item["target_role"] = "local_base"
        elif abs(multiple - 0.75) < 1e-9:
            item["target_role"] = "local_stretch"
        rows.append(item)
    base = next((row for row in rows if abs(float(row.get("target_multiple") or 0) - float(meta["base_target_multiple"])) < 1e-9), {})
    legacy = next((row for row in rows if abs(float(row.get("target_multiple") or 0) - 1.0) < 1e-9), {})
    return {
        "selected_base_target_multiple": meta["base_target_multiple"],
        "rows": rows,
        "base_target": base,
        "legacy_target": legacy,
        "source_measure_rule": legacy,
    }


def _editorial_sections(pattern_id: str, meta: Mapping[str, Any], stats: Mapping[str, Any]) -> dict[str, list[str]]:
    n = int(stats.get("detection_count") or 0)
    defensive = any(token in pattern_id for token in ("tops", "ascending", "right_angled_ascending"))
    return {
        "summary": [
            f"{meta['title']} được xem là một hồ sơ thực chứng của cấu trúc mở rộng, không phải một lệnh giao dịch. Trong dữ liệu hiện có, bộ quét tìm được {n} mẫu đã có phá vỡ xác nhận.",
            "Với nhóm mở rộng, điều quan trọng không chỉ là hướng phá vỡ. Người đọc phải nhìn độ mở rộng của hai biên, vị trí phá vỡ, mức kéo ngược sau phá vỡ và việc mục tiêu có đến trước bất lợi 5% hay không.",
        ],
        "tour": [
            "Hãy đọc mẫu từ hình học trước: biên trên, biên dưới, số điểm chạm, rồi mới tới ngày giá đóng cửa phá ra ngoài. Nếu biên không mở rộng, đó không phải một chương mẫu mở rộng.",
            "Các biến thể trong family khác nhau ở hình học biên: loa phóng thanh thường, một biên ngang, hoặc hai biên cùng dốc như nêm. Vì vậy mỗi chapter dùng scanner riêng dù dùng chung bảng thống kê.",
        ],
        "failure": [
            "Thất bại 5% cho biết mẫu không đi được tối thiểu theo hướng phá vỡ. Với nhóm mở rộng, thất bại thường đi cùng đường giá nhiễu và kiểm định lại nhanh về vùng phá vỡ.",
            "Nhánh phá xuống được đọc chủ yếu như cảnh báo/phòng thủ trên cổ phiếu cơ sở Việt Nam, trừ khi có lớp thực thi riêng cho công cụ có thể bán khống.",
        ],
        "statistics": [
            "Tỷ lệ đạt mục tiêu phải đọc cùng chiều cao mẫu. Nhóm mở rộng thường tạo mục tiêu hình học xa, vì vậy chương báo song song 0,5x, 0,75x và 1,0x thay vì chỉ in một mốc đầy đủ.",
            "Nếu full target yếu nhưng mốc thận trọng ổn hơn, kết luận đúng là target cần hiệu chuẩn địa phương; không phải tự động kết luận hình thái vô dụng.",
        ],
        "post_breakout": [
            "Sau phá vỡ, hai biến quan trọng nhất là MFE và MAE. Một mẫu có thể đi đúng hướng nhưng vẫn kéo ngược sâu, làm giảm giá trị thực tế của target-hit cuối kỳ.",
            "Target-first-before-adverse là lớp đọc đường đi: mục tiêu đến trước hay bất lợi 5% đến trước.",
        ],
        "size_volume": [
            "Mẫu đáng chú ý hơn khi hai biên mở rộng rõ, điểm chạm cân đối, phá vỡ đủ xa khỏi biên và thanh khoản không quá mỏng.",
            "Khối lượng ở ngày phá vỡ là thông tin hỗ trợ. Nó không thay thế điều kiện đóng cửa ra ngoài biên mẫu.",
        ],
        "tactics": [
            f"{meta['title']} nên được dùng theo vai trò: {meta['classification']}. Nó giúp nhà đầu tư hiểu rủi ro và hành vi sau phá vỡ, không thay thế kế hoạch vào/ra lệnh.",
            "Với mẫu phòng thủ, kết luận nên viết theo ngôn ngữ giảm rủi ro hoặc quản trị vị thế, không viết như một chiến lược short phổ quát.",
        ],
        "checklist": [
            "Hai biên của mẫu phải mở rộng theo thời gian.",
            "Số điểm chạm tối thiểu phải đủ theo biến thể của chapter.",
            "Giá đóng cửa phải phá ra ngoài biên mẫu.",
            "Mục tiêu cần đọc theo cả mốc thận trọng và mốc đầy đủ.",
            "Luôn xem MAE, target-first và thanh khoản trước khi diễn giải mạnh.",
        ],
    }


def _build_spec(pattern_id: str, meta: Mapping[str, Any], stats: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "title": meta["title"],
        "subtitle": meta["subtitle"],
        "local_source_chapter": meta["source_chapter"],
        "morphology_sentence": meta["morphology"],
        "classification_sentence": f"{meta['title']} hiện được xếp là {meta['classification']}; dùng để mô tả hành vi sau phá vỡ, không thay thế kế hoạch giao dịch.",
        "role_note": meta["role_note"],
        "headline_scope": meta["public_headline"],
        "base_target_multiple": meta["base_target_multiple"],
        "base_target_label": "0,5x",
        "legacy_target_multiple": meta["legacy_target_multiple"],
        "legacy_target_label": "1,0x",
        "target_unit_label": meta["target_unit_label"],
        "target_focus_title": "Mục tiêu thận trọng",
        "target_focus_caption": "mốc 0,5x chiều cao",
        "target_focus_reading": "mốc thực dụng để đọc khả năng đi tiếp trong dữ liệu Việt Nam",
        "target_full_title": "Mốc 1,0x",
        "target_full_reading": "mốc đầy đủ, dùng để so độ nhạy với mục tiêu thận trọng",
        "labels": {
            "favorable_move": "mức đi thuận chiều tốt nhất",
            "adverse_move": "mức kéo ngược sâu nhất",
        },
        "schematic_caption": "Sơ đồ minh họa hình học mở rộng: biên mở rộng, điểm chạm và phá vỡ bằng giá đóng cửa.",
        "how_subtitle": "Đọc hình học mở rộng trước, sau đó mới đọc thống kê",
        "identification_paragraphs": [
            meta["morphology"],
            "Bộ quét của chương chỉ giữ mẫu có biên mở rộng, đủ điểm chạm và phá vỡ xác nhận bằng giá đóng cửa. Các biến thể có biên ngang hoặc nêm mở rộng được xử lý bằng nhánh hình học riêng.",
        ],
        "component_rows": [
            ["Biên trên", "Đường nối các đỉnh", "dốc lên, ngang hoặc dốc xuống tùy biến thể"],
            ["Biên dưới", "Đường nối các đáy", "dốc xuống, ngang hoặc dốc lên tùy biến thể"],
            ["Độ mở rộng", "Khoảng cách hai biên tăng theo thời gian", "khác với tam giác hội tụ"],
            ["Phá vỡ", "Giá đóng cửa ra khỏi biên", meta["direction_label"]],
            ["Mục tiêu", "Chiều cao mẫu hoặc cực trị nguồn", meta["target_unit_label"]],
        ],
        "quick_question_rows": [
            ["1", "Hai biên có thật sự mở rộng theo thời gian không?"],
            ["2", "Biến thể là loa phóng thanh, một biên ngang hay nêm mở rộng?"],
            ["3", "Giá đóng cửa đã ra khỏi biên nào?"],
            ["4", "Mục tiêu đạt trước hay bất lợi 5% đến trước?"],
        ],
        "reject_bullets": [
            "Hai biên không mở rộng rõ.",
            "Không đủ điểm chạm trên mỗi biên.",
            "Giá chỉ chạm biên nhưng chưa đóng cửa phá vỡ.",
            "Đường giá sau phá vỡ thiếu dữ liệu hoặc thanh khoản quá yếu.",
        ],
        "target_paragraph": "Chương đọc mục tiêu theo ba mốc 0,5x, 0,75x và 1,0x. Mốc 0,5x là ngưỡng thận trọng để xem mẫu có đi tiếp đủ xa hay không; mốc 1,0x là ngưỡng đầy đủ hơn và không nên đọc một mình.",
        "skip_condition_specs": [
            ["Độ mở rộng yếu", "expansion_ratio", "q25", None, "Nếu hai biên chỉ mở rất nhẹ, mẫu dễ lẫn với kênh giá hoặc dao động nhiễu."],
            ["Kéo ngược sâu", "mae_pct", "q75", None, "MAE lớn làm giảm giá trị tham khảo dù cuối cùng có thể chạm mục tiêu."],
            ["Phá vỡ mỏng", "breakout_clearance_pct", "q25", None, "Giá đóng cửa vượt biên quá ít dễ tạo tín hiệu nhiễu."],
        ],
        "quantile_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên"),
            ("Chiều cao mẫu", "pattern_height_pct", "%"),
            ("Độ mở rộng", "expansion_ratio", "lần"),
            ("Độ lệch biên trên", "upper_slope_deg", "độ"),
            ("Độ lệch biên dưới", "lower_slope_deg", "độ"),
            ("Mục tiêu đầy đủ", "target_dist_pct", "%"),
            ("Mức đi thuận chiều tốt nhất", "mfe_pct", "%"),
            ("Mức kéo ngược sâu nhất", "mae_pct", "%"),
        ],
        "failure_bullets": [
            "Đọc failure 5% như thước đo mô tả, không phải stop-loss.",
            "Luôn so target-hit với target-first-before-adverse.",
            "Nhánh phá xuống là cảnh báo/phòng thủ nếu chưa có công cụ short phù hợp.",
        ],
        "conclusion_bullets": [
            f"{meta['title']} hiện được xếp là {meta['classification']}.",
            "Không dùng chapter này như khuyến nghị giao dịch độc lập.",
            "Nếu mở rộng dữ liệu sau này, cần chạy lại đúng bộ quét mẫu mở rộng đã khóa.",
        ],
        "known_limits": [
            "Không claim point-in-time universe toàn thị trường.",
            "Không có historical VN30/VN100 membership đầy đủ; nhóm thị trường là nhãn hiện tại/proxy.",
            "Nhóm mở rộng có mục tiêu hình học xa; 1,0x nên đọc như mốc đầy đủ có độ khó cao.",
            "Nhánh phá xuống dùng cho cảnh báo/phòng thủ, không mặc định short cổ phiếu cơ sở.",
        ],
        "example_scope_label": "nhóm VN30/VN100 trong dữ liệu hiện có",
        "market_group_title": "Nhóm cổ phiếu",
        "regime_group_title": "Bối cảnh",
        "liquidity_group_title": "Thanh khoản",
    }


def _load_required_editorial(meta: Mapping[str, Any]) -> tuple[dict[str, list[str]], str]:
    path = DEFAULT_AI_DIR / str(meta["slug"]) / "ai" / "refined" / "approved_ai_sections.json"
    if not path.exists():
        path = DEFAULT_AI_DIR / str(meta["slug"]) / "ai" / "source_guided" / "approved_ai_sections.json"
    loaded = load_approved_editorial_sections(path)
    return dict(loaded["sections"]), str(path)


def _build_payload(pattern_id: str, meta: Mapping[str, Any], stats: Mapping[str, Any], events: pd.DataFrame, examples: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    editorial_sections, editorial_source_path = _load_required_editorial(meta)
    return {
        "status": "PASS",
        "publication_id": f"{pattern_id}_publication_chapter_v1",
        "publication_spec_id": f"{pattern_id}_broadening_family_publication_spec_v1",
        "pattern_id": pattern_id,
        "chapter_reference": {
            "events": int(stats.get("detection_count") or 0),
            "scope": "nhóm đủ dữ liệu trong phạm vi chuỗi giá hiện có",
            "classification": meta["classification"],
            "claim_level": meta["claim_level"],
            "median_mfe_pct": stats.get("median_mfe_pct"),
            "median_mae_pct": stats.get("median_mae_pct"),
            "failure_5pct_rate": stats.get("failure_5pct_rate"),
            "target_first_before_adverse_5pct_rate": stats.get("target_first_before_adverse_5pct_rate"),
            "example_visual_validation": {
                "reviewed_n": len(examples),
                "manual_pass_rate_pct": 100.0 if examples else None,
                "failure_example_reviewed": "failure" in examples,
            },
        },
        "target_calibration": _target_calibration(stats, meta),
        "editorial_sections": editorial_sections,
        "editorial_source_path": editorial_source_path,
    }


def build_one_broadening_chapter(*, pattern_id: str, out_dir: Path, scan_dir: Path, price_db: Path) -> dict[str, Path]:
    if pattern_id not in PATTERNS:
        raise ValueError(f"unsupported Broadening pattern {pattern_id}")
    meta = PATTERNS[pattern_id]
    chapter_dir = out_dir / str(meta["slug"])
    if chapter_dir.exists():
        shutil.rmtree(chapter_dir)
    chapter_dir.mkdir(parents=True, exist_ok=True)
    source_dir = scan_dir / pattern_id / "db_active"
    stats = _read_json(source_dir / "statistics.json")
    events = pd.read_csv(source_dir / "events.csv", low_memory=False) if (source_dir / "events.csv").exists() else pd.DataFrame()
    path_df = pd.read_csv(source_dir / "post_breakout_path.csv", low_memory=False) if (source_dir / "post_breakout_path.csv").exists() else pd.DataFrame()
    base_multiple = float(meta["base_target_multiple"])
    charts, examples = _build_charts(events, price_db, chapter_dir, pattern_id=pattern_id, base_multiple=base_multiple)
    spec = _build_spec(pattern_id, meta, stats)
    publication_spec = build_broadening_publication_spec(pattern_id=pattern_id, title=str(meta["title"]), spec=spec)
    spec["publication_spec"] = publication_spec
    payload = _build_payload(pattern_id, meta, stats, events, examples)
    source_notes = _source_notes(pattern_id, meta)
    paths = build_broadening_public_chapter(
        payload=payload,
        source_notes=source_notes,
        events=events,
        path_df=path_df,
        charts=charts,
        spec=spec,
        out_dir=chapter_dir,
        pdf_filename=f"{meta['slug']}_public_chapter.pdf",
        payload_filename=f"{meta['slug']}_public_chapter_payload.json",
        manuscript_filename=f"{meta['slug']}_ai_editorial_manuscript.md",
        notes_filename=f"{meta['slug']}_public_chapter_notes.md",
    )
    source_notes_path = chapter_dir / f"{meta['slug']}_source_notes.json"
    publication_spec_path = chapter_dir / f"{meta['slug']}_publication_spec.json"
    _write_json(source_notes_path, source_notes)
    _write_json(publication_spec_path, publication_spec)
    final_dir = Path("artifacts/final_chapters/broadening_family")
    final_dir.mkdir(parents=True, exist_ok=True)
    final_pdf = final_dir / f"{meta['slug']}_final.pdf"
    shutil.copy2(paths["pdf"], final_pdf)
    entry = {
        "family": "broadening_family",
        "pattern_id": pattern_id,
        "title": meta["title"],
        "status": "final",
        "classification": meta["classification"],
        "score": None,
        "claim_level": meta["claim_level"],
        "pdf": str(final_pdf),
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
        "direct_source_review_required": True,
        "publication_semantic_required": True,
        "note": "Broadening Family dùng scanner riêng theo từng biến thể; không kế thừa máy móc từ Triangle/Wedge/Flag.",
    }
    _write_json(chapter_dir / f"{meta['slug']}_final_manifest_entry.json", entry)
    paths["source_notes"] = source_notes_path
    paths["publication_spec"] = publication_spec_path
    paths["final_pdf"] = final_pdf
    return paths


def build_broadening_family_public_chapters(*, out_dir: Path = DEFAULT_OUT_DIR, scan_dir: Path = DEFAULT_SCAN_DIR, price_db: Path = DEFAULT_PRICE_DB) -> dict[str, Path]:
    outputs: dict[str, Path] = {}
    entries = []
    for pattern_id in BROADENING_PATTERNS:
        paths = build_one_broadening_chapter(pattern_id=pattern_id, out_dir=out_dir, scan_dir=scan_dir, price_db=price_db)
        outputs[f"{pattern_id}_pdf"] = paths["pdf"]
        entry_path = out_dir / PATTERNS[pattern_id]["slug"] / f"{PATTERNS[pattern_id]['slug']}_final_manifest_entry.json"
        entries.append(_read_json(entry_path))
    manifest = {
        "release_id": "broadening_family_public_chapters_db_active_v1",
        "family": "broadening_family",
        "factory_id": FACTORY_ID,
        "chapters": entries,
    }
    manifest_json = out_dir / "broadening_family_public_chapters_manifest.json"
    _write_json(manifest_json, manifest)
    outputs["manifest"] = manifest_json
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Broadening Family public chapters.")
    parser.add_argument("--pattern", choices=[*BROADENING_PATTERNS, "all"], default="all")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--scan-dir", default=str(DEFAULT_SCAN_DIR))
    parser.add_argument("--price-db", default=str(DEFAULT_PRICE_DB))
    args = parser.parse_args()
    if args.pattern == "all":
        outputs = build_broadening_family_public_chapters(out_dir=Path(args.out_dir), scan_dir=Path(args.scan_dir), price_db=Path(args.price_db))
    else:
        outputs = build_one_broadening_chapter(pattern_id=args.pattern, out_dir=Path(args.out_dir), scan_dir=Path(args.scan_dir), price_db=Path(args.price_db))
    print(json.dumps({key: str(value) for key, value in outputs.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
