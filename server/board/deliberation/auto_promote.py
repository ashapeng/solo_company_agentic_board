"""Auto-Promote-to-Live (spec §9.2): rebuttal sub-pipeline.

When Stage 2 produces a high disagreement score and the HEAVY-tier gate is on,
this module orchestrates a chair-moderated live rebuttal between the most
contentious member pair(s), then summarizes each rebuttal into a REBUTTAL
OUTCOME block the chair reads during Stage 3 synthesis.

Public surface used by the orchestrator (`deliberate()`):
  - compute_disagreement(stage2_responses) -> int
  - pick_top_pairs(stage2_responses, contradictions, *, max_pairs) -> list[dict]
  - run_live_rebuttal(*, ...) -> dict
  - summarize_rebuttal(transcript, *, model) -> tuple[str, str | None]
  - format_rebuttal_outcomes_block(rebuttals) -> str

Behind a dark-launch flag (`hardening.auto_promote_enabled: False`) so the
cheap orchestration ships immediately and the expensive live-rebuttal loop
stays off until calibration data exists. The disagreement score is computed
and persisted on the session unconditionally — telemetry for tuning the
threshold later.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from server.board.deliberation.orchestrator import MemberResponse

logger = logging.getLogger(__name__)


# ─── §9.2.2 disagreement score ───────────────────────────────────────────────


def compute_disagreement(stage2_responses: "Sequence[MemberResponse]") -> int:
    """Spec §9.2.2 formula. Counts ``[Challenge]`` markers per response and
    adds 1 per response containing ``"Changed because"`` (presence, not count).

    Pure function — no LLM call. Safe to invoke regardless of the dark-launch
    flag; the orchestrator always persists the result on
    ``session.disagreement_score`` for tuning telemetry.
    """
    score = 0
    for r in stage2_responses or []:
        text = (getattr(r, "content", "") or "")
        score += text.count("[Challenge]")
        if "Changed because" in text:
            score += 1
    return score
