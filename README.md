# ChartPatternscan

## Bot quét tích lũy VN100 EOD

Repo này có một lane vận hành độc lập để:

- lấy đúng rổ VN100 hiện tại qua Vnstock;
- chia tải qua KBS/VCI với quota rolling-window, jitter, cooldown và failover;
- quét nền phẳng, tam giác, cờ tăng và co hẹp biến động chỉ bằng dữ liệu đã đóng nến;
- gửi ứng viên mới qua Telegram, với Gemini là lớp diễn giải tùy chọn;
- chạy tự động khoảng 03:07 giờ Việt Nam sau mỗi phiên bằng GitHub Actions.

Lane live không gọi `post_breakout_analyzer` và không xuất MFE/MAE/target/failure.
Xem hướng dẫn triển khai và quy trình thay khóa tại
[`docs/VN100_NIGHTLY_BOT.md`](docs/VN100_NIGHTLY_BOT.md).

Nghiên cứu và quét (scan) mô hình giá trên dữ liệu **OHLCV** quy mô lớn (SQLite), kèm lớp **đánh giá hậu breakout** (look-ahead) để tổng hợp thống kê.

## Tuyên bố học thuật, phạm vi và trích dẫn

- Dự án phục vụ **nghiên cứu/giáo dục**, không phải tư vấn đầu tư.
- Lớp **Post-Breakout Analyzer** sử dụng **dữ liệu tương lai** (look-ahead) để đo *failure/ultimate/throwback/target/MFE/MAE*; **không** dùng để ra quyết định giao dịch thời gian thực.
- Nhiều khái niệm/thuật ngữ và cách đo lường trong lĩnh vực chart patterns thường được chuẩn hoá theo tài liệu kinh điển. Nếu bạn dùng dự án này trong báo cáo học thuật, hãy **trích dẫn nguồn** bên dưới.

**Tài liệu tham khảo chính (primary reference):**
- Thomas N. Bulkowski, *Encyclopedia of Chart Patterns*, 2nd Edition, Wiley. ISBN: 978-0-471-66826-8.

**Lưu ý bản quyền:**
- Repo này **không** phân phối sách/tài liệu có bản quyền hoặc các bản trích xuất dung lượng lớn từ sách.
- Nếu bạn có bộ “digitized specs”/pattern definitions được trích xuất từ sách hoặc nguồn có bản quyền: hãy đảm bảo **quyền sử dụng/phân phối** trước khi public.

## Cấu trúc repo

- `scanner/`: scanner core, benchmark, governance, builder scripts.
- `docs/`: tài liệu kiến trúc, publication, stage reports, backlog nghiên cứu.
- `extraction_phase_1/`: dữ liệu và báo cáo của phase trích xuất spec.
- `schemas/`: JSON schemas, hiện dùng cho `Book v2`.
- `tests/`: regression tests.
- `scan_results/`: artifact local và DB kết quả scan/build. Thư mục này chủ yếu để làm việc local và khá lớn.

## Scanner V2 Rebuild Status

The legacy scanner path is quarantined and must not be used as the source of
truth for new research or PDF monograph facts. New work should use `scanner/v2/`
and the task list in `docs/project/v2-pdf-monograph-task-list.md`.

For final investor-facing chapters, the active working standard is
`docs/project/canonical-chapter-working-standard.md`. A chapter is not final
unless it passes the canonical publication flow in
`docs/project/canonical-publication-flow.md`.

Historical comparison only:

```bash
CHARTPATTERNSCAN_ALLOW_LEGACY_SCANNER=1 python3 scanner/run_full_scan.py ...
```

## Optional analysis lanes

- The OHLCV scanner is the primary lane and remains runnable by itself.
- THIUCUBU is an advisory regime/flow/risk signal by default.
- GPT and GLM independently review supplied chart-pattern facts; they cannot edit values or add symbols.
- Gemini only supplies context wording; provider quota/network errors do not fail the scan.
- Set `THIUCUBU_ENFORCE=1` only when the stricter THIUCUBU gate is explicitly desired.
- Cross-repo consumers use `data/pattern_feed_latest.json`; AI reviews remain in a separate artifact and never enter this facts feed.

