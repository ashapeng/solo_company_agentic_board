from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from server.discovery.store import DiscoveryStore


RUN_STATUSES = frozenset(
    {"pending", "running", "failed", "timed_out", "invalid_output", "completed"}
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProducerRun:
    id: str
    week: str
    producer_name: str
    producer_version: str
    status: str
    prepared_bundle: str
    instructions: str
    output: str
    events: str
    stderr: str
    schema: str
    command: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    timed_out: bool = False
    validation: dict[str, Any] | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.status not in RUN_STATUSES:
            raise ValueError(f"unknown producer run status: {self.status}")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ProducerRun":
        return cls(**value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProducerRunStore:
    """File-native producer run ledger; run output and logs live beside each record."""

    def __init__(self, discovery_root: Path):
        self.discovery_root = Path(discovery_root)
        self.root = self.discovery_root / "producer-runs"

    def paths(self, run_id: str) -> dict[str, Path]:
        return {
            "record": self.root / f"{run_id}.json",
            "output": self.root / f"{run_id}.output.json",
            "events": self.root / f"{run_id}.events.jsonl",
            "stderr": self.root / f"{run_id}.stderr.log",
        }

    def create(
        self,
        *,
        week: str,
        producer_name: str,
        producer_version: str,
        prepared_bundle: Path,
        instructions: Path,
        schema: Path,
        run_id: str | None = None,
        status: str = "pending",
    ) -> ProducerRun:
        run_id = run_id or f"run_{uuid4().hex}"
        if self.get(run_id) is not None:
            raise ValueError(f"producer run already exists: {run_id}")
        paths = self.paths(run_id)
        run = ProducerRun(
            id=run_id,
            week=week,
            producer_name=producer_name,
            producer_version=producer_version,
            status=status,
            prepared_bundle=str(prepared_bundle),
            instructions=str(instructions),
            output=str(paths["output"]),
            events=str(paths["events"]),
            stderr=str(paths["stderr"]),
            schema=str(schema),
        )
        return self.save(run)

    def save(self, run: ProducerRun) -> ProducerRun:
        run.__post_init__()
        path = self.paths(run.id)["record"]
        DiscoveryStore._atomic_write(
            path, json.dumps(run.to_dict(), indent=2, ensure_ascii=False) + "\n"
        )
        return run

    def get(self, run_id: str) -> ProducerRun | None:
        path = self.paths(run_id)["record"]
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("root must be an object")
            run = ProducerRun.from_dict(value)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid producer run {path}: {exc}") from exc
        if run.id != run_id:
            raise ValueError(f"invalid producer run {path}: id mismatch")
        return run

    def list(self, *, week: str | None = None) -> list[ProducerRun]:
        if not self.root.exists():
            return []
        record_paths = (
            path for path in sorted(self.root.glob("run_*.json")) if "." not in path.stem
        )
        runs = [self.get(path.stem) for path in record_paths]
        return [run for run in runs if run is not None and (week is None or run.week == week)]

    def request(self, run: ProducerRun, repository_dir: Path) -> "ProducerRequest":
        from .base import ProducerRequest

        return ProducerRequest(
            run_id=run.id,
            week=run.week,
            repository_dir=repository_dir,
            instructions_path=Path(run.instructions),
            bundle_path=Path(run.prepared_bundle),
            output_path=Path(run.output),
            event_log_path=Path(run.events),
            stderr_log_path=Path(run.stderr),
            schema_path=Path(run.schema),
        )

    @staticmethod
    def resumable(run: ProducerRun) -> bool:
        return run.status in {"pending", "failed", "timed_out", "invalid_output"}

    def mark_started(self, run: ProducerRun, command: list[str]) -> ProducerRun:
        run.status = "running"
        run.command = command
        run.started_at = utc_now()
        run.finished_at = None
        return self.save(run)

    def apply_result(self, run: ProducerRun, result: "ProducerResult") -> ProducerRun:
        from .base import ProducerResult

        if not isinstance(result, ProducerResult):
            raise TypeError("result must be a ProducerResult")
        run.status = result.status
        run.command = list(result.command)
        run.exit_code = result.exit_code
        run.timed_out = result.timed_out
        if result.status != "pending":
            run.finished_at = utc_now()
        return self.save(run)

    def record_validation(
        self, run: ProducerRun, *, valid: bool, error: str | None = None
    ) -> ProducerRun:
        run.validation = {"valid": valid, "validated_at": utc_now(), "error": error}
        run.status = "completed" if valid else "invalid_output"
        run.finished_at = utc_now()
        return self.save(run)
