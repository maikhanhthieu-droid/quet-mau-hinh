# After-the-Buy Deep Integration V2 Report

## Executive Summary

Vòng này chuyển *Chart Patterns: After the Buy* từ một tập rule rời rạc thành một lớp tích hợp toàn sách.  Kết quả không phải là cố làm mọi chapter thành `tradable-final-95`, mà là biết rõ rule nào đi vào scanner, rule nào đi vào thống kê, rule nào đi vào trade layer, và rule nào dùng để viết phần "Hành vi sau phá vỡ" trong atlas.

Artifact chính: `artifacts/scanner_v2/after_buy_vietnam_v2/`.

## Before / After

| Lớp | Trước vòng này | Sau vòng này |
|---|---|---|
| Source reading | Các rule After-the-Buy nằm rải rác trong từng builder | 26 chương nguồn được đọc qua outline/section evidence; 211 section-evidence rows |
| Rule system | Khó biết rule nào dùng cho scanner/thống kê/trade/publication | 150 normalized rule rows, mỗi rule có pattern ownership và layer mapping |
| Scanner | Nhiều logic after-buy còn ẩn trong từng pattern | 135 scanner-rule mappings để làm quality gates riêng theo pattern/family |
| Statistics | MFE/MAE/target-first đã có, nhưng chưa có bản đồ nguồn | 66 stat-metric mappings cho target, failure, stop, retest, path, walk-forward |
| Trade layer | Có nhiều rerun riêng, khó nhìn toàn cục | 122 trade-layer mappings và no-overfit gate cho từng chapter |
| Defensive safety | Có defensive gate V1 | Được nối vào config 63 chapter, đảm bảo top/downside không thành long-cash BUY |
| Publication | Chưa có cầu nối toàn sách để viết phần after-buy | 150 publication-interpretation rows sẵn cho mục "Hành vi sau phá vỡ" |

## Quantitative Result

| Chỉ tiêu | Kết quả |
|---|---:|
| Source chapters read | 26 |
| Atlas chapters covered | 63 |
| Section evidence rows | 211 |
| Normalized rule rows | 150 |
| Chapters mapped to After-the-Buy source | 26 |
| BUY-allowed chapters | 15 |
| Chapters with direct scanner/stat/trade rules | 16 |
| Defensive/reference/unmapped-for-BUY chapters | 48 |
| BUY/watchlist chapters still blocked by evidence | 12 |
| Tradable PASS chapters in current governance | 6 |

## Practical Decisions

| Nhóm | Quyết định |
|---|---|
| BUY/tradable đã pass | Giữ nguyên, không làm hỏng benchmark hiện tại. |
| BUY/watchlist còn fold âm hoặc score dưới 95 | Không overfit; chỉ nâng nếu rule nguồn tạo cải thiện bền qua validation/holdout. |
| Top/downside/bearish | Chuyển thành avoid/exit/risk filter, không xem là cơ hội BUY cổ phiếu cơ sở Việt Nam. |
| Publication | Có thể thêm mục "Hành vi sau phá vỡ" vào atlas bằng payload đã chuẩn hóa, thay vì viết cảm tính. |

## Output Files

| File | Vai trò |
|---|---|
| `after_buy_deep_rules.json` | Section evidence + normalized rule rows |
| `after_buy_chapter_coverage_matrix.csv/json` | Ma trận 63 chapter: source, role, score, blocker, action |
| `after_buy_rule_layer_mapping.json` | Rule nào dùng cho scanner/stat/trade/publication |
| `after_buy_scanner_stat_trade_config.json` | Runtime bridge cho matrix scanner và trade layer |
| `after_buy_before_after_impact_report.json` | Báo cáo trước/sau dạng machine-readable |
| `after_buy_deep_integration_pack.md/json` | Tóm tắt triển khai |

## Application Layer

V2 đã được nối vào các workflow dự án thông qua `artifacts/scanner_v2/after_buy_vietnam_v2/application/`.

