# Per-Pattern Tradable Workflow

This project does not promote a chapter to `tradable-final-95` just because the publication chapter is strong.  Each pattern must pass a separate executable layer.

## Required Sequence

1. Source morphology audit
   - Confirm the pattern-specific shape against the Bulkowski source notes.
   - Do not reuse another family scanner except for shared infrastructure.

2. Publication chapter
   - Build the investor-facing reference chapter with source-grounded narrative, examples, statistics, and caveats.
   - This can reach `publication_final` without being tradable.

3. Tradable preflight
   - Run the lightweight preflight score to decide whether deeper execution work is worth doing.
   - Treat this as triage, not promotion evidence.
   - Use the chapter's calibrated base target when available.
   - If aggregate scoring hides a known source-safe branch, record the branch explicitly instead of silently changing the sample.
   - If a weak preflight chapter is still being optimized, run `preflight_branch_ceiling_audit_v1`; stop this layer when no unselected branch adds at least 3 score points.

4. Pattern-specific tradable audit
   - Test entry, exit, stop, target, cost, slippage, sizing, capacity, validation, holdout, walk-forward, cost stress, and Monte Carlo.
   - Build scanner/source branches only for the blocker that is actually observed.

5. Blocker matrix
   - Record the primary blocker and next action in `artifacts/final_chapters/governance/tradable_blocker_matrix.*`.
   - If the blocker is real under current data, lock the chapter at the correct use label instead of forcing a higher tier.

6. No-overlift decision
   - `tradable-final-95` requires score >= 95 and no hard blocker.
   - Do not weaken gates, pick parameters on holdout, or narrow the sample until the result merely looks better.
   - For non-final chapters that still look improvable, run `tradable_candidate_ceiling_audit_v1` after all local audits. Stop when no known evidence layer adds at least 3 points or clears promotion review.

7. Family rescue when variants are too thin
   - If Adam/Eve-style variants have too few standalone validation/holdout trades, test a source-grounded family branch instead of forcing each variant through an impossible standalone gate.
   - Report the variants as subgroups inside the family branch; do not automatically promote each variant to `tradable-final-95`.
   - A family rescue can support a family-level chapter or promotion review only when the branch is source-safe, score >= 95, fixed walk-forward has no negative fold, and the scope is direct long cash equity.
   - Downside/top families remain defensive/informational on cash equities even when the statistical execution score is high.

## Current Pattern Lessons

- Bull Flag: benchmark `tradable-final-95`.
- Double Bottom Adam & Adam: dynamic retest/reclaim entry clears the current `tradable-final-95` gate under available-series scope.
- Ascending Triangle: publication/investment-reference candidate, but fold instability blocks tradable promotion.
- Falling Wedge: locked as watchlist/reference under current data due to liquidity and walk-forward blockers.
- Symmetrical Triangle: aggregate mixed-direction score is misleading; publication/preflight can use a source-safe branch, but tradable promotion still requires a separate up-breakout branch to pass.
- Bear Flag, Bull Pennant, Symmetrical Triangle, and Rising Wedge: current preflight branch ceiling audit finds no remaining material branch lift; further improvements must come from data depth, scope, or tradable execution logic, not more preflight branch mining.
- Bull Pennant, Rising Wedge, Double Top Adam & Adam, Descending Triangle, Falling Wedge, Ascending Triangle, Symmetrical Triangle, and Bear Flag: current tradable ceiling audit finds no computed evidence layer with remaining material score lift. Treat remaining blockers as true contract/data/scope blockers until new data or a preregistered execution design exists.
- Double Pattern Family: individual Adam/Eve variants can be too thin for standalone tradable promotion. `double_family_tradable_rescue_v1` shows Double Bottoms can be evaluated as a family-level long cash setup with variants as subgroups, while Double Tops remains defensive/informational even when the family score is high.

## Implementation Rule

Shared code should stay at the statistics/governance/report-factory layer.  Scanner geometry, branch filters, and tradable entry logic must remain pattern- or family-specific.
