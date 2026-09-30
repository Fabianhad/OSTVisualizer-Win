import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView


class FakeTrackingViewport:
    def __init__(self):
        self.tracking = []
        self.updates = 0

    def setMouseTracking(self, enabled):
        self.tracking.append(enabled)

    def update(self):
        self.updates += 1


def _plan_view_with_tracking_viewport(cursor_mode="select"):
    viewport = FakeTrackingViewport()
    view = TakeoffPlanView.__new__(TakeoffPlanView)
    view.viewport = lambda: viewport
    view._cursor_mode = cursor_mode
    view._tool_revision = 0
    view._tool_state = (cursor_mode, None, None)
    view._annotation_place_type = None
    view._place_session_uid = None
    view._use_full_window_crosshairs = False
    view._pdf_text_runs = []
    view._persistent_cursor_mode = cursor_mode
    view._right_pan_active = False
    view._pre_zoom_persistent_mode = None
    view._update_cursor = lambda: None
    return view, viewport
