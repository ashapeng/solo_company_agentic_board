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
    """Spec §9.2.4: member may call validate_claim max 1 time per round.
    Even if the model's follow-up response tries to emit ANOTHER
    validate_claim tool_call, the structural cap (follow-up call uses
    tools=None + tool_choice='none') means it's silently dropped — only
    one tool_call_record lands. Also asserts the follow-up `query_llm`
    invocation received tools=None / tool_choice='none' so a counter-based
    refactor that relaxed the cap would fail this test."""
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
        # Follow-up call: model TRIES to emit another validate_claim, but
        # since we passed tool_choice="none", a well-behaved provider would
        # return content only. We script a misbehaving model to prove the
        # call's tool_calls are NEVER iterated/dispatched by the helper.
        llm.LLMResponse(
            content="Final position after one validate.",
            model="m", input_tokens=10, output_tokens=5,
            latency_seconds=0.1, finish_reason="stop",
            tool_calls=[llm.ToolCall(
                id="tc2", name="validate_claim",
                arguments={"claim": "second (should be ignored)"})],
        ),
    ])

    captured_calls: list[dict] = []

    async def _fake_query(*a, **kw):
        captured_calls.append({
            "tools": kw.get("tools"),
            "tool_choice": kw.get("tool_choice"),
        })
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
    assert content == "Final position after one validate."
    # Exactly one validate_claim record despite the follow-up's misbehaving
    # tool_call — proves the structural cap is structural, not counter-based.
    assert len(tcs) == 1
    assert len(session.tool_call_results) == 1
    # Structural-cap proof: the second query_llm invocation was passed
    # tools=None + tool_choice="none", so the provider couldn't dispatch
    # another tool even if the LLM tried.
    assert len(captured_calls) == 2
    assert captured_calls[1]["tools"] is None
    assert captured_calls[1]["tool_choice"] == "none"


@pytest.mark.asyncio
async def test_run_live_rebuttal_two_rounds_no_early_close():
    """Full mock-driven rebuttal: opening + 2 rounds × (chair→A, A, chair→B, B)
    = 1 + 8 = 9 chair/member LLM calls. Member turns produce content with no
    tool calls. closed_early = False. Routes calls to A/B queues by
    matching the member's system_prompt (not call order) so the test is
    robust against an A-before-B order flip."""
    from server.board import llm
    from server.board.deliberation import auto_promote
    from server.board.config import BoardMember

    chair = BoardMember(
        id="chairperson", title="Chairperson", role="chair",
        expertise=[], system_prompt="You are the chair (base prompt).",
    )
    member_a = BoardMember(
        id="strategist", title="Strategist", role="strategist",
        expertise=[], system_prompt="MEMBER A IDENTITY.",
    )
    member_b = BoardMember(
        id="product", title="Product", role="product",
        expertise=[], system_prompt="MEMBER B IDENTITY.",
    )
    session = _make_session_with_persistence_field()

    chair_texts = [
        "Opening: contested claim is X.",
        "Member A, defend.", "Member B, respond.",
        "Member A, defend again.", "Member B, respond again.",
    ]
    a_texts = ["A round 1", "A round 2"]
    b_texts = ["B round 1", "B round 2"]

    def _next_response(*a, **kw) -> llm.LLMResponse:
        sys = (kw.get("system") or "") if "system" in kw else (a[2] if len(a) > 2 else "")
        lower = (sys or "").lower()
        # Chair turn: moderator suffix contains "moderating".
        if "moderating" in lower:
            text = chair_texts.pop(0)
        # Route by member identity in system_prompt — no call-order coupling.
        elif "member a identity" in lower:
            text = a_texts.pop(0)
        elif "member b identity" in lower:
            text = b_texts.pop(0)
        else:
            raise AssertionError(f"unrecognized system prompt: {sys!r}")
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
    assert transcript[0]["role"] == "chair"
    # Members alternate
    member_roles = [t["role"] for t in transcript if t["role"] in ("member_a", "member_b")]
    assert member_roles == ["member_a", "member_b", "member_a", "member_b"]
    # Member content matches the identity-routed queue, not call order.
    member_a_turns = [t["content"] for t in transcript if t["role"] == "member_a"]
    assert member_a_turns == ["A round 1", "A round 2"]
    member_b_turns = [t["content"] for t in transcript if t["role"] == "member_b"]
    assert member_b_turns == ["B round 1", "B round 2"]
    assert result["tokens_in"] == 5 * 9
    assert result["tokens_out"] == 3 * 9
    assert result["closed_early"] is False


@pytest.mark.asyncio
async def test_run_live_rebuttal_short_circuits_on_rebuttal_closed():
    """Chair emits 'REBUTTAL CLOSED' on the chair→B turn → loop breaks
    BEFORE member B speaks (saving one LLM call). Transcript has 4 turns:
    opening + chair→A + member A + chair→B (with CLOSED). Round 2 skipped."""
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
        # chair → B (includes REBUTTAL CLOSED — break immediately, skip member B)
        llm.LLMResponse(
            content="B, respond. REBUTTAL CLOSED.",
            model="m", input_tokens=1, output_tokens=1,
            latency_seconds=0.01, finish_reason="stop", tool_calls=[],
        ),
        # If member B or round 2 starts, the next call would dequeue here and
        # the test would fail with StopIteration — proving the saved call.
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
    # 4 turns: opening + chair→A + member A + chair→B (with CLOSED).
    # Member B and round 2 skipped — saving up to 5 LLM calls vs naive end-of-round check.
    assert len(result["transcript"]) == 4
    # No member_b turn ever recorded.
    assert all(t["role"] != "member_b" for t in result["transcript"])


