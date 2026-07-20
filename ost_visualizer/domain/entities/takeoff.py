from dataclasses import dataclass, field, fields
from typing import List, Mapping, Optional
from .area import UNASSIGNED_AREA_UID
from .condition import Condition

_ROOT_TAKEOFF_PARENT_UIDS = frozenset({"", "0"})


def find_takeoff_parent_cycle_uids(
    parent_uid_by_takeoff_uid: Mapping[str, str],
) -> set[str]:
    parent_map = {
        str(uid): str(parent_uid)
        for uid, parent_uid in parent_uid_by_takeoff_uid.items()
        if str(parent_uid) not in _ROOT_TAKEOFF_PARENT_UIDS
    }
    completed: set[str] = set()
    cycle_uids: set[str] = set()
    for start_uid in parent_map:
        if start_uid in completed:
            continue
        path: list[str] = []
        path_index: dict[str, int] = {}
        current_uid = start_uid
        while current_uid in parent_map and current_uid not in completed:
            if current_uid in path_index:
                cycle_uids.update(path[path_index[current_uid] :])
                break
            path_index[current_uid] = len(path)
            path.append(current_uid)
            current_uid = parent_map[current_uid]
        completed.update(path)
    return cycle_uids


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

    def has_valid_contract(self) -> bool:
        if any(field_info.name not in self.__dict__ for field_info in fields(self)):
            return False
        return (
            isinstance(self.uid, str)
            and bool(self.uid)
            and isinstance(self.condition_uid, str)
            and bool(self.condition_uid)
            and isinstance(self.page_uid, str)
            and bool(self.page_uid)
            and isinstance(self.area_uid, str)
            and isinstance(self.position, list)
            and all(type(value) in (int, float) for value in self.position)
            and type(self.rotation) in (int, float)
            and type(self.curve) is int
            and isinstance(self.parent_uid, str)
            and isinstance(self.is_negative, bool)
            and (
                self.dimension_font_name is None
                or isinstance(self.dimension_font_name, str)
            )
            and (
                self.dimension_font_color is None
                or type(self.dimension_font_color) is int
            )
            and (
                self.dimension_font_size is None
                or type(self.dimension_font_size) is int
            )
            and isinstance(self.dimension_font_bold, bool)
            and isinstance(self.dimension_font_italic, bool)
            and isinstance(self.dimension_font_underline, bool)
            and (self.name_font_name is None or isinstance(self.name_font_name, str))
            and (self.name_font_color is None or type(self.name_font_color) is int)
            and (self.name_font_size is None or type(self.name_font_size) is int)
            and isinstance(self.name_font_bold, bool)
            and isinstance(self.name_font_italic, bool)
            and isinstance(self.name_font_underline, bool)
        )

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
        return self.parent_uid not in _ROOT_TAKEOFF_PARENT_UIDS

    @property
    def has_valid_position(self) -> bool:
        return len(self.position) >= 4
