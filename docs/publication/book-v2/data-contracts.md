# Book V2 Data Contracts

## Purpose

This document defines the stable payload contracts that Book v2 and related Stage 2 outputs should consume.

These contracts separate:

- deterministic research facts
- optional commentary
- final presentation

The goal is that every major output can be rendered correctly without AI.

## Contract Set

### 1. Market Report

Purpose:

- describe the Vietnamese market structurally in pattern terms

Schema:

- [schemas/book_v2/market_report.schema.json](../../../schemas/book_v2/market_report.schema.json)

Current producer:

- [build_vietnam_research_report.py](../../../scanner/build_vietnam_research_report.py)

### 2. Pattern Monograph

Purpose:

- deterministic chapter payload for one pattern or one canonical family

Schema:

- [schemas/book_v2/pattern_monograph.schema.json](../../../schemas/book_v2/pattern_monograph.schema.json)

Current producer:

- [build_pattern_monographs.py](../../../scanner/build_pattern_monographs.py)

### 3. Symbol Profile

Purpose:

- summarize the historical pattern fingerprint of one symbol

Schema:

- [schemas/book_v2/symbol_profile.schema.json](../../../schemas/book_v2/symbol_profile.schema.json)

Current producer:

- [build_symbol_pattern_profiles.py](../../../scanner/build_symbol_pattern_profiles.py)

### 4. Current Outlook

Purpose:

- connect current detections with historical conditional behavior

Schema:

- [schemas/book_v2/current_outlook.schema.json](../../../schemas/book_v2/current_outlook.schema.json)

Planned producer:

- `scanner/build_current_outlook_reports.py`

## Design Rules

All four contracts should follow the same rules:

1. top-level payloads are deterministic
2. benchmark and governance fields come from locked research outputs
3. figures and example cases are attached as explicit fields, not inferred by AI
4. optional AI commentary must live outside the core payload

## Commentary Layer Rule

Book v2 commentary must not mutate the core payload.

Recommended layer model:

- `payload.json`
- `core.md`
- `commentary.md`
- `final.md`

This allows:

- fully deterministic builds
- optional DeepSeek augmentation
- stable cache invalidation

## Deterministic Sample Rules

Representative cases for pattern monographs follow deterministic selection rules documented in:

- [sample-selection-rules.md](sample-selection-rules.md)

## Current Scope

Phase 1 defines the contracts and removes the old publication builder from the active path.

Phase 2 should implement:

- pattern monograph payload generation
- deterministic monograph rendering

Phase 3 should implement:

- optional DeepSeek commentary
- final book assembly
