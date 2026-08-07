from __future__ import annotations
from dataclasses import replace
from PySide6 import QtCore, QtGui, QtWidgets
from ....domain.entities.config import Config
from ....domain.entities.font_definition import FontDefinition
from ...config import COMPACT_SPACING, DIALOG_BUTTON_WIDTH, RELAXED_SPACING
from ...utils.color_swatch import rounded_color_swatch
from ...utils.font_catalog import (
    qfont_from_resolved_definition,
    resolve_font_definition,
)
from ...utils.windows import remove_minimize_maximize
from .font_dialog import FontDialog

FONT_CATEGORY_TEXT = "text"
FONT_CATEGORY_AREA_LABEL = "area_label"
FONT_CATEGORY_DIMENSION_LINE = "dimension_line"
FONT_CATEGORY_DEFAULT_STYLE_LABEL = "default_style_label"
COLOR_CATEGORY_TEXT = "text"
COLOR_CATEGORY_AREA_LABEL = "area_label"
COLOR_CATEGORY_DEFAULT_STYLE_LABEL = "default_style_label"
COLOR_CATEGORY_HIGHLIGHT = "highlight"
COLOR_CATEGORY_HOTLINK = "hotlink"
COLOR_CATEGORY_INACTIVE_OBJECTS = "inactive_objects"
FONT_CATEGORIES = (
    (FONT_CATEGORY_TEXT, "Text"),
    (FONT_CATEGORY_AREA_LABEL, "Area Label"),
    (FONT_CATEGORY_DIMENSION_LINE, "Dimension Line"),
    (FONT_CATEGORY_DEFAULT_STYLE_LABEL, "Default Style Label"),
)
COLOR_CATEGORIES = (
    (COLOR_CATEGORY_TEXT, "Text"),
    (COLOR_CATEGORY_AREA_LABEL, "Area Label"),
    (COLOR_CATEGORY_DEFAULT_STYLE_LABEL, "Default Style Label"),
    (COLOR_CATEGORY_HIGHLIGHT, "Highlight"),
    (COLOR_CATEGORY_HOTLINK, "Hot Link"),
    (COLOR_CATEGORY_INACTIVE_OBJECTS, "Inactive Objects"),
)


