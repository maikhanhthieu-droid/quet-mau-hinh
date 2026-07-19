"""Audit publication entrypoints so legacy PDF builders cannot become final flow.

This is a source-level guard. The manifest audits prove current artifacts are
clean; this audit prevents future work from adding another direct PDF writer
that bypasses the canonical chapter factory.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


AUDIT_ID = "publication_entrypoint_guard_v1"
ROOT = Path(__file__).resolve().parents[1]

CANONICAL_RENDERER = Path("scanner/pattern_publication_core.py")
CANONICAL_PUBLICATION_MODULES = {
    Path("scanner/pattern_publication_core.py"),
    Path("scanner/canonical_publication_chapter_factory.py"),
    Path("scanner/rebuild_source_guided_final_chapters.py"),
    Path("scanner/rerender_final_chapters_render_only.py"),
}

# These files render non-final technical reports or books, not final chapter
# PDFs. They remain allowed because their outputs are outside final_chapters.
ALLOWED_NON_CHAPTER_RENDERERS = {
    Path("scanner/build_edition1_book.py"),
    Path("scanner/build_book_level_finalization_pack.py"),
    Path("scanner/build_book_v2.py"),
    Path("scanner/research_support_analysis.py"),
    Path("scanner/v2/flags_experiment.py"),
    Path("scanner/v2/bull_flags_monograph.py"),
    Path("scanner/v2/bear_flags_monograph.py"),
}

# Legacy chapter PDFs are allowed to remain only in the quarantine folder and
# only if their CLI main is blocked by require_legacy_publication_builder_enabled.
# Active code must not import helpers from these files.
QUARANTINED_LEGACY_CHAPTER_RENDERERS = {
    Path("scanner/_legacy_quarantine/build_bull_flag_public_chapter.py"),
    Path("scanner/_legacy_quarantine/build_bull_flag_investor_chapter.py"),
}
FORBIDDEN_CANONICAL_IMPORTS = {
    "scanner.build_bull_flag_public_chapter",
    "scanner.build_bull_flag_investor_chapter",
}
FORBIDDEN_MANIFEST_BUILDERS = {
    "scanner.build_bull_flag_public_chapter",
    "scanner.build_bull_flag_investor_chapter",
}
FORBIDDEN_SELF_APPROVED_ARTIFACT = "approved_human_sections.json"
FORBIDDEN_FALLBACK_FRAGMENTS = {
    "source_kind=\"approved_human_sections\"": "self-approved inline editorial source kind",
    "source_kind='approved_human_sections'": "self-approved inline editorial source kind",
    "source_kind or \"approved_human_sections\"": "fallback to self-approved inline editorial source kind",
    "source_kind or 'approved_human_sections'": "fallback to self-approved inline editorial source kind",
    "\"approved_human_sections\":": "payload/schema exposes self-approved editorial source",
    "'approved_human_sections':": "payload/schema exposes self-approved editorial source",
}
FORBIDDEN_PUBLIC_BUILDER_FRAGMENTS = {
    "payload[\"editorial_sections\"] = {": "builder fabricates public prose inline",
    "payload['editorial_sections'] = {": "builder fabricates public prose inline",
    "\"editorial_sections\": _editorial_sections(": "builder fabricates public prose from local helper",
    "'editorial_sections': _editorial_sections(": "builder fabricates public prose from local helper",
}


def _rel(path: Path) -> Path:
    try:
        return path.relative_to(ROOT)
    except ValueError:
        return path


def _python_files() -> list[Path]:
    return sorted((ROOT / "scanner").rglob("*.py"))


def _contains_direct_pdf_render(text: str) -> bool:
    return "SimpleDocTemplate(" in text or "canvas.Canvas(" in text


def _has_legacy_publication_guard(text: str) -> bool:
    return "require_legacy_publication_builder_enabled(" in text


def _iter_public_builder_values(value: Any, path: str = "$") -> list[tuple[str, str]]:
    if isinstance(value, dict):
        out: list[tuple[str, str]] = []
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key == "public_chapter_builder" and isinstance(child, str):
                out.append((child_path, child))
            out.extend(_iter_public_builder_values(child, child_path))
        return out
    if isinstance(value, list):
        out = []
        for idx, child in enumerate(value):
            out.extend(_iter_public_builder_values(child, f"{path}[{idx}]"))
        return out
    return []


def _manifest_legacy_builder_failures(root: Path) -> list[dict[str, str]]:
    path = root / "scanner/v2/pattern_family_manifest.json"
    if not path.exists():
        return []
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [
            {
                "check": "manifest_json_invalid",
                "path": str(_rel(path)),
                "detail": str(exc),
            }
        ]
    failures: list[dict[str, str]] = []
    for json_path, builder in _iter_public_builder_values(manifest):
        if builder in FORBIDDEN_MANIFEST_BUILDERS:
            failures.append(
                {
                    "check": "manifest_points_to_quarantined_builder",
                    "path": f"{_rel(path)}:{json_path}",
                    "detail": builder,
                }
            )
    return failures


def audit_publication_entrypoints(root: Path = ROOT) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    renderers: list[dict[str, str]] = []

    def add_failure(check: str, rel: Path, detail: str) -> None:
        failures.append({"check": check, "path": str(rel), "detail": detail})

    for path in sorted((root / "scanner").rglob("*.py")):
        rel = _rel(path)
        if rel == Path("scanner/audit_publication_entrypoints.py"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if rel not in QUARANTINED_LEGACY_CHAPTER_RENDERERS and "_legacy_quarantine" not in rel.parts:
            if FORBIDDEN_SELF_APPROVED_ARTIFACT in text:
                add_failure(
                    "active_code_creates_self_approved_public_sections",
                    rel,
                    "final public prose must come from canonical source-guided AI/refinement artifacts",
                )
            for fragment, detail in FORBIDDEN_FALLBACK_FRAGMENTS.items():
                if fragment in text:
                    add_failure("active_code_contains_publication_fallback_fragment", rel, detail)
            for fragment, detail in FORBIDDEN_PUBLIC_BUILDER_FRAGMENTS.items():
                if fragment in text and "load_public_editorial_sections(" not in text:
                    add_failure("active_builder_fabricates_inline_public_prose", rel, detail)
        for forbidden in FORBIDDEN_CANONICAL_IMPORTS:
            if forbidden in text and rel not in QUARANTINED_LEGACY_CHAPTER_RENDERERS:
                add_failure("active_code_imports_quarantined_builder", rel, forbidden)
        direct = _contains_direct_pdf_render(text)
        if direct:
            renderers.append({"path": str(rel), "kind": "direct_pdf"})
            if rel == CANONICAL_RENDERER or rel in ALLOWED_NON_CHAPTER_RENDERERS:
                continue
            if rel in QUARANTINED_LEGACY_CHAPTER_RENDERERS:
                if not _has_legacy_publication_guard(text):
                    add_failure("legacy_renderer_missing_guard", rel, "direct chapter renderer must be CLI-quarantined")
                continue
            add_failure(
                "unauthorized_direct_pdf_renderer",
                rel,
                "final chapters must render through canonical_publication_chapter_factory_v1",
            )

    failures.extend(_manifest_legacy_builder_failures(root))

    return {
        "audit_id": AUDIT_ID,
        "status": "PASS" if not failures else "FAIL",
        "counts": {
            "direct_pdf_renderers": len(renderers),
            "failures": len(failures),
        },
        "direct_pdf_renderers": renderers,
        "failures": failures,
    }


def write_report(report: Mapping[str, Any], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "publication_entrypoint_guard_audit.json"
    md_path = out_dir / "publication_entrypoint_guard_audit.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Publication Entrypoint Guard Audit",
        "",
        f"Audit ID: `{report.get('audit_id')}`",
        f"Status: `{report.get('status')}`",
        "",
        "| Check | Path | Detail |",
        "|---|---|---|",
    ]
    for row in report.get("failures", []):
        lines.append(f"| {row.get('check')} | {row.get('path')} | {row.get('detail')} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit PDF publication entrypoints.")
    parser.add_argument("--out-dir", default="artifacts/final_chapters/governance")
    args = parser.parse_args()
    report = audit_publication_entrypoints()
    paths = write_report(report, Path(args.out_dir))
    print(json.dumps({"report": report, "paths": paths}, ensure_ascii=False, indent=2))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
