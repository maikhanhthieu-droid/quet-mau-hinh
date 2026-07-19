# Stage 2 Research / Strategy Backlog

## Purpose

Stage 2 starts after the Stage 1 scanner and governance overhaul is closed.

Stage 2 is not another infrastructure-overhaul phase. Its purpose is to:

- turn the Stage 1 baseline into a usable research program
- decide which families can graduate toward strategy evaluation
- reduce the remaining benchmark drift versus the Bulkowski reference baseline
- split broad families into more decision-useful research cohorts

## Stage 1 Baseline

Reference baseline for Stage 2:

- Stage 1 closure: [stage1-closure-report.md](stage1-closure-report.md)
- Final snapshot: `scan_results/audits/spec-audit-20260308/snapshots/final-snapshot/final_overhaul_snapshot.md`
- Final governance: `scan_results/audits/spec-audit-20260308/snapshots/final-snapshot/phase3/phase3_governance_report.md`
- Final benchmark: `scan_results/audits/spec-audit-20260308/snapshots/final-snapshot/benchmark/benchmark_report.md`

Current baseline counts:

- `1` candidate
- `2` watchlist
- `40` research_only
- `7` recalibrate
- `5` retire_from_strategy

Current benchmark counts:

- `9` materially_weaker
- `4` mixed
- `2` roughly_aligned
- `23` sparse
- `15` no_benchmark

## Stage 2 Principles

- Strategy work only starts from `candidate` or `watchlist` branches.
- Recalibration work must be family-first, not chapter-by-chapter.
- Broad families should be split into research cohorts or subtypes before more threshold tuning.
- Sparse families are not forced into production lanes.
- Every major pass ends with a rerun, governance refresh, and benchmark refresh.

## Official Priority Queue

### P0: Strategy-Critical

#### 1. `broadening_bottoms` strategy evaluation

Goal:

- Decide whether `broadening_bottoms` can enter a Stage-2 experimental strategy lane.

Why first:

- It is the only live `candidate`.
- Stage 1 already produced a dedicated candidate evaluation pack.

Work:

- define strategy entry/exit rules around the existing detector
- test robustness by cohort, especially `all` vs `narrower_core`
- check sensitivity to hold window, stop logic, and target policy
- document whether the branch is `strategy_trial`, `stay_candidate`, or `demote`

Done when:

- there is a written go/no-go decision for the strategy lane
- candidate status is explicitly confirmed or changed in governance

#### 2. `double_bottoms_adam_adam`

Goal:

- Try to move `double_bottoms_adam_adam` from `watchlist` to a stronger benchmark or limited strategy-trial state.

Why second:

- It is one of the two watchlist branches.
- It is one of the most practically useful Bulkowski-style families.

Work:

- review calibration-valid drift directly on the AA branch
- inspect survivor quality and failure clusters
- tune only AA-specific logic if necessary
- do not expand non-AA variants as part of this task

Done when:

- AA has a fresh family rerun and a promotion/demotion decision

#### 3. `double_tops_adam_adam`

Goal:

- Same promotion decision process as `double_bottoms_adam_adam`.

Why third:

- It is the second watchlist branch and the natural paired family to the double-bottom work.

Work:

- repeat the same AA-only process as bottoms
- compare calibration-valid drift and failure behavior
- keep non-AA variants out of scope unless a blocker requires them

Done when:

- AA has a fresh family rerun and a promotion/demotion decision

### P1: Research Families With Clear Leverage

#### 4. `measured_move_down_up` branch split review

Goal:

- Convert the Stage 1 rewrite into a stable Stage 2 research family.

Why now:

- The dedicated scanner is already in place.
- `measured_move_up` improved enough to leave recalibration backlog.
- `measured_move_down` still looks mixed.

Work:

- benchmark `measured_move_up` and `measured_move_down` separately
- decide whether bearish branch needs a targeted tightening pass
- keep the bullish branch stable unless evidence says otherwise

