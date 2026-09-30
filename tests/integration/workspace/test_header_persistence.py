import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.condition_summary_dtos import (
    SUMMARY_NODE_GROUP,
    ConditionSummaryGrouping,
    ConditionSummaryNode,
)
from ost_visualizer.domain.aggregates.workspace_state_aggregate import (
    WorkspaceStateAggregate,
)
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.cdn_type import CdnType
from ost_visualizer.domain.entities.cover_sheet import JobStatus
from ost_visualizer.domain.entities.employee import Employee
from ost_visualizer.domain.entities.file_state import FileEntry
from ost_visualizer.domain.entities.loaded_file import LoadedFile
from ost_visualizer.domain.entities.project import Project
from ost_visualizer.infrastructure.persistence.repositories.json_workspace_state_repository import (
    JsonWorkspaceStateRepository,
)
from ost_visualizer.presentation.components.condition_summary import ConditionSummaryTab
from ost_visualizer.presentation.components.conditions_sidebar import ConditionsSidebar
from ost_visualizer.presentation.components.layers_sidebar import BidLayersSidebar
from ost_visualizer.presentation.components.project_tree_view import ProjectView
from ost_visualizer.presentation.dialogs.areas_dialog import BidAreasDialog
from ost_visualizer.presentation.dialogs.condition_types_dialog import (
    ConditionTypesDialog,
)
from ost_visualizer.presentation.dialogs.employees_dialog import EmployeesDialog
from ost_visualizer.presentation.dialogs.job_statuses_dialog import JobStatusesDialog
from ost_visualizer.presentation.dialogs.open_files_dialog import OpenFilesDialog
from ost_visualizer.presentation.utils.persistent_header import (
    PersistentHeaderController,
)
from PySide6 import QtCore, QtWidgets
from tests.presentation.utils.header_support import (
    _EventBus as _header_support__EventBus,
    _IconProvider as _header_support__IconProvider,
    _app as _header_support__app,
)


