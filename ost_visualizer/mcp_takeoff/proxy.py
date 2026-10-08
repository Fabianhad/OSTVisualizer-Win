import base64
import binascii
import copy
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from ..application.dtos.ai_takeoff_dtos import INLINE_RESPONSE_MAX_BYTES
from .protocol import INVALID_PARAMS, JsonRpcError
from .tool_catalog import TOOLS, tool_items

PREVIEW_MAX_CHARS = 3000
_MAX_UNIQUE_ATTEMPTS = 1000


class TakeoffProxy:
    def __init__(
        self,
        client,
        output_dir: Path,
        inline_max_bytes: int = INLINE_RESPONSE_MAX_BYTES,
        clock: Callable[[], datetime] = datetime.now,
        nonce_factory: Callable[[], str] = lambda: uuid.uuid4().hex[:8],
    ):
        self._client = client
        self._output_dir = Path(output_dir)
        self._inline_max_bytes = max(256, int(inline_max_bytes))
        self._clock = clock
        self._nonce_factory = nonce_factory
        self._tool_names = frozenset(tool.name for tool in TOOLS)

    def list_tools(self) -> list:
        return tool_items()

    def call_tool(self, name: str, arguments: dict) -> dict:
        if name not in self._tool_names:
            raise JsonRpcError(INVALID_PARAMS, f"Unknown tool: {name}")
        result = self._client.call(name, arguments)
        return self._to_mcp_result(name, result)

    def _to_mcp_result(self, name: str, result: dict) -> dict:
        structured = copy.deepcopy(result)
        content = []
        png_bytes = _pop_png(structured)
        if png_bytes is not None:
            encoded = base64.b64encode(png_bytes).decode("ascii")
            if len(encoded) <= self._inline_max_bytes // 2:
                content.append(
                    {"type": "image", "data": encoded, "mimeType": "image/png"}
                )
            else:
                image = _image_section(structured)
                try:
                    image["file"] = self._save_png(name, png_bytes)
                except OSError as exc:
                    image["file_saved"] = False
                    image["file_save_error"] = str(exc)
        text = json.dumps(structured)
        if len(text.encode("utf-8")) > self._inline_max_bytes:
            structured, text = self._spill_json(name, structured, text)
        content.append({"type": "text", "text": text})
        return {
            "content": content,
            "structuredContent": structured,
            "isError": result.get("success") is not True,
        }

    def _save_png(self, label: str, png_bytes: bytes) -> dict:
        path = self._write_unique(label, ".png", png_bytes)
        return {
            "path": str(path),
            "size_bytes": len(png_bytes),
            "mime_type": "image/png",
        }

    def _spill_json(self, label: str, structured: dict, text: str):
        full_text = json.dumps(structured, indent=2)
        preview = text[:PREVIEW_MAX_CHARS]
        summary = {
            "inline_truncated": True,
            "inline_byte_count": len(text.encode("utf-8")),
            "preview": preview,
        }
        for key in ("success", "status", "meta", "error"):
            if key in structured:
                summary[key] = structured[key]
        image = _image_section(structured)
        if image:
            summary["image"] = image
        try:
            path = self._write_unique(label, ".json", full_text.encode("utf-8"))
        except OSError as exc:
            summary["full_output_saved"] = False
            summary["output_save_error"] = str(exc)
            message = (
                f"Output from {label} was too large to show inline and saving it "
                f"failed: {exc}. Preview:\n{preview}"
            )
        else:
            summary["full_output_saved"] = True
            summary["full_output"] = {"path": str(path), "format": "json"}
            message = (
                f"Output from {label} was too large to show inline. Full output "
                f"saved to: {path}\nPreview:\n{preview}"
            )
        budget = max(64, self._inline_max_bytes - 64)
        return summary, message.encode("utf-8")[:budget].decode("utf-8", "ignore")

    def _write_unique(self, label: str, suffix: str, data: bytes) -> Path:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        stamp = self._clock().strftime("%Y%m%d_%H%M%S_%f")
        nonce = _safe(self._nonce_factory())[:16] or "output"
        base = f"{stamp}_{_safe(label)}_{nonce}"
        for attempt in range(_MAX_UNIQUE_ATTEMPTS):
            name = base if attempt == 0 else f"{base}_{attempt}"
            path = self._output_dir / f"{name}{suffix}"
            try:
                with path.open("xb") as handle:
                    handle.write(data)
            except FileExistsError:
                continue
            return path
        raise FileExistsError("Could not create a unique output file")


def _image_section(structured: dict) -> dict:
    data = structured.get("data")
    if not isinstance(data, dict):
        return {}
    image = data.get("image")
    return image if isinstance(image, dict) else {}


def _pop_png(structured: dict) -> Optional[bytes]:
    image = _image_section(structured)
    encoded = image.pop("png_base64", None)
    if not isinstance(encoded, str):
        return None
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None


def _safe(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value)).strip("-._")
    return cleaned[:80] or "output"
