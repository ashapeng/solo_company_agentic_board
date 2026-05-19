"""Live, turn-routed board conversation runtime."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from server.harness.config import get_config, resolve_stage_max_tokens
from server.harness.ledger import record_session as _record_to_ledger
from server.memory.review import propose_memory_update

from ..config import (
    BoardMember,
    get_board_members,
    get_chairman_model,
    get_members_by_id,
)
from ..llm import LLMStreamChunk, query_llm_stream
from ..metrics import CallMetrics, SessionMetrics
from ..projection import project_board_decision
from .orchestrator import (
    BoardSession,
    MemberResponse,
    _assign_models,
    _build_participation_decisions,
    _metadata_for_decision,
)
from .prompts import format_live_secretary_brief
from .shortcut import ShortcutType, detect_shortcut

logger = logging.getLogger(__name__)

_LEDGER_DB_PATH = None
_LENGTH_FINISH_REASONS = {"length", "max_tokens", "max_output_tokens"}

MEMBER_ORDER = [
    "strategist",
    "product",
    "researcher",
    "critic",
    "architect",
    "builder",
    "guardian",
    "operator",
]

QUERY_TYPE_OPENERS = {
    "strategic": "strategist",
    "product": "product",
    "customer": "researcher",
    "technical": "architect",
    "security": "guardian",
    "operational": "operator",
    "finance": "strategist",
    "legal": "critic",
    "full-board": "strategist",
}

TRIGGER_RULES: list[tuple[str, str, tuple[str, ...], str]] = [
    (
        "customer_research",
        "researcher",
        ("customer research", "customer", "interview", "persona", "pain", "observed behavior", "voice of customer"),
        "Customer evidence was requested, so the Customer Researcher should respond next.",
    ),
    (
        "product_strategy",
        "product",
        ("mvp", "feature", "product", "scope", "value proposition", "pmf"),
        "The thread moved into product scope and prioritization.",
    ),
    (
        "technical_feasibility",
        "architect",
        ("technical", "architecture", "integrat", "prototype", "build vs buy", "data pipeline"),
        "The thread raised technical feasibility questions.",
    ),
    (
        "risk_challenge",
        "critic",
        ("risk", "fatal flaw", "assumption", "premortem", "failure mode", "unverified"),
        "The thread needs explicit assumption pressure and dissent.",
    ),
    (
        "execution_feasibility",
        "builder",
        ("build", "ship", "experiment", "validation", "implementation", "concierge"),
        "The thread needs an execution and validation path.",
    ),
    (
        "security_review",
        "guardian",
        ("privacy", "security", "threat", "compliance", "regulated", "attack"),
        "The thread raised privacy, security, or compliance implications.",
    ),
    (
        "operations",
        "operator",
        ("deploy", "monitor", "operations", "incident", "runbook", "release"),
        "The thread raised operational readiness concerns.",
    ),
    (
        "market_strategy",
        "strategist",
        ("market", "segment", "competition", "channel", "go-to-market", "positioning"),
        "The thread needs market strategy framing.",
    ),
]


@dataclass
class ConversationMessage:
    id: str
    turn_index: int
    member_id: str
    member_title: str
    role: str
    content: str
    reply_to_message_id: str | None = None
    model: str | None = None
    elapsed_seconds: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None
    simulated_stream: bool = False
    created_at: str = ""
    speaker: str = "agent"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return {key: value for key, value in payload.items() if value is not None}


@dataclass
class TurnDecision:
    member_id: str | None
    trigger: str
    routing_reason: str
    reply_to_message_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def route_next_speaker(
    council: list[BoardMember],
    *,
    chairperson: BoardMember,
    messages: list[ConversationMessage],
    used_member_ids: set[str],
    turn_index: int,
    max_turns: int,
) -> TurnDecision:
    """Choose the next speaker from the latest message and unused capabilities."""
    if turn_index > max_turns:
        return TurnDecision(
            member_id=None,
            trigger="awaiting_ceo_decision",
            routing_reason="The live discussion reached the turn budget; the CEO should make the call.",
            reply_to_message_id=messages[-1].id if messages else None,
        )

    available = {
        member.id: member
        for member in council
        if member.id not in used_member_ids
    }
    if not available:
        return TurnDecision(
            member_id=None,
            trigger="awaiting_ceo_decision",
            routing_reason="Every routed council member has spoken; the CEO should make the call.",
            reply_to_message_id=messages[-1].id if messages else None,
        )

    latest = (messages[-1].content if messages else "").lower()
    for trigger, member_id, keywords, reason in TRIGGER_RULES:
        if member_id in available and any(keyword in latest for keyword in keywords):
            return TurnDecision(
                member_id=member_id,
                trigger=trigger,
                routing_reason=reason,
                reply_to_message_id=messages[-1].id if messages else None,
            )

    for member_id in MEMBER_ORDER:
        if member_id in available:
            return TurnDecision(
                member_id=member_id,
                trigger="unused_perspective",
                routing_reason="No stronger trigger was detected, so the next unused routed perspective speaks.",
                reply_to_message_id=messages[-1].id if messages else None,
            )

    member_id = next(iter(available))
    return TurnDecision(
        member_id=member_id,
        trigger="unused_perspective",
        routing_reason="A routed member has not spoken yet.",
        reply_to_message_id=messages[-1].id if messages else None,
    )


class LiveBoardConversation:
    """Runs an adaptive, sequential board conversation with streamed messages."""

    def __init__(
        self,
        *,
        members: list[BoardMember] | None = None,
        chairman_id: str = "chairperson",
        on_event: Callable[[dict[str, Any]], None] | None = None,
        max_turns: int | None = None,
    ) -> None:
        all_members = members or get_board_members()
        members_by_id = get_members_by_id()
        self.chairperson = members_by_id[chairman_id]
        self.all_members = all_members
        self.council = [member for member in all_members if member.id != chairman_id]
        self.model_assignments = _assign_models([*self.council, self.chairperson])
        self.chairman_model = get_chairman_model()
        self.metrics = SessionMetrics()
        self.on_event = on_event
        self.max_turns = max_turns or int(os.getenv("AGENTIC_BOARD_LIVE_MAX_TURNS", "5"))
        self.max_continuations = _positive_int_env("AGENTIC_BOARD_LIVE_MAX_CONTINUATIONS") or 2
        self._current_round = 0

    def _emit(self, event: dict[str, Any]) -> None:
        if self.on_event:
            self.on_event(event)

    async def discuss(
        self,
        user_query: str,
        *,
        member_ids: list[str] | None = None,
        skip_classify: bool = False,
        verify: bool = False,  # kept for endpoint symmetry; live verification is deferred
        session_id: str | None = None,
        initiative_id: str | None = None,
        initiative_mode: str = "ad_hoc",
        clarification_answers: dict[str, Any] | None = None,  # reserved for parity
        existing_session: BoardSession | None = None,
    ) -> BoardSession:
        del verify, clarification_answers

        if existing_session is not None:
            session = existing_session
            session_id = session.session_id
            if not getattr(session, "initiative_id", None) and initiative_id:
                session.initiative_id = initiative_id
            if (
                getattr(session, "initiative_mode", "ad_hoc") == "ad_hoc"
                and initiative_mode != "ad_hoc"
            ):
                session.initiative_mode = initiative_mode
            # Cap check before doing any work.
            if session.continuation_count >= self.max_continuations:
                self._emit({
                    "event": "meeting_capped",
                    "session_id": session_id,
                    "continuation_count": session.continuation_count,
                    "max_continuations": self.max_continuations,
                    "message": "Continuation cap reached. Adjourn to finalize.",
                })
                return session
            session.continuation_count += 1
            session.status = "running"
            self._current_round = session.continuation_count
            # Append the new CEO message to the conversation.
            session.conversation["messages"].append({
                "id": f"user_{len(session.conversation['messages'])}",
                "turn_index": len(session.conversation["messages"]),
                "member_id": self.chairperson.id,
                "member_title": "CEO / Chairperson",
                "role": "CEO",
                "speaker": "user",
                "content": user_query,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        else:
            session_id = session_id or f"board_{int(time.time())}"
            session = BoardSession(
                session_id=session_id,
                user_query=user_query,
                initiative_id=initiative_id,
                initiative_mode=initiative_mode,
            )
            session.metrics = self.metrics
            session.status = "running"
            self._current_round = 0
        self.metrics = session.metrics
        t0 = time.monotonic()
        response_language = detect_response_language(user_query)

        # ── Shortcut detection  (short-circuit BEFORE full pipeline) ────────
        shortcut = detect_shortcut(user_query)
        if shortcut is not None:
            logger.info(
                "Live shortcut detected: %s (target=%s)",
                shortcut.type.value, shortcut.target_member_id,
            )
            self._emit({"event": "phase_change", "phase": shortcut.type.value, "message": f"{shortcut.display_label} — short-circuiting."})
            self._emit({"event": "council_selected", "member_ids": [shortcut.target_member_id], "chairman_id": self.chairperson.id})

            if shortcut.type == ShortcutType.SECRETARY_BRIEF:
                from .orchestrator import BoardOrchestrator
                tmp_orch = BoardOrchestrator(
                    on_stage_start=lambda s, n: self._emit({"event": "stage_start", "stage": s, "name": n}),
                    on_member_started=lambda s, m: self._emit({"event": "member_speaking", "stage": s, "member_id": m.id, "member_title": m.title}),
                    on_member_done=lambda s, m, r, **kw: (
                        None if (kw.get("error")) else
                        self._emit({"event": "member_done", "stage": s, "member_id": m.id, "member_title": m.title, "content": r.content})
                    ),
                    on_stage_done=lambda s, rs: self._emit({"event": "stage_done", "stage": s, "count": 1}),
                )
                result = await tmp_orch.run_secretary_shortcut(
                    user_query,
                    session_id=session_id,
                    initiative_id=session.initiative_id,
                    initiative_mode=session.initiative_mode,
                )
                result.status = "completed"
                return result

        query_type = None
        complexity = None
        if existing_session is None:
            if member_ids:
                selected = set(member_ids)
                self.council = [
                    member for member in self.all_members
                    if member.id in selected and member.id != self.chairperson.id
                ]
                mode_reason = "Selected by manual scope."
            elif not skip_classify:
                from .classifier import classify_query

                classification = await classify_query(user_query)
                query_type = classification.query_type
                complexity = classification.complexity
                selected = set(classification.relevant_member_ids)
                self.council = [
                    member for member in self.all_members
                    if member.id in selected and member.id != self.chairperson.id
                ]
                session.classification = {
                    "query_type": classification.query_type,
                    "complexity": classification.complexity,
                    "relevant_member_ids": classification.relevant_member_ids,
                    "reasoning": classification.reasoning,
                    "required_capabilities": classification.required_capabilities or [],
                    "unavailable_capabilities": classification.unavailable_capabilities or [],
                    "stage_profile": classification.stage_profile,
                    "role_gap_memo": classification.role_gap_memo,
                }
                mode_reason = "Selected by capability routing."
            else:
                mode_reason = "Selected by full-board mode."

            if not self.council:
                self.council = []

            self.model_assignments = _assign_models(
                [*self.council, self.chairperson],
                query_type=query_type,
                config=get_config(),
            )
            session.participation = _build_participation_decisions(
                self.all_members,
                self.council,
                chairman_id=self.chairperson.id,
                classification=session.classification,
                mode_reason=mode_reason,
            )
            session.selected_council_ids = [m.id for m in self.council]
        else:
            mode_reason = "Reusing council from meeting start (continuation)."

        if existing_session is None:
            session.conversation = {
                "messages": [{
                    "id": "user_0",
                    "turn_index": 0,
                    "member_id": self.chairperson.id,
                    "member_title": "CEO / Chairperson",
                    "role": "CEO",
                    "speaker": "user",
                    "content": user_query,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }],
                "routing_trace": [],
            }

        self._emit({
            "event": "council_selected",
            "member_ids": [member.id for member in self.council],
            "chairman_id": self.chairperson.id,
        })
        self._emit({
            "event": "conversation_started",
            "session_id": session_id,
            "member_ids": [member.id for member in self.council],
            "chairman_id": self.chairperson.id,
            "response_language": response_language,
        })

        messages: list[ConversationMessage] = []
        used_member_ids: set[str] = set()

        # ── Pre-conversation evidence collection (Layer 1+2) ────────────
        from server.execution.web_search import (
            web_search,
            is_query_type_search_worthy,
            _build_role_specific_query,
        )
        _evidence_addenda: dict[str, str] = {}
        if is_query_type_search_worthy(query_type):
            for member in self.council:
                role_query = _build_role_specific_query(
                    base_query=user_query,
                    member_id=member.id,
                    member_role=member.role,
                )
                try:
                    result = await web_search(role_query, session_id=session_id)
                    results = result.get("results") or []
                    if results:
                        lines = ["## Retrieved Evidence"]
                        for item in results[:3]:
                            title = (item.get("title") or "Untitled").strip()
                            url = (item.get("url") or "").strip()
                            snippet = (item.get("snippet") or "").strip()
                            if len(snippet) > 500:
                                snippet = snippet[:500].rstrip() + "\u2026"
                            lines.append(f"- [{title}]({url}) \u2014 {snippet}")
                        _evidence_addenda[member.id] = "\n".join(lines)
                except Exception:
                    pass  # Non-critical: live mode continues without evidence
        self._live_evidence_addenda = _evidence_addenda

        decision = self._opening_turn_decision(query_type=query_type)

        for turn_index in range(1, self.max_turns + 1):
            if decision.member_id is None:
                session.status = "awaiting_chair_decision"
                # Defer chair_decision_required emission until after secretary brief
                break

            member = self._member_for_turn(decision.member_id)
            session.conversation["routing_trace"].append({
                "turn_index": turn_index,
                "member_title": member.title,
                **decision.to_dict(),
            })
            self._emit({
                "event": "turn_routed",
                "session_id": session_id,
                "turn_index": turn_index,
                "member_title": member.title,
                **{
                    **decision.to_dict(),
                    "routing_reason": _display_routing_reason(decision, response_language),
                },
            })

            message = await self._stream_member_message(
                member,
                user_query=user_query,
                messages=messages,
                decision=decision,
                turn_index=turn_index,
                query_type=query_type,
                complexity=complexity,
                response_language=response_language,
                session_id=session_id,
            )
            messages.append(message)
            session.conversation["messages"].append(message.to_dict())

            used_member_ids.add(member.id)
            decision = route_next_speaker(
                self.council,
                chairperson=self.chairperson,
                messages=messages,
                used_member_ids=used_member_ids,
                turn_index=turn_index + 1,
                max_turns=self.max_turns,
            )

        if session.status == "running":
            session.status = "awaiting_chair_decision"

        # ── Final Secretary Executive Brief ────────────────────────────
        # Comprehensive summary after ALL members have spoken.
        # This supersedes the per-turn interim briefs with a complete picture.
        if messages and session.status == "awaiting_chair_decision":
            await self._produce_live_secretary_brief(
                session=session,
                user_query=user_query,
                messages=messages,
                response_language=response_language,
                session_id=session_id,
                round_index=self._current_round,
            )

        # Only emit chair_decision_required AFTER secretary has briefed.
        # This ensures the frontend shows the summary alongside the prompt
        # for CEO decision.
        if session.status == "awaiting_chair_decision":
            self._emit({
                "event": "chair_decision_required",
                "session_id": session_id,
                "turn_index": len(messages) + 1,
                "trigger": "awaiting_ceo_decision",
                "routing_reason": _display_routing_reason(
                    TurnDecision(
                        member_id=None,
                        trigger="awaiting_ceo_decision",
                        routing_reason="The board has provided its input; the CEO should make the call.",
                        reply_to_message_id=messages[-1].id if messages else "user_0",
                    ),
                    response_language,
                ),
                "reply_to_message_id": messages[-1].id if messages else "user_0",
            })

        if session.stage3_synthesis:
            session.decision = _metadata_for_decision(
                project_board_decision(session.stage3_synthesis.content),
                session=session,
                chairman=self.chairperson,
                council=self.council,
            )
            session.delegation_plan = {
                "session_id": session_id,
                "tasks": [],
                "warnings": ["Live discussion mode does not yet generate delegation tasks."],
                "requires_approval": True,
                "structured_output_failed": False,
                "truncated": False,
            }
            session.memory = propose_memory_update(
                session.stage3_synthesis.content,
                session_id=session_id,
            )

        self._emit({
            "event": "conversation_done",
            "session_id": session_id,
            "message_count": len(session.conversation["messages"]),
            "status": session.status,
        })

        session.total_elapsed = round(time.monotonic() - t0, 2)
        session.save()
        try:
            _record_to_ledger(session, config_version=get_config().version, db_path=_LEDGER_DB_PATH)
        except Exception:
            logger.warning("Failed to record live discussion session to harness ledger", exc_info=True)
        return session

    def _opening_turn_decision(self, *, query_type: str | None) -> TurnDecision:
        by_id = {member.id: member for member in self.council}
        preferred_id = QUERY_TYPE_OPENERS.get(query_type or "full-board", "strategist")
        member_id = preferred_id if preferred_id in by_id else None
        if member_id is None:
            for candidate in MEMBER_ORDER:
                if candidate in by_id:
                    member_id = candidate
                    break
        if member_id is None:
            return TurnDecision(
                member_id=None,
                trigger="awaiting_ceo_decision",
                routing_reason="No routed board member is available; the CEO should make the call or add members.",
                reply_to_message_id="user_0",
            )
        return TurnDecision(
            member_id=member_id,
            trigger="initial_route",
            routing_reason="Initial speaker selected from the query classification and routed council.",
            reply_to_message_id="user_0",
        )

    def _member_for_turn(self, member_id: str) -> BoardMember:
        if member_id == self.chairperson.id:
            return self.chairperson
        by_id = {member.id: member for member in self.council}
        return by_id.get(member_id) or self.chairperson

    async def _stream_member_message(
        self,
        member: BoardMember,
        *,
        user_query: str,
        messages: list[ConversationMessage],
        decision: TurnDecision,
        turn_index: int,
        query_type: str | None,
        complexity: str | None,
        response_language: str,
        session_id: str,
    ) -> ConversationMessage:
        message_id = f"{session_id}_msg_{turn_index}"
        model = self.model_assignments.get(member.id)
        if not model:
            model = self.chairman_model
        prompt = _format_live_prompt(
            member=member,
            user_query=user_query,
            messages=messages,
            decision=decision,
            is_chair=False,
            response_language=response_language,
        )
        max_tokens = _resolve_live_turn_max_tokens(query_type=query_type, complexity=complexity)

        self._emit({
            "event": "message_start",
            "session_id": session_id,
            "message_id": message_id,
            "turn_index": turn_index,
            "member_id": member.id,
            "member_title": member.title,
            "reply_to_message_id": decision.reply_to_message_id,
            "trigger": decision.trigger,
            "routing_reason": decision.routing_reason,
        })

        started = time.monotonic()
        stream_finals: list[LLMStreamChunk] = []
        system_prompt = _live_system_prompt(
            member,
            user_query=user_query,
            evidence_addendum=getattr(self, "_live_evidence_addenda", {}).get(member.id),
        )
        content, final_chunk = await self._stream_visible_llm_response(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            system=system_prompt,
            max_tokens=max_tokens,
            existing_content="",
            event_base={
                "session_id": session_id,
                "message_id": message_id,
                "turn_index": turn_index,
                "member_id": member.id,
                "member_title": member.title,
            },
        )
        if final_chunk:
            stream_finals.append(final_chunk)

        continuation_count = 0
        while _needs_stream_continuation(final_chunk) and continuation_count < self.max_continuations:
            continuation_count += 1
            content, final_chunk = await self._stream_visible_llm_response(
                model=model,
                messages=[
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": _continuation_prompt(response_language)},
                ],
                system=system_prompt,
                max_tokens=max_tokens,
                existing_content=content,
                event_base={
                    "session_id": session_id,
                    "message_id": message_id,
                    "turn_index": turn_index,
                    "member_id": member.id,
                    "member_title": member.title,
                },
            )
            if final_chunk:
                stream_finals.append(final_chunk)

        elapsed = round(time.monotonic() - started, 2)
        input_tokens = _sum_known_tokens(stream_finals, "input_tokens")
        output_tokens = _sum_known_tokens(stream_finals, "output_tokens")
        final_model = final_chunk.model if final_chunk and final_chunk.model else model
        finish_reason = final_chunk.finish_reason if final_chunk else None
        response_id = final_chunk.response_id if final_chunk else None
        simulated_stream = any(chunk.simulated_stream for chunk in stream_finals) if stream_finals else False
        self.metrics.record(CallMetrics(
            member_id=member.id,
            stage=1,
            model=final_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_seconds=elapsed,
            finish_reason=finish_reason,
            response_id=response_id,
        ))

        message = ConversationMessage(
            id=message_id,
            turn_index=turn_index,
            member_id=member.id,
            member_title=member.title,
            role=member.role,
            content=content,
            reply_to_message_id=decision.reply_to_message_id,
            model=final_model,
            elapsed_seconds=elapsed,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            finish_reason=finish_reason,
            simulated_stream=simulated_stream,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._emit({
            "event": "message_done",
            "session_id": session_id,
            "message_id": message_id,
            "turn_index": turn_index,
            "member_id": member.id,
            "member_title": member.title,
            "reply_to_message_id": decision.reply_to_message_id,
            "content": content,
            "model": message.model,
            "elapsed": elapsed,
            "finish_reason": message.finish_reason,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "simulated_stream": message.simulated_stream,
        })
        return message

    async def _stream_visible_llm_response(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        system: str,
        max_tokens: int,
        existing_content: str,
        event_base: dict[str, Any],
    ) -> tuple[str, LLMStreamChunk | None]:
        local_content = ""
        final_chunk = None
        async for chunk in query_llm_stream(
            model,
            messages,
            system=system,
            max_tokens=max_tokens,
        ):
            if chunk.done:
                final_chunk = chunk
                local_content = chunk.content or local_content
                continue
            if not chunk.delta:
                continue
            local_content = chunk.content or f"{local_content}{chunk.delta}"
            self._emit({
                "event": "message_delta",
                **event_base,
                "delta": chunk.delta,
                "content": f"{existing_content}{local_content}",
                "simulated_stream": chunk.simulated_stream,
            })
        return f"{existing_content}{local_content}", final_chunk

    async def _produce_live_secretary_brief(
        self,
        *,
        session: BoardSession,
        user_query: str,
        messages: list[ConversationMessage],
        response_language: str,
        session_id: str,
        round_index: int,
    ) -> None:
        """Summarise the live discussion via the Secretary agent (one call per round)."""
        from ..config import get_members_by_id
        from ..llm import LLMStreamChunk, query_llm_stream
        from ..metrics import CallMetrics
        from server.harness.config import get_config, resolve_stage_max_tokens

        secretary = get_members_by_id().get("secretary")
        if secretary is None:
            logger.warning("Secretary not available for live discussion brief.")
            return

        # Build transcript from all messages spoken so far
        transcript = _format_full_transcript(messages)

        message_id = f"{session_id}_secretary_brief_r{round_index}"

        self._emit({
            "event": "secretary_starting",
            "session_id": session_id,
            "message_id": message_id,
            "member_id": secretary.id,
            "member_title": secretary.title,
            "round_index": round_index,
        })

        started = time.monotonic()
        # Pin the secretary to a non-reasoning model. Both kimi/k2.6 (chair) and
        # deepseek-v4-pro (council) combine reasoning + output into one
        # max_tokens budget; on the secretary's prompt they burn the entire
        # budget on internal thinking and emit zero visible content
        # (finish_reason=length, output_tokens=0). qwen3.6-plus is non-thinking
        # by default and produces structured bullet output reliably; the dated
        # snapshot also carries free DashScope credits.
        # Override via AGENTIC_BOARD_LIVE_SECRETARY_MODEL if a future config
        # needs a different choice.
        model = os.getenv("AGENTIC_BOARD_LIVE_SECRETARY_MODEL", "qwen/qwen3.6-plus-2026-04-02")
        max_tokens = _resolve_live_turn_max_tokens(
            query_type=None,
            complexity=None,
        )
        # Belt-and-suspenders: 6000 covers a worst-case ~80-line bullet brief
        # plus headroom for any provider that silently leaks reasoning tokens
        # into the output budget. The brief itself is ~960 tokens of bullets;
        # remaining ~5000 tokens absorb any reasoning the model insists on.
        max_tokens = max(max_tokens, 6000)

        # Use a MINIMAL system prompt for the live brief. The full secretary.md
        # member prompt (~130 lines) combined with a long transcript triggers
        # heavy reasoning on K2.6 / DeepSeek that consumes the entire token
        # budget without emitting visible content. The user-prompt template
        # already specifies the four-section format, attribution rules, and
        # hard caps — that's enough for the model.
        system = (
            "You are the Board Secretary producing concise executive briefs "
            "for the CEO. Follow the user message instructions exactly. Output "
            "only the requested section headers and bullets — no preamble, no "
            "closing remarks, no reasoning trace."
        )

        prompt = format_live_secretary_brief(
            user_query=user_query,
            transcript=transcript,
            round_index=round_index,
        )

        brief_content = ""
        final_chunk: LLMStreamChunk | None = None
        stream_finals: list[LLMStreamChunk] = []

        try:
            async for chunk in query_llm_stream(
                model,
                messages=[{"role": "user", "content": prompt}],
                system=system,
                max_tokens=max_tokens,
            ):
                if chunk.done:
                    final_chunk = chunk
                    brief_content = chunk.content or brief_content
                    continue
                if not chunk.delta:
                    continue
                brief_content = f"{brief_content}{chunk.delta}"
                self._emit({
                    "event": "secretary_delta",
                    "session_id": session_id,
                    "message_id": message_id,
                    "member_id": secretary.id,
                    "member_title": secretary.title,
                    "round_index": round_index,
                    "delta": chunk.delta,
                    "content": brief_content,
                    "simulated_stream": chunk.simulated_stream,
                })
        except Exception as exc:
            logger.warning("Secretary brief failed: %s", exc)
            self._emit({
                "event": "secretary_failed",
                "session_id": session_id,
                "member_id": secretary.id,
                "round_index": round_index,
                "error": str(exc),
            })
            return

        elapsed = round(time.monotonic() - started, 2)
        final_model = final_chunk.model if final_chunk else model
        finish_reason = final_chunk.finish_reason if final_chunk else None

        self._emit({
            "event": "secretary_done",
            "session_id": session_id,
            "message_id": message_id,
            "member_id": secretary.id,
            "member_title": secretary.title,
            "round_index": round_index,
            "content": brief_content,
            "model": final_model,
            "elapsed": elapsed,
            "finish_reason": finish_reason,
        })

        from .orchestrator import MemberResponse
        session.secretary_briefs.append(MemberResponse(
            member_id=secretary.id,
            stage=4,
            content=brief_content,
            model=final_model,
            elapsed_seconds=elapsed,
        ))
        self.metrics.record(CallMetrics(
            member_id=secretary.id,
            stage=4,
            model=final_model,
            input_tokens=-1,
            output_tokens=-1,
            latency_seconds=elapsed,
            finish_reason=finish_reason,
        ))


def detect_response_language(user_query: str) -> str:
    """Return the visible response language expected for this CEO prompt."""
    cjk_chars = sum(1 for char in user_query if "\u4e00" <= char <= "\u9fff")
    return "zh" if cjk_chars >= 2 else "en"


def _resolve_live_turn_max_tokens(*, query_type: str | None, complexity: str | None) -> int:
    override = _positive_int_env("AGENTIC_BOARD_LIVE_TURN_MAX_TOKENS")
    if override is not None:
        return override
    base = resolve_stage_max_tokens(
        1,
        query_type=query_type,
        complexity=complexity,
        config=get_config(),
    )
    minimum = _positive_int_env("AGENTIC_BOARD_LIVE_TURN_MIN_TOKENS") or 2400
    return max(base, minimum)


def _positive_int_env(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _needs_stream_continuation(chunk: LLMStreamChunk | None) -> bool:
    if not chunk or not chunk.finish_reason:
        return False
    return str(chunk.finish_reason).strip().lower() in _LENGTH_FINISH_REASONS


def _sum_known_tokens(chunks: list[LLMStreamChunk], field: str) -> int:
    values = [
        int(getattr(chunk, field))
        for chunk in chunks
        if isinstance(getattr(chunk, field, None), int) and int(getattr(chunk, field)) >= 0
    ]
    return sum(values) if values else -1


def _continuation_prompt(response_language: str) -> str:
    if response_language == "zh":
        return (
            "上一段发言因为长度限制被截断。请只继续刚才没有说完的内容，"
            "不要重复已经输出的文字，不要重新开头，用简体中文自然收尾。"
        )
    return (
        "The previous boardroom message was cut off by a token limit. "
        "Continue only the unfinished thought, do not repeat text already shown, "
        "do not restart the answer, and end naturally."
    )


def _language_instruction(response_language: str) -> str:
    if response_language == "zh":
        return (
            "语言要求：全程使用简体中文回答，不要中英混杂。"
            "只有专有名词、产品名、网站名、代码/API 标识符、URL 或必须保留的英文引用可以使用英文。"
        )
    return "Language requirement: respond in clear English."


def _display_routing_reason(decision: TurnDecision, response_language: str) -> str:
    if response_language != "zh":
        return decision.routing_reason
    if decision.trigger == "initial_route":
        return "已根据议题和成员能力选择首位发言成员。"
    if decision.trigger == "awaiting_ceo_decision":
        return "董事会成员已经给出输入，接下来由 CEO/Chairperson 做最终判断。"
    return "议题触发了新的专业视角，已邀请下一位成员回应。"


def _live_system_prompt(member: BoardMember, *, user_query: str, evidence_addendum: str | None = None) -> str:
    response_language = detect_response_language(user_query)
    parts = [member.system_prompt]
    parts.append(
        "Live boardroom conversation rules:\n"
        f"- {_language_instruction(response_language)}\n"
        "- Speak in natural language only. Do not return JSON or fenced code.\n"
        "- Be concise but complete: 2-4 short paragraphs or bullets.\n"
        "- Address the CEO's decision directly and respond to the prior speaker when relevant.\n"
        "- If another board role should speak next, name the capability gap plainly.",
    )
    if evidence_addendum:
        parts.append(f"\n{evidence_addendum}\n")
    return "\n".join(parts)


def _format_live_prompt(
    *,
    member: BoardMember,
    user_query: str,
    messages: list[ConversationMessage],
    decision: TurnDecision,
    is_chair: bool,
    response_language: str | None = None,
) -> str:
    response_language = response_language or detect_response_language(user_query)
    language_instruction = _language_instruction(response_language)
    transcript = _format_transcript(messages)
    if is_chair:
        return f"""You are closing this live board discussion as Chairperson.

