import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
            order=["removed", "quantity", "number", "name"],
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
        self.assertEqual(
            [header.sectionSize(logical) for logical in range(4)],
            [80, 90, 240, 120],
        )
        self.assertEqual(header.sortIndicatorSection(), 0)
        self.assertEqual(
            header.sortIndicatorOrder(), QtCore.Qt.SortOrder.AscendingOrder
        )
        self.assertEqual(
            self.model.state.header_layouts["ordinary_table"],
            HeaderLayoutState(
                widths={"name": 240, "removed": 400},
                order=["removed", "quantity", "number", "name"],
                sort_column="removed",
                sort_descending=True,
            ),
        )
        header.resizeSection(0, 100)
        self.assertEqual(
            self.model.state.header_layouts["ordinary_table"],
            HeaderLayoutState(
                widths={"number": 100, "added": 90, "name": 240, "quantity": 120},
                order=["quantity", "number", "added", "name"],
                sort_column="number",
                sort_descending=False,
            ),
        )
        del controller
        tree.deleteLater()

    def test_new_leading_column_is_placed_before_next_known_neighbor(self):
        state = WorkspaceState()
        state.header_layouts["ordinary_table"] = HeaderLayoutState(
            order=["quantity", "number"]
        )
        self.model.update_state(state)
        tree = self._tree()
        controller = PersistentHeaderController(
            tree,
            "ordinary_table",
            ("first", "number", "quantity"),
            self.model,
            sorting=False,
            movable=True,
        )
        header = tree.header()
        self.assertEqual([header.logicalIndex(i) for i in range(3)], [2, 0, 1])
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
        self.assertEqual(
            model.state.header_layouts["ordinary_table"],
            HeaderLayoutState(
                widths={"number": 80, "name": 245, "quantity": 120},
                order=["quantity", "number", "name"],
                sort_column="name",
                sort_descending=True,
            ),
        )
        self.assertEqual(repository.load().header_layouts, model.state.header_layouts)
        del controller
        tree.deleteLater()

    def test_explicit_restore_applies_changed_stored_layout_without_persisting(self):
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
        state = model.state
        state.header_layouts["ordinary_table"] = HeaderLayoutState(
            widths={"name": 300, "quantity": 5000},
            order=["name", "quantity", "number"],
            sort_column="quantity",
            sort_descending=True,
        )
        model.update_state(state)
        self.assertEqual(repository.saves, 1)
        controller.restore()
        self.assertEqual(repository.saves, 1)
        self.assertEqual([header.logicalIndex(i) for i in range(3)], [1, 2, 0])
        self.assertEqual(header.sectionSize(1), 300)
        self.assertEqual(header.sectionSize(2), 120)
        self.assertEqual(header.sortIndicatorSection(), 2)
        self.assertEqual(
            header.sortIndicatorOrder(), QtCore.Qt.SortOrder.DescendingOrder
        )
        del controller
        tree.deleteLater()

    def test_failed_workspace_save_is_ignored_for_user_changes(self):
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
        try:
            with mock.patch.object(
                WorkspaceStateAggregate, "update_state", side_effect=OSError("disk")
            ):
                tree.header().resizeSection(1, 245)
            self.assertEqual(tree.header().sectionSize(1), 245)
        finally:
            del controller
            tree.deleteLater()

    def test_invalid_semantic_columns_are_rejected(self):
        tree = self._tree()
        try:
            for keys in (
                ("number", "name"),
                ("number", "name", "name"),
                ("number", "", "quantity"),
            ):
                with self.subTest(keys=keys):
                    with self.assertRaises(ValueError):
                        PersistentHeaderController(
                            tree,
                            "ordinary_table",
                            keys,
                            self.model,
                            sorting=True,
                            movable=True,
                        )
            with self.assertRaises(ValueError):
                PersistentHeaderController(
                    tree,
                    "ordinary_table",
                    ("number", "name", "quantity"),
                    self.model,
                    sorting=True,
                    movable=True,
                    default_sort_column="missing",
                )
        finally:
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
        self.assertEqual([tree.header().logicalIndex(i) for i in range(3)], [2, 0, 1])
        self.assertEqual([tree.topLevelItem(i).text(0) for i in range(2)], row_order)
        self.assertEqual(row_order, ["2", "1"])
        self.assertFalse(tree.isSortingEnabled())
        self.assertFalse(tree.header().isSortIndicatorShown())
        layout = self.model.state.header_layouts["visual_order_only"]
        self.assertEqual(layout.order, ["quantity", "number", "name"])
        self.assertIsNone(layout.sort_column)
        del controller
        tree.deleteLater()
