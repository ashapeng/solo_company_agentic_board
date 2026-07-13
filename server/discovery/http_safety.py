"""Shared bounded HTTP behavior for approved discovery adapters."""

from __future__ import annotations

import random
import threading
import time
from datetime import date
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx


USER_AGENT = "agentic-board-discovery/0.1 (read-only weekly research; contact via repository)"
TRANSIENT_STATUS = frozenset({500, 502, 503, 504})
STOP_STATUS = frozenset({401, 403, 429})
CHALLENGE_MARKERS = (
    "captcha",
    "verify you are human",
    "account challenge",
    "consent required",
)


class DiscoveryHttpStop(RuntimeError):
    """Request must stop for human/policy review; callers must not retry it."""


class SafeHttpClient:
    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30,
        follow_redirects: bool = False,
        max_retries: int = 2,
        daily_request_ceiling: int = 500,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
    ):
        self._client = httpx.Client(
            transport=transport,
            timeout=timeout,
            follow_redirects=follow_redirects,
            headers={"User-Agent": USER_AGENT},
        )
        self._max_retries = max(0, max_retries)
        self._daily_request_ceiling = max(1, daily_request_ceiling)
        self._sleep = sleep
        self._jitter = jitter
        self._request_day = date.today()
        self._request_count = 0
        self._count_lock = threading.Lock()
        self._host_locks: dict[str, threading.Lock] = {}

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def head(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("HEAD", url, **kwargs)

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        host = urlsplit(url).hostname
        if not host:
            raise DiscoveryHttpStop("request URL has no public host")
        lock = self._host_locks.setdefault(host.casefold(), threading.Lock())
        with lock:  # Per-host concurrency defaults to one.
            for attempt in range(self._max_retries + 1):
                self._consume_request()
                response = self._client.request(method, url, **kwargs)
                if response.status_code in STOP_STATUS:
                    raise DiscoveryHttpStop(
                        f"request stopped on HTTP {response.status_code}; human review required"
                    )
                self._detect_challenge(response)
                if response.status_code not in TRANSIENT_STATUS or attempt >= self._max_retries:
                    return response
                self._sleep(self._retry_delay(response, attempt))
        raise AssertionError("unreachable")

    def _consume_request(self) -> None:
        with self._count_lock:
            today = date.today()
            if today != self._request_day:
                self._request_day = today
                self._request_count = 0
            if self._request_count >= self._daily_request_ceiling:
                raise DiscoveryHttpStop("daily request ceiling reached; collection stopped")
            self._request_count += 1

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(300.0, max(0.0, float(retry_after)))
            except ValueError:
                try:
                    parsed = parsedate_to_datetime(retry_after)
                    return min(300.0, max(0.0, parsed.timestamp() - time.time()))
                except (TypeError, ValueError, OverflowError):
                    pass
        base = min(30.0, 0.5 * (2**attempt))
        return base + self._jitter(0, base / 4)

    @staticmethod
    def _detect_challenge(response: httpx.Response) -> None:
        content_type = response.headers.get("content-type", "").casefold()
        if "html" not in content_type:
            return
        sample = response.text[:20_000].casefold()
        if any(marker in sample for marker in CHALLENGE_MARKERS):
            raise DiscoveryHttpStop("request stopped on CAPTCHA, consent, or account challenge")
