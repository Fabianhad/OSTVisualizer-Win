from PySide6 import QtGui, QtWidgets
from ....application.dtos.annotation_caption_dto import ANNOTATION_CAPTION_SPECS
from ....domain.entities.annotation_caption import (
    ANNOTATION_CAPTION_ORDER,
    AnnotationCaptionId,
)
from ...components.color_button import ColorButton
from ...config import (
    COMPACT_SPACING,
    OPTIONS_GROUP_ELEVATION_CALLOUTS,
    OPTIONS_GROUP_PDF_ANNOTATION_CAPTIONS,
    OPTIONS_LABEL_ELEVATION_CALLOUT_BOTTOM,
    OPTIONS_LABEL_ELEVATION_CALLOUT_CONDITION,
    OPTIONS_LABEL_ELEVATION_CALLOUT_CUBIC_YARDS,
    OPTIONS_LABEL_ELEVATION_CALLOUT_TOP,
    OPTIONS_LABEL_ENABLE_PDF_ANNOTATION_CAPTIONS,
    OPTIONS_LABEL_HTML_ELEVATION_CALLOUT_COLOR,
    OPTIONS_LABEL_INCLUDE_HTML_ELEVATION_CALLOUTS,
    OPTIONS_LABEL_INCLUDE_PDF_ELEVATION_CALLOUTS,
    OPTIONS_LABEL_PDF_ELEVATION_CALLOUT_COLOR,
    RELAXED_SPACING,
)


class ExportTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.caption_checks: dict[AnnotationCaptionId, QtWidgets.QCheckBox] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(RELAXED_SPACING)
        group = QtWidgets.QGroupBox(OPTIONS_GROUP_PDF_ANNOTATION_CAPTIONS, self)
        group_layout = QtWidgets.QVBoxLayout(group)
        group_layout.setSpacing(COMPACT_SPACING)
        self.captions_enabled_check = QtWidgets.QCheckBox(
            OPTIONS_LABEL_ENABLE_PDF_ANNOTATION_CAPTIONS,
            group,
        )
        group_layout.addWidget(self.captions_enabled_check)
        caption_layout = QtWidgets.QVBoxLayout()
        caption_layout.setContentsMargins(24, 0, 0, 0)
        caption_layout.setSpacing(COMPACT_SPACING)
        for caption_id in ANNOTATION_CAPTION_ORDER:
            spec = ANNOTATION_CAPTION_SPECS[caption_id]
            check = QtWidgets.QCheckBox(spec.title, group)
            self.caption_checks[caption_id] = check
            caption_layout.addWidget(check)
        group_layout.addLayout(caption_layout)
        layout.addWidget(group)
        callout_group = QtWidgets.QGroupBox(OPTIONS_GROUP_ELEVATION_CALLOUTS, self)
        callout_layout = QtWidgets.QVBoxLayout(callout_group)
        callout_layout.setSpacing(COMPACT_SPACING)
        self.html_elevation_callouts_check = QtWidgets.QCheckBox(
            OPTIONS_LABEL_INCLUDE_HTML_ELEVATION_CALLOUTS,
            callout_group,
        )
        self.pdf_elevation_callouts_check = QtWidgets.QCheckBox(
            OPTIONS_LABEL_INCLUDE_PDF_ELEVATION_CALLOUTS,
            callout_group,
        )
        self.elevation_callout_condition_check = QtWidgets.QCheckBox(
            OPTIONS_LABEL_ELEVATION_CALLOUT_CONDITION,
            callout_group,
        )
        self.elevation_callout_top_check = QtWidgets.QCheckBox(
            OPTIONS_LABEL_ELEVATION_CALLOUT_TOP,
            callout_group,
        )
        self.elevation_callout_bottom_check = QtWidgets.QCheckBox(
            OPTIONS_LABEL_ELEVATION_CALLOUT_BOTTOM,
            callout_group,
        )
        self.elevation_callout_cubic_yards_check = QtWidgets.QCheckBox(
            OPTIONS_LABEL_ELEVATION_CALLOUT_CUBIC_YARDS,
            callout_group,
        )
        self.callout_content_checks = (
            self.elevation_callout_condition_check,
            self.elevation_callout_top_check,
            self.elevation_callout_bottom_check,
            self.elevation_callout_cubic_yards_check,
        )
        self.html_elevation_callout_color_button = ColorButton(
            QtGui.QColor("#00ff00"),
            callout_group,
            show_color_tooltip=True,
            dialog_title=OPTIONS_LABEL_HTML_ELEVATION_CALLOUT_COLOR,
        )
        self.pdf_elevation_callout_color_button = ColorButton(
            QtGui.QColor("#00ff00"),
            callout_group,
            show_color_tooltip=True,
            dialog_title=OPTIONS_LABEL_PDF_ELEVATION_CALLOUT_COLOR,
        )
        callout_layout.addWidget(self.html_elevation_callouts_check)
        callout_layout.addWidget(self.pdf_elevation_callouts_check)
        content_layout = QtWidgets.QVBoxLayout()
        content_layout.setContentsMargins(24, 0, 0, 0)
        content_layout.setSpacing(COMPACT_SPACING)
        for check in self.callout_content_checks:
            content_layout.addWidget(check)
        callout_layout.addLayout(content_layout)
        color_layout = QtWidgets.QFormLayout()
        color_layout.setContentsMargins(24, 0, 0, 0)
        color_layout.setSpacing(COMPACT_SPACING)
        color_layout.addRow(
            OPTIONS_LABEL_HTML_ELEVATION_CALLOUT_COLOR,
            self.html_elevation_callout_color_button,
        )
        color_layout.addRow(
            OPTIONS_LABEL_PDF_ELEVATION_CALLOUT_COLOR,
            self.pdf_elevation_callout_color_button,
        )
        callout_layout.addLayout(color_layout)
        layout.addWidget(callout_group)
        layout.addStretch(1)
        self.captions_enabled_check.toggled.connect(self._update_caption_checks_enabled)
        self.html_elevation_callouts_check.toggled.connect(
            self.update_callout_controls_enabled
        )
        self.pdf_elevation_callouts_check.toggled.connect(
            self.update_callout_controls_enabled
        )
        self._update_caption_checks_enabled(False)
        self.update_callout_controls_enabled()

    def _update_caption_checks_enabled(self, enabled: bool) -> None:
        for check in self.caption_checks.values():
            check.setEnabled(enabled)

    def update_callout_controls_enabled(self, *_args) -> None:
        html_enabled = self.html_elevation_callouts_check.isChecked()
        pdf_enabled = self.pdf_elevation_callouts_check.isChecked()
        content_enabled = html_enabled or pdf_enabled
        for check in self.callout_content_checks:
            check.setEnabled(content_enabled)
        self.html_elevation_callout_color_button.setEnabled(html_enabled)
        self.pdf_elevation_callout_color_button.setEnabled(pdf_enabled)
