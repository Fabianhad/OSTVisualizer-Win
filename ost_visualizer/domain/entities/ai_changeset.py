import math
import unicodedata
from dataclasses import dataclass, replace
from typing import List, Optional, Tuple
from .database_descriptor import DatabaseBackend
from ..services.elevation import (
    format_structural_elevation,
    parse_elevation,
    reassemble_elevation,
)

MAX_CHANGESET_TAKEOFFS = 200
MAX_CHANGESET_NEW_CONDITIONS = 25
MAX_POLYGON_VERTICES = 2000
MAX_CHANGESET_VERTICES = 20000
MAX_OPEN_CHANGESETS_PER_BID = 5
CHANGESET_EXPIRY_SECONDS = 30 * 60
HIGH_IMPACT_CLOSING_SEGMENT_IN = 12.0
MAX_SLAB_THICKNESS_IN = 120.0
MAX_ABS_TOP_ELEVATION_IN = 100000.0
MAX_CONDITION_BASE_NAME_CHARS = 80
KIND_ELEMENTS = "elements"
KIND_SCALE = "scale"
CHANGESET_KINDS = (KIND_ELEMENTS, KIND_SCALE)
STATUS_PROPOSED = "proposed"
STATUS_PENDING_APPROVAL = "pending_approval"
STATUS_APPLYING = "applying"
STATUS_APPLIED = "applied"
STATUS_REJECTED = "rejected"
STATUS_DISCARDED = "discarded"
STATUS_EXPIRED = "expired"
STATUS_STALE = "stale"
STATUS_FAILED = "failed"
STATUS_UNDONE = "undone"
OPEN_STATUSES = (STATUS_PROPOSED, STATUS_PENDING_APPROVAL, STATUS_APPLYING)
ASSUMPTION_OPEN = "open"
ASSUMPTION_ACCEPTED = "accepted"
ASSUMPTION_OVERRIDDEN = "overridden"
IMPACT_HIGH = "high"
IMPACT_NORMAL = "normal"
SUBJECT_SCALE = "scale"
SUBJECT_THICKNESS = "thickness"
SUBJECT_TOP_ELEVATION = "top_elevation"
SUBJECT_CLOSING_SEGMENT = "closing_segment"
SUBJECT_OTHER = "other"
ASSUMPTION_SUBJECTS = (
    SUBJECT_SCALE,
    SUBJECT_THICKNESS,
    SUBJECT_TOP_ELEVATION,
    SUBJECT_CLOSING_SEGMENT,
    SUBJECT_OTHER,
)
_HIGH_IMPACT_SUBJECTS = (SUBJECT_SCALE, SUBJECT_THICKNESS, SUBJECT_TOP_ELEVATION)
EXISTING_CONDITION_PREFIX = "existing:"
ERROR_CHANGESET_TOO_LARGE = "changeset_too_large"
ERROR_INVALID_GEOMETRY = "invalid_geometry"
ERROR_ASSUMPTION_UNRESOLVED = "assumption_unresolved"
ERROR_STALE_CHANGESET = "stale_changeset"
ERROR_APPROVAL_REQUIRED = "approval_required"
ERROR_CHANGESET_NOT_FOUND = "not_found"
ERROR_INVALID_STATE = "invalid_state"
ERROR_SQL_APPLY_UNAVAILABLE = "sql_apply_unavailable"
SQL_APPLY_UNAVAILABLE_MESSAGE = (
    "AI takeoff changes cannot be applied to SQL Server bids yet. Read tools "
    "and proposals still work; enter the change by hand or use an Access bid."
)
_BIDI_FORMATTING = frozenset(
    "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
)


def apply_blocked_reason(descriptor) -> str:
    if descriptor is not None and descriptor.backend == DatabaseBackend.SQL_SERVER:
        return SQL_APPLY_UNAVAILABLE_MESSAGE
    return ""


class ChangesetError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def assumption_impact(subject: str, closing_length_in: Optional[float] = None) -> str:
    if subject in _HIGH_IMPACT_SUBJECTS:
        return IMPACT_HIGH
    if (
        subject == SUBJECT_CLOSING_SEGMENT
        and closing_length_in is not None
        and closing_length_in > HIGH_IMPACT_CLOSING_SEGMENT_IN
    ):
        return IMPACT_HIGH
    return IMPACT_NORMAL


