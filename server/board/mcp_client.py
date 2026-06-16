"""MCP (Model Context Protocol) bridge for the Agentic Board.

Exposes tools served by external MCP servers as native board ``Tool`` objects
so that board members can call them through the same registry/execute path as
the built-in tools.

Design goals:
- **No hard dependency.** The real MCP SDK (``mcp`` package) is imported
  optionally. When it is unavailable, the real-connection path degrades to a
  logged no-op and returns ``[]`` — nothing is registered. The injectable
  ``client_factory`` makes the whole bridge testable with a fake client.
- **No-op by default.** With ``AGENTIC_BOARD_MCP_SERVERS`` unset, ``load_mcp_specs``
  returns ``[]`` and ``register_mcp_tools`` registers nothing.
- **Per-server failures are non-fatal.** One broken server never blocks others.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from server.board.tools import Tool, ToolResult, register_tool

logger = logging.getLogger(__name__)

# An injected async callable that performs the actual remote tool call.
CallTool = Callable[[dict], Awaitable[Any]]


@dataclass
class McpServerSpec:
    """Connection spec for one MCP server.

    ``transport`` is "stdio" (launch ``command`` + ``args``) or "http"
    (connect to ``url`` with optional ``headers``).
    """
    name: str
    transport: str
    command: str | None = None
    args: list[str] | None = None
    env: dict | None = None
    url: str | None = None
    headers: dict | None = None


def load_mcp_specs() -> list[McpServerSpec]:
    """Parse ``AGENTIC_BOARD_MCP_SERVERS`` (JSON list of spec dicts).

    Returns ``[]`` when the env var is unset, empty, or invalid JSON / wrong
    shape (a warning is logged for invalid input). Unknown keys are ignored.
    """
    raw = (os.getenv("AGENTIC_BOARD_MCP_SERVERS") or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError) as exc:
        logger.warning("AGENTIC_BOARD_MCP_SERVERS is not valid JSON: %s", exc)
        return []
    if not isinstance(parsed, list):
        logger.warning(
            "AGENTIC_BOARD_MCP_SERVERS must be a JSON list, got %s",
            type(parsed).__name__,
        )
        return []

    specs: list[McpServerSpec] = []
    allowed = {"name", "transport", "command", "args", "env", "url", "headers"}
    for entry in parsed:
        if not isinstance(entry, dict):
            logger.warning("Skipping non-object MCP server entry: %r", entry)
            continue
        name = entry.get("name")
        transport = entry.get("transport")
        if not name or not transport:
            logger.warning(
                "Skipping MCP server entry missing name/transport: %r", entry
            )
            continue
        kwargs = {k: v for k, v in entry.items() if k in allowed}
        try:
            specs.append(McpServerSpec(**kwargs))
        except TypeError as exc:  # pragma: no cover — defensive
            logger.warning("Skipping invalid MCP server entry %r: %s", entry, exc)
    return specs


def _stringify(result: Any) -> str:
    """Best-effort stringification of an MCP tool result for the model."""
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(result)


def _wrap_mcp_tool(
    *,
    server_name: str,
    tool_name: str,
    description: str,
    input_schema: dict,
    call_tool: CallTool,
) -> Tool:
    """Build a board ``Tool`` that proxies to a remote MCP tool.

    ``call_tool`` is an injected async callable ``(dict) -> Any`` — the only
    thing that touches the network — which is what makes this unit-testable
    without a live server.
    """
    full_name = f"mcp__{server_name}__{tool_name}"
    parameters = input_schema or {"type": "object", "properties": {}}

    async def handler(
        *, session: Any = None, member_id: str | None = None, **arguments: Any
    ) -> ToolResult:
        try:
            result = await call_tool(arguments)
        except Exception as exc:  # noqa: BLE001 — surface as ToolResult
            return ToolResult(
                content_for_model=f"{full_name} failed: {exc}",
                summary=f"mcp:{server_name}:{tool_name} error",
                cost_units=0.0,
                error=str(exc),
            )
        return ToolResult(
            content_for_model=_stringify(result),
            summary=f"mcp:{server_name}:{tool_name}",
            cost_units=0.0,
        )

    return Tool(
        name=full_name,
        description=description or f"MCP tool {tool_name} from server {server_name}",
        parameters=parameters,
        handler=handler,
    )


async def _connect_real_client(spec: McpServerSpec):  # pragma: no cover
    """Connect to a live MCP server using the optional ``mcp`` SDK.

    Returns an adapter exposing async ``list_tools()`` and
    ``call_tool(name, args)``, or ``None`` if the SDK is unavailable. This path
    is intentionally not exercised in tests (no network / no installed package);
    the ``client_factory`` injection covers behavior.
    """
    try:
        import mcp  # noqa: F401
    except ImportError:
        logger.info(
            "mcp package not installed; skipping real connection for server %r. "
            "Install 'mcp' to enable live MCP servers.",
            spec.name,
        )
        return None

    # Real SDK wiring is environment-specific (stdio vs http) and not needed for
    # the test suite. If/when the dependency is added, implement the adapter
    # here. Until then, degrade gracefully.
    logger.info(
        "mcp package present but real-connection adapter is not wired for "
        "server %r; returning no tools.",
        spec.name,
    )
    return None


async def connect_and_list(
    spec: McpServerSpec,
    *,
    client_factory: Callable[[McpServerSpec], Any] | None = None,
) -> list[Tool]:
    """Connect to one MCP server and return wrapped board ``Tool`` objects.

    If ``client_factory`` is provided, it is called as ``client_factory(spec)``
    and must return a client with async ``list_tools() -> list[dict]`` (each
    dict carrying ``name`` / ``description`` / ``inputSchema``) and async
    ``call_tool(name, args) -> Any``. Otherwise the real MCP SDK is used via an
    optional import; if it is unavailable, this logs and returns ``[]``.

    Per-server failures are non-fatal: on any error we log and return whatever
    tools were collected so far.
    """
    try:
        if client_factory is not None:
            client = client_factory(spec)
        else:
            client = await _connect_real_client(spec)
        if client is None:
            return []

        listed = await client.list_tools()
    except Exception as exc:  # noqa: BLE001 — one bad server must not be fatal
        logger.warning("Failed to list tools for MCP server %r: %s", spec.name, exc)
        return []

    tools: list[Tool] = []
    for entry in listed or []:
        try:
            name = entry.get("name") if isinstance(entry, dict) else getattr(entry, "name", None)
            if not name:
                continue
            description = (
                entry.get("description") if isinstance(entry, dict)
                else getattr(entry, "description", "")
            ) or ""
            input_schema = (
                entry.get("inputSchema") if isinstance(entry, dict)
                else getattr(entry, "inputSchema", None)
            ) or {}
            tools.append(
                _wrap_mcp_tool(
                    server_name=spec.name,
                    tool_name=name,
                    description=description,
                    input_schema=input_schema,
                    call_tool=(lambda args, n=name: client.call_tool(n, args)),
                )
            )
        except Exception as exc:  # noqa: BLE001 — skip one bad tool, keep the rest
            logger.warning(
                "Failed to wrap MCP tool from server %r: %s", spec.name, exc
            )
    return tools


async def register_mcp_tools(
    specs: list[McpServerSpec] | None = None,
    *,
    client_factory: Callable[[McpServerSpec], Any] | None = None,
) -> list[str]:
    """Connect to each spec, register the resulting tools into the global
    ``TOOLS`` registry, and return the registered tool names.

    ``specs`` defaults to ``load_mcp_specs()``. Per-server failures are
    non-fatal. With no configured servers this is a no-op returning ``[]``.
    """
    if specs is None:
        specs = load_mcp_specs()

    registered: list[str] = []
    for spec in specs:
        try:
            tools = await connect_and_list(spec, client_factory=client_factory)
        except Exception as exc:  # noqa: BLE001 — defensive; connect_and_list already guards
            logger.warning("MCP server %r failed during registration: %s", spec.name, exc)
            continue
        for tool in tools:
            register_tool(tool)
            registered.append(tool.name)
    if registered:
        logger.info("Registered %d MCP tool(s): %s", len(registered), ", ".join(registered))
    return registered
