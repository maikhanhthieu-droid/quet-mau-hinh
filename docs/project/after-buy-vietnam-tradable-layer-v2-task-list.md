# After-the-Buy Vietnam Tradable Layer V2 Task List

This workstream localizes *Chart Patterns: After the Buy* for Vietnam cash-equity use.  The layer is BUY-first: bearish/downside chapters are useful as avoid, exit, and defensive filters, but they are not promoted into default short-selling setups.

## Ground Rules

1. Every BUY rule must be source-grounded against the After-the-Buy PDF.
2. Every BUY rule must be localized for Vietnam cash equities: long-only by default, liquidity-aware, with no assumed single-stock shorting.
3. Context chapters can support a setup but cannot become a standalone BUY rule.
4. Pattern-level overrides beat source-chapter family labels.  For example, `Flags and Pennants` is BUY-core as a source chapter, but `bear_flags` and `bear_pennants` are defensive/avoid, not BUY.
5. A chapter that fails to improve after source-grounded setup/stop/throwback logic should be recorded as a data, sample-depth, or pattern-nature ceiling rather than overfit.

## Source Artifacts

Run:

```bash
PYTHONPATH=. python3 -m scanner.after_buy_source_grounding
PYTHONPATH=. python3 -m scanner.build_after_buy_tradable_priority
PYTHONPATH=. python3 -m scanner.build_after_buy_bull_flag_control
PYTHONPATH=. python3 -m scanner.build_after_buy_head_shoulders_bottoms_rules
PYTHONPATH=. python3 -m scanner.build_after_buy_double_bottoms_rules
PYTHONPATH=. python3 -m scanner.build_after_buy_rectangles_rules
PYTHONPATH=. python3 -m scanner.build_after_buy_high_tight_flags_rules
PYTHONPATH=. python3 -m scanner.build_after_buy_bull_pennants_rules
PYTHONPATH=. python3 -m scanner.build_after_buy_measured_move_up_rules
PYTHONPATH=. python3 -m scanner.build_after_buy_triangles_rules
PYTHONPATH=. python3 -m scanner.build_after_buy_broadening_bottoms_rules
PYTHONPATH=. python3 -m scanner.build_after_buy_defensive_conversion_rules
PYTHONPATH=. python3 -m scanner.build_after_buy_deep_integration
PYTHONPATH=. python3 -m scanner.build_after_buy_application_layer
PYTHONPATH=. python3 -m scanner.run_after_buy_quantitative_effect
```

Outputs:

- `artifacts/scanner_v2/after_buy_vietnam_v1/after_buy_source_map.json`
- `artifacts/scanner_v2/after_buy_vietnam_v1/after_buy_source_map.md`
- `artifacts/scanner_v2/after_buy_vietnam_v1/after_buy_tradable_priority.json`
- `artifacts/scanner_v2/after_buy_vietnam_v1/after_buy_tradable_priority.md`
- `artifacts/scanner_v2/after_buy_vietnam_v1/bull_flags_control/bull_flag_after_buy_control.json`
- `artifacts/scanner_v2/after_buy_vietnam_v1/head_shoulders_bottoms/head_shoulders_bottoms_after_buy_rules.json`
- `artifacts/scanner_v2/after_buy_vietnam_v1/double_bottoms/double_bottoms_after_buy_rules.json`
- `artifacts/scanner_v2/after_buy_vietnam_v1/rectangles/rectangles_after_buy_rules.json`
- `artifacts/scanner_v2/after_buy_vietnam_v1/high_tight_flags/high_tight_flags_after_buy_rules.json`
- `artifacts/scanner_v2/after_buy_vietnam_v1/bull_pennants/bull_pennants_after_buy_rules.json`
- `artifacts/scanner_v2/after_buy_vietnam_v1/measured_move_up/measured_move_up_after_buy_rules.json`
- `artifacts/scanner_v2/after_buy_vietnam_v1/triangles/triangles_after_buy_rules.json`
- `artifacts/scanner_v2/after_buy_vietnam_v1/broadening_bottoms/broadening_bottoms_after_buy_rules.json`
- `artifacts/scanner_v2/after_buy_vietnam_v1/defensive_conversion/defensive_conversion_rules.json`
- `artifacts/scanner_v2/after_buy_vietnam_v2/after_buy_deep_integration_pack.json`
- `artifacts/scanner_v2/after_buy_vietnam_v2/after_buy_deep_rules.json`
- `artifacts/scanner_v2/after_buy_vietnam_v2/after_buy_chapter_coverage_matrix.csv`
- `artifacts/scanner_v2/after_buy_vietnam_v2/after_buy_rule_layer_mapping.json`
- `artifacts/scanner_v2/after_buy_vietnam_v2/after_buy_scanner_stat_trade_config.json`
- `artifacts/scanner_v2/after_buy_vietnam_v2/after_buy_before_after_impact_report.json`
- `artifacts/scanner_v2/after_buy_vietnam_v2/application/after_buy_application_scope.json`
- `artifacts/scanner_v2/after_buy_vietnam_v2/application/scanner_before_after.csv`
- `artifacts/scanner_v2/after_buy_vietnam_v2/application/statistics_metric_plan.csv`
- `artifacts/scanner_v2/after_buy_vietnam_v2/application/tradable_before_after.csv`
- `artifacts/scanner_v2/after_buy_vietnam_v2/application/defensive_runtime_signals.json`
- `artifacts/scanner_v2/after_buy_vietnam_v2/application/publication_pilot_payload.json`
- `artifacts/scanner_v2/after_buy_vietnam_v2/application/after_buy_application_report.md`
- `artifacts/scanner_v2/after_buy_vietnam_v2/quantitative_effect/after_buy_quantitative_effect_report.json`
- `artifacts/scanner_v2/after_buy_vietnam_v2/quantitative_effect/after_buy_quantitative_effect_comparison.csv`
- `artifacts/scanner_v2/after_buy_vietnam_v2/quantitative_effect/after_buy_quantitative_effect_report.md`

