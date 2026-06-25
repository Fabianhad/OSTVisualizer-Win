import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
from ....application.interfaces.i_color_service import IColorService
from ....application.interfaces.i_coordinate_transformer import ICoordinateTransformer
from ....application.interfaces.i_takeoff_domain_service import ITakeoffDomainService
from ....domain.dtos.mesh_metadata_dto import MeshMetadata
from ....domain.entities.config import Config
from ....domain.entities.condition import Condition
from ....domain.entities.takeoff import Takeoff
from ..core.boolean_operations import apply_boolean_operations
from ..core.mesh_generator import MeshData
from ..meshing.mesh_builder import get_holes_for_takeoff
from ..meshing.mesh_factory import MeshFactory

logger = logging.getLogger(__name__)


class BaseExporter(ABC):
    def __init__(
        self,
        coord_system: ICoordinateTransformer,
        color_service: IColorService,
        takeoff_service: ITakeoffDomainService,
    ):
        self._coord_system = coord_system
        self._color_service = color_service
        self._takeoff_service = takeoff_service
        self.mesh_factory = MeshFactory(coord_system)
        self.area_holes_map = {}
        self.processed_mesh_cache = {}

    def cleanup(self) -> None:
        if self.area_holes_map:
            self.area_holes_map.clear()
        self.area_holes_map = {}
        if self.processed_mesh_cache:
            self.processed_mesh_cache.clear()
        self.processed_mesh_cache = {}
        self.mesh_factory = None

    def export(
        self,
        bid_conditions: Dict[str, Condition],
        bid_takeoffs: List[Takeoff],
        output_path: str,
        display_mode: str = Config.DISPLAY_MODE_SOLID,
        grayscale_enabled: bool = True,
        page_area_selections: Optional[Dict[str, Optional[str]]] = None,
        **kwargs,
    ) -> bool:
        exportable_takeoffs = None
        hierarchy_map = None
        color_map = None
        takeoffs_by_group = None
        materials_info = None
        try:
            exportable_takeoffs = self._filter_exportable_takeoffs(
                bid_takeoffs, bid_conditions
            )
            if not exportable_takeoffs:
                logger.warning("No exportable elements found for exporter")
                return False
            exportable_takeoffs, self.area_holes_map = (
                self._takeoff_service.group_area_takeoffs_with_holes(
                    exportable_takeoffs, bid_conditions
                )
            )
            hierarchy_map, color_map = self._color_service.get_color_mapping(
                bid_conditions, exportable_takeoffs, display_mode, grayscale_enabled
            )
            takeoffs_by_group, materials_info = self._prepare_hierarchical_export(
                exportable_takeoffs, bid_conditions, color_map, page_area_selections
            )
            self._apply_boolean_operations(takeoffs_by_group, bid_conditions)
            self._write_output(
                output_path,
                takeoffs_by_group,
                materials_info,
                bid_conditions,
                display_mode,
                **kwargs,
            )
            return True
        except Exception:
            logger.exception("Error during export")
            return False
        finally:
            if exportable_takeoffs is not None:
                exportable_takeoffs.clear()
                del exportable_takeoffs
            if hierarchy_map is not None:
                hierarchy_map.clear()
                del hierarchy_map
            if color_map is not None:
                color_map.clear()
                del color_map
            if takeoffs_by_group is not None:
                takeoffs_by_group.clear()
                del takeoffs_by_group
            if materials_info is not None:
                materials_info.clear()
                del materials_info
            self.cleanup()

    def _filter_exportable_takeoffs(
        self, bid_takeoffs: List[Takeoff], bid_conditions: Dict[str, Condition]
    ) -> List[Takeoff]:
        return [
            t
            for t in bid_takeoffs
            if (c_uid := t.condition_uid) in bid_conditions
            and bid_conditions[c_uid].condition_type in [0, 1, 2, 3]
        ]

    def _prepare_hierarchical_export(
        self,
        exportable_takeoffs,
        bid_conditions,
        condition_color_map,
        page_area_selections: Optional[Dict[str, Optional[str]]] = None,
    ) -> Tuple[Dict, Dict]:
        takeoffs_by_condition = {}
        materials_info = {}
        for takeoff in exportable_takeoffs:
            condition_uid = takeoff.condition_uid
            condition = bid_conditions[condition_uid]
            if self._color_service.should_gray_out_takeoff(
                takeoff, page_area_selections
            ):
                hex_color = "#808080"
            else:
                color_entry = condition_color_map.get(condition_uid, "#808080")
                hex_color, _ = self._color_service.as_hex_with_opacity(color_entry)
            condition_name = (
                condition.name if condition.name else f"Condition_{condition_uid}"
            )
            cdn_type = condition.cdn_type_name if condition.cdn_type_name else "Unknown"
            material_name = self._sanitize_material_name(
                f"{cdn_type}_{condition_name}_{condition_uid[:8]}"
            )
            if condition_uid not in materials_info:
                materials_info[condition_uid] = (
                    material_name,
                    condition_name,
                    hex_color,
                )
            takeoffs_by_condition.setdefault(condition_uid, []).append(
                (takeoff, condition)
            )
        return takeoffs_by_condition, materials_info

    def _apply_boolean_operations(
        self, takeoffs_by_group: Dict, bid_conditions: Dict
    ) -> None:
        meshes_with_metadata: List[Tuple[MeshData, MeshMetadata]] = []
        takeoff_to_index: Dict[str, int] = {}
        index = 0
        for _, pairs in takeoffs_by_group.items():
            for takeoff, condition in pairs:
                takeoff_uid = takeoff.uid
                mesh = self._generate_mesh_for_takeoff(takeoff, condition)
                if mesh and mesh.vertices and mesh.faces:
                    is_negative = takeoff.is_negative
                    metadata: MeshMetadata = {
                        "IsNegativeQuantity": is_negative,
                        "takeoff_uid": takeoff_uid,
                    }
                    meshes_with_metadata.append((mesh, metadata))
                    takeoff_to_index[takeoff_uid] = index
                    index += 1
        if not meshes_with_metadata:
            logger.warning("No meshes generated for boolean operations")
            return
        processed_meshes = apply_boolean_operations(meshes_with_metadata)
        for mesh, metadata in processed_meshes:
            takeoff_uid = metadata.get("takeoff_uid", "")
            if takeoff_uid:
                self.processed_mesh_cache[takeoff_uid] = mesh

    @staticmethod
    def _sanitize_material_name(name: str) -> str:
        sanitized = (
            name.replace(" ", "_")
            .replace('"', "")
            .replace("'", "")
            .replace(",", "")
            .replace("/", "_")
            .replace("\\", "_")
            .replace(":", "_")
            .replace(";", "_")
            .replace("*", "_")
            .replace("?", "_")
            .replace("<", "_")
            .replace(">", "_")
            .replace("|", "_")
            .replace(".", "_")
            .replace("(", "_")
            .replace(")", "_")
            .replace("[", "_")
            .replace("]", "_")
            .replace("{", "_")
            .replace("}", "_")
        )
        if sanitized and sanitized[0].isdigit():
            sanitized = "Mat_" + sanitized
        return sanitized if sanitized else "Unknown"

    def _generate_mesh_for_takeoff(
        self,
        takeoff: Takeoff,
        condition: Condition,
    ) -> Optional[MeshData]:
        takeoff_uid = takeoff.uid
        if takeoff_uid in self.processed_mesh_cache:
            return self.processed_mesh_cache[takeoff_uid]
        holes = get_holes_for_takeoff(takeoff_uid, self.area_holes_map)
        return self.mesh_factory.create_mesh_for_takeoff(takeoff, condition, holes)

    @abstractmethod
    def _write_output(
        self,
        output_path: str,
        takeoffs_by_group: Dict,
        materials_info: Dict,
        bid_conditions: Dict,
        display_mode: str,
        **kwargs,
    ):
        pass
