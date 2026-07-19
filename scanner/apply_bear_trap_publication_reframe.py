"""Apply the bearish reclaim caution framing to bearish final chapters.

This is not a PDF builder.  It patches locked canonical payloads and manifest
entries so the existing canonical chapter factory can render the public PDFs
with the right reader framing.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.validate_final_chapters_manifest import DEFAULT_MANIFEST  # noqa: E402


REFRAME_ID = "bear_trap_stoploss_publication_reframe_v1"
LEGACY_REFRAME_FRAGMENTS = (
    REFRAME_ID,
    "bear-trap/stop-loss caution",
    "BUY signal",
    "short setup",
    "stop-loss cơ học",
    "Bảng stop-loss caution",
    "Cách đọc mới của chương này là quản lý bẫy giảm",
    "Thất bại quan trọng nhất của một phá vỡ giảm",
    "Bảng cảnh báo cắt lỗ bổ sung",
    "Khi phá vỡ giảm bị quay lại vùng phá vỡ",
    "Quy tắc sử dụng thực tế: theo dõi cửa sổ 5/10/20 phiên sau phá vỡ giảm",
    "Sau phá vỡ giảm, kiểm tra giá có đóng cửa quay lại vùng phá vỡ",
    "Nếu nhịp quay lại xảy ra nhanh",
    "Nếu sau nhịp quay lại xuất hiện phá vỡ giảm lần hai",
    "Không dùng lớp bear-trap/cắt lỗ",
)
DEFAULT_SUMMARY = Path("artifacts/scanner_v2/bear_trap_stoploss_caution/bear_trap_stoploss_caution_summary.csv")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bear_trap_stoploss_caution/publication_reframe")
BEAR_PATTERN_IDS = (
    "bear_flags",
    "bear_pennants",
    "triangles_descending",
    "double_tops_adam_adam",
    "double_tops_adam_eve",
    "double_tops_eve_adam",
    "double_tops_eve_eve",
    "head_and_shoulders_tops",
    "head_and_shoulders_tops_complex",
    "measured_move_down",
    "rectangle_tops",
    "broadening_tops",
    "pipe_tops",
    "triple_tops",
    "bump_and_run_reversal_tops",
    "rounding_tops",
    "horn_tops",
    "diamond_tops",
)
NEW_CLASSIFICATION = "hồ sơ quản lý bẫy giảm và kỷ luật cắt lỗ trong phạm vi dữ liệu hiện có"
NEW_CLAIM_LEVEL = "đọc như hồ sơ kiểm tra độ sạch của phá vỡ giảm, không phải tín hiệu mua hoặc bán khống tự động"
NEW_ROLE_NOTE = (
    "Dùng để kiểm tra bẫy giảm sau phá vỡ: quan sát giá đóng cửa quay lại vùng phá vỡ trong 5/10/20 phiên "
    "trước khi xem phá vỡ giảm là sạch; "
    "không phải tín hiệu mua hoặc bán khống tự động."
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def _load_summary(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = {row["pattern_id"]: row for row in csv.DictReader(handle) if row.get("pattern_id")}
    missing = sorted(set(BEAR_PATTERN_IDS) - set(rows))
    if missing:
        raise ValueError(f"bear-trap summary missing patterns: {missing}")
    return rows


def _pct(row: Mapping[str, str], key: str) -> str:
    value = row.get(key, "")
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "n/a"


def _num(row: Mapping[str, str], key: str) -> str:
    value = row.get(key, "")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if number.is_integer():
        return str(int(number))
    return f"{number:.1f}"


def _caution_label(row: Mapping[str, str]) -> str:
    severity = str(row.get("caution_severity") or "")
    if severity.startswith("high"):
        return "cao"
    if severity.startswith("moderate"):
        return "vừa"
    if severity.startswith("limited"):
        return "thấp"
    return "chưa phân loại"


def _has_reframe(sections: Mapping[str, Any]) -> bool:
    return False


def _remove_previous_reframe(sections: Mapping[str, Any]) -> bool:
    changed = False
    for key, value in list(sections.items()):
        if not isinstance(value, list):
            continue
        filtered = [
            item
            for item in value
            if REFRAME_ID not in str(item)
            and not any(fragment in str(item) for fragment in LEGACY_REFRAME_FRAGMENTS)
        ]
        if len(filtered) != len(value):
            sections[key] = filtered
            changed = True
    return changed


def _append_once(items: list[Any], text: str) -> None:
    marker = REFRAME_ID
    if not any(marker in str(item) for item in items):
        items.append(text)


def _patch_editorial_sections(payload: dict[str, Any], row: Mapping[str, str]) -> bool:
    sections = payload.get("editorial_sections")
    if not isinstance(sections, dict):
        raise ValueError(f"{payload.get('pattern_id')} payload missing editorial_sections")
    removed = _remove_previous_reframe(sections)

    source_events = _num(row, "source_events")
    caution_events = _num(row, "caution_events")
    reclaim_20 = _pct(row, "failed_breakdown_reclaim_20d_rate_pct")
    reclaim_10 = _pct(row, "fast_reclaim_10d_rate_pct")
    reclaim_bar = _num(row, "median_reclaim_bar")
    second_breakdown = _pct(row, "second_breakdown_after_reclaim_20d_rate_pct")
    severity = _caution_label(row)

    def section(name: str) -> list[Any]:
        value = sections.get(name)
        if not isinstance(value, list):
            value = []
            sections[name] = value
        return value

    summary = (
        "Cách đọc mới của chương này là quản lý bẫy giảm sau phá vỡ, "
        f"không phải gắn nhãn phòng thủ một cách chung chung. Trong {source_events} sự kiện có thể đo, "
        f"{caution_events} sự kiện có dữ liệu quay lại vùng phá vỡ để kiểm tra. Tỷ lệ giá đóng cửa quay lại trên vùng phá vỡ "
        f"trong 20 phiên là {reclaim_20}, trong 10 phiên là {reclaim_10}; mức cảnh báo cắt lỗ được xếp loại {severity}."
    )
    failure = (
        "Thất bại quan trọng nhất của một phá vỡ giảm không chỉ là giá không giảm tiếp, "
        f"mà là cú quay lại vùng phá vỡ quá nhanh khiến người đọc nhầm phá vỡ giảm thành tín hiệu sạch. "
        f"Trung vị thời gian quay lại vùng phá vỡ là {reclaim_bar} phiên. Sau nhịp quay lại này, tỷ lệ xuất hiện "
        f"một nhịp phá vỡ giảm thứ hai trong 20 phiên là {second_breakdown}, vì vậy nó không tự động biến mẫu "
        "thành cơ hội mua; nó chủ yếu cảnh báo rằng cắt lỗ máy móc dễ bị quét."
    )
    statistics = (
        "Bảng cảnh báo cắt lỗ bổ sung một câu hỏi thực dụng cho số liệu hậu phá vỡ: "
        f"nếu giá phá xuống, bao lâu thì nó quay lại vùng phá vỡ? Với mẫu này, tỷ lệ quay lại trong 20 phiên là {reclaim_20} "
        f"và trong 10 phiên là {reclaim_10}. Con số này nên được đọc cùng mức thuận lợi, mức bất lợi và thứ tự chạm mục tiêu, "
        "không thay thế các thống kê gốc của chapter."
    )
    post_breakout = (
        "Khi phá vỡ giảm bị quay lại vùng phá vỡ, chương nên được đọc như hồ sơ kiểm tra độ sạch của nhịp giảm. "
        "Nếu giá đóng cửa quay lại trên vùng phá vỡ trong vài phiên đầu, tín hiệu giảm đã yếu đi và việc cắt lỗ/thoát vị thế "
        "cần tránh phản ứng máy móc. Nếu nhịp quay lại thất bại rồi giá phá xuống lần hai, rủi ro giảm vẫn còn nhưng đã chuyển "
        "sang một đường đi nhiều nhiễu hơn."
    )
    tactics = (
        "Quy tắc sử dụng thực tế: theo dõi cửa sổ 5/10/20 phiên sau phá vỡ giảm. "
        "Không xem nhịp quay lại vùng phá vỡ là tín hiệu mua mới; hãy dùng nó để đánh giá lại kỷ luật cắt lỗ, "
        "độ sạch của phá vỡ, và khả năng phá vỡ ban đầu chỉ là bẫy giảm."
    )
    checklist = [
        "Sau phá vỡ giảm, kiểm tra giá có đóng cửa quay lại vùng phá vỡ trong 5/10/20 phiên không.",
        "Nếu nhịp quay lại xảy ra nhanh, hạ độ tin cậy của phá vỡ giảm sạch thay vì lập tức đảo chiều sang luận điểm mua.",
        "Nếu sau nhịp quay lại xuất hiện phá vỡ giảm lần hai, ghi nhận rủi ro giảm vẫn tồn tại nhưng đường đi đã nhiễu hơn.",
        "Không dùng lớp cảnh báo bẫy giảm như tín hiệu mua hoặc tín hiệu bán khống tự động.",
    ]

    _append_once(section("summary"), summary)
    _append_once(section("failure"), failure)
    _append_once(section("statistics"), statistics)
    _append_once(section("post_breakout"), post_breakout)
    _append_once(section("tactics"), tactics)
    current_checklist = section("checklist")
    for item in checklist:
        if item not in current_checklist:
            current_checklist.append(item)
    return True or removed


def _patch_payload(payload: dict[str, Any], row: Mapping[str, str]) -> dict[str, Any]:
    changed = False
    for key, value in {
        "classification": NEW_CLASSIFICATION,
        "claim_level": NEW_CLAIM_LEVEL,
        "role_note": NEW_ROLE_NOTE,
        "bear_trap_publication_reframe_id": REFRAME_ID,
    }.items():
        if payload.get(key) != value:
            payload[key] = value
            changed = True
    caution = {
        "layer_id": "bear_trap_stoploss_caution_layer_v1",
        "pattern_id": row.get("pattern_id"),
        "source_events": int(float(row.get("source_events") or 0)),
        "caution_events": int(float(row.get("caution_events") or 0)),
        "failed_breakdown_reclaim_20d_rate_pct": float(row.get("failed_breakdown_reclaim_20d_rate_pct") or 0.0),
        "fast_reclaim_10d_rate_pct": float(row.get("fast_reclaim_10d_rate_pct") or 0.0),
        "fast_reclaim_5d_rate_pct": float(row.get("fast_reclaim_5d_rate_pct") or 0.0),
        "median_reclaim_bar": float(row.get("median_reclaim_bar") or 0.0),
        "second_breakdown_after_reclaim_20d_rate_pct": float(row.get("second_breakdown_after_reclaim_20d_rate_pct") or 0.0),
        "caution_severity": row.get("caution_severity"),
        "decision": row.get("decision"),
        "tradable_promotion_allowed": False,
        "reader_role": "stop_loss_caution_not_buy_signal",
    }
    if payload.get("bear_trap_stoploss_caution") != caution:
        payload["bear_trap_stoploss_caution"] = caution
        changed = True
    scope = payload.get("data_scope_and_caveats")
    if not isinstance(scope, dict):
        scope = {}
        payload["data_scope_and_caveats"] = scope
        changed = True
    caveats = scope.get("remaining_caveats")
    if not isinstance(caveats, list):
        caveats = []
        scope["remaining_caveats"] = caveats
        changed = True
    note = "Lớp cảnh báo bẫy giảm chỉ đo reclaim sau phá vỡ giảm; không chuyển chapter thành tín hiệu mua hoặc bán khống tự động."
    if note not in caveats:
        caveats.append(note)
        changed = True
    changed = _patch_editorial_sections(payload, row) or changed
    return {"changed": changed, "payload": payload}


def _patch_manifest_entry(entry: dict[str, Any], row: Mapping[str, str]) -> bool:
    changed = False
    updates = {
        "classification": NEW_CLASSIFICATION,
        "claim_level": NEW_CLAIM_LEVEL,
        "bear_trap_publication_reframe_id": REFRAME_ID,
        "bear_trap_stoploss_caution_layer_id": "bear_trap_stoploss_caution_layer_v1",
        "bear_trap_reclaim_20d_rate_pct": float(row.get("failed_breakdown_reclaim_20d_rate_pct") or 0.0),
        "bear_trap_fast_reclaim_10d_rate_pct": float(row.get("fast_reclaim_10d_rate_pct") or 0.0),
        "bear_trap_second_breakdown_after_reclaim_20d_rate_pct": float(row.get("second_breakdown_after_reclaim_20d_rate_pct") or 0.0),
    }
    for key, value in updates.items():
        if entry.get(key) != value:
            entry[key] = value
            changed = True
    note = str(entry.get("note") or "").strip()
    new_note = "Chapter giảm giá được đọc theo lớp quản lý bẫy giảm và kỷ luật cắt lỗ; không phải tín hiệu mua hoặc bán khống tự động."
    if note != new_note:
        entry["note"] = new_note
        changed = True
    return changed


def apply_reframe(*, manifest_path: Path = DEFAULT_MANIFEST, summary_path: Path = DEFAULT_SUMMARY, out_dir: Path = DEFAULT_OUT_DIR) -> dict[str, Any]:
    summary_rows = _load_summary(summary_path)
    manifest = _read_json(manifest_path)
    chapters = manifest.get("chapters")
    if not isinstance(chapters, list):
        raise ValueError(f"{manifest_path} missing chapters list")
    by_pattern = {
        str(entry.get("pattern_id")): entry
        for entry in chapters
        if isinstance(entry, dict) and entry.get("pattern_id")
    }
    missing = sorted(set(BEAR_PATTERN_IDS) - set(by_pattern))
    if missing:
        raise ValueError(f"final manifest missing bear chapters: {missing}")

    reports: list[dict[str, Any]] = []
    changed_manifest = False
    for pattern_id in BEAR_PATTERN_IDS:
        entry = by_pattern[pattern_id]
        row = summary_rows[pattern_id]
        payload_path = Path(str(entry.get("payload") or ""))
        if not payload_path.exists():
            raise FileNotFoundError(payload_path)
        payload = _read_json(payload_path)
        patched = _patch_payload(payload, row)
        if patched["changed"]:
            _write_json(payload_path, patched["payload"])
        entry_changed = _patch_manifest_entry(entry, row)
        changed_manifest = changed_manifest or entry_changed
        reports.append(
            {
                "pattern_id": pattern_id,
                "payload": str(payload_path),
                "payload_changed": bool(patched["changed"]),
                "manifest_changed": bool(entry_changed),
                "reclaim_20d_rate_pct": row.get("failed_breakdown_reclaim_20d_rate_pct"),
                "caution_severity": row.get("caution_severity"),
            }
        )

    if changed_manifest:
        _write_json(manifest_path, manifest)

    report = {
        "reframe_id": REFRAME_ID,
        "status": "PASS",
        "manifest": str(manifest_path),
        "summary": str(summary_path),
        "pattern_count": len(BEAR_PATTERN_IDS),
        "changed_manifest": changed_manifest,
        "patterns": reports,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "bear_trap_publication_reframe_report.json", report)
    lines = [
        "# Bear-Trap Publication Reframe",
        "",
        f"Reframe ID: `{REFRAME_ID}`",
        f"Status: `{report['status']}`",
        "",
        "| Pattern | Payload changed | Manifest changed | Reclaim 20d | Severity |",
        "|---|---:|---:|---:|---|",
    ]
    for item in reports:
        lines.append(
            f"| {item['pattern_id']} | {item['payload_changed']} | {item['manifest_changed']} | "
            f"{item['reclaim_20d_rate_pct']} | {item['caution_severity']} |"
        )
    (out_dir / "bear_trap_publication_reframe_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Patch bearish final chapters with bearish reclaim caution framing.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    report = apply_reframe(manifest_path=Path(args.manifest), summary_path=Path(args.summary), out_dir=Path(args.out_dir))
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
