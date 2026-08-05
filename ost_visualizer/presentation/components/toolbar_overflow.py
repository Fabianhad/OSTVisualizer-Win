from __future__ import annotations
from typing import Callable, Optional
from PySide6 import QtCore, QtGui, QtWidgets
from ..config import (
    VIEWER_OVERFLOW_COMBO_MIN_WIDTH,
    VIEWER_OVERFLOW_PAGE_SETTINGS_COMBO_MIN_WIDTH,
)

OverflowWidgetFactory = Callable[[QtWidgets.QWidget], QtWidgets.QWidget]


def add_overflow_widget(
    toolbar: QtWidgets.QToolBar,
    widget: QtWidgets.QWidget,
    *,
    overflow_factory: OverflowWidgetFactory,
    text: str,
    visibility_action: Optional[QtGui.QAction] = None,
) -> "ToolbarOverflowWidgetAction":
    action = ToolbarOverflowWidgetAction(
        widget,
        toolbar,
        overflow_factory=overflow_factory,
        text=text,
        visibility_action=visibility_action,
    )
    toolbar.addAction(action)
    return action


class ToolbarOverflowWidgetAction(QtWidgets.QWidgetAction):
    """A toolbar widget action that can also create a native overflow widget."""

    def __init__(
        self,
        toolbar_widget: QtWidgets.QWidget,
        parent: QtWidgets.QToolBar,
        *,
        overflow_factory: OverflowWidgetFactory,
        text: str,
        visibility_action: Optional[QtGui.QAction] = None,
    ) -> None:
        super().__init__(parent)
        self._toolbar_widget = toolbar_widget
        self._toolbar_widget.setParent(parent)
        self._overflow_factory = overflow_factory
        self._visibility_action = visibility_action
        self.setText(text)
        if visibility_action is not None:
            visibility_action.changed.connect(self._sync_visibility)
            self._sync_visibility()

    def _sync_visibility(self) -> None:
        self.setVisible(self._visibility_action.isVisible())

    def createWidget(self, parent: QtWidgets.QWidget) -> Optional[QtWidgets.QWidget]:
        if isinstance(parent, QtWidgets.QToolBar):
            return self._toolbar_widget
        widget = self._overflow_factory(parent)
        widget.setProperty("takeoffToolbarOverflowWidget", True)
        return widget


class SyncedComboOverflowWidget(QtWidgets.QWidget):
    """A labelled overflow combo synchronized with one canonical toolbar combo."""

    def __init__(
        self,
        source: QtWidgets.QComboBox,
        label: str,
        on_activated: Callable[[int], None],
        parent: Optional[QtWidgets.QWidget] = None,
        *,
        on_text_submitted: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent)
        self._source = source
        self._on_activated_callback = on_activated
        self._on_text_submitted_callback = on_text_submitted
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)
        layout.addWidget(QtWidgets.QLabel(label, self))
        self.combo = QtWidgets.QComboBox(self)
        self.combo.setObjectName(f"takeoffToolbarOverflow{label}Combo")
        self.combo.setMinimumWidth(
            max(VIEWER_OVERFLOW_COMBO_MIN_WIDTH, source.minimumWidth())
        )
        self.combo.setEditable(source.isEditable())
        self.combo.setInsertPolicy(source.insertPolicy())
        layout.addWidget(self.combo)
        self.setFocusProxy(self.combo)
        self.combo.activated.connect(self._on_activated)
        if self.combo.isEditable() and self.combo.lineEdit() is not None:
            self.combo.lineEdit().returnPressed.connect(self._on_return_pressed)
        source.currentIndexChanged.connect(self.sync_from_source)
        source.currentTextChanged.connect(self.sync_from_source)
        source.model().dataChanged.connect(self.sync_from_source)
        source.model().modelReset.connect(self.sync_from_source)
        source.model().rowsInserted.connect(self.sync_from_source)
        source.model().rowsRemoved.connect(self.sync_from_source)
        source.installEventFilter(self)
        self.sync_from_source()

    def eventFilter(self, watched, event) -> bool:
        if watched is self._source and event.type() in (
            QtCore.QEvent.Type.EnabledChange,
            QtCore.QEvent.Type.FontChange,
            QtCore.QEvent.Type.StyleChange,
        ):
            self.sync_from_source()
        return super().eventFilter(watched, event)

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        self.sync_from_source()
        super().showEvent(event)

    def sync_from_source(self, *_args) -> None:
        source = self._source
        combo = self.combo
        source_items = [
            (source.itemIcon(index), source.itemText(index), source.itemData(index))
            for index in range(source.count())
        ]
        current_items = [
            (combo.itemIcon(index), combo.itemText(index), combo.itemData(index))
            for index in range(combo.count())
        ]
        blocked = combo.blockSignals(True)
        try:
            if source_items != current_items:
                combo.clear()
                for icon, text, data in source_items:
                    combo.addItem(icon, text, data)
            combo.setEnabled(source.isEnabled())
            combo.setCurrentIndex(source.currentIndex())
            if combo.isEditable():
                combo.setEditText(source.currentText())
        finally:
            combo.blockSignals(blocked)

    def _on_activated(self, index: int) -> None:
        self._on_activated_callback(index)
        self.sync_from_source()

    def _on_return_pressed(self) -> None:
        if self._on_text_submitted_callback is None:
            return
        self._on_text_submitted_callback(self.combo.currentText())
        self.sync_from_source()


