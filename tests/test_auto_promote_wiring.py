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


# ─── T7: stage3() rebuttal_outcomes prepend ─────────────────────────────────


@pytest.mark.asyncio
async def test_stage3_prepends_rebuttal_outcomes_block_when_non_empty():
    """When stage3() receives rebuttal_outcomes, the formatted block must
    appear in the prompt that goes to query_llm BEFORE the existing
    format_stage3() output."""
    from server.board import llm
    from server.board.deliberation.orchestrator import BoardOrchestrator

    captured_messages: list = []

    async def _capture_query(*a, **kw):
        # Capture the messages arg (positional 1 or kwarg) for inspection.
        msgs = kw.get("messages") if "messages" in kw else (a[1] if len(a) > 1 else [])
        captured_messages.extend(msgs)
        return llm.LLMResponse(
            content="synth", model="m", input_tokens=1, output_tokens=1,
            latency_seconds=0.01, finish_reason="stop", tool_calls=[],
        )

    orch = BoardOrchestrator()
    # Patch model attrs to avoid env dependencies.
    orch.chairman_model = "m"

    s1 = [MemberResponse(member_id="strategist", stage=1, content="S1A",
                          model="m", elapsed_seconds=0.01)]
    s2 = [MemberResponse(member_id="strategist", stage=2, content="S2A",
                          model="m", elapsed_seconds=0.01)]

    rebuttals = [
        {"summary": "REBUTTAL OUTCOME — t1\nResolution: PARTIAL\n...", "topic": "t1"},
    ]

    with patch("server.board.deliberation.orchestrator.query_llm",
               AsyncMock(side_effect=_capture_query)):
        await orch.stage3(
            "user q", s1, s2,
            sotb="(no warnings)",
            rebuttal_outcomes=rebuttals,
        )

    assert captured_messages, "stage3 didn't call query_llm"
    user_msg = captured_messages[0]["content"]
    # Rebuttal block must appear (spec §9.2.6 header is the load-bearing marker).
    assert "REBUTTAL OUTCOME (auto-promoted" in user_msg
    assert "REBUTTAL OUTCOME — t1" in user_msg


@pytest.mark.asyncio
async def test_stage3_no_block_when_rebuttal_outcomes_empty_or_none():
    """Default behaviour unchanged when rebuttal_outcomes=None or [].
    The spec §9.2.6 marker must NOT appear."""
    from server.board import llm
    from server.board.deliberation.orchestrator import BoardOrchestrator

    captured: list = []

    async def _capture(*a, **kw):
        msgs = kw.get("messages") if "messages" in kw else (a[1] if len(a) > 1 else [])
        captured.extend(msgs)
        return llm.LLMResponse(
            content="synth", model="m", input_tokens=1, output_tokens=1,
            latency_seconds=0.01, finish_reason="stop", tool_calls=[],
        )

    orch = BoardOrchestrator()
    orch.chairman_model = "m"

    s1 = [MemberResponse(member_id="strategist", stage=1, content="S1",
                          model="m", elapsed_seconds=0.01)]
    s2 = [MemberResponse(member_id="strategist", stage=2, content="S2",
                          model="m", elapsed_seconds=0.01)]

    with patch("server.board.deliberation.orchestrator.query_llm",
               AsyncMock(side_effect=_capture)):
        await orch.stage3("user q", s1, s2, sotb="(no warnings)")  # default kwargs
        await orch.stage3("user q", s1, s2, sotb="(no warnings)",
                           rebuttal_outcomes=[])

    for msg in captured:
        assert "REBUTTAL OUTCOME (auto-promoted" not in msg["content"]


# ─── T8: deliberate() wiring (dark-launch + live paths) ─────────────────────


