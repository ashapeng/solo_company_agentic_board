"""Execution unit registry derived from persistent manager agents."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .agents import EXECUTION_AGENTS


@dataclass(frozen=True)
class ExecutionUnit:
    id: str
    title: str
    description: str
    capabilities: list[str]
    manager_agent_id: str
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


EXECUTION_UNITS = [
    ExecutionUnit(
        id=agent.execution_unit_id,
        title=agent.title.replace(" Agent", " Unit"),
        description=agent.role,
        capabilities=agent.capabilities,
        manager_agent_id=agent.id,
        active=agent.active,
    )
    for agent in EXECUTION_AGENTS
]


def list_execution_units(*, active_only: bool = False) -> list[dict[str, Any]]:
    units = EXECUTION_UNITS
    if active_only:
        units = [unit for unit in units if unit.active]
    return [unit.to_dict() for unit in units]
