from __future__ import annotations

from pathlib import Path

from scanner.compare_bear_flag_public_chapters import build_comparison


def test_bear_flag_public_chapter_comparison_promotes_db_active_when_available(tmp_path: Path) -> None:
    paths = build_comparison(out_dir=tmp_path / "comparison")

    assert paths["json"].exists()
    text = paths["md"].read_text(encoding="utf-8")
    assert "PROMOTE_DB_ACTIVE_CHAPTER_CANDIDATE" in text
    assert "Headline N: 24" in text
