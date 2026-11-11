from PySide6 import QtWidgets
from ..config import EDGES_TOGGLE_LABEL, EDGES_TOGGLE_TOOLTIP
from .mesh_view import OpenGLViewer


class EdgesToggle(QtWidgets.QCheckBox):
    def __init__(self, viewer: OpenGLViewer, parent: QtWidgets.QWidget | None = None):
        super().__init__(EDGES_TOGGLE_LABEL, parent)
        self._viewer = viewer
        self.setToolTip(EDGES_TOGGLE_TOOLTIP)
        self.setChecked(viewer.edges_visible())
        self.toggled.connect(viewer.request_edges_visible)
        viewer.view_options_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        if self.isChecked() != self._viewer.edges_visible():
            self.blockSignals(True)
            self.setChecked(self._viewer.edges_visible())
            self.blockSignals(False)
