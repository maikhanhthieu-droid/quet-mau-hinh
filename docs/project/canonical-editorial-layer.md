# Canonical Editorial Layer

## Mục tiêu

Lớp này giải quyết điểm yếu hiện tại của các chapter public: nội dung có đủ
số liệu nhưng còn mỏng về diễn giải. Từ nay, trước khi render PDF, mỗi chapter
phải đi qua một lớp biên tập riêng.

```text
scanner/statistics/source-grounding
  -> editorial dossier
  -> AI hoặc human editorial pass
  -> canonical_chapter_content_generator_v1
  -> canonical_ai_editorial_gate_v1
  -> canonical_publication_chapter_factory_v1
  -> pattern_publication_core_v1
```

## Vai trò của AI

AI không được làm nguồn sự thật. AI chỉ được:

- đọc số liệu đã khóa;
- viết diễn giải tiếng Việt;
- biến mỗi con số chính thành câu trả lời: người đọc nên hiểu gì;
- viết caption ví dụ theo dữ liệu event đã khóa;
- đề xuất chỗ cần thận trọng.

AI không được:

- tự thêm số liệu;
- tự đổi target hoặc branch;
- viết như tín hiệu mua/bán;
- dùng thuật ngữ nội bộ trong body;
- đưa claim không truy ngược được về metric hoặc caveat.

## Prompt block chuẩn

Không yêu cầu model viết cả chương trong một lần. Tất cả chapter dùng cùng
`canonical_editorial_workflow_v1`, chia thành block:

1. `source_rule_grounding`: đọc hình thái và quy tắc nguồn.
2. `metrics_interpreter`: chuyển số liệu thành inventory diễn giải.
3. `example_caption_writer`: viết caption ví dụ và tự kiểm event fields.
4. `public_chapter_writer`: viết các section public bằng tiếng Việt.
5. `critic_red_team`: bắt lỗi overclaim, mỏng diễn giải, thuật ngữ nội bộ.
6. `deterministic_synthesizer`: code tổng hợp output sạch, không để model tự merge cuối.

Điểm quan trọng: các block này **không tối ưu riêng từng mẫu hình**. Mẫu hình
chỉ cung cấp dữ kiện khác nhau; workflow viết, section role và guard giống
nhau cho toàn bộ sách.

Mỗi chapter phải tạo dossier theo schema chung:

- `chapter_identity`;
- `facts_locked`;
- `source_rule_inventory`;
- `example_inventory`;
- `section_roles`;
- `required_output_schema`.

Module chuẩn là `scanner/canonical_editorial_workflow.py`.

## Điểm tập trung nội dung

Từ mốc này, mọi nội dung public phải đi qua
`scanner/canonical_chapter_content.py`. Module này là nơi duy nhất được map
output AI/human thành `editorial_sections`.

Các family builder không được tự viết hoặc tự map `editorial_sections` cho bản
final. Chúng chỉ được cung cấp facts, examples, source notes và đường dẫn tới
artifact AI/human đã duyệt. Content generator chung sẽ:

- đọc `approved_ai_sections.json` hoặc approved human sections;
- map các alias như `intro`, `how_it_works`, `usage` về 8 section chuẩn;
- gắn `canonical_content_generator_id`;
- ghi `editorial_source_path` và source kind;
- chuyển payload đã chuẩn hóa sang editorial gate.

Các hàm cũ như `build_ai_editorial_sections()` hoặc `_editorial_sections()`
chỉ còn là legacy/draft adapter. Chúng không được dùng để promote final PDF.

## Cổng chất lượng

`canonical_ai_editorial_gate_v1` hiện kiểm:

- đủ 8 section: `summary`, `tour`, `failure`, `statistics`,
  `post_breakout`, `size_volume`, `tactics`, `checklist`;
- mỗi section đủ số đoạn và độ dài tối thiểu;
- có ngôn ngữ diễn giải cho người đọc, không chỉ liệt kê số;
- không rò thuật ngữ như `MFE`, `MAE`, `breakout`, `scanner`, `pipeline`,
  `payload`, `factory`;
- section nhiều số phải có đủ câu giải thích ý nghĩa.

Nếu gate fail, canonical factory không được render PDF.

## Chuẩn văn phong v2

Vòng Bull Flag ngày 2026-05-23 cho thấy chỉ qua gate độ dài là chưa đủ. Một
chapter có thể đúng số liệu nhưng vẫn đọc như báo cáo kỹ thuật. Vì vậy
`canonical_editorial_workflow_v1` đã thêm `public_chapter_style_blueprint`.

Nhịp viết bắt buộc từ đây:

1. Mở bằng hành vi trên biểu đồ, không mở bằng bảng số.
2. Gọi tên hành vi bằng tiếng Việt dễ hiểu.
3. Chỉ đưa một hoặc hai con số chính sau khi người đọc đã thấy hình thái.
4. Giải thích con số đó làm thay đổi cách đọc biểu đồ như thế nào.
5. Chốt bằng ranh giới: khi nào nên giảm độ tin cậy, hoặc điều gì không được
   overclaim.

