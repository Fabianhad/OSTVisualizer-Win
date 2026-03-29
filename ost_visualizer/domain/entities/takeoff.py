from dataclasses import dataclass, field
from typing import List, Optional
from .condition import Condition


@dataclass
class Takeoff:
    CURVE_DISABLED = -1
    CURVE_ENABLED = 0
    uid: str
    condition_uid: str
    page_uid: str = ""
    area_uid: str = "0"
    position: List[float] = field(default_factory=list)
    rotation: float = 0.0
    curve: int = -1
    parent_uid: str = "0"
    is_negative: bool = False

    def is_visible(self, conditions: dict) -> bool:
        if not self.condition_uid:
            return True
        condition = conditions.get(self.condition_uid)
        if not condition:
            return True
        return condition.layer_visible

    def get_condition(self, conditions: dict) -> Optional[Condition]:
        return conditions.get(self.condition_uid)

    @property
    def is_hole(self) -> bool:
        return self.parent_uid not in ("0", "", None)

    @property
    def has_valid_position(self) -> bool:
        return len(self.position) >= 4
