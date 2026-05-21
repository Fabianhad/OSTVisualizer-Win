import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from ost_visualizer.mcp_server.registry import DatabaseRegistry
from ost_visualizer.mcp_server.server import build_mcp_server

EXPECTED_TOOLS = {
    "list_databases",
    "get_current_context",
    "list_projects",
    "list_bids",
    "get_bid_summary",
    "list_pages",
    "get_current_page",
    "get_page_pdf_info",
    "list_conditions",
    "search_conditions",
    "get_condition_summary",
    "list_takeoffs",
    "get_selected_takeoffs_summary",
    "get_selected_pages_summary",
    "summarize_quantities",
    "get_page_quantity_summary",
    "search_takeoffs",
    "get_bid_quantity_summary",
    "review_scope_gaps",
    "find_duplicate_conditions",
    "find_zero_quantity_conditions",
    "find_unplaced_takeoffs",
    "get_page_context",
    "find_pages_without_takeoffs",
    "find_conditions_without_takeoffs",
}


class McpInternalServerProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        registry = DatabaseRegistry(app_data_dir=Path(self.tmp.name))
        self.server = build_mcp_server(registry)

    def request(self, method, params=None, request_id=1):
        return self.server._handle_request(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params or {},
            }
        )

    def test_initialize_and_ping(self):
        initialized = self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        )
        result = initialized["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(result["serverInfo"]["name"], "ost-visualizer")
        self.assertIn("tools", result["capabilities"])
        self.assertEqual(self.request("ping")["result"], {})

    def test_tools_list_and_call_shape(self):
        tools = self.request("tools/list")["result"]["tools"]
        tool_names = {tool["name"] for tool in tools}
        self.assertEqual(tool_names, EXPECTED_TOOLS)
        self.assertFalse(any("csv" in name.lower() for name in tool_names))
        self.assertTrue(all(tool["description"] for tool in tools))
        response = self.request(
            "tools/call",
            {"name": "list_databases", "arguments": {}},
        )["result"]
        self.assertEqual(response["content"][0]["type"], "text")
        self.assertFalse(response["isError"])
        self.assertTrue(response["structuredContent"]["success"])
        self.assertEqual(response["structuredContent"]["status"], "no_checked_database")

    def test_resources_and_templates(self):
        resources = self.request("resources/list")["result"]["resources"]
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["uri"], "ost://databases")
        read = self.request(
            "resources/read",
            {"uri": "ost://databases"},
        )[
            "result"
        ]["contents"]
        self.assertEqual(read[0]["mimeType"], "application/json")
        payload = json.loads(read[0]["text"])
        self.assertTrue(payload["success"])
        templates = self.request("resources/templates/list")["result"][
            "resourceTemplates"
        ]
        self.assertEqual(
            {template["uriTemplate"] for template in templates},
            {
                "ost://database/{database_id}/hierarchy",
                "ost://database/{database_id}/bid/{bid_uid}/pages",
                "ost://database/{database_id}/bid/{bid_uid}/conditions",
                "ost://database/{database_id}/bid/{bid_uid}/quantities",
            },
        )

    def test_prompts_list_and_get(self):
        prompts = self.request("prompts/list")["result"]["prompts"]
        prompt_names = {prompt["name"] for prompt in prompts}
        self.assertEqual(
            prompt_names,
            {"review_current_estimator_context", "review_takeoff_scope"},
        )
        self.assertTrue(all(prompt["description"] for prompt in prompts))
        response = self.request(
            "prompts/get",
            {
                "name": "review_takeoff_scope",
                "arguments": {"database_id": "db", "bid_uid": "bid"},
            },
        )["result"]
        self.assertEqual(response["messages"][0]["role"], "user")
        self.assertIn("database_id=db", response["messages"][0]["content"]["text"])

    def test_json_rpc_errors_and_notifications(self):
        self.assertEqual(
            self.server._handle_request({"id": 1, "method": "ping", "params": {}})[
                "error"
            ]["code"],
            -32600,
        )
        self.assertEqual(
            self.server._handle_request(
                {"jsonrpc": "1.0", "id": 1, "method": "ping", "params": {}}
            )["error"]["message"],
            "JSON-RPC version must be 2.0",
        )
        self.assertEqual(
            self.server._handle_request({"jsonrpc": "2.0", "id": 1})["error"]["code"],
            -32600,
        )
        self.assertEqual(
            self.server._handle_request(
                {"jsonrpc": "2.0", "id": 1, "method": 123, "params": {}}
            )["error"]["code"],
            -32600,
        )
        self.assertEqual(
            self.request("does/not/exist")["error"]["code"],
            -32601,
        )
        self.assertEqual(
            self.request(
                "tools/call",
                {"name": "missing_tool", "arguments": {}},
            )[
                "error"
            ]["code"],
            -32601,
        )
        self.assertEqual(
            self.request(
                "tools/call",
                {"name": "list_databases", "arguments": []},
            )[
                "error"
            ]["code"],
            -32602,
        )
        self.assertIsNone(
            self.server._handle_request(
                {"jsonrpc": "2.0", "method": "notifications/initialized"}
            )
        )
        self.assertIsNone(
            self.server._handle_request({"jsonrpc": "2.0", "method": "ping"})
        )

    def test_malformed_json_input_returns_parse_error(self):
        stdin = io.StringIO("{not json}\n")
        stdout = io.StringIO()
        old_stdin = sys.stdin
        old_stdout = sys.stdout
        try:
            sys.stdin = stdin
            sys.stdout = stdout
            with contextlib.redirect_stderr(io.StringIO()):
                self.server.run_stdio()
        finally:
            sys.stdin = old_stdin
            sys.stdout = old_stdout
        response = json.loads(stdout.getvalue())
        self.assertEqual(response["error"]["code"], -32700)


if __name__ == "__main__":
    unittest.main()
