from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union
from ....application.dtos.color_dtos import ColorMappingResult, ColorWithOpacity
from ....application.interfaces.i_color_service import ColorRGBA
from ....domain.entities import pattern as pt
from ....domain.entities.condition import Condition
from ....domain.entities.config import Config


def parse_hex_color(color: str) -> Tuple[float, float, float]:
    hex_value = color.lstrip("#")
    if len(hex_value) != 6:
        return 0.5, 0.5, 0.5
    r = int(hex_value[0:2], 16) / 255.0
    g = int(hex_value[2:4], 16) / 255.0
    b = int(hex_value[4:6], 16) / 255.0
    return r, g, b


def _parse_rgba_string(color: str) -> ColorRGBA:
    values = color[color.index("(") + 1 : color.rindex(")")].split(",")
    r, g, b = (float(values[i].strip()) for i in range(3))
    a = float(values[3].strip()) if len(values) > 3 else 1.0
    if max(r, g, b) > 1.0:
        r /= 255.0
        g /= 255.0
        b /= 255.0
    return (
        max(0.0, min(1.0, r)),
        max(0.0, min(1.0, g)),
        max(0.0, min(1.0, b)),
        max(0.0, min(1.0, a)),
    )


def int_to_hex(color_fill) -> str:
    int_color = int(color_fill)
    r = int_color & 0xFF
    g = (int_color >> 8) & 0xFF
    b = (int_color >> 16) & 0xFF
    return f"#{r:02x}{g:02x}{b:02x}"


def hex_to_rgb(_hex: str) -> Tuple[float, float, float]:
    r = int(_hex[1:3], base=16) / 255.0
    g = int(_hex[3:5], base=16) / 255.0
    b = int(_hex[5:7], base=16) / 255.0
    return (r, g, b)


def hex_to_rgb_int(hex_color: str) -> List[int]:
    r, g, b = hex_to_rgb(hex_color)
    return [int(r * 255), int(g * 255), int(b * 255)]


def _as_grayscale(hex_color: str) -> str:
    r, g, b = parse_hex_color(hex_color)
    gray = 0.299 * r + 0.587 * g + 0.114 * b
    gray_int = int(gray * 255)
    return f"#{gray_int:02x}{gray_int:02x}{gray_int:02x}"


def _apply_transparent(
    color_map: Dict[str, ColorWithOpacity],
) -> Dict[str, ColorWithOpacity]:
    return {
        uid: ColorWithOpacity(hex=entry.hex, opacity=entry.opacity * 0.5)
        for uid, entry in color_map.items()
    }


def _apply_grayscale(
    color_map: Dict[str, ColorWithOpacity],
) -> Dict[str, ColorWithOpacity]:
    return {
        uid: ColorWithOpacity(hex=_as_grayscale(entry.hex), opacity=entry.opacity)
        for uid, entry in color_map.items()
    }


def _get_pattern_opacity(pattern_value) -> float:
    if pattern_value is None:
        return 1.0
    return pt.get_2d_opacity(int(pattern_value))


def _make_color_entry(color: str, opacity: float) -> ColorWithOpacity:
    opacity = max(0.0, min(1.0, float(opacity)))
    return ColorWithOpacity(hex=color, opacity=opacity)


