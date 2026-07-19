# Release gate Bulkowski cho Việt Nam

Tài liệu này chuyển nghiên cứu GPT Pro thứ tư do người dùng cung cấp (`P4`)
thành release gate và red-team checklist cho từng chapter.

P4 được dùng như hướng dẫn phương pháp. Các trích dẫn dạng `turn...` trong P4
không phải nguồn bền vững có thể kiểm tra lại, nên không được chép vào chương
công bố cho tới khi truy được nguồn gốc thật.

## Vai trò

Release gate này là lớp chặn cuối cùng sau:

- [`bulkowski-vietnam-methodology-contract.md`](bulkowski-vietnam-methodology-contract.md)
- [`bulkowski-vietnam-statistics-contract.md`](bulkowski-vietnam-statistics-contract.md)
- [`bulkowski-vietnam-chapter-framework.md`](bulkowski-vietnam-chapter-framework.md)
- [`bulkowski-vietnam-85-90-standard.md`](bulkowski-vietnam-85-90-standard.md)

Một chapter chỉ được gọi là `investment-reference chapter` khi:

- mọi mục `High` severity đều pass
- event-level JSON/CSV tái lập được PDF
- AI narrative có link về metric hoặc caveat trong payload
- examples không cherry-pick
- reviewer/release status rõ ràng

Nếu một mục `High` fail, trạng thái chapter là `Hold` dù điểm tổng hợp cao.

## Chapter Contract Pass/Fail

| Hạng mục | Điều kiện pass/fail | Severity | Trường phải có trong JSON | Trường phải in trong PDF |
|---|---|---|---|---|
| Universe point-in-time | Fail nếu thiếu cổ phiếu delisted/halted trong phạm vi cần nghiên cứu | High | `universe_version`, `is_delisted_in_sample` | date range, universe scope |
| Corporate actions | Fail nếu không chứng minh adjustment point-in-time | High | `adjusted_flag`, `adjustment_source` | data note |
| Rule provenance | Fail nếu không có `rule_id`, `rule_version`, `params` | High | `rule_id`, `rule_version`, `param_hash` | methodology box |
| Scanner coverage | Fail nếu không có audit sample hoặc manual QA note | High | `audit_precision`, `audit_recall`, `audit_n` | scanner QA note |
| Overlap policy | Fail nếu event selection không nhất quán | High | `overlap_group_id`, `is_primary_event` | overlap policy |
| Regime policy | Fail nếu regime label không có rule cố định | High | `regime_rule_id`, `regime_label` | regime definition |
| Liquidity policy | Fail nếu main results không có filter/disclosure | High | `liquidity_filter_id`, `adtv_20` | filter note |
| Sample threshold | Main table chỉ pass khi N đủ lớn; subgroup nhỏ xuống appendix | Medium | `sample_n`, `subgroup_n` | N ở mọi bảng |
| Statistics pack | Fail nếu thiếu summary, direction, regime, target/failure, behavior | High | derived statistics fields | đủ 5 bảng chính |
| Inference | Fail nếu có kết luận so sánh mà không có CI/p-value | High | `ci_method`, `p_value` | CI / p / p_adj |
| Multiple testing | Fail nếu ranking pattern/subgroup mà chỉ dùng raw p | High | `p_adj_method`, `p_adj` | adjusted p note |
| Chart examples | Fail nếu chỉ chọn case đẹp | Medium | `example_selection_rule` | caption + metadata |
| AI narrative | Fail nếu AI nói quá bằng chứng | Medium | `claim_metric_links` | AI disclaimer |
| Governance | Fail nếu không có reviewer sign-off và release gate | High | `reviewer_id`, `release_status` | release note |

## Output Bắt Buộc

Mỗi chapter release phải có ba artifact đồng bộ:

- event-level JSON
- event-level CSV
- PDF chapter

PDF là bản đọc. JSON/CSV là bản tái lập. Không có JSON/CSV thì PDF không đủ tư
cách audit.

### CSV Header Tối Thiểu

```csv
event_id,pattern_id,ticker,exchange,market_group,pattern_start,pattern_end,breakout_date,breakout_direction,breakout_price,target_price,vnindex_regime,rule_version,scanner_version,data_version,overlap_group_id,is_primary_event,r_1,r_5,r_10,r_20,r_60,r_120,mfe_20,mae_20,target_hit_120,time_to_target,censored,adtv_20,turnover_20,amihud_20,pit_ok,corp_action_ok,delisting_checked
```

### JSON Record Tối Thiểu

```json
{
  "event_id": "triangle_asc_FPT_2024-03-12_01",
  "pattern_id": "triangle_ascending",
  "ticker": "FPT",
  "exchange": "HOSE",
  "market_group": "VN30",
  "pattern_start": "2024-01-15",
  "pattern_end": "2024-03-11",
  "breakout_date": "2024-03-12",
  "breakout_direction": "up",
  "breakout_price": 98.4,
  "target_price": 112.0,
  "vnindex_regime": "bull",
  "rule_version": "triangle_asc@2.1.0",
  "scanner_version": "scanner@0.9.4",
  "data_version": "pit_eod_2026-05-01",
  "overlap_group_id": "FPT_2024Q1_cluster3",
  "is_primary_event": true,
  "window_stats": {
    "r_1": 0.012,
    "r_5": 0.036,
    "r_10": 0.041,
    "r_20": 0.067,
    "r_60": 0.104,
    "r_120": 0.082,
    "mfe_20": 0.088,
    "mae_20": -0.021,
    "target_hit_120": true,
    "time_to_target": 34,
    "censored": false
  },
  "liquidity": {
    "adtv_20": 185000000000,
    "turnover_20": 0.012,
    "amihud_20": 1.6e-10
  },
  "qa": {
    "pit_ok": true,
    "corp_action_ok": true,
    "delisting_checked": true
  }
}
```

