from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from pypdf import PdfReader
from reportlab.pdfgen import canvas
import scanner.canonical_publication_chapter_factory as canonical_factory
from scanner.audit_canonical_publication_flow import audit_manifest
from scanner.canonical_chapter_content import (
    CANONICAL_CONTENT_GENERATOR_ID,
    load_approved_editorial_sections,
    prepare_canonical_chapter_content,
)
from scanner.canonical_editorial_layer import CANONICAL_AI_EDITORIAL_GATE_ID, validate_canonical_editorial_sections
from scanner.canonical_editorial_workflow import (
    CANONICAL_EDITORIAL_WORKFLOW_ID,
    EDITORIAL_BLOCK_SEQUENCE,
    build_canonical_editorial_dossier,
    build_canonical_editorial_prompt,
)
from scanner.canonical_publication_chapter_factory import (
    CANONICAL_PUBLICATION_FACTORY_ID,
    CANONICAL_PUBLICATION_FLOW,
    CANONICAL_PUBLICATION_STYLE_VERSION,
    CANONICAL_READER_EXPERIENCE_GATE_ID,
    canonicalize_publication_payload,
)
from scanner.audit_publication_style_v3 import audit_publication_style_v3
from scanner.audit_final_chapter_pdf_quality import audit_manifest as audit_final_pdf_quality_manifest
from scanner.audit_final_family_shared_content import audit_manifest as audit_final_family_shared_content
from scanner.audit_publication_entrypoints import audit_publication_entrypoints
from scanner.promote_final_chapter import promote_final_chapter
from scanner.audit_scanner_tradable_integrity import (
    audit_manifest as audit_scanner_tradable_integrity,
    audit_preflight_sources,
    audit_tradable_governance,
)
from scanner.publication_flow_contract import (
    CANONICAL_SOURCE_GUIDED_REFINEMENT_ID,
    SOURCE_GROUNDED_PUBLICATION_GATE_ID,
    validate_publication_contract,
    validate_source_guided_refinement_contract,
)
from scanner.publication_semantic_contract import PUBLICATION_SEMANTIC_GATE_ID, validate_publication_semantic_contract
from scanner.validate_final_chapters_manifest import validate_final_manifest


REQUIRED_SECTIONS = ["summary", "tour", "failure", "statistics", "post_breakout", "size_volume", "tactics", "checklist"]


def _write_text_pdf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path))
    pdf.drawString(72, 760, text[:180])
    pdf.save()


def _rich_editorial_sections() -> dict[str, list[str]]:
    return {
        "summary": [
            "Mẫu này được trình bày như một chương đọc biểu đồ, không phải một bảng thống kê rời rạc. Người đọc nên hiểu trước hình thái, sau đó mới đọc kết quả hậu phá vỡ để biết mẫu thường cư xử thế nào.",
            "Điều này cho thấy số liệu chỉ có ý nghĩa khi gắn với đường đi giá. Vì vậy phần chính phải nói rõ khi nào mẫu đáng chú ý hơn và khi nào cần thận trọng hơn.",
            "Nếu một con số xuất hiện trong chương, nó phải trả lời câu hỏi cách đọc thực tế là gì. Nghĩa là thống kê không đứng một mình, mà được chuyển thành hàm ý cho người đọc.",
            "Phần mở đầu cũng phải chỉ ra vai trò sử dụng của chương: mẫu có thể là tham khảo đầu tư, tham khảo phòng thủ hoặc chỉ là ghi chú mô tả. Cách đọc này giúp người đọc không nhầm một hồ sơ mẫu hình với một tín hiệu giao dịch tự động.",
        ],
        "tour": [
            "Phần tour giải thích mẫu hình hoạt động ra sao từ nhịp trước mẫu, vùng nghỉ hoặc vùng đảo chiều, tới phiên xác nhận. Người đọc cần thấy trình tự này trước khi xem bảng.",
            "Khi mẫu không có bối cảnh phù hợp, cách đọc phải thận trọng hơn dù hình dạng vẫn có vẻ đúng. Điều này giúp chương không biến mọi hình vẽ thành tín hiệu.",
            "Tour tốt phải trả lời câu hỏi mẫu đang đại diện cho lực tiếp diễn, lực đảo chiều hay trạng thái nhiễu. Vì vậy nó là phần diễn giải cốt lõi, không phải đoạn mở bài trang trí.",
        ],
        "failure": [
            "Thất bại được đặt trong phần chính vì người đọc cần biết mẫu sai như thế nào. Nếu giá không đi đủ xa hoặc bị kéo ngược mạnh trước mục tiêu, cách đọc phải khác với một mẫu đi tiếp gọn.",
            "Điều này cho thấy tỷ lệ thất bại không phải phụ lục kỹ thuật. Vì vậy chương phải có ví dụ thất bại và diễn giải vì sao nó làm giảm độ tin cậy của mẫu.",
            "Một đoạn thất bại đạt chuẩn phải nói rõ thất bại xuất hiện ở đâu trên đường giá: thiếu lực sau xác nhận, kéo ngược quá sâu, hoặc mục tiêu quá xa so với cấu trúc mẫu. Người đọc cần phần này để biết khi nào nên bỏ qua mẫu.",
        ],
        "statistics": [
            "Các thống kê chính được dùng để mô tả hành vi lịch sử, nhưng mỗi số liệu phải đi kèm cách đọc. Người đọc nên hiểu tỷ lệ đạt mục tiêu, thất bại và đường đi sau phá vỡ như một bộ ba.",
            "Điều này cho thấy kết quả trung vị không đủ để kết luận. Vì vậy chương cần nói thêm về vùng phân bố, mức kéo ngược và nhóm bối cảnh nơi mẫu đáng chú ý hơn.",
            "Nếu một bảng chỉ có số mà không có diễn giải, nó không giúp người đọc ra quyết định đọc biểu đồ. Phần thống kê đạt chuẩn phải biến từng con số chính thành câu hỏi thực dụng: mẫu có đi đủ xa, đi đủ gọn và có đủ ổn định hay không.",
        ],
        "post_breakout": [
            "Sau phá vỡ, câu hỏi không chỉ là giá có đi đúng hướng hay không. Người đọc cần biết mục tiêu có đến trước khi bị kéo ngược mạnh hay không.",
            "Nếu mẫu đi đúng hướng nhưng quá chậm hoặc quay lại kiểm định nhiều lần, cách đọc nên thận trọng hơn. Điều này biến đường đi giá thành phần diễn giải chính.",
            "Phần hậu phá vỡ cũng phải nói về tốc độ và trật tự sự kiện. Một mẫu chạm mục tiêu nhanh trước khi bị kéo ngược có ý nghĩa khác hẳn mẫu chạm mục tiêu sau một đoạn nhiễu dài.",
        ],
        "size_volume": [
            "Kích thước và khối lượng giúp phân biệt mẫu gọn với vùng dao động nhiễu. Người đọc nên hiểu mẫu quá dài hoặc quá rộng là dấu hiệu cần giảm độ tin cậy.",
            "Khi khối lượng hoặc thanh khoản không xác nhận, chương không nên kết luận quá mạnh. Điều này giữ phần diễn giải gần với cách đọc biểu đồ thực tế.",
            "Phần này đạt chuẩn khi nó chỉ rõ điều kiện nào làm mẫu đáng chú ý hơn, không chỉ liệt kê kích thước. Vì vậy mỗi biến bối cảnh phải được gắn với một hành động đọc: ưu tiên, theo dõi hoặc thận trọng.",
        ],
        "tactics": [
            "Cách sử dụng thực tế của chương là tham khảo có điều kiện. Người đọc có thể dùng nó để đặt câu hỏi về xác nhận, rủi ro đường đi và bối cảnh, không phải để nhận lệnh mua bán.",
            "Nếu mẫu xuất hiện trong nhóm thanh khoản yếu hoặc sau một nhịp đã đi quá xa, cách đọc phải thận trọng hơn. Điều này giúp tách tài liệu tham khảo khỏi tín hiệu giao dịch tự động.",
            "Phần sử dụng tốt phải nói rõ người đọc nên làm gì với thông tin: kiểm xác nhận, so đường đi với vùng rủi ro, so mục tiêu với độ biến động và loại các tình huống nhiễu. Nó không được biến thống kê thành mệnh lệnh giao dịch.",
        ],
        "checklist": [
            "Kiểm tra bối cảnh trước mẫu trước khi đọc kết quả.",
            "Chỉ đọc mẫu sau khi có xác nhận phá vỡ rõ.",
            "Luôn xem thất bại và mức kéo ngược sâu nhất.",
            "Ưu tiên mẫu có đường giá sạch và thanh khoản đủ.",
            "Không biến chương thành lời khuyên giao dịch.",
        ],
    }


