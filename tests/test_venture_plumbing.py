"""Tests for venture_id plumbing through the deliberation request flow.

Verifies that a `venture_id` threads from the API request schema through the
orchestrator session and into venture-scoped persistence, while preserving
exact back-compat for the default venture.
"""

from __future__ import annotations

import inspect
import json

from server.api.schemas import QueryRequest
from server.board.deliberation.orchestrator import BoardOrchestrator, BoardSession
from server.ventures import venture_slug


# ── 1. QueryRequest schema ──────────────────────────────────────────────


def test_query_request_venture_id_defaults_none():
    req = QueryRequest(query="x")
    assert req.venture_id is None


def test_query_request_venture_id_round_trips():
    req = QueryRequest(query="x", venture_id="acme")
    assert req.venture_id == "acme"
    assert QueryRequest(**req.model_dump()).venture_id == "acme"


# ── 2. BoardSession.to_dict includes venture_id ─────────────────────────


def test_board_session_default_venture_id():
    session = BoardSession(session_id="board_1", user_query="Q")
    assert session.venture_id == "default"
    assert session.to_dict()["venture_id"] == "default"


def test_board_session_to_dict_includes_venture_id():
    session = BoardSession(session_id="board_1", user_query="Q", venture_id="acme")
    assert session.to_dict()["venture_id"] == "acme"


# ── 3. save() venture-scoped vs flat path ───────────────────────────────


def test_save_writes_under_slug_subdirectory(tmp_path):
    session = BoardSession(session_id="board_42", user_query="Q", venture_id="Acme Co")
    out = session.save(directory=str(tmp_path))

    expected = tmp_path / venture_slug("Acme Co") / "board_42.json"
    assert out == expected
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["venture_id"] == "Acme Co"
    # The flat path must NOT be used.
    assert not (tmp_path / "board_42.json").exists()


def test_save_default_venture_stays_flat(tmp_path):
    session = BoardSession(session_id="board_99", user_query="Q")  # default venture
    out = session.save(directory=str(tmp_path))

    assert out == tmp_path / "board_99.json"
    assert out.exists()
    # No slug subdirectory should be created for the default venture.
    assert list(tmp_path.iterdir()) == [out]


# ── 4. deliberate() accepts venture_id + passes it to read_sotb_governed ──


def test_deliberate_accepts_venture_id_kwarg():
    sig = inspect.signature(BoardOrchestrator.deliberate)
    assert "venture_id" in sig.parameters


def test_deliberate_threads_venture_into_sotb_read(monkeypatch):
    """Assert read_sotb_governed is called with the session's venture_id.

    We stub Stage 1/2 to return nothing and replace `read_sotb_governed` with a
    sentinel that captures `venture_id` then raises to short-circuit before any
    networked Stage 3 work. No provider calls occur.
    """
    import asyncio

    from server.board.deliberation import orchestrator as orch_mod

    captured: dict = {}

    class _StopHere(Exception):
        pass

    async def _fake_read_sotb_governed(query, *, verify, venture_id="default", **kwargs):
        captured["venture_id"] = venture_id
        raise _StopHere()

    async def _empty_stage(*a, **k):
        return []

    monkeypatch.setattr(orch_mod, "detect_shortcut", lambda q: None)
    monkeypatch.setattr(orch_mod, "read_sotb_governed", _fake_read_sotb_governed)

    orch = BoardOrchestrator()
    monkeypatch.setattr(orch, "stage1", _empty_stage)
    monkeypatch.setattr(orch, "stage2", _empty_stage)

    async def _run():
        return await orch.deliberate(
            "should we ship?",
            member_ids=[m.id for m in orch.council],
            skip_classify=True,
            venture_id="acme",
        )

    try:
        asyncio.run(_run())
    except _StopHere:
        pass

    assert captured.get("venture_id") == "acme"
