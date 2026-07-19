# Contract thống kê Bulkowski cho Việt Nam

Tài liệu này chuyển nghiên cứu GPT Pro thứ hai do người dùng cung cấp (`P2`)
thành contract thống kê cho mọi chương mẫu hình.

P2 được dùng như hướng dẫn phương pháp. Các trích dẫn dạng `turn...` trong P2
không phải nguồn bền vững có thể kiểm tra lại, nên không được chép vào chương
công bố cho tới khi truy được nguồn gốc thật.

## Mục tiêu

Một chương mẫu hình không được chỉ là trang mô tả nhận diện hoặc backtest tín
hiệu. Nó phải là một hồ sơ thực nghiệm của từng mẫu hình:

```text
pattern instance
-> breakout metadata
-> OHLC path sau breakout
-> outcome metrics
-> context splits
-> uncertainty / sample limits
-> PDF chapter
```

Contract này bổ sung cho
[`bulkowski-vietnam-methodology-contract.md`](bulkowski-vietnam-methodology-contract.md):

- methodology contract quyết định chương có đủ tư cách nghiên cứu hay không
- statistics contract quyết định chương phải đo gì và trình bày bảng nào
- chapter framework quyết định cách chấm điểm, gate loại trực tiếp, pipeline và
  biểu đồ cần có: [`bulkowski-vietnam-chapter-framework.md`](bulkowski-vietnam-chapter-framework.md)
- release gate quyết định pass/fail, artifact JSON/CSV/PDF và red-team risks:
  [`bulkowski-vietnam-release-gate.md`](bulkowski-vietnam-release-gate.md)

## Event Model Bắt Buộc

Mỗi pattern instance phải được xem như một event có tối thiểu:

- `symbol`
- `pattern_key`
- `formation_start_date`
- `formation_end_date`
- `breakout_date`
- `breakout_direction`
- `breakout_price_ref`
- `breakout_price_exec`
- `target_price`
- `post_breakout_ohlcv_path`
- `regime_at_breakout`
- `market_group`
- `scanner_version`
- `spec_hash`

Không được chỉ lưu high/low sau breakout. Nếu không có OHLC path theo ngày sau
breakout thì không thể đo đúng:

- target đạt trước hay adverse move xảy ra trước
- retest trong 30 phiên
- time-to-target
- time-to-retest
- MFE/MAE theo từng horizon
- close-based return
- benchmark excess theo horizon

## Chuẩn Hóa Dấu Return

Mọi return chính trong chương phải quy về lợi suất cùng chiều breakout.

| Hướng breakout | Return cùng chiều |
|---|---|
| Breakout lên | giá tăng là dương |
| Breakout xuống | giá giảm là dương |

Chuẩn này giúp các thống kê median, quantile, failure, target hit, benchmark
excess và regime split đọc cùng một chiều.

## Hai Anchor Giá

Mỗi event phải lưu hai anchor:

| Anchor | Ý nghĩa | Dùng cho |
|---|---|---|
| `B_ref` | giá breakout do scanner xác nhận | thống kê tham chiếu theo cấu trúc mẫu hình |
| `B_exec` | giá mở cửa phiên kế tiếp sau breakout | thống kê gần khả năng thực thi hơn |

Headline table nên ưu tiên `B_exec` khi dữ liệu đủ. Appendix hoặc audit panel có
thể in thêm `B_ref` để bám sát scanner.

Nếu chưa có `B_exec`, chương phải ghi rõ đang dùng `B_ref` và không được gọi kết
quả đó là thống kê thực thi.

## Regime

Regime chính nên là VNINDEX broad-market regime theo point-in-time tại ngày
breakout.

Chuẩn mục tiêu:

- bear khi VNINDEX giảm ít nhất 20% từ peak gần nhất
- bull khi VNINDEX tăng ít nhất 20% từ trough gần nhất
- mọi nhãn regime phải được tính bằng dữ liệu sẵn có tại ngày breakout

Có thể thêm sensitivity bằng 200DMA hoặc slope của chỉ số, nhưng đó là lớp phụ.
Không được dùng thông tin tương lai để gắn nhãn regime.

## Ultimate Move Và Censoring

Khi triển khai ultimate high/low kiểu Bulkowski:

- `ultimate_high`: đỉnh cao nhất trước khi close giảm ít nhất 20% từ đỉnh đó
- `ultimate_low`: đáy thấp nhất trước khi close tăng ít nhất 20% từ đáy đó

Nếu event thiếu hậu dữ liệu, bị delist, ngừng giao dịch hoặc hết mẫu trước khi
đủ điều kiện xác nhận ultimate, event phải được đánh dấu `censored`.

Không được coi event bị thiếu dữ liệu là quan sát hoàn chỉnh.

