"""Build the shipped tower crane kit from the Sketchfab original.
Usage (from the repository root, with the project venv)::
    .\\venv\\Scripts\\python.exe tools\\prepare_tower_crane_asset.py
Reads ``assets/models/tower_crane.source.glb`` ("Tower Crane" by Chamod on
Sketchfab, CC BY 4.0) and writes
``ost_visualizer/resources/models/tower_crane_kit.glb``: the crane cut into
reusable parts, one glTF node per part, which both viewers assemble from a
layout computed in Python (``tower_crane_layout.py``).
* node transforms are baked; the origin is the mast axis (the centre of the
  four mast legs) on top of the model's own footing, so ``(0, 0, 0)`` sits on
  top of the count takeoff that is the footing;
* every source node is assigned to a part by an explicit table (an unassigned
  node fails the build). The model's footing, tie bars and hoist ropes are
  dropped: the takeoff is the footing and every rope is generated;
* the mast, jib and counterjib are cut at their lattice bay planes. Long
  members (legs, chords, rails) are clipped; short pieces (rungs, gussets,
  diagonals) go whole to the bay that holds their centre. The mast and jib
  keep two alternating bays each because their diagonals zigzag. The tool
  checks that the model really repeats and that its pitches match
  ``ost_visualizer/domain/entities/tower_crane_spec.py``;
* textures, UVs and images are dropped; each material gets the area-weighted
  median of its base texture sampled at the UVs its triangles use. The factors
  hold display (sRGB) values on purpose: both viewers draw raw colours;
* the counter-jib walkway grating (16k triangles on one plane) becomes a thin
  plate;
* edge lines are baked per part as glTF LINES primitives (boundary and crease
  edges, without the seams the slicing creates), so both viewers draw the
  same edges;
* positions are int16 and normals int8 through ``KHR_mesh_quantization``, each
  part about its own origin with one shared scale;
* ``asset.extras.kit`` carries the layout metadata (pitches, attach points,
  part bounds). glTF conventions are kept: metres, Y-up, jib along +X.
"""

from __future__ import annotations
import argparse
import bisect
import json
import math
import struct
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "assets" / "models" / "tower_crane.source.glb"
FOOTING_NODE_PREFIX = "Cube.073"
MAST_LEGS_NODE_PREFIX = "Cube.052"
GLASS_MATERIAL = "GLASS"
GLASS_ALPHA = 0.5
PLATE_MIN_THICKNESS = 0.02
MAX_BYTES = 1_000_000
Matrix = List[List[float]]
Vec3 = Tuple[float, float, float]
_COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
_FORMATS = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}


def _read_glb(path: Path) -> Tuple[dict, bytes]:
    data = path.read_bytes()
    magic, version, _length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF" or version != 2:
        raise ValueError(f"{path} is not a glTF 2.0 binary")
    json_length, json_type = struct.unpack_from("<I4s", data, 12)
    if json_type != b"JSON":
        raise ValueError("first GLB chunk is not JSON")
    document = json.loads(data[20 : 20 + json_length])
    offset = 20 + json_length
    bin_length, bin_type = struct.unpack_from("<I4s", data, offset)
    if bin_type != b"BIN\x00":
        raise ValueError("second GLB chunk is not BIN")
    return document, data[offset + 8 : offset + 8 + bin_length]


def _accessor(document: dict, binary: bytes, index: int) -> List[Tuple[float, ...]]:
    accessor = document["accessors"][index]
    view = document["bufferViews"][accessor["bufferView"]]
    fmt = _FORMATS[accessor["componentType"]]
    components = _COMPONENTS[accessor["type"]]
    item = struct.calcsize("<" + fmt * components)
    stride = view.get("byteStride") or item
    start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    unpack = struct.Struct("<" + fmt * components).unpack_from
    return [unpack(binary, start + i * stride) for i in range(accessor["count"])]


def _multiply(a: Matrix, b: Matrix) -> Matrix:
    return [
        [sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)
    ]


def _local_matrix(node: dict) -> Matrix:
    if "matrix" in node:
        m = node["matrix"]
        return [[m[c * 4 + r] for c in range(4)] for r in range(4)]
    result = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
    if "scale" in node:
        sx, sy, sz = node["scale"]
        result = _multiply(
            result, [[sx, 0, 0, 0], [0, sy, 0, 0], [0, 0, sz, 0], [0, 0, 0, 1]]
        )
    if "rotation" in node:
        x, y, z, w = node["rotation"]
        rotation = [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0],
            [0, 0, 0, 1],
        ]
        result = _multiply(rotation, result)
    if "translation" in node:
        tx, ty, tz = node["translation"]
        result = _multiply(
            [[1, 0, 0, tx], [0, 1, 0, ty], [0, 0, 1, tz], [0, 0, 0, 1]], result
        )
    return result


def _determinant(m: Matrix) -> float:
    a = [row[:3] for row in m[:3]]
    return (
        a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
        - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
        + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0])
    )


def _normal_matrix(m: Matrix) -> Matrix:
    a = [row[:3] for row in m[:3]]
    cofactor = [
        [
            a[(i + 1) % 3][(j + 1) % 3] * a[(i + 2) % 3][(j + 2) % 3]
            - a[(i + 1) % 3][(j + 2) % 3] * a[(i + 2) % 3][(j + 1) % 3]
            for j in range(3)
        ]
        for i in range(3)
    ]
    # The cofactor matrix is det * inverse-transpose; normals are renormalized.
    # A mirrored transform has a negative det, which would turn every normal
    # inside out, so keep the direction of the inverse-transpose itself.
    if _determinant(m) < 0:
        cofactor = [[-value for value in row] for row in cofactor]
    return cofactor


def _apply(m: Matrix, v: Sequence[float]) -> Vec3:
    return tuple(
        m[r][0] * v[0] + m[r][1] * v[1] + m[r][2] * v[2] + m[r][3] for r in range(3)
    )


def _apply3(m: Matrix, v: Sequence[float]) -> Vec3:
    x, y, z = (m[r][0] * v[0] + m[r][1] * v[1] + m[r][2] * v[2] for r in range(3))
    length = math.sqrt(x * x + y * y + z * z) or 1.0
    return (x / length, y / length, z / length)