class FontsColorsTab(QtWidgets.QWidget):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fonts: dict[str, FontDefinition] = {}
        self._colors: dict[str, str] = {}
        self._build_ui()

    def load_config(self, config: Config) -> None:
        self._fonts = {
            FONT_CATEGORY_TEXT: config.default_text_font,
            FONT_CATEGORY_AREA_LABEL: config.default_area_label_font,
            FONT_CATEGORY_DIMENSION_LINE: config.default_dimension_annotation_font,
            FONT_CATEGORY_DEFAULT_STYLE_LABEL: config.default_style_label_font,
        }
        self._colors = {
            COLOR_CATEGORY_TEXT: config.default_text_color,
            COLOR_CATEGORY_AREA_LABEL: config.default_area_label_color,
            COLOR_CATEGORY_DEFAULT_STYLE_LABEL: config.default_style_label_color,
            COLOR_CATEGORY_HIGHLIGHT: config.default_highlight_color,
            COLOR_CATEGORY_HOTLINK: config.default_hotlink_color,
            COLOR_CATEGORY_INACTIVE_OBJECTS: config.inactive_object_color,
        }
        if self.font_list.currentRow() < 0:
            self.font_list.setCurrentRow(0)
        if self.color_list.currentRow() < 0:
            self.color_list.setCurrentRow(0)
        self._refresh_font_preview()
        self._refresh_color_preview()

    def apply_to_config(self, config: Config) -> Config:
        return replace(
            config,
            default_text_font=self._fonts[FONT_CATEGORY_TEXT],
            default_area_label_font=self._fonts[FONT_CATEGORY_AREA_LABEL],
            default_dimension_annotation_font=self._fonts[FONT_CATEGORY_DIMENSION_LINE],
            default_style_label_font=self._fonts[FONT_CATEGORY_DEFAULT_STYLE_LABEL],
            default_text_color=self._colors[COLOR_CATEGORY_TEXT],
            default_area_label_color=self._colors[COLOR_CATEGORY_AREA_LABEL],
            default_style_label_color=self._colors[COLOR_CATEGORY_DEFAULT_STYLE_LABEL],
            default_highlight_color=self._colors[COLOR_CATEGORY_HIGHLIGHT],
            default_hotlink_color=self._colors[COLOR_CATEGORY_HOTLINK],
            inactive_object_color=self._colors[COLOR_CATEGORY_INACTIVE_OBJECTS],
        )

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(RELAXED_SPACING)
        layout.addWidget(self._build_font_group())
        layout.addWidget(self._build_color_group())
        layout.addStretch(1)

    def _build_font_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Default Font", self)
        group_layout = QtWidgets.QHBoxLayout(group)
        group_layout.setSpacing(RELAXED_SPACING)
        self.font_list = self._category_list(FONT_CATEGORIES, group)
        self.font_list.setObjectName("defaultFontCategoryList")
        group_layout.addWidget(self.font_list, 1)
        preview_layout = QtWidgets.QVBoxLayout()
        preview_layout.setSpacing(COMPACT_SPACING)
        self.font_preview = QtWidgets.QLabel(group)
        self.font_preview.setObjectName("defaultFontPreview")
        self.font_preview.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.font_preview.setFrameShape(QtWidgets.QFrame.Shape.Panel)
        self.font_preview.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        self.change_font_button = QtWidgets.QPushButton("Change Font", group)
        self.change_font_button.setMinimumWidth(DIALOG_BUTTON_WIDTH)
        preview_layout.addWidget(self.font_preview, 1)
        preview_layout.addWidget(
            self.change_font_button, 0, QtCore.Qt.AlignmentFlag.AlignHCenter
        )
        group_layout.addLayout(preview_layout, 1)
        self.font_list.currentRowChanged.connect(self._refresh_font_preview)
        self.change_font_button.clicked.connect(self._change_font)
        return group

    def _build_color_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Default Color", self)
        group_layout = QtWidgets.QHBoxLayout(group)
        group_layout.setSpacing(RELAXED_SPACING)
        self.color_list = self._category_list(COLOR_CATEGORIES, group)
        self.color_list.setObjectName("defaultColorCategoryList")
        group_layout.addWidget(self.color_list, 1)
        preview_layout = QtWidgets.QVBoxLayout()
        preview_layout.setSpacing(COMPACT_SPACING)
        self.color_preview = QtWidgets.QLabel(group)
        self.color_preview.setObjectName("defaultColorPreview")
        self.color_preview.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.color_preview.setFrameShape(QtWidgets.QFrame.Shape.Panel)
        self.color_preview.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        self.change_color_button = QtWidgets.QPushButton("Change Color", group)
        self.change_color_button.setMinimumWidth(DIALOG_BUTTON_WIDTH)
        preview_layout.addWidget(self.color_preview, 1)
        preview_layout.addWidget(
            self.change_color_button, 0, QtCore.Qt.AlignmentFlag.AlignHCenter
        )
        group_layout.addLayout(preview_layout, 1)
        self.color_list.currentRowChanged.connect(self._refresh_color_preview)
        self.change_color_button.clicked.connect(self._change_color)
        return group

    @staticmethod
    def _category_list(categories, parent) -> QtWidgets.QListWidget:
        widget = QtWidgets.QListWidget(parent)
        for category_id, label in categories:
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, category_id)
            widget.addItem(item)
        widget.setCurrentRow(0)
        return widget

    @staticmethod
    def _selected_category(widget: QtWidgets.QListWidget) -> str | None:
        item = widget.currentItem()
        if item is None:
            return None
        category_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if not isinstance(category_id, str) or not category_id:
            raise RuntimeError("Options category item is missing its stable ID")
        return category_id

    def _refresh_font_preview(self, *_args) -> None:
        category_id = self._selected_category(self.font_list)
        if category_id is None:
            self.font_preview.clear()
            return
        definition = self._fonts[category_id]
        resolved = resolve_font_definition(definition)
        self.font_preview.setFont(qfont_from_resolved_definition(resolved))
        self.font_preview.setText(
            f"AaBbYyZz\n{resolved.family}, {resolved.style_name}, "
            f"{resolved.point_size} pt"
        )

    def _refresh_color_preview(self, *_args) -> None:
        category_id = self._selected_category(self.color_list)
        if category_id is None:
            self.color_preview.clear()
            return
        color = self._colors[category_id]
        swatch_size = self.style().pixelMetric(
            QtWidgets.QStyle.PixelMetric.PM_LargeIconSize, None, self
        )
        pixmap = rounded_color_swatch(QtGui.QColor(color), swatch_size)
        self.color_preview.setPixmap(pixmap)
        self.color_preview.setToolTip(color)

    def _change_font(self) -> None:
        category_id = self._selected_category(self.font_list)
        if category_id is None:
            return
        dialog = FontDialog(self._fonts[category_id], self.change_font_button)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        selected = dialog.selected_font()
        if selected is None or selected == self._fonts[category_id]:
            return
        self._fonts[category_id] = selected
        self._refresh_font_preview()
        self.changed.emit()

    def _change_color(self) -> None:
        category_id = self._selected_category(self.color_list)
        if category_id is None:
            return
        current = self._colors[category_id]
        dialog = QtWidgets.QColorDialog(QtGui.QColor(current), self.change_color_button)
        dialog.setWindowTitle("Color")
        remove_minimize_maximize(dialog)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        selected = dialog.currentColor()
        if not selected.isValid():
            return
        color = selected.name().lower()
        if color == current:
            return
        self._colors[category_id] = color
        self._refresh_color_preview()
        self.changed.emit()
