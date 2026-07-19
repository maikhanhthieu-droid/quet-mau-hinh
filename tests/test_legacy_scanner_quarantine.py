from __future__ import annotations

import pytest

from scanner.legacy_guard import (
    ALLOW_LEGACY_ENV,
    ALLOW_LEGACY_PUBLICATION_ENV,
    require_legacy_enabled,
    require_legacy_publication_builder_enabled,
)


def test_legacy_scanner_is_blocked_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ALLOW_LEGACY_ENV, raising=False)

    with pytest.raises(RuntimeError, match="quarantined legacy scanner logic"):
        require_legacy_enabled("legacy-test")


def test_legacy_scanner_can_be_enabled_for_historical_comparison(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ALLOW_LEGACY_ENV, "1")

    require_legacy_enabled("legacy-test")


def test_legacy_publication_builder_is_blocked_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ALLOW_LEGACY_PUBLICATION_ENV, raising=False)

    with pytest.raises(RuntimeError, match="quarantined legacy PDF publication logic"):
        require_legacy_publication_builder_enabled("legacy-publication-test")


def test_legacy_publication_builder_can_be_enabled_for_historical_comparison(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ALLOW_LEGACY_PUBLICATION_ENV, "1")

    require_legacy_publication_builder_enabled("legacy-publication-test")


def test_legacy_report_entrypoints_are_blocked_before_argparse(monkeypatch: pytest.MonkeyPatch) -> None:
    from scanner.audit_kpi import main as audit_kpi_main
    from scanner.report_bulkowski import main as report_bulkowski_main

    monkeypatch.delenv(ALLOW_LEGACY_ENV, raising=False)

    with pytest.raises(RuntimeError, match="scanner/report_bulkowski.py is quarantined"):
        report_bulkowski_main()
    with pytest.raises(RuntimeError, match="scanner/audit_kpi.py is quarantined"):
        audit_kpi_main()


def test_legacy_publication_entrypoints_are_blocked_before_argparse(monkeypatch: pytest.MonkeyPatch) -> None:
    from scanner._legacy_quarantine.build_bull_flag_investor_chapter import main as investor_main
    from scanner._legacy_quarantine.build_bull_flag_public_chapter import main as public_main

    monkeypatch.delenv(ALLOW_LEGACY_PUBLICATION_ENV, raising=False)

    with pytest.raises(RuntimeError, match="scanner/_legacy_quarantine/build_bull_flag_public_chapter.py is quarantined"):
        public_main()
    with pytest.raises(RuntimeError, match="scanner/_legacy_quarantine/build_bull_flag_investor_chapter.py is quarantined"):
        investor_main()


def test_canonical_publication_flow_is_not_wired_to_legacy_builders() -> None:
    from scanner.audit_publication_entrypoints import audit_publication_entrypoints

    report = audit_publication_entrypoints()

    assert report["status"] == "PASS"


def test_publication_core_requires_approved_public_rules() -> None:
    from scanner.pattern_publication_core import _rule_rows

    with pytest.raises(ValueError, match="Missing approved public recognition rules"):
        _rule_rows({}, {"title": "missing-rules"}, {})
