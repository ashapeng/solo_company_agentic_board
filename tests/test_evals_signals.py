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


def test_extract_signals_populates_blinded_verifier_per_claim():
    """When session.verification has per_claim entries (BlindedVerificationResult), they
    surface as ObservedSignals.blinded_verifier_per_claim."""
    session = BoardSession(
        session_id="board_test", user_query="x",
        metrics=SessionMetrics(),
        verification={
            "score": 3, "passed": False,
            "deficiencies": ["CONTRADICTED - \"X grew 30%\" - source says 10%"],
            "suggestions": [],
            "per_claim": [
                {"claim_id": "a", "claim_text": "X grew 30%",
                 "verdict": "CONTRADICTED", "rationale": "source says 10%",
                 "evidence_refs": ["https://example.com"]},
                {"claim_id": "b", "claim_text": "Y is in Paris",
                 "verdict": "SUPPORTED", "rationale": "confirmed",
                 "evidence_refs": ["https://example.com/p"]},
            ],
            "contradicted_count": 1, "unverified_count": 0, "supported_count": 1,
        },
    )
    signals = extract_signals(session)
    assert len(signals.blinded_verifier_per_claim) == 2
    assert signals.blinded_verifier_per_claim[0]["verdict"] == "CONTRADICTED"
    assert "source says 10%" in signals.blinded_verifier_per_claim[0]["rationale"]


def test_extract_signals_blinded_per_claim_absent_when_checklist_fallback():
    """Old checklist verifier sets no per_claim — field stays empty."""
    session = BoardSession(
        session_id="board_test", user_query="x",
        metrics=SessionMetrics(),
        verification={
            "score": 8, "passed": True, "deficiencies": [], "suggestions": [],
            # no per_claim key
        },
    )
    signals = extract_signals(session)
    assert signals.blinded_verifier_per_claim == []


def test_extract_signals_counts_synthesis_unverified_tags():
    """[UNVERIFIED] markers in the chair synthesis are counted so the eval can
    tell when the chair appropriately deferred rather than fabricated."""
    session = BoardSession(
        session_id="board_test", user_query="2026 MAU?",
        metrics=SessionMetrics(),
        verification={"score": 7, "passed": True, "deficiencies": [], "suggestions": []},
        stage3_synthesis=MemberResponse(
            member_id="chairperson", stage=3,
            content=(
                "## Board Decision\n"
                "- Anthropic doesn't disclose MAU [UNVERIFIED].\n"
                "- 2026 estimates vary widely [UNVERIFIED].\n"
                "- Action: defer until Q3 data lands [UNVERIFIED].\n"
            ),
            model="kimi", elapsed_seconds=0.1,
        ),
    )
    signals = extract_signals(session)
    assert signals.synthesis_unverified_count == 3


def test_extract_signals_counts_zero_unverified_when_no_synthesis():
    """No stage3 → 0 unverified markers (no crash)."""
    session = BoardSession(session_id="board_test", user_query="x", metrics=SessionMetrics())
    signals = extract_signals(session)
    assert signals.synthesis_unverified_count == 0


def test_observed_signals_roundtrip_includes_unverified_count():
    original = ObservedSignals(verifier_passed=True, synthesis_unverified_count=5)
    rehydrated = ObservedSignals.from_dict(original.to_json())
    assert rehydrated.synthesis_unverified_count == 5


def test_extract_signals_populates_contradictions_surfaced():
    """When session.contradictions has entries (P2 detector fired), the eval
    signal counts them so cross_member_conflict checker can pass."""
    session = BoardSession(
        session_id="board_test", user_query="x",
        metrics=SessionMetrics(),
        contradictions=[
            {"topic": "EV growth", "claim_a": {"member_id": "a"},
             "claim_b": {"member_id": "b"}, "severity": "material"},
            {"topic": "MAU", "claim_a": {"member_id": "c"},
             "claim_b": {"member_id": "d"}, "severity": "load_bearing"},
        ],
    )
    signals = extract_signals(session)
    assert signals.contradictions_surfaced == 2


