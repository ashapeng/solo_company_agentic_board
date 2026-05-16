"""Test bootstrap: load .env so live tests can reach provider APIs.

Live tests (`@pytest.mark.live`) call the real LLM pipeline via
`evals.runner.run_corpus`, which only loads dotenv inside its own `main()`.
Importing `run_corpus` directly skips that, leaving provider API keys unset.
Loading here keeps unit tests unaffected (they mock providers) while letting
`pytest -m live` exercise the real stack.
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()
