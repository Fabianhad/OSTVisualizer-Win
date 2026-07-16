import re
from functools import lru_cache
from typing import Tuple
from ...domain.services.dimension_format_service import inches_to_display
from ...domain.services.elevation import parse_elevation, reassemble_elevation

_IMPERIAL_FEET_INCHES = re.compile(
    r"^-?\s*\d+\s*[\'′]\s*(?:-?\s*)?\s*\d+(?:\s+\d+/\d+)?\s*\"", re.IGNORECASE
)
_IMPERIAL_FEET_ONLY = re.compile(r"^-?\s*\d+\s*[\'′]\b", re.IGNORECASE)
_IMPERIAL_INCHES_ONLY = re.compile(
    r"^-?\s*(?:\d+(?:\s+\d+/\d+)?|\d+/\d+)\s*\"", re.IGNORECASE
)
_METRIC_M_PLUS_CM = re.compile(
    r"^-?\s*\d+(?:[\.,]\d+)?\s*m\s*(?:and|\+)?\s*-?\s*\d+(?:[\.,]\d+)?\s*cm",
    re.IGNORECASE,
)
_METRIC_METERS_ONLY = re.compile(
    r"^-?\s*\d+(?:[\.,]\d+)?\s*(?:m|meters?)\b", re.IGNORECASE
)
_METRIC_CM_ONLY = re.compile(
    r"^-?\s*\d+(?:[\.,]\d+)?\s*(?:cm|centimeters?)\b", re.IGNORECASE
)


def _is_valid_elevation_text(text: str) -> bool:
    return any(
        p.match(text)
        for p in (
            _IMPERIAL_FEET_INCHES,
            _IMPERIAL_FEET_ONLY,
            _IMPERIAL_INCHES_ONLY,
            _METRIC_M_PLUS_CM,
            _METRIC_METERS_ONLY,
            _METRIC_CM_ONLY,
        )
    )


def cm_to_inches(cm: float) -> float:
    return cm / 2.54


def _parse_fractional_inches_text(inch_text: str) -> float:
    inch_text = inch_text.strip()
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
            frac = float(num) / float(den)
        else:
            frac = float(frac_part)
        value = whole + frac
    elif "/" in inch_text:
        num, den = inch_text.split("/", 1)
        value = float(num) / float(den)
    else:
        value = float(inch_text)
    return -value if negative else value


def _parse_imperial_elevation(elevation_text: str) -> float:
    text = elevation_text.strip()
    m = re.search(
        r"(?P<feet>-?\d+)\s*[\'′]\s*(?:-?\s*)?(?P<inches>\d+(?:\s+\d+/\d+)?|\d+/\d+)\s*\"",
        text,
    )
    if m:
        feet_str = m.group("feet").strip()
        inches_str = m.group("inches").strip()
        negative = feet_str.startswith("-")
        feet_val = abs(int(feet_str))
        inches_val = _parse_fractional_inches_text(inches_str)
        total = feet_val * 12 + inches_val
        return -total if negative else total
    m = re.search(r"(?P<feet>-?\d+)\s*[\'′]\b", text)
    if m:
        feet_str = m.group("feet").strip()
        feet_val = int(feet_str)
        return float(feet_val * 12)
    m = re.search(r"(?P<inches>-?\s*(?:\d+(?:\s+\d+/\d+)?|\d+/\d+))\s*\"", text)
    if m:
        inches_str = m.group("inches").replace(" ", " ").strip()
        return _parse_fractional_inches_text(inches_str)
    return 0.0


def _parse_metric_elevation(elevation_text: str) -> float:
    text = elevation_text.strip().lower().replace(",", ".")
    m = re.search(
        r"(-?\s*\d+(?:\.\d+)?)\s*m\s*(?:and|\+)?\s*(-?\s*\d+(?:\.\d+)?)\s*cm", text
    )
    if m:
        meter_part = float(m.group(1).strip())
        cm_part = float(m.group(2).strip())
        return meter_part * 100.0 + cm_part
    m = re.search(r"(-?\s*\d+(?:\.\d+)?)\s*(?:m|meters?)\b", text)
    if m:
        meter_part = float(m.group(1).strip())
        return meter_part * 100.0
    m = re.search(r"(-?\s*\d+(?:\.\d+)?)\s*(?:cm|centimeters?)\b", text)
    if m:
        return float(m.group(1).strip())
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
    cm = inches * 2.54
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
