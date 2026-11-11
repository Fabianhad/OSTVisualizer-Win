from __future__ import annotations
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Mapping, Optional, Tuple
from ..services.notes_tags import (
    FEET_PER_METRE,
    Choice,
    PercentOrLength,
    KeySpec,
    Length,
    SectionsOrLength,
    TagFraction,
    TagSchema,
    parse_notes_tags,
)

TOWER_CRANE_TAG = "crane"
MODEL_KEY = "model"
MODEL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
TYPE_CHANGE_HIDES_CRANE_WARNING = (
    "[crane]: the condition is no longer a count condition, so its tower crane "
    "will no longer show."
)
NOT_A_COUNT_CONDITION_WARNING = (
    "[crane]: only count conditions show a tower crane; the tag is ignored."
)


@dataclass(frozen=True)
class TowerCraneModel:
    id: str
    label: str
    mast_base_m: float
    mast_pitch_m: float
    jib_first_bay_m: float
    jib_pitch_m: float
    jib_tip_length_m: float
    counterjib_pitch_m: float
    hoist_top_above_mast_m: float
    hook_below_rope_m: float
    trolley_travel_start_m: float
    trolley_tip_clearance_m: float
    default_mast: int
    default_jib: int
    default_counterjib: int
    default_trolley_fraction: float
    default_hook_rope_ft: float
    min_hook_rope_ft: float
    mast_range: Tuple[int, int]
    jib_range: Tuple[int, int]
    counterjib_range: Tuple[int, int]

    @classmethod
    def from_kit_metadata(cls, kit: Mapping) -> "TowerCraneModel":
        try:
            model, mast, jib = kit["model"], kit["mast"], kit["jib"]
            counterjib, hook, trolley = kit["counterjib"], kit["hook"], kit["trolley"]
            result = cls(
                id=str(model["id"]),
                label=str(model["label"]),
                mast_base_m=float(mast["base_y"]),
                mast_pitch_m=float(mast["pitch"]),
                jib_first_bay_m=float(jib["first_bay_x"]),
                jib_pitch_m=float(jib["pitch"]),
                jib_tip_length_m=float(jib["tip_length"]),
                counterjib_pitch_m=float(counterjib["pitch"]),
                hoist_top_above_mast_m=float(kit["anchors"]["hoist_top"][1]),
                hook_below_rope_m=float(hook["below_rope"]),
                trolley_travel_start_m=float(trolley["travel_start"]),
                trolley_tip_clearance_m=float(trolley["tip_clearance"]),
                default_mast=int(mast["default"]),
                default_jib=int(jib["default"]),
                default_counterjib=int(counterjib["default"]),
                default_trolley_fraction=float(trolley["default_fraction"]),
                default_hook_rope_ft=float(hook["default_rope_ft"]),
                min_hook_rope_ft=float(hook["min_rope_ft"]),
                mast_range=(int(mast["min"]), int(mast["max"])),
                jib_range=(int(jib["min"]), int(jib["max"])),
                counterjib_range=(int(counterjib["min"]), int(counterjib["max"])),
            )
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ValueError(
                f"tower crane kit metadata is incomplete: {error}"
            ) from error
        if not MODEL_ID_PATTERN.match(result.id):
            raise ValueError(f"tower crane model id {result.id!r} is not valid")
        for name, (low, high), default in (
            ("mast", result.mast_range, result.default_mast),
            ("jib", result.jib_range, result.default_jib),
            ("counterjib", result.counterjib_range, result.default_counterjib),
        ):
            if not 1 <= low <= default <= high:
                raise ValueError(
                    f"tower crane model {result.id!r}: {name} default {default} is "
                    f"outside {low} to {high}"
                )
        if min(result.mast_pitch_m, result.jib_pitch_m, result.counterjib_pitch_m) <= 0:
            raise ValueError(
                f"tower crane model {result.id!r} has a non-positive pitch"
            )
        return result

    @property
    def mast_pitch_ft(self) -> float:
        return self.mast_pitch_m * FEET_PER_METRE

    @property
    def mast_reach_base_ft(self) -> float:
        return self.mast_base_m * FEET_PER_METRE

    @property
    def jib_pitch_ft(self) -> float:
        return self.jib_pitch_m * FEET_PER_METRE

    @property
    def jib_reach_base_ft(self) -> float:
        return (
            self.jib_first_bay_m - self.jib_pitch_m + self.jib_tip_length_m
        ) * FEET_PER_METRE

    @property
    def counterjib_pitch_ft(self) -> float:
        return self.counterjib_pitch_m * FEET_PER_METRE

    def hoist_top_ft(self, mast: int) -> float:
        return (
            self.mast_base_m + mast * self.mast_pitch_m + self.hoist_top_above_mast_m
        ) * FEET_PER_METRE

    def max_hook_rope_ft(self, mast: int) -> float:
        return self.hoist_top_ft(mast) - self.hook_below_rope_m * FEET_PER_METRE

    def jib_tip_ft(self, jib: int) -> float:
        return (
            self.jib_first_bay_m + (jib - 1) * self.jib_pitch_m + self.jib_tip_length_m
        ) * FEET_PER_METRE

    def trolley_travel_ft(self, jib: int) -> Tuple[float, float]:
        return (
            self.trolley_travel_start_m * FEET_PER_METRE,
            self.jib_tip_ft(jib) - self.trolley_tip_clearance_m * FEET_PER_METRE,
        )


