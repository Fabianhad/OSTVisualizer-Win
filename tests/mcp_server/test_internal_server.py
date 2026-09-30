import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from ost_visualizer.mcp_server.registry import DatabaseRegistry
from ost_visualizer.mcp_server.server import build_mcp_server


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
        invalid_id = self.server._handle_request(
            {"jsonrpc": "2.0", "id": {"bad": "id"}, "method": "ping", "params": {}}
        )
        self.assertEqual(invalid_id["id"], None)
        self.assertEqual(invalid_id["error"]["code"], -32600)
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
        self.assertEqual(
            self.server._handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "notifications/initialized",
                }
            )["error"]["code"],
            -32601,
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
