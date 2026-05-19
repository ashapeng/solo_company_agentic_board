"""Test bootstrap: load .env so live tests can reach provider APIs.

Live tests (`@pytest.mark.live`) call the real LLM pipeline via
`evals.runner.run_corpus`, which only loads dotenv inside its own `main()`.
Importing `run_corpus` directly skips that, leaving provider API keys unset.
Loading here keeps unit tests unaffected (they mock providers) while letting
`pytest -m live` exercise the real stack.
"""
from __future__ import annotations

import pytest
from dotenv import load_dotenv

load_dotenv()


@pytest.fixture(autouse=True)
def _unit_test_hook_rate_limits(monkeypatch, request):
    if request.node.get_closest_marker("live"):
        return
    monkeypatch.setenv("AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT", "1000")
    monkeypatch.setenv("AGENTIC_BOARD_DELEGATED_TASK_RATE_WINDOW_SECONDS", "1")
    monkeypatch.setenv("AGENTIC_BOARD_WEB_SEARCH_SESSION_CAP", "1000")