Mỗi phần chính cần đọc như một đoạn hướng dẫn sử dụng mẫu hình:

- `summary`: định vị mẫu, kết quả chính, vai trò sử dụng và giới hạn.
- `tour`: dẫn người đọc từ nhịp trước mẫu, vùng hình thành, đến xác nhận.
- `failure`: mô tả giải phẫu thất bại, không chỉ nêu tỷ lệ.
- `statistics`: biến từng con số headline thành hàm ý đọc biểu đồ.
- `post_breakout`: giải thích đường đi sau xác nhận, không chỉ kết quả cuối.
- `size_volume`: nói điều kiện nào làm mẫu sắc nét hoặc nhiễu hơn.
- `tactics`: đưa workflow đọc mẫu, không biến thành lời khuyên giao dịch.
- `checklist`: ngắn, thao tác được, không có thuật ngữ nội bộ.

Các từ vận hành nội bộ như `regime`, `bucket`, `proxy`, `margin`,
`zero-and-stale`, `scanner`, `payload`, `factory` không được xuất hiện trong
body public. Nếu cần giữ ý nghĩa, phải Việt hóa thành bối cảnh thị trường,
nhóm, dấu hiệu thay thế, đòn bẩy, giá đứng yên/thiếu giao dịch, v.v.

Kết quả thử nghiệm Bull Flag `style_v2`:

- approved sections tăng từ khoảng 7.082 lên 13.042 ký tự;
- PDF tăng từ 9 lên 10 trang;
- canonical flow audit: pass;
- editorial gate: pass;
- full test suite: `245 passed`;
- lỗi formatter số tròn `digits=0` đã được vá để không biến `20` thành `2`.

## Chuẩn văn phong v3

Vòng Bull Flag tiếp theo cho thấy vẫn còn hai điểm làm chapter đọc giống báo
cáo nội bộ: bảng xuất hiện quá nhiều mà chưa có câu nối diễn giải, và caption
ví dụ còn giống nhãn biểu đồ hơn là case study. Từ v3, prompt và renderer cùng
phải xử lý hai điểm này.

Prompt v3 thêm các quy tắc:

- mỗi bảng phải được bao bởi một ý đọc biểu đồ, không để bảng làm giọng nói
  chính của chương;
- caption ví dụ phải có ba nhịp: điều cần nhìn trên biểu đồ, dữ kiện event
  thật, bài học đọc mẫu;
- model không được tự thêm số ngày, tỷ lệ khối lượng, mức tăng hoặc outcome
  nếu trường đó không có trong `example_inventory`;
- tránh văn báo cáo kiểu chỉ so sánh số mà không nói người đọc nên hiểu gì.

Renderer v3 thêm các lớp deterministic:

- bridge paragraph sau các bảng chính: kết quả, nhận diện, thất bại, mục tiêu,
  điều kiện sử dụng;
- caption ví dụ được dựng từ event thật để tránh model bịa số;
- phụ lục không bị ép ngắt trang cứng; phần cuối có bảng cách dùng phụ lục để
  tránh trang trắng và giữ vai trò đọc cho nhà đầu tư;
- các caveat/spec text đi qua `_public_term()` để không rò `Flag Family`,
  `Corporate actions`, `delisted/halted`, `status tape`, hoặc các cụm tiếng Anh
  nội bộ.

Kết quả Bull Flag `style_v3`:

- DeepSeek V4 Pro style v3 đã chạy đủ block và editorial gate pass, nhưng bản
  văn AI v3 ngắn hơn style v2 và có câu quá gần ngôn ngữ giao dịch; vì vậy
  không dùng nguyên văn cho PDF;
- bản PDF cuối dùng approved text style v2 đã sạch, cộng renderer v3;
- PDF còn 9 trang, khoảng 27.8k ký tự và 6.1k từ;
- không còn leak các thuật ngữ nội bộ đã kiểm: `scanner`, `pipeline`,
  `payload`, `factory`, `MFE`, `MAE`, `target-hit`, `target-first`,
  `Flag Family`, `Corporate actions`, `delisted/halted`, `status tape`,
  `vào lệnh`, `dừng lỗ`;
- PNG review không còn trang trắng cụt; trang cuối là phần kết thúc phụ lục có
  nội dung sử dụng.

## Vì sao cần lớp này

`pattern_publication_core_v1` chỉ là máy in. Nó có thể in một bản mỏng hoặc
một bản tốt nếu input hợp lệ. Vấn đề các vòng trước là family script tự tạo
`editorial_sections`, gọi core, rồi coi output là final.

Lớp editorial mới chặn lỗi đó ở trước nhà in: chưa đủ diễn giải thì không có
canonical PDF.