def test_final_manifest_blocks_incomplete_triangle_final_contract(tmp_path) -> None:
    pdf = tmp_path / "triangle.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "chapters": [
                    {
                        "family": "triangle_family",
                        "pattern_id": "triangles_ascending",
                        "status": "final",
                        "pdf": str(pdf),
                        "publication_flow": "triangle_family_public_chapter_factory_v1 + pattern_publication_core_v1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = validate_final_manifest(manifest)

    assert report["status"] == "FAIL"
    checks = {item["check"] for item in report["failures"]}
    assert "payload_exists" in checks
    assert "manuscript_exists" in checks
    assert "source_notes_exists" in checks


def test_current_final_manifest_has_completed_canonical_pdf_factory_rebuild() -> None:
    manifest_payload = json.loads(Path("artifacts/final_chapters/final_chapters_manifest.json").read_text(encoding="utf-8"))
    chapter_count = len(manifest_payload.get("chapters", []))
    report = validate_final_manifest()

    assert report["status"] == "PASS"
    assert report["final_count"] == chapter_count
    assert report["quarantine_count"] == 5
    assert report["failures"] == []
    assert not any(item["check"] == "canonical_publication_flow" for item in report["failures"])

    canonical_audit = audit_manifest()
    assert canonical_audit["status"] == "PASS"
    assert canonical_audit["counts"] == {"chapters": chapter_count, "canonical_pass": chapter_count, "canonical_fail": 0}
    assert canonical_audit["canonical_publication_factory_id"] == CANONICAL_PUBLICATION_FACTORY_ID

    pdf_quality_audit = audit_final_pdf_quality_manifest(Path("artifacts/final_chapters/final_chapters_manifest.json"))
    assert pdf_quality_audit["status"] == "PASS"
    assert pdf_quality_audit["counts"] == {"chapters": chapter_count, "pass": chapter_count, "fail": 0, "warnings": 0}

    entrypoint_audit = audit_publication_entrypoints()
    assert entrypoint_audit["status"] == "PASS"
    assert entrypoint_audit["counts"]["failures"] == 0

    shared_content_audit = audit_final_family_shared_content(Path("artifacts/final_chapters/final_chapters_manifest.json"))
    assert shared_content_audit["status"] == "PASS"
    assert shared_content_audit["counts"]["duplicate_findings"] == 0

    scanner_tradable_audit = audit_scanner_tradable_integrity(Path("artifacts/final_chapters/final_chapters_manifest.json"))
    assert scanner_tradable_audit["status"] == "PASS"
    assert scanner_tradable_audit["counts"]["failures"] == 0

    manifest = json.loads(Path("artifacts/final_chapters/final_chapters_manifest.json").read_text(encoding="utf-8"))
    final_ids = {chapter["pattern_id"] for chapter in manifest["chapters"]}
    assert {
        "double_bottoms_eve_adam",
        "double_bottoms_eve_eve",
        "double_tops_adam_adam",
        "double_tops_adam_eve",
        "double_tops_eve_adam",
        "double_tops_eve_eve",
        "bull_pennants",
        "bear_pennants",
        "high_tight_flags",
        "rectangle_bottoms",
        "rectangle_tops",
        "head_and_shoulders_bottoms",
        "head_and_shoulders_bottoms_complex",
        "head_and_shoulders_tops",
        "head_and_shoulders_tops_complex",
        "broadening_bottoms",
        "broadening_formations_right_angled_ascending",
        "broadening_formations_right_angled_descending",
        "broadening_tops",
        "broadening_wedges_ascending",
        "broadening_wedges_descending",
        "cup_with_handle",
        "cup_with_handle_inverted",
        "measured_move_down",
        "measured_move_up",
        "pipe_bottoms",
        "pipe_tops",
            "scallops_ascending",
            "scallops_ascending_inverted",
            "scallops_descending",
            "scallops_descending_inverted",
            "island_reversals",
            "islands_long",
        }.issubset(final_ids)

    governance = json.loads(Path("artifacts/final_chapters/governance/chapter_governance_matrix.json").read_text(encoding="utf-8"))
    assert governance["governance_matrix_id"] == "dual_axis_chapter_scoring_v1"
    assert governance["counts"]["chapters"] == chapter_count
    assert governance["counts"]["publication_final"] == chapter_count
    assert governance["counts"]["preflight_available"] == chapter_count
    assert (
        governance["counts"]["tradable_final_95"]
        + governance["counts"]["tradable_research_candidate_blocked"]
        + governance["counts"]["tradable_tested_blocked"]
        + governance["counts"]["not_tested"]
        == chapter_count
    )
    by_pattern = {row["pattern_id"]: row for row in governance["chapters"]}
    assert by_pattern["bull_flags"]["tradable_status"] == "tradable_final_95"
    assert by_pattern["bull_flags"]["tradable_preflight_status"] == "preflight_candidate"
    assert by_pattern["double_bottoms_adam_adam"]["tradable_status"] == "tradable_final_95"
    assert by_pattern["double_bottoms_adam_adam"]["tradable_evidence_id"] == "local_blocker_audit"
    assert by_pattern["double_tops_adam_adam"]["tradable_status"] == "tradable_research_candidate_blocked"
    assert by_pattern["double_tops_adam_adam"]["tradable_evidence_id"] == "local_blocker_audit"
    assert by_pattern["double_tops_adam_adam"]["tradable_score"] >= 90
    assert by_pattern["bull_pennants"]["tradable_status"] == "tradable_research_candidate_blocked"
    assert by_pattern["bull_pennants"]["tradable_preflight_status"] == "preflight_strong"
    assert by_pattern["bear_pennants"]["tradable_status"] == "tradable_tested_blocked"
    assert by_pattern["bear_pennants"]["tradable_evidence_id"] == "generic_tradable_layer"
    assert by_pattern["bear_pennants"]["tradable_preflight_status"] == "preflight_weak"
    assert by_pattern["high_tight_flags"]["tradable_status"] == "tradable_tested_blocked"
    assert by_pattern["high_tight_flags"]["tradable_evidence_id"] == "branch_optimization_layer"
    assert by_pattern["high_tight_flags"]["tradable_preflight_status"] == "preflight_watchlist"
    assert by_pattern["triangles_ascending"]["tradable_status"] == "tradable_tested_blocked"
    assert by_pattern["triangles_ascending"]["tradable_preflight_status"] == "preflight_strong"
    assert by_pattern["triangles_ascending"]["tradable_evidence_id"] == "local_blocker_audit"
    assert by_pattern["wedges_rising"]["tradable_status"] == "tradable_research_candidate_blocked"
    assert by_pattern["wedges_rising"]["tradable_preflight_status"] == "preflight_candidate"
    assert by_pattern["wedges_rising"]["tradable_evidence_id"] == "local_blocker_audit"
    assert by_pattern["bear_flags"]["tradable_preflight_status"] == "preflight_strong"
    assert by_pattern["triangles_symmetrical"]["tradable_preflight_status"] == "preflight_strong"
    assert by_pattern["triangles_symmetrical"]["tradable_evidence_id"] == "branch_optimization_layer"
    assert by_pattern["rectangle_bottoms"]["tradable_status"] == "tradable_tested_blocked"
    assert by_pattern["rectangle_bottoms"]["tradable_preflight_status"] == "preflight_strong"
    assert by_pattern["rectangle_bottoms"]["tradable_evidence_id"] == "generic_tradable_layer"
    assert by_pattern["rectangle_tops"]["tradable_status"] == "tradable_tested_blocked"
    assert by_pattern["rectangle_tops"]["tradable_preflight_status"] == "preflight_strong"
    assert by_pattern["rectangle_tops"]["tradable_evidence_id"] == "generic_tradable_layer"
    assert by_pattern["head_and_shoulders_bottoms_complex"]["tradable_status"] == "tradable_tested_blocked"
    assert by_pattern["head_and_shoulders_bottoms_complex"]["tradable_evidence_id"] == "local_blocker_audit"
    assert by_pattern["head_and_shoulders_bottoms_complex"]["tradable_preflight_status"] == "preflight_candidate"
    assert by_pattern["head_and_shoulders_tops_complex"]["tradable_status"] == "tradable_tested_blocked"
    assert by_pattern["head_and_shoulders_tops_complex"]["tradable_evidence_id"] == "generic_tradable_layer"
    assert by_pattern["head_and_shoulders_tops_complex"]["tradable_score"] >= 85
    assert by_pattern["head_and_shoulders_tops_complex"]["tradable_preflight_status"] == "preflight_strong"
    assert by_pattern["broadening_bottoms"]["tradable_status"] == "tradable_research_candidate_blocked"
    assert by_pattern["broadening_bottoms"]["tradable_evidence_id"] == "branch_optimization_layer"
    assert by_pattern["broadening_bottoms"]["tradable_score"] >= 90
    assert by_pattern["broadening_bottoms"]["tradable_preflight_status"] == "preflight_strong"
    assert by_pattern["broadening_formations_right_angled_ascending"]["tradable_status"] == "tradable_tested_blocked"
    assert by_pattern["broadening_formations_right_angled_ascending"]["tradable_evidence_id"] == "local_blocker_audit"
    assert by_pattern["broadening_formations_right_angled_descending"]["tradable_status"] == "tradable_tested_blocked"
    assert by_pattern["broadening_formations_right_angled_descending"]["tradable_evidence_id"] == "local_blocker_audit"
    assert by_pattern["broadening_tops"]["tradable_status"] == "tradable_tested_blocked"
    assert by_pattern["broadening_wedges_ascending"]["tradable_status"] == "tradable_tested_blocked"
    assert by_pattern["broadening_wedges_ascending"]["tradable_evidence_id"] == "local_blocker_audit"
    assert by_pattern["broadening_wedges_descending"]["tradable_status"] == "tradable_tested_blocked"
    assert by_pattern["broadening_wedges_descending"]["tradable_evidence_id"] == "local_blocker_audit"
    assert by_pattern["broadening_wedges_descending"]["tradable_preflight_status"] == "preflight_strong"
    assert by_pattern["pipe_bottoms"]["tradable_status"] == "tradable_final_95"
    assert by_pattern["pipe_bottoms"]["tradable_release_status"] == "PASS"
    assert by_pattern["pipe_bottoms"]["tradable_score"] >= 95
    assert by_pattern["pipe_bottoms"]["tradable_blockers"] == ""

    preflight = json.loads(
        Path("artifacts/final_chapters/governance/chapter_tradable_preflight_matrix.json").read_text(encoding="utf-8")
    )
    assert preflight["preflight_matrix_id"] == "tradable_preflight_matrix_v1"
    assert preflight["counts"]["chapters"] == chapter_count
    assert preflight["counts"]["preflight_available"] == chapter_count
    assert preflight["counts"]["insufficient_or_missing"] <= 1
    preflight_by_pattern = {row["pattern_id"]: row for row in preflight["chapters"]}
    assert preflight_by_pattern["bull_pennants"]["preflight_target_multiple"] == 0.5
    assert preflight_by_pattern["bear_pennants"]["preflight_branch_id"] == "volume_confirmed"
    assert preflight_by_pattern["high_tight_flags"]["preflight_target_multiple"] == 0.5
    assert preflight_by_pattern["bear_flags"]["preflight_branch_id"] == "clean_breakdown_body"
    assert preflight_by_pattern["triangles_symmetrical"]["preflight_branch_id"] == "mature_compression"
    assert preflight_by_pattern["wedges_rising"]["preflight_branch_id"] == "bull_high_liq_width_core"


def test_validate_final_manifest_accepts_canonical_flow_shape_for_non_default_manifest(tmp_path) -> None:
    pdf = tmp_path / "chapter.pdf"
    payload = tmp_path / "payload.json"
    manuscript = tmp_path / "manuscript.md"
    notes = tmp_path / "notes.md"
    source_notes = tmp_path / "source.json"
    _write_text_pdf(pdf, "Kết quả quan trọng Mẫu hình hoạt động ra sao Cách nhận diện")
    payload.write_text(
        json.dumps(
                {
                    "status": "PASS",
                    "factory_id": CANONICAL_PUBLICATION_FACTORY_ID,
                    "publication_core_id": "pattern_publication_core_v1",
                    "canonical_publication_factory_id": CANONICAL_PUBLICATION_FACTORY_ID,
                    "canonical_reader_experience_gate_id": CANONICAL_READER_EXPERIENCE_GATE_ID,
                    "canonical_publication_style_version": CANONICAL_PUBLICATION_STYLE_VERSION,
                    "canonical_editorial_workflow_id": CANONICAL_EDITORIAL_WORKFLOW_ID,
                    "canonical_ai_editorial_gate_id": CANONICAL_AI_EDITORIAL_GATE_ID,
                    "canonical_content_generator_id": CANONICAL_CONTENT_GENERATOR_ID,
                    "editorial_sections": _rich_editorial_sections(),
                }
        ),
        encoding="utf-8",
    )
    manuscript.write_text(
        "Family factory: `canonical_publication_chapter_factory_v1`\n"
        "Publication core: `pattern_publication_core_v1`\n"
        + "\n".join(f"## {section}\nok" for section in REQUIRED_SECTIONS),
        encoding="utf-8",
    )
    notes.write_text(
        "Family factory: `canonical_publication_chapter_factory_v1`\nPublication core: `pattern_publication_core_v1`\n",
        encoding="utf-8",
    )
    source_notes.write_text(json.dumps({"status": "PASS", "source_rules": [{"rule_id": "a"}, {"rule_id": "b"}]}), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "chapters": [
                    {
                        "family": "flag_family",
                        "pattern_id": "demo",
                        "status": "final",
                        "pdf": str(pdf),
                        "payload": str(payload),
                        "manuscript": str(manuscript),
                        "notes": str(notes),
                        "source_notes": str(source_notes),
                        "factory_id": CANONICAL_PUBLICATION_FACTORY_ID,
                        "publication_core_id": "pattern_publication_core_v1",
                            "publication_flow": CANONICAL_PUBLICATION_FLOW,
                            "canonical_publication_factory_id": CANONICAL_PUBLICATION_FACTORY_ID,
                            "canonical_reader_experience_gate_id": CANONICAL_READER_EXPERIENCE_GATE_ID,
                            "canonical_publication_style_version": CANONICAL_PUBLICATION_STYLE_VERSION,
                            "canonical_editorial_workflow_id": CANONICAL_EDITORIAL_WORKFLOW_ID,
                            "canonical_ai_editorial_gate_id": CANONICAL_AI_EDITORIAL_GATE_ID,
                            "canonical_content_generator_id": CANONICAL_CONTENT_GENERATOR_ID,
                        }
                ],
                "quarantined_chapters": [],
            }
        ),
        encoding="utf-8",
    )

    report = validate_final_manifest(manifest)

    assert report["status"] == "PASS"


