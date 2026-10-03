import ast
import contextlib
import inspect
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Optional, Union
from unittest.mock import patch
from ost_visualizer.mcp_server import internal_server
from ost_visualizer.mcp_server.internal_server import OstMcpServer
from ost_visualizer.mcp_server.output_artifacts import McpOutputFormatter
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


def add(a: int, b: int = 2) -> dict:
    """Add two integers."""
    return {"success": True, "sum": a + b}


def refuse() -> dict:
    return {"success": False, "error": {"code": "refused", "message": "no"}}


def explode() -> dict:
    raise RuntimeError("kaboom")


def type_error_inside() -> dict:
    return {"value": len(5)}


def typed(
    name: Optional[str] = None,
    count: int = 1,
    ratio: float = 0.5,
    flag: bool = False,
    options: dict = None,
    items: list = None,
    anything=None,
    unknown: set = None,
) -> dict:
    return {"name": name}


def greet(name: str, punctuation: str = "!") -> str:
    """Say hello."""
    return f"Hello {name}{punctuation}"


def lookup(item: str, part: str) -> dict:
    return {"item": item, "part": part}


def fixed() -> dict:
    return {"fixed": True}


def listing() -> list:
    return ["a", "b"]


def plain_text() -> str:
    return "plain"


def count_prompt() -> int:
    return 5


def accented() -> dict:
    return {"name": "café"}