| Artifact | Ý nghĩa |
|---|---|
| `after_buy_application_scope.json` | Phân loại 63 chapter thành BUY pass, BUY/watchlist blocked, defensive, reference/unmapped |
| `scanner_before_after.csv` | So sánh base scanner artifact với After-the-Buy quality overlay cho 12 pattern ưu tiên |
| `statistics_metric_plan.csv` | Kế hoạch metric hậu breakout theo rule nguồn; 84 rows, 66 rows được data hiện tại hỗ trợ |
| `tradable_before_after.csv` | So sánh score/decision trước-sau; không inflate điểm nếu chưa rerun thật |
| `defensive_runtime_signals.json` | 48 signals dùng cho avoid-buy/exit/risk-context |
| `publication_pilot_payload.json` | Payload cho 5 section mẫu "Hành vi sau phá vỡ" |
| `../quantitative_effect/after_buy_quantitative_effect_report.json` | Rerun branch/tradable thật cho 12 pattern ưu tiên, dùng để kiểm tra After-the-Buy có làm điểm giao dịch tốt hơn không |

Realtime watchlist cũng đã nhận các trường After-the-Buy:

- `after_buy_role`
- `after_buy_action`
- `after_buy_trade_mode`
- `after_buy_risk_context`
- `after_buy_no_overfit_blocked`

Trial với Bull Flag, Bear Flag, Bull Pennant tạo 44 rows: Bull Flag được gắn nhãn actionable long-cash candidate; Bear Flag là avoid/exit warning; Bull Pennant là watchlist-only do còn fold blocker.

## Bear-Trap / Cắt Lỗ Thận Trọng

Sau pilot bear-trap, dự án không giữ nhánh `bear-trap long setup`.  Hành vi giá quay lại vùng phá vỡ sau một phá vỡ giảm được chuyển thành lớp cảnh báo cắt lỗ:

- không tạo BUY alert;
- không chấm `tradable-final`;
- không sinh `release_candidate`;
- chỉ theo dõi giá đóng cửa quay lại vùng phá vỡ trong 5/10/20 phiên để cảnh báo phá vỡ giảm chưa sạch.

Realtime watchlist nhận thêm các trường:

- `stoploss_caution_role`
- `stoploss_caution_action`
- `stoploss_caution_window_bars`
- `stoploss_caution_is_buy_signal`

Artifact chuẩn: `artifacts/scanner_v2/bear_trap_stoploss_caution/`.

Vòng publication mới đã áp dụng lớp này vào 18 chapter bearish/top/downside final bằng `bear_trap_stoploss_publication_reframe_v1`.  Điều kiện public là: không in marker kỹ thuật, không dùng lại nhãn `defensive/informational` trong PDF final, và câu “Cách dùng” trên trang đầu phải nói rõ đây là lớp kiểm tra bẫy giảm/cắt lỗ thận trọng, không phải tín hiệu mua hoặc bán khống tự động.

## Current Ceiling

Vòng này cải thiện mạnh ở tầng tổ chức logic và khả năng dùng tài liệu nguồn.  Nó không tự làm số đẹp hơn.  Những chapter còn bị chặn bởi `walk_forward_has_negative_fold`, thiếu validation/holdout trade depth, hoặc scope defensive vẫn phải giữ đúng nhãn thay vì ép lên 95.

## Quantitative Effect Rerun

Để kiểm tra hiệu quả định lượng, đã chạy:

```bash
PYTHONPATH=. python3 -m scanner.run_after_buy_quantitative_effect
```

Kết quả trên 12 priority BUY/watchlist chapters:

| Nhóm kết quả | Số chapter |
|---|---:|
| Được nâng lên tradable-final | 0 |
| Cải thiện sạch nhưng chưa đủ final | 0 |
| Gần như không đổi | 2 |
| Có cải thiện điểm nhưng vẫn bị blocker release | 1 |
| Xấu hơn hoặc bảo thủ hơn sau rerun | 9 |
| Vẫn bị block release gate | 12 |

Kết luận: V2 đã chứng minh hiệu quả ở tầng cấu trúc dự án: source grounding, scanner overlay, metric plan, realtime watchlist và publication payload.  Nhưng ở tầng tradable score, rerun thực tế chưa chứng minh được cải thiện bền.  Vì vậy không được viết rằng After-the-Buy đã "nâng điểm giao dịch" cho các chapter còn block; cách viết đúng là "After-the-Buy làm rõ cách dùng, blocker, và điều kiện cần kiểm tra tiếp".
