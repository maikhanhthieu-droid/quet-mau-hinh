# Project Direction: From Research Data to Trading Application

## Core Thesis

The project should not stop at building a scanner or reproducing a book.

The correct direction is:

1. build a Bulkowski-referenced scanner baseline
2. turn that scanner into a Vietnam-specific pattern research engine
3. use that research engine to describe the Vietnamese market and individual symbols
4. use the same engine to detect current live patterns
5. use the resulting historical research to estimate conditional post-pattern behavior for trading decisions

This creates one continuous pipeline:

`reference research -> scanner -> Vietnam pattern corpus -> market analytics -> symbol analytics -> live detection -> conditional outlook / strategy`

## The 5 Expectations Mapped to Product Direction

### 1. Build a scanner based on Thomas Bulkowski as a research reference

Meaning:

- Bulkowski is the reference baseline for taxonomy, structural pattern rules, and benchmark expectations.
- The scanner should not mechanically copy chapter names. It should preserve Bulkowski compatibility while using a more robust internal architecture.

Project objective:

- maintain a `Bulkowski-compatible research scanner`
- keep family/variant mapping back to the original reference taxonomy
- keep benchmark comparison versus the reference baseline as part of the standard workflow

Success condition:

- every major family has a defensible scanner
- every pattern can be positioned against the Bulkowski reference baseline

### 2. Characterize those patterns using Vietnamese market data and produce a Vietnam research document

Meaning:

- the project must create a Vietnam-specific empirical layer, not just a detector
- the final output should look like a local research corpus inspired by Bulkowski, not a literal copy

Project objective:

- build a `Vietnam Pattern Research Dataset`
- for each pattern/family:
  - frequency
  - calibration vs validation behavior
  - move distribution
  - failure behavior
  - target behavior
  - throwback/pullback behavior
  - sample notes and caveats

Deliverable:

- `Vietnam Pattern Research Report`
- eventually a book/report/site/API, but the core asset is the research dataset

Success condition:

- the project can say how a pattern behaves in Vietnam, not just whether it exists

### 3. Show which patterns are common in Vietnam

Meaning:

- the project should describe the Vietnamese market structurally, not only pattern-by-pattern

Project objective:

- build a `market-level prevalence layer`

Key questions:

- which patterns appear most often in Vietnam?
- which families dominate by sector, capitalization, or liquidity bucket?
- which patterns are common but weak?
- which patterns are rare but high-quality?

Deliverables:

- `Pattern prevalence report for Vietnam`
- market heatmaps / ranking tables
- family-level and variant-level prevalence summaries

Success condition:

- the project can describe the Vietnamese market in pattern terms, not only backtest isolated chapters

### 4. Show which patterns a stock XXX often exhibits

Meaning:

- the system should profile symbols, not just patterns

Project objective:

- build a `symbol pattern profile` layer

Key questions:

- stock `XXX` historically tends to show which pattern families?
- which patterns recur on that stock?
- which of those patterns are strongest or weakest for that symbol?
- does the symbol behave like the market average or have its own pattern fingerprint?

Deliverables:

- per-symbol pattern profile
- per-symbol recurring family distribution
- per-symbol success / failure summary

Success condition:

- for any stock, the system can describe its historical pattern personality

### 5. Detect what pattern a stock XXX is showing now and estimate likely price direction

Meaning:

- this is the bridge from research to trading application
- it must be built on conditional historical evidence, not on unsupported prediction language

Project objective:

- build a `live pattern detection + conditional outlook` layer

Key questions:

- what pattern is currently active on stock `XXX`?
- how similar is it to validated historical cases?
- what usually happened next in Vietnam after similar cases?
- what is the likely path in terms of:
  - continuation / reversal bias
  - target tendency
  - failure risk
  - boundary invalidation risk
  - timing tendency

Deliverables:

- live scanner view
- pattern-level outlook report
- later: signal ranking / strategy layer

Success condition:

- the system can turn current pattern detection into a disciplined conditional expectation report

## The Project Should Be Organized Into 4 Layers

### Layer A: Scanner Platform

Purpose:

- detect patterns consistently and map them back to the reference taxonomy

Output:

- pattern detections
- family metrics
- variant metadata

This layer is largely the result of Stage 1.

### Layer B: Vietnam Research Corpus

Purpose:

- turn detections into reliable local research statistics

Output:

- family and variant performance tables
- prevalence tables
- benchmark deltas vs Bulkowski
- sample-quality notes

This should be the first major focus of Stage 2.

### Layer C: Analytics Products

Purpose:

- expose the research corpus in forms useful to users and researchers

Output:

- market-level prevalence reports
- symbol-level pattern profiles
- sector / liquidity / time-split pattern analytics

This is how expectations 3 and 4 become concrete products.

### Layer D: Live Outlook / Strategy

Purpose:

- connect current pattern detection with historically grounded expectations

Output:

- current pattern dashboard
- conditional outlook report
- later: experimental trading models

This is where expectation 5 lives.

## Recommended Stage 2 Structure

Stage 2 should not be treated as one flat backlog. It should be split into 3 workstreams.

### Workstream 1: Vietnam Research Report

Goal:

- satisfy expectations 2 and 3

Main outputs:

- Vietnam pattern report
- prevalence ranking by family / variant
- benchmark comparison vs Bulkowski

First tasks:

- `gaps` subtype benchmark program
- `measured_move` branch review
- `islands` follow-up decision
- final pattern prevalence tables from unified DB

### Workstream 2: Symbol Pattern Profiling

Goal:

- satisfy expectation 4

Main outputs:

- profile for each stock:
  - common families
  - recurring variants
  - historically strongest / weakest pattern outcomes

First tasks:

- define symbol-level summary schema
- compute top families per symbol
- compute per-symbol quality deltas vs market average
- create query/report layer for `stock -> pattern fingerprint`

### Workstream 3: Live Detection and Conditional Outlook

Goal:

- satisfy expectation 5

Main outputs:

- current active pattern report for a symbol
- conditional historical outlook
- later: candidate trading strategies

First tasks:

- `broadening_bottoms` strategy evaluation
- `double_bottoms_adam_adam` watchlist review
- `double_tops_adam_adam` watchlist review
- define the output contract:
  - current pattern
  - confidence
  - similar historical cohort
  - expected move range
  - failure risk
  - time horizon

## Official Direction of the Project

The project should now be managed with this priority:

1. preserve the scanner as a research-grade reference engine
2. build the Vietnam research corpus
3. publish market-level and symbol-level analytics
4. expose live pattern detection
5. turn validated live detection into conditional trading applications

This means:

- the project is no longer “just a scanner”
- it is also not “just a book project”
- it is a `research-to-application platform` built on Vietnam market data using Bulkowski as the baseline reference

## What Counts as Success for the Whole Project

The project succeeds if, for any pattern or symbol, it can answer these 5 questions:

1. What is the reference pattern definition?
2. How does this pattern behave in Vietnam?
3. How common is it in the Vietnamese market?
4. How does a specific stock historically express this pattern family?
5. If the pattern appears now, what has historically happened next in similar Vietnamese cases?

When the project can answer those 5 questions reliably, it will have achieved the full direction you described: `from research data to trading application`.
