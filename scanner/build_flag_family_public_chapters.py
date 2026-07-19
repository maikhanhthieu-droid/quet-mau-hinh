"""Build the DB-active Flag Family public chapters as one release bundle."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.build_bull_flag_publication_chapter import build_publication_payload  # noqa: E402
from scanner.canonical_example_charts import build_canonical_example_charts  # noqa: E402
from scanner.flag_family_public_chapter_factory import FACTORY_ID, build_flag_public_chapter  # noqa: E402
from scanner.publication_example_support import load_public_editorial_sections  # noqa: E402


DEFAULT_PRICE_DB = Path("../market_cache/stock_ohlcv/latest.sqlite")
DEFAULT_OUT_DIR = Path("artifacts/scanner_v2/flag_family_public_chapters")
DEFAULT_BULL_STATS = Path("artifacts/scanner_v2/bull_flags_db_source_parity/db_active/statistics.json")
DEFAULT_BULL_EVENTS = Path("artifacts/scanner_v2/bull_flags_db_source_parity/db_active/events.csv")
DEFAULT_BULL_PATH = Path("artifacts/scanner_v2/bull_flags_db_source_parity/db_active/post_breakout_path.csv")
DEFAULT_BULL_AI = Path("artifacts/scanner_v2/source_guided_refinement_final_v1/flag_family/bull_flag/ai/refined/approved_ai_sections.json")
DEFAULT_BULL_SOURCE_NOTES = Path("artifacts/scanner_v2/bull_flags_source_grounding/bull_flag_source_notes.json")
DEFAULT_BEAR_STATS = Path("artifacts/scanner_v2/bear_flags_db_source_parity/db_active/statistics.json")
DEFAULT_BEAR_EVENTS = Path("artifacts/scanner_v2/bear_flags_db_source_parity/db_active/events.csv")
DEFAULT_BEAR_PATH = Path("artifacts/scanner_v2/bear_flags_db_source_parity/db_active/post_breakout_path.csv")
DEFAULT_BEAR_AI = Path("artifacts/scanner_v2/source_guided_refinement_final_v1/flag_family/bear_flag/ai/refined/approved_ai_sections.json")
DEFAULT_BEAR_SOURCE_NOTES = Path("artifacts/scanner_v2/bear_flags_source_grounding/bear_flag_source_notes.json")


def _read_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _normalize_public_text(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("–", "-").replace("—", "-").replace("‑", "-")
    if isinstance(value, list):
        return [_normalize_public_text(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_public_text(item) for key, item in value.items()}
    return value


def _pdf_info(path: Path) -> dict[str, Any]:
    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return {"path": str(path), "pages": len(reader.pages), "chars": len(text), "size_bytes": path.stat().st_size}


def _draw_flag_schematic(path: Path, *, direction: str) -> None:
    if direction == "up":
        x = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.4, 8.4])
        y = np.array([12.0, 16.0, 23.0, 31.0, 29.0, 30.0, 28.0, 33.0, 36.0])
        title = "Giải phẫu mẫu cờ tăng"
        pole_label = "cột cờ tăng"
        body_label = "thân cờ nghỉ ngắn"
        breakout_label = "phá vỡ lên"
        target_label = "mục tiêu cơ sở 0,46 lần chiều cao cột cờ"
        breakout_y = 33.0
        target_y = 36.0
        pole_xy, pole_text = (2.15, 23.0), (0.6, 27.0)
        body_xy, body_text = (5.1, 29.2), (4.25, 24.0)
        breakout_xy, breakout_text = (7.4, 33.0), (6.5, 37.0)
        target_text_y = 36.6
    else:
        x = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.4, 8.4])
        y = np.array([32.0, 29.0, 24.0, 17.0, 19.0, 18.0, 20.0, 15.0, 12.0])
        title = "Giải phẫu mẫu cờ giảm"
        pole_label = "cột cờ giảm"
        body_label = "thân cờ hồi ngắn"
        breakout_label = "phá vỡ xuống"
        target_label = "mục tiêu cơ sở 0,46 lần chiều cao cột cờ"
        breakout_y = 15.0
        target_y = 12.0
        pole_xy, pole_text = (2.2, 22.0), (0.7, 18.0)
        body_xy, body_text = (5.0, 19.0), (4.3, 25.0)
        breakout_xy, breakout_text = (7.4, 15.0), (6.5, 10.0)
        target_text_y = 11.2

    fig, ax = plt.subplots(figsize=(9.2, 3.9), dpi=180)
    ax.plot(x, y, color="#173b3a", linewidth=2.0)
    ax.scatter(x, y, s=22, color="#173b3a")
    ax.axvspan(3.85, 6.15, color="#1f77b4", alpha=0.11)
    ax.annotate(pole_label, xy=pole_xy, xytext=pole_text, arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
    ax.annotate(body_label, xy=body_xy, xytext=body_text, arrowprops={"arrowstyle": "->", "color": "#555555"}, fontsize=9)
    ax.annotate(breakout_label, xy=breakout_xy, xytext=breakout_text, arrowprops={"arrowstyle": "->", "color": "#6f4aa8"}, color="#6f4aa8", fontsize=9)
    ax.axhline(breakout_y, color="#6f4aa8", linestyle="--", linewidth=0.9)
    ax.axhline(target_y, color="#e98b2a", linestyle="--", linewidth=0.9)
    ax.text(0, target_text_y, target_label, color="#e98b2a", fontsize=8)
    ax.set_title(title, loc="left", fontsize=10)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)


def _target_row(stats: Mapping[str, Any], label: str, multiple: float = 0.46) -> Mapping[str, Any]:
    for row in stats.get("target_family_sensitivity") or []:
        if row.get("label") == label and float(row.get("target_multiple") or -1) == float(multiple):
            return row
    return {}


def _rule_text_map(direction: str) -> dict[str, str]:
    if direction == "up":
        return {
            "Steep, quick price trend": "Xu hướng giá nhanh và dốc",
            "Price action bounded by two parallel trend lines.": "Giá nằm trong hai đường xu hướng gần song song.",
            "Flags are short, from a few days to 3 weeks.": "Thân cờ ngắn, từ vài ngày đến khoảng ba tuần.",
            "They rise in a down-trend and fall in an uptrend": "Cờ tăng thường nghỉ ngang hoặc nghiêng xuống nhẹ trong một xu hướng tăng.",
            "price closes outside the flag trend line": "Giá đóng cửa ra ngoài đường xu hướng của thân cờ.",
            "Volume usually trends downward throughout the formation.": "Khối lượng thường giảm trong quá trình hình thành mẫu.",
            "Calculate the price difference between the start of the trend and the formation.": "Đo chiều cao cột cờ từ điểm bắt đầu nhịp tăng tới vùng hình thành thân cờ.",
            "If you do not have a strong advance or decline leading to the chart pattern, ignore the flag.": "Nếu không có nhịp tăng mạnh dẫn vào mẫu, hãy bỏ qua cờ.",
            "Require a steep, quick advance before a Bull Flag formation.": "Yêu cầu một nhịp tăng nhanh và dốc trước khi thân cờ hình thành.",
            "Require the flag body to fit a short channel bounded by approximately parallel trendlines.": "Yêu cầu thân cờ nằm trong một kênh ngắn với hai đường biên gần song song.",
            "Reject formations that last longer than three trading weeks.": "Loại các thân cờ kéo dài quá khoảng ba tuần giao dịch.",
            "Confirm a Bull Flag only when price closes above the upper flag trendline.": "Chỉ xác nhận cờ tăng khi giá đóng cửa trên đường biên trên của thân cờ.",
            "Record falling volume during the flag as a context feature, but do not make it a hard gate.": "Ghi nhận khối lượng giảm như một biến bối cảnh, nhưng không dùng làm điều kiện loại trực tiếp.",
            "Compute the legacy pole-height measure rule from the start of the prior advance to the flag formation, then keep fractional targets as Vietnam calibration bands.": "Đo chiều cao cột cờ từ điểm bắt đầu nhịp tăng tới vùng thân cờ, rồi dùng các mức mục tiêu phân đoạn cho thị trường Việt Nam.",
        }
    return {
        "Steep, quick price trend": "Xu hướng giá nhanh và dốc",
        "Price action bounded by two parallel trend lines.": "Giá nằm trong hai đường xu hướng gần song song.",
        "Flags are short, from a few days to 3 weeks.": "Cờ là mẫu ngắn, từ vài ngày đến khoảng ba tuần.",
        "They rise in a down-trend and fall in an uptrend": "Cờ giảm thường hồi ngang hoặc nghiêng lên nhẹ trong một xu hướng giảm.",
        "price closes outside the flag trend line": "Giá đóng cửa ra ngoài đường xu hướng của thân cờ.",
        "Volume usually trends downward throughout the formation.": "Khối lượng thường giảm trong quá trình hình thành mẫu.",
        "Calculate the price difference between the start of the trend and the formation.": "Đo chiều cao cột cờ từ điểm bắt đầu nhịp giảm tới vùng hình thành thân cờ.",
        "If you do not have a strong advance or decline leading to the chart pattern, ignore the flag.": "Nếu không có nhịp giảm mạnh dẫn vào mẫu, hãy bỏ qua cờ.",
        "Require a steep, quick decline before a Bear Flag formation.": "Yêu cầu một nhịp giảm nhanh và dốc trước khi thân cờ hình thành.",
        "Require the bear flag body to fit a short channel bounded by approximately parallel trendlines.": "Yêu cầu thân cờ giảm nằm trong một kênh ngắn với hai đường biên gần song song.",
        "Reject bear flag formations that last longer than three trading weeks.": "Loại các thân cờ giảm kéo dài quá khoảng ba tuần giao dịch.",
        "For Bear Flags, the flag body should drift sideways to upward against the prior decline.": "Với cờ giảm, thân cờ nên hồi ngang hoặc nghiêng lên nhẹ, ngược hướng với nhịp giảm trước đó.",
        "Confirm a Bear Flag only when price closes below the lower flag trendline.": "Chỉ xác nhận cờ giảm khi giá đóng cửa dưới đường biên dưới của thân cờ.",
        "Record falling volume during the bear flag as a context feature, but do not make it a hard gate.": "Ghi nhận khối lượng giảm như một biến bối cảnh, nhưng không dùng làm điều kiện loại trực tiếp.",
        "Compute the legacy pole-height measure rule from the start of the prior decline to the flag formation, then keep fractional targets as Vietnam calibration bands.": "Đo chiều cao cột cờ từ điểm bắt đầu nhịp giảm tới vùng thân cờ, rồi dùng các mức mục tiêu phân đoạn cho thị trường Việt Nam.",
        "Invalidate Bear Flag candidates that do not follow a strong decline.": "Loại ứng viên cờ giảm nếu phía trước không có nhịp giảm đủ mạnh.",
    }


def _bull_spec() -> dict[str, Any]:
    return {
        "title": "Cờ tăng",
        "subtitle": "Mẫu tiếp diễn ngắn sau một nhịp tăng mạnh",
        "morphology_sentence": "Mẫu tiếp diễn ngắn: cột cờ tăng mạnh, thân cờ nghỉ hẹp, xác nhận bằng giá đóng cửa phá lên.",
        "role_note": "Dùng như hồ sơ tham khảo hậu phá vỡ, không phải tài liệu tham khảo tự động.",
        "classification_sentence": "Trong phạm vi dữ liệu hiện có, cờ tăng là ứng viên tham khảo đầu tư tốt nhất của Flag Family.",
        "schematic_caption": "Sơ đồ minh họa cấu trúc: cột cờ đi lên, thân cờ ngắn, phiên phá vỡ và mục tiêu cơ sở.",
        "how_subtitle": "Tour ngắn trước khi đi vào quy tắc nhận diện",
        "labels": {"favorable_move": "mức tăng tốt nhất", "adverse_move": "mức kéo ngược sâu nhất"},
        "source_rule_ids": ["bf.prior_trend.steep_up", "bf.shape.parallel_channel", "bf.duration.max_three_weeks", "bf.countertrend.drift", "bf.breakout.close_above_trendline", "bf.volume.downward_context"],
        "rule_text_map": _rule_text_map("up"),
        "public_rule_rows": [
            ["Phải có nhịp tăng dẫn trước đủ mạnh.", "Cờ tăng là mẫu tiếp diễn; nếu đoạn trước chỉ đi ngang, thân cờ phía sau không còn nhiều ý nghĩa."],
            ["Thân cờ phải là đoạn nghỉ ngắn trong kênh hẹp.", "Các đỉnh và đáy của thân cờ cần tạo hai đường biên tương đối song song; mẫu quá rộng hoặc quá dài bị hạ chất lượng."],
            ["Thân cờ thường đi ngang hoặc nghiêng xuống nhẹ.", "Đây là pha nghỉ ngược nhẹ với xu hướng trước đó; nếu tiếp tục tăng một mạch, mẫu không còn là cờ."],
            ["Chỉ xác nhận khi giá đóng cửa phá lên khỏi thân cờ.", "Không đo kết quả trước phiên xác nhận; xuyên biên trong phiên nhưng đóng cửa yếu chưa đủ."],
            ["Khối lượng là bối cảnh phụ.", "Khối lượng giảm trong thân cờ giúp mẫu dễ tin hơn, nhưng không thay thế hình thái và xác nhận phá vỡ."],
            ["Mục tiêu đo từ chiều cao cột cờ.", "0,46x-0,50x là mốc cơ sở; 0,75x và 1,0x là các mốc mở rộng để so sánh."],
        ],
        "quick_question_rows": [
            ["Cột cờ", "Nhịp tăng trước đó có đủ nhanh, đủ dốc và đủ rõ không?"],
            ["Thân cờ", "Giá có nghỉ trong một kênh ngắn, hẹp và không phá cấu trúc tăng không?"],
            ["Phá vỡ", "Giá đóng cửa có vượt lên khỏi thân cờ không?"],
            ["Đường đi sau đó", "Mục tiêu có đến trước khi giá kéo ngược sâu không?"],
        ],
        "component_rows": [
            ["Cột cờ", "Nhịp tăng nhanh trước vùng nghỉ; đây là phần quan trọng nhất.", "Nhìn lại 40 phiên; tăng tối thiểu 10%; độ dốc tối thiểu 8 độ."],
            ["Thân cờ", "Vùng nghỉ ngắn, thường nghiêng nhẹ ngược hướng tăng trước đó.", "Dài 5-25 phiên; cao 3-15%; thân cờ không quá 55% cột cờ."],
            ["Hai đường biên", "Giá nằm trong kênh tương đối song song.", "Sai lệch độ dốc tối đa 4 độ."],
            ["Phá vỡ", "Chỉ sau phiên xác nhận mới đo kết quả.", "Đóng cửa vượt biên trên với ngưỡng 0,75%; tìm trong 12 phiên."],
            ["Khối lượng", "Khối lượng giảm là dấu hiệu hỗ trợ, không phải điều kiện bắt buộc.", "Ghi nhận riêng, không dùng làm cổng loại trực tiếp."],
        ],
        "reject_bullets": [
            "Không có cột cờ rõ: nếu nhịp tăng trước đó yếu, mẫu chỉ là vùng đi ngang sau nhiễu giá.",
            "Thân cờ quá dài: cờ tăng là mẫu nghỉ ngắn; kéo dài quá lâu dễ chuyển thành kênh giá hoặc nền tích lũy.",
            "Phá vỡ không bằng giá đóng cửa: chỉ xuyên biên trong phiên nhưng đóng cửa yếu chưa đủ để xác nhận sự kiện.",
            "Khối lượng và đường giá bẩn: phiên không có khối lượng, thiếu phiên hoặc sự kiện quyền gần phá vỡ khiến mẫu khó tin hơn.",
        ],
        "identification_paragraphs": ["Cờ tăng chỉ có ý nghĩa khi xuất hiện sau một nhịp tăng nhanh. Phần thân cờ là đoạn nghỉ ngắn, thường hơi nghiêng xuống hoặc đi ngang, nằm trong hai đường biên tương đối song song. Mẫu chỉ được xác nhận khi giá đóng cửa vượt ra khỏi biên trên của thân cờ."],
        "example_intro": ["Ba ví dụ dưới đây đại diện cho một mẫu đạt mục tiêu, một mẫu trung vị và một mẫu thất bại. Cách chọn này giúp chương không biến thành bộ sưu tập biểu đồ đẹp."],
        "failure_bullets": ["Ví dụ thất bại không bị loại khỏi chương: nó là một phần của phân phối thật.", "Thất bại 5% khác ngưỡng rủi ro thực chiến.", "Mẫu hợp lệ vẫn có thể xấu nếu xác nhận yếu hoặc đường đi kéo ngược sâu."],
        "target_paragraph": "Mục tiêu giá của cờ tăng nên đọc theo thang 0,46x, 0,5x, 0,75x và 1,0x. Mốc 0,46x là cơ sở, còn 1,0x là mốc chạy xa.",
        "quick_conclusion_rows": [
            ["Mẫu này dùng để đọc gì?", "Một mẫu tiếp diễn ngắn sau nhịp tăng nhanh, có giá trị khi xác nhận phá lên rõ."],
            ["Mục tiêu nào nên là mốc chính?", "0,46x-0,50x chiều cao cột cờ là mốc cơ sở."],
            ["Rủi ro chính là gì?", "Giá kéo ngược sâu hoặc không đi đủ 5% sau phá vỡ."],
            ["Khi nào mẫu đáng chú ý hơn?", "Cột cờ rõ, thân cờ gọn, đường giá sạch và thanh khoản đủ tốt."],
        ],
        "caveat_bullets": ["Không claim point-in-time universe toàn thị trường.", "Không dùng historical VN30/VN100 membership làm kết luận chính.", "Corporate actions và delisted/halted hiện dùng kiểm tra thay thế, chưa phải status tape chính thức."],
        "conclusion_bullets": ["Cờ tăng là mẫu tiếp diễn ngắn có giá trị đọc hậu phá vỡ tốt nhất khi mục tiêu được hiệu chuẩn theo 0,46 lần chiều cao cột cờ.", "Mẫu không nên được đánh giá bằng một tỷ lệ đạt mục tiêu duy nhất.", "Trong phạm vi dữ liệu hiện có, cờ tăng đủ làm chương chuẩn đầu tiên của Flag Family."],
    }


def _bear_spec(branch: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "title": "Cờ giảm",
        "subtitle": "Mẫu tiếp diễn xuống dùng như tài liệu cảnh báo rủi ro",
        "morphology_sentence": "Mẫu tiếp diễn xuống: cột cờ giảm mạnh, thân cờ hồi ngắn, xác nhận bằng giá đóng cửa phá xuống.",
        "role_note": "Dùng như hồ sơ cảnh báo rủi ro sau phá vỡ xuống, không phải khuyến nghị bán khống.",
        "classification_sentence": "Cờ giảm được phân loại là tài liệu phòng thủ/thông tin, không phải tín hiệu bán khống mặc định.",
        "headline_scope": f"Nhóm điều kiện đọc chính: {branch.get('n')} mẫu, đạt 0,46x {branch.get('base_target_hit_rate')}%, thất bại {branch.get('failure_5pct_rate')}%.",
        "schematic_caption": "Sơ đồ minh họa cấu trúc: cột cờ giảm, thân cờ hồi ngắn, phiên phá vỡ xuống và mục tiêu cơ sở.",
        "how_subtitle": "Cờ giảm là nhịp nghỉ ngắn trong một xu hướng giảm",
        "labels": {"favorable_move": "mức giảm tốt nhất", "adverse_move": "mức bật ngược sâu nhất"},
        "source_rule_ids": ["brf.prior_trend.steep_down", "brf.shape.parallel_channel", "brf.duration.max_three_weeks", "brf.countertrend.drift", "brf.breakout.close_below_trendline", "brf.volume.downward_context"],
        "rule_text_map": _rule_text_map("down"),
        "public_rule_rows": [
            ["Phải có nhịp giảm dẫn trước đủ mạnh.", "Cờ giảm là mẫu tiếp diễn xuống; nếu đoạn trước chỉ đi ngang, tín hiệu cảnh báo phía sau yếu đi rõ."],
            ["Thân cờ là đoạn hồi ngắn trong kênh hẹp.", "Giá thường hồi lên hoặc đi ngang trong hai đường biên gần song song; thân quá dài dễ trở thành vùng dao động khác."],
            ["Thân cờ đi ngược nhẹ với xu hướng giảm trước đó.", "Pha hồi phải có kiểm soát; nếu bật quá mạnh, mẫu không còn là nhịp nghỉ giảm."],
            ["Chỉ xác nhận khi giá đóng cửa phá xuống khỏi thân cờ.", "Không đo kết quả trước phiên xác nhận; xuyên biên trong phiên nhưng đóng cửa yếu chưa đủ."],
            ["Khối lượng là bối cảnh phụ.", "Khối lượng hỗ trợ giúp mẫu dễ tin hơn, nhưng không thay thế hình thái rõ và phá vỡ xác nhận."],
            ["Mục tiêu đo từ chiều cao cột cờ giảm.", "0,46x-0,50x là mốc cơ sở thận trọng; 0,75x và 1,0x là mốc mở rộng để đối chiếu."],
        ],
        "quick_question_rows": [
            ["Cột cờ", "Nhịp giảm trước đó có đủ nhanh và rõ không?"],
            ["Thân cờ", "Giá có hồi ngắn trong hai đường biên gần song song không?"],
            ["Phá vỡ", "Giá đóng cửa có phá xuống dưới thân cờ không?"],
            ["Sau phá vỡ", "Giá giảm tiếp hay bật ngược đủ mạnh để phủ nhận cảnh báo?"],
        ],
        "component_rows": [
            ["Cột cờ giảm", "Nhịp giảm nhanh trước vùng hồi; đây là nguồn gốc của target family.", "Nhìn lại 40 phiên; giảm tối thiểu theo rule detector; độ dốc âm rõ."],
            ["Thân cờ hồi", "Vùng nghỉ ngắn, thường hồi lên hoặc đi ngang sau cú giảm.", "Dài 5-25 phiên; biên độ được giới hạn so với cột cờ."],
            ["Hai đường biên", "Giá nằm trong kênh tương đối song song.", "Sai lệch độ dốc bị giới hạn để tránh bắt nhầm kênh rộng."],
            ["Phá vỡ", "Chỉ sau phiên xác nhận mới đo kết quả.", "Đóng cửa phá xuống dưới biên dưới; không dùng giá tương lai để xác nhận."],
            ["Khối lượng", "Khối lượng là bối cảnh hỗ trợ, không phải cổng loại tuyệt đối.", "Ghi nhận phá vỡ volume và xu hướng volume trong thân cờ."],
        ],
        "reject_bullets": ["Không có cột cờ giảm rõ: mẫu chỉ là nhiễu hoặc kênh giảm chậm.", "Thân cờ hồi quá dài: mẫu không còn là nhịp nghỉ ngắn.", "Phá vỡ không bằng giá đóng cửa: xuyên biên trong phiên nhưng đóng cửa yếu chưa đủ xác nhận.", "Đường giá kém sạch khiến kết quả khó đọc."],
        "identification_paragraphs": ["Mẫu bắt đầu bằng một cột cờ giảm nhanh. Sau đó giá hồi hoặc đi ngang trong một kênh ngắn, thường nghiêng lên nhẹ. Sự kiện chỉ được xác nhận khi giá đóng cửa phá xuống dưới biên dưới của thân cờ."],
        "summary_paragraphs": ["Cờ giảm trong dữ liệu Việt Nam không nên được đọc như một cơ hội bán khống mặc định. Giá trị chính là nhận diện tình huống rủi ro: sau một nhịp giảm mạnh, cổ phiếu hồi ngắn trong thân cờ rồi phá xuống.", "Chương này giữ cùng cấu trúc đọc với cờ tăng: mô tả hình học mẫu, đo kết quả hậu phá vỡ, rồi mới nói cách sử dụng. Khác biệt nằm ở vai trò: cờ giảm là bản đồ phòng thủ."],
        "tour_paragraphs": ["Một lỗi phổ biến là xem mọi đoạn hồi sau giảm là cờ giảm. Cách đọc chặt hơn là hỏi liệu nhịp hồi có đủ ngắn, đủ hẹp và đủ giống một đoạn nghỉ hay không."],
        "example_intro": ["Ba ví dụ dưới đây đại diện cho một mẫu cảnh báo đúng, một mẫu trung vị và một mẫu thất bại. Với cờ giảm, ví dụ thất bại quan trọng ngang ví dụ thành công."],
        "failure_paragraphs": ["Với cờ giảm, thất bại có hai lớp: giá không giảm đủ 5% theo hướng phá vỡ, hoặc giá giảm một đoạn rồi bật ngược quá mạnh.", "Câu hỏi thực dụng là giá có giảm đủ nhanh và đủ xa trước khi bật ngược gây nhiễu hay không."],
        "failure_bullets": ["Ví dụ thất bại không bị loại khỏi chương; nó là một phần của phân phối thật.", "Thất bại 5% khác stop-loss thực chiến.", "Cờ giảm hợp lệ vẫn có thể là cảnh báo sai nếu giá bật ngược nhanh sau phá vỡ."],
        "target_paragraph": "Mục tiêu giá của cờ giảm không nên bị ép vào 1,0 lần chiều cao cột cờ. Mốc 0,46x là mục tiêu cơ sở; 1,0x là mốc chạy xa.",
        "usage_paragraphs": ["Cách dùng phù hợp nhất là phòng thủ: giảm tự tin với vị thế đang nắm giữ, kiểm tra lại luận điểm đầu tư, hoặc theo dõi rủi ro thủng vùng hỗ trợ.", "Nếu chưa nắm giữ, mẫu có thể giúp tránh mua đuổi trong một nhịp hồi yếu."],
        "checklist": ["Có cột cờ giảm đủ rõ trước thân cờ.", "Thân cờ hồi ngắn, không quá rộng và không kéo dài.", "Chỉ xác nhận khi giá đóng cửa phá xuống.", "Đọc 0,46x-0,5x là mục tiêu cơ sở; 1,0x là mốc căng.", "Không diễn giải thành khuyến nghị bán khống nếu chưa có lớp thực thi riêng."],
        "quick_conclusion_rows": [
            ["Mẫu này dùng để đọc gì?", "Một cảnh báo phòng thủ sau nhịp giảm mạnh: giá hồi ngắn rồi phá xuống."],
            ["Mục tiêu nào nên là mốc chính?", "0,46x-0,50x chiều cao cột cờ là mốc cơ sở."],
            ["Rủi ro chính là gì?", "Giá bật ngược sâu hoặc không giảm đủ 5% sau phá vỡ."],
            ["Khi nào mẫu đáng chú ý hơn?", "Cột cờ giảm rõ, thân cờ ngắn, phá vỡ đóng cửa dứt khoát và đường giá sạch."],
        ],
        "caveat_bullets": ["Không claim point-in-time universe toàn thị trường.", "Không dùng historical VN30/VN100 membership làm kết luận chính.", "Corporate actions và delisted/halted hiện dùng kiểm tra thay thế, chưa phải status tape chính thức."],
        "conclusion_bullets": ["Cờ giảm là tài liệu phòng thủ/thông tin: hữu ích để đọc rủi ro sau một nhịp hồi yếu.", "Mục tiêu cơ sở nên là 0,46x-0,50x chiều cao cột cờ; 1,00x chỉ là mốc chạy xa.", "Chương không được đọc như khuyến nghị bán khống trên cổ phiếu cơ sở Việt Nam."],
    }


def _chapter_summary(pattern_id: str, chapter_dir: Path, stats_path: Path) -> dict[str, Any]:
    stats = _read_json(stats_path)
    if pattern_id == "bull_flags":
        base = _target_row(stats, "bull_flags")
        return {
            "pattern_id": pattern_id,
            "chapter_label": "Cờ tăng",
            "classification": "investment-reference candidate under available-series scope",
            "pdf": _pdf_info(chapter_dir / "bull_flag_public_chapter.pdf"),
            "all_n": stats.get("detection_count"),
            "symbols_scanned": stats.get("symbols_scanned"),
            "headline_n": base.get("n"),
            "base_target_hit_rate": base.get("target_hit_rate"),
            "target_first_before_adverse_5pct_rate": base.get("target_first_before_adverse_5pct_rate"),
            "failure_5pct_rate": base.get("failure_5pct_rate"),
            "mfe_mae_median_ratio": base.get("mfe_mae_median_ratio"),
        }
    branch = stats.get("bear_branch_headline") if isinstance(stats.get("bear_branch_headline"), Mapping) else {}
    base = _target_row(stats, "bear_flags")
    return {
        "pattern_id": pattern_id,
        "chapter_label": "Cờ giảm",
        "classification": "defensive/informational-reference candidate under available-series scope",
        "pdf": _pdf_info(chapter_dir / "bear_flag_public_chapter.pdf"),
        "all_n": stats.get("detection_count"),
        "symbols_scanned": stats.get("symbols_scanned"),
        "headline_scope": branch.get("aggregate_id") or branch.get("branch_id"),
        "headline_n": branch.get("n"),
        "base_target_hit_rate": branch.get("base_target_hit_rate"),
        "target_first_before_adverse_5pct_rate": branch.get("base_target_first_before_adverse_5pct_rate"),
        "failure_5pct_rate": branch.get("failure_5pct_rate"),
        "mfe_mae_median_ratio": branch.get("mfe_mae_median_ratio"),
        "full_sample_base_target_hit_rate": base.get("target_hit_rate"),
    }


def _target_rows_for_label(stats: Mapping[str, Any], label: str) -> list[dict[str, Any]]:
    return [dict(row) for row in stats.get("target_family_sensitivity") or [] if isinstance(row, Mapping) and row.get("label") == label]


def _build_bear_publication_payload(stats: Mapping[str, Any], events: pd.DataFrame) -> dict[str, Any]:
    branch = stats.get("bear_branch_headline") if isinstance(stats.get("bear_branch_headline"), Mapping) else {}
    full_rows = _target_rows_for_label(stats, "bear_flags")
    full_base = _target_row(stats, "bear_flags", 0.46)
    legacy = _target_row(stats, "bear_flags", 1.0)
    branch_base = {
        "label": "bear_flags:headline_branch",
        "target_multiple": 0.46,
        "target_role": "headline_branch_base",
        "n": branch.get("n"),
        "target_hit_rate": branch.get("base_target_hit_rate"),
        "target_first_before_adverse_5pct_rate": branch.get("base_target_first_before_adverse_5pct_rate"),
        "failure_5pct_rate": branch.get("failure_5pct_rate"),
        "mfe_mae_median_ratio": branch.get("mfe_mae_median_ratio"),
    }
    rows = [branch_base, *full_rows]
    return {
        "publication_id": "bear_flag_publication_chapter_v1",
        "status": "PASS",
        "classification": "defensive/informational-reference candidate under available-series scope",
        "chapter_reference": {
            "symbols_scanned": stats.get("symbols_scanned"),
            "events": stats.get("detection_count"),
            "evaluated_events": stats.get("evaluated_count") or stats.get("detection_count"),
            "median_mfe_pct": stats.get("median_mfe_pct"),
            "median_mae_pct": stats.get("median_mae_pct"),
            "mfe_mae_median_ratio": full_base.get("mfe_mae_median_ratio"),
            "failure_5pct_rate": stats.get("failure_5pct_rate"),
            "legacy_target_hit_rate": legacy.get("target_hit_rate"),
            "legacy_target_first_before_adverse_5pct_rate": legacy.get("target_first_before_adverse_5pct_rate"),
            "liquidity_proxy_table": stats.get("liquidity_proxy_table"),
            "regime_proxy_table": stats.get("regime_proxy_table"),
            "path_quality_audit": stats.get("path_quality_audit"),
        },
        "target_calibration": {
            "target_family": stats.get("target_family"),
            "selected_base_target_multiple": 0.46,
            "selected_base_target_role": "headline_branch_base",
            "base_target": branch_base,
            "legacy_target": legacy,
            "rows": rows,
            "interpretation": "Bear Flag uses headline branch metrics for the public main claim and full-sample rows for appendix/reference.",
        },
        "editorial_sections": {
            "summary": [
                "Cờ giảm trong dữ liệu Việt Nam không nên được đọc như một cơ hội bán khống mặc định. Giá trị chính là nhận diện tình huống rủi ro: sau một nhịp giảm mạnh, cổ phiếu hồi ngắn trong thân cờ rồi phá xuống.",
                "Chương này giữ cùng cấu trúc đọc với cờ tăng: mô tả hình học mẫu, đo kết quả hậu phá vỡ, rồi mới nói cách sử dụng. Khác biệt nằm ở vai trò: cờ giảm là bản đồ phòng thủ.",
            ],
            "tour": [
                "Cờ giảm là nhịp nghỉ ngắn trong một xu hướng giảm. Mẫu bắt đầu bằng một cột cờ giảm nhanh, sau đó giá hồi hoặc đi ngang trong một kênh ngắn trước khi phá vỡ xuống.",
                "Một lỗi phổ biến là xem mọi đoạn hồi sau giảm là cờ giảm. Nếu thân cờ quá dài, quá rộng hoặc thiếu cột cờ giảm rõ phía trước, mẫu nên bị hạ cấp thành kênh hồi hoặc vùng dao động.",
            ],
            "failure": [
                "Với cờ giảm, thất bại có hai lớp: giá không giảm đủ 5% theo hướng phá vỡ, hoặc giá giảm một đoạn rồi bật ngược quá mạnh.",
                "Câu hỏi thực dụng là giá có giảm đủ nhanh và đủ xa trước khi bật ngược gây nhiễu hay không.",
            ],
            "statistics": [
                "Cờ giảm không nên được đánh giá bằng toàn mẫu global duy nhất. Toàn mẫu cho biết bức tranh rủi ro rộng, còn nhánh chính cho biết nhóm có điều kiện đọc tốt hơn.",
                "Các bảng phân vị giúp tránh đọc quá tay từ một vài ví dụ mạnh; với cờ giảm, mức bật ngược sâu nhất là biến phải đặt cạnh mức giảm tốt nhất.",
            ],
            "post_breakout": [
                "Sau phá vỡ, cờ giảm phải được đọc bằng đường đi chứ không chỉ bằng cực trị. Một mẫu có thể chạm mục tiêu nhưng trước đó đã bật ngược sâu.",
                "Target-first-before-adverse được đặt cạnh target-hit vì nó giữ lại thứ tự đường đi, điều mà tỷ lệ hit cuối kỳ không thể hiện được.",
            ],
            "size_volume": [
                "Cờ giảm nhạy với kích thước thân cờ và khối lượng. Thân cờ càng rộng, nguy cơ bật ngược càng lớn; khối lượng không xác nhận có thể làm phiên phá vỡ kém tin cậy.",
                "Các lát cắt theo thanh khoản, regime và nhóm cổ phiếu không dùng để chọn lại mẫu sau khi biết kết quả; chúng mô tả nơi mẫu dễ đọc hơn hoặc khó đọc hơn.",
            ],
            "tactics": [
                "Cách dùng phù hợp nhất là phòng thủ: giảm tự tin với vị thế đang nắm giữ, kiểm tra lại luận điểm đầu tư, hoặc theo dõi rủi ro thủng vùng hỗ trợ.",
                "Nếu chưa nắm giữ, mẫu có thể giúp tránh mua đuổi trong một nhịp hồi yếu.",
            ],
            "checklist": [
                "Có cột cờ giảm đủ rõ trước thân cờ.",
                "Thân cờ hồi ngắn, không quá rộng và không kéo dài.",
                "Chỉ xác nhận khi giá đóng cửa phá xuống.",
                "Đọc 0,46x-0,5x là mục tiêu cơ sở; 1,0x là mốc căng.",
                "Không diễn giải thành khuyến nghị bán khống nếu chưa có lớp thực thi riêng.",
            ],
        },
        "branch_audit_rows": [*(stats.get("bear_branch_headline_candidates") or []), *(stats.get("bear_branch_table") or [])],
        "data_scope_and_caveats": {
            "remaining_caveats": [
                "Không claim point-in-time universe toàn thị trường.",
                "Không dùng historical VN30/VN100 membership làm kết luận chính.",
                "Corporate actions và delisted/halted hiện dùng kiểm tra thay thế, chưa phải status tape chính thức.",
            ]
        },
    }


def build_flag_family_public_chapters(
    *,
    out_dir: Path = DEFAULT_OUT_DIR,
    price_db: Path = DEFAULT_PRICE_DB,
    bull_stats: Path = DEFAULT_BULL_STATS,
    bull_events: Path = DEFAULT_BULL_EVENTS,
    bull_path: Path = DEFAULT_BULL_PATH,
    bull_ai: Path = DEFAULT_BULL_AI,
    bull_source_notes: Path = DEFAULT_BULL_SOURCE_NOTES,
    bear_stats: Path = DEFAULT_BEAR_STATS,
    bear_events: Path = DEFAULT_BEAR_EVENTS,
    bear_path: Path = DEFAULT_BEAR_PATH,
    bear_ai: Path = DEFAULT_BEAR_AI,
    bear_source_notes: Path = DEFAULT_BEAR_SOURCE_NOTES,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    bull_publication_dir = out_dir / "bull_flag_publication_payload"
    bull_dir = out_dir / "bull_flag"
    bear_dir = out_dir / "bear_flag"
    for generated_dir in [bull_publication_dir, bull_dir, bear_dir]:
        if generated_dir.exists():
            shutil.rmtree(generated_dir)

    bull_events_df = pd.read_csv(bull_events)
    bull_path_df = pd.read_csv(bull_path)
    bull_source = _read_json(bull_source_notes)
    bull_payload = build_publication_payload(stats_path=bull_stats)
    if bull_payload.get("status") != "PASS":
        raise RuntimeError(f"Bull Flag publication payload failed: {bull_payload.get('failures')}")
    external_ai = load_public_editorial_sections(bull_ai if bull_ai.exists() else None)
    bull_ai_sections = external_ai.get("sections", {}) if isinstance(external_ai.get("sections"), Mapping) else {}
    missing_bull_sections = [
        key
        for key in ("summary", "tour", "failure", "statistics", "post_breakout", "size_volume", "tactics", "checklist")
        if not bull_ai_sections.get(key)
    ]
    if missing_bull_sections:
        raise RuntimeError(f"Bull Flag approved editorial file missing sections: {', '.join(missing_bull_sections)}")
    bull_ai_sections = _normalize_public_text(bull_ai_sections)
    bull_ai_captions = _normalize_public_text(external_ai.get("captions", {})) if isinstance(external_ai.get("captions"), Mapping) else {}
    bull_schematic = bull_dir / "charts" / "bull_flag_ideal_schematic.png"
    _draw_flag_schematic(bull_schematic, direction="up")
    bull_charts, bull_examples, bull_example_report = build_canonical_example_charts(
        pattern_id="bull_flags",
        events=bull_events_df,
        existing_examples=None,
        out_dir=bull_dir / "charts",
        price_db=price_db,
        schematic=bull_schematic,
    )
    bull_payload = {
        **dict(bull_payload),
        "editorial_sections": bull_ai_sections,
        "editorial_source_path": str(bull_ai),
        "example_captions": bull_ai_captions,
        "example_events": bull_examples,
        "example_chart_report": bull_example_report,
    }
    bull_publication_dir.mkdir(parents=True, exist_ok=True)
    bull_publication_payload_path = bull_publication_dir / "bull_flag_publication_payload.json"
    bull_publication_payload_path.write_text(json.dumps(bull_payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")

    bull_paths = build_flag_public_chapter(
        payload=bull_payload,
        source_notes=bull_source,
        events=bull_events_df,
        path_df=bull_path_df,
        charts=bull_charts,
        spec=_bull_spec(),
        out_dir=bull_dir,
        pdf_filename="bull_flag_public_chapter.pdf",
        payload_filename="bull_flag_public_chapter_payload.json",
        manuscript_filename="bull_flag_ai_editorial_manuscript.md",
        notes_filename="bull_flag_public_chapter_notes.md",
    )

    bear_stats_data = _read_json(bear_stats)
    bear_events_df = pd.read_csv(bear_events)
    bear_path_df = pd.read_csv(bear_path)
    bear_source = _read_json(bear_source_notes)
    bear_payload = _build_bear_publication_payload(bear_stats_data, bear_events_df)
    bear_payload = _normalize_public_text(bear_payload)
    bear_schematic = bear_dir / "charts" / "bear_flag_ideal_schematic.png"
    _draw_flag_schematic(bear_schematic, direction="down")
    bear_charts, bear_examples, bear_example_report = build_canonical_example_charts(
        pattern_id="bear_flags",
        events=bear_events_df,
        existing_examples=None,
        out_dir=bear_dir / "charts",
        price_db=price_db,
        schematic=bear_schematic,
    )
    bear_payload = {**bear_payload, "editorial_source_path": str(bear_ai), "example_events": bear_examples, "example_chart_report": bear_example_report}
    branch = bear_stats_data.get("bear_branch_headline") if isinstance(bear_stats_data.get("bear_branch_headline"), Mapping) else {}
    bear_paths = build_flag_public_chapter(
        payload=bear_payload,
        source_notes=bear_source,
        events=bear_events_df,
        path_df=bear_path_df,
        charts=bear_charts,
        spec=_bear_spec(branch),
        out_dir=bear_dir,
        pdf_filename="bear_flag_public_chapter.pdf",
        payload_filename="bear_flag_public_chapter_payload.json",
        manuscript_filename="bear_flag_ai_editorial_manuscript.md",
        notes_filename="bear_flag_public_chapter_notes.md",
    )

    summaries = [
        _chapter_summary("bull_flags", bull_dir, bull_stats),
        _chapter_summary("bear_flags", bear_dir, bear_stats),
    ]
    manifest = {
        "release_id": "flag_family_public_chapters_db_active_v1",
        "factory_id": FACTORY_ID,
        "source_scope": "DB active symbols from Market Cache latest.sqlite; no historical VN30/VN100 membership claim; no point-in-time all-market universe claim.",
        "price_db": str(price_db),
        "chapters": summaries,
        "outputs": {
            "bull_flag": {key: str(value) for key, value in bull_paths.items()},
            "bear_flag": {key: str(value) for key, value in bear_paths.items()},
            "bull_publication_payload": {"payload": str(bull_publication_payload_path)},
        },
    }
    json_path = out_dir / "flag_family_public_chapters_manifest.json"
    md_path = out_dir / "flag_family_public_chapters_manifest.md"
    json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    lines = [
        "# Flag Family public chapters",
        "",
        f"Factory: `{FACTORY_ID}`",
        "",
        f"Source scope: {manifest['source_scope']}",
        "",
        "| Chapter | Role | PDF pages | All N | Headline N | Hit | Target-first | Failure | MFE/MAE |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in summaries:
        lines.append(
            f"| {row['chapter_label']} | {row['classification']} | {row['pdf']['pages']} | {row.get('all_n')} | {row.get('headline_n')} | {row.get('base_target_hit_rate')}% | {row.get('target_first_before_adverse_5pct_rate')}% | {row.get('failure_5pct_rate')}% | {row.get('mfe_mae_median_ratio')} |"
        )
    lines.extend(
        [
            "",
            "## Files",
            "",
            f"- Bull Flag PDF: `{bull_paths['pdf']}`",
            f"- Bear Flag PDF: `{bear_paths['pdf']}`",
            f"- Manifest JSON: `{json_path}`",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "manifest_json": json_path,
        "manifest_md": md_path,
        "bull_pdf": bull_paths["pdf"],
        "bear_pdf": bear_paths["pdf"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build DB-active Bull/Bear Flag public chapters as a family bundle.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--price-db", default=str(DEFAULT_PRICE_DB))
    args = parser.parse_args()
    paths = build_flag_family_public_chapters(out_dir=Path(args.out_dir), price_db=Path(args.price_db))
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
