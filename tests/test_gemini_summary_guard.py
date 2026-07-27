from __future__ import annotations

import pytest

from scanner.live.gemini_summary import GeminiSummaryError, build_ai_intro


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "AAA có khả năng tăng 30% trong tháng tới."}
                        ]
                    }
                }
            ]
        }


def test_gemini_intro_rejects_new_numeric_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "scanner.live.gemini_summary.requests.post",
        lambda *args, **kwargs: _Response(),
    )
    with pytest.raises(GeminiSummaryError, match="thêm số"):
        build_ai_intro(
            [{"symbol": "AAA", "pattern_name_vi": "Nền phẳng"}],
            api_key="test",
            model="test",
        )