def test_family_shared_content_audit_rejects_exact_duplicate_recognition_rows(tmp_path) -> None:
    shared_rules = [["Mẫu phải có hình dạng rõ.", "Không dùng vùng dao động nhiễu."]]
    chapters = []
    for pattern_id in ["demo_a", "demo_b"]:
        payload = tmp_path / f"{pattern_id}_payload.json"
        spec = tmp_path / f"{pattern_id}_spec.json"
        payload.write_text(json.dumps({"source_rules_public": shared_rules}, ensure_ascii=False), encoding="utf-8")
        spec.write_text(json.dumps({"public_rule_rows": shared_rules}, ensure_ascii=False), encoding="utf-8")
        chapters.append(
            {
                "family": "demo_family",
                "pattern_id": pattern_id,
                "status": "final",
                "payload": str(payload),
                "publication_spec": str(spec),
            }
        )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"chapters": chapters}, ensure_ascii=False), encoding="utf-8")

    report = audit_final_family_shared_content(manifest)

    assert report["status"] == "FAIL"
    fields = {(failure["source"], failure["field"]) for failure in report["failures"]}
    assert ("payload", "source_rules_public") in fields
    assert ("spec", "public_rule_rows") in fields


def test_scanner_tradable_integrity_gate_rejects_shared_preflight_source_without_variant(tmp_path) -> None:
    events = tmp_path / "events.csv"
    events.write_text("event_id,variant\n1,a\n2,b\n", encoding="utf-8")
    preflight = tmp_path / "preflight.json"
    preflight.write_text(
        json.dumps(
            {
                "chapters": [
                    {"pattern_id": "demo_a", "preflight_available": True, "events_path": str(events)},
                    {"pattern_id": "demo_b", "preflight_available": True, "events_path": str(events)},
                ]
            }
        ),
        encoding="utf-8",
    )

    report = audit_preflight_sources(preflight)

    assert report["status"] == "FAIL"
    assert any(failure["check"] == "shared_preflight_source_missing_variant" for failure in report["failures"])


