"""Single source of truth for tunable harness parameters."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path


_DEFAULT_CONFIG_PATH = Path(__file__).parent / "harness_config.json"
_STAGE_TOKEN_FIELDS = {
    1: "stage1_max_tokens",
    2: "stage2_max_tokens",
    3: "stage3_max_tokens",
    4: "stage4_max_tokens",
}
DEFAULT_STAGE1_COMPACTION_SECTIONS = [
    "confidence",
    "tldr",
    "recommendation",
    "top_risk",
]
_VALID_STAGE1_COMPACTION_SECTIONS = {
    "confidence",
    "tldr",
    "analysis",
    "recommendation",
    "top_risk",
    "open_questions",
}


@dataclass
class HarnessConfig:
    # Stage token budgets
    stage1_max_tokens: int = 1200
    stage2_max_tokens: int = 800
    stage3_max_tokens: int = 4000
    stage4_max_tokens: int = 3000
    revision_max_tokens: int = 2500

    # Response thresholds
    min_stage1_responses: int = 3
    min_stage2_responses: int = 2

    # Verification
    verification_threshold: float = 7.0
    max_revision_attempts: int = 1

    # Complexity multipliers (Phase B tuner slot)
    complexity_multipliers: dict = field(default_factory=lambda: {
        "simple": 0.6,
        "moderate": 1.0,
        "complex": 1.5,
    })

    # Per-query-type overrides (Phase B+ tuner slot)
    per_query_type: dict = field(default_factory=dict)

    # Board hardening (P1+)
    hardening: dict = field(default_factory=lambda: {
        "atomizer_model": "qwen/qwen3.6-max-preview",
        "blinded_verifier_pass_threshold": 0.80,
        "blinded_verifier_evidence_max_chars": 4000,
    })

    # Version tracking
    version: int = 1
    last_modified: str = ""


def load_config(path: Path | None = None) -> HarnessConfig:
    """Load config from JSON. Returns defaults if file missing."""
    config_path = path or _DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return HarnessConfig()

    data = json.loads(config_path.read_text(encoding="utf-8"))
    known_fields = {f.name for f in HarnessConfig.__dataclass_fields__.values()}
    filtered = {k: v for k, v in data.items() if k in known_fields}
    return HarnessConfig(**filtered)


def save_config(config: HarnessConfig, path: Path | None = None) -> None:
    """Save config to JSON. Bumps version, sets last_modified, invalidates cache."""
    config_path = path or _DEFAULT_CONFIG_PATH
    config.version += 1
    config.last_modified = datetime.now(timezone.utc).isoformat()

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(asdict(config), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    get_config.cache_clear()


@lru_cache(maxsize=1)
def get_config() -> HarnessConfig:
    """Cached config access. Call get_config.cache_clear() to reload."""
    return load_config()


def resolve_stage_max_tokens(
    stage: int,
    *,
    query_type: str | None = None,
    complexity: str | None = None,
    config: HarnessConfig | None = None,
) -> int:
    """Resolve the token budget for a stage with optional tuned overrides."""
    field_name = _STAGE_TOKEN_FIELDS.get(stage)
    if field_name is None:
        raise ValueError(f"Unsupported stage for token budget: {stage}")

    cfg = config or get_config()
    budget = getattr(cfg, field_name)
    if not query_type or not isinstance(cfg.per_query_type, dict):
        return budget

    query_config = cfg.per_query_type.get(query_type)
    if not isinstance(query_config, dict):
        return budget

    query_budget = _positive_int(query_config.get(field_name))
    if query_budget is not None:
        budget = query_budget

    token_budgets = query_config.get("token_budgets")
    if not complexity or not isinstance(token_budgets, dict):
        return budget

    complexity_config = token_budgets.get(complexity)
    if not isinstance(complexity_config, dict):
        return budget

    complexity_budget = _positive_int(complexity_config.get(field_name))
    if complexity_budget is not None:
        return complexity_budget

    return budget


def resolve_verification_threshold(
    *,
    query_type: str | None = None,
    config: HarnessConfig | None = None,
) -> float:
    """Resolve verification threshold with optional per-query override."""
    cfg = config or get_config()
    threshold = float(cfg.verification_threshold)
    if not query_type or not isinstance(cfg.per_query_type, dict):
        return threshold

    query_config = cfg.per_query_type.get(query_type)
    if not isinstance(query_config, dict):
        return threshold

    query_threshold = _positive_float(query_config.get("verification_threshold"))
    if query_threshold is not None:
        return query_threshold

    return threshold


def resolve_routing_suppressed_member_ids(
    *,
    query_type: str | None = None,
    config: HarnessConfig | None = None,
) -> list[str]:
    """Return member IDs suppressed by routing accuracy tuning."""
    if not query_type:
        return []
    cfg = config or get_config()
    if not isinstance(cfg.per_query_type, dict):
        return []

    query_config = cfg.per_query_type.get(query_type)
    if not isinstance(query_config, dict):
        return []

    routing = query_config.get("routing")
    if not isinstance(routing, dict):
        return []

    return _string_list(routing.get("suppressed_member_ids"))


def resolve_stage1_compaction_policy(
    *,
    query_type: str | None = None,
    config: HarnessConfig | None = None,
) -> tuple[list[str], list[str]]:
    """Return stage-1 compaction sections and sections needing fuller detail."""
    cfg = config or get_config()
    sections = list(DEFAULT_STAGE1_COMPACTION_SECTIONS)
    detail_sections: list[str] = []

    if query_type and isinstance(cfg.per_query_type, dict):
        query_config = cfg.per_query_type.get(query_type)
        if isinstance(query_config, dict):
            compaction = query_config.get("compaction")
            if isinstance(compaction, dict):
                configured = _valid_stage1_sections(compaction.get("stage1_sections"))
                if configured:
                    sections = configured
                detail_sections = _valid_stage1_sections(
                    compaction.get("stage1_detail_sections"),
                    allow_confidence=False,
                )

    if "confidence" not in sections:
        sections.insert(0, "confidence")
    if not any(section != "confidence" for section in sections):
        sections.append("tldr")

    return _dedupe(sections), _dedupe(detail_sections)


def resolve_model_preferences(
    *,
    query_type: str | None = None,
    config: HarnessConfig | None = None,
) -> dict[str, str]:
    """Return per-member model preferences for a query type."""
    if not query_type:
        return {}
    cfg = config or get_config()
    if not isinstance(cfg.per_query_type, dict):
        return {}

    query_config = cfg.per_query_type.get(query_type)
    if not isinstance(query_config, dict):
        return {}

    preferences = query_config.get("model_preferences")
    if not isinstance(preferences, dict):
        return {}

    return {
        str(member_id): model
        for member_id, model in preferences.items()
        if isinstance(member_id, str) and isinstance(model, str) and model.strip()
    }


def _positive_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, int):
        return None
    if value <= 0:
        return None
    return value


def _positive_float(value) -> float | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    if value <= 0:
        return None
    return float(value)


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
    return _dedupe(result)


def _valid_stage1_sections(value, *, allow_confidence: bool = True) -> list[str]:
    sections: list[str] = []
    for item in _string_list(value):
        section = item.lower()
        if section == "tl;dr":
            section = "tldr"
        if section not in _VALID_STAGE1_COMPACTION_SECTIONS:
            continue
        if section == "confidence" and not allow_confidence:
            continue
        sections.append(section)
    return _dedupe(sections)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
