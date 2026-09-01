import math
import ntpath
from typing import Optional, Sequence
from ....domain.entities.overlay import overlay_units_per_sheet_inch

EMPTY_OVERLAY_RECT = (0.0, 0.0, 0.0, 0.0)
EMPTY_OVERLAY_RECT_STORAGE_MARKER = "*"


def overlay_path_storage_identity(path: object) -> str:
    text = str(path or "")
    if not text:
        return ""
    return ntpath.normcase(ntpath.normpath(text))


def _validated_overlay_rect(
    values: Sequence[object],
) -> tuple[float, float, float, float]:
    if len(values) != 4:
        raise ValueError("OverlayRect must contain exactly four values")
    try:
        rect = tuple(float(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise ValueError("OverlayRect values must be numeric") from exc
    if not all(math.isfinite(value) for value in rect):
        raise ValueError("OverlayRect values must be finite")
    if rect[2] < 0.0 or rect[3] < 0.0:
        raise ValueError("OverlayRect width and height cannot be negative")
    return rect


def parse_overlay_rect_storage(
    stored_rect: Optional[str],
) -> tuple[float, float, float, float]:
    if stored_rect is None:
        return EMPTY_OVERLAY_RECT
    text = str(stored_rect).strip()
    if not text or text == EMPTY_OVERLAY_RECT_STORAGE_MARKER:
        return EMPTY_OVERLAY_RECT
    return _validated_overlay_rect(tuple(part.strip() for part in text.split(",")))


def serialize_overlay_rect_storage(
    overlay_rect: tuple[float, float, float, float],
) -> str:
    rect = _validated_overlay_rect(overlay_rect)
    return ",".join(f"{value:.6f}" for value in rect)


def full_page_overlay_rect(
    width_inches: float,
    height_inches: float,
    scale_factor1: float,
    scale_factor2: float,
) -> str:
    overlay_units = overlay_units_per_sheet_inch(scale_factor1, scale_factor2)
    if overlay_units is None:
        raise ValueError("Overlay calibration must contain finite positive values")
    width = float(width_inches)
    height = float(height_inches)
    if not math.isfinite(width) or not math.isfinite(height):
        raise ValueError("Page dimensions must be finite")
    if width <= 0.0 or height <= 0.0:
        raise ValueError("Page dimensions must be positive")
    return serialize_overlay_rect_storage(
        (0.0, 0.0, width * overlay_units, height * overlay_units)
    )


def replacement_overlay_storage_values(
    overlay_image_path: str,
    width_inches: float,
    height_inches: float,
    scale_factor1: float,
    scale_factor2: float,
    *,
    original_image_path: str,
) -> dict[str, object]:
    path = str(overlay_image_path or "")
    values = {
        "OverlayImagePath": path,
        "OverlayRect": (
            full_page_overlay_rect(
                width_inches,
                height_inches,
                scale_factor1,
                scale_factor2,
            )
            if path
            else ""
        ),
        "OverlayOffsetX": 0.0,
        "OverlayOffsetY": 0.0,
        "OverlayRotation": 0.0,
        "OverlayResized": 0,
        "DeskewRotationOverlay": 0.0,
    }
    if not path:
        values["Show"] = 0
    elif not str(original_image_path or ""):
        values["Show"] = 1
    return values
