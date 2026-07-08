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

LONG_TEXT = "log line\n" * 40
LONG_JSON_VALUE = "x" * 200


class McpOutputArtifactTests(unittest.TestCase):
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

    def test_short_output_remains_inline_without_file(self):
        formatter = self.formatter(inline_max_chars=500)
        result = {"success": True, "data": {"message": "small"}}
        formatted = formatter.format_result("tool-list_databases", result)
        self.assertFalse(formatted.inline_truncated)
        self.assertEqual(json.loads(formatted.text), result)
        self.assertEqual(formatted.structured_content, result)
        self.assertFalse(self.output_dir.exists())

    def test_long_output_is_summarized_and_saved_to_json_file(self):
        formatter = self.formatter()
        result = {
            "success": True,
            "status": "truncated",
            "meta": {"truncated": True, "has_more": True},
            "data": {"stdout": LONG_JSON_VALUE},
        }
        formatted = formatter.format_result("tool-long_stdout", result)
        self.assertTrue(formatted.inline_truncated)
        self.assertIn("Full output saved to:", formatted.text)
        self.assertNotIn(LONG_JSON_VALUE, formatted.text)
        self.assertIsNotNone(formatted.artifact)
        output_path = Path(formatted.artifact.path)
        self.assertEqual(output_path.suffix, JSON_OUTPUT_SUFFIX)
        self.assertTrue(output_path.exists())
        self.assertEqual(json.loads(output_path.read_text(encoding="utf-8")), result)
        self.assertTrue(formatted.structured_content["full_output_saved"])
        self.assertEqual(formatted.structured_content["format"], "json")
        self.assertEqual(
            formatted.structured_content["meta"],
            {"truncated": True, "has_more": True},
        )
        self.assertGreater(formatted.structured_content["inline_char_count"], 80)
        self.assertEqual(
            formatted.structured_content["full_output"]["path"],
            str(output_path),
        )
        self.assertEqual(formatted.structured_content["full_output"]["format"], "json")
        self.assertNotIn("data", formatted.structured_content)

    def test_long_stderr_failure_preserves_full_output(self):
        formatter = self.formatter()
        result = {
            "success": False,
            "status": "command_failed",
            "error": {"code": "failed", "message": "command failed"},
            "stderr": "error line\n" * 80,
            "exit_code": 1,
        }
        formatted = formatter.format_result("tool-command", result)
        output_path = Path(formatted.artifact.path)
        saved = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["stderr"], result["stderr"])
        self.assertEqual(formatted.structured_content["error"], result["error"])
        self.assertTrue(formatted.structured_content["inline_truncated"])

    def test_long_plain_text_output_is_saved_to_txt_file(self):
        formatter = self.formatter()
        formatted = formatter.format_result("tool-log", LONG_TEXT)
        output_path = Path(formatted.artifact.path)
        self.assertEqual(output_path.suffix, TEXT_OUTPUT_SUFFIX)
        self.assertEqual(output_path.read_text(encoding="utf-8"), LONG_TEXT)
        self.assertEqual(formatted.artifact.format, "text")
        self.assertEqual(formatted.artifact.mime_type, "text/plain")
        self.assertEqual(formatted.structured_content["format"], "text")

    def test_file_names_are_sanitized(self):
        formatter = self.formatter()
        formatted = formatter.format_result(
            "tool:bad/name with spaces",
            {"data": "x" * 200},
        )
        output_name = Path(formatted.artifact.path).name
        self.assertIn("tool-bad-name-with-spaces", output_name)
        self.assertNotIn(":", output_name)
        self.assertNotIn("/", output_name)

    def test_existing_files_are_not_overwritten(self):
        formatter = self.formatter()
        self.output_dir.mkdir(parents=True)
        existing = (
            self.output_dir
            / f"20260707_123045_123456_tool-long_fixed-id{JSON_OUTPUT_SUFFIX}"
        )
        existing.write_text("keep me", encoding="utf-8")
        formatted = formatter.format_result("tool-long", {"data": "x" * 200})
        self.assertEqual(existing.read_text(encoding="utf-8"), "keep me")
        self.assertTrue(
            Path(formatted.artifact.path).name.endswith(f"_1{JSON_OUTPUT_SUFFIX}")
        )

    def test_file_write_failure_falls_back_to_inline_preview(self):
        blocking_path = self.output_dir
        blocking_path.write_text("not a directory", encoding="utf-8")
        formatter = self.formatter()
        formatted = formatter.format_result("tool-long", {"data": "x" * 200})
        self.assertTrue(formatted.inline_truncated)
        self.assertIsNone(formatted.artifact)
        self.assertIn("saving the full output failed", formatted.text)
        self.assertIn("output_save_error", formatted.structured_content)

    def test_preview_is_deterministic(self):
        formatter = self.formatter(preview_max_chars=25)
        result = {"data": "abcdefghijklmnopqrstuvwxyz" * 10}
        first = formatter.format_result("tool-preview", result)
        second = formatter.format_result("tool-preview", result)
        self.assertEqual(
            first.structured_content["preview"],
            second.structured_content["preview"],
        )
        self.assertLessEqual(len(first.structured_content["preview"]), 25)

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


if __name__ == "__main__":
    unittest.main()
