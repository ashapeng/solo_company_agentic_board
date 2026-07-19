"""Auditable local producers for discovery synthesis."""

from pathlib import Path

from .base import (
    ProducerConfig,
    ProducerRequest,
    ProducerResult,
    SynthesisProducer,
)
from .codex_cli import CodexCliProducer
from .manual import ManualHandoffProducer
from .runs import ProducerRun, ProducerRunStore

CANDIDATE_SCHEMA_PATH = Path(__file__).with_name("candidate.schema.json")

__all__ = [
    "CodexCliProducer",
    "CANDIDATE_SCHEMA_PATH",
    "ManualHandoffProducer",
    "ProducerConfig",
    "ProducerRequest",
    "ProducerResult",
    "ProducerRun",
    "ProducerRunStore",
    "SynthesisProducer",
]
