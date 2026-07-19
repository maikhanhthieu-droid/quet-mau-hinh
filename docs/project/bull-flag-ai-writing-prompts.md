# Prompt thử nghiệm viết chương Bull Flag bằng AI

Tài liệu này dùng để so sánh ba hướng viết chương public PDF cho mẫu **Cờ tăng / Bull Flag**:

1. **Codex tự viết**: bản hiện tại, text được viết trực tiếp trong builder và kiểm soát bằng pipeline.
2. **DeepSeek làm hết**: gửi dữ liệu và yêu cầu DeepSeek viết toàn bộ chapter.
3. **Hybrid Codex + DeepSeek**: Codex giữ số liệu, guardrail, layout; DeepSeek chỉ viết bản nháp diễn giải theo từng section.

Mục tiêu không phải chọn model "viết hay nhất" một cách cảm tính, mà là kiểm tra xem phương án nào tạo ra chương:

- đọc được như tài liệu public cho nhà đầu tư;
- không nói quá số liệu;
- giữ đúng tinh thần Bulkowski;
- vẫn render ổn trong PDF;
- có thể scale sang các mẫu hình khác.

## Dữ liệu đầu vào nên gửi

Nếu chạy thử DeepSeek, nên gửi các artifact sau:

```text
artifacts/scanner_v2/bull_flags_public_chapter/bull_flag_public_chapter_payload.json
artifacts/scanner_v2/bull_flags_publication_chapter/bull_flag_publication_payload.json
artifacts/scanner_v2/bull_flags/events.csv
artifacts/scanner_v2/bull_flags/statistics.json
artifacts/scanner_v2/bull_flags_public_chapter/bull_flag_content_parity_audit.md
artifacts/scanner_v2/bull_flags_public_chapter/charts/bull_flag_ideal_schematic.png
artifacts/scanner_v2/bull_flags_public_chapter/charts/textbook_success_SHB_2021-03-11.png
artifacts/scanner_v2/bull_flags_public_chapter/charts/middle_case_MBB_2024-02-05.png
artifacts/scanner_v2/bull_flags_public_chapter/charts/failure_MWG_2024-12-25.png
```

Không nên gửi bản PDF hiện tại trong lần DeepSeek làm hết, vì nó có thể bám theo văn phong sẵn có và làm sai mục tiêu so sánh độc lập.

## Prompt 1: DeepSeek làm toàn bộ chapter

Mục tiêu của prompt này là kiểm tra khả năng DeepSeek tự biến dữ liệu thành một bản chapter hoàn chỉnh.

````text
Bạn là biên tập viên nghiên cứu tài chính định lượng, viết tiếng Việt cho nhà đầu tư cá nhân có kiến thức trung bình-khá. Nhiệm vụ của bạn là viết một chương public-facing về mẫu hình Cờ tăng / Bull Flag cho thị trường chứng khoán Việt Nam, dựa hoàn toàn trên dữ liệu tôi gửi kèm.

Bối cảnh:
- Đây là một chương trong dự án "Bulkowski cho Việt Nam".
- Chương này là tài liệu tham khảo đầu tư có điều kiện, không phải khuyến nghị mua/bán.
- Không được viết như backtest quảng cáo lợi nhuận.
- Không được hứa hẹn xác suất thắng ngoài thị trường.
- Không được nói rằng dữ liệu bao phủ point-in-time toàn thị trường.
- Không được dùng historical VN30/VN100 membership như claim chính.
- Phải viết thuần tiếng Việt, tránh thuật ngữ tiếng Anh lộ ra trong body nếu có thể.

Dữ liệu tôi gửi:
- Payload thống kê chapter.
- Bảng sự kiện Bull Flag.
- File statistics.json.
- Audit nội dung theo cấu trúc chapter.
- Ảnh sơ đồ lý tưởng và 3 chart ví dụ trong VN100/VN30.

Yêu cầu nội dung:
Viết một chapter hoàn chỉnh theo cấu trúc sau:

