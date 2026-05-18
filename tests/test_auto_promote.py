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


# ─── T3: pick_top_pairs ──────────────────────────────────────────────────────


def _claim(member_id: str, text: str) -> dict:
    """Minimal claim dict shape (matches AtomizedClaim.to_dict() subset
    actually used by pick_top_pairs)."""
    return {"member_id": member_id, "text": text, "evidence_refs": []}


def test_pick_top_pairs_returns_empty_when_no_signal():
    """No contradictions and no [Challenge] markers → no pairs to fire."""
    from server.board.deliberation.auto_promote import pick_top_pairs
    responses = [_resp("strategist", "plain"), _resp("product", "plain")]
    assert pick_top_pairs(responses, contradictions=[], max_pairs=2) == []


def test_pick_top_pairs_primary_path_uses_contradictions_severity():
    """When contradictions present, rank by severity (load_bearing > material)."""
    from server.board.deliberation.auto_promote import pick_top_pairs
    responses = [
        _resp("strategist", "[Challenge] product is wrong"),
        _resp("product", "no concession"),
        _resp("critic", "[Challenge] minor stuff"),
    ]
    contradictions = [
        {"topic": "topic-minor",
         "claim_a": _claim("strategist", "ttm rev = $50M"),
         "claim_b": _claim("critic",     "ttm rev = $80M"),
         "severity": "minor"},
        {"topic": "topic-load-bearing",
         "claim_a": _claim("strategist", "market growth 20% YoY"),
         "claim_b": _claim("product",    "market growth 10% YoY"),
         "severity": "load_bearing"},
    ]
    pairs = pick_top_pairs(responses, contradictions=contradictions, max_pairs=2)
    # load_bearing ranks first
    assert pairs[0]["severity"] == "load_bearing"
    assert set(pairs[0]["pair_member_ids"]) == {"strategist", "product"}
    assert pairs[0]["topic"] == "topic-load-bearing"
    # minor second
    assert pairs[1]["severity"] == "minor"
    assert set(pairs[1]["pair_member_ids"]) == {"strategist", "critic"}


def test_pick_top_pairs_dedupes_same_pair_across_contradictions():
    """Two contradictions on the same member pair → one slot, highest severity."""
    from server.board.deliberation.auto_promote import pick_top_pairs
    responses = [_resp("strategist", ""), _resp("product", "")]
    contradictions = [
        {"topic": "t1",
         "claim_a": _claim("strategist", "a1"), "claim_b": _claim("product", "b1"),
         "severity": "minor"},
        {"topic": "t2",
         "claim_a": _claim("strategist", "a2"), "claim_b": _claim("product", "b2"),
         "severity": "load_bearing"},  # same pair, higher severity
    ]
    pairs = pick_top_pairs(responses, contradictions=contradictions, max_pairs=2)
    assert len(pairs) == 1
    assert pairs[0]["severity"] == "load_bearing"
    assert pairs[0]["topic"] == "t2"


def test_pick_top_pairs_caps_at_max_pairs():
    """More candidate pairs than max_pairs → slice to max_pairs after rank."""
    from server.board.deliberation.auto_promote import pick_top_pairs
    responses = [
        _resp("strategist", ""), _resp("product", ""),
        _resp("critic", ""), _resp("architect", ""),
    ]
    contradictions = [
        {"topic": f"t{i}", "claim_a": _claim(a, "x"), "claim_b": _claim(b, "y"),
         "severity": "material"}
        for i, (a, b) in enumerate([
            ("strategist", "product"),
            ("strategist", "critic"),
            ("product", "architect"),
            ("critic", "architect"),
        ])
    ]
    pairs = pick_top_pairs(responses, contradictions=contradictions, max_pairs=2)
    assert len(pairs) == 2  # cap applied


def test_pick_top_pairs_fallback_when_no_contradictions():
    """Spec §9.2.7: contradictions empty, [Challenge] count > 0 → pick top-2
    most-challenged members; topic = first [Challenge] line."""
    from server.board.deliberation.auto_promote import pick_top_pairs
    responses = [
        _resp("strategist", "[Challenge] product is wrong\nmore\n[Challenge] product underweights X"),  # 2
        _resp("product", "[Challenge] strategist over-claims"),                # 1
        _resp("critic", "plain"),                                              # 0
    ]
    pairs = pick_top_pairs(responses, contradictions=[], max_pairs=2)
    assert len(pairs) == 1  # fallback returns at most one pair
    # strategist is most-challenged, product second
    assert set(pairs[0]["pair_member_ids"]) == {"strategist", "product"}
    assert pairs[0]["severity"] is None  # fallback has no severity
    # Topic = first [Challenge] line from the most-challenged member.
    assert "product is wrong" in pairs[0]["topic"]


