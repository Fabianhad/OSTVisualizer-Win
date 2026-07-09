import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple
from ...domain.entities.annotation import (
    ANNOTATION_TYPE_CALLOUT,
    ANNOTATION_TYPE_DIMENSION,
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
)
from ...domain.entities.area import BidArea
from ...domain.entities.area import is_unassigned_area_uid as _is_unassigned_area_uid
from ...domain.entities.area import normalize_area_uid as _normalize_area_uid
from ...domain.entities.condition import Condition
from ...domain.entities.file_extensions import is_pdf_suffix
from ...domain.entities.file_results import BidLoadResult, FileLoadResult
from ...domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ...domain.entities.hotlink import build_hotlink_from_annotation
from ...domain.entities.named_view import NamedView, build_named_view_from_annotation
from ...domain.entities.page import Page
from ...domain.entities.takeoff import Takeoff
from ...domain.repositories.i_project_repository import IProjectRepository
from ...domain.services.condition_quantity_service import compute_page_quantities
from ...domain.services.takeoff_domain_service import is_takeoff_visible
from ...domain.services.uom_service import get_uom_label
from ..dtos.condition_summary_dtos import (
    SUMMARY_GROUP_AREA,
    SUMMARY_GROUP_PAGE,
    SUMMARY_GROUP_TYPE,
    SUMMARY_NODE_FOLDER,
    SUMMARY_NODE_GROUP,
    ConditionSummaryGrouping,
    ConditionSummaryNode,
    ConditionSummaryValues,
)
from ..dtos.mcp_context_dtos import (
    MCP_OVERLAY_KIND_PDF,
    MCP_OVERLAY_KIND_RASTER,
    MCP_PAGE_SOURCE_BLANK,
    MCP_PAGE_SOURCE_COMPOSITE,
    MCP_PAGE_SOURCE_MAIN,
    MCP_PAGE_SOURCE_OVERLAY,
    MCP_PDF_SOURCE_AUTO,
    MCP_PDF_SOURCE_MAIN,
    MCP_PDF_SOURCE_OVERLAY,
    MCP_PDF_SOURCES,
    MCP_STATUS_CONFIGURED,
    MCP_STATUS_DEFERRED,
    MCP_STATUS_EMPTY,
    MCP_STATUS_NOT_CONFIGURED,
    MCP_STATUS_NOT_PDF,
    MCP_STATUS_OK,
    MCP_STATUS_TRUNCATED,
    MCP_STATUS_UNAVAILABLE,
    MCP_SUMMARY_DEFAULT_GROUP_BY_AREA,
    MCP_SUMMARY_DEFAULT_GROUP_BY_PAGE,
    MCP_SUMMARY_DEFAULT_GROUP_BY_TYPE,
    MCP_SUMMARY_DEFAULT_LIMIT,
    MCP_SUMMARY_MAX_LIMIT,
    McpAreaDto,
    McpAreaSummaryDto,
    McpBidDto,
    McpBidQuantitySummaryDto,
    McpConditionDto,
    McpConditionQuantitySummaryDto,
    McpConditionSummaryDto,
    McpDatabaseDto,
    McpDuplicateConditionGroupDto,
    McpDuplicateConditionSummaryDto,
    McpHierarchyDto,
    McpHotlinkDto,
    McpLayerDto,
    McpMarkupSampleDto,
    McpNamedViewDto,
    McpPageContextDto,
    McpPageDto,
    McpPageMarkupsSummaryDto,
    McpPageOverlaySummaryDto,
    McpPageTakeoffSummaryDto,
    McpPdfOverlayTransformDto,
    McpPdfTextRunDto,
    McpPdfTextSearchMatchDto,
    McpPdfTextSearchSummaryDto,
    McpPdfTextSummaryDto,
    McpPdfVectorSegmentDto,
    McpPdfVectorsSummaryDto,
    McpProjectDto,
    McpQuantityDto,
    McpResultMetaDto,
    McpScopeGapSummaryDto,
    McpSelectedPagesSummaryDto,
    McpSelectedTakeoffsSummaryDto,
    McpSummaryDto,
    McpSummaryGroupingDto,
    McpSummaryNodeDto,
    McpSummaryValuesDto,
    McpTakeoffDto,
    McpUnplacedTakeoffSummaryDto,
    McpZeroQuantitySummaryDto,
)
from ..dtos.pdf_metadata_dtos import PdfPageInfoDto, PdfTextRunDto, PdfVectorSegmentDto
from ..interfaces.i_pdf_metadata_provider import IPdfMetadataProvider
from ..use_cases.project.condition_summary_service import ConditionSummaryService


class McpReadError(ValueError):
    pass


@dataclass
class McpDatabaseRef:
    database_id: str
    file_path: str
    display_name: str


def _summary_status_for_meta(meta: McpResultMetaDto) -> str:
    if meta.truncated:
        return MCP_STATUS_TRUNCATED
    if meta.total_count == 0:
        return MCP_STATUS_EMPTY
    return MCP_STATUS_OK


class McpLimitedList(list):
    def __init__(self, items: List, meta: McpResultMetaDto):
        super().__init__(items)
        self.meta = meta
        self.status = _summary_status_for_meta(meta)


