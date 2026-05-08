"""Tool registry for board members.

A Tool is a (name, description, JSON-schema parameters, async handler) record.
Handlers receive validated kwargs from the LLM's tool_call.arguments and
return a ToolResult. The registry is provider-agnostic; per-provider
schema conversion lives in llm.py.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

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
    """Wraps server.execution.web_search.web_search().
    Auto-augments query with role-specific keywords when member_id is known."""
    from server.execution.web_search import (
        web_search as _ws,
        _build_role_specific_query,
    )

    session_id = getattr(session, "session_id", None) if session else None
    effective_query = query
    if member_id:
        effective_query = _build_role_specific_query(
            base_query=query, member_id=member_id, member_role=""
        )
    raw = await _ws(
        query=effective_query,
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


# ────────────── SSRF guard ──────────────

_SSRF_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _is_blocked_url(url: str) -> bool:
    """Return True if the URL targets a loopback, private, or link-local host."""
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return True
    if host.lower() in _SSRF_BLOCKED_HOSTS:
        return True
    # Block private and link-local IP ranges
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return True
    except ValueError:
        pass  # not a literal IP — hostname; assume external
    return False


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

    if not isinstance(url, str) or not url.startswith(("http://", "https://")) or _is_blocked_url(url):
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


# ────────────── Chrome / Playwright helpers ──────────────

import os as _os
import sys as _sys
from pathlib import Path as _Path


def _resolve_chrome_user_data_dir() -> str:
    """Return the path to Chrome's user-data dir for the current OS.
    Override with AGENTIC_BOARD_CHROME_USER_DATA_DIR env var."""
    override = _os.getenv("AGENTIC_BOARD_CHROME_USER_DATA_DIR")
    if override:
        return override
    home = _Path(_os.path.expanduser("~"))
    if _sys.platform.startswith("linux"):
        return str(home / ".config" / "google-chrome")
    if _sys.platform == "darwin":
        return str(home / "Library" / "Application Support" / "Google" / "Chrome")
    if _sys.platform.startswith("win"):
        local = _os.getenv("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return str(_Path(local) / "Google" / "Chrome" / "User Data")
    return str(home / ".config" / "google-chrome")


# ────────────── open_browser ──────────────

import asyncio as _asyncio

_BROWSER_SEMAPHORE = _asyncio.Semaphore(1)
_OPEN_BROWSER_MAX_CHARS = 12000


async def _handle_open_browser(
    *,
    url: str,
    wait_for: str | None = None,
    extract: str = "markdown",
    session: Any = None,
    member_id: str | None = None,
    **_unused: Any,
) -> ToolResult:
    """Open a URL in local Chrome via Playwright; return rendered text.
    Mode controlled by AGENTIC_BOARD_BROWSER env: chrome (default) | tavily | disabled."""
    mode = (_os.getenv("AGENTIC_BOARD_BROWSER") or "chrome").lower()
    if mode == "disabled":
        return ToolResult(
            content_for_model="open_browser disabled (AGENTIC_BOARD_BROWSER=disabled)",
            summary="browser disabled",
            cost_units=0.0,
            error="browser disabled",
        )
    if mode == "tavily":
        return await _open_browser_via_tavily(url=url, member_id=member_id, session=session)
    return await _open_browser_via_playwright(
        url=url, wait_for=wait_for, extract=extract, member_id=member_id,
    )


async def _open_browser_via_tavily(
    *, url: str, member_id: str | None, session: Any,
) -> ToolResult:
    """Fallback when Playwright is unavailable: search the URL and return top snippets."""
    from server.execution.web_search import web_search as _ws
    session_id = getattr(session, "session_id", None) if session else None
    raw = await _ws(query=url, max_results=3, session_id=session_id)
    results = raw.get("results", []) if isinstance(raw, dict) else []
    if not results:
        return ToolResult(
            content_for_model=f"open_browser(fallback) for {url}: no content",
            summary="no fallback content", cost_units=1.0,
        )
    lines = [f"open_browser fallback for {url} (Tavily snippets):"]
    for r in results:
        lines.append(f"- {r.get('title', '')}: {r.get('snippet', '')[:300]}")
    return ToolResult(
        content_for_model="\n".join(lines)[:_OPEN_BROWSER_MAX_CHARS],
        summary=f"opened (fallback) {url}",
        cost_units=1.5,
    )


async def _open_browser_via_playwright(
    *, url: str, wait_for: str | None, extract: str, member_id: str | None,
) -> ToolResult:
    """Drive local Chrome with the user's profile via Playwright.
    Falls back to Tavily-style search if Playwright isn't installed."""
    if _is_blocked_url(url):
        return ToolResult(
            content_for_model=f"open_browser: blocked URL {url!r}",
            summary="open_browser blocked URL",
            cost_units=0.0,
            error=f"invalid URL: {url!r}",
        )
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        # Fall back transparently
        return await _open_browser_via_tavily(
            url=url, member_id=member_id, session=None,
        )
    try:
        from markdownify import markdownify as _md
    except ImportError:
        _md = None

    user_data_dir = _resolve_chrome_user_data_dir()
    headed = _os.getenv("AGENTIC_BOARD_BROWSER_HEADED", "1") != "0"
    async with _BROWSER_SEMAPHORE:
        async with async_playwright() as pw:
            try:
                ctx = await pw.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    channel="chrome",
                    headless=not headed,
                )
            except Exception as exc:
                return ToolResult(
                    content_for_model=(
                        f"open_browser failed to launch Chrome: {exc}. "
                        "Close any running Chrome with this profile, OR set "
                        "AGENTIC_BOARD_BROWSER=tavily."),
                    summary="chrome launch failed",
                    cost_units=0.0,
                    error=str(exc),
                )
            try:
                page = await ctx.new_page()
                await page.goto(url, timeout=30000)
                await page.wait_for_load_state("networkidle", timeout=20000)
                if wait_for:
                    try:
                        await page.wait_for_selector(wait_for, timeout=15000)
                    except Exception:
                        pass
                html = await page.content()
            finally:
                await ctx.close()

    if extract == "html":
        body = html
    elif extract == "text":
        # naive strip — markdownify gives us cleaner output normally
        import re
        body = re.sub(r"<[^>]+>", "", html)
    else:  # markdown
        body = _md(html, heading_style="ATX") if _md else html
    body = body[:_OPEN_BROWSER_MAX_CHARS]
    return ToolResult(
        content_for_model=f"open_browser('{url}') →\n{body}",
        summary=f"opened {url}",
        cost_units=3.0,
    )


