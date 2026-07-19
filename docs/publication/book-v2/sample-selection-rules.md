# Book V2 Sample Selection Rules

## Purpose

Representative cases in Book v2 must be selected deterministically.

They should show:

- what a strong survivor looks like
- what a typical case looks like
- what a stress or failure-looking case looks like
- how calibration compares with validation

These rules are implemented in:

- [build_pattern_monographs.py](../../../scanner/build_pattern_monographs.py)

## Selection Order

### 1. `best_case`

Source:

- validation split only

Rule:

- target hit required
- boundary invalidation not allowed
- highest favorable excursion wins
- ties prefer lower adverse excursion

Purpose:

- show the cleanest validation survivor

### 2. `typical_case`

Source:

- validation split only

Rule:

- compute median favorable excursion across validation survivors
- choose the case closest to that median
- ties prefer no invalidation and target hit

Purpose:

- show a case that is representative rather than exceptional

### 3. `stress_case`

Source:

- validation split only

Rule:

- boundary invalidation, no target hit, or elevated adverse excursion qualifies
- ties prefer explicit invalidation and larger adverse excursion

Purpose:

- show what a weak or failure-prone survivor looks like

### 4. `calib_reference`

Source:

- calibration split only

Rule:

- prefer target hit
- prefer no invalidation
- then prefer stronger favorable excursion

Purpose:

- provide one calibration-side comparison case

## Constraints

- no case may appear twice in the same chapter
- cases must be sourced from the final unified DB, not hand-picked from legacy book artifacts
- image paths are optional; the deterministic chapter core should remain valid even without generated figures

## Rationale

These rules keep the chapter core:

- reproducible
- interpretable
- comparable across patterns
- independent of AI
