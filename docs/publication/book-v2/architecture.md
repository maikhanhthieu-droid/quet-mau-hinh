# Book V2 Architecture

## Purpose

`Book v2` is the publication layer for the research engine.

It replaces the old `chapter + AI narrative` flow as the main book path.
Legacy generated artifacts may remain in local archives for audit only, but the old builder code is no longer part of the active workflow.

The new principle is:

`scanner -> Vietnam research dataset -> deterministic chapter core -> optional AI commentary -> final publication`

This makes the book a product of the research engine, not the other way around.

## Why The Previous Book Flow Was Retired

The old book flow was useful as a prototype, but it was structurally misaligned with the project's actual goals.

Problems in the old model:

- it was chapter-first instead of research-first
- AI narrative had too much influence on the perceived quality of the output
- deterministic and AI-generated content were too tightly coupled
- the book was treated as a primary product before the local research layer was mature

Book v2 reverses that order:

1. finalize deterministic research outputs
2. build readable chapters from those outputs
3. add optional AI commentary only after the core chapter is complete

## Core Principles

### 1. Deterministic facts first

Every chapter must be correct without AI.

If the AI layer is disabled, the document must still:

- render cleanly
- contain the correct tables and figures
- explain what the pattern is
- show Vietnam-specific evidence
- show benchmark comparison versus Bulkowski

### 2. AI is commentary, not authorship

DeepSeek may be used, but only for interpretation and editorial commentary.

DeepSeek may write:

- short qualitative observations
- benchmark interpretation
- false-positive caveats
- practical reading notes

DeepSeek may not define:

- pattern status
- rankings
- tables
- pattern prevalence
- benchmark values
- sample counts
- strategy gates

### 3. Bulkowski remains the reference baseline

Each chapter must preserve a direct connection to:

- the Bulkowski taxonomy
- the internal canonical family
- Vietnam market evidence
- benchmark deltas versus the reference baseline

### 4. One research engine, multiple outputs

Book v2 is only one output of the same research engine.

The same data contracts should support:

- market-level research report
- per-pattern monographs
- per-symbol pattern profiles
- current-pattern outlook reports

## Book V2 Product Model

Book v2 should not be one monolithic narrative artifact.

It should be built from a set of reusable document types.

### A. Market Report

Purpose:

- describe the Vietnamese market structurally in pattern terms

Example output:

- `Vietnam Pattern Research Report`

### B. Pattern Monograph

Purpose:

- provide a research chapter for one pattern or family

Example outputs:

- `double_bottoms.md`
- `triangles.md`
- `flag_family.md`
- `bull_flags.md`
- `bear_flags.md`

### C. Symbol Dossier

Purpose:

- explain which patterns a symbol tends to exhibit historically

Example outputs:

- `FPT_profile.md`
- `MWG_profile.md`

### D. Current Outlook Dossier

Purpose:

- explain what pattern is active now and what historically tended to happen next

Example outputs:

- `FPT_current_outlook.md`
- `HPG_current_outlook.md`

The book itself should then be assembled from the market report and pattern monographs, with optional links to symbol and outlook dossiers.

## The 3-Phase Plan

### Phase 1: Retire The Old Book Flow And Define Book V2 Contracts

Goal:

- remove the old book pipeline from the active code path
- define the data contracts that Book v2 will consume

Required actions:

- remove the old narrative-first builder and its validation path from the source tree
- keep old generated artifacts only as optional local history
- define stable payload schemas for:
  - market report
  - pattern monograph
  - symbol profile
  - current outlook

Deliverables:

- Book v2 architecture document
- data schema definitions
- removal note for the old publication path

Exit condition:

- no new feature work depends on the old book pipeline

### Phase 2: Build Deterministic Chapter Core

Goal:

- generate complete chapters from data without AI

Required actions:

- produce one deterministic payload per chapter
- render chapter core markdown from that payload
- ensure chapter output is readable and useful even when `--skip-ai` is enabled

Each deterministic chapter should contain:

1. pattern identity
   - Bulkowski chapter name
   - canonical family
   - variant mapping
2. pattern definition
   - reference description
   - detector interpretation in this project
3. Vietnam prevalence
   - detections
   - evals
   - symbol coverage
4. Vietnam outcome statistics
   - median move
   - fail-under-5 rate
   - target hit
   - boundary invalidation
   - throwback/pullback if relevant
5. benchmark section
   - comparison with Bulkowski baseline
   - benchmark status
6. sample section
   - representative cases
   - notes about sample quality