TOOLS["open_browser"] = Tool(
    name="open_browser",
    description="Open a URL in a real Chrome browser session and extract the "
                "rendered page text. Use for sites that block scrapers, JS-rendered "
                "content, or pages needing your logged-in session. Slower (~5–15s). "
                "Use sparingly.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "wait_for": {"type": "string",
                          "description": "(optional) CSS selector to wait for"},
            "extract": {"type": "string", "enum": ["text", "markdown", "html"],
                         "default": "markdown"},
        },
        "required": ["url"],
    },
    handler=_handle_open_browser,
)


# ────────────── validate_claim ──────────────

import os as _os_validate

VALIDATE_CLAIM_DEFAULT_MODEL = "gemini/gemini-2.5-flash"

# Module-level reference so tests can patch "server.board.tools.query_llm"
from server.board.llm import query_llm  # noqa: E402


async def _handle_validate_claim(
    *,
    claim: str,
    context: str = "",
    session: Any = None,
    member_id: str | None = None,
    **_unused: Any,
) -> ToolResult:
    """Cross-check a factual claim by searching the web and asking a fast
    judge LLM to verdict SUPPORTED / CONTRADICTED / UNVERIFIED."""
    if not claim or not claim.strip():
        return ToolResult(
            content_for_model="validate_claim: empty claim",
            summary="validate_claim: empty",
            cost_units=0.0,
            error="claim must be a non-empty string",
        )

    # Step 1: web_search for evidence
    from server.execution.web_search import web_search as _ws
    session_id = getattr(session, "session_id", None) if session else None
    raw = await _ws(query=claim, max_results=5, session_id=session_id)
    results = raw.get("results", []) if isinstance(raw, dict) else []

    if not results:
        return ToolResult(
            content_for_model=(
                f"validate_claim('{claim[:80]}'):\n"
                f"VERDICT: UNVERIFIED\n"
                f"RATIONALE: No web_search results returned for the query.\n"
                f"KEY_SOURCES: (none)"
            ),
            summary=f"validate_claim: UNVERIFIED (no search results)",
            cost_units=1.0,
        )

    # Step 2: build judge prompt
    evidence_text = "\n".join(
        f"- {r.get('title', '(no title)')}: "
        f"{(r.get('snippet') or r.get('description') or '')[:300]} "
        f"({r.get('url', '')})"
        for r in results[:5]
    )
    judge_prompt = (
        f"Claim to verify:\n{claim}\n\n"
        f"Context: {context or '(none)'}\n\n"
        f"Web search evidence:\n{evidence_text}\n\n"
        f"Judge whether the claim is SUPPORTED, CONTRADICTED, or UNVERIFIED "
        f"by the evidence above:\n"
        f"- SUPPORTED: At least 2 sources directly affirm the claim.\n"
        f"- CONTRADICTED: At least 1 credible source directly contradicts the claim.\n"
        f"- UNVERIFIED: Evidence is insufficient, ambiguous, or off-topic.\n\n"
        f"Respond in this exact format and nothing else:\n"
        f"VERDICT: <SUPPORTED|CONTRADICTED|UNVERIFIED>\n"
        f"RATIONALE: <one sentence>\n"
        f"KEY_SOURCES: <comma-separated URLs of the most relevant sources>"
    )

    # Step 3: call judge LLM
    judge_model = _os_validate.getenv("VALIDATE_CLAIM_MODEL", VALIDATE_CLAIM_DEFAULT_MODEL)
    try:
        judge_response = await query_llm(
            judge_model,
            [{"role": "user", "content": judge_prompt}],
            max_tokens=400,
            timeout=60.0,
            fallback=True,
        )
    except Exception as exc:  # noqa: BLE001 — surface judge failures as ToolResult
        return ToolResult(
            content_for_model=(
                f"validate_claim('{claim[:80]}'):\n"
                f"VERDICT: UNVERIFIED\n"
                f"RATIONALE: Judge LLM call failed: {exc}\n"
                f"KEY_SOURCES: (none)"
            ),
            summary="validate_claim: judge failed",
            cost_units=1.0,
            error=str(exc),
        )

    # Step 4: parse verdict (loose match)
    content = (judge_response.content or "").strip()
    upper = content.upper()
    if "VERDICT: SUPPORTED" in upper or "VERDICT:SUPPORTED" in upper:
        verdict = "SUPPORTED"
    elif "VERDICT: CONTRADICTED" in upper or "VERDICT:CONTRADICTED" in upper:
        verdict = "CONTRADICTED"
    else:
        verdict = "UNVERIFIED"

    return ToolResult(
        content_for_model=(
            f"validate_claim('{claim[:80]}'):\n{content}\n\n"
            f"Searched evidence:\n{evidence_text}"
        ),
        summary=f"validate_claim: {verdict}",
        cost_units=2.0,
    )


TOOLS["validate_claim"] = Tool(
    name="validate_claim",
    description="Cross-check a factual claim against a fresh web search. "
                "Returns SUPPORTED, CONTRADICTED, or UNVERIFIED with rationale "
                "and key sources. Use BEFORE relying on a load-bearing fact in "
                "your recommendation.",
    parameters={
        "type": "object",
        "properties": {
            "claim": {"type": "string",
                       "description": "The factual claim to verify"},
            "context": {"type": "string",
                         "description": "(optional) context to help the judge"},
        },
        "required": ["claim"],
    },
    handler=_handle_validate_claim,
)