def _face_normal(a: Vec3, b: Vec3, c: Vec3) -> Vec3:
    u = [b[i] - a[i] for i in range(3)]
    w = [c[i] - a[i] for i in range(3)]
    n = (
        u[1] * w[2] - u[2] * w[1],
        u[2] * w[0] - u[0] * w[2],
        u[0] * w[1] - u[1] * w[0],
    )
    length = math.sqrt(sum(x * x for x in n)) or 1.0
    return (n[0] / length, n[1] / length, n[2] / length)


class _Part:
    def __init__(self, name: str) -> None:
        self.name = name
        self.triangles: List[Tuple[Tuple[Vec3, Vec3], ...]] = []
        # (u, v, area) at each triangle centroid, for the texture colour.
        self.samples: List[Tuple[float, float, float]] = []


def _triangle_area(a: Vec3, b: Vec3, c: Vec3) -> float:
    u = [b[i] - a[i] for i in range(3)]
    w = [c[i] - a[i] for i in range(3)]
    n = (
        u[1] * w[2] - u[2] * w[1],
        u[2] * w[0] - u[0] * w[2],
        u[0] * w[1] - u[1] * w[0],
    )
    return 0.5 * math.sqrt(sum(x * x for x in n))


def _collect_parts(
    document: dict, binary: bytes
) -> Tuple[Dict[int, _Part], List[Vec3], List[Vec3]]:
    parts: Dict[int, _Part] = {}
    footing: List[Vec3] = []
    mast_legs: List[Vec3] = []
    identity = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]

    def walk(index: int, parent: Matrix, name_chain: str) -> None:
        node = document["nodes"][index]
        world = _multiply(parent, _local_matrix(node))
        name = node.get("name", "")
        chain = f"{name_chain}/{name}"
        if "mesh" in node:
            normal_matrix = _normal_matrix(world)
            # A mirrored node reverses its triangles' winding; swap it back.
            mirrored = _determinant(world) < 0
            for primitive in document["meshes"][node["mesh"]]["primitives"]:
                if primitive.get("mode", 4) != 4:
                    continue
                attributes = primitive["attributes"]
                positions = [
                    _apply(world, p)
                    for p in _accessor(document, binary, attributes["POSITION"])
                ]
                normals = None
                if "NORMAL" in attributes:
                    normals = [
                        _apply3(normal_matrix, n)
                        for n in _accessor(document, binary, attributes["NORMAL"])
                    ]
                uvs = None
                if "TEXCOORD_0" in attributes:
                    uvs = _accessor(document, binary, attributes["TEXCOORD_0"])
                if "indices" in primitive:
                    indices = [
                        i[0] for i in _accessor(document, binary, primitive["indices"])
                    ]
                else:
                    indices = list(range(len(positions)))
                if FOOTING_NODE_PREFIX in chain:
                    footing.extend(positions)
                    continue
                if MAST_LEGS_NODE_PREFIX in chain:
                    mast_legs.extend(positions)
                material = primitive.get("material", 0)
                part = parts.setdefault(
                    material,
                    _Part(
                        document["materials"][material].get(
                            "name", f"material{material}"
                        )
                    ),
                )
                for t in range(0, len(indices) - 2, 3):
                    ia, ib, ic = indices[t : t + 3]
                    if mirrored:
                        ib, ic = ic, ib
                    a, b, c = positions[ia], positions[ib], positions[ic]
                    if uvs is not None:
                        u = (uvs[ia][0] + uvs[ib][0] + uvs[ic][0]) / 3.0
                        v = (uvs[ia][1] + uvs[ib][1] + uvs[ic][1]) / 3.0
                        part.samples.append((u, v, _triangle_area(a, b, c)))
                    if normals is None:
                        n = _face_normal(a, b, c)
                        part.triangles.append(((a, n), (b, n), (c, n)))
                    else:
                        part.triangles.append(
                            ((a, normals[ia]), (b, normals[ib]), (c, normals[ic]))
                        )
        for child in node.get("children", []):
            walk(child, world, chain)

    for root in document["scenes"][document.get("scene", 0)]["nodes"]:
        walk(root, identity, "")
    if not footing:
        raise ValueError(f"footing node {FOOTING_NODE_PREFIX!r} not found")
    return parts, footing, mast_legs


def _base_origin(mast_legs: List[Vec3], footing: List[Vec3]) -> Vec3:
    """The mast axis (centre of the four mast legs) on top of the footing."""
    if not mast_legs:
        raise ValueError(f"mast legs node {MAST_LEGS_NODE_PREFIX!r} not found")
    slab_top = max(p[1] for p in footing)
    cx = (min(p[0] for p in mast_legs) + max(p[0] for p in mast_legs)) / 2.0
    cz = (min(p[2] for p in mast_legs) + max(p[2] for p in mast_legs)) / 2.0
    return (cx, slab_top, cz)


def _weighted_median(values: List[Tuple[float, float]]) -> float:
    values.sort()
    half = sum(weight for _, weight in values) / 2.0
    running = 0.0
    for value, weight in values:
        running += weight
        if running >= half:
            return value
    return values[-1][0]


def _texture_colours(
    document: dict, binary: bytes, parts: Dict[int, _Part]
) -> Dict[int, Tuple[float, float, float]]:
    from PySide6.QtGui import QImage

    colours: Dict[int, Tuple[float, float, float]] = {}
    for index, part in parts.items():
        material = document["materials"][index]
        pbr = material.get("pbrMetallicRoughness", {})
        factor = pbr.get("baseColorFactor", [1.0, 1.0, 1.0, 1.0])
        rgb = [1.0, 1.0, 1.0]
        texture_info = pbr.get("baseColorTexture")
        if texture_info is not None and part.samples:
            image_index = document["textures"][texture_info["index"]]["source"]
            view = document["bufferViews"][
                document["images"][image_index]["bufferView"]
            ]
            start = view.get("byteOffset", 0)
            image = QImage.fromData(binary[start : start + view["byteLength"]])
            if image.isNull():
                raise ValueError(f"cannot decode the texture of material {index}")
            width, height = image.width(), image.height()
            channels: List[List[Tuple[float, float]]] = [[], [], []]
            for u, v, area in part.samples:
                pixel = image.pixelColor(
                    int((u % 1.0) * width) % width, int((v % 1.0) * height) % height
                )
                for k, value in enumerate(
                    (pixel.redF(), pixel.greenF(), pixel.blueF())
                ):
                    channels[k].append((value, area))
            rgb = [_weighted_median(channel) for channel in channels]
        colours[index] = (rgb[0] * factor[0], rgb[1] * factor[1], rgb[2] * factor[2])
    return colours


