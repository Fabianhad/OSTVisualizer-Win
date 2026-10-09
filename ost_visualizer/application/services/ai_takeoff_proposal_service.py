import math
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple
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
    SUBJECT_OTHER,
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
from ...domain.services.ai_linework import (
    KIND_DASHED,
    KIND_SYMBOL,
    KIND_THIN,
    SYMBOL_MAX_PTS,
    SegmentGrid,
    classify_linework,
    point_segment_distance,
    suggested_min_width,
    symbol_groups,
    uncovered_runs,
)
from ...domain.services.ai_polygon_simplify import SimplifiedSlab, simplify_slab
from ...domain.services.ai_sheet_text import parse_dimension_in
from ...domain.services.ai_planar_regions import (
    PlanarRegion,
    PlanarRegionReport,
    RegionGap,
    RegionTooComplex,
    find_planar_regions_report,
    point_in_ring,
    ring_area,
)
from ..dtos.ai_takeoff_dtos import (
    COORDINATE_SPACE_KEY,
    ERROR_INVALID_ARGUMENT,
    ERROR_NOT_FOUND,
    MAX_REGIONS_PER_PAGE,
    STATUS_EMPTY,
    STATUS_OK,
    STATUS_TRUNCATED,
    AiTakeoffRequestError,
    PageSnapshot,
    ResultMeta,
    UntrustedText,
    decode_cursor,
    encode_cursor,
    find_regions_coordinate_space,
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
MAX_REGIONS_RETURNED = MAX_REGIONS_PER_PAGE
MAX_CACHED_REGIONS = 200
MAX_SUPPRESSED_BOXES = 20
OPENING_TOLERANCE_MIN_PTS = 1.0
OPENING_TOLERANCE_PX = 3.0
OPENING_SNAP_TOLERANCES = 3.0
OPENING_AREA_MATCH = 0.25
OPENING_LINE_ANGLE_DEG = 15.0
DIMENSION_REACH_MIN_PTS = 36.0
DIMENSION_REACH_SHARE = 0.25
DIMENSION_AGREE_PCT = 2.0
MIN_WIDTH_NONE = "none"
MIN_WIDTH_GIVEN = "given"
MIN_WIDTH_SUGGESTED = "suggested"
_COLOR_PATTERN = re.compile(r"#[0-9a-fA-F]{6}")
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
    px_per_pt: float = 0.0


@dataclass(frozen=True)
class _DimensionCheck:
    text: str
    real_in: float
    error_pct: float
    agrees: bool

    def to_dict(self) -> dict:
        return {
            "text": UntrustedText.of(self.text).to_dict(),
            "real_in": self.real_in,
            "error_pct": round(self.error_pct, 4),
            "agrees": self.agrees,
        }


@dataclass(frozen=True)
class _GapRecord:
    length_in: float
    p1_pts: Optional[Tuple[float, float]]
    p2_pts: Optional[Tuple[float, float]]


@dataclass(frozen=True)
class _RegionRecord:
    page_uid: str
    polygon_ost: Tuple[float, ...]
    holes_ost: Tuple[Tuple[float, ...], ...]
    gaps: Tuple[_GapRecord, ...]
    escaped: bool
    ost_per_page_point: float


@dataclass(frozen=True)
class _RegionFilters:
    max_gap_in: float
    min_width: Optional[float]
    exclude_dashed: bool
    exclude_thin_curves: bool
    colors: Optional[Tuple[str, ...]]
    min_area_sf: float
    symbol_max_pts: float
    min_width_source: str = MIN_WIDTH_NONE

    def to_dict(self) -> dict:
        return {
            "max_gap_in": self.max_gap_in,
            "min_width": self.min_width,
            "exclude_dashed": self.exclude_dashed,
            "exclude_thin_curves": self.exclude_thin_curves,
            "colors": None if self.colors is None else list(self.colors),
            "min_area_sf": self.min_area_sf,
            "symbol_max_pts": self.symbol_max_pts,
            "min_width_source": self.min_width_source,
        }


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
        return self.plan_scale(
            page_uid,
            p1_pts,
            p2_pts,
            real_in=real_in,
            preset=preset,
            reason=reason,
            sheet_ref=sheet_ref,
        )()

    def plan_scale(
        self,
        page_uid: Any,
        p1_pts: Any,
        p2_pts: Any,
        real_in: Any = None,
        preset: Any = None,
        reason: Any = None,
        sheet_ref: Any = None,
    ) -> Callable[[], dict]:
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
        stated_reason = _text(reason, "reason")
        stated_sheet_ref = _text(sheet_ref, "sheet_ref")
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
            summary=f"Page scale {sf1:g} : {sf2:g}",
        )

        def finish() -> dict:
            check = self._dimension_check(snapshot, first, second, chosen)
            text = stated_reason or "Scale proposed by the AI from a measured distance."
            if check is not None and not check.agrees:
                text = (
                    f"{text} A dimension near the measured points reads "
                    f"{check.real_in:g} in, but this scale gives "
                    f"{chosen * distance:.4g} in ({check.error_pct:.1f}% off)."
                )
            assumption = ChangesetAssumption(
                uid="a1",
                subject=SUBJECT_SCALE,
                target_key=snapshot.uid,
                value=f"{sf1:g}:{sf2:g}",
                reason=text,
                sheet_ref=stated_sheet_ref,
                impact=IMPACT_HIGH,
            )
            data = self.describe(
                self._add(replace(changeset, assumptions=(assumption,)))
            )
            data["scale"]["dimension_check"] = (
                None if check is None else check.to_dict()
            )
            return ok_result(data)

        return finish

    def _dimension_check(
        self,
        snapshot: PageSnapshot,
        first: Tuple[float, float],
        second: Tuple[float, float],
        chosen: float,
    ) -> Optional["_DimensionCheck"]:
        status, lines = self._read_service.page_text_lines(snapshot)
        if status != STATUS_OK:
            return None
        distance = math.dist(first, second)
        reach = max(DIMENSION_REACH_MIN_PTS, DIMENSION_REACH_SHARE * distance)
        best = None
        for line in lines:
            real = parse_dimension_in(line.text)
            if real is None:
                continue
            away = point_segment_distance(
                (line.left + line.right) / 2.0,
                (line.top + line.bottom) / 2.0,
                first[0],
                first[1],
                second[0],
                second[1],
            )
            if away <= reach and (best is None or away < best[0]):
                best = (away, line.text, real)
        if best is None:
            return None
        implied = best[2] / distance
        error_pct = abs(chosen - implied) / implied * 100.0
        return _DimensionCheck(
            best[1], best[2], error_pct, error_pct <= DIMENSION_AGREE_PCT
        )

    def find_regions(
        self,
        snapshot: PageSnapshot,
        bbox_pts: Any,
        gap_close_in: Any = None,
        seed_pts: Any = None,
        max_gap_in: Any = None,
        min_width: Any = None,
        exclude_dashed: Any = None,
        colors: Any = None,
        min_area_sf: Any = None,
        symbol_max_pts: Any = None,
        cursor: Any = None,
        limit: Any = None,
        exclude_thin_curves: Any = None,
    ) -> dict:
        k = snapshot.ost_per_page_point
        if k is None or k <= 0.0:
            raise AiTakeoffRequestError(ERROR_SCALE_UNSET, "Set the page scale first")
        left, top, right, bottom = _numbers(bbox_pts, "bbox_pts", 4)
        if right <= left or bottom <= top:
            raise AiTakeoffRequestError(
                ERROR_INVALID_ARGUMENT, "bbox_pts must be [left, top, right, bottom]"
            )
        box = (left, top, right, bottom)
        filters = _region_filters(
            gap_close_in,
            max_gap_in,
            min_width,
            exclude_dashed,
            exclude_thin_curves,
            colors,
            min_area_sf,
            symbol_max_pts,
        )
        seed = None if seed_pts is None else _numbers(seed_pts, "seed_pts", 2)
        offset, size = _region_page(cursor, limit)
        (
            status,
            linework,
            extraction_truncated,
            extraction_scope,
        ) = self._read_service.page_linework_scoped(snapshot, box)
        if status != STATUS_OK:
            return ok_result(
                {
                    "page_uid": snapshot.uid,
                    "regions": [],
                    COORDINATE_SPACE_KEY: find_regions_coordinate_space(),
                },
                status,
            )
        lines = [line for _segment_id, line in linework]
        if filters.min_width is None:
            suggested = suggested_min_width(lines)
            if suggested is not None:
                filters = replace(
                    filters, min_width=suggested, min_width_source=MIN_WIDTH_SUGGESTED
                )
        segments, excluded, symbol_boxes = _filter_linework(lines, box, filters)
        next_cursor = None
        if seed is not None:
            item, report = self._seed_item(snapshot, segments, box, seed, filters)
            items = [] if item is None else [item]
            total = len(items)
            meta = ResultMeta(limit=1, returned_count=total, total_count=total)
            result_status = STATUS_OK if items else STATUS_EMPTY
        else:
            report = _planar(segments, filters.max_gap_in / k, filters.symbol_max_pts)
            min_area_pts = filters.min_area_sf * 144.0 / (k * k)
            regions = [
                region for region in report.regions if region.area >= min_area_pts
            ]
            page = regions[offset : offset + size]
            items = [self._vector_item(snapshot, region, k) for region in page]
            total = len(regions)
            end = offset + len(page)
            next_cursor = encode_cursor(end) if end < total else None
            meta = ResultMeta(
                limit=size,
                returned_count=len(items),
                total_count=total,
                next_cursor=next_cursor,
            )
            if next_cursor is not None:
                result_status = STATUS_TRUNCATED
            else:
                result_status = STATUS_OK if items else STATUS_EMPTY
        suppressed = list(symbol_boxes) + list(report.suppressed)
        return ok_result(
            {
                "page_uid": snapshot.uid,
                "regions": items,
                "truncated": next_cursor is not None,
                "total_count": total,
                "filters": filters.to_dict(),
                "segment_count": len(segments),
                "excluded": excluded,
                "suppressed_symbol_count": len(suppressed),
                "suppressed_symbols_pts": [
                    list(bounds) for bounds in suppressed[:MAX_SUPPRESSED_BOXES]
                ],
                "extraction_truncated": extraction_truncated,
                "extraction_scope": extraction_scope,
                COORDINATE_SPACE_KEY: find_regions_coordinate_space(),
            },
            result_status,
            meta,
        )

    def _seed_item(
        self,
        snapshot: PageSnapshot,
        segments: List[Tuple[float, float, float, float]],
        box: Tuple[float, float, float, float],
        seed: Tuple[float, ...],
        filters: _RegionFilters,
    ) -> Tuple[Optional[dict], PlanarRegionReport]:
        k = snapshot.ost_per_page_point
        symbol_max = filters.symbol_max_pts
        plain = _planar(segments, 0.0, symbol_max)
        best = _smallest_containing(plain.regions, seed)
        if best is not None:
            return self._vector_item(snapshot, best, k), plain
        gap_pts = filters.max_gap_in / k
        pen = max(gap_pts, 1.0)
        raster = self._raster_fill(segments, box, seed, pen)
        closures = (
            [] if raster is None else _sealed_openings(raster, segments, pen, seed)
        )
        if closures:
            closed = _planar(segments, 0.0, symbol_max, closures)
            best = _smallest_containing(closed.regions, seed)
            raster_area = abs(ring_area(raster.ring))
            if (
                best is not None
                and abs(abs(ring_area(best.outer)) - raster_area)
                <= OPENING_AREA_MATCH * raster_area
            ):
                return self._vector_item(snapshot, best, k), closed
        if gap_pts > 0.0:
            bridged = _planar(segments, gap_pts, symbol_max)
            best = _smallest_containing(bridged.regions, seed)
            if best is not None:
                return self._vector_item(snapshot, best, k), bridged
        if raster is None:
            return None, plain
        gaps = tuple(
            RegionGap((x1, y1), (x2, y2), math.dist((x1, y1), (x2, y2)))
            for x1, y1, x2, y2 in closures
        )
        sealed_in = filters.max_gap_in if not gaps and pen > 1.0 else None
        return self._raster_item(snapshot, raster, k, gaps, sealed_in), plain

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
        return self.plan_element(
            kind,
            page_uid,
            polygon_ost=polygon_ost,
            region_id=region_id,
            holes_ost=holes_ost,
            thickness_in=thickness_in,
            top_elev_in=top_elev_in,
            level_id=level_id,
            name=name,
            summary=summary,
            condition_uid=condition_uid,
        )()

    def plan_element(
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
    ) -> Callable[[], dict]:
        if kind not in ELEMENT_KINDS:
            raise AiTakeoffRequestError(ERROR_INVALID_ARGUMENT, "kind must be slab")
        snapshot = self._read_service.page_snapshot(page_uid)
        if snapshot.ost_per_page_point is None:
            raise AiTakeoffRequestError(ERROR_SCALE_UNSET, "Set the page scale first")
        if (polygon_ost is None) == (region_id is None):
            raise AiTakeoffRequestError(
                ERROR_INVALID_ARGUMENT, "Give exactly one of polygon_ost or region_id"
            )
        gaps: Tuple[_GapRecord, ...] = ()
        record: Optional[_RegionRecord] = None
        polygon: Tuple[float, ...] = ()
        holes: Tuple[Tuple[float, ...], ...] = ()
        if region_id is not None:
            record = self._region(region_id, snapshot.uid)
            if not math.isclose(
                record.ost_per_page_point, snapshot.ost_per_page_point, rel_tol=1e-9
            ):
                raise AiTakeoffRequestError(
                    ERROR_NOT_FOUND,
                    "That region was found at a different page scale; call find_regions again",
                )
            if record.escaped:
                raise AiTakeoffRequestError(
                    ERROR_INVALID_GEOMETRY, "That region leaks outside its outline"
                )
            gaps = record.gaps
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
        stated_summary = _text(summary, "summary")
        database_id = self._open_database_id()
        bid_uid = self._open_bid_uid()

        def finish() -> dict:
            slab = None
            outline, inner = polygon, holes
            if record is not None:
                slab = simplify_slab(record.polygon_ost, record.holes_ost)
                outline, inner = slab.outline, slab.holes
            return self._element_result(
                snapshot.uid,
                base,
                thickness,
                top,
                existing,
                condition_key,
                conditions,
                gaps,
                slab,
                outline,
                inner,
                stated_summary,
                database_id,
                bid_uid,
            )

        return finish

    def _element_result(
        self,
        page_uid: str,
        base: str,
        thickness: Optional[float],
        top: Optional[float],
        existing: str,
        condition_key: str,
        conditions: tuple,
        gaps: Tuple[_GapRecord, ...],
        slab: Optional[SimplifiedSlab],
        polygon: Tuple[float, ...],
        holes: Tuple[Tuple[float, ...], ...],
        summary: str,
        database_id: str,
        bid_uid: str,
    ) -> dict:
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
        for gap in gaps:
            assumptions.append(
                self._assumption(
                    len(assumptions),
                    SUBJECT_CLOSING_SEGMENT,
                    *_gap_assumption_text(gap),
                    gap.length_in,
                )
            )
        if slab is not None and slab.holes_dropped:
            assumptions.append(
                self._assumption(
                    len(assumptions),
                    SUBJECT_OTHER,
                    f"{slab.holes_dropped} hole(s) left out",
                    f"{slab.holes_dropped} traced hole(s) crossed the slab outline "
                    "and were left out; check the outline.",
                )
            )
        changeset = AiChangeset(
            uid="",
            database_id=database_id,
            bid_uid=bid_uid,
            bid_key="",
            kind=KIND_ELEMENTS,
            created_at=0.0,
            conditions=conditions,
            takeoffs=(ProposedTakeoff("t1", page_uid, condition_key, polygon, holes),),
            assumptions=tuple(assumptions),
            summary=summary or f"{base} on page {page_uid}",
        )
        result = ok_result(self.describe(self._add(changeset)))
        if slab is not None:
            result["data"]["geometry"] = {
                "outline_vertices": list(slab.outline_vertices),
                "hole_vertices": list(slab.hole_vertices),
                "holes_dropped": slab.holes_dropped,
                "area_change_pct": round(slab.area_change_pct, 4),
            }
        return result

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
        record = _RegionRecord(
            snapshot.uid, polygon, holes, _gap_records(region.gaps, k), False, k
        )
        return {
            "id": self._store_region(record),
            "method": "vector",
            "polygon_ost": list(polygon),
            "holes_ost": [list(hole) for hole in holes],
            "area_sf": round(region.area * k * k / 144.0, 4),
            "leak_risk": bool(region.gaps),
            "gaps": _gap_items(region.gaps, k),
        }

    def _raster_item(
        self,
        snapshot: PageSnapshot,
        raster,
        k: float,
        gaps: Tuple[RegionGap, ...] = (),
        sealed_in: Optional[float] = None,
    ) -> dict:
        polygon = tuple(value * k for point in raster.ring for value in point)
        records = _gap_records(gaps, k)
        if sealed_in is not None:
            records += (_GapRecord(sealed_in, None, None),)
        record = _RegionRecord(snapshot.uid, polygon, (), records, bool(raster.leak), k)
        return {
            "id": self._store_region(record),
            "method": "raster",
            "polygon_ost": list(polygon),
            "holes_ost": [],
            "area_sf": round(abs(polygon_area(polygon)) / 144.0, 4),
            "leak_risk": bool(raster.leak) or bool(records),
            "gaps": _gap_items(gaps, k),
            "unlocated_gaps_up_to_in": sealed_in,
        }