class OstMcpServerUnitTests(unittest.TestCase):
    """Protocol behaviour of the stdlib server without the OST registry."""

    def setUp(self):
        self.server = OstMcpServer("unit-server")
        self.server.register_tool(add)
        self.server.register_tool(refuse)
        self.server.register_tool(explode)
        self.server.register_tool(type_error_inside)
        self.server.register_tool(typed)
        self.server.register_prompt(greet)
        self.server.register_resource("ost://thing/{item}/part/{part}", lookup)
        self.server.register_resource("ost://fixed", fixed)
        self.server.register_tool(listing)
        self.server.register_tool(plain_text)
        self.server.register_tool(accented)
        self.server.register_prompt(count_prompt)

    def request(self, method, params=None, request_id=1):
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        return self.server._handle_request(message)

    def error_of(self, response):
        self.assertNotIn("result", response)
        return response["error"]["code"], response["error"]["message"]

    def test_initialize_defaults_protocol_version_and_reports_read_only_capabilities(
        self,
    ):
        result = self.request("initialize")["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(
            result["serverInfo"], {"name": "unit-server", "version": "unknown"}
        )
        self.assertEqual(
            result["capabilities"],
            {
                "experimental": {},
                "prompts": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
                "tools": {"listChanged": False},
            },
        )
        echoed = self.request("initialize", {"protocolVersion": "2024-11-05"})
        self.assertEqual(echoed["result"]["protocolVersion"], "2024-11-05")

    def test_tools_list_builds_schemas_from_signatures_and_docstrings(self):
        tools = {t["name"]: t for t in self.request("tools/list")["result"]["tools"]}
        self.assertEqual(
            tools["add"],
            {
                "name": "add",
                "description": "Add two integers.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "integer"},
                        "b": {"type": "integer", "default": 2},
                    },
                    "required": ["a"],
                },
            },
        )
        self.assertEqual(tools["refuse"]["description"], "Refuse")
        self.assertEqual(
            tools["refuse"]["inputSchema"], {"type": "object", "properties": {}}
        )
        self.assertEqual(
            tools["typed"]["inputSchema"]["properties"],
            {
                "name": {"type": "string", "nullable": True, "default": None},
                "count": {"type": "integer", "default": 1},
                "ratio": {"type": "number", "default": 0.5},
                "flag": {"type": "boolean", "default": False},
                "options": {"type": "object", "default": None},
                "items": {"type": "array", "default": None},
                "anything": {"default": None},
                "unknown": {"default": None},
            },
        )
        self.assertNotIn("required", tools["typed"]["inputSchema"])

    def test_tool_call_applies_defaults_and_ignores_undeclared_arguments(self):
        result = self.request(
            "tools/call",
            {"name": "add", "arguments": {"a": 5, "evil": "rm -rf"}},
        )["result"]
        self.assertEqual(result["structuredContent"], {"success": True, "sum": 7})
        self.assertEqual(
            result["content"], [{"type": "text", "text": '{"success": true, "sum": 7}'}]
        )
        self.assertFalse(result["isError"])
        explicit = self.request(
            "tools/call", {"name": "add", "arguments": {"a": 5, "b": 10}}
        )
        self.assertEqual(explicit["result"]["structuredContent"]["sum"], 15)
        no_arguments = self.request("tools/call", {"name": "refuse"})
        self.assertEqual(
            no_arguments["result"]["structuredContent"]["error"]["code"], "refused"
        )

    def test_only_explicit_success_false_is_flagged_as_error(self):
        for name, expected in (("typed", {"name": None}), ("listing", ["a", "b"])):
            with self.subTest(name=name):
                result = self.request("tools/call", {"name": name})["result"]
                self.assertFalse(result["isError"])
                self.assertEqual(result["structuredContent"], expected)
        accented_text = self.request("tools/call", {"name": "accented"})["result"]
        self.assertEqual(accented_text["content"][0]["text"], '{"name": "café"}')
        text = self.request("tools/call", {"name": "plain_text"})["result"]
        self.assertFalse(text["isError"])
        self.assertEqual(text["structuredContent"], "plain")
        self.assertEqual(text["content"], [{"type": "text", "text": '"plain"'}])

    def test_tool_result_with_success_false_is_flagged_as_error(self):
        result = self.request("tools/call", {"name": "refuse", "arguments": {}})[
            "result"
        ]
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["success"], False)

    def test_tool_call_argument_and_name_validation_errors(self):
        cases = (
            ({"name": "add", "arguments": {}}, -32602, "Missing required argument: a"),
            ({"name": "add", "arguments": []}, -32602, "arguments must be an object"),
            (
                {"name": "add", "arguments": "a=1"},
                -32602,
                "arguments must be an object",
            ),
            ({"arguments": {}}, -32602, "Missing required string parameter: name"),
            (
                {"name": "", "arguments": {}},
                -32602,
                "Missing required string parameter: name",
            ),
            (
                {"name": 7, "arguments": {}},
                -32602,
                "Missing required string parameter: name",
            ),
            ({"name": "nope", "arguments": {}}, -32601, "Unknown tool: nope"),
        )
        for params, code, message in cases:
            with self.subTest(params=params):
                self.assertEqual(
                    self.error_of(self.request("tools/call", params)), (code, message)
                )

    def test_tool_failures_map_to_json_rpc_error_codes(self):
        self.assertEqual(
            self.error_of(self.request("tools/call", {"name": "explode"})),
            (-32603, "kaboom"),
        )
        code, message = self.error_of(
            self.request("tools/call", {"name": "type_error_inside"})
        )
        self.assertEqual(code, -32602)
        self.assertIn("len()", message)

    def test_params_must_be_an_object_when_present(self):
        self.assertEqual(self.request("ping", None)["result"], {})
        null_params = self.server._handle_request(
            {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": None}
        )
        self.assertEqual(null_params["result"], {})
        for params in ([], "x", 3):
            with self.subTest(params=params):
                self.assertEqual(
                    self.error_of(self.request("ping", params)),
                    (-32602, "JSON-RPC params must be an object"),
                )

    def test_request_validation_messages_and_ids(self):
        self.assertEqual(
            self.error_of(self.server._handle_request([1])),
            (-32600, "Invalid JSON-RPC request"),
        )
        self.assertEqual(
            self.error_of(self.server._handle_request("ping")),
            (-32600, "Invalid JSON-RPC request"),
        )
        missing = self.server._handle_request({"jsonrpc": "2.0", "id": 4})
        self.assertEqual(
            self.error_of(missing), (-32600, "Missing or invalid JSON-RPC method")
        )
        self.assertEqual(missing["id"], 4)
        for good_id in ("abc", 0, 2.5, None):
            with self.subTest(good_id=good_id):
                response = self.request("ping", request_id=good_id)
                self.assertEqual(response["id"], good_id)
                self.assertEqual(response["result"], {})
        for bad_id in (True, False, [1], {"a": 1}):
            with self.subTest(bad_id=bad_id):
                response = self.request("ping", request_id=bad_id)
                self.assertIsNone(response["id"])
                self.assertEqual(
                    self.error_of(response), (-32600, "Invalid JSON-RPC id")
                )

    def test_notifications_never_get_a_response_even_when_unknown(self):
        for method in ("notifications/initialized", "tools/call", "does/not/exist"):
            with self.subTest(method=method):
                self.assertIsNone(
                    self.server._handle_request({"jsonrpc": "2.0", "method": method})
                )

    def test_unsupported_methods_report_method_not_found(self):
        for method in ("tools/delete", "resources/write", "sampling/createMessage"):
            with self.subTest(method=method):
                self.assertEqual(
                    self.error_of(self.request(method)),
                    (-32601, f"Unsupported method: {method}"),
                )

    def test_resources_list_separates_fixed_uris_from_templates(self):
        resources = self.request("resources/list")["result"]["resources"]
        self.assertEqual(
            resources,
            [
                {
                    "uri": "ost://fixed",
                    "name": "fixed",
                    "description": "Fixed",
                    "mimeType": "application/json",
                }
            ],
        )
        templates = self.request("resources/templates/list")["result"][
            "resourceTemplates"
        ]
        self.assertEqual(
            templates,
            [
                {
                    "uriTemplate": "ost://thing/{item}/part/{part}",
                    "name": "lookup",
                    "description": "Lookup",
                    "mimeType": "application/json",
                }
            ],
        )

    def test_resource_read_matches_templates_and_returns_json_text(self):
        read = self.request("resources/read", {"uri": "ost://thing/a-1/part/p%202"})
        contents = read["result"]["contents"]
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0]["uri"], "ost://thing/a-1/part/p%202")
        self.assertEqual(contents[0]["mimeType"], "application/json")
        self.assertEqual(
            json.loads(contents[0]["text"]), {"item": "a-1", "part": "p%202"}
        )
        accented = self.request("resources/read", {"uri": "ost://thing/café/part/b"})
        self.assertIn("café", accented["result"]["contents"][0]["text"])
        fixed = self.request("resources/read", {"uri": "ost://fixed"})
        self.assertEqual(
            json.loads(fixed["result"]["contents"][0]["text"]), {"fixed": True}
        )

    def test_resource_read_rejects_non_matching_and_missing_uris(self):
        for uri in (
            "ost://thing/a/part/b/extra",
            "ost://thing//part/b",
            "ost://thing/a/part/",
            "xost://thing/a/part/b",
            "ost://fixed/more",
            "file:///etc/passwd",
        ):
            with self.subTest(uri=uri):
                self.assertEqual(
                    self.error_of(self.request("resources/read", {"uri": uri})),
                    (-32601, f"Unknown resource: {uri}"),
                )
        self.assertEqual(
            self.error_of(self.request("resources/read", {})),
            (-32602, "Missing required string parameter: uri"),
        )

    def test_uri_template_matching_escapes_literal_text_and_stops_at_slashes(self):
        match = internal_server._match_uri_template
        self.assertEqual(match("ost://a.b/{x}", "ost://a.b/1"), {"x": "1"})
        self.assertIsNone(match("ost://a.b/{x}", "ost://aXb/1"))
        self.assertEqual(match("ost://fixed", "ost://fixed"), {})
        self.assertIsNone(match("ost://{x}", "ost://a/b"))
        self.assertEqual(
            match("ost://{x}/{y}", "ost://one/two"), {"x": "one", "y": "two"}
        )

    def test_prompts_list_and_get(self):
        prompts = self.request("prompts/list")["result"]["prompts"]
        self.assertEqual(
            prompts,
            [
                {
                    "name": "greet",
                    "description": "Say hello.",
                    "arguments": [
                        {"name": "name", "description": "", "required": True},
                        {"name": "punctuation", "description": "", "required": False},
                    ],
                },
                {
                    "name": "count_prompt",
                    "description": "Count prompt",
                    "arguments": [],
                },
            ],
        )
        got = self.request(
            "prompts/get", {"name": "greet", "arguments": {"name": "Ana"}}
        )
        self.assertEqual(
            got["result"],
            {
                "description": "Say hello.",
                "messages": [
                    {"role": "user", "content": {"type": "text", "text": "Hello Ana!"}}
                ],
            },
        )
        number = self.request("prompts/get", {"name": "count_prompt"})
        self.assertEqual(
            number["result"]["messages"][0]["content"], {"type": "text", "text": "5"}
        )
        self.assertEqual(
            self.error_of(self.request("prompts/get", {"name": "greet"})),
            (-32602, "Missing required argument: name"),
        )
        self.assertEqual(
            self.error_of(self.request("prompts/get", {"name": "nope"})),
            (-32601, "Unknown prompt: nope"),
        )

    def test_decorators_register_and_return_the_original_function(self):
        server = OstMcpServer("decorated")

        @server.tool
        def bare() -> dict:
            """Bare tool."""
            return {}

        @server.tool()
        def called() -> dict:
            return {}

        @server.prompt()
        def prompted() -> str:
            return "p"

        @server.resource("ost://decorated")
        def resourced() -> dict:
            return {}

        self.assertEqual(bare(), {})
        self.assertEqual([t["name"] for t in server.list_tools()], ["bare", "called"])
        self.assertEqual(server.list_tools()[0]["description"], "Bare tool.")
        self.assertEqual([p["name"] for p in server.list_prompts()], ["prompted"])
        self.assertEqual(
            [r["uri"] for r in server.list_resources()], ["ost://decorated"]
        )

    def test_registering_a_tool_twice_keeps_the_latest_definition(self):
        def add(a: int) -> dict:
            return {"replaced": a}

        self.server.register_tool(add)
        names = [t["name"] for t in self.server.list_tools()]
        self.assertEqual(names.count("add"), 1)
        result = self.request("tools/call", {"name": "add", "arguments": {"a": 3}})
        self.assertEqual(result["result"]["structuredContent"], {"replaced": 3})

    def test_output_formatter_labels_tool_and_resource_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            formatter = McpOutputFormatter(Path(tmp), inline_max_chars=20)
            server = OstMcpServer("formatted", output_formatter=formatter)
            server.register_tool(add)
            server.register_resource("ost://thing/{item}/part/{part}", lookup)
            called = server._handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "add", "arguments": {"a": 1}},
                }
            )["result"]
            self.assertTrue(called["structuredContent"]["inline_truncated"])
            self.assertIn(
                "Output from tool-add was too long", called["content"][0]["text"]
            )
            self.assertFalse(called["isError"])
            read = server._handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "resources/read",
                    "params": {"uri": "ost://thing/aaaaaaaa/part/bbbbbbbb"},
                }
            )["result"]["contents"][0]
            summary = json.loads(read["text"])
            self.assertTrue(summary["inline_truncated"])
            names = sorted(p.name for p in Path(tmp).iterdir())
            self.assertEqual(len(names), 2)
            self.assertTrue(any("_tool-add_" in name for name in names))
            self.assertTrue(any("_resource-lookup_" in name for name in names))

    def run_stdio(self, text):
        stdout = io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(text)), patch.object(
            sys, "stdout", stdout
        ):
            self.server.run_stdio()
        return stdout.getvalue()

    def test_stdio_loop_answers_requests_skips_blanks_and_notifications(self):
        output = self.run_stdio(
            "\n"
            '{"jsonrpc": "2.0", "method": "notifications/initialized"}\n'
            "   \n"
            '{"jsonrpc": "2.0", "id": 7, "method": "ping"}\n'
            '{"jsonrpc": "2.0", "id": "x", "method": "tools/call",'
            ' "params": {"name": "add", "arguments": {"a": 1, "b": 1}}}\n'
        )
        lines = output.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], '{"jsonrpc":"2.0","id":7,"result":{}}')
        second = json.loads(lines[1])
        self.assertEqual(second["id"], "x")
        self.assertEqual(second["result"]["structuredContent"]["sum"], 2)
        self.assertNotIn("\n", lines[1])

    def test_stdio_loop_survives_bad_lines_and_keeps_serving(self):
        output = self.run_stdio(
            "{not json}\n" "[1, 2]\n" '{"jsonrpc": "2.0", "id": 1, "method": "ping"}\n'
        )
        responses = [json.loads(line) for line in output.splitlines()]
        self.assertEqual(len(responses), 3)
        self.assertEqual(responses[0]["error"]["code"], -32700)
        self.assertTrue(responses[0]["error"]["message"].startswith("Parse error: "))
        self.assertIsNone(responses[0]["id"])
        self.assertEqual(responses[1]["error"]["code"], -32600)
        self.assertEqual(responses[2]["result"], {})


class OstMcpServerSchemaHelperTests(unittest.TestCase):
    def test_optional_and_union_annotations_become_nullable_schemas(self):
        schema = internal_server._schema_for_annotation
        self.assertEqual(schema(Optional[int]), {"type": "integer", "nullable": True})
        self.assertEqual(schema(Optional[bool]), {"type": "boolean", "nullable": True})
        self.assertEqual(schema(Union[str, int]), {})
        self.assertEqual(schema(Any), {"type": "object"})
        self.assertEqual(schema(inspect.Parameter.empty), {})

    def test_server_imports_only_stdlib_and_relative_modules(self):
        tree = ast.parse(Path(internal_server.__file__).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                imported.add(node.module.split(".")[0])
        self.assertIn("json", imported)
        self.assertEqual(imported - set(sys.stdlib_module_names), set())
