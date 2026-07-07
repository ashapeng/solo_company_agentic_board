from __future__ import annotations

from server.discovery.channels.base import ChannelHealth, RawPost


class AgentReachChannel:
    name = "agent_reach"

    def fetch(self, item: dict) -> list[RawPost]:
        raise RuntimeError(
            "agent_reach channel is phase 2 — install Agent-Reach "
            "(https://github.com/Panniantong/Agent-Reach) and implement this wrapper"
        )

    def health(self) -> ChannelHealth:
        return ChannelHealth(
            self.name, "unconfigured", "phase 2 — Agent-Reach CLI wrapper not yet enabled"
        )
