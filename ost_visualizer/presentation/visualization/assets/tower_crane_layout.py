from __future__ import annotations
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import List, Mapping, Sequence, Tuple
from ....domain.entities.tower_crane_spec import TowerCraneSpec
from ....domain.services.notes_tags import FEET_PER_METRE
from .tower_crane_asset import (
    Bounds3,
    read_tower_crane_kit,
    tower_crane_kit_metadata,
)

Matrix = Tuple[float, ...]
Point = Tuple[float, float, float]
LayoutItem = Tuple[str, Matrix]
ROPE_PART = "rope"
PENDANT_THICKNESS = 1.5
TROLLEY_ROPE_START_M = 0.2
TROLLEY_ROPE_END_M = 0.3
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
    items: List[LayoutItem] = []

    def place(part: str, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> None:
        items.append((part, _translation(x, y, z)))

    def rope(start: Point, end: Point, thickness: float = 1.0) -> None:
        if math.dist(start, end) >= MIN_ROPE_M:
            items.append((ROPE_PART, _rope(start, end, thickness)))

    place("base")
    for bay in range(spec.mast):
        place("mast_b" if bay % 2 else "mast_a", y=mast["base_y"] + bay * mast["pitch"])
    top = mast["base_y"] + spec.mast * mast["pitch"]
    for part in ("slewing", "head", "jib_root", "cjib_root"):
        place(part, y=top)
    for bay in range(1, spec.jib - 1):
        place(
            "jib_b" if bay % 2 else "jib_a",
            x=jib["first_bay_x"] + bay * jib["pitch"],
            y=top,
        )
    tip_start = jib["first_bay_x"] + (spec.jib - 1) * jib["pitch"]
    tip = tip_start + jib["tip_length"]
    place("jib_tip", x=tip_start, y=top)
    head_jib = (anchors["head_jib"][0], top + anchors["head_jib"][1], 0.0)
    pendant_dx, pendant_y, pendant_z = anchors["jib_pendant"]
    lugs = [(tip_start + jib["lug_outer_dx"], anchors["jib_outer_pendant_dx"])]
    if spec.jib >= jib["lug_inner_min_bays"]:
        inner_bay = round(jib["lug_inner_fraction"] * spec.jib)
        lugs.append(
            (
                jib["first_bay_x"] + inner_bay * jib["pitch"] + jib["lug_inner_dx"],
                pendant_dx,
            )
        )
    for lug_x, attach_dx in lugs:
        place("jib_lug", x=lug_x, y=top)
        for side in (-1.0, 1.0):
            rope(
                head_jib,
                (lug_x + attach_dx, top + pendant_y, side * pendant_z),
                PENDANT_THICKNESS,
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
    head_counterjib = (
        anchors["head_counterjib"][0],
        top + anchors["head_counterjib"][1],
        0.0,
    )
    counter_dx, counter_y, counter_z = anchors["counterjib_pendant"]
    for side in (-1.0, 1.0):
        rope(
            head_counterjib,
            (end_plane + counter_dx, top + counter_y, side * counter_z),
            PENDANT_THICKNESS,
        )
    trolley_x = spec.trolley_ft / FEET_PER_METRE
    rope_length = spec.hook_rope_ft / FEET_PER_METRE
    sheave_dx, hoist_y = anchors["hoist_top"]
    hoist_y += top
    place("trolley", x=trolley_x, y=top)
    place("hook_block", x=trolley_x, y=hoist_y - rope_length)
    rope(
        (jib["start_x"] + TROLLEY_ROPE_START_M, hoist_y, 0.0),
        (trolley_x - sheave_dx, hoist_y, 0.0),
    )
    rope(
        (trolley_x + sheave_dx, hoist_y, 0.0),
        (tip - TROLLEY_ROPE_END_M, hoist_y, 0.0),
    )
    for side in (-1.0, 1.0):
        rope(
            (trolley_x + side * sheave_dx, hoist_y, 0.0),
            (
                trolley_x + side * anchors["hoist_bottom_dx"],
                hoist_y - rope_length,
                0.0,
            ),
        )
    for part, matrix in items:
        if _determinant(matrix) <= 0.0:
            raise ValueError(f"tower crane layout mirrors or flattens {part}")
    return TowerCraneLayout(tuple(items), _bounds(items, kit["parts"]))


@lru_cache(maxsize=1)
def shipped_tower_crane_kit() -> Mapping:
    return tower_crane_kit_metadata(read_tower_crane_kit())


@lru_cache(maxsize=256)
def tower_crane_layout(spec: TowerCraneSpec) -> TowerCraneLayout:
    return build_tower_crane_layout(spec, shipped_tower_crane_kit())