def clean_condition_base_name(text: str) -> str:
    kept = []
    for character in str(text or ""):
        if character in "\t\n\r\x0b\x0c":
            kept.append(" ")
        elif (
            character not in _BIDI_FORMATTING
            and unicodedata.category(character) != "Cc"
        ):
            kept.append(character)
    cleaned = " ".join("".join(kept).split())
    cleaned = parse_elevation(cleaned).base_name.strip()
    cleaned = cleaned.replace("@", "at")
    return cleaned[:MAX_CONDITION_BASE_NAME_CHARS].strip() or "AI Slab"


@dataclass(frozen=True)
class ProposedCondition:
    key: str
    base_name: str
    thickness_in: Optional[float]
    top_elev_in: Optional[float]


def resolved_condition_name(condition: ProposedCondition) -> str:
    base = clean_condition_base_name(condition.base_name)
    if condition.top_elev_in is None:
        return base
    return reassemble_elevation(
        base, 0, format_structural_elevation(condition.top_elev_in)
    )


@dataclass(frozen=True)
class ProposedTakeoff:
    key: str
    page_uid: str
    condition_key: str
    polygon: Tuple[float, ...]
    holes: Tuple[Tuple[float, ...], ...] = ()

    @property
    def vertex_count(self) -> int:
        return (len(self.polygon) + sum(len(hole) for hole in self.holes)) // 2

    def validate(self) -> None:
        for ring in (self.polygon, *self.holes):
            _validate_ring(ring)
        for hole in self.holes:
            if not _ring_within(hole, self.polygon):
                raise ChangesetError(
                    ERROR_INVALID_GEOMETRY,
                    "Every hole must lie inside its slab outline",
                )


def _ring_points(ring: Tuple[float, ...]) -> List[Tuple[float, float]]:
    return [(ring[index], ring[index + 1]) for index in range(0, len(ring), 2)]


def _on_segment(point, start, end) -> bool:
    (px, py), (ax, ay), (bx, by) = point, start, end
    cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
    scale = max(1.0, math.hypot(bx - ax, by - ay))
    if abs(cross) > 1e-9 * scale * scale:
        return False
    return (
        min(ax, bx) - 1e-9 <= px <= max(ax, bx) + 1e-9
        and min(ay, by) - 1e-9 <= py <= max(ay, by) + 1e-9
    )


def _inside_or_on(point, points) -> bool:
    inside = False
    px, py = point
    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        if _on_segment(point, start, end):
            return True
        (ax, ay), (bx, by) = start, end
        if (ay > py) != (by > py) and px < (bx - ax) * (py - ay) / (by - ay) + ax:
            inside = not inside
    return inside


def _properly_cross(first_start, first_end, second_start, second_end) -> bool:
    def side(a, b, c) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    d1 = side(second_start, second_end, first_start)
    d2 = side(second_start, second_end, first_end)
    d3 = side(first_start, first_end, second_start)
    d4 = side(first_start, first_end, second_end)
    return d1 * d2 < 0.0 and d3 * d4 < 0.0


def _ring_within(inner: Tuple[float, ...], outer: Tuple[float, ...]) -> bool:
    inner_points = _ring_points(inner)
    outer_points = _ring_points(outer)
    if abs(polygon_area(inner)) >= abs(polygon_area(outer)):
        return False
    if not all(_inside_or_on(point, outer_points) for point in inner_points):
        return False
    for index, start in enumerate(inner_points):
        end = inner_points[(index + 1) % len(inner_points)]
        for other_index, other_start in enumerate(outer_points):
            other_end = outer_points[(other_index + 1) % len(outer_points)]
            if _properly_cross(start, end, other_start, other_end):
                return False
    return True


