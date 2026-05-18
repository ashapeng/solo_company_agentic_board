"""Static dry-run validator for HarnessConfig (Phase 1).

Zero LLM calls. Catches typos and structurally broken configs before
`apply_harness_review` writes them. See
`docs/superpowers/specs/2026-05-18-harness-cross-cutting-expansion-design.md`
§4 for the design.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Literal

from .config import HarnessConfig


Severity = Literal["error", "warning"]
Readiness = Literal["ready", "warning", "blocked"]


@dataclass(frozen=True)
class ValidationIssue:
    """A single check result with a stable code and dotted config path."""
    code: str
    path: str
    message: str
    severity: Severity


@dataclass(frozen=True)
class ValidationReport:
    """The output of validate_config(); see spec §4.1."""
    ok: bool
    errors: list[ValidationIssue]
    warnings: list[ValidationIssue]
    readiness: Readiness

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "readiness": self.readiness,
            "errors": [
                {
                    "code": issue.code,
                    "path": issue.path,
                    "message": issue.message,
                    "severity": issue.severity,
                }
                for issue in self.errors
            ],
            "warnings": [
                {
                    "code": issue.code,
                    "path": issue.path,
                    "message": issue.message,
                    "severity": issue.severity,
                }
                for issue in self.warnings
            ],
        }


def validate_config(candidate: HarnessConfig | dict) -> ValidationReport:
    """Validate a HarnessConfig candidate.

    Per spec §4.1: accepts either a `HarnessConfig` dataclass or a plain dict
    (e.g. parsed straight from JSON). Returns a `ValidationReport` with the
    overall readiness verdict and lists of errors and warnings.
    """
    config = _coerce_to_config(candidate)
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    # Future tasks add: schema, cross-ref, safety checks here.
    readiness = _compute_readiness(errors, warnings)
    return ValidationReport(
        ok=(readiness == "ready"),
        errors=errors,
        warnings=warnings,
        readiness=readiness,
    )


def _coerce_to_config(candidate: HarnessConfig | dict) -> HarnessConfig:
    """Accept either a HarnessConfig or a plain dict; return HarnessConfig."""
    if isinstance(candidate, HarnessConfig):
        return candidate
    if not isinstance(candidate, dict):
        raise TypeError(
            f"validate_config expects HarnessConfig or dict, got {type(candidate).__name__}"
        )
    known_fields = {f.name for f in fields(HarnessConfig)}
    filtered = {k: v for k, v in candidate.items() if k in known_fields}
    return HarnessConfig(**filtered)


def _compute_readiness(
    errors: list[ValidationIssue], warnings: list[ValidationIssue],
) -> Readiness:
    if errors:
        return "blocked"
    if warnings:
        return "warning"
    return "ready"
