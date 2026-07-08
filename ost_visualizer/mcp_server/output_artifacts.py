import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

DEFAULT_INLINE_MAX_CHARS = 12000
DEFAULT_PREVIEW_MAX_CHARS = 3000
DEFAULT_PREVIEW_MAX_LINES = 40
MCP_OUTPUT_DIR_NAME = "mcp_outputs"
JSON_OUTPUT_FORMAT = "json"
TEXT_OUTPUT_FORMAT = "text"
JSON_OUTPUT_SUFFIX = ".json"
TEXT_OUTPUT_SUFFIX = ".txt"
JSON_MIME_TYPE = "application/json"
TEXT_MIME_TYPE = "text/plain"
MAX_UNIQUE_FILENAME_ATTEMPTS = 1000


@dataclass(frozen=True)
class McpOutputArtifact:
    path: str
    format: str
    mime_type: str
    size_bytes: int


@dataclass(frozen=True)
class McpFormattedOutput:
    text: str
    structured_content: Any
    inline_truncated: bool = False
    artifact: Optional[McpOutputArtifact] = None
    save_error: Optional[str] = None


@dataclass(frozen=True)
class _SerializedOutput:
    inline_text: str
    full_text: str
    suffix: str
    format: str
    mime_type: str


class McpOutputFormatter:
    def __init__(
        self,
        output_dir: Path,
        inline_max_chars: int = DEFAULT_INLINE_MAX_CHARS,
        preview_max_chars: int = DEFAULT_PREVIEW_MAX_CHARS,
        preview_max_lines: int = DEFAULT_PREVIEW_MAX_LINES,
        clock: Callable[[], datetime] = datetime.now,
        nonce_factory: Callable[[], str] = lambda: uuid.uuid4().hex[:8],
    ):
        self._output_dir = Path(output_dir)
        self._inline_max_chars = max(1, int(inline_max_chars))
        self._preview_max_chars = max(1, int(preview_max_chars))
        self._preview_max_lines = max(1, int(preview_max_lines))
        self._clock = clock
        self._nonce_factory = nonce_factory

    @property
    def output_dir(self) -> Path:
        return self._output_dir

    @property
    def inline_max_chars(self) -> int:
        return self._inline_max_chars

    def format_result(self, label: str, result: Any) -> McpFormattedOutput:
        serialized = self._serialize_result(result)
        inline_char_count = len(serialized.inline_text)
        if inline_char_count <= self._inline_max_chars:
            return McpFormattedOutput(
                text=serialized.inline_text,
                structured_content=result,
            )
        preview = self._preview(serialized.inline_text)
        try:
            artifact = self._write_artifact(label, serialized)
        except (OSError, UnicodeError) as exc:
            save_error = str(exc)
            return McpFormattedOutput(
                text=self._save_failed_text(
                    label,
                    inline_char_count,
                    preview,
                    save_error,
                ),
                structured_content=self._summary_content(
                    result=result,
                    preview=preview,
                    inline_char_count=inline_char_count,
                    output_format=serialized.format,
                    artifact=None,
                    save_error=save_error,
                ),
                inline_truncated=True,
                save_error=save_error,
            )
        return McpFormattedOutput(
            text=self._saved_text(label, inline_char_count, preview, artifact),
            structured_content=self._summary_content(
                result=result,
                preview=preview,
                inline_char_count=inline_char_count,
                output_format=serialized.format,
                artifact=artifact,
                save_error=None,
            ),
            inline_truncated=True,
            artifact=artifact,
        )

    @staticmethod
    def _serialize_result(result: Any) -> _SerializedOutput:
        if isinstance(result, str):
            return _SerializedOutput(
                inline_text=result,
                full_text=result,
                suffix=TEXT_OUTPUT_SUFFIX,
                format=TEXT_OUTPUT_FORMAT,
                mime_type=TEXT_MIME_TYPE,
            )
        return _SerializedOutput(
            inline_text=json.dumps(result, ensure_ascii=False),
            full_text=json.dumps(result, ensure_ascii=False, indent=2),
            suffix=JSON_OUTPUT_SUFFIX,
            format=JSON_OUTPUT_FORMAT,
            mime_type=JSON_MIME_TYPE,
        )

    def _write_artifact(
        self,
        label: str,
        output: _SerializedOutput,
    ) -> McpOutputArtifact:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        encoded = output.full_text.encode("utf-8")
        for path in self._candidate_paths(label, output.suffix):
            try:
                with path.open("xb") as handle:
                    handle.write(encoded)
                break
            except FileExistsError:
                continue
        else:
            raise FileExistsError("Could not create a unique MCP output file")
        return McpOutputArtifact(
            path=str(path),
            format=output.format,
            mime_type=output.mime_type,
            size_bytes=len(encoded),
        )

    def _candidate_paths(self, label: str, suffix: str) -> Iterator[Path]:
        timestamp = self._clock().strftime("%Y%m%d_%H%M%S_%f")
        safe_label = _sanitize_filename_part(label)
        nonce = _sanitize_filename_part(self._nonce_factory())[:16] or "output"
        base = f"{timestamp}_{safe_label}_{nonce}"
        yield self._output_dir / f"{base}{suffix}"
        for attempt in range(1, MAX_UNIQUE_FILENAME_ATTEMPTS):
            yield self._output_dir / f"{base}_{attempt}{suffix}"

    def _preview(self, text: str) -> str:
        lines = text.splitlines() or [text]
        preview_lines = []
        used = 0
        for line in lines:
            if len(preview_lines) >= self._preview_max_lines:
                break
            remaining = self._preview_max_chars - used
            if remaining <= 0:
                break
            if len(line) > remaining:
                preview_lines.append(line[:remaining].rstrip())
                used = self._preview_max_chars
                break
            preview_lines.append(line)
            used += len(line) + 1
        return "\n".join(preview_lines).strip()

    @staticmethod
    def _saved_text(
        label: str,
        char_count: int,
        preview: str,
        artifact: McpOutputArtifact,
    ) -> str:
        return (
            f"Output from {label} was too long to show inline "
            f"({char_count} characters). Full output saved to: {artifact.path}\n\n"
            f"Preview:\n{preview}"
        )

    @staticmethod
    def _save_failed_text(
        label: str,
        char_count: int,
        preview: str,
        error_message: str,
    ) -> str:
        return (
            f"Output from {label} was too long to show inline "
            f"({char_count} characters), and saving the full output failed: "
            f"{error_message}\n\nPreview:\n{preview}"
        )

    @staticmethod
    def _summary_content(
        result: Any,
        preview: str,
        inline_char_count: int,
        output_format: str,
        artifact: Optional[McpOutputArtifact],
        save_error: Optional[str],
    ) -> dict:
        summary = {
            "inline_truncated": True,
            "inline_char_count": inline_char_count,
            "preview": preview,
            "format": output_format,
            "full_output_saved": artifact is not None,
        }
        if isinstance(result, dict):
            for key in ("success", "status", "meta", "error"):
                if key in result:
                    summary[key] = result[key]
        if artifact is not None:
            summary["full_output"] = {
                "path": artifact.path,
                "format": artifact.format,
                "mime_type": artifact.mime_type,
                "size_bytes": artifact.size_bytes,
            }
        if save_error:
            summary["output_save_error"] = save_error
        return summary


def _sanitize_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value)).strip("-._")
    return cleaned[:80] or "mcp-output"
