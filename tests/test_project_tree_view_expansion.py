import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtTest, QtWidgets
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.loaded_file import LoadedFile
from ost_visualizer.domain.entities.project import Project
from ost_visualizer.presentation.components.project_tree_view import (
    _DELETED_PROJECT_UID,
    ProjectView,
)


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class _EventBus:
    def publish(self, *_args, **_kwargs):
        pass


class ProjectTreeViewExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        self.view.deleteLater()
        self.app.processEvents()

    def setUp(self):
        self.view = ProjectView(None, _EventBus())

    def _loaded_file(self, source_bid_uids, deleted_bid_uids=()):
        return [
            LoadedFile(
                file_path="C:/jobs/test.mdb",
                display_name="test.mdb",
                projects=[
                    Project(
                        uid="project-1",
                        name="Source",
                        bids=[Bid(uid=uid, name=uid) for uid in source_bid_uids],
                    ),
                    Project(
                        uid="project-2",
                        name="Target",
                        bids=[],
                    ),
                    Project(
                        uid=_DELETED_PROJECT_UID,
                        name="Deleted Bids",
                        bids=[Bid(uid=uid, name=uid) for uid in deleted_bid_uids],
                    ),
                ],
            )
        ]

    def _find_item(self, uid):
        found = None

        def walk(item):
            nonlocal found
            data = item.data(0, self.view._ITEM_ROLE)
            if data and data[1] == uid:
                found = item
                return
            for index in range(item.childCount()):
                walk(item.child(index))

        for index in range(self.view.top_tree.topLevelItemCount()):
            walk(self.view.top_tree.topLevelItem(index))
        return found

    def test_selection_restore_records_expanded_parent_nodes_for_rebuild(self):
        self.view.set_expanded_node_keys([])
        self.view.set_selected_node_state(
            {
                "kind": "bid",
                "file_path": "C:/jobs/test.mdb",
                "bid_uid": "bid-1",
                "project_uid": None,
            }
        )
        self.view.build_complete_structure(self._loaded_file(["bid-1", "bid-2"]))
        source_project = self._find_item("project-1")
        self.assertTrue(source_project.isExpanded())

    def test_blank_bid_status_displays_unassigned(self):
        self.view.build_complete_structure(self._loaded_file(["bid-1"]))
        bid_item = self._find_item("bid-1")
        self.assertEqual("(unassigned)", bid_item.text(2))
        self.assertIn(
            "project|C:/jobs/test.mdb|project-1",
            self.view.get_expanded_node_keys(),
        )
        self.view.build_complete_structure(self._loaded_file(["bid-2"], ["bid-1"]))
        source_project = self._find_item("project-1")
        self.assertTrue(source_project.isExpanded())

    def test_multi_select_bids_does_not_switch_active_bid(self):
        bid_selections = []
        multi_selections = []
        self.view.on_bid_selection = lambda bid_ref: bid_selections.append(bid_ref)
        self.view.on_multi_selection = lambda bids, projects: multi_selections.append(
            (list(bids), list(projects))
        )
        self.view.build_complete_structure(self._loaded_file(["bid-1", "bid-2"]))
        bid_1 = self._find_item("bid-1")
        bid_2 = self._find_item("bid-2")
        self.view.top_tree.setCurrentItem(bid_1)
        bid_1.setSelected(True)
        self.assertEqual([ref.bid_uid for ref in bid_selections], ["bid-1"])
        bid_2.setSelected(True)
        self.assertEqual([ref.bid_uid for ref in bid_selections], ["bid-1"])
        self.assertEqual(
            sorted(ref.bid_uid for ref in multi_selections[-1][0]),
            ["bid-1", "bid-2"],
        )

    def test_right_click_project_selects_target_and_emits_context_menu(self):
        self.view.build_complete_structure(self._loaded_file(["bid-1"]))
        self.view.top_tree.expandAll()
        bid_item = self._find_item("bid-1")
        target_project = self._find_item("project-2")
        self.view.top_tree.setCurrentItem(bid_item)
        bid_item.setSelected(True)
        emitted_positions = []
        self.view.top_tree.customContextMenuRequested.disconnect()

        def record_context(pos):
            emitted_positions.append(pos)
            item = self.view.top_tree.itemAt(pos)
            if item is not None:
                self.view._prepare_context_menu_selection(item)

        self.view.top_tree.customContextMenuRequested.connect(record_context)
        self.view.top_tree.scrollToItem(target_project)
        self.app.processEvents()
        pos = self.view.top_tree.visualItemRect(target_project).center()
        QtTest.QTest.mouseClick(
            self.view.top_tree.viewport(),
            QtCore.Qt.MouseButton.RightButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
            pos,
        )
        self.assertEqual(
            [
                item.data(0, self.view._ITEM_ROLE)[1]
                for item in self.view.top_tree.selectedItems()
            ],
            ["project-2"],
        )
        self.assertEqual(len(emitted_positions), 1)

    def test_right_click_selected_bid_preserves_multi_selection(self):
        self.view.build_complete_structure(self._loaded_file(["bid-1", "bid-2"]))
        self.view.top_tree.expandAll()
        bid_1 = self._find_item("bid-1")
        bid_2 = self._find_item("bid-2")
        bid_1.setSelected(True)
        bid_2.setSelected(True)
        self.view.top_tree._set_current_item_preserving_selection(bid_1)
        emitted_positions = []
        self.view.top_tree.customContextMenuRequested.disconnect()
        self.view.top_tree.customContextMenuRequested.connect(
            lambda pos: emitted_positions.append(pos)
        )
        self.view.top_tree.scrollToItem(bid_1)
        self.app.processEvents()
        pos = self.view.top_tree.visualItemRect(bid_1).center()
        QtTest.QTest.mouseClick(
            self.view.top_tree.viewport(),
            QtCore.Qt.MouseButton.RightButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
            pos,
        )
        self.assertEqual(
            sorted(
                item.data(0, self.view._ITEM_ROLE)[1]
                for item in self.view.top_tree.selectedItems()
            ),
            ["bid-1", "bid-2"],
        )
        self.assertEqual(len(emitted_positions), 1)

    def test_right_click_empty_space_preserves_selection_and_emits_context_menu(self):
        self.view.build_complete_structure(self._loaded_file(["bid-1"]))
        self.view.top_tree.expandAll()
        bid_item = self._find_item("bid-1")
        self.view.top_tree.setCurrentItem(bid_item)
        bid_item.setSelected(True)
        emitted_positions = []
        self.view.top_tree.customContextMenuRequested.disconnect()
        self.view.top_tree.customContextMenuRequested.connect(
            lambda pos: emitted_positions.append(pos)
        )
        pos = self.view.top_tree.viewport().rect().bottomRight() - QtCore.QPoint(4, 4)
        QtTest.QTest.mouseClick(
            self.view.top_tree.viewport(),
            QtCore.Qt.MouseButton.RightButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
            pos,
        )
        self.assertEqual(
            [
                item.data(0, self.view._ITEM_ROLE)[1]
                for item in self.view.top_tree.selectedItems()
            ],
            ["bid-1"],
        )
        self.assertEqual(len(emitted_positions), 1)

    def test_context_menu_paste_target_uses_right_clicked_project(self):
        self.view.build_complete_structure(self._loaded_file(["bid-1"]))
        target_project = self._find_item("project-2")
        self.view.on_can_paste_bids = (
            lambda file_path, project_uid: file_path == "C:/jobs/test.mdb"
            and project_uid == "project-2"
        )
        self.assertTrue(
            self.view._can_paste_to_target(
                self.view._paste_target_for_item(target_project)
            )
        )

    def test_context_copy_uses_right_clicked_unselected_bid(self):
        copied = []
        self.view.on_copy_bids = lambda refs: copied.append(list(refs))
        self.view.build_complete_structure(self._loaded_file(["bid-1", "bid-2"]))
        bid_1 = self._find_item("bid-1")
        bid_2 = self._find_item("bid-2")
        self.view.top_tree.setCurrentItem(bid_1)
        bid_1.setSelected(True)
        context = self.view._context_for_item(bid_2)
        self.view._copy_bid_refs(context.copy_refs)
        self.assertEqual(
            [[ref.bid_uid for ref in refs] for refs in copied], [["bid-2"]]
        )

    def test_context_paste_blocks_different_database_target(self):
        self.view.build_complete_structure(
            [
                LoadedFile(
                    file_path="C:/jobs/source.mdb",
                    display_name="source.mdb",
                    projects=[
                        Project(
                            uid="project-source",
                            name="Source",
                            bids=[Bid(uid="bid-1", name="bid-1")],
                        )
                    ],
                ),
                LoadedFile(
                    file_path="C:/jobs/target.mdb",
                    display_name="target.mdb",
                    projects=[
                        Project(uid="project-target", name="Target", bids=[]),
                    ],
                ),
            ]
        )
        target_project = self._find_item("project-target")
        self.view.on_can_paste_bids = (
            lambda file_path, _project_uid: file_path == "C:/jobs/source.mdb"
        )
        self.assertFalse(
            self.view._can_paste_to_target(
                self.view._paste_target_for_item(target_project)
            )
        )


if __name__ == "__main__":
    unittest.main()
