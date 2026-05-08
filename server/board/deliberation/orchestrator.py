"""
3-Stage Board Deliberation Orchestrator.

Implements the Karpathy LLM Council pattern adapted for an agentic board:
  Stage 1: Independent Analysis   — all members analyze independently
  Stage 2: Peer Review & Challenge — members review anonymized peer responses
  Stage 3: Chairman Synthesis      — chairperson produces final board decision
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from server.execution import parse_delegation_plan, record_delegation_plan
from server.harness.config import (
    get_config,
    resolve_model_preferences,
    resolve_routing_suppressed_member_ids,
    resolve_stage_max_tokens,
)
from server.harness.ledger import record_session as _record_to_ledger
from server.memory.review import propose_memory_update
from server.memory.sotb import read_sotb

from .compaction import (
    compact_stage1_responses,
    compact_stage2_responses,
    compact_stage1_with_warnings,
    compact_stage2_with_warnings,
)
from ..config import BoardMember, get_board_members, get_members_by_id, get_chairman_model, get_council_models
from ..llm import query_llm, LLMResponse, ToolCall
from ..tools import Tool, ToolResult, execute_tool
from ..metrics import CallMetrics, SessionMetrics
from ..projection import project_board_decision, verification_to_dict
from .prompts import format_stage1, format_stage2, format_stage3, format_stage4, format_standalone_secretary_brief
from .shortcut import ShortcutType, detect_shortcut

logger = logging.getLogger(__name__)

_LEDGER_DB_PATH = None  # Use default; tests can patch this
MAX_TOOL_RESULT_CHARS = 8000


class BoardDeliberationError(Exception):
    """Raised when a deliberation cannot complete (e.g. too few members responded)."""
    pass


@dataclass
class ToolBudget:
    tool_calls_max: int
    wall_seconds_max: int
    per_call_timeout: float
    open_browser_max: int
    web_search_max: int
    fetch_url_max: int
    ask_user_max: int
    tool_calls_used: int = 0
    wall_seconds_used: float = 0.0
    sub_used: dict[str, int] = field(default_factory=dict)

    SUB_CAPS_BY_TOOL = {
        "web_search": "web_search_max",
        "open_browser": "open_browser_max",
        "fetch_url": "fetch_url_max",
        "ask_user_clarifying_question": "ask_user_max",
    }

    @classmethod
    def for_mode(cls, mode: str, *, member_role: str = "member") -> "ToolBudget":
        if mode == "fast":
            return cls(0, 60, 240.0, 0, 0, 0, 1 if member_role == "chair" else 0)
        if mode == "standard":
            return cls(3, 180, 240.0, 1, 3, 2,
                        2 if member_role == "chair" else 0)
        if mode == "deep":
            return cls(8, 480, 240.0, 3, 6, 4,
                        3 if member_role == "chair" else 1)
        raise ValueError(f"unknown mode {mode!r}; expected fast|standard|deep")

    def can_call(self, name: str) -> bool:
        if self.tool_calls_used >= self.tool_calls_max:
            return False
        cap_attr = self.SUB_CAPS_BY_TOOL.get(name)
        if cap_attr is None:
            return True
        cap = getattr(self, cap_attr)
        return self.sub_used.get(name, 0) < cap

    def spend(self, name: str, cost_units: float) -> None:
        self.tool_calls_used += 1
        self.sub_used[name] = self.sub_used.get(name, 0) + 1

    def exhausted(self) -> bool:
        return self.tool_calls_used >= self.tool_calls_max


@dataclass
class MemberTurnResult:
    content: str
    tool_calls_made: int
    finish_reason: str | None
    aborted: bool = False
    abort_reason: str | None = None
    evidence_packets: list[str] = field(default_factory=list)


def _budget_filtered_tools(all_tools: list[Tool], budget: ToolBudget) -> list[dict]:
    """Return only the tool schemas the budget still allows."""
    return [t.to_openai_schema() for t in all_tools if budget.can_call(t.name)]


def _tool_call_message(tcs: list[ToolCall], reasoning_content: str | None = None) -> dict:
    """Build the assistant message that records the tool_calls request."""
    msg = {
        "role": "assistant", "content": "",
        "tool_calls": [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.name,
                          "arguments": json.dumps(tc.arguments)}}
            for tc in tcs
        ],
    }
    if reasoning_content:
        msg["reasoning_content"] = reasoning_content
    return msg


class SimpleEvent:
    """Lightweight event for the on_event stream during Phase 1.
    Phase 2 replaces this with the proper Event hierarchy in live.py."""
    def __init__(self, kind: str, *args: Any) -> None:
        self.kind = kind
        self.args = args
    def __repr__(self) -> str:
        return f"Event({self.kind!r}, {self.args!r})"


async def agentic_member_turn(
    *,
    member: BoardMember,
    model: str,
    system_prompt: str,
    initial_user_message: str,
    tools: list[Tool],
    budget: ToolBudget,
    session: object,
    stage: int,
    on_event: Callable[[Any], None],
) -> MemberTurnResult:
    """Run the model in a tool-use loop bounded by `budget`.
    Loop terminates when:
      - LLM returns content with no tool_calls, OR
      - budget is exhausted (one final tool_choice='none' call to write
        the final analysis), OR
      - wall-clock budget is exceeded.
    """
    on_event(SimpleEvent("MemberStart", member.id, stage))
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": initial_user_message}
    ]
    t_start = time.monotonic()

    # Define _exec outside the loop; it captures member, session, on_event via closure
    async def _exec(tc: ToolCall) -> tuple[ToolCall, ToolResult]:
        on_event(SimpleEvent("ToolCall", member.id, tc.name, tc.arguments))
        result = await execute_tool(
            name=tc.name, arguments=tc.arguments,
            session=session, member_id=member.id,
        )
        on_event(SimpleEvent("ToolResult", member.id, tc.name,
                              result.summary, result.cost_units))
        return tc, result

    _iter = 0
    _MAX_ITERS = max(budget.tool_calls_max + 4, 12)

    while True:
        _iter += 1
        if _iter > _MAX_ITERS:
            on_event(SimpleEvent("MemberAborted", member.id, "max_iters_exceeded"))
            return MemberTurnResult(
                content="[Aborted: tool-use loop exceeded max iterations]",
                tool_calls_made=budget.tool_calls_used,
                finish_reason="aborted",
                aborted=True,
                abort_reason="max_iters_exceeded",
            )
        wall = time.monotonic() - t_start
        budget.wall_seconds_used = wall
        budget_tools = _budget_filtered_tools(tools, budget)
        no_more_tools = (
            not budget_tools
            or budget.exhausted()
            or wall >= budget.wall_seconds_max
        )

        on_event(SimpleEvent("MemberThinking", member.id))
        response: LLMResponse = await query_llm(
            model, messages,
            system=system_prompt,
            tools=None if no_more_tools else budget_tools,
            tool_choice="none" if no_more_tools else "auto",
            timeout=budget.per_call_timeout,
        )

        if not response.tool_calls:
            on_event(SimpleEvent("MemberComplete", member.id, response.finish_reason))
            return MemberTurnResult(
                content=response.content or "",
                tool_calls_made=budget.tool_calls_used,
                finish_reason=response.finish_reason,
            )

        # Append assistant tool-call message
        messages.append(_tool_call_message(response.tool_calls, response.reasoning_content))

        # Execute tool calls in parallel
        results = await asyncio.gather(*[_exec(tc) for tc in response.tool_calls])
        for tc, result in results:
            messages.append({
                "role": "tool", "tool_call_id": tc.id,
                "content": result.content_for_model[:MAX_TOOL_RESULT_CHARS],
            })
            budget.spend(tc.name, result.cost_units)


@dataclass
class MemberResponse:
    member_id: str
    stage: int
    content: str
    model: str
    elapsed_seconds: float


@dataclass
class BoardSession:
    """Full record of a board deliberation session."""
    session_id: str
    user_query: str
    stage1_responses: list[MemberResponse] = field(default_factory=list)
    stage2_responses: list[MemberResponse] = field(default_factory=list)
    stage3_synthesis: MemberResponse | None = None
    secretary_briefs: list[MemberResponse] = field(default_factory=list)
    continuation_count: int = 0
    selected_council_ids: list[str] = field(default_factory=list)

    @property
    def secretary_brief(self) -> MemberResponse | None:
        """Latest Secretary brief — alias for `secretary_briefs[-1]` for back-compat."""
        return self.secretary_briefs[-1] if self.secretary_briefs else None

    @secretary_brief.setter
    def secretary_brief(self, value: MemberResponse | None) -> None:
        """Setter retained for back-compat: appends to `secretary_briefs` if non-None.

        New code should use `secretary_briefs.append(...)` directly.
        """
        if value is not None:
            self.secretary_briefs.append(value)
    total_elapsed: float = 0.0
    metrics: SessionMetrics = field(default_factory=SessionMetrics)
    classification: dict | None = None  # query classification info
    participation: list[dict] = field(default_factory=list)
    decision: dict | None = None
    delegation_plan: dict | None = None
    verification: dict | None = None
    memory: dict | None = None
    status: str = "completed"
    intake_cards: list[dict] = field(default_factory=list)
    clarification: dict = field(default_factory=dict)
    structured_output_warnings: list[str] = field(default_factory=list)
    evidence_packets: dict = field(default_factory=dict)
    conversation: dict = field(default_factory=lambda: {
        "messages": [],
        "routing_trace": [],
    })

    def to_dict(self) -> dict:
        def _resp(r: MemberResponse) -> dict:
            return {
                "member_id": r.member_id,
                "stage": r.stage,
                "content": r.content,
                "model": r.model,
                "elapsed_seconds": r.elapsed_seconds,
            }
        result = {
            "session_id": self.session_id,
            "user_query": self.user_query,
            "stage1": [_resp(r) for r in self.stage1_responses],
            "stage2": [_resp(r) for r in self.stage2_responses],
            "stage3": _resp(self.stage3_synthesis) if self.stage3_synthesis else None,
            "secretary_brief": _resp(self.secretary_brief) if self.secretary_brief else None,
            "secretary_briefs": [_resp(b) for b in self.secretary_briefs],
            "continuation_count": self.continuation_count,
            "selected_council_ids": self.selected_council_ids,
            "decision": self.decision,
            "delegation_plan": self.delegation_plan,
            "verification": self.verification,
            "memory": self.memory,
            "status": self.status,
            "intake_cards": self.intake_cards,
            "clarification": self.clarification,
            "structured_output_warnings": self.structured_output_warnings,
            "evidence_packets": self.evidence_packets,
            "conversation": self.conversation,
            "total_elapsed": self.total_elapsed,
            "metrics": self.metrics.summary(),
            "participation": self.participation,
        }
        if self.classification:
            result["classification"] = self.classification
        return result

    def save(self, directory: str = "data/sessions") -> Path:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        filepath = path / f"{self.session_id}.json"
        filepath.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))
        return filepath


def _assign_models(
    members: list[BoardMember],
    *,
    query_type: str | None = None,
    config=None,
) -> dict[str, str]:
    """Assign an LLM model to each board member via override, tuning, or round-robin."""
    models = get_council_models()
    preferences = resolve_model_preferences(query_type=query_type, config=config)
    assignments: dict[str, str] = {}
    for i, member in enumerate(members):
        if member.model_override:
            assignments[member.id] = member.model_override
        elif member.id in preferences:
            assignments[member.id] = preferences[member.id]
        else:
            assignments[member.id] = models[i % len(models)]
    return assignments


def _anonymize_responses(
    responses: list[MemberResponse],
    exclude_member_id: str | None = None,
) -> str:
    """Format responses with anonymous labels (Member A, B, C, ...) for peer review."""
    lines: list[str] = []
    label_idx = 0
    for resp in responses:
        if resp.member_id == exclude_member_id:
            continue
        label = chr(ord("A") + label_idx)
        lines.append(f"### Member {label}")
        lines.append(resp.content)
        lines.append("")
        label_idx += 1
    return "\n".join(lines)


def _format_identified_responses(responses: list[MemberResponse]) -> str:
    """Format responses with real member titles for chairman synthesis."""
    members_by_id = get_members_by_id()
    lines: list[str] = []
    for resp in responses:
        member = members_by_id.get(resp.member_id)
        title = member.title if member else resp.member_id
        role = member.role if member else ""
        lines.append(f"### {title} ({role})")
        lines.append(resp.content)
        lines.append("")
    return "\n".join(lines)


def _minimum_required_responses(total_members: int, max_required: int) -> int:
    """Return the minimum viable response count for a focused route."""
    return max(1, min(max_required, total_members))


def _apply_routing_adjustments(
    member_ids: list[str],
    *,
    query_type: str | None,
    chairman_id: str,
) -> list[str]:
    """Apply Phase D routing suppressions while preserving a viable council."""
    cfg = get_config()
    suppressed = set(resolve_routing_suppressed_member_ids(
        query_type=query_type,
        config=cfg,
    ))
    if not suppressed:
        return member_ids

    filtered = [
        member_id
        for member_id in member_ids
        if member_id == chairman_id or member_id not in suppressed
    ]
    if not any(member_id != chairman_id for member_id in filtered):
        return member_ids
    return filtered


def _build_participation_decisions(
    all_members: list[BoardMember],
    council: list[BoardMember],
    *,
    chairman_id: str,
    classification: dict | None,
    mode_reason: str,
) -> list[dict]:
    """Create an explicit Stage 0 participation record.

    V1 keeps the actual speaking flow deterministic, but records who is
    participating, observing, or abstaining so later versions can make this
    member-declared.
    """
    council_ids = {member.id for member in council}
    required_capabilities = classification.get("required_capabilities", []) if classification else []
    decisions: list[dict] = []
    for member in all_members:
        if member.id == chairman_id:
            mode = "participate"
            reason = "Chair synthesizes the final decision."
            confidence = "high"
        elif member.id == "secretary":
            mode = "participate"
            reason = "Secretary produces executive brief after synthesis."
            confidence = "high"
        elif member.id in council_ids:
            mode = "participate"
            reason = mode_reason
            confidence = "medium"
        else:
            mode = "abstain"
            reason = "Not selected by this route."
            confidence = "medium"
        decisions.append({
            "member_id": member.id,
            "mode": mode,
            "reason": reason,
            "confidence": confidence,
            "triggered_capabilities": required_capabilities if member.id in council_ids else [],
        })
    return decisions


def _should_pause_for_clarification(user_query: str, council: list[BoardMember]) -> bool:
    from server.board.roster import get_clarification_gate, load_roster

    gate = get_clarification_gate()

    words = [w for w in user_query.replace("-", " ").split() if w.strip()]
    if len(words) > gate["max_query_words"]:
        return False

    gating_caps = set(gate["gating_capabilities"])
    if gating_caps:
        roster_members = load_roster().get("members", {})
        has_gating_member = any(
            any(
                cap in gating_caps
                for cap in roster_members.get(member.id, {}).get("capabilities", [])
            )
            for member in council
        )
        if not has_gating_member:
            return False

    ambiguous = set(gate["ambiguous_terms"])
    lower = user_query.lower()
    hits = sum(1 for term in ambiguous if term in lower)
    return hits >= gate["min_terms_present"]


def _build_intake_card(member: BoardMember, user_query: str, *, blocking: bool) -> dict:
    intake = member.intake
    if intake is None:
        # Non-council (e.g., chairperson) path: generic fallback.
        return {
            "member_id": member.id,
            "member_title": member.title,
            "clarifying_question": "What missing fact would change this board member's recommendation?",
            "immediate_concern": "The prompt lacks enough context for a fully accountable decision.",
            "proposed_path": "Name the assumption and verify it before execution.",
            "required_execution_unit": "strategy",
            "confidence": "medium",
            "blocking": blocking,
        }
    return {
        "member_id": member.id,
        "member_title": member.title,
        "clarifying_question": intake.clarifying_question,
        "immediate_concern": intake.immediate_concern,
        "proposed_path": intake.proposed_path,
        "required_execution_unit": intake.required_execution_unit,
        "confidence": "medium",
        "blocking": blocking,
    }


def _format_clarification_context(user_query: str, clarification: dict) -> str:
    answers = clarification.get("answers") or {}
    if not answers:
        return user_query
    lines = [user_query, "", "Clarification answers supplied before deliberation:"]
    if isinstance(answers, dict):
        lines.extend(f"- {key}: {value}" for key, value in answers.items())
    else:
        lines.append(str(answers))
    return "\n".join(lines)


def _wrap_delegation_json(content: str) -> str:
    return f"### Delegation Plan\n```json\n{content.strip()}\n```"


def _format_delegation_prompt(user_query: str, synthesis_content: str) -> str:
    return f"""Create the execution delegation plan for this board decision.

