from typing import Dict, List, Protocol, Tuple
from ...domain.entities.condition import Condition
from ...domain.entities.takeoff import Takeoff


class ITakeoffDomainService(Protocol):
    def group_takeoffs_by_type(
        self,
        bid_conditions: Dict[str, Condition],
        bid_takeoffs: List[Takeoff],
    ) -> Dict[int, List[Takeoff]]: ...
    def group_area_takeoffs_with_holes(
        self,
        bid_takeoffs: List[Takeoff],
        bid_conditions: Dict[str, Condition],
    ) -> Tuple[List[Takeoff], Dict[str, List[Takeoff]]]: ...
