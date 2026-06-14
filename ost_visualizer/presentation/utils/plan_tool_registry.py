from dataclasses import dataclass
from ..config import (
    ACTION_ARROW_ANNOTATION_LABEL,
    ACTION_ARROW_ANNOTATION_TOOLTIP,
    ACTION_CLOUD_ANNOTATION_LABEL,
    ACTION_CLOUD_ANNOTATION_TOOLTIP,
    ACTION_DIMENSION_LABEL,
    ACTION_DIMENSION_TOOLTIP,
    ACTION_HIGHLIGHT_ANNOTATION_LABEL,
    ACTION_HIGHLIGHT_ANNOTATION_TOOLTIP,
    ACTION_LINE_ANNOTATION_LABEL,
    ACTION_LINE_ANNOTATION_TOOLTIP,
    ACTION_OVAL_ANNOTATION_LABEL,
    ACTION_OVAL_ANNOTATION_TOOLTIP,
    ACTION_PAN_LABEL,
    ACTION_PAN_TOOLTIP,
    ACTION_PLACE_LABEL,
    ACTION_PLACE_TOOLTIP,
    ACTION_POLYGON_ANNOTATION_LABEL,
    ACTION_POLYGON_ANNOTATION_TOOLTIP,
    ACTION_RECTANGLE_ANNOTATION_LABEL,
    ACTION_RECTANGLE_ANNOTATION_TOOLTIP,
    ACTION_SELECT_LABEL,
    ACTION_SELECT_TOOLTIP,
    ACTION_TEXT_ANNOTATION_LABEL,
    ACTION_TEXT_ANNOTATION_TOOLTIP,
    ACTION_ZOOM_LABEL,
    ACTION_ZOOM_TOOLTIP,
)
from ..managers.icon_manager import IconId


@dataclass(frozen=True)
class PlanToolSpec:
    action_key: str
    label: str
    tooltip: str
    icon_id: IconId
    annotation_type: str | None = None


PLAN_CURSOR_TOOL_SPECS = (
    PlanToolSpec(
        "select_tool",
        ACTION_SELECT_LABEL,
        ACTION_SELECT_TOOLTIP,
        IconId.SELECT_TOOL,
    ),
    PlanToolSpec(
        "place_tool",
        ACTION_PLACE_LABEL,
        ACTION_PLACE_TOOLTIP,
        IconId.PLACE_TOOL,
    ),
    PlanToolSpec(
        "pan_tool",
        ACTION_PAN_LABEL,
        ACTION_PAN_TOOLTIP,
        IconId.PAN_TOOL,
    ),
    PlanToolSpec(
        "zoom_tool",
        ACTION_ZOOM_LABEL,
        ACTION_ZOOM_TOOLTIP,
        IconId.ZOOM_TOOL,
    ),
)
PLAN_ANNOTATION_TOOL_SPECS = (
    PlanToolSpec(
        "dimension_tool",
        ACTION_DIMENSION_LABEL,
        ACTION_DIMENSION_TOOLTIP,
        IconId.DIMENSION_TOOL,
        annotation_type="dimension",
    ),
    PlanToolSpec(
        "text_annotation_tool",
        ACTION_TEXT_ANNOTATION_LABEL,
        ACTION_TEXT_ANNOTATION_TOOLTIP,
        IconId.TEXT_ANNOTATION_TOOL,
        annotation_type="text",
    ),
    PlanToolSpec(
        "highlight_annotation_tool",
        ACTION_HIGHLIGHT_ANNOTATION_LABEL,
        ACTION_HIGHLIGHT_ANNOTATION_TOOLTIP,
        IconId.HIGHLIGHT_ANNOTATION_TOOL,
        annotation_type="highlight",
    ),
    PlanToolSpec(
        "arrow_annotation_tool",
        ACTION_ARROW_ANNOTATION_LABEL,
        ACTION_ARROW_ANNOTATION_TOOLTIP,
        IconId.ARROW_ANNOTATION_TOOL,
        annotation_type="arrow",
    ),
    PlanToolSpec(
        "line_annotation_tool",
        ACTION_LINE_ANNOTATION_LABEL,
        ACTION_LINE_ANNOTATION_TOOLTIP,
        IconId.LINE_ANNOTATION_TOOL,
        annotation_type="line",
    ),
    PlanToolSpec(
        "rectangle_annotation_tool",
        ACTION_RECTANGLE_ANNOTATION_LABEL,
        ACTION_RECTANGLE_ANNOTATION_TOOLTIP,
        IconId.RECTANGLE_ANNOTATION_TOOL,
        annotation_type="rect",
    ),
    PlanToolSpec(
        "oval_annotation_tool",
        ACTION_OVAL_ANNOTATION_LABEL,
        ACTION_OVAL_ANNOTATION_TOOLTIP,
        IconId.OVAL_ANNOTATION_TOOL,
        annotation_type="oval",
    ),
    PlanToolSpec(
        "polygon_annotation_tool",
        ACTION_POLYGON_ANNOTATION_LABEL,
        ACTION_POLYGON_ANNOTATION_TOOLTIP,
        IconId.POLYGON_ANNOTATION_TOOL,
        annotation_type="polygon",
    ),
    PlanToolSpec(
        "cloud_annotation_tool",
        ACTION_CLOUD_ANNOTATION_LABEL,
        ACTION_CLOUD_ANNOTATION_TOOLTIP,
        IconId.CLOUD_ANNOTATION_TOOL,
        annotation_type="cloud",
    ),
)
PLAN_TOOL_SPECS = PLAN_CURSOR_TOOL_SPECS + PLAN_ANNOTATION_TOOL_SPECS
PLAN_TOOL_ACTION_KEYS = tuple(spec.action_key for spec in PLAN_TOOL_SPECS)
PLAN_TOOL_MENU_ITEMS = tuple(("shared", spec.action_key) for spec in PLAN_TOOL_SPECS)
PLAN_TOOL_CONTEXT_ACTIONS = tuple(
    (spec.label, spec.action_key) for spec in PLAN_TOOL_SPECS
)
