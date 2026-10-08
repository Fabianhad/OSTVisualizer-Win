import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence, Set, Tuple
from ...domain.entities.ai_changeset import (
    ERROR_SQL_APPLY_UNAVAILABLE,
    MAX_ABS_TOP_ELEVATION_IN,
    MAX_SLAB_THICKNESS_IN,
    ASSUMPTION_SUBJECTS,
    IMPACT_HIGH,
    KIND_ELEMENTS,
    KIND_SCALE,
    STATUS_APPLIED,
    STATUS_APPLYING,
    STATUS_FAILED,
    STATUS_PENDING_APPROVAL,
    STATUS_REJECTED,
    STATUS_UNDONE,
    SUBJECT_CLOSING_SEGMENT,
    SUBJECT_SCALE,
    SUBJECT_THICKNESS,
    SUBJECT_TOP_ELEVATION,
    AiChangeset,
    ChangesetAssumption,
    ChangesetError,
    ProposedCondition,
    ProposedScale,
    ProposedTakeoff,
    assumption_impact,
    clean_condition_base_name,
    polygon_area,
    quantity_delta,
    resolved_condition_name,
)
from ...domain.services.ai_planar_regions import (
    RegionTooComplex,
    find_planar_regions,
    point_in_ring,
    ring_area,
)
from ..dtos.ai_takeoff_dtos import (
    ERROR_INVALID_ARGUMENT,
    ERROR_NOT_FOUND,
    STATUS_OK,
    AiTakeoffRequestError,
    PageSnapshot,
    UntrustedText,
    ok_result,
)
from .ai_changeset_store import AiChangesetProposals

ERROR_SCALE_UNSET = "scale_unset"
ERROR_INVALID_GEOMETRY = "invalid_geometry"
ELEMENT_KINDS = ("slab",)
PRESET_MATCH_PCT = 1.0
MIN_SCALE_DISTANCE_PTS = 1.0
SNAP_TOLERANCE_PTS = 0.5
MAX_GAP_CLOSE_IN = 48.0
MAX_REGIONS_RETURNED = 50
MAX_CACHED_REGIONS = 200
MAX_THICKNESS_IN = MAX_SLAB_THICKNESS_IN
_SCALE_ASSUMPTION_MESSAGE = (
    "The scale assumption cannot be added or revised; call propose_scale again"
)
MAX_ABS_ELEVATION_IN = MAX_ABS_TOP_ELEVATION_IN
_REPORTED_STATUSES = (
    STATUS_APPLYING,
    STATUS_APPLIED,
    STATUS_REJECTED,
    STATUS_FAILED,
    STATUS_UNDONE,
)
APPROVAL_MESSAGE = (
    "Waiting for the user to approve this changeset in OST Visualizer. Call "
    "apply_changeset again later to see whether it was applied or rejected."
)


@dataclass(frozen=True)
class RasterResult:
    ring: Tuple[Tuple[float, float], ...]
    leak: bool


@dataclass(frozen=True)
class _RegionRecord:
    page_uid: str
    polygon_ost: Tuple[float, ...]
    holes_ost: Tuple[Tuple[float, ...], ...]
    gap_lengths_in: Tuple[float, ...]
    leak: bool
    ost_per_page_point: float


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AiTakeoffRequestError(ERROR_INVALID_ARGUMENT, f"{label} must be a number")
    try:
        number = float(value)
    except OverflowError:
        number = math.inf
    if not math.isfinite(number):
        raise AiTakeoffRequestError(ERROR_INVALID_ARGUMENT, f"{label} must be finite")
    return number


def _numbers(values: Any, label: str, count: Optional[int] = None) -> Tuple[float, ...]:
    if not isinstance(values, list) or (count is not None and len(values) != count):
        expected = f"{count} numbers" if count is not None else "a list of numbers"
        raise AiTakeoffRequestError(ERROR_INVALID_ARGUMENT, f"{label} needs {expected}")
    return tuple(_number(value, label) for value in values)


def _text(value: Any, label: str, required: bool = False) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise AiTakeoffRequestError(ERROR_INVALID_ARGUMENT, f"{label} must be text")
    return value


