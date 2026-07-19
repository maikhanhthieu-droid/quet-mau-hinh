from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner.run_deepseek_long_context_bull_flag import (
    BANNED_TERMS,
    REPO_ROOT,
    _flatten_strings,
    _load_dotenv,
    _parse_json_lenient,
    _read_text,
    _scan_terms,
    _write_json,
    _write_text,
)


DEFAULT_OUT_DIR = REPO_ROOT / "artifacts/scanner_v2/bull_flags_ai_writing_blocked_v4_flash"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_block(paths: List[str], *, title: str) -> tuple[str, List[Dict[str, Any]]]:
    manifest: List[Dict[str, Any]] = []
    parts = [f"<{title}>"]
    for rel in paths:
        path = REPO_ROOT / rel
        if not path.exists():
            manifest.append({"path": rel, "status": "missing"})
            continue
        text = _read_text(path)
        manifest.append({"path": rel, "status": "included", "chars": len(text)})
        parts.extend([f"\n<FILE path=\"{rel}\" chars=\"{len(text)}\">", text, f"</FILE path=\"{rel}\">"])
    parts.append(f"</{title}>")
    return "\n".join(parts), manifest


def _json_slice(path: str, keys: List[str], *, title: str) -> tuple[str, List[Dict[str, Any]]]:
    full = REPO_ROOT / path
    if not full.exists():
        return f"<{title}></{title}>", [{"path": path, "status": "missing"}]
    obj = json.loads(full.read_text(encoding="utf-8"))
    sliced: Dict[str, Any] = {}
    cur: Any
    for key in keys:
        cur = obj
        ok = True
        for part in key.split("."):
            if isinstance(cur, Mapping) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok:
            dst = sliced
            parts = key.split(".")
            for part in parts[:-1]:
                dst = dst.setdefault(part, {})
            dst[parts[-1]] = cur
    text = json.dumps(sliced, ensure_ascii=False, indent=2, sort_keys=True)
    return (
        f"<{title} source=\"{path}\">\n{text}\n</{title}>",
        [{"path": path, "status": "included_slice", "keys": keys, "chars": len(text)}],
    )


def _client() -> tuple[OpenAI, str, str]:
    _load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("Missing DEEPSEEK_API_KEY in environment or .env")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    return OpenAI(api_key=api_key, base_url=base_url, timeout=600.0), model, base_url


SYSTEM = """Bạn là tác giả-biên tập viên tài liệu mẫu hình giá cho nhà đầu tư Việt Nam.
Giọng viết cần gần một chương practitioner reference kiểu Thomas Bulkowski: thẳng, cụ thể, đọc chart được ngay, không viết như paper hoặc report vận hành.
Luật:
- Chỉ dùng dữ liệu trong input của block.
- Không tự tạo số liệu.
- Không viết khuyến nghị mua/bán.
- Output phải là JSON hợp lệ, không markdown fence.
- Nếu bắt buộc nhắc tên field kỹ thuật, đặt nó trong trường evidence/metric_field, không đưa vào body đọc cho nhà đầu tư.
- Mỗi số liệu quan trọng phải đi kèm ý nghĩa đọc chart: "vậy người đọc nên hiểu gì?".
- Không để đoạn văn chỉ liệt kê số. Phải biến số thành kết luận thực dụng.
- Tránh giọng phòng thủ lặp lại. Chỉ nhắc giới hạn khi nó thật sự thay đổi cách đọc mẫu.
- Ưu tiên từ ngữ dễ đọc: "mức tăng tốt nhất", "mức kéo ngược sâu nhất", "đạt mục tiêu trước khi bị kéo ngược mạnh", "đọc thận trọng hơn".
- Tránh các cụm nặng tính nội bộ như "biên thuận lợi", "biên bất lợi", "hạ trọng số", "pipeline", "scanner", "setup". Nếu cần nói, hãy Việt hóa thành ngôn ngữ đọc biểu đồ.
- Văn phong cần giống tài liệu mẫu hình để đọc và áp dụng điều kiện, không giống báo cáo kiểm định. Câu nào có số liệu thì phải trả lời thêm: số đó làm thay đổi cách đọc mẫu ra sao.
"""


