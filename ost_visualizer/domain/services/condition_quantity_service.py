from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple
from ..entities.condition import Condition
from ..entities.takeoff import Takeoff
from .uom_service import (
    CALC_AREA_VOLUME,
    CALC_VOLUME,
    UOM_CUBIC_YARDS,
    UOM_EACH,
    calculate_condition_quantities,
)


def compute_takeoff_cubic_yards(
    condition: Condition,
    takeoff: Takeoff,
    hole_takeoffs: Optional[List[Takeoff]] = None,
) -> float:
    volume_calc_type = CALC_AREA_VOLUME if condition.is_area else CALC_VOLUME
    cubic_yards, _unused_q2, _unused_q3 = calculate_condition_quantities(
        condition_type=condition.condition_type,
        calc_type1=volume_calc_type,
        calc_type2=0,
        calc_type3=0,
        uom1=UOM_CUBIC_YARDS,
        uom2=UOM_EACH,
        uom3=UOM_EACH,
        width=condition.width,
        height=condition.height,
        depth=condition.depth,
        thickness=condition.thickness,
        position=takeoff.position,
        hole_positions=[hole.position for hole in (hole_takeoffs or [])],
        rise=condition.rise,
        run=condition.run,
        grid_size1=condition.grid_size1,
        grid_size2=condition.grid_size2,
        gap=condition.gap,
        curve=takeoff.curve,
        round_quantity=condition.round_quantity,
        round_up=condition.round_up,
    )
    return -cubic_yards if takeoff.is_negative else cubic_yards


def compute_page_quantities(
    conditions: Dict[str, Condition],
    takeoffs: List[Takeoff],
    only_condition_uids: Optional[Set[str]] = None,
) -> Dict[str, Tuple[float, float, float]]:
    by_condition: Dict[str, List[Takeoff]] = defaultdict(list)
    for t in takeoffs:
        if only_condition_uids and t.condition_uid not in only_condition_uids:
            continue
        by_condition[t.condition_uid].append(t)
    holes_by_parent: Dict[str, List[Takeoff]] = defaultdict(list)
    for t in takeoffs:
        if t.parent_uid and t.parent_uid not in ("0", "None"):
            if not only_condition_uids or t.condition_uid in only_condition_uids:
                holes_by_parent[t.parent_uid].append(t)
    result: Dict[str, Tuple[float, float, float]] = {}
    if only_condition_uids:
        for cond_uid in only_condition_uids:
            if cond_uid in conditions:
                result[cond_uid] = (0.0, 0.0, 0.0)
    for cond_uid, cond_takeoffs in by_condition.items():
        condition = conditions.get(cond_uid)
        if not condition:
            continue
        total_q1 = 0.0
        total_q2 = 0.0
        total_q3 = 0.0
        primaries = [
            t
            for t in cond_takeoffs
            if not t.parent_uid or t.parent_uid in ("0", "None")
        ]
        for t in primaries:
            hole_positions = None
            children = holes_by_parent.get(t.uid)
            if children:
                hole_positions = [c.position for c in children if c.position]
            sign = -1.0 if t.is_negative else 1.0
            q1, q2, q3 = calculate_condition_quantities(
                condition_type=condition.condition_type,
                calc_type1=condition.calc_type1,
                calc_type2=condition.calc_type2,
                calc_type3=condition.calc_type3,
                uom1=condition.uom1,
                uom2=condition.uom2,
                uom3=condition.uom3,
                width=condition.width,
                height=condition.height,
                depth=condition.depth,
                thickness=condition.thickness,
                position=t.position,
                hole_positions=hole_positions,
                rise=condition.rise,
                run=condition.run,
                grid_size1=condition.grid_size1,
                grid_size2=condition.grid_size2,
                gap=condition.gap,
                curve=t.curve,
                round_quantity=condition.round_quantity,
                round_up=condition.round_up,
            )
            total_q1 += q1 * sign
            total_q2 += q2 * sign
            total_q3 += q3 * sign
        result[cond_uid] = (total_q1, total_q2, total_q3)
    return result