def test_extract_signals_contradictions_zero_when_field_absent():
    """No contradictions on session → count stays 0 (no crash)."""
    session = BoardSession(session_id="board_test", user_query="x", metrics=SessionMetrics())
    signals = extract_signals(session)
    assert signals.contradictions_surfaced == 0


def test_source_quality_trap_checker_passes_when_verdict_downgraded():
    """End-to-end signal flow: when validate_claim returned a downgraded
    UNVERIFIED verdict for the trap claim, _check_source_quality_trap passes.

    This is the unit-level exercise of the path P3a unlocks. The orchestrator
    does not yet persist tool-call verdicts onto the session (separate
    workstream), so a live eval still records 0 here. This test ensures the
    checker correctly credits a downgraded verdict whenever those verdicts
    DO land on the signal."""
    from evals.corpus import EvalPrompt
    from evals.metrics import check_signal_for_prompt
    from evals.signals import ObservedSignals

    prompt = EvalPrompt(
        id="source-001",
        category="source_quality_trap",
        query="What's the conversion rate for AI demos?",
        tier="heavy",
        planted={"kind": "numeric"},
        expected_outcome={"claim_substring": "conversion rate", "validate_claim_verdict_not_supported": True},
    )

    signals = ObservedSignals(
        validate_claim_verdicts=[
            {
                "claim": "average conversion rate from AI demo signup to paid is 8%",
                "verdict": "UNVERIFIED",
                "rationale": "insufficient source authority — found 3 unknown; need ≥1 academic OR ≥2 major_news OR ≥3 established_blog",
            },
        ],
    )

    assert check_signal_for_prompt(prompt, signals) is True


def test_source_quality_trap_checker_fails_when_verdict_still_supported():
    """Sanity: if the downgrade did NOT happen and the verdict stays SUPPORTED,
    the checker correctly reports a failure."""
    from evals.corpus import EvalPrompt
    from evals.metrics import check_signal_for_prompt
    from evals.signals import ObservedSignals

    prompt = EvalPrompt(
        id="source-001",
        category="source_quality_trap",
        query="x",
        tier="heavy",
        planted={"kind": "numeric"},
        expected_outcome={"claim_substring": "conversion rate", "validate_claim_verdict_not_supported": True},
    )
    signals = ObservedSignals(
        validate_claim_verdicts=[
            {"claim": "conversion rate is 8%", "verdict": "SUPPORTED", "rationale": "ok"},
        ],
    )
    assert check_signal_for_prompt(prompt, signals) is False


def test_board_session_tool_call_results_defaults_empty():
    """New BoardSession ships with tool_call_results == []."""
    session = BoardSession(session_id="board_test", user_query="x")
    assert session.tool_call_results == []


def test_board_session_to_dict_includes_tool_call_results_roundtrip():
    """When tool_call_results carries entries, they survive to_dict()."""
    entry = {
        "member_id": "strategist",
        "stage": 1,
        "tool_name": "validate_claim",
        "tool_call_id": "tc_1",
        "arguments": {"claim": "X is 8%"},
        "summary": "validate_claim: UNVERIFIED",
        "content_for_model": "VERDICT: UNVERIFIED ...",
        "verdict": "UNVERIFIED",
        "error": None,
        "elapsed_seconds": 1.23,
        "timestamp": "2026-05-17T00:00:00+00:00",
    }
    session = BoardSession(
        session_id="board_test", user_query="x",
        tool_call_results=[entry],
    )
    d = session.to_dict()
    assert "tool_call_results" in d
    assert d["tool_call_results"] == [entry]


def test_extract_signals_populates_validate_claim_verdicts_from_session():
    """When session.tool_call_results carries validate_claim entries,
    extract_signals surfaces them on ObservedSignals.validate_claim_verdicts
    in the shape the checker expects (claim, verdict, rationale)."""
    session = BoardSession(
        session_id="board_test", user_query="x",
        metrics=SessionMetrics(),
        tool_call_results=[
            {
                "member_id": "strategist", "stage": 1,
                "tool_name": "validate_claim", "tool_call_id": "tc_1",
                "arguments": {"claim": "average conversion rate from AI demo signup to paid is 8%"},
                "summary": "validate_claim: UNVERIFIED",
                "content_for_model": "VERDICT: SUPPORTED ... [SOURCE-AUTHORITY DOWNGRADE] ...",
                "verdict": "UNVERIFIED",
                "error": None, "elapsed_seconds": 1.0,
                "timestamp": "2026-05-17T00:00:00+00:00",
            },
        ],
    )
    signals = extract_signals(session)
    assert len(signals.validate_claim_verdicts) == 1
    entry = signals.validate_claim_verdicts[0]
    assert entry["claim"] == "average conversion rate from AI demo signup to paid is 8%"
    assert entry["verdict"] == "UNVERIFIED"
    assert "validate_claim" in entry["rationale"] or entry["rationale"] != ""


