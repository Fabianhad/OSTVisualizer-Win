from __future__ import annotations
import json
import math
import struct
from pathlib import Path
from typing import Dict, List, Optional, Tuple

TOWER_CRANE_MODEL_PATH = (
    Path(__file__).resolve().parents[3] / "resources" / "models" / "tower_crane.glb"
)
TOWER_CRANE_CREDIT: Dict[str, str] = {
    "title": "Tower Crane",
    "author": "Chamod",
    "author_url": "https://sketchfab.com/Chamodp",
    "source_url": (
        "https://sketchfab.com/3d-models/tower-crane-49851dc7a51b43bda6aea06856c26a85"
    ),
    "site": "Sketchfab",
    "license": "CC BY 4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "modified": "simplified: textures removed, geometry merged and quantized, base slab removed",
}
Bounds3 = Tuple[Tuple[float, float, float], Tuple[float, float, float]]


def read_tower_crane_model() -> bytes:
    return TOWER_CRANE_MODEL_PATH.read_bytes()


def _matrix_multiply(a: List[float], b: List[float]) -> List[float]:
    return [
        sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4))
        for c in range(4)
        for r in range(4)
    ]


def _node_matrix(node: dict) -> List[float]:
    if "matrix" in node:
        matrix = [float(value) for value in node["matrix"]]
        if len(matrix) != 16:
            raise ValueError("node matrix must have 16 values")
        return matrix
    tx, ty, tz = node.get("translation", (0.0, 0.0, 0.0))
    x, y, z, w = node.get("rotation", (0.0, 0.0, 0.0, 1.0))
    sx, sy, sz = node.get("scale", (1.0, 1.0, 1.0))
    r00, r01, r02 = 1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)
    r10, r11, r12 = 2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)
    r20, r21, r22 = 2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)
    columns = (
        (r00 * sx, r10 * sx, r20 * sx, 0.0),
        (r01 * sy, r11 * sy, r21 * sy, 0.0),
        (r02 * sz, r12 * sz, r22 * sz, 0.0),
        (tx, ty, tz, 1.0),
    )
    return [value for column in columns for value in column]


def _world_matrix_of(nodes: List[dict]):
    parents = {
        child: index
        for index, node in enumerate(nodes)
        for child in node.get("children", [])
    }
    worlds: Dict[int, List[float]] = {}

    def world(index: int, trail: Tuple[int, ...] = ()) -> List[float]:
        if index not in worlds:
            if index in trail:
                raise ValueError("node hierarchy has a cycle")
            local = _node_matrix(nodes[index])
            parent = parents.get(index)
            worlds[index] = (
                local
                if parent is None
                else _matrix_multiply(world(parent, trail + (index,)), local)
            )
        return worlds[index]

    return world


def glb_local_bounds(data: bytes) -> Optional[Bounds3]:
    try:
        if data[:4] != b"glTF":
            return None
        json_length = struct.unpack_from("<I", data, 12)[0]
        document = json.loads(data[20 : 20 + json_length])
        lo = [float("inf")] * 3
        hi = [float("-inf")] * 3
        nodes = document.get("nodes", [])
        world_matrix = _world_matrix_of(nodes)
        for node_index, node in enumerate(nodes):
            if "mesh" not in node:
                continue
            m = world_matrix(node_index)
            for primitive in document["meshes"][node["mesh"]]["primitives"]:
                accessor = document["accessors"][primitive["attributes"]["POSITION"]]
                amin, amax = accessor["min"], accessor["max"]
                for corner in range(8):
                    p = [amax[k] if corner & (1 << k) else amin[k] for k in range(3)]
                    world = [
                        m[0 + r] * p[0] + m[4 + r] * p[1] + m[8 + r] * p[2] + m[12 + r]
                        for r in range(3)
                    ]
                    for k in range(3):
                        lo[k] = min(lo[k], world[k])
                        hi[k] = max(hi[k], world[k])
        if lo[0] > hi[0]:
            return None
        return (tuple(lo), tuple(hi))
    except (
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        RecursionError,
        struct.error,
    ):
        return None


def native_instance_corners(
    local_bounds: Bounds3,
    units_per_metre: float,
    x: float,
    y: float,
    z: float,
    rotation: float,
) -> List[Tuple[float, float, float]]:
    lo, hi = local_bounds
    c, s = math.cos(rotation), math.sin(rotation)
    corners = []
    for corner in range(8):
        gx = hi[0] if corner & 1 else lo[0]
        gy = hi[1] if corner & 2 else lo[1]
        gz = hi[2] if corner & 4 else lo[2]
        lx, ly, lz = -gx * units_per_metre, gz * units_per_metre, gy * units_per_metre
        corners.append((c * lx - s * ly + x, s * lx + c * ly + y, lz + z))
    return corners
