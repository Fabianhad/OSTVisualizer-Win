from __future__ import annotations
import math
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple, Union
from ....application.dtos.mesh_geometry_dto import MeshGeometry
from ....application.interfaces.i_color_service import IColorService

if TYPE_CHECKING:
    from ..core.mesh_generator import MeshData


def get_box_edges() -> List[List[int]]:
    return [
        [0, 1],
        [1, 2],
        [2, 3],
        [3, 0],
        [4, 5],
        [5, 6],
        [6, 7],
        [7, 4],
        [0, 4],
        [1, 5],
        [2, 6],
        [3, 7],
    ]


def get_box_faces() -> List[List[int]]:
    return [
        [0, 1, 2],
        [0, 2, 3],
        [4, 6, 5],
        [4, 7, 6],
        [0, 3, 7],
        [0, 7, 4],
        [1, 0, 4],
        [1, 4, 5],
        [2, 1, 5],
        [2, 5, 6],
        [3, 2, 6],
        [3, 6, 7],
    ]


def get_slope_factor(
    rise: Optional[float], run: Optional[float]
) -> Tuple[Optional[float], Optional[float], float, bool]:
    has_slope = rise is not None and run is not None and run != 0
    if not has_slope:
        return rise, run, 1.0, False
    slope_factor = math.sqrt(rise**2 + run**2) / abs(run)
    return rise, run, slope_factor, has_slope


def _transform_vertex(vertex) -> Tuple[float, float, float]:
    x = float(vertex[0])
    y = float(vertex[1])
    z = float(vertex[2])
    return x, y, z


def _transform_normal(normal) -> Tuple[float, float, float]:
    x = float(normal[0])
    y = float(normal[1])
    z = float(normal[2])
    return x, y, z


def _normalize_vector(vector: Tuple[float, float, float]) -> Tuple[float, float, float]:
    nx, ny, nz = vector
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length == 0.0:
        return (0.0, 1.0, 0.0)
    nx /= length
    ny /= length
    nz /= length
    if nz < 0.0:
        nx, ny, nz = -nx, -ny, -nz
    return (nx, ny, nz)


def _compute_face_normals(
    vertices: List[Tuple[float, float, float]],
    faces: List[Tuple[int, int, int]],
) -> List[Tuple[float, float, float]]:
    normals: List[Tuple[float, float, float]] = []
    for face in faces:
        if len(face) < 3:
            normals.append((0.0, 1.0, 0.0))
            continue
        a, b, c = face[:3]
        if (
            a >= len(vertices)
            or b >= len(vertices)
            or c >= len(vertices)
            or a < 0
            or b < 0
            or c < 0
        ):
            normals.append((0.0, 1.0, 0.0))
            continue
        v0 = vertices[a]
        v1 = vertices[b]
        v2 = vertices[c]
        e1 = (v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2])
        e2 = (v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2])
        nx = e1[1] * e2[2] - e1[2] * e2[1]
        ny = e1[2] * e2[0] - e1[0] * e2[2]
        nz = e1[0] * e2[1] - e1[1] * e2[0]
        normals.append(_normalize_vector((nx, ny, nz)))
    return normals


def prepare_vertices_for_shading(
    vertices: List[Tuple[float, float, float]],
    faces: List[Tuple[int, int, int]],
    crease_angle_degrees: float = 60.0,
) -> Tuple[
    List[Tuple[float, float, float]],
    List[Tuple[float, float, float]],
    List[Tuple[int, int, int]],
]:
    if not vertices or not faces:
        return vertices[:], [(0.0, 1.0, 0.0) for _ in vertices], faces[:]
    cos_threshold = math.cos(math.radians(crease_angle_degrees))
    face_normals = _compute_face_normals(vertices, faces)
    vertex_faces: List[List[int]] = [[] for _ in vertices]
    for face_idx, face in enumerate(faces):
        for vid in face:
            if 0 <= vid < len(vertices):
                vertex_faces[vid].append(face_idx)
    face_vertex_map: Dict[Tuple[int, int], int] = {}
    new_vertices: List[Tuple[float, float, float]] = []
    new_normals: List[Tuple[float, float, float]] = []
    for vid, adjacent_faces in enumerate(vertex_faces):
        if not adjacent_faces:
            new_index = len(new_vertices)
            new_vertices.append(vertices[vid])
            new_normals.append((0.0, 1.0, 0.0))
            continue
        groups: List[Dict[str, object]] = []
        for face_idx in adjacent_faces:
            normal = face_normals[face_idx]
            assigned_group = None
            for group in groups:
                rep = group["representative"]
                dot_product = (
                    normal[0] * rep[0] + normal[1] * rep[1] + normal[2] * rep[2]
                )
                if dot_product >= cos_threshold:
                    assigned_group = group
                    break
            if not assigned_group:
                assigned_group = {
                    "faces": [],
                    "normal_sum": [0.0, 0.0, 0.0],
                    "representative": normal,
                }
                groups.append(assigned_group)
            assigned_group["faces"].append(face_idx)
            assigned_group["normal_sum"][0] += normal[0]
            assigned_group["normal_sum"][1] += normal[1]
            assigned_group["normal_sum"][2] += normal[2]
            assigned_group["representative"] = _normalize_vector(
                (
                    assigned_group["normal_sum"][0],
                    assigned_group["normal_sum"][1],
                    assigned_group["normal_sum"][2],
                )
            )
        for group in groups:
            normal_vec = _normalize_vector(
                (
                    group["normal_sum"][0],
                    group["normal_sum"][1],
                    group["normal_sum"][2],
                )
            )
            new_index = len(new_vertices)
            new_vertices.append(vertices[vid])
            new_normals.append(normal_vec)
            for face_idx in group["faces"]:
                face_vertex_map[(face_idx, vid)] = new_index
    remapped_faces: List[Tuple[int, int, int]] = []
    for face_idx, face in enumerate(faces):
        remapped = []
        for vid in face:
            key = (face_idx, vid)
            if key in face_vertex_map:
                remapped.append(face_vertex_map[key])
            else:
                new_index = len(new_vertices)
                new_vertices.append(vertices[vid])
                new_normals.append(face_normals[face_idx])
                face_vertex_map[key] = new_index
                remapped.append(new_index)
        remapped_faces.append(tuple(remapped))
    return new_vertices, new_normals, remapped_faces