## Current Progress

| Item | Status | Evidence |
|---|---|---|
| BUY-first source map | PASS | 26 After-the-Buy chapters mapped; 12 Edition-1 pattern branches allowed for BUY layer. |
| Bull Flag control | PASS | Benchmark score remains 95.78; release status PASS; source chapter is Flags and Pennants. |
| H&S Bottoms source rules | PASS | 12 source-grounded setup/stop/configuration rules extracted from After-the-Buy Chapter 9. |
| H&S Bottoms first tradable score | BLOCKED | Score 51.24; blocker is validation/holdout trade depth, walk-forward return, and capacity. |
| H&S Bottoms Complex current tradable evidence | BLOCKED | Governance score 68.64; still below 95 and needs source-guided rerun, not overfit. |
| Double Bottoms source rules | PASS | 11 source-grounded rules extracted from After-the-Buy Chapter 5. |
| Double Bottoms family rescue | PASS | Family rescue score 97.97; Adam/Eve variants remain subgroups instead of forced standalone 95. |
| Rectangle source rules | PASS | 11 source-grounded rules extracted from After-the-Buy Chapter 15. |
| Rectangle Bottoms up-breakout rerun | BLOCKED | Up-breakout-only scope still scores 47.42; weak path/cost/walk-forward, not merely mixed-direction aggregation. |
| Rectangle Tops BUY promotion | BLOCKED BY POLICY | Avoid/exit only; never promote as Vietnam long-cash BUY. |
| High-and-Tight Flags source rules | PASS | After-the-Buy has no direct High-and-Tight chapter; use Chapter 8 Flags and Pennants for post-buy behavior, while geometry/0.5x target stays pattern-specific. |
| High-and-Tight Flags tradable evidence | BLOCKED | Branch optimization score 68.72; source-aligned branch was tested but negative walk-forward folds block tradable-final promotion. |
| Bull Pennants source rules | PASS | Chapter 8 directly supports Pennants; geometry remains Bull-Pennant specific with converging body and steep prior pole. |
| Bull Pennants no-overlift decision | BLOCKED | Score 92.18; ceiling audit best score 93.80; negative walk-forward folds remain, so stop optimization under no-overlift guard. |
| Measured Move Up source rules | PASS | Chapter 12 directly supports the long setup; selected local contract keeps ideal retrace, first-leg linearity, and 0.5x executable base target. |
| Measured Move Up tradable evidence | PASS | Score 95.64; release PASS; no promotion blockers; keep as BUY-core tradable-final reference. |
| Triangle source rules | PASS | Chapters 21-24 locked; Ascending is BUY-core, Descending/Symmetrical only use up-breakout branches for BUY. |
| Triangle tradable evidence | BLOCKED | Ascending 85.84, Symmetrical 84.03, Descending 89.13; all remain below 95 and carry walk-forward/scope blockers. |
| Broadening Bottoms source rules | PASS | Chapter 3 locked with required sections: behavior, identification, buy setup, sell setups, stops, configuration, measure rule, trading, and closing position. |
| Broadening Bottoms tradable evidence | BLOCKED | Best branch score 90.26; still blocked by mixed-scope and negative walk-forward folds, so keep as BUY-watchlist/reference. |
| Defensive conversion gate | PASS | 17 bearish/top/downside chapters are denied as long-cash BUY and converted to avoid/exit/risk-filter use. |
| Deep After-the-Buy integration | PASS | 26 source chapters, 63 atlas chapters, 211 section evidence rows, 150 normalized rule rows, 16 chapters with direct After-the-Buy rules, and runtime config for scanner/stat/trade/publication layers. |
| After-the-Buy application layer | PASS | 12 priority patterns have scanner overlays, 66 supported stat-metric rows, 12 tradable before/after rows, 48 defensive runtime signals, and 5 publication pilot payloads. |
| Quantitative branch-rerun effect | PASS | Full rerun over 12 priority BUY/watchlist chapters completed; 0 promoted, 0 clean improved, 2 unchanged, 1 blocked-after-rerun, 9 worse/more conservative, 12 still blocked. |

