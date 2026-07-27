from dataclasses import dataclass, field
from typing import Dict, List, Optional
from ...domain.entities.area import UNASSIGNED_AREA_UID

MCP_BRIDGE_SERVER_NAME = "OSTVisualizerMcpBridge.v1"
MCP_STATUS_OK = "ok"
MCP_STATUS_EMPTY = "empty"
MCP_STATUS_TRUNCATED = "truncated"
MCP_STATUS_NOT_CONFIGURED = "not_configured"
MCP_STATUS_CONFIGURED = "configured"
MCP_STATUS_NOT_PDF = "not_pdf"
MCP_STATUS_NOT_REQUESTED = "not_requested"
MCP_STATUS_UNAVAILABLE = "unavailable"
MCP_STATUS_DEFERRED = "deferred"
MCP_STATUS_DUPLICATE_REF_NO = "duplicate_ref_no"
MCP_PDF_SOURCE_AUTO = "auto"
MCP_PDF_SOURCE_MAIN = "main"
MCP_PDF_SOURCE_OVERLAY = "overlay"
MCP_PDF_SOURCES = frozenset(
    {MCP_PDF_SOURCE_AUTO, MCP_PDF_SOURCE_MAIN, MCP_PDF_SOURCE_OVERLAY}
)
MCP_PAGE_SOURCE_BLANK = "blank"
MCP_PAGE_SOURCE_MAIN = MCP_PDF_SOURCE_MAIN
MCP_PAGE_SOURCE_OVERLAY = MCP_PDF_SOURCE_OVERLAY
MCP_PAGE_SOURCE_COMPOSITE = "composite"
MCP_OVERLAY_KIND_PDF = "pdf"
MCP_OVERLAY_KIND_RASTER = "raster"
MCP_SUMMARY_DEFAULT_GROUP_BY_PAGE = False
MCP_SUMMARY_DEFAULT_GROUP_BY_TYPE = True
MCP_SUMMARY_DEFAULT_GROUP_BY_AREA = True
MCP_SUMMARY_DEFAULT_LIMIT = 500
MCP_SUMMARY_MAX_LIMIT = 5000
MCP_BID_COMPARISON_DEFAULT_LIMIT = 250
MCP_BID_COMPARISON_MAX_LIMIT = 5000


@dataclass
class McpDatabaseDto:
    database_id: str
    display_name: str
    basename: str = ""
    path_status: str = "checked"
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
    sheet_no: str = ""
    sequence: int = 0
    folder_uid: Optional[str] = None
    image_basename: Optional[str] = None
    image_path_status: str = MCP_STATUS_NOT_CONFIGURED
    is_pdf: bool = False
    page_index: int = 0
    width_pts: float = 0.0
    height_pts: float = 0.0
    scale_factor1: float = 1.0
    scale_factor2: float = 1.0
    rotation: int = 0
    layer_visible: bool = True
    overlay_basename: Optional[str] = None
    overlay_path_status: str = MCP_STATUS_NOT_CONFIGURED
    has_overlay: bool = False
    source_kind: str = MCP_PAGE_SOURCE_BLANK
    page_width: float = 0.0
    page_height: float = 0.0
    pdf_metadata_status: str = MCP_STATUS_NOT_REQUESTED
    pdf_page_count: int = 0
    media_width_pts: float = 0.0
    media_height_pts: float = 0.0
    crop_width_pts: float = 0.0
    crop_height_pts: float = 0.0
    intrinsic_rotation: int = 0
    has_embedded_text: bool = False
    text_run_count: int = 0
    character_count: int = 0
    snap_line_count: int = 0
    snap_point_count: int = 0
    overlay_kind: str = MCP_STATUS_NOT_CONFIGURED
    overlay_transform_summary: Optional["McpPdfOverlayTransformDto"] = None
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
    area_uid: str = UNASSIGNED_AREA_UID
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
    has_more: bool = False


@dataclass
class McpPdfOverlayTransformDto:
    offset_x: float = 0.0
    offset_y: float = 0.0
    rotation: float = 0.0
    deskew_rotation: float = 0.0
    scale: float = 0.0
    rect_x: float = 0.0
    rect_y: float = 0.0
    rect_width: float = 0.0
    rect_height: float = 0.0
    resized: bool = False


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
class McpSummaryGroupingDto:
    group_by_page: bool = MCP_SUMMARY_DEFAULT_GROUP_BY_PAGE
    group_by_type: bool = MCP_SUMMARY_DEFAULT_GROUP_BY_TYPE
    group_by_area: bool = MCP_SUMMARY_DEFAULT_GROUP_BY_AREA


