"""Thin publication/statistical core for chart-pattern chapters.

This module is intentionally pattern-agnostic. It renders event-level outcome
statistics, tables, charts, payloads, and notes from a family-specific spec.
Pattern geometry, target interpretation, setup scoring, and narrative terms
belong in family/pattern modules, not here.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from scanner.publication_rendering_primitives import (  # noqa: E402
    _FONT_REGULAR,
    _STYLES,
    _bullet,
    _callout,
    _fmt as _raw_fmt,
    _image,
    _metric_card,
    _p,
    _section_title,
    _table,
    _vi_bool,
)


PUBLICATION_CORE_ID = "pattern_publication_core_v1"
GOVERNANCE_MATRIX = Path("artifacts/final_chapters/governance/chapter_governance_matrix.json")
DOUBLE_FAMILY_RESCUE = Path("artifacts/scanner_v2/double_family_tradable_rescue/double_family_tradable_rescue.json")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _read_json_object(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _num(value: Any, default: float = float("nan")) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return default if pd.isna(out) else out


def _pct_bool(series: pd.Series) -> float:
    if series.empty:
        return float("nan")
    return float(series.map(_truthy).mean() * 100.0)


def _numeric_series(events: pd.DataFrame, column: str) -> pd.Series:
    if column not in events:
        return pd.Series(np.nan, index=events.index, dtype="float64")
    return pd.to_numeric(events[column], errors="coerce")


def _fmt(value: Any, digits: int = 2) -> str:
    """Format values for public chapters without leaking internal missing-value tokens."""

    formatted = _raw_fmt(value, digits)
    return "chưa đủ dữ liệu" if formatted == "n/a" else formatted


def _has_missing_public_value(value: str) -> bool:
    return value.strip().lower() == "chưa đủ dữ liệu"


def _fmt_unit(value: Any, unit: str, digits: int = 2) -> str:
    formatted = _fmt(value, digits)
    return formatted if _has_missing_public_value(formatted) else f"{formatted}{unit}"


def _fmt_public(value: Any, digits: int = 2, *, suffix: str = "") -> str:
    formatted = _fmt(value, digits)
    return formatted if _has_missing_public_value(formatted) else f"{formatted}{suffix}"


def _metric_label(spec: Mapping[str, Any], key: str, default: str) -> str:
    labels = spec.get("labels") if isinstance(spec.get("labels"), Mapping) else {}
    return str(labels.get(key, default))


def _base_multiple(spec: Mapping[str, Any]) -> float:
    return _num(spec.get("base_target_multiple"), 0.46)


def _base_multiple_label(spec: Mapping[str, Any]) -> str:
    return str(spec.get("base_target_label") or f"{_fmt(_base_multiple(spec))}x").replace(".", ",")


def _target_focus_title(spec: Mapping[str, Any]) -> str:
    return str(spec.get("target_focus_title") or "Mục tiêu cơ sở")


def _target_focus_caption(spec: Mapping[str, Any]) -> str:
    return str(spec.get("target_focus_caption") or "mục tiêu cơ sở")


def _target_focus_reading(spec: Mapping[str, Any]) -> str:
    return str(spec.get("target_focus_reading") or "mốc nên đọc đầu tiên")


def _target_full_title(spec: Mapping[str, Any]) -> str:
    return str(spec.get("target_full_title") or "Mốc 1,0x chiều cao")


def _target_full_reading(spec: Mapping[str, Any]) -> str:
    return str(spec.get("target_full_reading") or "mốc căng, không dùng một mình")


def _legacy_multiple(spec: Mapping[str, Any]) -> float:
    return _num(spec.get("legacy_target_multiple"), 1.0)


def _legacy_multiple_label(spec: Mapping[str, Any]) -> str:
    return str(spec.get("legacy_target_label") or f"{_fmt(_legacy_multiple(spec))}x").replace(".", ",")


def _show_source_comparison(spec: Mapping[str, Any]) -> bool:
    return bool(spec.get("show_source_comparison_in_public"))


def _target_unit_label(spec: Mapping[str, Any]) -> str:
    return str(spec.get("target_unit_label") or "chiều cao mẫu")


def _event_is_down_breakout(event: Mapping[str, Any]) -> bool:
    direction = str(
        event.get("breakout_direction")
        or event.get("direction")
        or event.get("breakout_dir")
        or ""
    ).strip().lower()
    if direction in {"down", "bear", "bearish", "short", "-1", "false"}:
        return True
    raw_sign = event.get("direction_sign") or event.get("breakout_sign") or event.get("s_i")
    try:
        return float(raw_sign) < 0
    except (TypeError, ValueError):
        return False


def _event_metric_labels(spec: Mapping[str, Any], event: Mapping[str, Any]) -> tuple[str, str]:
    if _event_is_down_breakout(event):
        favorable_default = "mức giảm tốt nhất"
        adverse_default = "mức bật ngược sâu nhất"
    else:
        favorable_default = "mức tăng tốt nhất"
        adverse_default = "mức kéo ngược sâu nhất"
    return (
        _metric_label(spec, "favorable_move", favorable_default),
        _metric_label(spec, "adverse_move", adverse_default),
    )


def _event_label(spec: Mapping[str, Any], event: Mapping[str, Any]) -> str:
    symbol = event.get("symbol") or "không rõ mã"
    date = event.get("breakout_date") or "không rõ ngày"
    favorable, adverse = _event_metric_labels(spec, event)
    return (
        f"{symbol} ngày {date}: {favorable} {_fmt(event.get('mfe_pct'))}%, "
        f"{adverse} {_fmt(event.get('mae_pct'))}%, đạt mục tiêu {_vi_bool(event.get('target_hit'))}."
    )


def _caption_map(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    captions = payload.get("example_captions")
    return captions if isinstance(captions, Mapping) else {}


def _safe_caption_text(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower() in {"none", "null", "nan", "n/a"}:
        return ""
    replacements = {
        "MFE": "mức tăng tốt nhất",
        "MAE": "mức kéo ngược sâu nhất",
        "target-hit": "tỷ lệ đạt mục tiêu",
        "target-first": "đạt mục tiêu trước khi bị kéo ngược mạnh",
        "scanner": "bộ tiêu chí nhận diện",
        "pipeline": "quy trình",
        "proxy": "dấu hiệu thay thế",
        "setup": "cấu trúc đọc mẫu",
        "backtest": "kiểm tra thực thi minh họa",
        "validation": "giai đoạn kiểm tra kế tiếp",
        "holdout": "giai đoạn kiểm tra sau cùng",
        "vào lệnh": "xác nhận",
        "dừng lỗ": "ngưỡng rủi ro",
        "stop-loss": "ngưỡng rủi ro",
        "(lead-in)": "",
        "lead-in": "nhịp dẫn",
        "Lead-in": "Nhịp dẫn",
        "trendline": "đường xu hướng",
        "Trendline": "Đường xu hướng",
        "short setup": "hồ sơ bán khống",
        "short cấu trúc đọc mẫu": "hồ sơ bán khống",
        "short cấu trúc mẫu": "hồ sơ bán khống",
        "short cấu hình": "hồ sơ bán khống",
        "short cổ phiếu cơ sở": "bán khống cổ phiếu cơ sở",
        "long-watchlist": "hồ sơ theo dõi hướng tăng",
        "long-theo dõi": "hồ sơ theo dõi hướng tăng",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.replace("–", "-").replace("—", "-").replace("‑", "-")


def _caption_or_default(value: Any, default: str) -> str:
    text = _safe_caption_text(value)
    return text if text else default


def _schematic_caption(value: Any, default: str) -> str:
    text = _caption_or_default(value, default).strip()
    lower = text.lower()
    if lower.startswith("sơ đồ"):
        return text
    if lower.startswith("minh họa"):
        return "Sơ đồ " + text[:1].lower() + text[1:]
    if lower.startswith("hình ảnh minh họa"):
        rest = text[len("Hình ảnh "):].strip()
        return "Sơ đồ " + rest[:1].lower() + rest[1:]
    if lower.startswith("cấu trúc minh họa"):
        rest = text[len("Cấu trúc minh họa"):].strip()
        if rest.startswith(":"):
            rest = rest[1:].strip()
        return "Sơ đồ minh họa cấu trúc" + (": " + rest if rest else ".")
    return "Sơ đồ minh họa: " + text


def _chart_digest(path: Path) -> str:
    """Stable content digest used to avoid printing the same example twice."""

    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return str(path.resolve())


def _example_caption(
    *,
    key: str,
    fallback: str,
    event: Mapping[str, Any],
    spec: Mapping[str, Any],
) -> str:
    if not event:
        return (
            f"{fallback} Biểu đồ này được giữ lại để minh họa hình thái và cách xác nhận của mẫu. "
            "Bộ dữ liệu chương hiện tại không có đủ metadata sự kiện chi tiết cho ví dụ này, nên caption chỉ đọc như minh họa trực quan, "
            "không dùng như một quan sát thống kê riêng."
    )
    symbol = event.get("symbol") or "không rõ mã"
    date = event.get("breakout_date") or "không rõ ngày"
    favorable, adverse = _event_metric_labels(spec, event)
    width = _fmt(event.get("pattern_width_bars"), 0)
    height = _fmt(event.get("pattern_height_pct"))
    pole_value = event.get("pole_move_pct")
    pole_label = "nhịp dẫn trước"
    if pole_value is None or pd.isna(pole_value):
        pole_value = event.get("prior_trend_pct")
        pole_label = "xu hướng trước mẫu"
    pole = _fmt_public(pole_value)
    target = _vi_bool(event.get("target_hit"))
    failure = _vi_bool(event.get("failure_5pct"))
    days_to_target = event.get("days_to_target")
    if days_to_target is None or pd.isna(days_to_target):
        timing = "không chạm mục tiêu trong cửa sổ đo"
    else:
        timing = f"chạm mục tiêu sau {_fmt(days_to_target, 0)} phiên"
    path_quality = _public_term(event.get("path_quality_bucket") or event.get("tradability_quality_bucket") or "không rõ")
    if key == "textbook_success":
        lesson = (
            "Điểm đáng học là mẫu vừa có thân hình gọn, vừa có xác nhận đủ lực, nên đường đi sau đó không bắt người đọc chịu một nhịp kéo ngược lớn."
        )
    elif key == "middle_case":
        lesson = (
            "Điểm đáng học là mẫu vẫn có ý nghĩa tiếp diễn nhưng không chạy đủ xa để thỏa mọi mốc mục tiêu; đây là kiểu trường hợp giúp tránh kỳ vọng quá tham."
        )
    elif key == "failure":
        lesson = (
            "Điểm đáng học là hình thái hợp lệ không cứu được một nhịp xác nhận yếu; khi giá không đi nổi tối thiểu theo hướng mẫu, ví dụ này phải nằm trong phần thất bại."
        )
    else:
        lesson = "Điểm đáng học là phải đọc hình thái cùng đường đi sau xác nhận, thay vì chỉ nhìn tên mẫu."
    return (
        f"{fallback} {symbol} xác nhận ngày {date}: thân mẫu {width} phiên, biên độ {height}%, "
        f"{pole_label} {pole if pole == 'chưa đủ dữ liệu' else pole + '%'}, {favorable} {_fmt_public(event.get('mfe_pct'), suffix='%')}, {adverse} {_fmt_public(event.get('mae_pct'), suffix='%')}, "
        f"đạt mục tiêu {target}, thất bại 5% {failure}, {timing}, chất lượng đường giá {path_quality}. {lesson}"
    )


def _reader_bridge(payload: Mapping[str, Any], spec: Mapping[str, Any], bridge_id: str) -> str:
    ref = payload.get("chapter_reference") if isinstance(payload.get("chapter_reference"), Mapping) else {}
    target = payload.get("target_calibration") if isinstance(payload.get("target_calibration"), Mapping) else {}
    base = target.get("base_target") if isinstance(target.get("base_target"), Mapping) else {}
    legacy = target.get("legacy_target") if isinstance(target.get("legacy_target"), Mapping) else {}
    favorable = _metric_label(spec, "favorable_move", "mức tăng tốt nhất")
    adverse = _metric_label(spec, "adverse_move", "mức kéo ngược sâu nhất")
    if bridge_id == "results":
        return (
            f"Nói bằng ngôn ngữ biểu đồ, bảng trên không bảo rằng cứ thấy mẫu là hành động ngay. Nó nói rằng mẫu chỉ đáng đọc kỹ khi hình thái đã rõ, "
            f"và khi mục tiêu cơ sở {_base_multiple_label(spec)} được đặt cạnh thất bại 5% {_fmt(base.get('failure_5pct_rate') or ref.get('failure_5pct_rate'))}%."
        )
    if bridge_id == "identification":
        custom = spec.get("identification_bridge")
        if custom:
            return _public_paragraph(custom)
        return (
            "Các quy tắc nhận diện nên được đọc như một phễu loại sai: trước hết phải có nhịp dẫn đủ rõ, sau đó mới kiểm tra thân mẫu, rồi cuối cùng mới chờ phiên xác nhận. "
            "Nếu đảo thứ tự này, người đọc rất dễ biến một vùng dao động bình thường thành mẫu hình."
        )
    if bridge_id == "failure":
        return (
            f"Điểm quan trọng là thất bại không chỉ nằm ở tỷ lệ không đạt mục tiêu. Một mẫu có thể có {favorable} khá tốt nhưng vẫn khó dùng nếu {adverse} xuất hiện quá sớm hoặc quá sâu."
        )
    if bridge_id == "target":
        return (
            f"Cách đọc thang mục tiêu là đi từ gần đến xa: {_base_multiple_label(spec)} dùng để đo nhịp tiếp diễn thực tế hơn, còn {_legacy_multiple_label(spec)} cho biết mẫu có đủ lực chạy xa hay không. "
            "Hai mốc này trả lời hai câu hỏi khác nhau, nên không nên thay thế nhau."
        )
    if bridge_id == "conditions":
        return (
            "Bảng điều kiện không phải công thức chọn mẫu sau khi biết kết quả. Nó là bản đồ ưu tiên khi nhìn biểu đồ: mẫu càng gọn, càng có xác nhận rõ và càng ít nhiễu dữ liệu thì phần thống kê phía trước càng đáng tin hơn."
        )
    if bridge_id == "usage":
        return (
            "Nếu phải rút gọn thành một nguyên tắc sử dụng, hãy đọc mẫu theo ba lớp: hình thái có đúng không, phiên xác nhận có đủ rõ không, và đường đi sau đó có đủ gọn không."
        )
    return ""


def _selected_examples(example_events: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    return {key: value for key, value in example_events.items() if isinstance(value, Mapping)}


def _distinct_example_chart_specs(charts: Mapping[str, Path], spec: Mapping[str, Any]) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Return example charts without duplicate image content.

    Thin-sample chapters can produce two semantic example slots that point to
    the same rendered chart. Printing both under different labels is misleading,
    so the publication core keeps the first one and records the labels that were
    collapsed.
    """

    candidates = [
        ("textbook_success", str(spec.get("success_heading", "Ví dụ đạt mục tiêu")), "Trường hợp này đi đúng hướng và chạm mục tiêu trước khi xuất hiện bất lợi 5%."),
        ("middle_case", "Ví dụ trung vị", "Trường hợp này gần trung vị của mẫu: có đi thuận lợi, nhưng không đủ xa để hoàn thành mục tiêu đầy đủ."),
        ("failure", "Ví dụ thất bại", "Trường hợp này thất bại theo ngưỡng 5%, nhắc rằng hình thái hợp lệ không bảo đảm tiếp diễn."),
    ]
    seen: set[str] = set()
    selected: list[tuple[str, str, str]] = []
    skipped: list[str] = []
    for key, heading, fallback in candidates:
        if key not in charts:
            continue
        digest = _chart_digest(Path(charts[key]))
        if digest in seen:
            skipped.append(heading)
            continue
        seen.add(digest)
        selected.append((key, heading, fallback))
    return selected, skipped


