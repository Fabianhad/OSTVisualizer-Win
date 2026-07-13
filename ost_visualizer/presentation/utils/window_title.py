from pathlib import PureWindowsPath
from typing import Any, Optional
from ..config import MAIN_WINDOW_TITLE


def format_main_window_title(
    database_path: Optional[str],
    *,
    bid_no: Any = None,
    bid_name: Optional[str] = None,
) -> str:
    database_name = _database_filename(database_path)
    if not database_name:
        return MAIN_WINDOW_TITLE
    bid_label = _format_bid_label(bid_no, bid_name)
    if bid_label:
        return f"{bid_label}; {database_name} - {MAIN_WINDOW_TITLE}"
    return f"{database_name} - {MAIN_WINDOW_TITLE}"


def _database_filename(database_path: Optional[str]) -> str:
    text = str(database_path or "").strip()
    if not text:
        return ""
    return PureWindowsPath(text).name


def _format_bid_label(bid_no: Any, bid_name: Optional[str]) -> str:
    number = _format_bid_number(bid_no)
    name = str(bid_name or "").strip()
    if number and name:
        return f"{number} {name}"
    return number or name


def _format_bid_number(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text == "0":
        return ""
    if text.startswith("[") and text.endswith("]"):
        return text
    return f"[{text}]"
