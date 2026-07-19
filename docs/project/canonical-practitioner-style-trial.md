# Canonical Practitioner Style Trial

## Mục tiêu

Thử nâng lớp viết nội dung public chapter bằng DeepSeek V4 Pro với văn phong
giàu diễn giải hơn, nhưng không thay scanner, thống kê, target calibration hoặc
PDF factory. Bull Flag được dùng làm mẫu kiểm vì đây là chapter chuẩn hiện tại.

## Thiết lập đã thử

| Trial | Payload | Temperature | Kết quả |
|---|---|---:|---|
| `practitioner_t045` | payload cũ 110 mẫu | 0.45 | Gate pass, nhưng văn phong hơi trượt sang ngôn ngữ hành động/giao dịch. Không dùng làm candidate. |
| `practitioner_t035` | payload cũ 110 mẫu | 0.35 | Gate pass, ít trade-like hơn, nhưng không hợp lệ để render family vì renderer DB-active dùng 193 mẫu. |
| `practitioner_t035_db_active` | payload DB-active 193 mẫu | 0.35 | Candidate hợp lệ: số liệu và PDF cùng scope, editorial guard pass, style V3 audit pass. |
| `bulkowski_source_t035_db_active_sanitized_v2` | payload DB-active 193 mẫu + dossier phong cách Flags từ PDF gốc | 0.35 | Candidate tốt nhất hiện tại: bám cấu trúc encyclopedia hơn, mở bằng tour hình thái, phụ lục kỹ thuật tách riêng, style V3 audit pass. |
| `reader_refine_v1_t03_db_active` | refinement pass trên source-guided candidate | 0.30 | Candidate viết tốt nhất hiện tại: giữ factory/số liệu cũ, chỉ viết lại văn để tăng tính case-study và diễn giải phổ thông; style V3 audit pass. |

## Candidate hợp lệ

- AI artifact: `artifacts/scanner_v2/bull_flags_ai_writing_canonical_v4_pro_practitioner_t035_db_active/approved_ai_sections.json`
- Guard: `artifacts/scanner_v2/bull_flags_ai_writing_canonical_v4_pro_practitioner_t035_db_active/approved_ai_sections_guard.json`
- PDF thử nghiệm: `artifacts/scanner_v2/flag_family_public_chapters_practitioner_t035_db_active/bull_flag/bull_flag_public_chapter.pdf`
- PDF audit: `artifacts/scanner_v2/flag_family_public_chapters_practitioner_t035_db_active/bull_flag/style_v3_audit.json`

Kết quả kiểm:

- `canonical_ai_editorial_gate_v1`: PASS
- `canonical_publication_style_v3_pdf_audit`: PASS
- PDF: 11 trang, khoảng 32,630 ký tự text extraction
- Không còn mismatch payload 110 mẫu trong bản DB-active; PDF dùng 193 mẫu.
- Target headline: 0,46x, tỷ lệ đạt 68,39%, thất bại 5% là 25,39%.

## Nhận xét chất lượng

So với Bull Flag final cũ, bản `t035_db_active` đọc giàu diễn giải hơn ở ba
điểm: phần mở đầu chuyển số liệu thành ý nghĩa biểu đồ rõ hơn, phần hình học
nhấn mạnh thứ tự đọc cột cờ - thân cờ - xác nhận tốt hơn, và phần cách dùng bớt
giống bảng thống kê thuần.

Đổi lại, bản này dài hơn: 11 trang so với 9 trang ở Bull Flag final cũ. Trang
cuối còn khá nhiều khoảng trắng, nhưng không có lỗi layout, chồng chữ hoặc rò
thuật ngữ nội bộ. Nếu muốn promote thành chuẩn mới, nên chấp nhận độ dài này
hoặc làm thêm một lượt compact nhẹ ở renderer/prose để giữ quanh 10 trang.

## Quy tắc rút ra

- Không dùng temperature 0.45 làm mặc định; dễ tạo câu gần ngôn ngữ giao dịch.
- Candidate hiện tại nên dùng `temperature=0.35` với profile
  `canonical_publication_practitioner_style_trial_v1`.
- Khi cần nâng chất lượng diễn giải, dùng profile
  `canonical_publication_bulkowski_source_guided_v1`: trích xuất một dossier
  phong cách từ chương gốc liên quan, đưa vào DeepSeek như tài liệu tham chiếu
  về cấu trúc và nhịp viết, không dùng làm nguồn số liệu và không sao chép/diễn
  dịch văn bản gốc.