Return ONLY valid JSON. No Markdown. No commentary.

Schema:
{{
  "tasks": [
    {{
      "title": "short task name",
      "objective": "specific outcome",
      "execution_unit_id": "strategy|product|research|engineering|security|operations|finance|legal",
      "manager_agent_id": "strategy_lead|product_lead|research_lead|technical_lead|security_lead|operations_lead|finance_lead|legal_lead",
      "accountable_board_member_id": "chairperson|strategist|product|researcher|critic|architect|builder|guardian|operator",
      "priority": "p0|p1|p2",
      "acceptance_criteria": ["observable completion criterion"],
      "dependencies": [],
      "approval_required": true
    }}
  ]
}}

Use approval_required=true unless a task is purely informational.
Do not claim work has already been executed.
Create at most 4 tasks.

Original request:
{user_query}

Board decision:
{synthesis_content}
"""


def _synthesis_has_actions(content: str) -> bool:
    lower = content.lower()
    return "### next steps" in lower or "### implementation plan" in lower


def _metadata_for_decision(
    decision: dict | None,
    *,
    session: BoardSession,
    chairman: BoardMember,
    council: list[BoardMember],
) -> dict | None:
    if decision is None:
        return None
    participant_titles = [member.title for member in [chairman, *council]]
    enriched = dict(decision)
    enriched.setdefault("prepared_by", chairman.title)
    enriched.setdefault("decision_authority", f"{chairman.title} ({chairman.role})")
    enriched.setdefault("participants", participant_titles)
    enriched.setdefault("decision_date", datetime.now(timezone.utc).isoformat())
    enriched.setdefault("session_id", session.session_id)
    enriched.setdefault("status", session.status)
    enriched.setdefault("assumptions", [])
    enriched.setdefault("accountable_owners", _accountable_owners(enriched))
    return enriched


def _accountable_owners(decision: dict) -> list[str]:
    owners: list[str] = []
    for item in decision.get("next_steps") or []:
        text = str(item)
        if ":" in text:
            owners.append(text.split(":", 1)[0].strip("* "))
    return owners


class BoardOrchestrator:
    """Runs the 3-stage board deliberation."""

    def __init__(
        self,
        *,
        members: list[BoardMember] | None = None,
        chairman_id: str = "chairperson",
        on_stage_start: callable = None,
        on_member_started: callable = None,
        on_member_done: callable = None,
        on_stage_done: callable = None,
        on_intake_card: callable = None,
        on_clarification_required: callable = None,
        on_clarification_answered: callable = None,
        on_structured_output_warning: callable = None,
        on_council_selected: callable = None,
        on_phase: callable = None,
    ):
        all_members = members or get_board_members()
        members_by_id = get_members_by_id()
        self.chairman = members_by_id[chairman_id]
        # Council excludes both chairperson (synthesizes at Stage 3) and
        # secretary (produces executive brief at Stage 4/5)
        _non_deliberating = {chairman_id, "secretary"}
        self.council = [m for m in all_members if m.id not in _non_deliberating]
        self.model_assignments = _assign_models(all_members)
        self.chairman_model = get_chairman_model()
        self.metrics = SessionMetrics()

        # Callbacks for progress reporting
        self._on_stage_start = on_stage_start
        self._on_member_started = on_member_started
        self._on_member_done = on_member_done
        self._on_stage_done = on_stage_done
        self._on_intake_card = on_intake_card
        self._on_clarification_required = on_clarification_required
        self._on_clarification_answered = on_clarification_answered
        self._on_structured_output_warning = on_structured_output_warning
        self._on_council_selected = on_council_selected
        self._on_phase = on_phase
        self._token_budget_query_type: str | None = None
        self._token_budget_complexity: str | None = None
        self._evidence_addenda: dict[str, str] = {}
        self._current_session_id: str | None = None

    def _fire(self, callback, *args):
        if callback:
            callback(*args)

    def _session_id_for_search(self) -> str:
        return getattr(self, "_current_session_id", None) or "anon"

    async def _collect_member_evidence(
        self,
        query: str,
        *,
        query_type: str | None = None,
    ):
        """Fetch web search results and build markdown addenda.

        Layer 1 (expanded coverage):
          - Members with evidence_required=True always get search.
          - When query_type is search-worthy (strategic/product/customer/technical/
            finance/legal), ALL council members receive evidence.

        Layer 2 (intelligent triggering):
          - Search is auto-enabled for query types needing real-time data.
          - Each member gets a role-specific query augmentation for targeted results.

        Returns (addenda, packet_ids).
        """
        from server.execution.web_search import (
            web_search,
            is_query_type_search_worthy,
            _build_role_specific_query,
        )

        auto_all = is_query_type_search_worthy(query_type)
        if not any(getattr(m, "evidence_required", False) for m in self.council) and not auto_all:
            return {}, {}

        addenda: dict[str, str] = {}
        packet_ids: dict[str, str] = {}
        for member in self.council:
            should_search = getattr(member, "evidence_required", False) or auto_all
            if not should_search:
                continue

            # Role-specific query for better results (Layer 2)
            search_query = (
                _build_role_specific_query(
                    base_query=query,
                    member_id=member.id,
                    member_role=member.role,
                )
                if auto_all
                else query
            )

            try:
                result = await web_search(
                    search_query,
                    session_id=self._session_id_for_search(),
                )
            except Exception as exc:
                logger.warning("Evidence retrieval failed for %s: %s", member.id, exc)
                continue

            results = result.get("results") or []
            if not results:
                continue

            lines = ["## Retrieved Evidence"]
            for item in results[:3]:
                title = (item.get("title") or "Untitled").strip()
                url = (item.get("url") or "").strip()
                snippet = (item.get("snippet") or "").strip()
                if len(snippet) > 500:
                    snippet = snippet[:500].rstrip() + "…"
                lines.append(f"- [{title}]({url}) — {snippet}")
            addenda[member.id] = "\n".join(lines)

            packet = result.get("evidence_packet") or {}
            pid = packet.get("id") or packet.get("packet_id")
            if pid:
                packet_ids[member.id] = str(pid)

        return addenda, packet_ids

    def stage0_intake(
        self,
        user_query: str,
        *,
        clarification_answers: dict[str, Any] | None = None,
    ) -> tuple[list[dict], dict]:
        """Create immediate member intake cards before expensive deliberation."""
        self._fire(self._on_stage_start, 0, "Board Intake")
        should_pause = _should_pause_for_clarification(user_query, self.council)
        cards: list[dict] = []
        questions: list[dict] = []
        for member in self.council:
            card = _build_intake_card(member, user_query, blocking=should_pause)
            cards.append(card)
            self._fire(self._on_intake_card, card)
            if card["blocking"]:
                questions.append({
                    "member_id": member.id,
                    "member_title": member.title,
                    "question": card["clarifying_question"],
                })

        answers = clarification_answers or {}
        if questions and not answers:
            clarification = {
                "status": "required",
                "questions": questions,
                "answers": {},
            }
            self._fire(self._on_clarification_required, clarification)
        elif questions:
            clarification = {
                "status": "answered",
                "questions": questions,
                "answers": answers,
            }
            self._fire(self._on_clarification_answered, clarification)
        else:
            clarification = {
                "status": "not_required",
                "questions": [],
                "answers": answers,
            }
        self._fire(self._on_stage_done, 0, cards)
        return cards, clarification

    def _record_metrics(self, member_id: str, stage: int, llm_resp: LLMResponse) -> None:
        """Record metrics from an LLM response."""
        self.metrics.record(CallMetrics(
            member_id=member_id,
            stage=stage,
            model=llm_resp.model,
            input_tokens=llm_resp.input_tokens,
            output_tokens=llm_resp.output_tokens,
            latency_seconds=llm_resp.latency_seconds,
            finish_reason=llm_resp.finish_reason,
            response_id=llm_resp.response_id,
        ))

    async def _query_member(
        self,
        member: BoardMember,
        prompt: str,
        stage: int,
        *,
        query_type: str | None = None,
        complexity: str | None = None,
    ) -> MemberResponse:
        model = self.model_assignments.get(member.id, get_council_models()[0])
        messages = [{"role": "user", "content": prompt}]

        cfg = get_config()
        max_tokens = resolve_stage_max_tokens(
            stage,
            query_type=query_type if query_type is not None else self._token_budget_query_type,
            complexity=complexity if complexity is not None else self._token_budget_complexity,
            config=cfg,
        )

        system_prompt = member.system_prompt
        addendum = getattr(self, "_evidence_addenda", {}).get(member.id)
        if stage == 1 and addendum:
            system_prompt = f"{member.system_prompt}\n\n{addendum}"

        self._fire(self._on_member_started, stage, member)

        llm_resp = await query_llm(
            model,
            messages,
            system=system_prompt,
            max_tokens=max_tokens,
        )

        self._record_metrics(member.id, stage, llm_resp)

        resp = MemberResponse(
            member_id=member.id,
            stage=stage,
            content=llm_resp.content,
            model=llm_resp.model,  # reflects actual model used (may differ if fallback)
            elapsed_seconds=round(llm_resp.latency_seconds, 2),
        )
        self._fire(self._on_member_done, stage, member, resp)
        return resp

    # ── STAGE 1: Independent Analysis ──────────────────────────────────

    async def stage1(
        self,
        user_query: str,
        *,
        query_type: str | None = None,
        complexity: str | None = None,
    ) -> list[MemberResponse]:
        self._fire(self._on_stage_start, 1, "Independent Analysis")
        self._token_budget_query_type = query_type
        self._token_budget_complexity = complexity

        tasks = []
        for member in self.council:
            prompt = format_stage1(role=member.role, user_query=user_query)
            tasks.append(self._query_member(member, prompt, stage=1))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions, log warnings, fire failure callbacks
        responses: list[MemberResponse] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                member = self.council[i]
                logger.warning(
                    "Stage 1: member '%s' failed: %s", member.id, result
                )
                self._fire(self._on_member_done, 1, member, None, str(result))
            else:
                responses.append(result)

        minimum_required = _minimum_required_responses(
            len(self.council),
            get_config().min_stage1_responses,
        )
        if len(responses) < minimum_required:
            raise BoardDeliberationError(
                f"Stage 1 failed: only {len(responses)}/{len(self.council)} members responded "
                f"(minimum: {minimum_required})"
            )

        self._fire(self._on_stage_done, 1, responses)
        return responses

    # ── STAGE 2: Peer Review ───────────────────────────────────────────

    async def stage2(
        self,
        user_query: str,
        stage1_responses: list[MemberResponse],
        *,
        query_type: str | None = None,
        complexity: str | None = None,
    ) -> list[MemberResponse]:
        self._fire(self._on_stage_start, 2, "Peer Review & Challenge")
        self._token_budget_query_type = query_type
        self._token_budget_complexity = complexity

        if len(self.council) <= 1:
            logger.info("Stage 2 skipped: peer review requires at least 2 council members.")
            self._fire(self._on_stage_done, 2, [])
            return []

        # Compact Stage 1 responses before passing to peer review
        compacted_s1 = compact_stage1_responses(stage1_responses, query_type=query_type)

        tasks = []
        for member in self.council:
            anonymized = _anonymize_responses(compacted_s1, exclude_member_id=member.id)
            stage2_extra = member.stage2_behavior or member.stage2_addendum
            prompt = format_stage2(
                role=member.role,
                user_query=user_query,
                anonymized_responses=anonymized,
                stage2_behavior=stage2_extra,
            )
            tasks.append(self._query_member(member, prompt, stage=2))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions, log warnings, fire failure callbacks
        responses: list[MemberResponse] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                member = self.council[i]
                logger.warning(
                    "Stage 2: member '%s' failed: %s", member.id, result
                )
                self._fire(self._on_member_done, 2, member, None, str(result))
            else:
                responses.append(result)

        minimum_required = _minimum_required_responses(
            len(self.council),
            get_config().min_stage2_responses,
        )
        if len(responses) < minimum_required:
            raise BoardDeliberationError(
                f"Stage 2 failed: only {len(responses)}/{len(self.council)} members responded "
                f"(minimum: {minimum_required})"
            )

        self._fire(self._on_stage_done, 2, responses)
        return responses

    # ── STAGE 3: Chairman Synthesis ────────────────────────────────────

    async def stage3(
        self,
        user_query: str,
        stage1_responses: list[MemberResponse],
        stage2_responses: list[MemberResponse],
        *,
        sotb: str = "",
        query_type: str | None = None,
        complexity: str | None = None,
    ) -> MemberResponse:
        self._fire(self._on_stage_start, 3, "Chairman Synthesis")

        # Compact inter-stage context before passing to chairman. Raw responses
        # remain in the saved session JSON for audit.
        compacted_s1 = compact_stage1_responses(stage1_responses, query_type=query_type)
        compacted_s2 = compact_stage2_responses(stage2_responses)

        prompt = format_stage3(
            user_query=user_query,
            stage1_responses=_format_identified_responses(compacted_s1),
            stage2_responses=_format_identified_responses(compacted_s2),
            sotb=sotb,
        )

        messages = [{"role": "user", "content": prompt}]
        cfg = get_config()
        self._fire(self._on_member_started, 3, self.chairman)
        llm_resp = await query_llm(
            self.chairman_model, messages,
            system=self.chairman.system_prompt,
            max_tokens=resolve_stage_max_tokens(
                3,
                query_type=query_type,
                complexity=complexity,
                config=cfg,
            ),
        )

        self._record_metrics(self.chairman.id, 3, llm_resp)

        synthesis = MemberResponse(
            member_id=self.chairman.id,
            stage=3,
            content=llm_resp.content,
            model=self.chairman_model,
            elapsed_seconds=round(llm_resp.latency_seconds, 2),
        )
        self._fire(self._on_member_done, 3, self.chairman, synthesis)
        self._fire(self._on_stage_done, 3, synthesis)
        return synthesis

    # ── STAGE 4: Secretary Executive Brief ──────────────────────────────

    def _get_secretary(self) -> BoardMember | None:
        """Return the secretary board member if loaded, else None."""
        return get_members_by_id().get("secretary")

    async def stage4_secretary_brief(
        self,
        user_query: str,
        stage1_responses: list[MemberResponse],
        stage2_responses: list[MemberResponse],
        stage3_synthesis: MemberResponse,
        *,
        query_type: str | None = None,
        complexity: str | None = None,
    ) -> MemberResponse | None:
        """Produce a concise executive brief from all deliberation stages.

        The secretary consolidates opinions, flags conflicts, attributes claims
        to their sources, and produces a CEO-friendly structured brief.
        Returns None if secretary member is not available.
        """
        secretary = self._get_secretary()
        if secretary is None:
            logger.info("Stage 4 skipped: secretary member not found.")
            return None

        self._fire(self._on_stage_start, 4, "Secretary Executive Brief")

        compacted_s1 = compact_stage1_responses(stage1_responses, query_type=query_type)
        compacted_s2 = compact_stage2_responses(stage2_responses)

        prompt = format_stage4(
            user_query=user_query,
            stage1_responses=_format_identified_responses(compacted_s1),
            stage2_responses=_format_identified_responses(compacted_s2),
            stage3_synthesis=stage3_synthesis.content,
        )

        messages = [{"role": "user", "content": prompt}]
        cfg = get_config()

        # Use council model assignment for secretary (or chairman model as fallback)
        secretary_model = self.model_assignments.get("secretary", self.chairman_model)

        self._fire(self._on_member_started, 4, secretary)
        llm_resp = await query_llm(
            secretary_model, messages,
            system=secretary.system_prompt,
            max_tokens=resolve_stage_max_tokens(
                4,
                query_type=query_type,
                complexity=complexity,
                config=cfg,
            ),
        )

        self._record_metrics(secretary.id, 4, llm_resp)

        brief = MemberResponse(
            member_id=secretary.id,
            stage=4,
            content=llm_resp.content,
            model=secretary_model,
            elapsed_seconds=round(llm_resp.latency_seconds, 2),
        )
        self._fire(self._on_member_done, 4, secretary, brief)
        self._fire(self._on_stage_done, 4, brief)
        return brief

    async def run_secretary_shortcut(
        self,
        user_query: str,
        *,
        session_id: str | None = None,
    ) -> BoardSession:
        """Produce a secretary executive brief **without** running Stages 1–3.

        This is the short-circuit path triggered when the CEO's query matches a
        shortcut such as ``secretary summarize`` or ``/brief``.  If a prior
        session is referenced (``source_session_id``) we load its deliberation
        data and feed it into the normal Stage 4 prompt; otherwise we use the
        standalone brief template that asks the secretary to analyse from
        first principles.
        """
        sid = session_id or f"board_{int(time.time())}"
        session = BoardSession(session_id=sid, user_query=user_query)
        session.metrics = self.metrics
        session.status = "completed"

        secretary = self._get_secretary()
        if secretary is None:
            logger.warning("Secretary shortcut requested but secretary member not available.")
            session.status = "failed"
            return session

        # Try to load a previous session's data if referenced
        from .shortcut import detect_shortcut
        detection = detect_shortcut(user_query)
        source_data = None

        if detection and detection.source_session_id:
            source_data = self._load_session_for_brief(detection.source_session_id)
        else:
            # Auto-discover most recent completed session
            source_data = self._load_most_recent_session()

        self._fire(self._on_phase, "secretary", "Secretary producing executive brief (shortcut mode).")

        if source_data:
            # Normal Stage 4 path with loaded context
            s1_responses = [
                MemberResponse(**r) for r in source_data.get("stage1", [])
                if isinstance(r, dict)
            ]
            s2_responses = [
                MemberResponse(**r) for r in source_data.get("stage2", [])
                if isinstance(r, dict)
            ]
            s3_raw = source_data.get("stage3")
            s3_synthesis = (
                MemberResponse(**s3_raw) if isinstance(s3_raw, dict) else None
            )

            if s3_synthesis:
                brief = await self.stage4_secretary_brief(
                    user_query,
                    s1_responses,
                    s2_responses,
                    s3_synthesis,
                )
                session.secretary_brief = brief
            else:
                # Has stage 1/2 but no synthesis — fall back to standalone
                brief = await self._standalone_secretary_call(user_query, secretary)
                session.secretary_brief = brief
        else:
            # No prior session — standalone analysis
            brief = await self._standalone_secretary_call(user_query, secretary)
            session.secretary_brief = brief

        session.total_elapsed = 0.0  # not meaningful for shortcut
        session.save()
        return session

    def _load_session_for_brief(self, target_sid: str) -> dict | None:
        """Load a persisted session JSON by ID."""
        from pathlib import Path
        for dirname in ("data/sessions", "data/conversations"):
            p = Path(dirname) / f"{target_sid}.json"
            if p.exists():
                import json
                try:
                    return json.loads(p.read_text())
                except Exception:
                    logger.warning("Failed to read session file %s", p)
                    return None
        return None

    def _load_most_recent_session(self) -> dict | None:
        """Find and load the most recent completed session with stage data."""
        from pathlib import Path
        import json

        best: tuple[float, dict | None] = (-1.0, None)
        for dirname in ("data/sessions", "data/conversations"):
            d = Path(dirname)
            if not d.is_dir():
                continue
            for f in sorted(d.glob("board_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                if f.stat().st_mtime <= best[0]:
                    break
                try:
                    data = json.loads(f.read_text())
                    # Must have at least some stage data or a decision
                    if data.get("stage1") or data.get("stage3") or data.get("decision"):
                        best = (f.stat().st_mtime, data)
                        break  # first (newest) hit is enough
                except Exception:
                    continue
        return best[1]

    async def _standalone_secretary_call(
        self,
        user_query: str,
        secretary: BoardMember,
    ) -> MemberResponse:
        """Call the secretary with the standalone (no-prior-context) prompt."""
        self._fire(self._on_stage_start, 4, "Secretary Executive Brief")
        prompt = format_standalone_secretary_brief(user_query=user_query)
        messages = [{"role": "user", "content": prompt}]

        cfg = get_config()
        secretary_model = self.model_assignments.get("secretary", self.chairman_model)

        self._fire(self._on_member_started, 4, secretary)
        llm_resp = await query_llm(
            secretary_model,
            messages,
            system=secretary.system_prompt,
            max_tokens=resolve_stage_max_tokens(4, config=cfg),
        )
        self._record_metrics(secretary.id, 4, llm_resp)

        brief = MemberResponse(
            member_id=secretary.id,
            stage=4,
            content=llm_resp.content,
            model=secretary_model,
            elapsed_seconds=round(llm_resp.latency_seconds, 2),
        )
        self._fire(self._on_member_done, 4, secretary, brief)
        self._fire(self._on_stage_done, 4, [brief])
        return brief

    async def build_delegation_plan(
        self,
        *,
        user_query: str,
        synthesis_content: str,
        session_id: str,
        query_type: str | None = None,
        complexity: str | None = None,
    ) -> dict[str, Any]:
        """Generate delegation JSON in a dedicated structured pass."""
        prompt = _format_delegation_prompt(user_query, synthesis_content)
        messages = [{"role": "user", "content": prompt}]
        cfg = get_config()
        first = await query_llm(
            self.chairman_model,
            messages,
            system=(
                "You convert approved board decisions into execution tasks. "
                "Return valid JSON only."
            ),
            temperature=0.1,
            max_tokens=max(1200, min(resolve_stage_max_tokens(
                3,
                query_type=query_type,
                complexity=complexity,
                config=cfg,
            ), 3000)),
        )
        self._record_metrics("delegation_planner", 3, first)
        plan = parse_delegation_plan(
            _wrap_delegation_json(first.content),
            session_id=session_id,
        )
        if plan.get("tasks") and not plan.get("structured_output_failed"):
            return plan

        warning = "Delegation JSON parse failed; retrying once with repair prompt."
        plan.setdefault("warnings", []).append(warning)
        self._fire(self._on_structured_output_warning, warning)
        repair = await query_llm(
            self.chairman_model,
            [
                {"role": "user", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        "The previous response did not parse as the required JSON. "
                        "Repair it now. Return only a valid JSON object with a tasks array.\n\n"
                        f"Previous response:\n{first.content}"
                    ),
                },
            ],
            system=(
                "You repair malformed delegation JSON. Return valid JSON only."
            ),
            temperature=0.0,
            max_tokens=3000,
        )
        self._record_metrics("delegation_planner", 3, repair)
        repaired = parse_delegation_plan(
            _wrap_delegation_json(repair.content),
            session_id=session_id,
        )
        repaired.setdefault("warnings", [])
        repaired["warnings"] = [*plan.get("warnings", []), *repaired["warnings"]]
        if first.finish_reason == "length" or repair.finish_reason == "length":
            repaired["truncated"] = True
            repaired["structured_output_failed"] = not bool(repaired.get("tasks"))
        return repaired

    # ── Full Deliberation ──────────────────────────────────────────────

    async def deliberate(
        self,
        user_query: str,
        *,
        member_ids: list[str] | None = None,
        skip_classify: bool = False,
        verify: bool = False,
        session_id: str | None = None,
        clarification_answers: dict[str, Any] | None = None,
    ) -> BoardSession:
        """Run the full 3-stage board deliberation.

        Parameters
        ----------
        user_query : str
            The question to deliberate on.
        member_ids : list[str] | None
            If provided, only these members participate (manual override).
        skip_classify : bool
            If True, skip the classifier and use the full board.
        verify : bool
            If True, run Stage 4 verification on the chairman synthesis.
        session_id : str | None
            Optional session identifier.
        """
        session_id = session_id or f"board_{int(time.time())}"
        session = BoardSession(session_id=session_id, user_query=user_query)
        session.metrics = self.metrics

        # ── Shortcut detection  (intent-based routing BEFORE full pipeline) ──
        shortcut = detect_shortcut(user_query)
        if shortcut is not None:
            logger.info(
                "Shortcut detected: %s (target=%s, confidence=%.2f)",
                shortcut.type.value, shortcut.target_member_id, shortcut.confidence,
            )
            self._fire(self._on_phase, shortcut.type.value, f"{shortcut.display_label} — short-circuiting to {shortcut.target_member_id}.")
            self._fire(
                self._on_council_selected,
                [shortcut.target_member_id],
                self.chairman.id,
            )

            if shortcut.type == ShortcutType.SECRETARY_BRIEF:
                return await self.run_secretary_shortcut(
                    user_query,
                    session_id=session_id,
                )
            # Future shortcut types can be added here.

        # ── Classification / member selection ─────────────────────────────
        all_members = get_board_members()
        if member_ids:
            # Manual override — use only the specified members
            self.council = [m for m in all_members if m.id in member_ids and m.id != self.chairman.id]
            self.model_assignments = _assign_models(self.council + [self.chairman])
            logger.info("Manual member override. Selected: %s", [m.id for m in self.council])
        elif not skip_classify:
            from .classifier import classify_query

            classification = await classify_query(user_query)
            relevant_member_ids = _apply_routing_adjustments(
                classification.relevant_member_ids,
                query_type=classification.query_type,
                chairman_id=self.chairman.id,
            )
            self.council = [
                m for m in all_members
                if m.id in relevant_member_ids and m.id != self.chairman.id
            ]
            self.model_assignments = _assign_models(
                self.council + [self.chairman],
                query_type=classification.query_type,
                config=get_config(),
            )
            session.classification = {
                "query_type": classification.query_type,
                "complexity": classification.complexity,
                "relevant_member_ids": relevant_member_ids,
                "reasoning": classification.reasoning,
                "required_capabilities": classification.required_capabilities or [],
                "unavailable_capabilities": classification.unavailable_capabilities or [],
                "stage_profile": classification.stage_profile,
                "role_gap_memo": classification.role_gap_memo,
            }
            logger.info(
                "Query classified as '%s' (%s). Selected: %s",
                classification.query_type,
                classification.complexity,
                [m.id for m in self.council],
            )
        # else: skip_classify=True — use the full council set from __init__

        session.participation = _build_participation_decisions(
            all_members,
            self.council,
            chairman_id=self.chairman.id,
            classification=session.classification,
            mode_reason="Selected by manual scope." if member_ids else "Selected by capability routing.",
        )

        self._fire(
            self._on_council_selected,
            [m.id for m in self.council],
            self.chairman.id,
        )

        t0 = time.monotonic()

        if not skip_classify:
            session.intake_cards, session.clarification = self.stage0_intake(
                user_query,
                clarification_answers=clarification_answers,
            )
            if session.clarification.get("status") == "required":
                session.status = "clarification_required"
                session.decision = _metadata_for_decision(
                    project_board_decision(
                        "### Executive Summary\n"
                        "The board requires clarification before issuing a final decision.\n\n"
                        "### Next Steps\n"
                        "- CEO: Answer the clarification questions and resume the board session."
                    ),
                    session=session,
                    chairman=self.chairman,
                    council=self.council,
                )
                session.total_elapsed = round(time.monotonic() - t0, 2)
                session.save()
                try:
                    _record_to_ledger(session, config_version=get_config().version, db_path=_LEDGER_DB_PATH)
                except Exception:
                    logger.warning("Failed to record clarification session to harness ledger", exc_info=True)
                return session

        effective_query = _format_clarification_context(user_query, session.clarification)

        # Capture session id for the duration of this run so the evidence hook
        # can key the web-search rate limiter per-session.
        self._current_session_id = session_id

        # Extract query_type early for evidence auto-trigger (Layer 2)
        _evidence_query_type: str | None = None
        if session.classification:
            _evidence_query_type = session.classification.get("query_type")

        evidence_addenda, evidence_packet_ids = await self._collect_member_evidence(
            effective_query,
            query_type=_evidence_query_type,
        )
        self._evidence_addenda = evidence_addenda
        session.evidence_packets = evidence_packet_ids

        # Stage 1: All members analyze independently (parallel)
        query_type = None
        complexity = None
        if session.classification:
            query_type = session.classification.get("query_type")
            complexity = session.classification.get("complexity")

        session.stage1_responses = await self.stage1(
            effective_query,
            query_type=query_type,
            complexity=complexity,
        )

        # Record Stage 1 JSON parse warnings
        _, _s1_warnings = compact_stage1_with_warnings(
            session.stage1_responses,
            query_type=query_type,
            config=get_config(),
        )
        session.structured_output_warnings.extend(_s1_warnings)

        # Stage 2: Peer review with anonymized responses (parallel)
        session.stage2_responses = await self.stage2(
            effective_query,
            session.stage1_responses,
            query_type=query_type,
            complexity=complexity,
        )

        # Record Stage 2 JSON parse warnings
        _, _s2_warnings = compact_stage2_with_warnings(session.stage2_responses)
        session.structured_output_warnings.extend(_s2_warnings)

        # Read institutional memory before synthesis
        sotb = read_sotb()

        # Stage 3: Chairman synthesizes everything (with SOTB context)
        session.stage3_synthesis = await self.stage3(
            effective_query, session.stage1_responses, session.stage2_responses,
            sotb=sotb,
            query_type=query_type,
            complexity=complexity,
        )

        # Stage 4: Verification (opt-in)
        if verify and session.stage3_synthesis:
            self._fire(self._on_phase, "verifying", "Quality gate auditing the chair synthesis.")
            from .verification import verify_synthesis

            # Get compacted stage 2 for verification context
            compacted_s2, _s2v_warnings = compact_stage2_with_warnings(session.stage2_responses)
            session.structured_output_warnings.extend(_s2v_warnings)
            compacted_s2_text = "\n".join(r.content for r in compacted_s2)

            result = await verify_synthesis(
                synthesis=session.stage3_synthesis.content,
                stage2_compacted=compacted_s2_text,
                user_query=effective_query,
                query_type=query_type,
            )

            logger.info("Verification score: %d/10 (passed: %s)", result.score, result.passed)
            session.verification = verification_to_dict(result)

            # If failed, try one revision
            if not result.passed:
                logger.info("Verification failed. Requesting chairman revision...")
                revision_prompt = (
                    f"Your previous synthesis scored {result.score}/10. "
                    f"Deficiencies found:\n"
                    + "\n".join(f"- {d}" for d in result.deficiencies)
                    + "\n\nPlease revise your synthesis to address these issues. "
                    "Keep the same Board Decision format."
                )

                revision_resp = await query_llm(
                    self.chairman_model,
                    messages=[
                        {"role": "user", "content": session.stage3_synthesis.content},
                        {"role": "user", "content": revision_prompt},
                    ],
                    system=self.chairman.system_prompt,
                    max_tokens=get_config().revision_max_tokens,
                )

                session.stage3_synthesis = MemberResponse(
                    member_id=self.chairman.id,
                    stage=3,
                    content=revision_resp.content,
                    model=self.chairman_model,
                    elapsed_seconds=round(revision_resp.latency_seconds, 2),
                )
                self._record_metrics(self.chairman.id, 3, revision_resp)

                # Re-verify (but don't loop)
                result = await verify_synthesis(
                    synthesis=session.stage3_synthesis.content,
                    stage2_compacted=compacted_s2_text,
                    user_query=effective_query,
                    query_type=query_type,
                )
                logger.info("Revision score: %d/10 (passed: %s)", result.score, result.passed)
                session.verification = verification_to_dict(result)

        # Stage 5: Secretary Executive Brief
        if session.stage3_synthesis:
            self._fire(self._on_phase, "secretary", "Secretary producing executive brief for CEO.")
            session.secretary_brief = await self.stage4_secretary_brief(
                effective_query,
                session.stage1_responses,
                session.stage2_responses,
                session.stage3_synthesis,
                query_type=query_type,
                complexity=complexity,
            )

        if session.stage3_synthesis:
            session.decision = _metadata_for_decision(
                project_board_decision(session.stage3_synthesis.content),
                session=session,
                chairman=self.chairman,
                council=self.council,
            )
            if _synthesis_has_actions(session.stage3_synthesis.content):
                self._fire(self._on_phase, "delegation", "Chair drafting the execution delegation plan.")
                session.delegation_plan = await self.build_delegation_plan(
                    user_query=effective_query,
                    synthesis_content=session.stage3_synthesis.content,
                    session_id=session_id,
                    query_type=query_type,
                    complexity=complexity,
                )
            else:
                session.delegation_plan = {
                    "session_id": session_id,
                    "tasks": [],
                    "warnings": ["No delegation-worthy action section found in chair synthesis."],
                    "requires_approval": True,
                    "structured_output_failed": False,
                    "truncated": False,
                }
            for warning in session.delegation_plan.get("warnings", []):
                if "parse" in warning.lower() or session.delegation_plan.get("structured_output_failed"):
                    session.structured_output_warnings.append(warning)
                    self._fire(self._on_structured_output_warning, warning)
            self._fire(self._on_phase, "memory", "Proposing SOTB memory update for CEO approval.")
            session.memory = propose_memory_update(
                session.stage3_synthesis.content,
                session_id=session_id,
            )
            if session.memory.get("proposed_sotb_update"):
                logger.info("SOTB update proposed for session %s; awaiting approval", session_id)

        self._fire(self._on_phase, "finalizing", "Saving session and updating the learning ledger.")
        session.total_elapsed = round(time.monotonic() - t0, 2)
        session.save()

        if session.delegation_plan:
            try:
                record_delegation_plan(session.delegation_plan, db_path=_LEDGER_DB_PATH)
            except Exception:
                logger.warning("Failed to record delegation plan", exc_info=True)

        # Record to harness ledger
        try:
            _record_to_ledger(session, config_version=get_config().version, db_path=_LEDGER_DB_PATH)
        except Exception:
            logger.warning("Failed to record session to harness ledger", exc_info=True)

        return session
