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

    _check_schema(config, errors)
    _check_model_preferences(config, errors)
    _check_suppressed_members(config, errors, warnings)
    _check_query_type_keys(config, warnings)
    _check_stage1_sections(config, errors)
    _check_hardening_models(config, errors)

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


_REQUIRED_COMPLEXITY_KEYS = {"simple", "moderate", "complex"}


def _allowed_models() -> set[str]:
    """Build the set of explicit allowed model IDs from the live project state.

    The check is: a model is allowed if its ID is in this set OR its prefix
    is in the known provider prefix set (see `_known_prefixes()`).
    """
    from server.board.config import (
        get_chairman_model,
        get_classifier_model,
        get_council_models,
        get_verification_model,
    )
    allowed: set[str] = set()
    allowed.add(get_chairman_model())
    allowed.add(get_classifier_model())
    allowed.add(get_verification_model())
    allowed.update(get_council_models())
    return {m for m in allowed if m}


def _known_prefixes() -> set[str]:
    """Set of provider prefixes recognised by the LLM client."""
    from server.board.llm import _PROVIDERS
    return set(_PROVIDERS.keys())


def _model_is_resolvable(model: str) -> bool:
    """A model ID resolves if either listed explicitly or its prefix is known.

    Mirrors `server.board.llm._split_model_id` semantics: `openrouter:<id>`
    has a colon, all others use `<prefix>/<id>`.
    """
    if not isinstance(model, str) or not model.strip():
        return False
    if model in _allowed_models():
        return True
    if model.startswith("openrouter:"):
        return "openrouter" in _known_prefixes()
    if "/" in model:
        prefix = model.split("/", 1)[0]
        return prefix in _known_prefixes()
    return False


def _check_model_preferences(
    config: HarnessConfig, errors: list[ValidationIssue],
) -> None:
    """Cross-ref every per_query_type.*.model_preferences entry."""
    per_qt = config.per_query_type if isinstance(config.per_query_type, dict) else {}
    for query_type, qt_config in per_qt.items():
        if not isinstance(qt_config, dict):
            continue
        prefs = qt_config.get("model_preferences")
        if not isinstance(prefs, dict):
            continue
        for member_id, model in prefs.items():
            if not _model_is_resolvable(model):
                errors.append(ValidationIssue(
                    code="xref.model_unknown",
                    path=f"per_query_type.{query_type}.model_preferences.{member_id}",
                    message=(
                        f"model {model!r} does not resolve: not in the allowed "
                        f"set and prefix not in {sorted(_known_prefixes())}"
                    ),
                    severity="error",
                ))