## Current BUY Priority Queue

This list is generated from current governance/tradable evidence and should be refreshed before each work session.

| Rank | Pattern | Source chapter | Role | Current issue |
|---:|---|---|---|---|
| 1 | `head_and_shoulders_bottoms` | Head-and-Shoulders Bottoms | BUY core | Missing or incomplete tradable score; build setup/stop layer first. |
| 2 | `double_bottoms_adam_eve` | Double Bottoms | BUY core | Low tradable score; use throwback/stop/configuration logic before more branch mining. |
| 3 | `rectangle_bottoms` | Rectangles | BUY watchlist | Accumulation pattern needs post-breakout setup logic, not just morphology. |
| 4 | `double_bottoms_eve_adam` | Double Bottoms | BUY core | Low score and sample-depth risk; prefer setup-subtype/family-level evidence. |
| 5 | `head_and_shoulders_bottoms_complex` | Head-and-Shoulders Bottoms | BUY core | Sample depth and validation depth need source-guided setup design. |
| 6 | `high_tight_flags` | Flags and Pennants | BUY core | Source relationship is now locked; branch score 68.72 remains blocked by negative walk-forward folds. |
| 7 | `double_bottoms_eve_eve` | Double Bottoms | BUY core | Do not over-tighten; test family-level/retest setup. |
| 8 | `triangles_symmetrical` | Triangles, Symmetrical | BUY watchlist | Up-breakout branch only; current best score 84.03, blocked by scope/walk-forward. |
| 9 | `triangles_ascending` | Triangles, Ascending | BUY core | Direct BUY-core candidate; current best score 85.84, blocked by walk-forward. |
| 10 | `triangles_descending` | Triangles, Descending | BUY watchlist | Up-breakout/reversal branch only; breakdown branch is avoid/exit; current best score 89.13. |
| 11 | `bull_pennants` | Flags and Pennants | BUY core | Near-threshold but locked: score 92.18, ceiling 93.80, still blocked by negative walk-forward folds. |
| 12 | `bull_flags` | Flags and Pennants | BUY core | Benchmark; use as control for After-the-Buy layer design. |
| 13 | `double_bottoms_adam_adam` | Double Bottoms | BUY core | Already strong; use as Double Bottom control branch. |
| 14 | `measured_move_up` | Measured Move Up | BUY core | Locked as source-grounded tradable-final reference: score 95.64, release PASS, no blockers. |
| 15 | `broadening_bottoms` | Broadening Bottoms | BUY watchlist | Source rules locked; best branch score 90.26, blocked by mixed-scope and negative walk-forward folds. |

## Implementation Phases

### Phase A - Bull Flag control