class WorkspaceHeaderPersistenceTests(unittest.TestCase):
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

    def test_semantic_layout_round_trips_through_only_workspace_state_json(self):
        tree = self._tree()
        controller = PersistentHeaderController(
            tree,
            "ordinary_table",
            ("number", "name", "quantity"),
            self.model,
            sorting=True,
            movable=True,
            default_sort_column="number",
        )
        header = tree.header()
        header.resizeSection(1, 245)
        header.moveSection(header.visualIndex(2), 0)
        tree.sortByColumn(1, QtCore.Qt.SortOrder.DescendingOrder)
        self.app.processEvents()
        reloaded_model = WorkspaceStateAggregate(
            JsonWorkspaceStateRepository(self.state_path)
        )
        restored = self._tree()
        restored_controller = PersistentHeaderController(
            restored,
            "ordinary_table",
            ("number", "name", "quantity"),
            reloaded_model,
            sorting=True,
            movable=True,
            default_sort_column="number",
        )
        restored_header = restored.header()
        self.assertEqual(restored_header.sectionSize(1), 245)
        self.assertEqual(restored_header.logicalIndex(0), 2)
        self.assertEqual(restored_header.sortIndicatorSection(), 1)
        self.assertEqual(
            restored_header.sortIndicatorOrder(),
            QtCore.Qt.SortOrder.DescendingOrder,
        )
        self.assertEqual(restored.topLevelItem(0).text(1), "Beta")
        self.assertEqual(
            sorted(path.name for path in Path(self.temp_dir.name).iterdir()),
            ["workspace_state.json"],
        )
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertIn("ordinary_table", payload["header_layouts"])
        self.assertNotIn("header_state_b64", json.dumps(payload))
        del controller, restored_controller
        tree.deleteLater()
        restored.deleteLater()

    def test_duplicate_or_unusable_order_fully_resets_the_header_layout(self):
        for order in (
            ["name", "name"],
            ["removed", "also_removed"],
            [1, "name"],
        ):
            with self.subTest(order=order):
                self.state_path.write_text(
                    json.dumps(
                        {
                            "header_layouts": {
                                "ordinary_table": {
                                    "widths": {"name": 245},
                                    "order": order,
                                    "sort_column": "name",
                                    "sort_descending": True,
                                }
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                original_payload = self.state_path.read_text(encoding="utf-8")
                model = WorkspaceStateAggregate(
                    JsonWorkspaceStateRepository(self.state_path)
                )
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
                self.assertEqual([header.logicalIndex(i) for i in range(3)], [0, 1, 2])
                self.assertEqual(header.sectionSize(1), 180)
                self.assertEqual(header.sortIndicatorSection(), 0)
                self.assertEqual(
                    self.state_path.read_text(encoding="utf-8"), original_payload
                )
                del controller
                tree.deleteLater()

    def test_summary_order_width_and_sort_survive_rebuild_and_reopen(self):
        tab = ConditionSummaryTab(None)
        controller = PersistentHeaderController(
            tab.tree,
            "condition_summary",
            tab.column_keys,
            self.model,
            sorting=True,
            movable=True,
            default_sort_column="name",
        )
        tab.columns_about_to_change.connect(controller.begin_columns_update)
        tab.columns_changed.connect(controller.end_columns_update)
        name_column = tab.column_keys.index("name")
        area_column = tab.column_keys.index("area")
        notes_column = tab.column_keys.index("notes")
        tab.tree.header().resizeSection(name_column, 260)
        tab.tree.header().resizeSection(area_column, 310)
        tab.tree.header().moveSection(tab.tree.header().visualIndex(notes_column), 0)
        tab.tree.sortByColumn(name_column, QtCore.Qt.SortOrder.DescendingOrder)
        root = ConditionSummaryNode(kind=SUMMARY_NODE_GROUP)
        tab.load_summary(root, ConditionSummaryGrouping())
        self.assertEqual(tab.tree.header().sectionSize(name_column), 260)
        self.assertEqual(tab.tree.header().logicalIndex(0), notes_column)
        tab.load_summary(root, ConditionSummaryGrouping(by_area=True))
        self.assertNotIn("area", tab.column_keys)
        self.assertEqual(
            tab.tree.header().logicalIndex(0), tab.column_keys.index("notes")
        )
        self.assertEqual(
            set(self.model.state.header_layouts["condition_summary"].order),
            {
                "number",
                "name",
                "height",
                "area",
                "quantity1",
                "uom1",
                "quantity2",
                "uom2",
                "quantity3",
                "uom3",
                "notes",
            },
        )
        visible_name_column = tab.column_keys.index("name")
        tab.tree.header().resizeSection(visible_name_column, 280)
        tab.load_summary(root, ConditionSummaryGrouping())
        self.assertEqual(tab.tree.header().logicalIndex(0), notes_column)
        self.assertEqual(tab.tree.header().sectionSize(name_column), 280)
        self.assertEqual(tab.tree.header().sectionSize(area_column), 310)
        reopened = ConditionSummaryTab(None)
        reopened_controller = PersistentHeaderController(
            reopened.tree,
            "condition_summary",
            reopened.column_keys,
            self.model,
            sorting=True,
            movable=True,
            default_sort_column="name",
        )
        self.assertEqual(reopened.tree.header().sectionSize(name_column), 280)
        self.assertEqual(reopened.tree.header().sectionSize(area_column), 310)
        self.assertEqual(reopened.tree.header().logicalIndex(0), notes_column)
        self.assertEqual(reopened.tree.header().sortIndicatorSection(), name_column)
        del controller, reopened_controller
        tab.deleteLater()
        reopened.deleteLater()

    def test_projects_sort_only_siblings_and_preserve_domain_hierarchy(self):
        projects = [
            Project(
                uid="project-z",
                name="Zulu",
                bids=[
                    Bid(uid="bid-20", name="Twenty", bid_no=20),
                    Bid(uid="bid-10", name="Ten", bid_no=10),
                ],
            ),
            Project(uid="project-a", name="Alpha", bids=[]),
        ]
        loaded_file = LoadedFile(
            file_path="C:/jobs/test.mdb",
            display_name="test.mdb",
            projects=projects,
        )
        view = ProjectView(None, _header_support__EventBus())
        view.build_complete_structure([loaded_file])
        controller = PersistentHeaderController(
            view.top_tree,
            "project_tree_test",
            (
                "number",
                "name",
                "status",
                "bid_date",
                "job_number",
                "estimator",
                "pages",
                "conditions",
                "notes",
                "copy_from",
                "copy_timestamp",
            ),
            self.model,
            sorting=True,
            movable=True,
            default_sort_column="number",
        )
        view.top_tree.sortByColumn(0, QtCore.Qt.SortOrder.AscendingOrder)
        root = view.top_tree.topLevelItem(0)
        self.assertEqual(
            [root.child(i).text(0) for i in range(2)],
            ["Alpha", "Zulu"],
        )
        zulu_item = next(
            root.child(i)
            for i in range(root.childCount())
            if root.child(i).text(0) == "Zulu"
        )
        self.assertEqual(
            [zulu_item.child(i).text(0) for i in range(2)],
            ["10", "20"],
        )
        view.top_tree.header().moveSection(view.top_tree.header().visualIndex(1), 0)
        self.assertEqual(
            [zulu_item.child(i).parent() for i in range(2)],
            [zulu_item, zulu_item],
        )
        self.assertEqual(
            [project.uid for project in projects], ["project-z", "project-a"]
        )
        self.assertEqual([bid.uid for bid in projects[0].bids], ["bid-20", "bid-10"])
        del controller
        view.deleteLater()

    def test_open_databases_restores_resizable_width_and_sort_but_not_movement(self):
        database_path = Path(self.temp_dir.name) / "sample.mdb"
        database_path.touch()
        entries = [FileEntry(str(database_path), is_checked=True)]
        dialog = OpenFilesDialog(
            _header_support__IconProvider(),
            None,
            entries,
            object(),
            workspace_state_model=self.model,
        )
        header = dialog.table.header()
        header.resizeSection(3, 275)
        dialog.table.sortByColumn(4, QtCore.Qt.SortOrder.DescendingOrder)
        self.assertFalse(header.sectionsMovable())
        dialog.close()
        dialog.cleanup()
        dialog.deleteLater()
        reopened = OpenFilesDialog(
            _header_support__IconProvider(),
            None,
            entries,
            object(),
            workspace_state_model=self.model,
        )
        reopened_header = reopened.table.header()
        self.assertEqual(reopened_header.sectionSize(3), 275)
        self.assertEqual(reopened_header.sortIndicatorSection(), 4)
        self.assertEqual(
            reopened_header.sortIndicatorOrder(),
            QtCore.Qt.SortOrder.DescendingOrder,
        )
        reopened.close()
        reopened.cleanup()
        reopened.deleteLater()

    def test_explicit_sort_indicator_and_movement_exemptions(self):
        conditions = ConditionsSidebar(None)
        conditions_controller = PersistentHeaderController(
            conditions.tree,
            "conditions_sidebar",
            ("number", "name", "quantity_1", "quantity_2", "quantity_3"),
            self.model,
            sorting=True,
            movable=False,
            default_sort_column="number",
        )
        layers = BidLayersSidebar(None)
        layers_controller = PersistentHeaderController(
            layers.table,
            "layers_sidebar",
            ("visible", "layer"),
            self.model,
            sorting=False,
            movable=True,
            persisted_width_keys=("layer",),
        )
        areas = BidAreasDialog(
            _header_support__IconProvider(),
            bid_areas=[BidArea("a1", "b1", "", "Area", 1)],
            workspace_state_model=self.model,
        )
        condition_types = ConditionTypesDialog(
            _header_support__IconProvider(),
            condition_types=[CdnType(uid="t1", name="Concrete")],
            workspace_state_model=self.model,
        )
        statuses = JobStatusesDialog(
            _header_support__IconProvider(),
            job_statuses=[JobStatus("s1", "Bidding", False, 1)],
            workspace_state_model=self.model,
        )
        self.assertTrue(conditions.tree.header().isSortIndicatorShown())
        self.assertFalse(conditions.tree.header().sectionsMovable())
        self.assertFalse(layers.table.header().isSortIndicatorShown())
        self.assertFalse(areas.tree.header().isSortIndicatorShown())
        self.assertFalse(areas.tree.header().sectionsMovable())
        self.assertTrue(condition_types.tree.header().isSortIndicatorShown())
        self.assertFalse(condition_types.tree.header().sectionsMovable())
        self.assertFalse(statuses.tree.header().isSortIndicatorShown())
        del conditions_controller, layers_controller
        areas.cleanup()
        condition_types.cleanup()
        for widget in (conditions, layers, areas, condition_types, statuses):
            widget.close()
            widget.deleteLater()

    def test_employees_is_an_ordinary_sortable_movable_persistent_table(self):
        employees = [
            Employee(
                uid="e1",
                employee_no="1",
                first_name="Ava",
                last_name="Lee",
            )
        ]
        dialog = EmployeesDialog(
            _header_support__IconProvider(),
            employees=employees,
            workspace_state_model=self.model,
        )
        header = dialog.tree.header()
        header.resizeSection(1, 235)
        header.moveSection(header.visualIndex(3), 0)
        dialog.tree.sortByColumn(1, QtCore.Qt.SortOrder.DescendingOrder)
        self.assertTrue(header.sectionsMovable())
        self.assertTrue(header.isSortIndicatorShown())
        dialog.close()
        dialog.cleanup()
        dialog.deleteLater()
        reopened = EmployeesDialog(
            _header_support__IconProvider(),
            employees=employees,
            workspace_state_model=self.model,
        )
        self.assertEqual(reopened.tree.header().sectionSize(1), 235)
        self.assertEqual(reopened.tree.header().logicalIndex(0), 3)
        self.assertEqual(reopened.tree.header().sortIndicatorSection(), 1)
        reopened.close()
        reopened.cleanup()
        reopened.deleteLater()
