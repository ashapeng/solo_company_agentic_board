"""Packaged board profiles ("products"). Opt-in via ``BOARD_PROFILE``."""

from __future__ import annotations

from .loader import (
    PROFILES_DIR,
    ProfileError,
    apply_harness_overrides,
    get_active_profile_name,
    list_profiles,
    load_profile,
    profile_member_ids,
)

__all__ = [
    "PROFILES_DIR",
    "ProfileError",
    "apply_harness_overrides",
    "get_active_profile_name",
    "list_profiles",
    "load_profile",
    "profile_member_ids",
]