def test_extract_signals_skips_non_validate_claim_tool_results():
    """web_search / fetch_url / open_browser entries on tool_call_results
    are NOT surfaced as validate_claim_verdicts."""
    session = BoardSession(
        session_id="board_test", user_query="x",
        metrics=SessionMetrics(),
        tool_call_results=[
            {"member_id": "x", "stage": 1, "tool_name": "web_search",
             "tool_call_id": "tc_1", "arguments": {"query": "q"},
             "summary": "web_search 'q' → 3 results",
             "content_for_model": "...", "verdict": None, "error": None,
             "elapsed_seconds": 0.5, "timestamp": "2026-05-17T00:00:00+00:00"},
            {"member_id": "x", "stage": 1, "tool_name": "fetch_url",
             "tool_call_id": "tc_2", "arguments": {"url": "https://x"},
             "summary": "fetched", "content_for_model": "...",
             "verdict": None, "error": None,
             "elapsed_seconds": 0.5, "timestamp": "2026-05-17T00:00:00+00:00"},
        ],
    )
    signals = extract_signals(session)
    assert signals.validate_claim_verdicts == []


def test_extract_signals_validate_claim_verdicts_empty_when_field_absent():
    """Sessions without tool_call_results (e.g. from older saved JSONs)
    fall back to []. No crash."""
    session = BoardSession(session_id="board_test", user_query="x",
                            metrics=SessionMetrics())
    delattr(session, "tool_call_results")
    signals = extract_signals(session)
    assert signals.validate_claim_verdicts == []


def test_extract_signals_validate_claim_verdicts_handles_missing_claim_arg():
    """Defensive: if arguments lacks 'claim' (malformed record), the
    extractor must not crash. Surfaces an empty string claim and lets the
    checker decline to match."""
    session = BoardSession(
        session_id="board_test", user_query="x",
        metrics=SessionMetrics(),
        tool_call_results=[
            {"member_id": "x", "stage": 1, "tool_name": "validate_claim",
             "tool_call_id": "tc", "arguments": {},  # no 'claim' key
             "summary": "validate_claim: UNVERIFIED",
             "content_for_model": "...", "verdict": "UNVERIFIED",
             "error": None, "elapsed_seconds": 0.5,
             "timestamp": "2026-05-17T00:00:00+00:00"},
        ],
    )
    signals = extract_signals(session)
    assert len(signals.validate_claim_verdicts) == 1
    assert signals.validate_claim_verdicts[0]["claim"] == ""


def test_source_quality_trap_checker_passes_when_signal_built_from_session():
    """End-to-end signal flow: session carries a downgraded validate_claim
    record → extract_signals populates validate_claim_verdicts → the
    _check_source_quality_trap checker passes.

    This is the session-driven companion to the existing P3a regression-guard
    tests (which constructed ObservedSignals directly). It exercises the
    full path this plan unlocks."""
    from evals.corpus import EvalPrompt
    from evals.metrics import check_signal_for_prompt

    prompt = EvalPrompt(
        id="source-001",
        category="source_quality_trap",
        query="What's the conversion rate for AI demos?",
        tier="heavy",
        planted={"kind": "numeric"},
        expected_outcome={
            "claim_substring": "conversion rate",
            "validate_claim_verdict_not_supported": True,
        },
    )

    session = BoardSession(
        session_id="board_test", user_query=prompt.query,
        metrics=SessionMetrics(),
        tool_call_results=[
            {"member_id": "strategist", "stage": 1,
             "tool_name": "validate_claim", "tool_call_id": "tc_v",
             "arguments": {"claim": "average conversion rate from AI demo signup is 8%"},
             "summary": "validate_claim: UNVERIFIED",
             "content_for_model": (
                 "VERDICT: SUPPORTED\nRATIONALE: ok\n"
                 "[SOURCE-AUTHORITY DOWNGRADE] insufficient source authority."
             ),
             "verdict": "UNVERIFIED", "error": None, "elapsed_seconds": 1.0,
             "timestamp": "2026-05-17T00:00:00+00:00"},
        ],
    )

    signals = extract_signals(session)
    assert check_signal_for_prompt(prompt, signals) is True


