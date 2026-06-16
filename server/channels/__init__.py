"""Multi-channel reach: relay board deliberations to external surfaces."""

from __future__ import annotations

from .loader import load_enabled_channels
from .mapper import SessionMapper
from .protocol import ChannelAdapter, ChannelDeps
from .render import render_brief
from .telegram import TelegramChannel

__all__ = [
    "ChannelAdapter",
    "ChannelDeps",
    "SessionMapper",
    "render_brief",
    "TelegramChannel",
    "load_enabled_channels",
]
