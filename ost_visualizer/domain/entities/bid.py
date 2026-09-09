from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional
from .folder import Folder
from .page import Page


@dataclass
class Bid:
    uid: str
    name: str
    bid_no: int = 0
    bid_date: Optional[Any] = None
    notes: str = ""
    job_id: str = ""
    status: str = ""
    status_uid: Optional[str] = None
    estimator: str = ""
    page_count: int = 0
    condition_count: int = 0
    measure_base: int = 0
    takeoff_increments: float = 1.0
    orig_bid_project_uid: Optional[str] = None
    copy_from_bid_no: int = 0
    copy_timestamp: Optional[Any] = None
    folders: Dict[str, Folder] = field(default_factory=dict)
    pages_without_folder: List[Page] = field(default_factory=list)

    def replace_pages(self, pages: Iterable[Page]) -> None:
        folders_by_uid: Dict[str, Folder] = {}

        def index_folders(folders: Iterable[Folder]) -> None:
            for folder in folders:
                folders_by_uid[str(folder.uid)] = folder
                folder.pages.clear()
                index_folders(folder.subfolders.values())

        index_folders(self.folders.values())
        self.pages_without_folder.clear()
        ordered_pages = sorted(pages, key=lambda page: page.sequence)
        for page in ordered_pages:
            folder = folders_by_uid.get(str(page.folder_uid or ""))
            if folder is None:
                self.pages_without_folder.append(page)
            else:
                folder.pages.append(page)
        self.page_count = len(ordered_pages)