def test_scanner_tradable_integrity_gate_rejects_wrong_selected_strategy_pattern(tmp_path) -> None:
    selected = tmp_path / "selected.json"
    selected.write_text(json.dumps({"pattern_id": "other_pattern", "selected_strategy_id": "s1"}), encoding="utf-8")
    governance = tmp_path / "governance.json"
    governance.write_text(
        json.dumps({"chapters": [{"pattern_id": "demo_pattern", "tradable_selected_strategy": str(selected)}]}),
        encoding="utf-8",
    )

    report = audit_tradable_governance(governance)

    assert report["status"] == "FAIL"
    assert any(failure["check"] == "tradable_selected_strategy_pattern_mismatch" for failure in report["failures"])


def test_canonical_editorial_gate_rejects_thin_statistical_sections() -> None:
    report = validate_canonical_editorial_sections(
        {
            "editorial_sections": {
                section: ["Tỷ lệ đạt 70%, trung vị 12%, thất bại 20%."]
                for section in REQUIRED_SECTIONS
            }
        }
    )

    assert report["status"] == "FAIL"
    checks = {failure["check"] for failure in report["failures"]}
    assert "editorial_section_too_short" in checks
    assert "editorial_section_lacks_reader_implication" in checks


def test_canonical_editorial_gate_rejects_style_v3_internal_leaks() -> None:
    sections = _rich_editorial_sections()
    sections["summary"] = sections["summary"] + [
        "Đây là setup có stop-loss và dừng lỗ được gợi ý sau khi scanner chạy xong."
    ]

    report = validate_canonical_editorial_sections({"editorial_sections": sections})

    assert report["status"] == "FAIL"
    leaks = [failure for failure in report["failures"] if failure["check"] == "editorial_section_forbidden_terms"]
    assert leaks
    assert "stop-loss" in leaks[0]["detail"] or "dừng lỗ" in leaks[0]["detail"]


def test_canonical_editorial_gate_accepts_reader_facing_sections() -> None:
    report = validate_canonical_editorial_sections({"editorial_sections": _rich_editorial_sections()})

    assert report["status"] == "PASS"
    assert report["gate_id"] == CANONICAL_AI_EDITORIAL_GATE_ID


def test_canonical_factory_refuses_to_render_thin_editorial_payload() -> None:
    try:
        canonicalize_publication_payload(
            prepare_canonical_chapter_content(
                {"status": "PASS"},
                editorial_sections={
                    section: ["Tỷ lệ đạt 70%, trung vị 12%, thất bại 20%."]
                    for section in REQUIRED_SECTIONS
                },
                source_kind="canonical_test_sections",
            )
        )
    except ValueError as exc:
        assert "editorial gate failed" in str(exc)
    else:
        raise AssertionError("canonical factory accepted thin editorial payload")


def test_canonical_factory_refuses_raw_editorial_sections_without_content_generator() -> None:
    try:
        canonicalize_publication_payload({"status": "PASS", "editorial_sections": _rich_editorial_sections()})
    except ValueError as exc:
        assert "canonical content generator missing" in str(exc)
    else:
        raise AssertionError("canonical factory accepted raw editorial sections")


def test_canonical_factory_attaches_ai_editorial_gate_metadata() -> None:
    payload = canonicalize_publication_payload(
        prepare_canonical_chapter_content(
            {"status": "PASS"},
            editorial_sections=_rich_editorial_sections(),
            source_kind="canonical_test_sections",
        )
    )

    assert payload["canonical_editorial_workflow_id"] == CANONICAL_EDITORIAL_WORKFLOW_ID
    assert payload["canonical_ai_editorial_gate_id"] == CANONICAL_AI_EDITORIAL_GATE_ID
    assert payload["canonical_publication_style_version"] == CANONICAL_PUBLICATION_STYLE_VERSION
    assert payload["canonical_content_generator_id"] == CANONICAL_CONTENT_GENERATOR_ID
    assert payload["canonical_ai_editorial_gate_report"]["status"] == "PASS"


