from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


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


def ok(data: Any) -> dict:
    return {
        "success": True,
        "data": to_jsonable(data),
    }


def error(message: str, code: str = "mcp_error") -> dict:
    return {
        "success": False,
        "error": {
            "code": code,
            "message": str(message),
        },
    }
