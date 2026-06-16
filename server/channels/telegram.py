"""Telegram channel adapter.

Polls Telegram's getUpdates long-polling endpoint, relays each message to the
board, and replies with the rendered decision. The HTTP client is injectable
so tests never touch the network; the default stdlib (urllib) client is built
lazily and used only at runtime.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .mapper import SessionMapper
from .protocol import ChannelDeps

logger = logging.getLogger(__name__)


class _UrllibTelegramClient:
    """Minimal stdlib-based Telegram Bot API client.

    Built only at runtime (never injected in tests). Uses ``urllib`` so no
    third-party package is required.
    """

    def __init__(self, token: str, *, poll_timeout: int = 30) -> None:
        self._base = f"https://api.telegram.org/bot{token}"
        self._poll_timeout = poll_timeout

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        import asyncio
        import urllib.request

        url = f"{self._base}/{method}"
        data = json.dumps(payload).encode("utf-8")

        def _do() -> dict[str, Any]:
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=self._poll_timeout + 10) as resp:
                return json.loads(resp.read().decode("utf-8"))

        return await asyncio.to_thread(_do)

    async def get_updates(self, offset: int) -> list[dict[str, Any]]:
        payload = {"timeout": self._poll_timeout, "offset": offset}
        result = await self._call("getUpdates", payload)
        return result.get("result", []) if isinstance(result, dict) else []

    async def send_message(self, chat_id: Any, text: str) -> dict[str, Any]:
        return await self._call(
            "sendMessage",
            {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        )


class TelegramChannel:
    """Telegram channel adapter implementing the ``ChannelAdapter`` protocol."""

    channel_key = "telegram"

    def __init__(self, token: str, *, http: Any = None, poll_timeout: int = 30) -> None:
        self.token = token
        self.poll_timeout = poll_timeout
        self.http = http if http is not None else _UrllibTelegramClient(
            token, poll_timeout=poll_timeout
        )
        self.mapper = SessionMapper()

    @staticmethod
    def _extract(update: dict[str, Any]) -> tuple[Any, str, Any] | None:
        """Pull ``(chat_id, text, user_id)`` out of a Telegram update.

        Returns ``None`` when the update has no usable message/text.
        """
        if not isinstance(update, dict):
            return None
        message = update.get("message") or update.get("edited_message")
        if not isinstance(message, dict):
            return None
        text = message.get("text")
        if not isinstance(text, str) or not text.strip():
            return None
        chat = message.get("chat")
        if not isinstance(chat, dict):
            return None
        chat_id = chat.get("id")
        if chat_id is None:
            return None
        user = message.get("from") or {}
        user_id = user.get("id", chat_id) if isinstance(user, dict) else chat_id
        return chat_id, text, user_id

    async def _handle_update(self, update: dict[str, Any], deps: ChannelDeps) -> None:
        """Process a single Telegram update. Never raises."""
        try:
            extracted = self._extract(update)
            if extracted is None:
                return
            chat_id, text, user_id = extracted

            # Resolve a stable session for this thread (chat).
            self.mapper.resolve(
                self.channel_key, str(user_id), str(chat_id)
            )

            result = await deps.deliberate(text)
            reply = deps.render(result)
            await self.http.send_message(chat_id, reply)
        except Exception:  # never crash the loop on a single bad update
            logger.exception("telegram: failed to handle update")

    async def start(self, deps: ChannelDeps) -> None:
        """Long-poll getUpdates and handle each update. Thin by design."""
        offset = 0
        while True:
            try:
                updates = await self.http.get_updates(offset)
            except Exception:
                logger.exception("telegram: getUpdates failed; backing off")
                import asyncio

                await asyncio.sleep(min(self.poll_timeout, 5))
                continue

            for update in updates or []:
                update_id = update.get("update_id") if isinstance(update, dict) else None
                if isinstance(update_id, int):
                    offset = max(offset, update_id + 1)
                await self._handle_update(update, deps)