def _check_schema(config: HarnessConfig, errors: list[ValidationIssue]) -> None:
    """Schema checks: types/ranges/required keys for top-level fields."""
    from .tuning import (
        VERIFICATION_THRESHOLD_CEILING,
        VERIFICATION_THRESHOLD_FLOOR,
    )

    for stage_field in (
        "stage1_max_tokens",
        "stage2_max_tokens",
        "stage3_max_tokens",
        "stage4_max_tokens",
        "revision_max_tokens",
    ):
        value = getattr(config, stage_field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            errors.append(ValidationIssue(
                code="schema.stage_tokens_non_positive",
                path=stage_field,
                message=f"{stage_field} must be a positive int, got {value!r}",
                severity="error",
            ))

    for field_name in ("min_stage1_responses", "min_stage2_responses"):
        value = getattr(config, field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            errors.append(ValidationIssue(
                code="schema.min_responses_below_one",
                path=field_name,
                message=f"{field_name} must be >= 1, got {value!r}",
                severity="error",
            ))

    if (
        not isinstance(config.max_revision_attempts, int)
        or isinstance(config.max_revision_attempts, bool)
        or config.max_revision_attempts < 0
    ):
        errors.append(ValidationIssue(
            code="schema.max_revision_attempts_negative",
            path="max_revision_attempts",
            message=f"max_revision_attempts must be >= 0, got {config.max_revision_attempts!r}",
            severity="error",
        ))

    threshold = config.verification_threshold
    if (
        not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
        or threshold < VERIFICATION_THRESHOLD_FLOOR
        or threshold > VERIFICATION_THRESHOLD_CEILING
    ):
        errors.append(ValidationIssue(
            code="schema.verification_threshold_out_of_range",
            path="verification_threshold",
            message=(
                f"verification_threshold must be in "
                f"[{VERIFICATION_THRESHOLD_FLOOR}, {VERIFICATION_THRESHOLD_CEILING}], "
                f"got {threshold!r}"
            ),
            severity="error",
        ))

    multipliers = config.complexity_multipliers
    if not isinstance(multipliers, dict):
        errors.append(ValidationIssue(
            code="schema.complexity_multipliers_not_dict",
            path="complexity_multipliers",
            message=f"complexity_multipliers must be a dict, got {type(multipliers).__name__}",
            severity="error",
        ))
    else:
        missing = sorted(_REQUIRED_COMPLEXITY_KEYS - set(multipliers))
        if missing:
            errors.append(ValidationIssue(
                code="schema.complexity_multipliers_missing_keys",
                path="complexity_multipliers",
                message=f"complexity_multipliers missing required keys: {missing}",
                severity="error",
            ))

    if not isinstance(config.per_query_type, dict):
        errors.append(ValidationIssue(
            code="schema.per_query_type_not_dict",
            path="per_query_type",
            message=f"per_query_type must be a dict, got {type(config.per_query_type).__name__}",
            severity="error",
        ))

    if not isinstance(config.hardening, dict):
        errors.append(ValidationIssue(
            code="schema.hardening_not_dict",
            path="hardening",
            message=f"hardening must be a dict, got {type(config.hardening).__name__}",
            severity="error",
        ))


def _member_universe() -> tuple[set[str], set[str]]:
    """Return (active_ids, shelved_ids) read directly from server/members/*.md.

    Active = filenames without leading underscore. Shelved = filenames with
    leading underscore (and the file stem stripped of that underscore).
    Templates are filtered out via the `_template` shelved-id exclusion.
    """
    from pathlib import Path
    members_dir = Path(__file__).resolve().parent.parent / "members"
    active: set[str] = set()
    shelved: set[str] = set()
    if not members_dir.is_dir():
        return active, shelved
    for filepath in members_dir.glob("*.md"):
        if filepath.name.startswith("_"):
            stem = filepath.stem.lstrip("_")
            if stem and stem != "template":
                shelved.add(stem)
        else:
            active.add(filepath.stem)
    return active, shelved


def _check_suppressed_members(
    config: HarnessConfig,
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
) -> None:
    """Cross-ref every per_query_type.*.routing.suppressed_member_ids entry."""
    active, shelved = _member_universe()
    per_qt = config.per_query_type if isinstance(config.per_query_type, dict) else {}
    for query_type, qt_config in per_qt.items():
        if not isinstance(qt_config, dict):
            continue
        routing = qt_config.get("routing")
        if not isinstance(routing, dict):
            continue
        suppressed = routing.get("suppressed_member_ids")
        if not isinstance(suppressed, list):
            continue
        for member_id in suppressed:
            path = f"per_query_type.{query_type}.routing.suppressed_member_ids"
            if not isinstance(member_id, str) or not member_id.strip():
                errors.append(ValidationIssue(
                    code="xref.member_unknown",
                    path=path,
                    message=f"empty or non-string member ID {member_id!r}",
                    severity="error",
                ))
                continue
            if member_id in shelved:
                warnings.append(ValidationIssue(
                    code="xref.member_shelved",
                    path=path,
                    message=(
                        f"member {member_id!r} is shelved (file "
                        f"server/members/_{member_id}.md); suppression is a no-op"
                    ),
                    severity="warning",
                ))
                continue
            if member_id not in active:
                errors.append(ValidationIssue(
                    code="xref.member_unknown",
                    path=path,
                    message=(
                        f"member {member_id!r} not found under server/members/*.md "
                        f"(known active: {sorted(active)})"
                    ),
                    severity="error",
                ))


_HARDENING_MODEL_FIELDS = (
    "atomizer_model",
    "contradiction_judge_model",
    "sotb_judge_model",
    "auto_promote_summarizer_model",
)


def _known_query_types() -> set[str]:
    """Decision types enumerated in roster.yaml — the classifier output schema."""
    try:
        from server.board.roster import load_roster
        roster = load_roster()
    except Exception:
        return set()
    decision_types = roster.get("decision_types") or {}
    return set(decision_types.keys())


def _check_query_type_keys(
    config: HarnessConfig, warnings: list[ValidationIssue],
) -> None:
    known = _known_query_types()
    if not known:
        return
    per_qt = config.per_query_type if isinstance(config.per_query_type, dict) else {}
    for query_type in per_qt:
        if query_type not in known:
            warnings.append(ValidationIssue(
                code="xref.query_type_unknown",
                path=f"per_query_type.{query_type}",
                message=(
                    f"query_type {query_type!r} is not in roster.yaml "
                    f"decision_types (known: {sorted(known)})"
                ),
                severity="warning",
            ))


def _check_stage1_sections(
    config: HarnessConfig, errors: list[ValidationIssue],
) -> None:
    from .config import _VALID_STAGE1_COMPACTION_SECTIONS
    per_qt = config.per_query_type if isinstance(config.per_query_type, dict) else {}
    for query_type, qt_config in per_qt.items():
        if not isinstance(qt_config, dict):
            continue
        compaction = qt_config.get("compaction")
        if not isinstance(compaction, dict):
            continue
        for sub_key in ("stage1_sections", "stage1_detail_sections"):
            sections = compaction.get(sub_key)
            if not isinstance(sections, list):
                continue
            for section in sections:
                if not isinstance(section, str):
                    errors.append(ValidationIssue(
                        code="xref.stage1_section_unknown",
                        path=f"per_query_type.{query_type}.compaction.{sub_key}",
                        message=f"non-string section entry {section!r}",
                        severity="error",
                    ))
                    continue
                normalized = section.lower()
                if normalized == "tl;dr":
                    normalized = "tldr"
                if normalized not in _VALID_STAGE1_COMPACTION_SECTIONS:
                    errors.append(ValidationIssue(
                        code="xref.stage1_section_unknown",
                        path=f"per_query_type.{query_type}.compaction.{sub_key}",
                        message=(
                            f"section {section!r} is not valid (allowed: "
                            f"{sorted(_VALID_STAGE1_COMPACTION_SECTIONS)})"
                        ),
                        severity="error",
                    ))


def _check_hardening_models(
    config: HarnessConfig, errors: list[ValidationIssue],
) -> None:
    hardening = config.hardening if isinstance(config.hardening, dict) else {}
    for field_name in _HARDENING_MODEL_FIELDS:
        value = hardening.get(field_name)
        if value is None:
            continue  # None falls back to atomizer_model per spec §4.2
        if not _model_is_resolvable(value):
            errors.append(ValidationIssue(
                code="xref.hardening_model_unknown",
                path=f"hardening.{field_name}",
                message=(
                    f"hardening.{field_name} = {value!r} does not resolve: "
                    f"not in allowed set and prefix not in {sorted(_known_prefixes())}"
                ),
                severity="error",
            ))
