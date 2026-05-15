"""ObservedSignals extraction tests."""
from __future__ import annotations

from server.board.deliberation.orchestrator import BoardSession, MemberResponse
from server.board.metrics import CallMetrics, SessionMetrics

from evals.signals import ObservedSignals, extract_signals


def _make_metrics() -> SessionMetrics:
    m = SessionMetrics()
    m.record(CallMetrics(member_id="strategist", stage=1, model="kimi/kimi-k2.6",
                         input_tokens=500, output_tokens=300, latency_seconds=2.1))
    m.record(CallMetrics(member_id="chairperson", stage=3, model="kimi/kimi-k2.6",
                         input_tokens=1200, output_tokens=800, latency_seconds=5.0))
    return m


def test_extract_signals_basic_session():
    session = BoardSession(
        session_id="board_test",
        user_query="anything",
        stage1_responses=[
            MemberResponse(member_id="strategist", stage=1, content="x", model="m", elapsed_seconds=2.1),
        ],
        stage2_responses=[],
        stage3_synthesis=MemberResponse(
            member_id="chairperson", stage=3, content="y", model="m", elapsed_seconds=5.0,
        ),
        metrics=_make_metrics(),
        verification={"score": 8, "passed": True, "deficiencies": []},
        clarification={"questions": [], "answers": {}},
        total_elapsed=7.1,
    )

    signals = extract_signals(session)

    assert isinstance(signals, ObservedSignals)
    assert signals.verifier_passed is True
    assert signals.verifier_score == 8
    assert signals.clarification_required is False
    assert signals.validate_claim_verdicts == []
    assert signals.contradictions_surfaced == 0  # not implemented at P0
    assert signals.blinded_verifier_per_claim == []  # not implemented at P0
    assert signals.total_latency_seconds == 7.1
    assert signals.total_tokens > 0
    assert signals.total_cost_usd >= 0.0


def test_extract_signals_verifier_failed():
    session = BoardSession(
        session_id="board_test", user_query="x",
        metrics=SessionMetrics(),
        verification={"score": 4, "passed": False,
                      "deficiencies": ["growth rate is unverified", "cite a source"]},
    )
    signals = extract_signals(session)
    assert signals.verifier_passed is False
    assert signals.verifier_score == 4
    assert "growth rate is unverified" in signals.verifier_deficiencies


def test_extract_signals_no_verification():
    """When Stage 4 didn't run, verifier_passed is None."""
    session = BoardSession(session_id="board_test", user_query="x", metrics=SessionMetrics())
    signals = extract_signals(session)
    assert signals.verifier_passed is None
    assert signals.verifier_score is None


def test_extract_signals_clarification_fired():
    session = BoardSession(
        session_id="board_test", user_query="x",
        metrics=SessionMetrics(),
        clarification={
            "questions": [{"prompt": "Which market?"}, {"prompt": "What timeframe?"}],
            "answers": {},
        },
    )
    signals = extract_signals(session)
    assert signals.clarification_required is True
    assert len(signals.clarification_questions) == 2


def test_extract_signals_validate_claim_verdicts_always_empty_at_p0():
    """Standard deliberate() makes no tool calls, so verdicts stay [] at P0.

    See plan §Architecture observability note. The field exists for
    forward-compat with P3 (which will persist tool calls).
    """
    session = BoardSession(
        session_id="board_test", user_query="x",
        metrics=SessionMetrics(),
    )
    signals = extract_signals(session)
    assert signals.validate_claim_verdicts == []


def test_observed_signals_from_dict_roundtrip():
    original = ObservedSignals(
        verifier_passed=True, verifier_score=8,
        verifier_deficiencies=["x"],
        clarification_required=True,
        clarification_questions=["which market?"],
        validate_claim_verdicts=[{"claim": "c", "verdict": "SUPPORTED"}],
        blinded_verifier_per_claim=[{"id": "c1", "verdict": "SUPPORTED"}],
        contradictions_surfaced=2,
        total_cost_usd=0.42, total_latency_seconds=12.5, total_tokens=3200,
    )
    rehydrated = ObservedSignals.from_dict(original.to_json())
    assert rehydrated == original