def _gap_assumption_text(gap: _GapRecord) -> Tuple[str, str]:
    if gap.p1_pts is None or gap.p2_pts is None:
        return (
            f"up to {gap.length_in:.2f} in",
            "The fill may have closed openings up to "
            f"{gap.length_in:.2f} in that could not be located; check the outline.",
        )
    return (
        f"{gap.length_in:.2f} in",
        f"The outline was closed across a {gap.length_in:.2f} in gap in the drawing "
        f"from ({gap.p1_pts[0]:.1f}, {gap.p1_pts[1]:.1f}) to "
        f"({gap.p2_pts[0]:.1f}, {gap.p2_pts[1]:.1f}) page points.",
    )


def _planar(
    segments, gap_pts: float, symbol_max: float, closures=()
) -> PlanarRegionReport:
    try:
        return find_planar_regions_report(
            segments,
            SNAP_TOLERANCE_PTS,
            gap_pts,
            symbol_max=symbol_max,
            closures=closures,
        )
    except RegionTooComplex as exc:
        raise AiTakeoffRequestError(ERROR_INVALID_ARGUMENT, str(exc)) from exc


def _gap_records(gaps: Sequence[RegionGap], k: float) -> Tuple[_GapRecord, ...]:
    return tuple(_GapRecord(gap.length * k, gap.p1, gap.p2) for gap in gaps)


