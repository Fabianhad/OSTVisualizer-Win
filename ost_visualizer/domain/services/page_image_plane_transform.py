import math
from dataclasses import dataclass
from typing import Iterable, Optional

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


def resolve_page_floor_elevations(
    page_vertices: Iterable[tuple[str, Iterable[float]]],
) -> dict[str, float]:
    elevations: dict[str, float] = {}
    for page_uid_value, z_values in page_vertices:
        page_uid = str(page_uid_value)
        if not page_uid:
            continue
        for z_value in z_values:
            elevation = float(z_value)
            if not math.isfinite(elevation):
                continue
            current = elevations.get(page_uid)
            if current is None or elevation < current:
                elevations[page_uid] = elevation
    return elevations


def threejs_page_plane_transform(
    page_width: float,
    page_height: float,
    page_floor_elevation: float,
) -> Optional[PagePlaneTransform]:
    if page_width <= 0.0 or page_height <= 0.0:
        return None
    return PagePlaneTransform(
        plane_x=-page_width / 2.0,
        plane_y=float(page_floor_elevation) - PAGE_PLANE_FLOOR_OFFSET,
        plane_z=-page_height / 2.0,
        plane_width=page_width,
        plane_height=page_height,
        flip_u=True,
        flip_v=True,
    )


def native_page_plane_transform(
    page_width: float,
    page_height: float,
    page_floor_elevation: float,
) -> Optional[PagePlaneTransform]:
    if page_width <= 0.0 or page_height <= 0.0:
        return None
    return PagePlaneTransform(
        plane_x=-page_width / 2.0,
        plane_y=page_height / 2.0,
        plane_z=float(page_floor_elevation) - PAGE_PLANE_FLOOR_OFFSET,
        plane_width=page_width,
        plane_height=page_height,
        flip_u=True,
        flip_v=False,
    )
