"""Small compatibility layer around the public ``vnstock`` package."""

from __future__ import annotations

import contextlib
import io
import logging
from datetime import date
from typing import Any, Iterable

import pandas as pd

from .config import canonical_source
from .source_pool import SourceNeutralError, safe_exception_summary


LOGGER = logging.getLogger(__name__)
OHLCV_COLUMNS = ("time", "open", "high", "low", "close", "volume")


class VnstockAdapterError(SourceNeutralError):
    """Raised for invalid or unusable vnstock responses."""


class UnsupportedVnstockSource(VnstockAdapterError):
    """Raised when vnstock has no OHLCV provider for a configured source."""


class VnstockAdapter:
    """Fetch VN100 membership and daily bars through vnstock 4.x."""

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key
        try:
            from vnstock import Listing, Quote, register_user
        except ImportError as exc:
            raise VnstockAdapterError(
                "Thiếu package vnstock; chạy pip install -r requirements.txt"
            ) from exc
        self._Listing = Listing
        self._Quote = Quote
        self._register_user = register_user
        self._supported_cache: dict[str, tuple[bool, str | None]] = {}

    def register(self) -> None:
        if not self.api_key:
            LOGGER.warning(
                "Không có VNSTOCK_API_KEY; vnstock sẽ dùng hạn mức khách"
            )
            return
        # vnstock currently prints partial key fragments during registration.
        # Suppress vendor stdout/stderr so even fragments never reach CI logs.
        sink = io.StringIO()
        try:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                registered = self._register_user(api_key=self.api_key)
        except Exception as exc:  # noqa: BLE001 - vendor exceptions vary
            raise VnstockAdapterError(
                "Không đăng ký được VNSTOCK_API_KEY "
                f"({safe_exception_summary(exc)})"
            ) from None
        finally:
            sink.seek(0)
            sink.truncate(0)
        if not registered:
            raise VnstockAdapterError("Không đăng ký được VNSTOCK_API_KEY")

    def source_support(self, source: str) -> tuple[bool, str | None]:
        source = canonical_source(source)
        if source in self._supported_cache:
            return self._supported_cache[source]
        try:
            quote = self._Quote(symbol="FPT", source=source, show_log=False)
            provider_name = type(quote.provider).__module__
        except Exception as exc:  # noqa: BLE001 - vnstock provider errors vary
            result = (False, safe_exception_summary(exc))
        else:
            result = (True, provider_name)
        self._supported_cache[source] = result
        return result

    def supported_sources(self, sources: Iterable[str]) -> tuple[list[str], dict[str, str]]:
        supported: list[str] = []
        rejected: dict[str, str] = {}
        for source in sources:
            canonical = canonical_source(source)
            ok, detail = self.source_support(canonical)
            if ok:
                supported.append(canonical)
            else:
                rejected[canonical] = detail or "không có OHLCV provider"
        return list(dict.fromkeys(supported)), rejected

    def list_vn100(self, *, source: str = "KBS") -> list[str]:
        source = canonical_source(source)
        ok, detail = self.source_support(source)
        if not ok:
            raise UnsupportedVnstockSource(f"{source}: {detail}")
        listing = self._Listing(source=source, show_log=False)
        # Call the provider directly so SourcePool, rather than vnstock's
        # hidden Tenacity wrapper, owns retry and quota behavior.
        raw = listing.provider.symbols_by_group(
            group="VN100",
            show_log=False,
        )
        symbols = self._extract_symbols(raw)
        if len(symbols) != 100:
            raise VnstockAdapterError(
                f"Nguồn {source} trả về {len(symbols)} mã VN100; "
                "yêu cầu đúng 100 mã unique"
            )
        return symbols

    @staticmethod
    def _extract_symbols(raw: Any) -> list[str]:
        if isinstance(raw, pd.Series):
            values = raw.tolist()
        elif isinstance(raw, pd.DataFrame):
            column = next(
                (
                    candidate
                    for candidate in ("symbol", "ticker", "code", "organ_code")
                    if candidate in raw.columns
                ),
                None,
            )
            if column is None and raw.shape[1] == 1:
                column = str(raw.columns[0])
            if column is None:
                raise VnstockAdapterError(
                    f"Không tìm thấy cột mã trong listing: {list(raw.columns)}"
                )
            values = raw[column].tolist()
        elif isinstance(raw, (list, tuple, set)):
            values = list(raw)
        else:
            raise VnstockAdapterError(
                f"Kiểu listing không được hỗ trợ: {type(raw).__name__}"
            )
        symbols = sorted(
            {
                str(value).strip().upper()
                for value in values
                if str(value).strip()
            }
        )
        return symbols

    def fetch_daily(
        self,
        source: str,
        symbol: str,
        *,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        source = canonical_source(source)
        ok, detail = self.source_support(source)
        if not ok:
            raise UnsupportedVnstockSource(f"{source}: {detail}")

        quote = self._Quote(
            symbol=str(symbol).upper(), source=source, show_log=False
        )
        # Call the pinned provider method directly so this project's external
        # limiter owns every retry.  Quote.history() adds hidden Tenacity
        # retries that would otherwise make one scheduled slot issue up to
        # three upstream requests after an error.
        raw = quote.provider.history(
            start=start.isoformat(),
            end=end.isoformat(),
            interval="1D",
        )
        if not isinstance(raw, pd.DataFrame) or raw.empty:
            raise VnstockAdapterError(
                f"{source}/{symbol}: phản hồi OHLCV rỗng"
            )
        return normalize_ohlcv(raw, symbol=symbol, source=source)


def normalize_ohlcv(
    raw: pd.DataFrame, *, symbol: str, source: str
) -> pd.DataFrame:
    """Normalize provider output and reject structurally invalid bars."""

    frame = raw.copy()
    if "date" in frame.columns and "time" not in frame.columns:
        frame = frame.rename(columns={"date": "time"})
    missing = [column for column in OHLCV_COLUMNS if column not in frame.columns]
    if missing:
        raise VnstockAdapterError(
            f"{source}/{symbol}: thiếu cột {', '.join(missing)}"
        )

    frame["time"] = pd.to_datetime(frame["time"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=list(OHLCV_COLUMNS)).copy()
    frame = frame[
        (frame["open"] > 0)
        & (frame["high"] > 0)
        & (frame["low"] > 0)
        & (frame["close"] > 0)
        & (frame["volume"] >= 0)
    ]
    frame = frame[
        (frame["high"] >= frame[["open", "close", "low"]].max(axis=1))
        & (frame["low"] <= frame[["open", "close", "high"]].min(axis=1))
    ].copy()
    if frame.empty:
        raise VnstockAdapterError(
            f"{source}/{symbol}: không còn bar hợp lệ sau kiểm tra"
        )

    # Daily bars from KBS may carry 07:00 while VCI uses midnight.  Scanner
    # storage is trading-date based, so intentionally normalize to the date.
    if frame["time"].dt.tz is not None:
        frame["time"] = frame["time"].dt.tz_localize(None)
    frame["time"] = frame["time"].dt.normalize()
    frame["symbol"] = str(symbol).strip().upper()
    frame["source"] = canonical_source(source)
    frame = (
        frame[
            ["symbol", "time", "open", "high", "low", "close", "volume", "source"]
        ]
        .drop_duplicates(subset=["symbol", "time"], keep="last")
        .sort_values("time")
        .reset_index(drop=True)
    )
    return frame
