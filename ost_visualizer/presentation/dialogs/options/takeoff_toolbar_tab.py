from PySide6 import QtCore, QtWidgets
from ....domain.entities.config import Config
from ...config import NO_MARGINS, RELAXED_MARGINS, RELAXED_SPACING
from ...utils.plan_tool_registry import TAKEOFF_TOOLBAR_ITEMS


class TakeoffToolbarTab(QtWidgets.QWidget):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._unknown_hidden: tuple[str, ...] = ()
        self.checks: dict[str, QtWidgets.QCheckBox] = {}
        outer_layout = QtWidgets.QVBoxLayout(self)
        outer_layout.setContentsMargins(*NO_MARGINS)
        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        content = QtWidgets.QWidget(scroll)
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(*RELAXED_MARGINS)
        layout.setSpacing(RELAXED_SPACING)
        groups = QtWidgets.QGridLayout()
        groups.setSpacing(RELAXED_SPACING)
        layout.addLayout(groups)
        for index, group in enumerate(
            dict.fromkeys(spec.group for spec in TAKEOFF_TOOLBAR_ITEMS)
        ):
            box = QtWidgets.QGroupBox(group, content)
            group_layout = QtWidgets.QVBoxLayout(box)
            for spec in TAKEOFF_TOOLBAR_ITEMS:
                if spec.group != group:
                    continue
                check = QtWidgets.QCheckBox(spec.label, box)
                check.setObjectName(f"takeoff_toolbar_{spec.key}")
                check.toggled.connect(self.changed)
                self.checks[spec.key] = check
                group_layout.addWidget(check)
            groups.addWidget(
                box, index // 2, index % 2, alignment=QtCore.Qt.AlignmentFlag.AlignTop
            )
        self.restore_button = QtWidgets.QPushButton("Restore Default Toolbar", content)
        self.restore_button.clicked.connect(self.restore_defaults)
        layout.addWidget(
            self.restore_button, alignment=QtCore.Qt.AlignmentFlag.AlignLeft
        )
        layout.addStretch(1)
        scroll.setWidget(content)
        outer_layout.addWidget(scroll)

    def load_hidden_items(self, hidden: tuple[str, ...]) -> None:
        self._unknown_hidden = tuple(key for key in hidden if key not in self.checks)
        with QtCore.QSignalBlocker(self):
            for key, check in self.checks.items():
                check.setChecked(key not in hidden)

    def hidden_items(self) -> tuple[str, ...]:
        return Config.normalize_hidden_toolbar_items(
            [
                *self._unknown_hidden,
                *(key for key, check in self.checks.items() if not check.isChecked()),
            ]
        )

    def restore_defaults(self) -> None:
        self.load_hidden_items(())
        self.changed.emit()
