import unittest

from hermes.plugins.agentic_board.plugin import _local_base_url, tool_schemas


class HermesPluginScaffoldTest(unittest.TestCase):
    def test_tool_schemas_include_memory_proposal_only(self):
        names = {tool["name"] for tool in tool_schemas()}

        self.assertIn("agentic_board_deliberate", names)
        self.assertIn("agentic_board_propose_sotb_update", names)
        self.assertNotIn("agentic_board_apply_sotb_update", names)

    def test_plugin_rejects_remote_api_targets(self):
        with self.assertRaises(ValueError):
            _local_base_url("https://example.com")

        self.assertEqual("http://127.0.0.1:8000", _local_base_url("http://127.0.0.1:8000"))


if __name__ == "__main__":
    unittest.main()