1. Tóm tắt chương
   - Mẫu hình là gì.
   - Số mẫu, mục tiêu cơ sở, tỷ lệ đạt mục tiêu cơ sở, thất bại 5%.
   - Kết luận chính phải cân bằng: có giá trị tham khảo nhưng không phải tín hiệu mua tự động.

2. Cách nhận diện
   - Cột cờ.
   - Thân cờ.
   - Hai đường biên.
   - Phá vỡ.
   - Khối lượng.
   - Các điều kiện loại nhanh.

3. Ví dụ trong VN100/VN30
   - Viết caption cho sơ đồ lý tưởng.
   - Viết caption cho ví dụ đạt mục tiêu.
   - Viết caption cho ví dụ trung vị.
   - Viết caption cho ví dụ thất bại.
   - Không chọn thêm ví dụ ngoài dữ liệu.

4. Tập trung vào thất bại
   - Giải thích thất bại 5%.
   - Giải thích mục tiêu đến trước bất lợi.
   - Giải thích vì sao hình thái hợp lệ vẫn có thể thất bại.

5. Thống kê kết quả
   - Diễn giải bảng summary.
   - Diễn giải target family 0,46x / 0,5x / 0,75x / 1,0x nếu có trong payload.
   - Mục tiêu 0,46x là mục tiêu cơ sở.
   - Mục tiêu 1,0x chỉ là mốc tham chiếu căng.

6. Hành vi sau phá vỡ
   - Thời gian chạm mục tiêu.
   - Kiểm định lại vùng phá vỡ.
   - Biên thuận lợi/bất lợi.
   - Dừng lỗ, phá ngược, rủi ro đường đi.

7. Kích thước, khối lượng và vị trí trong năm
   - Thân cờ ngắn/dài.
   - Thân cờ thấp/cao.
   - Khối lượng xác nhận.
   - Vị trí trong biên năm.

8. Bối cảnh thị trường
   - Trạng thái thị trường.
   - Thanh khoản.
   - Nhóm cổ phiếu.
   - Nhấn mạnh đây là split mô tả trong phạm vi dữ liệu hiện có.

9. Cách sử dụng thực tế
   - Cách đọc mẫu.
   - Điều nên kiểm tra trước khi hành động.
   - Không viết như khuyến nghị giao dịch.

10. Chất lượng dữ liệu và giới hạn
   - Dữ liệu kỹ thuật daily hiện có.
   - Audit sự kiện quyền.
   - Dấu hiệu biên độ giá.
   - Giới hạn không có point-in-time universe toàn thị trường.
   - Giới hạn không có delisted/halted status tape đầy đủ.

Yêu cầu định dạng đầu ra:
Trả về Markdown theo cấu trúc sau:

```markdown
# Cờ tăng

## Tóm tắt chương
...

## Cách nhận diện
...

...
```

Sau chapter, bắt buộc thêm một phần riêng:

```markdown
## Claim ledger

| Claim | Số liệu hoặc nguồn trong payload | Mức độ chắc chắn | Có cần caveat không |
|---|---|---|---|
```

Quy tắc bắt buộc:
- Mỗi claim định lượng phải nêu số liệu cụ thể từ payload.
- Nếu không thấy số liệu trong payload, không được tự bịa.
- Nếu thiếu dữ liệu, viết là "chưa đủ dữ liệu để kết luận", không nội suy.
- Không dùng các cụm "nên mua", "chắc chắn", "đảm bảo", "xác suất thắng thực tế".
- Không dùng tiếng Anh như MFE, MAE, target-hit, breakout trong body; thay bằng biên thuận lợi, biên bất lợi, tỷ lệ đạt mục tiêu, phá vỡ.
- Văn phong phải giống một chương tài liệu nghiên cứu dễ đọc, không giống báo cáo vận hành nội bộ.
````

## Prompt 2: Hybrid Codex + DeepSeek

Mục tiêu của prompt này là để DeepSeek chỉ viết phần diễn giải, còn Codex giữ:

- số liệu cuối cùng;
- claim guard;
- bảng;
- layout PDF;
- thuật ngữ thống nhất;
- kiểm tra không overclaim.

Prompt này an toàn hơn để scale sang nhiều mẫu hình.

