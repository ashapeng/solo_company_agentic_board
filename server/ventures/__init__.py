"""Venture (WorkSpace) domain public interface."""

from pathlib import Path

from . import store as _store
from .models import (
    DEFAULT_VENTURE_ID,
    DEFAULT_VENTURE_SLUG,
    Venture,
    VentureError,
    VentureStatus,
    venture_slug,
)

_DEFAULT_DB_PATH: Path | None = _store.DEFAULT_DB_PATH


def create_venture(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.create_venture(*args, **kwargs)


def get_venture(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.get_venture(*args, **kwargs)


def get_venture_by_slug(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.get_venture_by_slug(*args, **kwargs)


def list_ventures(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.list_ventures(*args, **kwargs)


def ensure_default_venture(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.ensure_default_venture(*args, **kwargs)


def update_venture(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.update_venture(*args, **kwargs)


__all__ = [
    "DEFAULT_VENTURE_ID",
    "DEFAULT_VENTURE_SLUG",
    "Venture",
    "VentureError",
    "VentureStatus",
    "venture_slug",
    "create_venture",
    "ensure_default_venture",
    "get_venture",
    "get_venture_by_slug",
    "list_ventures",
    "update_venture",
]
