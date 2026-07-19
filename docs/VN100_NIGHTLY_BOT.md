# Bot quét tích lũy VN100 lúc 03:00

Đây là lane chạy EOD độc lập với pipeline nghiên cứu/post-breakout. Mọi detector
chỉ nhìn dữ liệu đã tồn tại tại thời điểm quét và chỉ tạo **watchlist ứng viên**.
Gemini không quyết định mẫu hình; nó chỉ có thể viết lại phần mở đầu của thông báo.

## 1. Thu hồi ba khóa đã lộ

Các khóa từng được gửi trong hội thoại phải được xem là đã lộ và không được dùng
lại:

1. Telegram: mở BotFather, dùng `/revoke` cho bot rồi lấy token mới.
2. Gemini: xóa key cũ trong Google AI Studio/Google Cloud, tạo key mới và kiểm tra
   lịch sử sử dụng/quota.
3. Vnstock: thu hồi key cũ trong tài khoản Vnstock và tạo key mới.

Không dán khóa mới vào file, commit, issue, log hoặc tin nhắn. Dự án chỉ đọc khóa
từ biến môi trường/GitHub Secrets.

## 2. Lấy Telegram Chat ID

Mở bot, nhấn Start hoặc gửi `/start`. Sau đó chạy cục bộ:

```powershell
$env:TELEGRAM_BOT_TOKEN="TOKEN_MOI"
python tools/telegram_chat_id.py
```

Lưu số nhận được làm `TELEGRAM_CHAT_ID`.

## 3. Tạo GitHub Secrets

Nên dùng repository **private**. Vào `Settings → Secrets and variables → Actions`
và tạo bốn repository secrets:

- `VNSTOCK_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `GEMINI_API_KEY` (tùy chọn)

Không đặt khóa vào Actions Variables; Variables chỉ dùng cho cấu hình không bí mật.

## 4. Nguồn dữ liệu và quota

Vnstock 4.0.4 hiện có OHLCV cổ phiếu hoạt động qua `KBS` và `VCI`. DNSE trong
package này là connector tài khoản/đặt lệnh, không phải nguồn lịch sử OHLCV.
`VIETFIN` được parser chấp nhận như bí danh của `DNSE`, dùng chung một quota/circuit
và không tạo thêm hạn mức. Nguồn không có OHLCV sẽ bị cách ly khi khởi động.

Cấu hình production mặc định:

```env
SCAN_API_SOURCES=KBS,VCI
SCAN_SOURCE_REQUESTS_PER_MINUTE=20
SCAN_SOURCE_LIMITS=KBS=20,VCI=20,DNSE=15
SCAN_SOURCE_USAGE_RATIO=0.78
SCAN_REQUEST_JITTER_MIN_SEC=1.25
SCAN_REQUEST_JITTER_MAX_SEC=3.75
SCAN_SOURCE_ERROR_COOLDOWN_MIN_SEC=30
SCAN_SOURCE_ERROR_COOLDOWN_MAX_SEC=120
SCAN_SOURCE_RECOVER_AFTER_SEC=300
SCAN_RETRY_AFTER_MAX_SEC=300
SCAN_MAX_WORKERS=2
```

Tỷ lệ `0.78` tạo trần thực tế 15 request/phút cho KBS và 15 request/phút cho VCI.
Jitter chỉ làm lệch thời điểm request; limiter rolling-window mới là lớp thực sự
giữ quota.

## 5. Lịch chạy

Workflow `.github/workflows/vn100-nightly-scan.yml` chạy lúc khoảng **03:07 giờ
Việt Nam, từ thứ Ba đến thứ Bảy**, tương ứng năm phiên thị trường thứ Hai–thứ Sáu.
Nó thêm startup jitter tối đa ba phút, chống hai run chồng nhau, lưu SQLite trong
Actions cache và chỉ gửi những ứng viên chưa từng gửi của phiên đó.

GitHub Actions có thể khởi chạy trễ. Đây là scanner cuối ngày nên độ trễ vài phút
không ảnh hưởng logic. Có thể chạy thủ công bằng `workflow_dispatch`.

## 6. Chạy cục bộ

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Nạp biến môi trường bằng cách an toàn của hệ điều hành hoặc secret manager, rồi:

```powershell
python -m scanner.run_vn100_nightly_scan --validate-config
python -m scanner.run_vn100_nightly_scan --mode dry-run --no-gemini
python -m scanner.run_vn100_nightly_scan --mode incremental
```

`dry-run` vẫn tải/quét và tạo báo cáo, nhưng không gửi Telegram.

## 7. Kết quả

- SQLite: `data/vn100_ohlcv.sqlite`
- JSON: `artifacts/live_scan/latest/report.json`
- CSV: `artifacts/live_scan/latest/candidates.csv`
- Báo cáo: `artifacts/live_scan/latest/report.md`
- Nội dung Telegram: `artifacts/live_scan/latest/telegram_message.txt`

Các mẫu ban đầu gồm nền phẳng, tam giác tăng, tam giác cân, cờ tăng và co hẹp
biến động/khối lượng. Output bị chặn bởi JSON Schema và không cho phép các trường
look-ahead như MFE, MAE, target-hit hay failure-rate.

## 8. Kiểm thử

```powershell
python -m pytest -q `
  tests/test_live_config.py `
  tests/test_live_source_pool.py `
  tests/test_live_storage.py `
  tests/test_live_patterns.py `
  tests/test_live_integrations.py
```

Cache GitHub chỉ là lớp tăng tốc, không phải kho lưu trữ vĩnh viễn. Nếu cache bị
xóa, pipeline sẽ tự tải lại lịch sử. Với nhu cầu vận hành thương mại hoặc lưu trạng
thái lâu dài, hãy chuyển SQLite sang object storage/database riêng và kiểm tra điều
khoản cấp phép của Vnstock.
