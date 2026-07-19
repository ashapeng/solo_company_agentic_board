"""Architecture guard: discovery is operated by the IDE agent, not project LLMs."""

from __future__ import annotations

import ast
from pathlib import Path


DISCOVERY_ROOT = Path(__file__).parents[1] / "server" / "discovery"
FORBIDDEN_PREFIXES = (
    "server.board.llm",
    "openai",
    "google.genai",
    "dashscope",
    "zai",
)


def test_discovery_does_not_import_project_or_provider_llms():
    violations: list[str] = []
    for path in DISCOVERY_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        blocked = [
            name for name in imported
            if any(name == prefix or name.startswith(f"{prefix}.") for prefix in FORBIDDEN_PREFIXES)
        ]
        if blocked:
            violations.append(f"{path.relative_to(DISCOVERY_ROOT)}: {', '.join(blocked)}")

    assert not violations, "Discovery must not invoke project/provider LLMs:\n" + "\n".join(violations)
