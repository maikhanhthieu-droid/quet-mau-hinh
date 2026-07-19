# Contract phương pháp Bulkowski cho Việt Nam

Tài liệu này chuyển nghiên cứu GPT Pro đầu tiên do người dùng cung cấp (`P1`)
thành contract vận hành cho dự án.

P1 được dùng như hướng dẫn phương pháp. Các trích dẫn dạng `turn...` trong P1
không phải nguồn bền vững có thể kiểm tra lại, nên không được chép vào chương
công bố cho tới khi truy được nguồn gốc thật.

## Mục tiêu

Mục tiêu của dự án không chỉ là tạo ra các chương PDF đẹp. Mục tiêu là xây một
tài liệu tham khảo nghiên cứu cho thị trường Việt Nam, giữ đúng tinh thần thực
chứng của Thomas Bulkowski:

- định nghĩa mẫu hình trước khi đo kết quả
- chỉ đo hành vi sau khi có breakout xác nhận
- công khai mẫu số và cách tính từng chỉ tiêu
- tách bối cảnh thị trường, hướng breakout và xu hướng nền
- nói rõ giới hạn dữ liệu, điểm mơ hồ và điều kiện thất bại
- xem thống kê lịch sử là tham khảo mô tả, không phải lời hứa lợi nhuận

Với dự án này, một chương đạt 85-90% mục tiêu "Bulkowski cho Việt Nam" nghĩa là:

```text
định nghĩa mẫu hình có nguồn
-> rule coverage chính thức trong Scanner V2
-> phát hiện tái lập được trên dữ liệu Việt Nam
-> thống kê sau breakout có mẫu số rõ ràng
-> tách regime và bối cảnh thị trường
-> caveat và giới hạn dữ liệu rõ
-> PDF có thể truy ngược từ kết quả về source rule
```

Bộ thống kê bắt buộc cho các chương nằm ở
[`bulkowski-vietnam-statistics-contract.md`](bulkowski-vietnam-statistics-contract.md).
Contract phương pháp quyết định chương có đủ tư cách nghiên cứu hay không;
contract thống kê quyết định chương phải đo gì và trình bày bảng nào.
Framework chấm và dựng chapter nằm ở
[`bulkowski-vietnam-chapter-framework.md`](bulkowski-vietnam-chapter-framework.md).
Release gate/red-team trước khi publish nằm ở
[`bulkowski-vietnam-release-gate.md`](bulkowski-vietnam-release-gate.md).
Bản chốt 85-90% sau P1-P5 nằm ở
[`bulkowski-vietnam-85-90-standard.md`](bulkowski-vietnam-85-90-standard.md).

## Ba làn tài liệu

Mỗi chương phải khai báo một làn chính.

| Làn | Mục tiêu | Được phép nói |
|---|---|---|
| Tài liệu nhận diện mẫu hình | Dạy cách nhận diện và loại bỏ mẫu hình | "Đây là cách mẫu hình được định nghĩa và phát hiện." |
| Tài liệu tham khảo đầu tư | Mô tả hành vi lịch sử sau breakout xác nhận | "Trong bộ dữ liệu này, các sự kiện xác nhận đã hành xử như sau." |
| Hệ thống tín hiệu giao dịch | Sinh entry, exit, position sizing và risk rule có thể thực thi | "Bộ rule này đã được kiểm thử như một chiến lược giao dịch với các giả định đã nêu." |

Rebuild hiện tại chỉ nhắm tới hai làn đầu. Một chương không được tự gọi là hệ
thống giao dịch nếu chưa có giả định thực thi, chi phí, lô giao dịch, biên độ
giá, position sizing và walk-forward validation.

## Gate bắt buộc cho mỗi chương

### 1. Định nghĩa mẫu hình trước khi đo

Detector phải dựa trên rule có nguồn trước khi tính thống kê kết quả.

Bắt buộc có:

- chương/trang/section hoặc bảng nguồn
- evidence excerpt ngắn
- interpreted rule
- numeric threshold hoặc ghi rõ "nguồn không nêu ngưỡng số"
- notes_when_ambiguous
- golden fixtures gồm cả case đạt và case bị loại

Không có provenance thì không được vào scanner chính thức.

### 2. Ranh giới breakout xác nhận

