from typing import Dict, Iterable, List, Tuple
from ..entities.condition import Condition
from ..entities.takeoff import Takeoff


def is_takeoff_visible(takeoff: Takeoff, bid_conditions: Dict[str, Condition]) -> bool:
    return takeoff.is_visible(bid_conditions)


def has_renderable_takeoff_position(takeoff: Takeoff, condition: Condition) -> bool:
    position_len = len(takeoff.position or [])
    if condition.is_count or condition.is_attachment:
        return position_len >= 2
    if condition.is_linear:
        return position_len >= 4
    if condition.is_area:
        return position_len >= 6
    return False


def is_takeoff_relevant_for_area_usage(
    takeoff: Takeoff, bid_conditions: Dict[str, Condition]
) -> bool:
    condition = takeoff.get_condition(bid_conditions)
    if condition is None:
        return False
    if takeoff.is_hole:
        return False
    if not is_takeoff_visible(takeoff, bid_conditions):
        return False
    return has_renderable_takeoff_position(takeoff, condition)


def group_takeoffs_by_type(
    bid_conditions: Dict[str, Condition], bid_takeoffs: List[Takeoff]
) -> Dict[int, List[Takeoff]]:
    takeoffs_by_type: Dict[int, List[Takeoff]] = {0: [], 1: [], 2: [], 3: []}
    for takeoff in bid_takeoffs:
        condition = takeoff.get_condition(bid_conditions)
        if not condition:
            continue
        if condition.condition_type in takeoffs_by_type:
            takeoffs_by_type[condition.condition_type].append(takeoff)
    return takeoffs_by_type


def group_area_takeoffs_with_holes(
    bid_takeoffs: List[Takeoff], bid_conditions: Dict[str, Condition]
) -> Tuple[List[Takeoff], Dict[str, List[Takeoff]]]:
    area_takeoffs = []
    non_area_takeoffs = []
    for t in bid_takeoffs:
        condition = bid_conditions.get(t.condition_uid)
        if condition and condition.is_area:
            area_takeoffs.append(t)
        else:
            non_area_takeoffs.append(t)
    if not area_takeoffs:
        return bid_takeoffs, {}
    takeoff_map = {t.uid: t for t in area_takeoffs}
    holes_map: Dict[str, List[Takeoff]] = {}
    child_uids: set = set()
    for takeoff in area_takeoffs:
        if takeoff.is_hole:
            parent_uid = takeoff.parent_uid
            if str(parent_uid) in takeoff_map:
                holes_map.setdefault(str(parent_uid), []).append(takeoff)
                child_uids.add(takeoff.uid)
    parent_takeoffs = [t for t in area_takeoffs if t.uid not in child_uids]
    return non_area_takeoffs + parent_takeoffs, holes_map


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
