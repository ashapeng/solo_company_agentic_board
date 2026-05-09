"""Day-1 smoke: confirm Kimi and DeepSeek emit a tool_calls response.

Hits real APIs. Requires MOONSHOT_API_KEY and DEEPSEEK_API_KEY in env.
Run: uv run python scripts/smoke_tool_call.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from server.board import llm


SEARCH_TOOL = [{
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for current information.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}]


async def smoke_one(model: str) -> bool:
    print(f"\n=== Smoking {model} ===")
    resp = await llm.query_llm(
        model,
        [{"role": "user",
          "content": "Use web_search to find the current population of Tokyo."}],
        tools=SEARCH_TOOL,
        tool_choice="auto",
        max_tokens=512,
        timeout=60.0,
        fallback=False,
    )
    print(f"  finish_reason: {resp.finish_reason}")
    print(f"  content: {(resp.content or '')[:200]!r}")
    print(f"  tool_calls: {[(tc.name, tc.arguments) for tc in resp.tool_calls]}")
    if not resp.tool_calls:
        print("  ✗ no tool_calls — model did not invoke web_search")
        return False
    print(f"  ✓ {len(resp.tool_calls)} tool_call(s)")
    return True


async def main() -> int:
    failures: list[str] = []
    if not os.getenv("MOONSHOT_API_KEY"):
        print("MOONSHOT_API_KEY missing; skipping kimi")
    elif not await smoke_one("kimi/kimi-k2.6"):
        failures.append("kimi")
    if not os.getenv("DEEPSEEK_API_KEY"):
        print("DEEPSEEK_API_KEY missing; skipping deepseek")
    elif not await smoke_one("deepseek/deepseek-v4-pro"):
        failures.append("deepseek")
    if failures:
        print(f"\n✗ smoke failures: {failures}")
        return 1
    print("\n✓ all smokes passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
