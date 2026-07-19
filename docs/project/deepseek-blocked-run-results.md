# Kết quả chạy DeepSeek theo block cho Bull Flag

Ngày chạy: 2026-05-18  
Model: `deepseek-v4-flash`  
Artefact chính: `artifacts/scanner_v2/bull_flags_ai_writing_blocked_v4_flash/`

## Mục tiêu

Lượt này kiểm tra hướng chia việc thành nhiều block chuyên trách, thay vì gửi một dossier rất lớn rồi yêu cầu model vừa audit vừa viết vừa tự sửa.

Các block đã chạy:

1. Source & rule grounding.
2. Metrics interpreter.
3. Example caption writer.
4. Public chapter writer.
5. Critic / red-team.
6. Deterministic synthesizer.

## Kết quả kỹ thuật

Tất cả 6 block đều trả JSON hợp lệ.

| Block | Prompt tokens | Completion tokens | Body guard |
|---|---:|---:|---|
| Source & rule grounding | 11.997 | 3.702 | Pass |
| Metrics interpreter | 52.381 | 3.087 | Pass |
| Example caption writer | 40.678 | 3.449 | Pass |
| Public chapter writer | 9.605 | 4.562 | Fail |
| Critic / red-team | 9.897 | 4.234 | Pass |
| Deterministic synthesizer | 0 | 0 | Pass sau repair |

So với long-context một cục, tổng prompt nhỏ hơn rất nhiều ở từng call. Long-context dùng gần 900K prompt tokens/pass; blocked pipeline dùng khoảng 6K-52K prompt tokens/block. Đổi lại, do mỗi block có input khác nhau nên không có context cache đáng kể.

## Chất lượng nội dung

Block hóa cho kết quả tốt hơn ở các vai trò chuyên trách:

- Block source/rule không bị lẫn sang viết văn hoặc claim giao dịch.
- Block metrics tạo được inventory số liệu và caveat rõ hơn.
- Block example caption tự kiểm caption theo event data và tránh lỗi MBB của lượt long-context trước: MBB được ghi là **không chạm mục tiêu 17,92**, với biên thuận lợi 11,94% và biên bất lợi 5,25%.
- Critic tìm lỗi văn phong cụ thể: `half-staff`, `swing`, `path`, và câu deck hơi mạnh.

Điểm yếu còn lại nằm ở writer/synthesizer:

- Writer vẫn để lọt một số thuật ngữ hoặc cụm bị guard bắt như `MFE`, `MAE`, `scanner`, `khuyến nghị mua`, `đảm bảo`.
- Nhiều trường hợp là ngữ cảnh phủ định hoặc callout, nhưng vẫn không nên đưa thẳng vào PDF nếu mục tiêu là tiếng Việt thuần.
- Tổng hợp cuối đã chuyển sang deterministic code. DeepSeek không còn viết lại block cuối để tránh lỗi JSON dài/cắt output.

## Repair hậu kiểm

Sau writer/critic, đã chạy một bước synthesize + repair deterministic có chọn lọc:

- Chỉ sửa trường public-facing như `paragraphs`, `callout.bullets`, `example_captions`, `final_caveat`.
- Giữ nguyên `id` và `claims_used` để không phá cấu trúc tích hợp.
- Thay `MFE/MAE` bằng `biên thuận lợi/bất lợi`, `Breakout` bằng `Phá vỡ`, `scanner` bằng `bộ quét`, và bỏ các cụm tiếng Anh trong caption.

Output sạch:

- `approved_ai_sections_cleaned_v2.json`
- `approved_ai_sections_cleaned_v2_guard.json`
- Sau khi chốt logic, tên canonical là `approved_ai_sections.json` và `approved_ai_sections_guard.json`.

Guard sau repair:

- Body banned terms: không còn.
- Caption banned terms: không còn.
- Guard: pass.

Các thuật ngữ còn xuất hiện trong toàn JSON chỉ nằm ở field kỹ thuật như `claims_used` hoặc `id`, không nằm trong nội dung đọc cho nhà đầu tư.

## Đánh giá so với long-context một cục

| Tiêu chí | Long-context một cục | Blocked pipeline |
|---|---|---|
| Khả năng đọc dữ liệu rất lớn | Mạnh hơn | Vừa đủ, tùy block |
| Chi phí/token mỗi call | Rất cao | Thấp hơn nhiều |
| Cache | Rất tốt ở pass 2-3 | Gần như không có |
| Kiểm soát vai trò | Trung bình | Tốt hơn rõ |
| Caption quality | Tự critic bắt lỗi nhưng writer vẫn sai | Caption block sạch hơn |
| Public body guard | Còn fail | Pass sau deterministic synth + repair |
| Khả năng tích hợp PDF | Cần guard lớn | Tốt hơn, nên dùng output cleaned |

## Kết luận

Hướng block hóa tốt hơn cho pipeline xuất bản. Long-context một cục phù hợp làm audit tổng thể hoặc kiểm tra dữ liệu sâu. Còn để sinh nội dung public-quality, nên dùng block pipeline:

`source -> metrics -> examples -> writer -> critic -> deterministic synth -> deterministic guard`

Output nên tích hợp thử vào PDF là:

`artifacts/scanner_v2/bull_flags_ai_writing_blocked_v4_flash/approved_ai_sections.json`

Điều kiện trước khi nối vào builder:

1. Thêm validator caption vào code, không chỉ dựa vào model.
2. Thêm body/caption guard vào test.
3. Cho phép field kỹ thuật chứa `MFE/MAE/breakout`, nhưng cấm các cụm đó trong body/caption.
4. Không tin self-score của critic; chỉ dùng critic làm checklist sửa.

## Lượt chốt sau khi sửa workflow

Sau khi chuyển block tổng hợp cuối sang deterministic code, chạy lại cho kết quả:

- `approved_ai_sections_guard.json`: pass.
- PDF chính đã được build lại tại `artifacts/scanner_v2/bull_flags_public_chapter/bull_flag_public_chapter.pdf`.
- PDF text QA không còn các cụm: `MFE`, `MAE`, `breakout`, `stop loss`, `khuyến nghị mua`, `half-staff`, `swing`, `path dữ liệu`, `research`, `setup`, `volume`, `OHLCV`, `target`, `hit`, `median`, `proxy`, `available`.
- Tests public chapter: 4 passed.
