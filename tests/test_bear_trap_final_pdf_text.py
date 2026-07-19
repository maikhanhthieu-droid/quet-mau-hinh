import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scanner.apply_bear_trap_publication_reframe import BEAR_PATTERN_IDS


MANIFEST = Path("artifacts/final_chapters/final_chapters_manifest.json")


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext is required for final PDF text audit")
def test_bear_trap_final_pdfs_use_public_reclaim_framing() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    chapters = {row["pattern_id"]: row for row in manifest["chapters"]}
    for pattern_id in BEAR_PATTERN_IDS:
        pdf = Path(chapters[pattern_id]["pdf"])
        text = subprocess.run(
            ["pdftotext", str(pdf), "-"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert "Dùng để kiểm tra bẫy giảm sau phá vỡ" in text
        assert "quay lại vùng phá vỡ" in text
        assert "defensive/informational" not in text
        assert "stop-loss" not in text
        assert "BUY signal" not in text
        assert "short setup" not in text
        assert "retuyên bố" not in text
        assert "bear_trap_stoploss_publication_reframe_v1" not in text
        assert "bear trap stoploss" not in text