## Năm Bảng Lõi

### 1. Bảng tóm tắt

Rows:

- `All`
- `VN30`
- `VN100 ex VN30`
- `Outside VN100`

Columns bắt buộc:

- `N event`
- `N ticker`
- tỷ lệ breakout lên
- tỷ lệ bull regime
- mean favorable move
- median favorable move
- Q25/Q50/Q75 favorable move
- break-even failure 5%
- target hit
- retest 30 phiên
- median MAE20
- signed close return 20/60 phiên
- excess vs VNINDEX 20/60 phiên
- concentration metric

### 2. Bảng theo hướng phá vỡ

Rows:

- `Up breakout`
- `Down breakout`

Columns bắt buộc:

- `N event`
- `N ticker`
- bull share
- bear share
- favorable move quantiles
- failure ladder 5/10/20/40
- target hit
- target multiple
- retest rate
- median days-to-target
- excess return 20/60 phiên

### 3. Bảng theo regime

Rows:

- `Bull`
- `Bear`
- nếu đủ mẫu: `Bull-Up`, `Bull-Down`, `Bear-Up`, `Bear-Down`

Columns bắt buộc:

- `N event`
- `N ticker`
- breakout up share
- favorable quantiles
- adverse quantiles
- target hit
- failure ladder
- retest
- close return 20/60
- benchmark excess

### 4. Bảng thất bại và mục tiêu

Rows:

- `All`
- `Up`
- `Down`
- nếu đủ mẫu: split thêm `Bull`/`Bear`

Columns bắt buộc:

- break-even failure 5%
- failure 10%
- failure 20%
- failure 40%
- target hit
- median target distance
- median target multiple
- overshoot conditional on hit
- target-first-before-adverse-5%

### 5. Bảng hành vi sau phá vỡ

Rows:

- `With retest`
- `Without retest`
- horizons `5`, `10`, `20`, `60` phiên

Columns bắt buộc:

- throwback/pullback rate
- median days-to-retest
- MFE5/10/20/60
- MAE5/10/20/60
- signed close return 5/10/20/60
- target hit with retest vs without retest
- benchmark excess with retest vs without retest

## Nhóm Thị Trường

Để so sánh giữa nhóm, dùng các nhóm không chồng lặp:

- `VN30`
- `VN100 ex VN30`
- `Outside VN100`

`All` là master row. Nếu in `VN100`, nó chỉ là reference panel, không phải
comparison panel, vì nó chồng lặp với `VN30`.

## Ngưỡng Sample

| Quy mô cell | Cách trình bày |
|---:|---|
| `N >= 100` | đủ chất liệu cho headline chapter |
| `N >= 30` | được in tỷ lệ và so sánh cell |
| `10 <= N < 30` | chỉ exploratory; in count, median, IQR |
| `N < 10` | không xếp hạng, không diễn giải mạnh |

Nếu một panel phụ dưới 30 event, PDF phải gắn nhãn exploratory.

## Công Thức P0

Gọi:

- `B` = anchor price đang dùng, ưu tiên `B_exec` cho headline
- `T` = target price
- `Close_h`, `High_h`, `Low_h` = close/high/low sau `h` phiên
- `I0`, `Ih` = VNINDEX close tại ngày breakout và sau `h` phiên
- `dir` = `up` hoặc `down`

| Chỉ số | Công thức |
|---|---|
| N event | số event breakout xác nhận |
| N ticker | số mã cổ phiếu duy nhất |
| breakout up share | `count(dir = up) / N` |
| bull share | `count(regime = bull) / N` |
| favorable ultimate, up | `(UltimateHigh - B) / B` |
| favorable ultimate, down | `(B - UltimateLow) / B` |
| signed close return H, up | `(Close_H - B) / B` |
| signed close return H, down | `(B - Close_H) / B` |
| MFE_H, up | `(max(High_1:H) - B) / B` |
| MFE_H, down | `(B - min(Low_1:H)) / B` |
| MAE_H, up | `(B - min(Low_1:H)) / B` |
| MAE_H, down | `(max(High_1:H) - B) / B` |
| failure k | `mean(favorable_ultimate < k)` với `k = 5%, 10%, 20%, 40%` |
| target distance, up | `(T - B) / B` |
| target distance, down | `(B - T) / B` |
| target hit | `mean(favorable_ultimate >= target_distance)` |
| target multiple | `favorable_ultimate / target_distance` |
| overshoot on hit | `median((favorable_ultimate - target_distance) / target_distance | target_hit)` |
| days to target | phiên đầu tiên favorable extreme chạm target; không chạm thì censored |
| target-first-before-adverse-5% | `mean(days_to_target < days_to_adverse_5%)` |
| retest 30, up | `min(Low_1:30) <= B * (1 + epsilon)` |
| retest 30, down | `max(High_1:30) >= B * (1 - epsilon)` |
| excess return H | signed close return H của cổ phiếu trừ signed VNINDEX return H |
| outperformance rate | `mean(excess_return_H > 0)` |
| concentration HHI | `sum(w_symbol^2)` với `w_symbol = event_count_symbol / N` |
| top10 share | tỷ trọng event của 10 mã xuất hiện nhiều nhất |

