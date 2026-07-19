import json
from pathlib import Path

from scanner import run_after_buy_quantitative_effect as effect


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_after_buy_quantitative_effect_compares_real_rerun_rows(tmp_path: Path, monkeypatch) -> None:
    governance_path = tmp_path / "governance.json"
    after_buy_dir = tmp_path / "after_buy_v2"
    out_dir = tmp_path / "effect"
    patterns = ("alpha_pattern", "beta_pattern")

    _write_json(
        governance_path,
        {
            "chapters": [
                {
                    "pattern_id": "alpha_pattern",
                    "tradable_score": 88.0,
                    "tradable_release_status": "BLOCK",
                    "tradable_blockers": "score_below_95",
                },
                {
                    "pattern_id": "beta_pattern",
                    "tradable_score": 96.0,
                    "tradable_release_status": "PASS",
                    "tradable_blockers": "",
                },
            ]
        },
    )
    _write_json(
        after_buy_dir / "after_buy_scanner_stat_trade_config.json",
        {
            "patterns": [
                {
                    "pattern_id": "alpha_pattern",
                    "trade_layer_mode": "source_guided_watchlist_or_rerun_blocked",
                    "no_overfit_gate": {"currently_blocked": True},
                },
                {
                    "pattern_id": "beta_pattern",
                    "trade_layer_mode": "preserve_tradable_final",
                    "no_overfit_gate": {"currently_blocked": False},
                },
            ]
        },
    )

    def fake_run_all_branch_optimizations(*, out_dir: Path, chapters: set[str], reuse_existing: bool = False):
        assert chapters == set(patterns)
        assert reuse_existing is False
        _write_json(
            out_dir / "all_chapters_branch_optimization_summary.json",
            {
                "rows": [
                    {
                        "pattern_id": "alpha_pattern",
                        "score": 91.5,
                        "release_status": "BLOCK",
                        "promotion_blockers": ["walk_forward_has_negative_fold"],
                        "branch_count": 12,
                        "selected_strategy_id": "alpha_branch",
                        "fixed_walk_forward_summary": {
                            "positive_fold_rate_pct": 75.0,
                            "worst_fold_return_pct": -1.2,
                        },
                    },
                    {
                        "pattern_id": "beta_pattern",
                        "score": 95.5,
                        "release_status": "PASS",
                        "promotion_blockers": [],
                        "branch_count": 4,
                        "selected_strategy_id": "beta_branch",
                        "fixed_walk_forward_summary": {
                            "positive_fold_rate_pct": 100.0,
                            "worst_fold_return_pct": 2.1,
                        },
                    },
                ]
            },
        )

    monkeypatch.setattr(effect, "run_all_branch_optimizations", fake_run_all_branch_optimizations)

    result = effect.build_after_buy_quantitative_effect(
        after_buy_v2_dir=after_buy_dir,
        out_dir=out_dir,
        governance_path=governance_path,
        patterns=patterns,
    )

    assert result["status"] == "PASS"
    assert result["summary"]["pattern_count"] == 2
    assert result["summary"]["promoted_count"] == 1
    assert result["summary"]["blocked_after_rerun_count"] == 1

    rows = {row["pattern_id"]: row for row in result["rows"]}
    assert rows["alpha_pattern"]["decision"] == "blocked_after_rerun"
    assert rows["alpha_pattern"]["after_buy_no_overfit_blocked"] is True
    assert rows["beta_pattern"]["decision"] == "promoted_to_tradable_final"
    assert rows["beta_pattern"]["score_delta"] == -0.5

    assert (out_dir / "after_buy_quantitative_effect_report.json").exists()
    assert (out_dir / "after_buy_quantitative_effect_comparison.csv").exists()
    assert (out_dir / "after_buy_quantitative_effect_report.md").exists()
    assert "real branch-rerun comparison" in result["interpretation"]