@pytest.mark.asyncio
async def test_dark_launch_persists_score_no_rebuttals(monkeypatch):
    """auto_promote_enabled=False (default): disagreement_score is still
    computed and persisted on the session, but no rebuttals fire and
    auto_promoted_rebuttals stays empty."""
    from server.board.deliberation import orchestrator as orch_mod
    from server.board.deliberation.orchestrator import BoardOrchestrator, MemberResponse

    # Patch deliberate's internal seam helpers to keep the test mocky.
    orch = BoardOrchestrator()
    orch.chairman_model = "m"

    # Fake stage 1/2 outputs with [Challenge] markers so score > threshold.
    s1 = [
        MemberResponse(member_id="strategist", stage=1, content="x", model="m", elapsed_seconds=0.01),
        MemberResponse(member_id="product",    stage=1, content="y", model="m", elapsed_seconds=0.01),
    ]
    s2 = [
        MemberResponse(member_id="strategist", stage=2,
                        content="[Challenge] product wrong\n[Challenge] more\n[Challenge] more\n[Challenge] more\nChanged because data",
                        model="m", elapsed_seconds=0.01),
        MemberResponse(member_id="product", stage=2, content="x", model="m", elapsed_seconds=0.01),
    ]

    # Bypass classifier + stage1 + stage2 by patching the methods.
    async def _fake_stage1(*a, **kw): return s1
    async def _fake_stage2(*a, **kw): return s2
    async def _fake_stage3(*a, **kw):
        return MemberResponse(member_id="chairperson", stage=3, content="synth",
                              model="m", elapsed_seconds=0.01)
    async def _fake_stage4(*a, **kw): return None
    async def _fake_atomize(*a, **kw): return {}
    async def _fake_intake(*a, **kw): return ([], {"status": "not_required", "answers": {}})
    async def _fake_evidence(*a, **kw): return ({}, {})
    async def _fake_sotb_gov(*a, **kw):
        from server.memory.sotb_governance import SotbHealth
        return ("", SotbHealth())
    async def _fake_delegate(*a, **kw):
        return {"session_id": "t", "tasks": [], "warnings": [], "requires_approval": True,
                "structured_output_failed": False, "truncated": False}

    monkeypatch.setattr(orch, "stage1", _fake_stage1)
    monkeypatch.setattr(orch, "stage2", _fake_stage2)
    monkeypatch.setattr(orch, "stage3", _fake_stage3)
    monkeypatch.setattr(orch, "stage4_secretary_brief", _fake_stage4)
    monkeypatch.setattr(orch, "stage0_intake", lambda *a, **kw: ([], {"status": "not_required", "answers": {}}))
    monkeypatch.setattr(orch, "_collect_member_evidence", _fake_evidence)
    monkeypatch.setattr(orch, "_atomize_stage1", _fake_atomize)
    monkeypatch.setattr(orch, "build_delegation_plan", _fake_delegate)
    monkeypatch.setattr(orch_mod, "read_sotb_governed", _fake_sotb_gov)
    monkeypatch.setattr(orch_mod, "propose_memory_update",
                        lambda *a, **kw: {"proposed_sotb_update": None})

    # Patch Stage-4 verification so we don't fire real LLMs (mock-only).
    from server.board.deliberation import verification as _verif_mod
    async def _fake_verify(**kw):
        return _verif_mod.VerificationResult(score=10, passed=True)
    monkeypatch.setattr(_verif_mod, "verify_synthesis", _fake_verify)

    # Default config: auto_promote_enabled = False
    session = await orch.deliberate("q", skip_classify=True, verify=True)

    assert session.disagreement_score >= 4  # 4 [Challenge] + 1 Changed because = 5
    assert session.auto_promoted_rebuttals == []  # dark-launch: nothing fired


