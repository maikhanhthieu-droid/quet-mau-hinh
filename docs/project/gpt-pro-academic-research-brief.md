# GPT Pro Academic Research Brief

Mục tiêu của tài liệu này là dùng GPT Pro như một cố vấn học thuật độc lập,
không phải reviewer của codebase. GPT Pro không cần đọc dự án. Nó chỉ cần giúp
thiết kế phương pháp để dự án đạt KPI:

> Bulkowski cho thị trường Việt Nam ở mức 85-90%.

## Cách dùng

Không đưa source code hoặc toàn bộ PDF dự án cho GPT Pro. Chỉ đưa câu hỏi nghiên
cứu, ngữ cảnh mục tiêu, và yêu cầu đầu ra. Kết quả từ GPT Pro sẽ được đưa ngược
lại pipeline nội bộ để tôi chuyển thành contract, thống kê, validator và PDF gate.

## Prompt 1 - Tinh thần học thuật Bulkowski

```text
Bạn là cố vấn học thuật độc lập cho một dự án xây tài liệu nghiên cứu mẫu hình
giá kiểu Thomas Bulkowski, nhưng áp dụng cho thị trường chứng khoán Việt Nam.

Không cần đọc code hoặc PDF dự án. Hãy phân tích ở mức phương pháp:

1. Tinh thần học thuật cốt lõi của Bulkowski là gì?
2. Một nghiên cứu mẫu hình giá nghiêm túc cần tối thiểu những lớp thống kê nào?
3. Những điểm nào thường bị hiểu sai khi cố tái tạo Bulkowski?
4. Làm sao phân biệt giữa:
   - tài liệu nhận diện mẫu hình
   - tài liệu tham khảo đầu tư
   - hệ thống tín hiệu giao dịch
5. Điều kiện tối thiểu để một chương mẫu hình được xem là đạt 85-90% tinh thần
   Bulkowski là gì?

Đầu ra mong muốn:
- Danh sách nguyên tắc phương pháp.
- Checklist chương nghiên cứu.
- Những lỗi nghiêm trọng cần tránh.
- Cách chấm điểm /100.
```

## Prompt 2 - Thiết kế thống kê bắt buộc

```text
Tôi đang xây một chương nghiên cứu cho từng mẫu hình giá, theo phong cách
Bulkowski nhưng dùng dữ liệu thị trường Việt Nam.

Hãy đề xuất bộ thống kê bắt buộc cho mỗi mẫu hình. Giả sử scanner có thể trả về:
- ngày bắt đầu mẫu
- ngày kết thúc mẫu
- hướng phá vỡ
- giá phá vỡ
- mục tiêu giá
- giá cao/thấp sau phá vỡ
- dữ liệu VNINDEX để phân loại bull/bear regime
- nhóm thị trường như VN30/VN100/toàn thị trường

Hãy thiết kế:
1. Bảng kết quả tóm tắt.
2. Bảng phân nhóm theo hướng phá vỡ.
3. Bảng phân nhóm theo bull/bear regime.
4. Bảng thất bại và mục tiêu.
5. Bảng hành vi sau phá vỡ.
6. Các phân vị nên dùng, không chỉ trung bình/trung vị.
7. Các chỉ số cần có để tăng giá trị tham khảo đầu tư.

Đầu ra mong muốn:
- Danh sách chỉ số bắt buộc.
- Công thức đo từng chỉ số.
- Cảnh báo bias hoặc diễn giải sai.
- Mức ưu tiên triển khai.
```

## Prompt 3 - Bias và rủi ro phương pháp

```text
Bạn là red-team thống kê cho một dự án nghiên cứu mẫu hình giá kiểu Bulkowski
áp dụng cho thị trường Việt Nam.

Hãy chỉ ra các bias và lỗi phương pháp có thể làm kết quả nghiên cứu bị thổi
phồng hoặc gây ngộ nhận đầu tư.

Các chủ đề cần xem xét:
- survivorship bias
- lookahead bias
- overlap giữa các mẫu
- chọn ví dụ đẹp
- thanh khoản thấp
- cổ phiếu bị hủy niêm yết hoặc thay đổi dữ liệu
- bull/bear regime
- chọn VN30/VN100/toàn thị trường
- target-hit rate
- failure rate
- sau phá vỡ dùng bao nhiêu phiên
- so sánh giữa các mẫu hình

Đầu ra mong muốn:
- 15 rủi ro phương pháp lớn nhất.
- Cách phát hiện từng rủi ro trong pipeline.
- Cách giảm thiểu từng rủi ro.
- Rủi ro nào phải chặn PDF, rủi ro nào chỉ cần ghi chú.
```

## Prompt 4 - Chapter Contract 85-90

```text
Hãy thiết kế một chapter contract cho dự án "Bulkowski cho Việt Nam".

Một chương chỉ được xem là đạt KPI 85-90 nếu đủ điều kiện học thuật và đủ giá trị
tham khảo đầu tư, nhưng không biến thành khuyến nghị giao dịch.

Hãy đề xuất contract gồm:
1. Điều kiện dữ liệu.
2. Điều kiện rule provenance.
3. Điều kiện scanner coverage.
4. Điều kiện thống kê.
5. Điều kiện ví dụ biểu đồ.
6. Điều kiện diễn giải bằng AI.
7. Điều kiện governance.
8. Điều kiện không được công bố nếu thiếu.

Đầu ra mong muốn:
- Checklist pass/fail.
- Severity của từng lỗi.
- Trường nào cần xuất ra payload JSON.
- Trường nào cần xuất hiện trong PDF.
```

## Prompt 5 - Từ nghiên cứu sang tham khảo đầu tư

```text
Một tài liệu mẫu hình giá có thể dùng làm tham khảo đầu tư khi nào?

Hãy thiết kế thang phân loại:
- research-only
- watchlist-reference
- investment-reference
- tradable-setup
- not-usable

Với mỗi cấp, hãy nêu:
1. Điều kiện định lượng.
2. Điều kiện định tính.
3. Rủi ro cần ghi chú.
4. Những kết luận được phép viết.
5. Những kết luận bị cấm viết.

Ngữ cảnh: dự án mô phỏng tinh thần Thomas Bulkowski cho thị trường Việt Nam,
không đưa khuyến nghị mua/bán trực tiếp.
```

## Cách dùng kết quả GPT Pro trong dự án

Sau khi có phản hồi từ GPT Pro, không đưa thẳng vào PDF. Cần chuyển thành:

1. `bulkowski-vietnam-methodology-contract.md`
2. schema payload mới cho chapter quality gate
3. validator pass/fail cho mỗi chương
4. checklist thống kê bắt buộc
5. prompt DeepSeek theo từng section
6. render PDF chỉ khi chapter gate đạt

## Nguyên tắc kiểm soát

- GPT Pro không được quyết định số liệu của dự án.
- GPT Pro không được bịa quy tắc nguồn.
- GPT Pro chỉ giúp thiết kế phương pháp và checklist.
- Mọi số liệu cuối cùng phải sinh từ code trong repo.
- Mọi rule cuối cùng phải có provenance hoặc bị loại khỏi scanner chính thức.