- Extract After-the-Buy setup, throwback, busted, and stop concepts for `Flags and Pennants`.
- Compare them with the existing Bull Flag tradable benchmark.
- Confirm that the new layer does not degrade the current `tradable-final-95` result.
- Current status: done; keep Bull Flag as the benchmark/control pattern for this workstream.

### Phase B - Highest-lift BUY candidates

Work in this order unless refreshed priority data says otherwise:

1. `head_and_shoulders_bottoms`
2. `double_bottoms_adam_eve`
3. `rectangle_bottoms`
4. `double_bottoms_eve_adam`
5. `head_and_shoulders_bottoms_complex`

For each pattern:

- Create `after_buy_source_notes.json`.
- Create `after_buy_setup_rules.json`.
- Add local execution rules: entry, stop, target band, time exit, retest/throwback handling.
- Rerun tradable layer.
- Record whether the score lift is real, weak, or overfit.

Current Phase-B finding:

- `head_and_shoulders_bottoms`: source rules are ready, but the first executable score is only 51.24 because validation/holdout trade depth and capacity are weak.
- `double_bottoms_*`: After-the-Buy supports a family-level interpretation.  The family rescue artifact reaches 97.97, while AE/EA/EE variants are too thin as standalone tradable-final chapters.  Keep those variants as published subgroups under the family evidence unless new data materially increases depth.
- `rectangle_bottoms`: source rules require direction-specific up-breakout/reclaim testing.  The up-only rerun did not improve the score, so current evidence supports BUY-watchlist/reference only, not tradable-final promotion.
- `high_tight_flags`: After-the-Buy does not provide a direct High-and-Tight chapter.  The valid V2 use is indirect: Chapter 8 supplies continuation/stop/failure handling, while High-and-Tight morphology and the 0.5x prior-advance target stay anchored to the pattern-specific source notes.  Branch optimization already tested source-aligned context, but score remains 68.72 with negative walk-forward folds; do not overfit it to 95.
- `bull_pennants`: source rules and no-overlift gate are now locked.  The chapter is close to tradable-final quality but still fails the explicit Bull Flag-style KPI because the best ceiling audit is 93.80 and fixed walk-forward keeps negative folds.  Treat as strong watchlist/tradable research candidate, not `tradable-final-95`.
- `measured_move_up`: After-the-Buy source rules are now locked and support the existing tradable-final evidence.  No further lift is required; preserve the selected 0.5x target, ideal 38-62 retrace band, first-leg linearity gate, and current execution contract.
- `triangles_*`: After-the-Buy branch policy is now locked.  Ascending Triangle remains a direct BUY-core candidate; Descending and Symmetrical Triangles can only contribute BUY evidence through upward breakout branches.  All three have already been optimized enough to identify the current blocker: below-95 score plus walk-forward/scope instability, not missing source rules.
- `broadening_bottoms`: After-the-Buy source rules are now locked.  The valid Vietnam use is BUY-watchlist/reference on bullish branch only; the best branch score is 90.26 and remains blocked by mixed-direction scope plus negative walk-forward folds.  Do not promote by tightening around holdout artifacts.

### Phase C - Branch-specific BUY watchlist

- `triangles_symmetrical`: upward breakout branch only.
- `triangles_descending`: upward reversal branch only.
- `rectangle_bottoms`: bottom/up-breakout branch only.
- `broadening_bottoms`: long branch with path-quality filters only.

Current Phase-C finding:

- `broadening_bottoms`: source-grounded branch logic is complete for the current data.  The remaining gap is not missing rule text but evidence quality: wide paths, mixed family behavior, and negative walk-forward folds keep it below tradable-final-95.

### Phase D - Defensive conversion

For bearish/downside chapters, build avoid/exit rules instead of BUY rules:

- `bear_flags`
- `bear_pennants`
- `double_tops_*`
- `head_and_shoulders_tops*`
- `measured_move_down`
- `rectangle_tops`
- `broadening_tops`

These can improve the realtime scanner as risk filters but should not be counted as long-cash tradable BUY setups.

Current Phase-D finding:

- Defensive conversion is now an explicit gate, not a prose convention.  It covers 17 chapters: the After-the-Buy mapped downside chapters plus Edition-1 top-like defensive chapters that are not direct After-the-Buy BUY sources.  The gate passes only when every row is denied as a long-cash BUY setup.

## KPI

The KPI is not "make every chapter 95."  The KPI is:

