from __future__ import annotations
import base64
import logging
from typing import Iterable, List, Optional, Tuple
from .....application.dtos.scene_data_dto import (
    SceneTowerCranePlacement,
    SceneTowerCranes,
)
from .....domain.dtos.mesh_metadata_dto import MeshMetadata
from .....domain.dtos.tower_crane_placement_dto import (
    INCHES_PER_METRE,
    TowerCranePlacement,
)
from ...assets.tower_crane_asset import (
    TOWER_CRANE_CREDIT,
    glb_local_bounds,
    native_instance_corners,
    read_tower_crane_model,
)
from ...core.mesh_generator import MeshData
from ...services.color_service import parse_hex_color

logger = logging.getLogger(__name__)


def _to_export(point: Tuple[float, float, float]) -> List[float]:
    x, y, z = point
    return [float(x), float(z), float(-y)]


def build_tower_crane_scene_data(
    processed_meshes: Iterable[Tuple[MeshData, MeshMetadata]],
) -> Optional[SceneTowerCranes]:
    cranes: List[Tuple[TowerCranePlacement, MeshMetadata]] = []
    for _mesh, metadata in processed_meshes:
        crane = metadata.get("tower_crane")
        if isinstance(crane, TowerCranePlacement):
            cranes.append((crane, metadata))
    if not cranes:
        return None
    try:
        model = read_tower_crane_model()
    except OSError:
        logger.warning("Tower crane model is missing; the export shows no cranes")
        return None
    local_bounds = glb_local_bounds(model)
    placements: List[SceneTowerCranePlacement] = []
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for crane, metadata in cranes:
        tint: List[float] = []
        if crane.inactive:
            tint = [float(c) for c in parse_hex_color(str(metadata.get("color", "")))]
        placements.append(
            {
                "position": _to_export((crane.x, crane.y, crane.z)),
                "rotation_y": float(crane.rotation),
                "tint": tint,
                "takeoff_uid": crane.takeoff_uid,
                "condition_uid": crane.condition_uid,
                "layer_uid": str(metadata.get("layer_uid", "") or ""),
                "area_uid": str(metadata.get("area_uid", "") or ""),
                "page_uid": crane.page_uid,
            }
        )
        if local_bounds is not None:
            for corner in native_instance_corners(
                local_bounds,
                INCHES_PER_METRE,
                crane.x,
                crane.y,
                crane.z,
                crane.rotation,
            ):
                exported = _to_export(corner)
                for k in range(3):
                    lo[k] = min(lo[k], exported[k])
                    hi[k] = max(hi[k], exported[k])
    data: SceneTowerCranes = {
        "model_base64": base64.b64encode(model).decode("ascii"),
        "units_per_metre": INCHES_PER_METRE,
        "credit": dict(TOWER_CRANE_CREDIT),
        "placements": placements,
        "render_bounds": (
            {"min": lo, "max": hi} if lo[0] <= hi[0] else {"min": [], "max": []}
        ),
    }
    return data