def _target_rows(payload: Mapping[str, Any], spec: Mapping[str, Any]) -> list[list[Any]]:
    target = payload.get("target_calibration") if isinstance(payload.get("target_calibration"), Mapping) else {}
    rows = [["Mốc", "Vai trò", "Tỷ lệ đạt", "Đạt trước kéo ngược", "Thất bại 5%", "Cách đọc"]]
    show_source = _show_source_comparison(spec)
    role_map = {
        "source_measure_rule": "mốc nguồn Bulkowski" if show_source else "mốc đầy đủ",
        "source_full_height": "mốc nguồn đầy đủ" if show_source else "mốc đầy đủ",
        "source_full_height_usable": "mốc nguồn đầy đủ" if show_source else "mốc đầy đủ",
        "diagnostic_local_caution": "mốc thận trọng",
        "local_caution": "mốc thận trọng",
        "bulkowski_adjusted_base": "cơ sở",
        "rounded_local_base": "cơ sở làm tròn",
        "local_base": "cơ sở",
        "local_stretch": "mục tiêu mở rộng",
        "headline_branch_base": "mốc chính của nhánh được chọn",
        "headline_branch_stretch": "mốc mở rộng của nhánh được chọn",
        "headline_branch_full": "mốc đầy đủ của nhánh được chọn",
        "legacy_full_pole": "mốc đầy đủ",
        "legacy_full_height": "mốc đầy đủ",
        "conservative_half_pipe": "mốc thận trọng",
        "source_full_pipe": "mốc đầy đủ",
    }
    base_multiple = _base_multiple(spec)
    legacy_multiple = _legacy_multiple(spec)
    for row in target.get("rows") or []:
        if not isinstance(row, Mapping):
            continue
        role = str(row.get("target_role") or "")
        multiple = _num(row.get("target_multiple"))
        if role == "source_measure_rule" and show_source:
            label = str(row.get("target_label") or "Mốc nguồn")
            reading = str(row.get("reading") or "mốc đối chiếu theo tài liệu gốc")
        else:
            label = f"{row.get('target_multiple')}x"
            reading = (
                _target_focus_reading(spec)
                if abs(multiple - base_multiple) < 1e-9
                else (_target_full_reading(spec) if abs(multiple - legacy_multiple) < 1e-9 else "mốc trung gian để so độ nhạy")
            )
        rows.append(
            [
                label,
                role_map.get(role, row.get("target_role")),
                f"{_fmt(row.get('target_hit_rate'))}%",
                f"{_fmt(row.get('target_first_before_adverse_5pct_rate'))}%",
                f"{_fmt(row.get('failure_5pct_rate'))}%",
                reading,
            ]
        )
    return rows


def _results_rows(payload: Mapping[str, Any], spec: Mapping[str, Any], events: pd.DataFrame) -> list[list[Any]]:
    ref = payload.get("chapter_reference") if isinstance(payload.get("chapter_reference"), Mapping) else {}
    target = payload.get("target_calibration") if isinstance(payload.get("target_calibration"), Mapping) else {}
    source_target = target.get("source_measure_rule") if isinstance(target.get("source_measure_rule"), Mapping) else {}
    base = target.get("base_target") if isinstance(target.get("base_target"), Mapping) else {}
    legacy = target.get("legacy_target") if isinstance(target.get("legacy_target"), Mapping) else {}
    example_scope = spec.get("example_scope_label", "VN30/VN100")
    example_n = int(events[events["market_group"].isin(["VN30", "VN100 ex VN30"])].shape[0]) if "market_group" in events.columns else 0
    role_note = _public_term(spec.get("role_note", "Dùng như hồ sơ tham khảo hậu phá vỡ, không phải tín hiệu giao dịch tự động."))
    unit = _target_unit_label(spec)
    base_label = _base_multiple_label(spec)
    legacy_label = _legacy_multiple_label(spec)
    target_title = _target_focus_title(spec)
    target_full_title = _target_full_title(spec)
    rows = [
        ["Mục", "Kết quả chính"],
        ["Diện mạo", spec.get("morphology_sentence", "")],
        ["Phạm vi kết luận chính", str(ref.get("scope") or "toàn bộ mẫu đủ điều kiện")],
        ["Phạm vi ví dụ", f"{example_n} mẫu thuộc {example_scope}; ví dụ in ra ưu tiên nhóm này nhưng vẫn phải qua cổng hình thái sạch."],
        ["Số mẫu đo được", f"{_fmt(ref.get('events'), 0)} mẫu / {_fmt(events['symbol'].nunique() if 'symbol' in events.columns else None, 0)} mã."],
    ]
    if source_target and _show_source_comparison(spec):
        source_dist = source_target.get("median_target_dist_pct")
        dist_text = "" if source_dist in (None, "") else f"; khoảng cách trung vị {_fmt(source_dist)}%."
        rows.append(["Mốc nguồn Bulkowski", f"Tỷ lệ đạt {_fmt(source_target.get('target_hit_rate'))}%{dist_text}"])
    rows.extend(
        [
            [target_title, f"{base_label} {unit}; tỷ lệ đạt {_fmt(base.get('target_hit_rate'))}%."],
            *(
                []
                if abs(_base_multiple(spec) - _legacy_multiple(spec)) < 1e-9
                else [[target_full_title, f"{legacy_label} {unit}; tỷ lệ đạt {_fmt(legacy.get('target_hit_rate'))}%."]]
            ),
            ["Thất bại 5%", f"{_fmt(base.get('failure_5pct_rate') or ref.get('failure_5pct_rate'))}% mẫu không đi được tối thiểu 5% theo hướng phá vỡ."],
            ["Cách dùng", role_note],
        ]
    )
    return rows


def _notable_findings(payload: Mapping[str, Any], spec: Mapping[str, Any], events: pd.DataFrame) -> list[str]:
    ref = payload.get("chapter_reference") if isinstance(payload.get("chapter_reference"), Mapping) else {}
    target = payload.get("target_calibration") if isinstance(payload.get("target_calibration"), Mapping) else {}
    source_target = target.get("source_measure_rule") if isinstance(target.get("source_measure_rule"), Mapping) else {}
    base = target.get("base_target") if isinstance(target.get("base_target"), Mapping) else {}
    legacy = target.get("legacy_target") if isinstance(target.get("legacy_target"), Mapping) else {}
    favorable = _metric_label(spec, "favorable_move", "mức tăng tốt nhất")
    adverse = _metric_label(spec, "adverse_move", "mức kéo ngược sâu nhất")
    base_label = _base_multiple_label(spec)
    legacy_label = _legacy_multiple_label(spec)
    target_focus = _target_focus_title(spec)
    target_phrase = target_focus if base_label in target_focus else f"{target_focus} {base_label}"
    out = [
        (
            f"{target_phrase} đạt {_fmt(base.get('target_hit_rate'))}%."
            if abs(_base_multiple(spec) - _legacy_multiple(spec)) < 1e-9
            else f"{target_phrase} đạt {_fmt(base.get('target_hit_rate'))}%, so với mốc {legacy_label} ở {_fmt(legacy.get('target_hit_rate'))}%."
        ),
        f"{favorable.capitalize()} trung vị là {_fmt(ref.get('median_mfe_pct'))}%, còn {adverse} trung vị là {_fmt(ref.get('median_mae_pct'))}%.",
    ]
    if source_target and _show_source_comparison(spec):
        out.insert(
            0,
            f"Mốc nguồn Bulkowski đạt {_fmt(source_target.get('target_hit_rate'))}%; mốc Việt Nam được ghi nhãn theo hiệu chuẩn riêng, không tự động thay thế nguồn.",
        )
    if spec.get("headline_scope"):
        out.insert(0, str(spec["headline_scope"]))
    if "liquidity_bucket" in events.columns and "failure_5pct" in events.columns:
        high = events[events["liquidity_bucket"].astype(str) == "high"]
        if not high.empty:
            out.append(
                f"Nhóm thanh khoản cao có {favorable} trung vị {_fmt(float(pd.to_numeric(high['mfe_pct'], errors='coerce').median()))}% "
                f"và thất bại 5% {_fmt(_pct_bool(high['failure_5pct']))}%."
            )
    out.append(_public_term(spec.get("classification_sentence", "Đọc cùng bối cảnh, chất lượng đường giá và giới hạn dữ liệu.")))
    return out


def _coerce_public_rule_rows(rows: Any) -> list[list[str]]:
    out: list[list[str]] = []
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return out
    for item in rows:
        rule_text = ""
        apply_text = ""
        if isinstance(item, Mapping):
            rule_text = str(
                item.get("rule")
                or item.get("public_rule")
                or item.get("public_description")
                or item.get("visual_rule")
                or item.get("name")
                or ""
            ).strip()
            apply_text = str(
                item.get("application")
                or item.get("how_to_apply")
                or item.get("cach_ap_dung")
                or item.get("importance")
                or item.get("why_it_matters")
                or item.get("common_mistake")
                or item.get("common_mistakes")
                or ""
            ).strip()
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)) and len(item) >= 2:
            rule_text = str(item[0]).strip()
            apply_text = str(item[1]).strip()
        if rule_text and apply_text:
            out.append([_public_term(rule_text), _public_term(apply_text)])
    return out


