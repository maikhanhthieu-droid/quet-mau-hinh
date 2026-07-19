"""Run the canonical editorial workflow through DeepSeek.

DeepSeek is only a writer/critic. This adapter prepares the canonical dossier,
calls the model block by block, then deterministically emits an approved content
artifact for `canonical_chapter_content_generator_v1`.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from json import JSONDecodeError
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from scanner.canonical_chapter_content import prepare_canonical_chapter_content
from scanner.canonical_editorial_layer import REQUIRED_EDITORIAL_SECTIONS, validate_canonical_editorial_sections
from scanner.canonical_editorial_workflow import (
    CANONICAL_EDITORIAL_WORKFLOW_ID,
    EDITORIAL_BLOCK_SEQUENCE,
    build_canonical_editorial_dossier,
    build_canonical_editorial_prompt,
)


CANONICAL_DEEPSEEK_EDITORIAL_ADAPTER_ID = "canonical_deepseek_editorial_adapter_v1"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-pro"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"

try:
    from json_repair import repair_json
except ImportError:  # pragma: no cover - optional robustness dependency
    repair_json = None  # type: ignore[assignment]

MODEL_BLOCKS = tuple(block for block in EDITORIAL_BLOCK_SEQUENCE if block != "deterministic_synthesizer")

PUBLIC_TEXT_REPLACEMENTS = (
    ("tổng mẫu quét lịch sử", "tổng mẫu lịch sử"),
    ("Tổng mẫu quét lịch sử", "Tổng mẫu lịch sử"),
    ("mẫu quét lịch sử", "mẫu lịch sử"),
    ("Mẫu quét lịch sử", "Mẫu lịch sử"),
    ("tổng mẫu quét", "tổng mẫu lịch sử"),
    ("Tổng mẫu quét", "Tổng mẫu lịch sử"),
    ("mẫu quét", "mẫu lịch sử"),
    ("Mẫu quét", "Mẫu lịch sử"),
    ("approved_human_sections", "nội dung biên tập đã duyệt"),
    ("source_full_pipe", "mốc đầy đủ"),
    ("Tham số hiện tại", "Dấu hiệu cần thấy"),
    ("Spike", "Cú xuyên giá"),
    ("spike", "cú xuyên giá"),
    ("Overlap", "Vùng chồng lấn"),
    ("overlap", "vùng chồng lấn"),
    ("MFE", "mức tăng tốt nhất"),
    ("MAE", "mức kéo ngược sâu nhất"),
    ("target-hit", "tỷ lệ đạt mục tiêu"),
    ("target-first", "đạt mục tiêu trước khi bị kéo ngược mạnh"),
    ("throwback", "quay lại kiểm định vùng phá vỡ"),
    ("Breakout", "Phá vỡ"),
    ("breakout", "phá vỡ"),
    ("scanner", "bộ quét"),
    ("pipeline", "quy trình"),
    ("proxy", "chỉ báo thay thế"),
    ("available-series", "dữ liệu hiện có"),
    ("setup", "cấu hình đọc mẫu"),
    ("profit factor", "hệ số lợi nhuận"),
    ("backtest", "kiểm tra thực thi minh họa"),
    ("validation", "giai đoạn kiểm tra kế tiếp"),
    ("holdout", "giai đoạn kiểm tra sau cùng"),
    ("Flag Family", "nhóm Cờ"),
    ("Corporate actions", "sự kiện quyền"),
    ("corporate actions", "sự kiện quyền"),
    ("delisted/halted", "hủy niêm yết hoặc tạm ngừng"),
    ("status tape", "băng trạng thái"),
    ("historical VN30/VN100 membership", "dữ liệu thành phần VN30/VN100 lịch sử"),
    ("point-in-time universe", "universe theo từng thời điểm"),
    ("regime", "bối cảnh thị trường"),
    ("bucket", "nhóm"),
    ("clean", "sạch"),
    ("caution", "cần theo dõi"),
    ("impaired", "suy giảm"),
    ("usable", "dùng được"),
    ("zero_and_stale", "giá đứng im và thiếu giao dịch"),
    ("stale_close", "nhiều phiên giá đứng"),
    ("bên mua", "lực cầu"),
    ("bên bán", "lực cung"),
    ("tín hiệu mua bán", "tài liệu tham khảo"),
    ("khuyến nghị mua bán", "khuyến nghị giao dịch"),
    ("ra lệnh mua bán", "ra lệnh giao dịch"),
    ("trước khi hành động dựa trên", "khi đọc"),
    ("khuyến nghị mua/bán", "khuyến nghị giao dịch"),
    ("mua/bán", "giao dịch"),
    ("ứng viên mua/cầm nắm", "ứng viên tham khảo theo hướng tăng"),
    ("mua/cầm nắm", "tham khảo theo hướng tăng"),
    ("tín hiệu mua tự động", "tài liệu tham khảo tự động"),
    ("tín hiệu mua bán", "tài liệu tham khảo"),
    ("tín hiệu mua", "tài liệu tham khảo theo hướng tăng"),
    ("lệnh mua", "quyết định giao dịch"),
    ("quyết định giao dịch bán cụ thể", "quyết định giao dịch cụ thể"),
    ("quyết định giao dịch mua cụ thể", "quyết định giao dịch cụ thể"),
    ("cắt lỗ", "ngưỡng rủi ro"),
    ("dừng lỗ", "ngưỡng rủi ro"),
    ("(lead-in)", ""),
    ("lead-in", "nhịp dẫn"),
    ("Lead-in", "Nhịp dẫn"),
    ("trendline", "đường xu hướng"),
    ("Trendline", "Đường xu hướng"),
    ("short setup", "hồ sơ bán khống"),
    ("short cấu trúc mẫu", "hồ sơ bán khống"),
    ("short cấu hình", "hồ sơ bán khống"),
    ("long-watchlist", "hồ sơ theo dõi hướng tăng"),
    ("long-theo dõi", "hồ sơ theo dõi hướng tăng"),
    ("biên thuận lợi", "mức tăng tốt nhất"),
    ("biên bất lợi", "mức kéo ngược sâu nhất"),
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _read_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, Mapping) else {}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() and path.is_file() else ""


def _parse_json_lenient(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = [line for line in stripped.splitlines() if not line.strip().startswith("```")]
        stripped = "\n".join(lines).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            candidate = stripped[start : end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                if repair_json is not None:
                    repaired = repair_json(candidate)
                    return json.loads(repaired) if isinstance(repaired, str) else repaired
                raise
        if repair_json is not None:
            repaired = repair_json(stripped)
            return json.loads(repaired) if isinstance(repaired, str) else repaired
        raise


def _call_deepseek_json(
    *,
    api_key: str,
    base_url: str,
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
    timeout_s: int,
) -> dict[str, Any]:
    endpoint = base_url.rstrip("/") + "/chat/completions"
    def post_json(body: dict[str, Any]) -> tuple[dict[str, Any], float]:
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        started_inner = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"DeepSeek HTTP {exc.code}: {detail[:1000]}") from exc
        return json.loads(raw), round(time.perf_counter() - started_inner, 3)

    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Bạn là biên tập viên chương mẫu hình giá cho nhà đầu tư Việt Nam. "
                    "Chỉ dùng dữ liệu trong prompt, không tự thêm số liệu. "
                    "Output phải là JSON hợp lệ."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    payload: dict[str, Any] | None = None
    elapsed = 0.0
    for attempt in range(1, 4):
        try:
            candidate, elapsed = post_json(body)
        except RuntimeError as exc:
            retryable = any(marker in str(exc) for marker in ("HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504"))
            if attempt == 3 or not retryable:
                raise
            time.sleep(2.0 * attempt)
            continue
        if isinstance(candidate, dict) and candidate.get("choices"):
            payload = candidate
            break
        if attempt == 3:
            raise RuntimeError(f"DeepSeek returned invalid response schema after {attempt} attempts: {str(candidate)[:500]}")
        time.sleep(1.5 * attempt)
    assert payload is not None
    message = payload["choices"][0]["message"]["content"] or ""
    try:
        parsed = _parse_json_lenient(message)
    except JSONDecodeError:
        repair_body = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Bạn là bộ sửa JSON. Chỉ trả về JSON hợp lệ. "
                        "Không thêm giải thích, không markdown fence, không đổi nội dung nếu không cần."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "JSON sau bị lỗi cú pháp. Hãy sửa thành JSON hợp lệ, giữ nguyên các trường và nội dung tối đa có thể:\n\n"
                        + message
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
            "max_tokens": max_tokens,
        }
        repaired_payload, repair_elapsed = post_json(repair_body)
        repaired_message = repaired_payload["choices"][0]["message"]["content"] or ""
        parsed = _parse_json_lenient(repaired_message)
        return {
            "elapsed_s": round(elapsed + repair_elapsed, 3),
            "raw": repaired_message,
            "raw_before_repair": message,
            "parsed": parsed,
            "finish_reason": repaired_payload["choices"][0].get("finish_reason"),
            "usage": {
                "original": payload.get("usage"),
                "repair": repaired_payload.get("usage"),
            },
            "json_repaired": True,
        }
    return {
        "elapsed_s": elapsed,
        "raw": message,
        "parsed": parsed,
        "finish_reason": payload["choices"][0].get("finish_reason"),
        "usage": payload.get("usage"),
    }


def _context_artifacts(paths: list[Path]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            artifacts.append({"path": str(path), "status": "missing"})
            continue
        text = _read_text(path)
        artifacts.append({"path": str(path), "status": "included", "chars": len(text), "text": text})
    return artifacts


def build_deepseek_dossier(
    *,
    payload: Mapping[str, Any],
    source_notes: Mapping[str, Any],
    chapter_meta: Mapping[str, Any] | None = None,
    extra_context_paths: list[Path] | None = None,
    style_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    dossier = build_canonical_editorial_dossier(
        payload=payload,
        source_notes=source_notes,
        chapter_meta=chapter_meta,
    )
    dossier["deepseek_adapter_id"] = CANONICAL_DEEPSEEK_EDITORIAL_ADAPTER_ID
    dossier["long_context_policy"] = {
        "model_target": DEFAULT_DEEPSEEK_MODEL,
        "use_case": "AI writes prose from locked facts; code validates and publishes",
        "not_allowed": ["invent numbers", "change scanner logic", "change target calibration", "write trade advice"],
    }
    if style_profile:
        dossier["editorial_style_profile"] = dict(style_profile)
    dossier["extra_context_artifacts"] = _context_artifacts(extra_context_paths or [])
    return dossier


def _section_list_to_mapping(sections: Any) -> dict[str, list[str]]:
    if isinstance(sections, Mapping):
        return {str(key): [str(item) for item in value] if isinstance(value, list) else [str(value)] for key, value in sections.items()}
    if not isinstance(sections, list):
        return {}
    out: dict[str, list[str]] = {}
    for item in sections:
        if not isinstance(item, Mapping):
            continue
        section_id = str(item.get("id") or "").strip()
        paragraphs = item.get("paragraphs")
        if section_id and isinstance(paragraphs, list):
            out[section_id] = [str(paragraph).strip() for paragraph in paragraphs if str(paragraph).strip()]
        callout = item.get("callout")
        if section_id and isinstance(callout, Mapping):
            bullets = callout.get("bullets")
            if isinstance(bullets, list) and bullets:
                out[f"{section_id}_callout"] = [str(bullet).strip() for bullet in bullets if str(bullet).strip()]
    return out


def _extract_editorial_sections(writer: Mapping[str, Any]) -> dict[str, list[str]]:
    for key in ("editorial_sections", "sections"):
        mapped = _section_list_to_mapping(writer.get(key))
        if mapped:
            return mapped
    return {}


def _extract_example_captions(writer: Mapping[str, Any], examples: Mapping[str, Any] | None = None) -> dict[str, str]:
    captions: dict[str, str] = {}
    candidate = writer.get("example_captions")
    if isinstance(candidate, Mapping):
        captions.update({str(key): str(value) for key, value in candidate.items() if str(value).strip()})
    if examples:
        candidate = examples.get("captions")
        if isinstance(candidate, Mapping):
            captions.update({str(key): str(value) for key, value in candidate.items() if str(value).strip()})
    return captions


def _clean_public_text(value: Any) -> Any:
    if isinstance(value, str):
        out = value
        for old, new in PUBLIC_TEXT_REPLACEMENTS:
            out = out.replace(old, new)
        return out
    if isinstance(value, list):
        return [_clean_public_text(item) for item in value]
    if isinstance(value, dict):
        return {key: _clean_public_text(item) for key, item in value.items()}
    return value


def _cue_count(text: str) -> int:
    cues = (
        "người đọc",
        "nên hiểu",
        "cách đọc",
        "vì vậy",
        "điều này",
        "cho thấy",
        "không nên",
        "cần",
        "khi",
        "nếu",
        "thận trọng",
        "đáng chú ý",
        "nghĩa là",
        "hàm ý",
    )
    lower = text.lower()
    return sum(lower.count(cue) for cue in cues)


def _repair_reader_implication_cues(sections: dict[str, list[str]]) -> dict[str, list[str]]:
    repaired = {key: list(value) for key, value in sections.items()}
    for section_id, paragraphs in repaired.items():
        if section_id == "checklist" or not paragraphs:
            continue
        text = "\n".join(paragraphs)
        if _cue_count(text) >= 2:
            continue
        paragraphs[-1] = (
            paragraphs[-1].rstrip()
            + " Điều này cho thấy người đọc nên xem phần này như một hướng dẫn đọc xác suất có điều kiện, không phải một tín hiệu tự động."
        )
    return repaired


def _synthesize_approved_sections(blocks: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    source_rules = blocks.get("source_rule_grounding", {}).get("parsed")
    writer = blocks.get("public_chapter_writer", {}).get("parsed")
    examples = blocks.get("example_caption_writer", {}).get("parsed")
    if not isinstance(writer, Mapping):
        raise ValueError("public_chapter_writer did not return a JSON object")
    sections = _extract_editorial_sections(writer)
    if not sections:
        raise ValueError("public_chapter_writer output has no editorial sections")
    sections = _repair_reader_implication_cues(_clean_public_text(sections))
    captions = _clean_public_text(_extract_example_captions(writer, examples if isinstance(examples, Mapping) else None))
    approved = {
        "canonical_editorial_workflow_id": CANONICAL_EDITORIAL_WORKFLOW_ID,
        "deepseek_adapter_id": CANONICAL_DEEPSEEK_EDITORIAL_ADAPTER_ID,
        "editorial_sections": sections,
        "example_captions": captions,
        "claims_to_verify": _clean_public_text(writer.get("claims_to_verify", [])),
    }
    if isinstance(source_rules, Mapping):
        for key in ("source_rules_public", "recognition_mistakes", "section_hints"):
            value = source_rules.get(key)
            if value:
                approved[key] = _clean_public_text(value)
    return approved


def _missing_editorial_sections(approved: Mapping[str, Any]) -> list[str]:
    sections = approved.get("editorial_sections") if isinstance(approved.get("editorial_sections"), Mapping) else {}
    return [section for section in REQUIRED_EDITORIAL_SECTIONS if not sections.get(section)]


def _repair_missing_editorial_sections_with_ai(
    *,
    approved: dict[str, Any],
    dossier: Mapping[str, Any],
    out_dir: Path,
    api_key: str,
    base_url: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout_s: int,
) -> dict[str, Any]:
    """Ask the model to write only missing canonical sections.

    This is an editorial repair pass, not a deterministic fallback: all added
    prose is generated by the same AI flow from the same locked dossier, then
    re-enters the canonical section validator.
    """

    missing = _missing_editorial_sections(approved)
    if not missing:
        return approved
    sections = approved.get("editorial_sections") if isinstance(approved.get("editorial_sections"), Mapping) else {}
    section_roles = dossier.get("section_roles") if isinstance(dossier.get("section_roles"), Mapping) else {}
    repair_dossier = {
        "canonical_editorial_workflow_id": CANONICAL_EDITORIAL_WORKFLOW_ID,
        "repair_reason": "public_chapter_writer omitted required canonical sections",
        "missing_sections": missing,
        "required_sections": list(REQUIRED_EDITORIAL_SECTIONS),
        "section_roles_for_missing": {key: section_roles.get(key) for key in missing},
        "facts_locked": dossier.get("facts_locked"),
        "source_rule_inventory": dossier.get("source_rule_inventory"),
        "existing_editorial_sections": sections,
        "public_chapter_style_blueprint": dossier.get("public_chapter_style_blueprint"),
        "global_writing_rules": dossier.get("global_writing_rules"),
    }
    prompt = (
        "Bạn là biên tập viên sửa lỗi thiếu section cho chương mẫu hình giá.\n"
        "Chỉ dùng REPAIR_DOSSIER; không tự thêm số liệu. Không viết lại các section đã có.\n"
        "Nhiệm vụ: viết đúng các section còn thiếu trong `missing_sections`.\n"
        "Output phải là JSON hợp lệ, không markdown fence, theo schema:\n"
        "{\"editorial_sections\": {\"<missing_section_id>\": [\"đoạn hoặc checklist item\", \"...\"]}}\n"
        "Nếu section là `checklist`, trả 7-9 câu ngắn. Nếu section là `tactics`, trả 3-4 đoạn văn.\n"
        "Mọi đoạn phải chuyển số liệu thành cách đọc biểu đồ và không biến thành khuyến nghị giao dịch.\n"
        "<REPAIR_DOSSIER>\n"
        + json.dumps(repair_dossier, ensure_ascii=False, indent=2, default=str)
        + "\n</REPAIR_DOSSIER>"
    )
    (out_dir / "missing_sections_repair_prompt.txt").write_text(prompt, encoding="utf-8")
    result = _call_deepseek_json(
        api_key=api_key,
        base_url=base_url,
        model=model,
        prompt=prompt,
        temperature=min(float(temperature), 0.2),
        max_tokens=max(8000, min(int(max_tokens), 20000)),
        timeout_s=timeout_s,
    )
    (out_dir / "missing_sections_repair_raw.json").write_text(result["raw"], encoding="utf-8")
    (out_dir / "missing_sections_repair_parsed.json").write_text(
        json.dumps(result["parsed"], ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    parsed = result["parsed"]
    repaired_sections = parsed.get("editorial_sections") if isinstance(parsed, Mapping) else None
    if not isinstance(repaired_sections, Mapping):
        raise ValueError("Missing-section AI repair did not return editorial_sections")
    merged = dict(approved)
    merged_sections = {str(key): list(value) if isinstance(value, list) else [str(value)] for key, value in sections.items()}
    for section in missing:
        values = repaired_sections.get(section)
        if isinstance(values, list):
            clean_values = [str(item).strip() for item in values if str(item).strip()]
        elif values is not None:
            clean_values = [str(values).strip()]
        else:
            clean_values = []
        if clean_values:
            merged_sections[section] = clean_values
    merged["editorial_sections"] = _repair_reader_implication_cues(_clean_public_text(merged_sections))
    still_missing = _missing_editorial_sections(merged)
    if still_missing:
        raise ValueError("Missing-section AI repair still missing: " + ", ".join(still_missing))
    merged["missing_sections_repair"] = {
        "status": "PASS",
        "missing_sections": missing,
        "repair_model": model,
        "repair_prompt_path": str(out_dir / "missing_sections_repair_prompt.txt"),
    }
    return merged


def _geometry_terms_for_payload(prepared_payload: Mapping[str, Any]) -> list[str]:
    pattern_id = str(prepared_payload.get("pattern_id") or prepared_payload.get("publication_id") or "").lower()
    pattern_name = str(prepared_payload.get("pattern_name") or "").lower()
    source_rules = prepared_payload.get("source_rules_public")
    rule_text = ""
    if isinstance(source_rules, list):
        rule_text = " ".join(
            " ".join(str(value) for value in row.values())
            if isinstance(row, Mapping)
            else " ".join(str(value) for value in row)
            if isinstance(row, (list, tuple))
            else str(row)
            for row in source_rules
        ).lower()
    identity_text = " ".join([pattern_id, pattern_name, rule_text])
    family_terms: list[str]
    if "head_and_shoulders" in pattern_id or "head_shoulders" in pattern_id or "head and shoulders" in pattern_name or "vai đầu vai" in pattern_name:
        family_terms = ["vai", "đầu", "đường cổ", "vai trái", "vai phải", "xác nhận"]
    elif "double_bottoms" in pattern_id:
        family_terms = ["hai đáy", "đáy thứ nhất", "đáy thứ hai", "adam", "eve", "đỉnh", "xác nhận", "phá vỡ"]
    elif "double_tops" in pattern_id:
        family_terms = ["hai đỉnh", "đỉnh thứ nhất", "đỉnh thứ hai", "adam", "eve", "đáy", "xác nhận", "phá vỡ"]
    elif "double" in pattern_id:
        family_terms = ["hai đáy", "hai đỉnh", "adam", "eve", "xác nhận", "phá vỡ"]
    elif "triple_bottoms" in pattern_id:
        family_terms = ["ba đáy", "vùng hỗ trợ", "đường xác nhận", "đỉnh tạm thời", "đóng cửa", "phá vỡ"]
    elif "triple_tops" in pattern_id:
        family_terms = ["ba đỉnh", "vùng kháng cự", "đường xác nhận", "đáy tạm thời", "đóng cửa", "phá vỡ"]
    elif "triple" in pattern_id:
        family_terms = ["ba đỉnh", "ba đáy", "vùng xác nhận", "kháng cự", "hỗ trợ", "đóng cửa"]
    elif "three_falling_peaks" in pattern_id or "three_rising_valleys" in pattern_id:
        family_terms = ["ba đỉnh", "ba đáy", "thấp dần", "cao dần", "đỉnh sau", "đáy sau", "đỉnh xen giữa", "đáy xen giữa", "vùng xác nhận", "đóng cửa"]
    elif "triangle" in pattern_id or "triangles" in pattern_id or "triangle" in pattern_name or "tam giác" in pattern_name:
        family_terms = ["tam giác", "đường xu hướng", "đỉnh", "đáy", "hội tụ", "kháng cự", "hỗ trợ", "phá vỡ"]
    elif "wedge" in pattern_id or "wedges" in pattern_id or "wedge" in pattern_name or "nêm" in pattern_name:
        family_terms = ["nêm", "đường xu hướng", "hội tụ", "dốc", "đỉnh", "đáy", "phá vỡ"]
    elif "flag" in pattern_id or "flags" in pattern_id or "pennant" in pattern_id or "flag" in pattern_name or "cờ" in pattern_name or "pennant" in pattern_name:
        family_terms = ["cột cờ", "thân cờ", "phá vỡ", "kênh", "song song", "ngắn", "hẹp"]
    elif "cup" in pattern_id or "cup" in pattern_name or "cốc" in pattern_name:
        family_terms = ["cốc", "tay cầm", "môi", "đáy", "chữ u", "phá vỡ", "tròn"]
    elif "rectangle" in pattern_id or "rectangle" in pattern_name or "chữ nhật" in pattern_name:
        family_terms = ["chữ nhật", "hai đường", "trần", "sàn", "biên ngang", "đóng cửa", "phá vỡ"]
    elif "measured_move_down" in pattern_id:
        family_terms = ["a", "b", "c", "nhịp giảm đầu", "pha hồi", "đóng cửa dưới", "0.5x"]
    elif "measured_move_up" in pattern_id:
        family_terms = ["a", "b", "c", "nhịp tăng đầu", "pha điều chỉnh", "đóng cửa trên", "0.5x"]
    elif "measured_move" in pattern_id or "measured" in pattern_id or "measured" in pattern_name:
        family_terms = ["nhịp đầu", "pha điều chỉnh", "nhịp thứ hai", "hồi", "lùi", "xác nhận"]
    elif "scallop" in pattern_id and "inverted" in pattern_id:
        family_terms = ["scallop", "ô", "môi trái", "môi phải", "đỉnh", "tròn", "cong", "phá vỡ"]
    elif "scallop" in pattern_id or "scallop" in pattern_name:
        family_terms = ["scallop", "chữ j", "lòng chảo", "đỉnh trái", "đỉnh phải", "môi", "cong", "phá vỡ"]
    elif "broadening" in pattern_id or "broadening" in pattern_name or "mở rộng" in pattern_name:
        family_terms = ["mở rộng", "đỉnh cao hơn", "đáy thấp hơn", "đường xu hướng", "phá vỡ"]
    elif "rounding" in pattern_id or "rounding" in pattern_name or "dạng bát" in pattern_name or "bát úp" in pattern_name:
        if "rounding_top" in pattern_id or "rounding top" in pattern_name or "bát úp" in pattern_name:
            family_terms = ["dạng bát úp", "biểu đồ tuần", "mép phải", "đỉnh", "đóng cửa", "xác nhận"]
        else:
            family_terms = ["dạng bát", "biểu đồ tuần", "mép phải", "đáy", "đóng cửa", "xác nhận"]
    elif "rising_three_methods" in pattern_id:
        family_terms = ["nến trắng dài", "ba nến", "nến thứ năm", "biên độ nến đầu", "đóng cửa", "xu hướng tăng"]
    elif "falling_three_methods" in pattern_id:
        family_terms = ["nến đen dài", "ba nến", "nến thứ năm", "biên độ nến đầu", "đóng cửa", "xu hướng giảm"]
    elif "pipe" in identity_text:
        family_terms = ["tuần", "cú xuyên", "chồng lấn", "liền", "đóng cửa", "xác nhận", "đỉnh", "đáy", "nổi bật", "khối lượng"]
    elif "horn" in identity_text:
        family_terms = ["tuần", "cú xuyên", "cách nhau", "tuần giữa", "mẫu 3 tuần", "đóng cửa", "xác nhận", "đỉnh", "đáy", "nổi bật"]
    elif "diamond" in identity_text or "kim cương" in identity_text:
        family_terms = ["diamond", "kim cương", "mở rộng", "thu hẹp", "đỉnh cao hơn", "đáy thấp hơn", "đỉnh thấp hơn", "đáy cao hơn", "đóng cửa", "xác nhận"]
    elif "bump_and_run_reversal_tops" in pattern_id or "bump-and-run reversal top" in identity_text:
        family_terms = ["nhịp dẫn", "bump", "run", "đường xu hướng", "đóng cửa dưới", "đỉnh bump", "kéo ngược"]
    elif "bump_and_run_reversal_bottoms" in pattern_id or "bump-and-run reversal bottom" in identity_text:
        family_terms = ["nhịp dẫn", "bump", "run", "đường xu hướng", "đóng cửa trên", "đáy bump", "kéo ngược"]
    elif "bump-and-run" in identity_text or "bump_and_run" in identity_text:
        family_terms = ["nhịp dẫn", "cú bump", "pha run", "đường xu hướng dẫn", "vượt lại", "rơi xuống dưới", "xác nhận"]
    elif "triangle" in identity_text or "tam giác" in identity_text:
        family_terms = ["tam giác", "đường xu hướng", "đỉnh", "đáy", "hội tụ", "kháng cự", "hỗ trợ", "phá vỡ"]
    elif "ttop." in identity_text or "tfp." in identity_text or "triple_tops" in identity_text or "ba đỉnh ngang" in identity_text:
        family_terms = ["ba đỉnh", "vùng kháng cự", "vùng xác nhận", "đáy trung gian", "đóng cửa"]
    elif "ttb." in identity_text or "triple_bottoms" in identity_text or "ba đáy ngang" in identity_text:
        family_terms = ["ba đáy", "cùng một vùng giá", "hỗ trợ", "đường xác nhận", "đỉnh tạm thời", "đóng cửa"]
    elif "near_level_extremes" in identity_text:
        family_terms = ["ba đỉnh", "ba đáy", "vùng xác nhận", "kháng cự", "hỗ trợ", "đóng cửa"]
    elif "three_falling_peaks" in identity_text or "three_rising_valleys" in identity_text or "ba đỉnh" in identity_text or "ba đáy" in identity_text:
        family_terms = ["ba đỉnh", "ba đáy", "thấp dần", "cao dần", "đỉnh sau", "đáy sau", "đỉnh xen giữa", "đáy xen giữa", "vùng xác nhận", "đóng cửa"]
    elif "rounding" in pattern_id or "rounding" in pattern_name or "dạng bát" in pattern_name or "bát úp" in pattern_name:
        if "rounding_top" in pattern_id or "rounding top" in pattern_name or "bát úp" in pattern_name:
            family_terms = ["dạng bát úp", "biểu đồ tuần", "mép phải", "đỉnh", "đóng cửa", "xác nhận"]
        else:
            family_terms = ["dạng bát", "biểu đồ tuần", "mép phải", "đáy", "đóng cửa", "xác nhận"]
    elif "hai đáy" in identity_text:
        family_terms = ["hai đáy", "đáy thứ nhất", "đáy thứ hai", "adam", "eve", "đỉnh", "xác nhận", "phá vỡ"]
    elif "double" in identity_text or "hai đỉnh" in identity_text:
        family_terms = ["hai đỉnh", "đỉnh thứ nhất", "đỉnh thứ hai", "adam", "eve", "đáy", "xác nhận", "phá vỡ"]
    elif "dead-cat" in identity_text or "dead_cat_bounce" in identity_text or "dead cat" in identity_text:
        if "inverted" in identity_text:
            family_terms = ["cú tăng", "sự kiện", "ngày thứ hai", "trả lại", "thành quả", "close-to-close", "gap", "khối lượng"]
        else:
            family_terms = ["cú rơi", "sự kiện", "nhịp hồi", "giảm sau hồi", "đáy sự kiện", "đỉnh hồi", "gap", "khối lượng"]
    elif "island" in identity_text or "vùng đảo" in identity_text:
        family_terms = ["vùng đảo", "khoảng trống", "gap", "cô lập", "đảo chiều", "xu hướng trước", "xác nhận", "gap lên", "gap xuống"]
    elif "gap" in identity_text or "khoảng trống" in identity_text:
        family_terms = ["khoảng trống", "gap", "đóng gap", "xu hướng", "tiếp diễn", "kiệt sức", "phá nền", "đảo chiều"]
    elif "rounding" in identity_text or "dạng bát" in identity_text or "bát úp" in identity_text:
        family_terms = ["dạng bát", "biểu đồ tuần", "mép phải", "đáy", "đỉnh", "đóng cửa", "xác nhận"]
    elif (
        "head_shoulders" in pattern_id
        or "head and shoulders" in pattern_name
        or "vai đầu vai" in pattern_name
        or "vai đầu vai" in identity_text
        or "đường cổ" in identity_text
    ):
        family_terms = ["vai", "đầu", "đường cổ", "vai trái", "vai phải", "xác nhận"]
    elif "cup" in identity_text or "cốc" in identity_text:
        family_terms = ["cốc", "tay cầm", "môi", "đáy", "chữ u", "phá vỡ", "tròn"]
    elif "rectangle" in identity_text or "chữ nhật" in identity_text:
        family_terms = ["hình chữ nhật", "kháng cự", "hỗ trợ", "biên trên", "biên dưới", "phá vỡ"]
    elif "measured" in identity_text or "measured move" in identity_text:
        family_terms = ["nhịp đầu", "pha điều chỉnh", "nhịp thứ hai", "hồi", "lùi", "xác nhận"]
    elif "scallop" in identity_text and "inverted" in identity_text:
        family_terms = ["scallop", "ô", "môi trái", "môi phải", "đỉnh", "tròn", "cong", "phá vỡ"]
    elif "scallop" in identity_text:
        family_terms = ["scallop", "chữ j", "lòng chảo", "đỉnh trái", "đỉnh phải", "môi", "cong", "phá vỡ"]
    elif "broadening" in identity_text or "mở rộng" in identity_text:
        family_terms = ["mở rộng", "đỉnh cao hơn", "đáy thấp hơn", "đường xu hướng", "phá vỡ"]
    else:
        family_terms = ["hình thái", "phá vỡ", "xác nhận", "đỉnh", "đáy", "đường giá"]
    return family_terms


def _spirit_score(prepared_payload: Mapping[str, Any], editorial_report: Mapping[str, Any]) -> dict[str, Any]:
    sections = prepared_payload.get("editorial_sections") if isinstance(prepared_payload.get("editorial_sections"), Mapping) else {}
    joined = "\n".join("\n".join(str(p) for p in paragraphs) for paragraphs in sections.values() if isinstance(paragraphs, list)).lower()
    total_chars = sum(len("\n".join(str(p) for p in paragraphs)) for paragraphs in sections.values() if isinstance(paragraphs, list))
    geometry_terms = _geometry_terms_for_payload(prepared_payload)
    plain_terms = ["người đọc", "nên hiểu", "cách đọc", "khi", "nếu", "thận trọng", "điều này", "cho thấy"]
    stat_terms = ["tỷ lệ", "trung vị", "mục tiêu", "thất bại", "mức tăng", "kéo ngược"]
    forbidden = ["mfe", "mae", "scanner", "pipeline", "target-hit", "target-first", "payload", "factory"]
    axis = {
        "stats_to_prose": min(100, 50 + 6 * sum(joined.count(term) for term in plain_terms) + 3 * sum(joined.count(term) for term in stat_terms)),
        "geometry_description": min(100, 20 + 12 * sum(1 for term in geometry_terms if term in joined)),
        "plain_language": max(0, 100 - 15 * sum(1 for term in forbidden if term in joined)),
        "interpretive_depth": min(100, int(total_chars / 65)),
    }
    if editorial_report.get("status") != "PASS":
        axis = {key: min(value, 72) for key, value in axis.items()}
    score = round(sum(axis.values()) / len(axis), 2)
    return {
        "score_0_100": score,
        "target_band": "80-90 Bulkowski-spirit" if 80 <= score < 90 else ("90+ strong" if score >= 90 else "below target"),
        "axes": axis,
        "geometry_terms_checked": geometry_terms,
        "total_chars": total_chars,
        "gate_status": editorial_report.get("status"),
    }


def _editorial_guard_status(editorial_report: Mapping[str, Any], spirit: Mapping[str, Any]) -> str:
    axes = spirit.get("axes") if isinstance(spirit.get("axes"), Mapping) else {}
    min_axis = min((float(value) for value in axes.values()), default=0.0)
    score = float(spirit.get("score_0_100") or 0.0)
    if editorial_report.get("status") != "PASS":
        return "FAIL"
    if score < 90:
        return "FAIL"
    if min_axis < 75:
        return "FAIL"
    return "PASS"


def run_canonical_deepseek_editorial(
    *,
    payload_path: Path,
    source_notes_path: Path,
    out_dir: Path,
    chapter_meta: Mapping[str, Any] | None = None,
    extra_context_paths: list[Path] | None = None,
    model: str = DEFAULT_DEEPSEEK_MODEL,
    base_url: str = DEFAULT_DEEPSEEK_BASE_URL,
    temperature: float = 0.0,
    max_tokens: int = 12000,
    timeout_s: int = 900,
    style_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("Missing DEEPSEEK_API_KEY")

    out_dir.mkdir(parents=True, exist_ok=True)
    payload = _read_json(payload_path)
    source_notes = _read_json(source_notes_path)
    dossier = build_deepseek_dossier(
        payload=payload,
        source_notes=source_notes,
        chapter_meta=chapter_meta,
        extra_context_paths=extra_context_paths,
        style_profile=style_profile,
    )
    (out_dir / "canonical_editorial_dossier.json").write_text(
        json.dumps(dossier, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    blocks: dict[str, dict[str, Any]] = {}
    running_dossier = dict(dossier)
    for block_name in MODEL_BLOCKS:
        prompt = build_canonical_editorial_prompt(running_dossier, block_name)
        (out_dir / f"{block_name}_prompt.txt").write_text(prompt, encoding="utf-8")
        result = _call_deepseek_json(
            api_key=api_key,
            base_url=base_url,
            model=model,
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
        )
        blocks[block_name] = result
        (out_dir / f"{block_name}_raw.json").write_text(result["raw"], encoding="utf-8")
        (out_dir / f"{block_name}_parsed.json").write_text(
            json.dumps(result["parsed"], ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        running_dossier["previous_block_outputs"] = {key: value["parsed"] for key, value in blocks.items()}

    approved = _synthesize_approved_sections(blocks)
    approved = _repair_missing_editorial_sections_with_ai(
        approved=approved,
        dossier=dossier,
        out_dir=out_dir,
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_s=timeout_s,
    )
    approved_path = out_dir / "approved_ai_sections.json"
    approved_path.write_text(json.dumps(approved, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")

    prepared_payload = prepare_canonical_chapter_content(payload, approved_sections_path=approved_path)
    editorial_report = validate_canonical_editorial_sections(prepared_payload)
    spirit = _spirit_score(prepared_payload, editorial_report)
    guard = {
        "status": _editorial_guard_status(editorial_report, spirit),
        "editorial_report": editorial_report,
        "bulkowski_spirit_score": spirit,
    }
    (out_dir / "approved_ai_sections_guard.json").write_text(
        json.dumps(guard, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    run_meta = {
        "adapter_id": CANONICAL_DEEPSEEK_EDITORIAL_ADAPTER_ID,
        "created_at": _utc_now_iso(),
        "model": model,
        "base_url": base_url,
        "temperature": temperature,
        "style_profile": dict(style_profile) if style_profile else None,
        "payload_path": str(payload_path),
        "source_notes_path": str(source_notes_path),
        "approved_ai_sections_path": str(approved_path),
        "guard_path": str(out_dir / "approved_ai_sections_guard.json"),
        "block_summary": {
            key: {
                "elapsed_s": value["elapsed_s"],
                "finish_reason": value["finish_reason"],
                "usage": value["usage"],
            }
            for key, value in blocks.items()
        },
        "guard": guard,
    }
    (out_dir / "run_meta.json").write_text(json.dumps(run_meta, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return run_meta


__all__ = [
    "CANONICAL_DEEPSEEK_EDITORIAL_ADAPTER_ID",
    "DEFAULT_DEEPSEEK_MODEL",
    "run_canonical_deepseek_editorial",
]
