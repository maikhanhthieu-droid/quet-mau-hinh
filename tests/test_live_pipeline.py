from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

import scanner.run_vn100_nightly_scan as runner
from scanner.live.config import LiveScanConfig
from scanner.live.storage import LiveScanStore
from scanner.live.telegram import TelegramSendError


class _FakeVnstockAdapter:
    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key

    def register(self) -> None:
        return None

    def supported_sources(
        self,
        sources: tuple[str, ...],
    ) -> tuple[list[str], dict[str, str]]:
        return list(sources), {}

    def list_vn100(self, *, source: str = "KBS") -> list[str]:
        return [f"S{index:03d}" for index in range(100)]

    def fetch_daily(
        self,
        source: str,
        symbol: str,
        *,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        close = np.concatenate(
            [
                np.linspace(50, 68, 120),
                np.array(
                    [
                        69.0,
                        69.5,
                        70.0,
                        69.2,
                        70.2,
                        69.7,
                        70.4,
                        69.8,
                        70.5,
                        69.9,
                    ]
                    * 4
                ),
            ]
        )
        return pd.DataFrame(
            {
                "symbol": symbol,
                "time": pd.bdate_range(end=end, periods=len(close)),
                "open": close * 0.995,
                "high": close * 1.015,
                "low": close * 0.985,
                "close": close,
                "volume": 2_000_000,
                "source": source,
            }
        )


class _FailingTelegramSender:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        pass

    def send(self, message: str) -> int:
        raise TelegramSendError("Telegram HTTP 503")


class _SuccessfulTelegramSender:
    messages: list[str] = []

    def __init__(self, bot_token: str, chat_id: str) -> None:
        pass

    def send(self, message: str) -> int:
        self.messages.append(message)
        return 1


def _config(tmp_path) -> LiveScanConfig:
    return LiveScanConfig(
        sources=("KBS",),
        requests_per_minute=1000,
        source_limits={"KBS": 1000},
        usage_ratio=1.0,
        jitter_min_sec=0.0,
        jitter_max_sec=0.0,
        error_cooldown_min_sec=0.0,
        error_cooldown_max_sec=0.0,
        recover_after_sec=0.0,
        retry_after_max_sec=0.0,
        max_workers=1,
        request_attempts=1,
        startup_jitter_max_sec=0.0,
        database_path=tmp_path / "state.sqlite",
        output_dir=tmp_path / "output",
        bootstrap_calendar_days=180,
        overlap_calendar_days=7,
        min_bars=120,
        min_average_value_vnd=0.0,
        max_results=5,
        min_success_ratio=1.0,
        vnstock_api_key="vnstock_rotated_test_key",
        telegram_bot_token="123456:ROTATED_TEST_TOKEN",
        telegram_chat_id="-100123456",
        gemini_enabled=False,
    )


def test_missing_notification_secrets_fail_before_vnstock() -> None:
    config = LiveScanConfig(sources=("KBS",))
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        runner.run_scan(config=config)


def test_dry_run_pending_is_retried_and_verified_state_survives_failure(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    market_date = date(2026, 7, 17)
    monkeypatch.setattr(runner, "VnstockAdapter", _FakeVnstockAdapter)

    first = runner.run_scan(
        config=config,
        as_of=market_date,
        no_notify=True,
        use_gemini=False,
    )
    assert first["status"] == "success"
    assert first["candidates"] == 5
    store = LiveScanStore(config.database_path)
    assert len(store.pending_candidates(market_date)) == 5

    monkeypatch.setattr(runner, "TelegramSender", _FailingTelegramSender)
    failed_notification = runner.run_scan(
        config=config,
        as_of=market_date,
        use_gemini=False,
    )
    assert failed_notification["status"] == "notification_failed"
    assert failed_notification["telegram_error"] == "Telegram HTTP 503"
    assert (config.output_dir / "state_verified.json").exists()
    assert len(store.pending_candidates(market_date)) == 5
    assert len(store.symbols()) == 100

    _SuccessfulTelegramSender.messages.clear()
    monkeypatch.setattr(runner, "TelegramSender", _SuccessfulTelegramSender)
    retry = runner.run_scan(
        config=config,
        as_of=market_date,
        use_gemini=False,
    )
    assert retry["status"] == "success"
    assert retry["telegram_sent"] is True
    assert len(_SuccessfulTelegramSender.messages) == 1
    assert "Danh sách nghiên cứu" in _SuccessfulTelegramSender.messages[0]
    assert store.pending_candidates(market_date) == []