Retest tolerance `epsilon` phải được khóa trong payload. Giá trị khởi đầu hợp lý:
1 tick hoặc khoảng 0.25-0.5%, tùy dữ liệu giá.

## Quantile Và Uncertainty

Mỗi chapter phải có quantile layer, không chỉ mean/median.

| Biến | Phân vị bắt buộc |
|---|---|
| favorable ultimate | Q10, Q25, Q50, Q75, Q90 |
| signed close return 20/60 | Q10, Q25, Q50, Q75, Q90 |
| MFE20, MFE60 | Q10, Q25, Q50, Q75, Q90 |
| MAE20, MAE60 | Q10, Q25, Q50, Q75, Q90 |
| target multiple | Q25, Q50, Q75 |
| days to target | Q25, Q50, Q75 và survival median khi có |
| days to retest | Q25, Q50, Q75 |
| hit/fail/retest/outperform rates | point estimate + Wilson 95% CI |

Nên in thêm:

- quantile mở rộng Q1/Q5/Q95/Q99 cho biến liên tục chính khi N đủ lớn
- IQR = Q75 - Q25
- tail spread = Q90 - Q10
- Bowley skewness ở lớp P2 khi cần: `(Q75 + Q25 - 2*Q50) / (Q75 - Q25)`

Với time-to-event, không được chỉ tính median trên các event đã hit. Event chưa
hit phải được giữ là right-censored, hoặc tối thiểu phải in song song:

- median among hits
- probability not-yet-hit by 20/60/120 sessions

## P0 / P1 / P2

### P0 - Bắt buộc để gọi là investment-reference chapter

- event-level OHLC path point-in-time
- `B_ref` và `B_exec`
- năm bảng lõi
- split theo breakout direction
- split theo VNINDEX regime
- market-group panel không chồng lặp
- favorable move
- signed close return 20/60
- MFE20/60
- MAE20/60
- failure ladder 5/10/20/40
- target hit
- target-first-before-adverse-5%
- Race(+5%,-5%)
- Race(Target,-5%)
- RTR = FE/target distance
- retest 30 phiên
- quantiles Q10/Q25/Q50/Q75/Q90
- Wilson CI cho tỷ lệ
- bootstrap CI cho median/quantiles
- benchmark excess vs VNINDEX
- N event, N ticker
- concentration metric

Nếu thiếu cụm P0, chương chỉ nên được gọi là nhận diện hoặc research draft,
không phải investment-reference chapter.

### P1 - Nên có để chương đáng dùng hơn

- Kaplan-Meier cho time-to-target
- bảng 2x2 `Bull-Up`, `Bull-Down`, `Bear-Up`, `Bear-Down`
- sensitivity test: mỗi mã chỉ giữ một event trong rolling 60 phiên
- outperformance rate vs VNINDEX
- stop-hit rate theo stop library cố định
- version hóa scanner và refresh out-of-sample hằng năm
- breakout-volume panel khi volume rule được mở rộng

### P2 - Nâng cấp bản sắc Việt Nam

- true bust statistics khi có upper/lower pattern bounds
- yearly-range position của breakout
- market-cap/liquidity proxy ngoài VN30/VN100
- stop libraries theo pattern height/ATR
- volume trend trong thời gian hình thành mẫu
- cross-pattern ranking
- multiple-testing adjustment khi công bố top pattern hoặc best regime
- ECDF/forest/KM/heatmap/scatter diagnostic charts theo chapter framework

## Bias Cần Chặn

Statistics layer phải chặn rõ:

- scanner mơ hồ hoặc đổi rule không version hóa
- data snooping và multiple testing
- event clustering theo cùng mã hoặc cùng phase thị trường
- đọc long-horizon mean như sự thật ổn định
- survivorship và delisting bias
- raw price tạo breakout/failure giả quanh corporate actions
- nhầm target hit với target-first
- bỏ qua retest sau breakout

Tối thiểu, mỗi statistics payload phải lưu:

- `scanner_version`
- `spec_hash`
- `data_version`
- `event_window`
- `anchor_mode`
- `regime_method`
- `sample_policy`
- `overlap_policy`
- `censoring_policy`
- `retest_epsilon`
- `benchmark_symbol`
- `ci_method`
- `bootstrap_seed`
- `release_status`
- `claim_metric_links`
