# Scanner V2 Contract Layer

Scanner V2 starts from source fidelity, not detector convenience.

The current package is a contract-first foundation:

1. `core_patterns.json` stores the first provenance-seeded rules for the core pattern group.
2. `taxonomy_lineage.json` maps each pattern across the required chain:
   `Bulkowski chapter -> extracted source rule -> normalized rule spec -> scanner pattern key -> result payload -> book v2 chapter`.
3. `contracts.py` compiles a pattern only when provenance, lineage, and rule coverage are valid.

Activation policy:

- No provenance, no official scanner.
- Evidence excerpts must align to the claimed PDF pages.
- Unsupported rule type is a compile error.
- Golden fixtures are required before a pattern can be activated as official.
- Result metadata uses a full normalized spec hash, so any rule change changes the scanner identity.

Current official V2 patterns:

- `bull_flags` (available-series watchlist-reference candidate; active Market Stats universe gate passes, but no full point-in-time universe claim)
- `bear_flags` (defensive/informational candidate in the same Flag Family; not a cash-equity short recommendation)

Remaining core patterns are still draft and should not be used as official research scanners until
their provenance and fixtures pass the same gate.

The legacy scanner remains useful as a benchmark/prototype. V2 is the path for research-grade scans.

## Scanner Matrix

The scanner matrix is the standard expansion path for multiple chart patterns:

```text
Independent pattern scanner -> scanner matrix event contract -> common metrics/charts/PDF/watchlist
```

Flag Family is the reference implementation. Bull Flag remains the first completed public chapter, and Bear Flag is the next family branch. Their output is normalized by
`scanner.v2.matrix.normalize_bull_flag_events` into the shared event schema:

- `pattern_id`, `scanner_pattern_key`, `spec_hash`, `source_chapters`
- `formation_start`, `formation_end`, `confirmation_date`, `direction`, `confirmation_price`
- `target_family`, `setup_score`, `confirmation_score`, `followthrough_score`, `context_score`
- `market_regime`, `liquidity_bucket`, `path_quality`, `data_quality_bucket`

The rule for scaling is strict:

- scanner logic is pattern-specific;
- event output is common;
- Flag Family is the template for matrix output, not the geometry template for unrelated pattern families.

## Family-Based Architecture Principle

The project uses shared infrastructure only at the statistical/output layer.
Pattern logic is not shared across unrelated pattern families.

Shared across the whole project:

- OHLCV/path loading conventions.
- Scanner matrix event schema.
- Post-breakout statistics: target hit, failure, target-first-before-adverse, MFE, MAE, quantiles, Wilson intervals, and robustness tables.
- Thin PDF/table/chart rendering primitives.

Owned by each family:

- Geometry language and reader-facing terms.
- Target unit and target-family interpretation.
- Chapter structure details that depend on the family.
- Example-selection rules when the family requires different context.

Owned by each pattern:

- Scanner thresholds and branch logic.
- Setup-quality, confirmation, and follow-through scoring.
- Local calibration and optimization.

Current publication boundary:

- `scanner.pattern_publication_core`: thin statistical/publication core. It must stay pattern-agnostic.
- `scanner.flag_family_public_chapter_factory`: Flag Family publication factory.
- `scanner.triangle_family_public_chapter_factory`: Triangle Family publication factory.

The lesson from Bull/Bear Flag is now a hard rule: each pattern may require
its own optimization. A family can share language and structure only when the
patterns in that family genuinely share geometry and target semantics.

Build the current matrix artifacts with:

```bash
python scanner/run_scanner_matrix.py
```

Outputs:

- `artifacts/scanner_v2/scanner_matrix/scanner_matrix_events.csv`
- `artifacts/scanner_v2/scanner_matrix/scanner_matrix_manifest.json`
