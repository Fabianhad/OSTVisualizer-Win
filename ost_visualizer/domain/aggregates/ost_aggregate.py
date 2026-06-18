import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple
from ..entities.annotation import BidAnnotation
from ..entities.bid import Bid
from ..entities.cdn_type import CdnType
from ..entities.condition import Condition
from ..entities.condition_folder import BidConditionFolder
from ..entities.hierarchy_data import HierarchyBidInfo, HierarchyData
from ..entities.hierarchy_manager import HierarchyManager
from ..entities.identity_refs import BidRef
from ..entities.page import Page
from ..entities.project import Project
from ..entities.takeoff import Takeoff
from ..services.file_manager_service import FileManager
from ..services.page_selection_service import PageSelectionService


class OstAggregate:
    def __init__(
        self,
        file_manager: FileManager,
        logger: Optional[logging.Logger] = None,
    ):
        self.logger = logger or logging.getLogger(__name__)
        self.file_manager = file_manager
        self._hierarchy_manager = HierarchyManager()
        self._page_selection = PageSelectionService()
        self.projects: List[Project] = []
        self.bid_conditions: Dict[str, Condition] = {}
        self.bid_takeoffs: List[Takeoff] = []
        self.bid_takeoff_extras: Dict[str, Dict[str, Any]] = {}
        self.cdn_types: Dict[str, CdnType] = {}
        self.bid_condition_folders: Dict[str, BidConditionFolder] = {}
        self.page_area_selections: Dict[str, Optional[str]] = {}
        self.bid_layer_visibility: Dict[str, bool] = {}
        self.current_bid_ref: Optional[BidRef] = None
        self.current_bid: Optional[Bid] = None
        self.current_bid_locked: bool = False
        self.last_selected_page_uid: Optional[str] = None

    @property
    def current_bid_file_path(self) -> Optional[str]:
        return self.current_bid_ref.file_path if self.current_bid_ref else None

    def set_hierarchy(self, data: HierarchyData) -> None:
        self._hierarchy_manager.set_hierarchy(data)

    def get_hierarchy_data(self) -> HierarchyData:
        return self._hierarchy_manager.data

    def find_bid_info(self, bid_ref) -> Optional[HierarchyBidInfo]:
        return self._hierarchy_manager.find_bid_info(bid_ref)

    def bid_exists(self, bid_ref) -> bool:
        return self._hierarchy_manager.bid_exists(bid_ref)

    def get_current_file_path(self) -> Optional[str]:
        return self.file_manager.current_file_path

    def set_current_file_path(self, file_path: str) -> None:
        self.file_manager.current_file_path = file_path

    def set_pages(self, pages: Dict[str, Page]) -> None:
        self._page_selection.set_pages(pages)

    def set_annotations(self, annotations: List[BidAnnotation]) -> None:
        self._page_selection.set_annotations(annotations)

    def add_annotations(self, annotations: List[BidAnnotation]) -> None:
        self._page_selection.add_annotations(annotations)

    def remove_annotations_by_keys(
        self, annotation_keys: Iterable[Tuple[str, str]]
    ) -> List[str]:
        return self._page_selection.remove_annotations_by_keys(annotation_keys)

    def select_pages(self, page_uids: Iterable[str]) -> List[str]:
        return self._page_selection.select_pages(page_uids)

    def clear_page_selection(self) -> None:
        self._page_selection.clear()

    def deselect_pages(self) -> None:
        self._page_selection.clear_selection()

    def get_selected_pages(self) -> List[str]:
        return self._page_selection.get_selected_pages()

    def get_page(self, page_uid: str) -> Optional[Page]:
        return self._page_selection.get_page(page_uid)

    def get_all_pages(self) -> List[Page]:
        return list(self._page_selection.pages.values())

    def get_page_name(self, page_uid: str) -> str:
        return self._page_selection.get_page_name(page_uid)

    def get_page_takeoffs(self, page_uid: str) -> List[Takeoff]:
        return self._page_selection.get_page_takeoffs(page_uid)

    def get_all_takeoffs(self) -> List[Takeoff]:
        return self._page_selection.get_all_takeoffs()

    def get_all_selected_takeoffs(self) -> List[Takeoff]:
        return self._page_selection.get_all_selected_takeoffs()

    def has_takeoffs_for_pages(self, page_uids: Iterable[str]) -> bool:
        return self._page_selection.has_takeoffs_for_pages(page_uids)

    def get_page_annotations(self, page_uid: str) -> List[BidAnnotation]:
        return self._page_selection.get_page_annotations(page_uid)

    def get_all_annotations(self) -> List[BidAnnotation]:
        return self._page_selection.get_all_annotations()

    def get_takeoff_extras(self, takeoff_uid: str) -> Dict[str, Any]:
        return self.bid_takeoff_extras.get(str(takeoff_uid), {})

    def clear_bid(self) -> None:
        self.bid_conditions = {}
        self.bid_takeoffs = []
        self.bid_takeoff_extras = {}
        self.bid_condition_folders = {}
        self.page_area_selections = {}
        self.bid_layer_visibility = {}
        self.current_bid_ref = None
        self.current_bid = None
        self.current_bid_locked = False
        self.last_selected_page_uid = None
        self._page_selection.clear()