def _create_hierarchy_map(
    bid_conditions,
    conditions_used: Iterable[str],
    *,
    apply_pattern_alpha: bool = False,
):
    conditions_by_type: Dict[str, List[Condition]] = {}
    for condition_uid in conditions_used:
        condition = bid_conditions[condition_uid]
        cdn_type = condition.cdn_type_name if condition.cdn_type_name else "Unknown"
        conditions_by_type.setdefault(cdn_type, []).append(condition)
    for cdn_type in conditions_by_type:
        conditions_by_type[cdn_type].sort(key=lambda c: (c.z_value or 0, c.name or ""))
    cdn_types_sorted = sorted(conditions_by_type.keys())
    condition_color_map: Dict[str, ColorWithOpacity] = {}
    hierarchy_map: Dict[str, list] = {}
    for cdn_type in cdn_types_sorted:
        hierarchy_map[cdn_type] = []
        seen_combinations: Dict[Tuple[str, int, str], list] = {}
        for condition in conditions_by_type[cdn_type]:
            color_fill = condition.color_fill or 0
            hex_color = int_to_hex(color_fill)
            opacity = (
                _get_pattern_opacity(condition.pattern) if apply_pattern_alpha else 1.0
            )
            condition_color_map[condition.uid] = _make_color_entry(hex_color, opacity)
            condition_name = condition.name or ""
            condition_z = condition.z_value or 0
            combo_key = (condition_name, condition_z, hex_color)
            if combo_key in seen_combinations:
                seen_combinations[combo_key].append(condition.uid)
            else:
                seen_combinations[combo_key] = [condition.uid]
                hierarchy_map[cdn_type].append(
                    {
                        "uid": condition.uid,
                        "name": condition_name,
                        "z_value": condition_z,
                        "color": hex_color,
                        "count": 1,
                    }
                )
        for legend_entry in hierarchy_map[cdn_type]:
            combo_key = (
                legend_entry["name"],
                legend_entry["z_value"],
                legend_entry["color"],
            )
            if combo_key in seen_combinations:
                legend_entry["count"] = len(seen_combinations[combo_key])
    return hierarchy_map, condition_color_map


