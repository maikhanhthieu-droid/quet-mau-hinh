from pathlib import Path

import pytest

from scanner.after_buy_source_grounding import DEFAULT_AFTER_BUY_PDF
from scanner.build_after_buy_deep_integration import build_after_buy_deep_integration


def test_after_buy_deep_integration_builds_book_wide_layer_pack(tmp_path: Path) -> None:
    if not DEFAULT_AFTER_BUY_PDF.exists():
        pytest.skip("Missing After-the-Buy PDF")

    out_dir = tmp_path / "after_buy_v2"
    source_map_path = tmp_path / "after_buy_v1" / "after_buy_source_map.json"
    result = build_after_buy_deep_integration(source_map_path=source_map_path, out_dir=out_dir)

    assert result["status"] == "PASS"
    assert result["summary"]["source_chapters"] == 26
    assert result["summary"]["manifest_chapters"] == 63
    assert result["summary"]["section_evidence_rows"] >= 200
    assert result["summary"]["normalized_rule_rows"] >= 100
    assert result["summary"]["buy_allowed_chapter_count"] >= 10
    assert result["summary"]["chapters_with_rules"] >= 10

    expected_files = [
        "after_buy_deep_rules.json",
        "after_buy_chapter_coverage_matrix.json",
        "after_buy_chapter_coverage_matrix.csv",
        "after_buy_rule_layer_mapping.json",
        "after_buy_scanner_stat_trade_config.json",
        "after_buy_before_after_impact_report.json",
        "after_buy_deep_integration_pack.json",
        "after_buy_deep_integration_pack.md",
    ]
    for file_name in expected_files:
        assert (out_dir / file_name).exists()


def test_after_buy_runtime_config_separates_buy_and_defensive_patterns(tmp_path: Path) -> None:
    if not DEFAULT_AFTER_BUY_PDF.exists():
        pytest.skip("Missing After-the-Buy PDF")

    out_dir = tmp_path / "after_buy_v2"
    source_map_path = tmp_path / "after_buy_v1" / "after_buy_source_map.json"
    build_after_buy_deep_integration(source_map_path=source_map_path, out_dir=out_dir)

    import json

    config = json.loads((out_dir / "after_buy_scanner_stat_trade_config.json").read_text(encoding="utf-8"))
    rows = {row["pattern_id"]: row for row in config["patterns"]}

    assert rows["bull_flags"]["buy_layer_allowed"] is True
    assert rows["bull_flags"]["trade_layer_mode"] == "preserve_tradable_final"
    assert rows["bull_flags"]["scanner_quality_rule_ids"]
    assert rows["bull_flags"]["required_stat_rule_ids"]
    assert rows["bull_flags"]["trade_layer_rule_ids"]

    assert rows["measured_move_up"]["buy_layer_allowed"] is True
    assert rows["measured_move_up"]["trade_layer_mode"] == "preserve_tradable_final"

    assert rows["broadening_bottoms"]["buy_layer_allowed"] is True
    assert rows["broadening_bottoms"]["trade_layer_mode"] == "source_guided_watchlist_or_rerun_blocked"
    assert rows["broadening_bottoms"]["no_overfit_gate"]["currently_blocked"] is True

    assert rows["bear_flags"]["buy_layer_allowed"] is False
    assert rows["bear_flags"]["trade_layer_mode"] == "defensive_or_reference_filter"
    assert rows["double_tops_adam_adam"]["publication_after_buy_section"]["mode"] == "cảnh_báo_rủi_ro_sau_phá_vỡ"

    assert config["summary"]["pattern_count"] == 63
    assert config["summary"]["patterns_with_scanner_rules"] >= 10
    assert config["summary"]["patterns_with_stat_rules"] >= 10
    assert config["summary"]["patterns_with_trade_rules"] >= 10
