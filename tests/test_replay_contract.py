# tests/test_replay_contract.py
"""Phase 0 repro for Plan 5 (offline replay + drift observability)."""

from __future__ import annotations

import subprocess
import unittest


class ReplayModuleExistsTest(unittest.TestCase):
    def test_replay_module_importable(self):
        from server.harness import replay  # noqa: F401

        self.assertTrue(hasattr(replay, "replay_session"))


class CliFlagExistsTest(unittest.TestCase):
    def test_cli_accepts_replay_flag(self):
        result = subprocess.run(
            ["/home/apeng/projects/solo_company_agentic_board/.venv/bin/python",
             "-m", "server.cli", "--help"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertIn("--replay", result.stdout)


class ReplayReportShapeTest(unittest.TestCase):
    def test_replay_report_fields_present(self):
        from server.harness.replay import ReplayReport

        report = ReplayReport(
            replay_id="r1",
            source_session_id="board_1",
            candidate_config_path=None,
            baseline={"verification_score": 8, "synthesis_len": 100},
            candidate={"verification_score": 7, "synthesis_len": 80},
            delta={"verification_score": -1, "synthesis_len": -20},
        )
        d = report.to_dict()
        self.assertEqual(d["replay_id"], "r1")
        self.assertEqual(d["source_session_id"], "board_1")
        self.assertEqual(d["baseline"]["synthesis_len"], 100)
        self.assertEqual(d["delta"]["verification_score"], -1)

    def test_replay_session_rejects_session_without_stage3(self):
        import json
        import tempfile
        from pathlib import Path
        from server.harness.replay import replay_session

        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False,
        ) as tmp:
            json.dump(
                {
                    "session_id": "board_missing_stage3",
                    "user_query": "q",
                    "stage1": [],
                    "stage2": [],
                    "stage3": None,
                },
                tmp,
            )
            path = Path(tmp.name)
        try:
            with self.assertRaises(ValueError) as ctx:
                replay_session(path, verify=False)
            self.assertIn("stage3", str(ctx.exception).lower())
        finally:
            path.unlink(missing_ok=True)


class ReplayPatchesVerifierTest(unittest.TestCase):
    def test_replay_patches_verifier_query_llm(self):
        """Both orchestrator and verifier modules get their query_llm rebinding."""
        import asyncio
        from unittest.mock import AsyncMock

        import server.board.deliberation.orchestrator as orch_module
        import server.board.deliberation.verification as verif_module
        from server.harness.replay import _rerun_stage3_and_verify

        # Capture the query_llm references seen by Stage 3 and verifier during replay.
        seen_refs: dict[str, object] = {}

        original_orch = orch_module.query_llm
        original_verif = verif_module.query_llm

        async def spy_stage3(self_, user_query, stage1_responses, stage2_responses, *, sotb, query_type, complexity):
            seen_refs["orch"] = orch_module.query_llm
            from server.board.deliberation.orchestrator import MemberResponse
            return MemberResponse(
                member_id="chair", stage=3,
                content="### Executive Summary\nok\n\n### Next Steps\n- do it\n",
                model="m", elapsed_seconds=0.0,
            )

        # Stub orchestrator.stage3 and verify_synthesis to capture the live bindings.
        from server.board.deliberation import orchestrator as _om
        from server.board.deliberation import verification as _vm

        original_stage3 = _om.BoardOrchestrator.stage3
        original_verify_synthesis = _vm.verify_synthesis

        _om.BoardOrchestrator.stage3 = spy_stage3  # type: ignore[assignment]

        async def _spy_verify(synthesis, stage2_compacted, user_query, *, query_type=None):
            seen_refs["verif"] = verif_module.query_llm
            return type("R", (), {"score": 8, "passed": True})()

        _vm.verify_synthesis = _spy_verify

        try:
            session_data = {
                "session_id": "board_replay_test",
                "user_query": "q",
                "stage1": [],
                "stage2": [],
                "stage3": {"content": "existing synth"},
                "classification": {"query_type": "product", "complexity": "simple"},
                "verification": {"score": 7, "passed": True},
            }

            async def run():
                await _rerun_stage3_and_verify(
                    session_data,
                    candidate_config_path=None,
                    verify=True,
                )

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(run())
            finally:
                loop.close()

            # During replay, both modules' query_llm MUST NOT be the original.
            self.assertIn("orch", seen_refs)
            self.assertIsNot(
                seen_refs["orch"], original_orch,
                "orchestrator.query_llm was not patched during replay",
            )
            self.assertIn("verif", seen_refs)
            self.assertIsNot(
                seen_refs["verif"], original_verif,
                "verification.query_llm was not patched during replay",
            )
        finally:
            _om.BoardOrchestrator.stage3 = original_stage3
            _vm.verify_synthesis = original_verify_synthesis
            # Sanity: both refs restored after replay.
            self.assertIs(orch_module.query_llm, original_orch)
            self.assertIs(verif_module.query_llm, original_verif)


if __name__ == "__main__":
    unittest.main()