Đo kết quả chỉ bắt đầu sau breakout xác nhận. Chương phải nêu:

- điều kiện breakout
- ngày hoặc index breakout
- hướng breakout
- giá dùng để đo
- cửa sổ hậu-breakout

Hoàn tất hình thái và hiệu quả sau breakout là hai khái niệm khác nhau.

### 3. Chỉ tiêu hậu-breakout

Payload deterministic nên có ít nhất:

- số sự kiện phát hiện
- số sự kiện đủ điều kiện đánh giá
- split theo hướng breakout
- tỷ lệ đạt target và rule tính target
- failure rate, ưu tiên break-even failure 5% khi event model hỗ trợ
- maximum favorable excursion
- maximum adverse excursion
- median/mean move khi có ý nghĩa
- time-to-target hoặc time-to-failure khi đã triển khai
- throwback/pullback rate khi đã triển khai

Mỗi chỉ tiêu phải có mẫu số và quy tắc tính.

### 4. Tách bối cảnh

Tối thiểu, mỗi chương nghiên cứu nên tách theo:

- hướng breakout
- bull/bear regime của VNINDEX
- xu hướng trước khi hình thành mẫu

Khi data layer trưởng thành hơn, bổ sung:

- sàn giao dịch
- ngành
- nhóm thanh khoản
- nhóm vốn hóa
- giai đoạn thị trường

### 5. Toàn vẹn dữ liệu Việt Nam

Chương phải công khai lần chạy có dùng hoặc đã xử lý:

- adjusted OHLCV
- mã hủy niêm yết hoặc chuyển sàn
- lịch sử sàn/trạng thái giao dịch
- corporate actions
- phiên tạm ngừng, hạn chế hoặc kiểm soát giao dịch
- bộ lọc thanh khoản
- dữ liệu benchmark/index

Nếu các lớp này chưa đầy đủ, chương vẫn có thể là research draft, nhưng không
được claim đã đại diện đầy đủ cho thị trường Việt Nam.

### 6. Kiểm soát bias

Pipeline phải chống các lỗi:

- survivorship bias
- look-ahead bias
- viết rule sau khi đã nhìn kết quả
- cherry-pick ví dụ đẹp
- âm thầm đổi breakout rule giữa các pattern
- thử nhiều tolerance rồi chỉ báo cấu hình đẹp nhất
- coi sample mỏng là bằng chứng ổn định

Chính sách xử lý overlap và nested pattern phải được khóa trước khi nhân rộng.

### 7. Lớp robustness

Với pattern template đầu tiên, robustness có thể triển khai theo giai đoạn. Nhưng
trước khi dự án claim 85-90% ở quy mô nhiều pattern, methodology phải có:

- confidence interval hoặc bootstrap interval cho các chỉ tiêu chính
- sensitivity grid cho window/tolerance/liquidity filter
- rolling-origin hoặc walk-forward check nếu rule có tuning
- multiple-comparison correction khi so nhiều pattern, horizon hoặc threshold

Lớp này là bắt buộc cho claim toàn dự án, kể cả khi một chương đầu tiên có thể
ra trước dưới nhãn research reference.

### 8. Contract chương PDF

Mỗi chương PDF nên có:

- mục tiêu nghiên cứu và làn tài liệu
- phạm vi dữ liệu
- important results
- identification guidelines
- source rule provenance
- scanner coverage và constraint chưa xử lý
- thống kê thị trường Việt Nam
- phân tích regime/bối cảnh
- ví dụ gồm cả case mạnh và case yếu/thất bại
- limitations
- metadata tái lập

DeepSeek hoặc AI commentary chỉ được cải thiện diễn đạt. Nó không được thêm số
mới, nâng cấp làn tài liệu, giấu caveat hoặc biến thống kê mô tả thành khuyến
nghị giao dịch.

## Rubric 100 điểm

