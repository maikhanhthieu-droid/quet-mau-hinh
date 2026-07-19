# Canonical Publication Flow

## Nguyên tắc

Từ mốc này, một chapter chỉ được gọi là `final` nếu PDF public được sinh qua
`canonical_publication_chapter_factory_v1` và đạt chuẩn trình bày
`canonical_publication_style_v3`.

Các scanner/family builder không được tự quyết định cấu trúc PDF public. Chúng
chỉ được cung cấp nguyên liệu:

- rule hình thái và source-grounding;
- event table, post-breakout path, thống kê và target calibration;
- ví dụ biểu đồ;
- diễn giải riêng của pattern/family ở dạng payload có cấu trúc.

Quyền dựng PDF public cuối cùng thuộc về canonical factory.

Trước canonical factory phải có một lớp biên tập nội dung:

```text
data/statistics đã khóa
  -> canonical_editorial_workflow_v1
  -> AI hoặc human editorial pass
  -> canonical_chapter_content_generator_v1
  -> canonical_ai_editorial_gate_v1
  -> canonical_publication_chapter_factory_v1
  -> pattern_publication_core_v1
```

`canonical_editorial_workflow_v1` là workflow viết chung cho mọi chapter. Nó
chuẩn hóa dossier, block prompt, section role và output schema. Mẫu hình khác
nhau được phép khác dữ kiện, nhưng không được tự sinh một flow viết riêng.

Lớp `canonical_ai_editorial_gate_v1` không gọi AI. Nó kiểm đầu ra của AI/human
editorial pass: mỗi section phải đủ dài, có diễn giải cho người đọc biểu đồ,
không chỉ liệt kê số, và không rò thuật ngữ nội bộ như `scanner`, `pipeline`,
`payload`, `MFE`, `MAE`.

`canonical_publication_style_v3` là chuẩn đang hoạt động. V3 lấy Bull Flag bản
đã gọt dũa làm mốc: bảng phải có cầu nối bằng chữ, ví dụ biểu đồ phải đọc như
case study nhỏ, phụ lục không được kết thúc cụt, và toàn bộ PDF không được rò
ngôn ngữ audit nội bộ. Khi một chapter mới làm tốt hơn V3, cải tiến đó phải
được đưa ngược vào canonical layer, không được nằm trong script riêng của
chapter đó.

`canonical_chapter_content_generator_v1` là điểm duy nhất được phép đưa nội
dung đã duyệt vào `editorial_sections`. Điều này tránh việc mỗi chapter hoặc
mỗi family tự viết một hàm sinh nội dung riêng rồi gọi thẳng renderer. Khác
biệt giữa các chapter phải nằm ở dữ kiện đã khóa, không nằm ở logic viết public
riêng.

## Policy viết nội dung mới

Từ sau vòng Bull Flag source-guided refinement, baseline viết nội dung mới là:

```text
source/style dossier từ chương gốc tương ứng
  -> source-guided AI candidate
  -> refinement pass trên approved sections đã pass
  -> canonical_chapter_content_generator_v1
  -> canonical_publication_chapter_factory_v1
  -> style-v3 audit + visual PDF review
```

Policy id:

```text
canonical_source_guided_refinement_v1
```

Policy này không thay scanner, không thay thống kê và không thay target
calibration. Nó chỉ kiểm soát lớp viết public: AI được học cấu trúc và nhịp
diễn giải từ tài liệu gốc, nhưng không được sao chép, dịch lại hoặc mượn số liệu
gốc làm số liệu Việt Nam. Số liệu thật vẫn đến từ payload đã khóa.

Các artifact tối thiểu của một chapter viết theo policy này:

- `source_style_dossier`: dossier phong cách/hình thái trích từ chương gốc liên quan.
- `source_guided_ai_sections`: bản AI source-guided đầu tiên đã qua gate.
- `refined_ai_sections`: bản biên tập lại từ AI source-guided candidate.
- `canonical_pdf`: PDF render bằng canonical factory.
- `style_v3_audit`: audit PDF đã render.

Contract máy đọc được nằm trong:

```text
scanner.publication_flow_contract.validate_source_guided_refinement_contract
```

Mục đích là tránh mất ngữ cảnh hội thoại: chapter mới hoặc chapter được nâng
cấp không nên quay lại kiểu tự sinh nội dung nội bộ. Nếu thiếu refinement pass
hoặc thiếu style dossier từ tài liệu gốc, chapter vẫn có thể là draft, nhưng
không nên gọi là bản public đã gọt dũa theo chuẩn mới.

