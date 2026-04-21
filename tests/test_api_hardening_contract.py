# tests/test_api_hardening_contract.py
"""Phase 0 reproduction tests for API hardening plan.

These MUST FAIL on current main. They lock the diagnosis for:
  1. Path traversal on /sessions/{session_id}
  2. Missing rate limit on /deliberate
  3. CORS wildcard methods/headers

Tests authenticate as a remote client via the bearer-token path because
Starlette's TestClient presents a non-local client host that otherwise
trips the `enforce_local_only` middleware.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from server.api.app import app


def _make_fake_request(client_host: str = "1.2.3.4", xff: str | None = None):
    from starlette.datastructures import Headers
    class _Client:
        def __init__(self, h): self.host = h
    class _Request:
        def __init__(self, h, xff):
            self.client = _Client(h) if h else None
            self.headers = Headers({"x-forwarded-for": xff} if xff else {})
    return _Request(client_host, xff)


_TEST_TOKEN = "test-token-phase-0"


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


class SessionIdPathTraversalTest(unittest.TestCase):
    def setUp(self):
        _set_remote_auth_env()
        self.client = _auth_client()

    def tearDown(self):
        _unset_remote_auth_env()

    def test_traversal_in_session_id_is_rejected(self):
        resp = self.client.get("/sessions/..%2F..%2Fetc%2Fpasswd")
        self.assertEqual(
            resp.status_code, 400,
            f"expected 400 invalid_session_id, got {resp.status_code}: {resp.text}",
        )
        detail = resp.json().get("detail", {})
        if isinstance(detail, dict):
            self.assertEqual(detail.get("code"), "invalid_session_id")
        else:  # pragma: no cover - structural guard
            self.fail(f"detail was not a dict: {detail!r}")

    def test_adapter_route_also_rejects_traversal(self):
        resp = self.client.get("/sessions/..%2F..%2Fetc%2Fpasswd/adapter")
        self.assertEqual(
            resp.status_code, 400,
            f"expected 400 invalid_session_id, got {resp.status_code}: {resp.text}",
        )

    def test_delegation_plan_route_also_rejects_traversal(self):
        resp = self.client.get("/sessions/..%2F..%2Fetc%2Fpasswd/delegation-plan")
        self.assertEqual(
            resp.status_code, 400,
            f"expected 400 invalid_session_id, got {resp.status_code}: {resp.text}",
        )

    def test_feedback_route_also_rejects_traversal(self):
        resp = self.client.post(
            "/sessions/..%2F..%2Fetc%2Fpasswd/feedback",
            json={"rating": "positive"},
        )
        self.assertEqual(
            resp.status_code, 400,
            f"expected 400 invalid_session_id, got {resp.status_code}: {resp.text}",
        )

    def test_valid_session_id_shape_is_accepted(self):
        # Shape is valid even if session file is absent (→ 404 by design).
        resp = self.client.get("/sessions/board_1700000000")
        self.assertIn(resp.status_code, (200, 404))


class DeliberateRateLimitTest(unittest.TestCase):
    def setUp(self):
        _set_remote_auth_env()
        self._saved_rate_limit = os.environ.get("AGENTIC_BOARD_DELIBERATE_RATE_LIMIT")
        self._saved_rate_window = os.environ.get(
            "AGENTIC_BOARD_DELIBERATE_RATE_WINDOW_SECONDS",
        )
        os.environ["AGENTIC_BOARD_DELIBERATE_RATE_LIMIT"] = "3"
        os.environ["AGENTIC_BOARD_DELIBERATE_RATE_WINDOW_SECONDS"] = "60"
        self.client = _auth_client()

    def tearDown(self):
        _unset_remote_auth_env()
        for key, saved in (
            ("AGENTIC_BOARD_DELIBERATE_RATE_LIMIT", self._saved_rate_limit),
            ("AGENTIC_BOARD_DELIBERATE_RATE_WINDOW_SECONDS", self._saved_rate_window),
        ):
            if saved is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = saved
        # Purge module-level bucket between tests if it exists.
        try:
            from server.api.routes import board as board_routes
            bucket = getattr(board_routes, "_DELIBERATE_REQUESTS", None)
            if bucket is not None and hasattr(bucket, "clear"):
                bucket.clear()
        except Exception:
            pass

    def test_fourth_request_in_window_is_rate_limited(self):
        fake = AsyncMock()
        fake.return_value = type("S", (), {"to_dict": lambda self: {"ok": True}})()
        with patch(
            "server.api.routes.board.BoardOrchestrator.deliberate",
            new=fake,
        ):
            for _ in range(3):
                resp = self.client.post("/deliberate", json={"query": "ping"})
                self.assertEqual(resp.status_code, 200, resp.text)
            resp = self.client.post("/deliberate", json={"query": "ping"})
        self.assertEqual(resp.status_code, 429)
        detail = resp.json().get("detail", {})
        if isinstance(detail, dict):
            self.assertEqual(detail.get("code"), "rate_limited")
        else:
            self.fail(f"detail was not a dict: {detail!r}")
        self.assertIn("Retry-After", resp.headers)


class CorsTighteningTest(unittest.TestCase):
    def setUp(self):
        _set_remote_auth_env()
        self.client = _auth_client()

    def tearDown(self):
        _unset_remote_auth_env()

    def test_unexpected_method_is_not_advertised(self):
        resp = self.client.options(
            "/deliberate",
            headers={
                "Origin": "http://127.0.0.1:8000",
                "Access-Control-Request-Method": "TRACE",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        allow_methods = resp.headers.get("access-control-allow-methods", "")
        self.assertTrue(
            allow_methods,
            f"expected CORS allow-methods header to be present; got headers={dict(resp.headers)}",
        )
        self.assertNotIn("TRACE", allow_methods)
        self.assertNotEqual(allow_methods.strip(), "*")

    def test_unexpected_header_is_not_echoed(self):
        resp = self.client.options(
            "/deliberate",
            headers={
                "Origin": "http://127.0.0.1:8000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-evil",
            },
        )
        allow_headers = resp.headers.get("access-control-allow-headers", "").lower()
        self.assertTrue(
            allow_headers,
            f"expected CORS allow-headers header to be present; got headers={dict(resp.headers)}",
        )
        self.assertNotIn("x-evil", allow_headers)
        self.assertNotEqual(allow_headers.strip(), "*")


class DeliberateBucketKeyTest(unittest.TestCase):
    def test_default_uses_client_host(self):
        from server.api.routes.board import _deliberate_bucket_key
        request = _make_fake_request(client_host="1.2.3.4", xff=None)
        self.assertEqual(_deliberate_bucket_key(request), "1.2.3.4")

    def test_flag_off_ignores_forwarded_for(self):
        from server.api.routes.board import _deliberate_bucket_key
        request = _make_fake_request(client_host="10.0.0.1", xff="9.9.9.9")
        self.assertEqual(_deliberate_bucket_key(request), "10.0.0.1")

    def test_flag_on_prefers_forwarded_for(self):
        from server.api.routes.board import _deliberate_bucket_key
        os.environ["AGENTIC_BOARD_TRUST_FORWARDED_FOR"] = "1"
        try:
            request = _make_fake_request(client_host="10.0.0.1", xff="5.6.7.8")
            self.assertEqual(_deliberate_bucket_key(request), "5.6.7.8")
        finally:
            os.environ.pop("AGENTIC_BOARD_TRUST_FORWARDED_FOR", None)

    def test_flag_on_falls_back_when_xff_absent(self):
        from server.api.routes.board import _deliberate_bucket_key
        os.environ["AGENTIC_BOARD_TRUST_FORWARDED_FOR"] = "1"
        try:
            request = _make_fake_request(client_host="10.0.0.1", xff=None)
            self.assertEqual(_deliberate_bucket_key(request), "10.0.0.1")
        finally:
            os.environ.pop("AGENTIC_BOARD_TRUST_FORWARDED_FOR", None)

    def test_flag_on_uses_first_of_multiple_xff_hops(self):
        from server.api.routes.board import _deliberate_bucket_key
        os.environ["AGENTIC_BOARD_TRUST_FORWARDED_FOR"] = "1"
        try:
            request = _make_fake_request(client_host="10.0.0.1", xff="5.6.7.8, 9.9.9.9")
            self.assertEqual(_deliberate_bucket_key(request), "5.6.7.8")
        finally:
            os.environ.pop("AGENTIC_BOARD_TRUST_FORWARDED_FOR", None)


class DeliberateBucketEvictionTest(unittest.TestCase):
    def test_empty_buckets_are_swept(self):
        from server.api.routes import board as board_routes
        from collections import deque
        board_routes._DELIBERATE_REQUESTS.clear()
        board_routes._DELIBERATE_REQUESTS["stale_ip"] = deque()
        request = _make_fake_request(client_host="1.2.3.4")
        board_routes._enforce_deliberate_rate_limit(request)
        self.assertNotIn("stale_ip", board_routes._DELIBERATE_REQUESTS)
        self.assertIn("1.2.3.4", board_routes._DELIBERATE_REQUESTS)
        board_routes._DELIBERATE_REQUESTS.clear()
