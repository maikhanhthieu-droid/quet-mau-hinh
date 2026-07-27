"""Optional, non-authoritative pattern reviews from GPT and GLM.

The deterministic scanner and THIUCUBU gate decide eligibility.  Providers
may only describe whether the supplied pattern facts look coherent; failures
or disagreement never manufacture data and never promote a candidate.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

import requests


_ALLOWED_VIEWS = {"confirm", "mixed", "insufficient"}
_REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reviews"],
    "properties": {
        "reviews": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["symbol", "view", "caution"],
                "properties": {
                    "symbol": {"type": "string"},
                    "view": {"enum": sorted(_ALLOWED_VIEWS)},
                    "caution": {"type": "string", "maxLength": 180},
                },
            },
        }
    },
}


def _facts(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "symbol": row.get("symbol"),
            "pattern": row.get("pattern_name_vi"),
            "status": row.get("status"),
            "setup_score": row.get("setup_score"),
            "base_days": row.get("base_days"),
            "range_pct": row.get("range_pct"),
            "volume_ratio_5_20": row.get("volume_ratio_5_20"),
            "distance_to_breakout_pct": row.get("distance_to_breakout_pct"),
        }
        for row in candidates[:10]
    ]


def _prompt(facts: Sequence[Mapping[str, Any]]) -> str:
    return (
        "Đánh giá tính nhất quán cấu trúc của các mẫu hình chart từ JSON được cấp. "
        "Không tạo giá, target, xác suất, khuyến nghị mua/bán, hoặc mã mới. "
        "Trả JSON duy nhất: {\"reviews\":[{\"symbol\":string,"
        "\"view\":\"confirm|mixed|insufficient\",\"caution\":string}]}. "
        "Mỗi symbol xuất hiện tối đa một lần và caution tối đa 180 ký tự.\n"
        + json.dumps(list(facts), ensure_ascii=False)
    )


def _normalise(provider: str, raw: Any, symbols: set[str]) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or not isinstance(raw.get("reviews"), list):
        return {"provider": provider, "status": "invalid_response", "reviews": []}
    reviews: list[dict[str, str]] = []
    for item in raw["reviews"]:
        if not isinstance(item, Mapping):
            continue
        symbol = str(item.get("symbol") or "").upper()
        view = str(item.get("view") or "").lower()
        if symbol not in symbols or view not in _ALLOWED_VIEWS:
            continue
        caution = str(item.get("caution") or "")[:180].strip()
        mentioned = set(
            re.findall(r"(?<![A-Z0-9])[A-Z]{2,5}(?![A-Z0-9])", caution)
        )
        if re.search(r"\d", caution) or any(
            token not in symbols for token in mentioned
        ):
            caution = ""
        reviews.append({
            "symbol": symbol,
            "view": view,
            "caution": caution,
        })
    return {"provider": provider, "status": "ok", "reviews": reviews}


def _post_json(url: str, headers: Mapping[str, str], payload: Mapping[str, Any]) -> Any:
    response = requests.post(url, headers=dict(headers), json=dict(payload), timeout=30)
    response.raise_for_status()
    return response.json()


def _openai_review(api_key: str, model: str, facts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    payload = {
        "model": model,
        "input": _prompt(facts),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "pattern_reviews",
                "schema": _REVIEW_SCHEMA,
                "strict": True,
            }
        },
        "temperature": 0,
        "store": False,
    }
    data = _post_json(
        "https://api.openai.com/v1/responses",
        {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        payload,
    )
    text = _openai_output_text(data)
    return json.loads(text)


def _openai_output_text(data: Mapping[str, Any]) -> str:
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    parts: list[str] = []
    for output in data.get("output", []):
        if not isinstance(output, Mapping):
            continue
        for content in output.get("content", []):
            if not isinstance(content, Mapping):
                continue
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _zai_review(api_key: str, model: str, facts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    data = _post_json(
        "https://api.z.ai/api/paas/v4/chat/completions",
        {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        {
            "model": model,
            "messages": [{"role": "user", "content": _prompt(facts)}],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        },
    )
    text = str(data["choices"][0]["message"]["content"])
    return json.loads(text)


def build_ai_pattern_review(
    candidates: Sequence[Mapping[str, Any]],
    *,
    openai_api_key: str = "",
    openai_model: str = "gpt-4.1-mini",
    zai_api_key: str = "",
    zai_model: str = "glm-4.5-air",
) -> dict[str, Any]:
    facts = _facts(candidates)
    result: dict[str, Any] = {"input_symbols": [item["symbol"] for item in facts], "providers": []}
    if not facts:
        result["consensus"] = "no_candidates"
        return result
    symbols = {str(item["symbol"]) for item in facts}
    for provider, key, call in (
        ("openai", openai_api_key, lambda: _openai_review(openai_api_key, openai_model, facts)),
        ("zai", zai_api_key, lambda: _zai_review(zai_api_key, zai_model, facts)),
    ):
        if not key:
            result["providers"].append({"provider": provider, "status": "not_configured", "reviews": []})
            continue
        try:
            result["providers"].append(_normalise(provider, call(), symbols))
        except (requests.RequestException, ValueError, KeyError, TypeError):
            result["providers"].append({"provider": provider, "status": "unavailable", "reviews": []})

    views: dict[str, set[str]] = {symbol: set() for symbol in symbols}
    for provider in result["providers"]:
        for review in provider["reviews"]:
            views[review["symbol"]].add(review["view"])
    result["consensus"] = {
        symbol: "confirmed" if values == {"confirm"} and len(values) == 1 and sum(
            any(review["symbol"] == symbol and review["view"] == "confirm" for review in provider["reviews"])
            for provider in result["providers"]
        ) >= 2 else "mixed" if values else "unavailable"
        for symbol, values in views.items()
    }
    return result
