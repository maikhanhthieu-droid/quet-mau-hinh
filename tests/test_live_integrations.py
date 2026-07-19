from __future__ import annotations

import pandas as pd

from scanner.live.telegram import chunk_message
from scanner.live.vnstock_adapter import normalize_ohlcv


def test_daily_timestamps_are_normalized_across_sources() -> None:
    raw = pd.DataFrame(
        [
            {
                "time": "2026-07-17 07:00:00",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.3,
                "volume": 1000,
            }
        ]
    )
    normalized = normalize_ohlcv(raw, symbol="fpt", source="kbs")
    assert normalized.iloc[0]["time"] == pd.Timestamp("2026-07-17")
    assert normalized.iloc[0]["symbol"] == "FPT"
    assert normalized.iloc[0]["source"] == "KBS"


def test_telegram_chunking_preserves_content() -> None:
    text = "\n".join(f"Dòng {index}: " + "x" * 80 for index in range(100))
    chunks = chunk_message(text, limit=300)
    assert chunks
    assert all(len(chunk) <= 300 for chunk in chunks)
    assert "\n".join(chunks) == text
