from __future__ import annotations

import shlex

from .base import ProducerConfig, ProducerRequest, ProducerResult
from .codex_cli import build_codex_command, redact_command


class ManualHandoffProducer:
    name = "manual-handoff"
    version = "1"

    def __init__(self, config: ProducerConfig | None = None):
        self.config = config or ProducerConfig()

    def command(self, request: ProducerRequest) -> list[str]:
        return build_codex_command(self.config, request)

    def handoff_text(self, request: ProducerRequest) -> str:
        command = shlex.join(redact_command(self.command(request)))
        runnable = f"{command} < {shlex.quote(str(request.instructions_path))}"
        return (
            f"Run ID: {request.run_id}\n"
            f"Prepared bundle: {request.bundle_path}\n"
            f"Instructions: {request.instructions_path}\n"
            f"Output schema: {request.schema_path}\n"
            f"Candidate output: {request.output_path}\n"
            f"Command: {runnable}\n"
            "The prepared instructions identify the already-collected bundle; Codex must not "
            "collect from the network.\n"
        )

    def produce(self, request: ProducerRequest) -> ProducerResult:
        command = redact_command(self.command(request))
        return ProducerResult(
            status="pending",
            command=tuple(command),
            message=self.handoff_text(request),
        )