def test_pick_top_pairs_fallback_returns_empty_when_no_challenge_signal():
    """If both lists are empty signal-wise, return empty (no fire)."""
    from server.board.deliberation.auto_promote import pick_top_pairs
    responses = [_resp("strategist", "plain"), _resp("product", "plain")]
    assert pick_top_pairs(responses, contradictions=[], max_pairs=2) == []


def test_pick_top_pairs_score_is_combined_challenge_count():
    """Pair score = sum of [Challenge] counts for both members across their
    Stage 2 responses. Used as a tiebreaker within a single severity tier."""
    from server.board.deliberation.auto_promote import pick_top_pairs
    responses = [
        _resp("strategist", "[Challenge] x [Challenge] y"),   # 2
        _resp("product", "[Challenge] z"),                    # 1
        _resp("critic", ""),                                  # 0
        _resp("architect", "[Challenge] a [Challenge] b [Challenge] c"),  # 3
    ]
    contradictions = [
        # both pairs are material — score breaks the tie. critic+architect (3)
        # should rank above strategist+product (3) by member_id alpha tiebreak
        # below; assert the higher-score pair wins.
        {"topic": "t-low",  "claim_a": _claim("strategist", "x"), "claim_b": _claim("critic", "y"),
         "severity": "material"},
        {"topic": "t-high", "claim_a": _claim("architect", "x"), "claim_b": _claim("product", "y"),
         "severity": "material"},
    ]
    pairs = pick_top_pairs(responses, contradictions=contradictions, max_pairs=2)
    # First entry should be the (architect, product) pair (combined score 3+1 = 4).
    assert pairs[0]["topic"] == "t-high"
    assert pairs[0]["score"] == 4


# ─── T4: summarize_rebuttal + format_rebuttal_outcomes_block ────────────────


@pytest.mark.asyncio
async def test_summarize_rebuttal_extracts_resolution_from_well_formed_output():
    """Happy path: summarizer model returns spec §9.2.6 format; parser
    extracts the Resolution: line and returns the full summary text."""
    from server.board import llm
    from server.board.deliberation import auto_promote

    fake_summary = (
        "REBUTTAL OUTCOME — Market sizing\n\n"
        "Resolution: PARTIAL\n\n"
        "Final positions:\n"
        "  Member A: Conceded the 2025 figure was outdated; now estimates 18–22% YoY.\n"
        "  Member B: Maintains 28–35% YoY.\n"
    )
    transcript = [
        {"role": "chair", "member_id": "chairperson", "content": "Open.", "tool_calls": []},
        {"role": "member_a", "member_id": "strategist", "content": "A says.", "tool_calls": []},
        {"role": "member_b", "member_id": "product", "content": "B says.", "tool_calls": []},
    ]
    with patch(
        "server.board.deliberation.auto_promote.query_llm",
        AsyncMock(return_value=llm.LLMResponse(
            content=fake_summary, model="m",
            input_tokens=100, output_tokens=80,
            latency_seconds=0.1, finish_reason="stop", tool_calls=[],
        )),
    ):
        summary, resolution, tokens_in, tokens_out = await auto_promote.summarize_rebuttal(
            transcript=transcript, topic="Market sizing",
            claim_a_text="A claim", claim_b_text="B claim",
            model="qwen/qwen3.6-plus",
        )

    assert resolution == "PARTIAL"
    assert "REBUTTAL OUTCOME" in summary
    assert "Conceded" in summary
    assert tokens_in == 100
    assert tokens_out == 80


