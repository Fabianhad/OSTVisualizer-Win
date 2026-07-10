from dataclasses import dataclass
from typing import Optional, Sequence

PAGE_PLANE_FLOOR_OFFSET = 0.01


@dataclass(frozen=True)
class PagePlaneTransform:
    plane_x: float
    plane_y: float
    plane_z: float
    plane_width: float
    plane_height: float
    flip_u: bool
    flip_v: bool


def threejs_page_plane_transform(
    page_width: float,
    page_height: float,
    scene_bounds: Optional[dict],
) -> Optional[PagePlaneTransform]:
    if page_width <= 0.0 or page_height <= 0.0:
        return None
    floor_y = _scene_bounds_min_y(scene_bounds) - PAGE_PLANE_FLOOR_OFFSET
    return PagePlaneTransform(
        plane_x=-page_width / 2.0,
        plane_y=floor_y,
        plane_z=-page_height / 2.0,
        plane_width=page_width,
        plane_height=page_height,
        flip_u=True,
        flip_v=True,
    )


def native_page_plane_transform(
    page_width: float,
    page_height: float,
    mesh_bounds: Optional[Sequence[float]],
) -> Optional[PagePlaneTransform]:
    if page_width <= 0.0 or page_height <= 0.0:
        return None
    floor_z = _native_bounds_min_z(mesh_bounds) - PAGE_PLANE_FLOOR_OFFSET
    return PagePlaneTransform(
        plane_x=-page_width / 2.0,
        plane_y=page_height / 2.0,
        plane_z=floor_z,
        plane_width=page_width,
        plane_height=page_height,
        flip_u=True,
        flip_v=False,
    )


def _scene_bounds_min_y(scene_bounds: Optional[dict]) -> float:
    if not scene_bounds:
        return 0.0
    min_values = scene_bounds.get("min")
    if not min_values or len(min_values) < 2:
        return 0.0
    try:
        return float(min_values[1])
    except (TypeError, ValueError):
        return 0.0


def _native_bounds_min_z(mesh_bounds: Optional[Sequence[float]]) -> float:
    if not mesh_bounds or len(mesh_bounds) < 5:
        return 0.0
    try:
        return float(mesh_bounds[4])
    except (TypeError, ValueError):
        return 0.0
