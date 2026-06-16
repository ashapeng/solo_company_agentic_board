"""Channel adapter protocol and shared dependency container.

A *channel* is an external reach surface (Telegram, Slack, SMS, …) that
relays a user message to the board and returns the rendered decision. Each
channel adapter is constructed with its own credentials and is driven through
a small, injectable dependency bundle so the deliberation backend and the
renderer can be faked in tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable


@dataclass
class ChannelDeps:
    """Dependencies a channel needs to serve a request.

    Attributes:
        deliberate: async callable mapping a user query string to a board
            result (a ``BoardSession``, a dict, or any object the renderer
            understands). The channel does not care about the concrete type.
        render: callable turning a board result into channel-friendly text.
    """

    deliberate: Callable[[str], Awaitable[Any]]
    render: Callable[[Any], str]


@runtime_checkable
class ChannelAdapter(Protocol):
    """Structural contract every channel must satisfy."""

    channel_key: str

    async def start(self, deps: ChannelDeps) -> None:
        """Begin serving the channel using the supplied dependencies."""
        ...