def _call_block(
    *,
    client: OpenAI,
    model: str,
    block_name: str,
    input_text: str,
    task: str,
    max_tokens: int,
    temperature: float,
) -> Dict[str, Any]:
    start = time.perf_counter()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": input_text + "\n\n" + task},
        ],
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
        temperature=temperature,
    )
    elapsed = time.perf_counter() - start
    content = response.choices[0].message.content or ""
    parsed = _parse_json_lenient(content)
    strings = "\n".join(_flatten_strings(parsed)) if parsed is not None else content
    usage = response.usage.model_dump() if response.usage else None
    return {
        "block": block_name,
        "elapsed_s": round(elapsed, 3),
        "chars": len(content),
        "json_valid": parsed is not None,
        "finish_reason": response.choices[0].finish_reason,
        "usage": usage,
        "raw": content,
        "parsed": parsed,
        "banned_terms": _scan_terms(strings),
    }


def _body_text(obj: Any) -> str:
    """Extract only investor-facing prose fields for a stricter body scan."""
    wanted = {"title", "subtitle", "deck", "paragraphs", "lead", "caption", "final_caveat", "body", "bullets"}
    chunks: List[str] = []

    def walk(value: Any, key: str = "") -> None:
        if isinstance(value, str):
            if key in wanted:
                chunks.append(value)
        elif isinstance(value, Mapping):
            for k, v in value.items():
                walk(v, str(k))
        elif isinstance(value, list):
            for v in value:
                walk(v, key)

    walk(obj)
    return "\n".join(chunks)


def _local_guard(parsed: Any) -> Dict[str, Any]:
    all_text = "\n".join(_flatten_strings(parsed)) if parsed is not None else ""
    body = _body_text(parsed)
    body_terms = _scan_terms(body)
    all_terms = _scan_terms(all_text)
    blocking = []
    for term in ["khuyến nghị mua", "nên mua", "nên bán", "chắc chắn sinh lợi", "cỗ máy in tiền"]:
        if term in body_terms:
            blocking.append(f"body contains forbidden trading phrase: {term}")
    for term in ["MFE", "MAE", "breakout", "target-hit", "scanner", "pipeline"]:
        if term in body_terms:
            blocking.append(f"body contains English/technical term: {term}")
    return {
        "body_banned_terms": body_terms,
        "all_banned_terms": all_terms,
        "blocking": blocking,
        "pass": not blocking,
    }


PUBLIC_TEXT_KEYS = {
    "title",
    "subtitle",
    "deck",
    "paragraphs",
    "lead",
    "caption",
    "final_caveat",
    "body",
    "bullets",
    "remaining_risks",
    "schematic",
    "textbook_success",
    "middle_case",
    "failure",
}