```text
Bạn là writer phụ cho một chương nghiên cứu mẫu hình giá. Bạn KHÔNG được tự thay đổi số liệu, KHÔNG được tự tạo bảng thống kê, và KHÔNG được kết luận vượt quá dữ liệu.

Codex sẽ cung cấp:
- Tên mẫu hình.
- Tóm tắt số liệu đã được kiểm định.
- Các caveat đã khóa.
- Vai trò của từng section.

Nhiệm vụ của bạn:
- Viết bản nháp tiếng Việt cho từng section.
- Dùng giọng văn public-facing, dễ đọc cho nhà đầu tư.
- Giữ đúng khung "tài liệu tham khảo đầu tư có điều kiện".
- Không viết như khuyến nghị mua/bán.
- Không dùng thuật ngữ tiếng Anh nếu có thể thay bằng tiếng Việt.
- Không tự thêm số ngoài brief.
- Nếu một câu cần số liệu nhưng brief không có, hãy ghi placeholder dạng {{CAN_SO_LIEU}}.

Brief mẫu hình:

Tên mẫu hình: Cờ tăng / Bull Flag
Vai trò: mẫu tiếp diễn ngắn sau một nhịp tăng mạnh.
Phạm vi: dữ liệu kỹ thuật daily hiện có, không claim point-in-time universe toàn thị trường.
Mục tiêu cơ sở: 0,46x chiều cao cột cờ.
Mốc tham chiếu căng: 1,0x chiều cao cột cờ.
Số mẫu: {{events}}
Tỷ lệ đạt mục tiêu cơ sở: {{base_target_hit_rate}}
Tỷ lệ thất bại 5%: {{failure_5pct_rate}}
Biên thuận lợi trung vị: {{median_mfe_pct}}
Biên bất lợi trung vị: {{median_mae_pct}}
Các giới hạn chính:
- Không có point-in-time universe toàn thị trường.
- Không có delisted/halted status tape đầy đủ.
- Corporate-action audit hiện là proxy theo dữ liệu có sẵn, chưa phải factor log chính thức.
- Không dùng historical VN30/VN100 membership làm claim chính.

Hãy viết các section sau, mỗi section 1-3 đoạn ngắn:

1. Tóm tắt chương
2. Mẫu hình hoạt động ra sao
3. Cách đọc ví dụ đạt mục tiêu
4. Cách đọc ví dụ trung vị
5. Cách đọc ví dụ thất bại
6. Tập trung vào thất bại
7. Diễn giải thống kê kết quả
8. Hành vi sau phá vỡ
9. Kích thước, khối lượng và bối cảnh
10. Cách sử dụng thực tế
11. Chất lượng dữ liệu và giới hạn

Đầu ra phải là JSON:

{
  "summary": ["...", "..."],
  "tour": ["...", "..."],
  "example_success_caption": "...",
  "example_middle_caption": "...",
  "example_failure_caption": "...",
  "failure": ["...", "..."],
  "statistics": ["...", "..."],
  "post_breakout": ["...", "..."],
  "context": ["...", "..."],
  "tactics": ["...", "..."],
  "data_limits": ["...", "..."],
  "claims_to_verify": [
    {
      "claim": "...",
      "needs_metric": "...",
      "risk": "low|medium|high"
    }
  ]
}

Quy tắc:
- Không tự điền số liệu vào placeholder.
- Không viết "mẫu này tốt" nếu không kèm điều kiện.
- Không dùng ngôn ngữ khuyến nghị giao dịch.
- Không nói "theo Bulkowski" nếu brief không cung cấp câu tương ứng; chỉ được nói "theo tinh thần tài liệu mẫu hình thực chứng".
- Mỗi section phải đủ tự nhiên để đưa vào PDF sau khi Codex thay placeholder bằng số liệu thật.
```

## So sánh ba phiên bản

