"""Core types for discovery channels. No LLM calls live anywhere in this domain."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class RawPost:
    id: str
    channel: str
    source: str
    title: str
    body: str
    url: str
    author: str = ""
    score: int = 0
    comments: int = 0
    created_at: str = ""  # ISO 8601 UTC
    extra: dict = field(default_factory=dict)

    def key(self) -> str:
        return f"{self.channel}:{self.id}"


@dataclass
class ChannelHealth:
    channel: str
    status: str  # "ok" | "unconfigured" | "error"
    detail: str = ""


class Channel(Protocol):
    name: str

    def fetch(self, item: dict) -> list[RawPost]: ...

    def health(self) -> ChannelHealth: ...


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
