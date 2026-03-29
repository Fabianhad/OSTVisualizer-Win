from ..windows.view_window import ViewWindow
from .detached_page_view_manager import DetachedPageViewManager


class QtViewWindowManager(DetachedPageViewManager):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, window_factory=ViewWindow, **kwargs)
