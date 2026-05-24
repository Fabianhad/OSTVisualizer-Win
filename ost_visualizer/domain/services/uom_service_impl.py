from typing import List, Optional, Tuple
from .uom_service import (
    calculate_condition_quantities as _calculate_condition_quantities,
)
from .uom_service import calculate_net_area_sf as _calculate_net_area_sf


class UOMDomainService:
    def calculate_net_area_sf(
        self,
        position: List[float],
        hole_positions: Optional[List[List[float]]] = None,
    ) -> float:
        return _calculate_net_area_sf(position, hole_positions)

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
    ) -> Tuple[float, float, float]:
        return _calculate_condition_quantities(
            condition_type,
            calc_type1,
            calc_type2,
            calc_type3,
            uom1,
            uom2,
            uom3,
            width,
            height,
            depth,
            thickness,
            position,
            hole_positions,
            attachment_footprint,
            attachment_perimeter,
            rise,
            run,
            grid_size1,
            grid_size2,
            gap,
            curve,
            round_quantity,
            round_up,
        )