def _rule_rows(source_notes: Mapping[str, Any], spec: Mapping[str, Any], payload: Mapping[str, Any] | None = None) -> list[list[Any]]:
    rows = [["Quy tắc", "Cách áp dụng"]]
    payload = payload or {}
    approved_rows = _coerce_public_rule_rows(payload.get("source_rules_public"))
    if not approved_rows:
        approved_rows = _coerce_public_rule_rows(spec.get("public_rule_rows"))
    if approved_rows:
        rows.extend(approved_rows[:8])
        return rows
    ref = payload.get("chapter_reference") if isinstance(payload.get("chapter_reference"), Mapping) else {}
    pattern_id = payload.get("pattern_id") or ref.get("pattern_id") or spec.get("title")
    raise ValueError(
        "Missing approved public recognition rules for final chapter "
        f"{pattern_id!r}. Provide `source_rules_public` in the payload or explicit `public_rule_rows` in the publication spec."
    )


def _semantic_required_note(spec: Mapping[str, Any]) -> str:
    phrases = [str(item).strip() for item in spec.get("public_required_phrases") or [] if str(item).strip()]
    if not phrases:
        return ""
    unique_phrases = list(dict.fromkeys(phrases))
    joined = "; ".join(unique_phrases)
    return (
        "Khi kiểm biểu đồ, hãy đi qua lần lượt các mốc nhận diện sau: "
        f"{joined}. "
        "Nếu thiếu một trong các mốc này, các thống kê phía sau chỉ nên được xem là tham khảo thận trọng."
    )


def _component_rows(spec: Mapping[str, Any]) -> list[list[Any]]:
    rows = [["Thành phần", "Ý nghĩa thực tế", "Dấu hiệu cần thấy"]]
    for row in spec.get("component_rows") or []:
        rows.append([_public_term(cell) for cell in row])
    return rows


def _quick_question_rows(spec: Mapping[str, Any]) -> list[list[Any]]:
    rows = [["Bước đọc", "Câu hỏi"]]
    for row in spec.get("quick_question_rows") or []:
        rows.append([_public_term(cell) for cell in row])
    return rows


def _has_body_rows(rows: list[list[Any]]) -> bool:
    return len(rows) > 1


def _skip_conditions_rows(events: pd.DataFrame, spec: Mapping[str, Any]) -> list[list[Any]]:
    custom_rows = spec.get("skip_condition_specs")
    if custom_rows:
        rows = [["Tình huống", "Ngưỡng tham chiếu", "Lý do đọc thận trọng"]]
        for label, column, operator, value, reason in custom_rows:
            series = _numeric_series(events, str(column))
            if operator == "q75":
                threshold = f"Nhóm cao: {_fmt_unit(series.quantile(0.75), '%')}"
            elif operator == "q75_bars":
                threshold = f"Nhóm cao: {_fmt(series.quantile(0.75), 0)} phiên"
            elif operator == "q75_count":
                threshold = f"Nhóm cao: {_fmt(series.quantile(0.75), 0)} lần"
            elif operator == "q25":
                threshold = f"Nhóm thấp: {_fmt_unit(series.quantile(0.25), '%')}"
            elif operator == "q25_abs":
                threshold = f"Nhóm thấp: {_fmt_unit(series.abs().quantile(0.25), '%')}"
            elif value is None:
                threshold = "Theo ngưỡng đã khóa"
            else:
                threshold = str(value)
            rows.append([_public_term(label), threshold, _public_term(reason)])
        return rows

    width = _numeric_series(events, "pattern_width_bars")
    height = _numeric_series(events, "pattern_height_pct")
    mae = _numeric_series(events, "mae_pct")
    gap = _numeric_series(events, "breakout_gap_pct").abs()
    adverse = _metric_label(spec, "adverse_move", "mức kéo ngược sâu nhất")
    return [
        ["Tình huống", "Ngưỡng tham chiếu", "Lý do đọc thận trọng"],
        ["Mẫu kéo dài", f"Nhóm cao: {_fmt(width.quantile(0.75), 0) if width.notna().any() else 'chưa đủ dữ liệu'} phiên", "Thời gian hình thành quá dài có thể khiến mẫu gần giống kênh giá hoặc vùng dao động hơn là một cấu trúc rõ."],
        ["Biên độ mẫu quá rộng", f"Nhóm cao: {_fmt_unit(height.quantile(0.75), '%')}", "Biên dao động lớn làm phần hình học kém gọn và khiến đường đi sau xác nhận khó đọc hơn."],
        ["Khoảng nhảy giá lớn ở phá vỡ", f"Nhóm cao: {_fmt_unit(gap.quantile(0.75), '%')}", "Khoảng nhảy giá có thể làm tỷ lệ đạt mục tiêu nhìn tốt hơn nhưng điểm đọc thực tế lại khó hơn."],
        ["Đường giá kém sạch", "Thiếu phiên, đứng giá kéo dài hoặc thanh khoản thấp", "Thời gian chạm mục tiêu và kiểm định lại dễ bị méo nếu đường giá không giao dịch liên tục."],
        [f"{adverse.capitalize()} quá sâu", f"Nhóm cao: {_fmt_unit(mae.quantile(0.75), '%')}", "Đường đi sau xác nhận quá nhiễu so với vai trò tham khảo của mẫu."],
    ]


def _quantile_rows(events: pd.DataFrame, spec: Mapping[str, Any]) -> list[list[Any]]:
    favorable = _metric_label(spec, "favorable_move", "mức tăng tốt nhất")
    adverse = _metric_label(spec, "adverse_move", "mức kéo ngược sâu nhất")
    specs = spec.get("quantile_specs") or [
        ("Độ dài mẫu", "pattern_width_bars", "phiên"),
        ("Chiều cao mẫu", "pattern_height_pct", "%"),
        ("Nhịp dẫn trước mẫu", "pole_move_pct", "%"),
        ("Mục tiêu đầy đủ", "target_dist_pct", "%"),
        (favorable.capitalize(), "mfe_pct", "%"),
        (adverse.capitalize(), "mae_pct", "%"),
        ("Ngày chạm mục tiêu đầy đủ", "days_to_target", "phiên"),
    ]
    rows = [["Biến", "10% thấp", "25% thấp", "Trung vị", "25% cao", "10% cao", "Đơn vị"]]
    for label, col, unit in specs:
        if col not in events.columns:
            continue
        series = pd.to_numeric(events[col], errors="coerce").dropna()
        if series.empty:
            continue
        rows.append([_public_term(label), _fmt(series.quantile(0.10)), _fmt(series.quantile(0.25)), _fmt(series.quantile(0.50)), _fmt(series.quantile(0.75)), _fmt(series.quantile(0.90)), _public_term(unit)])
    return rows


def _group_rows(events: pd.DataFrame, group_col: str, title: str, spec: Mapping[str, Any]) -> list[list[Any]]:
    favorable = _metric_label(spec, "favorable_move", "mức tăng tốt nhất")
    adverse = _metric_label(spec, "adverse_move", "mức kéo ngược sâu nhất")
    rows = [[title, "Số mẫu", "Đạt mục tiêu", "Đạt trước kéo ngược", "Thất bại 5%", favorable.capitalize(), adverse.capitalize()]]
    if group_col not in events.columns:
        return rows
    for key, group in events.groupby(group_col, dropna=False):
        rows.append(
            [
                _vi_bucket(key),
                _fmt(len(group), 0),
                _fmt_public(_pct_bool(group["target_hit"]), suffix="%") if "target_hit" in group.columns else "chưa đủ dữ liệu",
                _fmt_public(_pct_bool(group["target_first_before_adverse_5pct"]), suffix="%") if "target_first_before_adverse_5pct" in group.columns else "chưa đủ dữ liệu",
                _fmt_public(_pct_bool(group["failure_5pct"]), suffix="%") if "failure_5pct" in group.columns else "chưa đủ dữ liệu",
                _fmt_public(float(pd.to_numeric(group["mfe_pct"], errors="coerce").median()), suffix="%") if "mfe_pct" in group.columns else "chưa đủ dữ liệu",
                _fmt_public(float(pd.to_numeric(group["mae_pct"], errors="coerce").median()), suffix="%") if "mae_pct" in group.columns else "chưa đủ dữ liệu",
            ]
        )
    return rows


def _base_target_hit_rate(group: pd.DataFrame, multiple: float = 0.46) -> float:
    if group.empty or "mfe_pct" not in group.columns or "target_dist_pct" not in group.columns:
        return float("nan")
    mfe = pd.to_numeric(group["mfe_pct"], errors="coerce")
    target = pd.to_numeric(group["target_dist_pct"], errors="coerce") * multiple
    return float((mfe >= target).mean() * 100.0)


def _basic_group_stats(group: pd.DataFrame) -> list[str]:
    return [
        _fmt(len(group), 0),
        _fmt_public(_base_target_hit_rate(group), suffix="%"),
        _fmt_public(_pct_bool(group["target_hit"]), suffix="%") if "target_hit" in group.columns else "chưa đủ dữ liệu",
        _fmt_public(_pct_bool(group["target_first_before_adverse_5pct"]), suffix="%") if "target_first_before_adverse_5pct" in group.columns else "chưa đủ dữ liệu",
        _fmt_public(_pct_bool(group["failure_5pct"]), suffix="%") if "failure_5pct" in group.columns else "chưa đủ dữ liệu",
    ]


def _best_conditions_rows(events: pd.DataFrame, spec: Mapping[str, Any]) -> list[list[Any]]:
    specs = spec.get("best_condition_specs")
    base_multiple = _base_multiple(spec)
    rows = [["Điều kiện", "Số mẫu", f"Đạt {_base_multiple_label(spec)}", f"Đạt {_legacy_multiple_label(spec)}", "Đạt trước kéo ngược", "Thất bại 5%", "Cách đọc"]]
    if not specs:
        width_med = float(pd.to_numeric(events["pattern_width_bars"], errors="coerce").median()) if "pattern_width_bars" in events.columns else 0
        specs = [
            ("Mẫu ngắn hơn trung vị", "pattern_width_bars", "<=", width_med, "Ưu tiên cấu trúc gọn và ít kéo dài."),
            ("Đường giá sạch", "path_quality_bucket", "==", "clean", "Ít thiếu phiên và ít chuỗi đứng giá."),
        ]
    for label, col, op, threshold, note in specs:
        if col not in events.columns:
            continue
        series = pd.to_numeric(events[col], errors="coerce") if isinstance(threshold, (int, float)) else events[col].astype(str)
        if op == "<=":
            group = events[series <= threshold].copy()
        elif op == ">":
            group = events[series > threshold].copy()
        elif op == "==":
            group = events[series == str(threshold)].copy()
        else:
            continue
        if group.empty:
            continue
        stats = _basic_group_stats(group)
        stats[1] = _fmt_public(_base_target_hit_rate(group, base_multiple), suffix="%")
        rows.append([label, *stats, note])
    return rows


def _post_breakout_rows(events: pd.DataFrame, spec: Mapping[str, Any]) -> list[list[Any]]:
    rows = [["Chỉ tiêu", "Giá trị", "Cách đọc"]]
    hits = events[events["target_hit"].map(_truthy)] if "target_hit" in events.columns else events.iloc[0:0]
    hit_day_col = next((col for col in ("days_to_target", "time_to_target_bars", "time_to_target") if col in hits.columns), None)
    hit_days = (
        pd.to_numeric(hits[hit_day_col], errors="coerce").dropna()
        if hit_day_col is not None
        else pd.Series(dtype=float)
    )
    target_caption = _target_focus_caption(spec)
    rows.append(
        [
            f"Thời gian chạm {target_caption}",
            f"trung vị {_fmt_public(float(hit_days.median()), 0) if not hit_days.empty else 'chưa đủ dữ liệu'} phiên",
            f"Chỉ tính mẫu đã chạm {target_caption}.",
        ]
    )
    if "throwback_to_breakout_30d" in events.columns:
        retest = events["throwback_to_breakout_30d"].map(_truthy)
        day_col = "days_to_throwback_to_breakout"
        days = pd.to_numeric(events.loc[retest, day_col], errors="coerce").dropna() if day_col in events.columns else pd.Series(dtype=float)
        rows.append(["Kiểm định lại vùng phá vỡ trong 30 phiên", f"{_fmt_public(float(retest.mean()*100), suffix='%')} / ngày trung vị {_fmt_public(float(days.median()), 0) if not days.empty else 'chưa đủ dữ liệu'}", "Giá quay lại vùng phá vỡ; cần đọc cùng mức kéo ngược sâu nhất."])
    favorable = _metric_label(spec, "favorable_move", "mức tăng tốt nhất")
    adverse = _metric_label(spec, "adverse_move", "mức kéo ngược sâu nhất")
    if "mfe_pct" in events.columns and "mae_pct" in events.columns:
        rows.append([f"{favorable.capitalize()} / {adverse}", f"{_fmt(float(events['mfe_pct'].median()))}% / {_fmt(float(events['mae_pct'].median()))}%", "So sánh quãng đi đúng hướng với quãng đi ngược bất lợi."])
    if "busted_pattern_flag" in events.columns:
        busted = events["busted_pattern_flag"].map(_truthy)
        rows.append(["Mẫu phá ngược", f"{_fmt(float(busted.mean()*100))}%", "Giá đi thuận lợi chưa đủ sâu rồi phá ngược cấu trúc mẫu."])
    return rows