| Hạng mục | Điểm | Ý nghĩa |
|---|---:|---|
| Mục tiêu và phạm vi | 10 | Chương nói rõ là nhận diện, tham khảo đầu tư hay tín hiệu giao dịch. |
| Chất lượng và độ bao phủ dữ liệu | 15 | Universe, adjusted data, mã hủy/chuyển sàn, trạng thái giao dịch và benchmark rõ ràng. |
| Kiểm soát bias | 15 | Survivorship, look-ahead, corporate actions, đồng bộ dữ liệu và event timing được kiểm soát hoặc công khai. |
| Định nghĩa mẫu hình | 15 | Rule viết trước, có nguồn, có ngưỡng khi có thể, có fixture kiểm thử. |
| Đo kết quả | 10 | Chỉ tiêu hậu-breakout có sample count, target/failure và favorable/adverse movement. |
| Mô hình thống kê | 10 | Có confidence interval, bootstrap, conditional comparison hoặc model-based check khi đủ trưởng thành. |
| Khả thi thị trường | 10 | Trading claim có chi phí, biên độ giá, lô giao dịch, thanh khoản và giả định thực thi. |
| Out-of-sample | 8 | Có walk-forward, rolling-origin hoặc holdout khi rule được tuning. |
| Robustness | 4 | Có sensitivity theo window, tolerance, liquidity và regime. |
| Multiple testing | 8 | Có điều chỉnh data-snooping khi so nhiều rule/pattern/horizon. |
| Minh bạch và tái lập | 5 | Có data version, code path, payload hash, spec hash, seed và limitations. |

Cách đọc điểm:

- 91-100: mạnh hơn tài liệu kiểu Bulkowski, gần chuẩn empirical research hiện đại
- 85-90: mức mục tiêu của dự án
- 70-84: research draft hữu ích nhưng thiếu ít nhất một trụ cột lớn
- dưới 70: chỉ nên xem là bản nháp nội bộ

## Áp dụng hiện tại cho Flag Family

Flag Family là lane hoạt động hiện tại của Scanner V2. Bull Flag đã vượt qua
ngưỡng template sớm và Bear Flag đang được dùng để mở rộng cùng framework sang
breakout xuống:

- đã có rule provenance từ nguồn
- đã có rule coverage chính thức trong Scanner V2
- đã chạy trên OHLCV Việt Nam thật
- target family có nguồn và có local calibration
- đã có split theo VNINDEX regime
- ví dụ gồm cả case đạt tốt và case yếu/thất bại
- AI commentary bị khóa bởi payload deterministic
- đã có PDF output

Tuy nhiên, Flag Family vẫn phải được xem là research-reference draft, chưa phải
hệ thống giao dịch trưởng thành. Riêng Bear Flag phải giữ ngôn ngữ
informational/defensive cho đến khi có lớp thực thi downside riêng.

Các khoảng trống trước khi claim đầy đủ mức 85-90%:

- cần audit chính thức về universe lịch sử và mã hủy/chuyển sàn
- cần note kiểm định chất lượng corporate-action adjustment
- liquidity filter chưa là trục phân tích cấp một
- confidence interval/bootstrap interval chưa vào PDF
- throwback/pullback và time-to-event chưa được báo cáo đầy đủ
- overlap và nested-pattern policy chưa được formal hóa
- sensitivity grid chưa được render
- multiple-comparison correction chưa cần cho một pattern, nhưng sẽ bắt buộc khi
  scale nhiều pattern và threshold

## Hệ quả triển khai

Các bước kỹ thuật tiếp theo nên là:

1. Thêm methodology status block vào mọi V2 monograph payload.
2. Thêm statistics contract block theo
   [`bulkowski-vietnam-statistics-contract.md`](bulkowski-vietnam-statistics-contract.md).
3. Thêm chapter framework score/gates theo
   [`bulkowski-vietnam-chapter-framework.md`](bulkowski-vietnam-chapter-framework.md).
4. Thêm release gate status theo
   [`bulkowski-vietnam-release-gate.md`](bulkowski-vietnam-release-gate.md).
5. Thêm data-integrity block gồm adjusted data, universe, delisting, status
   flags, liquidity filters và benchmark data.
6. Thêm trường làn tài liệu: `identification_reference`,
   `investment_reference`, hoặc `trading_signal_system`.
7. Render limitations trong PDF theo đúng các methodology gate còn thiếu.
8. Thêm confidence interval và sensitivity table trước khi dùng template để
   nhân rộng hàng loạt.
9. Giữ DeepSeek ở vai trò biên tập câu chữ; mọi fact của chương phải đến từ
   payload deterministic.
