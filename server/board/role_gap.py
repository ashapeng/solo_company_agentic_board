"""Role-gap review helpers for governed board evolution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .roster import load_roster


@dataclass
class RoleGapReview:
    recommendation: str
    rationale: str
    missing_capabilities: list[str] = field(default_factory=list)
    candidate_shelved_members: list[str] = field(default_factory=list)
    benchmark_query: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def review_role_gap(
    missing_capabilities: list[str],
    *,
    query: str = "",
    stage_profile: str = "pre_pmf",
    recurrence_count: int = 1,
    roster: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recommend no change, skill, shelved member activation, or new member."""
    data = roster or load_roster()
    members = data.get("members", {})
    profiles = data.get("stage_profiles", {})
    optional_ids = profiles.get(stage_profile, {}).get("optional", [])

    candidates = [
        member_id
        for member_id in optional_ids
        if set(missing_capabilities).intersection(set(members.get(member_id, {}).get("capabilities", [])))
    ]

    if not missing_capabilities:
        recommendation = "no_change"
        rationale = "No missing board capability was identified."
    elif candidates and recurrence_count >= 2:
        recommendation = "activate_shelved_member"
        rationale = "A shelved member covers the repeated missing capability."
    elif recurrence_count >= 3:
        recommendation = "create_new_board_member"
        rationale = "The missing capability appears durable and no shelved member covers it."
    else:
        recommendation = "create_hermes_skill"
        rationale = "Treat this as an operating skill until the gap repeats enough to justify board evolution."

    benchmark = query or (
        "Board benchmark: evaluate whether the current roster handles "
        + ", ".join(missing_capabilities)
        + " decisions better after the proposed change."
    )

    return RoleGapReview(
        recommendation=recommendation,
        rationale=rationale,
        missing_capabilities=missing_capabilities,
        candidate_shelved_members=candidates,
        benchmark_query=benchmark,
    ).to_dict()
