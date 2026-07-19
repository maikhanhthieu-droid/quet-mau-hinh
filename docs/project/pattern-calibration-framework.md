# Pattern Calibration Framework

## Mục tiêu

Framework này dùng để nội địa hóa từng mẫu hình cho thị trường Việt Nam mà
không biến quá trình nghiên cứu thành tham số hóa hậu nghiệm.

Nguyên tắc chính:

```text
Giữ rule nhận diện từ sách gốc làm provenance
-> chạy trên active Market Stats universe
-> đo target family cố định theo từng pattern family
-> chạy calibration riêng cho từng chapter/variant đã hoàn thành
-> chọn mốc headline bằng rule công khai
-> kiểm tra liquidity/regime/overlap/path-quality
-> mới viết chapter PDF
```

Đây là calibration, không phải optimization. Một target chỉ được chọn nếu qua
cổng thống kê đã khóa trước và không được gọi là "mục tiêu cơ sở" chỉ vì tiện.
Từ sau audit target final-chapters, mọi chapter phải chạy
`scanner/run_final_chapters_target_calibration_audit.py` trước khi render lại
PDF hoặc promote final.

## Target family hiện tại

| Pattern family | Target family | Ghi chú |
|---|---:|---|
| Flag Family | `0.46x`, `0.5x`, `0.75x`, `1.0x` | `0.46x` là Bulkowski-adjusted benchmark; `1.0x` chỉ là legacy full-pole benchmark |
| Triangle Family | `0.5x`, `0.75x`, `1.0x` | Ascending/Descending được phép dùng `1.0x` làm mốc nguồn/headline nếu full-height pass; Symmetrical hiện chỉ dùng `0.5x` như mốc thận trọng |
| Double Bottom Family | `0.5x`, `0.75x`, `1.0x` | Các biến thể Double Bottom đã pass full-height calibration nên dùng `1.0x` làm mốc nguồn/headline; `0.5x` là mốc thận trọng |
| Double Top Family | `0.5x`, `0.75x`, `1.0x` | Đọc như defensive/informational; `0.5x` là mốc thận trọng cho đến khi trích đủ target stats nguồn |
| Wedge Family | `0.5x`, `0.75x`, `1.0x` | Measure rule nguồn dùng cực trị hình học trong nêm, không tương đương fixed multiple; `0.5x` chỉ là mốc thận trọng/diagnostic |
| Unknown / draft pattern | `0.5x`, `0.75x`, `1.0x`, `1.25x` | Chỉ dùng diagnostic cho đến khi có provenance family riêng |

## Rule chọn mốc headline

Mốc headline của chapter phải được quyết định sau khi so với source rule. Không
được tự động chọn target đầu tiên trong family. Thứ tự quyết định:

1. Nếu source rule là fractional-adjusted như Flag `0.46x`, dùng mốc nguồn đó
   khi pass gate.
2. Nếu source rule là full-height `1.0x` và full-height pass gate, dùng `1.0x`
   làm mốc nguồn/headline; `0.5x` chỉ là mốc thận trọng.
3. Nếu full-height không pass hoặc source stats chưa trích đủ, không phong
   headline; dùng mốc thận trọng/diagnostic và nói rõ.
4. Nếu source rule là cực trị hình học, như Wedges, không quyết định bằng fixed
   multiple; fixed multiple chỉ là diagnostic.

| Gate | Ngưỡng hiện tại |
|---|---:|
| `N` tối thiểu | `100` cho headline pattern |
| Wilson lower bound của target hit | `>= 55%` |
| Target-first-before-adverse-5% | `>= 35%` |
| Failure 5% | `<= 30%` |

Nếu không target nào pass, chapter không được phong mốc headline. Khi đó chỉ
báo target sensitivity và ghi trạng thái `no_base_target_pass`.

## Audit target final-chapters

Artifact chuẩn:

- `artifacts/scanner_v2/final_chapters_target_calibration_audit/chapter_target_calibration_summary.json`
- `artifacts/scanner_v2/final_chapters_target_calibration_audit/chapter_target_band_rows.csv`

Kết quả gần nhất:

- Flag: giữ `0.46x` làm mốc nguồn/headline.
- Ascending Triangle và Descending Triangle: `1.0x` full-height pass nên dùng
  làm mốc nguồn/headline.
- Symmetrical Triangle: chưa phong `1.0x`; dùng `0.5x` như mốc thận trọng.
- Double Bottom variants: `1.0x` pass nên dùng làm mốc nguồn/headline.
- Double Top variants: giữ `0.5x` như mốc thận trọng cho đến khi target stats
  nguồn được trích riêng.
- Wedges: không dùng `0.5x` làm mốc nguồn; cần đọc fixed multiple như lớp
  diagnostic vì source rule là cực trị hình học.

## Split bắt buộc cho Flag Family

Bull Flag hiện là mẫu chuẩn của Flag Family. Bear Flag dùng cùng framework
nhưng phải được diễn giải như informational/defensive reference cho đến khi có
lớp thực thi downside riêng. Các lát cắt bắt buộc:

- `liquidity_bucket`: `high`, `mid`, `low`
- `primary_60d`: event chính sau cooldown 60 ngày và repeat event
- `path_proxy_clean` / `path_proxy_flagged`
- `corp_proxy_clean` / `corp_proxy_flagged`

Các split này không được dùng để cherry-pick target headline. Chúng chỉ dùng để
kiểm tra robustness và viết caveat.

## Kết quả Bull Flag hiện tại

Theo artifact `artifacts/scanner_v2/research_support/target_calibration_decisions.json`:

| Metric | Giá trị |
|---|---:|
| Selected target | `0.46x` |
| Role | `bulkowski_adjusted_base` |
| N | `110` |
| Target hit | `70.00%` |
| Wilson lower bound | `60.88%` |
| Target-first-before-adverse-5% | `42.73%` |
| Failure 5% | `24.55%` |
| MFE/MAE median ratio | `1.56` |

Kết luận vận hành: Bull Flag có thể dùng `0.46x pole` làm base target cho bản
chapter hiện tại, trong khi `0.5x` là rounded local base và `1.0x` chỉ là
legacy benchmark. Bear Flag sẽ kế thừa cùng target family để hoàn thiện Flag
Family, nhưng không được viết như cơ hội đầu tư long/short đối xứng trên thị
trường cơ sở Việt Nam.

## Cảnh báo

- Không dùng target family để tối ưu PnL.
- Không xếp hạng toàn bộ pattern trước khi mỗi pattern có calibration riêng.
- Không dùng historical VN30/VN100 membership làm headline khi dữ liệu không đủ.
- Không claim full point-in-time universe trong phạm vi `available_series_descriptive`.
- Bearish/downside pattern trên cash equities Việt Nam mặc định là
  informational/defensive reference cho đến khi có instrument và execution
  model phù hợp.
