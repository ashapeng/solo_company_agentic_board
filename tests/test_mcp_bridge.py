"""Tests for the MCP bridge (server/board/mcp_client.py).

These run entirely offline: no network and no installed ``mcp`` package. The
real-server path is exercised via an injected ``client_factory`` returning a
fake client.
"""
import unittest

from server.board import tools as tools_mod
from server.board.mcp_client import (
    McpServerSpec,
    load_mcp_specs,
    register_mcp_tools,
)
from server.board.tools import execute_tool


class FakeMcpClient:
    """Minimal stand-in for a live MCP client."""

    async def list_tools(self):
        return [
            {
                "name": "echo",
                "description": "echo",
                "inputSchema": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                },
            }
        ]

    async def call_tool(self, name, args):
        return {"echoed": args}


def _fake_factory(spec):
    return FakeMcpClient()


class McpBridgeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Snapshot the registry so we can restore it and never leak into
        # other tests.
        self._registered: list[str] = []
        self._snapshot = dict(tools_mod.TOOLS)

    def tearDown(self):
        for name in self._registered:
            tools_mod.TOOLS.pop(name, None)
        # Belt-and-braces: restore the exact pre-test registry.
        tools_mod.TOOLS.clear()
        tools_mod.TOOLS.update(self._snapshot)

    async def test_register_and_execute_fake_server(self):
        names = await register_mcp_tools(
            [McpServerSpec(name="demo", transport="stdio")],
            client_factory=_fake_factory,
        )
        self._registered = list(names)

        self.assertEqual(names, ["mcp__demo__echo"])
        self.assertIn("mcp__demo__echo", tools_mod.TOOLS)

        # Schema carries the remote input schema.
        tool = tools_mod.TOOLS["mcp__demo__echo"]
        schema = tool.to_openai_schema()
        self.assertEqual(schema["function"]["name"], "mcp__demo__echo")
        params = schema["function"]["parameters"]
        self.assertEqual(params["properties"]["text"]["type"], "string")

        # Execution reflects the echoed arguments.
        result = await execute_tool(
            name="mcp__demo__echo",
            arguments={"text": "hi"},
            session=None,
            member_id=None,
        )
        self.assertIsNone(result.error)
        self.assertIn("hi", result.content_for_model)
        self.assertIn("echoed", result.content_for_model)
        self.assertEqual(result.summary, "mcp:demo:echo")
        self.assertEqual(result.cost_units, 0.0)

    async def test_load_mcp_specs_unset_returns_empty(self):
        import os
        from unittest.mock import patch

        # Ensure the var is absent regardless of ambient environment.
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENTIC_BOARD_MCP_SERVERS", None)
            self.assertEqual(load_mcp_specs(), [])

    async def test_load_mcp_specs_parses_valid_json(self):
        import os
        import json
        from unittest.mock import patch

        payload = json.dumps(
            [
                {"name": "demo", "transport": "stdio", "command": "x", "args": ["a"]},
                {"name": "remote", "transport": "http", "url": "https://example.com"},
            ]
        )
        with patch.dict(os.environ, {"AGENTIC_BOARD_MCP_SERVERS": payload}):
            specs = load_mcp_specs()
        self.assertEqual(len(specs), 2)
        self.assertEqual(specs[0].name, "demo")
        self.assertEqual(specs[0].transport, "stdio")
        self.assertEqual(specs[0].command, "x")
        self.assertEqual(specs[0].args, ["a"])
        self.assertEqual(specs[1].transport, "http")
        self.assertEqual(specs[1].url, "https://example.com")

    async def test_load_mcp_specs_invalid_json_returns_empty(self):
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"AGENTIC_BOARD_MCP_SERVERS": "{not json"}):
            self.assertEqual(load_mcp_specs(), [])

    async def test_empty_specs_is_noop(self):
        before = dict(tools_mod.TOOLS)
        names = await register_mcp_tools([], client_factory=None)
        self.assertEqual(names, [])
        self.assertEqual(tools_mod.TOOLS, before)

    async def test_per_server_failure_is_nonfatal(self):
        def broken_factory(spec):
            raise RuntimeError("boom")

        names = await register_mcp_tools(
            [McpServerSpec(name="bad", transport="stdio")],
            client_factory=broken_factory,
        )
        self._registered = list(names)
        self.assertEqual(names, [])


if __name__ == "__main__":
    unittest.main()
