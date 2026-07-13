from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class LandingPageBrief:
    slug: str
    audience: str
    observed_problem: str
    proposed_outcome: str
    evidence_safe_claims: list[str]
    primary_cta: str
    privacy_text: str
    experiment_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LandingPageArtifact:
    experiment_id: str
    artifact_path: str
    digest: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeploymentResult:
    experiment_id: str
    deployment_id: str
    url: str
    provider: str
    published_at: str
    external: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