def _validate_ring(ring: Tuple[float, ...]) -> None:
    if len(ring) % 2 or len(ring) < 6:
        raise ChangesetError(
            ERROR_INVALID_GEOMETRY, "A polygon needs at least three points"
        )
    if not all(
        isinstance(value, (int, float)) and math.isfinite(value) for value in ring
    ):
        raise ChangesetError(
            ERROR_INVALID_GEOMETRY, "Polygon coordinates must be finite"
        )
    if abs(polygon_area(ring)) <= 1e-9:
        raise ChangesetError(ERROR_INVALID_GEOMETRY, "A polygon must enclose an area")
    if len(ring) // 2 > MAX_POLYGON_VERTICES:
        raise ChangesetError(
            ERROR_CHANGESET_TOO_LARGE,
            f"A polygon may have at most {MAX_POLYGON_VERTICES} vertices",
        )


def polygon_area(ring: Tuple[float, ...]) -> float:
    points = list(zip(ring[0::2], ring[1::2]))
    total = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        total += x1 * y2 - x2 * y1
    return total / 2.0


@dataclass(frozen=True)
class ProposedScale:
    page_uid: str
    sf1: float
    sf2: float
    previous_sf1: float
    previous_sf2: float
    error_pct: Optional[float] = None


@dataclass(frozen=True)
class ChangesetAssumption:
    uid: str
    subject: str
    target_key: str
    value: str
    reason: str
    sheet_ref: str
    impact: str
    status: str = ASSUMPTION_OPEN
    override_value: Optional[str] = None

    @property
    def is_blocking(self) -> bool:
        return self.impact == IMPACT_HIGH and self.status == ASSUMPTION_OPEN

    @property
    def effective_value(self) -> Optional[str]:
        if self.status == ASSUMPTION_OVERRIDDEN:
            return self.override_value
        if self.status == ASSUMPTION_ACCEPTED:
            return self.value
        return None


@dataclass(frozen=True)
class AiChangeset:
    uid: str
    database_id: str
    bid_uid: str
    bid_key: str
    kind: str
    created_at: float
    status: str = STATUS_PROPOSED
    conditions: Tuple[ProposedCondition, ...] = ()
    takeoffs: Tuple[ProposedTakeoff, ...] = ()
    scale: Optional[ProposedScale] = None
    assumptions: Tuple[ChangesetAssumption, ...] = ()
    base_tokens: Tuple[Tuple[str, str], ...] = ()
    summary: str = ""
    revision: int = 0

    @property
    def expires_at(self) -> float:
        return float(self.created_at) + CHANGESET_EXPIRY_SECONDS

    @property
    def vertex_count(self) -> int:
        return sum(takeoff.vertex_count for takeoff in self.takeoffs)

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    def is_expired(self, now: float) -> bool:
        return now >= self.expires_at

    @property
    def touched_resources(self) -> Tuple[str, ...]:
        resources = set()
        for takeoff in self.takeoffs:
            resources.add(f"page:{takeoff.page_uid}")
            if takeoff.condition_key.startswith(EXISTING_CONDITION_PREFIX):
                uid = takeoff.condition_key[len(EXISTING_CONDITION_PREFIX) :]
                resources.add(f"condition:{uid}")
        if self.scale is not None:
            resources.add(f"page:{self.scale.page_uid}")
            resources.add(f"page_takeoffs:{self.scale.page_uid}")
        return tuple(sorted(resources))

    @property
    def blocking_assumptions(self) -> Tuple[ChangesetAssumption, ...]:
        return tuple(item for item in self.assumptions if item.is_blocking)

    def validate_caps(self) -> None:
        if len(self.takeoffs) > MAX_CHANGESET_TAKEOFFS:
            raise ChangesetError(
                ERROR_CHANGESET_TOO_LARGE,
                f"A changeset may hold at most {MAX_CHANGESET_TAKEOFFS} takeoffs",
            )
        if len(self.conditions) > MAX_CHANGESET_NEW_CONDITIONS:
            raise ChangesetError(
                ERROR_CHANGESET_TOO_LARGE,
                f"A changeset may create at most {MAX_CHANGESET_NEW_CONDITIONS} conditions",
            )
        for takeoff in self.takeoffs:
            for ring in (takeoff.polygon, *takeoff.holes):
                if len(ring) // 2 > MAX_POLYGON_VERTICES:
                    raise ChangesetError(
                        ERROR_CHANGESET_TOO_LARGE,
                        f"A polygon may have at most {MAX_POLYGON_VERTICES} vertices",
                    )
        if self.vertex_count > MAX_CHANGESET_VERTICES:
            raise ChangesetError(
                ERROR_CHANGESET_TOO_LARGE,
                f"A changeset may hold at most {MAX_CHANGESET_VERTICES} vertices",
            )

    def resolved_conditions(self) -> Tuple[ProposedCondition, ...]:
        if self.blocking_assumptions:
            raise ChangesetError(
                ERROR_ASSUMPTION_UNRESOLVED,
                "High-impact assumptions must be accepted or overridden first",
            )
        resolved = []
        for condition in self.conditions:
            thickness = _resolved_number(
                condition.thickness_in,
                self.assumption_value(condition.key, SUBJECT_THICKNESS),
            )
            top = _resolved_number(
                condition.top_elev_in,
                self.assumption_value(condition.key, SUBJECT_TOP_ELEVATION),
            )
            if thickness is None or not 0.0 < thickness <= MAX_SLAB_THICKNESS_IN:
                raise ChangesetError(
                    ERROR_ASSUMPTION_UNRESOLVED,
                    f"Every slab needs a thickness above 0 and at most {MAX_SLAB_THICKNESS_IN:g} in",
                )
            if top is not None and abs(top) > MAX_ABS_TOP_ELEVATION_IN:
                raise ChangesetError(
                    ERROR_ASSUMPTION_UNRESOLVED,
                    f"Top elevations must be within {MAX_ABS_TOP_ELEVATION_IN:g} in",
                )
            resolved.append(replace(condition, thickness_in=thickness, top_elev_in=top))
        return tuple(resolved)

    def resolved_scale(self) -> ProposedScale:
        if self.scale is None:
            raise ChangesetError(ERROR_INVALID_STATE, "This changeset has no scale")
        if self.blocking_assumptions:
            raise ChangesetError(
                ERROR_ASSUMPTION_UNRESOLVED,
                "High-impact assumptions must be accepted or overridden first",
            )
        return self.scale

    def assumption_value(self, target_key: str, subject: str) -> Optional[str]:
        for item in self.assumptions:
            if item.target_key == target_key and item.subject == subject:
                value = item.effective_value
                if value is not None:
                    return value
        return None


