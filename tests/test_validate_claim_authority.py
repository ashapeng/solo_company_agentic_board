"""validate_claim source-authority weighting tests (spec §7.1.3)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from server.board.llm import LLMResponse
from server.board.tools import _handle_validate_claim


def _llm(text: str) -> LLMResponse:
    return LLMResponse(
        content=text, model="gemini/gemini-2.5-flash",
        input_tokens=10, output_tokens=20, latency_seconds=0.1,
    )


def _search_results(urls: list[str]) -> dict:
    """Shape mirrors what server.execution.web_search.web_search returns."""
    return {
        "results": [
            {"title": f"Result {i}", "snippet": "some snippet", "url": url}
            for i, url in enumerate(urls, 1)
        ],
    }


# ─── SUPPORTED with weak sources → downgraded to UNVERIFIED ─────────────────

@pytest.mark.asyncio
async def test_supported_with_only_unknown_refs_downgrades_to_unverified():
    """Judge says SUPPORTED but all 5 sources are unknown-tier blogs.
    Post-judge tier check must downgrade verdict to UNVERIFIED."""
    weak_urls = [
        "https://seo-blog-1.example/a",
        "https://seo-blog-2.example/b",
        "https://seo-blog-3.example/c",
        "https://content-farm.example/d",
        "https://aggregator.example/e",
    ]
    judge_response = (
        "VERDICT: SUPPORTED\n"
        "RATIONALE: Multiple sources confirm.\n"
        "KEY_SOURCES: " + ", ".join(weak_urls)
    )
    with (
        patch(
            "server.execution.web_search.web_search",
            new=AsyncMock(return_value=_search_results(weak_urls)),
        ),
        patch(
            "server.board.tools.query_llm",
            new=AsyncMock(return_value=_llm(judge_response)),
        ),
    ):
        result = await _handle_validate_claim(claim="some claim", session=None)
    assert result.summary == "validate_claim: UNVERIFIED"
    assert "insufficient source authority" in result.content_for_model.lower()
    # The downgrade rationale should hint at what was missing.
    assert "academic" in result.content_for_model.lower() \
        or "major_news" in result.content_for_model \
        or "established_blog" in result.content_for_model


@pytest.mark.asyncio
async def test_supported_with_one_major_news_only_still_downgrades():
    """Rule requires ≥2 major_news. One alone fails."""
    urls = [
        "https://reuters.com/article",
        "https://seo-blog.example/x",
        "https://another-blog.example/y",
    ]
    judge_response = (
        "VERDICT: SUPPORTED\nRATIONALE: ok\nKEY_SOURCES: " + ", ".join(urls)
    )
    with (
        patch("server.execution.web_search.web_search",
              new=AsyncMock(return_value=_search_results(urls))),
        patch("server.board.tools.query_llm",
              new=AsyncMock(return_value=_llm(judge_response))),
    ):
        result = await _handle_validate_claim(claim="x", session=None)
    assert result.summary == "validate_claim: UNVERIFIED"


# ─── SUPPORTED with strong sources → verdict preserved ──────────────────────

@pytest.mark.asyncio
async def test_supported_with_one_academic_ref_preserved():
    """≥1 academic source satisfies the threshold — keep SUPPORTED."""
    urls = [
        "https://arxiv.org/abs/2024.12345",
        "https://seo-blog.example/x",
    ]
    judge_response = (
        "VERDICT: SUPPORTED\nRATIONALE: ok\nKEY_SOURCES: " + ", ".join(urls)
    )
    with (
        patch("server.execution.web_search.web_search",
              new=AsyncMock(return_value=_search_results(urls))),
        patch("server.board.tools.query_llm",
              new=AsyncMock(return_value=_llm(judge_response))),
    ):
        result = await _handle_validate_claim(claim="x", session=None)
    assert result.summary == "validate_claim: SUPPORTED"
    assert "insufficient source authority" not in result.content_for_model.lower()


@pytest.mark.asyncio
async def test_supported_with_two_major_news_refs_preserved():
    urls = [
        "https://reuters.com/a",
        "https://bloomberg.com/b",
        "https://seo-blog.example/x",
    ]
    judge_response = (
        "VERDICT: SUPPORTED\nRATIONALE: ok\nKEY_SOURCES: " + ", ".join(urls)
    )
    with (
        patch("server.execution.web_search.web_search",
              new=AsyncMock(return_value=_search_results(urls))),
        patch("server.board.tools.query_llm",
              new=AsyncMock(return_value=_llm(judge_response))),
    ):
        result = await _handle_validate_claim(claim="x", session=None)
    assert result.summary == "validate_claim: SUPPORTED"


# ─── CONTRADICTED / UNVERIFIED unaffected ───────────────────────────────────

@pytest.mark.asyncio
async def test_contradicted_verdict_unaffected_by_tier_check():
    """The downgrade rule applies ONLY to SUPPORTED verdicts. CONTRADICTED
    passes through regardless of source tier."""
    urls = ["https://seo-blog.example/a"]
    judge_response = (
        "VERDICT: CONTRADICTED\nRATIONALE: refuted\nKEY_SOURCES: " + urls[0]
    )
    with (
        patch("server.execution.web_search.web_search",
              new=AsyncMock(return_value=_search_results(urls))),
        patch("server.board.tools.query_llm",
              new=AsyncMock(return_value=_llm(judge_response))),
    ):
        result = await _handle_validate_claim(claim="x", session=None)
    assert result.summary == "validate_claim: CONTRADICTED"


@pytest.mark.asyncio
async def test_unverified_verdict_unaffected_by_tier_check():
    urls = ["https://reuters.com/a", "https://bloomberg.com/b"]
    judge_response = (
        "VERDICT: UNVERIFIED\nRATIONALE: insufficient\nKEY_SOURCES: " + ", ".join(urls)
    )
    with (
        patch("server.execution.web_search.web_search",
              new=AsyncMock(return_value=_search_results(urls))),
        patch("server.board.tools.query_llm",
              new=AsyncMock(return_value=_llm(judge_response))),
    ):
        result = await _handle_validate_claim(claim="x", session=None)
    assert result.summary == "validate_claim: UNVERIFIED"


# ─── overrides plumbed from harness config ──────────────────────────────────

@pytest.mark.asyncio
async def test_overrides_from_harness_config_promote_industry_source():
    """When `hardening.source_authority_overrides` upgrades a domain to
    academic, a single ref from that domain satisfies the threshold."""
    from server.harness.config import HarnessConfig, get_config

    urls = ["https://industry-report.example/2026-q1"]
    judge_response = (
        "VERDICT: SUPPORTED\nRATIONALE: ok\nKEY_SOURCES: " + urls[0]
    )

    fake_cfg = HarnessConfig()
    fake_cfg.hardening = dict(fake_cfg.hardening)
    fake_cfg.hardening["source_authority_overrides"] = {
        "industry-report.example": "academic",
    }

    get_config.cache_clear()
    try:
        with (
            patch("server.harness.config.load_config", return_value=fake_cfg),
            patch("server.execution.web_search.web_search",
                  new=AsyncMock(return_value=_search_results(urls))),
            patch("server.board.tools.query_llm",
                  new=AsyncMock(return_value=_llm(judge_response))),
        ):
            result = await _handle_validate_claim(claim="x", session=None)
    finally:
        get_config.cache_clear()
    assert result.summary == "validate_claim: SUPPORTED"


# ─── judge prompt unchanged guard ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_judge_prompt_unchanged_no_authority_mention():
    """The downgrade happens AFTER the judge call. The prompt the judge sees
    must contain no reference to source-tier rules — that would change the
    judge's behavior, which spec §7.1.3 forbids."""
    urls = ["https://reuters.com/a", "https://bloomberg.com/b"]
    judge_response = "VERDICT: SUPPORTED\nRATIONALE: ok\nKEY_SOURCES: " + ", ".join(urls)
    judge_mock = AsyncMock(return_value=_llm(judge_response))
    with (
        patch("server.execution.web_search.web_search",
              new=AsyncMock(return_value=_search_results(urls))),
        patch("server.board.tools.query_llm", new=judge_mock),
    ):
        await _handle_validate_claim(claim="x", session=None)
    sent_prompt = judge_mock.await_args.args[1][0]["content"]
    assert "source_authority" not in sent_prompt
    assert "academic" not in sent_prompt
    assert "established_blog" not in sent_prompt
    # The pre-existing rules language is preserved.
    assert "SUPPORTED" in sent_prompt
