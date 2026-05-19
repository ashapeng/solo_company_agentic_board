"""Initiative domain public interface."""

from pathlib import Path

from . import store as _store
from .models import (
    ApprovalState,
    CarryoverDecisionValue,
    CreatedFrom,
    FounderOutcome,
    Initiative,
    InitiativeCloseout,
    InitiativeError,
    InitiativeLink,
    InitiativeStatus,
    LinkRelationship,
    LinkTargetType,
)

_DEFAULT_DB_PATH: Path | None = _store.DEFAULT_DB_PATH


def create_initiative(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.create_initiative(*args, **kwargs)


def get_initiative(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.get_initiative(*args, **kwargs)


def list_initiatives(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.list_initiatives(*args, **kwargs)


def update_initiative(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.update_initiative(*args, **kwargs)


def activate_initiative(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.activate_initiative(*args, **kwargs)


def create_link(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.create_link(*args, **kwargs)


def list_links(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.list_links(*args, **kwargs)


def list_linked_session_ids(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.list_linked_session_ids(*args, **kwargs)


def delete_link(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.delete_link(*args, **kwargs)


def get_closeout(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.get_closeout(*args, **kwargs)


def close_initiative(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.close_initiative(*args, **kwargs)


__all__ = [
    "ApprovalState",
    "CarryoverDecisionValue",
    "CreatedFrom",
    "FounderOutcome",
    "Initiative",
    "InitiativeCloseout",
    "InitiativeError",
    "InitiativeLink",
    "InitiativeStatus",
    "LinkRelationship",
    "LinkTargetType",
    "activate_initiative",
    "close_initiative",
    "create_initiative",
    "create_link",
    "delete_link",
    "get_closeout",
    "get_initiative",
    "list_initiatives",
    "list_linked_session_ids",
    "list_links",
    "update_initiative",
]
