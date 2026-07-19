"""Print chat IDs that have recently messaged the configured Telegram bot."""

from __future__ import annotations

import os
import sys

import requests


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("Thiếu TELEGRAM_BOT_TOKEN trong biến môi trường.", file=sys.stderr)
        return 2
    # Never print/log this URL; it embeds the bot token.
    response = requests.get(
        f"https://api.telegram.org/bot{token}/getUpdates",
        timeout=30,
    )
    response.raise_for_status()
    chats: dict[str, str] = {}
    for update in response.json().get("result", []):
        message = update.get("message") or update.get("channel_post") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            continue
        label = (
            chat.get("title")
            or chat.get("username")
            or " ".join(
                part
                for part in (chat.get("first_name"), chat.get("last_name"))
                if part
            )
            or "không tên"
        )
        chats[str(chat_id)] = str(label)
    if not chats:
        print("Chưa có chat. Hãy mở bot, gửi /start rồi chạy lại lệnh này.")
        return 1
    for chat_id, label in sorted(chats.items()):
        print(f"{chat_id}\t{label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
