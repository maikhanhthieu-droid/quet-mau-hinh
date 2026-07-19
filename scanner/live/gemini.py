"""Optional Gemini wording layer; deterministic facts remain authoritative."""

from __future__ import annotations

import json
import logging
from typing import Any, Iterable, Mapping

import requests


LOGGER = logging.getLogger(__name__)


class GeminiSummarizer:
    def __init__(self, api_key: str, model: str = "gemini-3.1-flash-lite") -> None:
        self.api_key = api_key
        self.model = model

    def summarize(
        self,
        candidates: Iterable[Mapping[str, Any]],
        *,
        as_of: str,
        fallback: str,
    ) -> str:
        if not self.api_key:
            return fallback
        rows = [dict(row) for row in candidates]
        facts = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
        prompt = (
            "Viết lại bản tin tiếng Việt ngắn gọn từ JSON sự kiện dưới đây. "
            "Chỉ được dùng đúng số liệu đã cho; không thêm mã, giá, xác suất hay "
            "khuyến nghị mua bán. Giữ nguyên cảnh báo đây chỉ là watchlist nghiên cứu. "
            f"Ngày dữ liệu: {as_of}. JSON: {facts}"
        )
        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )
        try:
            response = requests.post(
                endpoint,
                headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            text = payload["candidates"][0]["content"]["parts"][0]["text"].strip()
            return text if text else fallback
        except Exception as exc:  # noqa: BLE001 - optional enhancement must not fail scan
            LOGGER.warning("Gemini không khả dụng; dùng bản tin deterministic (%s)", type(exc).__name__)
            return fallback

