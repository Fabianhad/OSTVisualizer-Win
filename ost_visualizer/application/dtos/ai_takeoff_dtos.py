import unicodedata
from dataclasses import dataclass
from typing import Any, Optional

AI_TAKEOFF_BRIDGE_SERVER_NAME = "OSTVisualizerTakeoffBridge.v1"
APP_DATA_DIR_NAME = ".ost_visualizer"
AI_TAKEOFF_DIR_NAME = "ai_takeoff"
AI_TAKEOFF_SESSION_TOKEN_FILE_NAME = "session.token"
AI_TAKEOFF_SIDECAR_DIR_NAME = "bids"
AI_TAKEOFF_OUTPUT_DIR_NAME = "mcp_takeoff_outputs"
MAX_EXPOSED_TOOLS = 20
INLINE_RESPONSE_MAX_BYTES = 256 * 1024
UNTRUSTED_TEXT_MAX_CHARS = 500
DEFAULT_LIMIT = 100
MAX_LIMIT = 500
RENDER_DEFAULT_DPI = 100.0
RENDER_MAX_DPI = 200.0
RENDER_MAX_LONG_SIDE_PX = 1600
PIPE_READ_TIMEOUT_SECONDS = 120.0
COMMAND_LIST_SHEETS = "list_sheets"
COMMAND_RENDER_SHEET = "render_sheet"
COMMAND_LIST_TEXT = "list_text"
COMMAND_LIST_SEGMENTS = "list_segments"
COMMAND_GET_QUANTITIES = "get_quantities"
COMMAND_LIST_LEVELS = "list_levels"
COMMAND_LIST_ASSUMPTIONS = "list_assumptions"
M1A_COMMANDS = (
    COMMAND_LIST_SHEETS,
    COMMAND_RENDER_SHEET,
    COMMAND_LIST_TEXT,
    COMMAND_LIST_SEGMENTS,
    COMMAND_GET_QUANTITIES,
    COMMAND_LIST_LEVELS,
    COMMAND_LIST_ASSUMPTIONS,
)
M1A_COMMAND_ARGUMENTS = {
    COMMAND_LIST_SHEETS: frozenset({"bid_uid", "cursor", "limit"}),
    COMMAND_RENDER_SHEET: frozenset({"page_uid", "crop_pts", "dpi", "overlay_ids"}),
    COMMAND_LIST_TEXT: frozenset({"page_uid", "bbox_pts", "query", "cursor", "limit"}),
    COMMAND_LIST_SEGMENTS: frozenset({"page_uid", "bbox_pts", "cursor", "limit"}),
    COMMAND_GET_QUANTITIES: frozenset({"bid_uid", "group_by"}),
    COMMAND_LIST_LEVELS: frozenset({"bid_uid"}),
    COMMAND_LIST_ASSUMPTIONS: frozenset({"bid_uid", "status"}),
}
STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_TRUNCATED = "truncated"
STATUS_NOT_PDF = "not_pdf"
OVERLAY_NOT_SUPPORTED_UNTIL_M1B = "not_supported_until_m1b"
ERROR_APP_NOT_RUNNING = "app_not_running"
ERROR_UNAUTHORIZED = "unauthorized"
ERROR_FEATURE_DENIED = "feature_denied"
ERROR_UNKNOWN_COMMAND = "unknown_command"
ERROR_INVALID_ARGUMENT = "invalid_argument"
ERROR_BID_NOT_OPEN = "bid_not_open"
ERROR_NOT_FOUND = "not_found"
ERROR_MALFORMED_RESPONSE = "malformed_bridge_response"
ERROR_UNEXPECTED = "unexpected_error"
ERROR_APP_TIMEOUT = "app_timeout"
ERROR_BUSY = "busy"
SIDECAR_OK = "ok"
SIDECAR_EMPTY = "empty"
SIDECAR_REBIND_REQUIRED = "rebind_required"
SIDECAR_FINGERPRINT_MISMATCH = "fingerprint_mismatch"
SIDECAR_CORRUPT = "corrupt"
SIDECAR_UNAVAILABLE_NO_DATABASE_GUID = "unavailable_no_database_guid"
SIDECAR_STATUSES = (
    SIDECAR_OK,
    SIDECAR_EMPTY,
    SIDECAR_REBIND_REQUIRED,
    SIDECAR_FINGERPRINT_MISMATCH,
    SIDECAR_CORRUPT,
    SIDECAR_UNAVAILABLE_NO_DATABASE_GUID,
)
_CURSOR_PREFIX = "c:"


class AiTakeoffRequestError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PageSnapshot:
    uid: str
    image_path: str
    page_index: int
    width_pts: float
    height_pts: float
    ost_per_page_point: Optional[float]
    is_pdf: bool


@dataclass(frozen=True)
class CropPlan:
    page_uid: str
    file_path: str
    page_index: int
    frame_pts: tuple
    scale: float
    width_px: int
    height_px: int
    px_to_page_pts: tuple
    page_pts_to_ost: Optional[tuple]


_WHITESPACE_CONTROLS = frozenset("\t\n\r\x0b\x0c")
_BIDI_FORMATTING = frozenset(
    "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
)


def _strip_controls(value: str) -> str:
    kept = []
    for character in value:
        if character in _WHITESPACE_CONTROLS:
            kept.append(" ")
        elif (
            character not in _BIDI_FORMATTING
            and unicodedata.category(character) != "Cc"
        ):
            kept.append(character)
    return "".join(kept)


@dataclass(frozen=True)
class UntrustedText:
    value: str
    truncated: bool = False

    @classmethod
    def of(cls, text: Any) -> "UntrustedText":
        value = "" if text is None else str(text)
        value = value.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
        value = _strip_controls(value)
        if len(value) > UNTRUSTED_TEXT_MAX_CHARS:
            return cls(value=value[:UNTRUSTED_TEXT_MAX_CHARS], truncated=True)
        return cls(value=value)

    def to_dict(self) -> dict:
        return {"value": self.value, "untrusted": True, "truncated": self.truncated}


@dataclass(frozen=True)
class ResultMeta:
    limit: int
    returned_count: int
    total_count: int
    next_cursor: Optional[str] = None

    def to_dict(self) -> dict:
        has_more = self.next_cursor is not None
        return {
            "limit": self.limit,
            "returned_count": self.returned_count,
            "total_count": self.total_count,
            "truncated": has_more,
            "has_more": has_more,
            "next_cursor": self.next_cursor,
        }


def ok_result(
    data: Any, status: str = STATUS_OK, meta: Optional[ResultMeta] = None
) -> dict:
    result = {"success": True, "status": status, "data": data}
    if meta is not None:
        result["meta"] = meta.to_dict()
    return result


def error_result(code: str, message: str) -> dict:
    return {
        "success": False,
        "status": code,
        "error": {"code": code, "message": message},
    }


def encode_cursor(offset: int) -> str:
    return f"{_CURSOR_PREFIX}{int(offset)}"


def decode_cursor(cursor: Any) -> int:
    if cursor is None or cursor == "":
        return 0
    if not isinstance(cursor, str) or not cursor.startswith(_CURSOR_PREFIX):
        raise ValueError("Invalid cursor")
    digits = cursor[len(_CURSOR_PREFIX) :]
    if not digits.isdecimal():
        raise ValueError("Invalid cursor")
    return int(digits)


def clamp_limit(limit: Any) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer")
    return max(1, min(MAX_LIMIT, limit))
