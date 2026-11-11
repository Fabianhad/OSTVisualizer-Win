from PySide6 import QtCore, QtWidgets
from ..config import (
    COMPACT_SPACING,
    SECTION_CUT_EAST_WEST_LABEL,
    SECTION_CUT_EAST_WEST_TOOLTIP,
    SECTION_CUT_NORTH_SOUTH_LABEL,
    SECTION_CUT_NORTH_SOUTH_TOOLTIP,
    SECTION_CUT_OFF_TEXT,
)
from .edges_toggle import EdgesToggle
from .mesh_view import SECTION_CUT_EAST_WEST, SECTION_CUT_NORTH_SOUTH, OpenGLViewer
from .tower_crane_toggle import TowerCraneToggle

SECTION_CUT_SLIDER_STEPS = 1000
_CUTS = (
    (
        SECTION_CUT_NORTH_SOUTH,
        SECTION_CUT_NORTH_SOUTH_LABEL,
        SECTION_CUT_NORTH_SOUTH_TOOLTIP,
    ),
    (SECTION_CUT_EAST_WEST, SECTION_CUT_EAST_WEST_LABEL, SECTION_CUT_EAST_WEST_TOOLTIP),
)


def format_section_cut_value(offset_feet) -> str:
    if offset_feet is None:
        return SECTION_CUT_OFF_TEXT
    return f"{offset_feet:,.1f}'"


class SectionCutControls(QtWidgets.QWidget):
    def __init__(self, viewer: OpenGLViewer, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self._viewer = viewer
        self._sliders: dict[str, QtWidgets.QSlider] = {}
        self._values: dict[str, QtWidgets.QLabel] = {}
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(COMPACT_SPACING)
        for position, (cut, label, tooltip) in enumerate(_CUTS):
            if position:
                layout.addSpacing(16)
            title = QtWidgets.QLabel(label, self)
            slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal, self)
            slider.setRange(0, SECTION_CUT_SLIDER_STEPS)
            slider.setValue(SECTION_CUT_SLIDER_STEPS)
            slider.setMinimumWidth(120)
            slider.setToolTip(tooltip)
            slider.setAccessibleName(label)
            title.setBuddy(slider)
            value = QtWidgets.QLabel(SECTION_CUT_OFF_TEXT, self)
            value.setMinimumWidth(value.fontMetrics().horizontalAdvance("0,000.0'") + 4)
            value.setAlignment(
                QtCore.Qt.AlignmentFlag.AlignRight
                | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
            slider.valueChanged.connect(
                lambda position, cut=cut: self._on_slider_moved(cut, position)
            )
            layout.addWidget(title)
            layout.addWidget(slider, 1)
            layout.addWidget(value)
            self._sliders[cut] = slider
            self._values[cut] = value
        layout.addSpacing(16)
        self.edges_toggle = EdgesToggle(viewer, self)
        layout.addWidget(self.edges_toggle)
        self.tower_crane_toggle = TowerCraneToggle(viewer, self)
        layout.addWidget(self.tower_crane_toggle)
        viewer.scene_content_changed.connect(self.refresh)
        self.refresh()

    def slider(self, cut: str) -> QtWidgets.QSlider:
        return self._sliders[cut]

    def value_text(self, cut: str) -> str:
        return self._values[cut].text()

    def refresh(self) -> None:
        for cut, slider in self._sliders.items():
            position = round(
                self._viewer.section_cut_fraction(cut) * SECTION_CUT_SLIDER_STEPS
            )
            if slider.value() != position:
                slider.blockSignals(True)
                slider.setValue(position)
                slider.blockSignals(False)
            self._refresh_value(cut)

    def _on_slider_moved(self, cut: str, position: int) -> None:
        self._viewer.set_section_cut(cut, position / SECTION_CUT_SLIDER_STEPS)
        self._refresh_value(cut)

    def _refresh_value(self, cut: str) -> None:
        self._values[cut].setText(
            format_section_cut_value(self._viewer.section_cut_offset_feet(cut))
        )
