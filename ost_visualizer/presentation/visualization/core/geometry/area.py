import math
from typing import List, Optional, Tuple
from ...utils.mesh import get_slope_factor
from . import ost_earcut as earcut


def _calc_poly_orient(verts: List[Tuple[float, float]]) -> float:
    n = len(verts)
    return (
        sum(
            verts[i][0] * verts[(i + 1) % n][1] - verts[(i + 1) % n][0] * verts[i][1]
            for i in range(n)
        )
        / 2
    )


def calc_area_mesh_verts(
    vertices: List[Tuple[float, float]],
    thickness: float,
    z_offset: float = 0,
    holes: Optional[List[List[Tuple[float, float]]]] = None,
    rise: Optional[float] = None,
    run: Optional[float] = None,
    rotation: float = 0.0,
) -> Tuple[
    List[List[float]],
    List[List[float]],
    List[List[List[float]]],
    List[List[List[float]]],
    bool,
]:
    if not vertices or len(vertices) < 3:
        return [], [], [], [], False
    verts = vertices
    holes = holes if holes else None
    rise_v, run_v, _, has_slope = get_slope_factor(rise, run)
    z_bot = z_offset
    bot_verts = [[x, y, z_bot] for x, y in verts]
    if has_slope and rise_v and run_v:
        xs, ys = zip(*verts)
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        rot = -rotation
        dx, dy = math.cos(rot), math.sin(rot)
        projs = [(x - cx) * dx + (y - cy) * dy for x, y in verts]
        min_p, max_p = min(projs), max(projs)
        span = max_p - min_p
        slope_h = span * abs(rise_v) / abs(run_v)
        asc = (rise_v > 0 and run_v > 0) or (rise_v < 0 and run_v < 0)

        def calc_z(x, y):
            proj = (x - cx) * dx + (y - cy) * dy
            prog = (proj - min_p) / span if span > 0 else 0
            h_chg = span * prog * abs(rise_v) / abs(run_v)
            return z_offset + thickness + (h_chg if asc else slope_h - h_chg)

        top_verts = [[x, y, calc_z(x, y)] for x, y in verts]
        if holes:
            bot_holes = [[[x, y, z_bot] for x, y in h] for h in holes]
            top_holes = [[[x, y, calc_z(x, y)] for x, y in h] for h in holes]
        else:
            bot_holes = top_holes = []
    else:
        z_top = z_offset + thickness
        top_verts = [[x, y, z_top] for x, y in verts]
        bot_holes = [[[x, y, z_bot] for x, y in h] for h in holes] if holes else []
        top_holes = [[[x, y, z_top] for x, y in h] for h in holes] if holes else []
    return bot_verts, top_verts, bot_holes, top_holes, has_slope


def calc_area_faces(
    bot_verts: List[List[float]],
    top_verts: List[List[float]],
    bot_holes: List[List[List[float]]] = None,
    top_holes: List[List[List[float]]] = None,
) -> Tuple[List[List[float]], List[List[int]]]:
    all_v = bot_verts + top_verts
    faces = []
    b_start, t_start = 0, len(bot_verts)
    h_b_starts, h_t_starts = [], []
    if bot_holes and top_holes:
        for bh, th in zip(bot_holes, top_holes):
            h_b_starts.append(len(all_v))
            all_v.extend(bh)
            h_t_starts.append(len(all_v))
            all_v.extend(th)

    def triangulate(verts, holes, start_idx, reverse=False):
        if len(verts) < 3:
            return
        flat = [c for v in verts for c in [v[0], v[1]]]
        h_idx = []
        if holes:
            for h in holes:
                h_idx.append(len(flat) // 2)
                flat.extend([c for v in h for c in [v[0], v[1]]])
        tris = earcut.earcut(flat, h_idx, 2)

        def map_idx(vid):
            if vid < len(verts):
                return start_idx + vid
            vid -= len(verts)
            for i, h in enumerate(holes or []):
                if vid < len(h):
                    return (h_b_starts if start_idx == b_start else h_t_starts)[i] + vid
                vid -= len(h)
            return start_idx

        for i in range(0, len(tris), 3):
            if i + 2 < len(tris):
                idxs = [map_idx(tris[i + j]) for j in range(3)]
                faces.append(idxs[::-1] if reverse else idxs)

    triangulate(bot_verts, bot_holes, b_start)
    triangulate(top_verts, top_holes, t_start, True)
    is_ccw = _calc_poly_orient([(v[0], v[1]) for v in bot_verts]) > 0
    n_verts = len(bot_verts)
    for i in range(n_verts):
        j = (i + 1) % n_verts
        bi, bj, ti, tj = b_start + i, b_start + j, t_start + i, t_start + j
        if is_ccw:
            faces.extend([[bi, ti, tj], [bi, tj, bj]])
        else:
            faces.extend([[bi, bj, tj], [bi, tj, ti]])
    if bot_holes and top_holes:
        for idx, (bh, th) in enumerate(zip(bot_holes, top_holes)):
            h_ccw = _calc_poly_orient([(v[0], v[1]) for v in bh]) > 0
            n_h = len(bh)
            hb_s, ht_s = h_b_starts[idx], h_t_starts[idx]
            for i in range(n_h):
                j = (i + 1) % n_h
                bi, bj, ti, tj = hb_s + i, hb_s + j, ht_s + i, ht_s + j
                if h_ccw:
                    faces.extend([[bi, bj, tj], [bi, tj, ti]])
                else:
                    faces.extend([[bi, ti, tj], [bi, tj, bj]])
    return all_v, faces


def get_area_mesh_edges(
    bot_verts: List[List[float]],
    bot_holes: List[List[List[float]]] = None,
    top_holes: List[List[List[float]]] = None,
) -> List[List[int]]:
    edges = []
    n = len(bot_verts)
    t_s = n
    edges.extend([[i, (i + 1) % n] for i in range(n)])
    edges.extend([[t_s + i, t_s + (i + 1) % n] for i in range(n)])
    edges.extend([[i, t_s + i] for i in range(n)])
    if bot_holes and top_holes:
        v_idx = t_s + n
        for bh, th in zip(bot_holes, top_holes):
            h_n = len(bh)
            hb_s, ht_s = v_idx, v_idx + h_n
            edges.extend([[hb_s + i, hb_s + (i + 1) % h_n] for i in range(h_n)])
            edges.extend([[ht_s + i, ht_s + (i + 1) % h_n] for i in range(h_n)])
            edges.extend([[hb_s + i, ht_s + i] for i in range(h_n)])
            v_idx = ht_s + h_n
    return edges
