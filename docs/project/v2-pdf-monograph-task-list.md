# Scanner V2 Flag Family Task List

## Target Outcome

Scanner V2 now uses **Flag Family** as the active source-to-scanner and
chapter-production lane:

```text
source PDF
-> sourced rules
-> Bull Flag / Bear Flag detectors
-> Vietnam statistics
-> AI-assisted Vietnamese commentary
-> one public research chapter per pattern or pattern family
```

The active reference pattern remains `bull_flags`. The next family member is
`bear_flags`, treated as an informational or defensive reference for Vietnam
cash equities unless a separate short-enabled execution layer is proven.

## Current Status

Completed foundation:

- [x] `bull_flags` has source-backed rule provenance.
- [x] `bull_flags` evidence excerpts align to claimed PDF pages.
- [x] `bull_flags` has a Scanner V2 detector, golden fixtures, matrix outputs,
  robustness diagnostics, and a publication-style Vietnamese chapter.
- [x] `bear_flags` has been added to the official Scanner V2 registry with
  source-backed rules and golden fixtures.
- [x] The scanner matrix can register both `bull_flags` and `bear_flags`.
- [x] Outdated non-Flag V2 detector and monograph code has been retired from
  the rebuild path because that logic is no longer the standard.

## Flag Family Completion Definition

Do not call Flag Family complete until all of these are true:

- [x] Bull Flag source alignment audit passes.
- [x] Bull Flag scanner contract audit passes.
- [x] Bull Flag publication chapter is rendered from locked payload data.
- [x] Bear Flag source alignment audit passes.
- [x] Bear Flag golden fixtures pass.
- [x] Bear Flag real-data runner produces detections and statistics.
- [x] Bear Flag chapter payload exists with defensive/informational language.
- [x] Bull-vs-Bear Flag comparison uses the same horizon, target family,
  liquidity policy, and overlap policy.
- [ ] Full test suite passes after every promotion.

## Phase A - Bear Flag Data Runner

Goal:

Run `bear_flags` against the same market data layer used for Bull Flag.

Tasks:

- [x] Reuse the Flag Family scanner matrix rather than a standalone script.
- [x] Persist raw detections with `pattern_id`, `scanner_version`,
  `rule_hash`, `source_chapters`, `breakout_direction`, `breakout_date`,
  `symbol`, and matched rules.
- [x] Keep Bear Flag outputs in a separate defensive-reference lane.
- [x] Add deterministic sample tests for down-breakout events.

## Phase B - Flag Family Statistics

Goal:

Make Bull Flag and Bear Flag comparable without pretending downside patterns
have the same executability on Vietnam cash equities.

Tasks:

- [x] Use the same target bands: `0.46x`, `0.5x`, `0.75x`, `1.0x`.
- [x] Compute MFE, MAE, target hit, target-first-before-adverse, failure 5%,
  Wilson intervals, overlap sensitivity, liquidity buckets, and price-limit
  proxy diagnostics.
- [x] Report Bear Flag as informational/defensive unless execution research says
  otherwise.
- [x] Keep `1.0x` as legacy benchmark, not the default base target.

## Phase C - Chapter Payload And PDF

Goal:

Produce a reader-facing Vietnamese chapter that follows the Bulkowski-style
structure: important results, identification guidelines, examples, statistics,
interpretation, trading caveats, and data limitations.

Tasks:

- [x] Build `chapter_payload.json` from deterministic statistics only.
- [x] Use AI/editorial text only for bounded commentary, not for inventing facts.
- [x] Select examples by seeded protocol from eligible VN100 symbols when
  available.
- [x] Render the chapter with clean typography and compact tables.
- [x] Validate that every numeric claim maps back to the payload.

## Phase D - Matrix Module Standardization

Goal:

Turn Bull Flag into the template for a broader pattern-matrix system.

Tasks:

- [x] Define the Flag Family scanner matrix entry.
- [x] Add Bull Flag and Bear Flag to the core registry.
- [x] Add a pattern-family manifest that records active, retired, and legacy
  pattern modules.
- [ ] Require each future pattern to pass source alignment, golden fixtures,
  matrix normalization, and chapter payload validation before public output.

## Retired Logic

Outdated non-Flag V2 pattern logic is no longer the active standard. Historical
notes may remain in archived project reports, but active Scanner V2 code, task
lists, and promotion gates should use Flag Family as the reference lane.
