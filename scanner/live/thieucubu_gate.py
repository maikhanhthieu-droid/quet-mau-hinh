"""Read-only integration with THIUCUBU's published deterministic gate.

THIUCUBU remains the authority for market-regime, flow and risk gating.  This
module deliberately accepts only its published JSON facts and never asks an AI
model to invent a substitute score.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Mapping

import requests


DEFAULT_THIUCUBU_URL = (
    "https://raw.githubusercontent.com/maikhanhthieu-droid/THIUCUBU/"
    "main/data/filter_feed_latest.json"
)


class ThieucubuGateError(RuntimeError):
    """Raised when the external deterministic gate cannot be trusted."""


def fetch_report(url: str = DEFAULT_THIUCUBU_URL, *, timeout_sec: float = 20.0) -> dict[str, Any]:
    try:
        response = requests.get(url, timeout=timeout_sec)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ThieucubuGateError("Không tải được báo cáo THIUCUBU đã công bố") from exc
    has_legacy = isinstance(payload, dict) and isinstance(payload.get("advanced_top"), dict)
    has_feed = isinstance(payload, dict) and isinstance(payload.get("facts"), list)
    if not (has_legacy or has_feed):
        raise ThieucubuGateError("Báo cáo THIUCUBU thiếu facts")
    return payload


def _report_date(payload: Mapping[str, Any]) -> date | None:
    raw = str(
        payload.get("as_of")
        or payload.get("generated_at")
        or payload.get("updated_at")
        or ""
    ).strip()
    try:
        return datetime.fromisoformat(raw).date() if raw else None
    except ValueError:
        return None


def filter_candidates(
    candidates: Iterable[Mapping[str, Any]],
    report: Mapping[str, Any],
    *,
    as_of: date,
    max_age_days: int = 3,
    enforce: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply THIUCUBU as an advisory stream, or optionally as a hard gate."""
    report_date = _report_date(report)
    if report_date is None or (as_of - report_date).days > max_age_days:
        raise ThieucubuGateError("Báo cáo THIUCUBU quá cũ hoặc không có ngày cập nhật")

    advanced_raw = report.get("advanced_top")
    if isinstance(advanced_raw, Mapping):
        advanced = advanced_raw
        regime_payload = report.get("market_regime") or {}
    else:
        advanced = {
            str(item.get("symbol") or "").upper(): item
            for item in report.get("facts", [])
            if isinstance(item, Mapping) and item.get("symbol")
        }
        regime_payload = report.get("market") or {}
    regime = str(regime_payload.get("regime") or "UNKNOWN")
    accepted: list[dict[str, Any]] = []
    rejected: dict[str, str] = {}
    for candidate in candidates:
        symbol = str(candidate.get("symbol") or "").upper()
        detail = advanced.get(symbol)
        gate = detail.get("gate") if isinstance(detail, Mapping) else None
        quality = detail.get("data_quality") if isinstance(detail, Mapping) else None
        if isinstance(quality, Mapping) and quality.get("status") != "current":
            rejected[symbol] = (
                "Dữ liệu THIUCUBU của mã không current hoặc thiếu provenance"
            )
        elif not isinstance(gate, Mapping):
            rejected[symbol] = "Không có đánh giá THIUCUBU cùng phiên"
        elif gate.get("allowed") is not True:
            rejected[symbol] = str(gate.get("reason") or "THIUCUBU không cho phép")
        else:
            accepted.append(dict(candidate))
    if not enforce:
        # Keep the scanner's own candidates. THIUCUBU is informative unless a
        # user explicitly opts into the stricter gate.
        accepted = [dict(candidate) for candidate in candidates]
    metadata = {
        "status": "applied",
        "mode": "enforced" if enforce else "advisory",
        "source": "THIUCUBU",
        "source_updated_at": (
            report.get("as_of")
            or report.get("generated_at")
            or report.get("updated_at")
        ),
        "source_schema": report.get("schema_version", "legacy"),
        "market_regime": regime,
        "input_count": len(rejected) + len(accepted),
        "accepted_count": len(accepted),
        "rejected": rejected,
    }
    return accepted, metadata
