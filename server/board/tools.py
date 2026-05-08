"""Tool registry for board members.

A Tool is a (name, description, JSON-schema parameters, async handler) record.
Handlers receive validated kwargs from the LLM's tool_call.arguments and
return a ToolResult. The registry is provider-agnostic; per-provider
schema conversion lives in llm.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

ToolHandler = Callable[..., Awaitable["ToolResult"]]


@dataclass
class ToolResult:
    """Result of executing one tool call."""
    content_for_model: str
    summary: str
    cost_units: float
    artifact_id: str | None = None
    error: str | None = None


@dataclass
class Tool:
    """A registered tool with provider-agnostic schema and async handler."""
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def to_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# Registry — populated by Tasks 7–12
TOOLS: dict[str, Tool] = {}


async def execute_tool(
    *,
    name: str,
    arguments: dict[str, Any],
    session: Any,
    member_id: str | None,
) -> ToolResult:
    """Look up and invoke a registered tool. Returns a ToolResult with
    `error` set if the tool is unknown or if the handler raises."""
    tool = TOOLS.get(name)
    if tool is None:
        return ToolResult(
            content_for_model=f"Error: unknown tool {name!r}",
            summary=f"unknown tool {name!r}",
            cost_units=0.0,
            error=f"unknown tool: {name!r}",
        )
    try:
        return await tool.handler(
            session=session, member_id=member_id, **arguments,
        )
    except Exception as exc:  # noqa: BLE001 — surface tool errors as ToolResult
        return ToolResult(
            content_for_model=f"Tool {name} failed: {exc}",
            summary=f"{name} error: {exc}",
            cost_units=0.0,
            error=str(exc),
        )


# ────────────── web_search ──────────────

async def _handle_web_search(
    *,
    query: str,
    max_results: int = 5,
    recency_days: int | None = None,
    session: Any = None,
    member_id: str | None = None,
    **_unused: Any,
) -> ToolResult:
    """Wraps server.execution.web_search.web_search()."""
    from server.execution.web_search import web_search as _ws

    session_id = getattr(session, "session_id", None) if session else None
    raw = await _ws(
        query=query,
        max_results=min(int(max_results or 5), 10),
        session_id=session_id,
    )
    results = raw.get("results", []) if isinstance(raw, dict) else []
    if not results:
        return ToolResult(
            content_for_model=f"web_search('{query}') returned no results.",
            summary=f"web_search '{query}' → 0 results",
            cost_units=1.0,
        )
    lines = [f"web_search('{query}') results:"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "(no title)")
        url = r.get("url", "")
        snippet = (r.get("snippet") or r.get("description") or "")[:300]
        retrieved = r.get("retrieved_at", "")
        lines.append(f"{i}. {title}\n   URL: {url}\n   Snippet: {snippet}"
                     + (f"\n   Retrieved: {retrieved}" if retrieved else ""))
    return ToolResult(
        content_for_model="\n".join(lines),
        summary=f"web_search '{query}' → {len(results)} results",
        cost_units=1.0,
    )


TOOLS["web_search"] = Tool(
    name="web_search",
    description="Search the web for current information. Returns a list of "
                "results with title, snippet, url, retrieved_at. Use when you "
                "need facts you don't have or to verify a claim.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "the search query"},
            "max_results": {
                "type": "integer", "minimum": 1, "maximum": 10, "default": 5,
            },
            "recency_days": {
                "type": "integer",
                "description": "(optional) only results from last N days",
            },
        },
        "required": ["query"],
    },
    handler=_handle_web_search,
)


# ────────────── fetch_url ──────────────

async def _handle_fetch_url(
    *,
    url: str,
    session: Any = None,
    member_id: str | None = None,
    **_unused: Any,
) -> ToolResult:
    """HTTP GET a URL; return its text (truncated to 12k chars)."""
    import httpx

    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return ToolResult(
            content_for_model=f"fetch_url: invalid URL {url!r}",
            summary="fetch_url invalid URL",
            cost_units=0.0,
            error=f"invalid URL: {url!r}",
        )
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True,
                                  headers={"User-Agent": "AgenticBoard/1.0"}) as c:
        resp = await c.get(url)
        resp.raise_for_status()
    text = resp.text[:12000]
    return ToolResult(
        content_for_model=f"fetch_url('{url}') →\n{text}",
        summary=f"fetched {url} ({len(resp.text)} chars)",
        cost_units=0.5,
    )


TOOLS["fetch_url"] = Tool(
    name="fetch_url",
    description="HTTP GET a URL and return its text. Faster than open_browser "
                "but fails on JS-rendered or anti-bot-protected sites.",
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
    handler=_handle_fetch_url,
)


# ────────────── ask_user_clarifying_question ──────────────

async def _handle_ask_user(
    *,
    question: str,
    why_it_matters: str,
    session: Any = None,
    member_id: str | None = None,
    **_unused: Any,
) -> ToolResult:
    """Pause analysis and ask the user. Session must expose an async
    `ask_user(question, why)` method; otherwise return [NO_USER_RESPONSE]."""
    callback = getattr(session, "ask_user", None) if session else None
    if callback is None:
        return ToolResult(
            content_for_model="[NO_USER_RESPONSE] (session has no ask_user channel)",
            summary="ask_user: no channel",
            cost_units=0.0,
        )
    answer = await callback(question, why_it_matters)
    return ToolResult(
        content_for_model=f"User answered: {answer}",
        summary=f"asked: {question[:60]}",
        cost_units=2.0,
    )


TOOLS["ask_user_clarifying_question"] = Tool(
    name="ask_user_clarifying_question",
    description="Pause analysis and ask the user a clarifying question. "
                "Returns the user's response. Use ONLY when the question is "
                "essential to your analysis and not answerable by web search.",
    parameters={
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "why_it_matters": {
                "type": "string",
                "description": "one sentence explaining what it changes",
            },
        },
        "required": ["question", "why_it_matters"],
    },
    handler=_handle_ask_user,
)
