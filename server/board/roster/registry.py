"""Roster registry and capability-based member selection."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


DEFAULT_STAGE_PROFILE = "pre_pmf"
ROSTER_PATH = Path(__file__).resolve().parent / "roster.yaml"


@dataclass
class RosterSelection:
    member_ids: list[str]
    required_capabilities: list[str]
    unavailable_capabilities: list[str] = field(default_factory=list)
    stage_profile: str = DEFAULT_STAGE_PROFILE
    reasoning: str = ""
    role_gap_memo: str | None = None


def get_stage_profile() -> str:
    return os.getenv("BOARD_STAGE_PROFILE", DEFAULT_STAGE_PROFILE)


def load_roster(path: str | Path | None = None) -> dict[str, Any]:
    roster_path = Path(path) if path else ROSTER_PATH
    data = yaml.safe_load(roster_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Roster file did not parse as a mapping: {roster_path}")
    return data


def active_member_ids(
    *,
    stage_profile: str | None = None,
    roster: dict[str, Any] | None = None,
) -> list[str]:
    data = roster or load_roster()
    profile = stage_profile or get_stage_profile()
    profile_data = data.get("stage_profiles", {}).get(profile)
    if not profile_data:
        profile_data = data.get("stage_profiles", {}).get(DEFAULT_STAGE_PROFILE, {})
    return _as_string_list(profile_data.get("active", []))


def decision_capabilities(decision_type: str, *, roster: dict[str, Any] | None = None) -> list[str]:
    data = roster or load_roster()
    decision_types = data.get("decision_types", {})
    capabilities = decision_types.get(decision_type) or decision_types.get("full-board", [])
    return _as_string_list(capabilities)


def select_members_for_capabilities(
    required_capabilities: list[str],
    *,
    stage_profile: str | None = None,
    roster: dict[str, Any] | None = None,
    include_chairperson: bool = True,
) -> RosterSelection:
    """Select active board members whose capabilities cover the request."""
    data = roster or load_roster()
    profile = stage_profile or get_stage_profile()
    profile_data = data.get("stage_profiles", {}).get(profile)
    if not profile_data:
        profile = DEFAULT_STAGE_PROFILE
        profile_data = data.get("stage_profiles", {}).get(profile, {})

    active_ids = _as_string_list(profile_data.get("active", []))
    member_meta = data.get("members", {})
    member_ids: list[str] = []
    unavailable: list[str] = []

    for capability in _dedupe(required_capabilities):
        owners = [
            member_id
            for member_id in active_ids
            if capability in _as_string_list(member_meta.get(member_id, {}).get("capabilities", []))
        ]
        if owners:
            member_ids.extend(owners)
        else:
            unavailable.append(capability)

    if include_chairperson and "chairperson" in active_ids:
        member_ids.append("chairperson")

    if not member_ids:
        member_ids = active_ids

    return RosterSelection(
        member_ids=_sort_by_active_order(_dedupe(member_ids), active_ids),
        required_capabilities=_dedupe(required_capabilities),
        unavailable_capabilities=_dedupe(unavailable),
        stage_profile=profile,
        reasoning="Selected active members whose roster capabilities match the decision.",
        role_gap_memo=_build_role_gap_memo(unavailable, profile),
    )


def select_members_for_decision_type(
    decision_type: str,
    *,
    stage_profile: str | None = None,
    roster: dict[str, Any] | None = None,
) -> RosterSelection:
    data = roster or load_roster()
    capabilities = decision_capabilities(decision_type, roster=data)
    return select_members_for_capabilities(
        capabilities,
        stage_profile=stage_profile,
        roster=data,
        include_chairperson=True,
    )


def _sort_by_active_order(member_ids: list[str], active_ids: list[str]) -> list[str]:
    order = {member_id: idx for idx, member_id in enumerate(active_ids)}
    return sorted(member_ids, key=lambda member_id: order.get(member_id, len(order)))


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def get_clarification_gate(roster: dict | None = None) -> dict:
    """Return the clarification-gate configuration from roster.yaml."""
    roster = roster or load_roster()
    gate = roster.get("clarification_gate") or {}
    return {
        "ambiguous_terms": [str(t) for t in (gate.get("ambiguous_terms") or [])],
        "min_terms_present": int(gate.get("min_terms_present", 2)),
        "max_query_words": int(gate.get("max_query_words", 14)),
        "gating_capabilities": [str(c) for c in (gate.get("gating_capabilities") or [])],
    }


def _build_role_gap_memo(unavailable: list[str], stage_profile: str) -> str | None:
    if not unavailable:
        return None
    missing = ", ".join(_dedupe(unavailable))
    return (
        f"Stage profile '{stage_profile}' has no active board member for: {missing}. "
        "Use the closest active members for now; consider a role-gap review if this recurs."
    )
