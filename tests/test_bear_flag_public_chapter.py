from __future__ import annotations

import json
from pathlib import Path

from pypdf import PdfReader

from scanner.build_bear_flag_public_chapter import build_public_chapter
from scanner.build_bear_flag_source_grounding import build_source_notes
from scanner.canonical_publication_chapter_factory import CANONICAL_PUBLICATION_FACTORY_ID
from scanner.flag_family_public_chapter_factory import FACTORY_ID


def test_bear_flag_source_notes_are_grounded() -> None:
    notes = build_source_notes()

    assert notes["status"] == "PASS"
    assert notes["local_source"]["pattern_key"] == "bear_flags"
    assert notes["thepatternsite_measure_rule"]["flags_down_breakout_rule"].startswith("Flag high")
    assert notes["bulkowski_book_2e_stats"]["downward_breakouts"]["pullbacks_bull_bear_pct"] == [46, 44]


def test_bear_flag_public_chapter_emits_defensive_pdf_with_examples(tmp_path: Path) -> None:
    paths = build_public_chapter(out_dir=tmp_path / "bear_public")

    assert paths["pdf"].exists()
    assert paths["pdf"].stat().st_size > 100_000
    assert paths["chart_schematic"].exists()
    assert paths["chart_textbook_success"].exists()
    assert paths["chart_middle_case"].exists()
    assert paths["chart_failure"].exists()
    assert paths["manifest_json"].exists()

    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(paths["pdf"])).pages)
    assert len(text) > 14_000
    assert "Kết quả quan trọng" in text
    assert "Nhóm điều kiện đọc chính" in text
    assert "defensive_expanded" not in text
    assert "Audit nhánh scanner" not in text
    assert "Cách nhận diện" in text
    assert "Ví dụ minh họa" in text
    assert "Tập trung vào thất bại" in text
    assert "Mục tiêu giá" in text
    assert "Khi nên đọc thận trọng" in text
    assert "Khi mẫu đáng chú ý hơn" in text
    assert "Cách sử dụng thực tế" in text
    assert "Phụ lục kỹ thuật" in text
    assert "không phải khuyến nghị bán khống" in text

    payload = json.loads(paths["payload"].read_text(encoding="utf-8"))
    assert payload["factory_id"] == CANONICAL_PUBLICATION_FACTORY_ID
    assert payload["source_family_factory_id"] == FACTORY_ID
    assert payload["publication_id"] == "bear_flag_publication_chapter_v1"
    groups = {event["market_group"] for event in payload["example_events"].values()}
    assert groups & {"VN30", "VN100 ex VN30"}
