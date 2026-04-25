"""Live smoke tests — opt-in only.

Run with:
    uv run pytest -m live tests/test_llm_live_smoke.py -v

Each test is skipped if its required env var is unset.
"""
from __future__ import annotations

import os

import pytest

from server.board import llm

pytestmark = pytest.mark.live


PING = [{"role": "user", "content": "Say 'pong' and nothing else."}]


@pytest.mark.skipif(not os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"),
                    reason="GEMINI_API_KEY / GOOGLE_API_KEY not set")
async def test_live_gemini():
    resp = await llm.query_llm(
        "gemini/gemini-2.5-flash",
        PING,
        max_tokens=8,
        fallback=False,
    )
    assert resp.content
    assert resp.input_tokens >= 0


@pytest.mark.skipif(not os.getenv("ZAI_API_KEY"), reason="ZAI_API_KEY not set")
async def test_live_zai():
    resp = await llm.query_llm("glm/glm-4.5-flash", PING, max_tokens=8, fallback=False)
    assert resp.content


@pytest.mark.skipif(not os.getenv("DASHSCOPE_API_KEY"), reason="DASHSCOPE_API_KEY not set")
async def test_live_qwen():
    resp = await llm.query_llm("qwen/qwen-flash", PING, max_tokens=8, fallback=False)
    assert resp.content


@pytest.mark.skipif(not os.getenv("DEEPSEEK_API_KEY"), reason="DEEPSEEK_API_KEY not set")
async def test_live_deepseek():
    resp = await llm.query_llm("deepseek/deepseek-chat", PING, max_tokens=8, fallback=False)
    assert resp.content


@pytest.mark.skipif(not os.getenv("MOONSHOT_API_KEY"), reason="MOONSHOT_API_KEY not set")
async def test_live_kimi():
    resp = await llm.query_llm("kimi/kimi-k2.5", PING, max_tokens=8, fallback=False)
    assert resp.content


@pytest.mark.skipif(not os.getenv("OPENROUTER_API_KEY"), reason="OPENROUTER_API_KEY not set")
async def test_live_openrouter():
    resp = await llm.query_llm(
        "openrouter:anthropic/claude-haiku-4-5",
        PING,
        max_tokens=8,
        fallback=False,
    )
    assert resp.content
