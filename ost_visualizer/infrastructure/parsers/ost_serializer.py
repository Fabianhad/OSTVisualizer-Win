import datetime
import decimal
from typing import Any, Dict, List, Optional, Tuple, Type


def _format_decimal_string(value: decimal.Decimal) -> str:
    if value == int(value):
        return str(int(value))
    return format(value, "f").rstrip("0").rstrip(".")


def _format_float(value: float) -> str:
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.15f}".rstrip("0").rstrip(".")


def serialize_value(value: Any, col_type: Optional[Type] = None) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, datetime.datetime):
        return f"{value.year} {value.month} {value.day} {value.hour} {value.minute} {value.second}"
    if isinstance(value, bytes):
        decoded = value.decode("utf-8", errors="ignore")
        return decoded.replace("\x00", "")
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return _format_float(value)
    if isinstance(value, decimal.Decimal):
        return _format_decimal_string(value)
    return str(value)


def serialize_row(row: Any, cursor_description: List[Tuple]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for i, col_info in enumerate(cursor_description):
        col_name = col_info[0]
        col_type = col_info[1]
        value = row[i]
        result[col_name] = serialize_value(value, col_type)
    return result
