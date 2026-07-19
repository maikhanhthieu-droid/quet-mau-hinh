from __future__ import annotations

import json
from pathlib import Path

from pypdf import PdfReader

from scanner.build_symmetrical_triangle_public_chapter import build_symmetrical_triangle_public_chapter
from scanner.build_triangle_family_public_chapters import build_triangle_family_public_chapters
from scanner.canonical_publication_chapter_factory import CANONICAL_PUBLICATION_FACTORY_ID
from scanner.triangle_family_public_chapter_factory import FACTORY_ID


def test_ascending_triangle_public_chapter_uses_shared_public_flow(tmp_path: Path) -> None:
    paths = build_triangle_family_public_chapters(out_dir=tmp_path / "triangle_family")

    assert paths["pdf"].exists()
    assert paths["pdf"].stat().st_size > 100_000
    assert paths["manifest_json"].exists()

    payload = json.loads(paths["payload"].read_text(encoding="utf-8"))
    assert payload["factory_id"] == CANONICAL_PUBLICATION_FACTORY_ID
    assert payload["source_family_factory_id"] == FACTORY_ID
    assert payload["pattern_id"] == "triangles_ascending"
    assert payload["chapter_reference"]["all_scanner_events"] == 1745
    assert payload["chapter_reference"]["events"] == 877
    assert payload["chapter_reference"]["scope"] == "nhóm tốt nhất + nhóm chuẩn đủ điều kiện công bố"
    assert payload["editorial_source_path"].endswith(
        "source_guided_refinement_final_v1/triangle_family/ascending_triangle/ai/refined/approved_ai_sections.json"
    )
    premium_validation = payload["chapter_reference"]["premium_visual_validation"]
    assert premium_validation["status"] == "SCORED"
    assert premium_validation["scored_n"] == 28
    assert premium_validation["manual_score_median"] >= 4
    assert premium_validation["premium_visual_gate"] == "PASS"
    assert payload["target_calibration"]["selected_base_target_multiple"] == 1.0
    assert payload["target_calibration"]["selected_base_target_role"] == "source_full_height"
    assert payload["target_calibration"]["base_target"]["target_multiple"] == 1.0
    assert payload["target_calibration"]["legacy_target"]["target_multiple"] == 1.0
    assert payload["target_calibration"]["base_target"]["target_hit_rate"] == 74.23
    assert payload["target_calibration"]["rows"][0]["target_multiple"] == 0.5
    assert payload["target_calibration"]["rows"][0]["target_role"] == "local_caution"
    assert "target_hit_wilson" in payload["chapter_reference"]
    assert payload["example_events"]["textbook_success"]["publication_quality_tier"] == "premium"
    assert payload["example_events"]["textbook_success"]["manual_visual_score_1_to_5"] >= 4
    assert payload["example_events"]["middle_case"]["publication_quality_tier"] == "premium"
    assert payload["example_events"]["middle_case"]["manual_visual_score_1_to_5"] >= 4
    assert payload["example_events"]["textbook_success"]["event_id"] != payload["example_events"]["middle_case"]["event_id"]
    example_validation = payload["chapter_reference"]["example_visual_validation"]
    assert example_validation["status"] == "SCORED"
    assert example_validation["reviewed_n"] == 3
    assert example_validation["manual_pass_rate_pct"] == 100.0
    assert example_validation["failure_example_reviewed"] is True
    assert payload["example_events"]["failure"]["example_manual_visual_score_1_to_5"] >= 4
    assert payload["example_events"]["failure"]["example_manual_visual_bucket"] == "pass"
    example_tiers = {event["publication_quality_tier"] for event in payload["example_events"].values()}
    assert example_tiers <= {"premium", "standard"}

    manifest = json.loads(paths["manifest_json"].read_text(encoding="utf-8"))
    assert manifest["factory_id"] == FACTORY_ID
    assert manifest["chapters"][0]["pattern_id"] == "triangles_ascending"

    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(paths["pdf"])).pages)
    assert "Tam giác tăng" in text
    assert "Kết quả quan trọng" in text
    assert "Cách nhận diện" in text
    assert "Ví dụ minh họa" in text
    assert "Tập trung vào thất bại" in text
    assert "Mục tiêu giá" in text
    assert "Khi nên đọc thận trọng" in text
    assert "Khi mẫu đáng chú ý hơn" in text
    assert "Phụ lục kỹ thuật" in text
    assert "Chất lượng công bố" in text
    assert "Phạm vi kết luận chính" in text
    assert "Khoảng tin cậy" in text or "Wilson" in text
    assert "Kiểm tra bằng mắt nhóm tốt" in text
    assert "Kiểm tra bằng mắt ví dụ" in text
    assert "Ví dụ đã được kiểm tra bằng mắt" in text
    assert "Độ bền theo thời gian" in text
    assert "Tương tác bối cảnh và thanh khoản" in text
    assert "Contract nhân rộng family" not in text
    assert "Release gate trước khi chốt" not in text
    assert "điểm trung vị 4/5" in text
    assert "pass rate" not in text
    assert "xuyên" in text and "trong phiên" in text
    assert "Mốc nguồn" in text or "kết luận chính" in text
    assert "0,5x chỉ là mốc thận trọng" in text
    assert "Mục tiêu 0,5 lần chiều cao tam giác là mốc đọc đầu tiên" not in text
    assert "Lộ trình Triangle Family" not in text
    assert "publication_quality_tier" not in text
    assert "premium" not in text
    assert "standard" not in text
    assert "audit" not in text
    assert "payload" not in text
    assert "factory" not in text
    assert "branch_id" not in text
    assert "Audit nhánh scanner" not in text
    assert "Flag" not in text
    assert "pole" not in text
    assert "cột cờ" not in text
    assert "thân cờ" not in text


