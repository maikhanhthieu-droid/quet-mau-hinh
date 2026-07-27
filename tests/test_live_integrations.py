from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import pytest
import requests

from scanner.live.reporting import write_reports
from scanner.live.telegram import (
    TelegramSendError,
    TelegramSender,
    chunk_message,
)
from scanner.live.vnstock_adapter import (
    VnstockAdapter,
    VnstockAdapterError,
    normalize_ohlcv,
)
from scanner.send_telegram_test import build_test_message


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


class _FakeTelegramResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


def test_telegram_http_error_never_exposes_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "999999:TOP_SECRET_TOKEN"
    monkeypatch.setattr(
        "scanner.live.telegram.requests.post",
        lambda *args, **kwargs: _FakeTelegramResponse(
            401,
            {"ok": False, "description": f"echo {token}"},
        ),
    )
    with pytest.raises(TelegramSendError) as captured:
        TelegramSender(token, "123").send("test")
    rendered = str(captured.value)
    assert token not in rendered
    assert "api.telegram.org" not in rendered
    assert rendered == "Telegram HTTP 401"


def test_telegram_network_error_never_exposes_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "999999:TOP_SECRET_TOKEN"

    def fail(*args: object, **kwargs: object) -> object:
        raise requests.ConnectionError(
            f"https://api.telegram.org/bot{token}/sendMessage"
        )

    monkeypatch.setattr("scanner.live.telegram.requests.post", fail)
    with pytest.raises(TelegramSendError) as captured:
        TelegramSender(token, "123").send("test")
    assert token not in str(captured.value)
    assert "api.telegram.org" not in str(captured.value)


def test_vnstock_registration_suppresses_vendor_key_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    key = "vnstock_SENTINEL_FULL_SECRET"
    adapter = object.__new__(VnstockAdapter)
    adapter.api_key = key

    def noisy_register(*, api_key: str) -> bool:
        print(api_key)
        print(f"{api_key[:4]}***{api_key[-4:]}")
        return True

    adapter._register_user = noisy_register
    adapter.register()
    captured = capsys.readouterr()
    assert key not in captured.out + captured.err
    assert f"{key[:4]}***{key[-4:]}" not in captured.out + captured.err


def test_vnstock_registration_exception_is_sanitized() -> None:
    key = "vnstock_SENTINEL_FULL_SECRET"
    adapter = object.__new__(VnstockAdapter)
    adapter.api_key = key

    def failing_register(*, api_key: str) -> bool:
        raise RuntimeError(f"bad key {api_key}")

    adapter._register_user = failing_register
    with pytest.raises(VnstockAdapterError) as captured:
        adapter.register()
    assert key not in str(captured.value)
    assert "RuntimeError" in str(captured.value)


def test_smoke_message_and_report_artifact(tmp_path) -> None:
    message = build_test_message(
        now=datetime(2026, 7, 19, 2, 0, tzinfo=timezone.utc),
        timezone_name="Asia/Ho_Chi_Minh",
        run_url="https://github.com/example/repo/actions/runs/1",
    )
    assert "QUETCHART BOT ĐÃ KẾT NỐI" in message
    paths = write_reports(
        [],
        output_dir=tmp_path,
        metadata={"as_of_date": "2026-07-17"},
        telegram_message=message,
    )
    assert paths["telegram"].read_text(encoding="utf-8").strip() == message
    feed = json.loads(paths["pattern_feed"].read_text(encoding="utf-8"))
    assert feed["schema_version"] == "chart-patterns.facts.v1"
    assert feed["quality"]["ai_output_included"] is False
