from ....domain.entities.overlay import OST_OVERLAY_RECT_UNITS_PER_INCH


def default_overlay_rect(width_inches, height_inches) -> str:
    width = float(width_inches or 0.0) * OST_OVERLAY_RECT_UNITS_PER_INCH
    height = float(height_inches or 0.0) * OST_OVERLAY_RECT_UNITS_PER_INCH
    return f"0.000000,0.000000,{width:.6f},{height:.6f}"
