"""Single source of truth for tunable harness parameters."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path


_DEFAULT_CONFIG_PATH = Path(__file__).parent / "harness_config.json"


@dataclass
class HarnessConfig:
    # Stage token budgets
    stage1_max_tokens: int = 1200
    stage2_max_tokens: int = 800
    stage3_max_tokens: int = 4000
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
