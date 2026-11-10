"""Tiny in-memory GLB files for the native instanced-model tests."""

import json
import struct

# One unit cube face per entry: outward normal and its four corners.
_CUBE_FACES = (
    ((1, 0, 0), ((1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1))),
    ((-1, 0, 0), ((-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1))),
    ((0, 1, 0), ((-1, 1, -1), (-1, 1, 1), (1, 1, 1), (1, 1, -1))),
    ((0, -1, 0), ((-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1))),
    ((0, 0, 1), ((-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1))),
    ((0, 0, -1), ((-1, -1, -1), (-1, 1, -1), (1, 1, -1), (1, -1, -1))),
)


def cube_glb(parts):
    """GLB with one cube primitive per part.
    ``parts`` is a list of ``(name, half_size, centre, rgba, blend)`` in glTF
    metres (Y-up). Positions are plain floats, normals per face.
    """
    buffer = bytearray()
    views, accessors, primitives, materials = [], [], [], []
    for name, half, centre, rgba, blend in parts:
        positions, normals, indices = [], [], []
        for normal, corners in _CUBE_FACES:
            base = len(positions)
            for corner in corners:
                positions.append(tuple(centre[k] + half * corner[k] for k in range(3)))
                normals.append(normal)
            indices += [base, base + 1, base + 2, base, base + 2, base + 3]
        for data, fmt, kind, target in (
            (positions, "<3f", "VEC3", 34962),
            (normals, "<3f", "VEC3", 34962),
            (indices, "<H", "SCALAR", 34963),
        ):
            while len(buffer) % 4:
                buffer.append(0)
            start = len(buffer)
            for item in data:
                buffer += struct.pack(
                    fmt, *(item if isinstance(item, tuple) else (item,))
                )
            views.append(
                {
                    "buffer": 0,
                    "byteOffset": start,
                    "byteLength": len(buffer) - start,
                    "target": target,
                }
            )
            accessor = {
                "bufferView": len(views) - 1,
                "componentType": 5126 if fmt == "<3f" else 5123,
                "count": len(data),
                "type": kind,
            }
            if data is positions:
                accessor["min"] = [min(p[k] for p in positions) for k in range(3)]
                accessor["max"] = [max(p[k] for p in positions) for k in range(3)]
            accessors.append(accessor)
        position_index = len(accessors) - 3
        primitives.append(
            {
                "attributes": {
                    "POSITION": position_index,
                    "NORMAL": position_index + 1,
                },
                "indices": position_index + 2,
                "material": len(materials),
            }
        )
        material = {
            "name": name,
            "pbrMetallicRoughness": {"baseColorFactor": list(rgba)},
        }
        if blend:
            material["alphaMode"] = "BLEND"
        materials.append(material)
    while len(buffer) % 4:
        buffer.append(0)
    document = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": primitives}],
        "materials": materials,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(buffer)}],
    }
    json_bytes = bytearray(json.dumps(document).encode("utf-8"))
    while len(json_bytes) % 4:
        json_bytes += b" "
    total = 12 + 8 + len(json_bytes) + 8 + len(buffer)
    return (
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<I4s", len(json_bytes), b"JSON")
        + bytes(json_bytes)
        + struct.pack("<I4s", len(buffer), b"BIN\x00")
        + bytes(buffer)
    )