def test_style_v3_audit_rejects_pdf_with_internal_terms(tmp_path) -> None:
    pdf = tmp_path / "chapter.pdf"
    payload = tmp_path / "payload.json"
    _write_text_pdf(pdf, "Kết quả quan trọng Mẫu hình hoạt động ra sao scanner payload")
    payload.write_text(
        json.dumps(
            {
                "status": "PASS",
                "factory_id": CANONICAL_PUBLICATION_FACTORY_ID,
                "publication_core_id": "pattern_publication_core_v1",
                "canonical_reader_experience_gate_id": CANONICAL_READER_EXPERIENCE_GATE_ID,
                "canonical_publication_style_version": CANONICAL_PUBLICATION_STYLE_VERSION,
            }
        ),
        encoding="utf-8",
    )

    report = audit_publication_style_v3(pdf, payload)

    assert report["status"] == "FAIL"
    checks = {failure["check"] for failure in report["failures"]}
    assert "pdf_forbidden_public_terms" in checks
    assert any("scanner" in failure["detail"] or "payload" in failure["detail"] for failure in report["failures"])


def test_style_v3_audit_rejects_legacy_table_heading_leaks(tmp_path) -> None:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    pdf = tmp_path / "chapter.pdf"
    payload = tmp_path / "payload.json"
    font_path = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
    pdfmetrics.registerFont(TTFont("ArialUnicodeTest", str(font_path)))
    doc = canvas.Canvas(str(pdf))
    doc.setFont("ArialUnicodeTest", 12)
    doc.drawString(72, 760, "Cách nhận diện Tham số hiện tại Kết quả quan trọng")
    doc.save()
    payload.write_text(
        json.dumps(
            {
                "status": "PASS",
                "factory_id": CANONICAL_PUBLICATION_FACTORY_ID,
                "publication_core_id": "pattern_publication_core_v1",
                "canonical_reader_experience_gate_id": CANONICAL_READER_EXPERIENCE_GATE_ID,
                "canonical_publication_style_version": CANONICAL_PUBLICATION_STYLE_VERSION,
            }
        ),
        encoding="utf-8",
    )

    report = audit_publication_style_v3(pdf, payload)

    assert report["status"] == "FAIL"
    assert any(
        failure["check"] == "pdf_forbidden_public_terms" and "Tham số hiện tại" in failure["detail"]
        for failure in report["failures"]
    )


def test_canonical_editorial_workflow_builds_pattern_agnostic_dossier_and_prompts() -> None:
    dossier = build_canonical_editorial_dossier(
        payload={
            "pattern_id": "demo_pattern",
            "classification": "investment-reference candidate",
            "chapter_reference": {"events": 193, "target_hit_rate": 68.39},
            "target_calibration": {"base_target": {"target_hit_rate": 68.39}},
            "example_events": {"textbook_success": {"symbol": "AAA", "target_hit": True}},
        },
        source_notes={
            "source_rules": [
                {
                    "rule_id": "demo.geometry",
                    "rule_type": "shape",
                    "source_section": "Identification Guidelines",
                    "implementation_mapping": "Require a clear geometric structure before confirmation.",
                }
            ]
        },
        chapter_meta={"title": "Mẫu thử", "family": "demo_family"},
    )

    assert dossier["canonical_editorial_workflow_id"] == CANONICAL_EDITORIAL_WORKFLOW_ID
    assert dossier["workflow_blocks"] == list(EDITORIAL_BLOCK_SEQUENCE)
    assert set(dossier["section_roles"]) == set(REQUIRED_SECTIONS)
    assert dossier["chapter_identity"]["title"] == "Mẫu thử"
    assert dossier["source_rule_inventory"][0]["rule_id"] == "demo.geometry"

    prompt = build_canonical_editorial_prompt(dossier, "public_chapter_writer")
    assert "canonical_editorial_workflow_v1" in prompt
    assert "section_roles" in prompt
    assert "Không tự thêm số liệu" in prompt
    assert "mọi chapter" in prompt


def test_source_guided_refinement_contract_accepts_complete_writing_flow(tmp_path) -> None:
    artifacts = {}
    for name in (
        "source_style_dossier",
        "source_guided_ai_sections",
        "refined_ai_sections",
        "canonical_pdf",
        "style_v3_audit",
    ):
        path = tmp_path / f"{name}.json"
        if name == "canonical_pdf":
            path = tmp_path / "chapter.pdf"
            _write_text_pdf(path, "Kết quả quan trọng Mẫu hình hoạt động ra sao Cách nhận diện")
        else:
            path.write_text("{}", encoding="utf-8")
        artifacts[name] = str(path)

    report = validate_source_guided_refinement_contract(
        {
            "pattern_id": "bull_flags",
            "chapter_writing_policy_id": CANONICAL_SOURCE_GUIDED_REFINEMENT_ID,
            "chapter_writing_stages": artifacts,
            "chapter_writing_notes": "Use source style dossier; không sao chép; render through canonical factory.",
        }
    )

    assert report["status"] == "PASS"


def test_source_guided_refinement_contract_blocks_missing_refinement_stage(tmp_path) -> None:
    dossier = tmp_path / "style.md"
    dossier.write_text("style", encoding="utf-8")

    report = validate_source_guided_refinement_contract(
        {
            "pattern_id": "demo",
            "chapter_writing_policy_id": CANONICAL_SOURCE_GUIDED_REFINEMENT_ID,
            "chapter_writing_stages": {"source_style_dossier": str(dossier)},
            "chapter_writing_notes": "không sao chép; canonical factory.",
        }
    )

    assert report["status"] == "FAIL"
    checks = {failure["check"] for failure in report["failures"]}
    assert "refined_ai_sections_exists" in checks
    assert "canonical_pdf_exists" in checks


def test_canonical_content_generator_maps_approved_ai_sections(tmp_path) -> None:
    approved = tmp_path / "approved_ai_sections.json"
    approved.write_text(
        json.dumps(
            {
                "approved_sections": [
                    {"id": "intro", "paragraphs": _rich_editorial_sections()["summary"]},
                    {"id": "how_it_works", "paragraphs": _rich_editorial_sections()["tour"]},
                    {"id": "failure", "paragraphs": _rich_editorial_sections()["failure"]},
                    {"id": "statistics", "paragraphs": _rich_editorial_sections()["statistics"]},
                    {"id": "post_breakout", "paragraphs": _rich_editorial_sections()["post_breakout"]},
                    {"id": "size_volume", "paragraphs": _rich_editorial_sections()["size_volume"]},
                    {"id": "usage", "paragraphs": _rich_editorial_sections()["tactics"], "callout": {"bullets": _rich_editorial_sections()["checklist"]}},
                ],
                "example_captions": {"schematic": "Caption mẫu"},
            }
        ),
        encoding="utf-8",
    )

    loaded = load_approved_editorial_sections(approved)
    payload = prepare_canonical_chapter_content({"status": "PASS"}, approved_sections_path=approved)

    assert loaded["sections"]["summary"] == _rich_editorial_sections()["summary"]
    assert loaded["sections"]["checklist"] == _rich_editorial_sections()["checklist"]
    assert payload["canonical_content_generator_id"] == CANONICAL_CONTENT_GENERATOR_ID
    assert payload["canonical_content_source_kind"] == "approved_ai_sections"
    assert payload["editorial_source_path"] == str(approved)
    assert payload["example_captions"]["schematic"] == "Caption mẫu"
    assert payload["canonical_content_generation_report"]["editorial_gate_report"]["status"] == "PASS"


