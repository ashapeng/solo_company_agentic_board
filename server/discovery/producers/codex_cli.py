from __future__ import annotations

import subprocess
from pathlib import Path

from server.discovery.store import DiscoveryStore

from .base import ProducerConfig, ProducerRequest, ProducerResult


def build_codex_command(config: ProducerConfig, request: ProducerRequest) -> list[str]:
    command = [
        config.executable,
        "exec",
        "--json",
        "--sandbox",
        "read-only",
        "--cd",
        str(request.repository_dir.resolve()),
        "--output-schema",
        str(request.schema_path.resolve()),
        "--output-last-message",
        str(request.output_path.resolve()),
    ]
    if config.model:
        command.extend(("--model", config.model))
    if config.profile:
        command.extend(("--profile", config.profile))
    command.append("-")
    return command


def redact_command(command: list[str]) -> list[str]:
    """Defensive redaction if future Codex options introduce command-line secrets."""
    secret_flags = {"--api-key", "--token", "--password"}
    redacted: list[str] = []
    hide_next = False
    for argument in command:
        if hide_next:
            redacted.append("[REDACTED]")
            hide_next = False
        else:
            redacted.append(argument)
            hide_next = argument.casefold() in secret_flags
    return redacted


class CodexCliProducer:
    name = "codex-cli"
    version = "1"

    def __init__(self, config: ProducerConfig | None = None):
        self.config = config or ProducerConfig()

    def command(self, request: ProducerRequest) -> list[str]:
        return build_codex_command(self.config, request)

    def produce(self, request: ProducerRequest) -> ProducerResult:
        command = self.command(request)
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            process = subprocess.Popen(
                command,
                cwd=request.repository_dir,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                shell=False,
            )
            try:
                stdout, stderr = process.communicate(
                    input=request.instructions(), timeout=self.config.timeout_seconds
                )
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    stdout, stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    stdout, stderr = process.communicate()
                self._write_logs(request, stdout, stderr)
                return ProducerResult(
                    status="timed_out",
                    command=tuple(redact_command(command)),
                    exit_code=process.returncode,
                    timed_out=True,
                    message=f"Codex timed out after {self.config.timeout_seconds:g}s",
                )
        except OSError as exc:
            self._write_logs(request, "", str(exc))
            return ProducerResult(
                status="failed",
                command=tuple(redact_command(command)),
                message=f"could not execute Codex: {exc}",
            )
        self._write_logs(request, stdout, stderr)
        return ProducerResult(
            status="completed" if process.returncode == 0 else "failed",
            command=tuple(redact_command(command)),
            exit_code=process.returncode,
            message=None if process.returncode == 0 else "Codex exited unsuccessfully",
        )

    @staticmethod
    def _write_logs(request: ProducerRequest, stdout: str, stderr: str) -> None:
        # Codex --json stdout is retained verbatim as the audit JSONL stream.
        DiscoveryStore._atomic_write(request.event_log_path, stdout)
        DiscoveryStore._atomic_write(request.stderr_log_path, stderr)
