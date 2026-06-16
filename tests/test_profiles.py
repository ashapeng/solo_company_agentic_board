"""Tests for packaged board profiles (Plan 7).

Covers the loader contract and the default-off invariant: with no profile
active, harness config and the board member set are byte-for-byte unchanged.
"""

from __future__ import annotations

import pytest

from server.profiles import (
    PROFILES_DIR,
    ProfileError,
    apply_harness_overrides,
    get_active_profile_name,
    load_profile,
    profile_member_ids,
)


def test_load_example_profile():
    profile = load_profile("_example", profiles_dir=PROFILES_DIR)
    assert isinstance(profile, dict)
    assert "members" in profile
    assert "harness_overrides" in profile
    assert isinstance(profile["members"], list)


def test_apply_harness_overrides_merges_existing_key():
    profile = load_profile("_example", profiles_dir=PROFILES_DIR)
    base = {"verification_threshold": 7.0, "stage1_max_tokens": 1200}
    merged = apply_harness_overrides(base, profile)
    assert merged["verification_threshold"] == 7.5
    # untouched key preserved
    assert merged["stage1_max_tokens"] == 1200
    # input not mutated
    assert base["verification_threshold"] == 7.0


def test_apply_harness_overrides_ignores_unknown_keys():
    base = {"verification_threshold": 7.0}
    profile = {"harness_overrides": {"verification_threshold": 9.0, "not_a_field": 123}}
    merged = apply_harness_overrides(base, profile)
    assert merged["verification_threshold"] == 9.0
    assert "not_a_field" not in merged


def test_profile_member_ids_returns_list():
    profile = load_profile("_example", profiles_dir=PROFILES_DIR)
    ids = profile_member_ids(profile)
    assert isinstance(ids, list)
    assert "chairperson" in ids


def test_profile_member_ids_none_when_absent():
    assert profile_member_ids({}) is None


def test_missing_profile_raises():
    with pytest.raises(ProfileError):
        load_profile("does_not_exist", profiles_dir=PROFILES_DIR)


def test_get_active_profile_name_unset(monkeypatch):
    monkeypatch.delenv("BOARD_PROFILE", raising=False)
    assert get_active_profile_name() is None
    monkeypatch.setenv("BOARD_PROFILE", "   ")
    assert get_active_profile_name() is None
    monkeypatch.setenv("BOARD_PROFILE", "_example")
    assert get_active_profile_name() == "_example"


def test_default_off_invariant_then_profile_takes_effect(monkeypatch):
    """No profile => unchanged config + full board; then profile overlays apply."""
    import server.board.config as board_config
    from server.harness import config as harness_config

    # --- default off: no BOARD_PROFILE ---
    monkeypatch.delenv("BOARD_PROFILE", raising=False)
    harness_config.get_config.cache_clear()

    on_disk = harness_config.load_config()
    base_threshold = on_disk.verification_threshold

    full_members = board_config.get_board_members()
    full_ids = {m.id for m in full_members}
    assert base_threshold == 7.0
    # the example profile restricts to 7 members; full board is larger or equal,
    # and must contain ids the profile would filter out to prove filtering works.
    assert "chairperson" in full_ids

    # --- profile active: _example ---
    monkeypatch.setenv("BOARD_PROFILE", "_example")
    harness_config.get_config.cache_clear()

    overridden = harness_config.load_config()
    assert overridden.verification_threshold == 7.5
    assert harness_config.get_config().verification_threshold == 7.5

    profile = load_profile("_example", profiles_dir=PROFILES_DIR)
    expected_ids = set(profile_member_ids(profile))
    filtered_members = board_config.get_board_members()
    filtered_ids = {m.id for m in filtered_members}
    assert filtered_ids == (full_ids & expected_ids)
    assert filtered_ids <= expected_ids

    # --- teardown: restore default-off state for other tests ---
    monkeypatch.delenv("BOARD_PROFILE", raising=False)
    harness_config.get_config.cache_clear()
    assert harness_config.load_config().verification_threshold == 7.0
    assert {m.id for m in board_config.get_board_members()} == full_ids
