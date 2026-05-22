from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple
from ...domain.entities.area import BidArea
from ...domain.entities.condition import Condition
from ...domain.entities.file_results import BidLoadResult, FileLoadResult
from ...domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ...domain.entities.page import Page
from ...domain.entities.takeoff import Takeoff
from ...domain.repositories.i_project_repository import IProjectRepository
from ...domain.services.condition_quantity_service import compute_page_quantities
from ...domain.services.takeoff_domain_service import is_takeoff_visible
from ...domain.services.uom_service import get_uom_label
from ..dtos.mcp_context_dtos import (
    McpBidDto,
    McpBidQuantitySummaryDto,
    McpAreaDto,
    McpAreaSummaryDto,
    McpConditionDto,
    McpConditionQuantitySummaryDto,
    McpConditionSummaryDto,
    McpDatabaseDto,
    McpDuplicateConditionGroupDto,
    McpDuplicateConditionSummaryDto,
    McpHierarchyDto,
    McpPageContextDto,
    McpPageDto,
    McpPageTakeoffSummaryDto,
    McpProjectDto,
    McpQuantityDto,
    McpResultMetaDto,
    McpScopeGapSummaryDto,
    McpSelectedPagesSummaryDto,
    McpSelectedTakeoffsSummaryDto,
    McpTakeoffDto,
    McpUnplacedTakeoffSummaryDto,
    McpZeroQuantitySummaryDto,
)


class McpReadError(ValueError):
    pass


@dataclass
class McpDatabaseRef:
    database_id: str
    file_path: str
    display_name: str


class McpReadService:
    def __init__(
        self,
        project_repository: IProjectRepository,
        databases: Iterable[McpDatabaseRef],
    ):
        self._repository = project_repository
        self._databases: Dict[str, McpDatabaseRef] = {
            db.database_id: db for db in databases
        }

    def list_databases(self) -> List[McpDatabaseDto]:
        return [
            McpDatabaseDto(
                database_id=db.database_id,
                display_name=db.display_name,
                file_path=db.file_path,
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
                file_path=db.file_path,
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

    def list_pages(self, database_id: str, bid_uid: str) -> List[McpPageDto]:
        bid_data = self._load_bid(database_id, bid_uid)
        return [self._page_dto(page) for page in self._ordered_pages(bid_data)]

    def get_current_page(self, database_id: str, bid_uid: str) -> Optional[McpPageDto]:
        bid_data = self._load_bid(database_id, bid_uid)
        page_uid = bid_data.selected_page_uid
        if page_uid and page_uid in bid_data.pages:
            return self._page_dto(bid_data.pages[page_uid])
        pages = self._ordered_pages(bid_data)
        return self._page_dto(pages[0]) if pages else None

    def get_page_pdf_info(
        self, database_id: str, bid_uid: str, page_uid: str
    ) -> McpPageDto:
        bid_data = self._load_bid(database_id, bid_uid)
        page = bid_data.pages.get(page_uid)
        if page is None:
            raise McpReadError(f"Unknown page_uid: {page_uid}")
        return self._page_dto(page)

    def list_conditions(self, database_id: str, bid_uid: str) -> List[McpConditionDto]:
        bid_data = self._load_bid(database_id, bid_uid)
        return [
            self._condition_dto(condition)
            for condition in self._ordered_conditions(bid_data)
        ]

    def list_areas(
        self, database_id: str, bid_uid: str, limit: int = 500
    ) -> List[McpAreaDto]:
        bid_data = self._load_bid(database_id, bid_uid)
        counts, visible_counts, page_uids = self._area_usage_maps(bid_data)
        children = self._area_child_uid_map(bid_data)
        return [
            self._area_dto(area, counts, visible_counts, page_uids, children)
            for area in self._ordered_areas(bid_data)[: self._clean_limit(limit)]
        ]

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
            status=self._summary_status(meta),
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
        return matches[: self._clean_limit(limit, default=50)]

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
        clean_limit = self._clean_limit(limit)
        return [
            self._takeoff_dto(t, bid_data, include_geometry=include_geometry)
            for t in takeoffs[:clean_limit]
        ]

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
            status="ok",
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
            status="ok",
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
        return self._quantity_dtos(quantities, bid_data.bid_conditions, takeoffs)

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
            status=self._summary_status(meta),
            database_id=database_id,
            bid_uid=bid_uid,
            meta=meta,
            conditions=limited,
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
        meta = McpResultMetaDto(
            limit=clean_limit,
            returned_count=returned_count,
            total_count=total_count,
            truncated=returned_count < total_count,
        )
        return McpScopeGapSummaryDto(
            status=self._summary_status(meta),
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
            status=self._summary_status(meta),
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
            status=self._summary_status(meta),
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
            status=self._summary_status(meta),
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
            status="ok",
            database_id=database_id,
            bid_uid=bid_uid,
            page=page_dto,
            page_label=page.name,
            sheet_name=page.name,
            source_file_name=Path(image_path).name if image_path else "",
            has_pdf_source=page_dto.is_pdf,
            has_overlay=bool(page.overlay_image_path),
            page_text_status="deferred",
        )

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
        return matches[: self._clean_limit(limit, default=50)]

    def find_pages_without_takeoffs(
        self,
        database_id: str,
        bid_uid: str,
        limit: int = 500,
    ) -> List[McpPageDto]:
        bid_data = self._load_bid(database_id, bid_uid)
        return self._pages_without_takeoffs(bid_data)[: self._clean_limit(limit)]

    def find_conditions_without_takeoffs(
        self,
        database_id: str,
        bid_uid: str,
        limit: int = 500,
    ) -> List[McpConditionDto]:
        bid_data = self._load_bid(database_id, bid_uid)
        return self._conditions_without_takeoffs(bid_data)[: self._clean_limit(limit)]

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

    def _page_dto(self, page: Page) -> McpPageDto:
        image_path = page.image_path or None
        return McpPageDto(
            uid=page.uid,
            name=page.name,
            folder_uid=page.folder_uid,
            image_path=image_path,
            is_pdf=bool(image_path and image_path.lower().endswith(".pdf")),
            page_index=page.page_index,
            width_pts=page.width_pts,
            height_pts=page.height_pts,
            scale_factor1=page.scale_factor1,
            scale_factor2=page.scale_factor2,
            rotation=page.rotation,
            layer_visible=page.layer_visible,
            overlay_image_path=page.overlay_image_path,
            takeoff_count=len(page.takeoffs),
        )

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
        return str(area_uid or "0")

    @staticmethod
    def _is_unassigned_area_uid(area_uid: str) -> bool:
        return str(area_uid or "").strip() in {"", "0"}

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
    def _clean_limit(limit: int, default: int = 500) -> int:
        try:
            value = int(limit)
        except (TypeError, ValueError):
            value = default
        return max(1, min(value, 5000))

    def _limited(
        self,
        items: List,
        limit: int,
        default: int = 500,
    ) -> Tuple[List, McpResultMetaDto]:
        clean_limit = self._clean_limit(limit, default=default)
        limited = items[:clean_limit]
        return limited, McpResultMetaDto(
            limit=clean_limit,
            returned_count=len(limited),
            total_count=len(items),
            truncated=len(limited) < len(items),
        )

    @staticmethod
    def _summary_status(meta: McpResultMetaDto) -> str:
        if meta.truncated:
            return "truncated"
        if meta.total_count == 0:
            return "empty"
        return "ok"
