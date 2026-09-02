import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtTest, QtWidgets
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.loaded_file import LoadedFile
from ost_visualizer.domain.entities.project import Project
from ost_visualizer.presentation.components.project_tree_view import (
    _DELETED_PROJECT_UID,
    ProjectView,
)
from ost_visualizer.presentation.managers.icon_manager import IconId, IconManager


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class _EventBus:
    def publish(self, *_args, **_call_options):
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
        self.view.set_ui_access_manager(
            SimpleNamespace(is_allowed=lambda _feature: True)
        )

    def _loaded_file(
        self,
        source_bid_uids,
        deleted_bid_uids=(),
        orphan_bid_uids=(),
        file_path="C:/jobs/test.mdb",
    ):
        return [
            LoadedFile(
                file_path=file_path,
                display_name="test.mdb",
                projects=[
                    Project(
                        uid="project-1",
                        name="Source",
                        bids=[
                            Bid(uid=uid, name=uid, bid_no=index + 1)
                            for index, uid in enumerate(source_bid_uids)
                        ],
                    ),
                    Project(
                        uid="project-2",
                        name="Target",
                        bids=[],
                    ),
                    Project(
                        uid=_DELETED_PROJECT_UID,
                        name="Deleted Bids",
                        bids=[
                            Bid(uid=uid, name=uid, bid_no=index + 1)
                            for index, uid in enumerate(deleted_bid_uids)
                        ],
                    ),
                ],
                orphan_bids=[
                    Bid(uid=uid, name=uid, bid_no=index + 1)
                    for index, uid in enumerate(orphan_bid_uids)
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

    def _select_bid_items(self, *uids):
        self.view.top_tree.clearSelection()
        selected = []
        for uid in uids:
            item = self._find_item(uid)
            selected.append(item)
        if selected:
            self.view.top_tree.setCurrentItem(selected[0])
            for item in selected:
                item.setSelected(True)
        self.app.processEvents()
        return selected

    def test_delete_replacement_selects_next_bid_in_same_folder(self):
        self.view.build_complete_structure(self._loaded_file(["bid-1", "bid-2"]))
        self._select_bid_items("bid-1")
        state = self.view.get_delete_replacement_selection_state()
        self.assertEqual(state["kind"], "bid")
        self.assertEqual(state["bid_uid"], "bid-2")

    def test_delete_replacement_selects_next_bid_for_middle_selection(self):
        self.view.build_complete_structure(
            self._loaded_file(["bid-1", "bid-2", "bid-3"])
        )
        self._select_bid_items("bid-2")
        state = self.view.get_delete_replacement_selection_state()
        self.assertEqual(state["kind"], "bid")
        self.assertEqual(state["bid_uid"], "bid-3")

    def test_delete_replacement_selects_previous_bid_for_last_selection(self):
        self.view.build_complete_structure(
            self._loaded_file(["bid-1", "bid-2", "bid-3"])
        )
        self._select_bid_items("bid-3")
        state = self.view.get_delete_replacement_selection_state()
        self.assertEqual(state["kind"], "bid")
        self.assertEqual(state["bid_uid"], "bid-2")

    def test_delete_replacement_falls_back_to_parent_when_only_bid_selected(self):
        self.view.build_complete_structure(self._loaded_file(["bid-1"]))
        self._select_bid_items("bid-1")
        state = self.view.get_delete_replacement_selection_state()
        self.assertEqual(state["kind"], "project")
        self.assertEqual(state["project_uid"], "project-1")

    def test_delete_replacement_selects_orphan_sibling_in_same_database(self):
        self.view.build_complete_structure(
            self._loaded_file([], orphan_bid_uids=["orphan-1", "orphan-2"])
        )
        self._select_bid_items("orphan-1")
        state = self.view.get_delete_replacement_selection_state()
        self.assertEqual(state["kind"], "bid")
        self.assertEqual(state["file_path"], "C:/jobs/test.mdb")
        self.assertEqual(state["bid_uid"], "orphan-2")

    def test_delete_replacement_does_not_cross_database_for_only_bid(self):
        loaded_files = self._loaded_file(["bid-1"], file_path="C:/jobs/one.mdb")
        loaded_files.extend(self._loaded_file(["bid-2"], file_path="C:/jobs/two.mdb"))
        self.view.build_complete_structure(loaded_files)
        self._select_bid_items("bid-1")
        state = self.view.get_delete_replacement_selection_state()
        self.assertEqual(state["kind"], "project")
        self.assertEqual(state["file_path"], "C:/jobs/one.mdb")

    def test_delete_replacement_selects_after_multi_bid_range(self):
        self.view.build_complete_structure(
            self._loaded_file(["bid-1", "bid-2", "bid-3", "bid-4"])
        )
        self._select_bid_items("bid-1", "bid-2")
        state = self.view.get_delete_replacement_selection_state()
        self.assertEqual(state["kind"], "bid")
        self.assertEqual(state["bid_uid"], "bid-3")

    def test_delete_replacement_selects_next_deleted_bid_for_permanent_delete(self):
        self.view.build_complete_structure(
            self._loaded_file([], deleted_bid_uids=["deleted-1", "deleted-2"])
        )
        self._select_bid_items("deleted-1")
        state = self.view.get_delete_replacement_selection_state()
        self.assertEqual(state["kind"], "bid")
        self.assertEqual(state["bid_uid"], "deleted-2")

    def test_delete_replacement_selects_previous_deleted_bid_for_permanent_delete(self):
        self.view.build_complete_structure(
            self._loaded_file([], deleted_bid_uids=["deleted-1", "deleted-2"])
        )
        self._select_bid_items("deleted-2")
        state = self.view.get_delete_replacement_selection_state()
        self.assertEqual(state["kind"], "bid")
        self.assertEqual(state["bid_uid"], "deleted-1")

    def assert_item_icon(self, item, icon_id):
        self.assertFalse(item.icon(0).isNull())
        self.assertEqual(item.icon(0).cacheKey(), IconManager.icon(icon_id).cacheKey())

    def test_project_tree_applies_node_icons(self):
        self.view.build_complete_structure(self._loaded_file(["bid-1"]))
        database_item = self._find_item("C:/jobs/test.mdb")
        project_item = self._find_item("project-1")
        bid_item = self._find_item("bid-1")
        self.assert_item_icon(database_item, IconId.PROJECT_TREE_DATABASE)
        self.assert_item_icon(project_item, IconId.FOLDER)
        self.assert_item_icon(bid_item, IconId.PROJECT_TREE_BID)

    def test_project_tree_status_groups_use_folder_icon(self):
        self.view.build_complete_structure(self._loaded_file(["bid-1"]))
        self.view.set_group_by_job_status(True, notify=False)
        database_item = self._find_item("C:/jobs/test.mdb")
        status_group = database_item.child(0)
        self.assert_item_icon(status_group, IconId.FOLDER)

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

    def test_missing_saved_bid_selection_falls_back_to_its_database(self):
        self.view.set_selected_node_state(
            {
                "kind": "bid",
                "file_path": "C:/jobs/test.mdb",
                "bid_uid": "remotely-deleted",
                "project_uid": None,
            }
        )

        self.view.build_complete_structure(self._loaded_file(["bid-1"]))

        self.assertEqual(
            self.view.get_selected_node_state(),
            {
                "kind": "database",
                "file_path": "C:/jobs/test.mdb",
                "bid_uid": None,
                "project_uid": None,
            },
        )

    def test_rebuild_preserves_orphan_bid_selection_by_file_and_uid(self):
        selected_state = {
            "kind": "bid",
            "file_path": "C:/jobs/test.mdb",
            "bid_uid": "orphan-1",
            "project_uid": None,
        }
        self.view.set_selected_node_state(selected_state)
        self.view.build_complete_structure(
            self._loaded_file([], orphan_bid_uids=["orphan-1"])
        )
        self.view.build_complete_structure(
            self._loaded_file([], orphan_bid_uids=["orphan-1", "imported-bid"])
        )
        self.assertEqual(self.view.get_selected_node_state(), selected_state)

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

    def test_multi_select_projects_rejects_cross_database_write_scope(self):
        loaded_files = self._loaded_file([], file_path="C:/jobs/one.mdb")
        loaded_files[0].projects[0].uid = "project-one"
        loaded_files.extend(self._loaded_file([], file_path="C:/jobs/two.mdb"))
        loaded_files[1].projects[0].uid = "project-two"
        self.view.build_complete_structure(loaded_files)
        project_one, _ = self.view._find_project_item("project-one", "C:/jobs/one.mdb")
        project_two, _ = self.view._find_project_item("project-two", "C:/jobs/two.mdb")
        project_one.setSelected(True)
        project_two.setSelected(True)
        _bid_refs, project_uids = self.view._collect_multi_selection()
        self.assertEqual(project_uids, [])

    def test_grouped_project_multi_selection_deduplicates_project_uid(self):
        loaded_file = LoadedFile(
            file_path="C:/jobs/test.mdb",
            display_name="test.mdb",
            projects=[
                Project(
                    uid="project-shared",
                    name="Shared",
                    bids=[
                        Bid(uid="bid-open", name="Open", status="Open"),
                        Bid(uid="bid-won", name="Won", status="Won"),
                    ],
                )
            ],
            orphan_bids=[],
        )
        self.view._group_by_job_status = True
        self.view.build_complete_structure([loaded_file])
        project_items = []

        def collect(item):
            data = item.data(0, self.view._ITEM_ROLE)
            if data and data[:2] == ("project", "project-shared"):
                project_items.append(item)
            for index in range(item.childCount()):
                collect(item.child(index))

        for index in range(self.view.top_tree.topLevelItemCount()):
            collect(self.view.top_tree.topLevelItem(index))
        self.assertEqual(len(project_items), 2)
        for item in project_items:
            item.setSelected(True)
        _bid_refs, project_uids = self.view._collect_multi_selection()
        self.assertEqual(project_uids, ["project-shared"])

    def test_scheduled_rename_targets_matching_database_for_duplicate_project_uid(self):
        loaded_files = self._loaded_file([], file_path="C:/jobs/one.mdb")
        loaded_files[0].projects[0].uid = "project-shared"
        loaded_files.extend(self._loaded_file([], file_path="C:/jobs/two.mdb"))
        loaded_files[1].projects[0].uid = "project-shared"
        self.view.build_complete_structure(loaded_files)
        self.view.schedule_rename("project-shared", "C:/jobs/two.mdb")
        self.app.processEvents()
        self.assertIsNotNone(self.view._rename_item)
        self.assertEqual(self.view._rename_item[2], "C:/jobs/two.mdb")
        self.view.reset()

    def test_reset_cancels_active_rename_before_deleting_tree_item(self):
        rename_calls = []
        self.view.on_rename_project = lambda *args: rename_calls.append(args)
        self.view.build_complete_structure(self._loaded_file([]))
        item = self._find_item("project-1")
        self.view._start_project_rename(item, "project-1", "C:/jobs/test.mdb")
        self.app.processEvents()
        editor = self.view.top_tree.viewport().focusWidget()
        self.assertIsInstance(editor, QtWidgets.QLineEdit)
        editor.setText("Changed")
        self.view.reset()
        self.view._on_rename_editor_closed()
        self.assertIsNone(self.view._rename_item)
        self.assertFalse(self.view._rename_editor_connected)
        self.assertEqual(rename_calls, [])

    def test_tree_rebuild_preserves_outer_signal_block(self):
        self.view.top_tree.blockSignals(True)
        try:
            self.view.build_complete_structure(self._loaded_file(["bid-1"]))
            self.view._select_item(self._find_item("bid-1"))
            self.assertTrue(self.view.top_tree.signalsBlocked())
        finally:
            self.view.top_tree.blockSignals(False)

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
