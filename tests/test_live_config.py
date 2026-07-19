from __future__ import annotations

import pytest

from scanner.live.config import ConfigError, LiveScanConfig


def test_aliases_share_one_source_and_one_limit() -> None:
    config = LiveScanConfig.from_env(
        {
            "SCAN_API_SOURCES": "VIETFIN,DNSE,VCI",
            "SCAN_SOURCE_LIMITS": "VIETFIN=20,DNSE=15,VCI=20",
            "SCAN_SOURCE_REQUESTS_PER_MINUTE": "20",
            "SCAN_SOURCE_USAGE_RATIO": "0.78",
            "SCAN_MAX_WORKERS": "9",
        }
    )

    assert config.sources == ("DNSE", "VCI")
    assert config.source_limits["DNSE"] == 15
    assert config.effective_limit("VIETFIN") == 11
    assert config.effective_limit("DNSE") == 11
    assert config.effective_limit("VCI") == 15
    assert config.max_workers == 2


def test_global_limit_remains_a_ceiling() -> None:
    config = LiveScanConfig.from_env(
        {
            "SCAN_API_SOURCES": "KBS",
            "SCAN_SOURCE_REQUESTS_PER_MINUTE": "20",
            "SCAN_SOURCE_LIMITS": "KBS=99",
            "SCAN_SOURCE_USAGE_RATIO": "1",
        }
    )
    assert config.configured_limit("KBS") == 20


def test_invalid_jitter_range_is_rejected() -> None:
    with pytest.raises(ConfigError):
        LiveScanConfig.from_env(
            {
                "SCAN_REQUEST_JITTER_MIN_SEC": "4",
                "SCAN_REQUEST_JITTER_MAX_SEC": "1",
            }
        )