@dataclass
class McpSummaryValuesDto:
    number: str = ""
    name: str = ""
    type_name: str = ""
    height: str = ""
    height_inches: float = 0.0
    area: str = ""
    quantity1: float = 0.0
    uom1: int = 0
    uom1_label: str = ""
    quantity2: float = 0.0
    uom2: int = 0
    uom2_label: str = ""
    quantity3: float = 0.0
    uom3: int = 0
    uom3_label: str = ""
    notes: str = ""


@dataclass
class McpSummaryNodeDto:
    kind: str
    label: str = ""
    condition_uid: str = ""
    folder_uid: str = ""
    group_level: str = ""
    folder_path: List[str] = field(default_factory=list)
    page: str = ""
    type_name: str = ""
    area: str = ""
    values: McpSummaryValuesDto = field(default_factory=McpSummaryValuesDto)
    children: List["McpSummaryNodeDto"] = field(default_factory=list)
    child_count: int = 0
    copyable: bool = False
    deletable: bool = False
    layer_visible: bool = True
    color_fill: int = 0
    pattern: int = 0


@dataclass
class McpSummaryDto:
    status: str
    database_id: str
    bid_uid: str
    bid_name: str = ""
    project_uid: Optional[str] = None
    project_name: str = ""
    grouping: McpSummaryGroupingDto = field(default_factory=McpSummaryGroupingDto)
    meta: McpResultMetaDto = field(default_factory=McpResultMetaDto)
    root_label: str = ""
    total_node_count: int = 0
    nodes: List[McpSummaryNodeDto] = field(default_factory=list)


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
class McpBidComparisonCountsDto:
    unchanged: int = 0
    changed: int = 0
    added: int = 0
    removed: int = 0


@dataclass
class McpBidComparisonQuantityDto:
    uom_label: str = ""
    old: float = 0.0
    new: float = 0.0


@dataclass
class McpBidMetadataChangeDto:
    field: str
    old: object = None
    new: object = None


@dataclass
class McpBidComparisonGroupDto:
    cdn_type_name: str
    total_affected: int = 0
    changed: int = 0
    added: int = 0
    removed: int = 0
    qty1: McpBidComparisonQuantityDto = field(
        default_factory=McpBidComparisonQuantityDto
    )
    qty2: McpBidComparisonQuantityDto = field(
        default_factory=McpBidComparisonQuantityDto
    )
    qty3: McpBidComparisonQuantityDto = field(
        default_factory=McpBidComparisonQuantityDto
    )
    takeoffs: Dict[str, int] = field(default_factory=lambda: {"old": 0, "new": 0})
    affected_pages: List[str] = field(default_factory=list)


@dataclass
class McpBidComparisonDetailDto:
    ref_no: int
    classification: str
    cdn_type_name: str
    old_condition_name: Optional[str] = None
    new_condition_name: Optional[str] = None
    metadata_changed: bool = False
    quantity_changed: bool = False
    takeoff_count_changed: bool = False
    visible_takeoff_count_changed: bool = False
    affected_pages: List[str] = field(default_factory=list)


@dataclass
class McpDuplicateRefNoDto:
    bid: str
    ref_no: int
    condition_count: int
    condition_names: List[str] = field(default_factory=list)


@dataclass
class McpBidComparisonDto:
    old_bid: McpBidDto
    new_bid: McpBidDto
    counts: McpBidComparisonCountsDto = field(default_factory=McpBidComparisonCountsDto)
    bid_metadata_changed: bool = False
    bid_metadata_changes: List[McpBidMetadataChangeDto] = field(default_factory=list)
    groups: List[McpBidComparisonGroupDto] = field(default_factory=list)
    details: List[McpBidComparisonDetailDto] = field(default_factory=list)
    duplicate_ref_nos: List[McpDuplicateRefNoDto] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class McpBidComparisonMetaDto(McpResultMetaDto):
    matched_by: str = "ref_no"
    grouped_by: str = "cdn_type_name"
    details_included: bool = False
    detail_returned_count: int = 0
    detail_total_count: int = 0
    details_truncated: bool = False


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
    page_text_status: str = MCP_STATUS_DEFERRED


@dataclass
class McpPdfTextRunDto:
    snippet: str
    left: float = 0.0
    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0
    character_count: int = 0
    text: Optional[str] = None


@dataclass
class McpPdfTextSummaryDto:
    status: str
    database_id: str
    bid_uid: str
    page_uid: str
    source: str
    source_status: str
    meta: McpResultMetaDto
    text_run_count: int = 0
    character_count: int = 0
    returned_character_count: int = 0
    runs: List[McpPdfTextRunDto] = field(default_factory=list)


@dataclass
class McpPdfVectorSegmentDto:
    x1: float
    y1: float
    x2: float
    y2: float
    length: float = 0.0
    orientation: str = "other"


