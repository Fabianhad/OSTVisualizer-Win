from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, Tuple
from ..services.notes_tags import (
    FEET_PER_METRE,
    PercentOrLength,
    KeySpec,
    Length,
    SectionsOrLength,
    TagFraction,
    TagSchema,
    parse_notes_tags,
)

TOWER_CRANE_TAG = "crane"
MAST_PITCH_M = 1.52
MAST_BASE_M = 0.604
JIB_PITCH_M = 1.9973
JIB_FIRST_BAY_M = 1.103
JIB_TIP_LENGTH_M = 2.113
COUNTERJIB_PITCH_M = 1.8973
COUNTERJIB_FIRST_M = -1.597
HOIST_TOP_ABOVE_MAST_M = 5.483
HOOK_BELOW_ROPE_M = 1.151
TROLLEY_TRAVEL_START_M = 3.0
TROLLEY_TIP_CLEARANCE_M = 1.2
MAST_PITCH_FT = MAST_PITCH_M * FEET_PER_METRE
MAST_REACH_BASE_FT = MAST_BASE_M * FEET_PER_METRE
JIB_REACH_BASE_FT = (JIB_FIRST_BAY_M - JIB_PITCH_M + JIB_TIP_LENGTH_M) * FEET_PER_METRE
JIB_PITCH_FT = JIB_PITCH_M * FEET_PER_METRE
COUNTERJIB_PITCH_FT = COUNTERJIB_PITCH_M * FEET_PER_METRE
DEFAULT_MAST_SECTIONS = 25
DEFAULT_JIB_SECTIONS = 18
DEFAULT_COUNTERJIB_SECTIONS = 7
DEFAULT_TROLLEY_FRACTION = 0.79
DEFAULT_HOOK_ROPE_FT = 12.4
MIN_MAST_SECTIONS, MAX_MAST_SECTIONS = 1, 80
MIN_JIB_SECTIONS, MAX_JIB_SECTIONS = 4, 40
MIN_COUNTERJIB_SECTIONS, MAX_COUNTERJIB_SECTIONS = 2, 12
MIN_HOOK_ROPE_FT = 3.0
TYPE_CHANGE_HIDES_CRANE_WARNING = (
    "[crane]: the condition is no longer a count condition, so its tower crane "
    "will no longer show."
)
NOT_A_COUNT_CONDITION_WARNING = (
    "[crane]: only count conditions show a tower crane; the tag is ignored."
)
TOWER_CRANE_SCHEMA = TagSchema(
    TOWER_CRANE_TAG,
    (
        KeySpec(
            "mast",
            SectionsOrLength(MAST_PITCH_FT, reach_base_ft=MAST_REACH_BASE_FT),
            str(DEFAULT_MAST_SECTIONS),
            MIN_MAST_SECTIONS,
            MAX_MAST_SECTIONS,
            f"{MIN_MAST_SECTIONS} to {MAX_MAST_SECTIONS} sections",
        ),
        KeySpec(
            "jib",
            SectionsOrLength(JIB_PITCH_FT, reach_base_ft=JIB_REACH_BASE_FT),
            str(DEFAULT_JIB_SECTIONS),
            MIN_JIB_SECTIONS,
            MAX_JIB_SECTIONS,
            f"{MIN_JIB_SECTIONS} to {MAX_JIB_SECTIONS} sections",
        ),
        KeySpec(
            "counterjib",
            SectionsOrLength(COUNTERJIB_PITCH_FT),
            str(DEFAULT_COUNTERJIB_SECTIONS),
            MIN_COUNTERJIB_SECTIONS,
            MAX_COUNTERJIB_SECTIONS,
            f"{MIN_COUNTERJIB_SECTIONS} to {MAX_COUNTERJIB_SECTIONS} sections",
        ),
        KeySpec("trolley", PercentOrLength(), f"{DEFAULT_TROLLEY_FRACTION:.0%}"),
        KeySpec(
            "hook",
            Length(),
            f"{DEFAULT_HOOK_ROPE_FT:g} ft",
            MIN_HOOK_ROPE_FT,
            None,
            f"{MIN_HOOK_ROPE_FT:g} ft or more",
        ),
        KeySpec(
            "hookheight",
            Length(),
            "the hook rope length",
            0.0,
            None,
            "0 ft or more",
        ),
    ),
)
CONDITION_NOTES_SCHEMAS = (TOWER_CRANE_SCHEMA,)


