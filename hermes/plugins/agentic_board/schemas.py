"""Typed request shapes for the Agentic Board Hermes plugin scaffold."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class DeliberateRequest:
    query: str
    member_ids: list[str] | None = None
    full_board: bool = False
    verify: bool = True
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SotbProposalRequest:
    proposed_sotb_update: str
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
