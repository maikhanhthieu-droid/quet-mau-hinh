"""Deterministic reports for human review and Telegram delivery."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd


def write_reports(
    candidates: Iterable[Mapping[str, Any]],
    *,
    output_dir: Path,
    metadata: Mapping[str, Any],
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [dict(candidate) for candidate in candidates]
    frame = pd.DataFrame(rows)
    json_path = output_dir / "signals.json"
    csv_path = output_dir / "signals.csv"
    md_path = output_dir / "signals.md"
    meta_path = output_dir / "run_metadata.json"
    json_path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    if frame.empty:
        frame = pd.DataFrame(columns=["symbol", "pattern_id", "setup_score"])
    frame.to_csv(csv_path, index=False)
    lines = [
        "# VN100 accumulation scan",
        "",
        f"As-of: `{metadata.get('as_of_date', '')}`",
        f"Universe: `{metadata.get('universe_count', 0)} mã VN100`",
        f"Candidates: `{len(rows)}`",
        "",
        "| Mã | Mẫu hình | Trạng thái | Khoảng cách breakout | Điểm |",
        "|---|---|---|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row.get('symbol')} | {row.get('pattern_name_vi', row.get('pattern_name'))} | {row.get('status')} | "
            f"{row.get('distance_to_breakout_pct')}% | {row.get('setup_score')} |"
        )
    if not rows:
        lines.append("| – | Không có ứng viên đạt điều kiện | – | – | – |")
    lines.extend(
        [
            "",
            "> Đây là danh sách nghiên cứu mẫu hình đang hình thành, không phải khuyến nghị mua bán.",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    meta_path.write_text(
        json.dumps(dict(metadata), ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return {
        "json": json_path,
        "csv": csv_path,
        "markdown": md_path,
        "metadata": meta_path,
    }


def deterministic_message(
    candidates: Iterable[Mapping[str, Any]],
    *,
    as_of: date | str,
    warnings: Iterable[str] = (),
) -> str:
    rows = list(candidates)
    lines = [
        f"📊 VN100 TÍCH LŨY — {as_of}",
        f"Ứng viên: {len(rows)} | Dữ liệu đến phiên hoàn tất gần nhất",
        "",
    ]
    for index, row in enumerate(rows, start=1):
        lines.extend(
            [
                f"{index}. {row.get('symbol')} — {row.get('pattern_name_vi', row.get('pattern_name'))} ({row.get('status')})",
                f"   Giá {row.get('close')} | Cản {row.get('resistance')} | Cách breakout {row.get('distance_to_breakout_pct')}%",
                f"   Điểm {row.get('setup_score')} | Nền {row.get('base_days')} phiên | Vol {row.get('volume_ratio_5_20')}x",
            ]
        )
    if not rows:
        lines.append("Không có mẫu hình tích lũy đạt ngưỡng hôm nay.")
    warning_rows = [str(value) for value in warnings if str(value).strip()]
    if warning_rows:
        lines.extend(["", "⚠️ Cảnh báo:"])
        lines.extend(f"- {value}" for value in warning_rows[:5])
    lines.extend(["", "⚠️ Danh sách nghiên cứu, không phải khuyến nghị mua bán."])
    return "\n".join(lines)
