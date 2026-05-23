from typing import List, Optional, Tuple
from ......application.dtos.scene_data_dto import (
    SceneBoundsConfig,
    SceneCameraConfig,
    SceneData,
    SceneGeometryEntry,
)
from ......domain.dtos.mesh_metadata_dto import MeshMetadata
from ....core.mesh_generator import MeshData
from ....services.color_service import ColorService
from ....utils.mesh import prepare_vertices_for_shading

Bounds = Tuple[float, float, float, float, float, float]


class ThreejsMeshAdapter:
    def __init__(self, color_service: ColorService):
        self._color_service = color_service

    def build_scene_data(
        self,
        meshes: List[Tuple[MeshData, MeshMetadata]],
        bounds: Bounds,
        title: str,
    ) -> SceneData:
        geometries = []
        for mesh_data, metadata in meshes:
            geometry = self.convert_mesh(mesh_data, metadata)
            if geometry:
                geometries.append(geometry)
        center_x = (bounds[0] + bounds[1]) / 2
        center_y = (bounds[2] + bounds[3]) / 2
        center_z = (bounds[4] + bounds[5]) / 2
        size = max(
            bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4], 1.0
        )
        camera: SceneCameraConfig = {
            "position": [center_x, center_z + size * 1.5, -center_y - size],
            "target": [center_x, center_z, -center_y],
        }
        scene_bounds: SceneBoundsConfig = {
            "min": [bounds[0], bounds[4], -bounds[3]],
            "max": [bounds[1], bounds[5], -bounds[2]],
        }
        scene: SceneData = {
            "title": title,
            "geometries": geometries,
            "camera": camera,
            "bounds": scene_bounds,
        }
        return scene

    def convert_mesh(
        self,
        mesh_data: MeshData,
        metadata: MeshMetadata,
    ) -> Optional[SceneGeometryEntry]:
        if not mesh_data or not mesh_data.vertices or not mesh_data.faces:
            return None
        raw_vertices = [tuple(v) for v in mesh_data.vertices]
        raw_faces = [tuple(f[:3]) for f in mesh_data.faces if len(f) >= 3]
        vertices, normals, faces = prepare_vertices_for_shading(raw_vertices, raw_faces)
        vertex_buffer = []
        normal_buffer = []
        for v in vertices:
            vertex_buffer.extend([v[0], v[2], -v[1]])
        for n in normals:
            normal_buffer.extend([n[0], n[2], -n[1]])
        index_buffer = []
        for f in faces:
            index_buffer.extend([f[0], f[1], f[2]])
        color_hex = metadata.get("color", "#808080")
        r, g, b = self._color_service.parse_hex_color(color_hex)
        entry: SceneGeometryEntry = {
            "vertices": vertex_buffer,
            "normals": normal_buffer,
            "indices": index_buffer,
            "color": [r, g, b],
            "opacity": metadata.get("opacity", 1.0),
            "name": metadata.get("name", "Mesh"),
        }
        return entry
