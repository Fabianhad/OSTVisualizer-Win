from typing import Any, Dict, NamedTuple


class ColorWithOpacity(NamedTuple):
    hex: str
    opacity: float


class ColorMappingResult(NamedTuple):
    hierarchy_map: Dict[str, Any]
    condition_color_map: Dict[str, Any]