- Every BUY candidate has source-grounded After-the-Buy rules.
- Every low-score BUY chapter is retested with setup/stop/configuration logic.
- Every failed lift has a written blocker: data, sample depth, fold instability, execution scope, or pattern nature.
- No bearish/downside chapter is accidentally promoted into a Vietnam long-cash BUY setup.

## Deep Integration V2 Result

The V2 pack turns scattered chapter artifacts into one book-wide bridge:

| Layer | Before | After |
|---|---|---|
| Source reading | Individual builders held separate source rules | 211 section-evidence rows from 26 After-the-Buy chapters |
| Rule system | Pattern artifacts were hard to compare | 150 normalized rule rows with pattern ownership |
| Scanner | After-the-Buy quality logic was implicit | 135 scanner-rule mappings for pattern/family quality gates |
| Statistics | Metrics existed but were not source-indexed | 66 statistic-rule mappings for failure, target, retest, stop, and path metrics |
| Trade layer | Rerun decisions were pattern-by-pattern | 122 trade-rule mappings plus no-overfit gate per chapter |
| Publication | Atlas did not systematically expose After-the-Buy | 150 publication-interpretation rows ready for a "Hành vi sau phá vỡ" section |

Current machine-readable bridge:

- `after_buy_scanner_stat_trade_config.json` has 63 patterns.
- 15 patterns are BUY-allowed.
- 48 patterns are defensive/reference/unmapped for BUY.
- 16 patterns have scanner/stat/trade rules directly mapped.
- 12 BUY/watchlist patterns remain blocked by data/fold/scope evidence and should not be forced to 95.

## Application Layer Result

The application layer applies the V2 bridge to actual project outputs:

| Layer | Before | After |
|---|---|---|
| Scanner | Watchlist rows only carried base pattern fields | Realtime watchlist now carries `after_buy_role`, `after_buy_action`, `after_buy_trade_mode`, and risk-context flags |
| Scanner before/after | No per-pattern application table | 12 priority patterns have `scanner_before_after.csv` with non-destructive after-buy overlays |
| Statistics | Metrics were not arranged by After-the-Buy application | 84 rows in `statistics_metric_plan.csv`, with 66 supported by current event data |
| Trade layer | Scorecards existed but no application decision table | 12 rows in `tradable_before_after.csv`; scores are not inflated, blockers remain explicit |
| Defensive | Defensive gate existed separately | 48 defensive/reference/unmapped-for-BUY runtime signals are available |
| Publication | No pilot payload for after-buy sections | 5 pilot payloads for "Hành vi sau phá vỡ": Bull Pennant, Broadening Bottoms, Ascending Triangle, Rectangle Bottoms, H&S Bottoms |

Realtime trial:

```bash
PYTHONPATH=. python3 -m scanner.run_realtime_scan_watchlist \
  --lookback-days 30 \
  --pattern bull_flags --pattern bear_flags --pattern bull_pennants \
  --out-dir artifacts/realtime_scan/after_buy_application_trial
```

Result: 3 jobs, 44 watchlist rows.  Bull Flag rows are tagged `actionable_long_cash_candidate_after_buy_confirmed`; Bear Flag rows are tagged `avoid_buy_or_exit_warning`; Bull Pennant rows are tagged `watchlist_only_do_not_promote_until_fold_improves`.

## Quantitative Effect Check

The final validation command is:

```bash
PYTHONPATH=. python3 -m scanner.run_after_buy_quantitative_effect
```

This command reruns the executable branch layer for the 12 priority BUY/watchlist chapters and writes a separate evidence pack under `artifacts/scanner_v2/after_buy_vietnam_v2/quantitative_effect/`.

Current result:

| Outcome | Count |
|---|---:|
| Promoted to tradable-final | 0 |
| Improved without active walk-forward blocker | 0 |
| Unchanged within noise band | 2 |
| Improved but still blocked after rerun | 1 |
| Worse or more conservative | 9 |
| Still blocked by release gate | 12 |

Interpretation: the After-the-Buy V2 layer improves source grounding, scanner overlays, metric planning, defensive routing, publication payloads, and realtime watchlist context.  It does **not** yet prove a broad tradable-score lift across blocked chapters.  Any future score lift must come from real rerun evidence, not from the source-map or prose layer alone.