@pytest.mark.asyncio
async def test_summarize_rebuttal_resolution_none_when_missing():
    """Malformed summarizer output (no Resolution: line) → resolution = None,
    summary still returned so the chair gets something."""
    from server.board import llm
    from server.board.deliberation import auto_promote

    with patch(
        "server.board.deliberation.auto_promote.query_llm",
        AsyncMock(return_value=llm.LLMResponse(
            content="Some prose without the expected block.",
            model="m", input_tokens=10, output_tokens=5,
            latency_seconds=0.1, finish_reason="stop", tool_calls=[],
        )),
    ):
        summary, resolution, _i, _o = await auto_promote.summarize_rebuttal(
            transcript=[], topic="t", claim_a_text="a", claim_b_text="b",
            model="m",
        )
    assert resolution is None
    assert "Some prose" in summary


@pytest.mark.asyncio
async def test_summarize_rebuttal_uppercases_resolution():
    """Resolution: 'resolved' (lowercase) → returns 'RESOLVED' canonical form."""
    from server.board import llm
    from server.board.deliberation import auto_promote

    with patch(
        "server.board.deliberation.auto_promote.query_llm",
        AsyncMock(return_value=llm.LLMResponse(
            content="Resolution: resolved\n\nFinal positions: x",
            model="m", input_tokens=1, output_tokens=1,
            latency_seconds=0.1, finish_reason="stop", tool_calls=[],
        )),
    ):
        _s, resolution, _i, _o = await auto_promote.summarize_rebuttal(
            transcript=[], topic="t", claim_a_text="a", claim_b_text="b",
            model="m",
        )
    assert resolution == "RESOLVED"


@pytest.mark.asyncio
async def test_summarize_rebuttal_invalid_resolution_returns_none():
    """Resolution: 'CONFUSED' (not in {RESOLVED, PARTIAL, UNRESOLVED}) → None."""
    from server.board import llm
    from server.board.deliberation import auto_promote

    with patch(
        "server.board.deliberation.auto_promote.query_llm",
        AsyncMock(return_value=llm.LLMResponse(
            content="Resolution: confused\n", model="m",
            input_tokens=1, output_tokens=1,
            latency_seconds=0.1, finish_reason="stop", tool_calls=[],
        )),
    ):
        _s, resolution, _i, _o = await auto_promote.summarize_rebuttal(
            transcript=[], topic="t", claim_a_text="a", claim_b_text="b",
            model="m",
        )
    assert resolution is None


def test_format_rebuttal_outcomes_block_empty_returns_empty_string():
    from server.board.deliberation.auto_promote import format_rebuttal_outcomes_block
    assert format_rebuttal_outcomes_block([]) == ""


def test_format_rebuttal_outcomes_block_renders_each_entry_with_header():
    from server.board.deliberation.auto_promote import format_rebuttal_outcomes_block
    entries = [
        {"summary": "REBUTTAL OUTCOME — Topic 1\nResolution: PARTIAL\n...",
         "topic": "Topic 1"},
        {"summary": "REBUTTAL OUTCOME — Topic 2\nResolution: RESOLVED\n...",
         "topic": "Topic 2"},
    ]
    block = format_rebuttal_outcomes_block(entries)
    assert "REBUTTAL OUTCOME (auto-promoted" in block  # spec §9.2.6 header
    assert "REBUTTAL OUTCOME — Topic 1" in block
    assert "REBUTTAL OUTCOME — Topic 2" in block
    # Entries separated by a divider line of some kind.
    assert block.count("REBUTTAL OUTCOME") >= 3  # 1 header + 2 entries


def test_format_rebuttal_outcomes_block_skips_partial_empty_entries():
    """Mixed: one usable entry + one empty-summary entry → header + 1 entry."""
    from server.board.deliberation.auto_promote import format_rebuttal_outcomes_block
    out = format_rebuttal_outcomes_block([
        {"summary": "REBUTTAL OUTCOME — A\nResolution: PARTIAL"},
        {"summary": ""},
    ])
    assert "REBUTTAL OUTCOME (auto-promoted" in out  # header survived
    # Only the usable entry was rendered (header + 1 entry).
    assert out.count("REBUTTAL OUTCOME") == 2


def test_format_rebuttal_outcomes_block_all_empty_returns_empty_string():
    """If every summarizer failed, suppress the misleading header — chair
    should not see a promise with no body."""
    from server.board.deliberation.auto_promote import format_rebuttal_outcomes_block
    assert format_rebuttal_outcomes_block([{"summary": ""}, {"summary": None}]) == ""


