"""Day-3 smoke: open a JS-heavy page in local Chrome and dump first 500 chars.

Run: uv run python scripts/smoke_browser.py
With Tavily fallback: AGENTIC_BOARD_BROWSER=tavily uv run python scripts/smoke_browser.py
Headless: AGENTIC_BOARD_BROWSER_HEADED=0 uv run python scripts/smoke_browser.py
"""
from __future__ import annotations

import asyncio
import sys

from server.board.tools import execute_tool


async def main() -> int:
    url = "https://news.ycombinator.com/"
    print(f"Opening {url} via open_browser...")
    result = await execute_tool(
        name="open_browser",
        arguments={"url": url, "extract": "markdown"},
        session=None, member_id="smoke",
    )
    if result.error:
        print(f"✗ {result.error}")
        return 1
    print(f"✓ {result.summary}")
    print("---")
    print(result.content_for_model[:500])
    print("---")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