Done when:

- up/down branches have separate benchmark conclusions
- governance note no longer describes this family as “new rewrite pending review”

#### 5. `gaps` subtype benchmark program

Goal:

- Turn `gaps` from one broad research family into a useful subtype research surface.

Why now:

- Stage 1 already added subtype labels:
  - `common`
  - `continuation`
  - `exhaustion`
  - `breakaway`

Work:

- compare subtype performance across direction and split
- identify which subtype cohorts deserve active research and which should be downgraded
- decide whether governance should move from one family-level status to subtype-aware policy

Done when:

- a subtype benchmark report exists
- governance has explicit decisions for major subtype cohorts

#### 6. `islands` follow-up decision

Goal:

- Decide whether Stage 1’s sharp contraction is the correct final family shape.

Why now:

- `island_reversals` became structurally credible
- `islands_long` disappeared entirely

Work:

- review whether `islands_long` should remain reference-only
- only explore a long-island detector if there is evidence that the Stage 1 gate is too strict
- otherwise freeze long islands and keep only regular island reversals in the research lane

Done when:

- there is an explicit `keep frozen` or `build long-island detector` decision

### P2: Recalibration Backlog

#### 7. `scallop_ascending_descending`

Goal:

- Resolve the remaining weak branches, especially `ascending_inverted` and `descending`.

Why here:

- Stage 1 improved the family, but it is still in recalibration backlog.

Done when:

- family rerun is refreshed
- governance either reduces recalibration scope or confirms the family should stay blocked

#### 8. `three_falling_peaks`

Goal:

- Reduce drift and decide whether the family can move from recalibration into stable research.

Done when:

- a dedicated rerun and refreshed governance note exist

#### 9. `three_rising_valleys`

Goal:

- Same as `three_falling_peaks`, but for the bullish counterpart.

Done when:

- a dedicated rerun and refreshed governance note exist

#### 10. `double_bottoms_eve_eve`

Goal:

- Reassess whether this branch should remain in recalibration backlog or be downgraded.

Why lower priority:

- It is much thinner than the AA watchlist branch.

Done when:

- branch is either stabilized or explicitly demoted to reference-only/research-only

### P3: Secondary Research / Drift Cleanup

#### 11. `cup_with_handle`

Goal:

- Decide whether the bullish branch deserves more tuning or should simply remain stable research coverage.

Note:

- `cup_with_handle_inverted` stays out of active work unless a new bearish detector concept appears.

#### 12. `triangles`

Goal:

- Improve benchmark quality after the Stage 1 family refactor, especially for branches still sitting in `mixed`.

#### 13. `broadening_wedges`, `horns`, `pipe`, `triple`, `flags`

Goal:

- Keep as stable research families and only revisit if benchmark drift or new data justifies it.

## Execution Order

Stage 2 should run in this order:

1. `broadening_bottoms`
2. `double_bottoms_adam_adam`
3. `double_tops_adam_adam`
4. `measured_move_down_up`
5. `gaps`
6. `islands`
7. `scallop_ascending_descending`
8. `three_falling_peaks`
9. `three_rising_valleys`
10. `double_bottoms_eve_eve`
11. `cup_with_handle`
12. `triangles`
13. stable-family monitoring

## Deliverables Per Batch

Every Stage 2 batch should end with:

- family-level rerun DBs for valid and calibration
- one benchmark delta note
- one governance refresh
- one short batch summary with:
  - what changed
  - what improved
  - what remains blocked

## Stage 2 Exit Criteria

Stage 2 can be considered complete when:

- `broadening_bottoms` has a final strategy-lane decision
- both watchlist double-pattern branches have promotion or demotion decisions
- `gaps` is governed at subtype level, not just family level
- `measured_move` has a stable up/down research posture
- the recalibration backlog is materially reduced from `7` to a smaller, explicitly justified set
- a new benchmark/governance final snapshot is produced for the end of Stage 2
