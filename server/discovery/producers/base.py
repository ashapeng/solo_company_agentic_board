from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ProducerConfig:
    executable: str = "codex"
    model: str | None = None
    timeout_seconds: float = 600
    profile: str | None = None

    def __post_init__(self) -> None:
        if not self.executable.strip():
            raise ValueError("producer executable must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("producer timeout must be positive")


@dataclass(frozen=True)
class ProducerRequest:
    run_id: str
    week: str
    repository_dir: Path
    instructions_path: Path
    bundle_path: Path
    output_path: Path
    event_log_path: Path
    stderr_log_path: Path
    schema_path: Path

    def instructions(self) -> str:
        """Return the prepared instructions exactly as persisted."""
        return self.instructions_path.read_text(encoding="utf-8")


@dataclass(frozen=True)
class ProducerResult:
    status: str
    command: tuple[str, ...]
    exit_code: int | None = None
    timed_out: bool = False
    message: str | None = None


class SynthesisProducer(Protocol):
    name: str
    version: str

    def produce(self, request: ProducerRequest) -> ProducerResult: ...
