"""Orchestrator wiring tests for P5b auto-promote-to-live."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from server.board.deliberation.orchestrator import BoardSession, MemberResponse


# ─── T6: BoardSession.disagreement_score + auto_promoted_rebuttals ──────────


def test_board_session_disagreement_score_defaults_zero():
    s = BoardSession(session_id="t", user_query="x")
    assert s.disagreement_score == 0


def test_board_session_auto_promoted_rebuttals_defaults_empty():
    s = BoardSession(session_id="t", user_query="x")
    assert s.auto_promoted_rebuttals == []


def test_board_session_to_dict_includes_new_fields():
    s = BoardSession(
        session_id="t", user_query="x",
        disagreement_score=7,
        auto_promoted_rebuttals=[
            {"pair_member_ids": ["strategist", "product"],
             "disagreement_score": 7,
             "topic": "market sizing",
             "severity": "load_bearing",
             "transcript": [{"role": "chair", "content": "open"}],
             "summary": "REBUTTAL OUTCOME — ...",
             "resolution": "PARTIAL",
             "summarizer_model": "qwen/qwen3.6-plus",
             "tokens_in": 500,
             "tokens_out": 200,
             "cost_usd": 0.0,
             "started_at": "2026-05-17T00:00:00+00:00",
             "elapsed_seconds": 12.3,
             "closed_early": False},
        ],
    )
    d = s.to_dict()
    assert d["disagreement_score"] == 7
    assert len(d["auto_promoted_rebuttals"]) == 1
    assert d["auto_promoted_rebuttals"][0]["resolution"] == "PARTIAL"
    assert d["auto_promoted_rebuttals"][0]["transcript"] == [
        {"role": "chair", "content": "open"}
    ]
