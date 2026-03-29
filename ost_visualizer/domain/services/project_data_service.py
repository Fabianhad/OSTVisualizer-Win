import logging
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple
from ...domain.aggregates.ost_aggregate import OstAggregate
from ...domain.entities.bid import Bid
from ...domain.entities.condition import Condition
from ...domain.entities.hierarchy_data import HierarchyData
from ...domain.entities.identity_refs import BidRef
from ...domain.entities.page import Page
from ...domain.entities.project_factory import build_bid
from ...domain.entities.takeoff import Takeoff
from ..entities.annotation import BidAnnotation
from ..entities.condition_folder import BidConditionFolder
from .condition_quantity_service import compute_page_quantities
from .takeoff_domain_service import is_takeoff_visible


@dataclass
class CollectedTakeoffsResult:
    takeoffs: List[Takeoff] = field(default_factory=list)
    valid_page_uids: List[str] = field(default_factory=list)
    page_count: int = 0
    total_takeoffs: int = 0

    def __post_init__(self) -> None:
        if self.page_count == 0:
            self.page_count = len(self.valid_page_uids)
        if self.total_takeoffs == 0:
            self.total_takeoffs = len(self.takeoffs)

    def is_empty(self) -> bool:
        return not self.takeoffs


class ProjectDataService:
    def __init__(self, model: OstAggregate, logger: Optional[logging.Logger] = None):
        self.model = model
        self.logger = logger or logging.getLogger(__name__)

    def reset(self) -> None:
        self.model.clear_bid()
        self.model.cdn_types = {}
        self.model.projects = []
        self.model.set_hierarchy(HierarchyData())

    def has_loaded_files(self) -> bool:
        return bool(self.model.get_hierarchy_data().loaded_files)

    def has_takeoffs_for_pages(self, page_uids: Iterable[str]) -> bool:
        return self.model.has_takeoffs_for_pages(page_uids)

    def collect_takeoffs_for_pages(
        self, page_uids: List[str]
    ) -> CollectedTakeoffsResult:
        all_takeoffs: List[Takeoff] = []
        valid_pages: List[str] = []
        bid_conditions = self.model.bid_conditions
        for page_uid in page_uids:
            takeoffs = self.model.get_page_takeoffs(page_uid)
            if takeoffs:
                visible_takeoffs = [
                    t for t in takeoffs if is_takeoff_visible(t, bid_conditions)
                ]
                if visible_takeoffs:
                    all_takeoffs.extend(visible_takeoffs)
                    valid_pages.append(page_uid)
        return CollectedTakeoffsResult(
            takeoffs=all_takeoffs, valid_page_uids=valid_pages
        )

    def get_selected_page_uids(self) -> List[str]:
        return self.model.get_selected_pages()

    def get_current_bid(self) -> Optional[Bid]:
        return self.model.current_bid

    def get_hierarchy(self) -> HierarchyData:
        return self.model.get_hierarchy_data()

    def get_current_file_path(self) -> Optional[str]:
        return self.model.get_current_file_path()

    def clear_page_selection(self) -> None:
        self.model.clear_page_selection()

    def deselect_pages(self) -> None:
        self.model.deselect_pages()

    def select_pages(self, page_uids: List[str]) -> List[str]:
        return self.model.select_pages(page_uids)

    def get_page(self, page_uid: str) -> Optional[Page]:
        return self.model.get_page(page_uid)

    def get_bid(self, bid_ref: BidRef) -> Optional[Bid]:
        if self.model.current_bid_ref == bid_ref and self.model.current_bid:
            return self.model.current_bid
        bid_info = self.model.find_bid_info(bid_ref)
        if not bid_info:
            return None
        return build_bid(bid_info)

    def get_bid_conditions(self) -> Dict[str, Condition]:
        return self.model.bid_conditions

    def get_page_takeoffs(self, page_uid: str) -> List[Takeoff]:
        return self.model.get_page_takeoffs(page_uid)

    def get_takeoff_extras(self, takeoff_uid: str) -> Dict[str, object]:
        return self.model.get_takeoff_extras(takeoff_uid)

    def get_page_annotations(self, page_uid: str) -> List[BidAnnotation]:
        return self.model.get_page_annotations(page_uid)

    def get_page_area_selections(self) -> Dict[str, Optional[str]]:
        return self.model.page_area_selections

    def set_current_file(self, file_path: str) -> None:
        self.model.set_current_file_path(file_path)

    def get_page_name(self, page_uid: str) -> str:
        return self.model.get_page_name(page_uid)

    def get_all_annotations(self) -> List[BidAnnotation]:
        return self.model.get_all_annotations()

    def find_hotlinks_targeting(
        self, namedview_uids: Iterable[str]
    ) -> List[BidAnnotation]:
        target_uids = {str(uid) for uid in namedview_uids if uid}
        if not target_uids:
            return []
        return [
            a
            for a in self.model.get_all_annotations()
            if a.is_hotlink and a.hotlink_target_view_uid in target_uids
        ]

    def get_current_bid_ref(self) -> Optional[BidRef]:
        return self.model.current_bid_ref

    def get_current_bid_file_path(self) -> Optional[str]:
        return self.model.current_bid_file_path

    def get_all_selected_takeoffs(self) -> List[Takeoff]:
        return self.model.get_all_selected_takeoffs()

    def is_current_bid_locked(self) -> bool:
        return self.model.current_bid_locked

    def set_current_bid_locked(self, locked: bool) -> None:
        self.model.current_bid_locked = locked

    def get_last_selected_page_uid(self) -> Optional[str]:
        return self.model.last_selected_page_uid

    def get_all_takeoffs(self) -> List[Takeoff]:
        return self.model.get_all_takeoffs()

    def add_takeoffs(self, takeoffs: List[Takeoff]) -> None:
        if not takeoffs:
            return
        self.model.bid_takeoffs.extend(takeoffs)
        for takeoff in takeoffs:
            page = self.model.get_page(takeoff.page_uid)
            if page is not None:
                page.takeoffs.append(takeoff)

    def get_page_uids_for_takeoffs(self, takeoff_uids: Iterable[str]) -> List[str]:
        wanted = {str(uid) for uid in takeoff_uids if uid}
        if not wanted:
            return []
        page_uids = []
        seen = set()
        for takeoff in self.model.get_all_takeoffs():
            if takeoff.uid in wanted and takeoff.page_uid not in seen:
                page_uids.append(takeoff.page_uid)
                seen.add(takeoff.page_uid)
        return page_uids

    def update_takeoff_positions(
        self, positions: Iterable[Tuple[str, List[float]]]
    ) -> List[str]:
        changes = [(str(uid), list(position)) for uid, position in positions]
        page_uids = self.get_page_uids_for_takeoffs(uid for uid, _ in changes)
        by_uid = {uid: position for uid, position in changes}
        for takeoff in self.model.get_all_takeoffs():
            position = by_uid.get(takeoff.uid)
            if position is not None:
                takeoff.position = position
        return page_uids

    def update_takeoff_rotations(
        self, rotations: Iterable[Tuple[str, float]]
    ) -> List[str]:
        changes = [(str(uid), rotation) for uid, rotation in rotations]
        page_uids = self.get_page_uids_for_takeoffs(uid for uid, _ in changes)
        by_uid = {uid: rotation for uid, rotation in changes}
        for takeoff in self.model.get_all_takeoffs():
            if takeoff.uid in by_uid:
                takeoff.rotation = by_uid[takeoff.uid]
        return page_uids

    def remove_takeoffs(self, takeoff_uids: Iterable[str]) -> List[str]:
        wanted = {str(uid) for uid in takeoff_uids if uid}
        if not wanted:
            return []
        page_uids = self.get_page_uids_for_takeoffs(wanted)
        self.model.bid_takeoffs = [
            takeoff for takeoff in self.model.bid_takeoffs if takeoff.uid not in wanted
        ]
        for page_uid in page_uids:
            page = self.model.get_page(page_uid)
            if page is not None:
                page.takeoffs = [
                    takeoff for takeoff in page.takeoffs if takeoff.uid not in wanted
                ]
        return page_uids

    def get_takeoff(self, uid: str) -> Optional[Takeoff]:
        for t in self.model.get_all_takeoffs():
            if t.uid == uid:
                return t
        return None

    def get_condition(self, uid: str) -> Optional[Condition]:
        return self.model.bid_conditions.get(uid)

    def get_area_uids_with_takeoff(self) -> set:
        return {t.area_uid or "0" for t in self.model.get_all_takeoffs()}

    def get_area_uids_with_takeoff_for_page(self, page_uid: str) -> set:
        page = self.model.get_page(page_uid)
        if not page:
            return set()
        return {t.area_uid or "0" for t in page.takeoffs}

    def get_bid_condition_folders(self) -> Dict[str, BidConditionFolder]:
        return self.model.bid_condition_folders

    def get_cdn_types(self) -> dict:
        return self.model.cdn_types

    def find_project_uid_for_bid(self, bid_ref: BidRef) -> Optional[str]:
        hierarchy = self.model.get_hierarchy_data()
        for file_entry in hierarchy.loaded_files:
            if file_entry.file_path != bid_ref.file_path:
                continue
            for project_uid, project_info in file_entry.bid_projects.items():
                if any(b.uid == bid_ref.bid_uid for b in project_info.bids):
                    return project_uid
        return None

    def compute_quantities_for_pages(
        self, page_uids: List[str]
    ) -> Dict[str, Tuple[float, float, float]]:
        conditions = self.model.bid_conditions
        all_takeoffs: List[Takeoff] = []
        for uid in page_uids:
            all_takeoffs.extend(self.model.get_page_takeoffs(uid))
        return compute_page_quantities(conditions, all_takeoffs)

    def project_has_bids(self, project_uid: str) -> bool:
        hierarchy = self.model.get_hierarchy_data()
        for file_entry in hierarchy.loaded_files:
            project_info = file_entry.bid_projects.get(project_uid)
            if project_info is not None:
                return len(project_info.bids) > 0
        return False