def _gap_items(gaps: Sequence[RegionGap], k: float) -> list:
    return [
        {"p1_pts": list(gap.p1), "p2_pts": list(gap.p2), "length_in": gap.length * k}
        for gap in gaps
    ]


def _smallest_containing(
    regions: Sequence[PlanarRegion], seed: Tuple[float, ...]
) -> Optional[PlanarRegion]:
    containing = [region for region in regions if point_in_ring(seed, region.outer)]
    if not containing:
        return None
    return min(containing, key=lambda region: abs(ring_area(region.outer)))


def _optional_number(
    value: Any, label: str, default: Optional[float]
) -> Optional[float]:
    if value is None:
        return default
    number = _number(value, label)
    if number < 0.0:
        raise AiTakeoffRequestError(
            ERROR_INVALID_ARGUMENT, f"{label} must be 0 or more"
        )
    return number


def _flag(value: Any, label: str) -> bool:
    if value is None:
        return True
    if not isinstance(value, bool):
        raise AiTakeoffRequestError(
            ERROR_INVALID_ARGUMENT, f"{label} must be true or false"
        )
    return value


def _region_filters(
    gap_close_in: Any,
    max_gap_in: Any,
    min_width: Any,
    exclude_dashed: Any,
    exclude_thin_curves: Any,
    colors: Any,
    min_area_sf: Any,
    symbol_max_pts: Any,
) -> _RegionFilters:
    old_gap = _optional_number(gap_close_in, "gap_close_in", None)
    new_gap = _optional_number(max_gap_in, "max_gap_in", None)
    if old_gap is not None and new_gap is not None and old_gap != new_gap:
        raise AiTakeoffRequestError(
            ERROR_INVALID_ARGUMENT, "Give max_gap_in or gap_close_in, not two values"
        )
    gap = new_gap if new_gap is not None else (old_gap or 0.0)
    if gap > MAX_GAP_CLOSE_IN:
        raise AiTakeoffRequestError(
            ERROR_INVALID_ARGUMENT,
            f"max_gap_in must be between 0 and {MAX_GAP_CLOSE_IN:g}",
        )
    return _RegionFilters(
        max_gap_in=gap,
        min_width=_optional_number(min_width, "min_width", None),
        min_width_source=MIN_WIDTH_NONE if min_width is None else MIN_WIDTH_GIVEN,
        exclude_dashed=_flag(exclude_dashed, "exclude_dashed"),
        exclude_thin_curves=_flag(exclude_thin_curves, "exclude_thin_curves"),
        colors=_colors(colors),
        min_area_sf=_optional_number(min_area_sf, "min_area_sf", 0.0),
        symbol_max_pts=_optional_number(
            symbol_max_pts, "symbol_max_pts", SYMBOL_MAX_PTS
        ),
    )


