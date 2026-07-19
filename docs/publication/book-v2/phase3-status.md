# Book V2 Phase 3 Status

## Goal

Phase 3 adds:

- optional DeepSeek commentary
- commentary caching keyed by deterministic payload
- final chapter assembly
- final Book v2 assembly

## Expected Outputs

For each pattern chapter:

- `chapter_payload.json`
- `chapter_core.md`
- `chapter_commentary.json`
- `chapter_commentary.md`
- `chapter_final.md`

For the book:

- `book_v2.md`
- `book_v2_meta.json`

## Commentary Rules

DeepSeek is used only as an editorial layer.

It should:

- follow the style guide
- write in a compact research-reference form
- stay within deterministic facts

It should not:

- invent facts
- invent numbers
- change governance status
- override benchmark interpretation

## Technical Guardrails

The Phase 3 builder validates commentary by:

- keying cache off the deterministic payload fingerprint
- regenerating commentary when deterministic inputs change
- rejecting commentary that introduces unsupported numeric tokens

## Builder

Phase 3 builder:

- [build_book_v2.py](../../../scanner/build_book_v2.py)

Style guide:

- [commentary-style-guide.md](commentary-style-guide.md)

## Verified Outputs

Verified deterministic full build:

- [book_v2.md](../../../scan_results/books/book-v2/en-core-full/book_v2.md)
- [book_v2_meta.json](../../../scan_results/books/book-v2/en-core-full/book_v2_meta.json)
- [book_v2.pdf](../../../scan_results/books/book-v2/en-core-full/book_v2.pdf)
- [book_v2_meta.json](../../../scan_results/books/book-v2/en-core-full/book_v2_meta.json)

Verified AI pilot:

- [chapter_commentary.md](../../../scan_results/audits/spec-audit-20260308/book-v2-workbench/phase3-pilot-ai-debug/broadening_bottoms/chapter_commentary.md)
- [chapter_final.md](../../../scan_results/audits/spec-audit-20260308/book-v2-workbench/phase3-pilot-ai-debug/broadening_bottoms/chapter_final.md)

Current verification state:

- full `--skip-ai` book build: complete
- full `--skip-ai` PDF export: complete
- single-pattern AI commentary pilot: complete
- full AI book build: supported by the pipeline, but not awaited to completion in this phase because API latency is high
