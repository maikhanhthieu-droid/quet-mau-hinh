from __future__ import annotations

import pandas as pd

from scanner.pivot_detector import Pivot, PivotType
from scanner.v2.pipes import PIPE_BOTTOMS, PIPE_TOPS, PipeDetector


def _frame(values: list[tuple[float, float, float, float]], symbol: str = "AAA") -> pd.DataFrame:
    rows = []
    for i, (open_, high, low, close) in enumerate(values):
        rows.append(
            {
                "symbol": symbol,
                "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=i),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": 100_000 + i * 1_000,
            }
        )
    return pd.DataFrame(rows)


def _pivot(idx: int, price: float, pivot_type: PivotType) -> Pivot:
    return Pivot(idx=idx, date=pd.Timestamp("2024-01-01") + pd.Timedelta(days=idx), price=price, type=pivot_type, strength=5, classification="minor")


def test_pipe_bottom_requires_two_near_equal_down_spikes_and_up_confirmation() -> None:
    values = []
    for close in [18, 17.4, 16.8, 16.1, 15.2, 14.4]:
        values.append((close, close * 1.01, close * 0.99, close))
    values.extend(
        [
            (14.2, 15.2, 10.0, 14.9),
            (15.1, 16.2, 14.7, 15.7),
            (15.6, 16.4, 15.2, 15.9),
            (15.0, 15.3, 10.2, 14.8),
            (15.4, 16.1, 14.9, 15.8),
            (16.4, 17.2, 16.2, 16.8),
        ]
    )
    values.extend([(17.4, 18.0, 17.0, 17.8)] * 20)
    row = PipeDetector(PIPE_BOTTOMS).scan_pair(
        _frame(values),
        _pivot(6, 10.0, PivotType.LOW),
        _pivot(9, 10.2, PivotType.LOW),
    )
    assert row is not None
    assert row["sequence_tag"] == "LL"
    assert row["breakout_direction"] == "up"
    assert row["spike_similarity_pct"] <= 4.0


def test_pipe_top_requires_two_near_equal_up_spikes_and_down_confirmation() -> None:
    values = []
    for close in [10, 10.8, 11.6, 12.5, 13.4, 14.2]:
        values.append((close, close * 1.01, close * 0.99, close))
    values.extend(
        [
            (14.4, 20.0, 14.0, 14.8),
            (14.6, 15.0, 13.6, 14.0),
            (14.2, 15.2, 13.5, 14.5),
            (14.6, 19.7, 14.2, 14.9),
            (14.4, 15.0, 13.8, 14.1),
            (13.2, 13.6, 12.2, 12.7),
        ]
    )
    values.extend([(12.0, 12.4, 11.5, 11.8)] * 20)
    row = PipeDetector(PIPE_TOPS).scan_pair(
        _frame(values),
        _pivot(6, 20.0, PivotType.HIGH),
        _pivot(9, 19.7, PivotType.HIGH),
    )
    assert row is not None
    assert row["sequence_tag"] == "HH"
    assert row["breakout_direction"] == "down"
    assert row["spike_similarity_pct"] <= 4.0

