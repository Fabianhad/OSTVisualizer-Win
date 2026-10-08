from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from ..application.dtos.ai_takeoff_dtos import UntrustedText

UNTRUSTED_TEXT_KEYS = frozenset(
    {
        "name",
        "display_name",
        "basename",
        "description",
        "estimator",
        "job_id",
        "project_name",
        "bid_name",
        "page_name",
        "sheet_no",
        "sheet_name",
        "page_label",
        "condition_name",
        "old_condition_name",
        "new_condition_name",
        "area_name",
        "selected_area_name",
        "cdn_type_name",
        "type_name",
        "notes",
        "snippet",
        "text",
        "text_snippet",
        "label",
        "root_label",
        "page",
        "area",
        "target_named_view_name",
        "target_page_name",
        "image_basename",
        "overlay_basename",
        "source_file_name",
        "file_basename",
        "selected_file_basename",
    }
)
UNTRUSTED_TEXT_LIST_KEYS = frozenset(
    {"folder_path", "condition_names", "affected_pages", "warnings"}
)


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def _is_text_valued(key: str, node: dict) -> bool:
    if key in UNTRUSTED_TEXT_KEYS:
        return True
    if key in ("old", "new"):
        return "field" in node
    return key == "status" and "bid_no" in node


def mark_untrusted(value: Any) -> Any:
    if isinstance(value, dict):
        marked = {}
        for key, item in value.items():
            if _is_text_valued(key, value) and isinstance(item, str):
                marked[key] = UntrustedText.of(item).to_dict()
            elif key in UNTRUSTED_TEXT_LIST_KEYS and isinstance(item, list):
                marked[key] = [
                    (
                        UntrustedText.of(entry).to_dict()
                        if isinstance(entry, str)
                        else mark_untrusted(entry)
                    )
                    for entry in item
                ]
            else:
                marked[key] = mark_untrusted(item)
        return marked
    if isinstance(value, list):
        return [mark_untrusted(item) for item in value]
    return value


def ok(data: Any, status: str = "ok", meta: Any = None) -> dict:
    payload = {
        "success": True,
        "status": status,
        "data": mark_untrusted(to_jsonable(data)),
    }
    if meta is not None:
        payload["meta"] = to_jsonable(meta)
    return payload


def error(message: str, code: str = "mcp_error") -> dict:
    return {
        "success": False,
        "status": code,
        "error": {
            "code": code,
            "message": str(message),
        },
    }
