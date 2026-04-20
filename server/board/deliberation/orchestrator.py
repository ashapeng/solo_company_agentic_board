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
from typing import Any

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

from .compaction import compact_stage1_responses, compact_stage2_responses
from ..config import BoardMember, get_board_members, get_members_by_id, get_chairman_model, get_council_models
from ..llm import query_llm, LLMResponse
from ..metrics import CallMetrics, SessionMetrics
from ..projection import project_board_decision, verification_to_dict
from .prompts import format_stage1, format_stage2, format_stage3

logger = logging.getLogger(__name__)

_LEDGER_DB_PATH = None  # Use default; tests can patch this


class BoardDeliberationError(Exception):
    """Raised when a deliberation cannot complete (e.g. too few members responded)."""
    pass


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
            "decision": self.decision,
            "delegation_plan": self.delegation_plan,
            "verification": self.verification,
            "memory": self.memory,
            "status": self.status,
            "intake_cards": self.intake_cards,
            "clarification": self.clarification,
            "structured_output_warnings": self.structured_output_warnings,
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
    words = [word for word in user_query.replace("-", " ").split() if word.strip()]
    lower = user_query.lower()
    if len(words) > 14:
        return False
    if any(member.id in {"product", "researcher", "strategist", "architect"} for member in council):
        ambiguous_terms = {"business", "product", "ai", "search", "e-commerce", "ecommerce"}
        return sum(1 for term in ambiguous_terms if term in lower) >= 2
    return False


def _build_intake_card(member: BoardMember, user_query: str, *, blocking: bool) -> dict:
    defaults = {
        "strategist": (
            "Which seller segment and market wedge should this target first?",
            "Market and competitive assumptions are not yet grounded.",
            "Define the wedge and evidence threshold before spend.",
            "strategy",
        ),
        "product": (
            "Who is the exact buyer and what painful job are they hiring this for?",
            "The request describes a solution before validating the problem.",
            "Run problem validation before feature scoping.",
            "product",
        ),
        "researcher": (
            "Which customers have already shown this pain through behavior or spend?",
            "No customer evidence has been supplied.",
            "Collect customer discovery evidence before the final decision.",
            "research",
        ),
        "critic": (
            "What would make this decision obviously wrong within 30 days?",
            "The failure criteria and disconfirming evidence are undefined.",
            "Set explicit kill criteria and dissent checks.",
            "legal",
        ),
        "architect": (
            "What input images, output quality bar, and integration surface are required?",
            "Technical feasibility depends on unstated product constraints.",
            "Run a feasibility memo after customer constraints are known.",
            "engineering",
        ),
        "builder": (
            "What is the smallest manual or prototype test that proves demand?",
            "Execution could expand before the validation path is clear.",
            "Sequence a small validation slice before implementation.",
            "engineering",
        ),
    }
    question, concern, path, unit = defaults.get(member.id, (
        "What missing fact would change this board member's recommendation?",
        "The prompt lacks enough context for a fully accountable decision.",
        "Name the assumption and verify it before execution.",
        "strategy",
    ))
    return {
        "member_id": member.id,
        "member_title": member.title,
        "clarifying_question": question,
        "immediate_concern": concern,
        "proposed_path": path,
        "required_execution_unit": unit,
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
        on_member_done: callable = None,
        on_stage_done: callable = None,
        on_intake_card: callable = None,
        on_clarification_required: callable = None,
        on_clarification_answered: callable = None,
        on_structured_output_warning: callable = None,
    ):
        all_members = members or get_board_members()
        members_by_id = get_members_by_id()
        self.chairman = members_by_id[chairman_id]
        self.council = [m for m in all_members if m.id != chairman_id]
        self.model_assignments = _assign_models(all_members)
        self.chairman_model = get_chairman_model()
        self.metrics = SessionMetrics()

        # Callbacks for progress reporting
        self._on_stage_start = on_stage_start
        self._on_member_done = on_member_done
        self._on_stage_done = on_stage_done
        self._on_intake_card = on_intake_card
        self._on_clarification_required = on_clarification_required
        self._on_clarification_answered = on_clarification_answered
        self._on_structured_output_warning = on_structured_output_warning
        self._token_budget_query_type: str | None = None
        self._token_budget_complexity: str | None = None

    def _fire(self, callback, *args):
        if callback:
            callback(*args)

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

        llm_resp = await query_llm(
            model,
            messages,
            system=member.system_prompt,
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

        # Stage 2: Peer review with anonymized responses (parallel)
        session.stage2_responses = await self.stage2(
            effective_query,
            session.stage1_responses,
            query_type=query_type,
            complexity=complexity,
        )

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
            from .verification import verify_synthesis

            # Get compacted stage 2 for verification context
            compacted_s2 = compact_stage2_responses(session.stage2_responses)
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

        if session.stage3_synthesis:
            session.decision = _metadata_for_decision(
                project_board_decision(session.stage3_synthesis.content),
                session=session,
                chairman=self.chairman,
                council=self.council,
            )
            if _synthesis_has_actions(session.stage3_synthesis.content):
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
            session.memory = propose_memory_update(
                session.stage3_synthesis.content,
                session_id=session_id,
            )
            if session.memory.get("proposed_sotb_update"):
                logger.info("SOTB update proposed for session %s; awaiting approval", session_id)

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
