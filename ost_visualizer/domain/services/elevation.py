from dataclasses import dataclass
from math import isfinite
from typing import Optional
from ..entities.condition import Condition
from .dimension_format_service import inches_to_display


@dataclass
class ElevationParts:
    base_name: str = ""
    type: int = 0
    value: str = ""


@dataclass(frozen=True)
class ConditionElevationBounds:
    base_name: str
    top: float
    bottom: float


def parse_elevation(name: str) -> ElevationParts:
    parts = ElevationParts()
    if not name:
        return parts
    pos_t = name.rfind(" @T")
    pos_b = name.rfind(" @B")
    pos = -1
    marker_len = 3
    if pos_t != -1 and pos_b != -1:
        pos = max(pos_t, pos_b)
        parts.type = 1 if pos == pos_b else 0
    elif pos_t != -1:
        pos = pos_t
        parts.type = 0
    elif pos_b != -1:
        pos = pos_b
        parts.type = 1
    if pos == -1:
        pos_at = name.rfind(" @ ")
        if pos_at == -1:
            pos_at = name.rfind(" @")
        if pos_at != -1:
            pos = pos_at
            parts.type = 1
            marker_len = 2
    if pos == -1:
        parts.base_name = name
        parts.value = ""
        return parts
    parts.base_name = name[:pos]
    val_start = pos + marker_len
    if val_start < len(name) and name[val_start] == " ":
        val_start += 1
    parts.value = name[val_start:] if val_start < len(name) else ""
    return parts


def reassemble_elevation(base_name: str, elev_type: int, value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        return base_name
    tag = " @T " if elev_type == 0 else " @B "
    return base_name + tag + trimmed


def format_structural_elevation(value: float) -> str:
    sign = "-" if value < 0.0 else ""
    display = inches_to_display(abs(value), metric=False) or '0"'
    if "'" in display:
        feet, inches = display.split("'", 1)
        return f"{sign}{feet}' - {inches.strip()}"
    return f"{sign}0' - {display}"


def resolve_condition_elevation_bounds(
    condition: Condition,
) -> Optional[ConditionElevationBounds]:
    parts = parse_elevation(condition.name)
    if not parts.value.strip():
        return None
    is_top = bool(condition.is_top)
    if (parts.type == 0) != is_top:
        return None
    reference = float(condition.z_value)
    vertical_size = float(
        condition.thickness if condition.is_area else condition.height
    )
    if not isfinite(reference) or not isfinite(vertical_size) or vertical_size <= 0.0:
        return None
    if is_top:
        return ConditionElevationBounds(
            base_name=parts.base_name.strip(),
            top=reference,
            bottom=reference - vertical_size,
        )
    return ConditionElevationBounds(
        base_name=parts.base_name.strip(),
        top=reference + vertical_size,
        bottom=reference,
    )