def _request_error(exc: ChangesetError) -> AiTakeoffRequestError:
    return AiTakeoffRequestError(exc.code, exc.message)


class AiTakeoffProposalService:
    def __init__(
        self,
        read_service,
        proposals: AiChangesetProposals,
        presets: Sequence[Tuple[float, float, str]],
        raster_fill: Callable[..., Optional[object]],
        level_uids: Callable[[], Set[str]] = lambda: set(),
        apply_blocked: Callable[[str], str] = lambda _database_id: "",
    ):
        self._read_service = read_service
        self._proposals = proposals
        self._presets = tuple(
            (float(a), float(b), str(label)) for a, b, label in presets
        )
        self._raster_fill = raster_fill
        self._level_uids = level_uids
        self._apply_blocked = apply_blocked
        self._regions: "OrderedDict[str, _RegionRecord]" = OrderedDict()
        self._region_counter = 0
        self._lock = threading.Lock()

    def propose_scale(
        self,
        page_uid: Any,
        p1_pts: Any,
        p2_pts: Any,
        real_in: Any = None,
        preset: Any = None,
        reason: Any = None,
        sheet_ref: Any = None,
    ) -> dict:
        snapshot = self._read_service.page_snapshot(page_uid)
        first = _numbers(p1_pts, "p1_pts", 2)
        second = _numbers(p2_pts, "p2_pts", 2)
        distance = math.dist(first, second)
        if not distance >= MIN_SCALE_DISTANCE_PTS or not math.isfinite(distance):
            raise AiTakeoffRequestError(
                ERROR_INVALID_ARGUMENT,
                "p1_pts and p2_pts must be at least 1 point apart",
            )
        if real_in is None and preset is None:
            raise AiTakeoffRequestError(
                ERROR_INVALID_ARGUMENT, "Give real_in, preset or both"
            )
        measured = None
        if real_in is not None:
            real = _number(real_in, "real_in")
            if real <= 0.0:
                raise AiTakeoffRequestError(
                    ERROR_INVALID_ARGUMENT, "real_in must be positive"
                )
            measured = real / distance
            if not measured > 0.0:
                raise AiTakeoffRequestError(
                    ERROR_INVALID_ARGUMENT, "real_in gives a scale out of range"
                )
        if preset is not None:
            sf1, sf2 = self._preset(preset)
        else:
            sf1, sf2 = self._closest_scale(measured)
        chosen = sf2 / (72.0 * sf1)
        if not sf2 > 0.0 or not chosen > 0.0 or not math.isfinite(chosen):
            raise AiTakeoffRequestError(
                ERROR_INVALID_ARGUMENT, "The proposed scale is out of range"
            )
        error_pct = (
            None if measured is None else abs(chosen - measured) / measured * 100.0
        )
        page = self._read_service.page_entity(snapshot.uid)
        changeset = AiChangeset(
            uid="",
            database_id=self._open_database_id(),
            bid_uid=self._open_bid_uid(),
            bid_key="",
            kind=KIND_SCALE,
            created_at=0.0,
            scale=ProposedScale(
                snapshot.uid,
                sf1,
                sf2,
                float(page.scale_factor1 or 0.0),
                float(page.scale_factor2 or 0.0),
                error_pct,
            ),
            assumptions=(
                ChangesetAssumption(
                    uid="a1",
                    subject=SUBJECT_SCALE,
                    target_key=snapshot.uid,
                    value=f"{sf1:g}:{sf2:g}",
                    reason=_text(reason, "reason")
                    or "Scale proposed by the AI from a measured distance.",
                    sheet_ref=_text(sheet_ref, "sheet_ref"),
                    impact=IMPACT_HIGH,
                ),
            ),
            summary=f"Page scale {sf1:g} : {sf2:g}",
        )
        return ok_result(self.describe(self._add(changeset)))

    def find_regions(
        self,
        snapshot: PageSnapshot,
        bbox_pts: Any,
        gap_close_in: Any = 0.0,
        seed_pts: Any = None,
    ) -> dict:
        k = snapshot.ost_per_page_point
        if k is None or k <= 0.0:
            raise AiTakeoffRequestError(ERROR_SCALE_UNSET, "Set the page scale first")
        left, top, right, bottom = _numbers(bbox_pts, "bbox_pts", 4)
        if right <= left or bottom <= top:
            raise AiTakeoffRequestError(
                ERROR_INVALID_ARGUMENT, "bbox_pts must be [left, top, right, bottom]"
            )
        gap_in = _number(
            gap_close_in if gap_close_in is not None else 0.0, "gap_close_in"
        )
        if not 0.0 <= gap_in <= MAX_GAP_CLOSE_IN:
            raise AiTakeoffRequestError(
                ERROR_INVALID_ARGUMENT,
                f"gap_close_in must be between 0 and {MAX_GAP_CLOSE_IN:g}",
            )
        seed = None if seed_pts is None else _numbers(seed_pts, "seed_pts", 2)
        status, segments = self._read_service.page_segments_pts(
            snapshot, (left, top, right, bottom)
        )
        if status != STATUS_OK:
            return ok_result({"page_uid": snapshot.uid, "regions": []}, status)
        try:
            regions = find_planar_regions(segments, SNAP_TOLERANCE_PTS, gap_in / k)
        except RegionTooComplex as exc:
            raise AiTakeoffRequestError(ERROR_INVALID_ARGUMENT, str(exc)) from exc
        items = []
        if seed is not None:
            containing = [
                region for region in regions if point_in_ring(seed, region.outer)
            ]
            if containing:
                best = min(containing, key=lambda region: abs(ring_area(region.outer)))
                items.append(self._vector_item(snapshot, best, k))
            else:
                raster = self._raster_fill(
                    segments, (left, top, right, bottom), seed, max(gap_in / k, 1.0)
                )
                if raster is not None:
                    items.append(self._raster_item(snapshot, raster, k))
        else:
            items = [
                self._vector_item(snapshot, region, k)
                for region in regions[:MAX_REGIONS_RETURNED]
            ]
        return ok_result(
            {
                "page_uid": snapshot.uid,
                "regions": items,
                "truncated": seed is None and len(regions) > MAX_REGIONS_RETURNED,
            },
            STATUS_OK if items else "empty",
        )

    def propose_element(
        self,
        kind: Any,
        page_uid: Any,
        polygon_ost: Any = None,
        region_id: Any = None,
        holes_ost: Any = None,
        thickness_in: Any = None,
        top_elev_in: Any = None,
        level_id: Any = None,
        name: Any = None,
        summary: Any = None,
        condition_uid: Any = None,
    ) -> dict:
        if kind not in ELEMENT_KINDS:
            raise AiTakeoffRequestError(ERROR_INVALID_ARGUMENT, "kind must be slab")
        snapshot = self._read_service.page_snapshot(page_uid)
        if snapshot.ost_per_page_point is None:
            raise AiTakeoffRequestError(ERROR_SCALE_UNSET, "Set the page scale first")
        if (polygon_ost is None) == (region_id is None):
            raise AiTakeoffRequestError(
                ERROR_INVALID_ARGUMENT, "Give exactly one of polygon_ost or region_id"
            )
        gaps: Tuple[float, ...] = ()
        if region_id is not None:
            record = self._region(region_id, snapshot.uid)
            if not math.isclose(
                record.ost_per_page_point, snapshot.ost_per_page_point, rel_tol=1e-9
            ):
                raise AiTakeoffRequestError(
                    ERROR_NOT_FOUND,
                    "That region was found at a different page scale; call find_regions again",
                )
            if record.leak and not record.gap_lengths_in:
                raise AiTakeoffRequestError(
                    ERROR_INVALID_GEOMETRY, "That region leaks outside its outline"
                )
            polygon = record.polygon_ost
            holes = record.holes_ost
            gaps = record.gap_lengths_in
        else:
            polygon = _numbers(polygon_ost, "polygon_ost")
            if holes_ost is not None and not isinstance(holes_ost, list):
                raise AiTakeoffRequestError(
                    ERROR_INVALID_ARGUMENT, "holes_ost must be a list"
                )
            holes = tuple(_numbers(hole, "holes_ost") for hole in (holes_ost or []))
        thickness = (
            None if thickness_in is None else _number(thickness_in, "thickness_in")
        )
        if thickness is not None and not 0.0 < thickness <= MAX_THICKNESS_IN:
            raise AiTakeoffRequestError(
                ERROR_INVALID_ARGUMENT,
                f"thickness_in must be above 0 and at most {MAX_THICKNESS_IN:g}",
            )
        top = None if top_elev_in is None else _number(top_elev_in, "top_elev_in")
        if top is not None and abs(top) > MAX_ABS_ELEVATION_IN:
            raise AiTakeoffRequestError(
                ERROR_INVALID_ARGUMENT, "top_elev_in is out of range"
            )
        if (
            level_id is not None
            and _text(level_id, "level_id") not in self._level_uids()
        ):
            raise AiTakeoffRequestError(ERROR_INVALID_ARGUMENT, "Unknown level_id")
        base = clean_condition_base_name(
            _text(name, "name")
            or (f"Slab {thickness:g}in" if thickness is not None else "Slab")
        )
        existing = _text(condition_uid, "condition_uid")
        condition_key = f"existing:{existing}" if existing else "c1"
        conditions = (
            () if existing else (ProposedCondition("c1", base, thickness, top),)
        )
        assumptions = []
        if not existing:
            if thickness is None:
                assumptions.append(
                    self._assumption(
                        len(assumptions),
                        SUBJECT_THICKNESS,
                        "",
                        "The slab thickness was not given.",
                    )
                )
            if top is None:
                assumptions.append(
                    self._assumption(
                        len(assumptions),
                        SUBJECT_TOP_ELEVATION,
                        "",
                        "The top elevation was not given.",
                    )
                )
        for length in gaps:
            assumptions.append(
                self._assumption(
                    len(assumptions),
                    SUBJECT_CLOSING_SEGMENT,
                    f"{length:.2f} in",
                    "The outline was closed across a gap in the drawing.",
                    length,
                )
            )
        changeset = AiChangeset(
            uid="",
            database_id=self._open_database_id(),
            bid_uid=self._open_bid_uid(),
            bid_key="",
            kind=KIND_ELEMENTS,
            created_at=0.0,
            conditions=conditions,
            takeoffs=(
                ProposedTakeoff("t1", snapshot.uid, condition_key, polygon, holes),
            ),
            assumptions=tuple(assumptions),
            summary=_text(summary, "summary") or f"{base} on page {snapshot.uid}",
        )
        return ok_result(self.describe(self._add(changeset)))

    def update_assumption(
        self,
        changeset_id: Any,
        op: Any,
        assumption_id: Any = None,
        subject: Any = None,
        target_key: Any = None,
        value: Any = None,
        reason: Any = None,
        sheet_ref: Any = None,
        length_in: Any = None,
    ) -> dict:
        uid = _text(changeset_id, "changeset_id", required=True)
        try:
            if op == "add":
                if subject not in ASSUMPTION_SUBJECTS:
                    raise AiTakeoffRequestError(
                        ERROR_INVALID_ARGUMENT, "Unknown subject"
                    )
                if subject == SUBJECT_SCALE:
                    raise AiTakeoffRequestError(
                        ERROR_INVALID_ARGUMENT, _SCALE_ASSUMPTION_MESSAGE
                    )
                length = None if length_in is None else _number(length_in, "length_in")
                changeset = self._proposals.add_assumption(
                    uid,
                    subject,
                    _text(target_key, "target_key", required=True),
                    _text(value, "value"),
                    _text(reason, "reason"),
                    _text(sheet_ref, "sheet_ref"),
                    length,
                )
            elif op == "revise":
                assumption_uid = _text(assumption_id, "assumption_id", required=True)
                if any(
                    item.uid == assumption_uid and item.subject == SUBJECT_SCALE
                    for item in self._proposals.get(uid).assumptions
                ):
                    raise AiTakeoffRequestError(
                        ERROR_INVALID_ARGUMENT, _SCALE_ASSUMPTION_MESSAGE
                    )
                changeset = self._proposals.revise_assumption(
                    uid,
                    assumption_uid,
                    _text(value, "value"),
                    _text(reason, "reason"),
                )
            else:
                raise AiTakeoffRequestError(
                    ERROR_INVALID_ARGUMENT, "op must be add or revise"
                )
        except ChangesetError as exc:
            raise _request_error(exc) from exc
        return ok_result(self.describe(changeset))

    def apply_changeset(self, changeset_id: Any) -> dict:
        uid = _text(changeset_id, "changeset_id", required=True)
        try:
            changeset = self._proposals.get(uid)
            if changeset.status in _REPORTED_STATUSES:
                return ok_result(self.describe(changeset), changeset.status)
            blocked = self._apply_blocked(changeset.database_id)
            if blocked:
                raise AiTakeoffRequestError(ERROR_SQL_APPLY_UNAVAILABLE, blocked)
            changeset = self._proposals.request_apply(uid)
        except ChangesetError as exc:
            raise _request_error(exc) from exc
        data = self.describe(changeset)
        data["message"] = APPROVAL_MESSAGE
        return ok_result(data, STATUS_PENDING_APPROVAL)

    def discard_changeset(self, changeset_id: Any) -> dict:
        try:
            changeset = self._proposals.discard(
                _text(changeset_id, "changeset_id", required=True)
            )
        except ChangesetError as exc:
            raise _request_error(exc) from exc
        return ok_result(self.describe(changeset))

    def describe(self, changeset: AiChangeset) -> dict:
        data = {
            "changeset_id": changeset.uid,
            "status": changeset.status,
            "kind": changeset.kind,
            "summary": UntrustedText.of(changeset.summary).to_dict(),
            "conditions": [
                {
                    "key": condition.key,
                    "name": UntrustedText.of(
                        resolved_condition_name(condition)
                    ).to_dict(),
                    "thickness_in": condition.thickness_in,
                    "top_elev_in": condition.top_elev_in,
                }
                for condition in changeset.conditions
            ],
            "takeoffs": [
                {
                    "key": takeoff.key,
                    "page_uid": takeoff.page_uid,
                    "condition_key": takeoff.condition_key,
                    "vertex_count": takeoff.vertex_count,
                    "hole_count": len(takeoff.holes),
                }
                for takeoff in changeset.takeoffs
            ],
            "assumptions": [
                {
                    "id": item.uid,
                    "subject": item.subject,
                    "target_key": item.target_key,
                    "value": UntrustedText.of(item.value).to_dict(),
                    "reason": UntrustedText.of(item.reason).to_dict(),
                    "sheet_ref": UntrustedText.of(item.sheet_ref).to_dict(),
                    "impact": item.impact,
                    "status": item.status,
                }
                for item in changeset.assumptions
            ],
            "blocking_assumption_ids": [
                item.uid for item in changeset.blocking_assumptions
            ],
            "quantity_delta": [
                {
                    "key": delta.key,
                    "name": UntrustedText.of(delta.name).to_dict(),
                    "takeoff_count": delta.takeoff_count,
                    "area_sf": round(delta.area_sf, 4),
                    "volume_cy": (
                        None if delta.volume_cy is None else round(delta.volume_cy, 4)
                    ),
                }
                for delta in quantity_delta(changeset)
            ],
        }
        if changeset.scale is not None:
            data["scale"] = {
                "page_uid": changeset.scale.page_uid,
                "sf1_sf2": [changeset.scale.sf1, changeset.scale.sf2],
                "previous_sf1_sf2": [
                    changeset.scale.previous_sf1,
                    changeset.scale.previous_sf2,
                ],
                "error_pct": changeset.scale.error_pct,
            }
        record = self._proposals.applied_record(changeset.uid)
        if record is not None:
            data["applied"] = {
                "takeoff_uids": list(record.takeoff_uids),
                "condition_uids": list(record.condition_uids),
                "folder_uid": record.folder_uid,
            }
        return data

    def _add(self, changeset: AiChangeset) -> AiChangeset:
        try:
            return self._proposals.add(changeset)
        except ChangesetError as exc:
            raise _request_error(exc) from exc

    def _open_database_id(self) -> str:
        return str(self._read_service.open_bid_ref().file_path)

    def _open_bid_uid(self) -> str:
        return str(self._read_service.open_bid_ref().bid_uid)

    @staticmethod
    def _assumption(
        position: int,
        subject: str,
        value: str,
        reason: str,
        length: Optional[float] = None,
    ) -> ChangesetAssumption:
        return ChangesetAssumption(
            uid=f"a{position + 1}",
            subject=subject,
            target_key="c1",
            value=value,
            reason=reason,
            sheet_ref="",
            impact=assumption_impact(subject, length),
        )

    def _preset(self, preset: Any) -> Tuple[float, float]:
        text = _text(preset, "preset", required=True).strip()
        for sf1, sf2, label in self._presets:
            if label == text:
                return sf1, sf2
        parts = text.split(":")
        if len(parts) == 2:
            try:
                sf1, sf2 = float(parts[0]), float(parts[1])
            except ValueError:
                sf1 = sf2 = 0.0
            if sf1 > 0.0 and sf2 > 0.0 and math.isfinite(sf1) and math.isfinite(sf2):
                return sf1, sf2
        raise AiTakeoffRequestError(
            ERROR_INVALID_ARGUMENT, "Unknown preset; use a listed scale or sf1:sf2"
        )

    def _closest_scale(self, measured: float) -> Tuple[float, float]:
        best = None
        best_error = PRESET_MATCH_PCT
        for sf1, sf2, _label in self._presets:
            error = abs(sf2 / (72.0 * sf1) - measured) / measured * 100.0
            if error <= best_error:
                best, best_error = (sf1, sf2), error
        if best is not None:
            return best
        return 1.0, round(72.0 * measured, 6)

    def _store_region(self, record: _RegionRecord) -> str:
        with self._lock:
            self._region_counter += 1
            region_id = f"r{self._region_counter}"
            self._regions[region_id] = record
            while len(self._regions) > MAX_CACHED_REGIONS:
                self._regions.popitem(last=False)
            return region_id

    def _region(self, region_id: Any, page_uid: str) -> _RegionRecord:
        with self._lock:
            record = self._regions.get(str(region_id))
        if record is None or record.page_uid != page_uid:
            raise AiTakeoffRequestError(
                ERROR_NOT_FOUND, "Unknown region_id for this page"
            )
        return record

    def _vector_item(self, snapshot: PageSnapshot, region, k: float) -> dict:
        polygon = tuple(value * k for point in region.outer for value in point)
        holes = tuple(
            tuple(value * k for point in hole for value in point)
            for hole in region.holes
        )
        gaps = tuple(gap.length * k for gap in region.gaps)
        record = _RegionRecord(snapshot.uid, polygon, holes, gaps, bool(region.gaps), k)
        return {
            "id": self._store_region(record),
            "method": "vector",
            "polygon_ost": list(polygon),
            "holes_ost": [list(hole) for hole in holes],
            "area_sf": round(region.area * k * k / 144.0, 4),
            "leak_risk": bool(region.gaps),
            "gaps": [
                {
                    "p1_pts": list(gap.p1),
                    "p2_pts": list(gap.p2),
                    "length_in": gap.length * k,
                }
                for gap in region.gaps
            ],
        }

    def _raster_item(self, snapshot: PageSnapshot, raster, k: float) -> dict:
        polygon = tuple(value * k for point in raster.ring for value in point)
        record = _RegionRecord(snapshot.uid, polygon, (), (), bool(raster.leak), k)
        return {
            "id": self._store_region(record),
            "method": "raster",
            "polygon_ost": list(polygon),
            "holes_ost": [],
            "area_sf": round(abs(polygon_area(polygon)) / 144.0, 4),
            "leak_risk": bool(raster.leak),
            "gaps": [],
        }