def test_extract_signals_populates_sotb_health_warnings_from_session():
    """When session.sotb_health is populated, ObservedSignals surfaces the count."""
    session = BoardSession(
        session_id="board_test", user_query="x",
        metrics=SessionMetrics(),
    )
    session.sotb_health = {
        "expired": [{"entry_id": "a" * 12}],
        "low_confidence": [{"entry_id": "b" * 12}, {"entry_id": "c" * 12}],
        "stale": [],
        "query_conflicts": [],
        "conflicts_logged": [],
        "warnings_count": 3,
    }
    signals = extract_signals(session)
    assert signals.sotb_health_warnings == 3


def test_extract_signals_sotb_health_warnings_defaults_zero_when_missing():
    """Legacy session with no sotb_health attribute → signal is 0."""
    session = BoardSession(
        session_id="board_test", user_query="x",
        metrics=SessionMetrics(),
    )
    # Don't touch session.sotb_health (default None).
    signals = extract_signals(session)
    assert signals.sotb_health_warnings == 0


def test_observed_signals_p5b_defaults():
    s = ObservedSignals()
    assert s.auto_promoted_rebuttals_count == 0
    assert s.auto_promoted_resolutions == []
    assert s.disagreement_score == 0


def test_observed_signals_p5b_to_json_round_trip():
    s = ObservedSignals(
        auto_promoted_rebuttals_count=2,
        auto_promoted_resolutions=["PARTIAL", "RESOLVED"],
        disagreement_score=7,
    )
    d = s.to_json()
    assert d["auto_promoted_rebuttals_count"] == 2
    assert d["auto_promoted_resolutions"] == ["PARTIAL", "RESOLVED"]
    assert d["disagreement_score"] == 7
    back = ObservedSignals.from_dict(d)
    assert back.auto_promoted_rebuttals_count == 2
    assert back.auto_promoted_resolutions == ["PARTIAL", "RESOLVED"]
    assert back.disagreement_score == 7


def test_extract_signals_reads_p5b_fields_from_session():
    s = BoardSession(
        session_id="t", user_query="x",
        disagreement_score=5,
        auto_promoted_rebuttals=[
            {"pair_member_ids": ["strategist", "product"],
             "resolution": "PARTIAL", "summary": "..."},
            {"pair_member_ids": ["critic", "architect"],
             "resolution": "RESOLVED", "summary": "..."},
            {"pair_member_ids": ["x", "y"],
             "resolution": None, "summary": "(bad parse)"},  # excluded from list
        ],
    )
    sig = extract_signals(s)
    assert sig.disagreement_score == 5
    assert sig.auto_promoted_rebuttals_count == 3   # raw count
    # Only non-None resolutions surfaced
    assert sig.auto_promoted_resolutions == ["PARTIAL", "RESOLVED"]


def test_extract_signals_back_compat_with_session_missing_p5b_fields():
    """A SimpleNamespace mimicking pre-P5b session shape (no new fields)
    must return defaults, not raise."""
    from types import SimpleNamespace
    from server.board.metrics import SessionMetrics
    legacy = SimpleNamespace(
        session_id="t", user_query="x",
        verification=None,
        clarification={},
        stage3_synthesis=None,
        contradictions=[],
        sotb_health=None,
        tool_call_results=[],
        metrics=SessionMetrics(),
        total_elapsed=0.0,
    )
    sig = extract_signals(legacy)
    assert sig.disagreement_score == 0
    assert sig.auto_promoted_rebuttals_count == 0
    assert sig.auto_promoted_resolutions == []
