"""Build visual review contact sheets for final publication chapters.

This is a human-eye audit aid, not a renderer. It uses the final manifest,
renders representative pages from each final PDF, and creates contact sheets so
layout defects can be reviewed quickly before release.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader


DEFAULT_MANIFEST = Path("artifacts/final_chapters/final_chapters_manifest.json")
DEFAULT_OUT_DIR = Path("artifacts/final_chapters/visual_review/latest")
REVIEW_PACK_ID = "final_chapter_visual_review_pack_v1"


def _read_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return payload if isinstance(payload, Mapping) else {}


def _slug(chapter: Mapping[str, Any]) -> str:
    family = str(chapter.get("family") or "family")
    pattern = str(chapter.get("pattern_id") or Path(str(chapter.get("pdf") or "")).stem)
    return f"{family}_{pattern}".replace("/", "_")


def _page_texts(pdf: Path) -> list[str]:
    reader = PdfReader(str(pdf))
    return [page.extract_text() or "" for page in reader.pages]


def _representative_pages(pdf: Path) -> list[int]:
    texts = _page_texts(pdf)
    page_count = len(texts)
    selected = {1, page_count}
    anchors = ("Ví dụ minh họa", "Tập trung vào thất bại", "Phụ lục kỹ thuật")
    for index, text in enumerate(texts, start=1):
        if any(anchor in text for anchor in anchors):
            selected.add(index)
    return sorted(page for page in selected if 1 <= page <= page_count)


def _render_page(pdf: Path, page: int, out_dir: Path, slug: str) -> Path:
    if shutil.which("pdftoppm") is None:
        raise RuntimeError("pdftoppm is required for visual PDF review")
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / f"{slug}_p{page:02d}"
    subprocess.run(
        ["pdftoppm", "-png", "-f", str(page), "-l", str(page), "-scale-to", "1200", str(pdf), str(prefix)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    candidates = sorted(out_dir.glob(f"{prefix.name}-*.png"))
    if not candidates:
        raise FileNotFoundError(f"pdftoppm did not create image for {pdf} page {page}")
    final = out_dir / f"{slug}_p{page:02d}.png"
    candidates[0].replace(final)
    return final


def _contact_sheet(images: list[Path], out_path: Path, *, cols: int = 3) -> None:
    if not images:
        return
    thumbs: list[Image.Image] = []
    labels: list[str] = []
    for path in images:
        image = Image.open(path).convert("RGB")
        image.thumbnail((420, 600))
        thumbs.append(image.copy())
        labels.append(path.stem)
        image.close()

    pad = 18
    label_h = 42
    cell_w = max(img.width for img in thumbs) + pad * 2
    cell_h = max(img.height for img in thumbs) + label_h + pad * 2
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), "white")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("Arial.ttf", 16)
    except OSError:
        font = ImageFont.load_default()
    for idx, image in enumerate(thumbs):
        x = (idx % cols) * cell_w + pad
        y = (idx // cols) * cell_h + pad
        draw.text((x, y), labels[idx], fill=(20, 70, 65), font=font)
        sheet.paste(image, (x, y + label_h))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)


def build_visual_review_pack(manifest_path: Path = DEFAULT_MANIFEST, out_dir: Path = DEFAULT_OUT_DIR) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    chapters = [chapter for chapter in manifest.get("chapters", []) if isinstance(chapter, Mapping)]
    pages_dir = out_dir / "pages"
    rows: list[dict[str, Any]] = []
    images_by_family: dict[str, list[Path]] = {}
    all_images: list[Path] = []

    for chapter in chapters:
        pdf = Path(str(chapter.get("pdf") or ""))
        if not pdf.exists():
            rows.append({"pattern_id": chapter.get("pattern_id"), "status": "MISSING", "pdf": str(pdf), "pages": []})
            continue
        slug = _slug(chapter)
        pages = _representative_pages(pdf)
        rendered = [_render_page(pdf, page, pages_dir, slug) for page in pages]
        rows.append(
            {
                "pattern_id": chapter.get("pattern_id"),
                "family": chapter.get("family"),
                "status": "PASS",
                "pdf": str(pdf),
                "pages": pages,
                "rendered": [str(path) for path in rendered],
            }
        )
        images_by_family.setdefault(str(chapter.get("family") or "family"), []).extend(rendered)
        all_images.extend(rendered)

    sheets: dict[str, str] = {}
    for family, images in sorted(images_by_family.items()):
        sheet = out_dir / f"{family}_contact_sheet.png"
        _contact_sheet(images, sheet)
        sheets[family] = str(sheet)
    overview = out_dir / "all_final_chapters_contact_sheet.png"
    _contact_sheet(all_images, overview, cols=4)
    sheets["all"] = str(overview)

    report = {
        "review_pack_id": REVIEW_PACK_ID,
        "status": "PASS" if rows and all(row.get("status") == "PASS" for row in rows) else "FAIL",
        "manifest": str(manifest_path),
        "counts": {"chapters": len(rows), "rendered_pages": len(all_images), "families": len(images_by_family)},
        "sheets": sheets,
        "chapters": rows,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "visual_review_pack.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Final Chapter Visual Review Pack",
        "",
        f"Review pack ID: `{REVIEW_PACK_ID}`",
        f"Status: `{report['status']}`",
        "",
        "| Family | Pattern | Pages |",
        "|---|---|---|",
    ]
    for row in rows:
        lines.append(f"| {row.get('family')} | {row.get('pattern_id')} | {', '.join(map(str, row.get('pages') or []))} |")
    (out_dir / "visual_review_pack.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Render final chapter pages for human visual review.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()
    report = build_visual_review_pack(Path(args.manifest), Path(args.out_dir))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