@dataclass(frozen=True)
class TowerCraneCatalog:
    """The models a [crane] tag can name; the first one is the default."""

    models: Tuple[TowerCraneModel, ...]

    def __post_init__(self) -> None:
        ids = [model.id for model in self.models]
        if len(set(ids)) != len(ids):
            raise ValueError(f"tower crane model ids repeat: {', '.join(ids)}")

    @property
    def ids(self) -> Tuple[str, ...]:
        return tuple(model.id for model in self.models)

    @property
    def default(self) -> Optional[TowerCraneModel]:
        return self.models[0] if self.models else None

    def get(self, model_id: str) -> Optional[TowerCraneModel]:
        return next((model for model in self.models if model.id == model_id), None)


def _sections_key(name: str, pitch_ft: float, default: int, limits, reach_base_ft=None):
    return KeySpec(
        name,
        SectionsOrLength(pitch_ft, reach_base_ft=reach_base_ft),
        str(default),
        limits[0],
        limits[1],
        f"{limits[0]} to {limits[1]} sections",
    )


@lru_cache(maxsize=64)
def tower_crane_schema(model: TowerCraneModel, model_ids: Tuple[str, ...]) -> TagSchema:
    return TagSchema(
        TOWER_CRANE_TAG,
        (
            _sections_key(
                "mast",
                model.mast_pitch_ft,
                model.default_mast,
                model.mast_range,
                model.mast_reach_base_ft,
            ),
            _sections_key(
                "jib",
                model.jib_pitch_ft,
                model.default_jib,
                model.jib_range,
                model.jib_reach_base_ft,
            ),
            _sections_key(
                "counterjib",
                model.counterjib_pitch_ft,
                model.default_counterjib,
                model.counterjib_range,
            ),
            KeySpec(
                "trolley", PercentOrLength(), f"{model.default_trolley_fraction:.0%}"
            ),
            KeySpec(
                "hook",
                Length(),
                f"{model.default_hook_rope_ft:g} ft",
                model.min_hook_rope_ft,
                None,
                f"{model.min_hook_rope_ft:g} ft or more",
            ),
            KeySpec(
                "hookheight",
                Length(),
                "the hook rope length",
                0.0,
                None,
                "0 ft or more",
            ),
            KeySpec(MODEL_KEY, Choice(model_ids), model_ids[0] if model_ids else ""),
        ),
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
    model: str


@dataclass(frozen=True)
class TowerCraneTag:
    present: bool
    spec: Optional[TowerCraneSpec]
    warnings: Tuple[str, ...]
    notes: Tuple[str, ...] = ()


def _trolley_ft(model: TowerCraneModel, value, jib: int, warnings: list) -> float:
    low, high = model.trolley_travel_ft(jib)
    if value is None:
        value = TagFraction(model.default_trolley_fraction)
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


def _hook_rope_ft(model: TowerCraneModel, values, mast: int, warnings: list) -> float:
    longest = model.max_hook_rope_ft(mast)
    rope = values.get("hook")
    height = values.get("hookheight")
    if rope is not None and height is not None:
        warnings.append(
            "[crane]: hook and hookheight are both given; hookheight is used."
        )
    if height is not None:
        highest = longest - model.min_hook_rope_ft
        if height.feet > highest:
            warnings.append(
                f"[crane]: a hook height of {height.feet:.1f} ft is above the "
                f"highest hook position ({highest:.1f} ft); "
                "the hook is raised as far as it goes."
            )
            return model.min_hook_rope_ft
        return longest - height.feet
    length = model.default_hook_rope_ft if rope is None else rope.feet
    if length > longest:
        if rope is not None:
            warnings.append(
                f"[crane]: a hook rope of {length:.1f} ft is longer than the crane "
                f"is tall ({longest:.1f} ft); the hook rests at the footing."
            )
        return longest
    return length


@lru_cache(maxsize=1024)
def has_tower_crane_tag(notes: str) -> bool:
    """Whether the notes hold a [crane] tag (whatever its arguments)."""
    schema = TagSchema(TOWER_CRANE_TAG, ())
    return parse_notes_tags(notes, (schema,)).tag(TOWER_CRANE_TAG).present


def _parse(notes: str, model: TowerCraneModel, catalog: TowerCraneCatalog):
    parsed = parse_notes_tags(notes, (tower_crane_schema(model, catalog.ids),))
    return parsed, parsed.tag(TOWER_CRANE_TAG)


@lru_cache(maxsize=1024)
def resolve_tower_crane(notes: str, catalog: TowerCraneCatalog) -> TowerCraneTag:
    """The crane a condition's notes ask for. ``[crane model=...]`` picks the
    model (the catalog's first model otherwise); every other default, limit and
    length conversion comes from that model."""
    model = catalog.default
    if model is None:
        return TowerCraneTag(has_tower_crane_tag(notes), None, ())
    parsed, tag = _parse(notes, model, catalog)
    chosen = tag.values.get(MODEL_KEY) if tag.present else None
    if chosen and chosen != model.id:
        model = catalog.get(chosen)
        parsed, tag = _parse(notes, model, catalog)
    warnings = [warning.message for warning in (*parsed.warnings, *tag.warnings)]
    if not tag.present:
        return TowerCraneTag(False, None, tuple(warnings))
    values = tag.values
    mast = values.get("mast", model.default_mast)
    jib = values.get("jib", model.default_jib)
    spec = TowerCraneSpec(
        mast=mast,
        jib=jib,
        counterjib=values.get("counterjib", model.default_counterjib),
        trolley_ft=_thousandths(
            _trolley_ft(model, values.get("trolley"), jib, warnings)
        ),
        hook_rope_ft=_thousandths(_hook_rope_ft(model, values, mast, warnings)),
        model=model.id,
    )
    return TowerCraneTag(True, spec, tuple(warnings), tag.notes)


def default_tower_crane_spec(catalog: TowerCraneCatalog) -> Optional[TowerCraneSpec]:
    return resolve_tower_crane(f"[{TOWER_CRANE_TAG}]", catalog).spec
