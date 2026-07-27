"""Optional Gemini wording layer with a deterministic fallback."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

import requests


class GeminiSummaryError(RuntimeError):
    """Raised when Gemini cannot produce a safe short intro."""


def build_ai_intro(
    candidates: Sequence[Mapping[str, Any]],
    *,
    api_key: str,
    model: str,
    timeout_sec: float = 30.0,
) -> str:
    if not api_key:
        raise GeminiSummaryError("Thiếu GEMINI_API_KEY")
    facts = [
        {
            "symbol": row.get("symbol"),
            "pattern": row.get("pattern_name_vi"),
            "status": row.get("status"),
            "score": row.get("setup_score"),
            "distance_to_breakout_pct": row.get("distance_to_breakout_pct"),
        }
        for row in candidates[:10]
    ]
    prompt = (
        "Viết đúng 1-2 câu tiếng Việt mở đầu cho báo cáo watchlist chứng khoán. "
        "Chỉ mô tả các dữ kiện JSON bên dưới; không thêm giá, dự báo, xác suất, "
        "khuyến nghị mua/bán hoặc mã không có trong JSON. Tối đa 280 ký tự.\n"
        + json.dumps(facts, ensure_ascii=False)
    )
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    response = requests.post(
        url,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 160,
            },
        },
        timeout=timeout_sec,
    )
    response.raise_for_status()
    data = response.json()
    try:
        text = str(data["candidates"][0]["content"]["parts"][0]["text"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise GeminiSummaryError("Gemini trả về cấu trúc không hợp lệ") from exc
    if not text or len(text) > 400:
        raise GeminiSummaryError("Gemini trả về phần mở đầu rỗng hoặc quá dài")

    allowed_symbols = {str(row.get("symbol")) for row in facts}
    # Guard against the most damaging wording classes.  The deterministic
    # candidate details remain the source of truth even if this intro is used.
    lowered = text.lower()
    forbidden = ("chắc chắn", "cam kết", "mua ngay", "bán ngay", "lợi nhuận")
    if any(term in lowered for term in forbidden):
        raise GeminiSummaryError("Gemini tạo nội dung mang tính khuyến nghị")
    numeric_claim_check = re.sub(r"\bVN100\b", "", text, flags=re.IGNORECASE)
    if re.search(r"\d", numeric_claim_check):
        raise GeminiSummaryError(
            "Gemini thêm số ngoài phần dữ kiện deterministic"
        )
    mentioned = set(re.findall(r"(?<![A-Z0-9])[A-Z]{2,5}(?![A-Z0-9])", text))
    # This is only a soft hallucination check: ignore ordinary Vietnamese
    # words, but reject an obvious all-uppercase ticker not in the facts.
    unknown_tickers = {
        token
        for token in mentioned
        if token not in allowed_symbols
        and token
        not in {"VN100", "EOD", "KL", "VÀ", "ĐANG", "GẦN", "CÓ", "MẪU"}
    }
    if unknown_tickers:
        raise GeminiSummaryError(
            "Gemini nhắc mã ngoài dữ liệu: " + ", ".join(sorted(unknown_tickers))
        )
    return text
