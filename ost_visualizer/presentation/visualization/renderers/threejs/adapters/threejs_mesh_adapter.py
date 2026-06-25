from typing import Dict, List, Optional, Tuple
from ......application.dtos.scene_data_dto import (
    SceneAreaEntry,
    SceneBoundsConfig,
    SceneCameraConfig,
    SceneConditionEntry,
    SceneData,
    SceneGeometryEntry,
    SceneLayerEntry,
    ScenePageImageLayer,
)
from ......domain.dtos.mesh_metadata_dto import MeshMetadata
from ......domain.entities.area import (
    BidArea,
    is_unassigned_area_uid,
    normalize_area_uid,
)
from ......domain.entities.layer import BidLayer
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
        layers: Optional[List[BidLayer]] = None,
        areas: Optional[List[BidArea]] = None,
        page_image_layer: Optional[ScenePageImageLayer] = None,
    ) -> SceneData:
        geometries = []
        conditions_by_uid: Dict[str, SceneConditionEntry] = {}
        areas_by_uid: Dict[str, SceneAreaEntry] = self._convert_areas(areas or [])
        for mesh_data, metadata in meshes:
            geometry = self.convert_mesh(mesh_data, metadata)
            if geometry:
                geometries.append(geometry)
            condition_uid = str(metadata.get("condition_uid", "") or "")
            if condition_uid and condition_uid not in conditions_by_uid:
                conditions_by_uid[condition_uid] = {
                    "uid": condition_uid,
                    "name": str(metadata.get("name", "") or ""),
                    "layer_uid": str(metadata.get("layer_uid", "") or ""),
                    "visible": True,
                    "cdn_type_uid": str(metadata.get("cdn_type_uid", "") or ""),
                    "cdn_type_name": str(
                        metadata.get("cdn_type_name", "") or "Unknown"
                    ),
                    "color": str(metadata.get("condition_color", "") or ""),
                    "ref_no": int(metadata.get("condition_ref_no", 0) or 0),
                }
            area_uid = str(metadata.get("area_uid", "") or "")
            if area_uid and area_uid not in areas_by_uid:
                areas_by_uid[area_uid] = {
                    "uid": area_uid,
                    "name": str(metadata.get("area_name", "") or area_uid),
                    "visible": True,
                    "sequence": len(areas_by_uid),
                }
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
        scene_layers = self._convert_layers(layers or [], page_image_layer)
        if scene_layers:
            scene["layers"] = scene_layers
        if conditions_by_uid:
            scene["conditions"] = list(conditions_by_uid.values())
        if areas_by_uid:
            scene["areas"] = sorted(
                areas_by_uid.values(), key=lambda area: int(area["sequence"])
            )
        if page_image_layer:
            scene["page_image_layer"] = page_image_layer
        return scene

    @staticmethod
    def _convert_layers(
        layers: List[BidLayer],
        page_image_layer: Optional[ScenePageImageLayer] = None,
    ) -> List[SceneLayerEntry]:
        scene_layers: List[SceneLayerEntry] = []
        seen = set()
        ordered_layers = sorted(
            layers,
            key=lambda item: item.sequence if item.sequence is not None else 0,
        )
        for index, layer in enumerate(ordered_layers):
            uid = str(layer.uid or "")
            if not uid or uid in seen:
                continue
            sequence = layer.sequence if layer.sequence is not None else index
            scene_layers.append(
                {
                    "uid": uid,
                    "name": str(layer.name or uid),
                    "visible": bool(layer.show),
                    "sequence": int(sequence),
                }
            )
            seen.add(uid)
        if page_image_layer:
            uid = str(page_image_layer.get("uid", "") or "")
            if uid and uid not in seen:
                scene_layers.append(
                    {
                        "uid": uid,
                        "name": str(page_image_layer.get("name", "") or uid),
                        "visible": bool(page_image_layer.get("visible", True)),
                        "sequence": len(scene_layers),
                    }
                )
        return scene_layers

    @staticmethod
    def _convert_areas(areas: List[BidArea]) -> Dict[str, SceneAreaEntry]:
        scene_areas: Dict[str, SceneAreaEntry] = {}
        ordered_areas = sorted(
            areas,
            key=lambda item: item.sequence if item.sequence is not None else 0,
        )
        for index, area in enumerate(ordered_areas):
            uid = normalize_area_uid(area.uid)
            if is_unassigned_area_uid(uid) or uid in scene_areas:
                continue
            sequence = area.sequence if area.sequence is not None else index
            scene_areas[uid] = {
                "uid": uid,
                "name": str(area.name or uid),
                "visible": True,
                "sequence": int(sequence),
            }
        return scene_areas

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
            "visible": bool(metadata.get("visible", True)),
            "takeoff_uid": str(metadata.get("takeoff_uid", "") or ""),
            "page_uid": str(metadata.get("page_uid", "") or ""),
            "condition_uid": str(metadata.get("condition_uid", "") or ""),
            "area_uid": str(metadata.get("area_uid", "") or ""),
            "layer_uid": str(metadata.get("layer_uid", "") or ""),
            "cdn_type_uid": str(metadata.get("cdn_type_uid", "") or ""),
            "cdn_type_name": str(metadata.get("cdn_type_name", "") or "Unknown"),
        }
        return entry