@pytest.mark.asyncio
async def test_live_path_runs_rebuttal_and_appends_entry(monkeypatch):
    """auto_promote_enabled=True, verify=True, score >= threshold → fires
    one rebuttal, persists the entry, passes rebuttal_outcomes to stage3."""
    from server.board import llm
    from server.board.deliberation import auto_promote, orchestrator as orch_mod
    from server.board.deliberation.orchestrator import BoardOrchestrator, MemberResponse

    orch = BoardOrchestrator()
    orch.chairman_model = "m"

    # Flip the dark-launch flag for this test.
    cfg = orch_mod.get_config()
    monkeypatch.setitem(cfg.hardening, "auto_promote_enabled", True)
    monkeypatch.setitem(cfg.hardening, "atomizer_model", "qwen/qwen3.6-plus-2026-04-02")
    monkeypatch.setitem(cfg.hardening, "disagreement_threshold", 4)
    monkeypatch.setitem(cfg.hardening, "auto_promote_max_pairs", 2)

    s1 = [
        MemberResponse(member_id="strategist", stage=1, content="s1a", model="m", elapsed_seconds=0.01),
        MemberResponse(member_id="product",    stage=1, content="s1b", model="m", elapsed_seconds=0.01),
    ]
    s2 = [
        MemberResponse(member_id="strategist", stage=2,
                        content="[Challenge] product wrong\n[Challenge] x\n[Challenge] y\n[Challenge] z\nChanged because new data",
                        model="m", elapsed_seconds=0.01),
        MemberResponse(member_id="product", stage=2, content="x", model="m", elapsed_seconds=0.01),
    ]

    captured_rebuttal_outcomes: list = []

    async def _fake_stage1(*a, **kw): return s1
    async def _fake_stage2(*a, **kw): return s2
    async def _fake_stage3(*a, **kw):
        captured_rebuttal_outcomes.append(kw.get("rebuttal_outcomes"))
        return MemberResponse(member_id="chairperson", stage=3, content="synth",
                              model="m", elapsed_seconds=0.01)
    async def _fake_stage4(*a, **kw): return None
    async def _fake_atomize(*a, **kw): return {}
    async def _fake_evidence(*a, **kw): return ({}, {})
    async def _fake_sotb_gov(*a, **kw):
        from server.memory.sotb_governance import SotbHealth
        return ("", SotbHealth())
    async def _fake_delegate(*a, **kw):
        return {"session_id": "t", "tasks": [], "warnings": [], "requires_approval": True,
                "structured_output_failed": False, "truncated": False}

    monkeypatch.setattr(orch, "stage1", _fake_stage1)
    monkeypatch.setattr(orch, "stage2", _fake_stage2)
    monkeypatch.setattr(orch, "stage3", _fake_stage3)
    monkeypatch.setattr(orch, "stage4_secretary_brief", _fake_stage4)
    monkeypatch.setattr(orch, "stage0_intake", lambda *a, **kw: ([], {"status": "not_required", "answers": {}}))
    monkeypatch.setattr(orch, "_collect_member_evidence", _fake_evidence)
    monkeypatch.setattr(orch, "_atomize_stage1", _fake_atomize)
    monkeypatch.setattr(orch, "build_delegation_plan", _fake_delegate)
    monkeypatch.setattr(orch_mod, "read_sotb_governed", _fake_sotb_gov)
    monkeypatch.setattr(orch_mod, "propose_memory_update",
                        lambda *a, **kw: {"proposed_sotb_update": None})

    # Stub the rebuttal + summarizer so we don't drive 9+ LLM calls.
    async def _fake_rebuttal(**kw):
        return {
            "transcript": [{"role": "chair", "member_id": "chairperson",
                             "content": "opening", "tool_calls": []}],
            "tokens_in": 5, "tokens_out": 3,
            "elapsed_seconds": 0.01, "closed_early": False,
        }

    async def _fake_summarize(**kw):
        return ("REBUTTAL OUTCOME — fallback topic\nResolution: PARTIAL", "PARTIAL", 50, 20)

    monkeypatch.setattr(auto_promote, "run_live_rebuttal", _fake_rebuttal)
    monkeypatch.setattr(auto_promote, "summarize_rebuttal", _fake_summarize)

    # Patch Stage-4 verification so we don't fire real LLMs (mock-only).
    from server.board.deliberation import verification as _verif_mod
    async def _fake_verify(**kw):
        return _verif_mod.VerificationResult(score=10, passed=True)
    monkeypatch.setattr(_verif_mod, "verify_synthesis", _fake_verify)

    session = await orch.deliberate("q", skip_classify=True, verify=True)

    # Score computed
    assert session.disagreement_score >= 4
    # Rebuttal fired (no contradictions populated → fallback path picks
    # the top-2 most-challenged members: strategist+product).
    assert len(session.auto_promoted_rebuttals) == 1
    entry = session.auto_promoted_rebuttals[0]
    assert set(entry["pair_member_ids"]) == {"strategist", "product"}
    assert entry["summary"].startswith("REBUTTAL OUTCOME")
    assert entry["resolution"] == "PARTIAL"
    assert entry["summarizer_model"] == "qwen/qwen3.6-plus-2026-04-02"  # falls back to atomizer
    # stage3 received the outcomes
    assert captured_rebuttal_outcomes == [session.auto_promoted_rebuttals]


