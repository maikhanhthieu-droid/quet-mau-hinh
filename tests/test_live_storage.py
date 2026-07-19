from __future__ import annotations

from datetime import date

import pandas as pd

from scanner.live.storage import LiveScanStore


def _bars(close: float = 10.0) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "FPT",
                "time": pd.Timestamp("2026-07-17"),
                "open": close - 0.1,
                "high": close + 0.2,
                "low": close - 0.2,
                "close": close,
                "volume": 1_000_000,
                "source": "KBS",
            }
        ]
    )


def test_upsert_and_outbox_are_idempotent(tmp_path) -> None:
    store = LiveScanStore(tmp_path / "state.sqlite")
    assert store.upsert_bars(_bars(10.0)) == 1
    assert store.upsert_bars(_bars(10.5)) == 1

    loaded = store.load_symbol("FPT")
    assert len(loaded) == 1
    assert loaded.iloc[0]["close"] == 10.5
    assert store.latest_date("FPT") == date(2026, 7, 17)
    assert store.latest_source("FPT") == "KBS"

    candidate = {
        "as_of_date": "2026-07-17",
        "symbol": "FPT",
        "pattern_id": "flat_base",
        "detector_version": "v1",
    }
    assert store.queue_candidates([candidate]) == 1
    assert store.queue_candidates([candidate]) == 0
    pending = store.pending_candidates(date(2026, 7, 17))
    assert len(pending) == 1
    store.mark_sent(pending)
    assert store.pending_candidates(date(2026, 7, 17)) == []
    store.quick_check()
