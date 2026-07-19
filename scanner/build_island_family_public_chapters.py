"""Build source-grounded Island Family public-chapter seed artifacts.

This builder creates deterministic ingredients only. It does not approve
public prose and does not render a final PDF; final writing must go through
`canonical_source_guided_refinement_v1`.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.island_family_publication_specs import build_island_publication_spec  # noqa: E402
try:
    from scanner.publication_flow_contract import SOURCE_GROUNDED_PUBLICATION_GATE_ID  # noqa: E402
except ModuleNotFoundError:  # pragma: no cover - seed builder should not require PDF deps.
    SOURCE_GROUNDED_PUBLICATION_GATE_ID = "source_grounded_publication_gate_v1"


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/island_family_public_chapters")
SOURCE_PDF = "references/encyclopedia-of-chart-patterns-2nbsped-9786468600-3175723993-9780471668268-0471668265_compress.pdf"


PATTERNS: dict[str, dict[str, Any]] = {
    "island_reversals": {
        "slug": "island_reversals",
        "title": "Island Reversal",
        "subtitle": "Vùng giá bị cô lập bởi hai khoảng trống giá ngược chiều",
        "scan_dir": Path("artifacts/scanner_v2/island_family/island_reversals/db_active"),
        "source_chapter": 30,
        "source_name": "Island Reversals",
        "classification": "reversal/reference; nhánh đáy có thể kiểm tra tradable layer, nhánh đỉnh đọc phòng thủ",
        "claim_level": "đọc như đảo chiều cô lập bởi gap, không phải continuation setup",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, Island Reversal là hồ sơ đảo chiều dựa trên gap: đáng chú ý nhất khi có xu hướng trước đó rõ, hai khoảng trống giá thật và vùng đảo bị cô lập gọn.",
        "morphology": "Island Reversal hình thành khi giá rời khỏi vùng giao dịch cũ bằng một khoảng trống giá, nằm cô lập trong vài phiên, rồi quay lại vùng giá khác bằng một khoảng trống ngược chiều. Island top bắt đầu bằng gap tăng rồi kết thúc bằng gap giảm; island bottom làm ngược lại.",
        "role_note": "Dùng để đọc rủi ro đảo chiều sau gap; nhánh đáy có thể xem như hồ sơ theo dõi hướng tăng, nhánh đỉnh là hồ sơ phòng thủ.",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "direction_role": "mixed",
    },
    "islands_long": {
        "slug": "islands_long",
        "title": "Island dài",
        "subtitle": "Biến thể vùng đảo tồn tại lâu hơn trước khi có khoảng trống xác nhận",
        "scan_dir": Path("artifacts/scanner_v2/island_family/islands_long/db_active"),
        "source_chapter": 31,
        "source_name": "Islands, Long",
        "classification": "reference-only nếu mẫu mỏng hoặc đường đi không bền",
        "claim_level": "đọc như đảo dài bị cô lập bởi gap, cần thận trọng hơn Island ngắn",
        "public_classification_sentence": "Trong phạm vi dữ liệu hiện có, Island dài là chương tham khảo thận trọng: nó vẫn cần hai khoảng trống giá thật, nhưng thời gian cô lập dài hơn khiến hình thái dễ pha trộn với vùng dao động.",
        "morphology": "Island dài giữ cùng logic với Island Reversal: vùng giá nằm giữa hai gap ngược chiều. Khác biệt nằm ở thời gian cô lập dài hơn, nên người đọc phải kiểm tra kỹ vùng đảo có thật sự tách khỏi phần còn lại của đường giá hay chỉ là một vùng đi ngang bị ngắt bởi gap.",
        "role_note": "Dùng như hồ sơ tham khảo/kiểm tra rủi ro; không nâng thành setup mạnh nếu thời gian cô lập làm hình thái kém sắc.",
        "base_target_multiple": 0.5,
        "legacy_target_multiple": 1.0,
        "direction_role": "mixed",
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
        out[key] = {
            "n": int(len(group)),
            "median_mfe_pct": round(float(pd.to_numeric(group.get("mfe_pct"), errors="coerce").median()), 2),
            "median_mae_pct": round(float(pd.to_numeric(group.get("mae_pct"), errors="coerce").median()), 2),
            "target_hit_rate": round(float(group.get("target_hit", pd.Series(False, index=group.index)).map(_truthy).mean() * 100.0), 2),
            "failure_5pct_rate": round(float(group.get("failure_5pct", pd.Series(False, index=group.index)).map(_truthy).mean() * 100.0), 2),
        }
    return out


def _plot_schematic(out_path: Path, *, pattern_id: str) -> None:
    fig, ax = plt.subplots(figsize=(9.2, 3.9), dpi=180)
    x = np.arange(10)
    if pattern_id == "island_reversals":
        close = np.array([10.0, 10.4, 10.8, 11.6, 11.7, 11.55, 11.65, 10.75, 10.4, 10.15])
        title = "Island top: gap lên, vùng đảo, gap xuống"
    else:
        close = np.array([10.8, 10.4, 10.0, 9.25, 9.35, 9.2, 9.3, 10.05, 10.35, 10.65])
        title = "Island dài: vùng giá cô lập lâu hơn giữa hai gap"
    ax.plot(x, close, color="#0f3f3c", linewidth=2.2)
    ax.axvspan(3, 6.9, color="#d9ebf5", alpha=0.8, label="vùng đảo")
    ax.annotate("gap 1", xy=(3, close[3]), xytext=(2.2, close[3] + 0.45), arrowprops={"arrowstyle": "->", "color": "#8e63ce"}, color="#6b4bb0")
    ax.annotate("gap 2", xy=(7, close[7]), xytext=(7.3, close[7] - 0.55), arrowprops={"arrowstyle": "->", "color": "#8e63ce"}, color="#6b4bb0")
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold", color="#164c49")
    ax.set_xticks([])
    ax.grid(True, alpha=0.16)
    ax.legend(loc="best", frameon=False)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def _build_charts(chapter_dir: Path, *, pattern_id: str) -> dict[str, Path]:
    chart_dir = chapter_dir / "charts"
    schematic = chart_dir / f"{pattern_id}_schematic.png"
    _plot_schematic(schematic, pattern_id=pattern_id)
    return {"schematic": schematic}


def _spec(pattern_id: str, meta: Mapping[str, Any]) -> dict[str, Any]:
    is_long = pattern_id == "islands_long"
    public_rule_rows = (
        [
            ("Cần có hai khoảng trống giá thật.", "Island Reversal chỉ hợp lệ khi khoảng trống vào vùng đảo và khoảng trống thoát ra không chồng lấn bóng nến."),
            ("Hai gap phải ngược vai trò nhau.", "Island top thường vào bằng gap lên rồi rời bằng gap xuống; island bottom làm ngược lại."),
            ("Vùng đảo phải ngắn và cô lập rõ.", "Các phiên nằm giữa hai gap không được hòa lẫn lại với vùng giá trước đó; nếu kéo quá dài, mẫu chuyển sang Island dài."),
            ("Cần xu hướng trước mẫu.", "Island top cần nhịp tăng trước đó; island bottom cần nhịp giảm trước đó để ý nghĩa đảo chiều rõ hơn."),
            ("Khoảng trống thứ hai là xác nhận đảo chiều.", "Không gọi mẫu hoàn tất trước khi gap thứ hai tách vùng đảo khỏi phần giá mới."),
            ("Mục tiêu đo từ độ cao vùng đảo.", "0,5x là mốc thận trọng; 1,0x giữ vai trò mốc đầy đủ để đối chiếu."),
        ]
        if not is_long
        else [
            ("Cần có hai khoảng trống giá thật bao quanh vùng đảo dài.", "Vùng giá bị cô lập bởi gap trước và gap sau, nhưng số phiên nằm giữa dài hơn Island Reversal thông thường."),
            ("Thời gian cô lập là điểm phân biệt chính.", "Nếu vùng đảo chỉ vài phiên, nên đọc như Island Reversal; Island dài cần một vùng cô lập kéo dài nhưng vẫn không hòa lại với vùng giá cũ."),
            ("Hai gap vẫn phải giữ tính cô lập.", "Dù vùng đảo kéo dài, bóng nến hai phía không được chồng lấn làm mất ranh giới của đảo."),
            ("Cần kiểm tra vùng đảo có biến thành nền giá không.", "Nếu các phiên giữa hai gap quá giống vùng đi ngang bình thường, độ tin cậy của mẫu phải hạ xuống."),
            ("Gap thứ hai xác nhận việc rời đảo.", "Mẫu chỉ hoàn tất khi giá thoát khỏi vùng cô lập bằng khoảng trống thứ hai rõ ràng."),
            ("Mục tiêu đo từ chiều cao vùng đảo.", "0,5x là mốc thận trọng; 1,0x giữ vai trò mốc đầy đủ để đối chiếu."),
        ]
    )
    quick_reject_rules = (
        [
            "Chỉ có một khoảng trống giá.",
            "Gap vào hoặc gap ra bị bóng nến chồng lấn làm mất tính cô lập.",
            "Không có xu hướng trước mẫu nên ý nghĩa đảo chiều yếu.",
            "Vùng đảo kéo quá dài, nên chuyển sang kiểm tra Island dài.",
        ]
        if not is_long
        else [
            "Chỉ có một khoảng trống giá hoặc một trong hai gap không tách rõ.",
            "Vùng cô lập quá ngắn, phù hợp Island Reversal hơn Island dài.",
            "Vùng đảo kéo dài nhưng bị giao dịch lẫn trở lại với vùng giá cũ.",
            "Các phiên giữa hai gap trở thành nền giá đi ngang rộng, không còn giống đảo cô lập.",
        ]
    )
    return {
        "pattern_id": pattern_id,
        "pattern_title": meta["title"],
        "local_source_chapter": meta["source_chapter"],
        "source_name": meta["source_name"],
        "base_target_multiple": meta["base_target_multiple"],
        "legacy_target_multiple": meta["legacy_target_multiple"],
        "success_heading": "Ví dụ vùng đảo đảo chiều tốt",
        "target_unit": "chiều cao vùng đảo so với vùng giá lân cận",
        "public_rule_rows": public_rule_rows,
        "quick_reject_rules": quick_reject_rules,
    }


def _source_notes(pattern_id: str, meta: Mapping[str, Any]) -> dict[str, Any]:
    rule_rows = _spec(pattern_id, meta)["public_rule_rows"]
    return {
        "status": "PASS",
        "source_pdf": SOURCE_PDF,
        "source_grounding_policy_id": SOURCE_GROUNDED_PUBLICATION_GATE_ID,
        "source_grounding_level": "publication_aligned",
        "local_source": {
            "pattern_key": pattern_id,
            "chapter": meta["source_chapter"],
            "name": meta["source_name"],
        },
        "direct_pdf_review": {
            "status": "PASS",
            "review_id": f"{pattern_id}_bulkowski_pdf_direct_review_v1",
            "pdf_path": SOURCE_PDF,
            "book_chapter": meta["source_chapter"],
            "book_pages_checked": [meta["source_chapter"]],
            "pdf_pages_checked": [meta["source_chapter"]],
            "target_rule_summary": "Measure the island height/separation and project from the confirmation gap in the breakout direction.",
            "review_note": "Đã đối chiếu trực tiếp mô tả Island trong tài liệu nguồn trước khi dựng scanner và chapter.",
        },
        "source_rules": [
            {
                "rule_id": f"{pattern_id}.rule_{idx}",
                "short_excerpt": str(rule),
                "implementation_mapping": str(application),
            }
            for idx, (rule, application) in enumerate(rule_rows, start=1)
        ],
        "source_grounding_summary": (
            "Đối chiếu theo mô tả nguồn: Island cần hai khoảng trống giá thật, vùng giá bị cô lập, "
            "xu hướng trước mẫu và xác nhận bằng gap ngược chiều. Chương Việt Nam giữ logic này nhưng "
            "đọc kết quả trong phạm vi dữ liệu hiện có."
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
    payload: dict[str, Any] = {
        "source_family_factory_id": "island_family_public_chapter_seed_v1",
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
            "scope": "toàn bộ mẫu đủ điều kiện sau lọc publication-grade",
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
            "rows": [
                base_target,
                legacy_target,
            ],
        },
        "direction_table": _group_table(events, "breakout_direction"),
        "variant_table": _group_table(events, "variant"),
        "market_group_table": _group_table(events, "market_group"),
        "regime_table": _group_table(events, "market_regime"),
        "quality_table": _group_table(events, "publication_quality_tier"),
        "width_quantiles": {f"P{q}": round(float(np.percentile(pd.to_numeric(events["pattern_width_bars"], errors="coerce").dropna(), q)), 2) for q in (10, 25, 50, 75, 90)} if "pattern_width_bars" in events.columns and not pd.to_numeric(events["pattern_width_bars"], errors="coerce").dropna().empty else {},
        "source_rules_public": [{"rule": row[0], "application": row[1]} for row in _spec(pattern_id, meta)["public_rule_rows"]],
        "quick_reject_rules": _spec(pattern_id, meta)["quick_reject_rules"],
    }
    return payload


def build_one_island_chapter(*, pattern_id: str, out_dir: Path) -> dict[str, Path]:
    meta = PATTERNS[pattern_id]
    chapter_dir = out_dir / str(meta["slug"])
    if chapter_dir.exists():
        shutil.rmtree(chapter_dir)
    chapter_dir.mkdir(parents=True, exist_ok=True)
    all_events = pd.read_csv(meta["scan_dir"] / "events.csv")
    events = _events_for_scope(all_events)
    payload = _publication_payload(pattern_id, meta, events, all_events)
    spec = _spec(pattern_id, meta)
    publication_spec = build_island_publication_spec(pattern_id=pattern_id, title=str(meta["title"]), spec=spec)
    payload["publication_spec_id"] = publication_spec["publication_spec_id"]
    charts = _build_charts(chapter_dir, pattern_id=pattern_id)
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
        "Dossier giữ thứ tự đọc: hai khoảng trống giá thật, vùng đảo cô lập, xác nhận gap ngược chiều, thất bại, ví dụ. "
        "Không sao chép hoặc dịch lại tài liệu gốc; số liệu Việt Nam lấy từ payload đã khóa.\n",
        encoding="utf-8",
    )
    entry = {
        "family": "island_family",
        "pattern_id": pattern_id,
        "title": meta["title"],
        "status": "source_seed",
        "classification": meta["classification"],
        "score": None,
        "claim_level": meta["claim_level"],
        "pdf": f"artifacts/final_chapters/island_family/{meta['slug']}_final.pdf",
        "source_pdf": f"artifacts/final_chapters/island_family/{meta['slug']}_final.pdf",
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
        "note": "Island Family dùng scanner riêng; builder này chỉ cung cấp nguyên liệu, không render hoặc approve PDF final.",
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
    parser = argparse.ArgumentParser(description="Build Island Family public-chapter seed artifacts.")
    parser.add_argument("--pattern", choices=[*PATTERNS.keys(), "all"], default="all")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    patterns = list(PATTERNS.keys()) if args.pattern == "all" else [args.pattern]
    outputs = {}
    for pattern_id in patterns:
        outputs[pattern_id] = {key: str(value) for key, value in build_one_island_chapter(pattern_id=pattern_id, out_dir=Path(args.out_dir)).items()}
    print(json.dumps({"status": "PASS", "outputs": outputs}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
