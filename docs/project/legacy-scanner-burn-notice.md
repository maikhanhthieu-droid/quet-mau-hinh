# Legacy Scanner Burn Notice

## Decision

The legacy scanner path is no longer allowed as a source of truth for the
rebuild.

The project target is now:

```text
source PDF
-> sourced Scanner V2 rules
-> source alignment
-> official V2 detector
-> real-market detections
-> deterministic statistics
-> DeepSeek V4 Flash commentary
-> PDF monograph
```

## Why

The legacy path is useful for historical comparison, but it does not satisfy
the new standard:

- rules are not all backed by page-level provenance
- some extraction semantics were wrong or ambiguous
- unknown constraints could pass too easily
- result hashes were not tied to the full rule body
- output was scan/report oriented, not monograph-payload oriented

Keeping it as an active path makes the rebuild harder to reason about.

## Current Burn Scope

These active legacy entrypoints are quarantined:

- `scanner/pattern_scanner.py`
- `scanner/run_full_scan.py`
- `scanner/report_bulkowski.py`
- `scanner/report_symbol.py`
- `scanner/audit_kpi.py`
- `scanner/audit_book_v2_readiness.py`
- `scanner/build_pattern_monographs.py`
- `scanner/build_symbol_pattern_profiles.py`
- `scanner/build_vietnam_research_report.py`

They now require:

```bash
CHARTPATTERNSCAN_ALLOW_LEGACY_SCANNER=1
```

This flag is for historical comparison only. It must not be used to generate
new official research or PDF monograph facts.

## Still Allowed

These components are not burned because V2 still needs infrastructure like
normalization, pivots, post-breakout measurement, and document assembly:

- `scanner/ohlcv_normalizer.py`
- `scanner/pivot_detector.py`
- `scanner/post_breakout_analyzer.py`, until a V2 evaluator replaces it
- `scanner/build_book_v2.py`, as a DeepSeek/PDF assembly reference
- existing DB/report artifacts, for benchmark comparison only

## New Source Of Truth

Use:

- `scanner/v2/`
- `scanner/audit_scanner_v2_contract.py`
- `scanner/audit_scanner_v2_source_alignment.py`
- `docs/project/v2-pdf-monograph-task-list.md`

## Next Burn Steps

- [x] Stop referencing legacy scan commands in the top-level README.
- [x] Quarantine legacy report/readiness entrypoints behind the same env guard.
- [ ] Build the V2 data runner for `bear_flags` through the Flag Family matrix.
- [ ] Replace report builders with V2 monograph payload builders.
- [ ] Move legacy-only scripts into an archive folder after V2 has replacement commands.
- [ ] Delete legacy-only code only after no active V2 task imports it.