def _data_quality_rows(events: pd.DataFrame, ref: Mapping[str, Any] | None = None) -> list[list[Any]]:
    rows = [["Lớp kiểm tra", "Kết quả", "Cách đọc"]]
    ref = ref or {}
    premium_validation = ref.get("premium_visual_validation") if isinstance(ref.get("premium_visual_validation"), Mapping) else {}
    example_validation = ref.get("example_visual_validation") if isinstance(ref.get("example_visual_validation"), Mapping) else {}
    if premium_validation:
        score = _fmt_public(premium_validation.get("manual_score_median"))
        pass_rate = _fmt_public(premium_validation.get("manual_pass_rate_pct"), suffix="%")
        rows.append(
            [
                "Kiểm tra bằng mắt nhóm tốt nhất",
                (
                    f"n={_fmt(premium_validation.get('scored_n'), 0)}; "
                    f"điểm trung vị {score}/5; "
                    f"tỷ lệ đạt {pass_rate}"
                ),
                f"Cổng kiểm tra bằng mắt cho nhóm tốt nhất: {_public_term(_vi_bucket(premium_validation.get('premium_visual_gate')))}.",
            ]
        )
    if example_validation:
        failure_review = (
            "có ví dụ thất bại riêng"
            if example_validation.get("failure_example_reviewed")
            else "chưa có ví dụ thất bại đủ điều kiện trong nhóm minh họa"
        )
        rows.append(
            [
                "Kiểm tra bằng mắt ví dụ",
                (
                    f"n={_fmt(example_validation.get('reviewed_n'), 0)}; "
                    f"tỷ lệ đạt {_fmt_public(example_validation.get('manual_pass_rate_pct'), suffix='%')}; "
                    f"{failure_review}"
                ),
                "Các biểu đồ in trong chương được kiểm tra riêng để tránh ví dụ đẹp hoặc ví dụ thất bại bị chọn máy móc.",
            ]
        )
    if "tradability_quality_bucket" in events.columns:
        counts = events["tradability_quality_bucket"].fillna("không rõ").astype(str).value_counts().to_dict()
        score = pd.to_numeric(events.get("tradability_quality_score"), errors="coerce").median()
        label = " / ".join(f"{_vi_bucket(key)}: {value}" for key, value in sorted(counts.items()))
        rows.append(["Chất lượng giao dịch", f"điểm trung vị {_fmt(float(score))}; {label}", "Tổng hợp thiếu phiên, phiên không có khối lượng, chuỗi giá đứng yên và dấu hiệu biên độ giá."])
    if "publication_quality_tier" in events.columns:
        counts = events["publication_quality_tier"].fillna("không rõ").astype(str).value_counts().to_dict()
        score = pd.to_numeric(events.get("publication_quality_score"), errors="coerce").median()
        label = " / ".join(f"{_vi_bucket(key)}: {value}" for key, value in sorted(counts.items()))
        rows.append(["Chất lượng công bố", f"điểm trung vị {_fmt(float(score))}; {label}", "Tách mẫu đủ đúng để thống kê khỏi mẫu đủ sạch để đưa vào ví dụ hoặc kết luận chính."])
    if "price_limit_proxy_rate_60d" in events.columns:
        rows.append(["Dấu hiệu biên độ giá", f"trung vị {_fmt(float(pd.to_numeric(events['price_limit_proxy_rate_60d'], errors='coerce').median()))}% phiên", "Dấu hiệu thay thế cho các đường đi bị chi phối bởi biên độ dao động hoặc phiên bất thường."])
    if "missing_bar_rate_60d" in events.columns:
        rows.append(["Thiếu dữ liệu hậu phá vỡ", f"trung vị {_fmt(float(pd.to_numeric(events['missing_bar_rate_60d'], errors='coerce').median()))}%", "Nếu thiếu phiên, thời gian chạm mục tiêu và kiểm định lại chỉ nên được xem là ước lượng có điều kiện."])
    return rows


def _vi_bucket(value: Any) -> str:
    mapping = {
        "early": "giai đoạn đầu",
        "middle": "giai đoạn giữa",
        "late": "giai đoạn cuối",
        "bull": "thị trường tăng",
        "bear": "thị trường giảm",
        "unknown": "không rõ",
        "high": "cao",
        "medium": "trung bình",
        "mid": "trung bình",
        "low": "thấp",
        "clean": "sạch",
        "caution": "cần theo dõi",
        "impaired": "suy giảm",
        "usable": "dùng được",
        "watch": "cần theo dõi",
        "poor": "yếu",
        "premium": "tốt nhất",
        "standard": "chuẩn",
        "loose": "nới lỏng",
        "data_limited": "thiếu dữ liệu",
        "pass": "đạt",
        "fail": "không đạt",
        "outside vn100": "ngoài VN100",
        "vn100 ex vn30": "VN100 ngoài VN30",
    }
    raw = str(value or "không rõ")
    return mapping.get(raw.lower(), raw)


def _temporal_robustness_rows(ref: Mapping[str, Any]) -> list[list[Any]]:
    rows = [["Giai đoạn", "Số mẫu", "Đạt mốc chính", "Đạt trước kéo ngược", "Thất bại 5%", "Tăng/kéo ngược"]]
    source = ref.get("temporal_split_robustness") if isinstance(ref.get("temporal_split_robustness"), list) else []
    for row in source:
        if not isinstance(row, Mapping) or row.get("split_type") != "sample_thirds":
            continue
        rows.append(
            [
                _vi_bucket(row.get("period")),
                _fmt(row.get("n"), 0),
                f"{_fmt(row.get('target_hit_rate_pct'))}%",
                f"{_fmt(row.get('target_first_before_adverse_5pct_rate_pct'))}%",
                f"{_fmt(row.get('failure_5pct_rate_pct'))}%",
                _fmt(row.get("mfe_mae_median_ratio")),
            ]
        )
    return rows


def _regime_liquidity_interaction_rows(ref: Mapping[str, Any]) -> list[list[Any]]:
    rows = [["Bối cảnh", "Thanh khoản", "Số mẫu", "Đạt mốc chính", "Đạt trước kéo ngược", "Thất bại 5%", "Tăng/kéo ngược"]]
    source = ref.get("regime_liquidity_interaction") if isinstance(ref.get("regime_liquidity_interaction"), list) else []
    filtered = [row for row in source if isinstance(row, Mapping) and _num(row.get("n"), 0) >= 30]
    filtered = sorted(filtered, key=lambda item: (str(item.get("market_regime")), str(item.get("liquidity_bucket"))))
    for row in filtered[:12]:
        rows.append(
            [
                _vi_bucket(row.get("market_regime")),
                _vi_bucket(row.get("liquidity_bucket")),
                _fmt(row.get("n"), 0),
                f"{_fmt(row.get('target_hit_rate_pct'))}%",
                f"{_fmt(row.get('target_first_before_adverse_5pct_rate_pct'))}%",
                f"{_fmt(row.get('failure_5pct_rate_pct'))}%",
                _fmt(row.get("mfe_mae_median_ratio")),
            ]
        )
    return rows


def _general_statistics_rows(events: pd.DataFrame, spec: Mapping[str, Any], ref: Mapping[str, Any]) -> list[list[Any]]:
    rows = [
        ["Chỉ tiêu", "Giá trị", "Ý nghĩa"],
        ["Số mẫu / số mã", f"{_fmt(ref.get('events'), 0)} / {_fmt(events['symbol'].nunique() if 'symbol' in events.columns else None, 0)}", "Độ dày mẫu của chương."],
    ]
    if ref.get("all_scanner_events") is not None:
        rows.append(
            [
                "Phạm vi công bố",
                f"{_fmt(ref.get('public_grade_events'), 0)} / {_fmt(ref.get('all_scanner_events'), 0)} mẫu ({_fmt(ref.get('public_grade_share_pct'))}%)",
                "Kết luận chính dùng nhóm đủ chuẩn công bố; toàn bộ mẫu vẫn giữ trong hồ sơ nền.",
            ]
        )
    if isinstance(ref.get("target_hit_wilson"), Mapping):
        ci = ref.get("target_hit_wilson") or {}
        rows.append([f"Khoảng Wilson {_target_focus_caption(spec)}", f"{_fmt(ci.get('low'))}% - {_fmt(ci.get('high'))}", f"Khoảng tin cậy cho tỷ lệ đạt {_target_focus_caption(spec)}."])
    if isinstance(ref.get("target_first_wilson"), Mapping):
        ci = ref.get("target_first_wilson") or {}
        rows.append(["Khoảng Wilson đạt trước kéo ngược", f"{_fmt(ci.get('low'))}% - {_fmt(ci.get('high'))}", "Khoảng tin cậy cho tỷ lệ đạt mục tiêu trước kéo ngược 5%."])
    if isinstance(ref.get("mfe_mae_ratio_bootstrap_ci"), Mapping):
        ci = ref.get("mfe_mae_ratio_bootstrap_ci") or {}
        rows.append(["Khoảng bootstrap tỷ lệ đường đi", f"{_fmt(ci.get('low'))} - {_fmt(ci.get('high'))}", "Khoảng bootstrap cho bất đối xứng đường đi trung vị."])
    specs = spec.get("general_stat_specs") or [
        ("Độ dài mẫu", "pattern_width_bars", "phiên", "Mẫu quá dài dễ chuyển thành một vùng dao động khác, nên cần đọc thận trọng."),
        ("Chiều cao mẫu", "pattern_height_pct", "%", "Biên độ lớn cho thấy đường đi trong mẫu nhiều nhiễu hơn."),
        ("Nhịp dẫn trước mẫu", "pole_move_pct", "%", "Nhịp trước mẫu giúp đánh giá bối cảnh trước khi cấu trúc xuất hiện."),
        ("Tỷ lệ thân mẫu/nhịp dẫn", "flag_to_pole_pct", "%", "Nếu thân mẫu quá lớn so với nhịp dẫn, cấu trúc tiếp diễn trở nên kém gọn."),
    ]
    for label, col, unit, note in specs:
        if col not in events.columns:
            continue
        series = pd.to_numeric(events[col], errors="coerce").dropna()
        if series.empty:
            continue
        if len(series) >= 3:
            value = (
                f"vùng thấp {_fmt(series.quantile(0.25), 0 if unit == 'phiên' else 2)} / "
                f"trung vị {_fmt(series.median(), 0 if unit == 'phiên' else 2)} / "
                f"vùng cao {_fmt(series.quantile(0.75), 0 if unit == 'phiên' else 2)} {unit}"
            )
        else:
            value = f"trung vị {_fmt(series.median(), 0 if unit == 'phiên' else 2)} {unit}"
        rows.append([_public_term(label), value, _public_term(note)])
    return rows


def _quick_conclusion_rows(payload: Mapping[str, Any], spec: Mapping[str, Any]) -> list[list[Any]]:
    rows = [[_public_term(cell) for cell in row] for row in (spec.get("quick_conclusion_rows") or [])]
    if not rows:
        target = payload.get("target_calibration") if isinstance(payload.get("target_calibration"), Mapping) else {}
        base = target.get("base_target") if isinstance(target.get("base_target"), Mapping) else {}
        rows = [
            ["Mẫu này dùng để đọc gì?", "Đọc hành vi hậu phá vỡ trong phạm vi dữ liệu hiện có, không thay thế hệ thống giao dịch."],
            ["Mốc chính nên hiểu ra sao?", f"{_target_focus_title(spec)} đạt {_fmt(base.get('target_hit_rate'))}% nếu dữ liệu đủ để đo."],
            ["Rủi ro chính là gì?", f"Thất bại 5% ở mức {_fmt(base.get('failure_5pct_rate'))}% và đường đi có thể kéo ngược trước khi hoàn thành mục tiêu."],
            ["Khi nào nên thận trọng hơn?", "Khi hình thái thiếu sạch, thanh khoản yếu, hoặc nhóm dữ liệu phụ lục không cùng hướng với kết luận chính."],
        ]
    return [["Câu hỏi", "Câu trả lời trong dữ liệu hiện có"], *rows]


