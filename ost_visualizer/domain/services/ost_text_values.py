import datetime
from decimal import Decimal
from typing import Optional


def format_ost_datetime(value: datetime.date) -> str:
    if not isinstance(value, datetime.datetime):
        value = datetime.datetime(value.year, value.month, value.day)
    return (
        f"{value.year} {value.month} {value.day} "
        f"{value.hour} {value.minute} {value.second}"
    )


def parse_ost_datetime(text: Optional[str]) -> Optional[datetime.datetime]:
    try:
        parts = text.split()
        if len(parts) == 6:
            return datetime.datetime(*(int(part) for part in parts))
    except (AttributeError, ValueError, TypeError, OverflowError):
        pass
    return None


def format_ost_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError(f"Non-finite decimal value cannot be written: {value}")
    if value == int(value):
        return str(int(value))
    return format(value, "f").rstrip("0").rstrip(".")