def hoist_top_ft(mast: int) -> float:
    return (MAST_BASE_M + mast * MAST_PITCH_M + HOIST_TOP_ABOVE_MAST_M) * FEET_PER_METRE


def max_hook_rope_ft(mast: int) -> float:
    return hoist_top_ft(mast) - HOOK_BELOW_ROPE_M * FEET_PER_METRE


def jib_tip_ft(jib: int) -> float:
    return (
        JIB_FIRST_BAY_M + (jib - 1) * JIB_PITCH_M + JIB_TIP_LENGTH_M
    ) * FEET_PER_METRE


def trolley_travel_ft(jib: int) -> Tuple[float, float]:
    return (
        TROLLEY_TRAVEL_START_M * FEET_PER_METRE,
        jib_tip_ft(jib) - TROLLEY_TIP_CLEARANCE_M * FEET_PER_METRE,
    )


def _thousandths(value: float) -> float:
    return round(float(value), 3)


@dataclass(frozen=True)
class TowerCraneSpec:
    mast: int
    jib: int
    counterjib: int
    trolley_ft: float
    hook_rope_ft: float


@dataclass(frozen=True)
class TowerCraneTag:
    present: bool
    spec: Optional[TowerCraneSpec]
    warnings: Tuple[str, ...]
    notes: Tuple[str, ...] = ()


def _trolley_ft(value, jib: int, warnings: list) -> float:
    low, high = trolley_travel_ft(jib)
    if value is None:
        value = TagFraction(DEFAULT_TROLLEY_FRACTION)
    if isinstance(value, TagFraction):
        if value.value > 1.0:
            warnings.append(
                f"[crane]: a trolley position of {value.value * 100:g}% is outside "
                "0% to 100% of its travel; the jib tip end is used."
            )
        return low + min(value.value, 1.0) * (high - low)
    if low <= value.feet <= high:
        return value.feet
    warnings.append(
        f"[crane]: a trolley distance of {value.feet:.1f} ft is outside its travel "
        f"({low:.1f} ft to {high:.1f} ft from the mast); the nearest end is used."
    )
    return min(max(value.feet, low), high)


def _hook_rope_ft(values, mast: int, warnings: list) -> float:
    longest = max_hook_rope_ft(mast)
    rope = values.get("hook")
    height = values.get("hookheight")
    if rope is not None and height is not None:
        warnings.append(
            "[crane]: hook and hookheight are both given; hookheight is used."
        )
    if height is not None:
        highest = longest - MIN_HOOK_ROPE_FT
        if height.feet > highest:
            warnings.append(
                f"[crane]: a hook height of {height.feet:.1f} ft is above the "
                f"highest hook position ({highest:.1f} ft); "
                "the hook is raised as far as it goes."
            )
            return MIN_HOOK_ROPE_FT
        return longest - height.feet
    length = DEFAULT_HOOK_ROPE_FT if rope is None else rope.feet
    if length > longest:
        if rope is not None:
            warnings.append(
                f"[crane]: a hook rope of {length:.1f} ft is longer than the crane "
                f"is tall ({longest:.1f} ft); the hook rests at the footing."
            )
        return longest
    return length


@lru_cache(maxsize=1024)
def resolve_tower_crane(notes: str) -> TowerCraneTag:
    parsed = parse_notes_tags(notes, CONDITION_NOTES_SCHEMAS)
    tag = parsed.tag(TOWER_CRANE_TAG)
    warnings = [warning.message for warning in (*parsed.warnings, *tag.warnings)]
    if not tag.present:
        return TowerCraneTag(False, None, tuple(warnings))
    values = tag.values
    mast = values.get("mast", DEFAULT_MAST_SECTIONS)
    jib = values.get("jib", DEFAULT_JIB_SECTIONS)
    spec = TowerCraneSpec(
        mast=mast,
        jib=jib,
        counterjib=values.get("counterjib", DEFAULT_COUNTERJIB_SECTIONS),
        trolley_ft=_thousandths(_trolley_ft(values.get("trolley"), jib, warnings)),
        hook_rope_ft=_thousandths(_hook_rope_ft(values, mast, warnings)),
    )
    return TowerCraneTag(True, spec, tuple(warnings), tag.notes)


DEFAULT_TOWER_CRANE_SPEC: TowerCraneSpec = resolve_tower_crane(
    f"[{TOWER_CRANE_TAG}]"
).spec
