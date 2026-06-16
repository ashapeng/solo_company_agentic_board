"""Venture (WorkSpace) domain models and serialization helpers."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal


VentureStatus = Literal["active", "archived"]

DEFAULT_VENTURE_ID = "default"
DEFAULT_VENTURE_SLUG = "default"

_MAX_SLUG_LENGTH = 40
_SLUG_INVALID = re.compile(r"[^a-z0-9]+")
_SLUG_TRIM = re.compile(r"^-+|-+$")


class VentureError(Exception):
    """Raised when venture state cannot be read or changed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def venture_slug(value: str) -> str:
    """Produce a filesystem-safe slug for a venture.

    Lowercase, alphanumerics and hyphens only, collapsed and trimmed, capped at
    ~40 characters. Falls back to a stable hash when the input has no usable
    characters. The result never contains path separators or ``..`` so it is
    safe to use as a directory name.
    """
    text = str(value or "").strip().lower()
    slug = _SLUG_INVALID.sub("-", text)
    slug = _SLUG_TRIM.sub("", slug)
    slug = slug[:_MAX_SLUG_LENGTH]
    slug = _SLUG_TRIM.sub("", slug)
    if not slug:
        digest = hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()
        slug = f"v-{digest[:12]}"
    return slug


@dataclass
class Venture:
    id: str
    name: str
    slug: str
    status: VentureStatus = "active"
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
