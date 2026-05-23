from typing import Dict
from .adapters.fbx_writer import FBXMeshWriter
from .base_exporter import BaseExporter


class FBXExporter(BaseExporter):
    def __init__(self, coord_system, color_service, takeoff_service):
        super().__init__(coord_system, color_service, takeoff_service)
        self.fbx_writer = FBXMeshWriter(color_service)

    def cleanup(self) -> None:
        self.fbx_writer = None
        super().cleanup()

    def _write_output(
        self,
        output_path: str,
        takeoffs_by_group: Dict,
        materials_info: Dict,
        bid_conditions: Dict,
        color_mode: str,
        **kwargs,
    ):
        meshes_with_materials = []
        for key, pairs in takeoffs_by_group.items():
            material_name, original_name, hex_color = materials_info[key]
            for takeoff, condition in pairs:
                if takeoff.is_negative:
                    continue
                mesh_data = self._generate_mesh_for_takeoff(takeoff, condition)
                if mesh_data:
                    meshes_with_materials.append(
                        {
                            "mesh_data": mesh_data,
                            "material_key": key,
                            "material_name": material_name,
                            "original_name": original_name,
                            "mesh_type": mesh_data.metadata.get("type", ""),
                        }
                    )
        self.fbx_writer.write_fbx_file(
            output_path, meshes_with_materials, materials_info, color_mode
        )
        for mesh_dict in meshes_with_materials:
            mesh_data = mesh_dict.get("mesh_data")
            if mesh_data:
                mesh_data.vertices.clear()
                mesh_data.faces.clear()
                mesh_data.edges.clear()
                mesh_data.metadata.clear()
            mesh_dict.clear()
        meshes_with_materials.clear()
        del meshes_with_materials