def _pad4(data: bytearray) -> None:
    while len(data) % 4:
        data.append(0)


# ---------------------------------------------------------------------------
# Kit: the crane cut into reusable parts (one glTF node per part)
# ---------------------------------------------------------------------------
KIT_TARGET = REPO / "ost_visualizer" / "resources" / "models" / "tower_crane_kit.glb"
KIT_VERSION = 1
KIT_MODIFIED = (
    "cut into reusable parts (base, mast bays, slewing unit, tower head, jib bays, "
    "counterjib sections, trolley, hook block); textures removed (flat material "
    "colours), primitives welded, positions and normals quantized, edge lines "
    "baked, base slab, tie bars and ropes removed (ropes are generated), origin "
    "moved to the mast base"
)
ROPE_MATERIAL = "ROPE"
ROPE_RADIUS = 0.03
ROPE_SIDES = 6
EDGE_CREASE_DEGREES = 15.0
DEFAULT_MAST_BAYS = 25
DEFAULT_JIB_BAYS = 18
DEFAULT_COUNTERJIB_SECTIONS = 7
MAST_CANONICAL_BAYS = (10, 11)
JIB_CANONICAL_BAYS = (2, 3)
COUNTERJIB_CANONICAL_SECTION = 2
# The source model's jib diagonals wander up to about 7 cm from a perfect grid.
JIB_PERIOD_TOLERANCE = 0.08


def _numbered(prefix: str, first: int, last: int) -> Tuple[str, ...]:
    return tuple(f"{prefix}.{number:03d}" for number in range(first, last + 1))


MAST_LATTICE_NODES = _numbered("Cube", 74, 85)
MAST_NODES = ("Cube.052",) + MAST_LATTICE_NODES + ("Cylinder.016", "Plane.029")
JIB_LATTICE_NODES = ("Cube.102", "Cube.103")
JIB_NODES = ("Cube.055", "Plane.023") + JIB_LATTICE_NODES
JIB_LUG_NODES = ("Cube.070", "Plane.027")
COUNTERJIB_POST_NODES = ("Cube.057", "Cube.058")
COUNTERJIB_PLATE_NODE = "Cube.056"
COUNTERJIB_NODES = (
    "Cube.054",
    "Plane.024",
    COUNTERJIB_PLATE_NODE,
) + COUNTERJIB_POST_NODES
SHEAVE_NODES = ("Cylinder.010", "Cylinder.011")
HOIST_ROPE_NODES = ("Plane.005_Curve.002", "Plane.005_Curve.003")
JIB_TIE_NODES = ("Plane.026", "Plane.028", "Plane.030", "Plane.032")
COUNTERJIB_TIE_NODES = ("Plane.034", "Plane.035")
RIGID_PART_NODES: Dict[str, Tuple[str, ...]] = {
    "slewing": ("Cube.086", "Cube.087", "Cylinder.017", "Cube.100", "Cube.101")
    + ("Cylinder.018", "Cylinder.019", "Plane.043", "Plane.044", "Plane.045")
    + ("Cube.072",)
    + _numbered("Slice", 5, 9),
    "head": ("Cube.053", "Cube.059", "Cube.069")
    + _numbered("Cube", 88, 99)
    + ("Plane.040", "Plane.041", "Plane.038", "Plane.039")
    + _numbered("Cylinder", 12, 15),
    "counterweight": ("Cube.060", "Cube.061"),
    "cjib_lug": ("Cube.071", "Plane.036", "Plane.037"),
    "trolley": _numbered("Cube", 62, 67) + SHEAVE_NODES,
    "hook_block": ("Cube.068", "Plane.025"),
}
# The model's own footing, tie bars and hoist ropes are not shipped (the count
# takeoff is the footing and every rope is generated from the layout), and the
# outer jib lug pieces are replaced by a second instance of the inner lug.
DROPPED_NODES = (
    (FOOTING_NODE_PREFIX, "Plane.031", "Plane.033")
    + JIB_TIE_NODES
    + COUNTERJIB_TIE_NODES
    + HOIST_ROPE_NODES
)
KIT_PART_ORDER = (
    "base",
    "mast_a",
    "mast_b",
    "slewing",
    "head",
    "jib_root",
    "jib_a",
    "jib_b",
    "jib_tip",
    "jib_lug",
    "cjib_root",
    "cjib_section",
    "cjib_end",
    "counterweight",
    "cjib_lug",
    "trolley",
    "hook_block",
    "rope",
)
Vertex = Tuple[Vec3, Vec3]
Triangle = Tuple[Vertex, Vertex, Vertex, int]


def _node_key(name: str) -> str:
    """``Cube.052_UV_0`` -> ``Cube.052`` (the mesh node name without material)."""
    return name.rsplit("_", 2)[0]


def _collect_nodes(document: dict, binary: bytes) -> Dict[str, List[Triangle]]:
    """World-space triangles ``(vertex, vertex, vertex, material)`` per mesh node."""
    nodes: Dict[str, List[Triangle]] = {}
    identity = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]

    def walk(index: int, parent: Matrix) -> None:
        node = document["nodes"][index]
        world = _multiply(parent, _local_matrix(node))
        if "mesh" in node:
            normal_matrix = _normal_matrix(world)
            mirrored = _determinant(world) < 0
            triangles = nodes.setdefault(_node_key(node.get("name", "")), [])
            for primitive in document["meshes"][node["mesh"]]["primitives"]:
                if primitive.get("mode", 4) != 4:
                    continue
                attributes = primitive["attributes"]
                positions = [
                    _apply(world, p)
                    for p in _accessor(document, binary, attributes["POSITION"])
                ]
                normals = None
                if "NORMAL" in attributes:
                    normals = [
                        _apply3(normal_matrix, n)
                        for n in _accessor(document, binary, attributes["NORMAL"])
                    ]
                if "indices" in primitive:
                    indices = [
                        i[0] for i in _accessor(document, binary, primitive["indices"])
                    ]
                else:
                    indices = list(range(len(positions)))
                material = primitive.get("material", 0)
                for t in range(0, len(indices) - 2, 3):
                    ia, ib, ic = indices[t : t + 3]
                    if mirrored:
                        ib, ic = ic, ib
                    a, b, c = positions[ia], positions[ib], positions[ic]
                    if normals is None:
                        n = _face_normal(a, b, c)
                        triangles.append(((a, n), (b, n), (c, n), material))
                    else:
                        triangles.append(
                            (
                                (a, normals[ia]),
                                (b, normals[ib]),
                                (c, normals[ic]),
                                material,
                            )
                        )
        for child in node.get("children", []):
            walk(child, world)

    for root in document["scenes"][document.get("scene", 0)]["nodes"]:
        walk(root, identity)
    return nodes


