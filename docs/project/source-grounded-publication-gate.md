# Source-Grounded Publication Gate

Mục tiêu của gate này là ngăn việc chapter mới tự nội suy logic scanner, target hoặc bố cục xuất bản thay vì bám vào tài liệu gốc. Đây là nguyên tắc bắt buộc cho mọi family/pattern/variant được phát triển từ thời điểm này.

## Nguyên tắc chốt

1. **Đọc nguồn gốc trước khi viết scanner hoặc PDF.** Mỗi pattern phải có source contract từ PDF gốc Bulkowski trước khi render publication chapter.
2. **Không tự suy target hoặc tiêu chí nhận diện.** Nếu tài liệu gốc có confirmation line, measure rule, minimum rise, shape rule, throwback, volume rule hoặc failure definition thì contract phải ghi rõ.
3. **Chỉ dùng chung khung thống kê và renderer.** Scanner geometry, target calibration, quality tier, example policy và wording trọng tâm phải được thiết kế riêng theo family/pattern/variant.
4. **Variant là chapter logic riêng nếu Bulkowski tách chapter riêng.** Ví dụ Double Bottom Adam & Eve không được kế thừa mù quáng ghi chú Adam & Adam.
5. **Không render final nếu source audit còn lỗi publication.** High và medium source-grounding issues phải bằng 0 trước khi gọi chapter là final.
6. **Thiếu dữ liệu thì ghi thiếu, không tự lấp.** Nếu data hiện tại không đo được mục của Bulkowski, chapter phải ghi `không khả dụng trong phạm vi dữ liệu hiện có`, không thay bằng chỉ số tự nghĩ.
7. **PDF public phải đọc như chapter đầu tư tham khảo.** Phần vận hành/audit/internal payload không được tràn vào bản public.
8. **Source audit không thay thế editorial-semantic audit.** Một chapter có thể bám đúng nguồn nhưng vẫn chưa final nếu nội dung public còn dùng generic family spec, raw source-rule text, hoặc ngôn ngữ vận hành.
9. **Không tuyên bố Final nếu chưa kiểm PDF gốc trực tiếp.** Source JSON hoặc registry nội bộ chỉ là chỉ mục. Trước khi promote final, `source_notes.direct_pdf_review.status` phải là `PASS`, có `pdf_path`, `book_pages_checked`, `pdf_pages_checked`, và ghi rõ điểm đối chiếu quan trọng như target/measure rule.
10. **Target headline phải qua calibration riêng.** Sau khi có source target/measure rule, phải chạy audit target cho chapter/variant. Nếu source là full-height và pass calibration thì dùng full-height làm headline; nếu không pass thì chỉ ghi mốc thận trọng/diagnostic. Không được mặc định `0,5x` là "mục tiêu cơ sở" trên mọi pattern.
11. **Mỗi chapter phải có hai trục chấm điểm tách biệt.** `publication-final` chỉ nói chapter đủ điều kiện xuất bản như tài liệu tham khảo. `tradable-final-95` chỉ được dùng khi có lớp entry/exit/cost/slippage/sizing/portfolio/OOS/walk-forward riêng, có scorecard >= 95, release gate PASS, và không còn promotion blocker. Chapter chưa có lớp này phải ghi `tradable_status = not_tested`, không được ngầm hiểu là đã đạt hoặc đã thất bại.

## Contract tối thiểu cho một chapter mới

Mỗi chapter hoặc variant mới cần có:

- `source_notes.status = PASS`.
- Ít nhất 6 `source_rules` có `rule_id`, trích ý nguồn, và mapping sang scanner/chapter.
- `source_grounding_policy_id = source_grounded_publication_gate_v1` trong manifest hoặc source notes nếu chapter được đưa vào final.
- Nếu manifest đặt `direct_source_review_required = true`, source notes bắt buộc có `direct_pdf_review` đạt `PASS`; thiếu bước này thì publication contract phải fail.
- Ghi rõ chapter nguồn, ví dụ `Chapter 14 - Double Bottoms, Adam & Eve`.
- Audit sau render xác nhận không còn high/medium issue do sai nguồn.
- Semantic audit sau render theo `publication_semantic_gate_v1`; xem [publication-semantic-gate.md](publication-semantic-gate.md).
- Target calibration artifact cập nhật từ `scanner/run_final_chapters_target_calibration_audit.py` nếu chapter đã nằm trong nhóm final hoặc đang render lại từ nhóm đã hoàn thành.
- Governance matrix cập nhật từ `scanner/build_chapter_governance_matrix.py`, gồm cả `publication_status` và `tradable_status` cho từng chapter final.

## Cách áp dụng cho Double Pattern Family

Double Pattern Family là nhóm reversal quanh neckline, không dùng lại logic Flag hoặc Triangle ngoài phần thống kê/chapter core. Với Double Bottom, từng biến thể Adam/Eve phải giữ thứ tự hình thái:

- `AA`: Adam bên trái, Adam bên phải.
- `AE`: Adam bên trái, Eve bên phải.
- `EA`: Eve bên trái, Adam bên phải.
- `EE`: Eve bên trái, Eve bên phải.

Biến thể kế tiếp sau Adam & Adam là **Adam & Eve**, nên phải dùng Chapter 14 làm nguồn chính, không dùng mô tả Chapter 13 làm mặc định.
