from typing import Dict, List, Tuple
from ..entities.condition import Condition
from ..entities.takeoff import Takeoff
from .takeoff_domain_service import (
    group_area_takeoffs_with_holes,
    group_takeoffs_by_type,
)


class TakeoffDomainService:
    def group_takeoffs_by_type(
        self,
        bid_conditions: Dict[str, Condition],
        bid_takeoffs: List[Takeoff],
    ) -> Dict[int, List[Takeoff]]:
        return group_takeoffs_by_type(bid_conditions, bid_takeoffs)

    def group_area_takeoffs_with_holes(
        self,
        bid_takeoffs: List[Takeoff],
        bid_conditions: Dict[str, Condition],
    ) -> Tuple[List[Takeoff], Dict[str, List[Takeoff]]]:
        return group_area_takeoffs_with_holes(bid_takeoffs, bid_conditions)
