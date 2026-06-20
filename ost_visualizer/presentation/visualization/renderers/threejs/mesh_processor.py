from typing import Dict, List, Optional, Tuple
from .....application.interfaces.i_color_service import IColorService
from .....application.interfaces.i_coordinate_transformer import ICoordinateTransformer
from .....application.interfaces.i_takeoff_domain_service import ITakeoffDomainService
from .....domain.dtos.mesh_metadata_dto import MeshMetadata
from .....domain.entities.config import Config
from .....domain.entities.condition import Condition
from .....domain.entities.takeoff import Takeoff
from ...core.boolean_operations import apply_boolean_operations
from ...core.mesh_generator import MeshData
from ...meshing.mesh_builder import calculate_mesh_bounds, get_holes_for_takeoff
from ...meshing.mesh_factory import MeshFactory

Bounds = Tuple[float, float, float, float, float, float]


def process_meshes_for_threejs(
    bid_conditions: Dict[str, Condition],
    bid_takeoffs: List[Takeoff],
    coord_system: ICoordinateTransformer,
    color_service: IColorService,
    takeoff_service: ITakeoffDomainService,
    color_mode: str = Config.COLOR_MODE_SOLID,
    grayscale_enabled: bool = True,
    page_area_selections: Optional[Dict] = None,
) -> Tuple[List[Tuple[MeshData, MeshMetadata]], Bounds]:
    hierarchy_map, color_map = color_service.get_color_mapping(
        bid_conditions, bid_takeoffs, color_mode, grayscale_enabled
    )
    exportable_takeoffs, area_holes_map = (
        takeoff_service.group_area_takeoffs_with_holes(bid_takeoffs, bid_conditions)
    )
    takeoffs_by_type = takeoff_service.group_takeoffs_by_type(
        bid_conditions, exportable_takeoffs
    )
    mesh_factory = MeshFactory(coord_system)
    meshes_with_metadata: List[Tuple[MeshData, MeshMetadata]] = []
    for type_id in [1, 0, 2, 3]:
        type_takeoffs = takeoffs_by_type.get(type_id, [])
        for takeoff in type_takeoffs:
            condition_uid = takeoff.condition_uid
            if condition_uid not in bid_conditions:
                continue
            condition = bid_conditions[condition_uid]
            holes = get_holes_for_takeoff(takeoff.uid, area_holes_map)
            mesh_data = mesh_factory.create_mesh_for_takeoff(takeoff, condition, holes)
            if mesh_data and mesh_data.vertices and mesh_data.faces:
                color_hex, opacity = color_service.get_color_for_takeoff(
                    takeoff, condition, color_map, color_mode, page_area_selections
                )
                metadata: MeshMetadata = {
                    "IsNegativeQuantity": takeoff.is_negative,
                    "color": color_hex,
                    "opacity": opacity,
                    "name": (
                        condition.name if condition.name else f"Element {takeoff.uid}"
                    ),
                    "cdn_type": (
                        condition.cdn_type_name
                        if condition.cdn_type_name
                        else "Unknown"
                    ),
                }
                meshes_with_metadata.append((mesh_data, metadata))
    processed_meshes = apply_boolean_operations(meshes_with_metadata)
    bounds = calculate_mesh_bounds(processed_meshes)
    return processed_meshes, bounds