@pytest.mark.asyncio
async def test_summarize_rebuttal_uses_last_resolution_when_model_echoes_prompt():
    """Model echoes the prompt's `Resolution: <RESOLVED|...>` placeholder
    before producing its real answer → parser must skip the echo and read
    the trailing real value."""
    from server.board import llm
    from server.board.deliberation import auto_promote

    echoed = (
        "I will produce the structured outcome you requested.\n"
        "Resolution: <RESOLVED|PARTIAL|UNRESOLVED>\n"
        "\n"
        "REBUTTAL OUTCOME — Market sizing\n"
        "\n"
        "Resolution: PARTIAL\n"
    )
    with patch(
        "server.board.deliberation.auto_promote.query_llm",
        AsyncMock(return_value=llm.LLMResponse(
            content=echoed, model="m", input_tokens=1, output_tokens=1,
            latency_seconds=0.01, finish_reason="stop", tool_calls=[],
        )),
    ):
        _s, resolution, _i, _o = await auto_promote.summarize_rebuttal(
            transcript=[], topic="t", claim_a_text="a", claim_b_text="b",
            model="m",
        )
    assert resolution == "PARTIAL"


# ─── T5: _member_rebuttal_turn + run_live_rebuttal ──────────────────────────


from server.board.config import BoardMember


def _make_member(member_id: str, role: str = "strategist") -> BoardMember:
    return BoardMember(
        id=member_id, title=member_id.title(), role=role,
        expertise=[], system_prompt="You are a member.",
    )


def _make_session_with_persistence_field():
    """Build a minimal object that mimics BoardSession enough for the
    rebuttal persistence path. Avoids importing BoardSession to keep the
    test independent of orchestrator field additions."""
    from types import SimpleNamespace
    return SimpleNamespace(
        session_id="t",
        tool_call_results=[],
        stage1_responses=[],
    )


@pytest.mark.asyncio
async def test_member_rebuttal_turn_no_tool_call_returns_content_only():
    """Member's LLM produces text with no tool_call → returned as-is."""
    from server.board import llm
    from server.board.deliberation import auto_promote

    member = _make_member("strategist")
    session = _make_session_with_persistence_field()

    with patch(
        "server.board.deliberation.auto_promote.query_llm",
        AsyncMock(return_value=llm.LLMResponse(
            content="I stand by my position.",
            model="m", input_tokens=20, output_tokens=10,
            latency_seconds=0.1, finish_reason="stop", tool_calls=[],
        )),
    ):
        content, tcs, tokens_in, tokens_out = await auto_promote._member_rebuttal_turn(
            member=member, model="m",
            user_message="Defend.",
            session=session, stage=2,
        )
    assert content == "I stand by my position."
    assert tcs == []
    assert tokens_in == 20
    assert tokens_out == 10
    assert len(session.tool_call_results) == 0


@pytest.mark.asyncio
async def test_member_rebuttal_turn_executes_one_validate_claim_call():
    """Member's LLM emits a validate_claim tool_call; wrapper dispatches it
    once, persists the record, and feeds the result back for a final-message
    LLM call."""
    from server.board import llm, tools as tools_mod
    from server.board.deliberation import auto_promote

    member = _make_member("product")
    session = _make_session_with_persistence_field()

    responses = iter([
        llm.LLMResponse(
            content="", model="m", input_tokens=15, output_tokens=8,
            latency_seconds=0.1, finish_reason="tool_calls",
            tool_calls=[llm.ToolCall(
                id="tc1", name="validate_claim",
                arguments={"claim": "growth is 20% YoY"})],
        ),
        llm.LLMResponse(
            content="Validated. Standing by.",
            model="m", input_tokens=30, output_tokens=12,
            latency_seconds=0.1, finish_reason="stop", tool_calls=[],
        ),
    ])

    async def _fake_query(*a, **kw):
        return next(responses)

    async def _fake_validate(**kwargs):
        from server.board.tools import ToolResult
        return ToolResult(
            content_for_model="validate_claim('growth is 20% YoY'):\nVERDICT: SUPPORTED\nRATIONALE: ok\nKEY_SOURCES: x",
            summary="validate_claim: SUPPORTED",
            cost_units=2.0,
        )

    with patch(
        "server.board.deliberation.auto_promote.query_llm",
        AsyncMock(side_effect=_fake_query),
    ), patch.dict(
        tools_mod.TOOLS,
        {"validate_claim": tools_mod.Tool(
            name="validate_claim", description="d", parameters={},
            handler=_fake_validate,
        )},
        clear=False,
    ):
        content, tcs, tokens_in, tokens_out = await auto_promote._member_rebuttal_turn(
            member=member, model="m",
            user_message="Defend or concede.",
            session=session, stage=2,
        )
    assert content == "Validated. Standing by."
    assert len(tcs) == 1
    assert tcs[0]["tool_name"] == "validate_claim"
    assert tcs[0]["verdict"] == "SUPPORTED"
    # Persistence happened — session.tool_call_results got the same record.
    assert len(session.tool_call_results) == 1
    assert session.tool_call_results[0]["tool_name"] == "validate_claim"
    # Token totals sum across BOTH LLM calls.
    assert tokens_in == 45
    assert tokens_out == 20


