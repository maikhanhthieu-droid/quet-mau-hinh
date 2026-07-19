# Kết quả chạy thật DeepSeek V4 Flash long-context cho Bull Flag

Ngày chạy: 2026-05-18  
Model: `deepseek-v4-flash`  
Artefact chính: `artifacts/scanner_v2/bull_flags_ai_writing_long_context_v4_flash/`

## Mục tiêu

Lượt này kiểm tra giả thuyết mới: DeepSeek có thể hữu ích hơn nếu được dùng đúng lợi thế 1M context, tức là đọc gần toàn bộ dossier nghiên cứu thay vì chỉ nhận compact payload khoảng 24K input tokens như các lượt trước.

## Kết quả kỹ thuật

Lượt đầu tiên đưa cả `detections.json` thô vào prompt bị API từ chối vì vượt giới hạn:

- Context model: 1.048.576 tokens.
- Request ban đầu: 1.463.070 tokens, gồm 1.443.070 input tokens và 20.000 output tokens.

Sau đó runner được chỉnh lại: bỏ `detections.json` thô vì trùng lặp lớn với event/path payload, giữ nguyên các file quan trọng hơn là `events.csv`, `post_breakout_path.csv`, `statistics.json`, publication payload, source grounding, PDF extracted text và các báo cáo robustness/OOS. Lượt chạy thành công dùng:

- Dossier: 1.773.865 ký tự.
- Audit pass: 892.857 prompt tokens, 5.288 completion tokens.
- Writer pass: 897.063 prompt tokens, 5.120 completion tokens.
- Critic pass: 901.401 prompt tokens, 2.610 completion tokens.
- Context cache hoạt động rõ: writer có 884.736 cached prompt tokens; critic có 892.416 cached prompt tokens.

## Kết quả nội dung

Ba pass đều trả JSON hợp lệ:

| Pass | Thời gian | Vai trò | Kết quả |
|---|---:|---|---|
| Audit | 144,8 giây | Đọc dossier và audit chương hiện tại | Tạo metric inventory, claim ledger, outline đề xuất và 5 lỗi nội dung hiện tại |
| Writer | 59,4 giây | Viết bản nháp section public-facing | Tạo 9 section, có deck, caption, callout và claim-to-metric list |
| Critic | 41,2 giây | Rà output writer | Tự chấm 90/100, `Publish with caveats`, không báo unsupported claim |

Điểm đáng giá nhất là critic phát hiện một lỗi cụ thể ở caption ví dụ MBB: writer nói giá chạm 17,92 nhưng dữ liệu event cho thấy biên thuận lợi 11,94% từ giá 14,66, tương đương khoảng 16,41, chưa chạm mục tiêu 17,92. Đây là bằng chứng rằng long-context thật sự giúp model đối chiếu dữ liệu event-level, không chỉ viết văn chung chung.

## So với lượt compact-context trước

| Tiêu chí | Compact-context V4 Flash | Long-context V4 Flash |
|---|---|---|
| Input | Khoảng 24K prompt tokens | Khoảng 893K-901K prompt tokens |
| JSON | Hybrid hợp lệ sau rerun | Cả 3 pass hợp lệ |
| Cache | Có nhưng ít ý nghĩa | Cache hit rất lớn ở pass 2 và 3 |
| Khả năng audit dữ liệu | Hạn chế | Tốt hơn rõ, bắt được lỗi caption MBB |
| Rủi ro thuật ngữ tiếng Anh | Còn | Còn, nhưng phần lớn nằm ở field audit/claim kỹ thuật |
| Dùng trực tiếp vào PDF | Chưa nên | Chưa nên nếu không qua guard |
| Vai trò tốt nhất | Draft ngắn | Audit/editor/critic long-context |

## Đánh giá

DeepSeek long-context cải thiện đáng kể ở tầng **đọc hồ sơ và phát hiện vấn đề**. Nó không chỉ viết trôi chảy hơn, mà còn tạo được claim ledger, outline, và tự critic có căn cứ trên dữ liệu. Đây là cải thiện thật so với compact-context.

Nhưng nó vẫn chưa nên được nối thẳng vào PDF. Lý do:

- Writer vẫn để lọt một số thuật ngữ tiếng Anh như `scanner`, `breakout`, `MFE/MAE` trong các trường claim hoặc đoạn body.
- Một số cụm bị heuristic bắt như `đảm bảo` xuất hiện trong ngữ cảnh phủ định "không đảm bảo"; cần guard thông minh hơn thay vì đếm thô.
- Critic tự chấm `pass: true` dù vẫn có `blocking_issues`, nên Codex không được tin hoàn toàn vào self-rating của model.
- Caption ví dụ cần lớp kiểm tra số học độc lập, vì writer vẫn có thể suy sai từ target/move.

Kết luận thực dụng: **DeepSeek V4 Flash long-context đáng dùng trong pipeline mới, nhưng ở vai trò phụ tá audit + writer + critic. Codex vẫn phải giữ lớp fact guard, thuật ngữ guard, caption arithmetic guard và renderer PDF.**

## Hàm ý cho bước tiếp theo

Nên chuyển từ thử nghiệm sang pipeline có kiểm soát:

1. Tích hợp DeepSeek long-context như một bước tùy chọn tạo `ai_sections.json`, không ghi thẳng vào PDF.
2. Thêm guard sửa/loại thuật ngữ tiếng Anh trong body, nhưng cho phép trong tên field kỹ thuật.
3. Thêm kiểm tra caption arithmetic: mọi caption có giá, mục tiêu, biên thuận lợi/bất lợi phải khớp event data.
4. Dùng critic output như checklist sửa, không dùng self-score làm quyết định cuối.
5. Sau khi guard sạch, đưa section được duyệt vào canonical content layer; `build_bull_flag_public_chapter.py` đã được chuyển vào `_legacy_quarantine` và không còn là luồng xuất bản.
