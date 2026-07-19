from pathlib import Path

import pytest

from scanner.after_buy_source_grounding import DEFAULT_AFTER_BUY_PDF
from scanner.build_after_buy_defensive_conversion_rules import (
    EDITION1_POLICY_DEFENSIVE_PATTERNS,
    SOURCE_MAPPED_DEFENSIVE_PATTERNS,
    build_after_buy_defensive_conversion_rules,
)


def test_defensive_conversion_blocks_downside_chapters_from_buy_layer(tmp_path: Path) -> None:
    if not DEFAULT_AFTER_BUY_PDF.exists():
        pytest.skip("Missing After-the-Buy PDF")

    source_map_path = tmp_path / "source" / "after_buy_source_map.json"
    out_dir = tmp_path / "defensive_conversion"
    result = build_after_buy_defensive_conversion_rules(
        source_map_path=source_map_path,
        out_dir=out_dir,
    )

    assert result["status"] == "PASS"
    assert result["kpi_evidence"]["all_denied_as_long_cash_buy"] is True
    assert result["kpi_evidence"]["defensive_pattern_count"] == len(SOURCE_MAPPED_DEFENSIVE_PATTERNS) + len(EDITION1_POLICY_DEFENSIVE_PATTERNS)

    rows = {row["pattern_id"]: row for row in result["patterns"]}
    assert set(SOURCE_MAPPED_DEFENSIVE_PATTERNS).issubset(rows)
    assert set(EDITION1_POLICY_DEFENSIVE_PATTERNS).issubset(rows)

    for pattern_id in SOURCE_MAPPED_DEFENSIVE_PATTERNS:
        row = rows[pattern_id]
        assert row["source_status"] == "after_buy_mapped_defensive"
        assert row["buy_layer_allowed"] is False
        assert row["buy_gate_denies_long_cash_buy"] is True
        assert row["conversion"] == "avoid_exit_risk_filter"
        assert row["forbidden_use"] == "long-cash BUY setup or default short-selling setup"

    for pattern_id in EDITION1_POLICY_DEFENSIVE_PATTERNS:
        row = rows[pattern_id]
        assert row["source_status"] == "edition1_policy_defensive_not_direct_after_buy"
        assert row["buy_layer_allowed"] is False
        assert row["buy_gate_denies_long_cash_buy"] is True

    assert rows["bear_flags"]["source_title"] == "Flags and Pennants"
    assert rows["measured_move_down"]["source_title"] == "Measured Move Down"
    assert rows["rectangle_tops"]["source_title"] == "Rectangles"
    assert rows["pipe_tops"]["source_title"] is None

    assert (out_dir / "defensive_conversion_rules.json").exists()
    assert (out_dir / "defensive_conversion_rules.md").exists()
