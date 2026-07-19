from __future__ import annotations

import json
from pathlib import Path

from scanner.build_bull_flag_publication_chapter import build_publication_payload, render_publication_markdown, write_publication_chapter


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _publication_artifacts(tmp_path: Path) -> dict[str, Path]:
    stats = tmp_path / "statistics.json"
    release = tmp_path / "release.json"
    scorecard = tmp_path / "scorecard.json"
    selected = tmp_path / "selected.json"
    support = tmp_path / "support.json"
    fresh = tmp_path / "fresh.json"
    _write_json(
        stats,
        {
            "symbols_scanned": 1000,
            "detection_count": 110,
            "evaluated_count": 110,
            "median_mfe_pct": 12.72,
            "median_mae_pct": 8.18,
            "failure_5pct_rate": 24.55,
            "target_hit_rate": 39.09,
            "target_first_before_adverse_5pct_rate": 23.64,
            "target_family": {"bulkowski_adjusted_base": 0.46},
            "target_family_sensitivity": [
                {
                    "label": "bull_flags",
                    "target_multiple": 0.46,
                    "target_role": "bulkowski_adjusted_base",
                    "n": 110,
                    "target_hit_rate": 70.0,
                    "target_first_before_adverse_5pct_rate": 42.73,
                    "failure_5pct_rate": 24.55,
                    "mfe_mae_median_ratio": 1.56,
                },
                {
                    "label": "bull_flags",
                    "target_multiple": 1.0,
                    "target_role": "legacy_full_pole",
                    "n": 110,
                    "target_hit_rate": 39.09,
                    "target_first_before_adverse_5pct_rate": 23.64,
                    "failure_5pct_rate": 24.55,
                    "mfe_mae_median_ratio": 1.56,
                },
            ],
            "detector_config": {
                "width_min_bars": 5,
                "width_max_bars": 25,
                "pole_lookback_bars": 40,
                "pole_min_change_pct": 10.0,
                "pole_min_slope_deg": 8.0,
                "flag_to_pole_max_pct": 55.0,
                "breakout_threshold": 0.0075,
                "breakout_search_bars": 12,
                "require_volume_confirmed": False,
            },
        },
    )
    _write_json(
        release,
        {
            "release_status": "PASS",
            "classification": "bull_flag_tradable_research_candidate_95",
            "conservative_score": 95.78,
            "claim_level": "tradable-research-candidate under available-series descriptive scope",
            "closed_supporting_caveats": ["overlap_policy"],
            "remaining_caveats": ["corporate_action_audit"],
            "forbidden_claims": ["production trading system"],
            "main": {"score": 95.78},
            "fresh": {"score": 98.67},
        },
    )
    _write_json(scorecard, {"score": 95.78, "classification": "tradable-research-candidate"})
    _write_json(
        selected,
        {
            "selected_strategy_id": "bf_v2",
            "selection_basis": "fixed",
            "selected_metrics": {
                "trades": 62,
                "total_return_pct": 19.42,
                "validation_total_return_pct": 3.73,
                "holdout_total_return_pct": 5.54,
                "target_multiple": 0.46,
                "stop_loss_pct": 7.0,
                "entry_delay_bars": 3,
                "max_holding_days": 60,
                "position_size_pct": 0.1,
                "max_positions": 10,
                "commission_bps_per_side": 15.0,
                "slippage_bps_per_side": 10.0,
                "sell_tax_bps": 10.0,
                "median_adtv_participation_pct": 3.1,
                "min_setup_score": 60.0,
                "min_confirmation_score": None,
                "min_breakout_date": "2019-01-01",
                "allowed_market_regimes": ["bull", "bear"],
                "exclude_bear_high_liquidity_setup_score_min": 80.0,
            },
            "walk_forward_summary": {"positive_fold_rate_pct": 100.0},
            "cost_stress_summary": {"positive_scenario_rate_pct": 100.0},
            "monte_carlo_summary": {"prob_positive_pct": 100.0},
        },
    )
    _write_json(
        support,
        {
            "status": "PASS",
            "failures": [],
            "profiles": [
                {
                    "profile_id": "main_artifact",
                    "status": "PASS",
                    "scoped_events": 65,
                    "checks": {
                        "overlap_sensitivity": "PASS",
                        "liquidity_bucket_robustness": "PASS",
                        "price_limit_proxy_robustness": "PASS",
                    },
                }
            ],
        },
    )
    _write_json(
        fresh,
        {
            "scope": {"is_fresh_oos": True},
            "full_profile_evaluation": {
                "scorecard": {"score": 98.67},
                "summary": {"trades": 67, "total_return_pct": 18.15, "validation_total_return_pct": 5.48, "holdout_total_return_pct": 9.08},
                "walk_forward_summary": {"positive_fold_rate_pct": 100.0},
            },
        },
    )
    return {
        "stats": stats,
        "release": release,
        "scorecard": scorecard,
        "selected": selected,
        "support": support,
        "fresh": fresh,
    }


def test_bull_flag_publication_payload_has_contract_and_alignment(tmp_path: Path) -> None:
    paths = _publication_artifacts(tmp_path)

    payload = build_publication_payload(
        stats_path=paths["stats"],
        release_path=paths["release"],
        scorecard_path=paths["scorecard"],
        selected_strategy_path=paths["selected"],
        supporting_robustness_path=paths["support"],
        fresh_gate_path=paths["fresh"],
    )
    markdown = render_publication_markdown(payload)

    assert payload["status"] == "PASS"
    assert payload["narrative_contract"]["headline_label"].startswith("Bull Flag Tradable Research Candidate")
    assert payload["target_calibration"]["selected_base_target_multiple"] == 0.46
    assert payload["scanner_contract"]["setup_confirmation_followthrough"]["min_setup_score"] == 60.0
    assert payload["bulkowski_alignment"]["vietnam_implementation"]["base_target_multiple"] == 0.46
    assert "Bulkowski Alignment" in markdown


def test_bull_flag_publication_writer_emits_payload_markdown_and_pdf(tmp_path: Path) -> None:
    paths = _publication_artifacts(tmp_path)
    payload = build_publication_payload(
        stats_path=paths["stats"],
        release_path=paths["release"],
        scorecard_path=paths["scorecard"],
        selected_strategy_path=paths["selected"],
        supporting_robustness_path=paths["support"],
        fresh_gate_path=paths["fresh"],
    )

    out = write_publication_chapter(payload, tmp_path / "chapter")

    assert out["payload"].exists()
    assert out["markdown"].exists()
    assert out["pdf"].exists()
    assert out["pdf"].stat().st_size > 0
