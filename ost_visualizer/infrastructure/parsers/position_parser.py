from functools import lru_cache
from typing import Tuple
from ...domain.services.dimension_format_service import inches_to_display
from ...domain.services.elevation import parse_elevation, reassemble_elevation
from ...domain.services.elevation_text import (
    _parse_imperial_elevation,
    _parse_metric_elevation,
    cm_to_inches,
    elevation_text_inches,
)
from ...domain.services.elevation_text import (
    IMPERIAL_FEET_INCHES as _IMPERIAL_FEET_INCHES,
    IMPERIAL_FEET_ONLY as _IMPERIAL_FEET_ONLY,
    IMPERIAL_INCHES_ONLY as _IMPERIAL_INCHES_ONLY,
    METRIC_CM_ONLY as _METRIC_CM_ONLY,
    METRIC_METERS_ONLY as _METRIC_METERS_ONLY,
    METRIC_M_PLUS_CM as _METRIC_M_PLUS_CM,
)


@lru_cache(maxsize=2048)
def extract_z_value_from_name(name: str) -> Tuple[float, bool]:
    if not name or "@" not in name:
        return (0.0, False)
    parts = parse_elevation(name)
    if not parts.value:
        return (0.0, False)
    z_value = elevation_text_inches(parts.value)
    if z_value is None:
        return (0.0, False)
    return (z_value, parts.type == 0)


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
