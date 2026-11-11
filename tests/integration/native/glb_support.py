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


def cube_glb(parts, node_names=None, line_indices=None):
    """GLB with one cube primitive per part.
    ``parts`` is a list of ``(name, half_size, centre, rgba, blend)`` in glTF
    metres (Y-up). Positions are plain floats, normals per face.
    Without ``node_names`` every part is a primitive of one unnamed node. With
    it (one entry per part, ``None`` for unnamed) the parts are grouped into one
    node and mesh per distinct name, in first-seen order.
    ``line_indices`` (one entry per part, ``None`` for no lines) adds a LINES
    primitive per part that shares the part's POSITION accessor and material.
    Each cube face owns vertices ``4 * face .. 4 * face + 3`` (faces in
    ``_CUBE_FACES`` order: +x, -x, +y, -y, +z, -z).
    """
    buffer = bytearray()
    views, accessors, primitives, materials = [], [], [], []
    line_indices = line_indices or [None] * len(parts)
    for (name, half, centre, rgba, blend), part_lines in zip(
        parts, line_indices, strict=True
    ):
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
        part_primitives = [
            {
                "attributes": {
                    "POSITION": position_index,
                    "NORMAL": position_index + 1,
                },
                "indices": position_index + 2,
                "material": len(materials),
            }
        ]
        if part_lines is not None:
            while len(buffer) % 4:
                buffer.append(0)
            start = len(buffer)
            for index in part_lines:
                buffer += struct.pack("<H", index)
            views.append(
                {
                    "buffer": 0,
                    "byteOffset": start,
                    "byteLength": len(buffer) - start,
                    "target": 34963,
                }
            )
            accessors.append(
                {
                    "bufferView": len(views) - 1,
                    "componentType": 5123,
                    "count": len(part_lines),
                    "type": "SCALAR",
                }
            )
            part_primitives.append(
                {
                    "attributes": {"POSITION": position_index},
                    "indices": len(accessors) - 1,
                    "material": len(materials),
                    "mode": 1,
                }
            )
        primitives.append(part_primitives)
        material = {
            "name": name,
            "pbrMetallicRoughness": {"baseColorFactor": list(rgba)},
        }
        if blend:
            material["alphaMode"] = "BLEND"
        materials.append(material)
    while len(buffer) % 4:
        buffer.append(0)
    if node_names is None:
        nodes = [{"mesh": 0}]
        meshes = [{"primitives": [p for group in primitives for p in group]}]
    else:
        grouped = {}
        for node_name, part_primitives in zip(node_names, primitives, strict=True):
            grouped.setdefault(node_name, []).extend(part_primitives)
        nodes, meshes = [], []
        for node_name, node_primitives in grouped.items():
            node = {"mesh": len(meshes)}
            if node_name is not None:
                node["name"] = node_name
            nodes.append(node)
            meshes.append({"primitives": node_primitives})
    document = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
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
