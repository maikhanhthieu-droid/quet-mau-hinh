from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCAN_RESULTS = ROOT / "scan_results"


LEGACY_PUBLICATION_DIR_MAP = {
    "book_vi_all": "books/_archive/legacy-publication/all",
    "book_vi_debug": "books/_archive/legacy-publication/debug",
    "book_vi_rerun_20260306": "books/_archive/legacy-publication/rerun-20260306",
    "book_vi_smoke_20260306_1": "books/_archive/legacy-publication/smoke-20260306-1",
    "book_vi_smoke_20260306_ai1": "books/_archive/legacy-publication/smoke-20260306-ai1",
    "book_vi_smoke_20260306_noai": "books/_archive/legacy-publication/smoke-20260306-noai",
}

AUDIT_DIR_MAP = {
    "spec_audit_20260306": "audits/spec-audit-20260306",
    "spec_audit_20260308": "audits/spec-audit-20260308",
}

REPORT_FILE_MAP = {
    "README_CURRENT.md": "reports/current-notes.md",
    "pattern_set_review_latest.md": "reports/pattern-set-review-latest.md",
    "pattern_set_review_rerun_20260306.md": "reports/pattern-set-review-rerun-20260306.md",
}


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _move(src: Path, dest_rel: str) -> None:
    dest = SCAN_RESULTS / dest_rel
    _ensure_dir(dest.parent)
    if src.resolve() == dest.resolve():
        return
    if dest.exists():
        return
    shutil.move(str(src), str(dest))


def _db_bucket(name: str) -> str:
    lower = name.lower()
    if "smoke" in lower or lower.startswith("tmp_"):
        return "databases/smoke"
    if lower.startswith("full53_unified_") or lower.startswith("valid_2022_2025_all_eval") or lower.startswith("calib_2018_2021_all_eval"):
        return "databases/final"
    return "databases/family"


def _write_local_index() -> None:
    lines = [
        "# Scan Results Index",
        "",
        "Cấu trúc local sau khi dọn:",
        "",
        "- `books/book-v2/`: các bản xuất bản chính của Book v2.",
        "- `books/_archive/`: lịch sử local của các bản build cũ, nếu cần giữ lại.",
        "- `audits/`: các gói audit, benchmark, snapshot theo mốc thời gian.",
        "- `databases/final/`: các DB baseline/final unified.",
        "- `databases/family/`: các DB chạy riêng theo family/pass.",
        "- `databases/smoke/`: smoke runs và temporary DB.",
        "- `reports/`: ghi chú, review markdown ở mức top-level.",
        "",
        "Lưu ý: `scan_results/` là local workspace, không commit vào git.",
        "",
    ]
    (SCAN_RESULTS / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    if not SCAN_RESULTS.exists():
        raise SystemExit(f"Missing {SCAN_RESULTS}")

    for name, dest in LEGACY_PUBLICATION_DIR_MAP.items():
        src = SCAN_RESULTS / name
        if src.exists():
            _move(src, dest)

    for name, dest in AUDIT_DIR_MAP.items():
        src = SCAN_RESULTS / name
        if src.exists():
            _move(src, dest)

    for name, dest in REPORT_FILE_MAP.items():
        src = SCAN_RESULTS / name
        if src.exists():
            _move(src, dest)

    for p in list(SCAN_RESULTS.iterdir()):
        if p.name.startswith(".DS_Store"):
            p.unlink(missing_ok=True)

    for p in list(SCAN_RESULTS.iterdir()):
        if p.is_dir():
            continue
        if p.name in {"README.md"}:
            continue
        suffixes = p.suffixes
        if ".sqlite" in suffixes or p.suffix in {".sqlite", ".md"} or p.name.endswith((".sqlite-shm", ".sqlite-wal")):
            bucket = _db_bucket(p.name) if ".sqlite" in p.name else "reports"
            _move(p, f"{bucket}/{p.name}")

    _write_local_index()
    print("Organized scan_results/")


if __name__ == "__main__":
    main()
