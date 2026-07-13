from __future__ import annotations

from server.discovery.channels import CHANNELS, build_channel
from server.discovery.channels.base import ChannelHealth
from server.discovery.policy import source_policy


def run_doctor(names: list[str] | None = None) -> list[ChannelHealth]:
    results = []
    for name in names or sorted(CHANNELS):
        policy = source_policy(name)
        if policy.posture != "allowed":
            results.append(
                ChannelHealth(
                    name,
                    policy.posture,
                    policy.reason,
                    posture=policy.posture,
                    configured=False,
                    policy_reason=policy.reason,
                )
            )
            continue
        try:
            health = build_channel(name).health()
            results.append(
                ChannelHealth(
                    health.channel,
                    health.status,
                    health.detail,
                    posture=policy.posture,
                    configured=health.status == "ok",
                    policy_reason=policy.reason,
                )
            )
        except Exception as exc:
            results.append(
                ChannelHealth(
                    name,
                    "error",
                    str(exc),
                    posture=policy.posture,
                    configured=False,
                    policy_reason=policy.reason,
                )
            )
    return results
