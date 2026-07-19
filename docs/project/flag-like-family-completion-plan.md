# Flag-like Family Completion Plan

## Scope

The completed narrow Flag Family contains Bull Flag and Bear Flag. The broader
Flag-like continuation family adds Pennants and High-and-Tight Flags, but these
must not inherit Flag geometry. Shared infrastructure is limited to statistics,
calibration, release gates, and publication rendering.

## Current Status

| Pattern | Source chapter | Implementation state | Publication lane |
|---|---:|---|---|
| Bull Flag | 21 | Final chapter exists | Watchlist / investment-reference under available-series scope |
| Bear Flag | 21 | Final chapter exists | Defensive / informational |
| Bull Pennant | 34 | Final chapter exists | Watchlist-reference under available-series scope |
| Bear Pennant | 34 | Candidate scanner run | Defensive / informational candidate |
| High-and-Tight Flag | 22 | Source-grounded only | Detector required before any chapter |

## Pennant Candidate Scan

Full Market Stats V1 run:

- Symbols scanned: 1,414
- Total Pennants: 1,657
- Bull Pennants: 952
- Bear Pennants: 705

Headline result:

- Bull Pennant shows usable directionality: median MFE 14.05%, median MAE
  9.45%, MFE/MAE about 1.49.
- Bear Pennant is weaker as an opportunity pattern: median MFE 9.72%, median
  MAE 11.29%, MFE/MAE about 0.86.
- Raw 1.0x pole target is too demanding for the whole family. Any public chapter
  must run a source-aligned target calibration rather than presenting the raw
  pole projection as the base target.

## Bull Pennant Final Gate Result

Bull Pennant passed the available-series publication gate and was promoted to
`artifacts/final_chapters/flag_family/bull_pennant_final.pdf`.

- Public-grade sample: 929 events.
- Base target: 0.5x pole height.
- Base target hit rate: 69.64%.
- Target-first-before-adverse-5%: 39.40%.
- Failure 5%: 21.64%.
- Cluster-bootstrap MFE/MAE ratio CI: 1.29-1.69.
- Final manifest: PASS with 16 chapters.

## Gates Before Additional Public PDFs

1. Bear Pennant needs a separate defensive/informational branch decision before
   any public chapter.
2. High-and-Tight Flag needs its own detector before any chapter.
3. Source-grounding audit must remain PASS for every promoted pattern.
4. Publication factory must use the same semantic gate as Flag Family and must
   not expose internal audit/payload language.

## High-and-Tight Flag Blocker

High-and-Tight Flags require a dedicated detector. The source pattern is not a
normal flag: it requires a near-doubling advance in under two months, a tight
consolidation near the high, upward breakout only, and a half-prior-move target.
Until that detector exists, this pattern remains source-grounded but not
publication-ready.