{language_instruction}

CEO topic:
{user_query}

Conversation so far:
{transcript or "(No council messages yet.)"}

Produce the final board decision in Markdown with:
## Board Decision
### Executive Summary
### Strategic Direction
### Key Risks
### Next Steps

Keep it decisive and cite which perspectives changed the ruling."""

    return f"""You are speaking now as {member.title}.

{language_instruction}

CEO topic:
{user_query}

Why you were called next:
{decision.routing_reason}

Conversation so far:
{transcript or "(You are the opening speaker.)"}

Respond naturally to the CEO and the prior speaker. Give your strongest domain judgment, concrete next action, and any missing evidence that should route the next board member."""


def _format_transcript(messages: list[ConversationMessage]) -> str:
    if not messages:
        return ""
    lines: list[str] = []
    for message in messages[-6:]:
        lines.append(f"{message.member_title}: {message.content}")
    return "\n\n".join(lines)


def _format_full_transcript(messages: list[ConversationMessage]) -> str:
    """Format the entire conversation transcript for secretary summarisation."""
    if not messages:
        return "(No council messages.)"
    lines: list[str] = []
    for msg in messages:
        lines.append(f"**{msg.member_title}**: {msg.content}")
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# live_research script — Phase 1 implementation
# ---------------------------------------------------------------------------

import asyncio as _aio
from dataclasses import dataclass as _dc, field as _field

from ..config import get_council_models
from ..llm import query_llm
from ..tools import TOOLS, Tool
from .intake import (
    ChairOverrides, MemberAssignment, RoutingDecision, run_chair_intake,
)
from .orchestrator import (
    MemberTurnResult, ToolBudget, agentic_member_turn,
)


UPGRADED_MEMBERS = {"strategist", "researcher", "product", "critic",
                     "architect", "builder"}
PHASE1_TOOLS_FOR_MEMBERS = ["web_search", "fetch_url", "open_browser",
                             "ask_user_clarifying_question", "validate_claim"]


@_dc
class LiveResearchResult:
    routing: RoutingDecision
    member_responses: dict[str, MemberTurnResult] = _field(default_factory=dict)
    secretary_brief: str = ""


def _phase1_mode_override(assignments: list[MemberAssignment]) -> list[MemberAssignment]:
    """Force any member NOT in UPGRADED_MEMBERS to mode=fast (no tools).
    Phase 2: 6 council members are upgraded; chairperson runs intake separately,
    secretary runs the brief separately."""
    out: list[MemberAssignment] = []
    for a in assignments:
        if a.member_id in UPGRADED_MEMBERS:
            out.append(a)
        else:
            out.append(MemberAssignment(
                member_id=a.member_id, mode="fast",
                focus=a.focus, priority=a.priority,
            ))
    return out


def _select_member_model(member_id: str, council_models: list[str]) -> str:
    """Round-robin council models by member id; deterministic for tests."""
    if not council_models:
        return get_chairman_model()
    members = ["strategist", "product", "researcher", "critic",
               "architect", "builder"]
    try:
        idx = members.index(member_id)
    except ValueError:
        idx = 0
    return council_models[idx % len(council_models)]


def _budget_descriptor(budget: ToolBudget) -> str:
    return (f"{budget.tool_calls_max} tool calls, "
            f"{budget.web_search_max} web searches, "
            f"{budget.open_browser_max} browser opens, "
            f"{budget.wall_seconds_max}s wall budget")


def _user_message_for_member(query: str, focus: str, budget: ToolBudget) -> str:
    return (f"User query: {query}\n\n"
            f"Your focus: {focus}\n\n"
            f"Your tool budget: {_budget_descriptor(budget)}.\n\n"
            "Produce your Stage 1 analysis per your role's operating procedures.")


async def run_live_research(
    *,
    query: str,
    user_overrides: ChairOverrides | None = None,
    on_event=None,
    followup_buffer=None,
) -> LiveResearchResult:
    """Phase 1 live_research script: intake -> first round -> secretary brief.

    followup_buffer: optional FollowupBuffer instance. When provided, the
    function drains it between rounds and re-invokes targeted members with
    a deep budget + the new focus. Loop is bounded to max_followup_rounds=10.
    """
    from types import SimpleNamespace
    overrides = user_overrides or ChairOverrides()
    on_event = on_event or (lambda e: None)
    session = SimpleNamespace(
        session_id=None,
        ask_user=getattr(overrides, "ask_user", None),
    )

    routing = await run_chair_intake(
        raw_query=query,
        user_overrides=overrides,
        session=session,
        on_event=on_event,
        chair_model=get_chairman_model(),
    )
    routing_with_phase1 = RoutingDecision(
        interpreted_query=routing.interpreted_query,
        decision_type=routing.decision_type,
        complexity=routing.complexity,
        importance=routing.importance,
        rationale=routing.rationale,
        members=_phase1_mode_override(routing.members),
        script=routing.script,
        deep_research_dossier=routing.deep_research_dossier,
    )

    members_by_id = get_members_by_id()
    council = get_council_models()
    available_tools = [TOOLS[n] for n in PHASE1_TOOLS_FOR_MEMBERS if n in TOOLS]

    async def _run_one(asg: MemberAssignment):
        member = members_by_id.get(asg.member_id)
        if member is None:
            return asg.member_id, None
        budget = ToolBudget.for_mode(asg.mode, member_role="member")
        tools_for_member = available_tools if asg.mode != "fast" else []
        model = _select_member_model(asg.member_id, council)
        result = await agentic_member_turn(
            member=member,
            model=model,
            system_prompt=member.system_prompt,
            initial_user_message=_user_message_for_member(
                routing_with_phase1.interpreted_query, asg.focus, budget),
            tools=tools_for_member,
            budget=budget,
            session=session,
            stage=1,
            on_event=on_event,
        )
        return asg.member_id, result

    pairs = await _aio.gather(*[_run_one(a) for a in routing_with_phase1.members])
    responses = {mid: r for mid, r in pairs if r is not None}

    def _build_transcript(resp_dict: dict) -> str:
        lines = []
        for mid, r in resp_dict.items():
            member = members_by_id.get(mid)
            title = member.title if member else mid
            lines.append(f"**{title}**: {r.content}")
        return "\n\n".join(lines)

    secretary_system = (
        "You are the Board Secretary. Consolidate the council's Stage 1 outputs "
        "into a precise executive brief.\n\n"
        "Output sections, in order, omitting any that would be empty:\n"
        "## Agreements\n"
        "## Conflicts\n"
        "## Open Questions\n"
        "## Decision Needed From CEO\n"
        "## Sources\n\n"
        "Rules:\n"
        "- Bullet points, terse, one claim per line.\n"
        "- Attribute every claim with the member's title in square brackets at the end, "
        "e.g., '[Customer Researcher]'.\n"
        "- For ## Sources: extract every distinct source citation that members wrote inline "
        "as `[source: <title>, <url>, retrieved <date>]`. Number them, dedupe by URL, and "
        "list which members cited each one. Format: '1. <Title> — <URL> (retrieved <date>; "
        "cited by: <Member Title>, <Member Title>)'. If no members cited any sources, OMIT "
        "this section entirely.\n"
        "- Do NOT invent claims, sources, or attributions not present in the input.\n"
        "- Do NOT add commentary, conclusions, or recommendations of your own — only "
        "consolidate what the council provided."
    )
    # Pin to a non-reasoning model (same pattern as _produce_live_secretary_brief).
    # kimi/kimi-k2.6 (chair) burns its entire token budget on internal reasoning
    # and emits empty content; qwen3.6-plus is non-thinking by default and the
    # dated snapshot carries free DashScope credits.
    secretary_model = os.getenv(
        "AGENTIC_BOARD_LIVE_SECRETARY_MODEL", "qwen/qwen3.6-plus-2026-04-02"
    )

    async def _generate_brief(round_index: int) -> str:
        transcript = _build_transcript(responses)
        secretary_prompt = format_live_secretary_brief(
            user_query=routing_with_phase1.interpreted_query,
            transcript=transcript,
            round_index=round_index,
        )
        brief_response = await query_llm(
            secretary_model,
            [{"role": "user", "content": secretary_prompt}],
            system=secretary_system,
            max_tokens=2000,
            timeout=120.0,
        )
        return brief_response.content or "[Secretary brief unavailable]"

    secretary_brief = await _generate_brief(round_index=0)

    # ── Follow-up loop ────────────────────────────────────────────────────────
    # Drain the buffer between rounds; re-invoke targeted members with deep
    # budget and updated focus. Loop is bounded to prevent runaway execution.
    if followup_buffer is not None:
        from .followup import FollowupBuffer
        from .orchestrator import SimpleEvent
        max_followup_rounds = 10
        rounds = 0
        while rounds < max_followup_rounds:
            rounds += 1
            pending = await followup_buffer.snapshot()
            if not pending:
                break
            for f in pending:
                if f.target is None:
                    on_event(SimpleEvent("FollowupSkipped", "no_target", f.raw))
                    continue
                if f.target not in UPGRADED_MEMBERS:
                    on_event(SimpleEvent("FollowupSkipped", "unknown_member", f.target))
                    continue
                member = members_by_id.get(f.target)
                if member is None:
                    on_event(SimpleEvent("FollowupSkipped", "missing_member", f.target))
                    continue
                on_event(SimpleEvent("MemberRevising", f.target, f.text))
                prev_content = (
                    responses[f.target].content if f.target in responses else ""
                )[:4000]
                cont_msg = (
                    f"Continue your earlier analysis with this new focus from the user:\n"
                    f"\n{f.text}\n\n"
                    f"Your earlier analysis:\n{prev_content}\n\n"
                    f"Add new findings or revisions; reference your prior conclusions "
                    f"where unchanged. Your tool budget for this revision: deep."
                )
                new_budget = ToolBudget.for_mode("deep", member_role="member")
                new_result = await agentic_member_turn(
                    member=member,
                    model=_select_member_model(f.target, council),
                    system_prompt=member.system_prompt,
                    initial_user_message=cont_msg,
                    tools=available_tools,
                    budget=new_budget,
                    session=session,
                    stage=1,
                    on_event=on_event,
                )
                responses[f.target] = new_result
                on_event(SimpleEvent("MemberRevised", f.target, new_result.tool_calls_made))
            # Regenerate secretary brief after this follow-up round
            secretary_brief = await _generate_brief(round_index=rounds)

    return LiveResearchResult(
        routing=routing_with_phase1,
        member_responses=responses,
        secretary_brief=secretary_brief,
    )