class ColorService:
    def convert_to_rgba(
        self, color_entry: Union[str, dict, Sequence[object]]
    ) -> ColorRGBA:
        opacity = 1.0
        color_value: Union[str, Sequence[object]] = "#808080"
        if isinstance(color_entry, dict):
            color_value = color_entry.get("color", "#808080")
            opacity = color_entry.get("opacity", 1.0)
        elif isinstance(color_entry, (list, tuple)):
            if len(color_entry) >= 3 and all(
                isinstance(component, (int, float)) for component in color_entry[:3]
            ):
                color_value = color_entry[:3]
                if len(color_entry) > 3:
                    opacity = color_entry[3]
            elif color_entry:
                color_value = color_entry[0]
                if len(color_entry) > 1:
                    opacity = color_entry[1]
        elif isinstance(color_entry, str):
            color_value = color_entry
        opacity_float = float(opacity)
        opacity_float = max(0.0, min(1.0, opacity_float))
        if isinstance(color_value, str):
            if color_value.lower().startswith(("rgba", "rgb")):
                r, g, b, a = _parse_rgba_string(color_value)
                return r, g, b, max(0.0, min(1.0, opacity_float * a))
            r, g, b = parse_hex_color(color_value)
        elif isinstance(color_value, (list, tuple)) and len(color_value) >= 3:
            r = float(color_value[0])
            g = float(color_value[1])
            b = float(color_value[2])
            if max(r, g, b) > 1.0:
                r /= 255.0
                g /= 255.0
                b /= 255.0
        else:
            r, g, b = parse_hex_color("#808080")
        return (
            max(0.0, min(1.0, r)),
            max(0.0, min(1.0, g)),
            max(0.0, min(1.0, b)),
            opacity_float,
        )

    def as_hex_with_opacity(self, color_entry) -> ColorWithOpacity:
        color = "#808080"
        opacity = 1.0
        if isinstance(color_entry, dict):
            color = str(color_entry.get("color", color))
            opacity = color_entry.get("opacity", opacity)
        elif isinstance(color_entry, (tuple, list)):
            if len(color_entry) >= 3 and all(
                isinstance(component, (int, float)) for component in color_entry[:3]
            ):
                r, g, b, opacity = self.convert_to_rgba(color_entry)
                color = f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"
            elif color_entry:
                color = str(color_entry[0])
                if len(color_entry) > 1:
                    opacity = color_entry[1]
        elif isinstance(color_entry, str) and color_entry:
            color = color_entry
        opacity = max(0.0, min(1.0, float(opacity)))
        return ColorWithOpacity(hex=color, opacity=opacity)

    def is_inactive_area_takeoff(
        self,
        takeoff,
        page_area_selections: Optional[Dict[str, Optional[str]]],
    ) -> bool:
        if not page_area_selections:
            return False
        page_uid = str(takeoff.page_uid)
        selected_area_uid = page_area_selections.get(page_uid)
        if selected_area_uid is not None:
            takeoff_area_uid = takeoff.area_uid
            return takeoff_area_uid != selected_area_uid
        return False

    def get_condition_color(self, condition) -> List[int]:
        color_int = condition.color_fill if condition.color_fill is not None else 255
        hex_color = int_to_hex(color_int)
        return hex_to_rgb_int(hex_color)

    def get_color_mapping(
        self,
        bid_conditions,
        bid_takeoffs,
        display_mode: str = Config.DISPLAY_MODE_SOLID,
        grayscale_enabled: bool = True,
        extra_condition_uids=None,
    ):
        conditions_used = set()
        for takeoff in bid_takeoffs:
            condition_uid = takeoff.condition_uid
            if condition_uid in bid_conditions:
                conditions_used.add(condition_uid)
        if extra_condition_uids:
            conditions_used.update(
                uid for uid in extra_condition_uids if uid in bid_conditions
            )
        apply_pattern_alpha = display_mode == Config.DISPLAY_MODE_ORIGINAL
        hierarchy_map, condition_color_map = _create_hierarchy_map(
            bid_conditions, conditions_used, apply_pattern_alpha=apply_pattern_alpha
        )
        if display_mode == Config.DISPLAY_MODE_TRANSPARENT:
            condition_color_map = _apply_transparent(condition_color_map)
        if grayscale_enabled:
            condition_color_map = _apply_grayscale(condition_color_map)
            if hierarchy_map:
                for cdn_type in hierarchy_map:
                    for entry in hierarchy_map[cdn_type]:
                        entry["color"] = _as_grayscale(entry["color"])
        return ColorMappingResult(
            hierarchy_map=hierarchy_map,
            condition_color_map=condition_color_map,
        )

    def get_color_for_takeoff(
        self,
        takeoff,
        condition,
        color_map: Dict,
        display_mode: str,
        page_area_selections: Optional[Dict[str, Optional[str]]] = None,
        *,
        inactive_object_color: str,
    ) -> ColorWithOpacity:
        condition_uid = takeoff.condition_uid
        color_entry = color_map.get(condition_uid, "#808080")
        color_hex, opacity = self.as_hex_with_opacity(color_entry)
        if display_mode == Config.DISPLAY_MODE_ORIGINAL:
            pattern_type = condition.pattern if condition.pattern else pt.SOLID
            opacity = pt.get_3d_opacity(pattern_type)
        if self.is_inactive_area_takeoff(takeoff, page_area_selections):
            color_hex = inactive_object_color
        return ColorWithOpacity(hex=color_hex, opacity=opacity)

    def get_2d_color_for_takeoff(
        self,
        takeoff,
        condition,
        color_map: Dict,
        page_area_selections: Optional[Dict[str, Optional[str]]] = None,
        *,
        inactive_object_color: str,
    ) -> ColorWithOpacity:
        condition_uid = takeoff.condition_uid
        color_entry = color_map.get(condition_uid, "#808080")
        color_hex, opacity = self.as_hex_with_opacity(color_entry)
        if self.is_inactive_area_takeoff(takeoff, page_area_selections):
            color_hex = inactive_object_color
        return ColorWithOpacity(hex=color_hex, opacity=opacity)

    def int_to_hex(self, color_fill: int) -> str:
        return int_to_hex(color_fill)

    def hex_to_rgb_int(self, hex_color: str) -> List[int]:
        return hex_to_rgb_int(hex_color)

    def hex_to_rgb(self, _hex: str) -> Tuple[float, float, float]:
        return hex_to_rgb(_hex)

    def parse_hex_color(self, color: str) -> Tuple[float, float, float]:
        return parse_hex_color(color)
