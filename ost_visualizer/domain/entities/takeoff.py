from dataclasses import dataclass, field
from typing import List, Optional
from .area import UNASSIGNED_AREA_UID
from .condition import Condition


@dataclass
class Takeoff:
    CURVE_DISABLED = -1
    CURVE_ENABLED = 0
    uid: str
    condition_uid: str
    page_uid: str = ""
    area_uid: str = UNASSIGNED_AREA_UID
    position: List[float] = field(default_factory=list)
    rotation: float = 0.0
    curve: int = -1
    parent_uid: str = "0"
    is_negative: bool = False
    dimension_font_name: Optional[str] = None
    dimension_font_color: Optional[int] = None
    dimension_font_size: Optional[int] = None
    dimension_font_bold: bool = False
    dimension_font_italic: bool = False
    dimension_font_underline: bool = False
    name_font_name: Optional[str] = None
    name_font_color: Optional[int] = None
    name_font_size: Optional[int] = None
    name_font_bold: bool = False
    name_font_italic: bool = False
    name_font_underline: bool = False

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
        return self.parent_uid not in ("0", "", "None", None)

    @property
    def has_valid_position(self) -> bool:
        return len(self.position) >= 4
