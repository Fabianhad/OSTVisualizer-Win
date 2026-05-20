from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple
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
    McpConditionDto,
    McpConditionSummaryDto,
    McpDatabaseDto,
    McpHierarchyDto,
    McpPageDto,
    McpPageTakeoffSummaryDto,
    McpProjectDto,
    McpQuantityDto,
    McpSelectedPagesSummaryDto,
    McpSelectedTakeoffsSummaryDto,
    McpTakeoffDto,
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
            haystack = " ".join(
                [
                    takeoff.uid,
                    takeoff.condition_uid,
                    condition.name if condition else "",
                    page.name if page else "",
                    takeoff.page_uid,
                    takeoff.area_uid,
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
    ) -> List[McpPageDto]:
        bid_data = self._load_bid(database_id, bid_uid)
        pages_with_takeoffs = {t.page_uid for t in bid_data.bid_takeoffs}
        return [
            self._page_dto(page)
            for page in self._ordered_pages(bid_data)
            if page.uid not in pages_with_takeoffs
        ]

    def find_conditions_without_takeoffs(
        self,
        database_id: str,
        bid_uid: str,
    ) -> List[McpConditionDto]:
        bid_data = self._load_bid(database_id, bid_uid)
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
        target = str(file_path).lower()
        for entry in hierarchy.loaded_files:
            if str(entry.file_path).lower() == target:
                return entry
        return hierarchy.loaded_files[0] if hierarchy.loaded_files else None

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

    def _page_dto(self, page: Page, folder_uid: Optional[str] = None) -> McpPageDto:
        image_path = page.image_path or None
        return McpPageDto(
            uid=page.uid,
            name=page.name,
            folder_uid=folder_uid or page.folder_uid,
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
            parent_uid=takeoff.parent_uid,
            is_hole=takeoff.is_hole,
            is_negative=takeoff.is_negative,
            visible=is_takeoff_visible(takeoff, bid_data.bid_conditions),
            rotation=takeoff.rotation,
            curve=takeoff.curve,
            point_count=len(takeoff.position) // 2,
            position=list(takeoff.position) if include_geometry else None,
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
