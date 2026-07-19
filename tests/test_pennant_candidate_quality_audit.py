from __future__ import annotations

import pandas as pd

from scanner.run_pennant_candidate_quality_audit import _load_events, _metrics


def test_pennant_audit_maps_clean_usable_to_publication_tiers(tmp_path) -> None:
    events_csv = tmp_path / "events.csv"
    events_csv.write_text(
        "\n".join(
            [
                "event_id,symbol,variant,pattern_quality_tier,target_dist_pct,mfe_pct,mae_pct,failure_5pct,breakout_date",
                "e1,AAA,bull_pennant,clean,10,12,3,false,2024-01-01",
                "e2,BBB,bull_pennant,usable,10,2,9,true,2024-01-02",
                "e3,CCC,bear_pennant,loose,10,8,12,false,2024-01-03",
            ]
        ),
        encoding="utf-8",
    )
    path = pd.DataFrame(
        [
            {"event_id": "e1", "close": 10, "volume": 1000, "bar_after_breakout": 1, "signed_high_excursion_pct": 6, "signed_low_excursion_pct": -1},
            {"event_id": "e2", "close": 10, "volume": 1000, "bar_after_breakout": 1, "signed_high_excursion_pct": 3, "signed_low_excursion_pct": -6},
            {"event_id": "e3", "close": 10, "volume": 1000, "bar_after_breakout": 1, "signed_high_excursion_pct": 5, "signed_low_excursion_pct": -1},
        ]
    )

    events = _load_events(events_csv, path)

    assert events.loc[events["event_id"] == "e1", "publication_quality_tier"].iloc[0] == "premium"
    assert events.loc[events["event_id"] == "e2", "publication_quality_tier"].iloc[0] == "standard"
    assert events.loc[events["event_id"] == "e3", "publication_quality_tier"].iloc[0] == "loose"


def test_pennant_audit_metrics_use_path_order_for_target_first() -> None:
    events = pd.DataFrame(
        [
            {"event_id": "e1", "target_dist_pct": 10, "mfe_pct": 12, "mae_pct": 3, "failure_5pct": False},
            {"event_id": "e2", "target_dist_pct": 10, "mfe_pct": 12, "mae_pct": 8, "failure_5pct": False},
        ]
    )
    path = pd.DataFrame(
        [
            {"event_id": "e1", "bar_after_breakout": 1, "signed_high_excursion_pct": 6, "signed_low_excursion_pct": -1},
            {"event_id": "e2", "bar_after_breakout": 1, "signed_high_excursion_pct": 2, "signed_low_excursion_pct": -6},
            {"event_id": "e2", "bar_after_breakout": 2, "signed_high_excursion_pct": 6, "signed_low_excursion_pct": -6},
        ]
    )

    metrics = _metrics(events, path, target_multiple=0.5, row_id="test")

    assert metrics["target_hit_rate_pct"] == 100.0
    assert metrics["target_first_before_adverse_5pct_rate_pct"] == 50.0
    assert metrics["failure_5pct_rate_pct"] == 0.0
