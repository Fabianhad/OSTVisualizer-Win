"""Shared building blocks for the tower crane kits (see prepare_tower_crane_asset.py).

A kit is one source crane cut into reusable parts, one glTF node per part,
which both viewers assemble from a layout computed in Python
(``ost_visualizer/presentation/visualization/assets/tower_crane_layout.py``).
Each model has its own profile module (``tower_crane_classic.py``,
``tower_crane_liebherr.py``) that knows the source file's nodes; this module
holds what every profile shares: the GLB reader, the geometry helpers that
cut lattices into bays and check that they repeat, and the writer of the
quantized kit with its ``asset.extras.kit`` metadata.
"""

from __future__ import annotations
import bisect
import json
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[1]
MODELS_DIR = REPO / "ost_visualizer" / "resources" / "models"
KIT_VERSION = 2
MAX_BYTES = 1_000_000
PLATE_MIN_THICKNESS = 0.02
ROPE_RADIUS = 0.03
ROPE_SIDES = 6
EDGE_CREASE_DEGREES = 15.0
GLASS_ALPHA = 0.5
# Colours every kit sets rather than samples (display values, as both viewers
# draw them): one crane yellow, and the classic model's own glass (drawn
# GLASS_ALPHA transparent) and concrete counterweight colours.
CRANE_YELLOW = (0.9294, 0.8118, 0.0471)  # #edcf0c
GLASS_COLOUR = (0.4078, 0.4078, 0.4078)
CONCRETE_COLOUR = (0.1765, 0.1765, 0.1725)
Matrix = List[List[float]]
Vec3 = Tuple[float, float, float]
Vertex = Tuple[Vec3, Vec3]
Triangle = Tuple[Vertex, Vertex, Vertex, int]
_COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
_FORMATS = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}


def kit_target(model_id: str) -> Path:
    return MODELS_DIR / f"tower_crane_{model_id}.glb"


# ---------------------------------------------------------------------------
# Reading the source GLB
# ---------------------------------------------------------------------------
def read_glb(path: Path) -> Tuple[dict, bytes]:
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


def accessor(document: dict, binary: bytes, index: int) -> List[Tuple[float, ...]]:
    item_accessor = document["accessors"][index]
    view = document["bufferViews"][item_accessor["bufferView"]]
    fmt = _FORMATS[item_accessor["componentType"]]
    components = _COMPONENTS[item_accessor["type"]]
    item = struct.calcsize("<" + fmt * components)
    stride = view.get("byteStride") or item
    start = view.get("byteOffset", 0) + item_accessor.get("byteOffset", 0)
    unpack = struct.Struct("<" + fmt * components).unpack_from
    return [unpack(binary, start + i * stride) for i in range(item_accessor["count"])]


def multiply(a: Matrix, b: Matrix) -> Matrix:
    return [
        [sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)
    ]


def local_matrix(node: dict) -> Matrix:
    if "matrix" in node:
        m = node["matrix"]
        return [[m[c * 4 + r] for c in range(4)] for r in range(4)]
    result = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
    if "scale" in node:
        sx, sy, sz = node["scale"]
        result = multiply(
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
        result = multiply(rotation, result)
    if "translation" in node:
        tx, ty, tz = node["translation"]
        result = multiply(
            [[1, 0, 0, tx], [0, 1, 0, ty], [0, 0, 1, tz], [0, 0, 0, 1]], result
        )
    return result


def determinant(m: Matrix) -> float:
    a = [row[:3] for row in m[:3]]
    return (
        a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
        - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
        + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0])
    )


def normal_matrix(m: Matrix) -> Matrix:
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
    if determinant(m) < 0:
        cofactor = [[-value for value in row] for row in cofactor]
    return cofactor


def apply(m: Matrix, v: Sequence[float]) -> Vec3:
    return tuple(
        m[r][0] * v[0] + m[r][1] * v[1] + m[r][2] * v[2] + m[r][3] for r in range(3)
    )


def apply3(m: Matrix, v: Sequence[float]) -> Vec3:
    x, y, z = (m[r][0] * v[0] + m[r][1] * v[1] + m[r][2] * v[2] for r in range(3))
    length = math.sqrt(x * x + y * y + z * z) or 1.0
    return (x / length, y / length, z / length)