def _conclusion_bullets(payload: Mapping[str, Any], spec: Mapping[str, Any]) -> list[str]:
    items = [_public_term(item) for item in spec.get("conclusion_bullets", []) if str(item).strip()]
    if items:
        return items
    target = payload.get("target_calibration") if isinstance(payload.get("target_calibration"), Mapping) else {}
    base = target.get("base_target") if isinstance(target.get("base_target"), Mapping) else {}
    return [
        f"{spec.get('title', 'Mẫu hình')} nên được đọc như một hồ sơ hành vi sau phá vỡ trong phạm vi dữ liệu hiện có.",
        f"{_target_focus_title(spec)} là mốc đọc chính, nhưng tỷ lệ đạt {_fmt(base.get('target_hit_rate'))}% chỉ có ý nghĩa khi đặt cạnh thất bại 5% và mức kéo ngược.",
        "Giá trị của chương nằm ở cách kết hợp hình thái, xác nhận, ví dụ và phụ lục; không nằm ở một con số riêng lẻ.",
        "Nếu biểu đồ thật thiếu một trong các điều kiện nhận diện chính, người đọc nên hạ độ tin cậy thay vì ép mẫu vào kết luận thống kê.",
    ]


def _governance_row(pattern_id: str) -> Mapping[str, Any]:
    payload = _read_json_object(GOVERNANCE_MATRIX)
    for row in payload.get("chapters") or []:
        if isinstance(row, Mapping) and row.get("pattern_id") == pattern_id:
            return row
    return {}


def _infer_pattern_id(payload: Mapping[str, Any]) -> str:
    explicit = str(payload.get("pattern_id") or "").strip()
    if explicit:
        return explicit
    publication_id = str(payload.get("publication_id") or "").strip()
    known = {
        "bull_flag": "bull_flags",
        "bear_flag": "bear_flags",
        "bull_pennant": "bull_pennants",
    }
    for token, pattern_id in known.items():
        if publication_id.startswith(token):
            return pattern_id
    return ""


def _public_term(value: Any) -> str:
    text = str(value or "")
    mapping = {
        "publication-final": "chương xuất bản cuối",
        "publication_final": "chương xuất bản cuối",
        "investment-reference candidate under available-series public-grade scope": "ứng viên tham khảo đầu tư trong phạm vi nhóm đủ chuẩn công bố",
        "investment-reference candidate under available-series scope": "ứng viên tham khảo đầu tư trong phạm vi chuỗi hiện có",
        "defensive/informational-reference candidate under available-series scope": "ứng viên tham khảo phòng thủ/thông tin trong phạm vi chuỗi hiện có",
        "defensive/informational branch-reference under available-series scope": "tham khảo phòng thủ/thông tin theo nhánh trong phạm vi chuỗi hiện có",
        "watchlist-reference branch candidate under available-series scope": "ứng viên theo dõi theo nhánh trong phạm vi chuỗi hiện có",
        "variant watchlist-reference under available-series scope": "biến thể theo dõi trong phạm vi chuỗi hiện có",
        "variant defensive/informational reference under available-series scope": "biến thể phòng thủ/thông tin trong phạm vi chuỗi hiện có",
        "tradable-research-candidate under available-series descriptive scope": "ứng viên thực thi nghiên cứu trong phạm vi mô tả hiện có",
        "bull_flag_tradable_research_candidate_95": "cờ tăng đạt lớp thực thi nghiên cứu 95+",
        "watchlist-reference under available-series descriptive scope": "tham khảo theo dõi trong phạm vi mô tả hiện có",
        "watchlist-reference under available-series scope": "tham khảo theo dõi trong phạm vi chuỗi hiện có",
        "hồ sơ theo dõi trong phạm vi dữ liệu hiện có": "hồ sơ theo dõi trong phạm vi dữ liệu hiện có",
        "tài liệu phòng thủ và cảnh báo rủi ro trong phạm vi dữ liệu hiện có": "tài liệu phòng thủ và cảnh báo rủi ro trong phạm vi dữ liệu hiện có",
        "preflight_strong": "tiền kiểm mạnh",
        "preflight_candidate": "tiền kiểm ứng viên",
        "preflight_watchlist": "tiền kiểm theo dõi",
        "preflight_weak": "tiền kiểm yếu",
        "preflight_poor": "tiền kiểm rất yếu",
        "tradable_final_95": "đạt lớp thực thi 95+",
        "tradable_research_candidate_blocked": "ứng viên thực thi nhưng còn cổng chặn",
        "tradable_tested_blocked": "đã kiểm tra thực thi nhưng chưa đạt",
        "not_tested": "chưa kiểm tra thực thi",
        "insufficient_data": "chưa đủ dữ liệu",
        "missing_event_source": "thiếu nguồn sự kiện",
        "No executable entry/exit/cost/sizing/OOS gate exists for this chương.": "Chương này chưa có cổng thực thi đầy đủ về điểm xác nhận, điểm thoát, chi phí, trượt giá, quy mô vị thế và kiểm định ngoài mẫu.",
        "No executable entry/exit/cost/sizing/OOS gate exists for this chapter.": "Chương này chưa có cổng thực thi đầy đủ về điểm xác nhận, điểm thoát, chi phí, trượt giá, quy mô vị thế và kiểm định ngoài mẫu.",
        "review pack generated; formal human scores can be added before external publication": "đã tạo bộ biểu đồ để kiểm tra; chưa có điểm chấm thủ công chính thức",
        "long_cash_candidate": "ứng viên tham khảo theo hướng tăng trên cổ phiếu cơ sở",
        "tested_executable_layer": "đã kiểm tra lớp thực thi",
        "tested executable layer; local audit passed no-overlift guard": "đã kiểm tra lớp thực thi; kiểm tra cục bộ qua cổng không nâng quá mức",
        "local blocker audit; not promoted": "kiểm tra cục bộ còn chặn; không nâng hạng",
        "branch optimized but not promoted": "đã tối ưu nhánh nhưng không nâng hạng",
        "mixed_direction_reference": "tham khảo hai hướng",
        "defensive_informational": "phòng thủ/thông tin",
        "local_blocker_audit": "kiểm tra chặn cục bộ",
        "branch_optimization_layer": "lớp tối ưu nhánh",
        "specialized_tradable_layer": "lớp thực thi chuyên biệt",
        "FAMILY_PROMOTION_REVIEW_VARIANTS_REMAIN_SUBGROUPS": "đủ xem xét cấp family; biến thể vẫn là nhóm con",
        "DEFENSIVE_FAMILY_SUPPORT_ONLY": "chỉ hỗ trợ family phòng thủ/thông tin",
        "NO_FAMILY_PROMOTION_VARIANTS_REMAIN_STANDALONE_LIMITED": "không nâng cấp family; biến thể vẫn bị giới hạn riêng",
        "ELIGIBLE_FOR_FAMILY_PROMOTION_REVIEW": "đủ điều kiện xem xét nâng cấp cấp family",
        "STOP_NO_PROMOTION_UNDER_NO_OVERLIFT_POLICY": "dừng, không nâng hạng theo cổng không nâng quá mức",
    }
    if text in mapping:
        return mapping[text]
    replacements = {
        "scope_not_direct_long_cash_equity": "không phải phạm vi tham khảo tăng giá trực tiếp",
        "score_below_95": "điểm dưới 95",
        "score_threshold_95": "chưa qua ngưỡng 95",
        "walk_forward_has_negative_fold": "kiểm định cuốn chiếu còn kỳ âm",
        "walk_forward_negative_folds": "kiểm định cuốn chiếu còn kỳ âm",
        "walk_forward_sum_return_below_8pct": "tổng kiểm định cuốn chiếu dưới 8%",
        "validation_trade_count_below_12": "số giao dịch kiểm định dưới 12",
        "holdout_trade_count_below_12": "số giao dịch giữ lại dưới 12",
        "median_adtv_participation_above_5pct": "mức tham gia thanh khoản trung vị trên 5%",
        "direct_long_cash_scope": "phạm vi tham khảo tăng giá trực tiếp",
        "promotion_blockers": "các cổng chặn nâng hạng",
        "score_threshold": "ngưỡng điểm",
        "candidate": "ứng viên",
        "reference": "tham khảo",
        "defensive": "phòng thủ",
        "informational": "thông tin",
        "scope": "phạm vi",
        "audit": "kiểm tra",
        "available-series": "chuỗi hiện có",
        "watchlist": "theo dõi",
        "tradable": "thực thi",
        "blocked": "bị chặn",
        "Flag Family": "nhóm Cờ",
        "flag family": "nhóm Cờ",
        "Corporate actions": "Sự kiện quyền",
        "corporate actions": "sự kiện quyền",
        "delisted/halted": "hủy niêm yết hoặc tạm ngừng",
        "status tape": "dữ liệu trạng thái",
        "historical VN30/VN100 membership": "dữ liệu thành phần VN30/VN100 lịch sử",
        "point-in-time universe": "danh sách cổ phiếu theo từng thời điểm",
        "point-in-time": "theo từng thời điểm",
        "claim": "tuyên bố",
        "stop-loss": "ngưỡng rủi ro",
        "(lead-in)": "",
        "lead-in": "nhịp dẫn",
        "Lead-in": "Nhịp dẫn",
        "trendline": "đường xu hướng",
        "Trendline": "Đường xu hướng",
        "short setup": "hồ sơ bán khống",
        "short cấu trúc đọc mẫu": "hồ sơ bán khống",
        "short cấu trúc mẫu": "hồ sơ bán khống",
        "short cấu hình": "hồ sơ bán khống",
        "short cổ phiếu cơ sở": "bán khống cổ phiếu cơ sở",
        "long-watchlist": "hồ sơ theo dõi hướng tăng",
        "long-theo dõi": "hồ sơ theo dõi hướng tăng",
        "dừng lỗ": "ngưỡng rủi ro",
        "vào lệnh": "xác nhận",
        "Target-first-before-adverse": "mục tiêu đến trước nhịp kéo ngược bất lợi",
        "target-first-before-adverse": "mục tiêu đến trước nhịp kéo ngược bất lợi",
        "Target-first": "đạt mục tiêu trước kéo ngược",
        "target-first": "đạt mục tiêu trước kéo ngược",
        "Chapter": "Chương",
        "chapter": "chương",
        "target-hit": "tỷ lệ đạt mục tiêu",
        "backtest": "quay lại kiểm định",
        "public-grade": "đủ chuẩn công bố",
        "public": "công bố",
        "Đầu phải nổi bật": "Phần đầu phải nổi bật",
        "Đáy dùng đầu thấp hơn vai; đỉnh dùng đầu cao hơn vai; các vai quá lệch bị hạ chất lượng.": "Phần đầu phải nổi bật hơn hai vai theo hướng của mẫu; các vai quá lệch bị hạ chất lượng.",
        "vượt đường cổ theo hướng mẫu": "đi qua đường cổ theo hướng mẫu",
    }
    out = text
    for source, target in replacements.items():
        out = out.replace(source, target)
    return out.replace("_", " ")


def _public_items(values: Sequence[Any]) -> list[str]:
    return [_public_term(value) for value in values]


def _public_paragraph(value: Any) -> str:
    return _safe_caption_text(_public_term(value))


def _double_family_rows(pattern_id: str) -> list[list[Any]]:
    if not pattern_id.startswith(("double_bottoms_", "double_tops_")):
        return []
    rescue = _read_json_object(DOUBLE_FAMILY_RESCUE)
    family_key = "double_bottoms" if pattern_id.startswith("double_bottoms_") else "double_tops"
    family = next((row for row in rescue.get("families") or [] if isinstance(row, Mapping) and row.get("family") == family_key), {})
    if not family:
        return []
    label = "Nhóm hai đáy" if family_key == "double_bottoms" else "Nhóm hai đỉnh"
    guard = family.get("no_overlift_guard") if isinstance(family.get("no_overlift_guard"), Mapping) else {}
    stats = family.get("best_variant_trade_stats") if isinstance(family.get("best_variant_trade_stats"), Mapping) else {}
    suffix = pattern_id.replace(f"{family_key}_", "")
    variant_map = {"adam_adam": "AA", "adam_eve": "AE", "eve_adam": "EA", "eve_eve": "EE"}
    variant = variant_map.get(suffix, "")
    variant_stats = stats.get(variant) if isinstance(stats.get(variant), Mapping) else {}
    detail = (
        f"Biến thể {variant}: {variant_stats.get('trades')} giao dịch trong nhánh nhóm tốt nhất; "
        f"lợi suất ròng trung bình {_fmt(variant_stats.get('avg_net_return_pct'))}%; "
        f"tỷ lệ dương {_fmt(variant_stats.get('win_rate_pct'))}%."
        if variant_stats
        else "Biến thể này được đọc như nhóm con, không phải bằng chứng đứng riêng."
    )
    return [
        [
            "Bằng chứng cấp nhóm",
            f"{label}: điểm {_fmt(family.get('best_score'))}; {_public_term(family.get('variant_support_decision'))}.",
            detail,
        ],
        [
            "Cổng không nâng quá mức",
            _public_term(guard.get("promotion_decision") or "chưa đủ dữ liệu"),
            "Bằng chứng cấp nhóm không tự động nâng từng biến thể mỏng thành lớp thực thi cuối riêng lẻ.",
        ],
    ]


