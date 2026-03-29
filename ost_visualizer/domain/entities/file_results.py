from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from .annotation import BidAnnotation
from .cdn_type import CdnType
from .condition import Condition
from .condition_folder import BidConditionFolder
from .hierarchy_data import HierarchyData, HierarchyFileEntry
from .page import Page
from .page_info import BidPageInfo
from .takeoff import Takeoff


@dataclass
class FileLoadResult:
    success: bool
    hierarchy: HierarchyData = field(default_factory=HierarchyData)
    parsed_hierarchy: Optional[HierarchyFileEntry] = None
    cdn_types: Dict[str, CdnType] = field(default_factory=dict)
    error_message: Optional[str] = None
    pages: Dict[str, Page] = field(default_factory=dict)


@dataclass
class BidLoadResult:
    bid_conditions: Dict[str, Condition] = field(default_factory=dict)
    bid_takeoffs: List[Takeoff] = field(default_factory=list)
    bid_pages: Dict[str, BidPageInfo] = field(default_factory=dict)
    pages: Dict[str, Page] = field(default_factory=dict)
    page_area_selections: Dict[str, Optional[str]] = field(default_factory=dict)
    bid_annotations: List[BidAnnotation] = field(default_factory=list)
    bid_condition_folders: Dict[str, BidConditionFolder] = field(default_factory=dict)
    selected_page_uid: Optional[str] = None
    takeoff_extras: Dict[str, Dict[str, Any]] = field(default_factory=dict)
