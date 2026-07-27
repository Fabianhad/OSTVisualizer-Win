from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from .identity_refs import BidRef


@dataclass
class HierarchyPageInfo:
    uid: str
    name: str
    sheet_no: str = ""
    sequence: int = 0
    image_path: Optional[str] = None
    width: float = 0.0
    height: float = 0.0
    scale_factor1: float = 1.0
    scale_factor2: float = 1.0
    rotation: int = 0
    flip_x: bool = False
    flip_y: bool = False
    page_index: int = 0


@dataclass
class HierarchyFolderInfo:
    name: str
    description: str = ""
    parent_uid: Optional[str] = None
    pages: List[HierarchyPageInfo] = field(default_factory=list)
    subfolders: Dict[str, HierarchyFolderInfo] = field(default_factory=dict)


@dataclass
class HierarchyBidInfo:
    uid: str
    name: str = ""
    job_id: str = ""
    bid_no: int = 0
    bid_date: Optional[Any] = None
    notes: str = ""
    status: str = ""
    estimator: str = ""
    page_count: int = 0
    condition_count: int = 0
    measure_base: int = 0
    takeoff_increments: float = 1.0
    orig_bid_project_uid: Optional[str] = None
    copy_from_bid_no: int = 0
    copy_timestamp: Optional[Any] = None
    folders: Dict[str, HierarchyFolderInfo] = field(default_factory=dict)
    pages_without_folder: List[HierarchyPageInfo] = field(default_factory=list)


@dataclass
class HierarchyProjectInfo:
    name: str
    description: str = ""
    bids: List[HierarchyBidInfo] = field(default_factory=list)


@dataclass
class HierarchyFileEntry:
    file_path: str
    created_at: float = 0.0
    display_name: str = ""
    database_name: str = ""
    bid_projects: Dict[str, HierarchyProjectInfo] = field(default_factory=dict)
    orphan_bids: List[HierarchyBidInfo] = field(default_factory=list)


@dataclass
class HierarchyData:
    loaded_files: List[HierarchyFileEntry] = field(default_factory=list)

    def find_bid_info(self, bid_ref: BidRef) -> Optional[HierarchyBidInfo]:
        return self.find_bid_info_for_file(bid_ref.bid_uid, bid_ref.file_path)

    def find_bid_info_for_file(
        self, bid_uid: str, file_path: str
    ) -> Optional[HierarchyBidInfo]:
        if not bid_uid or not file_path:
            return None
        for file_entry in self.loaded_files:
            if file_entry.file_path != file_path:
                continue
            for project_info in file_entry.bid_projects.values():
                for bid in project_info.bids:
                    if bid.uid == bid_uid:
                        return bid
            for bid in file_entry.orphan_bids:
                if bid.uid == bid_uid:
                    return bid
        return None

    def bid_exists(self, bid_ref: BidRef) -> bool:
        return self.find_bid_info(bid_ref) is not None

    def page_exists(self, page_uid: str) -> bool:
        for file_entry in self.loaded_files:
            for project_info in file_entry.bid_projects.values():
                for bid in project_info.bids:
                    if self._bid_has_page(bid, page_uid):
                        return True
            for bid in file_entry.orphan_bids:
                if self._bid_has_page(bid, page_uid):
                    return True
        return False

    def find_file_path_for_project(
        self, project_uid: str, preferred_file_path: Optional[str] = None
    ) -> Optional[str]:
        if not project_uid:
            return None
        matched_file_path = None
        for file_entry in self.loaded_files:
            if project_uid not in file_entry.bid_projects:
                continue
            if preferred_file_path is not None:
                if file_entry.file_path == preferred_file_path:
                    return file_entry.file_path
                continue
            if matched_file_path is not None:
                return None
            matched_file_path = file_entry.file_path
        return matched_file_path

    @staticmethod
    def _bid_has_page(bid: HierarchyBidInfo, page_uid: str) -> bool:
        if any(p.uid == page_uid for p in bid.pages_without_folder):
            return True
        return HierarchyData._folders_have_page(bid.folders, page_uid)

    @staticmethod
    def _folders_have_page(
        folders: Dict[str, HierarchyFolderInfo], page_uid: str
    ) -> bool:
        for folder in folders.values():
            if any(p.uid == page_uid for p in folder.pages):
                return True
            if HierarchyData._folders_have_page(folder.subfolders, page_uid):
                return True
        return False
