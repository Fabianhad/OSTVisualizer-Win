import math
from typing import Any, Dict, List, Optional, Tuple
from ....application.interfaces.i_coordinate_transformer import ICoordinateTransformer
from ..utils.mesh import (
    get_box_edges,
    get_box_faces,
    get_radial_mesh_edges,
    get_radial_mesh_faces,
    get_rhombus_mesh_edges,
    get_rhombus_mesh_faces,
    get_triangle_mesh_edges,
    get_triangle_mesh_faces,
)
from .geometry.area import calc_area_faces, calc_area_mesh_verts, get_area_mesh_edges
from .geometry.ost_linear_geom import (
    calc_chord_length,
    calc_curve_segs,
    calc_linear_mesh_verts,
    gen_adv_curve_pts,
    gen_curved_wall_pts,
    get_curved_mesh_edges,
    get_curved_mesh_faces,
    proc_curved_pos,
    proc_slope_params,
)
from .geometry.radial import (
    calc_count_mesh_verts,
    calc_isosceles_triangle_mesh_verts,
    calc_radial_mesh_verts,
    calc_rhombus_mesh_verts,
)


class MeshData:
    def __init__(
        self,
        vertices: List[Tuple[float, float, float]],
        faces: List[Tuple[int, int, int]],
        edges: Optional[List[Tuple[int, int]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.vertices = vertices
        self.faces = faces
        self.edges = edges or []
        self.metadata = metadata or {}

    def __bool__(self):
        return bool(self.vertices) and bool(self.faces)


class MeshGenerator:
    def __init__(self, coord_system: ICoordinateTransformer):
        self._cs = coord_system

    @property
    def scale_ratio(self) -> float:
        return self._cs.scale_ratio

    def generate_area_mesh(
        self,
        vertices: List[Tuple[float, float]],
        thickness: float,
        z_offset: float = 0,
        holes: Optional[List[List[Tuple[float, float]]]] = None,
        rise: Optional[float] = None,
        run: Optional[float] = None,
        rotation: float = 0.0,
    ) -> Optional[MeshData]:
        if not vertices or len(vertices) < 3:
            return None
        verts_3d = self._cs.transform_vertices_to_3d(vertices)
        holes_3d = self._cs.transform_holes_to_3d(holes)
        real_thickness = self._cs.ost_to_real_units(thickness)
        real_z_offset = self._cs.ost_to_real_units(z_offset)
        real_rise = self._cs.ost_to_real_units(rise) if rise is not None else None
        real_run = self._cs.ost_to_real_units(run) if run is not None else None
        bv, tv, bh, th, has_slope = calc_area_mesh_verts(
            verts_3d,
            real_thickness,
            real_z_offset,
            holes_3d,
            real_rise,
            real_run,
            rotation,
        )
        if not bv:
            return None
        all_vertices, faces = calc_area_faces(bv, tv, bh, th)
        edges = get_area_mesh_edges(bv, bh, th)
        return MeshData(
            vertices=all_vertices,
            faces=faces,
            edges=edges,
            metadata={
                "type": "area",
                "has_slope": has_slope,
                "thickness": real_thickness,
                "z_offset": real_z_offset,
            },
        )

    def generate_linear_mesh(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        height: float,
        thickness: float,
        z_offset: float = 0,
        rise: Optional[float] = None,
        run: Optional[float] = None,
    ) -> Optional[MeshData]:
        x1_3d, y1_3d = self._cs.transform_to_3d(x1, y1)
        x2_3d, y2_3d = self._cs.transform_to_3d(x2, y2)
        real_height = self._cs.ost_to_real_units(height)
        real_thickness = self._cs.ost_to_real_units(thickness)
        real_z_offset = self._cs.ost_to_real_units(z_offset)
        real_rise = self._cs.ost_to_real_units(rise) if rise is not None else None
        real_run = self._cs.ost_to_real_units(run) if run is not None else None
        vertices, has_slope = calc_linear_mesh_verts(
            x1_3d,
            y1_3d,
            x2_3d,
            y2_3d,
            real_height,
            real_thickness,
            real_z_offset,
            real_rise,
            real_run,
        )
        if not vertices:
            return None
        faces = get_box_faces()
        edges = get_box_edges()
        return MeshData(
            vertices=vertices,
            faces=faces,
            edges=edges,
            metadata={
                "type": "linear",
                "has_slope": has_slope,
                "height": real_height,
                "thickness": real_thickness,
                "z_offset": real_z_offset,
            },
        )

    def generate_drop_stub_mesh(
        self,
        x_from: float,
        y_from: float,
        x2: float,
        y2: float,
        thickness: float,
        drop_value: float,
        z_offset: float,
        element_height: float,
        rise: Optional[float] = None,
        run: Optional[float] = None,
        slope_from_x: Optional[float] = None,
        slope_from_y: Optional[float] = None,
    ) -> Optional[MeshData]:
        if drop_value == 0:
            return None
        x_from_3d, y_from_3d = self._cs.transform_to_3d(x_from, y_from)
        x2_3d, y2_3d = self._cs.transform_to_3d(x2, y2)
        real_thickness = self._cs.ost_to_real_units(thickness)
        real_drop = self._cs.ost_to_real_units(abs(drop_value))
        real_z_offset = self._cs.ost_to_real_units(z_offset)
        real_height = self._cs.ost_to_real_units(element_height)
        half = real_thickness / 2
        dx, dy = x2_3d - x_from_3d, y2_3d - y_from_3d
        seg_len = math.sqrt(dx * dx + dy * dy)
        if seg_len < 0.001:
            return None
        dx_n, dy_n = dx / seg_len, dy / seg_len
        if slope_from_x is not None and slope_from_y is not None:
            sx_3d, sy_3d = self._cs.transform_to_3d(slope_from_x, slope_from_y)
            sdx, sdy = x2_3d - sx_3d, y2_3d - sy_3d
            chord_len = math.sqrt(sdx * sdx + sdy * sdy)
        else:
            chord_len = seg_len
        endpoint_v_chg = 0.0
        slope_over_stub = 0.0
        up = True
        if rise is not None and run is not None and run != 0:
            real_rise = self._cs.ost_to_real_units(rise)
            real_run = self._cs.ost_to_real_units(run)
            v_chg = chord_len * abs(real_rise) / abs(real_run)
            up = (real_rise > 0 and real_run > 0) or (real_rise < 0 and real_run < 0)
            endpoint_v_chg = v_chg if up else 0.0
            slope_over_stub = real_thickness * abs(real_rise) / abs(real_run)
        px, py = -dy_n * half, dx_n * half
        sx, sy = x2_3d - dx_n * real_thickness, y2_3d - dy_n * real_thickness
        ex, ey = x2_3d, y2_3d
        if up:
            z_extra_start = endpoint_v_chg - slope_over_stub
        else:
            z_extra_start = slope_over_stub
        z_extra_end = endpoint_v_chg
        if drop_value > 0:
            start_z_b = real_z_offset + z_extra_start + real_height
            start_z_t = real_z_offset + z_extra_start + real_height + real_drop
            end_z_b = real_z_offset + z_extra_end + real_height
            end_z_t = real_z_offset + z_extra_end + real_height + real_drop
        else:
            start_z_t = real_z_offset + z_extra_start
            start_z_b = real_z_offset + z_extra_start - real_drop
            end_z_t = real_z_offset + z_extra_end
            end_z_b = real_z_offset + z_extra_end - real_drop
        vertices = [
            (sx + px, sy + py, start_z_b),
            (sx - px, sy - py, start_z_b),
            (ex - px, ey - py, end_z_b),
            (ex + px, ey + py, end_z_b),
            (sx + px, sy + py, start_z_t),
            (sx - px, sy - py, start_z_t),
            (ex - px, ey - py, end_z_t),
            (ex + px, ey + py, end_z_t),
        ]
        faces = get_box_faces()
        edges = get_box_edges()
        return MeshData(
            vertices=vertices,
            faces=faces,
            edges=edges,
            metadata={
                "type": "drop_stub",
                "thickness": real_thickness,
                "z_offset": real_z_offset,
            },
        )

    def generate_curved_drop_stub_mesh(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        cx: float,
        cy: float,
        thickness: float,
        drop_value: float,
        z_offset: float,
        element_height: float,
        rise: Optional[float] = None,
        run: Optional[float] = None,
        position: Optional[List[float]] = None,
    ) -> Optional[MeshData]:
        if drop_value == 0:
            return None
        x1, y1, x2, y2, cx, cy = proc_curved_pos(position or [], x1, y1, x2, y2, cx, cy)
        x1_3d, y1_3d = self._cs.transform_to_3d(x1, y1)
        x2_3d, y2_3d = self._cs.transform_to_3d(x2, y2)
        cx_3d, cy_3d = self._cs.transform_to_3d(cx, cy)
        real_thickness = self._cs.ost_to_real_units(thickness)
        real_drop = self._cs.ost_to_real_units(abs(drop_value))
        real_z_offset = self._cs.ost_to_real_units(z_offset)
        real_height = self._cs.ost_to_real_units(element_height)
        h_len = calc_chord_length(x1_3d, y1_3d, x2_3d, y2_3d)
        real_rise = self._cs.ost_to_real_units(rise) if rise is not None else None
        real_run = self._cs.ost_to_real_units(run) if run is not None else None
        has_slope, v_chg, slope_up = proc_slope_params(real_rise, real_run, h_len)
        segs = calc_curve_segs(x1_3d, y1_3d, x2_3d, y2_3d, cx_3d, cy_3d)
        all_pts = gen_adv_curve_pts(x1_3d, y1_3d, x2_3d, y2_3d, cx_3d, cy_3d, segs)
        n_full = len(all_pts)
        if n_full < 2:
            return None
        ib_full, ob_full, it_full, ot_full = gen_curved_wall_pts(
            all_pts,
            real_thickness,
            real_height,
            real_z_offset,
            has_slope,
            v_chg,
            slope_up,
        )
        k = 0
        arc_len = 0.0
        for i in range(n_full - 2, -1, -1):
            px, py = all_pts[i]
            nxp, nyp = all_pts[i + 1]
            arc_len += math.sqrt((nxp - px) ** 2 + (nyp - py) ** 2)
            if arc_len >= real_thickness:
                k = i
                break
        n = n_full - k
        if n < 2:
            return None
        stub_ib, stub_ob, stub_it, stub_ot = [], [], [], []
        for j in range(n):
            idx = k + j
            if drop_value > 0:
                conn_i = it_full[idx]
                conn_o = ot_full[idx]
                stub_ib.append(conn_i)
                stub_ob.append(conn_o)
                stub_it.append((conn_i[0], conn_i[1], conn_i[2] + real_drop))
                stub_ot.append((conn_o[0], conn_o[1], conn_o[2] + real_drop))
            else:
                conn_i = ib_full[idx]
                conn_o = ob_full[idx]
                stub_ib.append((conn_i[0], conn_i[1], conn_i[2] - real_drop))
                stub_ob.append((conn_o[0], conn_o[1], conn_o[2] - real_drop))
                stub_it.append(conn_i)
                stub_ot.append(conn_o)
        vertices = stub_ib + stub_ob + stub_it + stub_ot
        faces = get_curved_mesh_faces(n)
        edges = get_curved_mesh_edges(n)
        return MeshData(
            vertices=vertices,
            faces=faces,
            edges=edges,
            metadata={
                "type": "curved_drop_stub",
                "thickness": real_thickness,
                "z_offset": real_z_offset,
            },
        )

    def generate_curved_mesh(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        cx: float,
        cy: float,
        height: float,
        thickness: float,
        z_offset: float = 0,
        segments: Optional[int] = None,
        rise: Optional[float] = None,
        run: Optional[float] = None,
        position: Optional[List[float]] = None,
    ) -> Optional[MeshData]:
        x1, y1, x2, y2, cx, cy = proc_curved_pos(position or [], x1, y1, x2, y2, cx, cy)
        x1_3d, y1_3d = self._cs.transform_to_3d(x1, y1)
        x2_3d, y2_3d = self._cs.transform_to_3d(x2, y2)
        cx_3d, cy_3d = self._cs.transform_to_3d(cx, cy)
        real_height = self._cs.ost_to_real_units(height)
        real_thickness = self._cs.ost_to_real_units(thickness)
        real_z_offset = self._cs.ost_to_real_units(z_offset)
        real_rise = self._cs.ost_to_real_units(rise) if rise is not None else None
        real_run = self._cs.ost_to_real_units(run) if run is not None else None
        segs = calc_curve_segs(x1_3d, y1_3d, x2_3d, y2_3d, cx_3d, cy_3d, segments)
        curve_pts = gen_adv_curve_pts(x1_3d, y1_3d, x2_3d, y2_3d, cx_3d, cy_3d, segs)
        if len(curve_pts) < 2:
            return None
        h_len = calc_chord_length(x1_3d, y1_3d, x2_3d, y2_3d)
        has_slope, v_chg, slope_up = proc_slope_params(real_rise, real_run, h_len)
        ib, ob, it, ot = gen_curved_wall_pts(
            curve_pts,
            real_thickness,
            real_height,
            real_z_offset,
            has_slope,
            v_chg,
            slope_up,
        )
        vertices = ib + ob + it + ot
        n = len(curve_pts)
        faces = get_curved_mesh_faces(n)
        edges = get_curved_mesh_edges(n)
        return MeshData(
            vertices=vertices,
            faces=faces,
            edges=edges,
            metadata={
                "type": "curved",
                "has_slope": has_slope,
                "segments": segs,
                "height": real_height,
                "thickness": real_thickness,
                "z_offset": real_z_offset,
            },
        )

    def generate_count_mesh(
        self,
        x: float,
        y: float,
        width: float,
        depth: float,
        height: float,
        z_offset: float = 0,
        rotation: float = 0.0,
    ) -> Optional[MeshData]:
        x_3d, y_3d = self._cs.transform_to_3d(x, y)
        real_width = self._cs.ost_to_real_units(width)
        real_depth = self._cs.ost_to_real_units(depth)
        real_height = self._cs.ost_to_real_units(height)
        real_z_offset = self._cs.ost_to_real_units(z_offset)
        vertices = calc_count_mesh_verts(
            x_3d, y_3d, real_width, real_depth, real_height, real_z_offset, -rotation
        )
        if not vertices:
            return None
        faces = get_box_faces()
        edges = get_box_edges()
        return MeshData(
            vertices=vertices,
            faces=faces,
            edges=edges,
            metadata={
                "type": "count",
                "width": real_width,
                "depth": real_depth,
                "height": real_height,
                "z_offset": real_z_offset,
            },
        )

    def generate_cylinder_mesh(
        self,
        x: float,
        y: float,
        diameter: float,
        height: float,
        z_offset: float = 0,
        rotation: float = 0.0,
        segments: int = 24,
    ) -> Optional[MeshData]:
        x_3d, y_3d = self._cs.transform_to_3d(x, y)
        real_diameter = self._cs.ost_to_real_units(diameter)
        real_height = self._cs.ost_to_real_units(height)
        real_z_offset = self._cs.ost_to_real_units(z_offset)
        vertices = calc_radial_mesh_verts(
            x_3d,
            y_3d,
            real_diameter / 2,
            None,
            real_height,
            segments,
            real_z_offset,
            -rotation,
            0.0,
            True,
        )
        if not vertices:
            return None
        faces = get_radial_mesh_faces(segments)
        edges = get_radial_mesh_edges(segments)
        return MeshData(
            vertices=vertices,
            faces=faces,
            edges=edges,
            metadata={
                "type": "cylinder",
                "diameter": real_diameter,
                "height": real_height,
                "z_offset": real_z_offset,
                "segments": segments,
            },
        )

    def generate_elliptical_cylinder_mesh(
        self,
        x: float,
        y: float,
        width: float,
        depth: float,
        height: float,
        z_offset: float = 0,
        rotation: float = 0.0,
        segments: int = 24,
    ) -> Optional[MeshData]:
        x_3d, y_3d = self._cs.transform_to_3d(x, y)
        real_width = self._cs.ost_to_real_units(width)
        real_depth = self._cs.ost_to_real_units(depth)
        real_height = self._cs.ost_to_real_units(height)
        real_z_offset = self._cs.ost_to_real_units(z_offset)
        vertices = calc_radial_mesh_verts(
            x_3d,
            y_3d,
            real_width / 2,
            real_depth / 2,
            real_height,
            segments,
            real_z_offset,
            -rotation,
            0.0,
            True,
        )
        if not vertices:
            return None
        faces = get_radial_mesh_faces(segments)
        edges = get_radial_mesh_edges(segments)
        return MeshData(
            vertices=vertices,
            faces=faces,
            edges=edges,
            metadata={
                "type": "elliptical_cylinder",
                "width": real_width,
                "depth": real_depth,
                "height": real_height,
                "z_offset": real_z_offset,
                "segments": segments,
            },
        )

    def generate_polygon_prism_mesh(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        sides: int,
        z_offset: float = 0,
        rotation: float = 0.0,
        angle_offset: float = 0.0,
    ) -> Optional[MeshData]:
        x_3d, y_3d = self._cs.transform_to_3d(x, y)
        real_width = self._cs.ost_to_real_units(width)
        real_height = self._cs.ost_to_real_units(height)
        real_z_offset = self._cs.ost_to_real_units(z_offset)
        vertices = calc_radial_mesh_verts(
            x_3d,
            y_3d,
            real_width / 2,
            None,
            real_height,
            sides,
            real_z_offset,
            -rotation,
            angle_offset,
            True,
        )
        if not vertices:
            return None
        faces = get_radial_mesh_faces(sides)
        edges = get_radial_mesh_edges(sides)
        return MeshData(
            vertices=vertices,
            faces=faces,
            edges=edges,
            metadata={
                "type": f"polygon_prism_{sides}",
                "width": real_width,
                "height": real_height,
                "z_offset": real_z_offset,
                "sides": sides,
            },
        )

    def generate_isosceles_triangle_prism_mesh(
        self,
        x: float,
        y: float,
        width: float,
        depth: float,
        height: float,
        z_offset: float = 0,
        rotation: float = 0.0,
    ) -> Optional[MeshData]:
        x_3d, y_3d = self._cs.transform_to_3d(x, y)
        real_width = self._cs.ost_to_real_units(width)
        real_depth = self._cs.ost_to_real_units(depth)
        real_height = self._cs.ost_to_real_units(height)
        real_z_offset = self._cs.ost_to_real_units(z_offset)
        vertices = calc_isosceles_triangle_mesh_verts(
            x_3d,
            y_3d,
            real_width,
            real_depth,
            real_height,
            real_z_offset,
            -rotation,
        )
        if not vertices:
            return None
        faces = get_triangle_mesh_faces()
        edges = get_triangle_mesh_edges()
        return MeshData(
            vertices=vertices,
            faces=faces,
            edges=edges,
            metadata={
                "type": "isosceles_triangle_prism",
                "width": real_width,
                "depth": real_depth,
                "height": real_height,
                "z_offset": real_z_offset,
            },
        )

    def generate_rhombus_prism_mesh(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        z_offset: float = 0,
        rotation: float = 0.0,
    ) -> Optional[MeshData]:
        x_3d, y_3d = self._cs.transform_to_3d(x, y)
        real_width = self._cs.ost_to_real_units(width)
        real_height = self._cs.ost_to_real_units(height)
        real_z_offset = self._cs.ost_to_real_units(z_offset)
        vertices = calc_rhombus_mesh_verts(
            x_3d,
            y_3d,
            real_width,
            real_height,
            real_z_offset,
            -rotation,
        )
        if not vertices:
            return None
        faces = get_rhombus_mesh_faces()
        edges = get_rhombus_mesh_edges()
        return MeshData(
            vertices=vertices,
            faces=faces,
            edges=edges,
            metadata={
                "type": "rhombus_prism",
                "width": real_width,
                "height": real_height,
                "z_offset": real_z_offset,
            },
        )
