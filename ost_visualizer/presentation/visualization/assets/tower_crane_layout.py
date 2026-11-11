from __future__ import annotations
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import List, Mapping, Sequence, Tuple
from ....domain.entities.tower_crane_spec import TowerCraneSpec
from ....domain.services.notes_tags import FEET_PER_METRE
from .tower_crane_asset import Bounds3
from .tower_crane_models import tower_crane_kit

Matrix = Tuple[float, ...]
Point = Tuple[float, float, float]
LayoutItem = Tuple[str, Matrix]
ROPE_PART = "rope"
MIN_ROPE_M = 0.05


@dataclass(frozen=True)
class TowerCraneLayout:
    items: Tuple[LayoutItem, ...]
    bounds: Bounds3

    @property
    def parts(self) -> Tuple[str, ...]:
        return tuple(part for part, _matrix in self.items)

    @property
    def flat_matrices(self) -> Tuple[float, ...]:
        return tuple(value for _part, matrix in self.items for value in matrix)


def _translation(x: float, y: float, z: float = 0.0) -> Matrix:
    return (1.0, 0.0, 0.0, x, 0.0, 1.0, 0.0, y, 0.0, 0.0, 1.0, z)


def _rope(start: Point, end: Point, thickness: float = 1.0) -> Matrix:
    direction = [end[k] - start[k] for k in range(3)]
    length = math.sqrt(sum(c * c for c in direction))
    along = [c / length for c in direction]
    reference = (0.0, 0.0, 1.0) if abs(along[2]) < 0.9 else (1.0, 0.0, 0.0)
    side = [
        along[1] * reference[2] - along[2] * reference[1],
        along[2] * reference[0] - along[0] * reference[2],
        along[0] * reference[1] - along[1] * reference[0],
    ]
    side_length = math.sqrt(sum(c * c for c in side))
    side = [c / side_length for c in side]
    other = [
        side[1] * along[2] - side[2] * along[1],
        side[2] * along[0] - side[0] * along[2],
        side[0] * along[1] - side[1] * along[0],
    ]
    return tuple(
        value
        for k in range(3)
        for value in (
            side[k] * thickness,
            along[k] * length,
            other[k] * thickness,
            start[k],
        )
    )


def _determinant(matrix: Matrix) -> float:
    a, b, c = matrix[0:3], matrix[4:7], matrix[8:11]
    return (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )


def _apply(matrix: Matrix, point: Sequence[float]) -> Point:
    return tuple(
        matrix[r * 4] * point[0]
        + matrix[r * 4 + 1] * point[1]
        + matrix[r * 4 + 2] * point[2]
        + matrix[r * 4 + 3]
        for r in range(3)
    )


def _bounds(items: Sequence[LayoutItem], part_bounds: Mapping[str, Mapping]) -> Bounds3:
    low = [math.inf] * 3
    high = [-math.inf] * 3
    for part, matrix in items:
        box = part_bounds[part]
        for corner in range(8):
            local = [
                box["max"][k] if corner & (1 << k) else box["min"][k] for k in range(3)
            ]
            point = _apply(matrix, local)
            for k in range(3):
                low[k] = min(low[k], point[k])
                high[k] = max(high[k], point[k])
    return (tuple(low), tuple(high))


