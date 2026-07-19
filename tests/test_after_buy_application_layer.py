from pathlib import Path

from scanner.build_after_buy_application_layer import build_after_buy_application_layer


def test_after_buy_application_layer_produces_kpi_artifacts(tmp_path: Path) -> None:
    out_dir = tmp_path / "application"
    result = build_after_buy_application_layer(out_dir=out_dir)

    assert result["status"] == "PASS"
    assert result["summary"]["chapter_count"] == 63
    assert result["summary"]["priority_pattern_count"] == 12
    assert result["summary"]["scanner_overlay_patterns"] >= 5
    assert result["summary"]["supported_stat_metric_rows"] >= 20
    assert result["summary"]["tradable_before_after_rows"] == 12
    assert result["summary"]["defensive_signal_count"] >= 40
    assert result["summary"]["publication_pilot_count"] == 5

    expected = [
        "after_buy_application_scope.json",
        "scanner_before_after.csv",
        "statistics_metric_plan.csv",
        "tradable_before_after.csv",
        "defensive_runtime_signals.json",
        "publication_pilot_payload.json",
        "after_buy_application_report.json",
        "after_buy_application_report.md",
    ]
    for filename in expected:
        assert (out_dir / filename).exists()


def test_after_buy_application_layer_writes_priority_pattern_notes(tmp_path: Path) -> None:
    out_dir = tmp_path / "application"
    build_after_buy_application_layer(out_dir=out_dir)

    bull_pennant_dir = out_dir / "priority_patterns" / "bull_pennants"
    broadening_dir = out_dir / "priority_patterns" / "broadening_bottoms"
    assert (bull_pennant_dir / "after_buy_application_notes.json").exists()
    assert (bull_pennant_dir / "accepted_rules.json").exists()
    assert (bull_pennant_dir / "blocker_summary.md").exists()
    assert (broadening_dir / "after_buy_application_notes.json").exists()
