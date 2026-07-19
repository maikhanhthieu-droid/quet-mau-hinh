# Publication Semantic Gate

Gate này bảo vệ tầng xuất bản public. Một chapter không được gọi là final chỉ vì scanner chạy đúng, source audit sạch, payload đủ section, hoặc PDF render được.

## Lỗi cần chặn

1. **Dùng generic family spec cho variant.** Variant như Adam & Eve phải có publication spec riêng; không được dùng `_spec(double_bottoms)` rồi thêm vài dòng variant.
2. **In raw source rule vào PDF.** Source notes dùng để grounding, không phải nội dung public. PDF phải dùng tiếng Việt đã biên tập, không in nguyên câu tiếng Anh hoặc implementation mapping.
3. **Rò rỉ ngôn ngữ vận hành.** PDF public không được có các từ như `payload`, `factory`, `source_alignment`, `publication_quality_tier`, `data_limited`, `candidate`, `audit`, `headline`.
4. **Thiếu kiểm soát cảm giác đọc.** Chapter phải có nhịp đọc của tài liệu tham khảo đầu tư: diện mạo mẫu hình, cách nhận diện, kết quả quan trọng, thống kê, ví dụ, thất bại, cách dùng và giới hạn.

## Điều kiện pass cho chapter mới

Một chapter bật `source_grounding_required` hoặc `publication_semantic_required` phải có:

- `publication_spec`: file JSON riêng cho pattern/variant.
- `publication_spec.status = PASS`.
- `publication_spec.semantic_gate_id = publication_semantic_gate_v1`.
- `publication_spec.spec_scope` không được là `generic_family`.
- `publication_spec.variant_specific = true` nếu pattern là biến thể Adam/Eve.
- `publication_spec.public_required_phrases` xuất hiện trong PDF.
- `publication_spec.public_forbidden_terms` không xuất hiện trong PDF.
- Không có raw `source_rules.short_excerpt` hoặc `source_rules.implementation_mapping` tiếng Anh dài xuất hiện trong PDF.

## Quy tắc promote

Từ thời điểm áp dụng gate này, không copy PDF thủ công vào `artifacts/final_chapters`. Final promotion phải đi qua manifest validation; nếu chapter bật semantic gate mà không có spec/report tương ứng, manifest phải fail.
