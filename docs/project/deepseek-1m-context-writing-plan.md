# Thiết kế lại prompt DeepSeek theo 1M context

Ngày cập nhật: 2026-05-18

## Điều chỉnh nhận thức sau khi đọc docs

Lượt test DeepSeek trước dùng **compact payload** khoảng 24K input tokens. Cách đó không tận dụng được lợi thế chính của DeepSeek V4: context dài.

Theo tài liệu DeepSeek API:

- `deepseek-v4-flash` và `deepseek-v4-pro` có **context length 1M**.
- Max output là **384K**.
- `deepseek-chat` và `deepseek-reasoner` là tên tương thích cũ, hiện map sang V4 Flash non-thinking/thinking và sẽ bị deprecate.
- Context caching tự động hoạt động theo prefix trùng lặp; nếu nhiều request dùng cùng phần đầu vào lớn, request sau có thể được cache hit.
- JSON Output cần `response_format={"type":"json_object"}`, prompt có chữ `json`, ví dụ output JSON, và `max_tokens` đủ lớn để tránh bị cắt cụt.

Hàm ý: thay vì chỉ gửi một payload rút gọn, nên gửi **full research dossier** gồm dữ liệu, thống kê, report hiện tại, prompt guard, caveat, chart metadata và cả output Codex baseline để DeepSeek đóng vai trò editor/reviewer/writer có ngữ cảnh đầy đủ.

## Vì sao prompt cũ chưa đủ sâu

Prompt cũ thất bại ở ba điểm:

1. **Thiếu context nguyên bản**  
   DeepSeek chỉ thấy compact JSON, nên nó tự suy diễn các đoạn nhận diện, chiến thuật, failure và ví dụ.

2. **Không có baseline PDF/manuscript để làm chuẩn phong cách**  
   Tôi tránh gửi PDF để test độc lập, nhưng khi mục tiêu là nâng chất lượng xuất bản, cần gửi bản hiện tại để model biết phải cải thiện cái gì.

3. **Không có nhiệm vụ audit trước khi viết**  
   Model được yêu cầu viết ngay. Với context 1M, nên bắt nó làm theo quy trình: đọc dossier -> lập claim inventory -> phát hiện risk -> đề xuất outline -> viết section -> tự audit.

## Chiến lược mới

Không dùng DeepSeek như “writer tự do”. Dùng theo ba pass:

| Pass | Mục tiêu | Output |
|---|---|---|
| Pass A: Audit | Đọc toàn bộ dossier, phát hiện claim/risk/gap | JSON audit |
| Pass B: Editorial rewrite | Viết lại section theo payload + audit | JSON section draft |
| Pass C: Critic | Tự kiểm output theo banned terms, overclaim, missing evidence | JSON review |

Codex vẫn giữ vai trò:

- render PDF;
- thay số liệu từ payload;
- validate JSON;
- scan banned terms;
- map claim về metric;
- quyết định đoạn nào được đưa vào bản xuất bản.

## Input dossier nên gửi cho DeepSeek 1M

Không cần nén quá mạnh. Nên gửi theo thứ tự cố định để tận dụng cache prefix.

```text
<SYSTEM_RULES>
Vai trò, điều cấm, thuật ngữ tiếng Việt chuẩn, non-advice policy.
</SYSTEM_RULES>

<PROJECT_CONTRACT>
docs/project/bulkowski-vietnam-methodology-contract.md
docs/project/bulkowski-vietnam-statistics-contract.md
docs/project/bulkowski-vietnam-release-gate.md
docs/project/pattern-calibration-framework.md
</PROJECT_CONTRACT>

<BULL_FLAG_SOURCE_GROUNDING>
artifacts/scanner_v2/bull_flags_source_grounding/bull_flag_source_notes.json
artifacts/scanner_v2/bull_flags_public_chapter/bull_flag_content_parity_audit.md
</BULL_FLAG_SOURCE_GROUNDING>

<CORE_DATA>
artifacts/scanner_v2/bull_flags/statistics.json
artifacts/scanner_v2/bull_flags/events.csv
artifacts/scanner_v2/bull_flags/post_breakout_path.csv
</CORE_DATA>

<PUBLICATION_PAYLOAD>
artifacts/scanner_v2/bull_flags_publication_chapter/bull_flag_publication_payload.json
artifacts/scanner_v2/bull_flags_public_chapter/bull_flag_public_chapter_payload.json
</PUBLICATION_PAYLOAD>

<CURRENT_BASELINE>
artifacts/scanner_v2/bull_flags_public_chapter/bull_flag_ai_editorial_manuscript.md
Extracted text from bull_flag_public_chapter.pdf
</CURRENT_BASELINE>

<CHART_METADATA>
Chart file paths, symbols, captions, event metadata.
</CHART_METADATA>
```

## Prompt 3A: Long-context audit

