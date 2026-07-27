from __future__ import annotations

from datetime import date

import pytest

from scanner.live.thieucubu_gate import ThieucubuGateError, filter_candidates


def _candidate(symbol: str) -> dict[str, object]:
    return {"symbol": symbol, "setup_score": 90.0}


def test_only_explicitly_allowed_thieucubu_symbols_pass() -> None:
    report = {
        "updated_at": "2026-07-27T11:04:44+07:00",
        "market_regime": {"regime": "BEAR"},
        "advanced_top": {
            "AAA": {"gate": {"allowed": True, "reason": "BEAR chi cho discount sau"}},
            "BBB": {"gate": {"allowed": False, "reason": "BEAR chan tin hieu mua"}},
        },
    }
    accepted, metadata = filter_candidates(
        [_candidate("AAA"), _candidate("BBB"), _candidate("CCC")],
        report,
        as_of=date(2026, 7, 27),
        enforce=True,
    )
    assert [row["symbol"] for row in accepted] == ["AAA"]
    assert metadata["market_regime"] == "BEAR"
    assert "BBB" in metadata["rejected"]
    assert "CCC" in metadata["rejected"]


def test_advisory_mode_keeps_scanner_candidates() -> None:
    report = {
        "updated_at": "2026-07-27T11:04:44+07:00",
        "market_regime": {"regime": "BEAR"},
        "advanced_top": {"AAA": {"gate": {"allowed": False, "reason": "BEAR"}}},
    }
    accepted, metadata = filter_candidates(
        [_candidate("AAA"), _candidate("BBB")],
        report,
        as_of=date(2026, 7, 27),
    )
    assert [row["symbol"] for row in accepted] == ["AAA", "BBB"]
    assert metadata["mode"] == "advisory"


def test_filter_feed_contract_is_consumed_without_legacy_shape() -> None:
    report = {
        "schema_version": "thieucubu.raw_filter.v1",
        "generated_at": "2026-07-27T11:04:44+07:00",
        "as_of": "2026-07-27",
        "market": {"regime": "BULL"},
        "facts": [
            {
                "symbol": "AAA",
                "gate": {"allowed": True, "reason": "BULL"},
                "data_quality": {"status": "current"},
            }
        ],
    }
    accepted, metadata = filter_candidates(
        [_candidate("AAA")],
        report,
        as_of=date(2026, 7, 27),
        enforce=True,
    )
    assert [row["symbol"] for row in accepted] == ["AAA"]
    assert metadata["source_schema"] == "thieucubu.raw_filter.v1"


def test_filter_feed_rejects_stale_symbol_even_when_gate_says_allowed() -> None:
    report = {
        "schema_version": "thieucubu.raw_filter.v1",
        "as_of": "2026-07-27",
        "market": {"regime": "BULL"},
        "facts": [{
            "symbol": "AAA",
            "gate": {"allowed": True},
            "data_quality": {"status": "stale"},
        }],
    }
    accepted, metadata = filter_candidates(
        [_candidate("AAA")],
        report,
        as_of=date(2026, 7, 27),
        enforce=True,
    )
    assert accepted == []
    assert "provenance" in metadata["rejected"]["AAA"]


def test_stale_thieucubu_report_is_rejected() -> None:
    with pytest.raises(ThieucubuGateError, match="quá cũ"):
        filter_candidates(
            [_candidate("AAA")],
            {"updated_at": "2026-07-01T00:00:00+07:00", "advanced_top": {}},
            as_of=date(2026, 7, 27),
        )
