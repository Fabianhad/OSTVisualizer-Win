from dataclasses import dataclass
from typing import Optional


@dataclass
class CreateConditionSpec:
    name: str = "Untitled"
    condition_type: int = 0
    backout: bool = False
    cdn_type_uid: Optional[str] = None
    layer_uid: Optional[str] = None
    height: float = 0.0
    width: float = 12.0
    depth: float = 0.0
    thickness: float = 4.0
    rise: float = 0.0
    run: float = 0.0
    display_size: float = 100.0
    shape: int = -1
    pattern: int = 0
    spacing: float = 4.0
    color_fill: int = 0
    color_line: int = 0
    uom1: int = 0
    uom2: int = -1
    uom3: int = -1
    calc_type1: int = 0
    calc_type2: int = 0
    calc_type3: int = 0
    notes: str = ""
    drop_run: bool = False
    drop_value: float = 0.0
    round_quantity: bool = False
    round_up: float = 0.0
    connect: bool = True
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
    folder_uid: Optional[str] = None
