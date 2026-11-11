"""Build the shipped tower crane GLB from the Sketchfab original.

Usage (from the repository root, with the project venv)::

    .\\venv\\Scripts\\python.exe tools\\prepare_tower_crane_asset.py

Reads ``assets/models/tower_crane.source.glb`` ("Tower Crane" by Chamod on
Sketchfab, CC BY 4.0) and writes ``ost_visualizer/resources/models/tower_crane.glb``:

* node transforms are baked; the model's own concrete footing (``Cube.073``) is
  dropped because the count takeoff is the footing;
* textures, UVs and images are dropped; each material gets the area-weighted
  median of its base texture sampled at the UVs its triangles use (so atlas
  gaps and grime do not darken it). The factors hold display (sRGB) values on
  purpose: both viewers draw raw colours without colour management, like every
  takeoff;
* the counter-jib walkway grating (``frame``: 16k triangles on one plane)
  becomes a thin plate, which keeps the file small and the Edges view clean;
* the origin moves to the crane's base origin: the mast axis at the top of the
  removed footing, so ``(0, 0, 0)`` sits on top of the takeoff footing;
* primitives are merged per material and welded, positions become int16 and
  normals int8 through ``KHR_mesh_quantization`` (uniform scale, so normals stay
  correct);
* glTF conventions are kept: metres, Y-up, jib along +X.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "assets" / "models" / "tower_crane.source.glb"
TARGET = REPO / "ost_visualizer" / "resources" / "models" / "tower_crane.glb"
FOOTING_NODE_PREFIX = "Cube.073"
GLASS_MATERIAL = "GLASS"
GLASS_ALPHA = 0.5
PLATE_MATERIAL = "frame"
PLATE_MIN_THICKNESS = 0.02
MAX_BYTES = 1_000_000
MODIFIED = (
    "textures removed (flat material colours), primitives merged and welded, "
    "positions and normals quantized, base slab removed, origin moved to the "
    "mast base"
)

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
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _local_matrix(node: dict) -> Matrix:
    if "matrix" in node:
        m = node["matrix"]
        return [[m[c * 4 + r] for c in range(4)] for r in range(4)]
    result = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
    if "scale" in node:
        sx, sy, sz = node["scale"]
        result = _multiply(result, [[sx, 0, 0, 0], [0, sy, 0, 0], [0, 0, sz, 0], [0, 0, 0, 1]])
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
        result = _multiply([[1, 0, 0, tx], [0, 1, 0, ty], [0, 0, 1, tz], [0, 0, 0, 1]], result)
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
    return tuple(m[r][0] * v[0] + m[r][1] * v[1] + m[r][2] * v[2] + m[r][3] for r in range(3))


def _apply3(m: Matrix, v: Sequence[float]) -> Vec3:
    x, y, z = (m[r][0] * v[0] + m[r][1] * v[1] + m[r][2] * v[2] for r in range(3))
    length = math.sqrt(x * x + y * y + z * z) or 1.0
    return (x / length, y / length, z / length)


def _face_normal(a: Vec3, b: Vec3, c: Vec3) -> Vec3:
    u = [b[i] - a[i] for i in range(3)]
    w = [c[i] - a[i] for i in range(3)]
    n = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
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
    n = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
    return 0.5 * math.sqrt(sum(x * x for x in n))


def _collect_parts(document: dict, binary: bytes) -> Tuple[Dict[int, _Part], List[Vec3]]:
    parts: Dict[int, _Part] = {}
    footing: List[Vec3] = []
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
                positions = [_apply(world, p) for p in _accessor(document, binary, attributes["POSITION"])]
                normals = None
                if "NORMAL" in attributes:
                    normals = [_apply3(normal_matrix, n) for n in _accessor(document, binary, attributes["NORMAL"])]
                uvs = None
                if "TEXCOORD_0" in attributes:
                    uvs = _accessor(document, binary, attributes["TEXCOORD_0"])
                if "indices" in primitive:
                    indices = [i[0] for i in _accessor(document, binary, primitive["indices"])]
                else:
                    indices = list(range(len(positions)))
                if FOOTING_NODE_PREFIX in chain:
                    footing.extend(positions)
                    continue
                material = primitive.get("material", 0)
                part = parts.setdefault(
                    material, _Part(document["materials"][material].get("name", f"material{material}"))
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
                        part.triangles.append(((a, normals[ia]), (b, normals[ib]), (c, normals[ic])))
        for child in node.get("children", []):
            walk(child, world, chain)

    for root in document["scenes"][document.get("scene", 0)]["nodes"]:
        walk(root, identity, "")
    if not footing:
        raise ValueError(f"footing node {FOOTING_NODE_PREFIX!r} not found")
    return parts, footing


def _base_origin(parts: Dict[int, _Part], footing: List[Vec3]) -> Vec3:
    slab_top = max(p[1] for p in footing)
    top = max(v[0][1] for part in parts.values() for tri in part.triangles for v in tri)
    low = slab_top + 0.25 * (top - slab_top)
    high = slab_top + 0.35 * (top - slab_top)
    band = [
        v[0]
        for part in parts.values()
        for tri in part.triangles
        for v in tri
        if low <= v[0][1] <= high
    ]
    if not band:
        raise ValueError("no mast vertices found between 25 % and 35 % height")
    cx = (min(p[0] for p in band) + max(p[0] for p in band)) / 2.0
    cz = (min(p[2] for p in band) + max(p[2] for p in band)) / 2.0
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
            view = document["bufferViews"][document["images"][image_index]["bufferView"]]
            start = view.get("byteOffset", 0)
            image = QImage.fromData(binary[start : start + view["byteLength"]])
            if image.isNull():
                raise ValueError(f"cannot decode the texture of material {index}")
            width, height = image.width(), image.height()
            channels: List[List[Tuple[float, float]]] = [[], [], []]
            for u, v, area in part.samples:
                pixel = image.pixelColor(int((u % 1.0) * width) % width, int((v % 1.0) * height) % height)
                for k, value in enumerate((pixel.redF(), pixel.greenF(), pixel.blueF())):
                    channels[k].append((value, area))
            rgb = [_weighted_median(channel) for channel in channels]
        colours[index] = (rgb[0] * factor[0], rgb[1] * factor[1], rgb[2] * factor[2])
    return colours


def _plate(part: _Part) -> None:
    """Replace a flat, dense part by the thin box that bounds it."""
    points = [vertex[0] for triangle in part.triangles for vertex in triangle]
    lo = [min(p[k] for p in points) for k in range(3)]
    hi = [max(p[k] for p in points) for k in range(3)]
    if hi[1] - lo[1] < PLATE_MIN_THICKNESS:
        middle = (lo[1] + hi[1]) / 2.0
        lo[1], hi[1] = middle - PLATE_MIN_THICKNESS / 2.0, middle + PLATE_MIN_THICKNESS / 2.0
    corners = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    faces = [
        ((0, 1, 3, 2), (-1, 0, 0)),
        ((4, 6, 7, 5), (1, 0, 0)),
        ((0, 4, 5, 1), (0, -1, 0)),
        ((2, 3, 7, 6), (0, 1, 0)),
        ((0, 2, 6, 4), (0, 0, -1)),
        ((1, 5, 7, 3), (0, 0, 1)),
    ]
    part.triangles = []
    for (a, b, c, d), normal in faces:
        n = tuple(float(x) for x in normal)
        for tri in ((a, b, c), (a, c, d)):
            part.triangles.append(tuple((corners[i], n) for i in tri))


def _pad4(data: bytearray) -> None:
    while len(data) % 4:
        data.append(0)


def build(source: Path, target: Path) -> dict:
    document, binary = _read_glb(source)
    parts, footing = _collect_parts(document, binary)
    origin = _base_origin(parts, footing)
    colours = _texture_colours(document, binary, parts)
    for part in parts.values():
        if part.name == PLATE_MATERIAL:
            _plate(part)

    welded = []
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for material in sorted(parts):
        part = parts[material]
        lookup: Dict[Tuple[int, ...], int] = {}
        positions: List[Vec3] = []
        normals: List[Tuple[int, int, int]] = []
        indices: List[int] = []
        for triangle in part.triangles:
            for position, normal in triangle:
                p = (position[0] - origin[0], position[1] - origin[1], position[2] - origin[2])
                n = tuple(max(-127, min(127, round(c * 127.0))) for c in normal)
                key = (round(p[0] * 2000), round(p[1] * 2000), round(p[2] * 2000)) + n
                index = lookup.get(key)
                if index is None:
                    index = len(positions)
                    lookup[key] = index
                    positions.append(p)
                    normals.append(n)
                    for k in range(3):
                        lo[k] = min(lo[k], p[k])
                        hi[k] = max(hi[k], p[k])
                indices.append(index)
        welded.append((material, part.name, positions, normals, indices))

    centre = [(lo[k] + hi[k]) / 2.0 for k in range(3)]
    scale = max(hi[k] - lo[k] for k in range(3)) / 65534.0

    buffer = bytearray()
    views: List[dict] = []
    accessors: List[dict] = []
    primitives: List[dict] = []
    materials: List[dict] = []
    for material, name, positions, normals, indices in welded:
        quantized = [tuple(round((p[k] - centre[k]) / scale) for k in range(3)) for p in positions]
        qmin = [min(q[k] for q in quantized) for k in range(3)]
        qmax = [max(q[k] for q in quantized) for k in range(3)]

        _pad4(buffer)
        start = len(buffer)
        for q in quantized:
            buffer += struct.pack("<hhhh", q[0], q[1], q[2], 0)
        views.append({"buffer": 0, "byteOffset": start, "byteLength": len(buffer) - start, "byteStride": 8, "target": 34962})
        position_accessor = len(accessors)
        accessors.append({"bufferView": len(views) - 1, "componentType": 5122, "count": len(quantized), "type": "VEC3", "min": qmin, "max": qmax})

        start = len(buffer)
        for n in normals:
            buffer += struct.pack("<bbbb", n[0], n[1], n[2], 0)
        views.append({"buffer": 0, "byteOffset": start, "byteLength": len(buffer) - start, "byteStride": 4, "target": 34962})
        normal_accessor = len(accessors)
        accessors.append({"bufferView": len(views) - 1, "componentType": 5120, "normalized": True, "count": len(normals), "type": "VEC3"})

        wide = len(positions) > 65535
        start = len(buffer)
        buffer += struct.pack(f"<{len(indices)}{'I' if wide else 'H'}", *indices)
        views.append({"buffer": 0, "byteOffset": start, "byteLength": len(buffer) - start, "target": 34963})
        index_accessor = len(accessors)
        accessors.append({"bufferView": len(views) - 1, "componentType": 5125 if wide else 5123, "count": len(indices), "type": "SCALAR"})

        r, g, b = colours[material]
        entry = {
            "name": name,
            "pbrMetallicRoughness": {
                "baseColorFactor": [round(r, 4), round(g, 4), round(b, 4), 1.0],
                "metallicFactor": 0.0,
                "roughnessFactor": 1.0,
            },
            "doubleSided": True,
        }
        if name == GLASS_MATERIAL:
            entry["pbrMetallicRoughness"]["baseColorFactor"][3] = GLASS_ALPHA
            entry["alphaMode"] = "BLEND"
        primitives.append(
            {"attributes": {"POSITION": position_accessor, "NORMAL": normal_accessor}, "indices": index_accessor, "material": len(materials), "mode": 4}
        )
        materials.append(entry)
    _pad4(buffer)

    extras = dict(document.get("asset", {}).get("extras", {}))
    extras["modified"] = MODIFIED
    extras["units"] = "metres, Y-up, jib along +X; origin = mast axis on top of the footing"
    out = {
        "asset": {"version": "2.0", "generator": "OST Visualizer prepare_tower_crane_asset.py", "extras": extras},
        "extensionsUsed": ["KHR_mesh_quantization"],
        "extensionsRequired": ["KHR_mesh_quantization"],
        "scene": 0,
        "scenes": [{"name": "TowerCrane", "nodes": [0]}],
        "nodes": [
            {
                "name": "TowerCrane",
                "mesh": 0,
                "matrix": [scale, 0, 0, 0, 0, scale, 0, 0, 0, 0, scale, 0, centre[0], centre[1], centre[2], 1],
            }
        ],
        "meshes": [{"name": "TowerCrane", "primitives": primitives}],
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
        raise SystemExit(f"output is {len(glb)} bytes, over the {MAX_BYTES} byte limit")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(bytes(glb))
    return {
        "bytes": len(glb),
        "origin_in_source": [round(c, 4) for c in origin],
        "bounds_min": [round(c, 3) for c in lo],
        "bounds_max": [round(c, 3) for c in hi],
        "parts": [
            {"name": name, "vertices": len(positions), "triangles": len(indices) // 3, "colour": [round(c, 3) for c in colours[material]]}
            for material, name, positions, normals, indices in welded
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--target", type=Path, default=TARGET)
    args = parser.parse_args(argv)
    report = build(args.source, args.target)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