## Vì sao cần chốt lại

Các vòng trước dùng chung `pattern_publication_core_v1`, nhưng từng family vẫn
tự sinh `editorial_sections` và tự gọi renderer. Điều này làm validator thấy
đủ artifact kỹ thuật nhưng PDF vẫn có thể đọc như báo cáo nội bộ. Lỗi này đã
lặp lại ở nhiều family.

Do đó, `pattern_publication_core_v1` chỉ còn là lõi render thấp tầng. Nó không
phải dấu hiệu đủ để gọi chapter là final.

## Cổng bắt buộc

Một entry final trong `artifacts/final_chapters/final_chapters_manifest.json`
phải có:

- `factory_id = canonical_publication_chapter_factory_v1`
- `publication_flow = canonical_publication_chapter_factory_v1 + pattern_publication_core_v1`
- `canonical_publication_factory_id = canonical_publication_chapter_factory_v1`
- `canonical_reader_experience_gate_id = canonical_reader_experience_gate_v1`
- `canonical_publication_style_version = canonical_publication_style_v3`
- `canonical_editorial_workflow_id = canonical_editorial_workflow_v1`
- `canonical_ai_editorial_gate_id = canonical_ai_editorial_gate_v1`
- `canonical_content_generator_id = canonical_chapter_content_generator_v1`

Payload, manuscript và notes cũng phải chứa dấu vết canonical tương ứng.

Không có cờ opt-out cho final chapter. Nếu một chapter cần chạy thử bằng
factory cũ, nó chỉ được xem là draft/internal artifact và không được promote
vào manifest final.

## Audit hiện tại

Chạy:

```bash
PYTHONPATH=. ./.venv/bin/python -m scanner.audit_canonical_publication_flow
```

Kết quả được ghi vào:

- `artifacts/final_chapters/governance/canonical_publication_flow_audit.json`
- `artifacts/final_chapters/governance/canonical_publication_flow_audit.csv`
- `artifacts/final_chapters/governance/canonical_publication_flow_audit.md`

Nếu audit FAIL, chapter chưa được gọi là canonical final dù các điểm thống kê
hoặc gate cũ có thể đã pass.

Sau khi render một PDF cụ thể, chạy thêm style gate:

```bash
PYTHONPATH=. ./.venv/bin/python -m scanner.audit_publication_style_v3 \
  --pdf path/to/chapter.pdf \
  --payload path/to/chapter_payload.json \
  --out path/to/style_v3_audit.json
```

Style gate đọc PDF đã render, kiểm đủ section, kiểm rò thuật ngữ nội bộ, kiểm
độ rỗng từng trang và kiểm đoạn đóng chương kiểu V3. Đây là bước bắt buộc
trước khi báo người dùng rằng một bản đã đạt publication chapter.

## Luồng chuẩn từ nay

```text
family scanner / pattern scanner
        ↓
stats + source-grounding + examples + family interpretation payload
        ↓
canonical_editorial_workflow_v1
        ↓
canonical_chapter_content_generator_v1
        ↓
canonical_ai_editorial_gate_v1
        ↓
canonical_publication_chapter_factory_v1
        ↓
reader-experience gate
        ↓
style-v3 PDF audit + visual page review
        ↓
final_chapters_manifest
```

## Vòng mở rộng an toàn

Khi mở rộng sang chapter mới, làm theo vòng sau:

1. Đối chiếu hình thái với tài liệu gốc trước khi viết scanner.
2. Chạy scanner/statistics riêng cho pattern hoặc family.
3. Tạo source/style dossier từ đúng chương gốc của pattern/family.
4. Đưa số liệu đã khóa vào `canonical_editorial_workflow_v1`.
5. Tạo source-guided AI candidate.
6. Chạy refinement pass trên `approved_ai_sections` đã qua gate.
7. Render bằng `canonical_publication_chapter_factory_v1`.
8. Chạy `audit_publication_style_v3` và xuất ảnh trang PDF để kiểm trực quan.
9. Nếu PDF còn đọc như báo cáo nội bộ, sửa canonical layer hoặc refinement prompt rồi render lại.
10. Chỉ promote khi cả flow audit, style audit, test và visual review đều pass.
