from ...application.interfaces.i_annotation_view_manager import IAnnotationViewManager
from ..windows.annotation_view_window import AnnotationViewWindow
from .detached_page_view_manager import DetachedPageViewManager


class QtAnnotationViewManager(DetachedPageViewManager, IAnnotationViewManager):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, window_factory=AnnotationViewWindow, **kwargs)
