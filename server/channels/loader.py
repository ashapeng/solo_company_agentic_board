"""Discover and construct enabled channel adapters from the environment.

A channel is enabled when its credential env var is present. With no tokens
configured, ``load_enabled_channels`` returns an empty list, making the
``--serve-channels`` CLI flag a safe no-op.
"""

from __future__ import annotations

import os
from typing import Any

from .telegram import TelegramChannel


def load_enabled_channels() -> list[Any]:
    """Return constructed adapters for every configured channel ([] if none)."""
    channels: list[Any] = []

    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if telegram_token:
        channels.append(TelegramChannel(telegram_token))

    return channels
