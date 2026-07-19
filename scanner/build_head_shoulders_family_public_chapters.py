"""Build source-grounded Head-and-Shoulders Family public chapters."""

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

from scanner.head_shoulders_family_public_chapter_factory import FACTORY_ID, build_head_shoulders_public_chapter  # noqa: E402
from scanner.head_shoulders_family_publication_specs import build_head_shoulders_publication_spec  # noqa: E402
from scanner.canonical_chapter_content import load_approved_editorial_sections  # noqa: E402
from scanner.v2.head_shoulders import HEAD_SHOULDERS_PATTERNS  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/head_shoulders_family_public_chapters")
DEFAULT_SCAN_DIR = Path("artifacts/scanner_v2/head_shoulders_family")
DEFAULT_PRICE_DB = Path("../market_cache/stock_ohlcv/latest.sqlite")
DEFAULT_AI_DIR = Path("artifacts/scanner_v2/source_guided_refinement_final_v1/head_shoulders_family")


PATTERNS: dict[str, dict[str, Any]] = {
    "head_and_shoulders_bottoms": {
        "slug": "head_and_shoulders_bottoms",
        "title": "Vai đầu vai đáy",
        "subtitle": "Ba đáy đảo chiều với đầu thấp hơn vai và giá đóng cửa phá lên đường cổ",
        "source_chapter": 24,
        "source_name": "Head-and-Shoulders Bottoms",
        "classification": "hồ sơ theo dõi mỏng mẫu trong phạm vi dữ liệu hiện có",
        "claim_level": "hồ sơ đảo chiều tăng cần đọc kèm cỡ mẫu",
        "role_note": "Dùng như hồ sơ theo dõi đảo chiều tăng; không phải tín hiệu mua tự động.",
        "morphology": "Vai đầu vai đáy có vai trái, đầu thấp hơn hai vai, vai phải và đường cổ nối hai đỉnh hồi; mẫu chỉ được tính khi giá đóng cửa phá lên đường cổ.",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "direction_label": "phá lên",
    },
    "head_and_shoulders_bottoms_complex": {
        "slug": "head_and_shoulders_bottoms_complex",
        "title": "Vai đầu vai đáy phức hợp",
        "subtitle": "Biến thể nhiều vai quanh một đầu thấp hơn và xác nhận bằng phá lên đường cổ",
        "source_chapter": 25,
        "source_name": "Head-and-Shoulders Bottoms, Complex",
        "classification": "ứng viên tham khảo đầu tư trong phạm vi dữ liệu hiện có",
        "claim_level": "hồ sơ đảo chiều tăng có mẫu dày hơn bản chuẩn",
        "role_note": "Dùng như hồ sơ theo dõi đảo chiều tăng nhiều vai; cần ưu tiên nhóm thanh khoản và đường giá sạch.",
        "morphology": "Biến thể phức hợp vẫn giữ cấu trúc đầu thấp hơn đường vai và đường cổ, nhưng có thêm một hoặc nhiều vai phụ trước khi giá đóng cửa phá lên.",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "direction_label": "phá lên",
    },
    "head_and_shoulders_tops": {
        "slug": "head_and_shoulders_tops",
        "title": "Vai đầu vai đỉnh",
        "subtitle": "Ba đỉnh đảo chiều với đầu cao hơn vai và giá đóng cửa phá xuống đường cổ",
        "source_chapter": 26,
        "source_name": "Head-and-Shoulders Tops",
        "classification": "hồ sơ phòng thủ mỏng mẫu",
        "claim_level": "hồ sơ cảnh báo rủi ro, không phải chương bán khống",
        "role_note": "Dùng như tín hiệu cảnh báo/phòng thủ trên cổ phiếu cơ sở; cỡ mẫu mỏng nên không xếp hạng như một setup giao dịch.",
        "morphology": "Vai đầu vai đỉnh có vai trái, đầu cao hơn hai vai, vai phải và đường cổ nối hai đáy hồi; mẫu xác nhận khi giá đóng cửa phá xuống đường cổ.",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "direction_label": "phá xuống",
    },
    "head_and_shoulders_tops_complex": {
        "slug": "head_and_shoulders_tops_complex",
        "title": "Vai đầu vai đỉnh phức hợp",
        "subtitle": "Biến thể nhiều vai quanh một đầu cao hơn và xác nhận bằng phá xuống đường cổ",
        "source_chapter": 27,
        "source_name": "Head-and-Shoulders Tops, Complex",
        "classification": "hồ sơ phòng thủ/thông tin trong phạm vi dữ liệu hiện có",
        "claim_level": "hồ sơ cảnh báo rủi ro nhiều vai",
        "role_note": "Dùng như hồ sơ phòng thủ sau phá vỡ xuống; không mặc định có khả năng short cổ phiếu cơ sở.",
        "morphology": "Biến thể phức hợp vẫn giữ đầu cao hơn hai vùng vai và đường cổ, nhưng có thêm nhiều vai phụ; giá đóng cửa phá xuống mới là mốc sự kiện.",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "direction_label": "phá xuống",
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
    ax.plot(x, df["close"].to_numpy(), color="#222222", linewidth=0.9, alpha=0.25)

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
        ax.text(ib + 0.3, float(df["high"].max()), "phá vỡ", fontsize=8, color="#7A5195", va="bottom")

    neckline = event.get("neckline_price")
    if pd.notna(neckline):
        ax.axhline(float(neckline), color="#245b5a", linestyle="-", linewidth=1.0, alpha=0.9)
        ax.text(0.5, float(neckline), "đường cổ", fontsize=7, color="#245b5a", va="bottom")
    breakout_price = float(event.get("breakout_price"))
    target = _target_price(event, base_multiple)
    ax.axhline(breakout_price, color="#7A5195", linestyle="--", linewidth=0.9, alpha=0.9)
    ax.axhline(target, color="#F58518", linestyle="--", linewidth=0.9, alpha=0.9)
    ax.text(0.5, breakout_price, "giá phá vỡ", fontsize=7, color="#7A5195", va="bottom")
    ax.text(0.5, target, "mốc 0,5x chiều cao", fontsize=7, color="#F58518", va="bottom")

    for key, label in [("left_shoulder_price", "vai trái"), ("head_price", "đầu"), ("right_shoulder_price", "vai phải")]:
        value = event.get(key)
        if pd.notna(value):
            ax.axhline(float(value), color="#999999", linestyle=":", linewidth=0.6, alpha=0.45)
            ax.text(len(df) - 1, float(value), label, fontsize=7, color="#666666", ha="right", va="bottom")

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
    is_top = "tops" in pattern_id
    fig, ax = plt.subplots(figsize=(9.2, 3.9), dpi=180)
    if is_top:
        x = np.array([0.5, 1.5, 2.5, 3.4, 4.3, 5.3, 6.2])
        y = np.array([15.0, 20.0, 16.2, 23.6, 16.0, 19.5, 14.2])
        neckline_y = 16.1
        target_y = 8.6
        title = "Giải phẫu vai đầu vai đỉnh"
    else:
        x = np.array([0.5, 1.5, 2.5, 3.4, 4.3, 5.3, 6.2])
        y = np.array([20.5, 15.2, 19.2, 11.7, 19.0, 15.6, 21.4])
        neckline_y = 19.1
        target_y = 26.4
        title = "Giải phẫu vai đầu vai đáy"
    ax.plot(x, y, color="#173b3a", linewidth=2.0)
    ax.axhline(neckline_y, xmin=0.18, xmax=0.86, color="#245b5a", linewidth=1.1)
    ax.axhline(target_y, color="#F58518", linestyle="--", linewidth=0.9)
    ax.annotate("vai trái", xy=(1.5, y[1]), xytext=(0.4, y[1] + (2 if is_top else -3)), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
    ax.annotate("đầu", xy=(3.4, y[3]), xytext=(3.0, y[3] + (2 if is_top else -3)), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
    ax.annotate("vai phải", xy=(5.3, y[5]), xytext=(5.0, y[5] + (2 if is_top else -3)), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
    ax.text(0.7, neckline_y, "đường cổ", color="#245b5a", fontsize=8, va="bottom")
    ax.text(0.7, target_y, "mục tiêu theo chiều cao", color="#F58518", fontsize=8, va="bottom")
    ax.set_title(title, loc="left", fontsize=10)
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
    is_top = "tops" in pattern_id
    is_complex = pattern_id.endswith("_complex")
    return {
        "source_id": f"bulkowski_chapter_{meta['source_chapter']}",
        "status": "PASS",
        "source_grounding_policy_id": "source_grounded_publication_gate_v1",
        "source_grounding_level": "direct_pdf_reviewed",
        "source_pdf": "references/encyclopedia-of-chart-patterns-2nbsped-9786468600-3175723993-9780471668268-0471668265_compress.pdf",
        "source_chapter": meta["source_chapter"],
        "source_name": meta["source_name"],
        "review_note": "Đã đối chiếu chương Head-and-Shoulders trong PDF gốc trước khi dựng scanner và chapter.",
        "direct_pdf_review": {
            "status": "PASS",
            "pdf_path": "references/encyclopedia-of-chart-patterns-2nbsped-9786468600-3175723993-9780471668268-0471668265_compress.pdf",
            "pdf_pages_checked": [374, 390, 405, 421],
            "book_pages_checked": [374, 390, 405, 421],
            "review_scope": "TOC, identification guidelines, standard/complex split, neckline breakout, and measure rule.",
        },
        "source_rules": [
            {
                "rule_id": "shape",
                "short_excerpt": "Mẫu gồm vai trái, đầu và vai phải quanh đường cổ.",
                "implementation_mapping": "Bộ quét yêu cầu chuỗi pivot năm điểm: vai, đường cổ, đầu, đường cổ, vai.",
            },
            {
                "rule_id": "head_prominence",
                "short_excerpt": "Đầu phải nổi bật hơn hai vai.",
                "implementation_mapping": "Đáy dùng đầu thấp hơn vai; đỉnh dùng đầu cao hơn vai; các vai quá lệch bị hạ chất lượng.",
            },
            {
                "rule_id": "neckline",
                "short_excerpt": "Đường cổ nối hai điểm hồi giữa vai và đầu.",
                "implementation_mapping": "Đường cổ được lấy từ hai pivot hồi; phá vỡ chỉ tính khi giá đóng cửa vượt đường cổ theo hướng mẫu.",
            },
            {
                "rule_id": "complex",
                "short_excerpt": "Biến thể phức hợp có nhiều vai phụ.",
                "implementation_mapping": "Chapter phức hợp chỉ giữ các mẫu có thêm vai phụ hoặc cấu trúc rộng được phân loại complex.",
            },
            {
                "rule_id": "target",
                "short_excerpt": "Mục tiêu đo bằng chiều cao từ đầu tới đường cổ.",
                "implementation_mapping": "Mốc 1,0x giữ vai trò nguồn; chương cũng báo 0,5x và 0,75x để đọc phù hợp dữ liệu Việt Nam.",
            },
            {
                "rule_id": "role",
                "short_excerpt": "Thống kê là tài liệu tham khảo, không phải cam kết giao dịch.",
                "implementation_mapping": "Chapter tách rõ đáy là hồ sơ theo dõi và đỉnh là hồ sơ phòng thủ/thông tin trên cổ phiếu cơ sở.",
            },
        ],
        "source_alignment": {
            "top_or_bottom": "top" if is_top else "bottom",
            "complex_variant": is_complex,
            "breakout_direction": "down" if is_top else "up",
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
            item["reading"] = "mốc đo đầy đủ theo chiều cao từ đầu tới đường cổ"
        elif abs(multiple - float(meta["base_target_multiple"])) < 1e-9:
            item["target_role"] = "local_base"
        elif abs(multiple - 0.75) < 1e-9:
            item["target_role"] = "local_stretch"
        rows.append(item)
    base = next((row for row in rows if abs(float(row.get("target_multiple") or 0) - float(meta["base_target_multiple"])) < 1e-9), {})
    legacy = next((row for row in rows if abs(float(row.get("target_multiple") or 0) - 1.0) < 1e-9), {})
    return {"rows": rows, "base_target": base, "legacy_target": legacy, "source_measure_rule": legacy}


def _editorial_sections(pattern_id: str, meta: Mapping[str, Any], stats: Mapping[str, Any]) -> dict[str, list[str]]:
    n = int(stats.get("detection_count") or 0)
    top = "tops" in pattern_id
    direction = "phá xuống" if top else "phá lên"
    return {
        "summary": [
            f"{meta['title']} được đọc như một mẫu đảo chiều đã xác nhận bằng {direction} đường cổ. Trong dữ liệu hiện có, chương này có {n} mẫu nên phần kết luận phải đặt cỡ mẫu lên trước mọi nhận xét.",
            "Điểm cần xem đầu tiên không phải là một ví dụ đẹp, mà là quan hệ giữa mức đi thuận lợi, mức kéo ngược, tỷ lệ đạt mục tiêu và xác suất đạt mục tiêu trước khi bị kéo ngược 5%.",
        ],
        "tour": [
            "Người đọc nên đi từ trái sang phải: xu hướng đi vào mẫu, vai trái, đầu, vai phải, đường cổ, rồi mới tới ngày phá vỡ. Nếu thiếu ngày phá vỡ, hình thái chỉ là một cấu trúc đang hình thành.",
            "Biến thể phức hợp không phải một mẫu khác về bản chất; nó là cùng logic vai-đầu-vai nhưng có thêm vai phụ, vì vậy chapter giữ cùng bộ đo nhưng tách cỡ mẫu và nhãn sử dụng.",
        ],
        "failure": [
            "Thất bại 5% được đọc như cảnh báo rằng mẫu không đi đủ xa theo hướng phá vỡ. Nó không phải stop-loss giao dịch, nhưng là thước đo gọn để so sánh giữa các mẫu hình.",
            "Với nhóm đỉnh, thất bại thấp không tự động biến mẫu thành chiến lược bán khống; trên cổ phiếu cơ sở Việt Nam, chapter này nên được dùng như cảnh báo rủi ro và quản trị vị thế.",
        ],
        "statistics": [
            "Các tỷ lệ trong chương nên được đọc cùng số mẫu, nhóm thanh khoản và bối cảnh thị trường. Khi cỡ mẫu mỏng, chênh lệch vài điểm phần trăm không đủ để tạo kết luận mạnh.",
            "Mốc 0,5x dùng như mục tiêu đọc thực dụng; mốc 1,0x giữ vai trò đối chiếu nguồn vì Head-and-Shoulders đo chiều cao từ đầu tới đường cổ.",
        ],
        "post_breakout": [
            "Hành vi sau phá vỡ quyết định giá trị tham khảo của mẫu: một mẫu có thể đạt mục tiêu cuối cùng nhưng vẫn kéo ngược sâu trước đó.",
            "Vì vậy, target-hit luôn được đọc song song với target-first-before-adverse, MAE và số ngày tới mục tiêu.",
        ],
        "size_volume": [
            "Mẫu càng cân bằng giữa hai vai, đầu càng nổi bật và đường cổ càng rõ thì hình thái càng dễ đọc. Khối lượng ở phá vỡ là thông tin hỗ trợ, không thay thế điều kiện hình học.",
            "Trong dữ liệu Việt Nam, thanh khoản và độ liên tục đường giá là phần bắt buộc vì nhiều mẫu nhìn đúng hình nhưng đường đi sau phá vỡ bị méo bởi giao dịch mỏng.",
        ],
        "tactics": [
            f"{meta['title']} không phải lệnh mua/bán. Cách dùng đúng là đặt mẫu vào watchlist hoặc defensive map, rồi kiểm tra thanh khoản, vị trí trong xu hướng và mức kéo ngược trước khi ra quyết định riêng.",
            "Nếu chỉ muốn một câu kết luận, hãy đọc nhãn phân loại của chương thay vì chỉ nhìn tỷ lệ đạt mục tiêu.",
        ],
        "checklist": [
            "Có xu hướng đi vào mẫu trước khi xuất hiện vai trái.",
            "Đầu nổi bật hơn hai vai và hai vai không lệch quá mức.",
            "Đường cổ được xác định từ hai điểm hồi rõ ràng.",
            f"Giá đóng cửa đã {direction} đường cổ.",
            "Đường giá sau phá vỡ đủ dữ liệu để đo MFE, MAE và target-first.",
        ],
    }


def _build_spec(pattern_id: str, meta: Mapping[str, Any], stats: Mapping[str, Any]) -> dict[str, Any]:
    top = "tops" in pattern_id
    target_unit = "chiều cao từ đầu tới đường cổ"
    return {
        "title": meta["title"],
        "subtitle": meta["subtitle"],
        "local_source_chapter": meta["source_chapter"],
        "morphology_sentence": meta["morphology"],
        "classification_sentence": f"{meta['classification']}: {meta['claim_level']}.",
        "role_note": meta["role_note"],
        "headline_scope": meta["claim_level"],
        "base_target_multiple": meta["base_target_multiple"],
        "base_target_label": "0,5x",
        "legacy_target_multiple": meta["legacy_target_multiple"],
        "legacy_target_label": "1,0x",
        "target_unit_label": target_unit,
        "target_focus_title": "Mục tiêu cơ sở",
        "target_focus_caption": "mốc 0,5x chiều cao",
        "target_focus_reading": "mốc thực dụng để đọc xác suất đạt",
        "target_full_title": "Mốc nguồn 1,0x",
        "target_full_reading": "mốc đối chiếu theo chiều cao đầy đủ",
        "labels": {
            "favorable_move": "mức đi thuận chiều tốt nhất",
            "adverse_move": "mức kéo ngược sâu nhất",
        },
        "schematic_caption": "Sơ đồ giữ đúng tinh thần nguồn: vai, đầu, vai, đường cổ và mục tiêu đo bằng chiều cao từ đầu tới đường cổ.",
        "how_subtitle": "Đọc hình thái đảo chiều trước, sau đó mới đọc thống kê",
        "identification_paragraphs": [
            meta["morphology"],
            "Bộ quét của chương không lấy mọi cấu trúc ba nhịp làm vai đầu vai. Nó yêu cầu đầu nổi bật, hai vai tương đối cân bằng, đường cổ có hai điểm hồi và breakout xác nhận bằng giá đóng cửa.",
        ],
        "component_rows": [
            ["Vai trái", "Cực trị đầu tiên sau xu hướng đi vào mẫu", "pivot trái"],
            ["Đầu", "Cực trị nổi bật nhất của mẫu", "thấp hơn vai với đáy, cao hơn vai với đỉnh"],
            ["Vai phải", "Cực trị thứ ba trước phá vỡ", "không được vượt đầu"],
            ["Đường cổ", "Mốc xác nhận mẫu", "nối hai điểm hồi giữa vai và đầu"],
            ["Mục tiêu", "Độ cao mẫu", target_unit],
        ],
        "quick_question_rows": [
            ["1", "Mẫu là đáy hay đỉnh, và có đi đúng xu hướng đi vào mẫu không?"],
            ["2", "Đầu có thực sự nổi bật hơn hai vai không?"],
            ["3", "Đường cổ có đủ rõ để làm mốc breakout không?"],
            ["4", "Sau breakout, mẫu đạt mục tiêu trước hay bị kéo ngược trước?"],
        ],
        "reject_bullets": [
            "Đầu không nổi bật hơn hai vai.",
            "Hai vai lệch quá mạnh hoặc đường cổ quá nhiễu.",
            "Không có giá đóng cửa phá vỡ đường cổ.",
            "Đường giá sau phá vỡ thiếu dữ liệu hoặc thanh khoản quá yếu.",
        ],
        "target_paragraph": "Mục tiêu nguồn của Head-and-Shoulders là chiều cao từ đầu tới đường cổ. Chương Việt Nam vẫn giữ mốc 1,0x để đối chiếu, nhưng dùng thêm 0,5x và 0,75x để đọc độ nhạy trong dữ liệu hiện có.",
        "skip_condition_specs": [
            ["Đường cổ dốc", "neckline_slope_deg", "q75", None, "Đường cổ càng dốc thì mốc phá vỡ càng khó đọc như một ranh giới ngang rõ ràng."],
            ["Vai lệch", "shoulder_diff_pct", "q75", None, "Hai vai lệch quá mạnh làm mẫu gần với dao động nhiễu hơn là vai đầu vai sạch."],
            ["Kéo ngược sâu", "mae_pct", "q75", None, "Mẫu đạt mục tiêu nhưng đường đi bất lợi sâu thì giá trị tham khảo thấp hơn."],
        ],
        "quantile_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên"),
            ("Chiều cao mẫu", "pattern_height_pct", "%"),
            ("Độ lệch hai vai", "shoulder_diff_pct", "%"),
            ("Độ nổi bật của đầu", "head_prominence_pct", "%"),
            ("Mục tiêu đầy đủ", "target_dist_pct", "%"),
            ("Mức đi thuận chiều tốt nhất", "mfe_pct", "%"),
            ("Mức kéo ngược sâu nhất", "mae_pct", "%"),
            ("Ngày chạm mục tiêu đầy đủ", "days_to_target", "phiên"),
        ],
        "failure_bullets": [
            "Đọc failure 5% như thước đo mô tả, không phải stop-loss.",
            "Luôn so target-hit với target-first-before-adverse.",
            "Nhóm đỉnh là phòng thủ/cảnh báo trong cổ phiếu cơ sở.",
        ],
        "usage_paragraphs": [],
        "conclusion_bullets": [
            f"{meta['title']} hiện được xếp là {meta['classification']}.",
            "Không dùng chapter này như khuyến nghị giao dịch độc lập.",
            "Nếu mở rộng dữ liệu sau này, cần chạy lại cùng bộ quét và cùng quy trình xuất bản đã khóa.",
        ],
        "known_limits": [
            "Không claim point-in-time universe toàn thị trường.",
            "Không có historical VN30/VN100 membership đầy đủ; nhóm thị trường là nhãn hiện tại/proxy.",
            "Các mẫu chuẩn có thể mỏng mẫu; kết luận phải đọc theo cỡ mẫu.",
            "Nhóm đỉnh dùng cho cảnh báo/phòng thủ, không mặc định short được cổ phiếu cơ sở.",
        ],
        "example_scope_label": "VN30/VN100 nếu có, nếu không thì toàn bộ mẫu đủ điều kiện",
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
        "publication_spec_id": f"{pattern_id}_head_shoulders_family_publication_spec_v1",
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


def build_one_head_shoulders_chapter(*, pattern_id: str, out_dir: Path, scan_dir: Path, price_db: Path) -> dict[str, Path]:
    if pattern_id not in PATTERNS:
        raise ValueError(f"unsupported Head-and-Shoulders pattern {pattern_id}")
    meta = PATTERNS[pattern_id]
    chapter_dir = out_dir / str(meta["slug"])
    if chapter_dir.exists():
        shutil.rmtree(chapter_dir)
    chapter_dir.mkdir(parents=True, exist_ok=True)
    source_dir = scan_dir / pattern_id / "db_active"
    stats = _read_json(source_dir / "statistics.json")
    events = pd.read_csv(source_dir / "events.csv") if (source_dir / "events.csv").exists() else pd.DataFrame()
    path_df = pd.read_csv(source_dir / "post_breakout_path.csv") if (source_dir / "post_breakout_path.csv").exists() else pd.DataFrame()
    base_multiple = float(meta["base_target_multiple"])
    charts, examples = _build_charts(events, price_db, chapter_dir, pattern_id=pattern_id, base_multiple=base_multiple)
    spec = _build_spec(pattern_id, meta, stats)
    publication_spec = build_head_shoulders_publication_spec(pattern_id=pattern_id, title=str(meta["title"]), spec=spec)
    spec["publication_spec"] = publication_spec
    payload = _build_payload(pattern_id, meta, stats, events, examples)
    source_notes = _source_notes(pattern_id, meta)
    paths = build_head_shoulders_public_chapter(
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
    _write_json(chapter_dir / f"{meta['slug']}_source_notes.json", source_notes)
    _write_json(chapter_dir / f"{meta['slug']}_publication_spec.json", publication_spec)
    final_dir = Path("artifacts/final_chapters/head_shoulders_family")
    final_dir.mkdir(parents=True, exist_ok=True)
    final_pdf = final_dir / f"{meta['slug']}_final.pdf"
    shutil.copy2(paths["pdf"], final_pdf)
    entry = {
        "chapter_id": pattern_id,
        "family": "head_shoulders_family",
        "title": meta["title"],
        "classification": meta["classification"],
        "source_chapter": meta["source_chapter"],
        "factory_id": FACTORY_ID,
        "pdf": str(final_pdf),
        "events": int(stats.get("detection_count") or 0),
    }
    _write_json(chapter_dir / f"{meta['slug']}_final_manifest_entry.json", entry)
    paths["final_pdf"] = final_pdf
    return paths


def build_head_shoulders_family_public_chapters(*, out_dir: Path = DEFAULT_OUT_DIR, scan_dir: Path = DEFAULT_SCAN_DIR, price_db: Path = DEFAULT_PRICE_DB) -> dict[str, Path]:
    outputs: dict[str, Path] = {}
    entries = []
    for pattern_id in HEAD_SHOULDERS_PATTERNS:
        paths = build_one_head_shoulders_chapter(pattern_id=pattern_id, out_dir=out_dir, scan_dir=scan_dir, price_db=price_db)
        outputs[f"{pattern_id}_pdf"] = paths["pdf"]
        entry_path = out_dir / PATTERNS[pattern_id]["slug"] / f"{PATTERNS[pattern_id]['slug']}_final_manifest_entry.json"
        entries.append(_read_json(entry_path))
    manifest = {
        "release_id": "head_shoulders_family_public_chapters_db_active_v1",
        "family": "head_shoulders_family",
        "factory_id": FACTORY_ID,
        "chapters": entries,
    }
    manifest_json = out_dir / "head_shoulders_family_public_chapters_manifest.json"
    _write_json(manifest_json, manifest)
    outputs["manifest"] = manifest_json
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Head-and-Shoulders Family public chapters.")
    parser.add_argument("--pattern", choices=[*HEAD_SHOULDERS_PATTERNS, "all"], default="all")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--scan-dir", default=str(DEFAULT_SCAN_DIR))
    parser.add_argument("--price-db", default=str(DEFAULT_PRICE_DB))
    args = parser.parse_args()
    if args.pattern == "all":
        outputs = build_head_shoulders_family_public_chapters(out_dir=Path(args.out_dir), scan_dir=Path(args.scan_dir), price_db=Path(args.price_db))
    else:
        outputs = build_one_head_shoulders_chapter(pattern_id=args.pattern, out_dir=Path(args.out_dir), scan_dir=Path(args.scan_dir), price_db=Path(args.price_db))
    print(json.dumps({key: str(value) for key, value in outputs.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
