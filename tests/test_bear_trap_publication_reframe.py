import json
from pathlib import Path

from scanner.apply_bear_trap_publication_reframe import (
    BEAR_PATTERN_IDS,
    NEW_CLASSIFICATION,
    NEW_CLAIM_LEVEL,
    NEW_ROLE_NOTE,
    REFRAME_ID,
)


MANIFEST = Path("artifacts/final_chapters/final_chapters_manifest.json")
SUMMARY = Path("artifacts/scanner_v2/bear_trap_stoploss_caution/bear_trap_stoploss_caution_summary.csv")


def _manifest_chapters() -> dict[str, dict]:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {row["pattern_id"]: row for row in payload["chapters"]}


def test_bear_trap_reframe_covers_all_bear_final_chapters() -> None:
    assert SUMMARY.exists()
    chapters = _manifest_chapters()
    missing = set(BEAR_PATTERN_IDS) - set(chapters)
    assert not missing
    for pattern_id in BEAR_PATTERN_IDS:
        row = chapters[pattern_id]
        assert row["classification"] == NEW_CLASSIFICATION
        assert row["claim_level"] == NEW_CLAIM_LEVEL
        assert row["bear_trap_publication_reframe_id"] == REFRAME_ID
        assert row["bear_trap_stoploss_caution_layer_id"] == "bear_trap_stoploss_caution_layer_v1"
        assert row["bear_trap_reclaim_20d_rate_pct"] >= 0.0


def test_bear_trap_reframe_payloads_have_reader_sections() -> None:
    chapters = _manifest_chapters()
    for pattern_id in BEAR_PATTERN_IDS:
        payload_path = Path(chapters[pattern_id]["payload"])
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        assert payload["classification"] == NEW_CLASSIFICATION
        assert payload["claim_level"] == NEW_CLAIM_LEVEL
        assert payload["role_note"] == NEW_ROLE_NOTE
        assert payload["bear_trap_publication_reframe_id"] == REFRAME_ID
        caution = payload["bear_trap_stoploss_caution"]
        assert caution["reader_role"] == "stop_loss_caution_not_buy_signal"
        assert caution["tradable_promotion_allowed"] is False
        sections = payload["editorial_sections"]
        combined = "\n".join(
            "\n".join(items) for items in sections.values() if isinstance(items, list)
        )
        assert REFRAME_ID not in combined
        assert "bẫy giảm" in combined
        assert "quay lại vùng phá vỡ" in combined
        assert "tín hiệu mua" in combined
        assert "defensive/informational" not in combined
        for forbidden in ("stop-loss", "MFE", "MAE", "target-first", "BUY signal", "short setup", "retuyên bố"):
            assert forbidden not in combined
