from __future__ import annotations

from server.discovery.channels.agent_reach import AgentReachChannel
from server.discovery.channels.base import Channel
from server.discovery.channels.canadabuys import CanadaBuysChannel
from server.discovery.channels.fake import FakeChannel
from server.discovery.channels.github import GitHubChannel
from server.discovery.channels.grants_gov import GrantsGovChannel
from server.discovery.channels.hackernews import HackerNewsChannel
from server.discovery.channels.producthunt import ProductHuntChannel
from server.discovery.channels.reddit import RedditChannel
from server.discovery.channels.rss import RssChannel
from server.discovery.channels.sam_gov import SamGovChannel
from server.discovery.channels.youtube import YouTubeChannel

CHANNELS: dict[str, type] = {
    cls.name: cls
    for cls in (
        RedditChannel,
        HackerNewsChannel,
        YouTubeChannel,
        GitHubChannel,
        RssChannel,
        ProductHuntChannel,
        SamGovChannel,
        GrantsGovChannel,
        CanadaBuysChannel,
        FakeChannel,
        AgentReachChannel,
    )
}


def build_channel(name: str) -> Channel:
    return CHANNELS[name]()
