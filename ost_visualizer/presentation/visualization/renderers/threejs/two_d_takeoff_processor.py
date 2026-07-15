from math import isfinite
from typing import Dict, List, Optional, Tuple
from .....application.dtos.scene_data_dto import (
    SceneElevationCalloutEntry,
    SceneTakeoff2DEntry,
)
from .....application.interfaces.i_color_service import IColorService
from .....application.interfaces.i_takeoff_domain_service import ITakeoffDomainService
from .....domain.dtos.page_render_info_dto import PageRenderInfo
from .....domain.entities.area import area_group_uid
from .....domain.entities.condition import Condition
from .....domain.entities.config import Config
from .....domain.entities.takeoff import Takeoff
from .....domain.services.condition_quantity_service import (
    compute_takeoff_cubic_yards,
)
from .....domain.services.coordinate_transformation_service import OSTCoordinateSystem
from .....domain.services.elevation import (
    format_structural_elevation,
    resolve_condition_elevation_bounds,
)
from .....domain.services.uom_service import UOM_CUBIC_YARDS, get_uom_label
from ...core.geometry.ost_linear_geom import (
    gen_curve_pts,
    gen_thick_curve_offsets,
    proc_curved_pos,
)
from ...core.geometry.takeoff_geometry import (
    compute_count_vertices,
    compute_curved_linear_vertices,
    compute_straight_linear_vertices,
)
from ...services.color_service import int_to_hex

Point = Tuple[float, float]
Ring = List[List[float]]


def build_elevation_callouts_for_threejs(
    takeoffs_2d: List[SceneTakeoff2DEntry],
    bid_conditions: Dict[str, Condition],
    bid_takeoffs: List[Takeoff],
    takeoff_service: ITakeoffDomainService,
) -> List[SceneElevationCalloutEntry]:
    _exportable_takeoffs, area_holes_map = (
        takeoff_service.group_area_takeoffs_with_holes(bid_takeoffs, bid_conditions)
    )
    takeoffs_by_uid = {takeoff.uid: takeoff for takeoff in bid_takeoffs}
    callouts: List[SceneElevationCalloutEntry] = []
    for entry in takeoffs_2d:
        condition = bid_conditions.get(entry["condition_uid"])
        takeoff = takeoffs_by_uid.get(entry["takeoff_uid"])
        if condition is None or takeoff is None:
            continue
        elevations = resolve_condition_elevation_bounds(condition)
        center = _outer_ring_bounds_center(entry["rings"])
        if elevations is None or center is None:
            continue
        cubic_yards = compute_takeoff_cubic_yards(
            condition,
            takeoff,
            area_holes_map.get(takeoff.uid, []),
        )
        callouts.append(
            {
                "takeoff_uid": entry["takeoff_uid"],
                "page_uid": entry["page_uid"],
                "condition_uid": entry["condition_uid"],
                "area_uid": entry["area_uid"],
                "layer_uid": entry["layer_uid"],
                "visible": entry["visible"],
                "x": center[0],
                "y": center[1],
                "condition_label": elevations.base_name,
                "top_label": format_structural_elevation(elevations.top),
                "bottom_label": format_structural_elevation(elevations.bottom),
                "quantity_label": _format_cubic_yards(cubic_yards),
            }
        )
    return callouts


def _outer_ring_bounds_center(rings: List[Ring]) -> Optional[Point]:
    if not rings or not rings[0]:
        return None
    points: List[Point] = []
    for point in rings[0]:
        if len(point) < 2:
            continue
        x = float(point[0])
        y = float(point[1])
        if isfinite(x) and isfinite(y):
            points.append((x, y))
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)


def _format_cubic_yards(value: float) -> str:
    return f"{value:.2f} {get_uom_label(UOM_CUBIC_YARDS)}"


def process_takeoffs_2d_for_threejs(
    bid_conditions: Dict[str, Condition],
    bid_takeoffs: List[Takeoff],
    color_service: IColorService,
    takeoff_service: ITakeoffDomainService,
    page_info: PageRenderInfo,
    display_mode: str = Config.DISPLAY_MODE_SOLID,
    grayscale_enabled: bool = True,
    page_area_selections: Optional[Dict[str, Optional[str]]] = None,
) -> List[SceneTakeoff2DEntry]:
    _hierarchy_map, color_map = color_service.get_color_mapping(
        bid_conditions, bid_takeoffs, display_mode, grayscale_enabled
    )
    coord_system = OSTCoordinateSystem(page_info)
    exportable_takeoffs, area_holes_map = (
        takeoff_service.group_area_takeoffs_with_holes(bid_takeoffs, bid_conditions)
    )
    entries: List[SceneTakeoff2DEntry] = []
    for takeoff in exportable_takeoffs:
        condition = bid_conditions.get(takeoff.condition_uid)
        if condition is None:
            continue
        rings = _build_takeoff_rings(takeoff, condition, area_holes_map, coord_system)
        if not rings:
            continue
        color_hex, opacity = color_service.get_2d_color_for_takeoff(
            takeoff, condition, color_map, page_area_selections
        )
        entries.append(
            {
                "takeoff_uid": str(takeoff.uid or ""),
                "page_uid": str(takeoff.page_uid or ""),
                "condition_uid": str(takeoff.condition_uid or ""),
                "area_uid": area_group_uid(takeoff.area_uid),
                "layer_uid": str(condition.layer_uid or ""),
                "name": condition.name if condition.name else f"Takeoff {takeoff.uid}",
                "visible": True,
                "kind": _condition_kind(condition),
                "color": color_hex or int_to_hex(condition.color_fill or 0),
                "opacity": float(opacity),
                "rings": rings,
                "is_negative": bool(takeoff.is_negative),
            }
        )
    return entries


