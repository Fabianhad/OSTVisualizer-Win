import json
import sys
from typing import Any, Callable, Optional, TextIO

DEFAULT_PROTOCOL_VERSION = "2025-06-18"
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class JsonRpcStdioServer:
    def __init__(
        self,
        name: str,
        list_tools: Callable[[], list],
        call_tool: Callable[[str, dict], dict],
        version: str = "unknown",
    ):
        self._name = name
        self._list_tools = list_tools
        self._call_tool = call_tool
        self._version = version

    def run(
        self, stdin: Optional[TextIO] = None, stdout: Optional[TextIO] = None
    ) -> None:
        source = stdin if stdin is not None else sys.stdin
        target = stdout if stdout is not None else sys.stdout
        for line in source:
            response = self.handle_line(line)
            if response is None:
                continue
            target.write(response + "\n")
            target.flush()

    def handle_line(self, line: str) -> Optional[str]:
        text = line.strip()
        if not text:
            return None
        try:
            request = json.loads(text)
        except json.JSONDecodeError as exc:
            return _encode(_error(None, PARSE_ERROR, f"Parse error: {exc.msg}"))
        except RecursionError:
            return _encode(_error(None, PARSE_ERROR, "Parse error: nesting too deep"))
        response = self.handle_request(request)
        return None if response is None else _encode(response)

    def handle_request(self, request: Any) -> Optional[dict]:
        if not isinstance(request, dict):
            return _error(None, INVALID_REQUEST, "Invalid JSON-RPC request")
        if "id" not in request:
            return None
        request_id = request.get("id")
        if not _is_valid_id(request_id):
            return _error(None, INVALID_REQUEST, "Invalid JSON-RPC id")
        if request.get("jsonrpc") != "2.0":
            return _error(request_id, INVALID_REQUEST, "JSON-RPC version must be 2.0")
        method = request.get("method")
        if not isinstance(method, str):
            return _error(request_id, INVALID_REQUEST, "Missing JSON-RPC method")
        params = request.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return _error(
                request_id, INVALID_PARAMS, "JSON-RPC params must be an object"
            )
        try:
            result = self._dispatch(method, params)
        except JsonRpcError as exc:
            return _error(request_id, exc.code, exc.message)
        except Exception as exc:
            return _error(
                request_id, INTERNAL_ERROR, f"Internal error: {type(exc).__name__}"
            )
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _dispatch(self, method: str, params: dict) -> dict:
        if method == "initialize":
            return {
                "protocolVersion": params.get("protocolVersion")
                or DEFAULT_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": self._name, "version": self._version},
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": self._list_tools()}
        if method == "tools/call":
            name = params.get("name")
            if not isinstance(name, str) or not name:
                raise JsonRpcError(INVALID_PARAMS, "Missing tool name")
            arguments = params.get("arguments")
            if arguments is None:
                arguments = {}
            if not isinstance(arguments, dict):
                raise JsonRpcError(INVALID_PARAMS, "Tool arguments must be an object")
            return self._call_tool(name, arguments)
        raise JsonRpcError(METHOD_NOT_FOUND, f"Unsupported method: {method}")


def _encode(response: dict) -> str:
    return json.dumps(response, separators=(",", ":"))


def _is_valid_id(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    return isinstance(value, (str, int, float))


def _error(request_id: Any, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }
