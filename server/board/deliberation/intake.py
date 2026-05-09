"""Chair intake turn: clarify query, emit RoutingDecision."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
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


# ─────────────────────────── run_chair_intake ────────────────────────────────

from ..config import get_chairman_model  # noqa: E402 — after dataclass defs
from ..llm import query_llm              # noqa: E402
from ..tools import TOOLS, Tool          # noqa: E402


_PROTOCOL_PATH = str(
    Path(__file__).parent.parent.parent / "protocols" / "chair_intake.md"
)

_INTAKE_TOOLS = ["web_search", "ask_user_clarifying_question"]
_MAX_INTAKE_LOOP_ITERS = 6  # safety cap


@dataclass
class ChairOverrides:
    """User-provided overrides applied after the chair's routing decision."""
    depth: str | None = None                 # forces all members to this mode
    members_filter: list[str] | None = None  # restricts roster
    intake: bool = True                      # if False, skip chair, use DEFAULT_ROUTING
    ask_user: Callable | None = None         # async (q, why) -> str


def _read_intake_prompt() -> str:
    return Path(_PROTOCOL_PATH).read_text(encoding="utf-8")


def _apply_overrides(rd: RoutingDecision, ovr: ChairOverrides) -> RoutingDecision:
    members = rd.members
    if ovr.members_filter:
        members = [m for m in members if m.member_id in ovr.members_filter]
        if not members:
            members = rd.members  # don't end up empty
    if ovr.depth in ("fast", "standard", "deep"):
        members = [
            MemberAssignment(member_id=m.member_id, mode=ovr.depth,
                             focus=m.focus, priority=m.priority)
            for m in members
        ]
    return RoutingDecision(
        interpreted_query=rd.interpreted_query,
        decision_type=rd.decision_type,
        complexity=rd.complexity,
        importance=rd.importance,
        rationale=rd.rationale,
        members=members,
        script=rd.script,
        deep_research_dossier=rd.deep_research_dossier,
    )


async def run_chair_intake(
    *,
    raw_query: str,
    user_overrides: ChairOverrides,
    session: object,
    on_event: Callable[[object], None],
    chair_model: str | None = None,
) -> RoutingDecision:
    """Run the chair intake. Always returns a RoutingDecision (falls back
    to DEFAULT_ROUTING on any failure)."""
    if not user_overrides.intake:
        rd = DEFAULT_ROUTING(raw_query)
        return _apply_overrides(rd, user_overrides)

    chair_model = chair_model or get_chairman_model()
    intake_tools = [TOOLS[name] for name in _INTAKE_TOOLS if name in TOOLS]
    tool_schemas = [t.to_openai_schema() for t in intake_tools]
    system_prompt = _read_intake_prompt()
    messages: list[dict] = [{"role": "user",
                              "content": f"User query: {raw_query}"}]

    last_content = ""
    for _ in range(_MAX_INTAKE_LOOP_ITERS):
        response = await query_llm(
            chair_model, messages,
            system=system_prompt,
            tools=tool_schemas,
            tool_choice="auto",
            max_tokens=2000,
            timeout=120.0,
        )
        last_content = response.content or last_content
        if not response.tool_calls:
            break
        asst_msg = {
            "role": "assistant", "content": response.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.name,
                              "arguments": json.dumps(tc.arguments)}}
                for tc in response.tool_calls
            ],
        }
        if response.reasoning_content:
            asst_msg["reasoning_content"] = response.reasoning_content
        messages.append(asst_msg)
        from ..tools import execute_tool as _exec  # local import — avoids load-order issues
        for tc in response.tool_calls:
            r = await _exec(name=tc.name, arguments=tc.arguments,
                            session=session, member_id="chairperson")
            messages.append({"role": "tool", "tool_call_id": tc.id,
                              "content": r.content_for_model[:6000]})

    rd = parse_routing_decision(last_content) or DEFAULT_ROUTING(raw_query)
    return _apply_overrides(rd, user_overrides)
