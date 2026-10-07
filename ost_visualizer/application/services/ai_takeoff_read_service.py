import math
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional
from ...domain.entities.ai_takeoff import ASSUMPTION_STATUSES, FINGERPRINT_OK
from ...domain.entities.condition import Condition
from ...domain.entities.database_descriptor import DatabaseDescriptor
from ...domain.entities.file_extensions import is_pdf_suffix
from ...domain.services.condition_quantity_service import compute_page_quantities
from ...domain.services.uom_service import get_uom_label
from ..dtos.ai_takeoff_dtos import (
    ERROR_BID_NOT_OPEN,
    ERROR_INVALID_ARGUMENT,
    ERROR_NOT_FOUND,
    OVERLAY_NOT_SUPPORTED_UNTIL_M1B,
    RENDER_DEFAULT_DPI,
    RENDER_MAX_DPI,
    RENDER_MAX_LONG_SIDE_PX,
    STATUS_EMPTY,
    STATUS_NOT_PDF,
    STATUS_OK,
    STATUS_TRUNCATED,
    AiTakeoffRequestError,
    CropPlan,
    PageSnapshot,
    ResultMeta,
    UntrustedText,
    clamp_limit,
    decode_cursor,
    encode_cursor,
    ok_result,
)
from ..interfaces.i_ai_takeoff_sidecar_repository import IAiTakeoffSidecarRepository
from ..interfaces.i_pdf_metadata_provider import IPdfMetadataProvider
from .ai_takeoff_sidecar_service import load_sidecar_context

QUANTITY_DECIMALS = 4
POINTS_PER_INCH = 72.0
_CONDITION_TYPE_NAMES = {
    Condition.TYPE_LINEAR: "linear",
    Condition.TYPE_AREA: "area",
    Condition.TYPE_COUNT: "count",
    Condition.TYPE_ATTACHMENT: "attachment",
}
_GROUPINGS = ("condition", "page")


@dataclass(frozen=True)
class _OpenBid:
    bid_ref: Any
    bid: Any
    pages: list


