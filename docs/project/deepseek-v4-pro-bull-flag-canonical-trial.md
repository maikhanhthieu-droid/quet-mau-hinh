# DeepSeek V4 Pro Canonical Trial - Bull Flag

## Mục tiêu

Chạy thử DeepSeek V4 Pro như lớp viết nội dung cho chương Bull Flag, nhưng vẫn
giữ Codex/code ở vai trò điều phối, kiểm soát fact, cleanup, gate và render.

Luồng dùng trong thử nghiệm:

```text
locked Bull Flag payload + source notes
  -> canonical_editorial_workflow_v1
  -> DeepSeek V4 Pro block writing
  -> DeepSeek V4 Pro repair pass
  -> deterministic public terminology cleanup
  -> canonical_chapter_content_generator_v1
  -> canonical_ai_editorial_gate_v1
```

## Artifact

- Output dir: `artifacts/scanner_v2/bull_flags_ai_writing_canonical_v4_pro`
- Approved sections: `approved_ai_sections.json`
- Guard: `approved_ai_sections_guard.json`
- Metadata: `run_meta.json`

## Kết quả chạy thật

Model: `deepseek-v4-pro`

Các block chính:

| Block | Thời gian | Prompt tokens | Completion tokens | Ghi chú |
|---|---:|---:|---:|---|
| `source_rule_grounding` | 164.567s | 38,159 | 8,275 | Đọc nguồn và quy tắc hình thái |
| `metrics_interpreter` | 117.076s | 42,816 | 5,855 | Diễn giải số liệu |
| `example_caption_writer` | 99.999s | 44,771 | 6,995 | Viết caption |
| `public_chapter_writer` | 102.271s | 49,430 | 5,808 | Viết section public |
| `critic_red_team` | 41.578s | 53,339 | 2,023 | Review lỗi |
| repair pass | 180.911s | 4,738 | 11,711 | Làm mượt và bỏ thuật ngữ nội bộ |

## Kết quả gate

Sau writer pass đầu, gate fail vì:

- còn `MFE` / `MAE` trong body;
- summary chưa đủ ngôn ngữ diễn giải theo `canonical_ai_editorial_gate_v1`.

Sau repair pass và cleanup deterministic:

- `canonical_ai_editorial_gate_v1`: PASS
- Body scan các thuật ngữ cấm trong `editorial_sections`: clean
- Heuristic Bulkowski-spirit score: PASS theo máy, nhưng không được hiểu là
  tương đương 100% tài liệu gốc.

## Đánh giá thực chất

So với cách Codex tự viết hoặc các flow nội sinh trước đây, hướng V4 Pro tốt
hơn ở các điểm:

- Tour hình học rõ hơn: cột cờ, thân cờ, đường xu hướng, xác nhận và lỗi nhận
  diện đều được diễn giải thành tiếng Việt dễ đọc.
- Số liệu được gắn với cách hiểu, không chỉ in bảng.
- Phần thất bại có chất practitioner hơn: không chỉ nói tỷ lệ, mà nói thất bại
  trông như thế nào trên đồ thị.
- DeepSeek vẫn cần critic/cleanup. Nếu dùng output thẳng, nó còn rò thuật ngữ
  kỹ thuật và câu gần trading instruction.

Mức đánh giá: dùng được làm nền cho quy trình viết chuẩn, đạt khoảng 8-9 phần
"tinh thần tài liệu gốc" ở mức nội dung diễn giải, nhưng chưa phải 100% vì còn
cần layout/chapter rendering, ví dụ biểu đồ, bảng và bản PDF cuối.

## Quy tắc rút ra

- DeepSeek V4 Pro nên là writer/critic chính cho nội dung dài.
- Không dùng DeepSeek-only để xuất bản trực tiếp.
- Block cuối vẫn phải là deterministic cleanup + gate.
- Mọi chapter khác phải dùng cùng adapter canonical, không viết prompt riêng
  theo từng family.