def _components(
    triangles: Sequence[Triangle], tolerance: float = 1e-3
) -> List[List[Triangle]]:
    """Triangles grouped into pieces that share vertex positions."""
    parent: Dict[Tuple[int, int, int], Tuple[int, int, int]] = {}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    first_keys = []
    for triangle in triangles:
        keys = [
            tuple(round(c / tolerance) for c in vertex[0]) for vertex in triangle[:3]
        ]
        for key in keys:
            parent.setdefault(key, key)
        parent[find(keys[0])] = find(keys[1])
        parent[find(keys[1])] = find(keys[2])
        first_keys.append(keys[0])
    groups: Dict[Tuple[int, int, int], List[Triangle]] = {}
    for triangle, key in zip(triangles, first_keys):
        groups.setdefault(find(key), []).append(triangle)
    return list(groups.values())


def _extent(triangles: Sequence[Triangle], axis: int) -> Tuple[float, float]:
    values = [vertex[0][axis] for triangle in triangles for vertex in triangle[:3]]
    return min(values), max(values)


def _clip_polygon(
    polygon: List[Vertex], axis: int, value: float, keep_above: bool
) -> List[Vertex]:
    """Sutherland-Hodgman clip of a convex polygon against an axis plane."""
    clipped: List[Vertex] = []
    for index, current in enumerate(polygon):
        following = polygon[(index + 1) % len(polygon)]
        current_inside = (
            current[0][axis] >= value if keep_above else current[0][axis] <= value
        )
        following_inside = (
            following[0][axis] >= value if keep_above else following[0][axis] <= value
        )
        if current_inside:
            clipped.append(current)
        if current_inside != following_inside:
            t = (value - current[0][axis]) / (following[0][axis] - current[0][axis])
            position = [
                current[0][k] + t * (following[0][k] - current[0][k]) for k in range(3)
            ]
            position[axis] = value
            normal = [
                current[1][k] + t * (following[1][k] - current[1][k]) for k in range(3)
            ]
            length = math.sqrt(sum(c * c for c in normal)) or 1.0
            clipped.append((tuple(position), tuple(c / length for c in normal)))
    return clipped


def _clip_triangles(
    triangles: Sequence[Triangle], axis: int, low: float | None, high: float | None
) -> List[Triangle]:
    """The part of each triangle between two axis planes (either may be open)."""
    result: List[Triangle] = []
    for triangle in triangles:
        polygon = list(triangle[:3])
        if low is not None:
            polygon = _clip_polygon(polygon, axis, low, True)
        if high is not None and len(polygon) >= 3:
            polygon = _clip_polygon(polygon, axis, high, False)
        for index in range(1, len(polygon) - 1):
            a, b, c = polygon[0], polygon[index], polygon[index + 1]
            if _triangle_area(a[0], b[0], c[0]) > 1e-12:
                result.append((a, b, c, triangle[3]))
    return result


def _split_along(
    triangles: Sequence[Triangle],
    axis: int,
    planes: Sequence[float],
    whole_limit: float,
) -> List[List[Triangle]]:
    """Split triangles into ``len(planes) + 1`` slabs along ``axis``.
    A connected piece no longer than ``whole_limit`` (a rung, a gusset, one
    diagonal) goes whole to the slab that holds its centre, so it is never cut.
    Longer pieces (legs, chords, rails) are clipped at the planes.
    """
    planes = list(planes)
    slabs: List[List[Triangle]] = [[] for _ in range(len(planes) + 1)]
    for component in _components(triangles):
        low, high = _extent(component, axis)
        if high - low <= whole_limit:
            slabs[bisect.bisect_right(planes, (low + high) / 2.0)].extend(component)
            continue
        first = bisect.bisect_right(planes, low)
        last = bisect.bisect_left(planes, high)
        for index in range(first, last + 1):
            slab_low = planes[index - 1] if index > 0 else None
            slab_high = planes[index] if index < len(planes) else None
            slabs[index].extend(_clip_triangles(component, axis, slab_low, slab_high))
    return slabs


def _shift(triangles: Sequence[Triangle], origin: Vec3) -> List[Triangle]:
    return [
        tuple(
            (tuple(vertex[0][k] - origin[k] for k in range(3)), vertex[1])
            for vertex in triangle[:3]
        )
        + (triangle[3],)
        for triangle in triangles
    ]


def _box_triangles(low: Vec3, high: Vec3, material: int) -> List[Triangle]:
    corners = [
        (x, y, z)
        for x in (low[0], high[0])
        for y in (low[1], high[1])
        for z in (low[2], high[2])
    ]
    faces = (
        ((0, 1, 3, 2), (-1.0, 0.0, 0.0)),
        ((4, 6, 7, 5), (1.0, 0.0, 0.0)),
        ((0, 4, 5, 1), (0.0, -1.0, 0.0)),
        ((2, 3, 7, 6), (0.0, 1.0, 0.0)),
        ((0, 2, 6, 4), (0.0, 0.0, -1.0)),
        ((1, 5, 7, 3), (0.0, 0.0, 1.0)),
    )
    triangles: List[Triangle] = []
    for (a, b, c, d), normal in faces:
        for i, j, k in ((a, b, c), (a, c, d)):
            triangles.append(
                (
                    (corners[i], normal),
                    (corners[j], normal),
                    (corners[k], normal),
                    material,
                )
            )
    return triangles


def _plate_node(triangles: Sequence[Triangle]) -> List[Triangle]:
    """A flat, dense node (the walkway grating) as the thin box that bounds it."""
    low = [_extent(triangles, k)[0] for k in range(3)]
    high = [_extent(triangles, k)[1] for k in range(3)]
    if high[1] - low[1] < PLATE_MIN_THICKNESS:
        middle = (low[1] + high[1]) / 2.0
        low[1] = middle - PLATE_MIN_THICKNESS / 2.0
        high[1] = middle + PLATE_MIN_THICKNESS / 2.0
    return _box_triangles(tuple(low), tuple(high), triangles[0][3])


