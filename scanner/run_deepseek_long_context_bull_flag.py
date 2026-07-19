from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from openai import OpenAI


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = REPO_ROOT / "artifacts/scanner_v2/bull_flags_ai_writing_long_context_v4_flash"


DOSSIER_FILES = [
    "docs/project/bulkowski-vietnam-methodology-contract.md",
    "docs/project/bulkowski-vietnam-statistics-contract.md",
    "docs/project/bulkowski-vietnam-release-gate.md",
    "docs/project/pattern-calibration-framework.md",
    "docs/project/bull-flag-ai-writing-test-results.md",
    "docs/project/deepseek-1m-context-writing-plan.md",
    "artifacts/scanner_v2/bull_flags_source_grounding/bull_flag_source_notes.md",
    "artifacts/scanner_v2/bull_flags_source_grounding/bull_flag_source_notes.json",
    "artifacts/scanner_v2/bull_flags_public_chapter/bull_flag_content_parity_audit.md",
    "artifacts/scanner_v2/bull_flags_public_chapter/bull_flag_content_parity_audit.json",
    "artifacts/scanner_v2/bull_flags/statistics.json",
    "artifacts/scanner_v2/bull_flags/events.csv",
    "artifacts/scanner_v2/bull_flags/post_breakout_path.csv",
    "artifacts/scanner_v2/bull_flags_publication_chapter/bull_flag_publication_payload.json",
    "artifacts/scanner_v2/bull_flags_public_chapter/bull_flag_public_chapter_payload.json",
    "artifacts/scanner_v2/bull_flags_public_chapter/bull_flag_ai_editorial_manuscript.md",
    "artifacts/scanner_v2/bull_flags_pdf_ai_review/bull_flags_pdf_extracted_text.txt",
    "artifacts/scanner_v2/bull_flags_public_chapter/bull_flag_public_chapter_notes.md",
    "artifacts/scanner_v2/bull_flags_tradable_setup/bull_flag_tradable_scorecard.json",
    "artifacts/scanner_v2/bull_flags_tradable_setup/bull_flag_tradable_backtest_report.md",
    "artifacts/scanner_v2/bull_flags_wider_oos/bull_flag_wider_oos_gate.json",
    "artifacts/scanner_v2/bull_flags_wider_oos/bull_flag_wider_oos_report.md",
]


