"""Telegram Bot API sender with safe chunking and secret-safe errors."""

from __future__ import annotations

import requests


TELEGRAM_LIMIT = 4096


class TelegramSendError(RuntimeError):
    """Raised without including the token-bearing Telegram request URL."""


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
        if not str(message).strip():
            raise ValueError("Nội dung Telegram không được để trống")
        # The token is embedded in the endpoint by Telegram; never log this URL.
        endpoint = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        sent = 0
        for chunk in chunk_message(message):
            try:
                response = requests.post(
                    endpoint,
                    json={
                        "chat_id": self.chat_id,
                        "text": chunk,
                        "disable_web_page_preview": True,
                    },
                    timeout=30,
                )
            except requests.RequestException:
                # ``requests`` exceptions can embed the full URL, which
                # contains the bot token. Deliberately discard their text.
                raise TelegramSendError(
                    "Không kết nối được Telegram Bot API"
                ) from None
            if not 200 <= response.status_code < 300:
                raise TelegramSendError(
                    f"Telegram HTTP {response.status_code}"
                )
            try:
                payload = response.json()
            except (ValueError, TypeError):
                raise TelegramSendError(
                    "Telegram trả về JSON không hợp lệ"
                ) from None
            if not payload.get("ok"):
                raise TelegramSendError("Telegram trả về ok=false")
            sent += 1
        return sent
