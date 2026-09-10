from PySide6 import QtCore, QtWidgets
from ....domain.entities.config import Config
from ...config import COMPACT_SPACING, RELAXED_SPACING
from ...utils.plan_tool_registry import TAKEOFF_TOOLBAR_ITEMS


class TakeoffToolbarTab(QtWidgets.QWidget):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._unknown_hidden: tuple[str, ...] = ()
        self.checks: dict[str, QtWidgets.QCheckBox] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        tab_layout = QtWidgets.QVBoxLayout(self)
        tab_layout.setSpacing(RELAXED_SPACING)
        annotation_group = self._build_group("Annotation tools", columns=2)
        tab_layout.addWidget(annotation_group)
        lower_layout = QtWidgets.QHBoxLayout()
        lower_layout.setSpacing(RELAXED_SPACING)
        lower_left_layout = QtWidgets.QVBoxLayout()
        lower_right_layout = QtWidgets.QVBoxLayout()
        lower_layout.addLayout(lower_left_layout, 1)
        lower_layout.addLayout(lower_right_layout, 1)
        lower_left_layout.addWidget(self._build_group("Page navigation"))
        lower_left_layout.addWidget(self._build_group("Cursor tools"))
        lower_right_layout.addWidget(self._build_group("View controls"))
        lower_right_layout.addWidget(self._build_group("Page Settings"))
        lower_left_layout.addStretch()
        lower_right_layout.addStretch()
        tab_layout.addLayout(lower_layout)
        self.restore_button = QtWidgets.QPushButton("Restore Default Toolbar", self)
        self.restore_button.clicked.connect(self.restore_defaults)
        tab_layout.addWidget(
            self.restore_button, alignment=QtCore.Qt.AlignmentFlag.AlignLeft
        )
        tab_layout.addStretch()

    def _build_group(self, group_name: str, *, columns: int = 1) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox(group_name)
        group.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        layout = QtWidgets.QHBoxLayout(group)
        layout.setSpacing(RELAXED_SPACING)
        column_layouts = [QtWidgets.QVBoxLayout() for _ in range(columns)]
        for column_layout in column_layouts:
            column_layout.setSpacing(COMPACT_SPACING)
            layout.addLayout(column_layout, 1)
        specs = tuple(
            spec for spec in TAKEOFF_TOOLBAR_ITEMS if spec.group == group_name
        )
        rows_per_column = (len(specs) + columns - 1) // columns
        for index, spec in enumerate(specs):
            check = QtWidgets.QCheckBox(spec.label, group)
            check.setObjectName(f"takeoff_toolbar_{spec.key}")
            check.toggled.connect(self.changed)
            self.checks[spec.key] = check
            column_layouts[index // rows_per_column].addWidget(check)
        for column_layout in column_layouts:
            column_layout.addStretch()
        return group

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