## Example Selection Gate

Chart examples must be selected by rule, not by taste.

Required set:

- one median case
- one strong-tail case
- one failure case
- one borderline or hard-to-identify case

Each caption must include ticker, exchange, pattern dates, breakout date, regime,
market group, liquidity bucket, target outcome, horizon outcome, and rule version.

## Red-Team Risk Register

| Rủi ro | Phát hiện trong pipeline | Giảm thiểu | Phân loại |
|---|---|---|---|
| Survivorship bias | so sample với universe point-in-time; đếm event ở mã còn sống vs delisted | include delisted/halted | Block publication |
| Look-ahead bias | audit timestamp; shift features +1 bar xem kết quả sụt không | chỉ dùng thông tin đã biết tại breakout | Block publication |
| Overlap cùng mẫu trong cùng mã | overlap ratio trong cùng ticker trong H phiên | primary-event rule hoặc event clusters | Block publication |
| Overlap giữa nhiều mẫu | multi-label rate trên cùng đoạn giá | hierarchy hoặc multi-label + primary label | Block publication |
| Chọn ví dụ đẹp | phân bố outcome của examples khác sample tổng thể | lấy ví dụ theo percentile bins + failure exemplar | Require note only |
| Thanh khoản thấp/stale prints | ADTV thấp, zero-return days cao, Amihud xấu | filter thanh khoản, tách appendix illiquid | Block publication |
| Delisting/suspension rơi khỏi dữ liệu | missing future bars, censoring reasons không rõ | cờ censoring + universe delisted | Block publication |
| Corporate action/sửa dữ liệu | spike bất thường, mismatch adjusted/unadjusted | point-in-time adjustment audit | Block publication |
| Bull/bear regime tùy ý | sensitivity qua nhiều rule regime | rule cố định + appendix sensitivity | Require note only |
| Chọn VN30/VN100/all để cherry-pick | kết quả thay đổi mạnh theo universe | report đồng thời strata hoặc matched sample | Require note only |
| Target-hit quá lỏng | intraday hit vs close hit khác xa; horizon đổi làm hit rate tăng | khóa trigger + horizon trước phân tích | Block publication |
| Failure rate trôi nghĩa | lúc là target-fail, lúc là return < 0 | đặt tên riêng từng loại failure | Block publication |
| Chọn horizon đẹp | chỉ công bố horizon tốt nhất | luôn xuất grid 1/5/10/20/60/120 | Require note only |
| Multiple testing/pattern shopping | số test lớn, raw p dày đặc | Holm/Romano-Wolf; exploratory vs confirmatory | Block publication |
| So sánh mẫu không chuẩn hóa | khác universe/date/filter/overlap/horizon | matched-sample hoặc standardized protocol | Block publication |

## Điểm Release /100

| Nhóm | Điểm tối đa | Tiêu chí pass chính |
|---|---:|---|
| Data | 20 | point-in-time, delisted, corporate actions, censoring rõ |
| Provenance | 15 | rule_version, scanner_version, overlap policy, QA |
| Statistics | 25 | đủ 5 bảng chính, percentiles, CI, p, adjusted p |
| Examples | 10 | median + tail + failure + metadata caption |
| Governance | 15 | reviewer sign-off, release gate, reproducibility artifact |
| Interpretability / AI | 15 | claim-to-metric links, uncertainty, không suy quá bằng chứng |

```text
Score = Data + Provenance + Statistics + Examples + Governance + InterpretabilityAI
```

Release status:

| Trạng thái | Điều kiện |
|---|---|
| `Hold` | bất kỳ mục High severity fail |
| `Publish with caveats` | điểm 85-89 và mọi High severity pass |
| `Strong chapter` | điểm >= 90, mọi High severity pass, đa số Medium pass |

## Classification Labels

| Classification | Ý nghĩa |
|---|---|
| `not-usable` | thiếu PTI data, provenance hoặc fail critical; không được dùng cho nhận định đầu tư |
| `research-only` | có rule và summary stats cơ bản, dùng cho nhận diện/mô tả |
| `watchlist-reference` | có P0 và subgroup chính, dùng theo dõi có điều kiện với caveat mạnh |
| `investment-reference` | có P0 đầy đủ, PTI universe, path metrics, uncertainty và red-team pass |
| `tradable-setup` | có thêm execution/cost/OOS/walk-forward/PBO; là tài liệu chiến lược riêng |

## Checklist Tối Giản Trước Khi In PDF

| Câu hỏi chốt | Pass nếu |
|---|---|
| Có point-in-time universe gồm cả delisted? | Có |
| Rule có provenance và versioning? | Có |
| Có policy overlap và censoring? | Có |
| Có đủ summary + direction + regime + failure/target + behavior tables? | Có |
| Có CI, raw p, adjusted p khi có so sánh/ranking? | Có |
| Có examples không cherry-pick? | Có |
| AI narrative có bị ràng bởi metrics hay không? | Có |
| Event-level JSON/CSV có tái lập được PDF? | Có |

Nếu câu trả lời là "Không" ở một mục High severity, chapter phải bị chặn, sửa
pipeline rồi mới công bố.
