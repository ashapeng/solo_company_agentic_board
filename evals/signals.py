"""Extract observable signals from a completed BoardSession.

At P0, the standard `deliberate()` pipeline does not call tools (see plan
§Architecture). The fields for tool-related and post-P1/P2 signals exist
for forward-compat and stay empty/zero here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from server.board.deliberation.orchestrator import BoardSession


@dataclass
class ObservedSignals:
    """All signals the eval harness extracts from one deliberation."""
    # Stage 4 verifier (existing pipeline) — None when Stage 4 didn't run
    verifier_passed: bool | None = None
    verifier_score: int | None = None
    verifier_deficiencies: list[str] = field(default_factory=list)
    # Intake clarification gate
    clarification_required: bool = False
    clarification_questions: list[str] = field(default_factory=list)
    # Tool-call verdicts — empty at P0 (standard deliberate() makes no tool calls).
    # Populated once P3 persists tool calls to BoardSession.
    validate_claim_verdicts: list[dict] = field(default_factory=list)
    # Per-claim blinded verifier results (P1+). Each entry:
    # {claim_id, claim_text, verdict, rationale, evidence_refs}.
    blinded_verifier_per_claim: list[dict] = field(default_factory=list)
    # Cross-member contradictions surfaced by the P2 detector (count of
    # entries in session.contradictions). Was always 0 pre-P2.
    contradictions_surfaced: int = 0
    # P4: SOTB governance warnings (expired + low_confidence + stale +
    # query_conflicts + conflicts_logged). Always 0 pre-P4.
    sotb_health_warnings: int = 0
    # Count of `[UNVERIFIED]` markers in the chair synthesis (P1.2+). Used by
    # the hallucination_planted checker to credit "appropriately deferred"
    # behavior: when the chair refuses to fabricate and tags claims [UNVERIFIED]
    # instead, the verifier may pass the well-formed deferral but the eval
    # should still treat that as a success.
    synthesis_unverified_count: int = 0
    # P5b: Auto-promote-to-live (spec §9.2). Always 0 / empty pre-P5b.
    # disagreement_score is populated even when the flag is dark, so this
    # signal lights up immediately and can be used to tune the threshold.
    auto_promoted_rebuttals_count: int = 0
    auto_promoted_resolutions: list[str] = field(default_factory=list)
    disagreement_score: int = 0
    # Cost + latency
    total_cost_usd: float = 0.0
    total_latency_seconds: float = 0.0
    total_tokens: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "verifier_passed": self.verifier_passed,
            "verifier_score": self.verifier_score,
            "verifier_deficiencies": list(self.verifier_deficiencies),
            "clarification_required": self.clarification_required,
            "clarification_questions": list(self.clarification_questions),
            "validate_claim_verdicts": list(self.validate_claim_verdicts),
            "blinded_verifier_per_claim": list(self.blinded_verifier_per_claim),
            "contradictions_surfaced": self.contradictions_surfaced,
            "sotb_health_warnings": self.sotb_health_warnings,
            "synthesis_unverified_count": self.synthesis_unverified_count,
            "auto_promoted_rebuttals_count": self.auto_promoted_rebuttals_count,
            "auto_promoted_resolutions": list(self.auto_promoted_resolutions),
            "disagreement_score": self.disagreement_score,
            "total_cost_usd": self.total_cost_usd,
            "total_latency_seconds": self.total_latency_seconds,
            "total_tokens": self.total_tokens,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ObservedSignals":
        return cls(
            verifier_passed=d.get("verifier_passed"),
            verifier_score=d.get("verifier_score"),
            verifier_deficiencies=list(d.get("verifier_deficiencies") or []),
            clarification_required=bool(d.get("clarification_required", False)),
            clarification_questions=list(d.get("clarification_questions") or []),
            validate_claim_verdicts=list(d.get("validate_claim_verdicts") or []),
            blinded_verifier_per_claim=list(d.get("blinded_verifier_per_claim") or []),
            contradictions_surfaced=int(d.get("contradictions_surfaced", 0)),
            sotb_health_warnings=int(d.get("sotb_health_warnings", 0)),
            synthesis_unverified_count=int(d.get("synthesis_unverified_count", 0)),
            auto_promoted_rebuttals_count=int(d.get("auto_promoted_rebuttals_count", 0)),
            auto_promoted_resolutions=list(d.get("auto_promoted_resolutions") or []),
            disagreement_score=int(d.get("disagreement_score", 0)),
            total_cost_usd=float(d.get("total_cost_usd", 0.0)),
            total_latency_seconds=float(d.get("total_latency_seconds", 0.0)),
            total_tokens=int(d.get("total_tokens", 0)),
        )


def extract_signals(session: BoardSession) -> ObservedSignals:
    """Build an ObservedSignals snapshot from a completed BoardSession."""
    verification = session.verification or {}
    clarification = getattr(session, "clarification", {}) or {}
    metrics = session.metrics

    verifier_passed: bool | None
    if verification:
        passed = verification.get("passed")
        verifier_passed = bool(passed) if passed is not None else None
    else:
        verifier_passed = None

    questions_raw = clarification.get("questions") or []
    questions: list[str] = []
    for q in questions_raw:
        if isinstance(q, dict):
            questions.append(str(q.get("prompt") or q.get("question") or ""))
        else:
            questions.append(str(q))

    total_tokens = 0
    if metrics is not None:
        try:
            total_tokens = int(metrics.total_tokens())
        except AttributeError:
            total_tokens = 0

    stage3 = getattr(session, "stage3_synthesis", None)
    synthesis_text = getattr(stage3, "content", "") or ""
    synthesis_unverified_count = synthesis_text.count("[UNVERIFIED]")

    return ObservedSignals(
        verifier_passed=verifier_passed,
        verifier_score=verification.get("score") if verification else None,
        verifier_deficiencies=list(verification.get("deficiencies") or []),
        clarification_required=bool(questions),
        clarification_questions=questions,
        # Populated from `session.tool_call_results` (set by
        # `agentic_member_turn`). Falls back to [] when the session was
        # constructed from a legacy JSON that predates the field. Each
        # surfaced entry is shaped per the eval checker's contract
        # (`evals/metrics.py::_check_source_quality_trap`): claim,
        # verdict, rationale.
        validate_claim_verdicts=[
            {
                "claim": str((entry.get("arguments") or {}).get("claim", "")),
                "verdict": entry.get("verdict"),
                "rationale": entry.get("summary", ""),
            }
            for entry in (getattr(session, "tool_call_results", []) or [])
            if entry.get("tool_name") == "validate_claim"
        ],
        blinded_verifier_per_claim=list(verification.get("per_claim") or []),
        contradictions_surfaced=len(getattr(session, "contradictions", None) or []),
        sotb_health_warnings=int(
            (getattr(session, "sotb_health", None) or {}).get("warnings_count", 0)
        ),
        synthesis_unverified_count=synthesis_unverified_count,
        auto_promoted_rebuttals_count=len(getattr(session, "auto_promoted_rebuttals", []) or []),
        auto_promoted_resolutions=[
            r["resolution"]
            for r in (getattr(session, "auto_promoted_rebuttals", []) or [])
            if r.get("resolution")
        ],
        disagreement_score=int(getattr(session, "disagreement_score", 0) or 0),
        total_cost_usd=float(metrics.total_cost_estimate()) if metrics else 0.0,
        total_latency_seconds=float(session.total_elapsed or 0.0),
        total_tokens=total_tokens,
    )