def face_normal(a: Vec3, b: Vec3, c: Vec3) -> Vec3:
    u = [b[i] - a[i] for i in range(3)]
    w = [c[i] - a[i] for i in range(3)]
    n = (
        u[1] * w[2] - u[2] * w[1],
        u[2] * w[0] - u[0] * w[2],
        u[0] * w[1] - u[1] * w[0],
    )
    length = math.sqrt(sum(x * x for x in n)) or 1.0
    return (n[0] / length, n[1] / length, n[2] / length)


def triangle_area(a: Vec3, b: Vec3, c: Vec3) -> float:
    u = [b[i] - a[i] for i in range(3)]
    w = [c[i] - a[i] for i in range(3)]
    n = (
        u[1] * w[2] - u[2] * w[1],
        u[2] * w[0] - u[0] * w[2],
        u[0] * w[1] - u[1] * w[0],
    )
    return 0.5 * math.sqrt(sum(x * x for x in n))


def _walk_meshes(document: dict, binary: bytes, visit) -> None:
    """Call ``visit(chain, name, world, primitive)`` for every triangle primitive."""
    identity = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]

    def walk(index: int, parent: Matrix, name_chain: str) -> None:
        node = document["nodes"][index]
        world = multiply(parent, local_matrix(node))
        name = node.get("name", "")
        chain = f"{name_chain}/{name}"
        if "mesh" in node:
            for primitive in document["meshes"][node["mesh"]]["primitives"]:
                if primitive.get("mode", 4) == 4:
                    visit(chain, name, world, primitive)
        for child in node.get("children", []):
            walk(child, world, chain)

    for root in document["scenes"][document.get("scene", 0)]["nodes"]:
        walk(root, identity, "")


def _primitive_indices(document: dict, binary: bytes, primitive: dict, count: int):
    if "indices" in primitive:
        return [i[0] for i in accessor(document, binary, primitive["indices"])]
    return list(range(count))


class MaterialSamples:
    """Texture coordinates (with triangle areas) used by one material."""

    def __init__(self, name: str) -> None:
        self.name = name
        # (u, v, area) at each triangle centroid, for the texture colour.
        self.samples: List[Tuple[float, float, float]] = []


def collect_material_samples(
    document: dict, binary: bytes, skip: Callable[[str], bool] = lambda chain: False
) -> Dict[int, MaterialSamples]:
    """UV samples per material over every node whose path ``skip`` refuses."""
    parts: Dict[int, MaterialSamples] = {}

    def visit(chain: str, _name: str, world: Matrix, primitive: dict) -> None:
        if skip(chain):
            return
        attributes = primitive["attributes"]
        positions = [
            apply(world, p) for p in accessor(document, binary, attributes["POSITION"])
        ]
        uvs = None
        if "TEXCOORD_0" in attributes:
            uvs = accessor(document, binary, attributes["TEXCOORD_0"])
        indices = _primitive_indices(document, binary, primitive, len(positions))
        material = primitive.get("material", 0)
        part = parts.setdefault(
            material,
            MaterialSamples(
                document["materials"][material].get("name", f"material{material}")
            ),
        )
        mirrored = determinant(world) < 0
        for t in range(0, len(indices) - 2, 3):
            ia, ib, ic = indices[t : t + 3]
            if mirrored:
                ib, ic = ic, ib
            if uvs is not None:
                a, b, c = positions[ia], positions[ib], positions[ic]
                u = (uvs[ia][0] + uvs[ib][0] + uvs[ic][0]) / 3.0
                v = (uvs[ia][1] + uvs[ib][1] + uvs[ic][1]) / 3.0
                part.samples.append((u, v, triangle_area(a, b, c)))

    _walk_meshes(document, binary, visit)
    return parts


def collect_points(
    document: dict, binary: bytes, match: Callable[[str], bool]
) -> List[Vec3]:
    """World positions of every node whose path ``match`` accepts."""
    points: List[Vec3] = []

    def visit(chain: str, _name: str, world: Matrix, primitive: dict) -> None:
        if match(chain):
            points.extend(
                apply(world, p)
                for p in accessor(document, binary, primitive["attributes"]["POSITION"])
            )

    _walk_meshes(document, binary, visit)
    return points