class McpReadService:
    PDF_TEXT_DEFAULT_LIMIT = 10
    PDF_TEXT_MAX_LIMIT = 50
    PDF_VECTOR_DEFAULT_LIMIT = 20
    PDF_VECTOR_MAX_LIMIT = 100
    MARKUP_DEFAULT_LIMIT = 50
    MARKUP_MAX_LIMIT = 250
    SUMMARY_DEFAULT_LIMIT = MCP_SUMMARY_DEFAULT_LIMIT
    SUMMARY_MAX_LIMIT = MCP_SUMMARY_MAX_LIMIT

    def __init__(
        self,
        project_repository: IProjectRepository,
        databases: Iterable[McpDatabaseRef],
        pdf_metadata_provider: Optional[IPdfMetadataProvider] = None,
        summary_service: Optional[ConditionSummaryService] = None,
    ):
        self._repository = project_repository
        self._pdf_metadata_provider = pdf_metadata_provider
        self._summary_service = summary_service or ConditionSummaryService()
        self._databases: Dict[str, McpDatabaseRef] = {
            db.database_id: db for db in databases
        }

    def list_databases(self) -> List[McpDatabaseDto]:
        return [
            McpDatabaseDto(
                database_id=db.database_id,
                display_name=db.display_name,
                basename=self._safe_basename(db.file_path),
                path_status="checked",
                exists=True,
            )
            for db in sorted(
                self._databases.values(),
                key=lambda item: (item.display_name.lower(), item.file_path.lower()),
            )
        ]

    def set_databases(self, databases: Iterable[McpDatabaseRef]) -> None:
        self._databases = {db.database_id: db for db in databases}

    def get_database(self, database_id: str) -> McpDatabaseRef:
        db = self._databases.get(str(database_id or ""))
        if db is None:
            raise McpReadError(f"Unknown database_id: {database_id}")
        return db

    def get_hierarchy(self, database_id: str) -> McpHierarchyDto:
        db = self.get_database(database_id)
        result = self._load_file(db)
        entry = self._find_file_entry(result.hierarchy, db.file_path)
        if entry is None:
            raise McpReadError("Database hierarchy is unavailable")
        return McpHierarchyDto(
            database=McpDatabaseDto(
                database_id=db.database_id,
                display_name=db.display_name,
                basename=self._safe_basename(db.file_path),
                path_status="checked",
            ),
            projects=[
                self._project_dto(uid, project)
                for uid, project in entry.bid_projects.items()
            ],
            orphan_bids=[self._bid_dto(bid, None, None) for bid in entry.orphan_bids],
        )

    def list_projects(self, database_id: str) -> List[McpProjectDto]:
        return self.get_hierarchy(database_id).projects

    def list_bids(
        self, database_id: str, project_uid: Optional[str] = None
    ) -> List[McpBidDto]:
        entry = self._get_file_entry(database_id)
        bids: List[McpBidDto] = []
        if project_uid:
            project = entry.bid_projects.get(project_uid)
            if project is None:
                raise McpReadError(f"Unknown project_uid: {project_uid}")
            return [
                self._bid_dto(bid, project_uid, project.name) for bid in project.bids
            ]
        for uid, project in entry.bid_projects.items():
            bids.extend(self._bid_dto(bid, uid, project.name) for bid in project.bids)
        bids.extend(self._bid_dto(bid, None, None) for bid in entry.orphan_bids)
        return bids

    def get_bid_summary(self, database_id: str, bid_uid: str) -> McpBidDto:
        entry = self._get_file_entry(database_id)
        bid, project_uid, project_name = self._find_bid(entry, bid_uid)
        bid_data = self._load_bid(database_id, bid_uid)
        dto = self._bid_dto(bid, project_uid, project_name)
        dto.selected_page_uid = bid_data.selected_page_uid
        return dto

    def list_pages(
        self, database_id: str, bid_uid: str, limit: int = 500
    ) -> List[McpPageDto]:
        bid_data = self._load_bid(database_id, bid_uid)
        pages = [self._page_dto(page) for page in self._ordered_pages(bid_data)]
        return self._limited_list(pages, limit)

    def get_current_page(self, database_id: str, bid_uid: str) -> Optional[McpPageDto]:
        bid_data = self._load_bid(database_id, bid_uid)
        page_uid = bid_data.selected_page_uid
        if page_uid and page_uid in bid_data.pages:
            return self._page_dto(bid_data.pages[page_uid])
        pages = self._ordered_pages(bid_data)
        return self._page_dto(pages[0]) if pages else None

    def search_pages(
        self,
        database_id: str,
        bid_uid: str,
        query: str,
        limit: int = 50,
    ) -> List[McpPageDto]:
        query_text = str(query or "").strip().lower()
        if not query_text:
            return self._limited_list([], limit, default=50)
        bid_data = self._load_bid(database_id, bid_uid)
        matches = []
        for page in self._ordered_pages(bid_data):
            haystack = " ".join(
                [page.uid, page.name, page.sheet_no, str(page.sequence)]
            ).lower()
            if query_text in haystack:
                matches.append(self._page_dto(page))
        return self._limited_list(matches, limit, default=50)

    def get_page_metadata(
        self, database_id: str, bid_uid: str, page_uid: str
    ) -> McpPageDto:
        bid_data = self._load_bid(database_id, bid_uid)
        page = bid_data.pages.get(page_uid)
        if page is None:
            raise McpReadError(f"Unknown page_uid: {page_uid}")
        return self._page_dto(page, include_pdf_metadata=True)

    def get_page_pdf_text_summary(
        self,
        database_id: str,
        bid_uid: str,
        page_uid: str,
        source: str = MCP_PDF_SOURCE_AUTO,
        include_text: bool = False,
        limit: int = 10,
    ) -> McpPdfTextSummaryDto:
        bid_data = self._load_bid(database_id, bid_uid)
        page = bid_data.pages.get(page_uid)
        if page is None:
            raise McpReadError(f"Unknown page_uid: {page_uid}")
        source_ref = self._resolve_pdf_source(page, source)
        clean_limit = self._clean_limit(
            limit,
            default=self.PDF_TEXT_DEFAULT_LIMIT,
            max_limit=self.PDF_TEXT_MAX_LIMIT,
        )
        if source_ref[2] != MCP_STATUS_CONFIGURED:
            meta = McpResultMetaDto(limit=clean_limit)
            return McpPdfTextSummaryDto(
                status=source_ref[2],
                database_id=database_id,
                bid_uid=bid_uid,
                page_uid=page_uid,
                source=source_ref[0],
                source_status=source_ref[2],
                meta=meta,
            )
        runs = self._read_pdf_text_runs(source_ref[1], source_ref[3])
        limited, meta = self._limited(
            runs,
            clean_limit,
            default=self.PDF_TEXT_DEFAULT_LIMIT,
            max_limit=self.PDF_TEXT_MAX_LIMIT,
        )
        total_character_count = sum(len(run.text or "") for run in runs)
        returned_runs = [
            self._pdf_text_run_dto(run, include_text=include_text) for run in limited
        ]
        return McpPdfTextSummaryDto(
            status=_summary_status_for_meta(meta),
            database_id=database_id,
            bid_uid=bid_uid,
            page_uid=page_uid,
            source=source_ref[0],
            source_status=source_ref[2],
            meta=meta,
            text_run_count=len(runs),
            character_count=total_character_count,
            returned_character_count=sum(len(run.text or "") for run in limited),
            runs=returned_runs,
        )

    def get_page_pdf_vectors_summary(
        self,
        database_id: str,
        bid_uid: str,
        page_uid: str,
        source: str = MCP_PDF_SOURCE_AUTO,
        limit: int = 20,
    ) -> McpPdfVectorsSummaryDto:
        bid_data = self._load_bid(database_id, bid_uid)
        page = bid_data.pages.get(page_uid)
        if page is None:
            raise McpReadError(f"Unknown page_uid: {page_uid}")
        source_ref = self._resolve_pdf_source(page, source)
        clean_limit = self._clean_limit(
            limit,
            default=self.PDF_VECTOR_DEFAULT_LIMIT,
            max_limit=self.PDF_VECTOR_MAX_LIMIT,
        )
        if source_ref[2] != MCP_STATUS_CONFIGURED:
            meta = McpResultMetaDto(limit=clean_limit)
            return McpPdfVectorsSummaryDto(
                status=source_ref[2],
                database_id=database_id,
                bid_uid=bid_uid,
                page_uid=page_uid,
                source=source_ref[0],
                source_status=source_ref[2],
                meta=meta,
            )
        segments = self._read_pdf_vector_segments(source_ref[1], source_ref[3])
        limited, meta = self._limited(
            segments,
            clean_limit,
            default=self.PDF_VECTOR_DEFAULT_LIMIT,
            max_limit=self.PDF_VECTOR_MAX_LIMIT,
        )
        point_count = self._pdf_snap_point_count(segments)
        return McpPdfVectorsSummaryDto(
            status=_summary_status_for_meta(meta),
            database_id=database_id,
            bid_uid=bid_uid,
            page_uid=page_uid,
            source=source_ref[0],
            source_status=source_ref[2],
            meta=meta,
            snap_line_count=len(segments),
            snap_point_count=point_count,
            segments=[self._pdf_vector_segment_dto(segment) for segment in limited],
        )

    def get_page_markups_summary(
        self,
        database_id: str,
        bid_uid: str,
        page_uid: str,
        limit: int = 50,
    ) -> McpPageMarkupsSummaryDto:
        bid_data = self._load_bid(database_id, bid_uid)
        page = bid_data.pages.get(page_uid)
        if page is None:
            raise McpReadError(f"Unknown page_uid: {page_uid}")
        markups = [
            annotation
            for annotation in bid_data.bid_annotations
            if annotation.page_uid == page_uid
        ]
        limited, meta = self._limited(
            markups,
            limit,
            default=self.MARKUP_DEFAULT_LIMIT,
            max_limit=self.MARKUP_MAX_LIMIT,
        )
        counts_by_type: Dict[str, int] = defaultdict(int)
        for annotation in markups:
            counts_by_type[annotation.annotation_type] += 1
        return McpPageMarkupsSummaryDto(
            status=_summary_status_for_meta(meta),
            database_id=database_id,
            bid_uid=bid_uid,
            page_uid=page_uid,
            page_name=page.name,
            sheet_no=page.sheet_no,
            meta=meta,
            total_markup_count=len(markups),
            visible_markup_count=sum(1 for annotation in markups if annotation.visible),
            dimension_count=counts_by_type.get(ANNOTATION_TYPE_DIMENSION, 0),
            text_annotation_count=counts_by_type.get(ANNOTATION_TYPE_TEXT, 0),
            callout_count=counts_by_type.get(ANNOTATION_TYPE_CALLOUT, 0),
            hotlink_count=counts_by_type.get(ANNOTATION_TYPE_HOTLINK, 0),
            named_view_count=counts_by_type.get(ANNOTATION_TYPE_NAMED_VIEW, 0),
            counts_by_type=dict(sorted(counts_by_type.items())),
            samples=[self._markup_sample_dto(annotation) for annotation in limited],
        )

    def get_page_overlay_summary(
        self,
        database_id: str,
        bid_uid: str,
        page_uid: str,
    ) -> McpPageOverlaySummaryDto:
        bid_data = self._load_bid(database_id, bid_uid)
        page = bid_data.pages.get(page_uid)
        if page is None:
            raise McpReadError(f"Unknown page_uid: {page_uid}")
        image_path = page.image_path or ""
        overlay_path = page.overlay_image_path or ""
        show_original, show_overlay = self._image_show_flags(page.image_show_mode)
        return McpPageOverlaySummaryDto(
            status=MCP_STATUS_OK if overlay_path else MCP_STATUS_NOT_CONFIGURED,
            database_id=database_id,
            bid_uid=bid_uid,
            page_uid=page_uid,
            page_name=page.name,
            sheet_no=page.sheet_no,
            source_kind=self._page_source_kind(page),
            image_basename=self._safe_basename(image_path) if image_path else None,
            image_path_status=(
                MCP_STATUS_CONFIGURED if image_path else MCP_STATUS_NOT_CONFIGURED
            ),
            is_pdf=bool(image_path and is_pdf_suffix(image_path)),
            has_overlay=bool(overlay_path),
            overlay_basename=(
                self._safe_basename(overlay_path) if overlay_path else None
            ),
            overlay_path_status=(
                MCP_STATUS_CONFIGURED if overlay_path else MCP_STATUS_NOT_CONFIGURED
            ),
            overlay_kind=self._overlay_kind(page),
            show_mode=page.image_show_mode,
            show_original=show_original,
            show_overlay=show_overlay and bool(overlay_path),
            overlay_transform_summary=self._overlay_transform_summary(page),
        )

    def search_page_pdf_text(
        self,
        database_id: str,
        bid_uid: str,
        page_uid: str,
        query: str,
        source: str = MCP_PDF_SOURCE_AUTO,
        limit: int = 10,
    ) -> McpPdfTextSearchSummaryDto:
        bid_data = self._load_bid(database_id, bid_uid)
        page = bid_data.pages.get(page_uid)
        if page is None:
            raise McpReadError(f"Unknown page_uid: {page_uid}")
        source_ref = self._resolve_pdf_source(page, source)
        clean_query = " ".join(str(query or "").split())
        clean_limit = self._clean_limit(
            limit,
            default=self.PDF_TEXT_DEFAULT_LIMIT,
            max_limit=self.PDF_TEXT_MAX_LIMIT,
        )
        if source_ref[2] != MCP_STATUS_CONFIGURED:
            meta = McpResultMetaDto(limit=clean_limit)
            return McpPdfTextSearchSummaryDto(
                status=source_ref[2],
                database_id=database_id,
                bid_uid=bid_uid,
                page_uid=page_uid,
                query=clean_query,
                source=source_ref[0],
                source_status=source_ref[2],
                meta=meta,
            )
        if not clean_query:
            meta = McpResultMetaDto(limit=clean_limit)
            return McpPdfTextSearchSummaryDto(
                status=MCP_STATUS_EMPTY,
                database_id=database_id,
                bid_uid=bid_uid,
                page_uid=page_uid,
                query=clean_query,
                source=source_ref[0],
                source_status=source_ref[2],
                meta=meta,
            )
        query_text = clean_query.lower()
        matches = [
            self._pdf_text_search_match_dto(page, source_ref[0], run, clean_query)
            for run in self._read_pdf_text_runs(source_ref[1], source_ref[3])
            if query_text in (run.text or "").lower()
        ]
        limited, meta = self._limited(
            matches,
            clean_limit,
            default=self.PDF_TEXT_DEFAULT_LIMIT,
            max_limit=self.PDF_TEXT_MAX_LIMIT,
        )
        return McpPdfTextSearchSummaryDto(
            status=_summary_status_for_meta(meta),
            database_id=database_id,
            bid_uid=bid_uid,
            page_uid=page_uid,
            query=clean_query,
            source=source_ref[0],
            source_status=source_ref[2],
            meta=meta,
            match_count=len(matches),
            matches=limited,
        )

    def list_conditions(
        self, database_id: str, bid_uid: str, limit: int = 500
    ) -> List[McpConditionDto]:
        bid_data = self._load_bid(database_id, bid_uid)
        conditions = [
            self._condition_dto(condition)
            for condition in self._ordered_conditions(bid_data)
        ]
        return self._limited_list(conditions, limit)

    def list_areas(
        self, database_id: str, bid_uid: str, limit: int = 500
    ) -> List[McpAreaDto]:
        bid_data = self._load_bid(database_id, bid_uid)
        counts, visible_counts, page_uids = self._area_usage_maps(bid_data)
        children = self._area_child_uid_map(bid_data)
        areas = [
            self._area_dto(area, counts, visible_counts, page_uids, children)
            for area in self._ordered_areas(bid_data)
        ]
        return self._limited_list(areas, limit)

    def get_area_summary(
        self,
        database_id: str,
        bid_uid: str,
        area_uid: str,
        limit: int = 250,
    ) -> McpAreaSummaryDto:
        bid_data = self._load_bid(database_id, bid_uid)
        normalized_uid = self._normalize_area_uid(area_uid)
        counts, visible_counts, page_uids = self._area_usage_maps(bid_data)
        children = self._area_child_uid_map(bid_data)
        if self._is_unassigned_area_uid(normalized_uid):
            area_dto = McpAreaDto(
                uid="0",
                bid_uid=str(bid_uid),
                name="Unassigned",
                takeoff_count=counts.get("0", 0),
                visible_takeoff_count=visible_counts.get("0", 0),
                page_count=len(page_uids.get("0", set())),
            )
            child_dtos: List[McpAreaDto] = []
        else:
            area = bid_data.bid_areas.get(normalized_uid)
            if area is None:
                raise McpReadError(f"Unknown area_uid: {area_uid}")
            area_dto = self._area_dto(area, counts, visible_counts, page_uids, children)
            child_dtos = [
                self._area_dto(child, counts, visible_counts, page_uids, children)
                for child in self._ordered_areas(bid_data)
                if child.parent_uid == area.uid
            ]
        area_takeoffs = [
            takeoff
            for takeoff in bid_data.bid_takeoffs
            if self._normalize_area_uid(takeoff.area_uid) == area_dto.uid
        ]
        pages = self._page_takeoff_summaries(area_takeoffs, bid_data)
        limited_pages, meta = self._limited(pages, limit, default=250)
        return McpAreaSummaryDto(
            status=_summary_status_for_meta(meta),
            database_id=database_id,
            bid_uid=bid_uid,
            area=area_dto,
            meta=meta,
            pages=limited_pages,
            children=child_dtos,
        )

    def resolve_area_name(
        self, database_id: str, bid_uid: str, area_uid: str
    ) -> Optional[str]:
        if self._is_unassigned_area_uid(area_uid):
            return None
        bid_data = self._load_bid(database_id, bid_uid)
        return self._area_name(area_uid, bid_data)

    def search_conditions(
        self,
        database_id: str,
        bid_uid: str,
        query: str,
        limit: int = 50,
    ) -> List[McpConditionDto]:
        query_text = str(query or "").strip().lower()
        if not query_text:
            return []
        bid_data = self._load_bid(database_id, bid_uid)
        matches = []
        for condition in self._ordered_conditions(bid_data):
            haystack = " ".join(
                [
                    condition.uid,
                    condition.name,
                    condition.cdn_type_name,
                    condition.notes,
                    str(condition.ref_no),
                    self._condition_type_name(condition),
                ]
            ).lower()
            if query_text in haystack:
                matches.append(self._condition_dto(condition))
        return self._limited_list(matches, limit, default=50)

    def get_condition_summary(
        self,
        database_id: str,
        bid_uid: str,
        condition_uid: str,
    ) -> McpConditionSummaryDto:
        bid_data = self._load_bid(database_id, bid_uid)
        condition = bid_data.bid_conditions.get(condition_uid)
        if condition is None:
            raise McpReadError(f"Unknown condition_uid: {condition_uid}")
        takeoffs = [
            t for t in bid_data.bid_takeoffs if t.condition_uid == condition_uid
        ]
        visible_takeoffs = [
            t for t in takeoffs if is_takeoff_visible(t, bid_data.bid_conditions)
        ]
        quantities = compute_page_quantities(
            bid_data.bid_conditions,
            visible_takeoffs,
            only_condition_uids={condition_uid},
        )
        return McpConditionSummaryDto(
            condition=self._condition_dto(condition),
            quantities=self._quantity_dtos(
                quantities, bid_data.bid_conditions, visible_takeoffs
            ),
            pages=self._page_takeoff_summaries(takeoffs, bid_data),
            takeoff_count=len(takeoffs),
            visible_takeoff_count=len(visible_takeoffs),
        )

    def list_takeoffs(
        self,
        database_id: str,
        bid_uid: str,
        page_uid: Optional[str] = None,
        condition_uid: Optional[str] = None,
        visible_only: bool = True,
        include_geometry: bool = False,
        limit: int = 500,
    ) -> List[McpTakeoffDto]:
        bid_data = self._load_bid(database_id, bid_uid)
        takeoffs = self._filter_takeoffs(
            bid_data,
            page_uid=page_uid,
            condition_uid=condition_uid,
            visible_only=visible_only,
        )
        max_limit = 250 if include_geometry else 5000
        limited, meta = self._limited(takeoffs, limit, max_limit=max_limit)
        return McpLimitedList(
            [
                self._takeoff_dto(t, bid_data, include_geometry=include_geometry)
                for t in limited
            ],
            meta,
        )

    def get_selected_takeoffs_summary(
        self,
        database_id: str,
        bid_uid: str,
        selected_takeoff_uids: List[str],
        limit: int = 500,
    ) -> McpSelectedTakeoffsSummaryDto:
        wanted = [str(uid) for uid in selected_takeoff_uids if uid]
        if not wanted:
            return McpSelectedTakeoffsSummaryDto(
                status="no_selection",
                message="No takeoffs are selected in the live OST Visualizer context.",
                database_id=database_id,
                bid_uid=bid_uid,
            )
        bid_data = self._load_bid(database_id, bid_uid)
        by_uid = {takeoff.uid: takeoff for takeoff in bid_data.bid_takeoffs}
        clean_limit = self._clean_limit(limit)
        selected = [by_uid[uid] for uid in wanted if uid in by_uid][:clean_limit]
        missing = [uid for uid in wanted if uid not in by_uid]
        if not selected:
            return McpSelectedTakeoffsSummaryDto(
                status="stale_selection",
                message="The live selected takeoff IDs were not found in the loaded bid.",
                database_id=database_id,
                bid_uid=bid_uid,
                missing_takeoff_uids=missing,
            )
        quantities = compute_page_quantities(bid_data.bid_conditions, selected)
        return McpSelectedTakeoffsSummaryDto(
            status=MCP_STATUS_OK,
            database_id=database_id,
            bid_uid=bid_uid,
            selected_takeoff_count=len(selected),
            missing_takeoff_uids=missing,
            takeoffs=[
                self._takeoff_dto(t, bid_data, include_geometry=False) for t in selected
            ],
            quantities=self._quantity_dtos(
                quantities, bid_data.bid_conditions, selected
            ),
            pages=self._page_takeoff_summaries(selected, bid_data),
            condition_uids=sorted({t.condition_uid for t in selected}),
        )

    def get_selected_pages_summary(
        self,
        database_id: str,
        bid_uid: str,
        selected_page_uids: List[str],
        active_view: str = "",
        active_page_uid: Optional[str] = None,
    ) -> McpSelectedPagesSummaryDto:
        wanted = [str(uid) for uid in selected_page_uids if uid]
        if not wanted:
            return McpSelectedPagesSummaryDto(
                status="no_selection",
                message="No pages are selected for the live OST Visualizer context.",
                database_id=database_id,
                bid_uid=bid_uid,
                active_view=active_view,
                active_page_uid=active_page_uid,
            )
        bid_data = self._load_bid(database_id, bid_uid)
        pages = [bid_data.pages[uid] for uid in wanted if uid in bid_data.pages]
        missing = [uid for uid in wanted if uid not in bid_data.pages]
        if not pages:
            return McpSelectedPagesSummaryDto(
                status="stale_selection",
                message="The live selected page IDs were not found in the loaded bid.",
                database_id=database_id,
                bid_uid=bid_uid,
                active_view=active_view,
                active_page_uid=active_page_uid,
                missing_page_uids=missing,
            )
        return McpSelectedPagesSummaryDto(
            status=MCP_STATUS_OK,
            database_id=database_id,
            bid_uid=bid_uid,
            active_view=active_view,
            active_page_uid=active_page_uid,
            selected_page_uids=[page.uid for page in pages],
            missing_page_uids=missing,
            pages=[self._page_dto(page) for page in pages],
        )

    def summarize_quantities(
        self,
        database_id: str,
        bid_uid: str,
        page_uid: Optional[str] = None,
        condition_uid: Optional[str] = None,
        limit: int = 500,
    ) -> List[McpQuantityDto]:
        bid_data = self._load_bid(database_id, bid_uid)
        takeoffs = self._filter_takeoffs(
            bid_data,
            page_uid=page_uid,
            condition_uid=condition_uid,
            visible_only=True,
        )
        quantities = compute_page_quantities(
            bid_data.bid_conditions,
            takeoffs,
            only_condition_uids={condition_uid} if condition_uid else None,
        )
        dtos = self._quantity_dtos(quantities, bid_data.bid_conditions, takeoffs)
        return self._limited_list(dtos, limit)

    def get_page_quantity_summary(
        self, database_id: str, bid_uid: str, page_uid: str
    ) -> List[McpQuantityDto]:
        return self.summarize_quantities(database_id, bid_uid, page_uid=page_uid)

    def get_bid_quantity_summary(
        self,
        database_id: str,
        bid_uid: str,
        limit: int = 250,
    ) -> McpBidQuantitySummaryDto:
        bid_data = self._load_bid(database_id, bid_uid)
        summaries = [
            self._condition_quantity_summary(condition, bid_data)
            for condition in self._ordered_conditions(bid_data)
        ]
        limited, meta = self._limited(summaries, limit, default=250)
        return McpBidQuantitySummaryDto(
            status=_summary_status_for_meta(meta),
            database_id=database_id,
            bid_uid=bid_uid,
            meta=meta,
            conditions=limited,
        )

    def get_summary(
        self,
        database_id: str,
        bid_uid: str,
        group_by_page: bool = MCP_SUMMARY_DEFAULT_GROUP_BY_PAGE,
        group_by_type: bool = MCP_SUMMARY_DEFAULT_GROUP_BY_TYPE,
        group_by_area: bool = MCP_SUMMARY_DEFAULT_GROUP_BY_AREA,
        limit: int = SUMMARY_DEFAULT_LIMIT,
    ) -> McpSummaryDto:
        entry = self._get_file_entry(database_id)
        bid, project_uid, project_name = self._find_bid(entry, bid_uid)
        bid_data = self._load_bid(database_id, bid_uid)
        grouping = ConditionSummaryGrouping(
            by_page=bool(group_by_page),
            by_type=bool(group_by_type),
            by_area=bool(group_by_area),
        )
        root = self._summary_service.build_summary(
            conditions=bid_data.bid_conditions,
            folders=bid_data.bid_condition_folders,
            takeoffs=bid_data.bid_takeoffs,
            pages=list(bid_data.pages.values()),
            areas=list(bid_data.bid_areas.values()),
            project_name=bid.name,
            grouping=grouping,
        )
        clean_limit = self._clean_limit(
            limit, default=self.SUMMARY_DEFAULT_LIMIT, max_limit=self.SUMMARY_MAX_LIMIT
        )
        total_count = self._summary_node_count(root)
        remaining = clean_limit
        nodes: List[McpSummaryNodeDto] = []
        for child in root.children:
            if remaining <= 0:
                break
            node, consumed = self._summary_node_dto_limited(
                child,
                remaining,
                folder_path=[],
                groups={},
            )
            if node is not None:
                nodes.append(node)
                remaining -= consumed
        returned_count = clean_limit - remaining
        truncated = returned_count < total_count
        meta = McpResultMetaDto(
            limit=clean_limit,
            returned_count=returned_count,
            total_count=total_count,
            truncated=truncated,
            has_more=truncated,
        )
        return McpSummaryDto(
            status=_summary_status_for_meta(meta),
            database_id=database_id,
            bid_uid=bid_uid,
            bid_name=bid.name,
            project_uid=project_uid,
            project_name=project_name or "",
            grouping=McpSummaryGroupingDto(
                group_by_page=grouping.by_page,
                group_by_type=grouping.by_type,
                group_by_area=grouping.by_area,
            ),
            meta=meta,
            root_label=root.label,
            total_node_count=total_count,
            nodes=nodes,
        )

    def review_scope_gaps(
        self,
        database_id: str,
        bid_uid: str,
        limit: int = 100,
    ) -> McpScopeGapSummaryDto:
        bid_data = self._load_bid(database_id, bid_uid)
        pages = self._pages_without_takeoffs(bid_data)
        conditions = self._conditions_without_takeoffs(bid_data)
        missing_pages = [
            takeoff
            for takeoff in bid_data.bid_takeoffs
            if not takeoff.page_uid or takeoff.page_uid not in bid_data.pages
        ]
        missing_conditions = [
            takeoff
            for takeoff in bid_data.bid_takeoffs
            if not takeoff.condition_uid
            or takeoff.condition_uid not in bid_data.bid_conditions
        ]
        total_count = (
            len(pages) + len(conditions) + len(missing_pages) + len(missing_conditions)
        )
        clean_limit = self._clean_limit(limit, default=100)
        remaining = clean_limit
        limited_pages = pages[:remaining]
        remaining -= len(limited_pages)
        limited_conditions = conditions[: max(0, remaining)]
        remaining -= len(limited_conditions)
        limited_missing_pages = missing_pages[: max(0, remaining)]
        remaining -= len(limited_missing_pages)
        limited_missing_conditions = missing_conditions[: max(0, remaining)]
        returned_count = (
            len(limited_pages)
            + len(limited_conditions)
            + len(limited_missing_pages)
            + len(limited_missing_conditions)
        )
        truncated = returned_count < total_count
        meta = McpResultMetaDto(
            limit=clean_limit,
            returned_count=returned_count,
            total_count=total_count,
            truncated=truncated,
            has_more=truncated,
        )
        return McpScopeGapSummaryDto(
            status=_summary_status_for_meta(meta),
            database_id=database_id,
            bid_uid=bid_uid,
            meta=meta,
            pages_without_takeoffs=limited_pages,
            conditions_without_takeoffs=limited_conditions,
            takeoffs_missing_pages=[
                self._takeoff_dto(takeoff, bid_data, include_geometry=False)
                for takeoff in limited_missing_pages
            ],
            takeoffs_missing_conditions=[
                self._takeoff_dto(takeoff, bid_data, include_geometry=False)
                for takeoff in limited_missing_conditions
            ],
        )

    def find_duplicate_conditions(
        self,
        database_id: str,
        bid_uid: str,
        limit: int = 100,
    ) -> McpDuplicateConditionSummaryDto:
        bid_data = self._load_bid(database_id, bid_uid)
        by_name: Dict[str, List[Condition]] = defaultdict(list)
        for condition in self._ordered_conditions(bid_data):
            name = " ".join(condition.name.lower().split())
            if name:
                by_name[name].append(condition)
        groups = [
            McpDuplicateConditionGroupDto(
                name=conditions[0].name,
                conditions=[self._condition_dto(condition) for condition in conditions],
            )
            for conditions in by_name.values()
            if len(conditions) > 1
        ]
        groups.sort(key=lambda group: group.name.lower())
        limited, meta = self._limited(groups, limit, default=100)
        return McpDuplicateConditionSummaryDto(
            status=_summary_status_for_meta(meta),
            database_id=database_id,
            bid_uid=bid_uid,
            meta=meta,
            groups=limited,
        )

    def find_zero_quantity_conditions(
        self,
        database_id: str,
        bid_uid: str,
        limit: int = 100,
    ) -> McpZeroQuantitySummaryDto:
        bid_data = self._load_bid(database_id, bid_uid)
        summaries = [
            self._condition_quantity_summary(condition, bid_data)
            for condition in self._ordered_conditions(bid_data)
        ]
        zero_summaries = [
            summary
            for summary in summaries
            if summary.takeoff_count > 0 and summary.zero_quantity
        ]
        limited, meta = self._limited(zero_summaries, limit, default=100)
        return McpZeroQuantitySummaryDto(
            status=_summary_status_for_meta(meta),
            database_id=database_id,
            bid_uid=bid_uid,
            meta=meta,
            conditions=limited,
        )

    def find_unplaced_takeoffs(
        self,
        database_id: str,
        bid_uid: str,
        limit: int = 100,
    ) -> McpUnplacedTakeoffSummaryDto:
        bid_data = self._load_bid(database_id, bid_uid)
        takeoffs = [
            takeoff
            for takeoff in bid_data.bid_takeoffs
            if not takeoff.page_uid
            or takeoff.page_uid == "NO_PAGE_ID"
            or takeoff.page_uid not in bid_data.pages
        ]
        limited, meta = self._limited(takeoffs, limit, default=100)
        return McpUnplacedTakeoffSummaryDto(
            status=_summary_status_for_meta(meta),
            database_id=database_id,
            bid_uid=bid_uid,
            meta=meta,
            takeoffs=[
                self._takeoff_dto(takeoff, bid_data, include_geometry=False)
                for takeoff in limited
            ],
        )

    def get_page_context(
        self,
        database_id: str,
        bid_uid: str,
        page_uid: str,
    ) -> McpPageContextDto:
        bid_data = self._load_bid(database_id, bid_uid)
        page = bid_data.pages.get(page_uid)
        if page is None:
            raise McpReadError(f"Unknown page_uid: {page_uid}")
        image_path = page.image_path or ""
        page_dto = self._page_dto(page)
        return McpPageContextDto(
            status=MCP_STATUS_OK,
            database_id=database_id,
            bid_uid=bid_uid,
            page=page_dto,
            page_label=page.name,
            sheet_name=page.name,
            source_file_name=self._safe_basename(image_path) if image_path else "",
            has_pdf_source=page_dto.is_pdf,
            has_overlay=bool(page.overlay_image_path),
            page_text_status=MCP_STATUS_DEFERRED,
        )

    def list_layers(
        self,
        database_id: str,
        bid_uid: str,
        limit: int = 500,
    ) -> List[McpLayerDto]:
        bid_data = self._load_bid(database_id, bid_uid)
        condition_counts: Dict[str, int] = defaultdict(int)
        takeoff_counts: Dict[str, int] = defaultdict(int)
        annotation_counts: Dict[str, int] = defaultdict(int)
        for condition in bid_data.bid_conditions.values():
            if condition.layer_uid:
                condition_counts[condition.layer_uid] += 1
        for takeoff in bid_data.bid_takeoffs:
            condition = bid_data.bid_conditions.get(takeoff.condition_uid)
            if condition and condition.layer_uid:
                takeoff_counts[condition.layer_uid] += 1
        for annotation in bid_data.bid_annotations:
            if annotation.layer_uid:
                annotation_counts[annotation.layer_uid] += 1
        layers = [
            McpLayerDto(
                uid=layer.uid,
                name=layer.name,
                visible=layer.show,
                sequence=layer.sequence,
                is_template=layer.is_template,
                is_locked=layer.is_locked,
                condition_count=condition_counts.get(layer.uid, 0),
                takeoff_count=takeoff_counts.get(layer.uid, 0),
                annotation_count=annotation_counts.get(layer.uid, 0),
            )
            for layer in sorted(
                bid_data.bid_layers,
                key=lambda item: (item.sequence, item.name.lower(), item.uid),
            )
        ]
        return self._limited_list(layers, limit)

    def list_named_views(
        self,
        database_id: str,
        bid_uid: str,
        page_uid: Optional[str] = None,
        limit: int = 250,
    ) -> List[McpNamedViewDto]:
        bid_data = self._load_bid(database_id, bid_uid)
        self._validate_optional_page_uid(bid_data, page_uid)
        views = []
        for named_view in self._named_views(bid_data):
            if page_uid and named_view.bid_page_uid != page_uid:
                continue
            page = bid_data.pages.get(named_view.bid_page_uid)
            views.append(self._named_view_dto(named_view, page))
        return self._limited_list(views, limit, default=250)

    def list_hotlinks(
        self,
        database_id: str,
        bid_uid: str,
        page_uid: Optional[str] = None,
        limit: int = 250,
    ) -> List[McpHotlinkDto]:
        bid_data = self._load_bid(database_id, bid_uid)
        self._validate_optional_page_uid(bid_data, page_uid)
        named_views = {view.uid: view for view in self._named_views(bid_data)}
        hotlinks = []
        for annotation in bid_data.bid_annotations:
            hotlink = build_hotlink_from_annotation(annotation)
            if hotlink is None:
                continue
            if page_uid and hotlink.bid_page_uid != page_uid:
                continue
            source_page = bid_data.pages.get(hotlink.bid_page_uid)
            target = (
                named_views.get(str(hotlink.target_view_uid))
                if hotlink.target_view_uid
                else None
            )
            target_page = (
                bid_data.pages.get(target.bid_page_uid) if target is not None else None
            )
            hotlinks.append(
                McpHotlinkDto(
                    uid=hotlink.uid,
                    page_uid=hotlink.bid_page_uid,
                    page_name=source_page.name if source_page else "",
                    layer_uid=hotlink.bid_layer_uid,
                    visible=annotation.visible,
                    target_named_view_uid=target.uid if target is not None else None,
                    target_named_view_name=target.name if target is not None else "",
                    target_page_uid=target.bid_page_uid if target is not None else None,
                    target_page_name=target_page.name if target_page else "",
                )
            )
        return self._limited_list(hotlinks, limit, default=250)

    def search_takeoffs(
        self,
        database_id: str,
        bid_uid: str,
        query: str,
        page_uid: Optional[str] = None,
        condition_uid: Optional[str] = None,
        limit: int = 50,
    ) -> List[McpTakeoffDto]:
        query_text = str(query or "").strip().lower()
        if not query_text:
            return []
        bid_data = self._load_bid(database_id, bid_uid)
        matches = []
        for takeoff in self._filter_takeoffs(
            bid_data,
            page_uid=page_uid,
            condition_uid=condition_uid,
            visible_only=True,
        ):
            condition = bid_data.bid_conditions.get(takeoff.condition_uid)
            page = bid_data.pages.get(takeoff.page_uid)
            area_name = self._area_name(takeoff.area_uid, bid_data)
            haystack = " ".join(
                [
                    takeoff.uid,
                    takeoff.condition_uid,
                    condition.name if condition else "",
                    page.name if page else "",
                    takeoff.page_uid,
                    takeoff.area_uid,
                    area_name or "",
                ]
            ).lower()
            if query_text in haystack:
                matches.append(
                    self._takeoff_dto(takeoff, bid_data, include_geometry=False)
                )
        return self._limited_list(matches, limit, default=50)

    def find_pages_without_takeoffs(
        self,
        database_id: str,
        bid_uid: str,
        limit: int = 500,
    ) -> List[McpPageDto]:
        bid_data = self._load_bid(database_id, bid_uid)
        return self._limited_list(self._pages_without_takeoffs(bid_data), limit)

    def find_conditions_without_takeoffs(
        self,
        database_id: str,
        bid_uid: str,
        limit: int = 500,
    ) -> List[McpConditionDto]:
        bid_data = self._load_bid(database_id, bid_uid)
        return self._limited_list(self._conditions_without_takeoffs(bid_data), limit)

    def _pages_without_takeoffs(self, bid_data: BidLoadResult) -> List[McpPageDto]:
        pages_with_takeoffs = {t.page_uid for t in bid_data.bid_takeoffs}
        return [
            self._page_dto(page)
            for page in self._ordered_pages(bid_data)
            if page.uid not in pages_with_takeoffs
        ]

    def _conditions_without_takeoffs(
        self,
        bid_data: BidLoadResult,
    ) -> List[McpConditionDto]:
        used_condition_uids = {t.condition_uid for t in bid_data.bid_takeoffs}
        return [
            self._condition_dto(condition)
            for condition in self._ordered_conditions(bid_data)
            if condition.uid not in used_condition_uids
        ]

    def _summary_node_count(self, root: ConditionSummaryNode) -> int:
        return sum(self._summary_subtree_count(child) for child in root.children)

    def _summary_subtree_count(self, node: ConditionSummaryNode) -> int:
        return 1 + sum(self._summary_subtree_count(child) for child in node.children)

    def _summary_node_dto_limited(
        self,
        node: ConditionSummaryNode,
        remaining: int,
        folder_path: List[str],
        groups: Dict[str, str],
    ) -> Tuple[Optional[McpSummaryNodeDto], int]:
        if remaining <= 0:
            return None, 0
        node_folder_path = list(folder_path)
        child_folder_path = node_folder_path
        if node.kind == SUMMARY_NODE_FOLDER:
            node_folder_path = [*folder_path, node.label]
            child_folder_path = node_folder_path
        node_groups = dict(groups)
        child_groups = node_groups
        if node.kind == SUMMARY_NODE_GROUP:
            node_groups[node.group_level] = node.label
            child_groups = node_groups
        dto = McpSummaryNodeDto(
            kind=node.kind,
            label=node.label,
            condition_uid=node.condition_uid,
            folder_uid=node.folder_uid,
            group_level=node.group_level,
            folder_path=node_folder_path,
            page=node_groups.get(SUMMARY_GROUP_PAGE, ""),
            type_name=(
                node_groups.get(SUMMARY_GROUP_TYPE, "") or node.values.type_name
            ),
            area=node_groups.get(SUMMARY_GROUP_AREA, "") or node.values.area,
            values=self._summary_values_dto(node.values),
            child_count=len(node.children),
            copyable=node.copyable,
            deletable=node.deletable,
            layer_visible=node.layer_visible,
            color_fill=node.color_fill,
            pattern=node.pattern,
        )
        consumed = 1
        child_remaining = remaining - consumed
        for child in node.children:
            if child_remaining <= 0:
                break
            child_dto, child_consumed = self._summary_node_dto_limited(
                child,
                child_remaining,
                child_folder_path,
                child_groups,
            )
            if child_dto is not None:
                dto.children.append(child_dto)
            consumed += child_consumed
            child_remaining -= child_consumed
        return dto, consumed

    @staticmethod
    def _summary_values_dto(values: ConditionSummaryValues) -> McpSummaryValuesDto:
        return McpSummaryValuesDto(
            number=values.number,
            name=values.name,
            type_name=values.type_name,
            height=values.height,
            height_inches=values.height_inches,
            area=values.area,
            quantity1=values.quantity1,
            uom1=values.uom1,
            uom1_label=get_uom_label(values.uom1),
            quantity2=values.quantity2,
            uom2=values.uom2,
            uom2_label=get_uom_label(values.uom2),
            quantity3=values.quantity3,
            uom3=values.uom3,
            uom3_label=get_uom_label(values.uom3),
            notes=values.notes,
        )

    def _load_file(self, db: McpDatabaseRef) -> FileLoadResult:
        result = self._repository.load_file(db.file_path)
        if not result.success:
            raise McpReadError(result.error_message or "Failed to load database")
        return result

    def _load_bid(self, database_id: str, bid_uid: str) -> BidLoadResult:
        db = self.get_database(database_id)
        self._load_file(db)
        bid_data = self._repository.load_bid(str(bid_uid or ""), db.file_path)
        if (
            not bid_data.bid_conditions
            and not bid_data.pages
            and not bid_data.bid_takeoffs
        ):
            entry = self._get_file_entry(database_id)
            self._find_bid(entry, bid_uid)
        return bid_data

    def _get_file_entry(self, database_id: str) -> HierarchyFileEntry:
        db = self.get_database(database_id)
        result = self._load_file(db)
        entry = self._find_file_entry(result.hierarchy, db.file_path)
        if entry is None:
            raise McpReadError("Database hierarchy is unavailable")
        return entry

    @staticmethod
    def _find_file_entry(
        hierarchy: HierarchyData, file_path: str
    ) -> Optional[HierarchyFileEntry]:
        target = McpReadService._normalize_path(file_path)
        for entry in hierarchy.loaded_files:
            if McpReadService._normalize_path(str(entry.file_path)) == target:
                return entry
        return None

    @staticmethod
    def _normalize_path(file_path: str) -> str:
        return str(Path(file_path).expanduser().resolve()).casefold()

    @staticmethod
    def _project_dto(uid: str, project: HierarchyProjectInfo) -> McpProjectDto:
        return McpProjectDto(
            uid=uid,
            name=project.name,
            description=project.description,
            bid_count=len(project.bids),
        )

    def _bid_dto(
        self,
        bid: HierarchyBidInfo,
        project_uid: Optional[str],
        project_name: Optional[str],
    ) -> McpBidDto:
        return McpBidDto(
            uid=bid.uid,
            name=bid.name,
            project_uid=project_uid,
            project_name=project_name,
            bid_no=bid.bid_no,
            job_id=bid.job_id,
            status=bid.status,
            estimator=bid.estimator,
            page_count=bid.page_count,
            condition_count=bid.condition_count,
        )

    @staticmethod
    def _find_bid(
        entry: HierarchyFileEntry, bid_uid: str
    ) -> Tuple[HierarchyBidInfo, Optional[str], Optional[str]]:
        for project_uid, project in entry.bid_projects.items():
            for bid in project.bids:
                if bid.uid == bid_uid:
                    return bid, project_uid, project.name
        for bid in entry.orphan_bids:
            if bid.uid == bid_uid:
                return bid, None, None
        raise McpReadError(f"Unknown bid_uid: {bid_uid}")

    def _ordered_pages(self, bid_data: BidLoadResult) -> List[Page]:
        if not bid_data.pages:
            return []
        return sorted(
            bid_data.pages.values(),
            key=lambda page: (page.page_index, page.name.lower(), page.uid),
        )

    def _ordered_conditions(self, bid_data: BidLoadResult) -> List[Condition]:
        return sorted(
            bid_data.bid_conditions.values(),
            key=lambda condition: (
                condition.ref_no,
                condition.name.lower(),
                condition.uid,
            ),
        )

    def _ordered_areas(self, bid_data: BidLoadResult) -> List[BidArea]:
        return sorted(
            bid_data.bid_areas.values(),
            key=lambda area: (
                area.sequence,
                area.name.lower(),
                area.uid,
            ),
        )

    def _page_dto(self, page: Page, include_pdf_metadata: bool = False) -> McpPageDto:
        image_path = page.image_path or ""
        overlay_path = page.overlay_image_path or ""
        dto = McpPageDto(
            uid=page.uid,
            name=page.name,
            sheet_no=page.sheet_no,
            sequence=page.sequence,
            folder_uid=page.folder_uid,
            image_basename=self._safe_basename(image_path) if image_path else None,
            image_path_status=(
                MCP_STATUS_CONFIGURED if image_path else MCP_STATUS_NOT_CONFIGURED
            ),
            is_pdf=bool(image_path and is_pdf_suffix(image_path)),
            page_index=page.page_index,
            width_pts=page.width_pts,
            height_pts=page.height_pts,
            scale_factor1=page.scale_factor1,
            scale_factor2=page.scale_factor2,
            rotation=page.rotation,
            layer_visible=page.layer_visible,
            overlay_basename=(
                self._safe_basename(overlay_path) if overlay_path else None
            ),
            overlay_path_status=(
                MCP_STATUS_CONFIGURED if overlay_path else MCP_STATUS_NOT_CONFIGURED
            ),
            has_overlay=bool(overlay_path),
            source_kind=self._page_source_kind(page),
            page_width=page.width_pts,
            page_height=page.height_pts,
            overlay_kind=self._overlay_kind(page),
            overlay_transform_summary=self._overlay_transform_summary(page),
            takeoff_count=len(page.takeoffs),
        )
        if include_pdf_metadata:
            self._enrich_page_pdf_metadata(dto, page)
        return dto

    @staticmethod
    def _page_source_kind(page: Page) -> str:
        has_main = bool(page.image_path)
        has_overlay = bool(page.overlay_image_path)
        if has_main and has_overlay:
            return MCP_PAGE_SOURCE_COMPOSITE
        if has_main:
            return MCP_PAGE_SOURCE_MAIN
        if has_overlay:
            return MCP_PAGE_SOURCE_OVERLAY
        return MCP_PAGE_SOURCE_BLANK

    @staticmethod
    def _overlay_kind(page: Page) -> str:
        overlay_path = page.overlay_image_path or ""
        if not overlay_path:
            return MCP_STATUS_NOT_CONFIGURED
        return (
            MCP_OVERLAY_KIND_PDF
            if is_pdf_suffix(overlay_path)
            else MCP_OVERLAY_KIND_RASTER
        )

    @staticmethod
    def _overlay_transform_summary(page: Page) -> Optional[McpPdfOverlayTransformDto]:
        if not page.overlay_image_path:
            return None
        rect_x, rect_y, rect_w, rect_h = page.overlay_rect
        scale = 0.0
        if rect_w > 0 and page.width_pts > 0:
            scale = rect_w / page.width_pts
        return McpPdfOverlayTransformDto(
            offset_x=page.overlay_offset_x,
            offset_y=page.overlay_offset_y,
            rotation=page.overlay_rotation + page.deskew_rotation_overlay,
            deskew_rotation=page.deskew_rotation_overlay,
            scale=scale,
            rect_x=rect_x,
            rect_y=rect_y,
            rect_width=rect_w,
            rect_height=rect_h,
            resized=page.overlay_resized,
        )

    @staticmethod
    def _image_show_flags(mode: int) -> Tuple[bool, bool]:
        show_original = mode in (0, 2)
        show_overlay = mode in (1, 2)
        return show_original, show_overlay

    def _enrich_page_pdf_metadata(self, dto: McpPageDto, page: Page) -> None:
        source_ref = self._resolve_pdf_source(page, MCP_PDF_SOURCE_AUTO)
        if source_ref[2] != MCP_STATUS_CONFIGURED:
            dto.pdf_metadata_status = source_ref[2]
            return
        page_info = self._read_pdf_page_info(source_ref[1], source_ref[3])
        dto.pdf_metadata_status = page_info.status
        dto.pdf_page_count = page_info.page_count
        if page_info.status == MCP_STATUS_OK:
            dto.page_width = page_info.effective_width_pts
            dto.page_height = page_info.effective_height_pts
            dto.media_width_pts = page_info.media_width_pts
            dto.media_height_pts = page_info.media_height_pts
            dto.crop_width_pts = page_info.crop_width_pts
            dto.crop_height_pts = page_info.crop_height_pts
            dto.intrinsic_rotation = page_info.intrinsic_rotation
        text_runs = self._read_pdf_text_runs(source_ref[1], source_ref[3])
        vector_segments = self._read_pdf_vector_segments(source_ref[1], source_ref[3])
        dto.has_embedded_text = bool(text_runs)
        dto.text_run_count = len(text_runs)
        dto.character_count = sum(len(run.text or "") for run in text_runs)
        dto.snap_line_count = len(vector_segments)
        dto.snap_point_count = self._pdf_snap_point_count(vector_segments)

    def _resolve_pdf_source(self, page: Page, source: str) -> Tuple[str, str, str, int]:
        clean_source = str(source or MCP_PDF_SOURCE_AUTO).strip().lower()
        if clean_source not in MCP_PDF_SOURCES:
            raise McpReadError(f"Unknown PDF source: {source}")
        if clean_source == MCP_PDF_SOURCE_MAIN:
            return self._pdf_source_tuple(
                MCP_PDF_SOURCE_MAIN, page.image_path or "", page.page_index
            )
        if clean_source == MCP_PDF_SOURCE_OVERLAY:
            return self._pdf_source_tuple(
                MCP_PDF_SOURCE_OVERLAY, page.overlay_image_path or "", 0
            )
        main = self._pdf_source_tuple(
            MCP_PDF_SOURCE_MAIN, page.image_path or "", page.page_index
        )
        if main[2] == MCP_STATUS_CONFIGURED:
            return main
        overlay = self._pdf_source_tuple(
            MCP_PDF_SOURCE_OVERLAY, page.overlay_image_path or "", 0
        )
        if overlay[2] == MCP_STATUS_CONFIGURED:
            return overlay
        return main if main[2] != MCP_STATUS_NOT_CONFIGURED else overlay

    @staticmethod
    def _pdf_source_tuple(
        source: str, file_path: str, page_index: int
    ) -> Tuple[str, str, str, int]:
        if not file_path:
            return (source, "", MCP_STATUS_NOT_CONFIGURED, int(page_index or 0))
        if not is_pdf_suffix(file_path):
            return (source, file_path, MCP_STATUS_NOT_PDF, int(page_index or 0))
        return (source, file_path, MCP_STATUS_CONFIGURED, int(page_index or 0))

    def _read_pdf_page_info(self, file_path: str, page_index: int):
        if self._pdf_metadata_provider is None:
            return PdfPageInfoDto(status=MCP_STATUS_UNAVAILABLE)
        return self._pdf_metadata_provider.get_page_info(file_path, page_index)

    def _read_pdf_text_runs(
        self, file_path: str, page_index: int
    ) -> List[PdfTextRunDto]:
        if self._pdf_metadata_provider is None:
            return []
        return self._pdf_metadata_provider.get_text_runs(file_path, page_index)

    def _read_pdf_vector_segments(
        self, file_path: str, page_index: int
    ) -> List[PdfVectorSegmentDto]:
        if self._pdf_metadata_provider is None:
            return []
        return self._pdf_metadata_provider.get_vector_segments(file_path, page_index)

    @staticmethod
    def _pdf_text_run_dto(
        run: PdfTextRunDto, include_text: bool = False
    ) -> McpPdfTextRunDto:
        text = run.text or ""
        return McpPdfTextRunDto(
            snippet=McpReadService._snippet(text),
            text=text[:500] if include_text else None,
            left=run.left,
            top=run.top,
            right=run.right,
            bottom=run.bottom,
            character_count=len(text),
        )

    @staticmethod
    def _snippet(text: str, max_chars: int = 80) -> str:
        clean = " ".join(str(text or "").split())
        if len(clean) <= max_chars:
            return clean
        return clean[: max_chars - 3].rstrip() + "..."

    @staticmethod
    def _snippet_around_query(text: str, query: str, max_chars: int = 120) -> str:
        clean_text = " ".join(str(text or "").split())
        clean_query = " ".join(str(query or "").split())
        if not clean_text or not clean_query:
            return McpReadService._snippet(clean_text, max_chars=max_chars)
        match_index = clean_text.lower().find(clean_query.lower())
        if match_index < 0 or len(clean_text) <= max_chars:
            return McpReadService._snippet(clean_text, max_chars=max_chars)
        start = max(0, match_index - max_chars // 3)
        end = min(len(clean_text), start + max_chars)
        start = max(0, end - max_chars)
        snippet = clean_text[start:end].strip()
        if start > 0:
            snippet = "..." + snippet.lstrip()
        if end < len(clean_text):
            snippet = snippet.rstrip() + "..."
        return snippet

    @staticmethod
    def _pdf_text_search_match_dto(
        page: Page,
        source: str,
        run: PdfTextRunDto,
        query: str,
    ) -> McpPdfTextSearchMatchDto:
        text = run.text or ""
        return McpPdfTextSearchMatchDto(
            page_uid=page.uid,
            page_name=page.name,
            sheet_no=page.sheet_no,
            source=source,
            snippet=McpReadService._snippet_around_query(text, query),
            left=run.left,
            top=run.top,
            right=run.right,
            bottom=run.bottom,
            character_count=len(text),
        )

    @staticmethod
    def _pdf_vector_segment_dto(
        segment: PdfVectorSegmentDto,
    ) -> McpPdfVectorSegmentDto:
        length = math.hypot(segment.x2 - segment.x1, segment.y2 - segment.y1)
        return McpPdfVectorSegmentDto(
            x1=segment.x1,
            y1=segment.y1,
            x2=segment.x2,
            y2=segment.y2,
            length=length,
            orientation=McpReadService._orientation_bucket(
                segment.x1, segment.y1, segment.x2, segment.y2
            ),
        )

    @staticmethod
    def _orientation_bucket(x1: float, y1: float, x2: float, y2: float) -> str:
        dx = x2 - x1
        dy = y2 - y1
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return "point"
        angle = abs(math.degrees(math.atan2(dy, dx))) % 180
        if angle <= 10 or angle >= 170:
            return "horizontal"
        if 80 <= angle <= 100:
            return "vertical"
        if 35 <= angle <= 55 or 125 <= angle <= 145:
            return "diagonal"
        return "other"

    @staticmethod
    def _pdf_snap_point_count(segments: List[PdfVectorSegmentDto]) -> int:
        points = set()
        for segment in segments:
            points.add((round(segment.x1, 3), round(segment.y1, 3)))
            points.add((round(segment.x2, 3), round(segment.y2, 3)))
        return len(points)

    @staticmethod
    def _markup_sample_dto(annotation: BidAnnotation) -> McpMarkupSampleDto:
        bbox = annotation.get_bbox_ost()
        bbox_left = bbox_top = bbox_right = bbox_bottom = None
        if bbox is not None:
            bbox_left, bbox_top, bbox_right, bbox_bottom = bbox
        length = None
        line = annotation.get_line_coords()
        if line is not None:
            x1, y1, x2, y2 = line
            length = math.hypot(x2 - x1, y2 - y1)
        text = ""
        if annotation.annotation_type in {
            ANNOTATION_TYPE_TEXT,
            ANNOTATION_TYPE_CALLOUT,
            ANNOTATION_TYPE_NAMED_VIEW,
        }:
            text = str(annotation.get_text_content() or "")
        linked_takeoff_count = 0
        if annotation.properties.get("BidTakeoffFromUID"):
            linked_takeoff_count += 1
        if annotation.properties.get("BidTakeoffToUID"):
            linked_takeoff_count += 1
        return McpMarkupSampleDto(
            uid=annotation.uid,
            annotation_type=annotation.annotation_type,
            layer_uid=annotation.layer_uid or None,
            visible=annotation.visible,
            color=annotation.color,
            width=annotation.width,
            point_count=McpReadService._annotation_point_count(annotation),
            bbox_left=bbox_left,
            bbox_top=bbox_top,
            bbox_right=bbox_right,
            bbox_bottom=bbox_bottom,
            length=length,
            text_snippet=McpReadService._snippet(text) if text else "",
            text_character_count=len(text),
            linked_takeoff_count=linked_takeoff_count,
        )

    @staticmethod
    def _annotation_point_count(annotation: BidAnnotation) -> int:
        if not annotation.position:
            return 0
        coordinate_count = len(annotation.position)
        if coordinate_count % 2 == 1:
            coordinate_count -= 1
        return max(0, coordinate_count // 2)

    @staticmethod
    def _condition_type_name(condition: Condition) -> str:
        if condition.is_linear:
            return "linear"
        if condition.is_area:
            return "area"
        if condition.is_count:
            return "count"
        if condition.is_attachment:
            return "attachment"
        return "unknown"

    def _condition_dto(self, condition: Condition) -> McpConditionDto:
        return McpConditionDto(
            uid=condition.uid,
            name=condition.name,
            condition_type=condition.condition_type,
            condition_type_name=self._condition_type_name(condition),
            ref_no=condition.ref_no,
            folder_uid=condition.folder_uid,
            layer_uid=condition.layer_uid,
            layer_visible=condition.layer_visible,
            cdn_type_uid=condition.cdn_type_uid,
            cdn_type_name=condition.cdn_type_name,
            uom1=condition.uom1,
            uom2=condition.uom2,
            uom3=condition.uom3,
            uom1_label=get_uom_label(condition.uom1),
            uom2_label=get_uom_label(condition.uom2),
            uom3_label=get_uom_label(condition.uom3),
            notes=condition.notes,
        )

    def _takeoff_dto(
        self,
        takeoff: Takeoff,
        bid_data: BidLoadResult,
        include_geometry: bool,
    ) -> McpTakeoffDto:
        condition = bid_data.bid_conditions.get(takeoff.condition_uid)
        page = bid_data.pages.get(takeoff.page_uid)
        return McpTakeoffDto(
            uid=takeoff.uid,
            condition_uid=takeoff.condition_uid,
            condition_name=condition.name if condition else "",
            page_uid=takeoff.page_uid,
            page_name=page.name if page else "",
            area_uid=takeoff.area_uid,
            area_name=self._area_name(takeoff.area_uid, bid_data),
            parent_uid=takeoff.parent_uid,
            is_hole=takeoff.is_hole,
            is_negative=takeoff.is_negative,
            visible=is_takeoff_visible(takeoff, bid_data.bid_conditions),
            rotation=takeoff.rotation,
            curve=takeoff.curve,
            point_count=len(takeoff.position) // 2,
            position=list(takeoff.position) if include_geometry else None,
        )

    def _area_dto(
        self,
        area: BidArea,
        counts: Dict[str, int],
        visible_counts: Dict[str, int],
        page_uids: Dict[str, Set[str]],
        child_uids: Dict[str, List[str]],
    ) -> McpAreaDto:
        return McpAreaDto(
            uid=area.uid,
            bid_uid=area.bid_uid,
            parent_uid=area.parent_uid,
            name=area.name,
            sequence=area.sequence,
            guid=area.guid,
            child_uids=child_uids.get(area.uid, []),
            takeoff_count=counts.get(area.uid, 0),
            visible_takeoff_count=visible_counts.get(area.uid, 0),
            page_count=len(page_uids.get(area.uid, set())),
        )

    def _area_name(
        self,
        area_uid: str,
        bid_data: BidLoadResult,
    ) -> Optional[str]:
        normalized_uid = self._normalize_area_uid(area_uid)
        if self._is_unassigned_area_uid(normalized_uid):
            return None
        area = bid_data.bid_areas.get(normalized_uid)
        return area.name if area else None

    @staticmethod
    def _normalize_area_uid(area_uid: str) -> str:
        return _normalize_area_uid(area_uid)

    @staticmethod
    def _is_unassigned_area_uid(area_uid: str) -> bool:
        return _is_unassigned_area_uid(area_uid)

    def _area_usage_maps(
        self, bid_data: BidLoadResult
    ) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, Set[str]]]:
        counts: Dict[str, int] = defaultdict(int)
        visible_counts: Dict[str, int] = defaultdict(int)
        page_uids: Dict[str, Set[str]] = defaultdict(set)
        for takeoff in bid_data.bid_takeoffs:
            area_uid = self._normalize_area_uid(takeoff.area_uid)
            counts[area_uid] += 1
            if takeoff.page_uid:
                page_uids[area_uid].add(takeoff.page_uid)
            if is_takeoff_visible(takeoff, bid_data.bid_conditions):
                visible_counts[area_uid] += 1
        return counts, visible_counts, page_uids

    def _area_child_uid_map(self, bid_data: BidLoadResult) -> Dict[str, List[str]]:
        children: Dict[str, List[str]] = {}
        for area in self._ordered_areas(bid_data):
            if area.parent_uid and area.parent_uid != "0":
                children.setdefault(area.parent_uid, []).append(area.uid)
        return children

    @staticmethod
    def _safe_basename(path: str) -> str:
        return str(path or "").replace("\\", "/").rstrip("/").split("/")[-1]

    @staticmethod
    def _validate_optional_page_uid(
        bid_data: BidLoadResult, page_uid: Optional[str]
    ) -> None:
        if page_uid and page_uid not in bid_data.pages:
            raise McpReadError(f"Unknown page_uid: {page_uid}")

    def _named_views(self, bid_data: BidLoadResult) -> List[NamedView]:
        views = []
        for annotation in bid_data.bid_annotations:
            view = build_named_view_from_annotation(annotation)
            if view is not None:
                views.append(view)
        return sorted(
            views,
            key=lambda item: (
                (
                    bid_data.pages.get(item.bid_page_uid).page_index
                    if item.bid_page_uid in bid_data.pages
                    else 0
                ),
                item.name.lower(),
                item.uid,
            ),
        )

    @staticmethod
    def _named_view_dto(named_view: NamedView, page: Optional[Page]) -> McpNamedViewDto:
        return McpNamedViewDto(
            uid=named_view.uid,
            page_uid=named_view.bid_page_uid,
            page_name=page.name if page else "",
            name=named_view.name,
            min_x=named_view.min_x,
            min_y=named_view.min_y,
            max_x=named_view.max_x,
            max_y=named_view.max_y,
            center_x=named_view.center_x,
            center_y=named_view.center_y,
            width=named_view.width,
            height=named_view.height,
        )

    def _condition_quantity_summary(
        self,
        condition: Condition,
        bid_data: BidLoadResult,
    ) -> McpConditionQuantitySummaryDto:
        takeoffs = [
            takeoff
            for takeoff in bid_data.bid_takeoffs
            if takeoff.condition_uid == condition.uid
        ]
        visible_takeoffs = [
            takeoff
            for takeoff in takeoffs
            if is_takeoff_visible(takeoff, bid_data.bid_conditions)
        ]
        quantities = compute_page_quantities(
            bid_data.bid_conditions,
            visible_takeoffs,
            only_condition_uids={condition.uid},
        )
        quantity_dtos = self._quantity_dtos(
            quantities,
            bid_data.bid_conditions,
            visible_takeoffs,
        )
        page_summaries = self._page_takeoff_summaries(takeoffs, bid_data)
        has_quantity = any(
            dto.quantity1 or dto.quantity2 or dto.quantity3 for dto in quantity_dtos
        )
        return McpConditionQuantitySummaryDto(
            condition=self._condition_dto(condition),
            quantities=quantity_dtos,
            pages=page_summaries,
            takeoff_count=len(takeoffs),
            visible_takeoff_count=len(visible_takeoffs),
            page_count=len(page_summaries),
            zero_quantity=bool(takeoffs and not has_quantity),
        )

    def _filter_takeoffs(
        self,
        bid_data: BidLoadResult,
        page_uid: Optional[str] = None,
        condition_uid: Optional[str] = None,
        visible_only: bool = True,
    ) -> List[Takeoff]:
        takeoffs = list(bid_data.bid_takeoffs)
        if page_uid:
            if page_uid not in bid_data.pages:
                raise McpReadError(f"Unknown page_uid: {page_uid}")
            takeoffs = [t for t in takeoffs if t.page_uid == page_uid]
        if condition_uid:
            if condition_uid not in bid_data.bid_conditions:
                raise McpReadError(f"Unknown condition_uid: {condition_uid}")
            takeoffs = [t for t in takeoffs if t.condition_uid == condition_uid]
        if visible_only:
            takeoffs = [
                t for t in takeoffs if is_takeoff_visible(t, bid_data.bid_conditions)
            ]
        return takeoffs

    def _quantity_dtos(
        self,
        quantities: Dict[str, Tuple[float, float, float]],
        conditions: Dict[str, Condition],
        takeoffs: List[Takeoff],
    ) -> List[McpQuantityDto]:
        counts: Dict[str, int] = {}
        for takeoff in takeoffs:
            if takeoff.is_hole:
                continue
            counts[takeoff.condition_uid] = counts.get(takeoff.condition_uid, 0) + 1
        result = []
        for condition_uid, values in quantities.items():
            condition = conditions.get(condition_uid)
            if condition is None:
                continue
            result.append(
                McpQuantityDto(
                    condition_uid=condition_uid,
                    condition_name=condition.name,
                    ref_no=condition.ref_no,
                    quantity1=values[0],
                    quantity2=values[1],
                    quantity3=values[2],
                    uom1=condition.uom1,
                    uom2=condition.uom2,
                    uom3=condition.uom3,
                    uom1_label=get_uom_label(condition.uom1),
                    uom2_label=get_uom_label(condition.uom2),
                    uom3_label=get_uom_label(condition.uom3),
                    takeoff_count=counts.get(condition_uid, 0),
                )
            )
        return sorted(
            result,
            key=lambda item: (
                item.ref_no,
                item.condition_name.lower(),
                item.condition_uid,
            ),
        )

    def _page_takeoff_summaries(
        self,
        takeoffs: List[Takeoff],
        bid_data: BidLoadResult,
    ) -> List[McpPageTakeoffSummaryDto]:
        counts: Dict[str, int] = {}
        visible_counts: Dict[str, int] = {}
        for takeoff in takeoffs:
            counts[takeoff.page_uid] = counts.get(takeoff.page_uid, 0) + 1
            if is_takeoff_visible(takeoff, bid_data.bid_conditions):
                visible_counts[takeoff.page_uid] = (
                    visible_counts.get(takeoff.page_uid, 0) + 1
                )
        result = []
        for page_uid, count in counts.items():
            page = bid_data.pages.get(page_uid)
            result.append(
                McpPageTakeoffSummaryDto(
                    page_uid=page_uid,
                    page_name=page.name if page else "",
                    takeoff_count=count,
                    visible_takeoff_count=visible_counts.get(page_uid, 0),
                )
            )
        return sorted(
            result,
            key=lambda item: (
                (
                    bid_data.pages.get(item.page_uid).page_index
                    if item.page_uid in bid_data.pages
                    else 0
                ),
                item.page_name.lower(),
                item.page_uid,
            ),
        )

    @staticmethod
    def _clean_limit(limit: int, default: int = 500, max_limit: int = 5000) -> int:
        return McpReadService._clean_limit_with_max(
            limit, default=default, max_limit=max_limit
        )

    @staticmethod
    def _clean_limit_with_max(
        limit: int, default: int = 500, max_limit: int = 5000
    ) -> int:
        try:
            value = int(limit)
        except (TypeError, ValueError):
            value = default
        return max(1, min(value, max_limit))

    def _limited(
        self,
        items: List,
        limit: int,
        default: int = 500,
        max_limit: int = 5000,
    ) -> Tuple[List, McpResultMetaDto]:
        clean_limit = self._clean_limit_with_max(
            limit, default=default, max_limit=max_limit
        )
        limited = items[:clean_limit]
        truncated = len(limited) < len(items)
        return limited, McpResultMetaDto(
            limit=clean_limit,
            returned_count=len(limited),
            total_count=len(items),
            truncated=truncated,
            has_more=truncated,
        )

    def _limited_list(
        self,
        items: List,
        limit: int,
        default: int = 500,
        max_limit: int = 5000,
    ) -> McpLimitedList:
        limited, meta = self._limited(
            items,
            limit,
            default=default,
            max_limit=max_limit,
        )
        return McpLimitedList(limited, meta)
