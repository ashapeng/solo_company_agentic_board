from __future__ import annotations

from server.discovery.channels.base import ChannelHealth, RawPost


class FakeChannel:
    name = "fake"

    def fetch(self, item: dict) -> list[RawPost]:
        label = item.get("label", "fake")
        return [
            RawPost(
                id="fake-1",
                channel=self.name,
                source=label,
                title="I wish there was a tool for tracking yarn inventory",
                body="Spreadsheets keep breaking, photos everywhere",
                url="https://example.com/fake-1",
                score=100,
                comments=25,
            ),
            RawPost(
                id="fake-2",
                channel=self.name,
                source=label,
                title="Pricing handmade goods is guesswork",
                body="No idea if I'm undercharging",
                url="https://example.com/fake-2",
                score=80,
                comments=12,
            ),
        ]

    def health(self) -> ChannelHealth:
        return ChannelHealth(self.name, "ok", "test channel")
