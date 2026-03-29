import os
from pathlib import Path
from typing import Dict
from ....application.interfaces.i_color_service import IColorService
from .adapters.obj_writer import OBJMeshWriter
from .base_exporter import BaseExporter


class OBJExporter(BaseExporter):
    def __init__(self, coord_system, color_service: IColorService, takeoff_service):
        super().__init__(coord_system, color_service, takeoff_service)
        self.obj_writer = OBJMeshWriter()

    def cleanup(self) -> None:
        self.obj_writer = None
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
        base_name = Path(output_path).stem
        output_dir = os.path.dirname(output_path) or "."
        mtl_filename = base_name + ".mtl"
        mtl_path = os.path.join(output_dir, mtl_filename)
        self._write_mtl_file(mtl_path, materials_info, color_mode)
        self._write_obj_file(
            output_path, takeoffs_by_group, materials_info, bid_conditions, mtl_filename
        )

    def _write_mtl_file(self, mtl_path: str, materials_info: Dict, color_mode: str):
        with open(mtl_path, "w") as mtl:
            mtl.write(f"# Created by OST Visualizer\n")
            mtl.write(f"# Color Mode: {color_mode}\n")
            mtl.write(f"# Materials: {len(materials_info)}\n\n")
            for key, (
                material_name,
                original_name,
                hex_color,
            ) in materials_info.items():
                mtl.write(f"newmtl {material_name}\n")
                mtl.write(f"# {original_name}\n")
                r, g, b = self._color_service.hex_to_rgb(hex_color)
                mtl.write(f"Kd {r:.6f} {g:.6f} {b:.6f}\n")
                mtl.write("Ka 0.200000 0.200000 0.200000\n")
                mtl.write("Ks 0.500000 0.500000 0.500000\n")
                mtl.write("Ns 20.000000\n")
                mtl.write("Ni 1.000000\n")
                mtl.write("d 1.000000\n")
                mtl.write("illum 2\n\n")

    def _write_obj_file(
        self,
        output_path: str,
        takeoffs_by_group: Dict,
        materials_info: Dict,
        bid_conditions: Dict,
        mtl_filename: str,
    ):
        with open(output_path, "w") as f:
            f.write("# Created by OST Visualizer\n")
            f.write(f"mtllib {mtl_filename}\n\n")
            self.obj_writer.reset_index()
            for key, pairs in takeoffs_by_group.items():
                material_name, original_name, _ = materials_info[key]
                f.write(f"# {original_name}\n")
                f.write(f"g {material_name}\n")
                f.write(f"usemtl {material_name}\n")
                for takeoff, condition in pairs:
                    if takeoff.is_negative:
                        continue
                    mesh_data = self._generate_mesh_for_takeoff(takeoff, condition)
                    if mesh_data:
                        self.obj_writer.write_mesh(f, mesh_data, material_name)
                        mesh_data.vertices.clear()
                        mesh_data.faces.clear()
                        mesh_data.edges.clear()
                        mesh_data.metadata.clear()
                        del mesh_data
                f.write("\n")