| Tiêu chí | Codex tự viết hiện tại | DeepSeek làm hết | Hybrid Codex + DeepSeek |
|---|---:|---:|---:|
| Kiểm soát số liệu | Rất cao | Trung bình | Rất cao |
| Rủi ro overclaim | Thấp | Cao hơn | Thấp-trung bình |
| Văn phong tự nhiên | Khá | Có thể cao | Cao nếu prompt tốt |
| Tính ổn định layout PDF | Rất cao | Thấp nếu render trực tiếp | Cao |
| Khả năng scale nhiều mẫu | Trung bình | Cao nhưng rủi ro | Cao nhất |
| Chi phí biên tập lại | Thấp | Cao | Trung bình |
| Phù hợp bản release hiện tại | Cao | Thấp-trung bình | Cao |
| Phù hợp thử nghiệm sáng tạo | Trung bình | Cao | Cao |

### Phiên bản 1: Codex tự viết

Điểm mạnh:

- Kiểm soát chặt từng claim.
- Dễ gắn số liệu với payload.
- Dễ giữ thuật ngữ nhất quán.
- Dễ kiểm soát layout ReportLab.
- Ít rủi ro biến chapter thành khuyến nghị mua/bán.

Điểm yếu:

- Văn phong có thể vẫn hơi "kỹ thuật".
- Mỗi lần muốn đổi tone phải sửa builder hoặc manuscript generator.
- Scale sang nhiều mẫu hình sẽ tốn công nếu không tách lớp writer.

Đánh giá: phù hợp nhất cho **release candidate hiện tại**.

### Phiên bản 2: DeepSeek làm hết

Điểm mạnh:

- Có thể tạo bản nháp dài, tự nhiên và giàu diễn giải nhanh.
- Hữu ích để phát hiện cách kể chuyện, ví dụ cách chuyển đoạn, cách đặt nhịp chương.
- Có thể giúp chapter bớt khô nếu dữ liệu được tóm tắt tốt.

Điểm yếu:

- Dễ viết quá bằng chứng.
- Dễ dùng sai hoặc lẫn thuật ngữ.
- Có thể tự tạo số liệu nếu prompt không khóa đủ chặt.
- Có thể phá cấu trúc chapter đã được kiểm định.
- Không nên render trực tiếp thành PDF nếu chưa qua guard.

Đánh giá: phù hợp để **lấy bản nháp tham khảo**, không nên dùng làm nguồn xuất bản trực tiếp.

### Phiên bản 3: Hybrid Codex + DeepSeek

Điểm mạnh:

- DeepSeek xử lý phần văn phong.
- Codex giữ số liệu, guardrail, layout và claim verification.
- Dễ scale sang các mẫu hình khác.
- Có thể sinh nhiều option diễn giải cho cùng một section.
- Giảm rủi ro overclaim so với DeepSeek làm hết.

Điểm yếu:

- Cần thêm pipeline cho prompt, response JSON, validation và placeholder replacement.
- Cần claim checker để loại câu không map được về metric.
- Ban đầu phức tạp hơn Codex-only.

Đánh giá: đây là hướng tốt nhất nếu mục tiêu là **xây hệ thống viết chapter quy mô lớn**.

## Khuyến nghị

Nên chạy thử cả hai prompt, nhưng không dùng DeepSeek làm nguồn xuất bản trực tiếp ngay.

Thứ tự hợp lý:

1. Giữ bản **Codex-only** hiện tại làm baseline.
2. Chạy **DeepSeek làm hết** để xem nó có tạo cách diễn giải nào hay hơn không.
3. Chạy **Hybrid** để lấy các section JSON.
4. Chấm ba bản theo rubric:
   - độ đúng số liệu;
   - độ tự nhiên;
   - khả năng đọc của nhà đầu tư;
   - mức độ giống một chapter public;
   - số claim cần sửa;
   - mức độ giữ đúng caveat.
5. Nếu Hybrid thắng, triển khai pipeline chính thức: `payload -> prompt -> AI section JSON -> claim guard -> ReportLab`.

Kết luận thực dụng: **Codex-only tốt nhất cho bản release hiện tại; Hybrid là hướng tốt nhất cho nền tảng dài hạn; DeepSeek-only chỉ nên dùng như benchmark sáng tạo, không nên xuất bản thẳng.**
