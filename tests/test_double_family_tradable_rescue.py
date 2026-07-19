from __future__ import annotations

import json
from pathlib import Path


ARTIFACT = Path("artifacts/scanner_v2/double_family_tradable_rescue/double_family_tradable_rescue.json")


def _payload() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_double_family_rescue_artifact_covers_bottoms_and_tops() -> None:
    payload = _payload()

    assert payload["audit_id"] == "double_family_tradable_rescue_v1"
    assert payload["family_count"] == 2
    assert {row["family"] for row in payload["families"]} == {"double_bottoms", "double_tops"}


def test_double_bottoms_family_can_recover_tradable_depth_without_variant_overclaim() -> None:
    rows = {row["family"]: row for row in _payload()["families"]}
    bottoms = rows["double_bottoms"]
    guard = bottoms["no_overlift_guard"]

    assert bottoms["scope"] == "long_cash_candidate"
    assert bottoms["best_score"] >= 95.0
    assert guard["promotion_decision"] == "ELIGIBLE_FOR_FAMILY_PROMOTION_REVIEW"
    assert guard["remaining_tradable_blockers"] == []
    assert bottoms["variant_support_decision"] == "FAMILY_PROMOTION_REVIEW_VARIANTS_REMAIN_SUBGROUPS"

    stats = bottoms["best_variant_trade_stats"]
    assert set(stats) == {"AA", "AE", "EA", "EE"}
    assert sum(item["trades"] for item in stats.values()) == bottoms["rows"][0]["trades"]
    assert stats["AE"]["trades"] > 0
    assert stats["EA"]["trades"] > 0
    assert stats["EE"]["trades"] > 0


def test_double_tops_family_remains_defensive_even_when_score_is_high() -> None:
    rows = {row["family"]: row for row in _payload()["families"]}
    tops = rows["double_tops"]
    guard = tops["no_overlift_guard"]

    assert tops["scope"] == "defensive_informational"
    assert tops["best_score"] >= 95.0
    assert guard["promotion_decision"] == "STOP_NO_PROMOTION_UNDER_NO_OVERLIFT_POLICY"
    assert "scope_not_direct_long_cash_equity" in guard["remaining_tradable_blockers"]
    assert "direct_long_cash_scope" in guard["failures"]
    assert tops["variant_support_decision"] == "DEFENSIVE_FAMILY_SUPPORT_ONLY"


def test_double_family_rescue_expands_source_depth_beyond_thin_variants() -> None:
    rows = {row["family"]: row for row in _payload()["families"]}
    bottoms = rows["double_bottoms"]
    tops = rows["double_tops"]

    bottom_scopes = bottoms["meta"]["source_scopes"]
    top_scopes = tops["meta"]["source_scopes"]

    assert bottom_scopes["loose_plus"]["events_scoped"] >= 500
    assert bottom_scopes["standard_premium"]["events_scoped"] >= 250
    assert top_scopes["loose_plus"]["events_scoped"] >= 300
    assert top_scopes["standard_premium"]["events_scoped"] >= 150
