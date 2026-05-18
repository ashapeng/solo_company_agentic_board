"""Expand-peer tool tests (spec §9.1)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from server.board import llm, tools
from server.board.config import BoardMember
from server.board.deliberation.orchestrator import (
    BoardSession,
    MemberResponse,
    ToolBudget,
    agentic_member_turn,
)


# ─── T1: BoardSession.stage2_anonymization_map data contract ────────────────

def test_board_session_stage2_anonymization_map_defaults_empty():
    """New BoardSession ships with an empty anonymization map."""
    s = BoardSession(session_id="t", user_query="x")
    assert s.stage2_anonymization_map == {}


def test_board_session_to_dict_roundtrips_anonymization_map():
    s = BoardSession(
        session_id="t", user_query="x",
        stage2_anonymization_map={"A": "strategist", "B": "product"},
    )
    d = s.to_dict()
    assert "stage2_anonymization_map" in d
    assert d["stage2_anonymization_map"] == {"A": "strategist", "B": "product"}


# ─── T2: _handle_expand_peer happy-path + failure modes ──────────────────────

from server.board.tools import _handle_expand_peer


def _resp(member_id: str, text: str, stage: int = 1) -> MemberResponse:
    return MemberResponse(
        member_id=member_id, stage=stage, content=text,
        model="kimi/kimi-k2.6", elapsed_seconds=0.1,
    )


def _session_with_stage1(letters_to_ids: dict[str, str],
                          contents: dict[str, str]) -> BoardSession:
    """Build a BoardSession with Stage 1 responses + populated anonymization map."""
    return BoardSession(
        session_id="t", user_query="x",
        stage1_responses=[_resp(mid, contents[mid]) for mid in letters_to_ids.values()],
        stage2_anonymization_map=dict(letters_to_ids),
    )


@pytest.mark.asyncio
async def test_expand_peer_returns_full_response_for_known_letter():
    """Letter A → real member_id → full un-compacted Stage 1 response."""
    session = _session_with_stage1(
        {"A": "strategist", "B": "product"},
        {"strategist": "Strategist's FULL analysis (1500 words, un-compacted).",
         "product": "Product Lead's FULL analysis (2000 words)."},
    )
    result = await _handle_expand_peer(
        member_letter="A", session=session, member_id="critic",
    )
    assert result.error is None
    assert "Strategist's FULL analysis" in result.content_for_model
    # Header reveals identity (acceptable — see Design Choices)
    assert "strategist" in result.content_for_model
    assert result.summary == "expand_peer A → strategist"


@pytest.mark.asyncio
async def test_expand_peer_returns_correct_response_for_letter_b():
    session = _session_with_stage1(
        {"A": "strategist", "B": "product"},
        {"strategist": "strat text", "product": "PRODUCT text"},
    )
    result = await _handle_expand_peer(
        member_letter="B", session=session, member_id="critic",
    )
    assert "PRODUCT text" in result.content_for_model
    assert "strat text" not in result.content_for_model


@pytest.mark.asyncio
async def test_expand_peer_unknown_letter_returns_error_not_raise():
    """Letter Z when only A/B exist → ToolResult with error, no exception."""
    session = _session_with_stage1(
        {"A": "strategist", "B": "product"},
        {"strategist": "x", "product": "y"},
    )
    result = await _handle_expand_peer(
        member_letter="Z", session=session, member_id="critic",
    )
    assert result.error is not None
    assert "no member with letter" in result.content_for_model.lower() \
        or "unknown" in result.content_for_model.lower()
    # CRITICAL: must NOT contain CONTRADICTED token so P3b doesn't force revision.
    assert "CONTRADICTED" not in (result.summary or "")


@pytest.mark.asyncio
async def test_expand_peer_self_expand_blocked():
    """Member B asking to expand B → error."""
    session = _session_with_stage1(
        {"A": "strategist", "B": "product"},
        {"strategist": "x", "product": "PRODUCT text"},
    )
    result = await _handle_expand_peer(
        member_letter="B", session=session, member_id="product",  # self!
    )
    assert result.error is not None
    assert "self" in result.content_for_model.lower() \
        or "own response" in result.content_for_model.lower()
    assert "PRODUCT text" not in result.content_for_model


@pytest.mark.asyncio
async def test_expand_peer_lowercase_letter_normalized():
    """`a` is treated the same as `A` — letters are case-insensitive."""
    session = _session_with_stage1(
        {"A": "strategist"},
        {"strategist": "strat text"},
    )
    result = await _handle_expand_peer(
        member_letter="a", session=session, member_id="critic",
    )
    assert result.error is None
    assert "strat text" in result.content_for_model


@pytest.mark.asyncio
async def test_expand_peer_map_letter_resolves_to_missing_response_returns_error():
    """Defensive: map says A→strategist, but session.stage1_responses has no
    entry for strategist (would only happen if stage 1 failed for one member
    between Stage 2 prep and the expand call). Return error, do not crash."""
    session = BoardSession(
        session_id="t", user_query="x",
        stage1_responses=[_resp("product", "PRODUCT text")],
        stage2_anonymization_map={"A": "strategist", "B": "product"},
    )
    result = await _handle_expand_peer(
        member_letter="A", session=session, member_id="critic",
    )
    assert result.error is not None
    assert "PRODUCT text" not in result.content_for_model


@pytest.mark.asyncio
async def test_expand_peer_no_session_returns_error():
    """If session is None (extreme defensive case), don't crash."""
    result = await _handle_expand_peer(
        member_letter="A", session=None, member_id="critic",
    )
    assert result.error is not None


# ─── T3: cap enforcement via ToolBudget ──────────────────────────────────────


def test_expand_peer_in_sub_caps_by_tool():
    """Wire-up sanity: SUB_CAPS_BY_TOOL knows the cap attribute."""
    from server.board.deliberation.orchestrator import ToolBudget
    assert ToolBudget.SUB_CAPS_BY_TOOL.get("expand_peer") == "expand_peer_max"


def test_expand_peer_cap_message_via_budget_filter():
    """When the budget is exhausted, `_budget_filtered_tools` drops the tool
    so the LLM never sees it. This is the natural enforcement path — the
    handler itself never gates."""
    from server.board.deliberation.orchestrator import (
        ToolBudget, _budget_filtered_tools,
    )
    from server.board import tools as tools_mod

    budget = ToolBudget.for_mode("standard", member_role="member")
    # Spend the cap
    budget.spend("expand_peer", 0.5)

    visible = _budget_filtered_tools(
        [tools_mod.TOOLS["web_search"], tools_mod.TOOLS["expand_peer"]],
        budget,
    )
    names = [t["function"]["name"] for t in visible]
    assert "web_search" in names
    assert "expand_peer" not in names
