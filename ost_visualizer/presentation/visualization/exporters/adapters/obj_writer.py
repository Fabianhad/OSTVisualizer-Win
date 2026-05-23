from typing import List, TextIO, Tuple
from ...core.mesh_generator import MeshData


class OBJMeshWriter:
    def __init__(self):
        self.vertex_index = 1

    def reset_index(self):
        self.vertex_index = 1

    def write_mesh(
        self,
        file_handle: TextIO,
        mesh_data: MeshData,
        material_name: str,
    ) -> int:
        if not mesh_data or not mesh_data.vertices:
            return self.vertex_index
        transformed_vertices = self._transform_vertices(mesh_data.vertices)
        for v in transformed_vertices:
            file_handle.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
        mesh_type = mesh_data.metadata.get("type", "")
        transformed_faces = self._transform_faces(mesh_data.faces, mesh_type)
        for face in transformed_faces:
            vi = self.vertex_index
            file_handle.write(f"f {face[0]+vi} {face[1]+vi} {face[2]+vi}\n")
        result_index = self.vertex_index + len(transformed_vertices)
        self.vertex_index = result_index
        return result_index

    @staticmethod
    def _transform_vertices(
        vertices: List[Tuple[float, float, float]],
    ) -> List[Tuple[float, float, float]]:
        return [(v[0], v[2], -v[1]) for v in vertices]

    @staticmethod
    def _transform_faces(
        faces: List[Tuple[int, int, int]],
        mesh_type: str = "",
    ) -> List[Tuple[int, int, int]]:
        return [(f[0], f[2], f[1]) for f in faces]
