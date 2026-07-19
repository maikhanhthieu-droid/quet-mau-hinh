"""Build source-style reference artifacts from the Bulkowski PDF.

The output is used as an editorial style reference for DeepSeek. It is not a
statistics source and must not be copied into public prose verbatim.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


DEFAULT_SOURCE_PDF = Path("references/encyclopedia-of-chart-patterns-2nbsped-9786468600-3175723993-9780471668268-0471668265_compress.pdf")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/bulkowski_style_reference/flags")


STYLE_DOSSIER = """# Bulkowski Style Reference - Flags

## Purpose

This artifact is a source-style reference for writing a Vietnamese public
chapter. It is not an evidence source for Vietnam statistics. The writer may
learn chapter architecture, sequencing, and explanatory rhythm from the source,
but must not copy or translate source wording into the public chapter.

## Observed Chapter Architecture

1. Start with a compact results snapshot before the long explanation.
2. Immediately translate the snapshot into a practical reading point.
3. Use a short tour section to help the reader see the pattern before tables.
4. Put identification guidelines before detailed statistics.
5. Treat failures as a main section, not as an appendix.
6. Explain each statistical table with short practical paragraphs.
7. Separate general statistics, failure rates, breakout/post-breakout behavior,
   size, volume, tactics, sample trade, and best-performance tips.
8. End with practical selection notes that point back to the tables.

## Observed Writing Moves

- Concrete image first, statistic second.
- Short paragraphs that answer "what does this mean for reading the chart?"
- Direct warnings when the pattern should be ignored or downgraded.
- Failure examples are used to teach pattern boundaries.
- Tables are not left alone; each table is followed by explanation.
- Performance claims are frequently qualified by sample size and measurement
  method.
- The source often states that flags are short, fast, and not directly
  comparable with other pattern types because measurement differs.

## Adaptation Rules for the Vietnam Chapter

- Write in Vietnamese.
- Keep the Vietnam numbers from the locked payload only.
- Use the source as chapter-shape guidance, not as a text template.
- Do not add trading instructions that are absent from the Vietnam payload.
- Replace direct trade language with reference-language unless the chapter has
  a validated tradable layer.
- Preserve the main-body / technical-appendix separation used by the canonical
  factory.

## Raw Style Sample

The companion file `bulkowski_flags_pages_358_372.txt` contains the extracted
source text for the Flags chapter pages used as style context.
"""


def extract_pages(*, source_pdf: Path, out_dir: Path, first_page: int, last_page: int) -> dict[str, Path]:
    if not source_pdf.exists():
        raise FileNotFoundError(source_pdf)
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        raise RuntimeError("pdftotext is required to build the source style reference")

    out_dir.mkdir(parents=True, exist_ok=True)
    raw_text = out_dir / "bulkowski_flags_pages_358_372.txt"
    dossier = out_dir / "bulkowski_flags_style_dossier.md"
    subprocess.run(
        [pdftotext, "-f", str(first_page), "-l", str(last_page), "-layout", str(source_pdf), str(raw_text)],
        check=True,
    )
    dossier.write_text(STYLE_DOSSIER, encoding="utf-8")
    return {"raw_text": raw_text, "dossier": dossier}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Bulkowski source style reference artifacts.")
    parser.add_argument("--source-pdf", default=str(DEFAULT_SOURCE_PDF))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--first-page", type=int, default=358)
    parser.add_argument("--last-page", type=int, default=372)
    args = parser.parse_args()
    paths = extract_pages(
        source_pdf=Path(args.source_pdf),
        out_dir=Path(args.out_dir),
        first_page=args.first_page,
        last_page=args.last_page,
    )
    for key, value in paths.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