class AiTakeoffReadService:
    def __init__(
        self,
        project_data,
        pdf_source: IPdfMetadataProvider,
        sidecar_repository: IAiTakeoffSidecarRepository,
        descriptor_resolver: Callable[[str], Optional[DatabaseDescriptor]],
    ):
        self._project_data = project_data
        self._pdf_source = pdf_source
        self._sidecar_repository = sidecar_repository
        self._descriptor_resolver = descriptor_resolver

    def list_sheets(
        self,
        bid_uid: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: Any = None,
    ) -> dict:
        open_bid = self._open_bid(bid_uid)
        sheets = [self._sheet(page) for page in open_bid.pages]
        page, meta = _paginate(sheets, cursor, limit)
        return ok_result(
            {
                "bid_uid": open_bid.bid.uid,
                "bid_name": UntrustedText.of(open_bid.bid.name).to_dict(),
                "sheets": page,
            },
            _page_status(page, meta),
            meta,
        )

    def get_quantities(
        self, bid_uid: Optional[str] = None, group_by: str = "condition"
    ) -> dict:
        if group_by not in _GROUPINGS:
            raise AiTakeoffRequestError(
                ERROR_INVALID_ARGUMENT, "group_by must be condition or page"
            )
        open_bid = self._open_bid(bid_uid)
        conditions = self._project_data.get_bid_conditions()
        if group_by == "condition":
            rows = self._quantity_rows(
                conditions, self._project_data.get_all_takeoffs()
            )
        else:
            rows = []
            for page in open_bid.pages:
                for row in self._quantity_rows(
                    conditions, self._project_data.get_page_takeoffs(page.uid)
                ):
                    rows.append({"page_uid": page.uid, **row})
        return ok_result(
            {"group_by": group_by, "rows": rows, "assumption_ids": []},
            STATUS_OK if rows else STATUS_EMPTY,
        )

    def list_levels(self, bid_uid: Optional[str] = None) -> dict:
        status, sidecar = self._sidecar(self._open_bid(bid_uid))
        levels = []
        if sidecar is not None:
            registered = {}
            for registration in sidecar.registrations:
                registered.setdefault(registration.level_uid, []).append(
                    registration.page_uid
                )
            levels = [
                {
                    "uid": level.uid,
                    "name": UntrustedText.of(level.name).to_dict(),
                    "top_elev_in": level.top_elev_in,
                    "sheet_page_uids": registered.get(level.uid, []),
                }
                for level in sidecar.levels
            ]
        return ok_result(
            {"sidecar_status": status, "levels": levels},
            STATUS_OK if levels else STATUS_EMPTY,
        )

    def list_assumptions(
        self, bid_uid: Optional[str] = None, status: Optional[str] = None
    ) -> dict:
        if status is not None and status not in ASSUMPTION_STATUSES:
            raise AiTakeoffRequestError(
                ERROR_INVALID_ARGUMENT, "status must be open, accepted or overridden"
            )
        sidecar_status, sidecar = self._sidecar(self._open_bid(bid_uid))
        assumptions = []
        if sidecar is not None:
            assumptions = [
                {
                    "uid": item.uid,
                    "value": UntrustedText.of(item.value).to_dict(),
                    "reason": UntrustedText.of(item.reason).to_dict(),
                    "sheet_ref": UntrustedText.of(item.sheet_ref).to_dict(),
                    "impact": item.impact,
                    "status": item.status,
                }
                for item in sidecar.assumptions
                if status is None or item.status == status
            ]
        return ok_result(
            {"sidecar_status": sidecar_status, "assumptions": assumptions},
            STATUS_OK if assumptions else STATUS_EMPTY,
        )

    def page_snapshot(self, page_uid: Any) -> PageSnapshot:
        self._open_bid(None)
        if not isinstance(page_uid, str) or not page_uid:
            raise AiTakeoffRequestError(ERROR_INVALID_ARGUMENT, "page_uid is required")
        page = self._project_data.get_page(page_uid)
        if page is None:
            raise AiTakeoffRequestError(ERROR_NOT_FOUND, "Unknown page_uid")
        return PageSnapshot(
            uid=page.uid,
            image_path=page.image_path or "",
            page_index=int(page.page_index or 0),
            width_pts=float(page.width_pts or 0.0),
            height_pts=float(page.height_pts or 0.0),
            ost_per_page_point=_ost_per_page_point(page),
            is_pdf=bool(page.image_path) and is_pdf_suffix(page.image_path),
        )

    def list_text(
        self,
        snapshot: PageSnapshot,
        bbox_pts: Any = None,
        query: Any = None,
        cursor: Optional[str] = None,
        limit: Any = None,
    ) -> dict:
        box = _optional_box(bbox_pts)
        if query is not None and not isinstance(query, str):
            raise AiTakeoffRequestError(ERROR_INVALID_ARGUMENT, "query must be text")
        needle = (query or "").strip().casefold()
        frame = self._raw_frame(snapshot)
        if isinstance(frame, str):
            return ok_result({"page_uid": snapshot.uid, "runs": []}, frame)
        runs = []
        for run in self._pdf_source.get_text_runs(
            snapshot.image_path, snapshot.page_index
        ):
            if needle and needle not in str(run.text).casefold():
                continue
            corners = (
                _raw_to_page(run.left, run.top, frame),
                _raw_to_page(run.right, run.bottom, frame),
            )
            bbox = _bounds(corners)
            if box is not None and not _intersects(bbox, box):
                continue
            runs.append(
                {
                    "text": UntrustedText.of(run.text).to_dict(),
                    "bbox_pts": bbox,
                    "bbox_ost": _scale_values(bbox, snapshot.ost_per_page_point),
                }
            )
        page, meta = _paginate(runs, cursor, limit)
        return ok_result(
            {"page_uid": snapshot.uid, "runs": page}, _page_status(page, meta), meta
        )

    def list_segments(
        self,
        snapshot: PageSnapshot,
        bbox_pts: Any = None,
        cursor: Optional[str] = None,
        limit: Any = None,
    ) -> dict:
        box = _optional_box(bbox_pts)
        frame = self._raw_frame(snapshot)
        if isinstance(frame, str):
            return ok_result({"page_uid": snapshot.uid, "segments": []}, frame)
        segments = []
        raw_segments = self._pdf_source.get_vector_segments(
            snapshot.image_path, snapshot.page_index
        )
        for index, segment in enumerate(raw_segments):
            p1 = _raw_to_page(segment.x1, segment.y1, frame)
            p2 = _raw_to_page(segment.x2, segment.y2, frame)
            if box is not None and not _intersects(_bounds((p1, p2)), box):
                continue
            segments.append(
                {
                    "id": f"s{index}",
                    "p1_pts": list(p1),
                    "p2_pts": list(p2),
                    "p1_ost": _scale_values(list(p1), snapshot.ost_per_page_point),
                    "p2_ost": _scale_values(list(p2), snapshot.ost_per_page_point),
                    "length_pts": math.hypot(p2[0] - p1[0], p2[1] - p1[1]),
                }
            )
        page, meta = _paginate(segments, cursor, limit)
        return ok_result(
            {"page_uid": snapshot.uid, "segments": page}, _page_status(page, meta), meta
        )

    def open_bid_ref(self):
        return self._open_bid(None).bid_ref

    def page_entity(self, page_uid: Any):
        self._open_bid(None)
        page = (
            self._project_data.get_page(page_uid) if isinstance(page_uid, str) else None
        )
        if page is None:
            raise AiTakeoffRequestError(ERROR_NOT_FOUND, "Unknown page_uid")
        return page

    def page_segments_pts(self, snapshot: PageSnapshot, box: Optional[tuple]) -> tuple:
        frame = self._raw_frame(snapshot)
        if isinstance(frame, str):
            return frame, []
        segments = []
        for segment in self._pdf_source.get_vector_segments(
            snapshot.image_path, snapshot.page_index
        ):
            p1 = _raw_to_page(segment.x1, segment.y1, frame)
            p2 = _raw_to_page(segment.x2, segment.y2, frame)
            if box is not None and not _intersects(_bounds((p1, p2)), box):
                continue
            segments.append((p1[0], p1[1], p2[0], p2[1]))
        return STATUS_OK, segments

    def plan_crop(
        self, snapshot: PageSnapshot, crop_pts: Any = None, dpi: Any = None
    ) -> CropPlan:
        if snapshot.width_pts <= 0.0 or snapshot.height_pts <= 0.0:
            raise AiTakeoffRequestError(ERROR_INVALID_ARGUMENT, "Page has no size")
        resolution = _dpi(dpi)
        if crop_pts is None:
            x, y, width, height = 0.0, 0.0, snapshot.width_pts, snapshot.height_pts
        else:
            x, y, width, height = _numbers(crop_pts, "crop_pts")
            if width <= 0.0 or height <= 0.0:
                raise AiTakeoffRequestError(
                    ERROR_INVALID_ARGUMENT, "crop_pts width and height must be positive"
                )
        left = max(0.0, x)
        top = max(0.0, y)
        right = min(snapshot.width_pts, x + width)
        bottom = min(snapshot.height_pts, y + height)
        if right <= left or bottom <= top:
            raise AiTakeoffRequestError(
                ERROR_INVALID_ARGUMENT, "crop_pts does not overlap the page"
            )
        frame_w = right - left
        frame_h = bottom - top
        scale = min(
            resolution / POINTS_PER_INCH,
            RENDER_MAX_LONG_SIDE_PX / max(frame_w, frame_h),
        )
        k = snapshot.ost_per_page_point
        return CropPlan(
            page_uid=snapshot.uid,
            file_path=snapshot.image_path,
            page_index=snapshot.page_index,
            frame_pts=(left, top, frame_w, frame_h),
            scale=scale,
            width_px=max(1, min(RENDER_MAX_LONG_SIDE_PX, round(frame_w * scale))),
            height_px=max(1, min(RENDER_MAX_LONG_SIDE_PX, round(frame_h * scale))),
            px_to_page_pts=(1.0 / scale, 0.0, 0.0, 1.0 / scale, left, top),
            page_pts_to_ost=None if k is None else (k, 0.0, 0.0, k, 0.0, 0.0),
        )

    @staticmethod
    def overlay_status(overlay_ids: Any) -> Optional[str]:
        if overlay_ids is None:
            return None
        if not isinstance(overlay_ids, list) or not all(
            isinstance(item, str) for item in overlay_ids
        ):
            raise AiTakeoffRequestError(
                ERROR_INVALID_ARGUMENT, "overlay_ids must be a list of ids"
            )
        return OVERLAY_NOT_SUPPORTED_UNTIL_M1B

    def _open_bid(self, bid_uid: Optional[str]) -> _OpenBid:
        bid_ref = self._project_data.get_current_bid_ref()
        bid = self._project_data.get_current_bid()
        if bid_ref is None or bid is None:
            raise AiTakeoffRequestError(
                ERROR_BID_NOT_OPEN, "Open a bid in OST Visualizer first."
            )
        if bid_uid is not None and str(bid_uid) != str(bid.uid):
            raise AiTakeoffRequestError(
                ERROR_BID_NOT_OPEN, "Only the bid open in OST Visualizer can be read."
            )
        pages = sorted(
            self._project_data.get_all_pages(),
            key=lambda page: (page.sequence, page.uid),
        )
        return _OpenBid(bid_ref, bid, pages)

    def _sheet(self, page) -> dict:
        if not page.image_path:
            source = "blank"
        elif is_pdf_suffix(page.image_path):
            source = "pdf"
        else:
            source = "image"
        return {
            "page_uid": page.uid,
            "name": UntrustedText.of(page.name).to_dict(),
            "sheet_no": UntrustedText.of(page.sheet_no).to_dict(),
            "sequence": page.sequence,
            "size_pts": [float(page.width_pts), float(page.height_pts)],
            "scale": {
                "sf1": float(page.scale_factor1),
                "sf2": float(page.scale_factor2),
            },
            "ost_inches_per_page_point": _ost_per_page_point(page),
            "source": source,
            "takeoff_count": len(self._project_data.get_page_takeoffs(page.uid)),
        }

    @staticmethod
    def _quantity_rows(conditions: dict, takeoffs: Iterable) -> list:
        takeoff_list = list(takeoffs)
        counts = {}
        for takeoff in takeoff_list:
            counts[takeoff.condition_uid] = counts.get(takeoff.condition_uid, 0) + 1
        totals = compute_page_quantities(conditions, takeoff_list)
        rows = []
        for condition_uid in sorted(totals):
            condition = conditions[condition_uid]
            quantities = [
                {"value": round(value, QUANTITY_DECIMALS), "uom": get_uom_label(uom)}
                for value, uom in zip(
                    totals[condition_uid],
                    (condition.uom1, condition.uom2, condition.uom3),
                )
                if uom is not None and uom >= 0
            ]
            rows.append(
                {
                    "condition_uid": condition_uid,
                    "name": UntrustedText.of(condition.name).to_dict(),
                    "type": _CONDITION_TYPE_NAMES.get(
                        condition.condition_type, "other"
                    ),
                    "takeoff_count": counts.get(condition_uid, 0),
                    "quantities": quantities,
                }
            )
        return rows

    def _sidecar(self, open_bid: _OpenBid):
        context = load_sidecar_context(
            open_bid.bid_ref,
            open_bid.bid,
            open_bid.pages,
            self._descriptor_resolver,
            self._sidecar_repository,
        )
        if context.status != FINGERPRINT_OK:
            return context.status, None
        return FINGERPRINT_OK, context.sidecar

    def _raw_frame(self, snapshot: PageSnapshot):
        if not snapshot.is_pdf:
            return STATUS_NOT_PDF
        info = self._pdf_source.get_page_info(snapshot.image_path, snapshot.page_index)
        if info.status != STATUS_OK:
            return info.status
        raw_w = info.crop_width_pts or info.media_width_pts or info.effective_width_pts
        raw_h = (
            info.crop_height_pts or info.media_height_pts or info.effective_height_pts
        )
        return float(raw_w), float(raw_h), int(info.intrinsic_rotation or 0) % 360