def meshes_to_geometries(
    meshes: Sequence[MeshData],
    mesh_colors: Dict[str, Union[str, Dict[str, object]]],
    color_service: IColorService,
) -> List[MeshGeometry]:
    geometries: List[MeshGeometry] = []
    for idx, mesh in enumerate(meshes):
        if not mesh or not mesh.vertices or not mesh.faces:
            continue
        vertices_raw = [tuple(v) for v in mesh.vertices]
        faces_raw = [tuple(face[:3]) for face in mesh.faces if len(face) >= 3]
        vertices, normals, faces = prepare_vertices_for_shading(vertices_raw, faces_raw)
        vertex_buffer: List[float] = []
        normal_buffer: List[float] = []
        for i, vertex in enumerate(vertices):
            tx, ty, tz = _transform_vertex(vertex)
            vertex_buffer.extend([tx, ty, tz])
            if i < len(normals):
                nn = normals[i]
                tnx, tny, tnz = _transform_normal(nn)
                normal_buffer.extend([tnx, tny, tnz])
        index_buffer: List[int] = []
        for face in faces:
            if not face:
                continue
            index_buffer.extend([int(face[0]), int(face[1]), int(face[2])])
        if not vertex_buffer or not index_buffer:
            continue
        color_entry = mesh_colors.get(f"mesh_{idx}", "#808080")
        color, opacity = color_service.as_hex_with_opacity(color_entry)
        condition_uid = ""
        takeoff_uid = ""
        page_uid = ""
        if isinstance(color_entry, dict):
            condition_uid = str(color_entry.get("condition_uid", ""))
            takeoff_uid = str(color_entry.get("takeoff_uid", ""))
            page_uid = str(color_entry.get("page_uid", ""))
        geometry = MeshGeometry(
            vertices=vertex_buffer,
            normals=normal_buffer,
            indices=index_buffer,
            color=color,
            opacity=opacity,
            page_uid=page_uid,
            condition_uid=condition_uid,
            takeoff_uid=takeoff_uid,
        )
        geometries.append(geometry)
    return geometries


def get_radial_mesh_edges(segments: int) -> List[List[int]]:
    edges = []
    for offset in [0, segments]:
        edges.extend(
            [[offset + i, offset + (i + 1) % segments] for i in range(segments)]
        )
    edges.extend([[i, segments + i] for i in range(segments)])
    return edges


def get_radial_mesh_faces(segments: int) -> List[List[int]]:
    faces = []
    c_b, c_t = 2 * segments, 2 * segments + 1
    for i in range(segments):
        j = (i + 1) % segments
        faces.append([c_b, i, j])
        faces.append([c_t, segments + j, segments + i])
    for i in range(segments):
        j = (i + 1) % segments
        faces.extend([[i, segments + i, segments + j], [i, segments + j, j]])
    return faces


def get_rhombus_mesh_edges() -> List[List[int]]:
    edges = [
        [0, 1],
        [1, 2],
        [2, 3],
        [3, 0],
        [4, 5],
        [5, 6],
        [6, 7],
        [7, 4],
        [0, 4],
        [1, 5],
        [2, 6],
        [3, 7],
    ]
    return edges


def get_rhombus_mesh_faces() -> List[List[int]]:
    faces = [
        [0, 3, 2],
        [0, 2, 1],
        [4, 5, 6],
        [4, 6, 7],
        [0, 1, 5],
        [0, 5, 4],
        [1, 2, 6],
        [1, 6, 5],
        [2, 3, 7],
        [2, 7, 6],
        [3, 0, 4],
        [3, 4, 7],
    ]
    return faces


def get_triangle_mesh_edges() -> List[List[int]]:
    edges = [
        [0, 1],
        [1, 2],
        [2, 0],
        [3, 4],
        [4, 5],
        [5, 3],
        [0, 3],
        [1, 4],
        [2, 5],
    ]
    return edges


def get_triangle_mesh_faces() -> List[List[int]]:
    faces = [
        [0, 2, 1],
        [3, 4, 5],
        [0, 1, 4],
        [0, 4, 3],
        [1, 2, 5],
        [1, 5, 4],
        [2, 0, 3],
        [2, 3, 5],
    ]
    return faces