def _rope_triangles(material: int) -> List[Triangle]:
    """A unit rope: a prism along +Y from 0 to 1 m with smooth sides."""
    ring = [
        (
            math.cos(2.0 * math.pi * i / ROPE_SIDES),
            math.sin(2.0 * math.pi * i / ROPE_SIDES),
        )
        for i in range(ROPE_SIDES)
    ]
    triangles: List[Triangle] = []
    for i in range(ROPE_SIDES):
        (x0, z0), (x1, z1) = ring[i], ring[(i + 1) % ROPE_SIDES]
        a = ((x0 * ROPE_RADIUS, 0.0, z0 * ROPE_RADIUS), (x0, 0.0, z0))
        b = ((x1 * ROPE_RADIUS, 0.0, z1 * ROPE_RADIUS), (x1, 0.0, z1))
        c = ((x1 * ROPE_RADIUS, 1.0, z1 * ROPE_RADIUS), (x1, 0.0, z1))
        d = ((x0 * ROPE_RADIUS, 1.0, z0 * ROPE_RADIUS), (x0, 0.0, z0))
        triangles.append((a, c, b, material))
        triangles.append((a, d, c, material))
        for y, normal, flip in (
            (0.0, (0.0, -1.0, 0.0), False),
            (1.0, (0.0, 1.0, 0.0), True),
        ):
            centre = ((0.0, y, 0.0), normal)
            p = ((x0 * ROPE_RADIUS, y, z0 * ROPE_RADIUS), normal)
            q = ((x1 * ROPE_RADIUS, y, z1 * ROPE_RADIUS), normal)
            triangles.append(
                (centre, q, p, material) if flip else (centre, p, q, material)
            )
    return triangles


def _same_points(
    first: Sequence[Vec3], second: Sequence[Vec3], tolerance: float
) -> bool:
    """Whether two point sets match one to one within ``tolerance``."""
    if len(first) != len(second):
        return False
    remaining = list(second)
    for point in first:
        best = min(
            range(len(remaining)),
            key=lambda i: sum((remaining[i][k] - point[k]) ** 2 for k in range(3)),
            default=None,
        )
        if best is None or math.dist(point, remaining[best]) > tolerance:
            return False
        remaining.pop(best)
    return True


def _assert_periodic(
    slabs: Sequence[Sequence[Triangle]],
    indices: Sequence[int],
    canonical: Tuple[int, int],
    axis: int,
    pitch: float,
    tolerance: float,
    label: str,
) -> None:
    """Every listed slab must repeat the canonical slab of its parity."""

    def points(index: int) -> List[Vec3]:
        seen = {}
        for triangle in slabs[index]:
            for vertex in triangle[:3]:
                moved = list(vertex[0])
                moved[axis] -= index * pitch
                seen[tuple(round(c, 4) for c in moved)] = tuple(moved)
        return list(seen.values())

    for index in indices:
        reference = canonical[(index - canonical[0]) % 2]
        if not _same_points(points(index), points(reference), tolerance):
            raise ValueError(
                f"{label} {index} does not repeat {label} {reference} within "
                f"{tolerance} m; the model is not periodic there"
            )


