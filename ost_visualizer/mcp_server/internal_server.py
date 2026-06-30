import inspect
import json
import re
import sys
from dataclasses import dataclass
from string import Formatter
from typing import Any, Callable, Optional, Union, get_args, get_origin


@dataclass(frozen=True)
class _Handler:
    name: str
    fn: Callable
    input_schema: dict
    description: str = ""


@dataclass(frozen=True)
class _ResourceHandler:
    uri_template: str
    fn: Callable
    name: str
    description: str = ""
    mime_type: str = "application/json"


class OstMcpServer:
    def __init__(self, name: str = "ost-visualizer"):
        self.name = name
        self._tools: dict[str, _Handler] = {}
        self._prompts: dict[str, _Handler] = {}
        self._resources: dict[str, _ResourceHandler] = {}

    def tool(self, fn: Optional[Callable] = None):
        def decorator(func: Callable):
            self.register_tool(func)
            return func

        return decorator(fn) if fn is not None else decorator

    def prompt(self, fn: Optional[Callable] = None):
        def decorator(func: Callable):
            self.register_prompt(func)
            return func

        return decorator(fn) if fn is not None else decorator

    def resource(self, uri_template: str):
        def decorator(func: Callable):
            self.register_resource(uri_template, func)
            return func

        return decorator

    def register_tool(self, fn: Callable) -> None:
        self._tools[fn.__name__] = _Handler(
            name=fn.__name__,
            fn=fn,
            input_schema=_input_schema_for(fn),
            description=_handler_description(fn),
        )

    def register_prompt(self, fn: Callable) -> None:
        self._prompts[fn.__name__] = _Handler(
            name=fn.__name__,
            fn=fn,
            input_schema=_input_schema_for(fn),
            description=_handler_description(fn),
        )

    def register_resource(self, uri_template: str, fn: Callable) -> None:
        self._resources[uri_template] = _ResourceHandler(
            uri_template=uri_template,
            fn=fn,
            name=fn.__name__,
            description=_handler_description(fn),
        )

    def list_tools(self) -> list[dict]:
        return [_tool_item(handler) for handler in self._tools.values()]

    def list_prompts(self) -> list[dict]:
        return [_prompt_item(handler) for handler in self._prompts.values()]

    def list_resources(self) -> list[dict]:
        resources = []
        for handler in self._resources.values():
            if "{" in handler.uri_template:
                continue
            resources.append(_resource_item(handler))
        return resources

    def list_resource_templates(self) -> list[dict]:
        templates = []
        for handler in self._resources.values():
            if "{" not in handler.uri_template:
                continue
            templates.append(_resource_template_item(handler))
        return templates

    def run_stdio(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                response = _error_response(None, -32700, f"Parse error: {exc.msg}")
            else:
                response = self._handle_request(request)
            if response is None:
                continue
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()

    def _handle_request(self, request: Any) -> Optional[dict]:
        if not isinstance(request, dict):
            return _error_response(None, -32600, "Invalid JSON-RPC request")
        if "id" not in request:
            return None
        request_id = request.get("id")
        if not _is_valid_request_id(request_id):
            return _error_response(None, -32600, "Invalid JSON-RPC id")
        if request.get("jsonrpc") != "2.0":
            return _error_response(request_id, -32600, "JSON-RPC version must be 2.0")
        method = request.get("method")
        params = request.get("params", {})
        if not isinstance(method, str):
            return _error_response(
                request_id, -32600, "Missing or invalid JSON-RPC method"
            )
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return _error_response(
                request_id, -32602, "JSON-RPC params must be an object"
            )
        try:
            result = self._dispatch(method, params)
        except KeyError as exc:
            return _error_response(request_id, -32601, str(exc).strip("'"))
        except TypeError as exc:
            return _error_response(request_id, -32602, str(exc))
        except Exception as exc:
            return _error_response(request_id, -32603, str(exc))
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _dispatch(self, method: str, params: dict) -> dict:
        if method == "initialize":
            protocol_version = params.get("protocolVersion") or "2025-06-18"
            return {
                "protocolVersion": protocol_version,
                "capabilities": {
                    "experimental": {},
                    "prompts": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                    "tools": {"listChanged": False},
                },
                "serverInfo": {"name": self.name, "version": "unknown"},
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": self.list_tools()}
        if method == "tools/call":
            name = _required_str(params, "name")
            arguments = _optional_object(params, "arguments")
            return self._call_tool(name, arguments)
        if method == "resources/list":
            return {"resources": self.list_resources()}
        if method == "resources/templates/list":
            return {"resourceTemplates": self.list_resource_templates()}
        if method == "resources/read":
            uri = _required_str(params, "uri")
            return self._read_resource(uri)
        if method == "prompts/list":
            return {"prompts": self.list_prompts()}
        if method == "prompts/get":
            name = _required_str(params, "name")
            arguments = _optional_object(params, "arguments")
            return self._get_prompt(name, arguments)
        raise KeyError(f"Unsupported method: {method}")

    def _call_tool(self, name: str, arguments: dict) -> dict:
        handler = self._tools.get(name)
        if handler is None:
            raise KeyError(f"Unknown tool: {name}")
        result = _invoke(handler.fn, arguments)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False),
                }
            ],
            "structuredContent": result,
            "isError": _is_error_result(result),
        }

    def _get_prompt(self, name: str, arguments: dict) -> dict:
        handler = self._prompts.get(name)
        if handler is None:
            raise KeyError(f"Unknown prompt: {name}")
        text = _invoke(handler.fn, arguments)
        return {
            "description": handler.description,
            "messages": [
                {
                    "role": "user",
                    "content": {"type": "text", "text": str(text)},
                }
            ],
        }

    def _read_resource(self, uri: str) -> dict:
        for handler in self._resources.values():
            match = _match_uri_template(handler.uri_template, uri)
            if match is None:
                continue
            result = handler.fn(**match)
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": handler.mime_type,
                        "text": json.dumps(result, ensure_ascii=False),
                    }
                ]
            }
        raise KeyError(f"Unknown resource: {uri}")


