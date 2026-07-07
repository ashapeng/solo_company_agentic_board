from __future__ import annotations

from server.discovery.channels import CHANNELS, build_channel
from server.discovery.channels.base import ChannelHealth


def run_doctor(names: list[str] | None = None) -> list[ChannelHealth]:
    results = []
    for name in names or sorted(CHANNELS):
        try:
            results.append(build_channel(name).health())
        except Exception as exc:
            results.append(ChannelHealth(name, "error", str(exc)))
    return results