- Bản source-guided phải qua thêm lớp làm sạch thuật ngữ giao dịch. Nếu AI đưa
  các cụm như `cắt lỗ`, `tín hiệu mua tự động`, `mua/cầm nắm`, cần chuyển về
  ngôn ngữ tham khảo trung tính trước khi render.
- Mọi trial phải dùng cùng payload với renderer family hiện hành; không trộn
  payload cũ 110 mẫu với PDF DB-active 193 mẫu.
- DeepSeek chỉ viết `approved_ai_sections`; PDF vẫn phải đi qua
  `canonical_publication_chapter_factory_v1`.

## Candidate source-guided

- Style reference builder: `scanner/build_bulkowski_style_reference.py`
- Style dossier: `artifacts/scanner_v2/bulkowski_style_reference/flags/bulkowski_flags_style_dossier.md`
- AI artifact: `artifacts/scanner_v2/bull_flags_ai_writing_canonical_v4_pro_bulkowski_source_t035_db_active/approved_ai_sections.json`
- PDF thử nghiệm: `artifacts/scanner_v2/flag_family_public_chapters_bulkowski_source_t035_db_active_sanitized_v2/bull_flag/bull_flag_public_chapter.pdf`
- PDF audit: `artifacts/scanner_v2/flag_family_public_chapters_bulkowski_source_t035_db_active_sanitized_v2/bull_flag/style_v3_audit.json`

Kết quả kiểm:

- `canonical_ai_editorial_gate_v1`: PASS
- `canonical_publication_style_v3_pdf_audit`: PASS
- PDF: 11 trang, khoảng 39,109 ký tự text extraction, 6,564 từ
- Số liệu scope đúng: 193 mẫu, mục tiêu cơ sở 0,46x, tỷ lệ đạt 68,39%.
- Không còn các cụm giao dịch quá trực tiếp trong bản sanitized v2.

Đánh giá: so với `practitioner_t035_db_active_appendix_v2`, bản source-guided
ít "báo cáo thống kê" hơn và giống một entry mẫu hình hơn: mở đầu bằng diện mạo,
tour nhận diện, lỗi loại nhanh, rồi mới sang bảng kết quả. Đây là hướng nên
promote làm chuẩn thử nghiệm tiếp theo cho các chapter mới, với điều kiện mỗi
family đều có style dossier lấy từ đúng chương gốc tương ứng.

## Candidate refinement pass

- Input: `artifacts/scanner_v2/bull_flags_ai_writing_canonical_v4_pro_bulkowski_source_t035_db_active/approved_ai_sections.json`
- AI artifact: `artifacts/scanner_v2/bull_flags_ai_writing_canonical_v4_pro_bulkowski_source_reader_refine_v1_t03_db_active/approved_ai_sections.json`
- PDF thử nghiệm: `artifacts/scanner_v2/flag_family_public_chapters_bulkowski_source_reader_refine_v1_t03_db_active/bull_flag/bull_flag_public_chapter.pdf`
- PDF audit: `artifacts/scanner_v2/flag_family_public_chapters_bulkowski_source_reader_refine_v1_t03_db_active/bull_flag/style_v3_audit.json`

Kết quả kiểm:

- `canonical_ai_editorial_gate_v1`: PASS
- `canonical_publication_style_v3_pdf_audit`: PASS
- PDF: 11 trang, khoảng 39,554 ký tự text extraction, 6,651 từ
- Số liệu scope đúng: 193 mẫu, mục tiêu cơ sở 0,46x, tỷ lệ đạt 68,39%.
- Full test suite sau thay đổi prompt/factory-adjacent logic: `247 passed, 1 warning`.

Đánh giá: refinement pass là cách ổn định hơn so với chạy lại toàn bộ workflow
nhiều block. Các block phụ của DeepSeek có xu hướng viết quá rộng khi thấy schema
chapter đầy đủ; vì vậy prompt builder đã được sửa để chỉ block writer thấy full
schema. Tuy nhiên, phương án thực dụng nhất cho lần tối ưu văn phong là: dùng
candidate source-guided đã qua gate làm bản nền, sau đó chạy một pass biên tập
ngắn để làm thân chương tự nhiên hơn. Bản `reader_refine_v1_t03_db_active` là
baseline khuyến nghị hiện tại cho Bull Flag.
