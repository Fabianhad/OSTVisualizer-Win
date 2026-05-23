from typing import Dict
from ..core import ost_geometry
from . import ost_dxf
from .base_exporter import BaseExporter


class DXFExporter(BaseExporter):
    def __init__(self, coord_system, color_service, takeoff_service):
        super().__init__(coord_system, color_service, takeoff_service)
        self.native_writer = ost_dxf.DXFWriter()

    def _write_output(
        self,
        output_path: str,
        takeoffs_by_group: Dict,
        materials_info: Dict,
        bid_conditions: Dict,
        color_mode: str,
        **kwargs,
    ):
        self.native_writer.clear()
        for key, (material_name, _, hex_color) in materials_info.items():
            self.native_writer.add_layer(material_name, hex_color)
        for key, pairs in takeoffs_by_group.items():
            if key not in materials_info:
                continue
            material_name = materials_info[key][0]
            for takeoff, condition in pairs:
                if takeoff.is_negative:
                    continue
                mesh_data = self._generate_mesh_for_takeoff(takeoff, condition)
                if mesh_data:
                    clean_data = ost_geometry.extract_feature_edges(mesh_data, 0.1)
                    vertices = clean_data.get("vertices", [])
                    edges = clean_data.get("edges", [])
                    for edge in edges:
                        v1 = vertices[edge[0]]
                        v2 = vertices[edge[1]]
                        self.native_writer.add_line(v1, v2, material_name)
        return self.native_writer.save(output_path)
