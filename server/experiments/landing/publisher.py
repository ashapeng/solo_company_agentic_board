from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from .models import DeploymentResult, LandingPageArtifact


class LandingPagePublisher(Protocol):
    name: str
    is_external: bool

    def publish(self, artifact: LandingPageArtifact, *, idempotency_key: str) -> DeploymentResult: ...


class FakeLandingPagePublisher:
    """Deterministic test adapter. It never opens a socket or publishes externally."""

    name = "fake"
    is_external = False

    def __init__(self) -> None:
        self._deployments: dict[str, DeploymentResult] = {}

    def publish(self, artifact: LandingPageArtifact, *, idempotency_key: str) -> DeploymentResult:
        if idempotency_key in self._deployments:
            return self._deployments[idempotency_key]
        result = DeploymentResult(
            experiment_id=artifact.experiment_id,
            deployment_id=f"fake_{artifact.experiment_id}",
            url=f"https://example.invalid/experiments/{artifact.experiment_id}",
            provider=self.name,
            published_at=datetime.now(timezone.utc).isoformat(),
            external=False,
        )
        self._deployments[idempotency_key] = result
        return result