def weighted_median(values: List[Tuple[float, float]]) -> float:
    values.sort()
    half = sum(weight for _, weight in values) / 2.0
    running = 0.0
    for value, weight in values:
        running += weight
        if running >= half:
            return value
    return values[-1][0]


def texture_colours(
    document: dict, binary: bytes, parts: Dict[int, MaterialSamples]
) -> Dict[int, Tuple[float, float, float]]:
    """Each material's area-weighted median texel times its base colour factor."""
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
            rgb = [weighted_median(channel) for channel in channels]
        colours[index] = (rgb[0] * factor[0], rgb[1] * factor[1], rgb[2] * factor[2])
    return colours


def node_key(name: str) -> str:
    """``Cube.052_UV_0`` -> ``Cube.052`` (the mesh node name without material)."""
    return name.rsplit("_", 2)[0]


def collect_nodes(document: dict, binary: bytes) -> Dict[str, List[Triangle]]:
    """World-space triangles ``(vertex, vertex, vertex, material)`` per mesh node."""
    nodes: Dict[str, List[Triangle]] = {}

    def visit(_chain: str, name: str, world: Matrix, primitive: dict) -> None:
        normals_matrix = normal_matrix(world)
        mirrored = determinant(world) < 0
        triangles = nodes.setdefault(node_key(name), [])
        attributes = primitive["attributes"]
        positions = [
            apply(world, p) for p in accessor(document, binary, attributes["POSITION"])
        ]
        normals = None
        if "NORMAL" in attributes:
            normals = [
                apply3(normals_matrix, n)
                for n in accessor(document, binary, attributes["NORMAL"])
            ]
        indices = _primitive_indices(document, binary, primitive, len(positions))
        material = primitive.get("material", 0)
        for t in range(0, len(indices) - 2, 3):
            ia, ib, ic = indices[t : t + 3]
            if mirrored:
                ib, ic = ic, ib
            a, b, c = positions[ia], positions[ib], positions[ic]
            if normals is None:
                n = face_normal(a, b, c)
                triangles.append(((a, n), (b, n), (c, n), material))
            else:
                triangles.append(
                    ((a, normals[ia]), (b, normals[ib]), (c, normals[ic]), material)
                )

    _walk_meshes(document, binary, visit)
    return nodes


def collect_node_texels(
    document: dict, binary: bytes, wanted: Callable[[str], bool]
) -> Dict[str, List[Optional[Tuple[float, float, float]]]]:
    """The base texture's colour at each triangle's centroid, per mesh node, in
    the order ``collect_nodes`` lists that node's triangles (``None`` where the
    primitive has no texture). Only nodes whose key ``wanted`` accepts are read."""
    from PySide6.QtGui import QImage

    images: Dict[int, Optional[QImage]] = {}
    texels: Dict[str, List[Optional[Tuple[float, float, float]]]] = {}

    def image_for(material: int):
        if material not in images:
            pbr = document["materials"][material].get("pbrMetallicRoughness", {})
            info = pbr.get("baseColorTexture")
            image = None
            if info is not None:
                source = document["textures"][info["index"]]["source"]
                view = document["bufferViews"][document["images"][source]["bufferView"]]
                start = view.get("byteOffset", 0)
                image = QImage.fromData(binary[start : start + view["byteLength"]])
                if image.isNull():
                    raise ValueError(f"cannot decode the texture of material {material}")
            images[material] = image
        return images[material]

    def visit(_chain: str, name: str, _world: Matrix, primitive: dict) -> None:
        key = node_key(name)
        if not wanted(key):
            return
        found = texels.setdefault(key, [])
        attributes = primitive["attributes"]
        count = document["accessors"][attributes["POSITION"]]["count"]
        indices = _primitive_indices(document, binary, primitive, count)
        image = image_for(primitive.get("material", 0))
        uvs = None
        if image is not None and "TEXCOORD_0" in attributes:
            uvs = accessor(document, binary, attributes["TEXCOORD_0"])
        for t in range(0, len(indices) - 2, 3):
            if uvs is None:
                found.append(None)
                continue
            ia, ib, ic = indices[t : t + 3]
            u = (uvs[ia][0] + uvs[ib][0] + uvs[ic][0]) / 3.0
            v = (uvs[ia][1] + uvs[ib][1] + uvs[ic][1]) / 3.0
            width, height = image.width(), image.height()
            pixel = image.pixelColor(
                int((u % 1.0) * width) % width, int((v % 1.0) * height) % height
            )
            found.append((pixel.redF(), pixel.greenF(), pixel.blueF()))

    _walk_meshes(document, binary, visit)
    return texels


