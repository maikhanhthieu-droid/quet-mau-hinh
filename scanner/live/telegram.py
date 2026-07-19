"""Telegram Bot API sender with safe chunking and no token logging."""

from __future__ import annotations

import logging
from typing import Iterable

import requests


LOGGER = logging.getLogger(__name__)
TELEGRAM_LIMIT = 4096


def chunk_message(message: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    if limit < 100:
        raise ValueError("limit Telegram quá nhỏ")
    message = str(message)
    if len(message) <= limit:
        return [message]
    chunks: list[str] = []
    remaining = message
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n", 0, limit)
        if cut < max(1, limit // 2):
            cut = limit
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    return chunks


class TelegramSender:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id

    def send(self, message: str) -> int:
        if not self.bot_token or not self.chat_id:
            raise ValueError("Thiếu TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID")
        # The token is embedded in the endpoint by Telegram; never log this URL.
        endpoint = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        sent = 0
        for chunk in chunk_message(message):
            response = requests.post(
                endpoint,
                json={
                    "chat_id": self.chat_id,
                    "text": chunk,
                    "disable_web_page_preview": True,
                },
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                raise RuntimeError("Telegram trả về ok=false")
            sent += 1
        return sent

