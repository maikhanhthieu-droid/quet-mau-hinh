# Kết quả test thật DeepSeek cho chương Bull Flag

Ngày chạy: 2026-05-18  
Model: `deepseek-chat`  
Input chính: compact payload từ Bull Flag public/publication payload, statistics và một số event mẫu.

Artifact output:

```text
artifacts/scanner_v2/bull_flags_ai_writing_test/input_compact_data.json
artifacts/scanner_v2/bull_flags_ai_writing_test/deepseek_only_output.md
artifacts/scanner_v2/bull_flags_ai_writing_test/hybrid_json_output.json
artifacts/scanner_v2/bull_flags_ai_writing_test/run_meta.json
```

## Kết quả chạy

| Phiên bản | Thời gian | Output | Ghi chú |
|---|---:|---:|---|
| DeepSeek làm hết | 69,24 giây | 15.459 ký tự | Viết được chapter dài, có Claim Ledger, nhưng cần sửa nhiều trước khi xuất bản |
| Hybrid DeepSeek JSON | 42,29 giây | 8.638 ký tự | JSON parse được sau khi bỏ code fence, dùng được làm draft section |
| DeepSeek V4 Flash làm hết | 82,24 giây | 14.956 ký tự | Sạch thuật ngữ hơn `deepseek-chat`, nhưng vẫn overclaim trading |
| Hybrid V4 Flash JSON | 66,53 giây | 7.304 ký tự | JSON hợp lệ sau rerun, ít lỗi thuật ngữ hơn bản hybrid `deepseek-chat` |
| Codex hiện tại | không gọi API | PDF 8 trang | Kiểm soát tốt nhất, đã có layout xuất bản |

## Kiểm tra tự động

| Tiêu chí | Codex-only | DeepSeek-only | Hybrid |
|---|---:|---:|---:|
| Đủ mục chapter chính | Đạt | Đạt | Đạt theo schema |
| JSON/format hợp lệ | Không áp dụng | Markdown hợp lệ | JSON parse được sau strip fence |
| Thuật ngữ tiếng Anh lộ ra | Rất ít | Nhiều: `MFE`, `MAE`, `breakout`, `proxy` | Có: `MFE`, `MAE`, `breakout`, `stop loss`, `proxy` |
| Claim ledger | Không cần | Có, nhưng dùng cả claim rủi ro cao | Có `claims_to_verify` |
| Nguy cơ overclaim | Thấp | Cao | Trung bình |
| Có thể render trực tiếp | Có | Không nên | Không, cần guard và replacement |

## Kết quả bổ sung: DeepSeek V4 Flash

Sau khi chạy `deepseek-chat`, đã chạy lại cùng dữ liệu và cùng prompt với model `deepseek-v4-flash`.

Artifact output:

```text
artifacts/scanner_v2/bull_flags_ai_writing_test_v4_flash/input_compact_data.json
artifacts/scanner_v2/bull_flags_ai_writing_test_v4_flash/deepseek_v4_flash_only_output.md
artifacts/scanner_v2/bull_flags_ai_writing_test_v4_flash/hybrid_v4_flash_json_retry_output.json
artifacts/scanner_v2/bull_flags_ai_writing_test_v4_flash/run_meta.json
artifacts/scanner_v2/bull_flags_ai_writing_test_v4_flash/hybrid_retry_meta.json
```

V4 Flash có hai điểm đáng chú ý:

- Bản full chapter ít vi phạm thuật ngữ hơn `deepseek-chat`: chỉ còn ít cụm như `MAE`, `breakout`, `proxy`, `khuyến nghị`, `đảm bảo`, `chắc chắn`.
- Bản Hybrid lần đầu bị cắt cụt vì `max_tokens=5200`; sau khi rerun với `max_tokens=9000`, JSON hợp lệ và ngắn hơn.

So sánh lỗi thuật ngữ/cảnh báo tự động:

| Phiên bản | Lỗi/thuật ngữ bị scan thấy |
|---|---|
| Codex PDF | `khuyến nghị` 2 lần |
| DeepSeek chat only | `MFE` 11, `MAE` 13, `breakout` 3, `proxy` 3, `cỗ máy in tiền` 1, `khuyến nghị` 2, `đảm bảo` 2, `chắc chắn` 1 |
| Hybrid chat | `MFE` 3, `MAE` 3, `breakout` 16, `stop loss` 2, `proxy` 1, `khuyến nghị` 3, `lợi nhuận dương ổn định` 1 |
| V4 Flash only | `MAE` 1, `breakout` 1, `proxy` 1, `khuyến nghị` 2, `đảm bảo` 1, `chắc chắn` 1, `khuyến nghị sử dụng` 1 |
| Hybrid V4 Flash retry | `breakout` 2, `proxy` 4, `khuyến nghị` 2 |

