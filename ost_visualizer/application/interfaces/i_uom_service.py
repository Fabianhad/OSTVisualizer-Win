from typing import List, Optional, Protocol, Tuple


class IUOMService(Protocol):
    def calculate_bounding_box_inches(
        self, position: List[float]
    ) -> Tuple[float, float]: ...
    def calculate_net_area_sf(
        self,
        position: List[float],
        hole_positions: Optional[List[List[float]]] = None,
    ) -> float: ...
    def calculate_condition_quantities(
        self,
        condition_type: int,
        calc_type1: int,
        calc_type2: int,
        calc_type3: int,
        uom1: int,
        uom2: int,
        uom3: int,
        width: float,
        height: float,
        depth: float,
        thickness: float,
        position: Optional[List[float]] = None,
        hole_positions: Optional[List[List[float]]] = None,
        attachment_footprint: float = 0.0,
        attachment_perimeter: float = 0.0,
        rise: float = 0.0,
        run: float = 0.0,
        grid_size1: float = 0.0,
        grid_size2: float = 0.0,
        gap: float = 0.0,
        curve: int = -1,
        round_quantity: bool = False,
        round_up: float = 0.0,
    ) -> Tuple[float, float, float]: ...
