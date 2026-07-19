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
from scanner.live.gemini import GeminiSummarizer  # noqa: E402
from scanner.live.patterns import AccumulationConfig, scan_symbol  # noqa: E402
from scanner.live.reporting import deterministic_message, write_reports  # noqa: E402
from scanner.live.source_pool import AllSourcesFailed, SourcePool  # noqa: E402
from scanner.live.storage import LiveScanStore  # noqa: E402
from scanner.live.telegram import TelegramSender  # noqa: E402
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
) -> tuple[str, pd.DataFrame | None, str | None]:
    latest = None if force_bootstrap else store.latest_date(symbol)
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
            )
        )
        return symbol, frame, source
    except AllSourcesFailed as exc:
        return symbol, None, str(exc)


def run_scan(
    *,
    config: LiveScanConfig,
    as_of: date | None = None,
    no_notify: bool = False,
    force_bootstrap: bool = False,
    startup_jitter: bool = False,
) -> dict[str, Any]:
    run_id = uuid.uuid4().hex
    scan_date = as_of or _date_from_arg(None, config.timezone)
    adapter = VnstockAdapter(api_key=config.vnstock_api_key)
    adapter.register()
    if startup_jitter and config.startup_jitter_max_sec > 0:
        delay = random.SystemRandom().uniform(0.0, config.startup_jitter_max_sec)
        LOGGER.info("Startup jitter %.1f giây", delay)
        time.sleep(delay)
    supported, rejected = adapter.supported_sources(config.sources)
    if not supported:
        raise VnstockAdapterError(
            "Không có nguồn OHLCV khả dụng. "
            + "; ".join(f"{name}: {reason}" for name, reason in rejected.items())
        )
    pool = SourcePool(config, sources=config.sources)
    for source, reason in rejected.items():
        pool.disable(source, f"vnstock không hỗ trợ OHLCV: {reason}")

    listing_source = "KBS" if "KBS" in supported else supported[0]
    symbols = adapter.list_vn100(source=listing_source)
    if len(symbols) > 100:
        symbols = symbols[:100]
    if len(symbols) < 80:
        raise VnstockAdapterError(f"Universe chỉ có {len(symbols)} mã, cần gần 100 mã")

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
                    returned_symbol, frame, source_or_error = future.result()
                except Exception as exc:  # noqa: BLE001 - isolate one symbol
                    errors[symbol] = f"{type(exc).__name__}: {exc}"
                    continue
                if frame is None:
                    errors[returned_symbol] = str(source_or_error or "rỗng")
                    continue
                store.upsert_bars(frame)
                frames[returned_symbol] = frame
                source_by_symbol[returned_symbol] = str(source_or_error)

        candidates: list[dict[str, Any]] = []
        pattern_config = AccumulationConfig(
            min_bars=config.min_bars,
            min_average_value_vnd=config.min_average_value_vnd,
            max_distance_to_breakout_pct=config.max_distance_to_breakout_pct,
        )
        for symbol in symbols:
            frame = store.load_symbol(symbol)
            if frame.empty:
                continue
            candidates.extend(scan_symbol(frame, config=pattern_config))
        candidates.sort(key=lambda row: (-float(row["setup_score"]), row["symbol"], row["pattern_id"]))
        candidates = candidates[: config.max_results]
        for candidate in candidates:
            candidate["source"] = source_by_symbol.get(candidate["symbol"], "cached")
        validate_candidates(candidates)
        store.queue_candidates(candidates)

        latest_market_date = store.latest_date()
        previous_market_date = store.last_successful_market_date()
        warnings = [
            f"Không tải được {len(errors)}/{len(symbols)} mã" if errors else "",
            *[f"Nguồn {source} bị loại: {reason}" for source, reason in rejected.items()],
        ]
        if latest_market_date and previous_market_date == latest_market_date:
            warnings.append("Không có phiên giao dịch mới; bỏ qua gửi lặp")

        metadata = {
            "run_id": run_id,
            "scan_date": scan_date.isoformat(),
            "as_of_date": latest_market_date.isoformat() if latest_market_date else None,
            "latest_market_date": latest_market_date.isoformat() if latest_market_date else None,
            "universe": "VN100",
            "universe_count": len(symbols),
            "symbols_downloaded": len(frames),
            "symbols_failed": len(errors),
            "seed": seed,
            "workers": workers,
            "sources": supported,
            "source_snapshots": pool.snapshots(),
            "rejected_sources": rejected,
            "errors": errors,
            "candidate_count": len(candidates),
            "causal_only": True,
        }
        paths = write_reports(candidates, output_dir=config.output_dir, metadata=metadata)

        fallback = deterministic_message(
            candidates,
            as_of=latest_market_date or scan_date,
            warnings=warnings,
        )
        message = fallback
        if config.gemini_runtime_enabled:
            message = GeminiSummarizer(
                config.gemini_api_key, model=config.gemini_model
            ).summarize(
                candidates,
                as_of=(latest_market_date or scan_date).isoformat(),
                fallback=fallback,
            )

        should_notify = (
            not no_notify
            and not config.telegram_disable_notification
            and config.telegram_enabled
            and bool(latest_market_date)
            and (previous_market_date != latest_market_date or bool(store.pending_candidates(scan_date)))
        )
        telegram_sent = False
        if should_notify:
            sender = TelegramSender(config.telegram_bot_token, config.telegram_chat_id)
            sender.send(message)
            store.mark_sent(candidates)
            telegram_sent = True

        store.finish_run(
            run_id,
            status="success",
            latest_market_date=latest_market_date,
            symbols_downloaded=len(frames),
            candidates=len(candidates),
            metadata=metadata,
        )
        store.quick_check()
        return {
            "status": "success",
            "run_id": run_id,
            "symbols": len(symbols),
            "downloaded": len(frames),
            "failed": len(errors),
            "candidates": len(candidates),
            "latest_market_date": latest_market_date.isoformat() if latest_market_date else None,
            "telegram_sent": telegram_sent,
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
            metadata={"error": f"{type(exc).__name__}: {exc}"},
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
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
