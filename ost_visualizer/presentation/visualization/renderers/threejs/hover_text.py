from __future__ import annotations
from typing import Optional, Sequence, Tuple
from .....domain.services.elevation import (
    format_structural_elevation,
    strip_elevation_suffix,
)

_UPWARD = 0.01


def hover_name(name: str) -> str:
    text = str(name or "").strip()
    return strip_elevation_suffix(text).strip() or text


def hover_elevations(
    vertices: Sequence[Sequence[float]], faces: Sequence[Sequence[int]]
) -> Optional[Tuple[str, str]]:
    triangles = [face[:3] for face in faces if len(face) >= 3]
    if not vertices or not triangles:
        return None
    heights = [float(v[2]) for v in vertices]
    volume6 = 0.0
    normals = []
    for i, j, k in triangles:
        a, b, c = vertices[i], vertices[j], vertices[k]
        u = [b[n] - a[n] for n in range(3)]
        w = [c[n] - a[n] for n in range(3)]
        normals.append(
            (
                u[1] * w[2] - u[2] * w[1],
                u[2] * w[0] - u[0] * w[2],
                u[0] * w[1] - u[1] * w[0],
            )
        )
        volume6 += (
            a[0] * (b[1] * c[2] - b[2] * c[1])
            - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0])
        )
    outward = -1.0 if volume6 < 0.0 else 1.0
    top_heights = []
    for (i, j, k), normal in zip(triangles, normals):
        length = (normal[0] ** 2 + normal[1] ** 2 + normal[2] ** 2) ** 0.5
        if length > 0.0 and outward * normal[2] / length > _UPWARD:
            top_heights.extend(float(vertices[n][2]) for n in (i, j, k))
    if not top_heights:
        top_heights = [max(heights)]
    low = format_structural_elevation(min(top_heights))
    high = format_structural_elevation(max(top_heights))
    top = low if low == high else f"{low} to {high}"
    return format_structural_elevation(min(heights)), top
