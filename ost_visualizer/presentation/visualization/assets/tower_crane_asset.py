from __future__ import annotations
import json
import math
import struct
from typing import Dict, List, Mapping, Tuple

TOWER_CRANE_KIT_VERSION = 2
# Parts every kit has; the mast and jib bays come from the kit's own cycles
# and the jib lug from its lugs.
TOWER_CRANE_REQUIRED_PARTS = (
    "base",
    "slewing",
    "head",
    "jib_root",
    "jib_tip",
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


def tower_crane_parts_without_edges(kit: Mapping) -> Tuple[str, ...]:
    parts = kit.get("parts", {})
    return tuple(
        name
        for name, part in parts.items()
        if isinstance(part, Mapping) and part.get("edges") is False
    )


def tower_crane_kit_parts(kit: Mapping) -> Tuple[str, ...]:
    """Every part a layout can place for this kit."""
    lugs = ("jib_lug",) if kit["jib"].get("lugs") else ()
    names = (
        TOWER_CRANE_REQUIRED_PARTS
        + tuple(kit["mast"]["cycle"])
        + tuple(kit["jib"]["cycle"])
        + lugs
    )
    return tuple(dict.fromkeys(names))


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
    try:
        required = tower_crane_kit_parts(kit)
    except (KeyError, TypeError) as error:
        raise ValueError(f"tower crane kit is unreadable: {error}") from error
    missing = [part for part in required if part not in nodes or part not in parts]
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
