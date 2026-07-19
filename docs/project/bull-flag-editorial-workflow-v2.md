# Bull Flag Editorial Workflow V2

Ngày chốt: 2026-05-18

## Mục tiêu

Luồng này tách rõ ba vai trò:

1. Code tính toán tạo dữ kiện khóa.
2. DeepSeek đọc và viết theo từng block chuyên trách.
3. Code hậu kiểm, sửa deterministic và chỉ đưa nội dung sạch vào PDF.

Không dùng DeepSeek như nguồn sự thật. DeepSeek chỉ là lớp đọc hồ sơ, biên tập và phản biện.

## Luồng chính

```text
scan / metrics / charts
  -> source block
  -> metrics block
  -> examples block
  -> writer block
  -> critic block
  -> deterministic synthesizer
  -> public-text cleaner
  -> body/caption guard
  -> PDF builder
  -> PDF text QA
```

## Artefact chuẩn

| Artefact | Vai trò |
|---|---|
| `artifacts/scanner_v2/bull_flags/statistics.json` | Dữ kiện thống kê |
| `artifacts/scanner_v2/bull_flags/events.csv` | Dữ kiện event và ví dụ |
| `artifacts/scanner_v2/bull_flags_publication_chapter/bull_flag_publication_payload.json` | Payload xuất bản đã khóa |
| `artifacts/scanner_v2/bull_flags_ai_writing_blocked_v4_flash/approved_ai_sections.json` | Nội dung AI đã hậu kiểm để PDF dùng |
| `artifacts/scanner_v2/bull_flags_ai_writing_blocked_v4_flash/approved_ai_sections_guard.json` | Kết quả guard cho nội dung AI |
| `artifacts/scanner_v2/bull_flags_public_chapter_trial_ai_blocks/bull_flag_public_chapter.pdf` | PDF trial dùng AI sections |

## Lệnh chạy chuẩn

```bash
python3 scanner/run_deepseek_blocked_bull_flag_editorial.py
```

Lệnh build PDF trial:

```bash
CHARTPATTERNSCAN_ALLOW_LEGACY_PUBLICATION_BUILDER=1 python3 scanner/_legacy_quarantine/build_bull_flag_public_chapter.py \
  --ai-sections artifacts/scanner_v2/bull_flags_ai_writing_blocked_v4_flash/approved_ai_sections.json \
  --out-dir artifacts/scanner_v2/bull_flags_public_chapter_trial_ai_blocks
```

Nếu môi trường Python thiếu thư viện PDF, tạo venv tạm từ `requirements.txt`.

## Gate chốt logic

Một output AI chỉ được đưa vào PDF khi:

- `approved_ai_sections_guard.json.pass = true`.
- `body_banned_terms = {}`.
- `caption_banned_terms = {}`.
- PDF text không có các cụm: `MFE`, `MAE`, `breakout`, `stop loss`, `half-staff`, `swing`, `path dữ liệu`, `research`, `setup`, `proxy`, `available`.
- Tests liên quan public chapter pass.

## Quyết định thiết kế

- Long-context một cục dùng tốt cho audit tổng thể, nhưng không ổn định bằng block pipeline cho xuất bản.
- Block cuối không gọi DeepSeek nữa. Tổng hợp cuối là deterministic code để tránh lỗi JSON dài/cắt output.
- Critic output là checklist, không phải quyết định cuối. Quyết định cuối nằm ở local guard và PDF QA.
- Field kỹ thuật có thể chứa tên field như `median_mfe_pct`, nhưng body/caption public không được chứa thuật ngữ đó.
