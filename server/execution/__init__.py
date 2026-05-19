"""Execution domain public interface."""

from .agents import (
    ExecutionAgent,
    SubAgentTemplate,
    get_execution_agent,
    list_execution_agents,
)
from pathlib import Path

from . import evidence as _evidence
from . import tasks as _tasks
from .evidence import EvidencePacket, EvidenceSource
from .tasks import (
    DelegatedTask,
    DelegationPlan,
    ExecutionError,
    Subtask,
    SubtaskPlan,
    default_subtask_plan,
    parse_delegation_plan,
)
from .units import ExecutionUnit, list_execution_units
from .web_search import WebSearchError, web_search
from server.harness.hooks import HookDeniedError

_DEFAULT_DB_PATH: Path | None = _tasks.DEFAULT_DB_PATH
_EVIDENCE_DIR = _evidence._EVIDENCE_DIR


def record_delegation_plan(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _tasks.record_delegation_plan(*args, **kwargs)


def save_delegated_task(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _tasks.save_delegated_task(*args, **kwargs)


def get_delegated_task(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _tasks.get_delegated_task(*args, **kwargs)


def get_delegation_plan(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _tasks.get_delegation_plan(*args, **kwargs)


def approve_delegated_task(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _tasks.approve_delegated_task(*args, **kwargs)


def get_delegated_tasks_for_initiative(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _tasks.get_delegated_tasks_for_initiative(*args, **kwargs)


def approve_external_action(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _tasks.approve_external_action(*args, **kwargs)


def plan_delegated_task(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _tasks.plan_delegated_task(*args, **kwargs)


def update_delegated_task_status(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _tasks.update_delegated_task_status(*args, **kwargs)


def attach_task_artifact(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _tasks.attach_task_artifact(*args, **kwargs)


def create_evidence_packet(*args, **kwargs):
    """Compatibility wrapper honoring package-level `_EVIDENCE_DIR` patches."""
    _evidence._EVIDENCE_DIR = _EVIDENCE_DIR
    return _evidence.create_evidence_packet(*args, **kwargs)


def get_evidence_packet(*args, **kwargs):
    """Compatibility wrapper honoring package-level `_EVIDENCE_DIR` patches."""
    _evidence._EVIDENCE_DIR = _EVIDENCE_DIR
    return _evidence.get_evidence_packet(*args, **kwargs)


__all__ = [
    "DelegatedTask",
    "DelegationPlan",
    "EvidencePacket",
    "EvidenceSource",
    "ExecutionAgent",
    "ExecutionError",
    "ExecutionUnit",
    "HookDeniedError",
    "WebSearchError",
    "SubAgentTemplate",
    "Subtask",
    "SubtaskPlan",
    "approve_delegated_task",
    "approve_external_action",
    "attach_task_artifact",
    "create_evidence_packet",
    "default_subtask_plan",
    "get_delegated_task",
    "get_delegated_tasks_for_initiative",
    "get_delegation_plan",
    "get_evidence_packet",
    "get_execution_agent",
    "list_execution_agents",
    "list_execution_units",
    "parse_delegation_plan",
    "plan_delegated_task",
    "record_delegation_plan",
    "save_delegated_task",
    "update_delegated_task_status",
    "web_search",
]