def test_canonical_factory_prefers_editorial_source_path_over_stale_payload_sections(tmp_path, monkeypatch) -> None:
    approved_sections = _rich_editorial_sections()
    stale_sections = _rich_editorial_sections()
    stale_sections["summary"] = [
        "STALE INLINE SECTION. " + paragraph
        for paragraph in stale_sections["summary"]
    ]
    approved = tmp_path / "approved_ai_sections.json"
    approved.write_text(
        json.dumps({"editorial_sections": approved_sections}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    payload = {
        "pattern_id": "factory_priority_test",
        "pattern_name": "Factory Priority Test",
        "canonical_content_generator_id": CANONICAL_CONTENT_GENERATOR_ID,
        "editorial_source_path": str(approved),
        "editorial_sections": stale_sections,
    }
    captured: dict[str, dict] = {}

    def fake_build_pattern_public_chapter(**kwargs):
        captured["payload"] = kwargs["payload"]
        return {
            "pdf": tmp_path / "chapter.pdf",
            "payload": tmp_path / "payload.json",
            "manuscript": tmp_path / "manuscript.md",
            "notes": tmp_path / "notes.md",
        }

    monkeypatch.setattr(canonical_factory, "build_pattern_public_chapter", fake_build_pattern_public_chapter)

    canonical_factory.build_canonical_publication_chapter(
        payload=payload,
        source_notes={},
        events=pd.DataFrame(),
        path_df=pd.DataFrame(),
        charts={},
        spec={},
        out_dir=tmp_path,
        pdf_filename="chapter.pdf",
        payload_filename="payload.json",
        manuscript_filename="manuscript.md",
        notes_filename="notes.md",
        family_id="test_family",
    )

    assert captured["payload"]["editorial_sections"]["summary"] == approved_sections["summary"]
    assert not captured["payload"]["editorial_sections"]["summary"][0].startswith("STALE INLINE SECTION")


def test_publication_contract_has_no_canonical_opt_out_for_final_chapters(tmp_path) -> None:
    pdf = tmp_path / "chapter.pdf"
    payload = tmp_path / "payload.json"
    manuscript = tmp_path / "manuscript.md"
    notes = tmp_path / "notes.md"
    source_notes = tmp_path / "source.json"
    _write_text_pdf(pdf, "Legacy chapter")
    payload.write_text(
        json.dumps(
            {
                "status": "PASS",
                "factory_id": "legacy_family_factory_v1",
                "publication_core_id": "pattern_publication_core_v1",
                "editorial_sections": {section: ["ok"] for section in REQUIRED_SECTIONS},
            }
        ),
        encoding="utf-8",
    )
    manuscript.write_text(
        "Family factory: `legacy_family_factory_v1`\n"
        "Publication core: `pattern_publication_core_v1`\n"
        + "\n".join(f"## {section}\nok" for section in REQUIRED_SECTIONS),
        encoding="utf-8",
    )
    notes.write_text("Family factory: `legacy_family_factory_v1`\nPublication core: `pattern_publication_core_v1`\n", encoding="utf-8")
    source_notes.write_text(json.dumps({"status": "PASS", "source_rules": [{"rule_id": "a"}, {"rule_id": "b"}]}), encoding="utf-8")

    report = validate_publication_contract(
        {
            "pattern_id": "legacy_demo",
            "status": "final",
            "canonical_publication_required": False,
            "factory_id": "legacy_family_factory_v1",
            "publication_core_id": "pattern_publication_core_v1",
            "publication_flow": "legacy_family_factory_v1 + pattern_publication_core_v1",
            "pdf": str(pdf),
            "payload": str(payload),
            "manuscript": str(manuscript),
            "notes": str(notes),
            "source_notes": str(source_notes),
        }
    )

    checks = {failure["check"] for failure in report["failures"]}
    assert report["status"] == "FAIL"
    assert "canonical_manifest_factory_id" in checks
    assert "canonical_publication_flow" in checks


def test_promote_final_chapter_rolls_back_legacy_self_generated_pdf(tmp_path) -> None:
    source_pdf = tmp_path / "source.pdf"
    final_pdf = tmp_path / "final" / "legacy.pdf"
    payload = tmp_path / "payload.json"
    manuscript = tmp_path / "manuscript.md"
    notes = tmp_path / "notes.md"
    source_notes = tmp_path / "source.json"
    entry_path = tmp_path / "entry.json"
    manifest = tmp_path / "manifest.json"
    _write_text_pdf(source_pdf, "Legacy self-generated chapter")
    payload.write_text(
        json.dumps(
            {
                "status": "PASS",
                "factory_id": "legacy_family_factory_v1",
                "publication_core_id": "pattern_publication_core_v1",
                "editorial_sections": {section: ["ok"] for section in REQUIRED_SECTIONS},
            }
        ),
        encoding="utf-8",
    )
    manuscript.write_text(
        "Family factory: `legacy_family_factory_v1`\n"
        "Publication core: `pattern_publication_core_v1`\n"
        + "\n".join(f"## {section}\nok" for section in REQUIRED_SECTIONS),
        encoding="utf-8",
    )
    notes.write_text("Family factory: `legacy_family_factory_v1`\nPublication core: `pattern_publication_core_v1`\n", encoding="utf-8")
    source_notes.write_text(json.dumps({"status": "PASS", "source_rules": [{"rule_id": "a"}, {"rule_id": "b"}]}), encoding="utf-8")
    manifest.write_text(json.dumps({"chapters": [], "quarantined_chapters": []}), encoding="utf-8")
    entry_path.write_text(
        json.dumps(
            {
                "family": "legacy_family",
                "pattern_id": "legacy_demo",
                "status": "final",
                "source_pdf": str(source_pdf),
                "pdf": str(final_pdf),
                "payload": str(payload),
                "manuscript": str(manuscript),
                "notes": str(notes),
                "source_notes": str(source_notes),
                "factory_id": "legacy_family_factory_v1",
                "publication_core_id": "pattern_publication_core_v1",
                "publication_flow": "legacy_family_factory_v1 + pattern_publication_core_v1",
            }
        ),
        encoding="utf-8",
    )

    report = promote_final_chapter(entry_path=entry_path, manifest_path=manifest)

    assert report["status"] == "FAIL"
    assert not final_pdf.exists()
    assert json.loads(manifest.read_text(encoding="utf-8"))["chapters"] == []
    assert any(failure["check"] == "canonical_publication_flow" for failure in report["failures"])


def test_final_manifest_keeps_legacy_double_aggregates_quarantined() -> None:
    manifest = json.loads(Path("artifacts/final_chapters/final_chapters_manifest.json").read_text(encoding="utf-8"))
    final_ids = {chapter["pattern_id"] for chapter in manifest["chapters"]}
    quarantined = {
        chapter["pattern_id"]: chapter
        for chapter in manifest.get("quarantined_chapters", [])
        if str(chapter.get("pattern_id", "")).startswith("double_")
    }

    assert "double_bottoms" not in final_ids
    assert "double_tops" not in final_ids
    assert {"double_bottoms", "double_tops"}.issubset(quarantined)
    for chapter in quarantined.values():
        assert "aggregate" in chapter["reason"].lower()
        assert Path(chapter["previous_pdf"]).exists()


def test_final_public_pdfs_do_not_leak_internal_publication_terms() -> None:
    manifest = json.loads(Path("artifacts/final_chapters/final_chapters_manifest.json").read_text(encoding="utf-8"))
    forbidden = [
        "Contract nhân rộng family",
        "Release gate trước khi chốt",
        "Scope headline",
        "publication_quality_tier",
        "interaction:bull:high",
        "branch_id",
        "payload",
        "factory",
        "data_limited",
        "low-liquidity",
        "aggregate",
        "headline",
    ]
    for chapter in manifest["chapters"]:
        text = "\n".join(page.extract_text() or "" for page in PdfReader(chapter["pdf"]).pages)
        leaked = [term for term in forbidden if term in text]
        assert not leaked, f"{chapter['pattern_id']} leaked internal terms: {leaked}"


def test_final_manifest_blocks_orphan_pdf_in_final_folder(tmp_path) -> None:
    orphan = tmp_path / "orphan.pdf"
    orphan.write_bytes(b"%PDF-1.4\n")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"chapters": [], "quarantined_chapters": []}), encoding="utf-8")

    report = validate_final_manifest(manifest)

    assert report["status"] == "FAIL"
    assert any(item["check"] == "orphan_final_pdf" for item in report["failures"])


