from dataclasses import dataclass
from ..config import (
    ACTION_DIMENSION_LABEL,
    ACTION_DIMENSION_TOOLTIP,
    ACTION_PAN_LABEL,
    ACTION_PAN_TOOLTIP,
    ACTION_PLACE_LABEL,
    ACTION_PLACE_TOOLTIP,
    ACTION_SELECT_LABEL,
    ACTION_SELECT_TOOLTIP,
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
    ),
)
PLAN_TOOL_SPECS = PLAN_CURSOR_TOOL_SPECS + PLAN_ANNOTATION_TOOL_SPECS
PLAN_TOOL_ACTION_KEYS = tuple(spec.action_key for spec in PLAN_TOOL_SPECS)
PLAN_TOOL_MENU_ITEMS = tuple(("shared", spec.action_key) for spec in PLAN_TOOL_SPECS)
PLAN_TOOL_CONTEXT_ACTIONS = tuple(
    (spec.label, spec.action_key) for spec in PLAN_TOOL_SPECS
)