def _colors(colors: Any) -> Optional[Tuple[str, ...]]:
    if colors is None:
        return None
    if not isinstance(colors, list) or not all(
        isinstance(color, str) and _COLOR_PATTERN.fullmatch(color) for color in colors
    ):
        raise AiTakeoffRequestError(
            ERROR_INVALID_ARGUMENT, "colors must be a list of #rrggbb values"
        )
    return tuple(color.lower() for color in colors)


def _region_page(cursor: Any, limit: Any) -> Tuple[int, int]:
    if cursor is not None and not isinstance(cursor, str):
        raise AiTakeoffRequestError(ERROR_INVALID_ARGUMENT, "cursor must be text")
    try:
        offset = decode_cursor(cursor)
    except ValueError as exc:
        raise AiTakeoffRequestError(ERROR_INVALID_ARGUMENT, str(exc)) from exc
    if limit is None:
        return offset, MAX_REGIONS_RETURNED
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_REGIONS_RETURNED
    ):
        raise AiTakeoffRequestError(
            ERROR_INVALID_ARGUMENT,
            f"limit must be a whole number from 1 to {MAX_REGIONS_RETURNED}",
        )
    return offset, limit


def _filter_linework(lines, box, filters: _RegionFilters):
    left, top, right, bottom = box
    kinds = classify_linework(lines, filters.symbol_max_pts)
    symbols = symbol_groups(lines, filters.symbol_max_pts)
    excluded = {"dashed": 0, "thin_curve": 0, "thin": 0, "color": 0, "symbol": 0}
    symbol_boxes: Dict[str, Tuple[float, float, float, float]] = {}
    kept = []
    for line, kind in zip(lines, kinds):
        if (
            max(line.x1, line.x2) < left
            or min(line.x1, line.x2) > right
            or max(line.y1, line.y2) < top
            or min(line.y1, line.y2) > bottom
        ):
            continue
        if kind == KIND_SYMBOL:
            excluded["symbol"] += 1
            symbol_boxes[line.group] = symbols[line.group]
        elif filters.exclude_dashed and kind == KIND_DASHED:
            excluded["dashed"] += 1
        elif filters.exclude_thin_curves and line.curve and kind == KIND_THIN:
            excluded["thin_curve"] += 1
        elif (
            filters.min_width is not None
            and line.stroked
            and (line.width or 0.0) < filters.min_width
            and not (
                filters.min_width_source == MIN_WIDTH_SUGGESTED and kind == KIND_DASHED
            )
        ):
            excluded["thin"] += 1
        elif filters.colors is not None and line.color not in filters.colors:
            excluded["color"] += 1
        else:
            kept.append(line.points)
    return kept, excluded, [symbol_boxes[group] for group in sorted(symbol_boxes)]