def _invoke(fn: Callable, arguments: dict) -> Any:
    signature = inspect.signature(fn)
    call_arguments = {}
    for name, parameter in signature.parameters.items():
        if name in arguments:
            call_arguments[name] = arguments[name]
        elif parameter.default is inspect.Parameter.empty:
            raise TypeError(f"Missing required argument: {name}")
    return fn(**call_arguments)


def _input_schema_for(fn: Callable) -> dict:
    signature = inspect.signature(fn)
    properties = {}
    required = []
    for name, parameter in signature.parameters.items():
        properties[name] = _schema_for_annotation(parameter.annotation)
        if parameter.default is not inspect.Parameter.empty:
            properties[name]["default"] = parameter.default
        else:
            required.append(name)
    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _tool_item(handler: _Handler) -> dict:
    return {
        "name": handler.name,
        "description": handler.description,
        "inputSchema": handler.input_schema,
    }


def _prompt_item(handler: _Handler) -> dict:
    return {
        "name": handler.name,
        "description": handler.description,
        "arguments": _prompt_arguments(handler.input_schema),
    }


def _resource_item(handler: _ResourceHandler) -> dict:
    return {
        "uri": handler.uri_template,
        "name": handler.name,
        "description": handler.description,
        "mimeType": handler.mime_type,
    }


def _resource_template_item(handler: _ResourceHandler) -> dict:
    return {
        "uriTemplate": handler.uri_template,
        "name": handler.name,
        "description": handler.description,
        "mimeType": handler.mime_type,
    }


def _handler_description(fn: Callable) -> str:
    return inspect.getdoc(fn) or fn.__name__.replace("_", " ").capitalize()


def _schema_for_annotation(annotation: Any) -> dict:
    if annotation is inspect.Parameter.empty:
        return {}
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Union and type(None) in args:
        non_none = [arg for arg in args if arg is not type(None)]
        schema = _schema_for_annotation(non_none[0]) if non_none else {}
        schema["nullable"] = True
        return schema
    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation in (dict, Any):
        return {"type": "object"}
    if annotation is list:
        return {"type": "array"}
    return {}


def _prompt_arguments(input_schema: dict) -> list[dict]:
    properties = input_schema.get("properties", {})
    required = set(input_schema.get("required", []))
    return [
        {
            "name": name,
            "description": "",
            "required": name in required,
        }
        for name in properties
    ]


def _match_uri_template(uri_template: str, uri: str) -> Optional[dict[str, str]]:
    fields = [field for _, field, _, _ in Formatter().parse(uri_template) if field]
    pattern = re.escape(uri_template)
    for field in fields:
        pattern = pattern.replace(r"\{" + field + r"\}", f"(?P<{field}>[^/]+)")
    match = re.fullmatch(pattern, uri)
    if match is None:
        return None
    return match.groupdict()


def _required_str(params: dict, name: str) -> str:
    value = params.get(name)
    if not isinstance(value, str) or not value:
        raise TypeError(f"Missing required string parameter: {name}")
    return value


def _optional_object(params: dict, name: str) -> dict:
    value = params.get(name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be an object")
    return value


def _is_error_result(result: Any) -> bool:
    return isinstance(result, dict) and result.get("success") is False


def _is_valid_request_id(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    return isinstance(value, (str, int, float))


def _error_response(request_id: Any, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }
