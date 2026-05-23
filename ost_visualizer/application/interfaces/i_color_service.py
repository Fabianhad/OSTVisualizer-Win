from typing import Dict, List, Optional, Protocol, Sequence, Set, Tuple, Union
from ...domain.entities.condition import Condition
from ...domain.entities.takeoff import Takeoff
from ..dtos.color_dtos import ColorMappingResult, ColorWithOpacity

ColorRGBA = Tuple[float, float, float, float]


class IColorService(Protocol):
    def convert_to_rgba(
        self, color_entry: Union[str, dict, Sequence[float]]
    ) -> ColorRGBA: ...
    def as_hex_with_opacity(
        self, color_entry: Union[str, dict, Sequence[float]]
    ) -> ColorWithOpacity: ...
    def should_gray_out_takeoff(
        self,
        takeoff: Takeoff,
        page_area_selections: Optional[Dict[str, Optional[str]]],
    ) -> bool: ...
    def get_condition_color(self, condition: Condition) -> List[int]: ...
    def get_color_mapping(
        self,
        bid_conditions,
        bid_takeoffs,
        color_mode: str = "Solid",
        grayscale_enabled: bool = True,
        extra_condition_uids: Optional[Set[str]] = None,
    ) -> ColorMappingResult: ...
    def get_color_for_takeoff(
        self,
        takeoff: Takeoff,
        condition: Condition,
        color_map: Dict,
        color_mode: str,
        page_area_selections: Optional[Dict[str, Optional[str]]] = None,
    ) -> ColorWithOpacity: ...
    def int_to_hex(self, color_fill: int) -> str: ...
    def hex_to_rgb_int(self, hex_color: str) -> List[int]: ...
    def hex_to_rgb(self, _hex: str) -> Tuple[float, float, float]: ...
    def parse_hex_color(self, color: str) -> Tuple[float, float, float]: ...
