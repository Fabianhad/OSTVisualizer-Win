import math
from typing import Optional

OST_PAGE_COORDINATE_DPI = 96.0


def overlay_units_per_sheet_inch(
    scale_factor1: object,
    scale_factor2: object,
) -> Optional[float]:
    try:
        sf1 = float(scale_factor1)
        sf2 = float(scale_factor2)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(sf1) or sf1 <= 0.0:
        return None
    ratio = sf2 / sf1
    return ratio if math.isfinite(ratio) and ratio > 0.0 else None