Đánh giá sau V4 Flash:

| Phiên bản | Điểm thô | Điểm sau guard/editor | Nhận định |
|---|---:|---:|---|
| Codex-only hiện tại | 88-90 | 88-90 | Vẫn tốt nhất để release hiện tại |
| DeepSeek chat only | 58-65 | 72-78 | Nhiều lỗi thuật ngữ và overclaim |
| Hybrid chat | 72-78 | 88-92 | Dùng được nếu có guard |
| V4 Flash only | 66-72 | 78-84 | Sạch hơn chat-only, nhưng vẫn không nên xuất bản thẳng |
| Hybrid V4 Flash | 78-82 | 90-93 | Ứng viên tốt nhất cho pipeline hybrid |

Kết luận bổ sung: **nếu dùng DeepSeek trong pipeline dài hạn, nên ưu tiên V4 Flash ở chế độ Hybrid hơn là DeepSeek-only.**

## Vấn đề của DeepSeek-only

DeepSeek-only viết khá tự nhiên và đủ dài, nhưng chưa an toàn để xuất bản thẳng.

Các lỗi/chỗ yếu chính:

- Dùng lại nhiều thuật ngữ tiếng Anh dù prompt cấm: `MFE`, `MAE`, `breakout`, `proxy`.
- Gọi thất bại 5% là "cắt lỗ 5%" trong nhiều đoạn, làm lẫn metric mô tả với rule giao dịch.
- Viết ngôn ngữ hơi marketing như "cỗ máy in tiền", dù đặt trong phủ định.
- Tự dựng phần "Chiến lược đề xuất từ nghiên cứu", dễ làm chapter trượt sang hệ thống giao dịch.
- Có các câu dễ overclaim như "lợi nhuận tiềm năng cao hơn rủi ro" hoặc "chiến lược ... có thể tạo ra lợi nhuận dương ổn định".
- Claim Ledger có ích nhưng chứa nhiều claim rủi ro cao về backtest, Monte Carlo và trading setup.

Kết luận: DeepSeek-only hữu ích để lấy văn phong và ý tưởng diễn giải, nhưng **không nên dùng làm bản xuất bản trực tiếp**.

## Vấn đề của Hybrid

Hybrid tốt hơn DeepSeek-only vì output có cấu trúc JSON và có `claims_to_verify`, nhưng vẫn chưa đủ sạch.

Các lỗi/chỗ yếu chính:

- Vẫn dùng thuật ngữ tiếng Anh trong body: `breakout`, `MFE`, `MAE`, `stop loss`, `proxy`.
- Có một số câu dùng từ "khuyến nghị", chưa phù hợp với tài liệu không phải khuyến nghị giao dịch.
- Một số claim cần guard lại, nhất là claim liên quan entry delay, lợi nhuận dương và hiệu quả trong bear/bull.
- Output bọc trong code fence dù prompt yêu cầu JSON duy nhất; parse được nhưng pipeline cần strip fence.

Kết luận: Hybrid là hướng tốt nhất để scale, nhưng phải có lớp:

```text
AI JSON -> strip fence -> JSON schema validation -> banned term scan -> claim guard -> placeholder replacement -> PDF renderer
```

## So sánh điểm

| Phiên bản | Điểm thô | Điểm sau guard/editor | Nhận định |
|---|---:|---:|---|
| Codex-only hiện tại | 88-90 | 88-90 | Tốt nhất để release hiện tại vì kiểm soát chắc và layout đã ổn |
| DeepSeek-only | 58-65 | 72-78 nếu biên tập mạnh | Có chất liệu văn phong nhưng quá rủi ro nếu xuất bản thẳng |
| Hybrid | 72-78 | 88-92 nếu có guard tốt | Hướng tốt nhất cho hệ thống dài hạn |

## Quyết định khuyến nghị

Không dùng DeepSeek-only để thay bản hiện tại.

Nên giữ **Codex-only** làm bản release Bull Flag hiện tại, đồng thời triển khai thử **Hybrid pipeline** nếu muốn scale sang các mẫu hình khác.

Ưu tiên kỹ thuật tiếp theo nếu đi theo Hybrid:

1. Tạo `ai_writer_input.json` từ publication payload.
2. Tạo schema cho AI section JSON.
3. Tự động strip code fence và validate JSON.
4. Scan banned terms: `MFE`, `MAE`, `breakout`, `target-hit`, `stop loss`, `proxy`, `khuyến nghị`, `đảm bảo`, `chắc chắn`.
5. Tạo claim ledger machine-readable.
6. Chỉ đưa section qua PDF nếu mọi claim định lượng map được về payload.

Kết luận thực nghiệm: **DeepSeek viết được, nhưng chưa thay được lớp editorial/guard của Codex. Hybrid đáng làm, DeepSeek-only không đáng dùng làm đường xuất bản chính.**
