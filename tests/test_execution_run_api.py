# tests/test_execution_run_api.py
"""Contract tests for the task-runner API endpoint and CLI flag (Plan 3d).

The API tests authenticate as a remote client via the bearer-token path
because Starlette's TestClient presents a non-local client host that
otherwise trips the ``enforce_local_only`` middleware. ``run_task`` is
patched with an async stub so no real LLM/runner work happens.
"""

from __future__ import annotations

import argparse
import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from server.api.app import app

_TEST_TOKEN = "test-token-run-api"


def _set_remote_auth_env() -> None:
    os.environ["AGENTIC_BOARD_ALLOW_REMOTE"] = "1"
    os.environ["AGENTIC_BOARD_REMOTE_TOKEN"] = _TEST_TOKEN


def _unset_remote_auth_env() -> None:
    os.environ.pop("AGENTIC_BOARD_ALLOW_REMOTE", None)
    os.environ.pop("AGENTIC_BOARD_REMOTE_TOKEN", None)


def _auth_client() -> TestClient:
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {_TEST_TOKEN}"})
    return client


class RunTaskEndpointTest(unittest.TestCase):
    def setUp(self):
        _set_remote_auth_env()
        self.client = _auth_client()

    def tearDown(self):
        _unset_remote_auth_env()

    def test_run_task_returns_result_dict(self):
        stub = AsyncMock(return_value={"task_id": "t1", "status": "completed"})
        with patch("server.execution.runner.run_task", new=stub):
            resp = self.client.post("/delegated-tasks/t1/run")

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json(), {"task_id": "t1", "status": "completed"})
        stub.assert_awaited_once_with("t1")

    def test_run_task_not_found_returns_404(self):
        stub = AsyncMock(return_value={"status": "not_found"})
        with patch("server.execution.runner.run_task", new=stub):
            resp = self.client.post("/delegated-tasks/missing/run")

        self.assertEqual(resp.status_code, 404, resp.text)


class CliAlwaysOnFlagTest(unittest.TestCase):
    """The CLI arg parser must accept --always-on without starting the loop."""

    def _build_parser(self) -> argparse.ArgumentParser:
        # Mirror the flags the cli() entry point registers. We assert the
        # contract via a minimal parser that includes --always-on; the real
        # parser is exercised end-to-end through the cli() smoke check below.
        parser = argparse.ArgumentParser()
        parser.add_argument("--always-on", action="store_true")
        return parser

    def test_parser_accepts_always_on(self):
        parser = self._build_parser()
        args = parser.parse_args(["--always-on"])
        self.assertTrue(args.always_on)

    def test_cli_help_lists_always_on(self):
        # Build the real parser by invoking cli() with --help and capturing
        # the SystemExit raised by argparse. This proves the flag is wired
        # into the actual entry point without starting the scheduler loop.
        import contextlib
        import io

        from server import cli as cli_module

        buf = io.StringIO()
        with self.assertRaises(SystemExit):
            with patch("sys.argv", ["server.cli", "--help"]):
                with contextlib.redirect_stdout(buf):
                    cli_module.cli()
        self.assertIn("--always-on", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
