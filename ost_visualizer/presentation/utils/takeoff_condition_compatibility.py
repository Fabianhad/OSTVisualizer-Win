from typing import Iterable
from ...domain.entities.condition import Condition
from ...domain.entities.takeoff import Takeoff


def condition_reassign_geometry_type(condition: Condition) -> int | None:
    if condition.is_linear:
        return Condition.TYPE_LINEAR
    if condition.is_area:
        return Condition.TYPE_AREA
    if condition.is_count or condition.is_attachment:
        return Condition.TYPE_COUNT
    return None


def common_reassign_geometry_type(
    takeoffs: Iterable[Takeoff],
    conditions: dict[str, Condition],
) -> int | None:
    selected_type: int | None = None
    for takeoff in takeoffs:
        condition = conditions.get(takeoff.condition_uid)
        if condition is None:
            return None
        condition_type = condition_reassign_geometry_type(condition)
        if condition_type is None:
            return None
        if selected_type is None:
            selected_type = condition_type
        elif selected_type != condition_type:
            return None
    return selected_type


def condition_matches_reassign_geometry(
    condition: Condition,
    geometry_type: int,
) -> bool:
    return condition_reassign_geometry_type(condition) == geometry_type


def takeoffs_can_reassign_to_condition(
    takeoffs: Iterable[Takeoff],
    conditions: dict[str, Condition],
    condition_uid: str,
) -> bool:
    target = conditions.get(str(condition_uid))
    if target is None:
        return False
    source_type = common_reassign_geometry_type(takeoffs, conditions)
    return source_type is not None and condition_matches_reassign_geometry(
        target, source_type
    )
