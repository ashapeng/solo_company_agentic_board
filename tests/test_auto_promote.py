"""Auto-Promote-to-Live tests (spec §9.2 + design-choices supplement)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from server.board.deliberation.orchestrator import MemberResponse


def _resp(member_id: str, text: str, stage: int = 2) -> MemberResponse:
    return MemberResponse(
        member_id=member_id, stage=stage, content=text,
        model="m", elapsed_seconds=0.1,
    )


# ─── T2: compute_disagreement (spec §9.2.2) ─────────────────────────────────


def test_compute_disagreement_zero_when_no_responses():
    from server.board.deliberation.auto_promote import compute_disagreement
    assert compute_disagreement([]) == 0


def test_compute_disagreement_counts_challenge_markers():
    from server.board.deliberation.auto_promote import compute_disagreement
    responses = [
        _resp("strategist", "Some text. [Challenge] Foo. [Challenge] Bar."),
        _resp("product", "Plain text without challenges."),
    ]
    assert compute_disagreement(responses) == 2


def test_compute_disagreement_adds_one_per_response_with_changed_because():
    """Spec §9.2.2 literal: presence check, not count."""
    from server.board.deliberation.auto_promote import compute_disagreement
    responses = [
        _resp("strategist", "Changed because of new evidence. Changed because of X."),
        _resp("product", "Plain."),
    ]
    # First response: 0 [Challenge] + 1 "Changed because" presence = 1
    # Second response: 0 + 0 = 0
    assert compute_disagreement(responses) == 1


def test_compute_disagreement_combines_both_signals():
    from server.board.deliberation.auto_promote import compute_disagreement
    responses = [
        _resp("strategist", "[Challenge] Foo. [Challenge] Bar. Changed because new data."),
        _resp("product", "[Challenge] Baz."),
        _resp("critic", "Plain."),
    ]
    # strategist: 2 + 1 = 3
    # product:    1 + 0 = 1
    # critic:     0 + 0 = 0
    assert compute_disagreement(responses) == 4


def test_compute_disagreement_handles_none_content():
    """Defensive: a member response with content=None should not crash."""
    from server.board.deliberation.auto_promote import compute_disagreement
    r = _resp("strategist", "")  # the dataclass requires str; use empty
    r.content = None  # simulate post-load corruption
    assert compute_disagreement([r]) == 0