def _resolved_number(
    proposed: Optional[float], assumed: Optional[str]
) -> Optional[float]:
    if assumed is not None:
        try:
            value = float(assumed)
        except ValueError:
            return None
        return value if math.isfinite(value) else None
    return proposed


@dataclass(frozen=True)
class ConditionQuantityDelta:
    key: str
    name: str
    takeoff_count: int
    area_sf: float
    volume_cy: Optional[float]


def quantity_delta(changeset: AiChangeset) -> Tuple[ConditionQuantityDelta, ...]:
    conditions = {condition.key: condition for condition in changeset.conditions}
    order = []
    totals = {}
    for takeoff in changeset.takeoffs:
        area = abs(polygon_area(takeoff.polygon)) - sum(
            abs(polygon_area(hole)) for hole in takeoff.holes
        )
        if takeoff.condition_key not in totals:
            order.append(takeoff.condition_key)
            totals[takeoff.condition_key] = [0, 0.0]
        totals[takeoff.condition_key][0] += 1
        totals[takeoff.condition_key][1] += area / 144.0
    deltas = []
    for key in order:
        count, area_sf = totals[key]
        condition = conditions.get(key)
        if condition is None:
            deltas.append(ConditionQuantityDelta(key, key, count, area_sf, None))
            continue
        thickness = _resolved_number(
            condition.thickness_in, changeset.assumption_value(key, SUBJECT_THICKNESS)
        )
        top = _resolved_number(
            condition.top_elev_in,
            changeset.assumption_value(key, SUBJECT_TOP_ELEVATION),
        )
        name = resolved_condition_name(replace(condition, top_elev_in=top))
        volume = None if thickness is None else area_sf * thickness / 12.0 / 27.0
        deltas.append(ConditionQuantityDelta(key, name, count, area_sf, volume))
    return tuple(deltas)
