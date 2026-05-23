from .components.window import DetachedPageViewWindow, DetachedPageViewWindowConfig

_ANNOTATION_WINDOW_CONFIG = DetachedPageViewWindowConfig(
    window_title="Annotation Window",
    show_scale_combo=True,
    show_select_tool=True,
    default_cursor_mode="select",
    allow_annotation_editing=True,
    dropdown_state_key="annotation",
)


class AnnotationViewWindow(DetachedPageViewWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, config=_ANNOTATION_WINDOW_CONFIG, **kwargs)
