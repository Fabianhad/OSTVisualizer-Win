from PySide6 import QtWidgets
from ..config import TOWER_CRANE_TOGGLE_LABEL, TOWER_CRANE_TOGGLE_TOOLTIP
from .mesh_view import OpenGLViewer


class TowerCraneToggle(QtWidgets.QCheckBox):
    def __init__(self, viewer: OpenGLViewer, parent: QtWidgets.QWidget | None = None):
        super().__init__(TOWER_CRANE_TOGGLE_LABEL, parent)
        self._viewer = viewer
        self.setToolTip(TOWER_CRANE_TOGGLE_TOOLTIP)
        self.setChecked(viewer.tower_crane_visible())
        self.toggled.connect(viewer.request_tower_crane_visible)
        viewer.scene_content_changed.connect(self.refresh)
        viewer.view_options_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self.setEnabled(self._viewer.tower_crane_count() > 0)
        if self.isChecked() != self._viewer.tower_crane_visible():
            self.blockSignals(True)
            self.setChecked(self._viewer.tower_crane_visible())
            self.blockSignals(False)
