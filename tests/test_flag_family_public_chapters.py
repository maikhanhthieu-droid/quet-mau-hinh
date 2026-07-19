from __future__ import annotations

import json
from pathlib import Path

from scanner.canonical_publication_chapter_factory import CANONICAL_PUBLICATION_FACTORY_ID
from scanner.flag_family_public_chapter_factory import FACTORY_ID


def test_flag_family_manifest_has_both_db_active_chapters() -> None:
    manifest_path = Path("artifacts/scanner_v2/flag_family_public_chapters/flag_family_public_chapters_manifest.json")
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chapters = {row["pattern_id"]: row for row in manifest["chapters"]}

    assert manifest["factory_id"] == FACTORY_ID
    assert set(chapters) == {"bull_flags", "bear_flags"}
    assert chapters["bull_flags"]["all_n"] == 193
    assert chapters["bear_flags"]["headline_n"] == 50
    assert "point-in-time all-market universe" in manifest["source_scope"]

    for chapter_key in ["bull_flag", "bear_flag"]:
        payload_path = Path(manifest["outputs"][chapter_key]["payload"])
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        assert payload["factory_id"] == CANONICAL_PUBLICATION_FACTORY_ID
        assert payload["source_family_factory_id"] == FACTORY_ID
