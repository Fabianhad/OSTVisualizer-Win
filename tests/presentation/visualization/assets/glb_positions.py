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


def glb_triangles(data: bytes, node_name: str):
    """The triangles (three ``(x, y, z)`` each) of one kit part, in its frame."""
    json_length = struct.unpack_from("<I", data, 12)[0]
    document = json.loads(data[20 : 20 + json_length])
    binary = data[20 + json_length + 8 :]
    triangles = []
    for node in document["nodes"]:
        if node.get("name") != node_name:
            continue
        m = node.get("matrix", _IDENTITY)
        for primitive in document["meshes"][node["mesh"]]["primitives"]:
            if primitive.get("mode", 4) != 4:
                continue
            accessor = document["accessors"][primitive["attributes"]["POSITION"]]
            view = document["bufferViews"][accessor["bufferView"]]
            unpack = struct.Struct("<3" + _FORMATS[accessor["componentType"]])
            stride = view.get("byteStride") or unpack.size
            start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
            points = []
            for index in range(accessor["count"]):
                x, y, z = unpack.unpack_from(binary, start + index * stride)
                points.append(
                    tuple(
                        m[row] * x + m[4 + row] * y + m[8 + row] * z + m[12 + row]
                        for row in range(3)
                    )
                )
            indices = document["accessors"][primitive["indices"]]
            index_view = document["bufferViews"][indices["bufferView"]]
            fmt = _FORMATS[indices["componentType"]]
            offset = index_view.get("byteOffset", 0) + indices.get("byteOffset", 0)
            values = struct.unpack_from(f"<{indices['count']}{fmt}", binary, offset)
            for i in range(0, len(values), 3):
                triangles.append(tuple(points[v] for v in values[i : i + 3]))
    return triangles


def open_edges(triangles, axis: int, plane: float, tolerance: float = 0.001):
    """The edges that only one triangle uses (cut, open ends) lying on the
    plane ``axis = plane``, as pairs of end points."""
    count, where = {}, {}
    for triangle in triangles:
        for i in range(3):
            a, b = triangle[i], triangle[(i + 1) % 3]
            ka = tuple(round(c / 0.0002) for c in a)
            kb = tuple(round(c / 0.0002) for c in b)
            if ka == kb:
                continue
            edge = (ka, kb) if ka < kb else (kb, ka)
            count[edge] = count.get(edge, 0) + 1
            where[ka], where[kb] = a, b
    return [
        (where[edge[0]], where[edge[1]])
        for edge, n in count.items()
        if n == 1 and all(abs(where[k][axis] - plane) <= tolerance for k in edge)
    ]


def distance_to_edges(point, edges):
    """Distance from ``point`` to the nearest of ``edges`` (segments)."""
    best = float("inf")
    for a, b in edges:
        ab = [b[k] - a[k] for k in range(3)]
        length = sum(c * c for c in ab)
        t = (
            0.0
            if length == 0.0
            else sum((point[k] - a[k]) * ab[k] for k in range(3)) / length
        )
        t = max(0.0, min(1.0, t))
        q = [a[k] + t * ab[k] for k in range(3)]
        best = min(best, sum((point[k] - q[k]) ** 2 for k in range(3)) ** 0.5)
    return best


def pieces(triangles):
    """The triangles grouped into connected pieces (shared vertex positions)."""
    parent = {}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    first = []
    for triangle in triangles:
        keys = [tuple(round(c / 0.0002) for c in p) for p in triangle]
        for key in keys:
            parent.setdefault(key, key)
        parent[find(keys[0])] = find(keys[1])
        parent[find(keys[1])] = find(keys[2])
        first.append(keys[0])
    groups = {}
    for triangle, key in zip(triangles, first):
        groups.setdefault(find(key), []).append(triangle)
    return list(groups.values())


def brace_slopes(triangles, along=0, up=1, across=2):
    """+1 for every side brace (a long flat bar in an ``along``/``up`` plane)
    that climbs as ``along`` grows, -1 for one that falls."""
    slopes = []
    for piece in pieces(triangles):
        points = [p for t in piece for p in t]
        span = [max(p[k] for p in points) - min(p[k] for p in points) for k in range(3)]
        if span[along] > 1.0 and span[up] > 0.9 and span[across] < 0.06:
            ma = sum(p[along] for p in points) / len(points)
            mu = sum(p[up] for p in points) / len(points)
            covariance = sum((p[along] - ma) * (p[up] - mu) for p in points)
            slopes.append(1 if covariance > 0 else -1)
    return slopes


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
