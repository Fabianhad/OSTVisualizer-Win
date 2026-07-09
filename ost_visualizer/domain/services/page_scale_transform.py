from __future__ import annotations
from typing import Iterable, List, Optional, Tuple

PageScale = Tuple[float, float]
SCALE_EPSILON = 1e-9


def page_scale_ratio(scale: Optional[PageScale]) -> float:
    if scale is None:
        return 1.0
    sf1, sf2 = scale
    try:
        sf1_value = float(sf1 or 0.0)
        sf2_value = float(sf2 or 0.0)
    except (TypeError, ValueError):
        return 1.0
    if sf1_value == 0.0:
        return 1.0
    return sf2_value / sf1_value


def position_rescale_factor_between_page_scales(
    source_scale: Optional[PageScale], target_scale: Optional[PageScale]
) -> float:
    source_ratio = page_scale_ratio(source_scale)
    target_ratio = page_scale_ratio(target_scale)
    if source_ratio == 0.0:
        return 1.0
    return target_ratio / source_ratio


def rescale_position_values(position: Iterable[object], factor: float) -> List[object]:
    scaled: List[object] = []
    for value in position:
        try:
            scaled.append(float(value) * factor)
        except (TypeError, ValueError):
            scaled.append(value)
    return scaled


def rescale_position_between_page_scales(
    position: Iterable[object],
    source_scale: Optional[PageScale],
    target_scale: Optional[PageScale],
) -> List[object]:
    factor = position_rescale_factor_between_page_scales(source_scale, target_scale)
    if abs(factor - 1.0) <= SCALE_EPSILON:
        return list(position)
    return rescale_position_values(position, factor)
