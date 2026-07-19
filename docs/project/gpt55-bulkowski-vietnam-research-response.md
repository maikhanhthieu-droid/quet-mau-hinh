# GPT 5.5 Research Response - Bulkowski Cho Việt Nam

Ngày cập nhật: 2026-05-16

## Kết luận cần đưa vào roadmap

Nghiên cứu GPT 5.5 Pro xác nhận hướng đọc đúng cho dự án:

- Kết quả scanner hiện tại là **descriptive reference**, chưa phải trading system.
- `Investment reference` chỉ được dùng khi đã qua audit dữ liệu, metric consistency, target calibration và robustness.
- `Tradable setup` là tầng riêng, cần entry/exit/size/cost/slippage/OOS, không được ngụy trang bằng thống kê pattern.

## Điều chỉnh kỹ thuật đã thực hiện sau phản hồi

Phản hồi chỉ ra bất nhất giữa summary `target-first-before-adverse-5%` và target sensitivity ở mốc `1.0x`.
Nguyên nhân kỹ thuật là target sensitivity đang đọc path 120 phiên, trong khi MFE/MAE/event summary hiện khóa ở 60 phiên.

Đã sửa:

- `scanner/research_support_analysis.py` khóa `target_sensitivity` mặc định ở `60` phiên.
- `target_sensitivity.csv` và `research_support_packet.md` ghi rõ horizon.
- `tests/test_research_support_analysis.py` có test chặn việc dùng path ngoài horizon.
- `gpt55_research_prompt.md` đã cập nhật lại số target-first theo horizon 60 phiên.

## Ưu tiên kỹ thuật tiếp theo

1. **Metric reconciliation audit**
   - Mọi bảng summary/sensitivity phải cùng `horizon_days`.
   - Các metric cùng tên phải dùng cùng định nghĩa.
   - Nếu có `120` phiên thì phải tách thành panel riêng, không ghi chung với `60`.

2. **Data integrity audit**
   - Point-in-time universe.
   - Delisted/halted coverage.
   - Corporate-action audit.
   - Liquidity/microstructure fields.

3. **Target calibration**
   - Giữ các band `0.5x`, `0.75x`, `1.0x`, `1.25x`.
   - Đối với Bull Flag, `0.5x` và `0.75x` là ứng viên local target tốt hơn `1.0x`.
   - Không gọi đây là nới lỏng target; gọi là local calibration theo empirical target attainment.

4. **Pattern tiering**
   - Bull Flag: chapter candidate có triển vọng nhất và là mẫu chuẩn hiện tại của Flag Family.
   - Bear Flag: informational/defensive reference, không nên xếp cùng investment-reference bullish pattern nếu chưa có lớp thực thi downside.
   - Các mẫu non-Flag dùng logic V2 cũ: đã đưa ra khỏi lane hoạt động cho đến khi được xây lại theo chuẩn matrix mới.

## Quy tắc vận hành

Không ranking pattern chính thức trước khi các gate sau pass:

- universe gate;
- exit/delisted gate;
- corporate-action gate;
- metric consistency gate;
- liquidity gate;
- overlap gate.
