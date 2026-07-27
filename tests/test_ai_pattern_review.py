from __future__ import annotations

import json

import pytest

from scanner.live.ai_pattern_review import (
    _openai_output_text,
    build_ai_pattern_review,
)


def _candidate(symbol: str = "AAA") -> dict[str, object]:
    return {
        "symbol": symbol,
        "pattern_name_vi": "Nền phẳng",
        "status": "forming",
        "setup_score": 90.0,
        "base_days": 25,
        "range_pct": 7.0,
        "volume_ratio_5_20": 0.7,
        "distance_to_breakout_pct": 2.0,
    }


def test_review_requires_two_matching_confirmations(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url, headers, payload):
        if "openai" in url:
            return {"output_text": json.dumps({"reviews": [{"symbol": "AAA", "view": "confirm", "caution": ""}]})}
        return {"choices": [{"message": {"content": json.dumps({"reviews": [{"symbol": "AAA", "view": "confirm", "caution": ""}]})}}]}

    monkeypatch.setattr("scanner.live.ai_pattern_review._post_json", fake_post)
    result = build_ai_pattern_review([_candidate()], openai_api_key="test", zai_api_key="test")
    assert result["consensus"]["AAA"] == "confirmed"


def test_ai_review_never_accepts_unknown_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "scanner.live.ai_pattern_review._post_json",
        lambda *args, **kwargs: {"output_text": json.dumps({"reviews": [{"symbol": "FAKE", "view": "confirm"}]})},
    )
    result = build_ai_pattern_review([_candidate()], openai_api_key="test")
    assert result["providers"][0]["reviews"] == []
    assert result["consensus"]["AAA"] == "unavailable"


def test_no_candidate_makes_no_provider_call() -> None:
    result = build_ai_pattern_review([], openai_api_key="test", zai_api_key="test")
    assert result == {"input_symbols": [], "providers": [], "consensus": "no_candidates"}


def test_review_strips_numeric_or_unknown_ticker_caution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "scanner.live.ai_pattern_review._post_json",
        lambda *args, **kwargs: {
            "output_text": json.dumps(
                {
                    "reviews": [
                        {
                            "symbol": "AAA",
                            "view": "mixed",
                            "caution": "BBB có target 30 phần trăm",
                        }
                    ]
                }
            )
        },
    )
    result = build_ai_pattern_review([_candidate()], openai_api_key="test")
    assert result["providers"][0]["reviews"][0]["caution"] == ""


def test_openai_output_text_supports_raw_responses_envelope() -> None:
    payload = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": '{"reviews":[]}',
                    }
                ],
            }
        ]
    }
    assert _openai_output_text(payload) == '{"reviews":[]}'