BANNED_TERMS = [
    "MFE",
    "MAE",
    "breakout",
    "target-hit",
    "stop loss",
    "stop-loss",
    "stop ",
    "proxy",
    "scanner",
    "pipeline",
    "khuyến nghị mua",
    "nên mua",
    "nên bán",
    "đảm bảo",
    "chắc chắn sinh lợi",
    "xác suất thắng thực tế",
    "cỗ máy in tiền",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_dotenv() -> None:
    dotenv = REPO_ROOT / ".env"
    if not dotenv.exists():
        return
    for raw in dotenv.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        os.environ.setdefault(key, value)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _parse_json_lenient(text: str) -> Optional[Any]:
    candidate = _strip_json_fence(text)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _flatten_strings(obj: Any) -> Iterable[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, Mapping):
        for value in obj.values():
            yield from _flatten_strings(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _flatten_strings(value)


def _scan_terms(text: str) -> Dict[str, int]:
    lowered = text.lower()
    counts: Dict[str, int] = {}
    for term in BANNED_TERMS:
        n = lowered.count(term.lower())
        if n:
            counts[term] = n
    return counts


def _build_dossier() -> tuple[str, List[Dict[str, Any]]]:
    manifest: List[Dict[str, Any]] = []
    parts = [
        "<DOSSIER_SCOPE>",
        "Dossier đầy đủ cho chương Cờ tăng / Bull Flag. Chỉ dùng nội dung trong dossier để audit và viết.",
        "Các file outcome chính được đưa nguyên văn để tận dụng cửa sổ ngữ cảnh dài.",
        "Ghi chú kỹ thuật: detections.json thô không được đưa nguyên văn vì API trả về 1.443M input tokens, vượt giới hạn 1M; events.csv, post_breakout_path.csv, statistics.json và payload xuất bản vẫn được đưa nguyên văn.",
        "</DOSSIER_SCOPE>",
    ]
    skipped_large = REPO_ROOT / "artifacts/scanner_v2/bull_flags/detections.json"
    if skipped_large.exists():
        manifest.append(
            {
                "path": "artifacts/scanner_v2/bull_flags/detections.json",
                "status": "skipped_to_fit_1m_context",
                "chars": len(_read_text(skipped_large)),
                "reason": "raw detections duplicated event/path payload and caused 1M context overflow",
            }
        )
    for rel in DOSSIER_FILES:
        path = REPO_ROOT / rel
        if not path.exists():
            manifest.append({"path": rel, "status": "missing"})
            continue
        text = _read_text(path)
        manifest.append({"path": rel, "status": "included", "chars": len(text)})
        parts.extend(
            [
                f"\n<FILE path=\"{rel}\" chars=\"{len(text)}\">",
                text,
                f"</FILE path=\"{rel}\">",
            ]
        )
    return "\n".join(parts), manifest


SYSTEM_RULES = """Bạn là biên tập viên kiểm định và biên tập chương nghiên cứu mẫu hình giá bằng tiếng Việt.
Luật bắt buộc:
- Chỉ dùng thông tin trong dossier.
- Không tự tạo số liệu.
- Không biến tài liệu thành khuyến nghị mua/bán.
- Không dùng thuật ngữ tiếng Anh trong body, trừ khi đang trích tên field kỹ thuật trong mục kiểm toán.
- Nếu một claim không có bằng chứng trong dossier, đánh dấu unsupported.
- Nếu có bằng chứng nhưng cần caveat dữ liệu, đánh dấu supported_with_caveat.
- Output phải là JSON hợp lệ, không markdown fence.
"""


PROMPT_A = """<TASK>
Bạn đang ở Pass A: audit long-context.
Hãy đọc toàn bộ dossier phía trên và audit chương Cờ tăng / Bull Flag hiện tại. Không viết lại chương.

Đầu ra JSON:
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
</TASK>"""


PROMPT_B = """<TASK>
Bạn đang ở Pass B: viết lại editorial section cho bản public-facing.
Hãy dùng dossier và audit JSON ở cuối prompt để viết bản nháp chương Cờ tăng / Bull Flag.

Luật:
- Output phải là JSON hợp lệ.
- Không viết markdown.
- Không tự tạo bảng, nhưng được đề xuất tên bảng và câu dẫn bảng.
- Không tự tạo số liệu.
- Không dùng các từ tiếng Anh trong body: MFE, MAE, breakout, target-hit, stop loss, proxy, scanner, pipeline.
- Không dùng các cụm: đảm bảo, chắc chắn, nên mua, khuyến nghị mua, xác suất thắng thực tế.
- Mỗi đoạn phải có mục đích rõ: nhận diện, thống kê, rủi ro, ví dụ, hoặc giới hạn.
- Không được viết như hệ thống giao dịch; phần thực thi chỉ là kiểm tra phụ trợ.

Đầu ra JSON:
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
  "table_leads": [
    {
      "table_id": "...",
      "lead": "..."
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
</TASK>"""


PROMPT_C = """<TASK>
Bạn đang ở Pass C: critic/reviewer cuối cùng.
Hãy kiểm tra writer JSON so với toàn bộ dossier và audit JSON. Không sửa trực tiếp, chỉ nêu lỗi và rewrite an toàn nếu cần.

Đầu ra JSON:
{
  "pass": true,
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
  "publication_readiness": {
    "score_0_100": 0,
    "classification": "...",
    "next_actions": ["..."]
  }
}
</TASK>"""


def _call_deepseek(
    *,
    client: OpenAI,
    model: str,
    dossier: str,
    task_prompt: str,
    suffix_context: str,
    max_tokens: int,
    timeout_note: str,
) -> Dict[str, Any]:
    user_content = dossier + "\n\n" + suffix_context + "\n\n" + task_prompt
    start = time.perf_counter()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_RULES},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
        temperature=0.2,
    )
    elapsed = time.perf_counter() - start
    content = response.choices[0].message.content or ""
    parsed = _parse_json_lenient(content)
    usage = response.usage.model_dump() if response.usage else None
    return {
        "timeout_note": timeout_note,
        "elapsed_s": round(elapsed, 3),
        "content": content,
        "chars": len(content),
        "json_valid": parsed is not None,
        "parsed": parsed,
        "usage": usage,
        "finish_reason": response.choices[0].finish_reason,
        "banned_terms": _scan_terms("\n".join(_flatten_strings(parsed)) if parsed is not None else content),
    }