def _ost_per_page_point(page) -> Optional[float]:
    sf1 = float(page.scale_factor1 or 0.0)
    sf2 = float(page.scale_factor2 or 0.0)
    if sf1 <= 0.0 or sf2 <= 0.0:
        return None
    return sf2 / (POINTS_PER_INCH * sf1)


def _raw_to_page(x: float, y: float, frame: tuple) -> tuple:
    raw_w, raw_h, rotation = frame
    x = float(x)
    y = float(y)
    if rotation == 90:
        return y, x
    if rotation == 180:
        return raw_w - x, y
    if rotation == 270:
        return raw_h - y, raw_w - x
    return x, raw_h - y


def _bounds(points) -> list:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _intersects(bounds: list, box: tuple) -> bool:
    left, top, right, bottom = box
    return not (
        bounds[2] < left or bounds[0] > right or bounds[3] < top or bounds[1] > bottom
    )


def _scale_values(values: list, factor: Optional[float]) -> Optional[list]:
    if factor is None:
        return None
    return [value * factor for value in values]


def _numbers(values: Any, label: str) -> tuple:
    if not isinstance(values, list) or len(values) != 4:
        raise AiTakeoffRequestError(
            ERROR_INVALID_ARGUMENT, f"{label} needs four numbers"
        )
    numbers = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AiTakeoffRequestError(
                ERROR_INVALID_ARGUMENT, f"{label} needs numbers"
            )
        number = float(value)
        if not math.isfinite(number):
            raise AiTakeoffRequestError(
                ERROR_INVALID_ARGUMENT, f"{label} must be finite"
            )
        numbers.append(number)
    return tuple(numbers)


