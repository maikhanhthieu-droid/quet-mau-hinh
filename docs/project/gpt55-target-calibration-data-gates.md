# GPT 5.5 research integration: target calibration and data gates

Date: 2026-05-16

This note converts the latest GPT 5.5 research response into implementation decisions for Scanner V2. It is an operational bridge, not a new academic source.

## Locked Decisions

- Treat current Scanner V2 outputs as an empirical post-breakout catalog, not a trading system.
- Do not use full `1.0x` measure rules as the default target for every pattern family.
- Keep `1.0x` as a legacy benchmark, then add Bulkowski-adjusted fractional targets as candidate base targets.
- Classify downside patterns in Vietnam cash equities as informational or defensive by default unless a separate instrument/execution layer is proven.
- Run data gates before ranking patterns.

## Target Families

| Pattern family | Base target | Additional bands | Legacy benchmark |
|---|---:|---|---:|
| Flag Family | `0.46x` pole height | `0.5x`, `0.75x` | `1.0x` |

The base target is not a tuned profit objective. It is the first empirical-calibration benchmark for the chapter. Selection must be validated by target-first-before-adverse, failure containment, Wilson confidence intervals, and holdout/regime robustness before being promoted.

## Data Gates

A chapter cannot move above descriptive-reference until these are disclosed or passed:

- point-in-time universe;
- delisted, halted, and suspended symbol coverage;
- corporate-action and adjusted OHLCV audit;
- liquidity filter and microstructure notes;
- overlap policy;
- VN30/VN100 membership point-in-time if those groups are used;
- price-limit and settlement caveats for path metrics.

## Current Pattern Triage

| Pattern | Current lane | Reason |
|---|---|---|
| Bull Flag | watchlist-reference candidate | Best current asymmetry; should be promoted from experiment only after provenance and data gates are added. |
| Bear Flag | informational/defensive-reference | Weak path statistics and limited downside executability in Vietnam cash equities. |

## Immediate Engineering Changes

- Research support analysis now uses pattern-specific target families.
- The next official Scanner V2 promotion candidate should be Bear Flag within the Flag Family lane, not a new unrelated pattern family.
- Ranking must wait until target families and data gates are encoded.