def _summarize_output(name: str, result: Mapping[str, Any]) -> List[str]:
    usage = result.get("usage") or {}
    total = usage.get("total_tokens")
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    cached = None
    details = usage.get("prompt_tokens_details")
    if isinstance(details, Mapping):
        cached = details.get("cached_tokens")
    line = (
        f"| {name} | {result.get('elapsed_s')} | {result.get('chars')} | "
        f"{'có' if result.get('json_valid') else 'không'} | {result.get('finish_reason')} | "
        f"{prompt or ''} | {completion or ''} | {total or ''} | {cached or ''} | "
        f"{json.dumps(result.get('banned_terms') or {}, ensure_ascii=False)} |"
    )
    return [line]


def _readiness_score(results: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    score = 70
    if all(r.get("json_valid") for r in results.values()):
        score += 10
    else:
        score -= 15
    banned_total = sum(sum((r.get("banned_terms") or {}).values()) for r in results.values())
    score -= min(15, banned_total * 2)
    critic = results.get("critic", {}).get("parsed")
    if isinstance(critic, Mapping):
        readiness = critic.get("publication_readiness") or {}
        blocking = critic.get("blocking_issues") or []
        unsupported = critic.get("unsupported_claims") or []
        if readiness.get("score_0_100") is not None:
            try:
                score = round((score + float(readiness["score_0_100"])) / 2)
            except Exception:
                pass
        if blocking:
            score -= 8
        if unsupported:
            score -= min(10, len(unsupported) * 2)
    score = max(0, min(100, int(score)))
    return {
        "heuristic_score": score,
        "banned_total": banned_total,
        "classification": "usable_with_guard" if score >= 85 else "needs_editorial_guard" if score >= 70 else "not_ready",
    }


def run(out_dir: Path, model: str, max_tokens_a: int, max_tokens_b: int, max_tokens_c: int) -> None:
    _load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("Missing DEEPSEEK_API_KEY in environment or .env")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=900.0)

    out_dir.mkdir(parents=True, exist_ok=True)
    dossier, manifest = _build_dossier()
    _write_text(out_dir / "long_context_dossier.txt", dossier)
    _write_json(out_dir / "dossier_manifest.json", manifest)

    meta: Dict[str, Any] = {
        "created_at": _utc_now_iso(),
        "model": model,
        "base_url": base_url,
        "dossier_chars": len(dossier),
        "manifest": manifest,
    }

    audit = _call_deepseek(
        client=client,
        model=model,
        dossier=dossier,
        suffix_context="",
        task_prompt=PROMPT_A,
        max_tokens=max_tokens_a,
        timeout_note="audit",
    )
    _write_text(out_dir / "pass_a_audit_raw.json", audit["content"])
    if audit["parsed"] is not None:
        _write_json(out_dir / "pass_a_audit_parsed.json", audit["parsed"])

    audit_suffix = "<AUDIT_JSON>\n" + json.dumps(audit["parsed"] or audit["content"], ensure_ascii=False) + "\n</AUDIT_JSON>"
    writer = _call_deepseek(
        client=client,
        model=model,
        dossier=dossier,
        suffix_context=audit_suffix,
        task_prompt=PROMPT_B,
        max_tokens=max_tokens_b,
        timeout_note="writer",
    )
    _write_text(out_dir / "pass_b_writer_raw.json", writer["content"])
    if writer["parsed"] is not None:
        _write_json(out_dir / "pass_b_writer_parsed.json", writer["parsed"])

    critic_suffix = (
        "<AUDIT_JSON>\n"
        + json.dumps(audit["parsed"] or audit["content"], ensure_ascii=False)
        + "\n</AUDIT_JSON>\n<WRITER_JSON>\n"
        + json.dumps(writer["parsed"] or writer["content"], ensure_ascii=False)
        + "\n</WRITER_JSON>"
    )
    critic = _call_deepseek(
        client=client,
        model=model,
        dossier=dossier,
        suffix_context=critic_suffix,
        task_prompt=PROMPT_C,
        max_tokens=max_tokens_c,
        timeout_note="critic",
    )
    _write_text(out_dir / "pass_c_critic_raw.json", critic["content"])
    if critic["parsed"] is not None:
        _write_json(out_dir / "pass_c_critic_parsed.json", critic["parsed"])

    results = {"audit": audit, "writer": writer, "critic": critic}
    score = _readiness_score(results)
    meta["passes"] = {
        name: {
            "elapsed_s": result["elapsed_s"],
            "chars": result["chars"],
            "json_valid": result["json_valid"],
            "finish_reason": result["finish_reason"],
            "usage": result["usage"],
            "banned_terms": result["banned_terms"],
        }
        for name, result in results.items()
    }
    meta["score"] = score
    _write_json(out_dir / "run_meta.json", meta)

    lines = [
        "# Báo cáo chạy thật DeepSeek long-context cho Bull Flag",
        "",
        f"- Thời điểm: `{meta['created_at']}`",
        f"- Model: `{model}`",
        f"- Dossier: `{len(dossier):,}` ký tự, `{sum(1 for m in manifest if m.get('status') == 'included')}` file được đưa vào.",
        f"- Phân loại heuristic: `{score['classification']}`; điểm heuristic: `{score['heuristic_score']}/100`.",
        "",
        "## Kết quả 3 pass",
        "",
        "| Pass | Giây | Ký tự output | JSON hợp lệ | Finish | Prompt tokens | Completion tokens | Total tokens | Cached tokens | Thuật ngữ/cụm rủi ro |",
        "|---|---:|---:|---|---|---:|---:|---:|---:|---|",
    ]
    for name in ["audit", "writer", "critic"]:
        lines.extend(_summarize_output(name, results[name]))
    lines.extend(
        [
            "",
            "## Nhận xét nhanh",
            "",
            "- Đây là lượt chạy long-context thật: dossier đầy đủ gồm rule contract, payload, bản thảo hiện tại, dữ liệu sự kiện, đường đi hậu phá vỡ và các báo cáo phụ trợ.",
            "- Nếu JSON hợp lệ ở cả ba pass, DeepSeek có thể dùng như lớp biên tập/audit có cấu trúc. Nếu còn thuật ngữ rủi ro hoặc critic báo lỗi chặn, Codex vẫn phải giữ lớp guard trước khi đưa vào PDF.",
            "- Điểm heuristic trong file này không thay thế đánh giá nội dung thủ công; nó chỉ đo độ sạch đầu ra theo tiêu chí JSON, thuật ngữ cấm và tự phê bình của critic.",
            "",
            "## Artefact",
            "",
            "- `long_context_dossier.txt`",
            "- `pass_a_audit_raw.json` / `pass_a_audit_parsed.json`",
            "- `pass_b_writer_raw.json` / `pass_b_writer_parsed.json`",
            "- `pass_c_critic_raw.json` / `pass_c_critic_parsed.json`",
            "- `run_meta.json`",
        ]
    )
    _write_text(out_dir / "long_context_run_report.md", "\n".join(lines) + "\n")
    print(f"Wrote {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run DeepSeek V4 Flash long-context 3-pass writing test for Bull Flag.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--model", default=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"))
    parser.add_argument("--max-tokens-a", type=int, default=20000)
    parser.add_argument("--max-tokens-b", type=int, default=24000)
    parser.add_argument("--max-tokens-c", type=int, default=16000)
    args = parser.parse_args()
    run(args.out_dir, args.model, args.max_tokens_a, args.max_tokens_b, args.max_tokens_c)


if __name__ == "__main__":
    main()
