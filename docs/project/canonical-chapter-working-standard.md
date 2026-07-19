# Canonical Chapter Working Standard

Tài liệu này là quy chuẩn làm việc bắt buộc cho mọi chapter mẫu hình giá từ
thời điểm này. Mục tiêu là chặn lặp lại lỗi tự sinh PDF, dùng fallback văn bản,
dùng logic legacy hoặc gọi nhầm builder lịch sử.

## Nguyên tắc lõi

1. **Source-grounding trước scanner**  
   Trước khi viết hoặc sửa scanner, phải đối chiếu hình thái với chương gốc
   Bulkowski tương ứng. Không tự nội suy hình học nếu tài liệu gốc có mô tả rõ.

2. **Scanner theo family/pattern, thống kê dùng chung khung**  
   Mỗi family được phép có scanner, nhánh chất lượng, target calibration và
   logic tối ưu riêng. Phần dùng chung chỉ là event schema, outcome metrics,
   uncertainty, publication/tradable scoring và audit.

3. **Không dùng builder legacy trong active code**  
   Active scanner/publication code không được import từ các file trong
   `scanner/_legacy_quarantine`. Audit `publication_entrypoint_guard_v1` phải
   fail nếu phát hiện import này.

4. **Final PDF chỉ đi qua canonical factory**  
   Một PDF chỉ được gọi là final nếu được render bằng:

   ```text
   canonical_editorial_workflow_v1
     -> canonical_chapter_content_generator_v1
     -> canonical_ai_editorial_gate_v1
     -> canonical_publication_chapter_factory_v1
     -> pattern_publication_core_v1
   ```

5. **Không fallback nội dung public**  
   Lỗi runtime hoặc thiếu section phải được sửa ở nguồn dữ liệu/editorial, không
   được bù bằng câu chung chung, placeholder hoặc bảng máy móc rồi promote final.

6. **Ví dụ biểu đồ là case study, không chỉ là event hợp lệ**  
   Selector tự động phải ưu tiên hình thái sạch. Với mẫu khó như vai đầu vai,
   cốc tay cầm, broadening hoặc các case thất bại hiếm, phải dùng queue review
   bằng mắt/whitelist nếu ví dụ tự động chỉ đạt `usable`.

7. **Hai thang điểm bắt buộc và nhãn sử dụng phải đúng vai**
   Mỗi chapter phải có publication/preflight score và tradable score nếu pattern
   có ý nghĩa thực thi long-cash. Pattern bearish/top/downside không được bị hạ
   xuống một nhãn “phòng thủ/thông tin” chung chung nếu dữ liệu cho phép đo bẫy
   giảm. Với các chapter này, cách đọc mặc định là: kiểm tra độ sạch của phá vỡ
   giảm, quan sát giá quay lại vùng phá vỡ trong 5/10/20 phiên, và dùng kết quả
   như lớp kỷ luật cắt lỗ/thoát vị thế, không phải tín hiệu mua hoặc bán khống
   tự động.

8. **Chỉ báo cáo khi đạt mốc hoặc gặp blocker thật**  
   Không gọi draft là final. Không promote khi audit còn cảnh báo nghiêm trọng.

## Checklist chapter mới

1. Đọc chapter gốc và tạo source/style dossier.
2. Viết hoặc sửa scanner riêng cho pattern/family.
3. Chạy scan, outcome metrics, target calibration và uncertainty.
4. Chạy publication/preflight score.
5. Chạy tradable layer nếu pattern phù hợp.
6. Sinh approved editorial sections qua canonical editorial workflow.
7. Chọn ví dụ minh họa; nếu role nào chỉ còn `usable`, ghi vào review queue.
8. Render bằng `canonical_publication_chapter_factory_v1`.
9. Chạy các audit bắt buộc:

   ```bash
   PYTHONPATH=. ./.venv/bin/python -m scanner.audit_publication_entrypoints
   PYTHONPATH=. ./.venv/bin/python -m scanner.audit_canonical_publication_flow
   PYTHONPATH=. ./.venv/bin/python -m scanner.audit_final_chapter_crosscheck --skip-realtime-watchlist
   ```

10. Đọc PDF bằng mắt hoặc contact sheet trước khi promote.
11. Nếu chapter thuộc nhóm bearish/top/downside có trong scope
    `bear_trap_stoploss_caution_layer_v1`, chạy thêm:

   ```bash
   PYTHONPATH=. ./.venv/bin/python -m scanner.build_bear_trap_stoploss_caution_layer
   PYTHONPATH=. ./.venv/bin/python -m scanner.apply_bear_trap_publication_reframe
   PYTHONPATH=. ./.venv/bin/python -m scanner.rerender_final_chapters_render_only --pattern <pattern_id> --promote
   PYTHONPATH=. ./.venv/bin/python -m pytest tests/test_bear_trap_publication_reframe.py tests/test_bear_trap_final_pdf_text.py
   ```

## Cấm

- Import helper từ `scanner/_legacy_quarantine`.
- Dùng `pattern_publication_core_v1` trực tiếp để gọi một chapter là final.
- Để `source_rules_public` chứa placeholder kiểu “quy tắc nguồn đã được chuyển
  thành...”.
- Dùng fallback để che lỗi thiếu AI/editorial section.
- Chọn ví dụ chỉ vì VN30/VN100 nếu hình thái kém.
- In marker kỹ thuật như `bear_trap_stoploss_publication_reframe_v1` ra PDF
  public.
- Để chữ public dùng lại cụm “defensive/informational” cho chapter bearish đã
  có lớp bẫy giảm/cắt lỗ thận trọng.
- Xóa/move file user tạo hoặc dữ liệu nghiên cứu nếu không phục vụ trực tiếp
  cho việc quarantine/cleanup.

## Khi chạm trần kỹ thuật

Nếu không thể nâng thêm vì sample depth, downside scope, thiếu dữ liệu trạng
thái, hoặc hình thái hiếm, chapter vẫn có thể final ở nhãn phù hợp:

- `investment/reference candidate`
- `watchlist/reference`
- `defensive/informational`
- `research appendix`

Không ép score bằng overfit hoặc rule hậu nghiệm.