@pytest.mark.asyncio
async def test_member_rebuttal_turn_caps_at_one_validate_claim_call():
    """Spec §9.2.4: member may call validate_claim max 1 time per round. If
    the LLM tries to call it a SECOND time in the same turn, the wrapper
    rejects via tool_choice='none' on the follow-up call."""
    from server.board import llm, tools as tools_mod
    from server.board.deliberation import auto_promote

    member = _make_member("product")
    session = _make_session_with_persistence_field()

    responses = iter([
        # First LLM call: requests validate_claim
        llm.LLMResponse(
            content="", model="m", input_tokens=10, output_tokens=5,
            latency_seconds=0.1, finish_reason="tool_calls",
            tool_calls=[llm.ToolCall(
                id="tc1", name="validate_claim",
                arguments={"claim": "first"})],
        ),
        # Second call: budget shows tool exhausted, model produces final text.
        llm.LLMResponse(
            content="Final position.",
            model="m", input_tokens=10, output_tokens=5,
            latency_seconds=0.1, finish_reason="stop", tool_calls=[],
        ),
    ])

    async def _fake_query(*a, **kw):
        return next(responses)

    async def _fake_validate(**kwargs):
        from server.board.tools import ToolResult
        return ToolResult(
            content_for_model="validate_claim('first'):\nVERDICT: UNVERIFIED\nRATIONALE: x\nKEY_SOURCES: y",
            summary="validate_claim: UNVERIFIED",
            cost_units=2.0,
        )

    with patch(
        "server.board.deliberation.auto_promote.query_llm",
        AsyncMock(side_effect=_fake_query),
    ), patch.dict(
        tools_mod.TOOLS,
        {"validate_claim": tools_mod.Tool(
            name="validate_claim", description="d", parameters={},
            handler=_fake_validate,
        )},
        clear=False,
    ):
        content, tcs, _i, _o = await auto_promote._member_rebuttal_turn(
            member=member, model="m",
            user_message="Defend.",
            session=session, stage=2,
        )
    assert content == "Final position."
    # Exactly one validate_claim record despite two LLM iterations.
    assert len(tcs) == 1


