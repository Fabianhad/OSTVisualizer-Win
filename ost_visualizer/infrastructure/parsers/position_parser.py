import re
from functools import lru_cache
from typing import Tuple
from ...domain.services.dimension_format_service import inches_to_display
from ...domain.services.elevation import parse_elevation, reassemble_elevation
from ...domain.services.elevation_text import (
    IMPERIAL_FEET_INCHES as _IMPERIAL_FEET_INCHES,
    IMPERIAL_FEET_ONLY as _IMPERIAL_FEET_ONLY,
    IMPERIAL_INCHES_ONLY as _IMPERIAL_INCHES_ONLY,
    METRIC_CM_ONLY as _METRIC_CM_ONLY,
    METRIC_METERS_ONLY as _METRIC_METERS_ONLY,
    METRIC_M_PLUS_CM as _METRIC_M_PLUS_CM,
    is_elevation_text as _is_valid_elevation_text,
)


def cm_to_inches(cm: float) -> float:
    return cm / 2.54


def _fraction_value(numerator_text: str, denominator_text: str) -> float:
    numerator = float(numerator_text)
    denominator = float(denominator_text)
    if denominator == 0.0:
        raise ValueError(
            f"zero denominator in fraction {numerator_text}/{denominator_text}"
        )
    return numerator / denominator


def _parse_fractional_inches_text(inch_text: str) -> float:
    inch_text = " ".join(inch_text.split())
    negative = inch_text.startswith("-")
    if negative:
        inch_text = inch_text[1:].strip()
    if " " in inch_text:
        whole_part, frac_part = inch_text.split(None, 1)
        try:
            whole = float(whole_part)
        except ValueError:
            whole = 0.0
        if "/" in frac_part:
            num, den = frac_part.split("/", 1)
            frac = _fraction_value(num, den)
        else:
            frac = float(frac_part)
        value = whole + frac
    elif "/" in inch_text:
        num, den = inch_text.split("/", 1)
        value = _fraction_value(num, den)
    else:
        value = float(inch_text)
    return -value if negative else value


def _without_whitespace(text: str) -> str:
    return "".join(text.split())


def _parse_imperial_elevation(elevation_text: str) -> float:
    text = elevation_text.strip()
    m = re.search(
        r"(?P<feet>-?\s*\d+)\s*[\'′]\s*(?:-?\s*)?(?P<inches>\d+(?:\s+\d+/\d+)?|\d+/\d+)\s*\"",
        text,
    )
    if m:
        feet_str = _without_whitespace(m.group("feet"))
        inches_str = m.group("inches").strip()
        negative = feet_str.startswith("-")
        feet_val = abs(int(feet_str))
        inches_val = _parse_fractional_inches_text(inches_str)
        total = feet_val * 12 + inches_val
        return -total if negative else total
    m = re.search(r"(?P<feet>-?\s*\d+)\s*[\'′]\b", text)
    if m:
        feet_str = _without_whitespace(m.group("feet"))
        feet_val = int(feet_str)
        return float(feet_val * 12)
    m = re.search(r"(?P<inches>-?\s*(?:\d+(?:\s+\d+/\d+)?|\d+/\d+))\s*\"", text)
    if m:
        inches_str = m.group("inches").strip()
        return _parse_fractional_inches_text(inches_str)
    return 0.0


def _parse_metric_elevation(elevation_text: str) -> float:
    text = elevation_text.strip().lower().replace(",", ".")
    m = re.search(
        r"(-?\s*\d+(?:\.\d+)?)\s*m\s*(?:and|\+)?\s*(-?\s*\d+(?:\.\d+)?)\s*cm", text
    )
    if m:
        meter_text = _without_whitespace(m.group(1))
        meter_part = float(meter_text)
        cm_part = float(_without_whitespace(m.group(2)))
        if meter_text.startswith("-"):
            return -(abs(meter_part) * 100.0 + abs(cm_part))
        return meter_part * 100.0 + cm_part
    m = re.search(r"(-?\s*\d+(?:\.\d+)?)\s*(?:m|meters?)\b", text)
    if m:
        meter_part = float(_without_whitespace(m.group(1)))
        return meter_part * 100.0
    m = re.search(r"(-?\s*\d+(?:\.\d+)?)\s*(?:cm|centimeters?)\b", text)
    if m:
        return float(_without_whitespace(m.group(1)))
    return 0.0


@lru_cache(maxsize=2048)
def extract_z_value_from_name(name: str) -> Tuple[float, bool]:
    if not name or "@" not in name:
        return (0.0, False)
    parts = parse_elevation(name)
    if not parts.value:
        return (0.0, False)
    elevation_text = parts.value.strip()
    if not _is_valid_elevation_text(elevation_text):
        return (0.0, False)
    is_top = parts.type == 0
    lowered = elevation_text.lower()
    has_imperial = (
        ("'" in elevation_text) or ("′" in elevation_text) or ('"' in elevation_text)
    )
    has_metric = "m" in lowered or "cm" in lowered
    if has_imperial and not has_metric:
        return (_parse_imperial_elevation(elevation_text), is_top)
    if has_metric and not has_imperial:
        cm_value = _parse_metric_elevation(elevation_text)
        return (cm_to_inches(cm_value), is_top)
    return (0.0, False)


def _format_metric_elevation(inches: float) -> str:
    cm = round(inches * 2.54, 2)
    if cm == int(cm):
        return f"{int(cm)} cm"
    return f"{cm:.2f} cm"


_ELEVATION_PATTERNS = (
    _IMPERIAL_FEET_INCHES,
    _IMPERIAL_FEET_ONLY,
    _IMPERIAL_INCHES_ONLY,
    _METRIC_M_PLUS_CM,
    _METRIC_METERS_ONLY,
    _METRIC_CM_ONLY,
)


def _is_full_elevation_text(text: str) -> bool:
    for p in _ELEVATION_PATTERNS:
        m = p.match(text)
        if m and m.end() == len(text):
            return True
    return False


def convert_elevation_in_name(name: str, metric: bool) -> str:
    if not name or "@" not in name:
        return name
    parts = parse_elevation(name)
    if not parts.value:
        return name
    elevation_text = parts.value.strip()
    if not _is_full_elevation_text(elevation_text):
        return name
    lowered = elevation_text.lower()
    has_imperial = (
        ("'" in elevation_text)
        or ("\u2032" in elevation_text)
        or ('"' in elevation_text)
    )
    has_metric = "m" in lowered or "cm" in lowered
    if has_imperial and not has_metric:
        inches = _parse_imperial_elevation(elevation_text)
    elif has_metric and not has_imperial:
        inches = cm_to_inches(_parse_metric_elevation(elevation_text))
    else:
        return name
    new_text = (
        _format_metric_elevation(inches)
        if metric
        else inches_to_display(inches, metric=False)
    )
    if not new_text:
        return name
    return reassemble_elevation(parts.base_name, parts.type, new_text)


def clear_caches() -> None:
    extract_z_value_from_name.cache_clear()