def _governance_assessment_rows(payload: Mapping[str, Any]) -> list[list[Any]]:
    pattern_id = _infer_pattern_id(payload)
    row = _governance_row(pattern_id)
    if not row:
        return []
    blockers = row.get("tradable_blockers")
    if isinstance(blockers, list):
        blocker_text = ", ".join(_public_term(item) for item in blockers) or "không có"
    else:
        blocker_text = _public_term(blockers or "không có")
    rows = [
        ["Lớp đánh giá", "Kết quả", "Cách đọc"],
        [
            "Chất lượng chương",
            _public_term(row.get("publication_classification") or row.get("publication_claim_level") or "publication-final"),
            "Chương đã qua cổng xuất bản; đây là chất lượng tài liệu đọc, không phải bằng chứng giao dịch.",
        ],
        [
            "Điểm sàng lọc",
            f"{_fmt_public(row.get('tradable_preflight_score'))} - {_public_term(row.get('tradable_preflight_status'))}",
            _public_term(row.get("tradable_preflight_scope") or "đọc như lớp sàng lọc/tham khảo"),
        ],
        [
            "Điểm thực thi",
            f"{_fmt_public(row.get('tradable_score'))} - {_public_term(row.get('tradable_status'))}",
            _public_term(row.get("tradable_claim_level") or row.get("tradable_applicability") or "đã kiểm tra lớp thực thi"),
        ],
        ["Cổng chặn còn lại", blocker_text, "Nếu còn cổng chặn, không được viết như tài liệu giao dịch hoàn chỉnh."],
    ]
    rows.extend(_double_family_rows(pattern_id))
    return rows


