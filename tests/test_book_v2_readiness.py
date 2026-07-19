from __future__ import annotations

from scanner.book_v2_readiness import chapter_readiness


def test_candidate_patterns_route_to_strategy_appendix() -> None:
    readiness, flags = chapter_readiness(
        valid_metrics={"evals": 100},
        calib_metrics={"evals": 100},
        phase3_row={"phase3_status": "candidate_after_review", "strategy_gate": "candidate"},
        benchmark_row={"benchmark_status": "roughly_aligned"},
    )

    assert readiness == "strategy_appendix"
    assert flags == []


def test_research_pattern_with_two_strong_splits_is_core_chapter() -> None:
    readiness, flags = chapter_readiness(
        valid_metrics={"evals": 20},
        calib_metrics={"evals": 20},
        phase3_row={"phase3_status": "research_only", "strategy_gate": "blocked"},
        benchmark_row={"benchmark_status": "mixed"},
    )

    assert readiness == "core_research_chapter"
    assert flags == []


def test_thin_pattern_keeps_visible_caveats() -> None:
    readiness, flags = chapter_readiness(
        valid_metrics={"evals": 3},
        calib_metrics={"evals": 2},
        phase3_row={"phase3_status": "research_only", "strategy_gate": "blocked"},
        benchmark_row={"benchmark_status": "sparse"},
    )

    assert readiness == "thin_research_chapter"
    assert flags == ["thin_valid_evals", "thin_calib_evals", "sparse_benchmark"]


def test_retired_patterns_are_reference_only_even_with_enough_evidence() -> None:
    readiness, flags = chapter_readiness(
        valid_metrics={"evals": 100},
        calib_metrics={"evals": 100},
        phase3_row={"phase3_status": "retire_from_strategy", "strategy_gate": "retired"},
        benchmark_row={"benchmark_status": "mixed"},
    )

    assert readiness == "reference_only"
    assert flags == ["reference_only_governance"]