def _sealed_openings(
    raster, segments, pen: float, seed: Tuple[float, ...]
) -> List[Tuple[float, float, float, float]]:
    if raster.px_per_pt > 0.0:
        tolerance = max(
            OPENING_TOLERANCE_MIN_PTS, OPENING_TOLERANCE_PX / raster.px_per_pt
        )
    else:
        tolerance = OPENING_TOLERANCE_MIN_PTS
    grid = SegmentGrid(segments)
    closures = []
    near = OPENING_SNAP_TOLERANCES * tolerance
    for start, end, chord in uncovered_runs(
        raster.ring, grid, tolerance, pen + 2.0 * tolerance
    ):
        reach = max(near, min(pen, chord) / 2.0)
        first = _snap_to_linework(start, grid, reach, seed)
        second = _snap_to_linework(end, grid, reach, seed)
        if (
            first is not None
            and second is not None
            and first != second
            and _continues_a_line(first, second, grid)
            and _continues_a_line(second, first, grid)
        ):
            closures.append((first[0], first[1], second[0], second[1]))
    return closures


def _continues_a_line(point, other, grid: SegmentGrid) -> bool:
    x, y = point
    dx, dy = other[0] - x, other[1] - y
    length = math.hypot(dx, dy)
    limit = math.sin(math.radians(OPENING_LINE_ANGLE_DEG))
    reach = SNAP_TOLERANCE_PTS
    for index in grid.query(x - reach, y - reach, x + reach, y + reach):
        x1, y1, x2, y2 = grid.segment(index)
        if point_segment_distance(x, y, x1, y1, x2, y2) > reach:
            continue
        sx, sy = x2 - x1, y2 - y1
        size = math.hypot(sx, sy) * length
        if size > 0.0 and abs(sx * dy - sy * dx) <= limit * size:
            return True
    return False


def _snap_to_linework(point, grid: SegmentGrid, reach: float, seed):
    x, y = point
    nearby = grid.query(x - reach, y - reach, x + reach, y + reach)
    best = None
    best_key = None
    for index in nearby:
        x1, y1, x2, y2 = grid.segment(index)
        for end in ((x1, y1), (x2, y2)):
            distance = math.dist(point, end)
            if distance > reach:
                continue
            key = (math.dist(seed, end), distance)
            if best_key is None or key < best_key:
                best, best_key = end, key
    return best
