"""Chair intake turn: clarify query, emit RoutingDecision."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class MemberAssignment:
    member_id: str
    mode: str        # fast|standard|deep
    focus: str
    priority: int


@dataclass
class RoutingDecision:
    interpreted_query: str
    decision_type: str
    complexity: str
    importance: str
    rationale: str
    members: list[MemberAssignment]
    script: str = "live_research"
    deep_research_dossier: bool = False


_DEFAULT_ROSTER = [
    ("strategist", "standard", "market context", 90),
    ("product",    "standard", "product framing", 85),
    ("researcher", "standard", "customer voice",   80),
    ("critic",     "standard", "risk pressure",    75),
    ("architect",  "standard", "technical reality", 65),
    ("builder",    "standard", "build path",       60),
]


def DEFAULT_ROUTING(query: str) -> RoutingDecision:
    """Fallback routing when intake fails or is skipped."""
    return RoutingDecision(
        interpreted_query=query,
        decision_type="full-board",
        complexity="medium",
        importance="notable",
        rationale="Fallback: chair intake unavailable; routing all members in standard mode.",
        members=[
            MemberAssignment(member_id=mid, mode=mode, focus=focus, priority=pri)
            for (mid, mode, focus, pri) in _DEFAULT_ROSTER
        ],
        script="live_research",
        deep_research_dossier=False,
    )


_REQUIRED_TOP_FIELDS = (
    "interpreted_query", "decision_type", "complexity", "importance",
    "rationale", "members",
)


def parse_routing_decision(raw: str) -> RoutingDecision | None:
    """Parse a JSON RoutingDecision; return None on any failure."""
    if not raw:
        return None
    # Tolerate code fences
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("RoutingDecision parse failed: %s", exc)
        return None
    if not isinstance(data, dict):
        return None
    if any(f not in data for f in _REQUIRED_TOP_FIELDS):
        return None
    members_raw = data.get("members") or []
    if not members_raw:
        return None
    try:
        members = [
            MemberAssignment(
                member_id=str(m["member_id"]),
                mode=str(m.get("mode", "standard")),
                focus=str(m.get("focus", "")),
                priority=int(m.get("priority", 50)),
            )
            for m in members_raw
        ]
    except (KeyError, TypeError, ValueError):
        return None
    return RoutingDecision(
        interpreted_query=str(data["interpreted_query"]),
        decision_type=str(data["decision_type"]),
        complexity=str(data["complexity"]),
        importance=str(data["importance"]),
        rationale=str(data["rationale"]),
        members=members,
        script=str(data.get("script", "live_research")),
        deep_research_dossier=bool(data.get("deep_research_dossier", False)),
    )
