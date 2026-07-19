# Bear-Trap / Cắt Lỗ Thận Trọng Layer

## Quyết định phương pháp

Nhánh `bear-trap long setup` đã bị đóng.  Dữ liệu pilot cho thấy phá vỡ giảm thất bại xuất hiện khá thường xuyên, nhưng mua theo nhịp giá quay lại vùng phá vỡ chưa đủ bền để nâng thành setup BUY hoặc `tradable-final`.

Cách dùng mới là `bear_trap_stoploss_caution_layer_v1`: đây là lớp cảnh báo khi đọc các mẫu giảm giá, đặc biệt với hành vi cắt lỗ máy móc ngay sau phiên phá vỡ giảm.  Vòng mở rộng đã chạy trên 18 chapter bearish/top/downside, bao gồm cả Descending Triangle vì đây là một chapter phá vỡ giảm quan trọng.

## Ý nghĩa thực tế

Khi một mẫu bearish phá xuống, người đọc không nên mặc định phá vỡ đó đã sạch ngay lập tức.  Nếu giá nhanh chóng đóng cửa trở lại trên vùng phá vỡ, đó là dấu hiệu phá vỡ giảm có thể là bẫy giảm hoặc tín hiệu nhiễu.

Lớp này trả lời ba câu hỏi:

| Câu hỏi | Cách đo |
|---|---|
| Phá vỡ giảm có bị quay lại vùng phá vỡ không? | Tỷ lệ đóng cửa lấy lại hỗ trợ/đường cổ/biên dưới trong 20 phiên |
| Nhịp quay lại có đến nhanh không? | Tỷ lệ quay lại vùng phá vỡ trong 5 và 10 phiên |
| Sau khi quay lại, giá có gãy lại không? | Tỷ lệ phá vỡ giảm lần hai trong 20 phiên sau nhịp quay lại |

## Artifact

Chạy:

```bash
PYTHONPATH=. python3 -m scanner.build_bear_trap_stoploss_caution_layer
```

Output:

- `artifacts/scanner_v2/bear_trap_stoploss_caution/bear_trap_stoploss_caution_report.json`
- `artifacts/scanner_v2/bear_trap_stoploss_caution/bear_trap_stoploss_caution_report.md`
- `artifacts/scanner_v2/bear_trap_stoploss_caution/bear_trap_stoploss_caution_summary.csv`
- `artifacts/scanner_v2/bear_trap_stoploss_caution/<pattern>/stoploss_caution_events.csv`
- `artifacts/scanner_v2/bear_trap_stoploss_caution/<pattern>/stoploss_caution_summary.json`

## Phạm vi đã chạy

| Nhóm | Pattern |
|---|---|
| Flag/Pennant | `bear_flags`, `bear_pennants` |
| Triangle | `triangles_descending` |
| Double Tops | `double_tops_adam_adam`, `double_tops_adam_eve`, `double_tops_eve_adam`, `double_tops_eve_eve` |
| Head & Shoulders | `head_and_shoulders_tops`, `head_and_shoulders_tops_complex` |
| Measured/Rectangle/Broadening | `measured_move_down`, `rectangle_tops`, `broadening_tops` |
| Weekly/Triple/Other tops | `pipe_tops`, `triple_tops`, `bump_and_run_reversal_tops`, `rounding_tops`, `horn_tops`, `diamond_tops` |

Kết quả hiện tại: tất cả 18 pattern đều có đủ event/path và cột vùng phá vỡ nguồn; không pattern nào phải dùng fallback duy nhất là `breakout_price`.

## Guardrail

Lớp này không được:

- tạo BUY alert,
- chấm `tradable-final`,
- sinh `release_candidate`,
- dùng future MFE/MAE để chọn event,
- biến chapter bearish thành tín hiệu mua hoặc tín hiệu bán khống tự động.

Lớp này được dùng để:

- cảnh báo phá vỡ giảm chưa sạch,
- nhắc người đọc theo dõi giá quay lại vùng phá vỡ trong 5/10/20 phiên,
- bổ sung mục “Khi phá vỡ giảm thất bại” trong chapter bearish,
- làm risk-context cho realtime watchlist.

## Publication reframe đã khóa

Vòng publication sau đó đã áp dụng `bear_trap_stoploss_publication_reframe_v1` cho 18 chapter final.  Các PDF final không được in marker kỹ thuật, không dùng lại nhãn `defensive/informational` trong phần public, và câu “Cách dùng” trên trang đầu phải nói rõ: dùng để kiểm tra bẫy giảm sau phá vỡ, quan sát giá đóng cửa quay lại vùng phá vỡ trong 5/10/20 phiên, không phải tín hiệu mua hoặc bán khống tự động.

Gate hiện hành:

```bash
PYTHONPATH=. pytest tests/test_bear_trap_publication_reframe.py tests/test_bear_trap_final_pdf_text.py
```