def _build_takeoff_rings(
    takeoff: Takeoff,
    condition: Condition,
    area_holes_map: Dict[str, List[Takeoff]],
    coord_system: OSTCoordinateSystem,
) -> List[Ring]:
    position = OSTCoordinateSystem.parse_position(takeoff.position)
    if len(position) < 2:
        return []
    if condition.is_area:
        outer_ring = _area_ring(position, coord_system)
        if not outer_ring:
            return []
        rings = [outer_ring]
        for hole_takeoff in area_holes_map.get(takeoff.uid, []):
            hole_position = OSTCoordinateSystem.parse_position(hole_takeoff.position)
            hole_ring = _area_ring(hole_position, coord_system)
            if hole_ring:
                rings.append(hole_ring)
        return rings
    if condition.is_linear:
        ring = _linear_ring(takeoff, condition, position, coord_system)
        return [ring] if ring else []
    if condition.is_count or condition.is_attachment:
        ring = _count_ring(takeoff, condition, position, coord_system)
        return [ring] if ring else []
    return []


def _area_ring(position: List[float], coord_system: OSTCoordinateSystem) -> Ring:
    if len(position) < 6:
        return []
    points = _transform_vertices_to_points(position, coord_system)
    return _points_to_ring(points)


def _linear_ring(
    takeoff: Takeoff,
    condition: Condition,
    position: List[float],
    coord_system: OSTCoordinateSystem,
) -> Ring:
    if len(position) < 4:
        return []
    thickness = _ost_to_pdf_points(
        condition.thickness if condition.thickness else 1.0, coord_system
    )
    thickness = max(thickness, 2.0)
    if takeoff.curve >= 0 and len(position) >= 6:
        rx1, ry1, rx2, ry2, rcx, rcy = position[:6]
        rx1, ry1, rx2, ry2, rcx, rcy = proc_curved_pos(
            position, rx1, ry1, rx2, ry2, rcx, rcy
        )
        points = _transform_vertices_to_points(
            [rx1, ry1, rx2, ry2, rcx, rcy], coord_system
        )
        if len(points) < 3:
            return []
        vertices = compute_curved_linear_vertices(
            points[0][0],
            points[0][1],
            points[1][0],
            points[1][1],
            points[2][0],
            points[2][1],
            gen_curve_pts,
            gen_thick_curve_offsets,
            thickness,
        )
    else:
        points = _transform_vertices_to_points(position[:4], coord_system)
        if len(points) < 2:
            return []
        vertices = compute_straight_linear_vertices(
            points[0][0], points[0][1], points[1][0], points[1][1], thickness
        )
    return _points_to_ring(vertices or [])


def _count_ring(
    takeoff: Takeoff,
    condition: Condition,
    position: List[float],
    coord_system: OSTCoordinateSystem,
) -> Ring:
    center_points = _transform_vertices_to_points(position[:2], coord_system)
    if not center_points:
        return []
    cx, cy = center_points[0]
    width_ost = max(condition.width if condition.width else 1.0, 1.0)
    if condition.shape in (0, 1):
        depth_ost = width_ost
    else:
        depth_ost = max(condition.depth if condition.depth else width_ost, 1.0)
    if condition.is_count:
        scale = max(condition.display_size, 0.1) / 100.0
        width_ost *= scale
        depth_ost *= scale
    width = _ost_to_pdf_points(width_ost, coord_system)
    depth = _ost_to_pdf_points(depth_ost, coord_system)
    min_dimension = min(width, depth)
    if 0 < min_dimension < 8.0:
        scale = 8.0 / min_dimension
        width *= scale
        depth *= scale
    vertices = compute_count_vertices(
        cx, cy, condition.shape, width, depth, takeoff.rotation
    )
    return _points_to_ring(vertices)


def _points_to_ring(points: List[Point]) -> Ring:
    if len(points) < 3:
        return []
    return [[float(x), float(y)] for x, y in points]


def _transform_vertices_to_points(
    position: List[float], coord_system: OSTCoordinateSystem
) -> List[Point]:
    transformed = coord_system.transform_vertices_to_2d(position)
    return [
        (float(transformed[index]), float(transformed[index + 1]))
        for index in range(0, len(transformed) - 1, 2)
    ]


def _ost_to_pdf_points(value: float, coord_system: OSTCoordinateSystem) -> float:
    return coord_system.ost_to_pdf_points(float(value))


def _condition_kind(condition: Condition) -> str:
    if condition.is_area:
        return "area"
    if condition.is_linear:
        return "linear"
    if condition.is_count:
        return "count"
    if condition.is_attachment:
        return "attachment"
    return "unknown"