7. governance section
   - candidate/watchlist/research/recalibrate/retired status

Deliverables:

- deterministic chapter payload builder
- deterministic chapter renderer
- sample figure selection rules

Exit condition:

- a chapter can be rendered correctly with no AI call

### Phase 3: Add Optional AI Commentary and Assemble Book V2

Goal:

- improve readability and interpretation without weakening factual control

Required actions:

- generate commentary only after chapter core is finalized
- store commentary separately from the deterministic chapter core
- assemble final chapter from:
  - deterministic core
  - optional commentary

Recommended file model:

- `chapter_payload.json`
- `chapter_core.md`
- `chapter_commentary.md`
- `chapter_final.md`

If AI is disabled:

- `chapter_final.md` should still be produced from the deterministic core

If AI is enabled:

- `chapter_commentary.md` is appended as an editorial layer

Deliverables:

- optional DeepSeek commentary prompt builder
- commentary cache keyed by deterministic payload fingerprint
- final book assembler

Exit condition:

- Book v2 can be built both with and without DeepSeek

## DeepSeek Role in Book V2

DeepSeek should be used in a narrow and explicit way.

### Allowed uses

- summarize the most important quantitative findings
- explain likely reasons for Vietnam vs Bulkowski divergence
- describe practical caveats in natural language
- provide careful, non-promissory usage notes

### Disallowed uses

- invent missing evidence
- write around sparse or absent data with generic prose
- override deterministic ranking or governance status
- infer facts not present in the payload
- produce strategy recommendations that exceed the evidence

### Prompting rule

The AI prompt should receive only structured, finalized chapter facts.

At minimum:

- chapter identity
- deterministic tables in markdown
- benchmark summary
- governance status
- explicit instructions that commentary must not introduce new facts

### Cache rule

The AI cache fingerprint must include all deterministic inputs:

- chapter payload fingerprint
- benchmark block
- governance block
- sample summary block

If any deterministic input changes, commentary must be invalidated.

## Proposed Chapter Schema

Each monograph chapter should follow the same structure.

### 1. Header

- pattern name
- Bulkowski reference
- canonical family
- chapter status in Vietnam research

### 2. Pattern Definition

- reference definition
- detector interpretation in this project
- branch/variant notes if relevant

### 3. Vietnam Prevalence

- detections
- evals
- symbol coverage
- prevalence notes

### 4. Vietnam Outcome Profile

- move
- target hit
- fail-under-5
- invalidation
- throwback/pullback

### 5. Benchmark Versus Bulkowski

- where Vietnam is aligned
- where Vietnam is weaker
- where evidence is sparse

### 6. Representative Cases

- best examples
- common failure-looking examples
- optional figure gallery

### 7. Symbol Tendencies

- symbols where the pattern recurs most
- symbols where it behaves unusually well or poorly

### 8. Current Research Status

- governance state
- whether it is research-only, watchlist, candidate, or retired

### 9. Optional Commentary

- DeepSeek editorial notes only

## Proposed Implementation Path

### Step 1

Keep using:

- [build_vietnam_research_report.py](../../../scanner/build_vietnam_research_report.py)
- [build_symbol_pattern_profiles.py](../../../scanner/build_symbol_pattern_profiles.py)

as the first deterministic research outputs.

### Step 2

Build a new script family, separate from the old book flow:

- `scanner/build_pattern_monographs.py`
- `scanner/build_current_outlook_reports.py`
- later, `scanner/build_book_v2.py`

### Step 3

Make `build_book_v2.py` consume deterministic monograph payloads instead of generating raw narrative-first chapters.

## What Book V2 Should Replace

Book v2 should become the main path for:

- Vietnam research publication
- pattern chapters
- future PDF/book-like outputs

Legacy generated artifacts should remain only for:

- legacy comparison
- historical output audit
- prompt reference if useful

## Success Criteria

Book v2 is successful when:

1. the project can build a complete research chapter with `--skip-ai`
2. the chapter remains correct after AI commentary is removed
3. the chapter clearly ties Bulkowski reference to Vietnam evidence
4. the same data contracts also power symbol and current-outlook reports
5. book generation is no longer the fragile center of the project

## Immediate Next Steps

1. keep Book v2 as the only active publication path
2. extend deterministic payload coverage before adding new commentary features
3. implement `scanner/build_current_outlook_reports.py`
4. keep testing Book v2 both with and without DeepSeek commentary
5. only promote live/strategy outputs when backed by the research corpus
