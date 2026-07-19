"""Send one deterministic Telegram connectivity test without scanning VN100."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from scanner.live.telegram import TelegramSendError, TelegramSender


def build_test_message(
    *,
    now: datetime | None = None,
    timezone_name: str = "Asia/Ho_Chi_Minh",
    run_url: str = "",
) -> str:
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")
        timezone_name = "UTC"
    current = now.astimezone(timezone) if now else datetime.now(timezone)
    lines = [
        "✅ QUETCHART BOT ĐÃ KẾT NỐI",
        f"Thời gian: {current:%Y-%m-%d %H:%M:%S} ({timezone_name})",
        "Kênh Telegram đã nhận được tin nhắn kiểm tra.",
        "",
        "Bước tiếp theo: chạy workflow VN100 ở chế độ incremental + notify=true.",
    ]
    if run_url.startswith("https://github.com/"):
        lines.extend(["", f"Workflow: {run_url}"])
    return "\n".join(lines)


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    missing = [
        name
        for name, value in (
            ("TELEGRAM_BOT_TOKEN", token),
            ("TELEGRAM_CHAT_ID", chat_id),
        )
        if not value
    ]
    if missing:
        print(
            "Thiếu GitHub Secret/biến môi trường: " + ", ".join(missing),
            file=sys.stderr,
        )
        return 2

    message = build_test_message(
        timezone_name=os.environ.get("SCAN_TIMEZONE", "Asia/Ho_Chi_Minh"),
        run_url=os.environ.get("GITHUB_RUN_URL", ""),
    )
    try:
        chunks = TelegramSender(token, chat_id).send(message)
    except (TelegramSendError, ValueError) as exc:
        # TelegramSendError is designed not to contain the token-bearing URL.
        print(f"Gửi Telegram thất bại: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {"status": "sent", "chunks": chunks},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
