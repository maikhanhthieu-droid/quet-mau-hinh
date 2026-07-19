"""Build the Edition 1.1 editorial inventory and prompt pack.

This is the front door for the next book-wide writing pass.  It does not call
DeepSeek and it does not render PDFs.  Its job is to freeze the 63-chapter input
set, classify each chapter's reader role, collect the locked artifacts that the
AI writer is allowed to see, and emit a single runbook for the DeepSeek +
Codex-postedit + canonical-factory flow.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.canonical_editorial_layer import REQUIRED_EDITORIAL_SECTIONS, validate_canonical_editorial_sections  # noqa: E402
from scanner.canonical_editorial_workflow import PUBLIC_CHAPTER_STYLE_BLUEPRINT  # noqa: E402
from scanner.run_canonical_deepseek_bull_flag_editorial import BULKOWSKI_SOURCE_GUIDED_READER_PROFILE  # noqa: E402
from scanner.validate_final_chapters_manifest import DEFAULT_MANIFEST  # noqa: E402


PACK_ID = "edition_1_1_deepseek_editorial_pack_v1"
DEFAULT_OUT_DIR = Path("artifacts/final_chapters/edition_1_1")
DEFAULT_GOVERNANCE = Path("artifacts/final_chapters/governance/chapter_governance_matrix.json")
DEFAULT_PREFLIGHT = Path("artifacts/final_chapters/governance/chapter_tradable_preflight_matrix.json")
DEFAULT_RANKINGS = Path("artifacts/final_chapters/book_level/aggregate_practical_rankings.json")
DEFAULT_AFTER_BUY_PACK = Path("artifacts/scanner_v2/after_buy_vietnam_v2/after_buy_deep_integration_pack.json")
DEFAULT_AFTER_BUY_COVERAGE = Path("artifacts/scanner_v2/after_buy_vietnam_v2/after_buy_chapter_coverage_matrix.json")

ROLE_PRIORITY = ("buy", "watchlist", "bear_trap_caution", "defensive", "research_only")

FORBIDDEN_PUBLIC_TERMS = (
    "approved_human_sections",
    "fallback",
    "MFE",
    "MAE",
    "target-hit",
    "target-first",
    "scanner",
    "pipeline",
    "proxy",
    "available-series",
    "holdout",
    "validation",
    "backtest",
    "profit factor",
    "BUY signal",
    "short setup",
    "tín hiệu mua",
    "tín hiệu bán",
    "khuyến nghị mua",
    "khuyến nghị bán",
    "vào lệnh",
    "cắt lỗ",
    "dừng lỗ",
)


def _read_json(path: Path) -> Any:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[Mapping[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _extract_pdf_text(pdf: Path, out_path: Path) -> tuple[str | None, int]:
    if not pdf.exists() or shutil.which("pdftotext") is None:
        return None, 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["pdftotext", "-layout", str(pdf), str(out_path)], check=True)
    text = out_path.read_text(encoding="utf-8", errors="replace")
    return str(out_path), len(text)


def _load_manifest(path: Path) -> list[Mapping[str, Any]]:
    payload = _read_json(path)
    chapters = payload.get("chapters") if isinstance(payload, Mapping) else []
    return [chapter for chapter in chapters if isinstance(chapter, Mapping)]


def _rows_by_pattern(path: Path, key: str) -> dict[str, Mapping[str, Any]]:
    payload = _read_json(path)
    rows = payload.get(key) if isinstance(payload, Mapping) else []
    return {str(row.get("pattern_id")): row for row in rows if isinstance(row, Mapping) and row.get("pattern_id")}


def _ranking_groups(path: Path) -> dict[str, list[str]]:
    payload = _read_json(path)
    groups = payload.get("groups") if isinstance(payload, Mapping) else {}
    out: dict[str, list[str]] = {}
    for group, rows in _mapping(groups).items():
        out[str(group)] = [
            str(row.get("pattern_id"))
            for row in rows
            if isinstance(row, Mapping) and row.get("pattern_id")
        ]
    return out


def _role_from_sources(
    *,
    pattern_id: str,
    entry: Mapping[str, Any],
    governance: Mapping[str, Any],
    ranking_groups: Mapping[str, list[str]],
    payload: Mapping[str, Any],
) -> str:
    text = " ".join(
        str(value or "").lower()
        for value in (
            entry.get("classification"),
            entry.get("claim_level"),
            governance.get("publication_classification"),
            governance.get("publication_claim_level"),
            governance.get("tradable_applicability"),
            governance.get("tradable_blockers"),
            payload.get("classification"),
            payload.get("claim_level"),
        )
    )
    if pattern_id in set(ranking_groups.get("tradable_final_95", [])):
        applicability = str(governance.get("tradable_applicability") or "").lower()
        if "defensive" not in applicability and "short" not in text:
            return "buy"
    if pattern_id in set(ranking_groups.get("long_cash_watchlist", [])):
        return "watchlist"
    if payload.get("bear_trap_stoploss_caution") or "bẫy giảm" in text or "bear-trap" in text:
        return "bear_trap_caution"
    if (
        pattern_id in set(ranking_groups.get("defensive_informational", []))
        or "defensive" in text
        or "phòng thủ" in text
        or "cảnh báo" in text
        or "downside" in text
        or "cash_equity_downside" in text
        or "scope_not_direct_long_cash_equity" in text
    ):
        return "defensive"
    if pattern_id in set(ranking_groups.get("research_only_or_descriptive", [])):
        return "research_only"
    return "watchlist"


def _after_buy_status(pattern_id: str, coverage: Mapping[str, Any]) -> dict[str, Any]:
    rows = coverage.get("chapters") if isinstance(coverage.get("chapters"), list) else []
    for row in rows:
        if isinstance(row, Mapping) and row.get("pattern_id") == pattern_id:
            return dict(row)
    return {}


def _chart_paths(payload_path: Path, payload: Mapping[str, Any]) -> dict[str, str]:
    chart_report = payload.get("canonical_example_chart_report")
    paths: dict[str, str] = {}
    if isinstance(chart_report, Mapping):
        for key in ("schematic", "textbook_success", "middle_case", "failure"):
            value = chart_report.get(key) or _mapping(chart_report.get("charts")).get(key)
            if isinstance(value, str):
                paths[key] = value
            elif isinstance(value, Mapping) and value.get("path"):
                paths[key] = str(value.get("path"))
    chart_dir = payload_path.parent / "charts"
    if chart_dir.exists():
        for png in sorted(chart_dir.glob("*.png")):
            name = png.name.lower()
            if "schematic" in name:
                paths.setdefault("schematic", str(png))
            elif "textbook_success" in name:
                paths.setdefault("textbook_success", str(png))
            elif "middle_case" in name:
                paths.setdefault("middle_case", str(png))
            elif "failure" in name:
                paths.setdefault("failure", str(png))
    return paths


def _metric_snapshot(payload: Mapping[str, Any], governance: Mapping[str, Any], preflight: Mapping[str, Any]) -> dict[str, Any]:
    ref = _mapping(payload.get("chapter_reference"))
    target = _mapping(payload.get("target_calibration"))
    base_target = _mapping(target.get("base_target"))
    return {
        "events": ref.get("events") or ref.get("evaluated_events") or preflight.get("n_events"),
        "symbols": ref.get("symbols_scanned") or preflight.get("n_symbols"),
        "median_mfe_pct": ref.get("median_mfe_pct") or preflight.get("median_mfe_pct"),
        "median_mae_pct": ref.get("median_mae_pct") or preflight.get("median_mae_pct"),
        "failure_5pct_rate": ref.get("failure_5pct_rate") or base_target.get("failure_5pct_rate") or preflight.get("failure_5pct_rate"),
        "target_hit_rate": (
            ref.get("legacy_target_hit_rate")
            or base_target.get("target_hit_rate")
            or preflight.get("target_hit_rate")
        ),
        "target_first_before_adverse_5pct_rate": (
            ref.get("target_first_before_adverse_5pct_rate")
            or ref.get("legacy_target_first_before_adverse_5pct_rate")
            or base_target.get("target_first_before_adverse_5pct_rate")
            or preflight.get("target_first_before_adverse_5pct_rate")
        ),
        "selected_base_target_multiple": target.get("selected_base_target_multiple") or preflight.get("preflight_target_multiple"),
        "preflight_status": preflight.get("preflight_status"),
        "preflight_score": preflight.get("preflight_score"),
        "tradable_status": governance.get("tradable_status"),
        "tradable_score": governance.get("tradable_score"),
        "tradable_blockers": governance.get("tradable_blockers"),
    }


def _validate_editorial_artifact(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "status": "FAIL",
            "input_lock_status": "FAIL",
            "rewrite_required": True,
            "missing": True,
            "missing_sections": list(REQUIRED_EDITORIAL_SECTIONS),
            "raw_gate_failures": [],
        }
    payload = _read_json(path)
    sections = _mapping(payload.get("editorial_sections") if isinstance(payload, Mapping) else {})
    missing = [
        section
        for section in REQUIRED_EDITORIAL_SECTIONS
        if not sections.get(section)
    ]
    report = validate_canonical_editorial_sections(payload if isinstance(payload, Mapping) else {})
    raw_failures = report.get("failures") if isinstance(report.get("failures"), list) else []
    input_lock_status = "PASS" if not missing else "FAIL"
    rewrite_required = bool(raw_failures)
    status = "PASS" if input_lock_status == "PASS" else "FAIL"
    return {
        "status": status,
        "input_lock_status": input_lock_status,
        "rewrite_required": rewrite_required,
        "missing": False,
        "missing_sections": missing,
        "raw_gate_status": report.get("status"),
        "raw_gate_failures": raw_failures,
        "report": report,
    }


def build_inventory(
    *,
    manifest_path: Path,
    governance_path: Path,
    preflight_path: Path,
    rankings_path: Path,
    after_buy_coverage_path: Path,
    out_dir: Path,
    extract_pdf_text: bool,
) -> dict[str, Any]:
    chapters = _load_manifest(manifest_path)
    governance_by_pattern = _rows_by_pattern(governance_path, "chapters")
    preflight_by_pattern = _rows_by_pattern(preflight_path, "chapters")
    ranking_groups = _ranking_groups(rankings_path)
    after_buy_coverage = _read_json(after_buy_coverage_path)
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    role_counts: Counter[str] = Counter()
    family_counts: Counter[str] = Counter()
    pdf_text_dir = out_dir / "current_pdf_text"
    for entry in chapters:
        pattern_id = str(entry.get("pattern_id"))
        family = str(entry.get("family") or "")
        payload_path = Path(str(entry.get("payload") or ""))
        pdf_path = Path(str(entry.get("pdf") or entry.get("source_pdf") or ""))
        source_pdf_path = Path(str(entry.get("source_pdf") or entry.get("pdf") or ""))
        payload = _read_json(payload_path)
        if not isinstance(payload, Mapping):
            payload = {}
            failures.append(f"{pattern_id}: payload missing or invalid")
        governance = governance_by_pattern.get(pattern_id, {})
        preflight = preflight_by_pattern.get(pattern_id, {})
        stages = _mapping(entry.get("chapter_writing_stages"))
        refined_path = Path(str(stages.get("refined_ai_sections") or payload.get("editorial_source_path") or ""))
        editorial_gate = _validate_editorial_artifact(refined_path)
        if editorial_gate["input_lock_status"] != "PASS":
            failures.append(f"{pattern_id}: refined editorial artifact missing required sections")
        role = _role_from_sources(
            pattern_id=pattern_id,
            entry=entry,
            governance=governance,
            ranking_groups=ranking_groups,
            payload=payload,
        )
        role_counts[role] += 1
        family_counts[family] += 1
        pdf_text_path = None
        pdf_text_chars = 0
        if extract_pdf_text:
            pdf_text_path, pdf_text_chars = _extract_pdf_text(pdf_path, pdf_text_dir / f"{pattern_id}.txt")
        row = {
            "pattern_id": pattern_id,
            "family": family,
            "title": entry.get("title") or payload.get("pattern_name") or pattern_id,
            "edition11_role": role,
            "classification": entry.get("classification") or payload.get("classification"),
            "claim_level": entry.get("claim_level") or payload.get("claim_level"),
            "payload": str(payload_path),
            "pdf": str(pdf_path),
            "source_pdf": str(source_pdf_path),
            "source_notes": str(entry.get("source_notes") or ""),
            "publication_spec": str(entry.get("publication_spec") or ""),
            "manuscript": str(entry.get("manuscript") or ""),
            "current_pdf_text": pdf_text_path,
            "current_pdf_text_chars": pdf_text_chars,
            "refined_ai_sections": str(refined_path),
            "editorial_artifact_status": editorial_gate["status"],
            "editorial_input_lock_status": editorial_gate["input_lock_status"],
            "editorial_raw_rewrite_required": editorial_gate["rewrite_required"],
            "editorial_raw_gate_status": editorial_gate.get("raw_gate_status"),
            "editorial_raw_gate_failures": editorial_gate.get("raw_gate_failures") or [],
            "editorial_missing_sections": ",".join(editorial_gate.get("missing_sections") or []),
            "chart_paths": _chart_paths(payload_path, payload),
            "example_keys": sorted(_mapping(payload.get("example_events")).keys()),
            "metric_snapshot": _metric_snapshot(payload, governance, preflight),
            "after_buy_coverage": _after_buy_status(pattern_id, after_buy_coverage if isinstance(after_buy_coverage, Mapping) else {}),
            "chapter_writing_policy_id": entry.get("chapter_writing_policy_id"),
            "factory_id": entry.get("canonical_publication_factory_id") or entry.get("factory_id"),
        }
        rows.append(row)

    rewrite_required_count = sum(1 for row in rows if row.get("editorial_raw_rewrite_required"))
    status = "PASS" if len(rows) == 63 and not failures and set(role_counts).issubset(set(ROLE_PRIORITY)) else "FAIL"
    return {
        "pack_id": PACK_ID,
        "status": status,
        "manifest": str(manifest_path),
        "chapter_count": len(rows),
        "family_count": len(family_counts),
        "role_counts": dict(role_counts),
        "family_counts": dict(family_counts),
        "rewrite_required_count": rewrite_required_count,
        "failures": failures,
        "chapters": rows,
    }


def build_style_guide(inventory: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "style_guide_id": "edition_1_1_public_chapter_style_guide_v1",
        "scope": "All 63 public chapters in Edition 1.1.",
        "reader_goal": (
            "Mỗi chương phải đọc như một mục tham khảo mẫu hình giá: nhìn được hình, hiểu được số, "
            "biết khi nào nên tin ít hơn, và không bị kéo sang ngôn ngữ khuyến nghị giao dịch."
        ),
        "source_style_inputs": [
            "Bulkowski original chapters: use as architecture/style reference only, not Vietnam statistics.",
            "After-the-Buy: use to enrich post-confirmation reading, failure/caution language, and role framing.",
            "Existing locked Vietnam payloads: the only source of numbers and examples.",
        ],
        "chapter_structure": [
            "headline_and_orientation",
            "pattern_recognition",
            "how_to_read_the_statistics",
            "failure_or_caution_anatomy",
            "after_confirmation_or_after_the_buy",
            "example_case_studies",
            "practical_reading_boundary",
            "caveats",
        ],
        "public_tone": [
            "Tiếng Việt thuần, dễ đọc, có nhịp giải thích.",
            "Bắt đầu từ hành vi giá trên biểu đồ trước khi đưa số.",
            "Mỗi số chính phải có ý nghĩa đọc biểu đồ đi kèm.",
            "Không để bảng thống kê thay cho văn diễn giải.",
            "Không dùng giọng khuyến nghị mua/bán hoặc hứa hẹn hiệu quả.",
        ],
        "role_guidance": {
            "buy": "Nhấn mạnh cách đọc nhánh long-cash đã có evidence tốt, nhưng vẫn giữ ranh giới tài liệu tham khảo.",
            "watchlist": "Nhấn mạnh điều kiện làm mẫu đáng theo dõi và lý do chưa nâng lên tradable-final.",
            "bear_trap_caution": "Viết như lớp cảnh báo bẫy giảm/kỷ luật đọc lại phá vỡ xuống, không biến thành tín hiệu mua ngược.",
            "defensive": "Viết như hồ sơ quản trị rủi ro/thoát vị thế/thận trọng, không viết như short setup phổ quát.",
            "research_only": "Viết như quan sát mô tả hoặc appendix-grade reference, nêu rõ giới hạn mẫu/dữ liệu.",
        },
        "forbidden_public_terms": list(FORBIDDEN_PUBLIC_TERMS),
        "canonical_blueprint": PUBLIC_CHAPTER_STYLE_BLUEPRINT,
        "deepseek_style_profile": BULKOWSKI_SOURCE_GUIDED_READER_PROFILE,
        "inventory_summary": {
            "chapter_count": inventory.get("chapter_count"),
            "family_count": inventory.get("family_count"),
            "role_counts": inventory.get("role_counts"),
        },
    }


def build_prompt_pack(style_guide: Mapping[str, Any]) -> dict[str, Any]:
    master = {
        "prompt_id": "edition_1_1_deepseek_v4_pro_master_prompt_v1",
        "model": "deepseek-v4-pro",
        "temperature_policy": {
            "source_guided_candidate": 0.35,
            "reader_refinement": 0.3,
            "critic": 0.0,
        },
        "input_contract": [
            "edition_1_1 editorial inventory row",
            "locked publication payload",
            "source notes and source/style dossier",
            "current PDF text",
            "chart/example metadata",
            "After-the-Buy coverage/context when available",
        ],
        "output_contract": {
            "file": "editorial_sections.json",
            "required_keys": [
                "canonical_editorial_workflow_id",
                "editorial_sections",
                "example_captions",
                "claims_to_verify",
            ],
            "required_editorial_sections": list(REQUIRED_EDITORIAL_SECTIONS),
        },
        "hard_rules": [
            "Do not invent numbers, dates, tickers, examples, or outcomes.",
            "Do not write trade recommendations.",
            "Do not use technical fallback text or internal marker names.",
            "Do not render PDF.",
            "Every material claim must map to payload/source_notes/current example fields.",
            "If the evidence is weak, write the weakness clearly instead of making the prose stronger.",
        ],
        "style_guide": style_guide,
    }
    role_prompts = {
        role: {
            "role": role,
            "instruction": style_guide["role_guidance"][role],
            "extra_constraints": [
                "Keep the same schema as the master prompt.",
                "Use role framing in prose but do not override locked classification or numbers.",
            ],
        }
        for role in ROLE_PRIORITY
    }
    return {
        "prompt_pack_id": "edition_1_1_deepseek_prompt_pack_v1",
        "master_prompt": master,
        "role_prompts": role_prompts,
    }


def write_markdown_report(out_dir: Path, inventory: Mapping[str, Any], style_guide: Mapping[str, Any], prompt_pack: Mapping[str, Any]) -> Path:
    path = out_dir / "edition_1_1_editorial_pack.md"
    lines = [
        "# Edition 1.1 Editorial Pack",
        "",
        f"- Status: **{inventory.get('status')}**",
        f"- Chapters: {inventory.get('chapter_count')}",
        f"- Families: {inventory.get('family_count')}",
        f"- Current AI artifacts needing Edition 1.1 rewrite: {inventory.get('rewrite_required_count')}",
        "",
        "## Role Counts",
        "",
    ]
    for role, count in sorted(_mapping(inventory.get("role_counts")).items()):
        lines.append(f"- `{role}`: {count}")
    lines.extend(["", "## Style Contract", ""])
    for item in style_guide.get("public_tone") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Hard Prompt Rules", ""])
    for item in _mapping(prompt_pack.get("master_prompt")).get("hard_rules") or []:
        lines.append(f"- {item}")
    failures = inventory.get("failures") or []
    if failures:
        lines.extend(["", "## Failures", ""])
        for failure in failures:
            lines.append(f"- {failure}")
    lines.extend(["", "## Output Files", ""])
    for filename in (
        "editorial_inventory.json",
        "editorial_inventory.csv",
        "edition_1_1_style_guide.json",
        "edition_1_1_prompt_pack.json",
    ):
        lines.append(f"- `{out_dir / filename}`")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Edition 1.1 editorial inventory, style guide, and prompt pack.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--governance", default=str(DEFAULT_GOVERNANCE))
    parser.add_argument("--preflight", default=str(DEFAULT_PREFLIGHT))
    parser.add_argument("--rankings", default=str(DEFAULT_RANKINGS))
    parser.add_argument("--after-buy-coverage", default=str(DEFAULT_AFTER_BUY_COVERAGE))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--skip-pdf-text", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    inventory = build_inventory(
        manifest_path=Path(args.manifest),
        governance_path=Path(args.governance),
        preflight_path=Path(args.preflight),
        rankings_path=Path(args.rankings),
        after_buy_coverage_path=Path(args.after_buy_coverage),
        out_dir=out_dir,
        extract_pdf_text=not args.skip_pdf_text,
    )
    style_guide = build_style_guide(inventory)
    prompt_pack = build_prompt_pack(style_guide)
    _write_json(out_dir / "editorial_inventory.json", inventory)
    flat_rows = []
    for row in inventory["chapters"]:
        metric = row.get("metric_snapshot") if isinstance(row.get("metric_snapshot"), Mapping) else {}
        flat_rows.append(
            {
                "pattern_id": row.get("pattern_id"),
                "family": row.get("family"),
                "title": row.get("title"),
                "edition11_role": row.get("edition11_role"),
                "classification": row.get("classification"),
                "claim_level": row.get("claim_level"),
                "events": metric.get("events"),
                "preflight_status": metric.get("preflight_status"),
                "preflight_score": metric.get("preflight_score"),
                "tradable_status": metric.get("tradable_status"),
                "tradable_score": metric.get("tradable_score"),
                "editorial_artifact_status": row.get("editorial_artifact_status"),
                "editorial_raw_rewrite_required": row.get("editorial_raw_rewrite_required"),
                "pdf": row.get("pdf"),
                "refined_ai_sections": row.get("refined_ai_sections"),
            }
        )
    _write_csv(
        out_dir / "editorial_inventory.csv",
        flat_rows,
        [
            "pattern_id",
            "family",
            "title",
            "edition11_role",
            "classification",
            "claim_level",
            "events",
            "preflight_status",
            "preflight_score",
            "tradable_status",
            "tradable_score",
            "editorial_artifact_status",
            "editorial_raw_rewrite_required",
            "pdf",
            "refined_ai_sections",
        ],
    )
    _write_json(out_dir / "edition_1_1_style_guide.json", style_guide)
    _write_json(out_dir / "edition_1_1_prompt_pack.json", prompt_pack)
    report_path = write_markdown_report(out_dir, inventory, style_guide, prompt_pack)
    print(
        json.dumps(
            {
                "status": inventory["status"],
                "chapter_count": inventory["chapter_count"],
                "role_counts": inventory["role_counts"],
                "rewrite_required_count": inventory["rewrite_required_count"],
                "failures": inventory["failures"],
                "report": str(report_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if inventory["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
