# Book V2 Chapter Contract

## Purpose

Book v2 is the Vietnam research publication layer. A chapter is not considered strong because it exists; it is strong only when the underlying Vietnam evidence supports it.

The chapter builder may render all Bulkowski 53 patterns for taxonomy completeness, but each chapter must clearly belong to one readiness lane.

The project-level methodology standard is maintained in
`docs/project/bulkowski-vietnam-methodology-contract.md`. This chapter contract
inherits that standard: a chapter must distinguish identification reference,
investment reference, and trading signal claims before it presents results.

The required statistics layer is maintained in
`docs/project/bulkowski-vietnam-statistics-contract.md`. A chapter cannot be
called an investment-reference chapter unless its deterministic payload satisfies
the P0 statistics set or clearly labels the missing items.

The chapter scoring and hard gates are maintained in
`docs/project/bulkowski-vietnam-chapter-framework.md`. These gates cap the
maximum claim quality even when a chapter has many tables.

The final release gate is maintained in
`docs/project/bulkowski-vietnam-release-gate.md`. Any `High` severity failure
keeps a chapter in `Hold` status regardless of its numeric score.

The final P1-P5 standard is maintained in
`docs/project/bulkowski-vietnam-85-90-standard.md`.

## Readiness Lanes

### `core_research_chapter`

Use for patterns with enough valid and calibration evidence to support a full empirical chapter.

Requirements:

- valid evals are sufficient for stable interpretation
- calibration evals are sufficient for split comparison
- governance does not mark the pattern retired from strategy
- caveats are still shown when benchmark drift exists

### `thin_research_chapter`

Use for patterns with some Vietnam evidence, but not enough for confident generalization.

Requirements:

- show all prevalence and outcome facts
- keep caveats visible near the top of the chapter
- do not imply the result is stable across the Vietnamese market

### `strategy_appendix`

Use for `candidate` and `watchlist` patterns.

Requirements:

- keep research evidence separate from strategy claims
- include validation/calibration split behavior
- include failure and invalidation risks
- do not promote to trading use without a separate strategy evaluation report

### `reference_only`

Use for patterns with sparse, retired, or effectively missing Vietnam evidence.

Requirements:

- preserve the Bulkowski taxonomy link
- explain why the Vietnam evidence is insufficient
- do not rank the pattern as a Vietnam opportunity
- do not include unsupported live-outlook language

## Required Chapter Sections

Every deterministic chapter should include:

1. pattern identity and Bulkowski mapping
2. detector interpretation
3. Vietnam prevalence
4. outcome statistics by valid/calibration split
5. benchmark comparison
6. representative cases when available
7. symbol tendencies when available
8. governance and readiness lane

Every Scanner V2 monograph chapter should additionally include:

1. declared chapter lane
2. data scope and data-integrity status
3. source rule provenance
4. confirmed breakout boundary
5. post-breakout metric definitions and denominators
6. required statistics panels from the P0 statistics contract
7. breakout direction, market-regime, and market-group splits
8. framework score and hard-gate status
9. release gate status and red-team risk notes
10. final classification label
11. limitations mapped to missing methodology/statistics/framework/release gates
12. reproducibility metadata such as payload hash, spec hash, model name, and
   render timestamp

## AI Commentary Boundary

Optional AI commentary may only interpret the deterministic chapter. It must not:

- invent facts or numbers
- change readiness lane
- change governance status
- introduce strategy claims
- hide sparse-data caveats

## Audit Tool

Use:

```bash
python3 scanner/audit_book_v2_readiness.py \
  --valid-db scan_results/databases/final/full53_unified_final_valid_20260308.sqlite \
  --calib-db scan_results/databases/final/full53_unified_final_calib_20260308.sqlite \
  --phase3-pattern-matrix scan_results/audits/spec-audit-20260308/snapshots/final-snapshot/phase3/phase3_pattern_matrix.json \
  --benchmark-pattern-matrix scan_results/audits/spec-audit-20260308/snapshots/final-snapshot/benchmark/benchmark_pattern_matrix.json \
  --out-md scan_results/audits/spec-audit-20260308/book-v2-readiness/readiness_audit.md \
  --out-json scan_results/audits/spec-audit-20260308/book-v2-readiness/readiness_audit.json
```

## Step 3 Gate

Before expanding the Corpus layer, run the reproducible readiness gate:

```bash
python3 scanner/validate_book_v2_readiness_gate.py \
  --valid-db scan_results/databases/final/full53_unified_final_valid_20260308.sqlite \
  --calib-db scan_results/databases/final/full53_unified_final_calib_20260308.sqlite \
  --phase3-pattern-matrix scan_results/audits/spec-audit-20260308/snapshots/final-snapshot/phase3/phase3_pattern_matrix.json \
  --benchmark-pattern-matrix scan_results/audits/spec-audit-20260308/snapshots/final-snapshot/benchmark/benchmark_pattern_matrix.json \
  --out-dir scan_results/audits/spec-audit-20260308/book-v2-readiness/step3-gate
```

The gate must pass these checks:

- readiness audit covers all 53 Bulkowski chart patterns
- deterministic builder emits 53 payloads and 53 core chapters
- every payload validates against `schemas/book_v2/pattern_monograph.schema.json`
- readiness in the audit matches readiness in every chapter payload
- Book v2 assembly works without AI/PDF
- active docs/code do not reference the retired V1 path

## Research Claim Boundary

A chapter may say it is an investment reference only when it reports confirmed
post-breakout behavior with visible sample sizes, data scope, caveats, and the
P0 statistics set from the statistics contract. It may not say or imply it is a
tradable signal system unless the payload includes
execution costs, price-band handling, lot-size assumptions, liquidity filters,
position/risk rules, and walk-forward validation.

Hard-gate caps:

- unresolved lookahead membership/regime caps the chapter at 60
- missing point-in-time corporate-action treatment caps the chapter at 50
- missing breakout-direction split or strata N caps the chapter at 70
- missing pattern-specific target rule caps the chapter at 70
- missing post-breakout OHLC path caps the chapter at 80 for investment-reference claims

Release status:

- any `High` severity release-gate failure means `Hold`
- score 85-89 with all `High` severity gates passing means `Publish with caveats`
- score >= 90 with all `High` severity gates and most `Medium` gates passing means `Strong chapter`