def _header_footer(label: str):
    def draw(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont(_FONT_REGULAR, 7)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(doc.leftMargin, 1.0 * cm, f"{label} - bản chương xuất bản")
        canvas.drawRightString(A4[0] - doc.rightMargin, 1.0 * cm, f"Trang {doc.page}")
        canvas.restoreState()

    return draw


def build_pattern_story(
    *,
    payload: Mapping[str, Any],
    source_notes: Mapping[str, Any],
    events: pd.DataFrame,
    charts: Mapping[str, Path],
    spec: Mapping[str, Any],
) -> list[Any]:
    ref = payload.get("chapter_reference") if isinstance(payload.get("chapter_reference"), Mapping) else {}
    target = payload.get("target_calibration") if isinstance(payload.get("target_calibration"), Mapping) else {}
    base = target.get("base_target") if isinstance(target.get("base_target"), Mapping) else {}
    examples = _selected_examples(payload.get("example_events") if isinstance(payload.get("example_events"), Mapping) else {})
    editorial = payload.get("editorial_sections") if isinstance(payload.get("editorial_sections"), Mapping) else {}
    captions = _caption_map(payload)
    title = str(spec.get("title", "Flag"))
    subtitle = str(spec.get("subtitle", "Mẫu tiếp diễn ngắn"))
    favorable = _metric_label(spec, "favorable_move", "mức tăng tốt nhất")
    adverse = _metric_label(spec, "adverse_move", "mức kéo ngược sâu nhất")
    story: list[Any] = []

    story.append(Paragraph("CHƯƠNG MẪU HÌNH GIÁ", _STYLES["Deck"]))
    story.append(Paragraph(title, _STYLES["Title"]))
    story.append(Paragraph(subtitle, _STYLES["Subtitle"]))
    cards = [
        _metric_card("Số mẫu", _fmt(ref.get("events"), 0), "mẫu đã kiểm tra"),
        _metric_card(_target_focus_title(spec), _base_multiple_label(spec), _target_unit_label(spec)),
        _metric_card("Tỷ lệ đạt", f"{_fmt(base.get('target_hit_rate'))}%", _target_focus_caption(spec)),
        _metric_card("Thất bại 5%", f"{_fmt(base.get('failure_5pct_rate') or ref.get('failure_5pct_rate'))}%", "không đi đủ 5%"),
    ]
    cards_table = Table([cards], colWidths=[4.0 * cm] * 4, hAlign="CENTER")
    cards_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0ece3")), ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d8d0c2")), ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d8d0c2")), ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9)]))
    story.append(cards_table)
    story.append(Spacer(1, 0.35 * cm))
    story.append(Paragraph("Kết quả quan trọng", _STYLES["H1"]))
    story.append(_table(_results_rows(payload, spec, events), [4.0 * cm, 12.3 * cm]))
    story.append(_callout("Điểm đáng chú ý", _notable_findings(payload, spec, events)))
    story.append(_p(_reader_bridge(payload, spec, "results"), _STYLES["Body"]))
    for paragraph in editorial.get("summary", []) or spec.get("summary_paragraphs", []):
        story.append(_p(_public_paragraph(paragraph), _STYLES["Body"]))
    story.append(_image(charts["schematic"], 16.2))
    schematic_caption = _schematic_caption(
        captions.get("schematic"),
        str(spec.get("schematic_caption", f"Sơ đồ minh họa cấu trúc mẫu hình và {_target_focus_caption(spec)}.")),
    )
    story.append(_p(schematic_caption, _STYLES["Caption"]))

    story.append(_section_title("1", "Mẫu hình hoạt động ra sao", str(spec.get("how_subtitle", "Tour ngắn trước khi đi vào quy tắc nhận diện"))))
    for paragraph in editorial.get("tour", []) or spec.get("tour_paragraphs", []):
        story.append(_p(_public_paragraph(paragraph), _STYLES["Body"]))
    quick_rows = _quick_question_rows(spec)
    if _has_body_rows(quick_rows):
        story.append(_table(quick_rows, [4.0 * cm, 12.3 * cm]))
    story.append(_p(_public_paragraph(spec.get("rule_first_note", "Cách đọc này giữ đúng tinh thần một chương mẫu hình: trước hết mô tả hình thái, sau đó mới đo kết quả.")), _STYLES["Body"]))

    story.append(_section_title("2", "Cách nhận diện", "Quy tắc hình học trước, kết quả phía sau"))
    for paragraph in spec.get("identification_paragraphs", []):
        story.append(_p(_public_paragraph(paragraph), _STYLES["Body"]))
    semantic_note = _semantic_required_note(spec)
    if semantic_note:
        story.append(_p(semantic_note, _STYLES["Body"]))
    story.append(Paragraph("Các quy tắc nhận diện được dùng", _STYLES["H2"]))
    story.append(_table(_rule_rows(source_notes, spec, payload), [5.8 * cm, 10.5 * cm]))
    component_rows = _component_rows(spec)
    if _has_body_rows(component_rows):
        story.append(_table(component_rows, [3.0 * cm, 7.0 * cm, 6.3 * cm]))
    story.append(_p(_reader_bridge(payload, spec, "identification"), _STYLES["Body"]))
    reject_items = _public_items(list(spec.get("reject_bullets") or []))
    if reject_items:
        story.append(_callout("Điểm loại nhanh", reject_items))
    story.append(Paragraph("Khi nên đọc thận trọng", _STYLES["H2"]))
    story.append(_table(_skip_conditions_rows(events, spec), [4.0 * cm, 3.5 * cm, 8.8 * cm]))

    # Let the appendix flow naturally after the closing bullets. A forced page
    # break here repeatedly created sparse pages when the main narrative ended
    # with only a short conclusion.
    story.append(Spacer(1, 0.35 * cm))
    distinct_example_charts, skipped_duplicate_examples = _distinct_example_chart_specs(charts, spec)
    example_subtitle = (
        "Một ví dụ đạt mục tiêu, một ví dụ trung vị và một ví dụ thất bại"
        if any(key == "failure" for key, _, _ in distinct_example_charts)
        else "Các ví dụ đủ điều kiện minh họa hình thái"
    )
    story.append(_section_title("3", "Ví dụ minh họa", example_subtitle))
    for paragraph in spec.get("example_intro", []):
        story.append(_p(_public_paragraph(paragraph), _STYLES["Body"]))
    example_validation = ref.get("example_visual_validation") if isinstance(ref.get("example_visual_validation"), Mapping) else {}
    if example_validation:
        failure_review = (
            "có ví dụ thất bại riêng"
            if example_validation.get("failure_example_reviewed")
            else "chưa có biểu đồ thất bại đủ điều kiện để in riêng"
        )
        story.append(
            _callout(
                "Ví dụ đã được kiểm tra bằng mắt",
                [
                    (
                        f"Đã kiểm tra {example_validation.get('reviewed_n')} biểu đồ ví dụ; "
                        f"in {len(distinct_example_charts)} biểu đồ không trùng lặp; "
                        f"tỷ lệ đạt {_fmt_public(example_validation.get('manual_pass_rate_pct'), suffix='%')}; "
                        f"{failure_review}."
                    )
                ],
            )
        )
    for key, heading, fallback in distinct_example_charts:
        event = examples.get(key, {}) if isinstance(examples, Mapping) else {}
        story.append(
            KeepTogether(
                [
                    Paragraph(str(heading), _STYLES["H2"]),
                    _image(charts[key], 16.0),
                    _p(
                        _example_caption(
                            key=key,
                            fallback=str(fallback),
                            event=event if isinstance(event, Mapping) else {},
                            spec=spec,
                        ),
                        _STYLES["Caption"],
                    ),
                ]
            )
        )
        if isinstance(event, Mapping) and event:
            story.append(Paragraph(_walkthrough_title(event, key), _STYLES["H2"]))
            story.append(_p(_walkthrough_intro(event, key), _STYLES["Body"]))
            story.append(_table(_sample_walkthrough_rows(event, spec, key), [3.5 * cm, 5.0 * cm, 7.8 * cm]))
            story.append(_p(_walkthrough_note(key, spec), _STYLES["Body"]))
    if skipped_duplicate_examples:
        story.append(
            _callout(
                "Ví dụ không in lặp",
                [
                    (
                        "Một số nhãn ví dụ trỏ tới cùng một biểu đồ nên không được in lại: "
                        f"{', '.join(skipped_duplicate_examples)}. "
                        "Điều này giữ phần minh họa trung thực với dữ liệu hiện có thay vì tạo cảm giác có nhiều trường hợp độc lập hơn thực tế."
                    )
                ],
            )
        )
    story.append(_section_title("4", "Tập trung vào thất bại", "Thất bại là một phần của hồ sơ mẫu hình, không phải phụ lục"))
    for paragraph in editorial.get("failure", []) or spec.get("failure_paragraphs", []):
        story.append(_p(_public_paragraph(paragraph), _STYLES["Body"]))
    story.append(_table(_failure_rows(payload, events, spec), [4.1 * cm, 5.6 * cm, 6.6 * cm]))
    story.append(_p(_reader_bridge(payload, spec, "failure"), _STYLES["Body"]))
    story.append(_callout("Quy tắc đọc thất bại", _public_items(list(spec.get("failure_bullets") or []))))
    story.append(Paragraph("Mục tiêu giá", _STYLES["H2"]))
    story.append(_p(_public_paragraph(spec.get("target_paragraph", "Mục tiêu giá nên được đọc theo thang 0,46x, 0,5x, 0,75x và 1,0x thay vì một mốc duy nhất.")), _STYLES["Body"]))
    story.append(_table(_target_rows(payload, spec), [1.55 * cm, 2.8 * cm, 1.75 * cm, 2.35 * cm, 1.8 * cm, 6.0 * cm]))
    story.append(_p(_reader_bridge(payload, spec, "target"), _STYLES["Body"]))
    story.append(Paragraph("Hành vi sau phá vỡ", _STYLES["H2"]))
    for paragraph in editorial.get("post_breakout", []) or []:
        story.append(_p(_public_paragraph(paragraph), _STYLES["Body"]))
    story.append(_table(_post_breakout_rows(events, spec), [4.5 * cm, 4.2 * cm, 7.6 * cm]))

    story.append(_section_title("5", "Cách đọc kết quả quan trọng", "Biến số liệu thành quyết định đọc biểu đồ"))
    for paragraph in editorial.get("statistics", []) or spec.get("statistics_paragraphs", []):
        story.append(_p(_public_paragraph(paragraph), _STYLES["Body"]))
    story.append(_table(_reader_question_rows(payload, spec), [4.2 * cm, 4.2 * cm, 7.9 * cm]))
    story.append(Paragraph("Vùng thường gặp và vùng cực trị", _STYLES["H2"]))
    story.append(_table(_quantile_rows(events, spec), [4.1 * cm, 1.65 * cm, 1.65 * cm, 1.65 * cm, 1.65 * cm, 1.65 * cm, 1.9 * cm]))

    story.append(_section_title("6", "Khi mẫu đáng chú ý hơn", "Kích thước, khối lượng và bối cảnh"))
    for paragraph in editorial.get("size_volume", []) or spec.get("size_volume_paragraphs", []):
        story.append(_p(_public_paragraph(paragraph), _STYLES["Body"]))
    story.append(_table(_best_conditions_rows(events, spec), [4.0 * cm, 1.25 * cm, 1.65 * cm, 1.65 * cm, 2.1 * cm, 1.7 * cm, 4.0 * cm]))
    story.append(_p(_reader_bridge(payload, spec, "conditions"), _STYLES["Body"]))

    story.append(_section_title("7", "Cách sử dụng thực tế", "Giữ ranh giới giữa tài liệu tham khảo và quyết định giao dịch"))
    for paragraph in editorial.get("tactics", []) or spec.get("usage_paragraphs", []):
        story.append(_p(_public_paragraph(paragraph), _STYLES["Body"]))
    story.append(Paragraph("Checklist đọc mẫu", _STYLES["H2"]))
    for item in editorial.get("checklist", []) or spec.get("checklist", []):
        story.append(_bullet(str(item), _STYLES["Body"]))
    story.append(_p(_reader_bridge(payload, spec, "usage"), _STYLES["Body"]))
    story.append(_table(_quick_conclusion_rows(payload, spec), [4.0 * cm, 12.3 * cm]))
    governance_rows = _governance_assessment_rows(payload)
    if governance_rows:
        story.append(_section_title("8", "Đánh giá hai trục", "Tách chất lượng tài liệu khỏi khả năng triển khai giao dịch"))
        story.append(_table(governance_rows, [3.8 * cm, 5.4 * cm, 7.1 * cm]))
    if not spec.get("suppress_main_conclusion"):
        # Do not wrap the closing section in KeepTogether. On content-heavy
        # chapters, a short conclusion block can otherwise be pushed onto an
        # almost blank page just before the technical appendix.
        story.append(Paragraph("Kết luận chương", _STYLES["H2"]))
        for item in _conclusion_bullets(payload, spec):
            story.append(_bullet(_public_term(item), _STYLES["Body"]))

    # Let the appendix flow naturally after the closing bullets. A forced page
    # break here repeatedly created sparse pages when the main narrative ended
    # with only a short conclusion.
    story.append(Spacer(1, 0.35 * cm))
    story.append(_section_title("A", "Phụ lục kỹ thuật", "Các bảng chi tiết để kiểm tra lại số liệu"))
    story.append(
        _p(
            "Phần chính phía trên là phần đọc dành cho nhà đầu tư: nhìn hình, hiểu kết quả chính, rồi biết khi nào nên thận trọng. "
            "Phụ lục này có vai trò khác: nó là nơi kiểm tra lại độ bền của kết luận bằng các lát cắt dữ liệu chi tiết hơn.",
            _STYLES["Body"],
        )
    )
    story.append(
        _p(
            "Cách đọc phụ lục không phải là tìm thêm một con số đẹp để thay thế kết luận chính. Người đọc nên dùng nó như bộ lọc: "
            "nếu các bảng phụ lục cùng hướng với phần chính thì kết luận đáng tin hơn; nếu chúng phân tán hoặc mẫu mỏng thì cần hạ độ tự tin.",
            _STYLES["Body"],
        )
    )
    story.append(Paragraph("Bức tranh tổng quát", _STYLES["H2"]))
    story.append(_table(_general_statistics_rows(events, spec, ref), [4.1 * cm, 5.2 * cm, 7.0 * cm]))
    story.append(
        _p(
            "Bảng tổng quát là điểm neo để đọc toàn bộ phụ lục. Nó cho biết mẫu có đủ độ dày, đường đi có đủ dữ liệu, và các đại lượng chính có đang nhất quán với câu chuyện ở phần thân chương hay không.",
            _STYLES["Body"],
        )
    )
    story.append(Paragraph("Theo thanh khoản", _STYLES["H2"]))
    story.append(_table(_group_rows(events, "liquidity_bucket", str(spec.get("liquidity_group_title", "Thanh khoản")), spec), [3.2 * cm, 1.5 * cm, 2.1 * cm, 2.4 * cm, 2.0 * cm, 2.1 * cm, 2.1 * cm]))
    story.append(
        _p(
            "Lát cắt thanh khoản giúp phân biệt mẫu dễ đọc với mẫu chỉ đẹp trên giấy. Nếu nhóm thanh khoản thấp cho kết quả khác hẳn, người đọc không nên xem toàn mẫu như một kinh nghiệm triển khai đồng nhất.",
            _STYLES["Body"],
        )
    )
    story.append(Paragraph("Theo bối cảnh thị trường", _STYLES["H2"]))
    story.append(_table(_group_rows(events, "market_regime", str(spec.get("regime_group_title", "Bối cảnh")), spec), [3.2 * cm, 1.5 * cm, 2.1 * cm, 2.4 * cm, 2.0 * cm, 2.1 * cm, 2.1 * cm]))
    story.append(
        _p(
            "Lát cắt bối cảnh cho biết mẫu đang sống nhờ một pha thị trường cụ thể hay có thể đọc được rộng hơn. Khi một bối cảnh có ít mẫu, con số ở đó chỉ nên dùng như cảnh báo, không dùng để đảo ngược kết luận chính.",
            _STYLES["Body"],
        )
    )
    story.append(Paragraph("Theo nhóm cổ phiếu", _STYLES["H2"]))
    story.append(_table(_group_rows(events, "market_group", str(spec.get("market_group_title", "Nhóm")), spec), [3.2 * cm, 1.5 * cm, 2.1 * cm, 2.4 * cm, 2.0 * cm, 2.1 * cm, 2.1 * cm]))
    story.append(
        _p(
            "Lát cắt nhóm cổ phiếu cho thấy kết luận có bị kéo bởi một nhóm vốn hóa hoặc nhóm theo dõi nhất định hay không. Đây là lớp kiểm tra phạm vi sử dụng, không phải một cách chọn riêng nhóm có kết quả đẹp nhất.",
            _STYLES["Body"],
        )
    )
    story.append(Paragraph("Chất lượng dữ liệu", _STYLES["H2"]))
    story.append(_table(_data_quality_rows(events, ref), [4.2 * cm, 4.8 * cm, 7.3 * cm]))
    story.append(
        _p(
            "Bảng chất lượng dữ liệu trả lời câu hỏi: các kết quả hậu phá vỡ có được đo trên đường giá đủ liên tục hay không. Nếu dữ liệu thiếu, đứng giá nhiều hoặc chuỗi hậu phá vỡ mỏng, kết luận phải được đọc như ước lượng có điều kiện.",
            _STYLES["Body"],
        )
    )
    temporal_rows = _temporal_robustness_rows(ref)
    if len(temporal_rows) > 1:
        story.append(Paragraph("Độ bền theo thời gian", _STYLES["H2"]))
        story.append(_table(temporal_rows, [3.2 * cm, 1.5 * cm, 2.0 * cm, 2.4 * cm, 2.0 * cm, 2.0 * cm]))
        story.append(
            _p(
                "Bảng thời gian kiểm tra xem kết quả có tập trung vào một giai đoạn thuận lợi hay không. Một mẫu đáng tin hơn khi các giai đoạn khác nhau không đảo chiều hoàn toàn câu chuyện chính.",
                _STYLES["Body"],
            )
        )
    interaction_rows = _regime_liquidity_interaction_rows(ref)
    story.append(Paragraph("Tương tác bối cảnh và thanh khoản", _STYLES["H2"]))
    if len(interaction_rows) > 1:
        story.append(_table(interaction_rows, [2.4 * cm, 2.2 * cm, 1.4 * cm, 1.8 * cm, 2.3 * cm, 1.8 * cm, 1.8 * cm]))
        story.append(
            _p(
                "Bảng tương tác là lớp kiểm tra mạnh hơn từng lát cắt riêng lẻ. Nó cho biết kết quả có còn đọc được khi vừa xét bối cảnh thị trường vừa xét thanh khoản, hay chỉ tốt trong một nhóm nhỏ.",
                _STYLES["Body"],
            )
        )
    else:
        story.append(_p("Không có nhóm bối cảnh-thanh khoản nào đủ dày theo ngưỡng công bố; phần này được giữ như một cổng kiểm tra thay vì bị bỏ khỏi chương.", _STYLES["Body"]))
    story.append(Paragraph("Giới hạn phải ghi rõ", _STYLES["H2"]))
    for item in spec.get("caveat_bullets", []):
        story.append(_bullet(_public_term(item), _STYLES["Body"]))
    story.append(
        _p(
            "Các giới hạn này không làm mất giá trị của chương, nhưng chúng đặt ranh giới cho cách sử dụng. Khi thiếu dữ liệu theo từng thời điểm hoặc dữ liệu trạng thái chính thức, chương nên được đọc như tài liệu tham khảo trên phạm vi dữ liệu hiện có.",
            _STYLES["Body"],
        )
    )
    story.append(Paragraph("Cách dùng sau khi đọc phụ lục", _STYLES["H2"]))
    story.append(
        _table(
            [
                ["Nếu người đọc thấy", "Cách hiểu phù hợp"],
                ["Mẫu đạt mục tiêu cơ sở nhưng kéo ngược sâu", "Mẫu có lực tiếp diễn, nhưng chất lượng đường đi không gọn; cần đọc thận trọng hơn."],
                ["Mẫu đẹp hình thái nhưng thất bại 5%", "Hình thái chỉ là điều kiện đầu vào; xác nhận và đường đi sau đó mới quyết định hồ sơ thực tế."],
                ["Một nhóm bối cảnh có mẫu mỏng", "Không dùng nhóm đó để kết luận mạnh; chỉ xem như dấu hiệu cần kiểm tra thêm."],
                ["Bảng phụ lục khác phần diễn giải chính", "Ưu tiên phần diễn giải chính; phụ lục dùng để kiểm tra độ bền và giới hạn của kết luận."],
            ],
            [4.5 * cm, 11.8 * cm],
        )
    )
    story.append(
        _p(
            "Nói ngắn gọn, phần phụ lục không nhằm làm chương nặng thêm. Nó giúp người đọc biết khi nào nên tin phần chính nhiều hơn, và khi nào phải hạ độ tin cậy dù mẫu nhìn có vẻ đúng.",
            _STYLES["Body"],
        )
    )
    story.append(
        _callout(
            "Điểm đóng chương",
            [
                "Đọc hình thái trước: nếu mẫu không có cấu trúc rõ, không dùng thống kê để hợp thức hóa nó.",
                "Đọc mục tiêu theo nhiều tầng: mốc cơ sở là kỳ vọng thực tế hơn, mốc đầy đủ là kịch bản mạnh.",
                "Đọc thất bại như một phần của mẫu: ví dụ thất bại giúp hiểu ranh giới, không phải chi tiết phụ.",
                "Đọc giới hạn dữ liệu như điều kiện sử dụng: chương là tài liệu tham khảo, không phải hệ thống giao dịch tự động.",
            ],
        )
    )
    family_rows = spec.get("family_roadmap_rows") if spec.get("include_family_governance_in_pdf") else None
    if family_rows:
        story.append(Paragraph(str(spec.get("family_roadmap_title", "Lộ trình family")), _STYLES["H2"]))
        story.append(_table([["Mẫu hình", "Trạng thái", "Việc còn lại"], *list(family_rows)], [4.2 * cm, 4.2 * cm, 7.9 * cm]))
    contract_rows = spec.get("family_contract_rows") if spec.get("include_family_governance_in_pdf") else None
    if contract_rows:
        gate_rows = spec.get("release_gate_rows")
        block = [
            Paragraph("Contract nhân rộng family", _STYLES["H2"]),
            _table([["Lớp", "Nguyên tắc", "Cách khóa"], *list(contract_rows)], [3.0 * cm, 3.6 * cm, 9.7 * cm]),
        ]
        if gate_rows:
            block.extend(
                [
                    Paragraph("Release gate trước khi chốt", _STYLES["H2"]),
                    _table([["Cổng", "Điều kiện pass"], *list(gate_rows)], [3.5 * cm, 12.8 * cm]),
                ]
            )
        story.append(KeepTogether(block))
    return story


