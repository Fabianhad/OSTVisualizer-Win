import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.aggregates.workspace_state_aggregate import (
    WorkspaceStateAggregate,
)
from ost_visualizer.domain.entities.workspace_state import (
    HeaderLayoutState,
    WorkspaceState,
)
from ost_visualizer.infrastructure.persistence.repositories.json_workspace_state_repository import (
    JsonWorkspaceStateRepository,
)
from ost_visualizer.presentation.utils.persistent_header import (
    PersistentHeaderController,
)
from PySide6 import QtCore, QtWidgets
from tests.helpers.workspace_state import InMemoryWorkspaceStateRepository
from tests.presentation.utils.header_support import (
    _CountingWorkspaceStateRepository as _header_support__CountingWorkspaceStateRepository,
    _app as _header_support__app,
)


class PersistentHeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _header_support__app()

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temp_dir.name) / "workspace_state.json"
        self.model = WorkspaceStateAggregate(
            JsonWorkspaceStateRepository(self.state_path)
        )

    def tearDown(self):
        self.app.processEvents()
        self.temp_dir.cleanup()

    @staticmethod
    def _tree():
        tree = QtWidgets.QTreeWidget()
        tree.setColumnCount(3)
        tree.setHeaderLabels(["Number", "Name", "Quantity"])
        tree.header().setStretchLastSection(False)
        for logical, width in enumerate((80, 180, 120)):
            tree.header().setSectionResizeMode(
                logical, QtWidgets.QHeaderView.ResizeMode.Interactive
            )
            tree.header().resizeSection(logical, width)
        tree.addTopLevelItems(
            [
                QtWidgets.QTreeWidgetItem(["2", "Beta", "4"]),
                QtWidgets.QTreeWidgetItem(["1", "Alpha", "3"]),
            ]
        )
        return tree

    def test_schema_changes_reconcile_known_order_and_ignore_removed_columns(self):
        state = WorkspaceState()
        state.header_layouts["ordinary_table"] = HeaderLayoutState(
            widths={"name": 240, "removed": 400},
            order=["removed", "quantity", "number"],
            sort_column="removed",
            sort_descending=True,
        )
        self.model.update_state(state)
        tree = QtWidgets.QTreeWidget()
        tree.setColumnCount(4)
        tree.setHeaderLabels(["Number", "Added", "Name", "Quantity"])
        for logical, width in enumerate((80, 90, 180, 120)):
            tree.header().setSectionResizeMode(
                logical, QtWidgets.QHeaderView.ResizeMode.Interactive
            )
            tree.header().resizeSection(logical, width)
        controller = PersistentHeaderController(
            tree,
            "ordinary_table",
            ("number", "added", "name", "quantity"),
            self.model,
            sorting=True,
            movable=True,
            default_sort_column="number",
        )
        header = tree.header()
        self.assertEqual(
            [header.logicalIndex(i) for i in range(4)],
            [3, 0, 1, 2],
        )
        self.assertEqual(header.sectionSize(2), 240)
        self.assertEqual(header.sortIndicatorSection(), 0)
        self.assertEqual(
            header.sortIndicatorOrder(), QtCore.Qt.SortOrder.AscendingOrder
        )
        del controller
        tree.deleteLater()

    def test_user_changes_persist_once_and_restore_does_not_write_back(self):
        repository = _header_support__CountingWorkspaceStateRepository(WorkspaceState())
        model = WorkspaceStateAggregate(repository)
        tree = self._tree()
        controller = PersistentHeaderController(
            tree,
            "ordinary_table",
            ("number", "name", "quantity"),
            model,
            sorting=True,
            movable=True,
            default_sort_column="number",
        )
        header = tree.header()
        self.assertEqual(repository.saves, 0)
        header.resizeSection(1, 245)
        self.assertEqual(repository.saves, 1)
        controller.restore()
        self.assertEqual(repository.saves, 1)
        tree.sortByColumn(1, QtCore.Qt.SortOrder.DescendingOrder)
        self.assertEqual(repository.saves, 2)
        tree.sortByColumn(1, QtCore.Qt.SortOrder.DescendingOrder)
        self.assertEqual(repository.saves, 2)
        header.moveSection(header.visualIndex(2), 0)
        self.assertEqual(repository.saves, 3)
        controller.restore()
        self.assertEqual(repository.saves, 3)
        del controller
        tree.deleteLater()

    def test_restore_and_model_reset_reapply_state_without_persisting(self):
        state = WorkspaceState()
        state.header_layouts["ordinary_table"] = HeaderLayoutState(
            widths={"name": 245},
            order=["quantity", "number", "name"],
            sort_column="name",
            sort_descending=True,
        )
        repository = _header_support__CountingWorkspaceStateRepository(state)
        model = WorkspaceStateAggregate(repository)
        tree = self._tree()
        controller = PersistentHeaderController(
            tree,
            "ordinary_table",
            ("number", "name", "quantity"),
            model,
            sorting=True,
            movable=True,
            default_sort_column="number",
        )
        header = tree.header()
        self.assertEqual(repository.saves, 0)
        controller.restore()
        self.assertEqual(repository.saves, 0)

        def disturb_header_during_reset():
            header.resizeSection(1, 100)
            header.moveSection(header.visualIndex(0), 0)
            tree.sortByColumn(0, QtCore.Qt.SortOrder.AscendingOrder)

        tree.model().modelAboutToBeReset.connect(disturb_header_during_reset)
        tree.clear()
        tree.model().modelAboutToBeReset.disconnect(disturb_header_during_reset)
        self.assertEqual(header.sectionSize(1), 245)
        self.assertEqual([header.logicalIndex(i) for i in range(3)], [2, 0, 1])
        self.assertEqual(header.sortIndicatorSection(), 1)
        self.assertEqual(
            header.sortIndicatorOrder(), QtCore.Qt.SortOrder.DescendingOrder
        )
        self.assertEqual(repository.saves, 0)
        del controller
        tree.deleteLater()

    def test_visual_column_movement_does_not_change_row_order(self):
        tree = self._tree()
        controller = PersistentHeaderController(
            tree,
            "visual_order_only",
            ("number", "name", "quantity"),
            self.model,
            sorting=False,
            movable=True,
        )
        row_order = [tree.topLevelItem(i).text(0) for i in range(2)]
        tree.header().moveSection(tree.header().visualIndex(2), 0)
        self.assertEqual([tree.topLevelItem(i).text(0) for i in range(2)], row_order)
        del controller
        tree.deleteLater()
