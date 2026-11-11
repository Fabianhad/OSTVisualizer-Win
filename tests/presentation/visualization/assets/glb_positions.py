"""Decode vertex positions from a GLB (test support, no renderer needed)."""

import json
import struct

_FORMATS = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
_IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def glb_positions(data: bytes, node_name=None):
    """World-space ``(x, y, z)`` of every vertex of flat (unparented) mesh nodes.
    With ``node_name`` only that node is read (a kit part, in its own frame).
    """
    json_length = struct.unpack_from("<I", data, 12)[0]
    document = json.loads(data[20 : 20 + json_length])
    binary = data[20 + json_length + 8 :]
    positions = []
    for node in document["nodes"]:
        if "mesh" not in node:
            continue
        if node_name is not None and node.get("name") != node_name:
            continue
        m = node.get("matrix", _IDENTITY)
        for primitive in document["meshes"][node["mesh"]]["primitives"]:
            accessor = document["accessors"][primitive["attributes"]["POSITION"]]
            view = document["bufferViews"][accessor["bufferView"]]
            unpack = struct.Struct("<3" + _FORMATS[accessor["componentType"]])
            stride = view.get("byteStride") or unpack.size
            start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
            for index in range(accessor["count"]):
                x, y, z = unpack.unpack_from(binary, start + index * stride)
                positions.append(
                    tuple(
                        m[row] * x + m[4 + row] * y + m[8 + row] * z + m[12 + row]
                        for row in range(3)
                    )
                )
    return positions


def bounds_of(points):
    return (
        tuple(min(p[k] for p in points) for k in range(3)),
        tuple(max(p[k] for p in points) for k in range(3)),
    )


def mast_anchor_bounds(data: bytes, below_m: float = -0.05):
    """Bounds of the mast legs where they enter the footing (below its top).
    The kit's ``base`` part is in the crane's own frame: its origin is the
    crane's origin, on top of the footing.
    """
    anchors = [p for p in glb_positions(data, "base") if p[1] < below_m]
    if not anchors:
        raise AssertionError("the model has no geometry below the footing top")
    return bounds_of(anchors)
