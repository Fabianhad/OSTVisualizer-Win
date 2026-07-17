from math import isfinite
from ..entities.condition import Condition
from ..entities.elevation_callout import (
    DEFAULT_ELEVATION_CALLOUT_SETTINGS,
    ElevationCallout,
    ElevationCalloutSettings,
    Point2D,
)
from ..entities.takeoff import Takeoff
from .condition_quantity_service import compute_takeoff_cubic_yards
from .elevation import format_structural_elevation, resolve_condition_elevation_bounds
from .uom_service import UOM_CUBIC_YARDS, get_uom_label


def resolve_elevation_callout(
    condition: Condition,
    takeoff: Takeoff,
    hole_takeoffs: list[Takeoff],
    outer_ring: tuple[Point2D, ...],
    settings: ElevationCalloutSettings = DEFAULT_ELEVATION_CALLOUT_SETTINGS,
) -> ElevationCallout | None:
    if not settings.has_content:
        return None
    elevations = resolve_condition_elevation_bounds(condition)
    center = _outer_ring_bounds_center(outer_ring)
    if elevations is None or center is None:
        return None
    lines = []
    if settings.include_condition:
        lines.append(elevations.base_name)
    if settings.include_top:
        lines.append(format_structural_elevation(elevations.top))
    if settings.include_bottom:
        lines.append(format_structural_elevation(elevations.bottom))
    if settings.include_cubic_yards:
        cubic_yards = compute_takeoff_cubic_yards(condition, takeoff, hole_takeoffs)
        lines.append(f"{cubic_yards:.2f} {get_uom_label(UOM_CUBIC_YARDS)}")
    return ElevationCallout(
        x=center[0],
        y=center[1],
        lines=tuple(lines),
    )


def _outer_ring_bounds_center(
    outer_ring: tuple[tuple[float, float], ...],
) -> tuple[float, float] | None:
    points = [
        (float(point[0]), float(point[1]))
        for point in outer_ring
        if isfinite(point[0]) and isfinite(point[1])
    ]
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
