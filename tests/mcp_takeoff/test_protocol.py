import ast
import io
import json
import sys
import unittest
from pathlib import Path
from ost_visualizer.mcp_takeoff import protocol
from ost_visualizer.mcp_takeoff.protocol import JsonRpcStdioServer

PACKAGE_DIR = Path(protocol.__file__).parent


def _server(calls=None, tools=None, failure=None):
    recorded = calls if calls is not None else []

    def call_tool(name, arguments):
        recorded.append((name, arguments))
        if failure is not None:
            raise failure
        return {"content": [], "structuredContent": {"ok": True}, "isError": False}

    return JsonRpcStdioServer(
        name="ost-visualizer-takeoff",
        list_tools=lambda: tools or [{"name": "list_sheets"}],
        call_tool=call_tool,
    )


def _request(method, params=None, request_id=1):
    request = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        request["params"] = params
    return json.dumps(request)


class JsonRpcStdioServerTests(unittest.TestCase):
    def test_initialize_echoes_the_protocol_version_and_offers_only_tools(self):
        response = json.loads(
            _server().handle_line(_request("initialize", {"protocolVersion": "X"}))
        )
        result = response["result"]
        self.assertEqual(result["protocolVersion"], "X")
        self.assertEqual(result["capabilities"], {"tools": {"listChanged": False}})
        self.assertEqual(result["serverInfo"]["name"], "ost-visualizer-takeoff")
        default = json.loads(_server().handle_line(_request("initialize", {})))
        self.assertEqual(
            default["result"]["protocolVersion"], protocol.DEFAULT_PROTOCOL_VERSION
        )

    def test_initialize_never_echoes_a_non_string_protocol_version(self):
        for value in ({"a": 1}, 5, ["2025-06-18"], ""):
            with self.subTest(value=value):
                response = json.loads(
                    _server().handle_line(
                        _request("initialize", {"protocolVersion": value})
                    )
                )
                self.assertEqual(
                    response["result"]["protocolVersion"],
                    protocol.DEFAULT_PROTOCOL_VERSION,
                )

    def test_non_finite_ids_are_refused_and_the_reply_is_strict_json(self):
        def refuse(constant):
            raise ValueError(constant)

        for literal in ("NaN", "Infinity", "-Infinity", "1e400"):
            with self.subTest(literal=literal):
                line = _server().handle_line(
                    '{"jsonrpc":"2.0","id":' + literal + ',"method":"ping"}'
                )
                response = json.loads(line, parse_constant=refuse)
                self.assertIsNone(response["id"])
                self.assertEqual(response["error"]["code"], -32600)

    def test_null_string_integer_and_finite_float_ids_are_echoed(self):
        for request_id in (None, "req-1", "", 0, 7, 1.5, -2.0):
            with self.subTest(request_id=request_id):
                response = json.loads(
                    _server().handle_line(_request("ping", request_id=request_id))
                )
                self.assertEqual(
                    response, {"jsonrpc": "2.0", "id": request_id, "result": {}}
                )

    def test_structured_ids_are_refused(self):
        for request_id in ([1], {"a": 1}, False):
            with self.subTest(request_id=request_id):
                response = json.loads(
                    _server().handle_line(_request("ping", request_id=request_id))
                )
                self.assertIsNone(response["id"])
                self.assertEqual(response["error"]["code"], -32600)

    def test_tool_names_must_be_non_empty_strings(self):
        for name in (5, "", ["list_sheets"], None):
            calls = []
            with self.subTest(name=name):
                response = json.loads(
                    _server(calls).handle_line(_request("tools/call", {"name": name}))
                )
                self.assertEqual(
                    response["error"], {"code": -32602, "message": "Missing tool name"}
                )
                self.assertEqual(calls, [])

    def test_json_rpc_errors_carry_their_message(self):
        error = protocol.JsonRpcError(protocol.INVALID_PARAMS, "Unknown tool: x")
        self.assertEqual(str(error), "Unknown tool: x")
        self.assertEqual((error.code, error.message), (-32602, "Unknown tool: x"))

    def test_each_response_is_flushed_before_the_next_line_is_read(self):
        buffer = io.BytesIO()
        stdout = io.TextIOWrapper(buffer, encoding="utf-8", newline="\n")
        seen_before_each_read = []

        def lines():
            for request_id in (1, 2):
                seen_before_each_read.append(buffer.getvalue())
                yield _request("ping", request_id=request_id) + "\n"
            seen_before_each_read.append(buffer.getvalue())

        _server().run(lines(), stdout)
        self.assertEqual(
            seen_before_each_read,
            [
                b"",
                b'{"jsonrpc":"2.0","id":1,"result":{}}\n',
                b'{"jsonrpc":"2.0","id":1,"result":{}}\n'
                b'{"jsonrpc":"2.0","id":2,"result":{}}\n',
            ],
        )

    def test_ping_and_tools_list(self):
        server = _server(tools=[{"name": "a"}, {"name": "b"}])
        self.assertEqual(json.loads(server.handle_line(_request("ping")))["result"], {})
        listed = json.loads(server.handle_line(_request("tools/list")))
        self.assertEqual(listed["result"], {"tools": [{"name": "a"}, {"name": "b"}]})

    def test_tools_call_passes_name_and_arguments(self):
        calls = []
        response = json.loads(
            _server(calls).handle_line(
                _request(
                    "tools/call", {"name": "list_sheets", "arguments": {"limit": 3}}
                )
            )
        )
        self.assertEqual(calls, [("list_sheets", {"limit": 3})])
        self.assertEqual(response["result"]["structuredContent"], {"ok": True})
        _server(calls).handle_line(_request("tools/call", {"name": "list_sheets"}))
        self.assertEqual(calls[-1], ("list_sheets", {}))

    def test_protocol_errors_use_json_rpc_codes(self):
        cases = (
            ("not json", -32700),
            (json.dumps([1, 2]), -32600),
            (json.dumps({"jsonrpc": "1.0", "id": 1, "method": "ping"}), -32600),
            (json.dumps({"jsonrpc": "2.0", "id": True, "method": "ping"}), -32600),
            (json.dumps({"jsonrpc": "2.0", "id": 1, "method": 5}), -32600),
            (
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "x", "params": []}),
                -32602,
            ),
            (_request("resources/list"), -32601),
            (_request("tools/call", {}), -32602),
            (_request("tools/call", {"name": "a", "arguments": []}), -32602),
        )
        for line, code in cases:
            with self.subTest(line=line):
                response = json.loads(_server().handle_line(line))
                self.assertEqual(response["error"]["code"], code)
                self.assertNotIn("result", response)

    def test_tool_failures_become_internal_errors_without_tracebacks(self):
        response = json.loads(
            _server(failure=RuntimeError("boom")).handle_line(
                _request("tools/call", {"name": "list_sheets"})
            )
        )
        self.assertEqual(response["error"]["code"], -32603)
        self.assertNotIn("Traceback", response["error"]["message"])

    def test_notifications_and_blank_lines_get_no_response(self):
        server = _server()
        self.assertIsNone(server.handle_line(""))
        self.assertIsNone(
            server.handle_line(json.dumps({"jsonrpc": "2.0", "method": "ping"}))
        )

    def test_deeply_nested_lines_get_a_parse_error_and_the_loop_continues(self):
        stdin = io.StringIO(
            "[" * 100000
            + "\n"
            + '{"a":' * 50000
            + "\n"
            + _request("ping", request_id=3)
            + "\n"
        )
        stdout = io.StringIO()
        _server().run(stdin, stdout)
        responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual([response["id"] for response in responses], [None, None, 3])
        self.assertEqual([r["error"]["code"] for r in responses[:2]], [-32700, -32700])
        self.assertEqual(responses[2]["result"], {})

    def test_strict_utf8_stdout_survives_lone_surrogates_from_a_client(self):
        stdin = io.StringIO(
            '{"jsonrpc":"2.0","id":1,"method":"\\ud800"}\n'
            + _request("ping", request_id=2)
            + "\n"
        )
        buffer = io.BytesIO()
        stdout = io.TextIOWrapper(buffer, encoding="utf-8", newline="\n")
        _server().run(stdin, stdout)
        stdout.flush()
        responses = [
            json.loads(line) for line in buffer.getvalue().decode("utf-8").splitlines()
        ]
        self.assertEqual([response["id"] for response in responses], [1, 2])
        self.assertEqual(responses[0]["error"]["message"], "Unsupported method: \ud800")

    def test_run_reads_lines_and_writes_compact_json_lines(self):
        stdin = io.StringIO(_request("ping", request_id=7) + "\n\n")
        stdout = io.StringIO()
        _server().run(stdin, stdout)
        lines = stdout.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(
            json.loads(lines[0]), {"jsonrpc": "2.0", "id": 7, "result": {}}
        )
        self.assertNotIn(" ", lines[0])


class StdlibOnlyTests(unittest.TestCase):
    ALLOWED_PROJECT_MODULES = {"ost_visualizer.application.dtos.ai_takeoff_dtos"}

    def test_every_module_imports_only_stdlib_and_the_takeoff_dtos(self):
        modules = sorted(PACKAGE_DIR.glob("*.py"))
        siblings = {path.stem for path in modules}
        self.assertGreaterEqual(len(modules), 2)
        for path in modules:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module]
                elif isinstance(node, ast.ImportFrom) and node.level == 1:
                    if (node.module or "") not in siblings:
                        names = ["sibling:" + (node.module or "")]
                elif isinstance(node, ast.ImportFrom):
                    names = ["ost_visualizer." + (node.module or "")]
                for name in names:
                    with self.subTest(module=path.name, imported=name):
                        root = name.split(".")[0]
                        self.assertTrue(
                            root in sys.stdlib_module_names
                            or name in self.ALLOWED_PROJECT_MODULES,
                            name,
                        )


if __name__ == "__main__":
    unittest.main()
