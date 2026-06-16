"""Unit tests for complexity-aware council model routing (Plan 4c).

Exercises ``_assign_models`` directly — no full deliberation, no network.
The feature is a config-gated, default-OFF cost lever: when
``routing.complexity_aware_models`` is enabled AND the query is classified
"simple", council members WITHOUT an explicit ``model_override`` are
downshifted to ``routing.simple_complexity_model``. The chairman and any
member carrying a ``model_override`` are never downshifted.
"""

from __future__ import annotations

import unittest

from server.board.config import BoardMember
from server.board.deliberation.orchestrator import _assign_models
from server.harness.config import HarnessConfig


CHAIRMAN_ID = "chairperson"
SIMPLE_MODEL = "qwen/qwen3.6-flash"


def _member(member_id: str, *, override: str | None = None) -> BoardMember:
    return BoardMember(
        id=member_id,
        title=f"{member_id.title()} Member",
        role="Test Role",
        expertise=[],
        system_prompt=f"{member_id} system prompt",
        model_override=override,
    )


def _members() -> list[BoardMember]:
    # Chairman has NO override so the downshift must skip it purely via
    # chairman_id (exercising the chair-exclusion path, not the override
    # path). Two council members: one with an explicit override, one
    # relying on round-robin.
    return [
        _member("strategist"),                          # council, no override
        _member("product", override="pinned/model-x"),  # council, override
        _member(CHAIRMAN_ID),                            # chair, no override
    ]


def _config(*, enabled: bool) -> HarnessConfig:
    return HarnessConfig(routing={
        "complexity_aware_models": enabled,
        "simple_complexity_model": SIMPLE_MODEL,
    })


class TestTieredRouting(unittest.TestCase):
    def test_flag_off_simple_unchanged(self):
        """Flag OFF: simple complexity must not alter any assignment."""
        cfg = _config(enabled=False)
        baseline = _assign_models(
            _members(), chairman_id=CHAIRMAN_ID, config=cfg,
        )
        downshifted = _assign_models(
            _members(),
            complexity="simple",
            chairman_id=CHAIRMAN_ID,
            config=cfg,
        )
        self.assertEqual(baseline, downshifted)

    def test_flag_off_complex_unchanged(self):
        cfg = _config(enabled=False)
        baseline = _assign_models(
            _members(), chairman_id=CHAIRMAN_ID, config=cfg,
        )
        complex_run = _assign_models(
            _members(),
            complexity="complex",
            chairman_id=CHAIRMAN_ID,
            config=cfg,
        )
        self.assertEqual(baseline, complex_run)

    def test_flag_on_simple_downshifts_only_unpinned_council(self):
        cfg = _config(enabled=True)
        # The chairman's baseline (non-downshifted) model — must be preserved.
        chair_baseline = _assign_models(
            _members(), chairman_id=CHAIRMAN_ID, config=cfg,
        )[CHAIRMAN_ID]

        assignments = _assign_models(
            _members(),
            complexity="simple",
            chairman_id=CHAIRMAN_ID,
            config=cfg,
        )
        # Council member without override is downshifted.
        self.assertEqual(SIMPLE_MODEL, assignments["strategist"])
        # Council member with override keeps its override.
        self.assertEqual("pinned/model-x", assignments["product"])
        # Chairman keeps its flagship (baseline) model — not downshifted.
        self.assertEqual(chair_baseline, assignments[CHAIRMAN_ID])
        self.assertNotEqual(SIMPLE_MODEL, assignments[CHAIRMAN_ID])

    def test_flag_on_complex_no_downshift(self):
        cfg = _config(enabled=True)
        baseline = _assign_models(
            _members(), chairman_id=CHAIRMAN_ID, config=cfg,
        )
        complex_run = _assign_models(
            _members(),
            complexity="complex",
            chairman_id=CHAIRMAN_ID,
            config=cfg,
        )
        # No downshift for non-simple complexity even when the flag is on.
        self.assertEqual(baseline, complex_run)
        self.assertNotEqual(SIMPLE_MODEL, complex_run["strategist"])

    def test_flag_on_simple_monkeypatched_get_config(self):
        """Routing reads get_config() when no explicit config is passed."""
        import server.board.deliberation.orchestrator as orch

        original = orch.get_config
        orch.get_config = lambda: _config(enabled=True)
        try:
            assignments = _assign_models(
                _members(),
                complexity="simple",
                chairman_id=CHAIRMAN_ID,
            )
        finally:
            orch.get_config = original

        self.assertEqual(SIMPLE_MODEL, assignments["strategist"])
        self.assertEqual("pinned/model-x", assignments["product"])
        self.assertNotEqual(SIMPLE_MODEL, assignments[CHAIRMAN_ID])


if __name__ == "__main__":
    unittest.main()
