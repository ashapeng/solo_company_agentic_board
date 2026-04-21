# server/execution/search_cache.py
"""Tiny TTL+LRU cache for web search results.

Used to avoid re-hitting a search provider for identical queries within a
short window. Not thread-safe by design; callers run in a single asyncio
event loop.
"""

from __future__ import annotations

import time
from collections import OrderedDict


class SearchCache:
    def __init__(self, maxsize: int = 128, ttl_seconds: int = 1800):
        self.maxsize = maxsize
        self.ttl_seconds = ttl_seconds
        self._store: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()

    def get(self, key: tuple) -> dict | None:
        entry = self._store.get(key)
        if not entry:
            return None
        ts, value = entry
        if time.monotonic() - ts > self.ttl_seconds:
            self._store.pop(key, None)
            return None
        self._store.move_to_end(key)
        return value

    def put(self, key: tuple, value: dict) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = (time.monotonic(), value)
        while len(self._store) > self.maxsize:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()
