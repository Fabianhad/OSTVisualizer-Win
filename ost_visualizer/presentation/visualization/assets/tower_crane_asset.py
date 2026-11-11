from __future__ import annotations
import json
import math
import struct
from pathlib import Path
from typing import Dict, List, Tuple

TOWER_CRANE_KIT_PATH = (
    Path(__file__).resolve().parents[3] / "resources" / "models" / "tower_crane_kit.glb"
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
    "modified": (
        "adapted: cut into reusable parts, textures removed, geometry quantized, "
        "base slab and ropes removed (ropes are generated)"
    ),
}
TOWER_CRANE_KIT_VERSION = 1
TOWER_CRANE_KIT_PARTS = (
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
Bounds3 = Tuple[Tuple[float, float, float], Tuple[float, float, float]]


def read_tower_crane_kit() -> bytes:
    return TOWER_CRANE_KIT_PATH.read_bytes()


def tower_crane_kit_metadata(data: bytes) -> Dict:
    try:
        if data[:4] != b"glTF":
            raise ValueError("not a binary glTF file")
        json_length = struct.unpack_from("<I", data, 12)[0]
        document = json.loads(data[20 : 20 + json_length])
        kit = document["asset"]["extras"]["kit"]
        version = kit["version"]
        nodes = {node.get("name") for node in document["nodes"]}
        parts = kit["parts"]
    except (KeyError, IndexError, TypeError, ValueError, struct.error) as error:
        raise ValueError(f"tower crane kit is unreadable: {error}") from error
    if version != TOWER_CRANE_KIT_VERSION:
        raise ValueError(
            f"tower crane kit version {version} is not {TOWER_CRANE_KIT_VERSION}"
        )
    missing = [
        part for part in TOWER_CRANE_KIT_PARTS if part not in nodes or part not in parts
    ]
    if missing:
        raise ValueError(f"tower crane kit lacks parts: {', '.join(missing)}")
    return kit


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