def build_tower_crane_layout(spec: TowerCraneSpec, kit: Mapping) -> TowerCraneLayout:
    mast, jib, counterjib, anchors = (
        kit["mast"],
        kit["jib"],
        kit["counterjib"],
        kit["anchors"],
    )
    trolley_kit = kit["trolley"]
    pendant_thickness = kit["pendant_thickness"]
    items: List[LayoutItem] = []

    def place(part: str, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> None:
        items.append((part, _translation(x, y, z)))

    def rope(start: Point, end: Point, thickness: float = 1.0) -> None:
        if math.dist(start, end) >= MIN_ROPE_M:
            items.append((ROPE_PART, _rope(start, end, thickness)))

    place("base")
    mast_cycle = mast["cycle"]
    for bay in range(spec.mast):
        place(mast_cycle[bay % len(mast_cycle)], y=mast["base_y"] + bay * mast["pitch"])
    top = mast["base_y"] + spec.mast * mast["pitch"]
    for part in ("slewing", "head", "jib_root", "cjib_root"):
        place(part, y=top)
    jib_cycle = jib["cycle"]
    for bay in range(1, spec.jib - 1):
        place(
            jib_cycle[bay % len(jib_cycle)],
            x=jib["first_bay_x"] + bay * jib["pitch"],
            y=top,
        )
    tip_start = jib["first_bay_x"] + (spec.jib - 1) * jib["pitch"]
    tip = tip_start + jib["tip_length"]
    place("jib_tip", x=tip_start, y=top)
    head_x, head_dy, head_z = anchors["head_jib"]
    head_jib = (head_x, top + head_dy, head_z)
    jib_pendant = anchors["jib_pendant"]
    for lug in jib["lugs"]:
        if spec.jib < lug["min_bays"]:
            continue
        if lug["at"] == "tip":
            lug_x = tip_start + lug["dx"]
        else:
            bay = round(lug["fraction"] * spec.jib)
            lug_x = jib["first_bay_x"] + bay * jib["pitch"] + lug["dx"]
        place("jib_lug", x=lug_x, y=top)
        for lateral in jib_pendant["lateral"]:
            rope(
                head_jib,
                (lug_x + lug["attach_dx"], top + jib_pendant["dy"], lateral),
                pendant_thickness,
            )
    for section in range(spec.counterjib - 1):
        place(
            "cjib_section",
            x=counterjib["first_x"] - section * counterjib["pitch"],
            y=top,
        )
    end_plane = counterjib["first_x"] - (spec.counterjib - 1) * counterjib["pitch"]
    for part in ("cjib_end", "counterweight", "cjib_lug"):
        place(part, x=end_plane, y=top)
    counter_x, counter_dy, counter_z = anchors["head_counterjib"]
    head_counterjib = (counter_x, top + counter_dy, counter_z)
    counter_pendant = anchors["counterjib_pendant"]
    for lateral in counter_pendant["lateral"]:
        rope(
            head_counterjib,
            (
                end_plane + counter_pendant["dx"],
                top + counter_pendant["dy"],
                lateral,
            ),
            pendant_thickness,
        )
    lead = anchors.get("hoist_lead")
    if lead:
        start_dx, start_dy, start_z = lead["from"]
        end_x, end_dy, end_z = lead["to"]
        rope(
            (end_plane + start_dx, top + start_dy, start_z),
            (end_x, top + end_dy, end_z),
        )
    trolley_x = spec.trolley_ft / FEET_PER_METRE
    rope_length = spec.hook_rope_ft / FEET_PER_METRE
    hoist_y = top + anchors["hoist_top"][1]
    place("trolley", x=trolley_x, y=top)
    place("hook_block", x=trolley_x, y=hoist_y - rope_length)
    run_dx, run_dy, run_z = anchors["trolley_rope"]
    run_y = top + run_dy
    rope(
        (jib["start_x"] + trolley_kit["rope_start_dx"], run_y, run_z),
        (trolley_x - run_dx, run_y, run_z),
    )
    rope(
        (trolley_x + run_dx, run_y, run_z),
        (tip - trolley_kit["rope_end_dx"], run_y, run_z),
    )
    for top_dx, bottom_dx, fall_z in anchors["hoist_falls"]:
        rope(
            (trolley_x + top_dx, hoist_y, fall_z),
            (trolley_x + bottom_dx, hoist_y - rope_length, fall_z),
        )
    for part, matrix in items:
        if _determinant(matrix) <= 0.0:
            raise ValueError(f"tower crane layout mirrors or flattens {part}")
    return TowerCraneLayout(tuple(items), _bounds(items, kit["parts"]))


@lru_cache(maxsize=256)
def tower_crane_layout(spec: TowerCraneSpec) -> TowerCraneLayout:
    kit = tower_crane_kit(spec.model)
    if kit is None:
        raise ValueError(f"there is no tower crane kit for model {spec.model!r}")
    return build_tower_crane_layout(spec, kit.metadata)
