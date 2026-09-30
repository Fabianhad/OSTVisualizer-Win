import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from ost_visualizer.mcp_server.internal_server import OstMcpServer
from ost_visualizer.mcp_server.output_artifacts import (
    JSON_OUTPUT_SUFFIX,
    MCP_OUTPUT_DIR_NAME,
    TEXT_OUTPUT_SUFFIX,
    McpOutputFormatter,
)


class McpOutputArtifactProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output_dir = Path(self.tmp.name) / MCP_OUTPUT_DIR_NAME
        self.clock = lambda: datetime(2026, 7, 7, 12, 30, 45, 123456)
        self.nonce_factory = lambda: "fixed-id"

    def formatter(self, inline_max_chars=80, preview_max_chars=30):
        return McpOutputFormatter(
            self.output_dir,
            inline_max_chars=inline_max_chars,
            preview_max_chars=preview_max_chars,
            clock=self.clock,
            nonce_factory=self.nonce_factory,
        )

    def test_mcp_tool_response_uses_file_reference_for_long_output(self):
        formatter = self.formatter()
        server = OstMcpServer("test", output_formatter=formatter)

        @server.tool()
        def noisy_tool() -> dict:
            return {"success": True, "data": {"lines": ["line"] * 100}}

        response = server._handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "noisy_tool", "arguments": {}},
            }
        )
        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertIn("Full output saved to:", result["content"][0]["text"])
        self.assertTrue(result["structuredContent"]["inline_truncated"])
        output_path = Path(result["structuredContent"]["full_output"]["path"])
        self.assertTrue(output_path.exists())
        self.assertEqual(result["structuredContent"]["full_output"]["format"], "json")

    def test_mcp_resource_response_uses_json_summary_for_long_output(self):
        formatter = self.formatter()
        server = OstMcpServer("test", output_formatter=formatter)

        @server.resource("ost://demo")
        def demo_resource() -> dict:
            return {"success": True, "data": {"rows": ["row"] * 100}}

        response = server._handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "resources/read",
                "params": {"uri": "ost://demo"},
            }
        )
        payload = json.loads(response["result"]["contents"][0]["text"])
        self.assertTrue(payload["inline_truncated"])
        self.assertTrue(Path(payload["full_output"]["path"]).exists())
