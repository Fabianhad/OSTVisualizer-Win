from ..config import ANNOTATION_WINDOW_TITLE
from ..modes.cursor import CURSOR_MODE_SELECT
from ..utils.plan_tool_registry import PLAN_ANNOTATION_TOOL_SPECS
from .components.window import DetachedPageViewWindow, DetachedPageViewWindowConfig

_ANNOTATION_WINDOW_CONFIG = DetachedPageViewWindowConfig(
    window_title=ANNOTATION_WINDOW_TITLE,
    show_scale_combo=True,
    show_select_tool=True,
    default_cursor_mode=CURSOR_MODE_SELECT,
    allow_annotation_editing=True,
    dropdown_state_key="annotation",
    annotation_tool_specs=PLAN_ANNOTATION_TOOL_SPECS,
)


class AnnotationViewWindow(DetachedPageViewWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, config=_ANNOTATION_WINDOW_CONFIG, **kwargs)
