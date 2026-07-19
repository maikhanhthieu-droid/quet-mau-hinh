"""Publication specs for Double Bottom Adam/Eve variants.

These specs are public-editorial contracts, not scanner contracts.  They turn
source-grounded rules into Vietnamese chapter text and prevent variants from
falling back to a generic Double Pattern Family narrative.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from scanner.publication_semantic_contract import PUBLICATION_SEMANTIC_GATE_ID


RULE_TEXT_MAP = {
    "Price trends downward leading to the double bottom.": "Giá cần đi xuống trước khi tạo đáy đầu tiên.",
    "Yêu cầu xu hướng giảm đi vào đáy thứ nhất trước khi chấp nhận mẫu Hai đáy.": "Chỉ xét mẫu khi trước đó có nhịp giảm đủ rõ; nếu không, hai đáy dễ chỉ là dao động ngang.",
    "Double bottom pattern with narrow or spike bottoms.": "Mẫu gồm hai đáy kiểm tra lại cùng một vùng giá.",
    "Require two lows that form the double-bottom structure.": "Bộ quét cần thấy đáy thứ nhất, đỉnh hồi ở giữa và đáy thứ hai trước khi tìm xác nhận.",
    "At least 10% from the lowest valley to the highest peak between the two bottoms.": "Nhịp hồi từ đáy thấp nhất lên neckline tối thiểu 10%.",
    "Require meaningful rise from the lower bottom to the neckline; 10% is the source-grounded publication filter.": "Nếu nhịp hồi quá nông, hai đáy chưa tách thành hai minor lows đủ rõ để đưa vào thống kê chính.",
    "Bottom to bottom price variation is small.": "Hai đáy phải nằm gần nhau về giá.",
    "Require the two bottom lows to be close enough in price to represent a retest, not two unrelated lows.": "Đọc hai đáy như một lần kiểm tra lại vùng hỗ trợ, không phải hai đáy rời rạc.",
    "Bottoms should be at least a few weeks apart. Best performance came from bottoms between 2 and 6 weeks apart.": "Hai đáy nên cách nhau vài tuần; vùng 2-6 tuần là khoảng đọc tốt trong tài liệu gốc.",
    "Keep two bottoms as distinct minor lows; source-aligned scope prefers roughly 2-6 weeks and treats wider than 8 weeks cautiously.": "Hai đáy cần đủ xa để là hai điểm kiểm tra riêng biệt, nhưng quá xa thì mẫu dễ thành vùng nền kéo dài.",
    "A close above the confirmation point is the breakout and confirms the pattern as a valid double bottom.": "Mẫu chỉ xác nhận khi giá đóng cửa vượt neckline.",
    "Count the event only after close-confirmed breakout above the highest high between the bottoms.": "Chỉ đo hậu phá vỡ sau phiên đóng cửa vượt đỉnh hồi giữa hai đáy.",
    "Compute the height from the highest high to the lowest low in the formation and add the difference to the highest high.": "Mục tiêu đầy đủ lấy chiều cao từ đáy thấp nhất tới neckline rồi cộng lên neckline.",
    "Measure-rule target is formation height added to the confirmation point for upward double-bottom breakouts.": "Bản Việt Nam giữ mốc đầy đủ 1,0x làm mốc nguồn/headline sau calibration, đồng thời đọc thêm mốc thận trọng 0,5x.",
    "Throwbacks occur about half the time and return to the confirmation price.": "Giá thường quay lại kiểm định vùng neckline sau xác nhận.",
    "Report throwback/retest behavior as a core post-breakout statistic, not as a decorative appendix.": "Hành vi quay lại neckline là phần chính của hồ sơ hậu phá vỡ.",
    "Usually higher on the left bottom than the right. Bottoms with higher left volume perform better.": "Khối lượng đáy trái thường cao hơn đáy phải và nên được ghi nhận như bối cảnh.",
    "Track left-versus-right bottom volume as a context metric; do not reject solely because right-bottom volume is higher.": "Khối lượng hỗ trợ cách đọc mẫu, nhưng không tự biến thành điều kiện loại trực tiếp.",
    "Adam is a narrow, V-shaped, perhaps pointed-looking bottom, sometimes a long one- or two-day spike.": "Adam là đáy hẹp, nhọn, thường giống chữ V hoặc một nhịp rũ mạnh.",
    "Classify Adam bottoms as narrow/V-shaped or spike-like extremes.": "Phân loại Adam bằng độ hẹp, độ nhọn và phản ứng bật lên quanh đáy.",
    "The right Eve bottom appears rounded and wider; Eve typically has several short price spikes.": "Eve là vùng đáy rộng và tròn hơn, đôi khi có nhiều gai ngắn.",
    "Classify Eve bottoms as wider/rounded extreme zones with multiple short spikes when present.": "Phân loại Eve bằng độ rộng, độ tròn và sự kéo dài quanh vùng đáy.",
    "For AEDBs, the Adam bottom must be on the left and the Eve bottom on the right.": "Với Adam & Eve, đáy Adam nằm bên trái và đáy Eve nằm bên phải.",
    "For the Adam & Eve chapter, require variant code AE: left bottom Adam, right bottom Eve.": "Chương Adam & Eve chỉ giữ đúng thứ tự: đáy trái Adam, đáy phải Eve.",
    "For the Eve & Adam chapter, require variant code EA: left bottom Eve, right bottom Adam.": "Chương Eve & Adam chỉ giữ đúng thứ tự: đáy trái Eve, đáy phải Adam.",
    "For the Eve & Eve chapter, require variant code EE: both bottoms Eve.": "Chương Eve & Eve chỉ giữ các mẫu mà cả hai đáy đều thuộc nhóm Eve.",
}


BASE_FORBIDDEN_TERMS = [
    "payload",
    "factory",
    "source_alignment",
    "publication_quality_tier",
    "data_limited",
    "branch_id",
    "chapter_lane",
    "candidate",
    "headline",
    "audit",
    "Double Pattern Family",
    "Require ",
    "Price trends downward",
    "Double bottom pattern",
    "At least 10%",
    "Bottom to bottom",
    "Bottoms should be",
    "A close above",
    "Compute the height",
]


def _base_story_spec() -> dict[str, Any]:
    return {
        "base_target_multiple": 1.0,
        "base_target_label": "1,0x",
        "legacy_target_multiple": 1.0,
        "legacy_target_label": "1,0x",
        "target_unit_label": "chiều cao từ đáy tới neckline",
        "target_focus_title": "Mốc nguồn/headline",
        "target_focus_caption": "mốc nguồn 1,0x",
        "target_focus_reading": "mốc đầy đủ đủ mạnh sau calibration",
        "target_full_title": "Mốc đầy đủ",
        "target_full_reading": "mốc này trùng với headline vì full-height đã vượt calibration.",
        "morphology_sentence": "Hai đáy kiểm tra lại cùng một vùng hỗ trợ, hồi lên neckline ở giữa và chỉ xác nhận khi đóng cửa vượt neckline.",
        "role_note": "Dùng như hồ sơ tham khảo hậu phá vỡ, không phải tín hiệu mua tự động.",
        "example_scope_label": "VN30/VN100 hiện có",
        "labels": {
            "favorable_move": "mức tăng tốt nhất",
            "adverse_move": "mức kéo ngược sâu nhất",
        },
        "source_rule_ids": [
            "db.prior_trend.downward",
            "db.rise_between_bottoms.min_10pct",
            "db.bottom_similarity.close_prices",
            "db.bottom_separation.few_weeks",
            "db.confirmation.close_above_highest_high",
            "db.measure_rule.height_to_confirmation",
        ],
        "rule_text_map": RULE_TEXT_MAP,
        "component_rows": [
            ["Đáy thứ nhất", "Điểm thị trường rơi về vùng hỗ trợ đầu tiên.", "Lưu giá đáy, độ nhọn/tròn và khối lượng."],
            ["Neckline", "Đỉnh hồi giữa hai đáy; đây là đường xác nhận.", "Dùng highest high giữa hai đáy."],
            ["Đáy thứ hai", "Lần kiểm tra lại vùng đáy đầu tiên.", "Giá phải gần đáy thứ nhất và không phá cấu trúc quá sâu."],
            ["Xác nhận", "Chỉ sau xác nhận mới đo kết quả.", "Đóng cửa vượt neckline."],
            ["Mục tiêu", "Mốc đo đường đi sau xác nhận.", "1,0x là mốc nguồn/headline; 0,5x là mốc thận trọng."],
        ],
        "reject_bullets": [
            "Không có xu hướng giảm trước mẫu: hai đáy khi đó dễ chỉ là nhiễu đi ngang.",
            "Nhịp hồi lên neckline dưới 10%: hai đáy chưa đủ tách biệt.",
            "Hai đáy lệch giá quá xa: mẫu không còn là kiểm định lại cùng vùng hỗ trợ.",
            "Không có đóng cửa vượt neckline: chưa có sự kiện phá vỡ để đo hậu quả.",
            "Đường giá thiếu dữ liệu hoặc thanh khoản quá yếu: kết quả hậu phá vỡ cần đọc thận trọng.",
        ],
        "skip_condition_specs": [
            ("Nhịp hồi quá nông", "pattern_height_pct", "q25", None, "Neckline thấp làm target dễ nhiễu và mẫu kém rõ."),
            ("Hai đáy lệch nhau nhiều", "extreme_spread_pct", "q75", None, "Độ giống nhau của hai đáy yếu đi."),
            ("Mẫu kéo dài", "pattern_width_bars", "q75_bars", None, "Quá dài thì mẫu dễ trở thành vùng nền thay vì hai đáy gọn."),
            ("Kéo ngược sâu", "mae_pct", "q75", None, "Đường đi sau xác nhận làm giảm giá trị tham khảo."),
        ],
        "quantile_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên"),
            ("Chiều cao tới neckline", "pattern_height_pct", "%"),
            ("Độ lệch hai đáy", "extreme_spread_pct", "%"),
            ("Mục tiêu đầy đủ", "target_dist_pct", "%"),
            ("Mức tăng tốt nhất", "mfe_pct", "%"),
            ("Mức kéo ngược sâu nhất", "mae_pct", "%"),
            ("Ngày chạm mục tiêu đầy đủ", "days_to_target", "phiên"),
        ],
        "general_stat_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên", "Cho biết hai đáy cách nhau bao lâu."),
            ("Chiều cao tới neckline", "pattern_height_pct", "%", "Đo sức hồi giữa hai đáy và là nền cho target."),
            ("Độ lệch hai đáy", "extreme_spread_pct", "%", "Hai đáy càng gần nhau, ý nghĩa kiểm định lại càng rõ."),
            ("Độ cân đối", "balance_ratio", "lần", "Hai nhịp quanh neckline càng cân bằng thì mẫu càng dễ đọc."),
        ],
        "best_condition_specs": [
            ("Hai đáy giống nhau hơn", "extreme_spread_pct", "<=", 2.5, "Hai điểm kiểm tra cùng vùng giá rõ hơn."),
            ("Mẫu cân đối", "balance_ratio", ">", 0.5, "Hai nhịp quanh neckline không quá lệch thời gian."),
            ("Đường giá sạch", "path_quality_bucket", "==", "clean", "Ít thiếu phiên và ít chuỗi đứng giá."),
        ],
        "walkthrough_rows": [
            ["Đáy thứ nhất", "{formation_start_date}", "Vùng hỗ trợ đầu tiên xuất hiện sau nhịp giảm."],
            ["Đáy thứ hai", "{formation_end_date}", "Giá kiểm định lại vùng hỗ trợ gần đáy đầu."],
            ["Xác nhận", "{breakout_date}", "Đóng cửa vượt neckline tại {breakout_price}; mốc đầy đủ là {target_price}."],
            ["Đường đi sau đó", "Tăng tốt nhất {mfe_pct}%; kéo ngược sâu nhất {mae_pct}%.", "Đây là phần quyết định chất lượng thực nghiệm."],
            ["Kết quả", "Đạt mục tiêu: {target_hit}; thất bại 5%: {failure_5pct}.", "Ví dụ minh họa, không phải lệnh giao dịch."],
        ],
        "failure_bullets": [
            "Thất bại 5% đo việc giá không đi được tối thiểu 5% sau xác nhận.",
            "Target-first quan trọng vì một mẫu có thể chạm target sau khi đã kéo ngược rất sâu.",
            "Đáy Adam/Eve đẹp không thay thế được xác nhận neckline và đường đi hậu phá vỡ.",
        ],
        "target_paragraph": "Mục tiêu đầy đủ lấy chiều cao từ đáy thấp nhất tới neckline. Sau kiểm định calibration, các biến thể Hai đáy dùng 1,0x làm mốc nguồn/headline; 0,5x chỉ là mốc thận trọng để xem nhịp ngắn.",
        "example_intro": [
            "Ví dụ được chọn để minh họa ba trạng thái: một mẫu đi đúng tốt, một mẫu gần trung vị và một mẫu thất bại. Mục tiêu là giúp người đọc thấy ranh giới của mẫu, không chỉ xem chart đẹp.",
        ],
        "success_heading": "Ví dụ xác nhận tốt",
        "quick_conclusion_rows": [
            ["Có dùng như tín hiệu mua không?", "Không. Đây là hồ sơ tham khảo hậu phá vỡ."],
            ["Mốc nào nên đọc trước?", "1,0x là mốc nguồn/headline; 0,5x là mốc thận trọng để xem nhịp ngắn."],
            ["Adam/Eve có tự tạo lợi thế không?", "Không. Hình thái chỉ là điều kiện nhận diện; kết quả vẫn phụ thuộc neckline và đường đi sau xác nhận."],
        ],
        "caveat_bullets": [
            "Không claim point-in-time universe toàn thị trường.",
            "Nhóm VN30/VN100 là đại diện hiện có, không phải membership lịch sử.",
            "Corporate actions và trạng thái hủy niêm yết/tạm ngừng chỉ được kiểm tra trong phạm vi dữ liệu hiện có.",
            "Đây là chapter tham khảo đầu tư, không phải hệ thống vào/ra lệnh.",
        ],
        "liquidity_group_title": "Thanh khoản",
        "regime_group_title": "Bối cảnh",
        "market_group_title": "Nhóm cổ phiếu",
        "failure_structure_label": "Neckline yếu hoặc mẫu kéo dài",
        "failure_structure_note": "Khi neckline không rõ hoặc mẫu kéo quá dài, hai đáy dễ mất tính đảo chiều gọn.",
    }


VARIANT_OVERRIDES = {
    "AA": {
        "title": "Hai đáy Adam & Adam",
        "subtitle": "Hai đáy hẹp, nhọn và xác nhận bằng neckline",
        "publication_spec_id": "double_bottoms_adam_adam_publication_spec_v1",
        "variant_label": "Adam & Adam",
        "source_chapter": 13,
        "variant_rule_id": "variant-filter",
        "variant_required_phrase": "Hai đáy Adam & Adam",
        "morphology_sentence": "Hai đáy Adam & Adam có hai đáy hẹp hoặc nhọn, thường giống hai lần rũ mạnh quanh cùng một vùng hỗ trợ.",
        "how_subtitle": "Hai lần rũ xuống cùng vùng giá, rồi xác nhận khi vượt neckline",
        "summary_paragraphs": [
            "Adam & Adam là biến thể hai đáy có cả hai đáy đều hẹp hoặc nhọn. Cách đọc quan trọng nhất là không xem hai spike là mẫu hợp lệ cho tới khi giá đóng cửa vượt neckline.",
            "Trong bản Việt Nam, chương này dùng mốc đầy đủ 1,0x chiều cao từ đáy tới neckline làm mốc nguồn/headline sau calibration; 0,5x chỉ là mốc thận trọng. Các con số dùng để tham khảo hành vi hậu phá vỡ, không phải tín hiệu mua tự động.",
        ],
        "tour_paragraphs": [
            "Biến thể Adam & Adam thường có cảm giác sắc và nhanh hơn các biến thể có Eve. Hai đáy giống hai lần thị trường rũ xuống, bật lên, rồi kiểm tra lại vùng hỗ trợ.",
            "Điểm dễ sai là nhìn hai đáy nhọn rồi kết luận quá sớm. Theo tinh thần Bulkowski, confirmation line mới là mốc biến cấu trúc thành mẫu đã xác nhận.",
        ],
        "identification_paragraphs": [
            "Tìm một nhịp giảm trước mẫu, sau đó là đáy Adam thứ nhất, hồi lên neckline, rồi đáy Adam thứ hai gần vùng giá đáy đầu.",
            "Hai đáy Adam cần hẹp hoặc nhọn. Nếu một đáy rộng và tròn hơn, mẫu có thể thuộc Adam & Eve hoặc Eve & Adam, không nên gộp vào chương này.",
            "Mẫu chỉ được tính khi giá đóng cửa vượt neckline sau đáy thứ hai.",
        ],
        "rule_first_note": "Adam & Adam là biến thể sắc: hình thái hai đáy quan trọng, nhưng xác nhận neckline mới quyết định thời điểm đo kết quả.",
        "conclusion_bullets": [
            "Adam & Adam nên được đọc như biến thể hai đáy nhọn, không phải toàn bộ họ Double Bottom.",
            "Mốc 1,0x giữ vai trò nguồn/headline; mốc 0,5x chỉ giúp đọc mức di chuyển thận trọng hơn.",
            "Nếu hai đáy không thật sự hẹp/nhọn hoặc chưa vượt neckline, không dùng mẫu để suy luận hậu phá vỡ.",
        ],
        "public_required_phrases": ["Hai đáy Adam & Adam", "hai đáy đều hẹp hoặc nhọn", "đóng cửa vượt neckline"],
    },
    "AE": {
        "title": "Hai đáy Adam & Eve",
        "subtitle": "Đáy trái nhọn, đáy phải rộng hơn và xác nhận bằng neckline",
        "publication_spec_id": "double_bottoms_adam_eve_publication_spec_v1",
        "variant_label": "Adam & Eve",
        "source_chapter": 14,
        "variant_rule_id": "db.variant.adam_eve_order",
        "variant_required_phrase": "Hai đáy Adam & Eve",
        "morphology_sentence": "Hai đáy Adam & Eve có đáy trái hẹp hoặc nhọn, đáy phải rộng và tròn hơn, rồi xác nhận khi giá đóng cửa vượt neckline.",
        "how_subtitle": "Đáy trái là cú rũ nhanh; đáy phải là vùng kiểm định rộng hơn",
        "summary_paragraphs": [
            "Adam & Eve là biến thể hai đáy trong đó đáy trái là Adam - hẹp, nhọn hoặc giống một cú rũ nhanh - còn đáy phải là Eve - rộng và tròn hơn.",
            "Chương này chỉ đo các mẫu đã vượt neckline. Mục tiêu là mô tả hậu quả lịch sử của biến thể Adam & Eve trong dữ liệu Việt Nam hiện có, không biến mẫu thành tín hiệu mua tự động.",
        ],
        "tour_paragraphs": [
            "Câu chuyện của Adam & Eve khác Adam & Adam ở đáy thứ hai. Sau cú rũ nhanh đầu tiên, thị trường quay lại vùng hỗ trợ nhưng mất nhiều thời gian hơn để tạo đáy phải.",
            "Vì đáy Eve rộng hơn, người đọc dễ nhầm mẫu với một vùng nền nhỏ. Do đó neckline và nhịp hồi tối thiểu lên neckline là hai cổng nhận diện quan trọng.",
        ],
        "identification_paragraphs": [
            "Tìm một nhịp giảm trước mẫu, sau đó là đáy trái Adam hẹp hoặc nhọn.",
            "Giá phải hồi lên neckline đủ rõ rồi quay lại tạo đáy phải Eve rộng hơn, tròn hơn hoặc có nhiều điểm chạm ngắn quanh vùng đáy.",
            "Mẫu chỉ được xác nhận khi giá đóng cửa vượt neckline; trước đó, nó chỉ là ứng viên hai đáy.",
        ],
        "rule_first_note": "Adam & Eve phải giữ đúng thứ tự: Adam ở bên trái, Eve ở bên phải. Nếu thứ tự đảo ngược, đó là biến thể khác và cần chương khác.",
        "conclusion_bullets": [
            "Adam & Eve là biến thể riêng, không phải Double Bottom tổng quát.",
            "Đáy phải Eve giúp mô tả quá trình kiểm định hỗ trợ kéo dài hơn, nhưng kết quả vẫn phải đọc qua target, failure và kéo ngược.",
            "Mốc 1,0x là mốc nguồn/headline; mốc 0,5x là mốc thận trọng để so sánh nhịp ngắn.",
        ],
        "public_required_phrases": ["Hai đáy Adam & Eve", "đáy trái hẹp hoặc nhọn", "đáy phải rộng và tròn hơn", "đóng cửa vượt neckline"],
    },
    "EA": {
        "title": "Hai đáy Eve & Adam",
        "subtitle": "Đáy trái rộng hơn, đáy phải nhọn hơn và xác nhận bằng neckline",
        "publication_spec_id": "double_bottoms_eve_adam_publication_spec_v1",
        "variant_label": "Eve & Adam",
        "source_chapter": 15,
        "variant_rule_id": "variant-filter",
        "variant_required_phrase": "Hai đáy Eve & Adam",
        "morphology_sentence": "Hai đáy Eve & Adam có đáy trái rộng hoặc tròn hơn, đáy phải hẹp hoặc nhọn hơn, rồi xác nhận khi giá đóng cửa vượt neckline.",
        "how_subtitle": "Đáy trái là vùng kiểm định rộng; đáy phải là cú rũ nhanh hơn trước xác nhận",
        "summary_paragraphs": [
            "Eve & Adam là biến thể hai đáy trong đó đáy trái là Eve - rộng, tròn hoặc kéo dài hơn - còn đáy phải là Adam - hẹp, nhọn hoặc giống một cú rũ nhanh.",
            "Chương này chỉ đo các mẫu đã vượt neckline. Vai trò của nó là mô tả hậu quả lịch sử của biến thể Eve & Adam trong dữ liệu Việt Nam hiện có, không biến mẫu thành tín hiệu mua tự động.",
        ],
        "tour_paragraphs": [
            "Câu chuyện của Eve & Adam thường bắt đầu bằng một vùng tạo đáy rộng hơn. Sau đó thị trường quay lại vùng hỗ trợ bằng một đáy phải sắc hơn trước khi xác nhận neckline.",
            "Điểm dễ sai là gộp Eve & Adam vào Double Bottom chung. Trong chương này, thứ tự hình thái là điều kiện cứng: Eve ở trái, Adam ở phải.",
        ],
        "identification_paragraphs": [
            "Tìm một nhịp giảm trước mẫu, sau đó là đáy trái Eve rộng hoặc tròn hơn.",
            "Giá phải hồi lên neckline đủ rõ rồi quay lại tạo đáy phải Adam hẹp hơn, nhọn hơn hoặc có phản ứng bật lên nhanh hơn.",
            "Mẫu chỉ được xác nhận khi giá đóng cửa vượt neckline; trước đó, nó chỉ là ứng viên hai đáy.",
        ],
        "rule_first_note": "Eve & Adam phải giữ đúng thứ tự: Eve ở bên trái, Adam ở bên phải. Nếu thứ tự đảo ngược, đó là Adam & Eve và cần chương khác.",
        "conclusion_bullets": [
            "Eve & Adam là biến thể riêng, không phải Double Bottom tổng quát.",
            "Đáy trái Eve mô tả giai đoạn tạo nền rộng hơn; đáy phải Adam mô tả cú kiểm định nhanh trước xác nhận.",
            "Mốc 1,0x là mốc nguồn/headline; mốc 0,5x là mốc thận trọng để so sánh nhịp ngắn.",
        ],
        "public_required_phrases": ["Hai đáy Eve & Adam", "đáy trái rộng hoặc tròn hơn", "đáy phải hẹp hoặc nhọn hơn", "đóng cửa vượt neckline"],
    },
    "EE": {
        "title": "Hai đáy Eve & Eve",
        "subtitle": "Hai đáy rộng hơn, tròn hơn và xác nhận bằng neckline",
        "publication_spec_id": "double_bottoms_eve_eve_publication_spec_v1",
        "variant_label": "Eve & Eve",
        "source_chapter": 16,
        "variant_rule_id": "variant-filter",
        "variant_required_phrase": "Hai đáy Eve & Eve",
        "morphology_sentence": "Hai đáy Eve & Eve có cả hai đáy đều rộng hoặc tròn hơn, rồi xác nhận khi giá đóng cửa vượt neckline.",
        "how_subtitle": "Hai vùng kiểm định hỗ trợ rộng hơn trước khi vượt neckline",
        "summary_paragraphs": [
            "Eve & Eve là biến thể hai đáy trong đó cả hai đáy đều rộng, tròn hoặc kéo dài hơn đáy Adam.",
            "Chương này đo riêng các mẫu Eve & Eve đã vượt neckline. Các con số được dùng như hồ sơ tham khảo hậu phá vỡ, không phải hệ thống giao dịch.",
        ],
        "tour_paragraphs": [
            "Eve & Eve thường có cảm giác chậm và rộng hơn Adam & Adam. Thay vì hai cú rũ sắc, người đọc nhìn thấy hai vùng kiểm định hỗ trợ có độ tròn hoặc độ kéo dài rõ hơn.",
            "Vì hai đáy đều rộng, mẫu dễ bị nhầm với một vùng nền. Do đó neckline, nhịp hồi tối thiểu và xác nhận đóng cửa là ba cổng quan trọng.",
        ],
        "identification_paragraphs": [
            "Tìm một nhịp giảm trước mẫu, sau đó là đáy Eve thứ nhất rộng hoặc tròn hơn.",
            "Giá hồi lên neckline rồi quay lại tạo đáy Eve thứ hai, cũng rộng hoặc tròn hơn thay vì chỉ là một spike hẹp.",
            "Mẫu chỉ được xác nhận khi giá đóng cửa vượt neckline; trước đó, nó chỉ là ứng viên hai đáy.",
        ],
        "rule_first_note": "Eve & Eve phải có cả hai đáy thuộc nhóm Eve. Nếu một đáy quá hẹp hoặc quá nhọn, mẫu có thể thuộc biến thể Adam/Eve khác.",
        "conclusion_bullets": [
            "Eve & Eve là biến thể hai đáy rộng hơn, thường cần đọc thận trọng hơn vì dễ hòa vào vùng nền.",
            "Xác nhận neckline là điều kiện bắt buộc trước khi đo hậu phá vỡ.",
            "Mốc 1,0x là mốc nguồn/headline; mốc 0,5x là mốc thận trọng để so sánh nhịp ngắn.",
        ],
        "public_required_phrases": ["Hai đáy Eve & Eve", "cả hai đáy đều rộng hoặc tròn hơn", "đóng cửa vượt neckline"],
    },
}


def build_double_bottom_variant_publication_spec(variant: str, *, n_events: int) -> dict[str, Any]:
    if variant not in VARIANT_OVERRIDES:
        raise ValueError(f"Unsupported Double Bottom variant: {variant}")
    overrides = VARIANT_OVERRIDES[variant]
    story = _base_story_spec()
    story.update({key: deepcopy(value) for key, value in overrides.items() if key not in {"publication_spec_id", "source_chapter", "variant_label", "variant_required_phrase", "public_required_phrases"}})
    story["classification_sentence"] = (
        f"{overrides['title']} là chương biến thể riêng, dựa trên {n_events} mẫu bám sát nguồn gốc và đủ dữ liệu đường giá."
    )
    story["headline_scope"] = (
        f"Kết luận chính chỉ áp dụng cho biến thể {overrides['variant_label']} đã xác nhận bằng neckline."
    )
    story["quick_question_rows"] = [
        ["Đây là chương gì?", f"Biến thể {overrides['variant_label']} của mẫu Hai đáy."],
        ["Có gộp với biến thể khác không?", "Không. Mỗi biến thể Adam/Eve có chương và thống kê riêng."],
        ["Khi nào mẫu được tính?", "Chỉ sau khi giá đóng cửa vượt neckline."],
    ]
    story["source_rule_ids"] = [
        "db.prior_trend.downward",
        "db.rise_between_bottoms.min_10pct",
        "db.bottom_similarity.close_prices",
        "db.bottom_separation.few_weeks",
        "db.confirmation.close_above_highest_high",
        str(overrides["variant_rule_id"]),
    ]
    semantic = {
        "status": "PASS",
        "semantic_gate_id": PUBLICATION_SEMANTIC_GATE_ID,
        "publication_spec_id": overrides["publication_spec_id"],
        "pattern_id": f"double_bottoms_{ {'AA': 'adam_adam', 'AE': 'adam_eve', 'EA': 'eve_adam', 'EE': 'eve_eve'}[variant] }",
        "family": "double_pattern_family",
        "source_chapter": overrides["source_chapter"],
        "spec_scope": "pattern_variant",
        "variant_specific": True,
        "variant": variant,
        "public_required_phrases": list(overrides["public_required_phrases"]),
        "public_forbidden_terms": list(BASE_FORBIDDEN_TERMS),
        "story_spec": story,
    }
    return semantic


TOP_RULE_TEXT_MAP = {
    "Upward price trend": "Giá cần đi lên trước khi tạo đỉnh thứ nhất.",
    "Require an upward trend into the first top before accepting a Double Top candidate.": "Chỉ xét mẫu khi trước đó có nhịp tăng đủ rõ; nếu không, hai đỉnh dễ chỉ là dao động ngang.",
    "Two well-defined peaks": "Mẫu cần hai đỉnh rõ, được ngăn cách bởi một neckline ở giữa.",
    "Require two top pivots that define the double-top structure.": "Bộ quét cần thấy đỉnh thứ nhất, đáy hồi ở giữa và đỉnh thứ hai trước khi tìm xác nhận.",
    "The valley depth usually measures in the 10% to 20% range, but allow exceptions.": "Độ sâu từ đỉnh xuống neckline thường quanh 10-20%, nhưng tài liệu gốc cho phép ngoại lệ.",
    "Require a meaningful decline from the higher top to the confirmation valley; 10% is the source-grounded publication filter when sample depth permits.": "Nếu nhịp rơi xuống neckline quá nông, hai đỉnh chưa tách thành hai minor highs đủ rõ để đưa vào thống kê chính.",
    "Top to top price variation is small, usually 0% to 3%, but allow higher differences.": "Hai đỉnh nên nằm gần nhau về giá; nếu lệch quá xa, mẫu dễ là hai đỉnh rời rạc.",
    "Require the two top highs to be close enough in price to represent a retest, not two unrelated peaks.": "Đọc hai đỉnh như một lần kiểm định lại vùng kháng cự, không phải hai đỉnh không liên quan.",
    "Tops should be at least a few weeks apart with most falling in the 2-7 week range.": "Hai đỉnh nên cách nhau vài tuần; vùng 2-7 tuần là khoảng đọc tốt trong tài liệu gốc.",
    "Keep two tops as distinct minor highs; source-aligned scope prefers roughly 2-7 weeks and treats wider formations cautiously.": "Hai đỉnh cần đủ xa để là hai lần kiểm định riêng biệt, nhưng quá xa thì mẫu dễ thành vùng phân phối kéo dài.",
    "Confirmation is a close below the lowest low between the two tops.": "Mẫu chỉ xác nhận khi giá đóng cửa dưới neckline.",
    "Count the event only after close-confirmed breakout below the valley between the tops.": "Chỉ đo hậu phá vỡ sau phiên đóng cửa xuyên xuống đáy hồi giữa hai đỉnh.",
    "Breakout is downward.": "Hướng xác nhận của Hai đỉnh là phá vỡ xuống.",
    "The first peak is an Adam top, usually with a narrow price spike, inverted V shape.": "Adam là đỉnh hẹp, nhọn, thường giống chữ V ngược hoặc một cú kéo lên nhanh.",
    "Classify Adam tops as narrow, pointed, inverted-V or spike-like extremes.": "Phân loại Adam bằng độ hẹp, độ nhọn và phản ứng đảo chiều quanh đỉnh.",
    "The Eve peak is wider and more rounded, perhaps composed of several short spikes.": "Eve là vùng đỉnh rộng và tròn hơn, đôi khi gồm nhiều gai ngắn.",
    "Classify Eve tops as wider/rounded extreme zones with multiple short spikes when present.": "Phân loại Eve bằng độ rộng, độ tròn và sự kéo dài quanh vùng đỉnh.",
    "Top volume usually higher on the left top.": "Khối lượng đỉnh trái thường cao hơn và nên được ghi nhận như bối cảnh.",
    "Track left-versus-right top volume as a context metric; do not reject solely because right-top volume is higher.": "Khối lượng hỗ trợ cách đọc mẫu, nhưng không tự biến thành điều kiện loại trực tiếp.",
}


TOP_FORBIDDEN_TERMS = [
    *BASE_FORBIDDEN_TERMS,
    "Double top pattern",
    "Upward price trend",
    "Two well-defined peaks",
    "Confirmation is a close",
    "Breakout is downward",
]


def _top_base_story_spec() -> dict[str, Any]:
    return {
        "base_target_multiple": 0.5,
        "base_target_label": "0,5x",
        "legacy_target_multiple": 1.0,
        "legacy_target_label": "1,0x",
        "target_unit_label": "chiều cao từ đỉnh tới neckline",
        "target_focus_title": "Mốc thận trọng",
        "target_focus_caption": "mốc thận trọng 0,5x",
        "target_focus_reading": "mốc giảm vừa phải dùng trong vai trò phòng thủ",
        "target_full_title": "Mốc đầy đủ 1,0x",
        "target_full_reading": "mốc đầy đủ giữ để so độ nhạy, chưa dùng làm headline khi chưa trích đủ thống kê nguồn.",
        "morphology_sentence": "Hai đỉnh kiểm tra lại cùng một vùng kháng cự, rơi xuống neckline ở giữa và chỉ xác nhận khi đóng cửa dưới neckline.",
        "role_note": "Dùng như hồ sơ cảnh báo/phòng thủ hậu phá vỡ, không phải tín hiệu bán khống tự động.",
        "example_scope_label": "VN30/VN100 hiện có",
        "labels": {
            "favorable_move": "mức giảm thuận lợi nhất",
            "adverse_move": "mức bật ngược bất lợi nhất",
        },
        "source_rule_ids": [
            "dt.prior_trend.upward",
            "dt.valley_depth.meaningful",
            "dt.top_similarity.close_prices",
            "dt.top_separation.few_weeks",
            "dt.confirmation.close_below_lowest_low",
            "dt.breakout.down",
        ],
        "rule_text_map": TOP_RULE_TEXT_MAP,
        "component_rows": [
            ["Đỉnh thứ nhất", "Điểm thị trường chạm vùng kháng cự đầu tiên.", "Lưu giá đỉnh, độ nhọn/tròn và khối lượng."],
            ["Neckline", "Đáy hồi giữa hai đỉnh; đây là đường xác nhận.", "Dùng lowest low giữa hai đỉnh."],
            ["Đỉnh thứ hai", "Lần kiểm định lại vùng đỉnh đầu tiên.", "Giá phải gần đỉnh thứ nhất và không phá cấu trúc quá mạnh."],
            ["Xác nhận", "Chỉ sau xác nhận mới đo kết quả.", "Đóng cửa dưới neckline."],
            ["Mục tiêu", "Mốc đo đường đi sau xác nhận.", "0,5x là mốc thận trọng; 1,0x là mốc đầy đủ để kiểm độ nhạy."],
        ],
        "reject_bullets": [
            "Không có xu hướng tăng trước mẫu: hai đỉnh khi đó dễ chỉ là nhiễu đi ngang.",
            "Nhịp rơi xuống neckline quá nông: hai đỉnh chưa đủ tách biệt.",
            "Hai đỉnh lệch giá quá xa: mẫu không còn là kiểm định lại cùng vùng kháng cự.",
            "Không có đóng cửa dưới neckline: chưa có sự kiện phá vỡ để đo hậu quả.",
            "Đường giá thiếu dữ liệu hoặc thanh khoản quá yếu: kết quả hậu phá vỡ cần đọc thận trọng.",
        ],
        "skip_condition_specs": [
            ("Neckline quá nông", "pattern_height_pct", "q25", None, "Neckline nông làm target dễ nhiễu và mẫu kém rõ."),
            ("Hai đỉnh lệch nhau nhiều", "extreme_spread_pct", "q75", None, "Độ giống nhau của hai đỉnh yếu đi."),
            ("Mẫu kéo dài", "pattern_width_bars", "q75_bars", None, "Quá dài thì mẫu dễ trở thành vùng phân phối kéo dài."),
            ("Bật ngược bất lợi sâu", "mae_pct", "q75", None, "Đường đi sau xác nhận làm giảm giá trị cảnh báo."),
        ],
        "quantile_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên"),
            ("Chiều cao tới neckline", "pattern_height_pct", "%"),
            ("Độ lệch hai đỉnh", "extreme_spread_pct", "%"),
            ("Mục tiêu đầy đủ", "target_dist_pct", "%"),
            ("Mức giảm thuận lợi", "mfe_pct", "%"),
            ("Mức bật ngược bất lợi", "mae_pct", "%"),
            ("Ngày chạm mục tiêu đầy đủ", "days_to_target", "phiên"),
        ],
        "general_stat_specs": [
            ("Độ dài mẫu", "pattern_width_bars", "phiên", "Cho biết hai đỉnh cách nhau bao lâu."),
            ("Chiều cao tới neckline", "pattern_height_pct", "%", "Đo độ sâu về neckline và là nền cho target."),
            ("Độ lệch hai đỉnh", "extreme_spread_pct", "%", "Hai đỉnh càng gần nhau, ý nghĩa kiểm định lại càng rõ."),
            ("Độ cân đối", "balance_ratio", "lần", "Hai nhịp quanh neckline càng cân bằng thì mẫu càng dễ đọc."),
        ],
        "best_condition_specs": [
            ("Hai đỉnh giống nhau hơn", "extreme_spread_pct", "<=", 2.5, "Hai điểm kiểm định cùng vùng giá rõ hơn."),
            ("Mẫu cân đối", "balance_ratio", ">", 0.5, "Hai nhịp quanh neckline không quá lệch thời gian."),
            ("Đường giá sạch", "path_quality_bucket", "==", "clean", "Ít thiếu phiên và ít chuỗi đứng giá."),
        ],
        "walkthrough_rows": [
            ["Đỉnh thứ nhất", "{formation_start_date}", "Vùng kháng cự đầu tiên xuất hiện sau nhịp tăng."],
            ["Đỉnh thứ hai", "{formation_end_date}", "Giá kiểm định lại vùng kháng cự gần đỉnh đầu."],
            ["Xác nhận", "{breakout_date}", "Đóng cửa dưới neckline tại {breakout_price}; mốc đầy đủ là {target_price}."],
            ["Đường đi sau đó", "Giảm thuận lợi nhất {mfe_pct}%; bật ngược bất lợi nhất {mae_pct}%.", "Đây là phần quyết định chất lượng cảnh báo."],
            ["Kết quả", "Đạt mục tiêu: {target_hit}; thất bại 5%: {failure_5pct}.", "Ví dụ minh họa, không phải khuyến nghị bán."],
        ],
        "failure_bullets": [
            "Thất bại 5% đo việc giá không đi được tối thiểu 5% theo hướng phá vỡ xuống.",
            "Target-first quan trọng vì một mẫu có thể chạm target sau khi đã bật ngược rất sâu.",
            "Đỉnh Adam/Eve đẹp không thay thế được xác nhận neckline và đường đi hậu phá vỡ.",
        ],
        "target_paragraph": "Mục tiêu đầy đủ lấy chiều cao từ đỉnh cao nhất tới neckline rồi trừ xuống neckline. Với Hai đỉnh, chương hiện đọc 0,5x như mốc thận trọng/phòng thủ vì thống kê nguồn cho target cần được trích riêng trước khi phong 1,0x làm headline.",
        "example_intro": [
            "Ví dụ được chọn để minh họa ba trạng thái: một mẫu đi đúng tốt, một mẫu gần trung vị và một mẫu thất bại. Mục tiêu là giúp người đọc thấy ranh giới cảnh báo của mẫu, không chỉ xem chart đẹp.",
        ],
        "success_heading": "Ví dụ xác nhận tốt",
        "quick_conclusion_rows": [
            ["Có dùng như tín hiệu bán không?", "Không. Đây là hồ sơ cảnh báo/phòng thủ hậu phá vỡ."],
            ["Mốc nào nên đọc trước?", "0,5x là mốc thận trọng; 1,0x là mốc đầy đủ để kiểm độ nhạy."],
            ["Adam/Eve có tự tạo lợi thế không?", "Không. Hình thái chỉ là điều kiện nhận diện; kết quả vẫn phụ thuộc neckline và đường đi sau xác nhận."],
        ],
        "caveat_bullets": [
            "Không claim point-in-time universe toàn thị trường.",
            "Nhóm VN30/VN100 là đại diện hiện có, không phải membership lịch sử.",
            "Corporate actions và trạng thái hủy niêm yết/tạm ngừng chỉ được kiểm tra trong phạm vi dữ liệu hiện có.",
            "Đây là chapter cảnh báo/phòng thủ, không phải hệ thống bán khống cổ phiếu cơ sở.",
        ],
        "liquidity_group_title": "Thanh khoản",
        "regime_group_title": "Bối cảnh",
        "market_group_title": "Nhóm cổ phiếu",
        "failure_structure_label": "Neckline yếu hoặc mẫu kéo dài",
        "failure_structure_note": "Khi neckline không rõ hoặc mẫu kéo quá dài, hai đỉnh dễ mất tính cảnh báo gọn.",
    }


TOP_VARIANT_OVERRIDES = {
    "AA": {
        "title": "Hai đỉnh Adam & Adam",
        "subtitle": "Hai đỉnh hẹp, nhọn và xác nhận bằng neckline",
        "publication_spec_id": "double_tops_adam_adam_publication_spec_v1",
        "variant_label": "Adam & Adam",
        "source_chapter": 17,
        "variant_rule_id": "variant-filter",
        "variant_required_phrase": "Hai đỉnh Adam & Adam",
        "morphology_sentence": "Hai đỉnh Adam & Adam có hai đỉnh đều hẹp hoặc nhọn, thường giống hai lần kéo lên nhanh quanh cùng một vùng kháng cự.",
        "how_subtitle": "Hai lần kéo lên cùng vùng giá, rồi xác nhận khi rơi dưới neckline",
        "summary_paragraphs": [
            "Adam & Adam là biến thể hai đỉnh có cả hai đỉnh đều hẹp hoặc nhọn. Cách đọc quan trọng nhất là không xem hai spike là mẫu hợp lệ cho tới khi giá đóng cửa dưới neckline.",
            "Trong bản Việt Nam, chương này được đọc như hồ sơ cảnh báo/phòng thủ. Mục tiêu là mô tả rủi ro hậu phá vỡ xuống, không mặc định thành chiến lược bán khống cổ phiếu cơ sở.",
        ],
        "tour_paragraphs": [
            "Biến thể Adam & Adam thường có cảm giác sắc và nhanh hơn các biến thể có Eve. Hai đỉnh giống hai lần thị trường kéo lên vùng kháng cự rồi bị từ chối.",
            "Điểm dễ sai là nhìn hai đỉnh nhọn rồi kết luận quá sớm. Theo tinh thần Bulkowski, confirmation line mới là mốc biến cấu trúc thành mẫu đã xác nhận.",
        ],
        "identification_paragraphs": [
            "Tìm một nhịp tăng trước mẫu, sau đó là đỉnh Adam thứ nhất, rơi xuống neckline, rồi đỉnh Adam thứ hai gần vùng giá đỉnh đầu.",
            "Hai đỉnh Adam cần hẹp hoặc nhọn. Nếu một đỉnh rộng và tròn hơn, mẫu có thể thuộc Adam & Eve hoặc Eve & Adam.",
            "Mẫu chỉ được tính khi giá đóng cửa dưới neckline sau đỉnh thứ hai.",
        ],
        "rule_first_note": "Adam & Adam là biến thể sắc: hình thái hai đỉnh quan trọng, nhưng xác nhận neckline mới quyết định thời điểm đo kết quả.",
        "conclusion_bullets": [
            "Adam & Adam nên được đọc như biến thể hai đỉnh nhọn, không phải toàn bộ họ Double Top.",
            "Mốc 0,5x giúp đọc mức giảm thực dụng; mốc 1,0x giữ vai trò measure-rule đầy đủ.",
            "Nếu hai đỉnh không thật sự hẹp/nhọn hoặc chưa rơi dưới neckline, không dùng mẫu để suy luận hậu phá vỡ.",
        ],
        "public_required_phrases": ["Hai đỉnh Adam & Adam", "hai đỉnh đều hẹp hoặc nhọn", "đóng cửa dưới neckline"],
    },
    "AE": {
        "title": "Hai đỉnh Adam & Eve",
        "subtitle": "Đỉnh trái nhọn, đỉnh phải rộng hơn và xác nhận bằng neckline",
        "publication_spec_id": "double_tops_adam_eve_publication_spec_v1",
        "variant_label": "Adam & Eve",
        "source_chapter": 18,
        "variant_rule_id": "variant-filter",
        "variant_required_phrase": "Hai đỉnh Adam & Eve",
        "morphology_sentence": "Hai đỉnh Adam & Eve có đỉnh trái hẹp hoặc nhọn, đỉnh phải rộng và tròn hơn, rồi xác nhận khi giá đóng cửa dưới neckline.",
        "how_subtitle": "Đỉnh trái là cú kéo lên nhanh; đỉnh phải là vùng phân phối rộng hơn",
        "summary_paragraphs": [
            "Adam & Eve là biến thể hai đỉnh trong đó đỉnh trái là Adam - hẹp, nhọn hoặc giống một cú kéo lên nhanh - còn đỉnh phải là Eve - rộng và tròn hơn.",
            "Chương này chỉ đo các mẫu đã rơi dưới neckline. Vai trò của nó là mô tả rủi ro hậu phá vỡ xuống trong dữ liệu Việt Nam hiện có.",
        ],
        "tour_paragraphs": [
            "Sau cú kéo lên nhanh đầu tiên, thị trường quay lại vùng kháng cự nhưng mất nhiều thời gian hơn để tạo đỉnh phải.",
            "Vì đỉnh Eve rộng hơn, người đọc dễ nhầm mẫu với một vùng phân phối nhỏ. Do đó neckline và nhịp rơi tối thiểu xuống neckline là hai cổng nhận diện quan trọng.",
        ],
        "identification_paragraphs": [
            "Tìm một nhịp tăng trước mẫu, sau đó là đỉnh trái Adam hẹp hoặc nhọn.",
            "Giá phải rơi xuống neckline đủ rõ rồi quay lại tạo đỉnh phải Eve rộng hơn, tròn hơn hoặc có nhiều điểm chạm ngắn quanh vùng đỉnh.",
            "Mẫu chỉ được xác nhận khi giá đóng cửa dưới neckline; trước đó, nó chỉ là ứng viên hai đỉnh.",
        ],
        "rule_first_note": "Adam & Eve phải giữ đúng thứ tự: Adam ở bên trái, Eve ở bên phải. Nếu thứ tự đảo ngược, đó là biến thể khác.",
        "conclusion_bullets": [
            "Adam & Eve là biến thể riêng, không phải Double Top tổng quát.",
            "Đỉnh phải Eve giúp mô tả quá trình phân phối kéo dài hơn, nhưng kết quả vẫn phải đọc qua target, failure và bật ngược.",
            "Mốc 0,5x là mốc thực dụng; mốc 1,0x là measure-rule đầy đủ để so sánh.",
        ],
        "public_required_phrases": ["Hai đỉnh Adam & Eve", "đỉnh trái hẹp hoặc nhọn", "đỉnh phải rộng và tròn hơn", "đóng cửa dưới neckline"],
    },
    "EA": {
        "title": "Hai đỉnh Eve & Adam",
        "subtitle": "Đỉnh trái rộng hơn, đỉnh phải nhọn hơn và xác nhận bằng neckline",
        "publication_spec_id": "double_tops_eve_adam_publication_spec_v1",
        "variant_label": "Eve & Adam",
        "source_chapter": 19,
        "variant_rule_id": "variant-filter",
        "variant_required_phrase": "Hai đỉnh Eve & Adam",
        "morphology_sentence": "Hai đỉnh Eve & Adam có đỉnh trái rộng hoặc tròn hơn, đỉnh phải hẹp hoặc nhọn hơn, rồi xác nhận khi giá đóng cửa dưới neckline.",
        "how_subtitle": "Đỉnh trái là vùng phân phối rộng; đỉnh phải là cú kéo lên nhanh hơn trước xác nhận",
        "summary_paragraphs": [
            "Eve & Adam là biến thể hai đỉnh trong đó đỉnh trái là Eve - rộng, tròn hoặc kéo dài hơn - còn đỉnh phải là Adam - hẹp, nhọn hoặc giống một cú kéo lên nhanh.",
            "Chương này chỉ đo các mẫu đã rơi dưới neckline và được đọc như hồ sơ cảnh báo/phòng thủ trong dữ liệu Việt Nam hiện có.",
        ],
        "tour_paragraphs": [
            "Câu chuyện của Eve & Adam thường bắt đầu bằng một vùng tạo đỉnh rộng hơn. Sau đó thị trường quay lại vùng kháng cự bằng một đỉnh phải sắc hơn trước khi xác nhận neckline.",
            "Thứ tự hình thái là điều kiện cứng: Eve ở trái, Adam ở phải.",
        ],
        "identification_paragraphs": [
            "Tìm một nhịp tăng trước mẫu, sau đó là đỉnh trái Eve rộng hoặc tròn hơn.",
            "Giá phải rơi xuống neckline đủ rõ rồi quay lại tạo đỉnh phải Adam hẹp hơn, nhọn hơn hoặc có phản ứng rơi xuống nhanh hơn.",
            "Mẫu chỉ được xác nhận khi giá đóng cửa dưới neckline; trước đó, nó chỉ là ứng viên hai đỉnh.",
        ],
        "rule_first_note": "Eve & Adam phải giữ đúng thứ tự: Eve ở bên trái, Adam ở bên phải. Nếu thứ tự đảo ngược, đó là Adam & Eve.",
        "conclusion_bullets": [
            "Eve & Adam là biến thể riêng, không phải Double Top tổng quát.",
            "Đỉnh trái Eve mô tả giai đoạn phân phối rộng hơn; đỉnh phải Adam mô tả cú kiểm định nhanh trước xác nhận.",
            "Mốc 0,5x là mốc thực dụng; mốc 1,0x là measure-rule đầy đủ để so sánh.",
        ],
        "public_required_phrases": ["Hai đỉnh Eve & Adam", "đỉnh trái rộng hoặc tròn hơn", "đỉnh phải hẹp hoặc nhọn hơn", "đóng cửa dưới neckline"],
    },
    "EE": {
        "title": "Hai đỉnh Eve & Eve",
        "subtitle": "Hai đỉnh rộng hơn, tròn hơn và xác nhận bằng neckline",
        "publication_spec_id": "double_tops_eve_eve_publication_spec_v1",
        "variant_label": "Eve & Eve",
        "source_chapter": 20,
        "variant_rule_id": "variant-filter",
        "variant_required_phrase": "Hai đỉnh Eve & Eve",
        "morphology_sentence": "Hai đỉnh Eve & Eve có cả hai đỉnh đều rộng hoặc tròn hơn, rồi xác nhận khi giá đóng cửa dưới neckline.",
        "how_subtitle": "Hai vùng kiểm định kháng cự rộng hơn trước khi rơi dưới neckline",
        "summary_paragraphs": [
            "Eve & Eve là biến thể hai đỉnh trong đó cả hai đỉnh đều rộng, tròn hoặc kéo dài hơn đỉnh Adam.",
            "Chương này đo riêng các mẫu Eve & Eve đã rơi dưới neckline. Với dữ liệu hiện tại, mẫu này cần cổng sample-depth rất chặt trước khi gọi final.",
        ],
        "tour_paragraphs": [
            "Eve & Eve thường có cảm giác chậm và rộng hơn Adam & Adam. Thay vì hai cú kéo sắc, người đọc nhìn thấy hai vùng kiểm định kháng cự có độ tròn hoặc độ kéo dài rõ hơn.",
            "Vì hai đỉnh đều rộng, mẫu dễ bị nhầm với một vùng phân phối. Do đó neckline, nhịp rơi tối thiểu và xác nhận đóng cửa là ba cổng quan trọng.",
        ],
        "identification_paragraphs": [
            "Tìm một nhịp tăng trước mẫu, sau đó là đỉnh Eve thứ nhất rộng hoặc tròn hơn.",
            "Giá rơi xuống neckline rồi quay lại tạo đỉnh Eve thứ hai, cũng rộng hoặc tròn hơn thay vì chỉ là một spike hẹp.",
            "Mẫu chỉ được xác nhận khi giá đóng cửa dưới neckline; trước đó, nó chỉ là ứng viên hai đỉnh.",
        ],
        "rule_first_note": "Eve & Eve phải có cả hai đỉnh thuộc nhóm Eve. Nếu một đỉnh quá hẹp hoặc quá nhọn, mẫu có thể thuộc biến thể Adam/Eve khác.",
        "conclusion_bullets": [
            "Eve & Eve là biến thể hai đỉnh rộng hơn, thường cần đọc thận trọng hơn vì dễ hòa vào vùng phân phối.",
            "Xác nhận neckline là điều kiện bắt buộc trước khi đo hậu phá vỡ.",
            "Mốc 0,5x là mốc thực dụng; mốc 1,0x là measure-rule đầy đủ để so sánh.",
        ],
        "public_required_phrases": ["Hai đỉnh Eve & Eve", "cả hai đỉnh đều rộng hoặc tròn hơn", "đóng cửa dưới neckline"],
    },
}


def build_double_top_variant_publication_spec(variant: str, *, n_events: int) -> dict[str, Any]:
    if variant not in TOP_VARIANT_OVERRIDES:
        raise ValueError(f"Unsupported Double Top variant: {variant}")
    overrides = TOP_VARIANT_OVERRIDES[variant]
    story = _top_base_story_spec()
    story.update({key: deepcopy(value) for key, value in overrides.items() if key not in {"publication_spec_id", "source_chapter", "variant_label", "variant_required_phrase", "public_required_phrases"}})
    story["classification_sentence"] = (
        f"{overrides['title']} là chương biến thể riêng, dựa trên {n_events} mẫu bám sát nguồn gốc và đủ dữ liệu đường giá."
    )
    story["headline_scope"] = (
        f"Kết luận chính chỉ áp dụng cho biến thể {overrides['variant_label']} đã xác nhận bằng neckline."
    )
    story["quick_question_rows"] = [
        ["Đây là chương gì?", f"Biến thể {overrides['variant_label']} của mẫu Hai đỉnh."],
        ["Có gộp với biến thể khác không?", "Không. Mỗi biến thể Adam/Eve có chương và thống kê riêng."],
        ["Khi nào mẫu được tính?", "Chỉ sau khi giá đóng cửa dưới neckline."],
    ]
    story["source_rule_ids"] = [
        "dt.prior_trend.upward",
        "dt.valley_depth.meaningful",
        "dt.top_similarity.close_prices",
        "dt.top_separation.few_weeks",
        "dt.confirmation.close_below_lowest_low",
        str(overrides["variant_rule_id"]),
    ]
    return {
        "status": "PASS",
        "semantic_gate_id": PUBLICATION_SEMANTIC_GATE_ID,
        "publication_spec_id": overrides["publication_spec_id"],
        "pattern_id": f"double_tops_{ {'AA': 'adam_adam', 'AE': 'adam_eve', 'EA': 'eve_adam', 'EE': 'eve_eve'}[variant] }",
        "family": "double_pattern_family",
        "source_chapter": overrides["source_chapter"],
        "spec_scope": "pattern_variant",
        "variant_specific": True,
        "variant": variant,
        "public_required_phrases": list(overrides["public_required_phrases"]),
        "public_forbidden_terms": list(TOP_FORBIDDEN_TERMS),
        "story_spec": story,
    }
