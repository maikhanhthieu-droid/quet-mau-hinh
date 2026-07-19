"""Source-grounded map for the After-the-Buy BUY-first tradable layer.

This module does not create trading signals.  Its job is narrower and earlier
in the pipeline: prove which Edition 1 chapters can inherit an After-the-Buy
setup layer, and classify each source chapter for Vietnam cash-equity use.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


SOURCE_GROUNDING_ID = "after_buy_vietnam_source_grounding_v1"
BUY_FIRST_POLICY_ID = "vietnam_cash_equity_buy_first_policy_v1"
DEFAULT_AFTER_BUY_PDF = Path("references/Wiley Trading Thomas N Bulkowski-Chart Patterns_ After the Buy-Wiley 2016.pdf")
DEFAULT_FINAL_MANIFEST = Path("artifacts/final_chapters/final_chapters_manifest.json")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/after_buy_vietnam_v1")

BUY_ROLES = {"buy_core", "buy_watchlist"}
NON_LONG_ROLES = {"avoid_exit", "defensive", "context_module"}

PATTERN_LOCAL_ROLE_OVERRIDES: dict[str, dict[str, Any]] = {
    "bear_flags": {
        "local_role": "avoid_exit",
        "buy_layer_allowed": False,
        "buy_scope": "defensive_downside_branch_only",
        "reason": "Bear Flag belongs to a BUY-core source chapter but is not a Vietnam long-cash BUY setup.",
    },
    "bear_pennants": {
        "local_role": "avoid_exit",
        "buy_layer_allowed": False,
        "buy_scope": "defensive_downside_branch_only",
        "reason": "Bear Pennant is retained as avoid/exit evidence, not as a BUY setup.",
    },
    "rectangle_tops": {
        "local_role": "avoid_exit",
        "buy_layer_allowed": False,
        "buy_scope": "top_structure_exit_warning",
        "reason": "Rectangle Tops are useful for avoid/exit framing on cash equities.",
    },
    "triangles_descending": {
        "local_role": "buy_watchlist",
        "buy_layer_allowed": True,
        "buy_scope": "up_breakout_branch_only",
        "reason": "Only the up-breakout/reversal branch is eligible for Vietnam BUY testing.",
    },
    "triangles_symmetrical": {
        "local_role": "buy_watchlist",
        "buy_layer_allowed": True,
        "buy_scope": "up_breakout_branch_only",
        "reason": "Only the upward breakout branch is eligible for Vietnam BUY testing.",
    },
}


@dataclass(frozen=True)
class AfterBuySourceChapter:
    source_chapter_no: int
    source_title: str
    local_role: str
    vietnam_use: str
    edition1_pattern_ids: tuple[str, ...] = ()
    notes: str = ""


AFTER_BUY_SOURCE_CHAPTERS: tuple[AfterBuySourceChapter, ...] = (
    AfterBuySourceChapter(1, "Big M", "avoid_exit", "Không mở short mặc định; dùng để tránh mua/thoát khi cấu trúc top xác nhận.", notes="Chưa có chapter Edition 1 riêng."),
    AfterBuySourceChapter(2, "Big W", "buy_core", "Ứng viên BUY sau xác nhận đảo chiều đáy; có thể triển khai như biến thể family double bottoms.", notes="Chưa có chapter Edition 1 riêng."),
    AfterBuySourceChapter(3, "Broadening Bottoms", "buy_watchlist", "BUY có điều kiện sau breakout/retest; cần kiểm soát đường đi rộng và failure.", ("broadening_bottoms",)),
    AfterBuySourceChapter(4, "Broadening Tops", "avoid_exit", "Dùng để tránh mua hoặc giảm tỷ trọng; không xem là short setup phổ quát.", ("broadening_tops",)),
    AfterBuySourceChapter(5, "Double Bottoms", "buy_core", "BUY sau xác nhận đáy đôi; ưu tiên entry/retest/stop theo nhánh biến thể có đủ mẫu.", ("double_bottoms_adam_adam", "double_bottoms_adam_eve", "double_bottoms_eve_adam", "double_bottoms_eve_eve")),
    AfterBuySourceChapter(6, "Double Tops", "avoid_exit", "Cảnh báo top/exit; chỉ dùng phòng thủ trên cổ phiếu cơ sở.", ("double_tops_adam_adam", "double_tops_adam_eve", "double_tops_eve_adam", "double_tops_eve_eve")),
    AfterBuySourceChapter(7, "Earnings Miss", "avoid_exit", "Sự kiện tin xấu: dùng như risk filter/avoid-buy, không phải chapter BUY chính.", notes="Chưa có scanner chapter Edition 1."),
    AfterBuySourceChapter(8, "Flags and Pennants", "buy_core", "Ưu tiên Bull Flag, Bull Pennant, High-and-Tight Flag; bearish branch chỉ là defensive.", ("bull_flags", "bull_pennants", "high_tight_flags", "bear_flags", "bear_pennants")),
    AfterBuySourceChapter(9, "Head-and-Shoulders Bottoms", "buy_core", "BUY sau xác nhận neckline; dùng stop/retest/configuration để nâng tradable layer.", ("head_and_shoulders_bottoms", "head_and_shoulders_bottoms_complex")),
    AfterBuySourceChapter(10, "Head-and-Shoulders Tops", "avoid_exit", "Exit/risk warning; không triển khai short mặc định.", ("head_and_shoulders_tops", "head_and_shoulders_tops_complex")),
    AfterBuySourceChapter(11, "Measured Move Down", "avoid_exit", "Downside continuation dùng để tránh mua/thoát, không phải BUY setup.", ("measured_move_down",)),
    AfterBuySourceChapter(12, "Measured Move Up", "buy_core", "BUY continuation sau nhịp điều chỉnh; phù hợp làm tradable layer long-cash.", ("measured_move_up",)),
    AfterBuySourceChapter(13, "Price Mirrors", "context_module", "Module bối cảnh/đối xứng giá; hỗ trợ đọc setup khác.", notes="Chưa có scanner chapter Edition 1."),
    AfterBuySourceChapter(14, "Price Mountains", "context_module", "Module bối cảnh; không phải BUY setup độc lập.", notes="Chưa có scanner chapter Edition 1."),
    AfterBuySourceChapter(15, "Rectangles", "buy_watchlist", "BUY khi rectangle bottom/up-breakout đủ xác nhận; rectangle top là avoid/exit.", ("rectangle_bottoms", "rectangle_tops")),
    AfterBuySourceChapter(16, "Reversals and Continuations", "context_module", "Module phân loại ngữ cảnh cho các pattern khác.", notes="Không nên tính như chapter trade độc lập."),
    AfterBuySourceChapter(17, "Straight-Line Run Down", "avoid_exit", "Risk/avoid-buy sau nhịp giảm thẳng; không short mặc định.", notes="Chưa có scanner chapter Edition 1."),
    AfterBuySourceChapter(18, "Straight-Line Run Up", "buy_watchlist", "Momentum/watchlist nhưng phải kiểm soát exhaustion và chase risk.", notes="Chưa có scanner chapter Edition 1."),
    AfterBuySourceChapter(19, "Tops and Bottoms", "context_module", "Module bối cảnh cho top/bottom; hỗ trợ filter chứ không phải setup riêng.", notes="Có thể liên hệ triple/horn/pipe nhưng không map một-một."),
    AfterBuySourceChapter(20, "Trends and Countertrends", "context_module", "Module trend context cho mọi setup BUY.", notes="Dùng như filter regime/trend."),
    AfterBuySourceChapter(21, "Triangle Apex and Turning Points", "context_module", "Module timing cho Triangle Family; không phải BUY setup độc lập.", ("triangles_ascending", "triangles_descending", "triangles_symmetrical")),
    AfterBuySourceChapter(22, "Triangles, Ascending", "buy_core", "BUY khi phá lên đủ xác nhận; dùng apex/retest/stop để nâng độ bền.", ("triangles_ascending",)),
    AfterBuySourceChapter(23, "Triangles, Descending", "buy_watchlist", "Chỉ xét BUY với up-breakout/reversal branch; breakdown là avoid/exit.", ("triangles_descending",)),
    AfterBuySourceChapter(24, "Triangles, Symmetrical", "buy_watchlist", "Chỉ xét branch phá lên; branch phá xuống là defensive.", ("triangles_symmetrical",)),
    AfterBuySourceChapter(25, "Vertical Run Down", "avoid_exit", "Risk/avoid-buy sau nhịp giảm dốc.", notes="Chưa có scanner chapter Edition 1."),
    AfterBuySourceChapter(26, "Vertical Run Up", "buy_watchlist", "Momentum/watchlist nhưng dễ exhaustion; cần stop/time exit chặt.", notes="Chưa có scanner chapter Edition 1."),
)


def _read_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _outline_chapters(pdf_path: Path) -> list[dict[str, Any]]:
    reader = PdfReader(str(pdf_path))
    chapters: list[dict[str, Any]] = []
    outline = list(reader.outline)
    idx = 0
    while idx < len(outline):
        item = outline[idx]
        if isinstance(item, list):
            idx += 1
            continue
        title = str(getattr(item, "title", item)).strip()
        if title.startswith("Chapter "):
            try:
                page = reader.get_destination_page_number(item) + 1
            except Exception:
                page = None
            sections: list[dict[str, Any]] = []
            if idx + 1 < len(outline) and isinstance(outline[idx + 1], list):
                for child in outline[idx + 1]:
                    if isinstance(child, list):
                        continue
                    child_title = str(getattr(child, "title", child)).strip()
                    try:
                        child_page = reader.get_destination_page_number(child) + 1
                    except Exception:
                        child_page = None
                    sections.append({"title": child_title, "pdf_page": child_page})
            chapters.append({"title": title, "pdf_page": page, "sections": sections})
        idx += 1
    return chapters


def _edition1_pattern_ids(final_manifest: Path) -> set[str]:
    manifest = _read_json(final_manifest)
    chapters = manifest.get("chapters") if isinstance(manifest.get("chapters"), list) else []
    return {str(ch.get("pattern_id")) for ch in chapters if isinstance(ch, Mapping) and ch.get("pattern_id")}


def _source_title_key(title: str) -> str:
    return " ".join(title.lower().replace("-", " ").replace(",", " ").split())


def _pattern_buy_roles(pattern_ids: Sequence[str], source_role: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pattern_id in pattern_ids:
        override = PATTERN_LOCAL_ROLE_OVERRIDES.get(pattern_id, {})
        local_role = str(override.get("local_role") or source_role)
        buy_allowed = bool(source_role in BUY_ROLES and override.get("buy_layer_allowed", local_role in BUY_ROLES))
        rows.append(
            {
                "pattern_id": pattern_id,
                "local_role": local_role,
                "buy_layer_allowed": buy_allowed,
                "buy_scope": str(override.get("buy_scope") or ("full_pattern_or_family_scope" if buy_allowed else "not_buy_eligible")),
                "reason": str(override.get("reason") or ""),
            }
        )
    return rows


def build_after_buy_source_map(
    *,
    after_buy_pdf: Path = DEFAULT_AFTER_BUY_PDF,
    final_manifest: Path = DEFAULT_FINAL_MANIFEST,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    if not after_buy_pdf.exists():
        raise FileNotFoundError(f"After-the-Buy PDF not found: {after_buy_pdf}")
    outline = _outline_chapters(after_buy_pdf)
    if len(outline) != 26:
        raise RuntimeError(f"Expected 26 source chapters from After the Buy outline, found {len(outline)}")

    outline_by_no: dict[int, Mapping[str, Any]] = {}
    for row in outline:
        parts = str(row["title"]).split(maxsplit=2)
        if len(parts) >= 2 and parts[0] == "Chapter":
            try:
                outline_by_no[int(parts[1])] = row
            except ValueError:
                continue

    edition1_ids = _edition1_pattern_ids(final_manifest)
    mapped: list[dict[str, Any]] = []
    missing_source: list[dict[str, Any]] = []
    title_mismatches: list[dict[str, Any]] = []
    missing_edition1: list[dict[str, Any]] = []
    for spec in AFTER_BUY_SOURCE_CHAPTERS:
        outline_row = outline_by_no.get(spec.source_chapter_no)
        if outline_row is None:
            missing_source.append({"source_chapter_no": spec.source_chapter_no, "source_title": spec.source_title})
            sections: list[dict[str, Any]] = []
            source_pdf_page = None
            source_outline_title = None
        else:
            sections = list(outline_row.get("sections") or [])
            source_pdf_page = outline_row.get("pdf_page")
            source_outline_title = outline_row.get("title")
            if _source_title_key(spec.source_title) not in _source_title_key(str(source_outline_title)):
                title_mismatches.append(
                    {
                        "source_chapter_no": spec.source_chapter_no,
                        "source_title": spec.source_title,
                        "outline_title": source_outline_title,
                    }
                )
        pattern_ids = list(spec.edition1_pattern_ids)
        available = [pid for pid in pattern_ids if pid in edition1_ids]
        missing = [pid for pid in pattern_ids if pid and pid not in edition1_ids]
        if missing:
            missing_edition1.append({"source_chapter_no": spec.source_chapter_no, "source_title": spec.source_title, "missing_pattern_ids": missing})
        pattern_buy_roles = _pattern_buy_roles(available, spec.local_role)
        mapped.append(
            {
                **asdict(spec),
                "edition1_pattern_ids": pattern_ids,
                "edition1_available_pattern_ids": available,
                "edition1_pattern_buy_roles": pattern_buy_roles,
                "has_edition1_chapter": bool(available),
                "source_outline_title": source_outline_title,
                "source_pdf_page": source_pdf_page,
                "source_sections": sections,
                "buy_layer_allowed": spec.local_role in BUY_ROLES,
                "long_cash_tradable_candidate": spec.local_role == "buy_core",
            }
        )

    buy_allowed = [row for row in mapped if row["buy_layer_allowed"]]
    buy_core = [row for row in mapped if row["local_role"] == "buy_core"]
    buy_allowed_patterns = [
        role
        for row in mapped
        for role in row.get("edition1_pattern_buy_roles", [])
        if role.get("buy_layer_allowed")
    ]
    source_map = {
        "source_grounding_id": SOURCE_GROUNDING_ID,
        "buy_first_policy_id": BUY_FIRST_POLICY_ID,
        "after_buy_pdf": str(after_buy_pdf),
        "final_manifest": str(final_manifest),
        "source_chapter_count": len(outline),
        "mapped_chapter_count": len(mapped),
        "buy_layer_allowed_count": len(buy_allowed),
        "buy_core_count": len(buy_core),
        "buy_layer_allowed_pattern_count": len(buy_allowed_patterns),
        "roles": {
            "buy_core": sum(1 for row in mapped if row["local_role"] == "buy_core"),
            "buy_watchlist": sum(1 for row in mapped if row["local_role"] == "buy_watchlist"),
            "avoid_exit": sum(1 for row in mapped if row["local_role"] == "avoid_exit"),
            "defensive": sum(1 for row in mapped if row["local_role"] == "defensive"),
            "context_module": sum(1 for row in mapped if row["local_role"] == "context_module"),
        },
        "chapters": mapped,
        "missing_source_chapters": missing_source,
        "source_title_mismatches": title_mismatches,
        "missing_edition1_pattern_ids": missing_edition1,
        "gate": {
            "status": "PASS" if not missing_source else "FAIL",
            "rule": "No After-the-Buy tradable BUY rule may be created unless its source chapter is present and classified as buy_core or buy_watchlist.",
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "after_buy_source_map.json").write_text(json.dumps(source_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_csv(out_dir / "after_buy_source_map.csv", mapped)
    _write_markdown(out_dir / "after_buy_source_map.md", source_map)
    return source_map


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = [
        "source_chapter_no",
        "source_title",
        "local_role",
        "buy_layer_allowed",
        "long_cash_tradable_candidate",
        "has_edition1_chapter",
        "edition1_available_pattern_ids",
        "source_pdf_page",
        "vietnam_use",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            out = {key: row.get(key) for key in fieldnames}
            out["edition1_available_pattern_ids"] = ",".join(row.get("edition1_available_pattern_ids") or [])
            writer.writerow(out)


def _write_markdown(path: Path, source_map: Mapping[str, Any]) -> None:
    lines = [
        "# After-the-Buy Vietnam Source Map",
        "",
        f"- Source grounding ID: `{source_map['source_grounding_id']}`",
        f"- BUY-first policy: `{source_map['buy_first_policy_id']}`",
        f"- Source chapters: `{source_map['source_chapter_count']}`",
        f"- BUY layer allowed: `{source_map['buy_layer_allowed_count']}`",
        f"- BUY core: `{source_map['buy_core_count']}`",
        f"- Gate: `{source_map['gate']['status']}`",
        "",
        "| # | Source chapter | Local role | Edition 1 chapters | Vietnam use |",
        "|---:|---|---|---|---|",
    ]
    for row in source_map["chapters"]:
        edition = ", ".join(row.get("edition1_available_pattern_ids") or []) or "chưa có chapter Edition 1 trực tiếp"
        lines.append(f"| {row['source_chapter_no']} | {row['source_title']} | `{row['local_role']}` | {edition} | {row['vietnam_use']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def assert_after_buy_buy_rule_allowed(pattern_id: str, source_map: Mapping[str, Any]) -> Mapping[str, Any]:
    denials: list[str] = []
    for chapter in source_map.get("chapters") or []:
        if pattern_id in set(chapter.get("edition1_available_pattern_ids") or chapter.get("edition1_pattern_ids") or []):
            for role in chapter.get("edition1_pattern_buy_roles") or []:
                if role.get("pattern_id") == pattern_id:
                    if role.get("buy_layer_allowed"):
                        return {**chapter, "pattern_buy_role": role}
                    denials.append(
                        f"{chapter.get('source_title')!r} local_role={role.get('local_role')!r}"
                    )
            if chapter.get("buy_layer_allowed") and not chapter.get("edition1_pattern_buy_roles"):
                return chapter
            denials.append(f"{chapter.get('source_title')!r} local_role={chapter.get('local_role')!r}")
    if denials:
        raise ValueError(
            f"{pattern_id} is mapped to After-the-Buy source chapters ({'; '.join(denials)}); "
            "do not create a long-cash BUY tradable rule."
        )
    raise ValueError(f"{pattern_id} has no source-grounded After-the-Buy mapping.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the After-the-Buy Vietnam source-grounding map.")
    parser.add_argument("--after-buy-pdf", type=Path, default=DEFAULT_AFTER_BUY_PDF)
    parser.add_argument("--final-manifest", type=Path, default=DEFAULT_FINAL_MANIFEST)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    result = build_after_buy_source_map(after_buy_pdf=args.after_buy_pdf, final_manifest=args.final_manifest, out_dir=args.out_dir)
    print(json.dumps({"status": result["gate"]["status"], "out_dir": str(args.out_dir), "buy_core_count": result["buy_core_count"], "buy_layer_allowed_count": result["buy_layer_allowed_count"]}, ensure_ascii=False, indent=2))
    return 0 if result["gate"]["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