```text
Bạn là editor kiểm định chương nghiên cứu mẫu hình giá. Bạn được cung cấp toàn bộ dossier của chương Cờ tăng / Bull Flag. Nhiệm vụ của bạn KHÔNG phải viết lại ngay, mà là audit.

Luật:
- Chỉ dùng thông tin trong dossier.
- Không tự tạo số liệu.
- Không biến tài liệu thành khuyến nghị mua/bán.
- Không dùng thuật ngữ tiếng Anh trong output, trừ khi nằm trong tên field kỹ thuật.
- Nếu một claim không có bằng chứng trong dossier, đánh dấu "unsupported".
- Nếu một claim có bằng chứng nhưng cần caveat, đánh dấu "supported_with_caveat".

Đầu ra phải là JSON hợp lệ:
{
  "chapter_positioning": {
    "one_sentence": "...",
    "allowed_claim_level": "...",
    "forbidden_claims": ["..."]
  },
  "metric_inventory": [
    {
      "metric": "...",
      "value": "...",
      "source_path_or_field": "...",
      "interpretation_allowed": "...",
      "interpretation_forbidden": "..."
    }
  ],
  "current_text_audit": [
    {
      "section": "...",
      "issue": "...",
      "severity": "low|medium|high",
      "fix": "..."
    }
  ],
  "claim_ledger": [
    {
      "claim": "...",
      "status": "supported|supported_with_caveat|unsupported",
      "evidence": "...",
      "required_caveat": "..."
    }
  ],
  "recommended_outline": [
    {
      "section": "...",
      "purpose": "...",
      "must_include_metrics": ["..."],
      "must_avoid": ["..."]
    }
  ],
  "banned_term_replacements": [
    {
      "bad_term": "...",
      "replacement": "..."
    }
  ]
}
```

## Prompt 3B: Long-context section writer

Prompt này dùng sau khi có audit JSON.

```text
Bạn là writer phụ. Hãy viết lại các section public-facing cho chương Cờ tăng / Bull Flag, dựa trên dossier và audit JSON.

Luật:
- Output phải là JSON hợp lệ.
- Không viết markdown.
- Không tự tạo bảng.
- Không tự tạo số liệu.
- Không dùng thuật ngữ tiếng Anh trong body: MFE, MAE, breakout, target-hit, stop loss, proxy.
- Không dùng các cụm: đảm bảo, chắc chắn, nên mua, khuyến nghị mua, xác suất thắng thực tế.
- Mỗi đoạn phải có một mục đích rõ: giải thích nhận diện, giải thích thống kê, giải thích rủi ro, hoặc nêu giới hạn.
- Nếu cần số liệu, dùng đúng field trong dossier.
- Không được viết như hệ thống giao dịch; phần thực thi chỉ là kiểm tra phụ trợ.

Đầu ra:
{
  "title": "Cờ tăng",
  "subtitle": "...",
  "deck": "...",
  "sections": [
    {
      "id": "summary",
      "title": "Tóm tắt chương",
      "subtitle": "...",
      "paragraphs": ["...", "..."],
      "callout": {
        "title": "...",
        "bullets": ["...", "..."]
      },
      "claims_used": ["..."]
    }
  ],
  "example_captions": {
    "schematic": "...",
    "success": "...",
    "middle": "...",
    "failure": "..."
  },
  "final_caveat": "...",
  "claims_to_verify": [
    {
      "claim": "...",
      "metric_field": "...",
      "risk": "low|medium|high"
    }
  ]
}
```

## Prompt 3C: Long-context critic

```text
Bạn là reviewer cuối cùng. Hãy kiểm tra JSON section draft so với toàn bộ dossier.

Đầu ra JSON:
{
  "pass": true|false,
  "blocking_issues": [
    {
      "section_id": "...",
      "issue": "...",
      "evidence": "...",
      "required_fix": "..."
    }
  ],
  "banned_terms_found": [
    {
      "term": "...",
      "section_id": "...",
      "replacement": "..."
    }
  ],
  "unsupported_claims": [
    {
      "claim": "...",
      "reason": "..."
    }
  ],
  "overclaim_risks": [
    {
      "claim": "...",
      "safer_rewrite": "..."
    }
  ],
  "ready_for_codex_renderer": true|false
}
```

## API settings đề xuất

### Audit / Writer JSON

```python
response = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[
        {"role": "system", "content": system_rules},
        {"role": "user", "content": long_context_prompt}
    ],
    response_format={"type": "json_object"},
    max_tokens=20000,
    temperature=0.2,
)
```

Lý do:

- JSON Output docs yêu cầu `response_format={"type":"json_object"}` và prompt có chữ JSON.
- `max_tokens` phải đủ lớn để tránh bị cắt cụt.
- Nên giữ temperature thấp để giảm overclaim.

### Long-context cache strategy

Gửi các request theo cùng prefix:

```text
SYSTEM_RULES + PROJECT_CONTRACT + CORE_DATA + BASELINE
```

Sau đó thay đổi phần cuối:

```text
TASK = audit
TASK = writer
TASK = critic
```

DeepSeek context cache hoạt động theo prefix trùng lặp, nên cách này có thể giảm chi phí/latency ở request sau.

## Khác biệt so với prompt cũ

| Điểm | Prompt cũ | Prompt 1M mới |
|---|---|---|
| Input | Compact JSON ~24K tokens | Full dossier, có thể 100K-300K+ tokens |
| Workflow | Viết ngay | Audit -> Write -> Critic |
| Baseline PDF | Không gửi | Gửi text baseline để cải thiện trực tiếp |
| Claim guard | Hậu kiểm thủ công | Bắt model tạo claim ledger trước |
| JSON mode | Chỉ yêu cầu bằng prompt | Dùng API `response_format` |
| Cache | Không tối ưu prefix | Thiết kế prefix cố định |
| Output | Markdown/JSON draft | JSON có section IDs, claims, callouts |

## Kết luận

Với 1M context, cách đúng không phải hỏi DeepSeek "hãy viết chương". Cách đúng là đưa nó toàn bộ dossier và buộc nó làm việc như một editor có kiểm toán:

```text
full dossier -> audit JSON -> section JSON -> critic JSON -> Codex guard -> PDF
```

Nếu triển khai bước này, DeepSeek V4 Flash có thể hữu ích hơn nhiều so với lượt test compact-context trước.
