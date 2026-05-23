from typing import List, Protocol, Tuple


class ILinearGeometry(Protocol):
    def calc_chord_length(
        self, x1: float, y1: float, x2: float, y2: float
    ) -> float: ...
    def proc_curved_pos(
        self,
        pos: List[float],
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        cx: float,
        cy: float,
    ) -> Tuple[float, float, float, float, float, float]: ...
    def gen_curve_pts(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        cx: float,
        cy: float,
        num_pts: int,
    ) -> List[float]: ...
    def gen_thick_curve_offsets(
        self,
        curve_pts: List[float],
        thickness: float,
    ) -> Tuple[List[float], List[float]]: ...
