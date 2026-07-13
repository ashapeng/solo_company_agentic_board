"""Safe-by-default source postures for discovery collection."""

from __future__ import annotations

from dataclasses import dataclass


POSTURES = frozenset({"allowed", "held", "disabled"})


@dataclass(frozen=True)
class SourcePolicy:
    posture: str
    reason: str

    def __post_init__(self) -> None:
        if self.posture not in POSTURES:
            raise ValueError(f"unknown source posture: {self.posture}")


SOURCE_POLICIES: dict[str, SourcePolicy] = {
    "reddit": SourcePolicy(
        "held",
        "Unauthenticated JSON adapter is not approved; OAuth/Data API replacement and use review required.",
    ),
    "youtube": SourcePolicy(
        "held",
        "yt-dlp adapter is not approved; YouTube Data API replacement and quota review required.",
    ),
    "agent_reach": SourcePolicy(
        "disabled", "Generic social/browser collection is intentionally unavailable."
    ),
    "hackernews": SourcePolicy("allowed", "Public Algolia API; bounded read-only queries."),
    "github": SourcePolicy("allowed", "Authenticated gh API access; provider limits apply."),
    "rss": SourcePolicy("allowed", "Public RSS/Atom feed; source terms still apply."),
    "producthunt": SourcePolicy("allowed", "Official API only when token is configured."),
    "sam_gov": SourcePolicy("allowed", "Official government API/open data."),
    "grants_gov": SourcePolicy("allowed", "Official government API/open data."),
    "canadabuys": SourcePolicy("allowed", "Official government open data."),
    "fake": SourcePolicy("allowed", "Test adapter; fetch requires an explicit watchlist fixture."),
}


def source_policy(channel: str) -> SourcePolicy:
    return SOURCE_POLICIES.get(
        channel, SourcePolicy("disabled", "No reviewed discovery source policy exists.")
    )


def fetch_allowed(channel: str, *, explicit_watchlist: bool) -> tuple[bool, SourcePolicy]:
    policy = source_policy(channel)
    if policy.posture != "allowed":
        return False, policy
    if channel == "fake" and not explicit_watchlist:
        return False, SourcePolicy(
            "disabled", "Fake adapter requires an explicit test or fixture watchlist."
        )
    return True, policy
