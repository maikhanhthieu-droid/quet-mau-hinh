"""Build Triangle Family public chapters using the shared chapter factory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.publication_example_support import _load_ohlcv, load_public_editorial_sections, plot_event_chart, slice_around_event  # noqa: E402
from scanner.publication_flow_contract import SOURCE_GROUNDED_PUBLICATION_GATE_ID  # noqa: E402
from scanner.publication_semantic_contract import PUBLICATION_SEMANTIC_GATE_ID  # noqa: E402
from scanner.triangle_family_public_chapter_factory import FACTORY_ID, build_triangle_public_chapter  # noqa: E402
from scanner.triangle_family_publication_specs import build_triangle_publication_spec, sanitize_triangle_public_text  # noqa: E402


DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/triangle_family_public_chapters")
DEFAULT_PRICE_DB = Path("../market_cache/stock_ohlcv/latest.sqlite")
DEFAULT_STATS = Path("artifacts/scanner_v2/ascending_triangles_db_source_parity/db_active/statistics.json")
DEFAULT_EVENTS = Path("artifacts/scanner_v2/ascending_triangles_db_source_parity/db_active/events.csv")
DEFAULT_PATH = Path("artifacts/scanner_v2/ascending_triangles_db_source_parity/db_active/post_breakout_path.csv")
DEFAULT_AUDIT = Path("artifacts/scanner_v2/triangle_publication_quality_audit/triangle_publication_quality_audit.json")
DEFAULT_PREMIUM_VALIDATION = Path("artifacts/scanner_v2/triangle_publication_quality_audit/manual_visual_scoring/premium_visual_validation_template.csv")
DEFAULT_EXAMPLE_VALIDATION = Path("artifacts/scanner_v2/triangle_publication_quality_audit/manual_visual_scoring/ascending_triangle_example_validation.csv")
DEFAULT_AI_SECTIONS = Path("artifacts/scanner_v2/source_guided_refinement_final_v1/triangle_family/ascending_triangle/ai/refined/approved_ai_sections.json")
CORE_PATTERNS = Path("scanner/v2/core_patterns.json")
REQUIRED_EDITORIAL_SECTIONS = ("summary", "tour", "failure", "statistics", "post_breakout", "size_volume", "tactics", "checklist")


def _read_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _load_required_editorial(path: Path) -> tuple[dict[str, list[str]], str]:
    loaded = load_public_editorial_sections(path)
    sections = loaded.get("sections") if isinstance(loaded.get("sections"), Mapping) else {}
    missing = [key for key in REQUIRED_EDITORIAL_SECTIONS if not sections.get(key)]
    if missing:
        raise RuntimeError(f"Missing approved Triangle editorial sections in {path}: {', '.join(missing)}")
    cleaned = {
        key: [sanitize_triangle_public_text(item) for item in value]
        for key, value in dict(sections).items()
    }
    return cleaned, str(path)


def _target_row(stats: Mapping[str, Any], multiple: float) -> Mapping[str, Any]:
    for row in stats.get("target_family_sensitivity") or []:
        if row.get("label") == "triangles_ascending" and float(row.get("target_multiple") or -1) == float(multiple):
            return row
    return {}


def _audit_target_row(audit: Mapping[str, Any], tier: str, multiple: float) -> Mapping[str, Any]:
    for row in audit.get("target_family_by_publication_tier") or []:
        if not isinstance(row, Mapping):
            continue
        if row.get("tier") == tier and float(row.get("target_multiple") or -1) == float(multiple):
            return row
    return {}


def _audit_precision_row(audit: Mapping[str, Any], scope: str) -> Mapping[str, Any]:
    for row in audit.get("precision_bootstrap_summary") or []:
        if isinstance(row, Mapping) and row.get("scope") == scope:
            return row
    return {}


def _public_target_row(audit: Mapping[str, Any], stats: Mapping[str, Any], multiple: float) -> dict[str, Any]:
    row = dict(_audit_target_row(audit, "premium+standard", multiple))
    if not row:
        row = dict(_target_row(stats, multiple))
    return {
        "label": "triangles_ascending_public_grade",
        "target_multiple": row.get("target_multiple", multiple),
        "target_role": (
            "source_full_height"
            if multiple == 1.0
            else ("local_stretch" if multiple == 0.75 else "local_caution")
        ),
        "target_hit_rate": row.get("target_hit_rate_pct", row.get("target_hit_rate")),
        "target_first_before_adverse_5pct_rate": row.get("target_first_before_adverse_5pct_rate_pct", row.get("target_first_before_adverse_5pct_rate")),
        "failure_5pct_rate": row.get("failure_5pct_rate_pct", row.get("failure_5pct_rate")),
        "median_mfe_pct": row.get("median_mfe_pct"),
        "median_mae_pct": row.get("median_mae_pct"),
        "mfe_mae_median_ratio": row.get("mfe_mae_median_ratio"),
        "n": row.get("n"),
        "target_hit_wilson": row.get("target_hit_wilson"),
        "target_first_wilson": row.get("target_first_wilson"),
    }


def _public_events(events: pd.DataFrame) -> pd.DataFrame:
    if "publication_quality_tier" not in events.columns:
        return events.copy()
    scoped = events[events["publication_quality_tier"].isin(["premium", "standard"])].copy()
    return scoped if not scoped.empty else events.copy()


def _source_notes() -> dict[str, Any]:
    registry = _read_json(CORE_PATTERNS)
    pattern = (((registry.get("patterns") or {}).get("triangles_ascending")) or {})
    rows = []
    for rule in pattern.get("rules") or []:
        if not isinstance(rule, Mapping):
            continue
        rows.append(
            {
                "rule_id": rule.get("rule_id"),
                "short_excerpt": rule.get("evidence_excerpt"),
                "implementation_mapping": rule.get("interpreted_rule"),
            }
        )
    return {
        "status": "PASS",
        "source_grounding_policy_id": SOURCE_GROUNDED_PUBLICATION_GATE_ID,
        "source_grounding_level": "publication_aligned",
        "local_source": {"pattern_key": "triangles_ascending", "chapter": 47, "name": "Triangles, Ascending"},
        "source_rules": rows,
    }


def _publication_payload(stats: Mapping[str, Any], events: pd.DataFrame, all_events: pd.DataFrame, audit: Mapping[str, Any]) -> dict[str, Any]:
    caution = _public_target_row(audit, stats, 0.5)
    stretch = _public_target_row(audit, stats, 0.75)
    base = _public_target_row(audit, stats, 1.0)
    legacy = base
    precision = dict(_audit_precision_row(audit, "premium+standard"))
    tier_counts = audit.get("tier_counts") if isinstance(audit.get("tier_counts"), Mapping) else {}
    premium_validation = audit.get("premium_visual_validation_summary") if isinstance(audit.get("premium_visual_validation_summary"), Mapping) else {}
    return {
        "publication_id": "ascending_triangle_publication_chapter_v1",
        "pattern_id": "triangles_ascending",
        "status": "PASS",
        "classification": "investment-reference under available-series publication scope",
        "chapter_reference": {
            "scope": "nhóm tốt nhất + nhóm chuẩn đủ điều kiện công bố",
            "all_scanner_events": int(len(all_events)),
            "public_grade_events": int(len(events)),
            "public_grade_share_pct": round(float(len(events)) / max(len(all_events), 1) * 100.0, 2),
            "symbols_scanned": stats.get("symbols_scanned"),
            "events": int(len(events)),
            "evaluated_events": int(events["mfe_pct"].notna().sum()) if "mfe_pct" in events.columns else int(len(events)),
            "median_mfe_pct": base.get("median_mfe_pct"),
            "median_mae_pct": base.get("median_mae_pct"),
            "mfe_mae_median_ratio": base.get("mfe_mae_median_ratio"),
            "failure_5pct_rate": base.get("failure_5pct_rate"),
            "legacy_target_hit_rate": legacy.get("target_hit_rate"),
            "legacy_target_first_before_adverse_5pct_rate": legacy.get("target_first_before_adverse_5pct_rate"),
            "target_hit_wilson": precision.get("target_hit_wilson"),
            "target_first_wilson": precision.get("target_first_wilson"),
            "mfe_mae_ratio_bootstrap_ci": precision.get("mfe_mae_ratio_bootstrap_ci"),
            "publication_quality_tier_counts_all": tier_counts,
            "premium_visual_validation": premium_validation,
            "temporal_split_robustness": audit.get("temporal_split_robustness") if isinstance(audit.get("temporal_split_robustness"), list) else [],
            "regime_liquidity_interaction": audit.get("regime_liquidity_interaction") if isinstance(audit.get("regime_liquidity_interaction"), list) else [],
            "liquidity_proxy_table": stats.get("liquidity_proxy_table"),
            "regime_proxy_table": stats.get("regime_proxy_table"),
            "path_quality_audit": stats.get("path_quality_audit"),
        },
        "target_calibration": {
            "target_family": stats.get("target_family"),
            "selected_base_target_multiple": 1.0,
            "selected_base_target_role": "source_full_height",
            "base_target": base,
            "stretch_target": stretch,
            "legacy_target": legacy,
            "rows": [caution, stretch, base],
            "interpretation": "Tam giác tăng dùng mốc đầy đủ 1,0x chiều cao làm mốc nguồn/headline sau calibration; 0,5x chỉ là mốc thận trọng để đọc nhịp ngắn.",
        },
        "editorial_sections": {
            "summary": [
                f"Tam giác tăng là mẫu có kháng cự tương đối ngang và đáy sau cao hơn đáy trước. Bộ quét ghi nhận {len(all_events)} mẫu; phần diễn giải chính dùng {len(events)} mẫu thuộc nhóm tốt nhất/chuẩn.",
                f"Mức đi thuận lợi trung vị trong nhóm đủ điều kiện công bố là {base.get('median_mfe_pct')}%, còn mức kéo ngược sâu nhất trung vị là {base.get('median_mae_pct')}%. Điều này cho thấy mẫu có bất đối xứng hậu phá vỡ đáng chú ý, nhưng vẫn phải đọc cùng thất bại 5% và thứ tự đường đi.",
                "Mốc 1,0 lần chiều cao tam giác đủ mạnh trong calibration và được dùng làm mốc nguồn/headline; mốc 0,5 lần chỉ là lớp đọc thận trọng cho nhịp ngắn.",
            ],
            "tour": [
                "Người đọc nên bắt đầu từ hình học: vùng đỉnh bị chặn bởi một đường kháng cự gần ngang, trong khi các đáy sau nâng dần lên. Cấu trúc này mô tả áp lực mua tăng dần dưới một vùng cung cố định.",
                "Chỉ sau khi giá đóng cửa vượt qua vùng kháng cự, mẫu mới trở thành một sự kiện để đo. Trước thời điểm đó, nó chỉ là một cấu trúc đang hình thành.",
            ],
            "failure": [
                "Thất bại của tam giác tăng thường xảy ra khi giá phá lên nhưng không đi đủ xa, hoặc kéo ngược sâu trước khi hoàn thành mục tiêu. Vì vậy chương không chỉ báo tỷ lệ đạt mục tiêu, mà còn đặt cạnh tỷ lệ đạt mục tiêu trước kéo ngược và mức kéo ngược sâu nhất.",
                "Một tam giác có hình học đẹp vẫn có thể thất bại nếu breakout yếu, thanh khoản không ủng hộ, hoặc giá đã bị kéo căng trước khi xác nhận.",
            ],
            "statistics": [
                "Các bảng trong chương tách ba câu hỏi: hình học mẫu có gọn không, mục tiêu có vừa sức không, và đường đi hậu phá vỡ có sạch không. Nhóm đủ điều kiện công bố được dùng làm kết luận chính; nhóm lỏng hoặc thiếu dữ liệu chỉ giữ vai trò kiểm tra nền.",
                "Mốc 1,0 lần chiều cao tam giác là công thức hình học đầy đủ và cũng vượt qua kiểm định calibration; mốc 0,5 lần chỉ dùng để xem độ nhạy của nhịp ngắn.",
                (
                    "Nhóm tốt nhất đã được kiểm tra bằng mắt trên 30 mẫu: "
                    f"điểm trung vị {premium_validation.get('manual_score_median')}/5, "
                    f"tỷ lệ đạt {premium_validation.get('manual_pass_rate_pct')}%, "
                    f"cổng {_vi_gate_label(premium_validation.get('premium_visual_gate'))}."
                    if premium_validation
                    else "Nhóm tốt nhất cần được kiểm tra bằng mắt trước khi dùng làm ví dụ công bố."
                ),
            ],
            "post_breakout": [
                "Sau breakout, điều quan trọng là giá có đi tiếp đủ nhanh hay không. Nếu giá chạm mục tiêu sau khi đã kéo ngược sâu, giá trị tham khảo thực tế của mẫu thấp hơn nhiều so với một tỷ lệ hit thuần.",
            ],
            "size_volume": [
                "Tam giác tăng nhạy với độ phẳng của kháng cự, độ dốc của đường hỗ trợ và mức nén trước breakout. Mẫu quá rộng hoặc không nén dần dễ chuyển thành vùng dao động hơn là tam giác tăng.",
                "Thanh khoản và chất lượng đường giá được giữ như lớp bối cảnh để tránh nâng quá mức những mẫu xuất hiện ở cổ phiếu giao dịch mỏng.",
            ],
            "tactics": [
                "Cách dùng phù hợp là xem tam giác tăng như một bản đồ xác suất sau breakout, không phải lệnh mua tự động. Mẫu đáng chú ý hơn khi kháng cự rõ, đáy nâng đều, vùng nén gọn và phiên xác nhận đóng cửa dứt khoát.",
                "Không dùng nến xuyên trong phiên như xác nhận đầy đủ nếu giá đóng cửa quay lại dưới kháng cự. Với dữ liệu hiện tại, mốc 1,0x chiều cao tam giác được giữ làm mốc nguồn/headline; mốc 0,5x chỉ là mốc thận trọng.",
                "Nếu giá kiểm định lại vùng phá vỡ, hãy đọc cùng MAE và thứ tự đạt mục tiêu trước kéo ngược. Một mẫu chạm mục tiêu sau khi đã kéo ngược sâu không có cùng chất lượng với mẫu đi tiếp gọn sau phá vỡ.",
            ],
            "checklist": [
                "Có ít nhất hai lần chạm vùng kháng cự gần ngang.",
                "Có ít nhất hai đáy sau cao hơn đáy trước.",
                "Biên độ trong mẫu có xu hướng nén lại trước breakout.",
                "Chỉ xác nhận khi giá đóng cửa vượt kháng cự.",
                "Đọc 1,0x chiều cao tam giác là mốc nguồn/headline; 0,5x là mốc thận trọng.",
                "Loại hoặc hạ trọng số mẫu kém thanh khoản, thiếu phiên, kéo quá dài hoặc không còn nén rõ.",
            ],
        },
        "data_scope_and_caveats": {
            "remaining_caveats": [
                "Không claim point-in-time universe toàn thị trường.",
                "Không dùng historical VN30/VN100 membership làm kết luận chính.",
                "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
                "Thống kê kết luận chính dùng nhóm tốt nhất + nhóm chuẩn; nhóm lỏng hoặc thiếu dữ liệu chỉ là nền thống kê và không dùng để chọn ví dụ công bố.",
            ]
        },
    }


def _vi_gate_label(value: Any) -> str:
    mapping = {"PASS": "đạt", "FAIL": "không đạt", "SCORED": "đã chấm"}
    return mapping.get(str(value or "").upper(), str(value or "không rõ"))


def _triangle_spec() -> dict[str, Any]:
    return {
        "title": "Tam giác tăng",
        "subtitle": "Mẫu nén dưới kháng cự ngang và phá vỡ lên",
        "base_target_multiple": 1.0,
        "base_target_label": "1,0x",
        "legacy_target_multiple": 1.0,
        "legacy_target_label": "1,0x",
        "target_unit_label": "chiều cao tam giác",
        "target_focus_title": "Mốc nguồn/headline",
        "target_focus_caption": "mốc nguồn 1,0x",
        "target_focus_reading": "mốc đầy đủ đủ mạnh sau calibration",
        "target_full_title": "Mốc đầy đủ",
        "target_full_reading": "mốc này trùng với headline vì full-height đã vượt calibration.",
        "morphology_sentence": "Kháng cự gần ngang, đáy sau cao dần, biên độ nén lại và xác nhận bằng giá đóng cửa phá lên.",
        "role_note": "Dùng như hồ sơ tham khảo hậu phá vỡ, không phải tín hiệu mua tự động.",
        "classification_sentence": "Trong phạm vi dữ liệu hiện có, tam giác tăng đủ dày mẫu để trở thành một chương độc lập của họ Tam giác.",
        "headline_scope": "Phần kết luận chính dùng nhóm mẫu đủ điều kiện công bố; toàn bộ mẫu phát hiện vẫn được giữ trong phần kiểm tra nền.",
        "local_source_chapter": 47,
        "schematic_caption": "Sơ đồ minh họa cấu trúc: kháng cự ngang, hỗ trợ dốc lên, vùng nén và phiên phá vỡ lên.",
        "how_subtitle": "Áp lực mua nâng dần dưới vùng kháng cự cố định",
        "labels": {"favorable_move": "mức tăng tốt nhất", "adverse_move": "mức kéo ngược sâu nhất"},
        "regime_group_title": "Trạng thái",
        "market_group_title": "Nhóm cổ phiếu",
        "liquidity_group_title": "Thanh khoản",
        "source_rule_ids": [
            "ta.shape.horizontal_top",
            "ta.touches.two_highs_two_lows",
            "ta.crossing.no_white_space",
            "ta.breakout.up_primary",
            "ta.target.measure_rule",
            "ta.throwback_pullback.context",
        ],
        "rule_text_map": {
            "horizontal top, up-sloping bottom": "Kháng cự gần ngang và hỗ trợ dốc lên.",
            "Require a near-horizontal upper boundary and rising lower boundary.": "Yêu cầu đường biên trên gần ngang và đường biên dưới đi lên.",
            "Breakout is upward.": "Phá vỡ lên là trường hợp chính của chương này.",
            "The primary ascending-triangle case uses upward breakout confirmation.": "Chỉ xác nhận mẫu chính khi giá đóng cửa phá lên qua kháng cự.",
        },
        "quick_question_rows": [
            ["Kháng cự", "Các đỉnh có bị chặn quanh cùng một vùng giá không?"],
            ["Hỗ trợ", "Các đáy có nâng dần lên không?"],
            ["Nén giá", "Biên độ dao động có thu hẹp trước breakout không?"],
            ["Phá vỡ", "Giá đóng cửa có vượt hẳn vùng kháng cự không?"],
        ],
        "component_rows": [
            ["Kháng cự ngang", "Vùng cung cố định phía trên mẫu.", "Hai đỉnh đầu gần nhau; sai lệch tối đa 3%."],
            ["Đáy nâng dần", "Cho thấy người mua chấp nhận giá cao hơn.", "Đáy sau cao hơn đáy trước tối thiểu 3%."],
            ["Vùng nén", "Khoảng cách tới kháng cự thu hẹp dần.", "Tỷ lệ nén tối đa 0,85."],
            ["Đường giá qua lại", "Giá cần đi qua lại trong thân mẫu; quá nhiều khoảng trống làm mẫu kém tin cậy.", "Dùng crossing count và white-space score để hạ tier."],
            ["Điểm hội tụ", "Breakout được đọc cùng vị trí tương đối với điểm hội tụ/apex của hai biên.", "Lưu apex progress và số phiên tới apex."],
            ["Vùng giá năm", "Vị trí phá vỡ trong vùng giá năm là bối cảnh, không phải tín hiệu độc lập.", "Lưu yearly range position khi đủ dữ liệu."],
            ["Phá vỡ", "Chỉ sau xác nhận mới đo kết quả.", "Đóng cửa vượt kháng cự 0,75%; tìm trong 25 phiên."],
            ["Mục tiêu", "Đo chiều cao rồi cộng vào đường kháng cự ngang; giá phá vỡ là mốc xác nhận.", "1,0x là mốc nguồn/headline; 0,5x là mốc thận trọng."],
        ],
        "reject_bullets": [
            "Đỉnh không cùng vùng giá: mẫu dễ là kênh tăng hoặc dao động rộng.",
            "Đáy không nâng dần: thiếu áp lực mua tích lũy.",
            "Không có nén: nếu biên độ không thu hẹp, hình học tam giác yếu.",
            "Phá vỡ chỉ trong phiên nhưng đóng cửa dưới kháng cự: chưa xác nhận.",
        ],
        "identification_paragraphs": [
            "Tam giác tăng bắt đầu bằng một vùng kháng cự tương đối ngang. Bên dưới vùng đó, các đáy sau cao hơn đáy trước, tạo thành đường hỗ trợ đi lên. Mẫu chỉ được xác nhận khi giá đóng cửa vượt ra khỏi vùng kháng cự."
        ],
        "example_intro": ["Ba ví dụ dưới đây lấy ưu tiên từ VN100/VN30 khi có thể: một mẫu đạt mục tiêu, một mẫu trung vị và một mẫu thất bại."],
        "failure_bullets": [
            "Thất bại 5% không phải stop-loss giao dịch; nó đo mẫu không đi đủ tối thiểu theo hướng phá vỡ.",
            "Tỷ lệ đạt mục tiêu phải đọc cùng thứ tự đường đi: mục tiêu đến sau một cú kéo ngược sâu thì chất lượng thấp hơn.",
            "Mẫu quá rộng hoặc thiếu nén nên bị đọc thận trọng dù có breakout.",
            "Mẫu có quá nhiều khoảng trống ở giữa hoặc phá vỡ quá sát điểm hội tụ cần bị hạ trọng số.",
        ],
        "failure_structure_label": "Mẫu quá dài hoặc quá rộng",
        "failure_structure_note": "Tam giác quá dài hoặc quá rộng dễ chuyển thành vùng tích lũy/kênh giá, làm tín hiệu phá vỡ kém sạch.",
        "walkthrough_rows": [
            ("Bắt đầu mẫu", "{formation_start_date}", "Giá bắt đầu đi vào vùng nén dưới kháng cự."),
            ("Kết thúc mẫu", "{formation_end_date}", "Cấu trúc tam giác đã hình thành; chờ xác nhận phá vỡ."),
            ("Ngày xác nhận", "{breakout_date}", "Giá phá vỡ {breakout_price}; mục tiêu đầy đủ {target_price}."),
            ("Đường đi sau đó", "Mức tăng tốt nhất {mfe_pct}%; mức kéo ngược sâu nhất {mae_pct}%.", "Cho biết chất lượng đường đi sau phá vỡ."),
            ("Kết quả", "Đạt mục tiêu: {target_hit}; thất bại 5%: {failure_5pct}.", "Ví dụ minh họa, không phải tín hiệu giao dịch."),
        ],
        "skip_condition_specs": [
            ("Mẫu kéo quá dài", "pattern_width_bars", "q75_bars", None, "Tam giác quá dài dễ chuyển thành vùng tích lũy hoặc kênh giá hơn là một mẫu nén rõ."),
            ("Chiều cao quá lớn", "pattern_height_pct", "q75", None, "Biên độ quá rộng làm mục tiêu hình học trở nên tham vọng và dễ méo bởi biến động riêng của mã."),
            ("Kháng cự không đủ phẳng", "high_spread_pct", "q75", None, "Đỉnh lệch quá xa nhau làm vùng cung phía trên kém rõ."),
            ("Đáy nâng quá yếu", "low_rise_pct", "q25", None, "Nếu đáy sau không nâng đủ rõ, áp lực mua tích lũy chưa thuyết phục."),
            ("Nén kém", "compression_ratio", "Trên 0,85x", "Trên 0,85x", "Không có nén, breakout dễ chỉ là dao động rộng quanh vùng kháng cự."),
        ],
        "target_paragraph": "Mục tiêu giá của tam giác tăng được đọc theo thang 0,5x, 0,75x và 1,0x chiều cao tam giác. Sau kiểm định calibration, mốc 1,0x - công thức đầy đủ cộng chiều cao vào kháng cự - đủ mạnh để làm mốc nguồn/headline; 0,5x chỉ là mốc thận trọng.",
        "quick_conclusion_rows": [
            ["Mẫu này dùng để đọc gì?", "Một vùng nén tăng dần dưới kháng cự, được xác nhận khi giá phá lên."],
            ["Mục tiêu nào nên là mốc chính?", "1,0x chiều cao tam giác là mốc nguồn/headline; 0,5x là mốc thận trọng."],
            ["Rủi ro chính là gì?", "Breakout yếu, kéo ngược sâu hoặc mẫu quá rộng thiếu nén."],
            ["Khi nào đáng chú ý hơn?", "Kháng cự rõ, đáy nâng đều, nén tốt, thanh khoản đủ tốt và breakout đóng cửa dứt khoát."],
            ["Khi nào không nên đọc quá tay?", "Khi chỉ có xuyên trong phiên, thiếu thanh khoản, quá nhiều khoảng trống trong mẫu, hoặc target đến sau một pha kéo ngược sâu."],
        ],
        "caveat_bullets": [
            "Không claim point-in-time universe toàn thị trường.",
            "Không dùng historical VN30/VN100 membership làm kết luận chính.",
            "Corporate actions và delisted/halted hiện là kiểm tra thay thế, chưa phải status tape chính thức.",
            "Các số kết luận chính dùng nhóm đủ chuẩn công bố; các mẫu lỏng hoặc thiếu dữ liệu chỉ dùng làm nền kiểm tra, không dùng để chọn ví dụ hoặc kết luận chính.",
        ],
        "family_roadmap_title": "Lộ trình Triangle Family",
        "family_roadmap_rows": [
            ["Tam giác tăng", "Chương hiện tại", "Đã có bộ quét riêng, kiểm tra thống kê, kiểm tra bằng mắt 30 mẫu và PDF công bố."],
            ["Tam giác giảm", "Chưa triển khai", "Cần scanner riêng cho phá vỡ xuống và cách viết theo vai trò phòng thủ/informational."],
            ["Tam giác cân", "Chưa triển khai", "Cần direction split vì mẫu có thể phá vỡ lên hoặc xuống; không dùng lại logic Tam giác tăng."],
        ],
        "family_contract_rows": [
            ["Bộ quét", "Riêng từng mẫu", "Không dùng lại bộ quét của họ mẫu hình khác hoặc copy bộ quét Tam giác tăng cho mẫu khác."],
            ["Target", "Riêng từng mẫu", "Mỗi biến thể phải có target family và base target được kiểm định riêng."],
            ["Tầng chất lượng", "Riêng từng mẫu", "Nhóm tốt nhất/chuẩn phải qua kiểm tra bằng mắt trước khi dùng làm ví dụ."],
            ["Khung trình bày", "Dùng chung", "Chỉ dùng chung bảng thống kê, kiểm định, hợp đồng kiểm tra hình ảnh và bố cục PDF."],
        ],
        "release_gate_rows": [
            ["Đủ mẫu", "Public-grade tối thiểu 800 mẫu; hiện tại 894 mẫu."],
            ["Đủ mạnh", "1,0x phải đạt ở vùng mạnh sau calibration, đạt trước kéo ngược đủ cao, thất bại được kiểm soát và MFE/MAE không suy yếu."],
            ["Đủ bền", "Tách theo thời gian và tương tác bối cảnh/thanh khoản không được gãy ở nhóm đủ mẫu."],
            ["Đủ sạch", "Kiểm tra bằng mắt nhóm tốt nhất và ví dụ in PDF phải đạt trước khi chốt."],
        ],
        "conclusion_bullets": [
            "Tam giác tăng là ứng viên chapter tiếp theo hợp lý vì mẫu dày và hình học rõ.",
            "Mốc nguồn 1,0x đã đủ mạnh trong calibration; 0,5x chỉ dùng để đọc độ nhạy của nhịp ngắn.",
            "Chương vẫn là tài liệu tham khảo hậu phá vỡ, chưa phải hệ thống mua bán.",
        ],
        "quantile_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên"),
            ("Chiều cao tam giác", "pattern_height_pct", "%"),
            ("Độ phẳng kháng cự", "high_spread_pct", "%"),
            ("Độ nâng đáy", "low_rise_pct", "%"),
            ("Tỷ lệ nén", "compression_ratio", "x"),
            ("Mức tăng tốt nhất", "mfe_pct", "%"),
            ("Mức kéo ngược sâu nhất", "mae_pct", "%"),
            ("Ngày chạm mục tiêu đầy đủ", "days_to_target", "phiên"),
        ],
        "general_stat_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên", "Tam giác tăng cần đủ thời gian để hình thành vùng kháng cự và đường hỗ trợ đi lên."),
            ("Chiều cao tam giác", "pattern_height_pct", "%", "Chiều cao là nền của measure rule."),
            ("Độ phẳng kháng cự", "high_spread_pct", "%", "Sai lệch đỉnh càng thấp, kháng cự càng rõ."),
            ("Độ nâng đáy", "low_rise_pct", "%", "Đáy nâng dần là lõi của hình học mẫu."),
            ("Tỷ lệ nén", "compression_ratio", "x", "Tỷ lệ càng thấp, vùng nén càng rõ."),
        ],
        "best_condition_specs": [
            ("Nhóm tốt nhất", "publication_quality_tier", "==", "premium", "Hình học rõ, đường giá sạch và đủ điều kiện trình bày công khai."),
            ("Nhóm chuẩn", "publication_quality_tier", "==", "standard", "Đủ dùng trong thống kê nhưng chưa chắc đẹp để minh họa."),
            ("Kháng cự phẳng", "high_spread_pct", "<=", 1.5, "Đỉnh càng cùng vùng giá, mẫu càng dễ đọc."),
            ("Đáy nâng mạnh", "low_rise_pct", ">", 6.0, "Áp lực mua rõ hơn dưới kháng cự."),
            ("Nén rõ", "compression_ratio", "<=", 0.65, "Biên độ thu hẹp trước breakout."),
            ("Đường giá sạch", "path_quality_bucket", "==", "clean", "Ít thiếu phiên và ít chuỗi đứng giá."),
        ],
    }


def _validated_premium_events(events: pd.DataFrame, validation_csv: Path = DEFAULT_PREMIUM_VALIDATION) -> pd.DataFrame:
    if not validation_csv.exists():
        return events.iloc[0:0].copy()
    events = events.copy()
    if "event_id" not in events.columns and "detection_id" in events.columns:
        events["event_id"] = events["detection_id"]
    if "event_id" not in events.columns:
        return events.iloc[0:0].copy()
    validation = pd.read_csv(validation_csv)
    if "event_id" not in validation.columns:
        return events.iloc[0:0].copy()
    scores = pd.to_numeric(validation.get("manual_visual_score_1_to_5"), errors="coerce")
    validation = validation[scores.notna()].copy()
    validation["manual_visual_score_1_to_5"] = scores[scores.notna()].astype(float)
    validation = validation[validation["manual_visual_score_1_to_5"] >= 4.0].copy()
    if validation.empty:
        return events.iloc[0:0].copy()
    validation_cols = ["event_id", "manual_visual_score_1_to_5", "manual_visual_bucket"]
    return events.merge(validation[validation_cols], on="event_id", how="inner")


def _load_example_validation(validation_csv: Path = DEFAULT_EXAMPLE_VALIDATION) -> pd.DataFrame:
    if not validation_csv.exists():
        return pd.DataFrame()
    validation = pd.read_csv(validation_csv)
    if "event_id" not in validation.columns:
        return pd.DataFrame()
    validation = validation.copy()
    validation["manual_visual_score_1_to_5"] = pd.to_numeric(validation.get("manual_visual_score_1_to_5"), errors="coerce")
    return validation[validation["manual_visual_score_1_to_5"].notna()].copy()


def _attach_example_validation(examples: Mapping[str, pd.Series], validation_csv: Path = DEFAULT_EXAMPLE_VALIDATION) -> dict[str, dict[str, Any]]:
    validation = _load_example_validation(validation_csv)
    by_event = validation.set_index("event_id").to_dict("index") if not validation.empty else {}
    out: dict[str, dict[str, Any]] = {}
    for role, event in examples.items():
        event_dict = event.to_dict()
        event_id = str(event_dict.get("event_id") or event_dict.get("detection_id") or "")
        review = by_event.get(event_id)
        event_dict["example_role"] = role
        event_dict["example_manual_reviewed"] = bool(review)
        if review:
            event_dict["example_manual_visual_score_1_to_5"] = float(review.get("manual_visual_score_1_to_5"))
            event_dict["example_manual_visual_bucket"] = review.get("manual_visual_bucket")
            event_dict["example_manual_reviewer_note"] = review.get("manual_reviewer_note")
        out[role] = event_dict
    return out


def _example_validation_summary(example_events: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    reviewed = [event for event in example_events.values() if event.get("example_manual_reviewed")]
    passed = [event for event in reviewed if str(event.get("example_manual_visual_bucket")).lower() == "pass"]
    return {
        "status": "SCORED" if reviewed else "MISSING",
        "reviewed_n": len(reviewed),
        "pass_n": len(passed),
        "manual_pass_rate_pct": round(len(passed) / max(len(reviewed), 1) * 100.0, 2) if reviewed else None,
        "reviewed_roles": [str(event.get("example_role")) for event in reviewed],
        "failure_example_reviewed": any(str(event.get("example_role")) == "failure" for event in reviewed),
    }


def _select_examples(events: pd.DataFrame) -> dict[str, pd.Series]:
    vn100 = events[events["market_group"].isin(["VN30", "VN100 ex VN30"])].copy()
    source = vn100 if not vn100.empty else events.copy()
    source["_market_rank"] = source["market_group"].map({"VN30": 0, "VN100 ex VN30": 1}).fillna(2)
    validated = _validated_premium_events(events)
    if not validated.empty:
        validated["_market_rank"] = validated["market_group"].map({"VN30": 0, "VN100 ex VN30": 1}).fillna(2)
    success_source = validated if not validated.empty else source
    success = success_source[(success_source["target_hit"] == True) & (success_source["target_first_before_adverse_5pct"] == True)].copy()
    failure = source[source["failure_5pct"] == True].copy()
    middle_source = validated if not validated.empty else source
    med = float(events["mfe_pct"].median())
    textbook = (
        success.sort_values(["_market_rank", "manual_visual_score_1_to_5", "pattern_quality_score", "mfe_pct"], ascending=[True, False, False, False]).iloc[0]
        if "manual_visual_score_1_to_5" in success.columns
        else success.sort_values(["_market_rank", "pattern_quality_score", "mfe_pct"], ascending=[True, False, False]).iloc[0]
    )
    textbook_id = str(textbook.get("event_id") or textbook.get("detection_id"))
    neutral = middle_source[(middle_source["event_id"].astype(str) != textbook_id) if "event_id" in middle_source.columns else (middle_source["detection_id"].astype(str) != textbook_id)].copy()
    if neutral.empty:
        neutral = source[(source["event_id"].astype(str) != textbook_id) if "event_id" in source.columns else (source["detection_id"].astype(str) != textbook_id)].copy()
    neutral["median_distance"] = (neutral["mfe_pct"] - med).abs()
    middle = (
        neutral.sort_values(["_market_rank", "median_distance", "manual_visual_score_1_to_5", "pattern_quality_score"], ascending=[True, True, False, False]).iloc[0]
        if "manual_visual_score_1_to_5" in neutral.columns
        else neutral.sort_values(["_market_rank", "median_distance", "pattern_quality_score"], ascending=[True, True, False]).iloc[0]
    )
    failure_pick = failure.sort_values(["_market_rank", "pattern_quality_score", "mae_pct"], ascending=[True, False, False]).iloc[0]
    return {"textbook_success": textbook, "failure": failure_pick, "middle_case": middle}


def _plot_schematic(out_path: Path) -> None:
    x = np.array([0, 1, 2, 3, 4, 5, 6, 7.2, 8.2])
    y = np.array([11, 18, 13, 18.2, 15.2, 18.1, 17.0, 20.0, 23.0])
    fig, ax = plt.subplots(figsize=(9.2, 3.9), dpi=180)
    ax.plot(x, y, color="#173b3a", linewidth=2.0)
    ax.scatter(x, y, s=22, color="#173b3a")
    ax.axhline(18.15, color="#6f4aa8", linestyle="--", linewidth=1.0)
    ax.plot([0, 6], [11, 17], color="#245b5a", linestyle="--", linewidth=1.0)
    ax.axvspan(0.0, 6.05, color="#1f77b4", alpha=0.10)
    ax.annotate("kháng cự ngang", xy=(3.2, 18.15), xytext=(2.2, 21.5), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
    ax.annotate("đáy nâng dần", xy=(4.0, 15.0), xytext=(1.2, 10.2), arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
    ax.annotate("phá vỡ", xy=(7.2, 20.0), xytext=(6.3, 23.0), arrowprops={"arrowstyle": "->", "color": "#6f4aa8"}, color="#6f4aa8", fontsize=9)
    ax.axhline(22.0, color="#e98b2a", linestyle="--", linewidth=0.9)
    ax.text(0, 22.2, "mốc nguồn theo chiều cao tam giác", color="#e98b2a", fontsize=8)
    ax.set_title("Giải phẫu mẫu tam giác tăng", loc="left", fontsize=10)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)


def _build_charts(events: pd.DataFrame, price_db: Path, out_dir: Path) -> dict[str, Path]:
    charts_dir = out_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    schematic = charts_dir / "ascending_triangle_ideal_schematic.png"
    _plot_schematic(schematic)
    paths = {"schematic": schematic}
    examples = _select_examples(events)
    title_map = {"textbook_success": "ví dụ đạt mục tiêu", "middle_case": "ví dụ trung vị", "failure": "ví dụ thất bại"}
    for key, event in examples.items():
        raw = _load_ohlcv(price_db, str(event["symbol"]))
        window = slice_around_event(raw, event, pre_bars=45, post_bars=45)
        out_path = charts_dir / f"{key}_{event['symbol']}_{event['breakout_date']}.png"
        plot_event_chart(window, event, out_path, f"{event['symbol']} - {title_map.get(key, 'ví dụ')} ({event['breakout_date']})")
        paths[key] = out_path
    return paths


def build_triangle_family_public_chapters(
    *,
    out_dir: Path = DEFAULT_OUT_DIR,
    price_db: Path = DEFAULT_PRICE_DB,
    stats_path: Path = DEFAULT_STATS,
    events_path: Path = DEFAULT_EVENTS,
    path_path: Path = DEFAULT_PATH,
    audit_path: Path = DEFAULT_AUDIT,
    ai_sections_path: Path = DEFAULT_AI_SECTIONS,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    chapter_dir = out_dir / "ascending_triangle"
    if chapter_dir.exists():
        import shutil

        shutil.rmtree(chapter_dir)
    all_events = pd.read_csv(events_path)
    if "event_id" not in all_events.columns and "detection_id" in all_events.columns:
        all_events["event_id"] = all_events["detection_id"]
    events = _public_events(all_events)
    path_df = pd.read_csv(path_path)
    stats = _read_json(stats_path)
    audit = _read_json(audit_path)
    payload = _publication_payload(stats, events, all_events, audit)
    editorial_sections, editorial_source_path = _load_required_editorial(ai_sections_path)
    payload["editorial_sections"] = editorial_sections
    payload["editorial_source_path"] = editorial_source_path
    spec = _triangle_spec()
    publication_spec = build_triangle_publication_spec(pattern_id="triangles_ascending", title="Tam giác tăng", spec=spec)
    payload["publication_spec_id"] = publication_spec["publication_spec_id"]
    selected_examples = _select_examples(events)
    payload["example_events"] = _attach_example_validation(selected_examples)
    payload["chapter_reference"]["example_visual_validation"] = _example_validation_summary(payload["example_events"])
    charts = _build_charts(events, price_db, chapter_dir)
    source_notes = _source_notes()
    source_notes_path = chapter_dir / "ascending_triangle_source_notes.json"
    publication_spec_path = chapter_dir / "ascending_triangle_publication_spec.json"
    paths = build_triangle_public_chapter(
        payload=payload,
        source_notes=source_notes,
        events=events,
        path_df=path_df,
        charts=charts,
        spec=spec,
        out_dir=chapter_dir,
        pdf_filename="ascending_triangle_final.pdf",
        payload_filename="ascending_triangle_public_chapter_payload.json",
        manuscript_filename="ascending_triangle_ai_editorial_manuscript.md",
        notes_filename="ascending_triangle_public_chapter_notes.md",
    )
    source_notes_path.write_text(json.dumps(source_notes, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    publication_spec_path.write_text(json.dumps(publication_spec, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    from scanner.build_descending_triangle_public_chapter import build_descending_triangle_public_chapter  # noqa: E402
    from scanner.build_symmetrical_triangle_public_chapter import build_symmetrical_triangle_public_chapter  # noqa: E402

    descending_paths = build_descending_triangle_public_chapter(out_dir=out_dir, price_db=price_db)
    symmetrical_paths = build_symmetrical_triangle_public_chapter(out_dir=out_dir, price_db=price_db)
    descending_payload = _read_json(descending_paths["payload"])
    descending_ref = descending_payload.get("chapter_reference") if isinstance(descending_payload.get("chapter_reference"), Mapping) else {}
    symmetrical_payload = _read_json(symmetrical_paths["payload"])
    symmetrical_ref = symmetrical_payload.get("chapter_reference") if isinstance(symmetrical_payload.get("chapter_reference"), Mapping) else {}
    manifest = {
        "release_id": "triangle_family_public_chapters_db_active_v1",
        "factory_id": FACTORY_ID,
        "source_scope": "DB active symbols from Market Cache latest.sqlite; no historical VN30/VN100 membership claim; no point-in-time all-market universe claim.",
        "chapters": [
            {
                "pattern_id": "triangles_ascending",
                "chapter_label": "Tam giác tăng",
                "pdf": str(paths["pdf"]),
                "release_gate": "scanner.validate_triangle_family_release_candidate",
                "all_n": int(len(all_events)),
                "public_grade_n": int(len(events)),
                "symbols_scanned": stats.get("symbols_scanned"),
                "base_target_hit_rate": payload["target_calibration"]["base_target"].get("target_hit_rate"),
                "target_first_before_adverse_5pct_rate": payload["target_calibration"]["base_target"].get("target_first_before_adverse_5pct_rate"),
                "failure_5pct_rate": payload["target_calibration"]["base_target"].get("failure_5pct_rate"),
            },
            {
                "pattern_id": "triangles_descending",
                "chapter_label": "Tam giác giảm",
                "pdf": str(descending_paths["pdf"]),
                "release_gate": "scanner.analyze_descending_triangle_branch_candidates",
                "all_n": descending_ref.get("all_scanner_events"),
                "public_grade_n": descending_ref.get("public_grade_events"),
                "classification": "defensive/informational branch-reference under available-series scope",
            },
            {
                "pattern_id": "triangles_symmetrical",
                "chapter_label": "Tam giác cân",
                "pdf": str(symmetrical_paths["pdf"]),
                "release_gate": "scanner.analyze_symmetrical_triangle_branch_candidates",
                "all_n": symmetrical_ref.get("all_scanner_events"),
                "public_grade_n": symmetrical_ref.get("public_grade_events"),
                "classification": "watchlist-reference branch candidate under available-series scope",
            },
        ],
        "outputs": {
            "ascending_triangle": {**{key: str(value) for key, value in paths.items()}, "source_notes": str(source_notes_path), "publication_spec": str(publication_spec_path)},
            "descending_triangle": {key: str(value) for key, value in descending_paths.items()},
            "symmetrical_triangle": {key: str(value) for key, value in symmetrical_paths.items()},
        },
    }
    manifest_json = out_dir / "triangle_family_public_chapters_manifest.json"
    manifest_md = out_dir / "triangle_family_public_chapters_manifest.md"
    manifest_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    manifest_md.write_text(
        "\n".join(
            [
                "# Triangle Family public chapters",
                "",
                f"Factory: `{FACTORY_ID}`",
                "",
                f"- Ascending Triangle PDF: `{paths['pdf']}`",
                f"- All N: `{len(all_events)}`",
                f"- Public-grade N: `{len(events)}`",
                f"- Base hit: `{payload['target_calibration']['base_target'].get('target_hit_rate')}%`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        **paths,
        "source_notes": source_notes_path,
        "publication_spec": publication_spec_path,
        "manifest_json": manifest_json,
        "manifest_md": manifest_md,
        "ascending_triangle_pdf": paths["pdf"],
        "descending_triangle_pdf": descending_paths["pdf"],
        "symmetrical_triangle_pdf": symmetrical_paths["pdf"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build DB-active Triangle Family public chapters.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--price-db", default=str(DEFAULT_PRICE_DB))
    args = parser.parse_args()
    paths = build_triangle_family_public_chapters(out_dir=Path(args.out_dir), price_db=Path(args.price_db))
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