def _optional_box(bbox_pts: Any) -> Optional[tuple]:
    if bbox_pts is None:
        return None
    left, top, right, bottom = _numbers(bbox_pts, "bbox_pts")
    if right <= left or bottom <= top:
        raise AiTakeoffRequestError(
            ERROR_INVALID_ARGUMENT, "bbox_pts must be [left, top, right, bottom]"
        )
    return left, top, right, bottom


def _dpi(dpi: Any) -> float:
    if dpi is None:
        return RENDER_DEFAULT_DPI
    if isinstance(dpi, bool) or not isinstance(dpi, (int, float)):
        raise AiTakeoffRequestError(ERROR_INVALID_ARGUMENT, "dpi must be a number")
    value = float(dpi)
    if not math.isfinite(value) or value < 1.0 or value > RENDER_MAX_DPI:
        raise AiTakeoffRequestError(
            ERROR_INVALID_ARGUMENT, f"dpi must be between 1 and {RENDER_MAX_DPI:g}"
        )
    return value


def _paginate(items: list, cursor: Optional[str], limit: Any):
    try:
        offset = decode_cursor(cursor)
        size = clamp_limit(limit)
    except ValueError as exc:
        raise AiTakeoffRequestError(ERROR_INVALID_ARGUMENT, str(exc)) from exc
    page = items[offset : offset + size]
    end = offset + len(page)
    next_cursor = encode_cursor(end) if end < len(items) else None
    meta = ResultMeta(
        limit=size,
        returned_count=len(page),
        total_count=len(items),
        next_cursor=next_cursor,
    )
    return page, meta


def _page_status(page: list, meta: ResultMeta) -> str:
    if meta.next_cursor is not None:
        return STATUS_TRUNCATED
    return STATUS_OK if page else STATUS_EMPTY
