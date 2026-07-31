import math
from typing import Dict, List, Tuple

ARCH_SCALES: List[Tuple[float, float, str]] = [
    (0.03125, 12.0, '1/32" = 1\' 0"'),
    (0.0625, 12.0, '1/16" = 1\' 0"'),
    (0.09375, 12.0, '3/32" = 1\' 0"'),
    (0.125, 12.0, '1/8" = 1\' 0"'),
    (0.1875, 12.0, '3/16" = 1\' 0"'),
    (0.25, 12.0, '1/4" = 1\' 0"'),
    (0.375, 12.0, '3/8" = 1\' 0"'),
    (0.5, 12.0, '1/2" = 1\' 0"'),
    (0.75, 12.0, '3/4" = 1\' 0"'),
    (1.0, 12.0, '1" = 1\' 0"'),
    (1.5, 12.0, '1-1/2" = 1\' 0"'),
    (3.0, 12.0, '3" = 1\' 0"'),
]
CIVIL_SCALES: List[Tuple[float, float, str]] = [
    (1.0, 1.0, '1" = 1"'),
    (1.0, 120.0, '1" = 10\' 0"'),
    (1.0, 240.0, '1" = 20\' 0"'),
    (1.0, 360.0, '1" = 30\' 0"'),
    (1.0, 480.0, '1" = 40\' 0"'),
    (1.0, 600.0, '1" = 50\' 0"'),
    (1.0, 720.0, '1" = 60\' 0"'),
    (1.0, 840.0, '1" = 70\' 0"'),
    (1.0, 960.0, '1" = 80\' 0"'),
    (1.0, 1080.0, '1" = 90\' 0"'),
    (1.0, 1200.0, '1" = 100\' 0"'),
]
METRIC_SCALES: List[Tuple[float, float, str]] = [
    (1.0, 1000.0, "1 : 1000"),
    (1.0, 500.0, "1 : 500"),
    (1.0, 300.0, "1 : 300"),
    (1.0, 200.0, "1 : 200"),
    (1.0, 100.0, "1 : 100"),
    (1.0, 60.0, "1 : 60"),
    (1.0, 50.0, "1 : 50"),
    (1.0, 40.0, "1 : 40"),
    (1.0, 30.0, "1 : 30"),
    (1.0, 20.0, "1 : 20"),
    (1.0, 10.0, "1 : 10"),
    (1.0, 5.0, "1 : 5"),
    (1.0, 2.0, "1 : 2"),
    (1.0, 1.0, "1 : 1"),
    (10.0, 1.0, "10 : 1"),
    (20.0, 1.0, "20 : 1"),
    (50.0, 1.0, "50 : 1"),
]
SCALES_BY_STYLE: Dict[int, List[Tuple[float, float, str]]] = {
    1: ARCH_SCALES,
    2: CIVIL_SCALES,
    3: METRIC_SCALES,
}
ALL_SCALES: List[Tuple[float, float, str]] = ARCH_SCALES + CIVIL_SCALES + METRIC_SCALES


def format_custom_scale(sf1: float, sf2: float) -> str:
    """Return a readable label for a valid scale not listed in ``ALL_SCALES``."""
    try:
        drawing_units = float(sf1)
        real_units = float(sf2)
    except (TypeError, ValueError):
        return ""
    if (
        not math.isfinite(drawing_units)
        or not math.isfinite(real_units)
        or drawing_units <= 0.0
        or real_units <= 0.0
    ):
        return ""
    drawing_text = f"{drawing_units:.15g}"
    if math.isclose(real_units, 12.0, rel_tol=0.0, abs_tol=1e-9):
        return f'{drawing_text}" = 1\' 0"'
    return f"{drawing_text} : {real_units:.15g}"
