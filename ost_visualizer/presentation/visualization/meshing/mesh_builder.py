from __future__ import annotations
from typing import Dict, List, Optional, Tuple, Union
from ....application.interfaces.i_color_service import IColorService
from ....application.interfaces.i_coordinate_transformer import ICoordinateTransformer
from ....application.interfaces.i_takeoff_domain_service import ITakeoffDomainService
from ....domain.dtos.mesh_metadata_dto import MeshMetadata
from ....domain.entities.config import Config
from ....domain.entities.condition import Condition
from ....domain.entities.takeoff import Takeoff
from ..core.boolean_operations import apply_boolean_operations
from ..core.mesh_generator import MeshData
from .mesh_factory import MeshFactory

Bounds = Tuple[float, float, float, float, float, float]


def calculate_mesh_bounds(meshes) -> Bounds:
    all_vertices = []
    for item in meshes:
        mesh = item[0] if isinstance(item, tuple) else item
        if mesh and mesh.vertices:
            all_vertices.extend(mesh.vertices)
    if not all_vertices:
        return (-1000, 1000, -1000, 1000, -10, 10)
    xs = [v[0] for v in all_vertices]
    ys = [v[1] for v in all_vertices]
    zs = [v[2] for v in all_vertices]
    return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


def _filter_valid_takeoffs(
    takeoffs: List[Takeoff], bid_conditions: Dict[str, Condition]
) -> List[Takeoff]:
    return [takeoff for takeoff in takeoffs if takeoff.condition_uid in bid_conditions]


def get_holes_for_takeoff(
    takeoff_uid: str, area_holes_map: Dict[str, List[Takeoff]]
) -> Optional[List[List[tuple]]]:
    child_takeoffs = area_holes_map.get(takeoff_uid, [])
    if not child_takeoffs:
        return None
    holes = []
    for child_takeoff in child_takeoffs:
        child_position = child_takeoff.position
        if len(child_position) < 6:
            continue
        hole_vertices = [
            (child_position[i], child_position[i + 1])
            for i in range(0, len(child_position), 2)
            if i + 1 < len(child_position)
        ]
        if len(hole_vertices) >= 3:
            holes.append(hole_vertices)
    return holes if holes else None


def _create_mesh(
    takeoff: Takeoff,
    condition: Condition,
    area_holes_map: Dict[str, List[Takeoff]],
    mesh_factory: MeshFactory,
) -> Optional[MeshData]:
    takeoff_uid = takeoff.uid
    holes = get_holes_for_takeoff(takeoff_uid, area_holes_map)
    return mesh_factory.create_mesh_for_takeoff(takeoff, condition, holes)


def process_takeoffs_to_meshes(
    bid_conditions: Dict[str, Condition],
    bid_takeoffs: List[Takeoff],
    coord_system: ICoordinateTransformer,
    color_service: IColorService,
    takeoff_service: ITakeoffDomainService,
    page_area_selections: Optional[Dict[str, Optional[str]]] = None,
    **config_options,
) -> Tuple[List[MeshData], Dict[str, Union[Dict[str, object], str]], Bounds]:
    if not bid_takeoffs:
        return [], {}, calculate_mesh_bounds([])
    mesh_factory = MeshFactory(coord_system)
    display_mode = config_options.get("display_mode", Config.DISPLAY_MODE_SOLID)
    grayscale_enabled = config_options.get("grayscale_enabled", True)
    hierarchy_map, color_map = color_service.get_color_mapping(
        bid_conditions, bid_takeoffs, display_mode, grayscale_enabled
    )
    exportable_takeoffs, area_holes_map = (
        takeoff_service.group_area_takeoffs_with_holes(bid_takeoffs, bid_conditions)
    )
    takeoffs_by_type = takeoff_service.group_takeoffs_by_type(
        bid_conditions, exportable_takeoffs
    )
    filtered_area_takeoffs = takeoffs_by_type.get(1, [])
    meshes_with_metadata: List[Tuple[MeshData, MeshMetadata]] = []
    mesh_colors_temp: Dict[int, Tuple[str, float]] = {}
    temp_idx = 0
    processing_order = [
        (1, filtered_area_takeoffs),
        (0, takeoffs_by_type.get(0, [])),
        (2, takeoffs_by_type.get(2, [])),
        (3, takeoffs_by_type.get(3, [])),
    ]
    for _, type_takeoffs in processing_order:
        if not type_takeoffs:
            continue
        valid_takeoffs = _filter_valid_takeoffs(type_takeoffs, bid_conditions)
        for takeoff in valid_takeoffs:
            condition_uid = takeoff.condition_uid
            condition = bid_conditions[condition_uid]
            color_hex, opacity = color_service.get_color_for_takeoff(
                takeoff, condition, color_map, display_mode, page_area_selections
            )
            mesh = _create_mesh(takeoff, condition, area_holes_map, mesh_factory)
            if mesh and mesh.vertices and mesh.faces:
                is_negative = takeoff.is_negative
                metadata: MeshMetadata = {
                    "IsNegativeQuantity": is_negative,
                    "condition_type": condition.condition_type,
                    "color": color_hex,
                    "opacity": opacity,
                    "condition_uid": condition_uid,
                    "takeoff_uid": takeoff.uid,
                }
                meshes_with_metadata.append((mesh, metadata))
                mesh_colors_temp[temp_idx] = (color_hex, opacity)
                temp_idx += 1
    meshes_with_metadata = apply_boolean_operations(meshes_with_metadata)
    meshes: List[MeshData] = []
    mesh_colors: Dict[str, Union[Dict[str, object], str]] = {}
    for mesh_idx, (mesh, metadata) in enumerate(meshes_with_metadata):
        meshes.append(mesh)
        mesh_colors[f"mesh_{mesh_idx}"] = {
            "color": metadata["color"],
            "opacity": metadata["opacity"],
            "condition_uid": metadata.get("condition_uid", ""),
            "takeoff_uid": metadata.get("takeoff_uid", ""),
        }
    bounds = calculate_mesh_bounds(meshes)
    return meshes, mesh_colors, bounds