## Kiến trúc

- Legacy logic, quarantined for historical comparison:
  - Scan/research baseline: `scanner/run_full_scan.py`
  - Pattern sets và mapping taxonomy: `scanner/pattern_set_metadata.py`
  - Detector family/spec logic: `scanner/digitized_pattern_engine.py`
  - Hậu kiểm breakout: `scanner/post_breakout_analyzer.py`
  - Results DB schema: `scanner/results_db.py`
  - Vietnam research report: `scanner/build_vietnam_research_report.py`
  - Symbol profile: `scanner/build_symbol_pattern_profiles.py`
  - Book v2 deterministic chapters: `scanner/build_pattern_monographs.py`
  - Book v2 readiness/governance audit: `scanner/audit_book_v2_readiness.py`
  - Book v2 assembly/commentary/PDF: `scanner/build_book_v2.py`

- Legacy publication builders quarantined outside the active scanner flow:
  - `scanner/_legacy_quarantine/build_bull_flag_public_chapter.py`
  - `scanner/_legacy_quarantine/build_bull_flag_investor_chapter.py`

- Canonical public chapter publication:
  - `scanner/canonical_publication_chapter_factory.py`: only allowed final chapter factory.
  - `scanner/canonical_chapter_content.py`: only allowed public editorial section adapter.
  - `scanner/canonical_editorial_layer.py`: gate for AI/human editorial sections.
  - `scanner/pattern_publication_core.py`: low-level renderer only; not enough by itself to declare final.

- `scanner/ohlcv_normalizer.py`: làm sạch OHLCV (NULL, high/low đảo, clamp open/close, loại bỏ giá <=0), tạo cột dẫn xuất (ATR, volume_ma, volume_ratio…)
- `scanner/pivot_detector.py`: phát hiện pivot highs/lows + lọc spacing để giảm nhiễu
- `scanner/digitized_pattern_engine.py`: scanners theo các bộ `--pattern-set`:
  - `digitized`: **spec-driven** đọc từ `extraction_phase_1/digitization/patterns_digitized/*_digitized.json` (nếu có) để cover **toàn bộ digitized specs** (hiện có **31** keys)
  - `bulkowski_53`: Bulkowski Part One (53 chapters) (tách biến thể theo chapter; nếu có digitized specs thì dùng spec-driven, nếu không sẽ fallback một số built-in proxies)
  - `bulkowski_53_strict`: phiên bản “spec-anchored” của `bulkowski_53` (khi đã digitize đủ 53/53 chapters thì **trùng với** `bulkowski_53`)
  - `bulkowski_strict_ohlcv`: `bulkowski_53_strict` + `event_ohlcv` → **55 patterns** (53 chart + 2 event-OHLCV)
  - `event_ohlcv`: Event patterns “ngoại lệ” có thể định nghĩa chỉ từ OHLCV (**Dead‑Cat Bounce**, **Dead‑Cat Bounce (Inverted)**)
  - `bulkowski_55_ohlcv`: `bulkowski_53` + `event_ohlcv`
- `scanner/pattern_scanner.py`: orchestrator (normalize → pivots → scan). Nếu thiếu digitized specs (repo public), fallback về legacy MVP scanners
- `scanner/post_breakout_analyzer.py`: đo thống kê hậu breakout (look-ahead **theo từng pattern** nếu có digitized specs; mặc định 252 bars), thời gian đo theo **calendar days**, và variant `AA/AE/EA/EE` cho Double Tops
- `scanner/results_db.py`: persist kết quả ra **DB riêng** (không ghi vào DB giá nguồn) + `run_id` + index
- `scanner/run_full_scan.py`: chạy scan full DB và lưu kết quả + thống kê tổng hợp
- `scanner/audit_kpi.py`: audit KPI + compliance theo digitized specs
- `scanner/report_bulkowski.py`: tạo báo cáo thống kê kiểu Bulkowski (median + bull/bear regime 18 tháng)
- `scanner/report_symbol.py`: góc nhìn theo từng mã cổ phiếu
- `scanner/README.md`: chỉ mục nhóm script `build_`, `report_`, `audit_`, `review_`

