from dataclasses import dataclass, field
from typing import List, Optional

MCP_BRIDGE_SERVER_NAME = "OSTVisualizerMcpBridge.v1"


@dataclass
class McpDatabaseDto:
    database_id: str
    display_name: str
    file_path: str
    exists: bool = True


@dataclass
class McpProjectDto:
    uid: str
    name: str
    description: str = ""
    bid_count: int = 0


@dataclass
class McpBidDto:
    uid: str
    name: str
    project_uid: Optional[str] = None
    project_name: Optional[str] = None
    bid_no: int = 0
    job_id: str = ""
    status: str = ""
    estimator: str = ""
    page_count: int = 0
    condition_count: int = 0
    selected_page_uid: Optional[str] = None


@dataclass
class McpPageDto:
    uid: str
    name: str
    folder_uid: Optional[str] = None
    image_path: Optional[str] = None
    is_pdf: bool = False
    page_index: int = 0
    width_pts: float = 0.0
    height_pts: float = 0.0
    scale_factor1: float = 1.0
    scale_factor2: float = 1.0
    rotation: int = 0
    layer_visible: bool = True
    overlay_image_path: Optional[str] = None
    takeoff_count: int = 0


@dataclass
class McpConditionDto:
    uid: str
    name: str
    condition_type: int
    condition_type_name: str
    ref_no: int = 0
    folder_uid: Optional[str] = None
    layer_uid: Optional[str] = None
    layer_visible: bool = True
    cdn_type_uid: Optional[str] = None
    cdn_type_name: str = ""
    uom1: int = 0
    uom2: int = 0
    uom3: int = 0
    uom1_label: str = ""
    uom2_label: str = ""
    uom3_label: str = ""
    notes: str = ""


@dataclass
class McpTakeoffDto:
    uid: str
    condition_uid: str
    condition_name: str = ""
    page_uid: str = ""
    page_name: str = ""
    area_uid: str = "0"
    area_name: Optional[str] = None
    parent_uid: str = "0"
    is_hole: bool = False
    is_negative: bool = False
    visible: bool = True
    rotation: float = 0.0
    curve: int = -1
    point_count: int = 0
    position: Optional[List[float]] = None


@dataclass
class McpQuantityDto:
    condition_uid: str
    condition_name: str
    ref_no: int = 0
    quantity1: float = 0.0
    quantity2: float = 0.0
    quantity3: float = 0.0
    uom1: int = 0
    uom2: int = 0
    uom3: int = 0
    uom1_label: str = ""
    uom2_label: str = ""
    uom3_label: str = ""
    takeoff_count: int = 0


@dataclass
class McpResultMetaDto:
    limit: int = 0
    returned_count: int = 0
    total_count: int = 0
    truncated: bool = False


@dataclass
class McpPageTakeoffSummaryDto:
    page_uid: str
    page_name: str
    takeoff_count: int = 0
    visible_takeoff_count: int = 0


@dataclass
class McpAreaDto:
    uid: str
    bid_uid: str
    parent_uid: str = ""
    name: str = ""
    sequence: int = 0
    guid: str = ""
    child_uids: List[str] = field(default_factory=list)
    takeoff_count: int = 0
    visible_takeoff_count: int = 0
    page_count: int = 0


@dataclass
class McpAreaSummaryDto:
    status: str
    database_id: str
    bid_uid: str
    area: McpAreaDto
    meta: "McpResultMetaDto"
    pages: List[McpPageTakeoffSummaryDto] = field(default_factory=list)
    children: List[McpAreaDto] = field(default_factory=list)


@dataclass
class McpConditionQuantitySummaryDto:
    condition: McpConditionDto
    quantities: List[McpQuantityDto] = field(default_factory=list)
    pages: List[McpPageTakeoffSummaryDto] = field(default_factory=list)
    takeoff_count: int = 0
    visible_takeoff_count: int = 0
    page_count: int = 0
    zero_quantity: bool = False


@dataclass
class McpConditionSummaryDto:
    condition: McpConditionDto
    quantities: List[McpQuantityDto] = field(default_factory=list)
    pages: List[McpPageTakeoffSummaryDto] = field(default_factory=list)
    takeoff_count: int = 0
    visible_takeoff_count: int = 0


@dataclass
class McpBidQuantitySummaryDto:
    status: str
    database_id: str
    bid_uid: str
    meta: McpResultMetaDto
    conditions: List[McpConditionQuantitySummaryDto] = field(default_factory=list)


@dataclass
class McpScopeGapSummaryDto:
    status: str
    database_id: str
    bid_uid: str
    meta: McpResultMetaDto
    pages_without_takeoffs: List[McpPageDto] = field(default_factory=list)
    conditions_without_takeoffs: List[McpConditionDto] = field(default_factory=list)
    takeoffs_missing_pages: List[McpTakeoffDto] = field(default_factory=list)
    takeoffs_missing_conditions: List[McpTakeoffDto] = field(default_factory=list)


@dataclass
class McpDuplicateConditionGroupDto:
    name: str
    conditions: List[McpConditionDto] = field(default_factory=list)


@dataclass
class McpDuplicateConditionSummaryDto:
    status: str
    database_id: str
    bid_uid: str
    meta: McpResultMetaDto
    groups: List[McpDuplicateConditionGroupDto] = field(default_factory=list)


@dataclass
class McpZeroQuantitySummaryDto:
    status: str
    database_id: str
    bid_uid: str
    meta: McpResultMetaDto
    conditions: List[McpConditionQuantitySummaryDto] = field(default_factory=list)


@dataclass
class McpUnplacedTakeoffSummaryDto:
    status: str
    database_id: str
    bid_uid: str
    meta: McpResultMetaDto
    takeoffs: List[McpTakeoffDto] = field(default_factory=list)


@dataclass
class McpPageContextDto:
    status: str
    database_id: str
    bid_uid: str
    page: McpPageDto
    page_label: str = ""
    sheet_name: str = ""
    source_file_name: str = ""
    has_pdf_source: bool = False
    has_overlay: bool = False
    page_text_status: str = "deferred"


@dataclass
class McpSelectedTakeoffsSummaryDto:
    status: str
    message: str = ""
    database_id: Optional[str] = None
    bid_uid: Optional[str] = None
    selected_takeoff_count: int = 0
    missing_takeoff_uids: List[str] = field(default_factory=list)
    takeoffs: List[McpTakeoffDto] = field(default_factory=list)
    quantities: List[McpQuantityDto] = field(default_factory=list)
    pages: List[McpPageTakeoffSummaryDto] = field(default_factory=list)
    condition_uids: List[str] = field(default_factory=list)


@dataclass
class McpSelectedPagesSummaryDto:
    status: str
    message: str = ""
    database_id: Optional[str] = None
    bid_uid: Optional[str] = None
    active_view: str = ""
    active_page_uid: Optional[str] = None
    selected_page_uids: List[str] = field(default_factory=list)
    missing_page_uids: List[str] = field(default_factory=list)
    pages: List[McpPageDto] = field(default_factory=list)


@dataclass
class McpHierarchyDto:
    database: McpDatabaseDto
    projects: List[McpProjectDto] = field(default_factory=list)
    orphan_bids: List[McpBidDto] = field(default_factory=list)
