from dataclasses import dataclass
from typing import Callable, List, Optional
from PySide6 import QtCore, QtWidgets
from ..config import (
    COMPACT_MARGINS,
    COMPACT_SPACING,
    RENAME_PAGE_WINDOW_WIDTH,
)
from ..utils.messagebox import show_warning
from ..utils.windows import remove_minimize_maximize, set_fixed_width_auto_height

_NAV_BUTTON_WIDTH = 100


@dataclass(frozen=True)
class PageRenameTarget:
    uid: str
    name: str


class RenamePageDialog(QtWidgets.QDialog):
    def __init__(
        self,
        icon_provider,
        parent: Optional[QtWidgets.QWidget],
        pages: List[PageRenameTarget],
        current_page_uid: str,
        save_fn: Callable[[str, str], bool],
    ) -> None:
        super().__init__(parent)
        self._icon_provider = icon_provider
        self._pages = list(pages)
        self._save_fn = save_fn
        self._current_index = self._resolve_current_index(current_page_uid)
        self._setup_ui()
        self._load_current_page()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Rename Page")
        self.setModal(True)
        remove_minimize_maximize(self)
        if self._icon_provider:
            self._icon_provider.set_window_icon(self)
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(*COMPACT_MARGINS)
        main_layout.setSpacing(COMPACT_SPACING)
        form = QtWidgets.QGridLayout()
        form.setSpacing(COMPACT_SPACING)
        form.setColumnStretch(1, 1)
        form.addWidget(
            QtWidgets.QLabel("Old Name:"),
            0,
            0,
            alignment=QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignVCenter,
        )
        self._old_name_edit = QtWidgets.QLineEdit()
        self._old_name_edit.setReadOnly(True)
        form.addWidget(self._old_name_edit, 0, 1)
        self._ok_btn = QtWidgets.QPushButton("OK")
        self._ok_btn.setDefault(True)
        self._ok_btn.clicked.connect(self._on_ok)
        form.addWidget(self._ok_btn, 0, 2)
        form.addWidget(
            QtWidgets.QLabel("New Name:"),
            1,
            0,
            alignment=QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignVCenter,
        )
        self._new_name_edit = QtWidgets.QLineEdit()
        form.addWidget(self._new_name_edit, 1, 1)
        self._cancel_btn = QtWidgets.QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        form.addWidget(self._cancel_btn, 1, 2)
        main_layout.addLayout(form)
        nav_layout = QtWidgets.QHBoxLayout()
        self._previous_btn = QtWidgets.QPushButton("Previous Page")
        self._next_btn = QtWidgets.QPushButton("Next Page")
        self._previous_btn.setFixedWidth(_NAV_BUTTON_WIDTH)
        self._next_btn.setFixedWidth(_NAV_BUTTON_WIDTH)
        self._previous_btn.clicked.connect(self._go_previous)
        self._next_btn.clicked.connect(self._go_next)
        nav_layout.addWidget(self._previous_btn)
        nav_layout.addWidget(self._next_btn)
        main_layout.addLayout(nav_layout)
        set_fixed_width_auto_height(self, RENAME_PAGE_WINDOW_WIDTH)

    def _resolve_current_index(self, current_page_uid: str) -> int:
        for index, page in enumerate(self._pages):
            if page.uid == current_page_uid:
                return index
        return 0

    def _current_page(self) -> Optional[PageRenameTarget]:
        if 0 <= self._current_index < len(self._pages):
            return self._pages[self._current_index]
        return None

    def _go_previous(self, *_args) -> None:
        self._go(-1)

    def _go_next(self, *_args) -> None:
        self._go(1)

    def _load_current_page(self) -> None:
        page = self._current_page()
        name = page.name if page else ""
        self._old_name_edit.setText(name)
        self._new_name_edit.setText(name)
        self._update_nav_buttons()
        self._select_new_name()

    def _update_nav_buttons(self) -> None:
        count = len(self._pages)
        self._previous_btn.setEnabled(count > 1 and self._current_index > 0)
        self._next_btn.setEnabled(count > 1 and self._current_index < count - 1)

    def _go(self, direction: int) -> None:
        target_index = self._current_index + direction
        if 0 <= target_index < len(self._pages):
            self._current_index = target_index
            self._load_current_page()

    def _select_new_name(self) -> None:
        self._new_name_edit.selectAll()
        if self._new_name_edit.isEnabled():
            self._new_name_edit.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)

    def _on_ok(self) -> None:
        page = self._current_page()
        if not page:
            self.reject()
            return
        new_name = self._new_name_edit.text().strip()
        if not new_name:
            show_warning(self, "Validation Error", "Page name cannot be empty.")
            self._select_new_name()
            return
        if new_name == page.name:
            self.accept()
            return
        if not self._save_fn(page.uid, new_name):
            show_warning(self, "Save Failed", "Failed to rename page.")
            return
        self.accept()

    def set_interactive(self, enabled: bool) -> None:
        interactive = bool(enabled)
        self._new_name_edit.setEnabled(interactive)
        self._ok_btn.setEnabled(interactive)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self._select_new_name)