def _feature_edges(
    positions: Sequence[Vec3], indices: Sequence[int], cuts: Sequence[Tuple[int, float]]
) -> List[int]:
    """Boundary and crease edges as vertex index pairs (the renderer's rule).
    Boundary edges that lie on a slicing plane are left out: they are seams
    between repeated parts, not real edges.
    """
    canonical: List[int] = []
    by_position: Dict[Tuple[int, int, int], int] = {}
    for index, position in enumerate(positions):
        key = tuple(round(c * 1.0e4) for c in position)
        canonical.append(by_position.setdefault(key, index))
    crease = math.cos(math.radians(EDGE_CREASE_DEGREES))
    face_normals: List[Vec3] = []
    open_edges: Dict[Tuple[int, int], Tuple[int, int, int]] = {}
    lines: List[int] = []
    for face in range(len(indices) // 3):
        corners = indices[face * 3 : face * 3 + 3]
        face_normals.append(_face_normal(*(positions[i] for i in corners)))
        for edge in range(3):
            va, vb = corners[edge], corners[(edge + 1) % 3]
            ca, cb = canonical[va], canonical[vb]
            if ca == cb:
                continue
            key = (min(ca, cb), max(ca, cb))
            other = open_edges.pop(key, None)
            if other is None:
                open_edges[key] = (face, va, vb)
                continue
            first = face_normals[other[0]]
            if sum(first[k] * face_normals[face][k] for k in range(3)) < crease:
                lines.extend((other[1], other[2]))

    def on_a_cut(va: int, vb: int) -> bool:
        return any(
            abs(positions[va][axis] - value) < 1e-3
            and abs(positions[vb][axis] - value) < 1e-3
            for axis, value in cuts
        )

    for _face, va, vb in open_edges.values():
        if not on_a_cut(va, vb):
            lines.extend((va, vb))
    return lines


class _KitPart:
    def __init__(
        self,
        name: str,
        triangles: List[Triangle],
        cuts: Sequence[Tuple[int, float]] = (),
        edges: bool = True,
    ):
        self.name = name
        self.triangles = triangles
        self.cuts = tuple(cuts)
        self.edges = edges

    def bounds(self) -> Tuple[List[float], List[float]]:
        return (
            [_extent(self.triangles, k)[0] for k in range(3)],
            [_extent(self.triangles, k)[1] for k in range(3)],
        )


def _centre(triangles: Sequence[Triangle], axis: int) -> float:
    low, high = _extent(triangles, axis)
    return (low + high) / 2.0


def _measure_layout(nodes: Dict[str, List[Triangle]]) -> dict:
    """The model's own bay pitches and first-bay positions (crane frame)."""
    frames = sorted(_extent(c, 1)[0] for c in _components(nodes[MAST_LATTICE_NODES[0]]))
    diagonals = sorted(
        {round(_extent(c, 0)[0], 3) for c in _components(nodes["Cube.102"])}
    )
    posts = sorted(_centre(c, 0) for c in _components(nodes[COUNTERJIB_POST_NODES[0]]))
    post_gap = (posts[-1] - posts[0]) / (len(posts) - 1)
    return {
        "mast_base": frames[0],
        "mast_pitch": (frames[-1] - frames[0]) / (len(frames) - 1),
        "mast_bays": len(frames) - 1,
        "jib_first_bay": diagonals[0],
        "jib_pitch": (diagonals[-1] - diagonals[0]) / (2 * (len(diagonals) - 1)),
        "counterjib_first": posts[-1] + post_gap / 2.0,
        "counterjib_pitch": 2.0 * post_gap,
    }


def build_kit(source: Path, target: Path) -> dict:
    """Cut the source crane into the reusable parts of the kit GLB."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from ost_visualizer.domain.entities import tower_crane_spec as spec

    document, binary = _read_glb(source)
    parts_by_material, footing, mast_legs = _collect_parts(document, binary)
    origin = _base_origin(mast_legs, footing)
    colours = _texture_colours(document, binary, parts_by_material)
    material_names = [
        m.get("name", f"material{i}") for i, m in enumerate(document["materials"])
    ]
    nodes = {
        name: _shift(tris, origin)
        for name, tris in _collect_nodes(document, binary).items()
    }
    assigned = set(
        MAST_NODES + JIB_NODES + JIB_LUG_NODES + COUNTERJIB_NODES + DROPPED_NODES
    )
    for part_nodes in RIGID_PART_NODES.values():
        assigned.update(part_nodes)
    unassigned = sorted(set(nodes) - assigned)
    missing = sorted(assigned - set(nodes))
    if unassigned or missing:
        raise ValueError(
            f"kit node table is out of date: unassigned {unassigned}, missing {missing}"
        )
    measured = _measure_layout(nodes)
    expected = {
        "mast_base": spec.MAST_BASE_M,
        "mast_pitch": spec.MAST_PITCH_M,
        "mast_bays": DEFAULT_MAST_BAYS,
        "jib_first_bay": spec.JIB_FIRST_BAY_M,
        "jib_pitch": spec.JIB_PITCH_M,
        "counterjib_first": spec.COUNTERJIB_FIRST_M,
        "counterjib_pitch": spec.COUNTERJIB_PITCH_M,
    }
    for key, value in expected.items():
        if abs(measured[key] - value) > 0.005:
            raise ValueError(
                f"model {key} is {measured[key]:.4f} but tower_crane_spec expects {value}"
            )
    y0, mast_pitch = spec.MAST_BASE_M, spec.MAST_PITCH_M
    x0, jib_pitch = spec.JIB_FIRST_BAY_M, spec.JIB_PITCH_M
    c0, cjib_pitch = spec.COUNTERJIB_FIRST_M, spec.COUNTERJIB_PITCH_M
    y_top = y0 + DEFAULT_MAST_BAYS * mast_pitch
    parts: Dict[str, _KitPart] = {}

    def gather(names: Sequence[str]) -> List[Triangle]:
        return [triangle for name in names for triangle in nodes[name]]

    # Mast: base stub, two alternating bays, and what is left above the last bay.
    mast_planes = [y0 + k * mast_pitch for k in range(DEFAULT_MAST_BAYS + 1)]
    mast_slabs = _split_along(gather(MAST_NODES), 1, mast_planes, 1.2 * mast_pitch)
    lattice_slabs = _split_along(
        gather(MAST_LATTICE_NODES), 1, mast_planes, 1.2 * mast_pitch
    )
    _assert_periodic(
        lattice_slabs[1:-1],
        range(DEFAULT_MAST_BAYS),
        MAST_CANONICAL_BAYS,
        1,
        mast_pitch,
        0.03,
        "mast bay",
    )
    parts["base"] = _KitPart("base", mast_slabs[0], [(1, y0)])
    for name, bay in zip(("mast_a", "mast_b"), MAST_CANONICAL_BAYS):
        parts[name] = _KitPart(
            name,
            _shift(mast_slabs[bay + 1], (0.0, mast_planes[bay], 0.0)),
            [(1, 0.0), (1, mast_pitch)],
        )
    upper = (0.0, y_top, 0.0)
    parts["slewing"] = _KitPart(
        "slewing",
        _shift(mast_slabs[-1] + gather(RIGID_PART_NODES["slewing"]), upper),
        [(1, 0.0)],
    )
    parts["head"] = _KitPart("head", _shift(gather(RIGID_PART_NODES["head"]), upper))
    # Jib: a root bay, two alternating bays and the tip bay.
    jib_planes = [x0 + i * jib_pitch for i in range(1, DEFAULT_JIB_BAYS)]
    jib_slabs = _split_along(gather(JIB_NODES), 0, jib_planes, 1.2 * jib_pitch)
    jib_lattice = _split_along(
        gather(JIB_LATTICE_NODES), 0, jib_planes, 1.2 * jib_pitch
    )
    _assert_periodic(
        jib_lattice,
        range(1, DEFAULT_JIB_BAYS - 1),
        JIB_CANONICAL_BAYS,
        0,
        jib_pitch,
        JIB_PERIOD_TOLERANCE,
        "jib bay",
    )
    parts["jib_root"] = _KitPart(
        "jib_root", _shift(jib_slabs[0], upper), [(0, x0 + jib_pitch)]
    )
    for name, bay in zip(("jib_a", "jib_b"), JIB_CANONICAL_BAYS):
        parts[name] = _KitPart(
            name,
            _shift(jib_slabs[bay], (x0 + bay * jib_pitch, y_top, 0.0)),
            [(0, 0.0), (0, jib_pitch)],
        )
    tip_start = x0 + (DEFAULT_JIB_BAYS - 1) * jib_pitch
    parts["jib_tip"] = _KitPart(
        "jib_tip", _shift(jib_slabs[-1], (tip_start, y_top, 0.0)), [(0, 0.0)]
    )
    mid_jib = (x0 + tip_start) / 2.0

    def lug_side(names: Sequence[str], inner: bool) -> List[Triangle]:
        return [
            triangle
            for component in _components(gather(names))
            if (_centre(component, 0) < mid_jib) == inner
            for triangle in component
        ]

    inner_lug_x = _centre(lug_side(("Cube.070",), True), 0)
    outer_lug_x = _centre(lug_side(("Cube.070",), False), 0)
    parts["jib_lug"] = _KitPart(
        "jib_lug", _shift(lug_side(JIB_LUG_NODES, True), (inner_lug_x, y_top, 0.0))
    )
    # Counterjib: a short root, a repeated section and the end with its ballast.
    nodes[COUNTERJIB_PLATE_NODE] = _plate_node(nodes[COUNTERJIB_PLATE_NODE])
    mid_sections = DEFAULT_COUNTERJIB_SECTIONS - 1
    cjib_planes = sorted(c0 - k * cjib_pitch for k in range(mid_sections + 1))
    cjib_slabs = _split_along(
        gather(COUNTERJIB_NODES), 0, cjib_planes, 1.2 * cjib_pitch
    )
    post_slabs = _split_along(
        gather(COUNTERJIB_POST_NODES), 0, cjib_planes, 1.2 * cjib_pitch
    )
    # Slab ``mid_sections - k`` is section ``k`` counted outward from the mast.
    _assert_periodic(
        post_slabs[1:-1],
        range(mid_sections),
        (0, 0),
        0,
        cjib_pitch,
        0.01,
        "counterjib section",
    )
    end_plane = c0 - mid_sections * cjib_pitch
    parts["cjib_root"] = _KitPart("cjib_root", _shift(cjib_slabs[-1], upper), [(0, c0)])
    section_slab = mid_sections - COUNTERJIB_CANONICAL_SECTION
    parts["cjib_section"] = _KitPart(
        "cjib_section",
        _shift(
            cjib_slabs[section_slab],
            (c0 - COUNTERJIB_CANONICAL_SECTION * cjib_pitch, y_top, 0.0),
        ),
        [(0, 0.0), (0, -cjib_pitch)],
    )
    end_origin = (end_plane, y_top, 0.0)
    parts["cjib_end"] = _KitPart(
        "cjib_end", _shift(cjib_slabs[0], end_origin), [(0, 0.0)]
    )
    for name in ("counterweight", "cjib_lug"):
        parts[name] = _KitPart(name, _shift(gather(RIGID_PART_NODES[name]), end_origin))
    # Trolley, hook block and the unit rope.
    sheaves = [
        (_centre(nodes[name], 0), _centre(nodes[name], 1)) for name in SHEAVE_NODES
    ]
    trolley_x = (sheaves[0][0] + sheaves[1][0]) / 2.0
    sheave_y = (sheaves[0][1] + sheaves[1][1]) / 2.0
    rope_bottom = min(_extent(nodes[name], 1)[0] for name in HOIST_ROPE_NODES)
    rope_feet = [
        sum(v[0][0] for t in nodes[name] for v in t[:3] if v[0][1] < rope_bottom + 0.05)
        / max(
            1,
            sum(1 for t in nodes[name] for v in t[:3] if v[0][1] < rope_bottom + 0.05),
        )
        for name in HOIST_ROPE_NODES
    ]
    parts["trolley"] = _KitPart(
        "trolley", _shift(gather(RIGID_PART_NODES["trolley"]), (trolley_x, y_top, 0.0))
    )
    hook = gather(RIGID_PART_NODES["hook_block"])
    parts["hook_block"] = _KitPart(
        "hook_block", _shift(hook, (trolley_x, rope_bottom, 0.0))
    )
    rope_material = material_names.index(ROPE_MATERIAL)
    parts["rope"] = _KitPart("rope", _rope_triangles(rope_material), edges=False)
    inner_tie, outer_tie = nodes[JIB_TIE_NODES[0]], nodes[JIB_TIE_NODES[2]]
    cjib_tie = nodes[COUNTERJIB_TIE_NODES[0]]
    inner_bay = round((inner_lug_x - x0) / jib_pitch - 0.5)
    kit = {
        "version": KIT_VERSION,
        "frame": "metres, Y-up, jib along +X; origin = mast axis on top of the footing",
        "mast": {"base_y": y0, "pitch": mast_pitch, "default": DEFAULT_MAST_BAYS},
        "jib": {
            "first_bay_x": x0,
            "pitch": jib_pitch,
            "default": DEFAULT_JIB_BAYS,
            "tip_length": round(_extent(parts["jib_tip"].triangles, 0)[1], 4),
            "start_x": round(_extent(parts["jib_root"].triangles, 0)[0], 4),
            "lug_outer_dx": round(outer_lug_x - tip_start, 4),
            "lug_inner_dx": round(inner_lug_x - (x0 + inner_bay * jib_pitch), 4),
            "lug_inner_fraction": round(inner_bay / DEFAULT_JIB_BAYS, 4),
            "lug_inner_min_bays": 8,
        },
        "counterjib": {
            "first_x": c0,
            "pitch": cjib_pitch,
            "default": DEFAULT_COUNTERJIB_SECTIONS,
        },
        "anchors": {
            "head_jib": [
                round(_extent(inner_tie, 0)[0], 4),
                round(_extent(inner_tie, 1)[1] - y_top, 4),
            ],
            "head_counterjib": [
                round(_extent(cjib_tie, 0)[1], 4),
                round(_extent(cjib_tie, 1)[1] - y_top, 4),
            ],
            "jib_pendant": [
                round(_extent(inner_tie, 0)[1] - inner_lug_x, 4),
                round(_extent(inner_tie, 1)[0] - y_top, 4),
                round(max(abs(c) for c in _extent(inner_tie, 2)), 4),
            ],
            "jib_outer_pendant_dx": round(_extent(outer_tie, 0)[1] - outer_lug_x, 4),
            "counterjib_pendant": [
                round(_extent(cjib_tie, 0)[0] - end_plane, 4),
                round(_extent(cjib_tie, 1)[0] - y_top, 4),
                round(max(abs(c) for c in _extent(cjib_tie, 2)), 4),
            ],
            "hoist_top": [
                round((sheaves[1][0] - sheaves[0][0]) / 2.0, 4),
                round(sheave_y - y_top, 4),
            ],
            "hoist_bottom_dx": round((rope_feet[1] - rope_feet[0]) / 2.0, 4),
        },
        "hook": {
            "default_rope": round(sheave_y - rope_bottom, 4),
            "below_rope": round(rope_bottom - _extent(hook, 1)[0], 4),
        },
        "trolley": {"default_x": round(trolley_x, 4)},
        "rope_radius": ROPE_RADIUS,
        "parts": {},
    }
    scale = (
        max(
            abs(v[0][k])
            for part in parts.values()
            for t in part.triangles
            for v in t[:3]
            for k in range(3)
        )
        / 32767.0
    )
    buffer = bytearray()
    views: List[dict] = []
    accessors: List[dict] = []
    meshes: List[dict] = []
    gltf_nodes: List[dict] = []
    used_materials = sorted({t[3] for part in parts.values() for t in part.triangles})
    material_slot = {material: slot for slot, material in enumerate(used_materials)}
    report_parts = []
    for name in KIT_PART_ORDER:
        part = parts[name]
        low, high = part.bounds()
        kit["parts"][name] = {
            "min": [round(c, 4) for c in low],
            "max": [round(c, 4) for c in high],
        }
        primitives = []
        triangle_count = line_count = vertex_count = 0
        for material in used_materials:
            lookup: Dict[Tuple[int, ...], int] = {}
            positions: List[Vec3] = []
            normals: List[Tuple[int, int, int]] = []
            indices: List[int] = []
            for triangle in part.triangles:
                if triangle[3] != material:
                    continue
                for position, normal in triangle[:3]:
                    n = tuple(max(-127, min(127, round(c * 127.0))) for c in normal)
                    q = tuple(round(c / scale) for c in position)
                    index = lookup.setdefault(q + n, len(positions))
                    if index == len(positions):
                        positions.append(tuple(c * scale for c in q))
                        normals.append(n)
                    indices.append(index)
            if not indices:
                continue
            quantized = [tuple(round(c / scale) for c in p) for p in positions]
            _pad4(buffer)
            start = len(buffer)
            for q in quantized:
                buffer += struct.pack("<hhhh", q[0], q[1], q[2], 0)
            views.append(
                {
                    "buffer": 0,
                    "byteOffset": start,
                    "byteLength": len(buffer) - start,
                    "byteStride": 8,
                    "target": 34962,
                }
            )
            position_accessor = len(accessors)
            accessors.append(
                {
                    "bufferView": len(views) - 1,
                    "componentType": 5122,
                    "count": len(quantized),
                    "type": "VEC3",
                    "min": [min(q[k] for q in quantized) for k in range(3)],
                    "max": [max(q[k] for q in quantized) for k in range(3)],
                }
            )
            start = len(buffer)
            for n in normals:
                buffer += struct.pack("<bbbb", n[0], n[1], n[2], 0)
            views.append(
                {
                    "buffer": 0,
                    "byteOffset": start,
                    "byteLength": len(buffer) - start,
                    "byteStride": 4,
                    "target": 34962,
                }
            )
            normal_accessor = len(accessors)
            accessors.append(
                {
                    "bufferView": len(views) - 1,
                    "componentType": 5120,
                    "normalized": True,
                    "count": len(normals),
                    "type": "VEC3",
                }
            )

            def index_accessor(values: Sequence[int]) -> int:
                wide = len(positions) > 65535
                _pad4(buffer)
                begin = len(buffer)
                buffer.extend(
                    struct.pack(f"<{len(values)}{'I' if wide else 'H'}", *values)
                )
                views.append(
                    {
                        "buffer": 0,
                        "byteOffset": begin,
                        "byteLength": len(buffer) - begin,
                        "target": 34963,
                    }
                )
                accessors.append(
                    {
                        "bufferView": len(views) - 1,
                        "componentType": 5125 if wide else 5123,
                        "count": len(values),
                        "type": "SCALAR",
                    }
                )
                return len(accessors) - 1

            primitives.append(
                {
                    "attributes": {
                        "POSITION": position_accessor,
                        "NORMAL": normal_accessor,
                    },
                    "indices": index_accessor(indices),
                    "material": material_slot[material],
                    "mode": 4,
                }
            )
            lines = _feature_edges(positions, indices, part.cuts) if part.edges else []
            if lines:
                primitives.append(
                    {
                        "attributes": {"POSITION": position_accessor},
                        "indices": index_accessor(lines),
                        "material": material_slot[material],
                        "mode": 1,
                    }
                )
            triangle_count += len(indices) // 3
            line_count += len(lines) // 2
            vertex_count += len(positions)
        gltf_nodes.append(
            {
                "name": name,
                "mesh": len(meshes),
                "matrix": [scale, 0, 0, 0, 0, scale, 0, 0, 0, 0, scale, 0, 0, 0, 0, 1],
            }
        )
        meshes.append({"name": f"{name}_mesh", "primitives": primitives})
        report_parts.append(
            {
                "name": name,
                "vertices": vertex_count,
                "triangles": triangle_count,
                "lines": line_count,
            }
        )
    _pad4(buffer)
    materials = []
    for material in used_materials:
        r, g, b = colours[material]
        entry = {
            "name": material_names[material],
            "pbrMetallicRoughness": {
                "baseColorFactor": [round(r, 4), round(g, 4), round(b, 4), 1.0],
                "metallicFactor": 0.0,
                "roughnessFactor": 1.0,
            },
            "doubleSided": True,
        }
        if material_names[material] == GLASS_MATERIAL:
            entry["pbrMetallicRoughness"]["baseColorFactor"][3] = GLASS_ALPHA
            entry["alphaMode"] = "BLEND"
        materials.append(entry)
    extras = dict(document.get("asset", {}).get("extras", {}))
    extras["modified"] = KIT_MODIFIED
    extras["kit"] = kit
    out = {
        "asset": {
            "version": "2.0",
            "generator": "OST Visualizer prepare_tower_crane_asset.py",
            "extras": extras,
        },
        "extensionsUsed": ["KHR_mesh_quantization"],
        "extensionsRequired": ["KHR_mesh_quantization"],
        "scene": 0,
        "scenes": [{"name": "TowerCraneKit", "nodes": list(range(len(gltf_nodes)))}],
        "nodes": gltf_nodes,
        "meshes": meshes,
        "materials": materials,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(buffer)}],
    }
    json_bytes = bytearray(json.dumps(out, separators=(",", ":")).encode("utf-8"))
    while len(json_bytes) % 4:
        json_bytes += b" "
    total = 12 + 8 + len(json_bytes) + 8 + len(buffer)
    glb = bytearray(struct.pack("<4sII", b"glTF", 2, total))
    glb += struct.pack("<I4s", len(json_bytes), b"JSON") + json_bytes
    glb += struct.pack("<I4s", len(buffer), b"BIN\x00") + buffer
    if len(glb) > MAX_BYTES:
        raise SystemExit(f"kit is {len(glb)} bytes, over the {MAX_BYTES} byte limit")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(bytes(glb))
    return {
        "bytes": len(glb),
        "scale_mm": round(scale * 1000.0, 4),
        "measured": {k: round(v, 4) for k, v in measured.items()},
        "kit": kit,
        "parts": report_parts,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--target", type=Path, default=KIT_TARGET)
    args = parser.parse_args(argv)
    report = build_kit(args.source, args.target)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
