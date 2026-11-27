import logging
from typing import List, Optional, Tuple
from ....domain.dtos.mesh_metadata_dto import MeshMetadata
from . import ost_geometry
from .mesh_generator import MeshData
from ...texts import (
    BOOLEAN_OPERATIONS_LOG_BOOLEAN_OPERATIONS_FAILED_RETURNING_POSITIVE_MESHES,
)

logger = logging.getLogger(__name__)


def _flip_manifold_faces(args: dict) -> dict:
    args["faces"] = [[f[0], f[2], f[1]] for f in args["faces"]]
    return args


def _dict_to_meshdata(args: dict, original_metadata: Optional[dict] = None) -> MeshData:
    metadata = original_metadata.copy() if original_metadata else {}
    metadata.update(args.get("metadata", {}))
    return MeshData(
        vertices=args["vertices"],
        faces=args["faces"],
        edges=args.get("edges", []),
        metadata=metadata,
    )


def _require_condition_types(
    meshes_with_metadata: List[Tuple[MeshData, MeshMetadata]],
) -> None:
    for _, meta in meshes_with_metadata:
        if "condition_type" not in meta:
            raise ValueError(
                "Boolean operations need condition_type for takeoff "
                f"{meta.get('takeoff_uid', '')}"
            )


def _bounds(mesh: MeshData) -> Tuple[Tuple[float, ...], Tuple[float, ...]]:
    return (
        tuple(min(vertex[axis] for vertex in mesh.vertices) for axis in range(3)),
        tuple(max(vertex[axis] for vertex in mesh.vertices) for axis in range(3)),
    )


def _bounds_overlap(first, second) -> bool:
    return all(
        first[0][axis] < second[1][axis] and second[0][axis] < first[1][axis]
        for axis in range(3)
    )


def _positives_with_cut_flags(
    meshes_with_metadata: List[Tuple[MeshData, MeshMetadata]],
) -> List[Tuple[MeshData, MeshMetadata, bool]]:
    negative_bounds: dict = {}
    for mesh, meta in meshes_with_metadata:
        if meta.get("IsNegativeQuantity", False) and mesh.vertices:
            negative_bounds.setdefault(meta["condition_type"], []).append(_bounds(mesh))
    positives = []
    for mesh, meta in meshes_with_metadata:
        if meta.get("IsNegativeQuantity", False):
            continue
        same_type_bounds = negative_bounds.get(meta["condition_type"], ())
        may_be_cut = not mesh.vertices or any(
            _bounds_overlap(_bounds(mesh), bounds) for bounds in same_type_bounds
        )
        positives.append((mesh, meta, may_be_cut))
    return positives


def apply_boolean_operations(
    meshes_with_metadata: List[Tuple[MeshData, MeshMetadata]],
) -> List[Tuple[MeshData, MeshMetadata]]:
    if not meshes_with_metadata:
        return []
    _require_condition_types(meshes_with_metadata)
    positive_count = sum(
        1
        for _, meta in meshes_with_metadata
        if not meta.get("IsNegativeQuantity", False)
    )
    negative_count = len(meshes_with_metadata) - positive_count
    if negative_count == 0:
        return [
            (mesh, meta)
            for mesh, meta in meshes_with_metadata
            if not meta.get("IsNegativeQuantity", False)
        ]
    try:
        result_data = ost_geometry.apply_boolean_operations(meshes_with_metadata)
        pending_positives = iter(_positives_with_cut_flags(meshes_with_metadata))
        results = []
        for args, metadata in result_data:
            original, may_be_cut = next(
                (mesh, cut) for mesh, meta, cut in pending_positives if meta is metadata
            )
            if not may_be_cut:
                results.append((original, metadata))
                continue
            _flip_manifold_faces(args)
            mesh = _dict_to_meshdata(args)
            results.append((mesh, metadata))
        return results
    except Exception as e:
        logger.error(
            BOOLEAN_OPERATIONS_LOG_BOOLEAN_OPERATIONS_FAILED_RETURNING_POSITIVE_MESHES.format(
                error=e
            )
        )
        return [
            (mesh, meta)
            for mesh, meta in meshes_with_metadata
            if not meta.get("IsNegativeQuantity", False)
        ]


def boolean_union(
    mesh1: MeshData, mesh2: MeshData, original_metadata: Optional[dict] = None
) -> Optional[MeshData]:
    try:
        result = ost_geometry.boolean_union(mesh1, mesh2)
        if result is None:
            return None
        _flip_manifold_faces(result)
        return _dict_to_meshdata(result, original_metadata)
    except Exception as e:
        logger.error("boolean_union failed: %s", e)
        return None
