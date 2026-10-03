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

    def call(self, server, name):
        return server._handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": {}},
            }
        )["result"]

    def test_mcp_tool_response_uses_file_reference_for_long_output(self):
        formatter = self.formatter()
        server = OstMcpServer("test", output_formatter=formatter)
        payload = {"success": True, "data": {"lines": ["line"] * 100}}

        @server.tool()
        def noisy_tool() -> dict:
            return payload

        result = self.call(server, "noisy_tool")
        self.assertFalse(result["isError"])
        output_path = Path(result["structuredContent"]["full_output"]["path"])
        # Timestamp from the injected clock, tool label and the injected nonce.
        self.assertEqual(
            output_path,
            self.output_dir / "20260707_123045_123456_tool-noisy_tool_fixed-id.json",
        )
        self.assertEqual(
            result["content"][0]["text"],
            "Output from tool-noisy_tool was too long to show inline "
            f"(838 characters). Full output saved to: {output_path}\n\n"
            'Preview:\n{"success": true, "data": {"li',
        )
        # The inline structured content is a bounded summary, not the payload.
        self.assertEqual(
            result["structuredContent"],
            {
                "inline_truncated": True,
                "inline_char_count": 838,
                "preview": '{"success": true, "data": {"li',
                "format": "json",
                "full_output_saved": True,
                "success": True,
                "full_output": {
                    "path": str(output_path),
                    "format": "json",
                    "mime_type": "application/json",
                    "size_bytes": output_path.stat().st_size,
                },
            },
        )
        # The saved file holds the complete, untruncated result.
        self.assertEqual(json.loads(output_path.read_text(encoding="utf-8")), payload)
        self.assertEqual(
            [path.name for path in self.output_dir.iterdir()], [output_path.name]
        )

    def test_mcp_tool_response_keeps_short_output_inline_without_file(self):
        # Positive control for the long-output test: under the inline limit the
        # result is returned verbatim and no artifact is written.
        server = OstMcpServer("test", output_formatter=self.formatter())

        @server.tool()
        def small_tool() -> dict:
            return {"success": True}

        result = self.call(server, "small_tool")
        self.assertEqual(result["content"][0]["text"], '{"success": true}')
        self.assertEqual(result["structuredContent"], {"success": True})
        self.assertFalse(result["isError"])
        self.assertFalse(self.output_dir.exists())

    def test_mcp_tool_response_reports_unwritable_output_directory(self):
        # The output directory path is occupied by a regular file, so the
        # artifact cannot be created: the preview is still returned and the
        # failure is reported, never silently dropped or raised to the client.
        self.output_dir.write_text("not a directory", encoding="utf-8")
        server = OstMcpServer("test", output_formatter=self.formatter())

        @server.tool()
        def noisy_tool() -> dict:
            return {"success": True, "data": {"lines": ["line"] * 100}}

        result = self.call(server, "noisy_tool")
        structured = result["structuredContent"]
        self.assertFalse(result["isError"])
        self.assertTrue(structured["inline_truncated"])
        self.assertFalse(structured["full_output_saved"])
        self.assertNotIn("full_output", structured)
        self.assertTrue(structured["output_save_error"])
        self.assertIn("saving the full output failed", result["content"][0]["text"])
        self.assertEqual(self.output_dir.read_text(encoding="utf-8"), "not a directory")

    def test_mcp_resource_response_uses_json_summary_for_long_output(self):
        formatter = self.formatter()
        server = OstMcpServer("test", output_formatter=formatter)
        payload = {"success": True, "data": {"rows": ["row"] * 100}}

        @server.resource("ost://demo")
        def demo_resource() -> dict:
            return payload

        response = server._handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "resources/read",
                "params": {"uri": "ost://demo"},
            }
        )
        content = response["result"]["contents"][0]
        self.assertEqual(content["uri"], "ost://demo")
        self.assertEqual(content["mimeType"], "application/json")
        summary = json.loads(content["text"])
        output_path = Path(summary["full_output"]["path"])
        self.assertEqual(
            output_path,
            self.output_dir
            / "20260707_123045_123456_resource-demo_resource_fixed-id.json",
        )
        self.assertEqual(summary["inline_char_count"], 737)
        self.assertTrue(summary["inline_truncated"])
        self.assertTrue(summary["full_output_saved"])
        self.assertEqual(summary["full_output"]["mime_type"], "application/json")
        self.assertEqual(json.loads(output_path.read_text(encoding="utf-8")), payload)
