from typing import List, Tuple
from . import ost_linear_geom as _native


class LinearGeometry:
    def calc_chord_length(self, x1: float, y1: float, x2: float, y2: float) -> float:
        return _native.calc_chord_length(x1, y1, x2, y2)

    def proc_curved_pos(
        self,
        pos: List[float],
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        cx: float,
        cy: float,
    ) -> Tuple[float, float, float, float, float, float]:
        return _native.proc_curved_pos(pos, x1, y1, x2, y2, cx, cy)

    def gen_curve_pts(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        cx: float,
        cy: float,
        num_pts: int,
    ) -> List[float]:
        return _native.gen_curve_pts(x1, y1, x2, y2, cx, cy, num_pts)

    def gen_thick_curve_offsets(
        self,
        curve_pts: List[float],
        thickness: float,
    ) -> Tuple[List[float], List[float]]:
        return _native.gen_thick_curve_offsets(curve_pts, thickness)