@pytest.mark.asyncio
async def test_run_live_rebuttal_two_rounds_no_early_close():
    """Full mock-driven rebuttal: opening + 2 rounds × (chair→A, A, chair→B, B)
    = 1 + 8 = 9 chair/member LLM calls. Member turns produce content with no
    tool calls. closed_early = False."""
    from server.board import llm
    from server.board.deliberation import auto_promote

    chair = _make_member("chairperson", role="chair")
    member_a = _make_member("strategist")
    member_b = _make_member("product")
    session = _make_session_with_persistence_field()

    # Scripted responses for every LLM call in order:
    #   opening (chair)
    #   round 1:  chair→A | member A | chair→B | member B
    #   round 2:  chair→A | member A | chair→B | member B
    chair_texts = [
        "Opening: contested claim is X.",
        "Member A, defend.", "Member B, respond.",
        "Member A, defend again.", "Member B, respond again.",
    ]
    a_texts = ["A round 1", "A round 2"]
    b_texts = ["B round 1", "B round 2"]

    # Interleave the expected order:
    call_log: list[str] = []

    def _next_response(*a, **kw) -> llm.LLMResponse:
        sys = (kw.get("system") or "") if "system" in kw else (a[2] if len(a) > 2 else "")
        msgs = kw.get("messages") if "messages" in kw else (a[1] if len(a) > 1 else [])
        # Use the system prompt to pick which queue to draw from. Chair turns
        # are dispatched with the moderator-suffixed chair system prompt
        # (CHAIR_MODERATOR_SUFFIX includes "chairperson moderating"); member
        # turns use the member's own system prompt ("You are a member.").
        if "moderating" in (sys or "").lower():
            text = chair_texts.pop(0)
            call_log.append(f"chair:{text}")
        else:
            # Member turn — first time wakes A, second time wakes B per call order
            # We can't easily distinguish A vs B by system_prompt in this fake;
            # use a deterministic call-order index instead.
            if len(a_texts) >= len(b_texts):
                text = a_texts.pop(0)
                call_log.append(f"a:{text}")
            else:
                text = b_texts.pop(0)
                call_log.append(f"b:{text}")
        return llm.LLMResponse(
            content=text, model="m",
            input_tokens=5, output_tokens=3,
            latency_seconds=0.01, finish_reason="stop", tool_calls=[],
        )

    with patch(
        "server.board.deliberation.auto_promote.query_llm",
        AsyncMock(side_effect=_next_response),
    ):
        result = await auto_promote.run_live_rebuttal(
            chair_member=chair, chair_model="m",
            member_a=member_a, member_a_model="m",
            member_b=member_b, member_b_model="m",
            topic="X", claim_a_text="A says", claim_b_text="B says",
            session=session, max_rounds=2,
            on_event=lambda e: None,
        )
    transcript = result["transcript"]
    # Opening + 2 rounds × 4 turns = 9 turns
    assert len(transcript) == 9
    # Opening is chair
    assert transcript[0]["role"] == "chair"
    # Members alternate
    member_roles = [t["role"] for t in transcript if t["role"] in ("member_a", "member_b")]
    assert member_roles == ["member_a", "member_b", "member_a", "member_b"]
    assert result["tokens_in"] == 5 * 9
    assert result["tokens_out"] == 3 * 9
    assert result["closed_early"] is False


@pytest.mark.asyncio
async def test_run_live_rebuttal_short_circuits_on_rebuttal_closed():
    """Chair emits 'REBUTTAL CLOSED' in round 1's last chair statement →
    loop breaks before starting round 2."""
    from server.board import llm
    from server.board.deliberation import auto_promote

    chair = _make_member("chairperson", role="chair")
    member_a = _make_member("strategist")
    member_b = _make_member("product")
    session = _make_session_with_persistence_field()

    responses = iter([
        # opening
        llm.LLMResponse(
            content="Opening.", model="m", input_tokens=1, output_tokens=1,
            latency_seconds=0.01, finish_reason="stop", tool_calls=[],
        ),
        # chair → A
        llm.LLMResponse(
            content="A, go.", model="m", input_tokens=1, output_tokens=1,
            latency_seconds=0.01, finish_reason="stop", tool_calls=[],
        ),
        # member A
        llm.LLMResponse(
            content="A position.", model="m", input_tokens=1, output_tokens=1,
            latency_seconds=0.01, finish_reason="stop", tool_calls=[],
        ),
        # chair → B (includes REBUTTAL CLOSED — short-circuit after this round)
        llm.LLMResponse(
            content="B, respond. REBUTTAL CLOSED.",
            model="m", input_tokens=1, output_tokens=1,
            latency_seconds=0.01, finish_reason="stop", tool_calls=[],
        ),
        # member B
        llm.LLMResponse(
            content="B position.", model="m", input_tokens=1, output_tokens=1,
            latency_seconds=0.01, finish_reason="stop", tool_calls=[],
        ),
        # If round 2 starts, the next call would dequeue here and the test
        # would fail with StopIteration — proving early exit.
    ])

    async def _fake(*a, **kw):
        return next(responses)

    with patch(
        "server.board.deliberation.auto_promote.query_llm",
        AsyncMock(side_effect=_fake),
    ):
        result = await auto_promote.run_live_rebuttal(
            chair_member=chair, chair_model="m",
            member_a=member_a, member_a_model="m",
            member_b=member_b, member_b_model="m",
            topic="X", claim_a_text="A", claim_b_text="B",
            session=session, max_rounds=2,
            on_event=lambda e: None,
        )
    assert result["closed_early"] is True
    # 5 turns: opening + round1's 4 turns; round 2 skipped.
    assert len(result["transcript"]) == 5
