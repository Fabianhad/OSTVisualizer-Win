from collections.abc import Callable
from PySide6 import QtCore, QtGui, QtWidgets
from .mesh_view import OpenGLViewer
from .plan_view.view import TakeoffPlanView
from .popup_tracking_combo import update_zoom_combo


def scene_navigation_available(
    viewer: OpenGLViewer,
    view_stack: QtWidgets.QStackedWidget | None = None,
    plan_view: TakeoffPlanView | None = None,
) -> bool:
    if view_stack is not None and view_stack.currentIndex() != 0:
        return bool(plan_view is not None and plan_view.current_page_uid)
    return viewer.has_renderable_content


class SceneNavigationControls(QtCore.QObject):
    def __init__(
        self,
        viewer: OpenGLViewer,
        actions: list[QtGui.QAction],
        zoom_combo: QtWidgets.QComboBox,
        parent: QtCore.QObject,
        view_stack: QtWidgets.QStackedWidget | None = None,
        refresh_zoom_fn: Callable[[], None] | None = None,
        plan_view: TakeoffPlanView | None = None,
    ) -> None:
        super().__init__(parent)
        self._viewer = viewer
        self._actions = actions
        self._zoom_combo = zoom_combo
        self._view_stack = view_stack
        self._plan_view = plan_view
        self._refresh_zoom_fn = refresh_zoom_fn
        self._projected_context: tuple[bool, bool] | None = None
        viewer.scene_content_changed.connect(self.refresh)
        if view_stack is not None:
            view_stack.currentChanged.connect(self.refresh)
        if plan_view is not None:
            plan_view.page_geometry_ready.connect(self.refresh)
            plan_view.page_cleared.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        is_3d = self._view_stack is None or self._view_stack.currentIndex() == 0
        available = scene_navigation_available(
            self._viewer, self._view_stack, self._plan_view
        )
        context = (is_3d, available)
        if context == self._projected_context:
            return
        self._projected_context = context
        for action in self._actions:
            action.setEnabled(available)
        self._zoom_combo.setEnabled(available)
        if available:
            if self._refresh_zoom_fn is not None:
                self._refresh_zoom_fn()
            elif is_3d:
                update_zoom_combo(
                    self._zoom_combo, self._viewer.get_zoom_percent() / 100.0
                )
        else:
            with QtCore.QSignalBlocker(self._zoom_combo):
                self._zoom_combo.setCurrentIndex(-1)
                self._zoom_combo.setEditText("")