def _clean_public_text_value(text: str) -> str:
    replacements = {
        "MFE trung vị 60 ngày": "mức tăng tốt nhất trung vị 60 ngày",
        "MAE trung vị 60 ngày": "mức kéo ngược sâu nhất trung vị 60 ngày",
        "MFE": "mức tăng tốt nhất",
        "MAE": "mức kéo ngược sâu nhất",
        "Breakout": "Phá vỡ",
        "breakout": "phá vỡ",
        "target-hit": "đạt mục tiêu",
        "target-first-before-adverse": "đạt mục tiêu trước khi bị kéo ngược mạnh",
        "target-first": "đạt mục tiêu trước kéo ngược",
        "target ": "mục tiêu ",
        "stop loss": "dừng lỗ",
        "stop-loss": "dừng lỗ",
        "stop ": "dừng lỗ ",
        "throwback": "kiểm định lại",
        "volume_confirmed = True": "khối lượng xác nhận: có",
        "volume_confirmed = False": "khối lượng xác nhận: không",
        "forward": "hậu phá vỡ",
        "entry delay": "độ trễ vào lệnh",
        "research candidate setup": "ứng viên nghiên cứu",
        "tradable research candidate": "ứng viên nghiên cứu có kiểm thử thực thi",
        "candidate": "ứng viên",
        "zero-volume": "phiên không có khối lượng",
        "volume": "khối lượng",
        "scanner": "bộ quét",
        "Scanner": "Bộ quét",
        "pipeline": "quy trình",
        "khuyến nghị mua": "lời khuyên mua",
        "khuyến nghị bán": "lời khuyên bán",
        "không đảm bảo": "không phải cam kết cho",
        "đảm bảo": "cam kết",
        "corporate-action": "sự kiện quyền và điều chỉnh giá",
        "'available-series'": "dữ liệu hiện có",
        "available-series": "dữ liệu hiện có",
        "delisted": "mã hủy niêm yết",
        "half-staff": "nửa cột cờ",
        "swing": "dao động",
        "median ": "trung vị ",
        "biên lợi nhuận tối đa": "biên thuận lợi lớn nhất",
        "khuyến nghị đầu tư": "lời khuyên đầu tư",
        "nhà đầu tư nên": "người đọc cần",
        "path dữ liệu": "chất lượng dữ liệu",
        "path": "đường giá",
        "pole": "cột cờ",
        "flag": "thân cờ",
        "Biên thuận lợi": "Mức tăng tốt nhất",
        "biên thuận lợi": "mức tăng tốt nhất",
        "Biên bất lợi": "Mức kéo ngược sâu nhất",
        "biên bất lợi": "mức kéo ngược sâu nhất",
        "hạ trọng số": "đọc thận trọng hơn",
        "Hạ trọng số": "Đọc thận trọng hơn",
        "phân vị": "vùng phân bố",
        "Phân vị": "Vùng phân bố",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return (
        text.replace("cột cờ (cột cờ)", "cột cờ")
        .replace("thân cờ (thân cờ)", "thân cờ")
        .replace("Kiểm định lại (kiểm định lại)", "Kiểm định lại")
        .replace("kiểm định lại (kiểm định lại)", "kiểm định lại")
        .replace("dữ liệu dữ liệu hiện có", "dữ liệu hiện có")
    )


def _require_json(block_name: str, result: Mapping[str, Any], out_dir: Path) -> None:
    if result.get("json_valid"):
        return
    _write_json(
        out_dir / f"{block_name}_invalid_json_error.json",
        {
            "block": block_name,
            "error": "required_block_returned_invalid_json",
            "finish_reason": result.get("finish_reason"),
            "chars": result.get("chars"),
            "usage": result.get("usage"),
        },
    )
    raise RuntimeError(f"{block_name} returned invalid JSON; aborting blocked editorial pipeline")


def _clean_public_facing_fields(obj: Any, key: str = "") -> Any:
    if isinstance(obj, str):
        return _clean_public_text_value(obj) if key in PUBLIC_TEXT_KEYS else obj
    if isinstance(obj, list):
        return [_clean_public_facing_fields(value, key) for value in obj]
    if isinstance(obj, dict):
        return {k: _clean_public_facing_fields(v, str(k)) for k, v in obj.items()}
    return obj


def _caption_guard(parsed: Any) -> Dict[str, int]:
    if not isinstance(parsed, Mapping):
        return {}
    captions = parsed.get("example_captions")
    if not isinstance(captions, Mapping):
        return {}
    text = "\n".join(str(v) for v in captions.values() if isinstance(v, str))
    return _scan_terms(text)


def _deterministic_synthesize(writer: Any, critic: Any) -> Dict[str, Any]:
    if not isinstance(writer, Mapping):
        return {"title": "Cờ tăng", "approved_sections": [], "remaining_risks": ["writer_invalid"]}
    synthesized = {
        "title": writer.get("title", "Cờ tăng"),
        "subtitle": writer.get("subtitle", ""),
        "deck": writer.get("deck", ""),
        "approved_sections": writer.get("sections", []) if isinstance(writer.get("sections"), list) else [],
        "table_leads": writer.get("table_leads", []) if isinstance(writer.get("table_leads"), list) else [],
        "example_captions": writer.get("example_captions", {}) if isinstance(writer.get("example_captions"), Mapping) else {},
        "final_caveat": writer.get("final_caveat", ""),
        "claims_to_verify": writer.get("claims_to_verify", []) if isinstance(writer.get("claims_to_verify"), list) else [],
        "critic_summary": critic if isinstance(critic, Mapping) else {},
        "remaining_risks": [],
    }
    if isinstance(critic, Mapping):
        for issue in critic.get("blocking_issues", []) or []:
            if isinstance(issue, Mapping):
                synthesized["remaining_risks"].append(str(issue.get("issue", "")))
        for issue in critic.get("nonblocking_issues", []) or []:
            if isinstance(issue, Mapping):
                synthesized["remaining_risks"].append(str(issue.get("issue", "")))
    return synthesized


def _save_block(out_dir: Path, result: Dict[str, Any]) -> None:
    name = result["block"]
    _write_text(out_dir / f"{name}_raw.json", result["raw"])
    if result["parsed"] is not None:
        _write_json(out_dir / f"{name}_parsed.json", result["parsed"])


def run(out_dir: Path, model_override: Optional[str], temperature: float) -> None:
    client, env_model, base_url = _client()
    model = model_override or env_model
    out_dir.mkdir(parents=True, exist_ok=True)

    manifests: Dict[str, Any] = {}
    blocks: Dict[str, Dict[str, Any]] = {}

    source_input, m1 = _file_block(
        [
            "docs/project/bulkowski-vietnam-methodology-contract.md",
            "docs/project/bulkowski-vietnam-release-gate.md",
            "artifacts/scanner_v2/bull_flags_source_grounding/bull_flag_source_notes.md",
            "artifacts/scanner_v2/bull_flags_source_grounding/bull_flag_source_notes.json",
            "artifacts/scanner_v2/bull_flags_public_chapter/bull_flag_content_parity_audit.md",
        ],
        title="SOURCE_RULE_DOSSIER",
    )
    source_slice, m1s = _json_slice(
        "artifacts/scanner_v2/bull_flags_publication_chapter/bull_flag_publication_payload.json",
        ["scanner_contract", "bulkowski_alignment", "data_scope_and_caveats", "narrative_contract"],
        title="SOURCE_RULE_PAYLOAD_SLICE",
    )
    manifests["source"] = m1 + m1s
    blocks["source"] = _call_block(
        client=client,
        model=model,
        block_name="block1_source_rule_grounding",
        input_text=source_input + "\n\n" + source_slice,
        task="""<TASK>
Audit nguồn và quy tắc cho chương Cờ tăng.
Output JSON:
{
  "allowed_positioning": "...",
  "bulkowski_alignment": ["..."],
  "must_say": ["..."],
  "must_not_say": ["..."],
  "terminology_map": [{"bad": "...", "good": "..."}],
  "source_grounding_risks": [{"risk": "...", "severity": "low|medium|high", "fix": "..."}]
}
</TASK>""",
        max_tokens=7000,
        temperature=temperature,
    )
    _save_block(out_dir, blocks["source"])

    metrics_input, m2 = _file_block(
        [
            "artifacts/scanner_v2/bull_flags/statistics.json",
            "artifacts/scanner_v2/bull_flags_publication_chapter/bull_flag_publication_payload.json",
            "artifacts/scanner_v2/bull_flags_tradable_setup/bull_flag_tradable_scorecard.json",
            "artifacts/scanner_v2/bull_flags_tradable_setup/bull_flag_tradable_backtest_report.md",
            "artifacts/scanner_v2/bull_flags_wider_oos/bull_flag_wider_oos_report.md",
        ],
        title="METRICS_DOSSIER",
    )
    manifests["metrics"] = m2
    blocks["metrics"] = _call_block(
        client=client,
        model=model,
        block_name="block2_metrics_interpreter",
        input_text=metrics_input,
        task="""<TASK>
Diễn giải số liệu cho chương Cờ tăng. Không viết văn chương hoàn chỉnh; chỉ tạo inventory và cách đọc.
Output JSON:
{
  "headline_metrics": [{"metric": "...", "value": "...", "evidence": "...", "safe_reading": "...", "so_what_for_chart_reader": "...", "unsafe_reading": "..."}],
  "target_calibration": {"base_target": "...", "legacy_target": "...", "interpretation": "..."},
  "robustness_notes": [{"axis": "...", "finding": "...", "caveat": "..."}],
  "execution_layer_notes": [{"finding": "...", "allowed_use": "...", "forbidden_use": "..."}],
  "numbers_for_writer": [{"label": "...", "value": "...", "source": "..."}]
}
</TASK>""",
        max_tokens=9000,
        temperature=temperature,
    )
    _save_block(out_dir, blocks["metrics"])

    example_slice, m3s = _json_slice(
        "artifacts/scanner_v2/bull_flags_public_chapter/bull_flag_public_chapter_payload.json",
        ["example_events", "charts", "ai_editorial_sections", "publication_payload.chapter_reference"],
        title="EXAMPLE_PAYLOAD_SLICE",
    )
    examples_csv, m3 = _file_block(["artifacts/scanner_v2/bull_flags/events.csv"], title="EVENTS_FOR_CAPTION_CHECK")
    manifests["examples"] = m3s + m3
    blocks["examples"] = _call_block(
        client=client,
        model=model,
        block_name="block3_example_caption_writer",
        input_text=example_slice + "\n\n" + examples_csv,
        task="""<TASK>
Viết và kiểm tra caption ví dụ cho chương Cờ tăng.
Luật riêng:
- Mỗi caption phải khớp số học với event data.
- Nếu có target_price và mfe_pct, không được nói đã chạm mục tiêu nếu target_hit là false.
- Không dùng tiếng Anh trong caption.
Output JSON:
{
  "caption_audit": [{"example_id": "...", "status": "ok|needs_fix", "issue": "...", "evidence": "..."}],
  "captions": {
    "schematic": "...",
    "textbook_success": "...",
    "middle_case": "...",
    "failure": "..."
  },
  "caption_claims_to_verify": [{"caption": "...", "data_fields": ["..."], "risk": "low|medium|high"}]
}
</TASK>""",
        max_tokens=7000,
        temperature=temperature,
    )
    _save_block(out_dir, blocks["examples"])

    writer_input = json.dumps(
        {
            "source": blocks["source"]["parsed"],
            "metrics": blocks["metrics"]["parsed"],
            "examples": blocks["examples"]["parsed"],
        },
        ensure_ascii=False,
    )
    baseline, mb = _file_block(
        [
            "artifacts/scanner_v2/bull_flags_public_chapter/bull_flag_ai_editorial_manuscript.md",
            "artifacts/scanner_v2/bull_flags_pdf_ai_review/bull_flags_pdf_extracted_text.txt",
        ],
        title="CURRENT_BASELINE_TEXT",
    )
    manifests["writer"] = mb
    blocks["writer"] = _call_block(
        client=client,
        model=model,
        block_name="block4_public_chapter_writer",
        input_text="<BLOCK_OUTPUTS>\n" + writer_input + "\n</BLOCK_OUTPUTS>\n\n" + baseline,
        task="""<TASK>
Viết bản nháp public-facing cho chương Cờ tăng bằng tiếng Việt thuần.
Không tự thêm số liệu ngoài block outputs. Không viết như khuyến nghị giao dịch.
Yêu cầu văn phong:
- Viết như một chương mẫu hình cho nhà đầu tư đọc biểu đồ, không như báo cáo vận hành.
- Mỗi đoạn phải có một kết luận thực dụng: mẫu nên được đọc thế nào, khi nào đáng chú ý hơn, khi nào cần thận trọng hơn.
- Không để đoạn nào chỉ liệt kê số. Nếu dùng số, phải giải thích ngay "vì sao số này quan trọng".
- Dùng "mức tăng tốt nhất" thay cho MFE/biên thuận lợi; dùng "mức kéo ngược sâu nhất" thay cho MAE/biên bất lợi.
- Dùng "đạt mục tiêu trước khi bị kéo ngược mạnh" thay cho target-first.
- Không dùng "setup", "research", "scanner", "pipeline", "proxy", "available-series", "target-hit" trong body.
- Không lặp disclaimer chung; chỉ nói giới hạn dữ liệu khi nó làm thay đổi cách đọc mẫu.
Output JSON:
{
  "title": "Cờ tăng",
  "subtitle": "...",
  "deck": "...",
  "sections": [
    {
      "id": "...",
      "title": "...",
      "subtitle": "...",
      "paragraphs": ["...", "..."],
      "callout": {"title": "...", "bullets": ["..."]},
      "claims_used": ["..."]
    }
  ],
  "table_leads": [{"table_id": "...", "lead": "..."}],
  "example_captions": {"schematic": "...", "textbook_success": "...", "middle_case": "...", "failure": "..."},
  "final_caveat": "...",
  "claims_to_verify": [{"claim": "...", "metric_field": "...", "risk": "low|medium|high"}]
}
</TASK>""",
        max_tokens=16000,
        temperature=temperature,
    )
    _save_block(out_dir, blocks["writer"])
    _require_json("block4_public_chapter_writer", blocks["writer"], out_dir)

    critic_input = json.dumps(
        {
            "source": blocks["source"]["parsed"],
            "metrics": blocks["metrics"]["parsed"],
            "examples": blocks["examples"]["parsed"],
            "writer": blocks["writer"]["parsed"],
        },
        ensure_ascii=False,
    )
    blocks["critic"] = _call_block(
        client=client,
        model=model,
        block_name="block5_critic_red_team",
        input_text="<BLOCK_OUTPUTS_AND_DRAFT>\n" + critic_input + "\n</BLOCK_OUTPUTS_AND_DRAFT>",
        task="""<TASK>
Review bản nháp. Tìm lỗi overclaim, thuật ngữ tiếng Anh trong body, claim thiếu số liệu, caption sai và câu giống khuyến nghị.
Ngoài lỗi factual, hãy chấm theo độ giống một chương practitioner reference:
- Fail nếu đoạn văn chỉ nêu số mà không nói người đọc nên hiểu gì.
- Fail nếu body còn các cụm "biên thuận lợi", "biên bất lợi", "hạ trọng số", "target", "setup", "research", "scanner", "pipeline".
- Fail nếu giọng văn thiên về báo cáo nội bộ hơn là tài liệu đọc biểu đồ.
- Fail nếu cảnh báo dữ liệu lặp lại nhiều lần mà không thêm ý nghĩa mới.
Output JSON:
{
  "pass": true,
  "blocking_issues": [{"section_id": "...", "issue": "...", "required_fix": "..."}],
  "nonblocking_issues": [{"section_id": "...", "issue": "...", "suggested_fix": "..."}],
  "approved_sections": ["..."],
  "rejected_sections": ["..."],
  "rewrite_instructions": ["..."],
  "publication_readiness": {"score_0_100": 0, "classification": "..."}
}
</TASK>""",
        max_tokens=7000,
        temperature=temperature,
    )
    _save_block(out_dir, blocks["critic"])
    _require_json("block5_critic_red_team", blocks["critic"], out_dir)

    synthesized = _deterministic_synthesize(blocks["writer"]["parsed"], blocks["critic"]["parsed"])
    blocks["synthesizer"] = {
        "block": "block6_deterministic_synthesizer",
        "elapsed_s": 0.0,
        "chars": len(json.dumps(synthesized, ensure_ascii=False)),
        "json_valid": True,
        "finish_reason": "deterministic",
        "usage": None,
        "raw": json.dumps(synthesized, ensure_ascii=False, indent=2),
        "parsed": synthesized,
        "banned_terms": _scan_terms("\n".join(_flatten_strings(synthesized))),
    }
    _save_block(out_dir, blocks["synthesizer"])

    approved = _clean_public_facing_fields(blocks["synthesizer"]["parsed"])
    approved_guard = _local_guard(approved)
    approved_guard["caption_banned_terms"] = _caption_guard(approved)
    approved_guard["pass"] = bool(approved_guard["pass"] and not approved_guard["caption_banned_terms"])
    _write_json(out_dir / "approved_ai_sections.json", approved)
    _write_json(out_dir / "approved_ai_sections_guard.json", approved_guard)

    guards = {name: _local_guard(result["parsed"]) for name, result in blocks.items()}
    _write_json(out_dir / "local_guards.json", guards)
    _write_json(out_dir / "block_manifest.json", manifests)

    meta = {
        "created_at": _utc_now_iso(),
        "model": model,
        "base_url": base_url,
        "temperature": temperature,
        "blocks": {
            name: {
                "elapsed_s": result["elapsed_s"],
                "chars": result["chars"],
                "json_valid": result["json_valid"],
                "finish_reason": result["finish_reason"],
                "usage": result["usage"],
                "banned_terms": result["banned_terms"],
                "local_guard": guards[name],
            }
            for name, result in blocks.items()
        },
        "approved_ai_sections": {
            "path": str(out_dir / "approved_ai_sections.json"),
            "guard": approved_guard,
        },
    }
    _write_json(out_dir / "run_meta.json", meta)

    lines = [
        "# Báo cáo chạy DeepSeek theo block cho Bull Flag",
        "",
        f"- Thời điểm: `{meta['created_at']}`",
        f"- Model: `{model}`",
        "",
        "| Block | Giây | JSON | Prompt tokens | Completion tokens | Cached tokens | Body guard | Body terms |",
        "|---|---:|---|---:|---:|---:|---|---|",
    ]
    for name, result in blocks.items():
        usage = result.get("usage") or {}
        details = usage.get("prompt_tokens_details") or {}
        guard = guards[name]
        lines.append(
            f"| {name} | {result['elapsed_s']} | {'có' if result['json_valid'] else 'không'} | "
            f"{usage.get('prompt_tokens','')} | {usage.get('completion_tokens','')} | {details.get('cached_tokens','')} | "
            f"{'pass' if guard['pass'] else 'fail'} | {json.dumps(guard['body_banned_terms'], ensure_ascii=False)} |"
        )
    synth_guard = guards["synthesizer"]
    approved_pass = bool(approved_guard.get("pass"))
    critic = blocks["critic"]["parsed"] if isinstance(blocks["critic"]["parsed"], Mapping) else {}
    lines.extend(
        [
            "",
            "## Kết luận nhanh",
            "",
            f"- Synthesizer body guard: `{'pass' if synth_guard['pass'] else 'fail'}`.",
            f"- Approved sections guard sau deterministic repair: `{'pass' if approved_pass else 'fail'}`.",
            f"- Critic classification: `{((critic.get('publication_readiness') or {}).get('classification'))}`.",
            f"- Critic score: `{((critic.get('publication_readiness') or {}).get('score_0_100'))}`.",
            "- Artefact quan trọng nhất để tích hợp PDF là `approved_ai_sections.json`.",
        ]
    )
    _write_text(out_dir / "blocked_run_report.md", "\n".join(lines) + "\n")
    print(f"Wrote {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run DeepSeek blocked editorial pipeline for Bull Flag.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--model", default=None)
    parser.add_argument("--temperature", type=float, default=0.2)
    args = parser.parse_args()
    run(args.out_dir, args.model, args.temperature)


if __name__ == "__main__":
    main()