@pytest.mark.asyncio
async def test_live_path_skipped_when_verify_false(monkeypatch):
    """verify=False (STANDARD tier) → no rebuttals fire even if flag is on."""
    from server.board.deliberation import auto_promote, orchestrator as orch_mod
    from server.board.deliberation.orchestrator import BoardOrchestrator, MemberResponse

    orch = BoardOrchestrator()
    orch.chairman_model = "m"

    cfg = orch_mod.get_config()
    monkeypatch.setitem(cfg.hardening, "auto_promote_enabled", True)

    s1 = [MemberResponse(member_id="strategist", stage=1, content="x", model="m", elapsed_seconds=0.01)]
    s2 = [MemberResponse(member_id="strategist", stage=2,
                          content="[Challenge] a\n[Challenge] b\n[Challenge] c\n[Challenge] d\nChanged because x",
                          model="m", elapsed_seconds=0.01)]

    async def _fake_stage1(*a, **kw): return s1
    async def _fake_stage2(*a, **kw): return s2
    async def _fake_stage3(*a, **kw):
        return MemberResponse(member_id="chairperson", stage=3, content="synth",
                              model="m", elapsed_seconds=0.01)
    async def _fake_stage4(*a, **kw): return None
    async def _fake_evidence(*a, **kw): return ({}, {})
    async def _fake_sotb_gov(*a, **kw):
        from server.memory.sotb_governance import SotbHealth
        return ("", SotbHealth())
    async def _fake_delegate(*a, **kw):
        return {"session_id": "t", "tasks": [], "warnings": [], "requires_approval": True,
                "structured_output_failed": False, "truncated": False}

    monkeypatch.setattr(orch, "stage1", _fake_stage1)
    monkeypatch.setattr(orch, "stage2", _fake_stage2)
    monkeypatch.setattr(orch, "stage3", _fake_stage3)
    monkeypatch.setattr(orch, "stage4_secretary_brief", _fake_stage4)
    monkeypatch.setattr(orch, "stage0_intake", lambda *a, **kw: ([], {"status": "not_required", "answers": {}}))
    monkeypatch.setattr(orch, "_collect_member_evidence", _fake_evidence)
    monkeypatch.setattr(orch, "build_delegation_plan", _fake_delegate)
    monkeypatch.setattr(orch_mod, "read_sotb_governed", _fake_sotb_gov)
    monkeypatch.setattr(orch_mod, "propose_memory_update",
                        lambda *a, **kw: {"proposed_sotb_update": None})

    # If these fire we'd crash since they're not patched — that's the assertion.
    fired = {"called": False}
    async def _trip(**kw):
        fired["called"] = True
        raise AssertionError("rebuttal fired despite verify=False")
    monkeypatch.setattr(auto_promote, "run_live_rebuttal", _trip)

    session = await orch.deliberate("q", skip_classify=True, verify=False)
    assert session.disagreement_score >= 4  # always computed
    assert fired["called"] is False
    assert session.auto_promoted_rebuttals == []
