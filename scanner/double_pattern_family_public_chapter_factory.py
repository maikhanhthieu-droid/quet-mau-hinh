"""Double Pattern Family public-chapter factory.

Double Pattern chapters share the same publication core as Flag/Triangle, but
own their reversal vocabulary, target unit, quality checks, and family identity.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping

import pandas as pd

from scanner.canonical_publication_chapter_factory import build_canonical_publication_chapter


DOUBLE_PATTERN_FAMILY_FACTORY_ID = "double_pattern_family_public_chapter_factory_v1"
FACTORY_ID = DOUBLE_PATTERN_FAMILY_FACTORY_ID


def build_double_pattern_public_chapter(
    *,
    payload: Mapping[str, Any],
    source_notes: Mapping[str, Any],
    events: pd.DataFrame,
    path_df: pd.DataFrame,
    charts: Mapping[str, Path],
    spec: Mapping[str, Any],
    out_dir: Path,
    pdf_filename: str,
    payload_filename: str,
    manuscript_filename: str,
    notes_filename: str,
) -> Dict[str, Path]:
    return build_canonical_publication_chapter(
        payload=payload,
        source_notes=source_notes,
        events=events,
        path_df=path_df,
        charts=charts,
        spec={**dict(spec), "family_id": "double_pattern_family"},
        out_dir=out_dir,
        pdf_filename=pdf_filename,
        payload_filename=payload_filename,
        manuscript_filename=manuscript_filename,
        notes_filename=notes_filename,
        family_id="double_pattern_family",
        source_family_factory_id=DOUBLE_PATTERN_FAMILY_FACTORY_ID,
    )
