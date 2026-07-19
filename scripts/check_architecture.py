#!/usr/bin/env python3
"""Detect structural drift between the repository and architecture catalog."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / "docs" / "architecture"
CATALOG_PATH = ARCH / "component-catalog.json"


def _directories(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {p.name for p in path.iterdir() if p.is_dir() and not p.name.startswith(".")}


def check() -> list[str]:
    errors: list[str] = []
    try:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read {CATALOG_PATH.relative_to(ROOT)}: {exc}"]

    components = catalog.get("components", [])
    ids = [item.get("id") for item in components]
    paths = [item.get("path") for item in components]
    if len(ids) != len(set(ids)):
        errors.append("component catalog contains duplicate IDs")
    if len(paths) != len(set(paths)):
        errors.append("component catalog contains duplicate paths")

    component_text = (ARCH / "components.md").read_text(encoding="utf-8")
    graph_text = (ARCH / "system-graph.md").read_text(encoding="utf-8")
    for item in components:
        component_id, relative = item.get("id"), item.get("path")
        if not component_id or not relative:
            errors.append(f"invalid component entry: {item!r}")
            continue
        if not (ROOT / relative).exists():
            errors.append(f"catalog path does not exist: {relative}")
        if relative not in component_text:
            errors.append(f"components.md does not mention catalog path: {relative}")
        # Graph can group UI domains, but every backend/integration component path
        # must appear verbatim so ownership remains unambiguous.
        if item.get("kind") != "frontend" and relative not in graph_text:
            errors.append(f"system-graph.md does not mention catalog path: {relative}")

    ignored = set(catalog.get("ignored_server_directories", []))
    documented_server = {
        Path(path).name for path in paths if isinstance(path, str) and path.startswith("server/")
    }
    actual_server = _directories(ROOT / "server") - ignored
    for name in sorted(actual_server - documented_server):
        errors.append(f"undocumented backend domain server/{name}")

    documented_ui = {
        Path(path).name
        for path in paths
        if isinstance(path, str) and path.startswith("ui/src/domains/")
    }
    for name in sorted(_directories(ROOT / "ui" / "src" / "domains") - documented_ui):
        errors.append(f"undocumented frontend domain ui/src/domains/{name}")

    actual_routes = {
        path.stem
        for path in (ROOT / "server" / "api" / "routes").glob("*.py")
        if path.stem != "__init__"
    }
    documented_routes = set(catalog.get("api_route_modules", []))
    for name in sorted(actual_routes - documented_routes):
        errors.append(f"undocumented API route module server/api/routes/{name}.py")
    for name in sorted(documented_routes - actual_routes):
        errors.append(f"cataloged API route module is missing: {name}")

    return errors


def main() -> int:
    errors = check()
    if errors:
        print("Architecture documentation drift detected:")
        for error in errors:
            print(f"- {error}")
        print("Update docs/architecture and component-catalog.json.")
        return 1
    print("Architecture catalog matches repository structure.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
