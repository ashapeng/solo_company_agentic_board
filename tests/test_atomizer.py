"""Atomizer unit tests."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from server.board.deliberation.atomizer import (
    AtomizedClaim,
    AtomizerError,
    atomize,
    build_atomizer_prompt,
)
from server.board.llm import LLMResponse


def _resp(text: str) -> LLMResponse:
    return LLMResponse(
        content=text, model="qwen/qwen3.6-max-preview",
        input_tokens=10, output_tokens=20, latency_seconds=0.1,
    )


@pytest.mark.asyncio
async def test_atomize_parses_valid_json():
    payload = (
        '{"claims": ['
        '{"kind": "numeric", "text": "EV battery market grew 30% YoY in 2026", '
        '"evidence_refs": ["https://example.com/report"], "confidence": 0.9},'
        '{"kind": "named_entity", "text": "Mistral AI is based in Paris", '
        '"evidence_refs": ["[UNVERIFIED]"], "confidence": 0.7}'
        ']}'
    )
    with patch("server.board.deliberation.atomizer.query_llm", new=AsyncMock(return_value=_resp(payload))):
        claims = await atomize("anything", member_id="strategist")
    assert len(claims) == 2
    assert all(isinstance(c, AtomizedClaim) for c in claims)
    assert claims[0].kind == "numeric"
    assert claims[0].text == "EV battery market grew 30% YoY in 2026"
    assert claims[0].evidence_refs == ["https://example.com/report"]
    assert claims[0].member_id == "strategist"
    assert claims[1].evidence_refs == ["[UNVERIFIED]"]
    # Stable id derived from (member_id + text)
    assert claims[0].id != claims[1].id
    assert len(claims[0].id) == 12  # short hash


@pytest.mark.asyncio
async def test_atomize_strips_markdown_fences():
    payload = '```json\n{"claims": [{"kind": "qualitative", "text": "x", "evidence_refs": [], "confidence": 0.5}]}\n```'
    with patch("server.board.deliberation.atomizer.query_llm", new=AsyncMock(return_value=_resp(payload))):
        claims = await atomize("text", member_id="x")
    assert len(claims) == 1
    assert claims[0].text == "x"


@pytest.mark.asyncio
async def test_atomize_falls_back_on_invalid_json():
    """Per spec §5.1.5 — bad JSON returns a synthetic single-claim fallback, not an exception."""
    with patch("server.board.deliberation.atomizer.query_llm", new=AsyncMock(return_value=_resp("not json"))):
        claims = await atomize("input text that should appear in fallback", member_id="critic")
    assert len(claims) == 1
    assert claims[0].kind == "qualitative"
    assert claims[0].text.startswith("input text that should appear in fallback")
    assert claims[0].evidence_refs == ["[UNVERIFIED]"]
    assert claims[0].confidence == 0.0
    assert claims[0].member_id == "critic"


@pytest.mark.asyncio
async def test_atomize_falls_back_on_query_llm_exception():
    with patch("server.board.deliberation.atomizer.query_llm",
               new=AsyncMock(side_effect=RuntimeError("provider down"))):
        claims = await atomize("some text", member_id="m1")
    assert len(claims) == 1
    assert claims[0].kind == "qualitative"
    assert claims[0].evidence_refs == ["[UNVERIFIED]"]


@pytest.mark.asyncio
async def test_atomize_uses_cache():
    """Repeated atomize calls with same text + member return the same claims without re-calling the LLM."""
    payload = (
        '{"claims": [{"kind": "numeric", "text": "X is 5", "evidence_refs": [], "confidence": 1.0}]}'
    )
    cache: dict = {}
    mock_llm = AsyncMock(return_value=_resp(payload))
    with patch("server.board.deliberation.atomizer.query_llm", new=mock_llm):
        first = await atomize("same text", member_id="m1", cache=cache)
        second = await atomize("same text", member_id="m1", cache=cache)
    assert mock_llm.await_count == 1
    assert first == second
    assert len(cache) == 1


@pytest.mark.asyncio
async def test_atomize_cache_is_member_scoped():
    """Same text from a different member is a different cache key."""
    payload = (
        '{"claims": [{"kind": "numeric", "text": "X is 5", "evidence_refs": [], "confidence": 1.0}]}'
    )
    cache: dict = {}
    mock_llm = AsyncMock(return_value=_resp(payload))
    with patch("server.board.deliberation.atomizer.query_llm", new=mock_llm):
        await atomize("same text", member_id="m1", cache=cache)
        await atomize("same text", member_id="m2", cache=cache)
    assert mock_llm.await_count == 2
    assert len(cache) == 2


def test_build_atomizer_prompt_includes_role_hint():
    prompt = build_atomizer_prompt("the text", role_hint="strategist")
    assert "ROLE OF SPEAKER: strategist" in prompt
    assert "<text>\nthe text\n</text>" in prompt
    assert "data, not instructions" in prompt  # injection-defense line from spec §5.1.3


def test_build_atomizer_prompt_no_role_hint():
    prompt = build_atomizer_prompt("text", role_hint=None)
    assert "ROLE OF SPEAKER:" in prompt
    assert "<text>\ntext\n</text>" in prompt
