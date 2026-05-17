"""Source-authority tier tests (spec §7.1.1)."""
from __future__ import annotations

import pytest

from server.board.source_authority import (
    DOMAIN_TIERS,
    tier_for_url,
)


# ─── DOMAIN_TIERS data shape ────────────────────────────────────────────────

def test_domain_tiers_contains_required_entries():
    """The default map must cover the categories spec §7.1.1 enumerates."""
    # academic
    assert DOMAIN_TIERS["*.edu"] == "academic"
    assert DOMAIN_TIERS["*.gov"] == "academic"
    assert DOMAIN_TIERS["arxiv.org"] == "academic"
    assert DOMAIN_TIERS["nature.com"] == "academic"
    assert DOMAIN_TIERS["science.org"] == "academic"
    assert DOMAIN_TIERS["doi.org"] == "academic"
    # major news
    assert DOMAIN_TIERS["reuters.com"] == "major_news"
    assert DOMAIN_TIERS["ft.com"] == "major_news"
    assert DOMAIN_TIERS["wsj.com"] == "major_news"
    assert DOMAIN_TIERS["bloomberg.com"] == "major_news"
    assert DOMAIN_TIERS["economist.com"] == "major_news"
    assert DOMAIN_TIERS["nytimes.com"] == "major_news"
    assert DOMAIN_TIERS["apnews.com"] == "major_news"
    # established blogs
    assert DOMAIN_TIERS["techcrunch.com"] == "established_blog"
    assert DOMAIN_TIERS["theverge.com"] == "established_blog"
    assert DOMAIN_TIERS["arstechnica.com"] == "established_blog"
    assert DOMAIN_TIERS["stratechery.com"] == "established_blog"
    assert DOMAIN_TIERS["a16z.com"] == "established_blog"


def test_domain_tiers_tier_values_are_valid():
    """No typos in tier strings."""
    valid = {"academic", "major_news", "established_blog"}
    for host, tier in DOMAIN_TIERS.items():
        assert tier in valid, f"{host!r} has invalid tier {tier!r}"


# ─── tier_for_url: exact host match ─────────────────────────────────────────

def test_tier_for_url_exact_host_reuters():
    assert tier_for_url("https://reuters.com/article/foo") == "major_news"


def test_tier_for_url_strips_www_prefix():
    assert tier_for_url("https://www.reuters.com/article") == "major_news"


def test_tier_for_url_strips_port():
    assert tier_for_url("https://reuters.com:8443/foo") == "major_news"


def test_tier_for_url_strips_path_query_fragment():
    """spec footnote: hostname-only matching."""
    assert tier_for_url("https://arxiv.org/abs/2024.12345?foo=bar#sec") == "academic"


def test_tier_for_url_lowercases_hostname():
    assert tier_for_url("https://Reuters.COM/x") == "major_news"


# ─── tier_for_url: wildcard match ───────────────────────────────────────────

def test_tier_for_url_wildcard_edu():
    assert tier_for_url("https://stanford.edu/research") == "academic"


def test_tier_for_url_wildcard_subdomain_edu():
    assert tier_for_url("https://cs.stanford.edu/paper.pdf") == "academic"


def test_tier_for_url_wildcard_gov_uk_when_only_gov_registered():
    """`*.gov` registered, `*.gov.uk` not — `*.gov` still matches `gov.uk` host."""
    # gov.uk ends in .gov? NO — .gov.uk ends in .uk, not .gov as the final label.
    # Confirming the algorithm only matches when the wildcard suffix matches at
    # the end of the hostname. "gov.uk" does not end with ".gov".
    assert tier_for_url("https://nhs.gov.uk") == "unknown"


def test_tier_for_url_wildcard_gov_matches_irs_gov():
    assert tier_for_url("https://www.irs.gov/forms") == "academic"


# ─── tier_for_url: longest-suffix-wins ──────────────────────────────────────

def test_tier_for_url_exact_host_beats_wildcard():
    """When both an exact host (`reuters.com`) and a hypothetical wildcard
    (`*.com`) match, exact wins regardless of suffix length."""
    overrides = {"*.com": "established_blog"}  # synthetic
    assert tier_for_url("https://reuters.com/x", overrides=overrides) == "major_news"


def test_tier_for_url_longest_wildcard_suffix_wins():
    """Among multiple wildcard matches, the longest suffix wins."""
    overrides = {"*.ac.uk": "academic", "*.uk": "established_blog"}
    assert tier_for_url("https://cam.ac.uk", overrides=overrides) == "academic"


# ─── tier_for_url: fall-through to "unknown" ────────────────────────────────

def test_tier_for_url_unknown_for_unlisted_domain():
    assert tier_for_url("https://some-seo-blog.example/article") == "unknown"


def test_tier_for_url_unknown_for_empty_url():
    assert tier_for_url("") == "unknown"


def test_tier_for_url_unknown_for_malformed_url():
    """Garbage in → 'unknown' out; never raises."""
    assert tier_for_url("not a url at all") == "unknown"
    assert tier_for_url("://broken") == "unknown"
    assert tier_for_url("ftp://reuters.com") == "unknown"  # non-http(s) scheme
    assert tier_for_url(None) == "unknown"  # type: ignore[arg-type]


def test_tier_for_url_unknown_for_unverified_literal():
    """The `[UNVERIFIED]` literal used by atomizer/refs is never authoritative."""
    assert tier_for_url("[UNVERIFIED]") == "unknown"
    assert tier_for_url("[INFERENCE]") == "unknown"
    assert tier_for_url("[DOMAIN_KNOWLEDGE]") == "unknown"


# ─── tier_for_url: overrides ────────────────────────────────────────────────

def test_tier_for_url_override_exact_host():
    overrides = {"myindustry.example": "major_news"}
    assert tier_for_url("https://myindustry.example/post", overrides=overrides) == "major_news"


def test_tier_for_url_override_wildcard():
    overrides = {"*.example.com": "established_blog"}
    assert tier_for_url("https://blog.example.com", overrides=overrides) == "established_blog"


def test_tier_for_url_override_takes_precedence_over_default():
    """Operator override beats the built-in map."""
    overrides = {"reuters.com": "established_blog"}
    assert tier_for_url("https://reuters.com/x", overrides=overrides) == "established_blog"


def test_tier_for_url_ignores_override_with_invalid_tier():
    """Invalid tier strings in overrides are silently dropped — fail open
    to the default tier; never crashes."""
    overrides = {"reuters.com": "not_a_real_tier"}
    assert tier_for_url("https://reuters.com/x", overrides=overrides) == "major_news"


def test_tier_for_url_empty_overrides_uses_default_map():
    assert tier_for_url("https://reuters.com/x", overrides={}) == "major_news"
    assert tier_for_url("https://reuters.com/x", overrides=None) == "major_news"