class PageSettingsOverflowWidget(QtWidgets.QWidget):
    """Overflow representation of the canonical scale and area controls."""

    _AREA_UID_ROLE = QtCore.Qt.ItemDataRole.UserRole

    def __init__(self, source, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._source = source
        layout = QtWidgets.QGridLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(4)
        layout.addWidget(QtWidgets.QLabel("Scale", self), 0, 0)
        self.scale_combo = QtWidgets.QComboBox(self)
        self.scale_combo.setObjectName("takeoffToolbarOverflowScaleCombo")
        self.scale_combo.setMinimumWidth(VIEWER_OVERFLOW_PAGE_SETTINGS_COMBO_MIN_WIDTH)
        layout.addWidget(self.scale_combo, 0, 1, 1, 2)
        layout.addWidget(QtWidgets.QLabel("Area", self), 1, 0)
        self.area_combo = QtWidgets.QComboBox(self)
        self.area_combo.setObjectName("takeoffToolbarOverflowAreaCombo")
        self.area_combo.setMinimumWidth(VIEWER_OVERFLOW_PAGE_SETTINGS_COMBO_MIN_WIDTH)
        layout.addWidget(self.area_combo, 1, 1)
        self.area_browse_button = QtWidgets.QPushButton("...", self)
        self.area_browse_button.setObjectName("takeoffToolbarOverflowAreaBrowse")
        self.area_browse_button.setFixedWidth(24)
        layout.addWidget(self.area_browse_button, 1, 2)
        self.setFocusProxy(self.scale_combo)
        self.scale_combo.activated.connect(self._on_scale_activated)
        self.area_combo.activated.connect(self._on_area_activated)
        self.area_browse_button.clicked.connect(self._on_area_browse)
        source.presentation_state_changed.connect(self.sync_from_source)
        self.sync_from_source()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        self.sync_from_source()
        super().showEvent(event)

    def sync_from_source(self, *_args) -> None:
        blocked = self.scale_combo.blockSignals(True)
        try:
            self.scale_combo.clear()
            for index in range(self._source.scale_combo.count()):
                self.scale_combo.addItem(
                    self._source.scale_combo.itemIcon(index),
                    self._source.scale_combo.itemText(index),
                    self._source.scale_combo.itemData(index),
                )
            self.scale_combo.setCurrentIndex(self._source.scale_combo.currentIndex())
            self.scale_combo.setEnabled(self._source.scale_combo.isEnabled())
        finally:
            self.scale_combo.blockSignals(blocked)
        blocked = self.area_combo.blockSignals(True)
        try:
            self.area_combo.clear()
            self._append_area_items(
                self._source.area_combo.popup_model(),
                QtCore.QModelIndex(),
                depth=0,
            )
            current_uid = self._source.area_combo.get_current_area_uid()
            self.area_combo.setCurrentIndex(
                self.area_combo.findData(current_uid, self._AREA_UID_ROLE)
            )
            self.area_combo.setEnabled(self._source.area_combo.isEnabled())
        finally:
            self.area_combo.blockSignals(blocked)
        self.area_browse_button.setEnabled(self._source.area_browse_btn.isEnabled())

    def _append_area_items(
        self,
        model: QtCore.QAbstractItemModel,
        parent: QtCore.QModelIndex,
        *,
        depth: int,
    ) -> None:
        for row in range(model.rowCount(parent)):
            index = model.index(row, 0, parent)
            text = str(index.data(QtCore.Qt.ItemDataRole.DisplayRole) or "")
            uid = index.data(self._AREA_UID_ROLE)
            icon = index.data(QtCore.Qt.ItemDataRole.DecorationRole)
            label = f"{'  ' * depth}{text}"
            if isinstance(icon, QtGui.QIcon):
                self.area_combo.addItem(icon, label, uid)
            else:
                self.area_combo.addItem(label, uid)
            font = index.data(QtCore.Qt.ItemDataRole.FontRole)
            if isinstance(font, QtGui.QFont):
                self.area_combo.setItemData(
                    self.area_combo.count() - 1,
                    font,
                    QtCore.Qt.ItemDataRole.FontRole,
                )
            self._append_area_items(model, index, depth=depth + 1)

    def _on_scale_activated(self, index: int) -> None:
        source_combo = self._source.scale_combo
        source_combo.setCurrentIndex(index)
        source_combo.activated.emit(index)
        self.sync_from_source()

    def _on_area_activated(self, index: int) -> None:
        uid = self.area_combo.itemData(index, self._AREA_UID_ROLE)
        target_uid = str(uid or "")
        self._source.area_combo.set_current_area_uid(target_uid)
        self._source.area_combo.area_activated.emit(target_uid)
        self.sync_from_source()

    def _on_area_browse(self) -> None:
        self._source.area_browse_btn.click()
        self.sync_from_source()
