# Chuẩn 85-90% Bulkowski cho Việt Nam

Tài liệu này là bản chốt sau năm nghiên cứu GPT Pro (`P1` đến `P5`). Nó gom
methodology, statistics, chapter framework và release gate thành một chuẩn vận
hành duy nhất cho dự án.

Các trích dẫn dạng `turn...` trong nghiên cứu GPT Pro không phải nguồn bền vững
có thể kiểm tra lại, nên không được chép vào chương công bố cho tới khi truy
được nguồn gốc thật.

## Định Nghĩa Ngắn

Một chapter đạt 85-90% tinh thần Bulkowski khi nó:

- mô tả mẫu hình bằng rule cố định, có provenance và versioning
- chỉ đo outcome sau breakout xác nhận
- đo hậu breakout bằng nhiều lớp outcome chuẩn hóa
- tách subgroup theo breakout direction, bull/bear regime và market group
- có point-in-time universe, delisted handling và corporate-action audit
- có event-path OHLCV sau breakout để đo time-to-target, throwback/pullback và censoring
- có quantiles, uncertainty, red-team checks và release gate
- vẫn từ chối viết như tín hiệu mua/bán hoặc khuyến nghị giao dịch

Nếu thiếu lớp cuối cùng về entry/exit/size/cost/slippage/OOS/walk-forward/PBO,
chapter không được gọi là trading system.

## Stack Contract Chính Thức

Các tài liệu dưới đây là stack vận hành:

1. [`bulkowski-vietnam-methodology-contract.md`](bulkowski-vietnam-methodology-contract.md)
2. [`bulkowski-vietnam-statistics-contract.md`](bulkowski-vietnam-statistics-contract.md)
3. [`bulkowski-vietnam-chapter-framework.md`](bulkowski-vietnam-chapter-framework.md)
4. [`bulkowski-vietnam-release-gate.md`](bulkowski-vietnam-release-gate.md)
5. [`scanner-v2-book-to-scanner-contract.md`](scanner-v2-book-to-scanner-contract.md)

Tài liệu hiện tại là bản tổng hợp cấp cao. Khi có mâu thuẫn, ưu tiên:

```text
release gate > chapter framework > statistics contract > methodology contract > task list
```

## Các Trường Bắt Buộc Trong JSON Payload

| Trường | Bắt buộc | Ghi chú |
|---|---|---|
| `chapter_id`, `pattern_id`, `pattern_name` | Có | định danh chapter |
| `data_snapshot_id` | Có | point-in-time reproducibility |
| `rule_id`, `rule_version`, `rule_hash` | Có | provenance của scanner |
| `universe_definition` | Có | HOSE/HNX/UPCoM/common shares only... |
| `sample_start`, `sample_end` | Có | cửa sổ dữ liệu |
| `regime_definition_id`, `regime_params` | Có | công thức bull/bear |
| `eligible_symbol_days`, `processed_symbol_days`, `coverage_rate` | Có | coverage audit |
| `n_total`, `n_symbol`, `n_up`, `n_down`, `n_bull`, `n_bear` | Có | headline counts |
| `summary_metrics` | Có | move/failure/target/tbpb/MAE/MFE |
| `quantile_metrics` | Có | P1..P99 cho biến cốt lõi |
| `direction_table`, `regime_table`, `market_group_table` | Có | subgroup outputs |
| `failure_target_table`, `post_breakout_table` | Có | tables chuyên đề |
| `overlap_rate`, `top10_symbol_share`, `hhi_symbol` | Có | bias diagnostics |
| `censor_horizon_days`, `censor_rate` | Có | time-to-event governance |
| `risk_flags` | Có | danh sách lỗi red-team |
| `classification`, `chapter_score`, `publish_status` | Có | quyết định công bố |
| `claim_metric_links` | Có | ràng buộc mọi AI claim về metric/caveat |

## Các Trường Bắt Buộc Trong PDF

| Trường PDF | Bắt buộc | Nội dung tối thiểu |
|---|---|---|
| Universe | Có | định nghĩa toàn thị trường hoặc rổ nào |
| Sample period | Có | từ ngày nào đến ngày nào |
| Rule provenance | Có | rule version, snapshot ID |
| Definitions | Có | breakout, failure, target, horizon, regime |
| Summary table | Có | headline metrics |
| Direction table | Có | split up/down |
| Regime table | Có | split bull/bear |
| Failure-target table | Có | failure + target-hit |
| Post-breakout table | Có | time-to-target, MAE, retrace, tb/pb |
| Distribution section | Có | quantiles, IQR, cảnh báo tail |
| Example charts | Có | theo seeded stratified selection protocol |
| Caveats | Có | bull/bear rule, delisting, liquidity, target bias |
| Classification label | Có | `research-only`, `investment-reference`, ... |
| Non-advice disclaimer | Có | không phải khuyến nghị giao dịch |

