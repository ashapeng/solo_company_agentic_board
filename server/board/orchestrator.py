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
from pathlib import Path

from .compaction import compact_stage1_responses, compact_stage2_responses
from .config import BoardMember, get_board_members, get_members_by_id, get_chairman_model, get_council_models
from .harness_config import get_config
from .llm import query_llm, LLMResponse
from .memory import read_sotb
from .memory_review import propose_memory_update
from .metrics import CallMetrics, SessionMetrics
from .prompts import format_stage1, format_stage2, format_stage3
from .schemas import project_board_decision, verification_to_dict

logger = logging.getLogger(__name__)


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
    decision: dict | None = None
    verification: dict | None = None
    memory: dict | None = None

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
            "verification": self.verification,
            "memory": self.memory,
            "total_elapsed": self.total_elapsed,
            "metrics": self.metrics.summary(),
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


def _assign_models(members: list[BoardMember]) -> dict[str, str]:
    """Assign an LLM model to each board member via round-robin or override."""
    models = get_council_models()
    assignments: dict[str, str] = {}
    for i, member in enumerate(members):
        if member.model_override:
            assignments[member.id] = member.model_override
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

    def _fire(self, callback, *args):
        if callback:
            callback(*args)

    def _record_metrics(self, member_id: str, stage: int, llm_resp: LLMResponse) -> None:
        """Record metrics from an LLM response."""
        self.metrics.record(CallMetrics(
            member_id=member_id,
            stage=stage,
            model=llm_resp.model,
            input_tokens=llm_resp.input_tokens,
            output_tokens=llm_resp.output_tokens,
            latency_seconds=llm_resp.latency_seconds,
        ))

    async def _query_member(
        self,
        member: BoardMember,
        prompt: str,
        stage: int,
    ) -> MemberResponse:
        model = self.model_assignments.get(member.id, get_council_models()[0])
        messages = [{"role": "user", "content": prompt}]

        cfg = get_config()
        stage_tokens = {
            1: cfg.stage1_max_tokens,
            2: cfg.stage2_max_tokens,
            3: cfg.stage3_max_tokens,
        }
        max_tokens = stage_tokens.get(stage, cfg.stage3_max_tokens)

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

    async def stage1(self, user_query: str) -> list[MemberResponse]:
        self._fire(self._on_stage_start, 1, "Independent Analysis")

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
        self, user_query: str, stage1_responses: list[MemberResponse]
    ) -> list[MemberResponse]:
        self._fire(self._on_stage_start, 2, "Peer Review & Challenge")

        if len(self.council) <= 1:
            logger.info("Stage 2 skipped: peer review requires at least 2 council members.")
            self._fire(self._on_stage_done, 2, [])
            return []

        # Compact Stage 1 responses before passing to peer review
        compacted_s1 = compact_stage1_responses(stage1_responses)

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
    ) -> MemberResponse:
        self._fire(self._on_stage_start, 3, "Chairman Synthesis")

        # Compact inter-stage context before passing to chairman. Raw responses
        # remain in the saved session JSON for audit.
        compacted_s1 = compact_stage1_responses(stage1_responses)
        compacted_s2 = compact_stage2_responses(stage2_responses)

        prompt = format_stage3(
            user_query=user_query,
            stage1_responses=_format_identified_responses(compacted_s1),
            stage2_responses=_format_identified_responses(compacted_s2),
            sotb=sotb,
        )

        messages = [{"role": "user", "content": prompt}]
        llm_resp = await query_llm(
            self.chairman_model, messages,
            system=self.chairman.system_prompt,
            max_tokens=get_config().stage3_max_tokens,
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

    # ── Full Deliberation ──────────────────────────────────────────────

    async def deliberate(
        self,
        user_query: str,
        *,
        member_ids: list[str] | None = None,
        skip_classify: bool = False,
        verify: bool = False,
        session_id: str | None = None,
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
        if member_ids:
            # Manual override — use only the specified members
            all_members = get_board_members()
            self.council = [m for m in all_members if m.id in member_ids and m.id != self.chairman.id]
            self.model_assignments = _assign_models(self.council + [self.chairman])
            logger.info("Manual member override. Selected: %s", [m.id for m in self.council])
        elif not skip_classify:
            from .classifier import classify_query

            classification = await classify_query(user_query)
            all_members = get_board_members()
            self.council = [
                m for m in all_members
                if m.id in classification.relevant_member_ids and m.id != self.chairman.id
            ]
            self.model_assignments = _assign_models(self.council + [self.chairman])
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
            logger.info(
                "Query classified as '%s' (%s). Selected: %s",
                classification.query_type,
                classification.complexity,
                [m.id for m in self.council],
            )
        # else: skip_classify=True — use the full council set from __init__

        t0 = time.monotonic()

        # Stage 1: All members analyze independently (parallel)
        session.stage1_responses = await self.stage1(user_query)

        # Stage 2: Peer review with anonymized responses (parallel)
        session.stage2_responses = await self.stage2(user_query, session.stage1_responses)

        # Read institutional memory before synthesis
        sotb = read_sotb()

        # Stage 3: Chairman synthesizes everything (with SOTB context)
        session.stage3_synthesis = await self.stage3(
            user_query, session.stage1_responses, session.stage2_responses,
            sotb=sotb,
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
                user_query=user_query,
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
                    user_query=user_query,
                )
                logger.info("Revision score: %d/10 (passed: %s)", result.score, result.passed)
                session.verification = verification_to_dict(result)

        if session.stage3_synthesis:
            session.decision = project_board_decision(session.stage3_synthesis.content)
            session.memory = propose_memory_update(
                session.stage3_synthesis.content,
                session_id=session_id,
            )
            if session.memory.get("proposed_sotb_update"):
                logger.info("SOTB update proposed for session %s; awaiting approval", session_id)

        session.total_elapsed = round(time.monotonic() - t0, 2)
        session.save()
        return session
