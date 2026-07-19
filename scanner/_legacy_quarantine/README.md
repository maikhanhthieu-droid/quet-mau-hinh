# Legacy Publication Quarantine

Files in this folder are historical artifacts only. They are not part of the
active publication flow and must not be imported by active scanner, statistics,
or PDF code.

The only allowed final publication path is:

```text
canonical_editorial_workflow_v1
  -> canonical_chapter_content_generator_v1
  -> canonical_ai_editorial_gate_v1
  -> canonical_publication_chapter_factory_v1
  -> pattern_publication_core_v1
```

If a quarantined script is needed for historical comparison, it must remain
blocked by `CHARTPATTERNSCAN_ALLOW_LEGACY_PUBLICATION_BUILDER=1`.
