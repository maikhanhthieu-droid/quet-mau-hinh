from __future__ import annotations

import json
from pathlib import Path

from scanner.validate_bull_flag_release_candidate import build_release_candidate, render_release_candidate_markdown, write_release_candidate


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _artifact_set(tmp_path: Path, *, main_score: float = 95.5, fresh_score: float = 98.0, fresh_positive_fold_rate: float = 100.0) -> dict[str, Path]:
    main_scorecard = tmp_path / "scorecard.json"
    selected = tmp_path / "selected.json"
    contract = tmp_path / "contract.json"
    fresh = tmp_path / "fresh.json"
    data_gate = tmp_path / "data_gate.json"
    support = tmp_path / "support.json"
    _write_json(
        main_scorecard,
        {
            "score": main_score,
            "classification": "tradable-research-candidate",
            "promotion_blockers": [],
        },
    )
    _write_json(
        selected,
        {
            "selected_strategy_id": "bf_v2",
            "selected_metrics": {
                "trades": 62,
                "total_return_pct": 19.4,
                "validation_total_return_pct": 3.7,
                "holdout_total_return_pct": 5.5,
                "median_adtv_participation_pct": 3.1,
                "min_breakout_date": "2019-01-01",
                "allowed_market_regimes": ["bull", "bear"],
            },
            "walk_forward_summary": {"positive_fold_rate_pct": 100.0, "sum_fold_return_pct": 10.0},
            "tradable_scorecard": {"score": main_score},
        },
    )
    _write_json(
        contract,
        {
            "sizing": {"target_adtv_participation_pct": 10.0, "max_adtv_participation_pct": 30.0},
            "execution_filters": {"min_breakout_date": "2019-01-01", "allowed_market_regimes": ["bull", "bear"]},
        },
    )
    _write_json(
        fresh,
        {
            "scope": {"is_fresh_oos": True, "failures": [], "warnings": ["membership_not_point_in_time"]},
            "full_profile_evaluation": {
                "events_n": 73,
                "scorecard": {"score": fresh_score, "classification": "tradable-research-candidate", "promotion_blockers": []},
                "summary": {
                    "trades": 67,
                    "total_return_pct": 18.1,
                    "validation_total_return_pct": 5.4,
                    "holdout_total_return_pct": 9.0,
                    "median_adtv_participation_pct": 3.5,
                },
                "walk_forward_summary": {"positive_fold_rate_pct": fresh_positive_fold_rate, "sum_fold_return_pct": 12.0},
            },
        },
    )
    _write_json(
        data_gate,
        {
            "investment_reference_data_gates_pass": True,
            "universe_scope": "available_series_descriptive",
            "blocked_by": [],
            "summary": {"pass": 2, "partial": 7, "fail": 0},
            "gates": [{"gate_id": "corporate_action_audit", "status": "PARTIAL"}],
        },
    )
    _write_json(
        support,
        {
            "status": "PASS",
            "failures": [],
            "closed_data_gate_partials": ["overlap_policy", "liquidity_proxy", "price_limit_microstructure"],
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
    return {
        "main_scorecard": main_scorecard,
        "selected_strategy": selected,
        "rule_contract": contract,
        "fresh_gate": fresh,
        "data_gate": data_gate,
        "supporting_robustness": support,
    }


def test_bull_flag_release_candidate_passes_with_current_contract(tmp_path: Path) -> None:
    paths = _artifact_set(tmp_path)

    payload = build_release_candidate(
        main_scorecard_path=paths["main_scorecard"],
        selected_strategy_path=paths["selected_strategy"],
        rule_contract_path=paths["rule_contract"],
        fresh_gate_path=paths["fresh_gate"],
        data_gate_path=paths["data_gate"],
        supporting_robustness_path=paths["supporting_robustness"],
    )
    report = render_release_candidate_markdown(payload)

    assert payload["release_status"] == "PASS"
    assert payload["conservative_score"] == 95.5
    assert payload["failures"] == []
    assert "corporate_action_audit" in payload["remaining_caveats"]
    assert "overlap_policy" not in payload["remaining_caveats"]
    assert "liquidity_proxy" not in payload["remaining_caveats"]
    assert "price_limit_microstructure" not in payload["remaining_caveats"]
    assert "Bull Flag Release Candidate Gate" in report


def test_bull_flag_release_candidate_writer_emits_pdf(tmp_path: Path) -> None:
    paths = _artifact_set(tmp_path)
    payload = build_release_candidate(
        main_scorecard_path=paths["main_scorecard"],
        selected_strategy_path=paths["selected_strategy"],
        rule_contract_path=paths["rule_contract"],
        fresh_gate_path=paths["fresh_gate"],
        data_gate_path=paths["data_gate"],
        supporting_robustness_path=paths["supporting_robustness"],
    )

    out_paths = write_release_candidate(payload, tmp_path / "release")

    assert out_paths["json"].exists()
    assert out_paths["report"].exists()
    assert out_paths["pdf"].exists()
    assert out_paths["pdf"].stat().st_size > 0


def test_bull_flag_release_candidate_blocks_when_fresh_walk_forward_breaks(tmp_path: Path) -> None:
    paths = _artifact_set(tmp_path, fresh_positive_fold_rate=80.0)

    payload = build_release_candidate(
        main_scorecard_path=paths["main_scorecard"],
        selected_strategy_path=paths["selected_strategy"],
        rule_contract_path=paths["rule_contract"],
        fresh_gate_path=paths["fresh_gate"],
        data_gate_path=paths["data_gate"],
        supporting_robustness_path=paths["supporting_robustness"],
    )

    assert payload["release_status"] == "BLOCK"
    assert "fresh_walk_forward_positive" in payload["failures"]


def test_bull_flag_release_candidate_blocks_when_score_drops_below_kpi(tmp_path: Path) -> None:
    paths = _artifact_set(tmp_path, main_score=94.9)

    payload = build_release_candidate(
        main_scorecard_path=paths["main_scorecard"],
        selected_strategy_path=paths["selected_strategy"],
        rule_contract_path=paths["rule_contract"],
        fresh_gate_path=paths["fresh_gate"],
        data_gate_path=paths["data_gate"],
        supporting_robustness_path=paths["supporting_robustness"],
    )

    assert payload["release_status"] == "BLOCK"
    assert "main_score_kpi" in payload["failures"]


def test_bull_flag_release_candidate_blocks_when_supporting_robustness_fails(tmp_path: Path) -> None:
    paths = _artifact_set(tmp_path)
    _write_json(paths["supporting_robustness"], {"status": "FAIL", "failures": ["main_artifact:liquidity_bucket_robustness"]})

    payload = build_release_candidate(
        main_scorecard_path=paths["main_scorecard"],
        selected_strategy_path=paths["selected_strategy"],
        rule_contract_path=paths["rule_contract"],
        fresh_gate_path=paths["fresh_gate"],
        data_gate_path=paths["data_gate"],
        supporting_robustness_path=paths["supporting_robustness"],
    )

    assert payload["release_status"] == "BLOCK"
    assert "supporting_robustness_closed" in payload["failures"]
