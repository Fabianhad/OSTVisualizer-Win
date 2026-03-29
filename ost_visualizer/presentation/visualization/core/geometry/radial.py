import math
from typing import List, Optional


def calc_circ_pts(
    segments: int, r_x: float, r_y: float = None, ang_off: float = 0.0, rot: float = 0.0
) -> List[List[float]]:
    r_y = r_y or r_x
    pts = []
    for i in range(segments):
        a = 2 * math.pi * i / segments + ang_off
        px, py = r_x * math.cos(a), r_y * math.sin(a)
        if rot != 0:
            px, py = (
                px * math.cos(rot) - py * math.sin(rot),
                px * math.sin(rot) + py * math.cos(rot),
            )
        pts.append([px, py])
    return pts


def calc_count_mesh_verts(
    x: float,
    y: float,
    width: float,
    depth: float,
    height: float,
    z_offset: float = 0,
    rotation: float = 0.0,
) -> List[List[float]]:
    hw, hd = width / 2, depth / 2
    corners = [[-hw, -hd], [hw, -hd], [hw, hd], [-hw, hd]]
    if rotation != 0:
        cos_r, sin_r = math.cos(rotation), math.sin(rotation)
        corners = [
            [px * cos_r - py * sin_r, px * sin_r + py * cos_r] for px, py in corners
        ]
    verts = []
    z_b, z_t = z_offset, z_offset + height
    for px, py in corners:
        tx, ty = x + px, y + py
        verts.append([tx, ty, z_b])
    for px, py in corners:
        tx, ty = x + px, y + py
        verts.append([tx, ty, z_t])
    return verts


def calc_isosceles_triangle_mesh_verts(
    x: float,
    y: float,
    width: float,
    depth: float,
    height: float,
    z_offset: float = 0,
    rotation: float = 0.0,
) -> List[List[float]]:
    hw, hd = width / 2, depth / 2
    corners = [[0, -hd], [hw, hd], [-hw, hd]]
    if rotation != 0:
        cos_r, sin_r = math.cos(rotation), math.sin(rotation)
        corners = [
            [px * cos_r - py * sin_r, px * sin_r + py * cos_r] for px, py in corners
        ]
    verts = []
    z_b, z_t = z_offset, z_offset + height
    for px, py in corners:
        tx, ty = x + px, y + py
        verts.append([tx, ty, z_b])
    for px, py in corners:
        tx, ty = x + px, y + py
        verts.append([tx, ty, z_t])
    return verts


def calc_rhombus_mesh_verts(
    x: float,
    y: float,
    width: float,
    height: float,
    z_offset: float = 0,
    rotation: float = 0.0,
) -> List[List[float]]:
    hw = width / 2
    horizontal_scale = 0.575
    h_half = hw * horizontal_scale
    corners = [[0, -hw], [h_half, 0], [0, hw], [-h_half, 0]]
    if rotation != 0:
        cos_r, sin_r = math.cos(rotation), math.sin(rotation)
        corners = [
            [px * cos_r - py * sin_r, px * sin_r + py * cos_r] for px, py in corners
        ]
    verts = []
    z_b, z_t = z_offset, z_offset + height
    for px, py in corners:
        tx, ty = x + px, y + py
        verts.append([tx, ty, z_b])
    for px, py in corners:
        tx, ty = x + px, y + py
        verts.append([tx, ty, z_t])
    return verts


def calc_radial_mesh_verts(
    x: float,
    y: float,
    r_x: float,
    r_y: Optional[float] = None,
    height: float = 1.0,
    segments: int = 24,
    z_offset: float = 0,
    rotation: float = 0.0,
    angle_offset: float = 0.0,
    include_centers: bool = True,
) -> List[List[float]]:
    pts_2d = calc_circ_pts(segments, r_x, r_y, angle_offset, rotation)
    verts = []
    z_b, z_t = z_offset, z_offset + height
    for z in [z_b, z_t]:
        for px, py in pts_2d:
            tx, ty = x + px, y + py
            verts.append([tx, ty, z])
    if include_centers:
        verts.extend([[x, y, z_b], [x, y, z_t]])
    return verts