@pytest.mark.asyncio
async def test_run_live_rebuttal_short_circuits_when_opening_signals_closed():
    """Edge case: chair's opening turn emits REBUTTAL CLOSED. No rounds run."""
    from server.board import llm
    from server.board.deliberation import auto_promote

    chair = _make_member("chairperson", role="chair")
    member_a = _make_member("strategist")
    member_b = _make_member("product")
    session = _make_session_with_persistence_field()

    responses = iter([
        llm.LLMResponse(
            content="Both members already agree. REBUTTAL CLOSED.",
            model="m", input_tokens=1, output_tokens=1,
            latency_seconds=0.01, finish_reason="stop", tool_calls=[],
        ),
        # No further calls expected — any next call raises StopIteration.
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
    assert len(result["transcript"]) == 1  # opening only
    assert result["transcript"][0]["role"] == "chair"


@pytest.mark.asyncio
async def test_run_live_rebuttal_degrades_on_llm_failure():
    """If a chair turn's LLM call raises, the rebuttal returns whatever
    partial transcript accumulated (degraded). Critical for production:
    the spec wants a partial REBUTTAL OUTCOME, not a kill of the whole
    Stage 2 → Stage 3 path."""
    from server.board.deliberation import auto_promote

    chair = _make_member("chairperson", role="chair")
    member_a = _make_member("strategist")
    member_b = _make_member("product")
    session = _make_session_with_persistence_field()

    call_count = {"n": 0}

    async def _fake(*a, **kw):
        call_count["n"] += 1
        # First call (opening) raises — the rebuttal must NOT propagate.
        raise RuntimeError("provider unreachable")

    with patch(
        "server.board.deliberation.auto_promote.query_llm",
        AsyncMock(side_effect=_fake),
    ):
        result = await auto_promote.run_live_rebuttal(
            chair_member=chair, chair_model="m",
            member_a=member_a, member_a_model="m",
            member_b=member_b, member_b_model="m",
            topic="t", claim_a_text="a", claim_b_text="b",
            session=session, max_rounds=2,
            on_event=lambda e: None,
        )
    # We get a transcript shape back, with an empty opening (LLM failed).
    assert "transcript" in result
    # At minimum the opening entry exists (with empty content from failure).
    assert len(result["transcript"]) >= 1
    assert result["transcript"][0]["content"] == ""


@pytest.mark.asyncio
async def test_run_live_rebuttal_surfaces_evidence_refs_in_moderator_prompt():
    """Spec §9.2.3 requires (Cited: <refs>) lines in the chair's moderator
    prompt. Capture the system prompt of the first query_llm call and assert
    both members' evidence refs are present."""
    from server.board import llm
    from server.board.deliberation import auto_promote

    chair = _make_member("chairperson", role="chair")
    member_a = _make_member("strategist")
    member_b = _make_member("product")
    session = _make_session_with_persistence_field()

    captured_systems: list[str] = []

    async def _capture(*a, **kw):
        sys = kw.get("system", "") if "system" in kw else (a[2] if len(a) > 2 else "")
        captured_systems.append(sys or "")
        return llm.LLMResponse(
            content="ok", model="m", input_tokens=1, output_tokens=1,
            latency_seconds=0.01, finish_reason="stop", tool_calls=[],
        )

    with patch(
        "server.board.deliberation.auto_promote.query_llm",
        AsyncMock(side_effect=_capture),
    ):
        await auto_promote.run_live_rebuttal(
            chair_member=chair, chair_model="m",
            member_a=member_a, member_a_model="m",
            member_b=member_b, member_b_model="m",
            topic="market growth",
            claim_a_text="20% YoY",
            claim_b_text="10% YoY",
            claim_a_evidence_refs=["https://bloomberg.com/a", "https://reuters.com/b"],
            claim_b_evidence_refs=["https://wsj.com/c"],
            session=session, max_rounds=1,  # one round = 5 calls; smaller test
            on_event=lambda e: None,
        )

    moderator_systems = [s for s in captured_systems if "moderating" in s.lower()]
    assert moderator_systems, "no chair turn captured"
    sample = moderator_systems[0]
    assert "bloomberg.com/a" in sample
    assert "reuters.com/b" in sample
    assert "wsj.com/c" in sample
    # Defaults render as [UNVERIFIED] when refs aren't passed.
    assert "[UNVERIFIED]" not in sample  # both sides had real refs


@pytest.mark.asyncio
async def test_run_live_rebuttal_evidence_refs_default_to_unverified():
    """When evidence_refs aren't passed, the prompt renders [UNVERIFIED]."""
    from server.board import llm
    from server.board.deliberation import auto_promote

    chair = _make_member("chairperson", role="chair")
    member_a = _make_member("strategist")
    member_b = _make_member("product")
    session = _make_session_with_persistence_field()

    captured_systems: list[str] = []

    async def _capture(*a, **kw):
        sys = kw.get("system", "") if "system" in kw else (a[2] if len(a) > 2 else "")
        captured_systems.append(sys or "")
        return llm.LLMResponse(
            content="ok", model="m", input_tokens=1, output_tokens=1,
            latency_seconds=0.01, finish_reason="stop", tool_calls=[],
        )

    with patch(
        "server.board.deliberation.auto_promote.query_llm",
        AsyncMock(side_effect=_capture),
    ):
        await auto_promote.run_live_rebuttal(
            chair_member=chair, chair_model="m",
            member_a=member_a, member_a_model="m",
            member_b=member_b, member_b_model="m",
            topic="t", claim_a_text="a", claim_b_text="b",
            # no evidence refs
            session=session, max_rounds=1,
            on_event=lambda e: None,
        )

    moderator_systems = [s for s in captured_systems if "moderating" in s.lower()]
    assert moderator_systems
    # Both sides should render [UNVERIFIED]
    assert moderator_systems[0].count("[UNVERIFIED]") == 2