## Thang Phân Loại Tài Liệu

| Cấp tài liệu | Điều kiện định lượng | Điều kiện định tính | Kết luận được phép viết | Kết luận bị cấm viết |
|---|---|---|---|---|
| `not-usable` | thiếu PTI data, provenance hoặc fail critical | không tái lập được | "Chapter chưa đủ điều kiện công bố." | mọi nhận định đầu tư |
| `research-only` | có rule và summary stats cơ bản nhưng thiếu path/liquidity/OOS | tốt cho nhận diện và mô tả | "Mẫu hình được nhận diện như sau và có phân phối lịch sử như sau." | "Pattern này đáng theo dõi để mua/bán." |
| `watchlist-reference` | có P0, direction/regime subgroup, quantiles | có ích cho theo dõi có điều kiện | "Trong subgroup X, lịch sử có xu hướng..." | "Xác suất thắng đủ để giao dịch." |
| `investment-reference` | có P0 đầy đủ, PTI universe, delisted handling, path metrics, uncertainty, red-team pass | có giá trị tham khảo đầu tư nhưng không có execution rules | "Có thể dùng như tài liệu tham khảo đầu tư có điều kiện và caveat rõ." | "Nên mua khi breakout." |
| `tradable-setup` | thêm entry/exit/size/cost/slippage/OOS/walk-forward/PBO | là hệ thống riêng, không còn là chapter Bulkowski thuần | "Đây là một setup cần tài liệu riêng về thực thi." | dùng chapter mô tả để ngụy trang thành khuyến nghị cá nhân hóa |

## Rubric Chấm Điểm /100

| Tiêu chí | Trọng số | Cách chấm |
|---|---:|---|
| Dữ liệu point-in-time và delisted handling | 20 | đủ universe, listing lifecycle, corporate actions, snapshot |
| Rule provenance | 12 | rule version/hash/params/changelog đầy đủ |
| Scanner coverage và audit | 10 | coverage cao, có error log và manual audit |
| Thống kê cốt lõi | 20 | đủ P0 metrics và subgroup tables |
| Phân phối và uncertainty | 10 | quantiles, IQR, CI, censoring, KM |
| Bias controls | 18 | pass các red-team checks lớn |
| Ví dụ biểu đồ | 5 | seeded stratified, không cherry-pick |
| AI interpretation discipline | 5 | không bịa causal claim, không trade language |
| Governance và reproducibility | 10 | reviewer, publish status, payload/PDF alignment |

Cách tính:

```text
Score = sum(weight_j * subscore_j / 100)
```

Hard gates:

- bất kỳ lỗi `Critical` nào: `publish_status = BLOCK`
- muốn đạt 85-90: phải đủ toàn bộ P0, không có Critical fail, classification tối thiểu là `investment-reference`
- 70-84: tối đa `watchlist-reference`
- dưới 70: không nên công bố ngoài nội bộ

## Chỉ Số P0 Được Chốt Sau P5

| Chỉ số | Ý nghĩa |
|---|---|
| `n_total`, `n_symbol` | độ dày và độ rộng mẫu |
| `coverage_rate` | coverage của scanner/data |
| `width_days`, `height_pct` | kích thước mẫu hình |
| `target_dist` | khoảng cách target theo rule pattern-specific |
| `fav_exc`, `adv_exc` | favorable/adverse excursion cùng chiều breakout |
| `fail_5_rate` | failure gần định nghĩa break-even failure của Bulkowski |
| `target_hit_rate` | tỷ lệ đạt measure rule |
| `tbpb_30_rate` | throwback/pullback trong 30 phiên |
| `t_hit` | time-to-target, có censoring |
| `mae_before_H`, `mfe_before_H` | risk/path profile theo horizon |
| `symbol_concentration` | top10 share hoặc HHI |
| `CI_95` | Wilson cho tỷ lệ, bootstrap cho median/quantile |

Nếu có dữ liệu `open+1`, chapter phải tách:

- `bulkowski_move_open1`: đo từ open phiên sau breakout
- `scanner_move_breakout`: đo từ breakout price

Nếu không có `open+1`, chapter phải nói rõ đang dùng gốc đo khác Bulkowski.

## Bảng Phân Vị Bắt Buộc

Các biến dưới đây phải có phân vị:

```text
P1, P5, P10, P25, P50, P75, P90, P95, P99
```

Áp dụng cho:

- `width_days`
- `height_pct`
- `target_dist`
- `fav_exc`
- `adv_exc`
- `t_hit` trong tập hit, kèm KM cho censoring
- `mae_before_H`
- `retrace_ratio`