@dataclass
class McpPdfVectorsSummaryDto:
    status: str
    database_id: str
    bid_uid: str
    page_uid: str
    source: str
    source_status: str
    meta: McpResultMetaDto
    snap_line_count: int = 0
    snap_point_count: int = 0
    segments: List[McpPdfVectorSegmentDto] = field(default_factory=list)


@dataclass
class McpMarkupSampleDto:
    uid: str
    annotation_type: str
    layer_uid: Optional[str] = None
    visible: bool = True
    color: str = ""
    width: float = 0.0
    point_count: int = 0
    bbox_left: Optional[float] = None
    bbox_top: Optional[float] = None
    bbox_right: Optional[float] = None
    bbox_bottom: Optional[float] = None
    length: Optional[float] = None
    text_snippet: str = ""
    text_character_count: int = 0
    linked_takeoff_count: int = 0


@dataclass
class McpPageMarkupsSummaryDto:
    status: str
    database_id: str
    bid_uid: str
    page_uid: str
    page_name: str
    sheet_no: str
    meta: McpResultMetaDto
    total_markup_count: int = 0
    visible_markup_count: int = 0
    dimension_count: int = 0
    text_annotation_count: int = 0
    callout_count: int = 0
    hotlink_count: int = 0
    named_view_count: int = 0
    counts_by_type: Dict[str, int] = field(default_factory=dict)
    samples: List[McpMarkupSampleDto] = field(default_factory=list)


@dataclass
class McpPageOverlaySummaryDto:
    status: str
    database_id: str
    bid_uid: str
    page_uid: str
    page_name: str
    sheet_no: str
    source_kind: str = MCP_PAGE_SOURCE_BLANK
    image_basename: Optional[str] = None
    image_path_status: str = MCP_STATUS_NOT_CONFIGURED
    is_pdf: bool = False
    has_overlay: bool = False
    overlay_basename: Optional[str] = None
    overlay_path_status: str = MCP_STATUS_NOT_CONFIGURED
    overlay_kind: str = MCP_STATUS_NOT_CONFIGURED
    show_mode: int = 0
    show_original: bool = True
    show_overlay: bool = False
    overlay_transform_summary: Optional[McpPdfOverlayTransformDto] = None


@dataclass
class McpPdfTextSearchMatchDto:
    page_uid: str
    page_name: str
    sheet_no: str
    source: str
    snippet: str
    left: float = 0.0
    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0
    character_count: int = 0


@dataclass
class McpPdfTextSearchSummaryDto:
    status: str
    database_id: str
    bid_uid: str
    page_uid: str
    query: str
    source: str
    source_status: str
    meta: McpResultMetaDto
    match_count: int = 0
    matches: List[McpPdfTextSearchMatchDto] = field(default_factory=list)


@dataclass
class McpLayerDto:
    uid: str
    name: str
    visible: bool = True
    sequence: int = 0
    is_template: bool = False
    is_locked: bool = False
    condition_count: int = 0
    takeoff_count: int = 0
    annotation_count: int = 0


@dataclass
class McpNamedViewDto:
    uid: str
    page_uid: str
    page_name: str = ""
    name: str = ""
    min_x: float = 0.0
    min_y: float = 0.0
    max_x: float = 0.0
    max_y: float = 0.0
    center_x: float = 0.0
    center_y: float = 0.0
    width: float = 0.0
    height: float = 0.0


@dataclass
class McpHotlinkDto:
    uid: str
    page_uid: str
    page_name: str = ""
    layer_uid: Optional[str] = None
    visible: bool = True
    target_named_view_uid: Optional[str] = None
    target_named_view_name: str = ""
    target_page_uid: Optional[str] = None
    target_page_name: str = ""


@dataclass
class McpSelectedTakeoffsSummaryDto:
    status: str
    message: str = ""
    database_id: Optional[str] = None
    bid_uid: Optional[str] = None
    meta: McpResultMetaDto = field(default_factory=McpResultMetaDto)
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
    meta: McpResultMetaDto = field(default_factory=McpResultMetaDto)
    active_view: str = ""
    active_page_uid: Optional[str] = None
    selected_page_uids: List[str] = field(default_factory=list)
    missing_page_uids: List[str] = field(default_factory=list)
    pages: List[McpPageDto] = field(default_factory=list)


@dataclass
class McpHierarchyDto:
    database: McpDatabaseDto
    status: str = MCP_STATUS_OK
    meta: McpResultMetaDto = field(default_factory=McpResultMetaDto)
    projects: List[McpProjectDto] = field(default_factory=list)
    orphan_bids: List[McpBidDto] = field(default_factory=list)
