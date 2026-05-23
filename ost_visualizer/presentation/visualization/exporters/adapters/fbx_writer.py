from datetime import datetime
from typing import Any, Dict, List
from .....application.interfaces.i_color_service import IColorService


class FBXMeshWriter:
    def __init__(self, color_service: IColorService):
        self.object_id_counter = 100000
        self._color_service = color_service

    def write_fbx_file(
        self,
        output_path: str,
        meshes_with_materials: List[Dict[str, Any]],
        materials_info: Dict,
        color_mode: str,
    ):
        material_ids = {}
        for key in materials_info.keys():
            material_ids[key] = self._get_next_id()
        geometry_models = []
        for mesh_info in meshes_with_materials:
            mesh_data = mesh_info["mesh_data"]
            material_key = mesh_info["material_key"]
            material_name = mesh_info["material_name"]
            original_name = mesh_info["original_name"]
            geometry_id = self._get_next_id()
            model_id = self._get_next_id()
            material_id = material_ids[material_key]
            mesh_type = mesh_data.metadata.get("type", "Unknown")
            mesh_name = f"{mesh_type}_{material_name}_{len(geometry_models)}"
            geometry_models.append(
                {
                    "geometry_id": geometry_id,
                    "model_id": model_id,
                    "material_id": material_id,
                    "mesh_name": mesh_name,
                    "vertices": mesh_data.vertices,
                    "faces": mesh_data.faces,
                    "mesh_type": mesh_data.metadata.get("type", ""),
                }
            )
        with open(output_path, "w") as f:
            self._write_header(f, color_mode, len(geometry_models), len(materials_info))
            self._write_materials(f, materials_info, material_ids)
            self._write_geometries_and_models(f, geometry_models)
            self._write_connections(f, geometry_models)

    def _get_next_id(self) -> int:
        current_id = self.object_id_counter
        self.object_id_counter += 1
        return current_id

    def _write_header(self, f, color_mode: str, num_models: int, num_materials: int):
        timestamp = datetime.now()
        header = f"""; FBX 7.4.0 project file
; Created by OST Visualizer
; Color Mode: {color_mode}
; Creation time: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}
FBXHeaderExtension: {{
\tFBXHeaderVersion: 1003
\tFBXVersion: 7400
\tCreationTimeStamp: {{
\t\tVersion: 1000
\t\tYear: {timestamp.year}
\t\tMonth: {timestamp.month}
\t\tDay: {timestamp.day}
\t\tHour: {timestamp.hour}
\t\tMinute: {timestamp.minute}
\t\tSecond: {timestamp.second}
\t\tMillisecond: {timestamp.microsecond//1000}
\t}}
\tCreator: "OST Visualizer"
}}
GlobalSettings: {{
\tVersion: 1000
\tProperties70: {{
\t\tP: "UpAxis", "int", "Integer", "",2
\t\tP: "UpAxisSign", "int", "Integer", "",1
\t\tP: "FrontAxis", "int", "Integer", "",1
\t\tP: "FrontAxisSign", "int", "Integer", "",-1
\t\tP: "CoordAxis", "int", "Integer", "",0
\t\tP: "CoordAxisSign", "int", "Integer", "",1
\t\tP: "OriginalUpAxis", "int", "Integer", "",2
\t\tP: "OriginalUpAxisSign", "int", "Integer", "",1
\t\tP: "UnitScaleFactor", "double", "Number", "",1
\t\tP: "OriginalUnitScaleFactor", "double", "Number", "",1
\t}}
}}
Documents: {{
\tCount: 1
\tDocument: 2000000, "", "Scene" {{
\t\tProperties70: {{
\t\t\tP: "SourceObject", "object", "", ""
\t\t\tP: "ActiveAnimStackName", "KString", "", "", ""
\t\t}}
\t\tRootNode: 0
\t}}
}}
References: {{
}}
Definitions: {{
\tVersion: 100
\tCount: {1 + num_models + num_models + num_materials}
\tObjectType: "GlobalSettings" {{
\t\tCount: 1
\t}}
\tObjectType: "Model" {{
\t\tCount: {num_models}
\t}}
\tObjectType: "Geometry" {{
\t\tCount: {num_models}
\t}}
\tObjectType: "Material" {{
\t\tCount: {num_materials}
\t}}
}}
Objects: {{
"""
        f.write(header)

    def _write_materials(self, f, materials_info: Dict, material_ids: Dict):
        for key, (material_name, original_name, hex_color) in materials_info.items():
            material_id = material_ids[key]
            r, g, b = self._color_service.hex_to_rgb(hex_color)
            material_def = f"""\tMaterial: {material_id}, "Material::{material_name}", "" {{
\t\tVersion: 102
\t\tShadingModel: "phong"
\t\tMultiLayer: 0
\t\tProperties70: {{
\t\t\tP: "DiffuseColor", "Color", "", "A",{r:.6f},{g:.6f},{b:.6f}
\t\t\tP: "AmbientColor", "Color", "", "A",0.2,0.2,0.2
\t\t\tP: "SpecularColor", "Color", "", "A",0.5,0.5,0.5
\t\t\tP: "Shininess", "Number", "", "A",20.0
\t\t\tP: "Opacity", "Number", "", "A",1.0
\t\t}}
\t}}
"""
            f.write(material_def)

    def _write_geometries_and_models(self, f, geometry_models: List[Dict]):
        for gm in geometry_models:
            f.write(
                f'\tModel: {gm["model_id"]}, "Model::{gm["mesh_name"]}", "Mesh" {{\n'
                f"\t\tVersion: 232\n"
                f"\t\tProperties70: {{\n"
                f'\t\t\tP: "RotationActive", "bool", "", "",1\n'
                f'\t\t\tP: "InheritType", "enum", "", "",1\n'
                f'\t\t\tP: "ScalingMax", "Vector3D", "Vector", "",0,0,0\n'
                f'\t\t\tP: "DefaultAttributeIndex", "int", "Integer", "",0\n'
                f"\t\t}}\n"
                f"\t\tShading: Y\n"
                f'\t\tCulling: "CullingOff"\n'
                f"\t}}\n"
            )
            vertices = gm["vertices"]
            faces = gm["faces"]
            mesh_type = gm.get("mesh_type", "")
            f.write(
                f'\tGeometry: {gm["geometry_id"]}, "Geometry::{gm["mesh_name"]}", "Mesh" {{\n'
                f"\t\tVertices: *{len(vertices)*3} {{\n"
                f"\t\t\ta: "
            )
            f.write(",".join(f"{x:.6f},{y:.6f},{z:.6f}" for x, y, z in vertices))
            f.write("\n\t\t}\n")
            f.write(f"\t\tPolygonVertexIndex: *{len(faces)*3} {{\n\t\t\ta: ")
            f.write(",".join(f"{face[0]},{face[2]},-{face[1]+1}" for face in faces))
            f.write("\n\t\t}\n")
            f.write(
                f"\t\tEdges: *0 {{\n\t\t\ta: \n\t\t}}\n" f"\t\tGeometryVersion: 124\n"
            )
            self._write_normals(f, vertices, faces, mesh_type)
            f.write(
                f"\t\tLayerElementMaterial: 0 {{\n"
                f"\t\t\tVersion: 101\n"
                f'\t\t\tName: ""\n'
                f'\t\t\tMappingInformationType: "AllSame"\n'
                f'\t\t\tReferenceInformationType: "IndexToDirect"\n'
                f"\t\t\tMaterials: *1 {{\n"
                f"\t\t\t\ta: 0\n"
                f"\t\t\t}}\n"
                f"\t\t}}\n"
            )
            f.write(
                "\t\tLayer: 0 {\n"
                "\t\t\tVersion: 100\n"
                "\t\t\tLayerElement: {\n"
                '\t\t\t\tType: "LayerElementNormal"\n'
                "\t\t\t\tTypedIndex: 0\n"
                "\t\t\t}\n"
                "\t\t\tLayerElement: {\n"
                '\t\t\t\tType: "LayerElementMaterial"\n'
                "\t\t\t\tTypedIndex: 0\n"
                "\t\t\t}\n"
                "\t\t}\n"
                "\t}\n"
            )

    def _write_normals(self, f, vertices, faces, mesh_type=""):
        f.write(
            f"\t\tLayerElementNormal: 0 {{\n"
            f"\t\t\tVersion: 101\n"
            f'\t\t\tName: ""\n'
            f'\t\t\tMappingInformationType: "ByPolygonVertex"\n'
            f'\t\t\tReferenceInformationType: "Direct"\n'
            f"\t\t\tNormals: *{len(faces)*9} {{\n"
            f"\t\t\t\ta: "
        )
        normals = []
        for face in faces:
            v0, v1, v2 = vertices[face[0]], vertices[face[2]], vertices[face[1]]
            edge1 = [v1[j] - v0[j] for j in range(3)]
            edge2 = [v2[j] - v0[j] for j in range(3)]
            nx = edge1[1] * edge2[2] - edge1[2] * edge2[1]
            ny = edge1[2] * edge2[0] - edge1[0] * edge2[2]
            nz = edge1[0] * edge2[1] - edge1[1] * edge2[0]
            length = (nx * nx + ny * ny + nz * nz) ** 0.5
            if length > 0:
                nx /= length
                ny /= length
                nz /= length
            normals.extend([f"{nx:.6f},{ny:.6f},{nz:.6f}"] * 3)
        f.write(",".join(normals))
        f.write("\n\t\t\t}\n\t\t}\n")

    def _write_connections(self, f, geometry_models: List[Dict]):
        f.write("}\n\nConnections: {\n")
        for gm in geometry_models:
            f.write(
                f'\tC: "OO",{gm["model_id"]},0\n'
                f'\tC: "OO",{gm["geometry_id"]},{gm["model_id"]}\n'
                f'\tC: "OO",{gm["material_id"]},{gm["model_id"]}\n'
            )
        f.write("}\n")