def test_publication_contract_requires_editorial_and_source_grounding(tmp_path) -> None:
    pdf = tmp_path / "chapter.pdf"
    payload = tmp_path / "payload.json"
    manuscript = tmp_path / "manuscript.md"
    notes = tmp_path / "notes.md"
    source_notes = tmp_path / "source.json"
    pdf.write_bytes(b"%PDF-1.4\n")
    payload.write_text(
        json.dumps(
            {
                "status": "PASS",
                "factory_id": "triangle_family_public_chapter_factory_v1",
                "publication_core_id": "pattern_publication_core_v1",
                "editorial_sections": {"summary": ["inline text only"]},
            }
        ),
        encoding="utf-8",
    )
    manuscript.write_text("Family factory: `triangle_family_public_chapter_factory_v1`\nPublication core: `pattern_publication_core_v1`\n## summary\ninline\n", encoding="utf-8")
    notes.write_text("Family factory: `triangle_family_public_chapter_factory_v1`\nPublication core: `pattern_publication_core_v1`\n", encoding="utf-8")
    source_notes.write_text(json.dumps({"status": "MISSING", "source_rules": []}), encoding="utf-8")

    report = validate_publication_contract(
        {
            "pattern_id": "triangles_ascending",
            "factory_id": "triangle_family_public_chapter_factory_v1",
            "publication_core_id": "pattern_publication_core_v1",
            "publication_flow": "triangle_family_public_chapter_factory_v1 + pattern_publication_core_v1",
            "pdf": str(pdf),
            "payload": str(payload),
            "manuscript": str(manuscript),
            "notes": str(notes),
            "source_notes": str(source_notes),
        }
    )

    assert report["status"] == "FAIL"
    checks = {failure["check"] for failure in report["failures"]}
    assert "editorial_sections" in checks
    assert "source_notes_status" in checks
    assert "source_rules" in checks
    assert "manuscript_sections" in checks


def test_cup_handle_publication_contract_rejects_code_generated_editorial_source(tmp_path) -> None:
    pdf = tmp_path / "chapter.pdf"
    payload = tmp_path / "payload.json"
    manuscript = tmp_path / "manuscript.md"
    notes = tmp_path / "notes.md"
    source_notes = tmp_path / "source.json"
    code_source = tmp_path / "build_cup_handle_family_public_chapters.py"
    _write_text_pdf(pdf, "Cup")
    code_source.write_text("# legacy inline editorial source\n", encoding="utf-8")
    sections = {key: ["ok"] for key in REQUIRED_SECTIONS}
    payload.write_text(
        json.dumps(
            {
                "status": "PASS",
                "factory_id": "cup_handle_family_public_chapter_factory_v1",
                "publication_core_id": "pattern_publication_core_v1",
                "editorial_sections": sections,
                "editorial_source_path": str(code_source),
            }
        ),
        encoding="utf-8",
    )
    manuscript.write_text(
        "Family factory: `cup_handle_family_public_chapter_factory_v1`\n"
        "Publication core: `pattern_publication_core_v1`\n"
        + "\n".join(f"## {section}\nok" for section in sections),
        encoding="utf-8",
    )
    notes.write_text(
        "Family factory: `cup_handle_family_public_chapter_factory_v1`\n"
        "Publication core: `pattern_publication_core_v1`\n",
        encoding="utf-8",
    )
    source_notes.write_text(
        json.dumps(
            {
                "status": "PASS",
                "source_grounding_policy_id": SOURCE_GROUNDED_PUBLICATION_GATE_ID,
                "source_grounding_level": "publication_aligned",
                "source_rules": [{"rule_id": str(i)} for i in range(6)],
                "direct_pdf_review": {
                    "status": "PASS",
                    "pdf_path": "references/source.pdf",
                    "pdf_pages_checked": [1],
                    "book_pages_checked": [1],
                },
            }
        ),
        encoding="utf-8",
    )

    report = validate_publication_contract(
        {
            "pattern_id": "cup_with_handle",
            "family": "cup_handle_family",
            "factory_id": "cup_handle_family_public_chapter_factory_v1",
            "publication_core_id": "pattern_publication_core_v1",
            "publication_flow": "cup_handle_family_public_chapter_factory_v1 + pattern_publication_core_v1",
            "pdf": str(pdf),
            "payload": str(payload),
            "manuscript": str(manuscript),
            "notes": str(notes),
            "source_notes": str(source_notes),
            "source_grounding_required": True,
            "direct_source_review_required": True,
        }
    )

    checks = {failure["check"] for failure in report["failures"]}
    assert "cup_handle_editorial_source_artifact" in checks


def test_entrypoint_guard_blocks_self_approved_publication_fallbacks(tmp_path) -> None:
    scanner_dir = tmp_path / "scanner"
    scanner_dir.mkdir()
    bad_builder = scanner_dir / "build_bad_family_public_chapters.py"
    bad_builder.write_text(
        "def build(payload):\n"
        "    payload[\"editorial_sections\"] = {\"summary\": [\"inline\"]}\n"
        "    prepare(source_kind=\"approved_human_sections\")\n",
        encoding="utf-8",
    )

    report = audit_publication_entrypoints(tmp_path)

    assert report["status"] == "FAIL"
    checks = {failure["check"] for failure in report["failures"]}
    assert "active_builder_fabricates_inline_public_prose" in checks
    assert "active_code_contains_publication_fallback_fragment" in checks


def test_source_grounded_gate_requires_deeper_source_contract(tmp_path) -> None:
    pdf = tmp_path / "chapter.pdf"
    payload = tmp_path / "payload.json"
    manuscript = tmp_path / "manuscript.md"
    notes = tmp_path / "notes.md"
    source_notes = tmp_path / "source.json"
    pdf.write_bytes(b"%PDF-1.4\n")
    sections = {
        key: ["ok"]
        for key in ["summary", "tour", "failure", "statistics", "post_breakout", "size_volume", "tactics", "checklist"]
    }
    payload.write_text(
        json.dumps(
            {
                "status": "PASS",
                "factory_id": "double_pattern_family_public_chapter_factory_v1",
                "publication_core_id": "pattern_publication_core_v1",
                "editorial_sections": sections,
            }
        ),
        encoding="utf-8",
    )
    manuscript.write_text(
        "Family factory: `double_pattern_family_public_chapter_factory_v1`\n"
        "Publication core: `pattern_publication_core_v1`\n"
        + "\n".join(f"## {section}\nok" for section in sections),
        encoding="utf-8",
    )
    notes.write_text(
        "Family factory: `double_pattern_family_public_chapter_factory_v1`\n"
        "Publication core: `pattern_publication_core_v1`\n",
        encoding="utf-8",
    )
    source_notes.write_text(
        json.dumps(
            {
                "status": "PASS",
                "source_grounding_policy_id": SOURCE_GROUNDED_PUBLICATION_GATE_ID,
                "source_rules": [{"rule_id": "a"}, {"rule_id": "b"}],
            }
        ),
        encoding="utf-8",
    )

    report = validate_publication_contract(
        {
            "pattern_id": "double_bottoms_adam_eve",
            "factory_id": "double_pattern_family_public_chapter_factory_v1",
            "publication_core_id": "pattern_publication_core_v1",
            "publication_flow": "double_pattern_family_public_chapter_factory_v1 + pattern_publication_core_v1",
            "source_grounding_policy_id": SOURCE_GROUNDED_PUBLICATION_GATE_ID,
            "pdf": str(pdf),
            "payload": str(payload),
            "manuscript": str(manuscript),
            "notes": str(notes),
            "source_notes": str(source_notes),
        }
    )

    assert report["status"] == "FAIL"
    checks = {failure["check"] for failure in report["failures"]}
    assert "source_grounded_source_rules" in checks


