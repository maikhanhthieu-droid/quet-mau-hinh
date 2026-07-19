"""Nightly causal VN100 accumulation scan.

Run locally with freshly rotated credentials:

    python -m scanner.run_vn100_nightly_scan --no-notify

The implementation is deliberately independent from the research scanners;
it never uses post-breakout or future-derived fields.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import secrets
import sys
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.live.config import LiveScanConfig  # noqa: E402
from scanner.live.contracts import validate_candidates  # noqa: E402
from scanner.live.gemini_summary import build_ai_intro  # noqa: E402
from scanner.live.patterns import AccumulationConfig, scan_symbol  # noqa: E402
from scanner.live.reporting import deterministic_message, write_reports  # noqa: E402
from scanner.live.source_pool import (  # noqa: E402
    AllSourcesFailed,
    SourcePool,
    safe_exception_summary,
)
from scanner.live.storage import LiveScanStore  # noqa: E402
from scanner.live.telegram import TelegramSendError, TelegramSender  # noqa: E402
from scanner.live.vnstock_adapter import (  # noqa: E402
    VnstockAdapter,
    VnstockAdapterError,
)


LOGGER = logging.getLogger("vn100-nightly")


def _date_from_arg(raw: str | None, timezone_name: str) -> date:
    if raw:
        return date.fromisoformat(raw)
    return datetime.now(ZoneInfo(timezone_name)).date()


def _fetch_one(
    symbol: str,
    *,
    store: LiveScanStore,
    adapter: VnstockAdapter,
    pool: SourcePool[pd.DataFrame],
    end_date: date,
    config: LiveScanConfig,
    force_bootstrap: bool = False,
) -> tuple[str, pd.DataFrame | None, str | None, bool]:
    latest = (
        None
        if force_bootstrap
        else store.latest_date(symbol, on_or_before=end_date)
    )
    previous_source = (
        store.latest_source(symbol, on_or_before=end_date) if latest else None
    )
    if latest:
        start_date = max(
            date(2000, 1, 1), latest - timedelta(days=config.overlap_calendar_days)
        )
    else:
        start_date = end_date - timedelta(days=config.bootstrap_calendar_days)
    try:
        frame, source = pool.call(
            lambda selected: adapter.fetch_daily(
                selected, symbol, start=start_date, end=end_date
            ),
            preferred=previous_source,
        )
        replace_history = False
        if latest and previous_source and source != previous_source:
            # Never splice a short KBS overlap onto a VCI history (or vice
            # versa). Provider adjustments can differ, so rebuild the complete
            # detector lookback through one selected source.
            full_start = end_date - timedelta(
                days=config.bootstrap_calendar_days
            )
            frame, source = pool.call(
                lambda selected: adapter.fetch_daily(
                    selected,
                    symbol,
                    start=full_start,
                    end=end_date,
                ),
                preferred=source,
            )
            replace_history = True
        return symbol, frame, source, replace_history
    except AllSourcesFailed as exc:
        return symbol, None, str(exc), False


def run_scan(
    *,
    config: LiveScanConfig,
    as_of: date | None = None,
    no_notify: bool = False,
    force_bootstrap: bool = False,
    startup_jitter: bool = False,
    use_gemini: bool = True,
) -> dict[str, Any]:
    run_id = uuid.uuid4().hex
    scan_date = as_of or _date_from_arg(None, config.timezone)
    if (
        not no_notify
        and not config.telegram_disable_notification
        and not config.telegram_enabled
    ):
        raise ValueError(
            "Đã yêu cầu gửi thông báo nhưng thiếu "
            "TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID"
        )
    if not no_notify and not config.vnstock_api_key:
        raise ValueError(
            "Chạy production cần VNSTOCK_API_KEY; "
            "chỉ dry-run/--no-notify mới được dùng guest"
        )
    if startup_jitter and config.startup_jitter_max_sec > 0:
        delay = random.SystemRandom().uniform(0.0, config.startup_jitter_max_sec)
        LOGGER.info("Startup jitter %.1f giây", delay)
        time.sleep(delay)
    adapter = VnstockAdapter(api_key=config.vnstock_api_key)
    adapter.register()
    supported, rejected = adapter.supported_sources(config.sources)
    if not supported:
        raise VnstockAdapterError(
            "Không có nguồn OHLCV khả dụng. "
            + "; ".join(f"{name}: {reason}" for name, reason in rejected.items())
        )
    pool = SourcePool(config, sources=config.sources)
    for source, reason in rejected.items():
        pool.disable(source, f"vnstock không hỗ trợ OHLCV: {reason}")

    symbols, listing_source = pool.call(
        lambda selected: adapter.list_vn100(source=selected),
        preferred="KBS" if "KBS" in supported else supported[0],
    )
    if len(symbols) != 100:
        raise VnstockAdapterError(
            f"Universe phải có đúng 100 mã unique, hiện có {len(symbols)}"
        )

    seed = config.random_seed
    if seed is None:
        seed = secrets.randbits(64)
    shuffled = list(symbols)
    random.Random(seed).shuffle(shuffled)

    store = LiveScanStore(config.database_path)
    store.start_run(run_id, scan_date, len(shuffled))
    frames: dict[str, pd.DataFrame] = {}
    source_by_symbol: dict[str, str] = {}
    errors: dict[str, str] = {}
    end_date = as_of or scan_date
    workers = max(1, min(config.max_workers, len(pool.healthy_sources()) or 1))

    try:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ohlcv") as executor:
            futures = {
                executor.submit(
                    _fetch_one,
                    symbol,
                    store=store,
                    adapter=adapter,
                    pool=pool,
                    end_date=end_date,
                    config=config,
                    force_bootstrap=force_bootstrap,
                ): symbol
                for symbol in shuffled
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    (
                        returned_symbol,
                        frame,
                        source_or_error,
                        replace_history,
                    ) = future.result()
                except Exception as exc:  # noqa: BLE001 - isolate one symbol
                    errors[symbol] = safe_exception_summary(exc)
                    continue
                if frame is None:
                    errors[returned_symbol] = str(source_or_error or "rỗng")
                    continue
                if replace_history:
                    store.replace_symbol_history(frame)
                else:
                    store.upsert_bars(frame)
                frames[returned_symbol] = frame
                source_by_symbol[returned_symbol] = str(source_or_error)

        refresh_ratio = len(frames) / len(symbols) if symbols else 0.0
        if refresh_ratio < config.min_success_ratio:
            raise VnstockAdapterError(
                f"Chỉ cập nhật được {len(frames)}/{len(symbols)} mã "
                f"({refresh_ratio:.1%}), dưới ngưỡng an toàn "
                f"{config.min_success_ratio:.0%}; không gửi Telegram"
            )

        # Use the modal last bar among responses rather than MAX(cache), which
        # could be skewed by one bad/future row or by a replay against a cache
        # that already contains later sessions.
        response_dates = [
            pd.Timestamp(frame["time"].max()).date()
            for frame in frames.values()
            if not frame.empty
        ]
        if response_dates:
            counts = Counter(response_dates)
            latest_market_date = max(
                counts,
                key=lambda value: (counts[value], value),
            )
        else:
            latest_market_date = store.latest_date(on_or_before=end_date)

        candidates: list[dict[str, Any]] = []
        stale_symbols: list[str] = []
        pattern_config = AccumulationConfig(
            min_bars=config.min_bars,
            min_average_value_vnd=config.min_average_value_vnd,
            max_distance_to_breakout_pct=config.max_distance_to_breakout_pct,
        )
        for symbol in symbols:
            frame = store.load_symbol(symbol)
            if frame.empty:
                continue
            known_frame = frame
            if latest_market_date:
                known_frame = frame.loc[
                    pd.to_datetime(frame["time"], errors="coerce")
                    <= pd.Timestamp(latest_market_date)
                ].copy()
                if (
                    known_frame.empty
                    or pd.Timestamp(known_frame["time"].max()).date()
                    != latest_market_date
                ):
                    stale_symbols.append(symbol)
                    continue
            candidates.extend(
                scan_symbol(
                    known_frame,
                    config=pattern_config,
                    as_of=latest_market_date,
                )
            )
        candidates.sort(key=lambda row: (-float(row["setup_score"]), row["symbol"], row["pattern_id"]))
        candidates = candidates[: config.max_results]
        for candidate in candidates:
            candidate["source"] = source_by_symbol.get(
                candidate["symbol"],
                candidate.get("source", "cached"),
            )
        validate_candidates(candidates)
        store.queue_candidates(candidates)

        previous_market_date = store.last_successful_market_date()
        pending_candidates = (
            store.pending_candidates(latest_market_date)
            if latest_market_date
            else []
        )
        warnings = [
            f"Không tải được {len(errors)}/{len(symbols)} mã" if errors else "",
            (
                f"Loại {len(stale_symbols)} mã không có bar ở phiên "
                f"{latest_market_date}"
                if stale_symbols
                else ""
            ),
            *[f"Nguồn {source} bị loại: {reason}" for source, reason in rejected.items()],
        ]
        if latest_market_date and previous_market_date == latest_market_date:
            warnings.append(
                "Không có phiên giao dịch mới; gửi lại thông báo đang chờ"
                if pending_candidates
                else "Không có phiên giao dịch mới; bỏ qua gửi lặp"
            )

        metadata = {
            "run_id": run_id,
            "scan_date": scan_date.isoformat(),
            "as_of_date": latest_market_date.isoformat() if latest_market_date else None,
            "latest_market_date": latest_market_date.isoformat() if latest_market_date else None,
            "universe": "VN100",
            "universe_count": len(symbols),
            "symbols_downloaded": len(frames),
            "symbols_failed": len(errors),
            "refresh_ratio": round(refresh_ratio, 4),
            "stale_symbols": stale_symbols,
            "seed": seed,
            "workers": workers,
            "sources": supported,
            "listing_source": listing_source,
            "source_snapshots": pool.snapshots(),
            "rejected_sources": rejected,
            "errors": errors,
            "candidate_count": len(candidates),
            "pending_notification_count": len(pending_candidates),
            "causal_only": True,
        }

        notification_candidates = pending_candidates or candidates
        fallback = deterministic_message(
            notification_candidates,
            as_of=latest_market_date or scan_date,
            warnings=warnings,
        )
        message = fallback
        should_notify = (
            not no_notify
            and not config.telegram_disable_notification
            and config.telegram_enabled
            and bool(latest_market_date)
            and (
                previous_market_date != latest_market_date
                or bool(pending_candidates)
            )
        )
        if (
            should_notify
            and use_gemini
            and config.gemini_runtime_enabled
        ):
            try:
                intro = build_ai_intro(
                    notification_candidates,
                    api_key=config.gemini_api_key,
                    model=config.gemini_model,
                )
            except Exception as exc:  # noqa: BLE001 - optional wording layer
                LOGGER.warning(
                    "Gemini không khả dụng; dùng bản tin deterministic (%s)",
                    type(exc).__name__,
                )
            else:
                # AI may only add an intro. The calculated facts, warnings and
                # disclaimer below remain deterministic and authoritative.
                message = intro.rstrip() + "\n\n" + fallback

        telegram_sent = False
        telegram_chunks = 0
        telegram_error: str | None = None
        if should_notify:
            sender = TelegramSender(config.telegram_bot_token, config.telegram_chat_id)
            try:
                telegram_chunks = sender.send(message)
            except TelegramSendError as exc:
                telegram_error = str(exc)
            else:
                store.mark_sent(pending_candidates)
                telegram_sent = True

        run_status = "notification_failed" if telegram_error else "success"
        metadata.update(
            {
                "notification_requested": not no_notify,
                "notification_eligible": should_notify,
                "telegram_sent": telegram_sent,
                "telegram_chunks": telegram_chunks,
                "telegram_error": telegram_error,
            }
        )
        paths = write_reports(
            candidates,
            output_dir=config.output_dir,
            metadata=metadata,
            telegram_message=message,
        )

        store.finish_run(
            run_id,
            status=run_status,
            latest_market_date=latest_market_date,
            symbols_downloaded=len(frames),
            candidates=len(candidates),
            metadata=metadata,
        )
        store.quick_check()
        state_marker = config.output_dir / "state_verified.json"
        state_marker.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": run_status,
                    "database_quick_check": "ok",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        paths["state_verified"] = state_marker
        return {
            "status": run_status,
            "run_id": run_id,
            "symbols": len(symbols),
            "downloaded": len(frames),
            "failed": len(errors),
            "candidates": len(candidates),
            "latest_market_date": latest_market_date.isoformat() if latest_market_date else None,
            "telegram_sent": telegram_sent,
            "telegram_chunks": telegram_chunks,
            "telegram_error": telegram_error,
            "paths": {key: str(value) for key, value in paths.items()},
            "sources": pool.snapshots(),
        }
    except Exception as exc:
        store.finish_run(
            run_id,
            status="failed",
            latest_market_date=store.latest_date(),
            symbols_downloaded=len(frames),
            candidates=0,
            metadata={"error": safe_exception_summary(exc)},
        )
        raise


def main() -> None:
    # Windows PowerShell may expose a cp1252 stdout; the CLI emits Vietnamese
    # report text, so make help/JSON reliable without requiring a shell tweak.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Nightly causal VN100 accumulation scanner")
    parser.add_argument("--no-notify", action="store_true", help="Không gửi Telegram")
    parser.add_argument(
        "--mode",
        choices=("incremental", "bootstrap", "dry-run"),
        default="incremental",
        help="incremental cập nhật tăng dần; bootstrap tải lại lịch sử; dry-run không gửi Telegram",
    )
    parser.add_argument("--startup-jitter", action="store_true", help="Chờ ngẫu nhiên trước khi gọi API")
    parser.add_argument("--as-of", help="Ngày kết thúc YYYY-MM-DD (phục vụ kiểm thử/replay)")
    parser.add_argument(
        "--no-gemini",
        action="store_true",
        help="Không dùng lớp viết mở đầu Gemini",
    )
    parser.add_argument("--validate-config", action="store_true", help="Chỉ kiểm tra cấu hình")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = LiveScanConfig.from_env()
    if args.validate_config:
        print(json.dumps({"status": "valid", "sources": config.sources, "workers": config.max_workers, "effective_limits": {source: config.effective_limit(source) for source in config.sources}}, ensure_ascii=False, indent=2))
        return
    summary = run_scan(
        config=config,
        as_of=date.fromisoformat(args.as_of) if args.as_of else None,
        no_notify=args.no_notify or args.mode == "dry-run",
        force_bootstrap=args.mode == "bootstrap",
        startup_jitter=args.startup_jitter,
        use_gemini=not args.no_gemini,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    if summary["status"] == "notification_failed":
        raise SystemExit(3)


if __name__ == "__main__":
    main()
