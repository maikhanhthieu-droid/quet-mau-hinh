"""Guard rails for legacy scanner entrypoints.

The project is rebuilding the source-book-to-scanner-to-PDF pipeline on
Scanner V2. Legacy scanners are kept only for historical comparison and should
not be run accidentally while the rebuild is in progress.
"""

from __future__ import annotations

import os


ALLOW_LEGACY_ENV = "CHARTPATTERNSCAN_ALLOW_LEGACY_SCANNER"
ALLOW_LEGACY_PUBLICATION_ENV = "CHARTPATTERNSCAN_ALLOW_LEGACY_PUBLICATION_BUILDER"


def legacy_enabled() -> bool:
    return str(os.getenv(ALLOW_LEGACY_ENV, "")).strip().lower() in {"1", "true", "yes", "on"}


def require_legacy_enabled(entrypoint: str) -> None:
    if legacy_enabled():
        return
    raise RuntimeError(
        f"{entrypoint} is quarantined legacy scanner logic. "
        "Use Scanner V2 for new research/PDF work. "
        f"For historical comparison only, rerun with {ALLOW_LEGACY_ENV}=1."
    )


def legacy_publication_enabled() -> bool:
    return str(os.getenv(ALLOW_LEGACY_PUBLICATION_ENV, "")).strip().lower() in {"1", "true", "yes", "on"}


def require_legacy_publication_builder_enabled(entrypoint: str) -> None:
    if legacy_publication_enabled():
        return
    raise RuntimeError(
        f"{entrypoint} is quarantined legacy PDF publication logic. "
        "Final chapters must be rendered through canonical_publication_chapter_factory_v1. "
        f"For historical comparison only, rerun with {ALLOW_LEGACY_PUBLICATION_ENV}=1."
    )
