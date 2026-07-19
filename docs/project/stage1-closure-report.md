# Stage 1 Closure Report

## Scope

Stage 1 covered the scanner-core overhaul needed to turn the project from a chapter-driven pattern library into a research-grade, family-first detection system aligned with the Bulkowski reference baseline.

This stage is considered closed when the following were complete:

- family-first detector refactors across the main Bulkowski families
- variant persistence and family metrics in the detection pipeline
- phase-3 governance and benchmark layers
- final candidate evaluation for `broadening_bottoms`
- dedicated family rewrite for `measured_move_down_up`
- dedicated recalibration pass for `islands`
- subtype stratification pass for `gaps`
- full unified rerun plus final benchmark and governance snapshot

## What Was Completed

### Scanner architecture

- Refactored the scanner core toward `family detector -> variant resolver -> governance`.
- Added and propagated `variant_code`, `variant_confidence`, `variant_evidence_json`, and `family_metrics_json`.
- Replaced the old shared measured-move logic with a dedicated `MeasuredMoveScanner`.
- Reworked `IslandScanner` to require prior-trend context and true isolation by gaps.
- Reworked `GapScanner` to emit stratified subtypes instead of one undifferentiated family bucket.

### Evaluation and governance

- Added candidate evaluation tooling for `broadening_bottoms`.
- Added family variant reporting for rewritten/recalibrated families.
- Refreshed the phase-3 governance matrix to reflect the new measured-move, islands, and gaps states.
- Built a final overhaul snapshot that ties together the final unified runs, benchmark summary, candidate evaluation, and family-level reports.

### Regression coverage

- Expanded regression tests for:
  - double-pattern variant resolution edge cases
  - head-and-shoulders bottoms gating
  - scallop branch-specific gates
  - measured-move family detection
  - gap subtype classification
  - island isolation and overlap rejection

## Final Stage-1 Snapshot

### Unified reruns

- Valid run: `scan_20260308T_full53_valid_final`
- Calibration run: `scan_20260308T_full53_calib_final`
- Valid totals: `173241 detections / 106005 evals`
- Calibration totals: `171974 detections / 107052 evals`

### Governance status

- `1` candidate
- `2` watchlist
- `40` research_only
- `7` recalibrate
- `5` retire_from_strategy

### Benchmark status

- `9` materially_weaker
- `4` mixed
- `2` roughly_aligned
- `23` sparse
- `15` no_benchmark

### Key family outcomes

- `broadening_bottoms` remains the only live candidate and now has a dedicated candidate-evaluation report.
- `measured_move_up` moved out of recalibration backlog into active research coverage.
- `measured_move_down` remains research-only with mixed KPI quality.
- `island_reversals` moved from blind recalibration backlog into research-only after a dedicated island pass.
- `islands_long` currently has no surviving sample and is treated as reference-only.
- `gaps` now has benchmarkable subtype labels: `common`, `continuation`, `exhaustion`, and `breakaway`, each split by direction.

## Authoritative Local Artifacts

The authoritative output artifacts for the closed Stage-1 state are local-only because `scan_results/` is git-ignored.

Primary artifact roots:

- `scan_results/databases/final/full53_unified_final_valid_20260308.sqlite`
- `scan_results/databases/final/full53_unified_final_calib_20260308.sqlite`
- `scan_results/audits/spec-audit-20260308/snapshots/final-snapshot/benchmark/benchmark_report.md`
- `scan_results/audits/spec-audit-20260308/snapshots/final-snapshot/phase3/phase3_governance_report.md`
- `scan_results/audits/spec-audit-20260308/snapshots/final-snapshot/final_overhaul_snapshot.md`

## Exit Criteria Assessment

Stage 1 is closed because the remaining work is no longer infrastructure-overhaul work. What remains is the next research cycle:

- strategy evaluation for the live candidate
- targeted recalibration of the remaining backlog families
- deeper subtype/family benchmark work against the Bulkowski baseline

Those items belong to Stage 2 research and strategy development, not to Stage 1 scanner/governance overhaul.
