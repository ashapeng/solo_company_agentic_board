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