def _example_role_name(example_key: str) -> str:
    return {
        "textbook_success": "đạt mục tiêu",
        "middle_case": "trung vị",
        "failure": "thất bại",
    }.get(example_key, "minh họa")


def _walkthrough_title(event: Mapping[str, Any], example_key: str = "textbook_success") -> str:
    symbol = str(event.get("symbol") or "").strip()
    date = str(event.get("breakout_date") or "").strip()
    role = _example_role_name(example_key)
    if symbol and date:
        return f"Diễn biến ví dụ {role}: {symbol} ngày {date}"
    if symbol:
        return f"Diễn biến ví dụ {role}: {symbol}"
    return f"Diễn biến ví dụ {role}"


def _walkthrough_intro(event: Mapping[str, Any], example_key: str = "textbook_success") -> str:
    role = _example_role_name(example_key)
    symbol = str(event.get("symbol") or f"ví dụ {role}").strip()
    start = str(event.get("formation_start_date") or "không rõ ngày bắt đầu").strip()
    end = str(event.get("formation_end_date") or "không rõ ngày kết thúc").strip()
    breakout = str(event.get("breakout_date") or "không rõ ngày xác nhận").strip()
    price = _fmt(event.get("breakout_price"))
    target = _fmt(event.get("target_price"))
    return (
        f"Bảng dưới đây đọc lại biểu đồ ví dụ {role} ngay phía trên: {symbol}, "
        f"hình thành từ {start} đến {end}, xác nhận ngày {breakout} tại giá {price}, "
        f"với mục tiêu tham khảo {target}. Hãy đọc bảng này như chú giải cho chính biểu đồ đó."
    )


def _walkthrough_note(example_key: str, spec: Mapping[str, Any]) -> str:
    if example_key == "textbook_success":
        default = "Bảng này dẫn người đọc qua từng mốc của một mẫu thành công, nhưng không biến ví dụ thành chỉ dẫn mua bán."
    elif example_key == "middle_case":
        default = "Bảng này cho thấy một mẫu gần trung vị thường có cả tín hiệu đúng hướng lẫn giới hạn về độ xa của nhịp đi sau phá vỡ."
    elif example_key == "failure":
        default = "Bảng này giúp đọc thất bại như một phần tự nhiên của phân phối mẫu, không phải ngoại lệ cần bỏ qua."
    else:
        default = "Bảng này là chú giải cho biểu đồ ngay phía trên, không phải một khuyến nghị giao dịch."
    return _public_paragraph(spec.get(f"walkthrough_note_{example_key}", default))


def _sample_walkthrough_rows(event: Mapping[str, Any], spec: Mapping[str, Any], example_key: str = "textbook_success") -> list[list[Any]]:
    role = _example_role_name(example_key)
    custom_rows = spec.get("walkthrough_rows")
    if custom_rows:
        rows = [["Mốc đọc mẫu", "Dữ kiện", "Ý nghĩa"]]
        context = {
            "symbol": event.get("symbol"),
            "formation_start_date": event.get("formation_start_date"),
            "formation_end_date": event.get("formation_end_date"),
            "breakout_date": event.get("breakout_date"),
            "breakout_price": _fmt(event.get("breakout_price")),
            "target_price": _fmt(event.get("target_price")),
            "mfe_pct": _fmt(event.get("mfe_pct")),
            "mae_pct": _fmt(event.get("mae_pct")),
            "target_hit": _vi_bool(event.get("target_hit")),
            "failure_5pct": _vi_bool(event.get("failure_5pct")),
        }
        rows.append(
            [
                "Biểu đồ đang đọc",
                f"{context.get('symbol') or 'không rõ mã'} - {context.get('breakout_date') or 'không rõ ngày'}",
                f"Bảng này thuộc ví dụ {role} in ngay phía trên, không phải một mẫu mới.",
            ]
        )
        for label, datum_template, meaning_template in custom_rows:
            rows.append([str(label), str(datum_template).format(**context), str(meaning_template).format(**context)])
        return rows

    favorable, adverse = _event_metric_labels(spec, event)
    symbol = event.get("symbol") or "không rõ mã"
    breakout_date = event.get("breakout_date") or "không rõ ngày"
    return [
        ["Mốc đọc mẫu", "Dữ kiện", "Ý nghĩa"],
        ["Biểu đồ đang đọc", f"{symbol} - {breakout_date}", f"Bảng này thuộc ví dụ {role} in ngay phía trên, không phải một mẫu mới."],
        ["Bắt đầu mẫu", event.get("formation_start_date"), "Sau nhịp trước đó, giá bắt đầu hình thành cấu trúc mẫu."],
        ["Kết thúc mẫu", event.get("formation_end_date"), "Vùng hình thái kết thúc; chờ xác nhận phá vỡ."],
        ["Ngày xác nhận", event.get("breakout_date"), f"Giá phá vỡ {_fmt(event.get('breakout_price'))}; mục tiêu đầy đủ {_fmt(event.get('target_price'))}."],
        ["Đường đi sau đó", f"{favorable.capitalize()} {_fmt(event.get('mfe_pct'))}%; {adverse} {_fmt(event.get('mae_pct'))}%.", "Cho biết chất lượng đường đi sau phá vỡ."],
        ["Kết quả", f"Đạt mục tiêu: {_vi_bool(event.get('target_hit'))}; thất bại 5%: {_vi_bool(event.get('failure_5pct'))}.", "Ví dụ minh họa, không phải tín hiệu giao dịch."],
    ]


def _failure_rows(payload: Mapping[str, Any], events: pd.DataFrame, spec: Mapping[str, Any]) -> list[list[Any]]:
    ref = payload.get("chapter_reference") if isinstance(payload.get("chapter_reference"), Mapping) else {}
    target = payload.get("target_calibration") if isinstance(payload.get("target_calibration"), Mapping) else {}
    base = target.get("base_target") if isinstance(target.get("base_target"), Mapping) else {}
    adverse = _metric_label(spec, "adverse_move", "mức kéo ngược sâu nhất")
    structure_label = str(spec.get("failure_structure_label") or "Mẫu quá dài hoặc quá rộng")
    structure_note = str(
        spec.get("failure_structure_note")
        or "Mẫu kéo dài hoặc dao động quá rộng dễ gần kênh giá/vùng nhiễu hơn là một cấu trúc rõ."
    )
    return [
        ["Dạng thất bại", "Dấu hiệu trong dữ liệu", "Cách xử lý khi đọc chương"],
        ["Không đi đủ 5%", f"{_fmt(base.get('failure_5pct_rate') or ref.get('failure_5pct_rate'))}% mẫu không đạt ngưỡng tối thiểu.", "Không xem hình thái đẹp là đủ; phải kiểm tra hậu quả sau phá vỡ."],
        [f"{adverse.capitalize()} trước mục tiêu", f"Tỷ lệ đạt mục tiêu trước khi bị kéo ngược mạnh là {_fmt(base.get('target_first_before_adverse_5pct_rate'))}%.", "Ưu tiên thứ tự đường đi, không chỉ tỷ lệ đạt mục tiêu cuối kỳ."],
        [structure_label, f"Độ dài trung vị {_fmt(events['pattern_width_bars'].median(), 0)} phiên; chiều cao trung vị {_fmt(float(events['pattern_height_pct'].median()))}%.", structure_note],
        ["Mẫu phá ngược", "Được đo bằng trạng thái phá ngược và các ngưỡng rủi ro đại diện nếu có.", "Giúp phân biệt mẫu chậm với mẫu bị phủ nhận."],
    ]


def _reader_question_rows(payload: Mapping[str, Any], spec: Mapping[str, Any]) -> list[list[Any]]:
    ref = payload.get("chapter_reference") if isinstance(payload.get("chapter_reference"), Mapping) else {}
    target = payload.get("target_calibration") if isinstance(payload.get("target_calibration"), Mapping) else {}
    base = target.get("base_target") if isinstance(target.get("base_target"), Mapping) else {}
    legacy = target.get("legacy_target") if isinstance(target.get("legacy_target"), Mapping) else {}
    favorable = _metric_label(spec, "favorable_move", "mức tăng tốt nhất")
    adverse = _metric_label(spec, "adverse_move", "mức kéo ngược sâu nhất")
    base_label = _base_multiple_label(spec)
    legacy_label = _legacy_multiple_label(spec)
    return [
        ["Câu hỏi của người đọc", "Con số cần nhìn", "Cách đọc thực tế"],
        ["Mẫu có đi tiếp không?", f"{base_label} đạt {_fmt(base.get('target_hit_rate'))}%", f"{_target_focus_title(spec)} cho biết nhịp hậu phá vỡ có đủ sức theo mốc hiệu chuẩn chính hay không."],
        *(
            []
            if abs(_base_multiple(spec) - _legacy_multiple(spec)) < 1e-9
            else [["Mốc 1,0x nên đọc thế nào?", f"{legacy_label} đạt {_fmt(legacy.get('target_hit_rate'))}%", _target_full_reading(spec)]]
        ),
        ["Đường đi có gọn không?", f"{adverse.capitalize()} trung vị {_fmt(ref.get('median_mae_pct'))}%", f"Cần đọc cùng {favorable}; mẫu tốt là mẫu đi tiếp mà không kéo ngược quá sâu."],
        ["Mẫu sai bao nhiêu?", f"Thất bại 5% {_fmt(base.get('failure_5pct_rate') or ref.get('failure_5pct_rate'))}%", "Đây là lý do không được chỉ chọn ví dụ đẹp hoặc chỉ nhìn tỷ lệ đạt mục tiêu."],
    ]


def build_pattern_public_chapter(
    *,
    payload: Mapping[str, Any],
    source_notes: Mapping[str, Any],
    events: pd.DataFrame,
    path_df: pd.DataFrame,
    charts: Mapping[str, Path],
    spec: Mapping[str, Any],
    out_dir: Path,
    pdf_filename: str,
    payload_filename: str,
    manuscript_filename: str,
    notes_filename: str,
    family_factory_id: str = PUBLICATION_CORE_ID,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / pdf_filename
    payload_path = out_dir / payload_filename
    manuscript_path = out_dir / manuscript_filename
    notes_path = out_dir / notes_filename
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=1.45 * cm,
        rightMargin=1.45 * cm,
        topMargin=1.35 * cm,
        bottomMargin=1.25 * cm,
        title=f"{spec.get('title')} - Chương xuất bản",
        author="Codex",
    )
    enriched_payload = {
        **dict(payload),
        "publication_core_id": PUBLICATION_CORE_ID,
        "factory_id": family_factory_id,
        "example_events": payload.get("example_events", {}),
    }
    story = build_pattern_story(payload=enriched_payload, source_notes=source_notes, events=events, charts=charts, spec=spec)
    footer = _header_footer(str(spec.get("title", "Flag")))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    editorial = enriched_payload.get("editorial_sections") if isinstance(enriched_payload.get("editorial_sections"), Mapping) else {}
    manuscript_lines = [f"# Bản thảo diễn giải cho chương {spec.get('title')}", "", f"Family factory: `{family_factory_id}`", f"Publication core: `{PUBLICATION_CORE_ID}`", ""]
    for key in ["summary", "tour", "failure", "statistics", "post_breakout", "size_volume", "tactics", "checklist"]:
        values = editorial.get(key) or []
        if not values:
            continue
        manuscript_lines.extend([f"## {key}", ""])
        for value in values:
            manuscript_lines.extend([str(value), ""])
    manuscript_path.write_text("\n".join(manuscript_lines).strip() + "\n", encoding="utf-8")
    notes_path.write_text(
        "\n".join(
            [
                f"# Ghi chú chương {spec.get('title')}",
                "",
                f"Family factory: `{family_factory_id}`",
                f"Publication core: `{PUBLICATION_CORE_ID}`",
                "",
                "Bản này được dựng bằng family-specific factory đi qua publication core chung; core không chứa logic hình học mẫu hình.",
                "",
                f"PDF: `{pdf_path}`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    payload_path.write_text(json.dumps(enriched_payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return {"pdf": pdf_path, "payload": payload_path, "manuscript": manuscript_path, "notes": notes_path}


# Backward-compatible aliases for older build scripts. New code should import
# family factories instead of calling these names directly.
FACTORY_ID = PUBLICATION_CORE_ID
build_flag_story = build_pattern_story
build_flag_public_chapter = build_pattern_public_chapter