## Bảng Xuất Bản Bắt Buộc

Mỗi chapter `investment-reference` phải có:

- bảng kết quả tóm tắt
- bảng phân nhóm theo hướng phá vỡ
- bảng phân nhóm theo bull/bear regime
- bảng thất bại và target-hit
- bảng hành vi sau phá vỡ
- distribution/visualization section
- red-team/gate section
- reproducibility section

## Checklist Pseudo-SQL Cho Validator

Các audit này nên được chuyển thành validator ở giai đoạn triển khai.

```sql
-- 1) Lookahead bias: mọi feature phải kết thúc không muộn hơn breakout_date
SELECT event_id, feature_name
FROM feature_audit
WHERE source_max_trade_date > breakout_date;

-- 2) Survivor bias ở universe: có mã từng eligible nhưng không bao giờ được scan/xuất
SELECT u.symbol
FROM historical_universe_pti u
LEFT JOIN chapter_events e
  ON e.symbol = u.symbol
 AND e.breakout_date BETWEEN u.eligible_from AND u.eligible_to
WHERE u.pattern_eligible = 1
GROUP BY u.symbol
HAVING COUNT(e.event_id) = 0
   AND MAX(u.delisted_flag) = 1;

-- 3) Historical constituent leakage: market_group của event phải bằng membership point-in-time
SELECT e.event_id, e.symbol, e.market_group, m.market_group AS expected_group
FROM chapter_events e
JOIN index_membership_pti m
  ON m.symbol = e.symbol
 AND e.breakout_date BETWEEN m.effective_from AND m.effective_to
WHERE e.market_group <> m.market_group;

-- 4) Overlap cùng mã
WITH ordered AS (
  SELECT event_id, symbol, start_date, end_date,
         LEAD(start_date) OVER (PARTITION BY symbol ORDER BY start_date) AS next_start
  FROM chapter_events
)
SELECT *
FROM ordered
WHERE next_start <= end_date;

-- 5) Horizon mining: một pattern không được dùng nhiều H rồi chỉ chọn kết quả đẹp
SELECT pattern_id, COUNT(DISTINCT horizon_days) AS n_horizons
FROM chapter_results
GROUP BY pattern_id
HAVING COUNT(DISTINCT horizon_days) > 1;

-- 6) Missing path data: không đủ OHLC sau breakout cho time-to-target/MAE/retrace
SELECT e.event_id
FROM chapter_events e
LEFT JOIN post_breakout_path p
  ON p.event_id = e.event_id
GROUP BY e.event_id
HAVING COUNT(p.trade_date) < :required_min_bars;

-- 7) Symbol concentration: một vài mã chi phối chapter
WITH c AS (
  SELECT symbol, COUNT(*) AS n
  FROM chapter_events
  GROUP BY symbol
),
r AS (
  SELECT symbol, n,
         ROW_NUMBER() OVER (ORDER BY n DESC) AS rk,
         SUM(n) OVER () AS total_n
  FROM c
)
SELECT SUM(n) * 1.0 / MAX(total_n) AS top10_symbol_share
FROM r
WHERE rk <= 10;

-- 8) Example selection phải seeded và stratified
SELECT chapter_id, COUNT(*) AS bad_examples
FROM example_selection
WHERE selection_mode <> 'seeded_stratified_random'
GROUP BY chapter_id
HAVING COUNT(*) > 0;

-- 9) Corporate-action revision audit
SELECT symbol, action_date, COUNT(DISTINCT snapshot_id) AS n_versions
FROM corp_action_snapshot_log
GROUP BY symbol, action_date
HAVING COUNT(DISTINCT snapshot_id) > 1;

-- 10) Failure definition drift
SELECT chapter_id, COUNT(DISTINCT failure_definition_id) AS n_defs
FROM chapter_results
GROUP BY chapter_id
HAVING COUNT(DISTINCT failure_definition_id) > 1;
```

## Trạng Thái Hiện Tại Của Flag Family

Theo chuẩn chốt này, `bull_flags` hiện là `watchlist-reference` đến
`investment-reference` trong phạm vi dữ liệu sẵn có, còn `bear_flags` là
`informational/defensive-reference` candidate. Các mẫu non-Flag dùng logic V2
cũ đã được đưa ra khỏi lane hoạt động cho đến khi được xây lại theo chuẩn
matrix mới.

Lý do:

- chưa có PTI universe đầy đủ gồm delisted/halted, nên kết luận dùng phạm vi
  active series hiện có
- chưa có corporate-action factor log chính thức, chỉ có proxy audit
- chưa có event-level JSON/CSV tái lập đầy đủ bảng PDF
- Bear Flag chưa có real-data chapter runner hoàn chỉnh
- chưa có release gate status/reviewer sign-off
