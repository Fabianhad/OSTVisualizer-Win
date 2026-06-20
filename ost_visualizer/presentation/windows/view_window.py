from ..config import VIEW_WINDOW_TITLE
from ..modes.cursor import CURSOR_MODE_PAN
from .components.window import DetachedPageViewWindow, DetachedPageViewWindowConfig

_VIEW_WINDOW_CONFIG = DetachedPageViewWindowConfig(
    window_title=VIEW_WINDOW_TITLE,
    show_scale_combo=False,
    show_select_tool=False,
    default_cursor_mode=CURSOR_MODE_PAN,
    allow_annotation_editing=False,
    dropdown_state_key="view",
)


class ViewWindow(DetachedPageViewWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, config=_VIEW_WINDOW_CONFIG, **kwargs)