## Yêu cầu dữ liệu

Mặc định đọc SQLite table `stock_price_history` với các cột:
- `symbol`, `time` (hoặc `date`), `open`, `high`, `low`, `close`, `volume`

## Cài đặt

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Chạy Scanner V2

Đây là đường chạy chính hiện tại. V2 dùng provenance, golden fixtures, active
Market Stats universe và data gates trước khi xuất chapter PDF.

```bash
python3 scanner/build_bull_flags_v2_monograph.py
python3 scanner/audit_bull_flags_data_gates.py
python3 scanner/research_support_analysis.py
```

Output chính:

- `artifacts/scanner_v2/bull_flags/bull_flags.pdf`
- `artifacts/scanner_v2/bull_flags/events.csv`
- `artifacts/scanner_v2/bull_flags/data_gate_audit.md`
- `artifacts/scanner_v2/research_support/target_sensitivity.csv`

Kiểm tra contract/source alignment:

```bash
python3 scanner/audit_scanner_v2_contract.py
python3 scanner/audit_scanner_v2_source_alignment.py
python3 -m pytest -q
```

## Legacy SQLite Scanner

Các command `scanner/run_full_scan.py`, `scanner/report_bulkowski.py`,
`scanner/report_symbol.py`, `scanner/build_pattern_monographs.py` và các report
builder dựa trên DB legacy chỉ còn dùng để đối chiếu lịch sử. Chúng không được
dùng để tạo kết luận chính thức cho “Bulkowski Việt Nam”.

Nếu cần chạy lại để so sánh lịch sử, phải bật rõ cờ:

```bash
CHARTPATTERNSCAN_ALLOW_LEGACY_SCANNER=1 python3 scanner/run_full_scan.py ...
```

## Tái lập (reproducibility)

Scanner V2 lưu artifact theo từng chapter:

- `detections.json`: detections, active-universe filter, rule metadata.
- `events.csv`: event-level statistics.
- `post_breakout_path.csv`: đường giá hậu breakout dùng cho path metrics.
- `statistics.json`: thống kê deterministic.
- `data_gate_audit.json/.md`: phạm vi dữ liệu, gate pass/fail/partial.

## Giới hạn hiện tại

- Phạm vi hiện tại là `available_series_descriptive`: chỉ nghiên cứu mã có trong active/current universe của Market Stats V1.
- Không dùng historical VN30/VN100 membership để làm headline claim.
- Không claim full point-in-time universe toàn thị trường.
- Corporate-action factor log chính thức chưa có; chapter dùng provider-adjusted OHLCV và proxy audit.
- Delisted/halted historical status tape chính thức không nằm trong phạm vi hiện tại; path-quality proxy vẫn được báo cáo để kiểm soát censoring.

## VN100 nightly Telegram watchlist

Luồng EOD độc lập nằm ở scanner/run_vn100_nightly_scan.py. Nó lấy đúng tối
đa 100 mã VN100, cập nhật OHLCV qua VCI/KBS, giới hạn request theo từng nguồn,
thêm jitter/cooldown/failover, rồi tìm các mẫu hình tích lũy đang hình thành.
Luồng này không dùng dữ liệu sau breakout. Xem hướng dẫn triển khai tại
docs/VN100_BOT_SETUP.md.

    python -m scanner.run_vn100_nightly_scan --validate-config
    python -m scanner.run_vn100_nightly_scan --no-notify
