from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
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
