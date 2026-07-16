import logging
from typing import List, Optional, Tuple
from ....domain.dtos.mesh_metadata_dto import MeshMetadata
from . import ost_geometry
from .mesh_generator import MeshData

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


def apply_boolean_operations(
    meshes_with_metadata: List[Tuple[MeshData, MeshMetadata]],
) -> List[Tuple[MeshData, MeshMetadata]]:
    if not meshes_with_metadata:
        return []
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
        results = []
        for args, metadata in result_data:
            _flip_manifold_faces(args)
            mesh = _dict_to_meshdata(args)
            results.append((mesh, metadata))
        return results
    except Exception as e:
        logger.error(
            "Boolean operations failed; returning positive meshes unchanged: %s", e
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