def test_direct_source_review_gate_requires_pdf_review_metadata(tmp_path) -> None:
    pdf = tmp_path / "chapter.pdf"
    payload = tmp_path / "payload.json"
    manuscript = tmp_path / "manuscript.md"
    notes = tmp_path / "notes.md"
    source_notes = tmp_path / "source.json"
    pdf.write_bytes(b"%PDF-1.4\n")
    sections = {key: ["ok"] for key in REQUIRED_SECTIONS}
    payload.write_text(
        json.dumps(
            {
                "status": "PASS",
                "factory_id": "wedge_family_public_chapter_factory_v1",
                "publication_core_id": "pattern_publication_core_v1",
                "editorial_sections": sections,
            }
        ),
        encoding="utf-8",
    )
    manuscript.write_text(
        "Family factory: `wedge_family_public_chapter_factory_v1`\n"
        "Publication core: `pattern_publication_core_v1`\n"
        + "\n".join(f"## {section}\nok" for section in REQUIRED_SECTIONS),
        encoding="utf-8",
    )
    notes.write_text(
        "Family factory: `wedge_family_public_chapter_factory_v1`\n"
        "Publication core: `pattern_publication_core_v1`\n",
        encoding="utf-8",
    )
    source_notes.write_text(
        json.dumps(
            {
                "status": "PASS",
                "source_grounding_policy_id": SOURCE_GROUNDED_PUBLICATION_GATE_ID,
                "source_grounding_level": "publication_aligned",
                "source_rules": [{"rule_id": f"r{i}"} for i in range(6)],
            }
        ),
        encoding="utf-8",
    )

    report = validate_publication_contract(
        {
            "pattern_id": "wedges_falling",
            "factory_id": "wedge_family_public_chapter_factory_v1",
            "publication_core_id": "pattern_publication_core_v1",
            "publication_flow": "wedge_family_public_chapter_factory_v1 + pattern_publication_core_v1",
            "source_grounding_policy_id": SOURCE_GROUNDED_PUBLICATION_GATE_ID,
            "source_grounding_required": True,
            "direct_source_review_required": True,
            "pdf": str(pdf),
            "payload": str(payload),
            "manuscript": str(manuscript),
            "notes": str(notes),
            "source_notes": str(source_notes),
        }
    )

    assert report["status"] == "FAIL"
    checks = {failure["check"] for failure in report["failures"]}
    assert "direct_source_review_status" in checks
    assert "direct_source_review_pdf_path" in checks
    assert "direct_source_review_pdf_pages" in checks
    assert "direct_source_review_book_pages" in checks


def test_final_manifest_blocks_source_grounded_chapter_without_semantic_spec(tmp_path) -> None:
    pdf = tmp_path / "chapter.pdf"
    payload = tmp_path / "payload.json"
    manuscript = tmp_path / "manuscript.md"
    notes = tmp_path / "notes.md"
    source_notes = tmp_path / "source.json"
    manifest = tmp_path / "manifest.json"
    _write_text_pdf(pdf, "Hai đáy Adam & Eve public chapter")
    sections = {key: ["ok"] for key in REQUIRED_SECTIONS}
    payload.write_text(
        json.dumps(
            {
                "status": "PASS",
                "factory_id": "double_pattern_family_public_chapter_factory_v1",
                "publication_core_id": "pattern_publication_core_v1",
                "editorial_sections": sections,
            }
        ),
        encoding="utf-8",
    )
    manuscript.write_text(
        "Family factory: `double_pattern_family_public_chapter_factory_v1`\n"
        "Publication core: `pattern_publication_core_v1`\n"
        + "\n".join(f"## {section}\nok" for section in REQUIRED_SECTIONS),
        encoding="utf-8",
    )
    notes.write_text(
        "Family factory: `double_pattern_family_public_chapter_factory_v1`\n"
        "Publication core: `pattern_publication_core_v1`\n",
        encoding="utf-8",
    )
    source_notes.write_text(
        json.dumps(
            {
                "status": "PASS",
                "source_grounding_policy_id": SOURCE_GROUNDED_PUBLICATION_GATE_ID,
                "source_grounding_level": "publication_aligned",
                "source_rules": [{"rule_id": f"r{i}"} for i in range(6)],
            }
        ),
        encoding="utf-8",
    )
    manifest.write_text(
        json.dumps(
            {
                "chapters": [
                    {
                        "family": "double_pattern_family",
                        "pattern_id": "double_bottoms_adam_eve",
                        "status": "final",
                        "pdf": str(pdf),
                        "payload": str(payload),
                        "manuscript": str(manuscript),
                        "notes": str(notes),
                        "source_notes": str(source_notes),
                        "factory_id": "double_pattern_family_public_chapter_factory_v1",
                        "publication_core_id": "pattern_publication_core_v1",
                        "publication_flow": "double_pattern_family_public_chapter_factory_v1 + pattern_publication_core_v1",
                        "source_grounding_required": True,
                    }
                ],
                "quarantined_chapters": [],
            }
        ),
        encoding="utf-8",
    )

    report = validate_final_manifest(manifest)

    assert report["status"] == "FAIL"
    checks = {failure["check"] for failure in report["failures"]}
    assert "semantic_publication_spec_exists" in checks


def test_semantic_gate_blocks_raw_source_text_in_public_pdf(tmp_path) -> None:
    pdf = tmp_path / "chapter.pdf"
    spec = tmp_path / "spec.json"
    source_notes = tmp_path / "source.json"
    raw = "Price trends downward leading to the double bottom and should not drift below the left bottom."
    _write_text_pdf(pdf, raw)
    spec.write_text(
        json.dumps(
            {
                "status": "PASS",
                "semantic_gate_id": PUBLICATION_SEMANTIC_GATE_ID,
                "publication_spec_id": "double_bottoms_adam_eve_publication_spec_v1",
                "pattern_id": "double_bottoms_adam_eve",
                "spec_scope": "pattern_variant",
                "variant_specific": True,
            }
        ),
        encoding="utf-8",
    )
    source_notes.write_text(
        json.dumps(
            {
                "status": "PASS",
                "source_rules": [
                    {
                        "rule_id": "db.prior_trend.downward",
                        "short_excerpt": raw,
                        "implementation_mapping": "Require a downward trend into the first bottom before accepting a Double Bottom candidate.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = validate_publication_semantic_contract(
        {
            "pattern_id": "double_bottoms_adam_eve",
            "pdf": str(pdf),
            "publication_spec": str(spec),
            "source_notes": str(source_notes),
        }
    )

    assert report["status"] == "FAIL"
    checks = {failure["check"] for failure in report["failures"]}
    assert "semantic_raw_source_text" in checks
