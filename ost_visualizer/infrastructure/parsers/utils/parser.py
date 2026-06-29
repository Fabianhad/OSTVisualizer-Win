import logging
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)


def decode_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("latin-1")
    return str(value)


def parse_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        str_val = str(value).replace(",", ".")
        return float(str_val)
    except (ValueError, TypeError):
        return default


def remove_empty_folders(folders_dict):
    result = {}
    for folder_uid, folder_data in folders_dict.items():
        folder_data.subfolders = remove_empty_folders(folder_data.subfolders)
        if folder_data.pages or folder_data.subfolders:
            result[folder_uid] = folder_data
    return result


def parse_overlay_rect(
    overlay_rect_str: Optional[str],
) -> Tuple[float, float, float, float]:
    if not overlay_rect_str:
        return (0.0, 0.0, 0.0, 0.0)
    try:
        groups = overlay_rect_str.split(",")
        if len(groups) < 4:
            return (0.0, 0.0, 0.0, 0.0)
        values = []
        i = 0
        while i < len(groups) and len(values) < 4:
            if i + 1 < len(groups) and len(groups[i + 1]) == 6:
                num_str = f"{groups[i]}.{groups[i + 1]}"
                i += 2
            else:
                num_str = groups[i]
                i += 1
            values.append(float(num_str))
        x = values[0] if len(values) > 0 else 0.0
        y = values[1] if len(values) > 1 else 0.0
        width = values[2] if len(values) > 2 else 0.0
        height = values[3] if len(values) > 3 else 0.0
        return (x, y, width, height)
    except (ValueError, IndexError) as exc:
        logger.warning("Failed to parse OverlayRect %r: %s", overlay_rect_str, exc)
        return (0.0, 0.0, 0.0, 0.0)
