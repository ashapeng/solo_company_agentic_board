"""Stable mapping from external channel identities to board sessions.

A single external thread (e.g. one Telegram chat) should resume the SAME
board session across messages so context can accumulate. The mapper turns the
triple ``(channel_key, external_user_id, external_thread_id)`` into a stable
board ``session_id`` (and a ``venture_id``).

The session_id is derived deterministically (hash of the triple) so that the
same conversation always resolves to the same id, even across process
restarts, while different threads always get distinct ids.
"""

from __future__ import annotations

import hashlib


def _stable_session_id(channel_key: str, user_id: str, thread_id: str) -> str:
    """Deterministic, collision-resistant session id for a channel triple."""
    raw = f"{channel_key}\x1f{user_id}\x1f{thread_id}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:16]
    return f"chan_{channel_key}_{digest}"


class SessionMapper:
    """Resolve external channel identities to stable board sessions.

    In-memory cache is purely an optimization; ids are deterministic, so a
    cold mapper still resolves a returning thread to the same session.
    """

    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str, str], tuple[str, str]] = {}

    def resolve(
        self,
        channel_key: str,
        user_id: str,
        thread_id: str,
        *,
        venture_id: str = "default",
    ) -> tuple[str, str]:
        """Return ``(session_id, venture_id)`` for a channel identity.

        The same triple always yields the same session_id; distinct triples
        yield distinct ids. First contact records the mapping; repeat contact
        returns the cached pair.
        """
        key = (str(channel_key), str(user_id), str(thread_id))
        existing = self._sessions.get(key)
        if existing is not None:
            return existing

        session_id = _stable_session_id(*key)
        pair = (session_id, venture_id)
        self._sessions[key] = pair
        return pair