def check_node_table(nodes: Mapping[str, object], assigned: Sequence[str]) -> None:
    """Every source node must be in exactly the profile's tables."""
    assigned_set = set(assigned)
    unassigned = sorted(set(nodes) - assigned_set)
    missing = sorted(assigned_set - set(nodes))
    if unassigned or missing:
        raise ValueError(
            f"kit node table is out of date: unassigned {unassigned}, missing {missing}"
        )


def check_measured(
    measured: Mapping[str, float],
    expected: Mapping[str, float],
    model: str,
    tolerance: float = 0.005,
) -> None:
    """Guard against a node table that measures the wrong pieces."""
    for key, value in expected.items():
        if abs(measured[key] - value) > tolerance:
            raise ValueError(
                f"model {key} is {measured[key]:.4f} but the {model} profile "
                f"expects {value}"
            )


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
def components(
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


def extent(triangles: Sequence[Triangle], axis: int) -> Tuple[float, float]:
    values = [vertex[0][axis] for triangle in triangles for vertex in triangle[:3]]
    return min(values), max(values)


def bounds(triangles: Sequence[Triangle]) -> Tuple[List[float], List[float]]:
    return (
        [extent(triangles, k)[0] for k in range(3)],
        [extent(triangles, k)[1] for k in range(3)],
    )


def centre(triangles: Sequence[Triangle], axis: int) -> float:
    low, high = extent(triangles, axis)
    return (low + high) / 2.0


def clip_polygon(
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


def clip_triangles(
    triangles: Sequence[Triangle], axis: int, low: float | None, high: float | None
) -> List[Triangle]:
    """The part of each triangle between two axis planes (either may be open)."""
    result: List[Triangle] = []
    for triangle in triangles:
        polygon = list(triangle[:3])
        if low is not None:
            polygon = clip_polygon(polygon, axis, low, True)
        if high is not None and len(polygon) >= 3:
            polygon = clip_polygon(polygon, axis, high, False)
        for index in range(1, len(polygon) - 1):
            a, b, c = polygon[0], polygon[index], polygon[index + 1]
            if triangle_area(a[0], b[0], c[0]) > 1e-12:
                result.append((a, b, c, triangle[3]))
    return result


def split_along(
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
    for component in components(triangles):
        low, high = extent(component, axis)
        if high - low <= whole_limit:
            slabs[bisect.bisect_right(planes, (low + high) / 2.0)].extend(component)
            continue
        first = bisect.bisect_right(planes, low)
        last = bisect.bisect_left(planes, high)
        for index in range(first, last + 1):
            slab_low = planes[index - 1] if index > 0 else None
            slab_high = planes[index] if index < len(planes) else None
            slabs[index].extend(clip_triangles(component, axis, slab_low, slab_high))
    return slabs


def shift(triangles: Sequence[Triangle], origin: Vec3) -> List[Triangle]:
    return [
        tuple(
            (tuple(vertex[0][k] - origin[k] for k in range(3)), vertex[1])
            for vertex in triangle[:3]
        )
        + (triangle[3],)
        for triangle in triangles
    ]


def rotate(triangles: Sequence[Triangle], rotation: Sequence[Sequence[float]]):
    """Triangles turned by a proper rotation (3x3, determinant +1)."""
    det = (
        rotation[0][0] * (rotation[1][1] * rotation[2][2] - rotation[1][2] * rotation[2][1])
        - rotation[0][1] * (rotation[1][0] * rotation[2][2] - rotation[1][2] * rotation[2][0])
        + rotation[0][2] * (rotation[1][0] * rotation[2][1] - rotation[1][1] * rotation[2][0])
    )
    if abs(det - 1.0) > 1e-9:
        raise ValueError(f"not a proper rotation (determinant {det})")

    def turn(v: Sequence[float]) -> Vec3:
        return tuple(sum(rotation[r][k] * v[k] for k in range(3)) for r in range(3))

    return [
        tuple((turn(vertex[0]), turn(vertex[1])) for vertex in triangle[:3])
        + (triangle[3],)
        for triangle in triangles
    ]


def stretch_along(
    triangles: Sequence[Triangle], axis: int, origin: float, factor: float
) -> List[Triangle]:
    """Scale triangles along one axis about ``origin`` (normals follow)."""
    if factor <= 0.0:
        raise ValueError("the stretch factor must be positive")

    def move(position: Vec3) -> Vec3:
        moved = list(position)
        moved[axis] = origin + (position[axis] - origin) * factor
        return tuple(moved)

    def normal(n: Vec3) -> Vec3:
        bent = list(n)
        bent[axis] /= factor
        length = math.sqrt(sum(c * c for c in bent)) or 1.0
        return tuple(c / length for c in bent)

    return [
        tuple((move(vertex[0]), normal(vertex[1])) for vertex in triangle[:3])
        + (triangle[3],)
        for triangle in triangles
    ]


def box_triangles(low: Vec3, high: Vec3, material: int) -> List[Triangle]:
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


def plate_node(triangles: Sequence[Triangle], thin_axis: int = 1) -> List[Triangle]:
    """A flat, dense node (a walkway grating) as the thin box that bounds it."""
    low = [extent(triangles, k)[0] for k in range(3)]
    high = [extent(triangles, k)[1] for k in range(3)]
    if high[thin_axis] - low[thin_axis] < PLATE_MIN_THICKNESS:
        middle = (low[thin_axis] + high[thin_axis]) / 2.0
        low[thin_axis] = middle - PLATE_MIN_THICKNESS / 2.0
        high[thin_axis] = middle + PLATE_MIN_THICKNESS / 2.0
    return box_triangles(tuple(low), tuple(high), triangles[0][3])


def rope_triangles(material: int, radius: float = ROPE_RADIUS) -> List[Triangle]:
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
        a = ((x0 * radius, 0.0, z0 * radius), (x0, 0.0, z0))
        b = ((x1 * radius, 0.0, z1 * radius), (x1, 0.0, z1))
        c = ((x1 * radius, 1.0, z1 * radius), (x1, 0.0, z1))
        d = ((x0 * radius, 1.0, z0 * radius), (x0, 0.0, z0))
        triangles.append((a, c, b, material))
        triangles.append((a, d, c, material))
        for y, normal, flip in (
            (0.0, (0.0, -1.0, 0.0), False),
            (1.0, (0.0, 1.0, 0.0), True),
        ):
            middle = ((0.0, y, 0.0), normal)
            p = ((x0 * radius, y, z0 * radius), normal)
            q = ((x1 * radius, y, z1 * radius), normal)
            triangles.append(
                (middle, q, p, material) if flip else (middle, p, q, material)
            )
    return triangles


def drum_triangles(
    axis: int,
    middle: Sequence[float],
    radius: float,
    low: float,
    high: float,
    material: int,
    sides: int = 16,
) -> List[Triangle]:
    """A closed cylinder along ``axis`` from ``low`` to ``high`` (a winch drum).
    ``middle`` holds the coordinates of its axis on the other two axes, in
    axis order."""
    if high <= low or radius <= 0.0:
        raise ValueError("a drum needs a positive length and radius")
    u_axis, v_axis = [k for k in range(3) if k != axis]

    def point(along: float, u: float, v: float) -> Vec3:
        p = [0.0, 0.0, 0.0]
        p[axis] = along
        p[u_axis] = middle[0] + u
        p[v_axis] = middle[1] + v
        return tuple(p)

    def direction(u: float, v: float, along: float = 0.0) -> Vec3:
        d = [0.0, 0.0, 0.0]
        d[axis] = along
        d[u_axis] = u
        d[v_axis] = v
        return tuple(d)

    ring = [
        (math.cos(2.0 * math.pi * i / sides), math.sin(2.0 * math.pi * i / sides))
        for i in range(sides)
    ]
    # The faces below are wound like the rope's, whose (u, v, along) frame is
    # left-handed (axis y); for x or z that frame is right-handed, so flip the
    # winding there to keep every face pointing outward.
    flip = axis != 1
    triangles: List[Triangle] = []

    def add(a: Vertex, b: Vertex, c: Vertex) -> None:
        triangles.append((a, c, b, material) if flip else (a, b, c, material))

    for i in range(sides):
        (u0, v0), (u1, v1) = ring[i], ring[(i + 1) % sides]
        a = (point(low, u0 * radius, v0 * radius), direction(u0, v0))
        b = (point(low, u1 * radius, v1 * radius), direction(u1, v1))
        c = (point(high, u1 * radius, v1 * radius), direction(u1, v1))
        d = (point(high, u0 * radius, v0 * radius), direction(u0, v0))
        add(a, c, b)
        add(a, d, c)
        bottom, top = direction(0.0, 0.0, -1.0), direction(0.0, 0.0, 1.0)
        add(
            (point(low, 0.0, 0.0), bottom),
            (point(low, u0 * radius, v0 * radius), bottom),
            (point(low, u1 * radius, v1 * radius), bottom),
        )
        add(
            (point(high, 0.0, 0.0), top),
            (point(high, u1 * radius, v1 * radius), top),
            (point(high, u0 * radius, v0 * radius), top),
        )
    return triangles


def _covers(first: Sequence[Vec3], second: Sequence[Vec3], tolerance: float) -> bool:
    """Whether every point of ``first`` has a point of ``second`` within
    ``tolerance``; a grid of ``tolerance`` cells keeps the search to the
    neighbouring cells, which hold every point close enough."""
    cell = max(tolerance, 1e-9)
    grid: Dict[Tuple[int, int, int], List[Vec3]] = {}
    for point in second:
        grid.setdefault(tuple(math.floor(c / cell) for c in point), []).append(point)
    limit = tolerance * tolerance
    for point in first:
        home = tuple(math.floor(c / cell) for c in point)
        if not any(
            sum((other[k] - point[k]) ** 2 for k in range(3)) <= limit
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for dz in (-1, 0, 1)
            for other in grid.get((home[0] + dx, home[1] + dy, home[2] + dz), ())
        ):
            return False
    return True


def same_points(first: Sequence[Vec3], second: Sequence[Vec3], tolerance: float) -> bool:
    """Whether two point sets cover each other within ``tolerance``: every point
    of each has a point of the other that close. Near-duplicate vertices (two
    welded copies a fraction of a millimetre apart) make a one-to-one match
    depend on rounding, so this is what the repeat check compares."""
    if not first or not second:
        return not first and not second
    return _covers(first, second, tolerance) and _covers(second, first, tolerance)


def assert_periodic(
    slabs: Sequence[Sequence[Triangle]],
    indices: Sequence[int],
    canonical: Sequence[int],
    axis: int,
    pitch: float,
    tolerance: float,
    label: str,
) -> None:
    """Every listed slab must repeat the canonical slab of its place in the cycle.
    ``canonical`` lists one slab per bay of the cycle: two for a lattice whose
    diagonals zigzag over two bays, one when every bay is the same."""

    def points(index: int) -> List[Vec3]:
        seen = {}
        for triangle in slabs[index]:
            for vertex in triangle[:3]:
                moved = list(vertex[0])
                moved[axis] -= index * pitch
                seen[tuple(round(c, 4) for c in moved)] = tuple(moved)
        return list(seen.values())

    cycle = len(canonical)
    for index in indices:
        reference = canonical[(index - canonical[0]) % cycle]
        if not same_points(points(index), points(reference), tolerance):
            raise ValueError(
                f"{label} {index} does not repeat {label} {reference} within "
                f"{tolerance} m; the model is not periodic there"
            )


def short_pieces(
    triangles: Sequence[Triangle], axis: int, whole_limit: float
) -> List[Triangle]:
    """The pieces that ``split_along`` keeps whole (no longer than the limit)."""
    return [
        triangle
        for component in components(triangles)
        if extent(component, axis)[1] - extent(component, axis)[0] <= whole_limit
        for triangle in component
    ]


def assert_prismatic(
    triangles: Sequence[Triangle],
    axis: int,
    span: Tuple[float, float],
    whole_limit: float,
    tolerance: float,
    label: str,
) -> None:
    """Every long piece (a chord, a rail, a walkway plate) must run the whole
    ``span`` with one cross-section, so any bay cut from it matches the rest.
    A long face cut at a plane leaves a point where its diagonal crosses the
    plane, and that point moves from bay to bay although the surface does not;
    this is why long pieces are checked here and not point by point."""
    others = [k for k in range(3) if k != axis]
    for component in components(triangles):
        low, high = extent(component, axis)
        if high - low <= whole_limit or high <= span[0] or low >= span[1]:
            continue
        if low > span[0] + 1e-3 or high < span[1] - 1e-3:
            raise ValueError(
                f"{label}: a long member from {low:.3f} to {high:.3f} m does not "
                f"run the whole repeat from {span[0]:.3f} to {span[1]:.3f} m"
            )
        reference = None
        steps = 8
        for step in range(steps + 1):
            plane = span[0] + (span[1] - span[0]) * step / steps
            cut = clip_triangles(component, axis, plane - 1e-4, plane + 1e-4)
            if not cut:
                continue
            section = [v for k in others for v in extent(cut, k)]
            if reference is None:
                reference = section
            elif max(abs(a - b) for a, b in zip(section, reference)) > tolerance:
                raise ValueError(
                    f"{label}: a long member changes its cross-section at {plane:.3f} m"
                )


def feature_edges(
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
        face_normals.append(face_normal(*(positions[i] for i in corners)))
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


class KitPart:
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
        return bounds(self.triangles)


@dataclass
class KitBuild:
    """What a profile hands the writer: parts, metadata and materials."""

    parts: Dict[str, KitPart]
    part_order: Tuple[str, ...]
    kit: Dict
    colours: Dict[int, Tuple[float, float, float]]
    material_names: List[str]
    source_extras: Dict
    modified: str
    measured: Dict[str, float] = field(default_factory=dict)
    glass_material: Optional[str] = None


def _pad4(data: bytearray) -> None:
    while len(data) % 4:
        data.append(0)


# ---------------------------------------------------------------------------
# Writing the kit
# ---------------------------------------------------------------------------
def write_kit(build: KitBuild, target: Path, max_bytes: int = MAX_BYTES) -> dict:
    """Quantize the parts into ``target`` with ``build.kit`` as the metadata."""
    parts = build.parts
    kit = dict(build.kit)
    kit["parts"] = {}
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
    for name in build.part_order:
        part = parts[name]
        low, high = part.bounds()
        kit["parts"][name] = {
            "min": [round(c, 4) for c in low],
            "max": [round(c, 4) for c in high],
        }
        if not part.edges:
            # Both viewers draw no edge lines for this part (the rope).
            kit["parts"][name]["edges"] = False
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
            lines = feature_edges(positions, indices, part.cuts) if part.edges else []
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
        r, g, b = build.colours[material]
        entry = {
            "name": build.material_names[material],
            "pbrMetallicRoughness": {
                "baseColorFactor": [round(r, 4), round(g, 4), round(b, 4), 1.0],
                "metallicFactor": 0.0,
                "roughnessFactor": 1.0,
            },
            "doubleSided": True,
        }
        if (
            build.glass_material is not None
            and build.material_names[material] == build.glass_material
        ):
            entry["pbrMetallicRoughness"]["baseColorFactor"][3] = GLASS_ALPHA
            entry["alphaMode"] = "BLEND"
        materials.append(entry)
    extras = dict(build.source_extras)
    extras["modified"] = build.modified
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
    if len(glb) > max_bytes:
        raise SystemExit(f"kit is {len(glb)} bytes, over the {max_bytes} byte limit")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(bytes(glb))
    return {
        "bytes": len(glb),
        "scale_mm": round(scale * 1000.0, 4),
        "measured": {k: round(v, 4) for k, v in build.measured.items()},
        "kit": kit,
        "parts": report_parts,
    }