def test_triangle_family_manifest_declares_family_specific_scope() -> None:
    manifest = json.loads(Path("scanner/v2/pattern_family_manifest.json").read_text(encoding="utf-8"))
    triangle = manifest["families"]["triangle_family"]

    assert triangle["status"] == "active_candidate"
    assert "pattern-specific" in triangle["family_rule"]
    assert triangle["patterns"]["triangles_ascending"]["status"] == "publication_candidate"
    assert triangle["patterns"]["triangles_ascending"]["quality_gate"].startswith("premium visual validation")
    assert triangle["patterns"]["triangles_ascending"]["release_gate"] == "scanner.validate_triangle_family_release_candidate"
    assert triangle["patterns"]["triangles_descending"]["status"] == "branch_headline_candidate"
    assert triangle["patterns"]["triangles_descending"]["branch_candidate_runner"] == "scanner.analyze_descending_triangle_branch_candidates"
    assert triangle["patterns"]["triangles_symmetrical"]["status"] == "branch_headline_candidate"
    assert triangle["patterns"]["triangles_symmetrical"]["branch_candidate_runner"] == "scanner.analyze_symmetrical_triangle_branch_candidates"
    assert triangle["patterns"]["triangles_symmetrical"]["public_chapter_builder"] == "scanner.build_symmetrical_triangle_public_chapter"


def test_symmetrical_triangle_public_chapter_uses_direction_branch_headline(tmp_path: Path) -> None:
    paths = build_symmetrical_triangle_public_chapter(out_dir=tmp_path / "triangle_family")

    assert paths["pdf"].exists()
    assert paths["pdf"].stat().st_size > 100_000

    payload = json.loads(paths["payload"].read_text(encoding="utf-8"))
    assert payload["factory_id"] == CANONICAL_PUBLICATION_FACTORY_ID
    assert payload["source_family_factory_id"] == FACTORY_ID
    assert payload["pattern_id"] == "triangles_symmetrical"
    assert payload["classification"] == "watchlist-reference branch under available-series scope"
    assert payload["chapter_reference"]["all_scanner_events"] == 3723
    assert payload["chapter_reference"]["events"] == 289
    assert payload["chapter_reference"]["scope"] == "phá vỡ lên x thanh khoản trung bình x nhóm đủ chuẩn công bố"
    assert payload["target_calibration"]["base_target"]["target_multiple"] == 0.5
    assert payload["target_calibration"]["base_target"]["target_hit_rate"] == 62.63
    assert payload["target_calibration"]["base_target"]["mfe_mae_median_ratio"] == 1.67
    assert payload["example_events"]["textbook_success"]["breakout_direction"] == "up"
    assert payload["example_events"]["middle_case"]["target_hit"] is False
    assert payload["example_events"]["failure"]["failure_5pct"] is True

    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(paths["pdf"])).pages)
    assert "Tam giác cân" in text
    assert "Kết quả quan trọng" in text
    assert "Cách nhận diện" in text
    assert "Ví dụ minh họa" in text
    assert "Mục tiêu giá" in text
    assert "Tương tác bối cảnh và thanh khoản" in text
    assert "phá vỡ lên x thanh khoản trung bình x nhóm đủ chuẩn công bố" in text
    assert "direction:up" not in text
    assert "publication_quality_tier" not in text
    assert "Flag" not in text
    assert "cột cờ" not in text
    assert "thân cờ" not in text
