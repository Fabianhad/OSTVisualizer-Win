from dataclasses import dataclass
from typing import Optional


@dataclass
class Condition:
    TYPE_LINEAR = 0
    TYPE_AREA = 1
    TYPE_COUNT = 2
    TYPE_ATTACHMENT = 3
    uid: str
    name: str = ""
    condition_type: int = 0
    thickness: float = 0.0
    height: float = 0.0
    width: float = 0.0
    depth: float = 0.0
    rise: float = 0.0
    run: float = 0.0
    shape: int = 0
    color_fill: int = 0
    color_line: int = 0
    z_value: float = 0.0
    is_top: bool = False
    cdn_type_uid: Optional[str] = None
    cdn_type_name: str = "Unknown"
    folder_uid: Optional[str] = None
    pattern: int = 0
    spacing: float = 0.0
    layer_visible: bool = True
    uom1: int = 0
    uom2: int = 0
    uom3: int = 0
    calc_type1: int = 0
    calc_type2: int = 0
    calc_type3: int = 0
    ref_no: int = 0
    display_size: float = 100.0
    drop_run: bool = False
    drop_value: float = 0.0
    notes: str = ""
    layer_uid: Optional[str] = None
    round_quantity: bool = False
    round_up: float = 0.0
    connect: bool = False
    connect_tolerance: float = 6.0
    trim: bool = False
    is_curved_segment: bool = False
    grid: bool = False
    grid_size1: float = 0.0
    grid_size2: float = 0.0
    gap: float = 0.0
    display_dimension: bool = False
    display_name: bool = False
    display_grid_while_drawing: bool = False
    snap_to_linear: int = -1

    @property
    def is_linear(self) -> bool:
        return self.condition_type == self.TYPE_LINEAR

    @property
    def is_area(self) -> bool:
        return self.condition_type == self.TYPE_AREA

    @property
    def is_count(self) -> bool:
        return self.condition_type == self.TYPE_COUNT

    @property
    def is_attachment(self) -> bool:
        return self.condition_type == self.TYPE_ATTACHMENT
