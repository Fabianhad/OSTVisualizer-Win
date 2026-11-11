from __future__ import annotations
import math
from typing import Optional
from ....application.interfaces.i_coordinate_transformer import ICoordinateTransformer
from ....domain.dtos.tower_crane_placement_dto import TowerCranePlacement
from ....domain.entities.condition import Condition
from ....domain.entities.takeoff import Takeoff
from ..assets.tower_crane_models import tower_crane_catalog
from ..core.geometry.takeoff_geometry import point_takeoff_vertical_extent


def _page_transform_active(coord_system: Optional[ICoordinateTransformer]) -> bool:
    if coord_system is None:
        return False
    page_info = coord_system.page_info
    return bool(
        int(page_info.get("rotation", 0))
        or bool(page_info.get("flip_x", False))
        or bool(page_info.get("flip_y", False))
    )


def tower_crane_placement(
    takeoff: Takeoff,
    condition: Condition,
    coord_system: ICoordinateTransformer,
    page_coord_system: Optional[ICoordinateTransformer] = None,
    *,
    inactive: bool = False,
) -> Optional[TowerCranePlacement]:
    spec = condition.tower_crane_spec(tower_crane_catalog())
    if spec is None or takeoff.is_negative:
        return None
    position = takeoff.position
    if not position or len(position) < 2:
        return None
    x, y = coord_system.transform_to_3d(position[0], position[1])
    z_offset, height = point_takeoff_vertical_extent(condition)
    z = coord_system.ost_to_real_units(z_offset) + coord_system.ost_to_real_units(
        height
    )
    raw_rotation = float(takeoff.rotation or 0.0)
    rotation = -raw_rotation if math.isfinite(raw_rotation) else 0.0
    if _page_transform_active(page_coord_system):
        ahead_x = x + math.cos(rotation)
        ahead_y = y + math.sin(rotation)
        x, y = page_coord_system.transform_to_3d(-x, y)
        ahead_x, ahead_y = page_coord_system.transform_to_3d(-ahead_x, ahead_y)
        rotation = math.atan2(ahead_y - y, ahead_x - x)
    if not all(math.isfinite(value) for value in (x, y, z, rotation)):
        return None
    return TowerCranePlacement(
        takeoff_uid=str(takeoff.uid),
        condition_uid=str(takeoff.condition_uid),
        page_uid=str(takeoff.page_uid or ""),
        x=float(x),
        y=float(y),
        z=float(z),
        rotation=float(rotation),
        inactive=bool(inactive),
        spec=spec,
    )
