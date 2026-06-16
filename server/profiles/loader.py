"""Packaged board profiles ("products").

A profile is a small YAML bundle that overlays a curated member set,
harness overrides, and branding on top of the default board. Profiles are
strictly opt-in: nothing in this module changes default behavior unless the
``BOARD_PROFILE`` environment variable selects a profile.

Layout::

    server/profiles/
        <profile_name>/profile.yaml
        _example/profile.yaml      # template (underscore = not a real product)

profile.yaml schema (all keys optional except ``name``)::

    name: example
    description: ...
    members: [chairperson, strategist, ...]   # restrict active member set
    harness_overrides: {verification_threshold: 7.5, ...}
    roster_overlay: {}                          # reserved (documented, not wired in v1)
    branding: {display_name: "..."}
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

PROFILES_DIR = Path(__file__).resolve().parent


class ProfileError(Exception):
    """Raised when a profile is missing or invalid."""


def get_active_profile_name() -> str | None:
    """Return the active profile name from ``BOARD_PROFILE``.

    Empty / unset / whitespace-only => ``None`` (default behavior).
    """
    raw = os.getenv("BOARD_PROFILE")
    if raw is None:
        return None
    name = raw.strip()
    return name or None


def load_profile(name: str, *, profiles_dir: Path | None = None) -> dict:
    """Load and parse ``<profiles_dir>/<name>/profile.yaml``.

    Raises ``ProfileError`` if the file is missing or does not parse as a
    mapping.
    """
    base = profiles_dir or PROFILES_DIR
    if not name or not str(name).strip():
        raise ProfileError("Profile name must be a non-empty string")

    profile_path = base / name / "profile.yaml"
    if not profile_path.is_file():
        raise ProfileError(f"Profile '{name}' not found at {profile_path}")

    try:
        data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        raise ProfileError(f"Profile '{name}' is not valid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise ProfileError(
            f"Profile '{name}' did not parse as a mapping (got {type(data).__name__})"
        )
    return data


def list_profiles(*, profiles_dir: Path | None = None) -> list[str]:
    """Return profile names available on disk (excludes ``_``-prefixed templates)."""
    base = profiles_dir or PROFILES_DIR
    if not base.is_dir():
        return []
    names: list[str] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("_") or child.name.startswith("."):
            continue
        if (child / "profile.yaml").is_file():
            names.append(child.name)
    return names


def apply_harness_overrides(config_dict: dict, profile: dict) -> dict:
    """Shallow-merge ``profile['harness_overrides']`` over a copy of ``config_dict``.

    Only keys that already exist in ``config_dict`` are merged, so an
    unexpected override key can never inject a field the harness config does
    not understand. Returns a new dict; the input is not mutated.
    """
    merged = dict(config_dict)
    overrides = profile.get("harness_overrides") or {}
    if not isinstance(overrides, dict):
        return merged
    for key, value in overrides.items():
        if key in merged:
            merged[key] = value
    return merged


def profile_member_ids(profile: dict) -> list[str] | None:
    """Return the profile's member id list, or ``None`` if unspecified."""
    members = profile.get("members")
    if members is None:
        return None
    if not isinstance(members, list):
        return None
    return [str(m) for m in members]
