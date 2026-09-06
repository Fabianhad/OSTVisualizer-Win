import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from shiboken6 import delete, isValid
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.cover_sheet import JobStatus
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.loaded_file import LoadedFile
from ost_visualizer.domain.entities.project import Project
from ost_visualizer.presentation.components.project_tree_view import (
    _DELETED_PROJECT_UID,
    ProjectView,
)
from ost_visualizer.presentation.handlers.project_write_handler import (
    ProjectWriteHandler,
)
from ost_visualizer.presentation.handlers.file_operation_handler import (
    FileOperationHandler,
)
from ost_visualizer.presentation.managers.icon_manager import IconId, IconManager
from ost_visualizer.presentation.managers.ui_state_manager import UIStateManager


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
            SimpleNamespace(
                is_allowed=lambda _feature: True,
                can_edit_project=lambda _file_path, _project_uid: True,
                can_delete_bids=lambda refs: bool(refs),
                can_edit_bid_structure=lambda refs: bool(refs),
            )
        )
        self.view.on_can_delete_bids = lambda refs: bool(refs)
        self.view.on_can_delete_projects = lambda _file_path, project_uids: bool(
            project_uids
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

    def test_pending_rename_is_dropped_after_project_view_destruction(self):
        calls = []
        view = ProjectView(None, _EventBus())
        view._find_project_item = lambda *_args: calls.append(True) or (None, None)
        view.schedule_rename("project-1", "C:/jobs/test.mdb")
        delete(view)
        self.app.processEvents()
        self.assertEqual(calls, [])

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

    def test_project_copy_shortcut_wins_over_enabled_window_action(self):
        window = QtWidgets.QMainWindow()
        self.addCleanup(window.close)
        window.setCentralWidget(self.view)
        copied = []
        plan_copy_calls = []
        self.view.on_copy_bids = lambda refs: copied.append(list(refs))
        self.view.build_complete_structure(self._loaded_file(["bid-1"]))
        self._select_bid_items("bid-1")
        shared_copy = QtGui.QAction("Copy", window)
        shared_copy.setShortcut(QtGui.QKeySequence("Ctrl+C"))
        shared_copy.triggered.connect(lambda: plan_copy_calls.append(True))
        window.addAction(shared_copy)
        window.show()
        self.view.top_tree.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
        self.app.processEvents()
        QtTest.QTest.keyClick(
            self.view.top_tree,
            QtCore.Qt.Key.Key_C,
            QtCore.Qt.KeyboardModifier.ControlModifier,
        )
        QtTest.QTest.keyRelease(self.view.top_tree, QtCore.Qt.Key.Key_Control)
        self.app.processEvents()
        self.assertEqual(copied, [[BidRef("C:/jobs/test.mdb", "bid-1")]])
        self.assertEqual(plan_copy_calls, [])

    def test_project_context_submenus_remain_owned_until_menu_execution(self):
        self.view.build_complete_structure(self._loaded_file(["bid-1"]))
        item = self._select_bid_items("bid-1")[0]
        context = self.view._context_for_item(item)
        menu = QtWidgets.QMenu(self.view)
        self.view._build_project_context_menu(menu, context)
        submenus = {
            action.text(): action.menu()
            for action in menu.actions()
            if action.text() in {"New", "Import", "Export", "Change Job Status"}
        }
        self.assertEqual(
            set(submenus), {"New", "Import", "Export", "Change Job Status"}
        )
        self.assertTrue(all(isValid(submenu) for submenu in submenus.values()))

    def test_job_status_submenu_uses_uid_when_display_names_collide(self):
        bid = Bid(
            uid="bid-1",
            name="Bid",
            status="Duplicate",
            status_uid="status-current",
        )
        loaded = self._loaded_file([])
        loaded[0].projects[0].bids = [bid]
        self.view.on_get_job_statuses = lambda _file_path: [
            JobStatus(uid="status-other", name="Duplicate"),
            JobStatus(uid="status-current", name="Duplicate"),
        ]
        self.view.on_can_update_bid_job_status = lambda _bid_ref: True
        self.view.build_complete_structure(loaded)
        item = self._select_bid_items("bid-1")[0]
        context = self.view._context_for_item(item)
        menu = QtWidgets.QMenu(self.view)
        self.view._add_job_status_submenu(menu, context)
        actions = menu.actions()[0].menu().actions()
        self.assertFalse(actions[0].isChecked())
        self.assertTrue(actions[0].isEnabled())
        self.assertTrue(actions[1].isChecked())
        self.assertFalse(actions[1].isEnabled())

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
        self.view.on_multi_selection = (
            lambda bids, projects, file_path: multi_selections.append(
                (list(bids), list(projects), file_path)
            )
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
        _bid_refs, project_uids, project_file_path = (
            self.view._collect_multi_selection()
        )
        self.assertEqual(project_uids, [])
        self.assertIsNone(project_file_path)

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
        _bid_refs, project_uids, project_file_path = (
            self.view._collect_multi_selection()
        )
        self.assertEqual(project_uids, ["project-shared"])
        self.assertEqual(project_file_path, "C:/jobs/test.mdb")

    def test_group_by_job_status_does_not_merge_same_name_status_uids(self):
        loaded_file = LoadedFile(
            file_path="C:/jobs/test.mdb",
            display_name="test.mdb",
            projects=[
                Project(
                    uid="project-1",
                    name="Project",
                    bids=[
                        Bid(
                            uid="bid-a",
                            name="A",
                            status="Duplicate",
                            status_uid="status-a",
                        ),
                        Bid(
                            uid="bid-b",
                            name="B",
                            status="Duplicate",
                            status_uid="status-b",
                        ),
                    ],
                )
            ],
        )
        self.view._group_by_job_status = True
        self.view.build_complete_structure([loaded_file])
        file_item = self.view.top_tree.topLevelItem(0)
        self.assertEqual(file_item.childCount(), 2)
        self.assertEqual(
            [file_item.child(index).text(0) for index in range(2)],
            ["Duplicate", "Duplicate"],
        )

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

    def test_project_inline_rename_rejection_and_escape_keep_authoritative_label(self):
        for completion in ("enter", "focus_loss", "escape"):
            with self.subTest(completion=completion):
                calls = []
                self.view.on_rename_project = lambda *args: calls.append(args) or False
                self.view.build_complete_structure(self._loaded_file([]))
                self.view.show()
                item = self._find_item("project-1")
                self.view._start_project_rename(item, "project-1", "C:/jobs/test.mdb")
                self.app.processEvents()
                editor = self.view.top_tree.viewport().focusWidget()
                self.assertIsInstance(editor, QtWidgets.QLineEdit)
                QtTest.QTest.keyClicks(editor, "Rejected name")
                if completion == "focus_loss":
                    self.view.top_tree.setFocus()
                else:
                    key = (
                        QtCore.Qt.Key.Key_Escape
                        if completion == "escape"
                        else QtCore.Qt.Key.Key_Return
                    )
                    QtTest.QTest.keyClick(editor, key)
                self.app.processEvents()
                self.view.top_tree.setFocus()
                self.app.processEvents()
                self.assertEqual(item.text(0), "Source")
                self.assertEqual(len(calls), 0 if completion == "escape" else 1)
                self.assertIs(self.view.top_tree.currentItem(), item)
                self.assertIsNone(self.view._rename_item)

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

    def test_context_duplicate_targets_right_clicked_bid_in_multi_selection(self):
        config = SimpleNamespace(
            display_modes_synced=True,
            display_mode_3d="solid",
            display_mode_2d="solid",
            grayscale_enabled=False,
        )
        ui_state = UIStateManager(config)
        duplicate_calls = []
        write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _path: False,
            duplicate_bid=lambda file_path, bid_uid, reload=False: (
                duplicate_calls.append((file_path, bid_uid, reload)) or "new-bid"
            ),
            reload_database=lambda _path: True,
            notify_database_refreshed=lambda _path: None,
        )
        handler = ProjectWriteHandler(
            window=self.view,
            project_data_service=SimpleNamespace(
                get_hierarchy=lambda: SimpleNamespace(
                    find_bid_info=lambda ref: SimpleNamespace(name=ref.bid_uid)
                )
            ),
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=SimpleNamespace(
                flush_for_file=lambda _path: True
            ),
        )
        handler._run_progress_dialog = lambda _title, work, **_options: (
            QtWidgets.QDialog.DialogCode.Accepted,
            work(),
            None,
        )
        self.view.on_bid_selection = ui_state.set_bid_selection
        self.view.on_multi_selection = (
            lambda bids, _projects, _file_path: ui_state.set_bid_multi_selection(bids)
        )
        self.view.on_duplicate_bid = handler.duplicate_bid
        self.view.on_can_duplicate_bid = lambda _bid_ref: True
        self.view.build_complete_structure(self._loaded_file(["bid-1", "bid-2"]))
        bid_1 = self._find_item("bid-1")
        bid_2 = self._find_item("bid-2")
        self.view.top_tree.setCurrentItem(bid_1)
        bid_1.setSelected(True)
        bid_2.setSelected(True)
        self.view._prepare_context_menu_selection(bid_2)
        context = self.view._context_for_item(bid_2)
        menu = QtWidgets.QMenu(self.view)
        self.view._build_project_context_menu(menu, context)
        duplicate_action = next(
            action for action in menu.actions() if action.text() == "Duplicate"
        )
        duplicate_action.trigger()
        self.assertEqual(
            duplicate_calls,
            [("C:/jobs/test.mdb", "bid-2", False)],
        )
        duplicate_calls.clear()
        handler.duplicate_selected()
        self.assertEqual(
            duplicate_calls,
            [("C:/jobs/test.mdb", "bid-1", False)],
        )

    def test_context_duplicate_rejects_rebuilt_tree_owner(self):
        duplicate_calls = []
        self.view.on_duplicate_bid = duplicate_calls.append
        self.view.on_can_duplicate_bid = lambda _bid_ref: True
        self.view.build_complete_structure(self._loaded_file(["bid-1"]))
        bid_item = self._find_item("bid-1")
        self.view._prepare_context_menu_selection(bid_item)
        context = self.view._context_for_item(bid_item)
        menu = QtWidgets.QMenu(self.view)
        self.view._build_project_context_menu(menu, context)
        duplicate_action = next(
            action for action in menu.actions() if action.text() == "Duplicate"
        )
        self.view.build_complete_structure(self._loaded_file(["bid-1"]))
        duplicate_action.trigger()
        self.assertEqual(duplicate_calls, [])

    def test_context_close_targets_right_clicked_database(self):
        unloaded = []
        ui_state = SimpleNamespace(selected_file_path="C:/jobs/active.mdb")
        handler = FileOperationHandler(
            window=self.view,
            icon_provider=SimpleNamespace(),
            event_bus=_EventBus(),
            file_state_model=SimpleNamespace(
                file_entries=[], update_entries=lambda _entries: None
            ),
            cleanup_deleted_files_use_case=SimpleNamespace(),
            file_loading_service=SimpleNamespace(),
            working_directory_service=SimpleNamespace(),
            unload_file_fn=lambda file_path: unloaded.append(file_path) or True,
            deferred_persistence_manager=SimpleNamespace(
                flush_for_file=lambda _path: True,
                cancel_for_file=lambda _path: None,
            ),
            ui_access_manager=SimpleNamespace(),
            sql_collaboration_coordinator=SimpleNamespace(),
            workspace_state_model=SimpleNamespace(),
            ui_state_manager=ui_state,
        )
        self.view.on_close_database = handler.unload_file_path
        self.view.on_can_close_database = lambda _file_path: True
        self.view.on_menu_command = lambda command: (
            handler.unload_file() if command == "unload_file" else None
        )
        self.view.on_menu_command_enabled = lambda _command: True
        files = self._loaded_file([], file_path="C:/jobs/active.mdb")
        files.extend(self._loaded_file([], file_path="C:/jobs/other.mdb"))
        self.view.build_complete_structure(files)
        active_root = self.view._find_file_item("C:/jobs/active.mdb")
        other_root = self.view._find_file_item("C:/jobs/other.mdb")
        active_root.setSelected(True)
        other_root.setSelected(True)
        self.view._prepare_context_menu_selection(other_root)
        context = self.view._context_for_item(other_root)
        menu = QtWidgets.QMenu(self.view)
        self.view._build_project_context_menu(menu, context)
        close_action = next(
            action for action in menu.actions() if action.text() == "Close"
        )
        close_action.trigger()
        self.assertEqual(unloaded, ["C:/jobs/other.mdb"])

    def test_context_import_targets_right_clicked_project(self):
        imports = []
        active_target = ("C:/jobs/active.mdb", "active-project")
        self.view.on_import_project_file = (
            lambda format_key, file_path, project_uid: imports.append(
                (format_key, file_path, project_uid)
            )
        )
        self.view.on_can_import_project_file = (
            lambda _format_key, _file_path, _project_uid: True
        )
        self.view.on_menu_command = lambda command: (
            imports.append((command, *active_target))
            if command == "import_ost"
            else None
        )
        self.view.on_menu_command_enabled = lambda _command: True
        files = self._loaded_file([], file_path="C:/jobs/active.mdb")
        files[0].projects[0].uid = "active-project"
        other_files = self._loaded_file([], file_path="C:/jobs/other.mdb")
        other_files[0].projects[0].uid = "other-project"
        files.extend(other_files)
        self.view.build_complete_structure(files)
        other_project, _ = self.view._find_project_item(
            "other-project", "C:/jobs/other.mdb"
        )
        self.view._prepare_context_menu_selection(other_project)
        context = self.view._context_for_item(other_project)
        menu = QtWidgets.QMenu(self.view)
        self.view._build_project_context_menu(menu, context)
        import_menu = next(
            submenu
            for submenu in menu.findChildren(QtWidgets.QMenu)
            if submenu.title() == "Import"
        )
        import_ost_action = next(
            action
            for action in import_menu.actions()
            if action.text() == ".ost File..."
        )
        import_ost_action.trigger()
        self.assertEqual(
            imports,
            [("ost", "C:/jobs/other.mdb", "other-project")],
        )

    def test_context_new_commands_use_right_clicked_database_and_project(self):
        creates = []
        active_target = ("C:/jobs/active.mdb", "active-project")
        self.view.on_create_bid = lambda file_path, project_uid: creates.append(
            ("bid", file_path, project_uid)
        )
        self.view.on_create_project = lambda file_path: creates.append(
            ("project", file_path, None)
        )
        self.view.on_can_create_bid = lambda _file_path, _project_uid: True
        self.view.on_can_create_project = lambda _file_path: True
        self.view.on_menu_command = lambda command: (
            creates.append(
                (
                    "bid" if command == "new_project" else "project",
                    *active_target,
                )
            )
            if command in {"new_project", "new_folder"}
            else None
        )
        self.view.on_menu_command_enabled = lambda _command: True
        files = self._loaded_file([], file_path="C:/jobs/active.mdb")
        files[0].projects[0].uid = "active-project"
        other_files = self._loaded_file([], file_path="C:/jobs/other.mdb")
        other_files[0].projects[0].uid = "other-project"
        files.extend(other_files)
        self.view.build_complete_structure(files)
        other_project, _ = self.view._find_project_item(
            "other-project", "C:/jobs/other.mdb"
        )
        self.view._prepare_context_menu_selection(other_project)
        context = self.view._context_for_item(other_project)
        menu = QtWidgets.QMenu(self.view)
        self.view._build_project_context_menu(menu, context)
        new_menu = next(
            submenu
            for submenu in menu.findChildren(QtWidgets.QMenu)
            if submenu.title() == "New"
        )
        next(
            action for action in new_menu.actions() if action.text() == "Project"
        ).trigger()
        next(
            action for action in new_menu.actions() if action.text() == "Folder"
        ).trigger()
        self.assertEqual(
            creates,
            [
                ("bid", "C:/jobs/other.mdb", "other-project"),
                ("project", "C:/jobs/other.mdb", None),
            ],
        )

    def test_nonactive_bid_context_disables_active_only_export_and_renumber(self):
        active_ref = ("C:/jobs/test.mdb", "bid-1")
        self.view.on_is_active_bid_context = (
            lambda bid_ref: (
                bid_ref.file_path,
                bid_ref.bid_uid,
            )
            == active_ref
        )
        self.view.on_menu_command_enabled = lambda _command: True
        self.view.on_export_formats = lambda: ["html"]
        self.view.on_can_renumber_conditions = lambda: True
        self.view.build_complete_structure(self._loaded_file(["bid-1", "bid-2"]))
        bid_1 = self._find_item("bid-1")
        bid_2 = self._find_item("bid-2")
        bid_1.setSelected(True)
        bid_2.setSelected(True)
        self.view._prepare_context_menu_selection(bid_2)
        context = self.view._context_for_item(bid_2)
        menu = QtWidgets.QMenu(self.view)
        self.view._build_project_context_menu(menu, context)
        export_menu = next(
            submenu
            for submenu in menu.findChildren(QtWidgets.QMenu)
            if submenu.title() == "Export"
        )
        renumber_action = next(
            action
            for action in menu.actions()
            if action.text() == "Renumber Conditions"
        )
        self.assertFalse(export_menu.isEnabled())
        self.assertFalse(renumber_action.isEnabled())

    def test_active_bid_export_rechecks_owner_before_trigger(self):
        active = {"uid": "bid-1"}
        commands = []
        self.view.on_is_active_bid_context = (
            lambda bid_ref: bid_ref.bid_uid == active["uid"]
        )
        self.view.on_menu_command_enabled = lambda _command: True
        self.view.on_menu_command = commands.append
        self.view.on_export_formats = lambda: []
        self.view.build_complete_structure(self._loaded_file(["bid-1", "bid-2"]))
        bid_1 = self._find_item("bid-1")
        self.view._prepare_context_menu_selection(bid_1)
        context = self.view._context_for_item(bid_1)
        menu = QtWidgets.QMenu(self.view)
        self.view._build_project_context_menu(menu, context)
        export_menu = next(
            submenu
            for submenu in menu.findChildren(QtWidgets.QMenu)
            if submenu.title() == "Export"
        )
        pdf_action = next(
            action
            for action in export_menu.actions()
            if action.text() == "To .pdf File"
        )
        self.assertTrue(pdf_action.isEnabled())
        active["uid"] = "bid-2"
        pdf_action.trigger()
        self.assertEqual(commands, [])

    def test_project_context_delete_is_disabled_for_mixed_bid_selection(self):
        self.view.on_menu_command_enabled = lambda _command: True
        self.view.build_complete_structure(self._loaded_file(["bid-1"]))
        project, _ = self.view._find_project_item("project-1", "C:/jobs/test.mdb")
        bid = self._find_item("bid-1")
        project.setSelected(True)
        bid.setSelected(True)
        self.view._prepare_context_menu_selection(project)
        context = self.view._context_for_item(project)
        menu = QtWidgets.QMenu(self.view)
        self.view._build_project_context_menu(menu, context)
        delete_action = next(
            action for action in menu.actions() if action.text() == "Delete"
        )
        self.assertFalse(delete_action.isEnabled())

    def test_project_context_delete_is_disabled_across_databases(self):
        self.view.on_menu_command_enabled = lambda _command: True
        files = self._loaded_file([], file_path="C:/jobs/active.mdb")
        files[0].projects[0].uid = "active-project"
        other = self._loaded_file([], file_path="C:/jobs/other.mdb")
        other[0].projects[0].uid = "other-project"
        files.extend(other)
        self.view.build_complete_structure(files)
        active_project, _ = self.view._find_project_item(
            "active-project", "C:/jobs/active.mdb"
        )
        other_project, _ = self.view._find_project_item(
            "other-project", "C:/jobs/other.mdb"
        )
        active_project.setSelected(True)
        other_project.setSelected(True)
        self.view._prepare_context_menu_selection(other_project)
        context = self.view._context_for_item(other_project)
        menu = QtWidgets.QMenu(self.view)
        self.view._build_project_context_menu(menu, context)
        delete_action = next(
            action for action in menu.actions() if action.text() == "Delete"
        )
        self.assertFalse(delete_action.isEnabled())

    def test_project_context_delete_uses_captured_database_and_projects(self):
        deletes = []
        self.view.on_delete_projects = lambda file_path, project_uids: deletes.append(
            (file_path, list(project_uids))
        )
        self.view.on_can_delete_projects = lambda _file_path, _project_uids: True
        self.view.on_menu_command = lambda command: (
            deletes.append(("C:/jobs/active.mdb", ["active-project"]))
            if command == "delete"
            else None
        )
        self.view.on_menu_command_enabled = lambda _command: True
        files = self._loaded_file([], file_path="C:/jobs/active.mdb")
        other = self._loaded_file([], file_path="C:/jobs/other.mdb")
        other[0].projects[0].uid = "other-project-1"
        other[0].projects[1].uid = "other-project-2"
        files.extend(other)
        self.view.build_complete_structure(files)
        first, _ = self.view._find_project_item("other-project-1", "C:/jobs/other.mdb")
        second, _ = self.view._find_project_item("other-project-2", "C:/jobs/other.mdb")
        first.setSelected(True)
        second.setSelected(True)
        self.view._prepare_context_menu_selection(second)
        context = self.view._context_for_item(second)
        menu = QtWidgets.QMenu(self.view)
        self.view._build_project_context_menu(menu, context)
        next(action for action in menu.actions() if action.text() == "Delete").trigger()
        self.assertEqual(
            deletes,
            [
                (
                    "C:/jobs/other.mdb",
                    ["other-project-1", "other-project-2"],
                )
            ],
        )

    def test_project_multi_selection_carries_owning_database(self):
        selections = []
        self.view.on_multi_selection = lambda *args: selections.append(args)
        files = self._loaded_file([], file_path="C:/jobs/active.mdb")
        other = self._loaded_file([], file_path="C:/jobs/other.mdb")
        other[0].projects[0].uid = "other-project-1"
        other[0].projects[1].uid = "other-project-2"
        files.extend(other)
        self.view.build_complete_structure(files)
        first, _ = self.view._find_project_item("other-project-1", "C:/jobs/other.mdb")
        second, _ = self.view._find_project_item("other-project-2", "C:/jobs/other.mdb")
        first.setSelected(True)
        second.setSelected(True)
        self.view._on_top_selection_change()
        self.assertEqual(
            selections[-1],
            ([], ["other-project-1", "other-project-2"], "C:/jobs/other.mdb"),
        )

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

    def test_tree_rebuild_cancels_context_menu_press_from_previous_rows(self):
        self.view.build_complete_structure(self._loaded_file(["bid-1"]))
        self.view.top_tree.expandAll()
        old_item = self._find_item("bid-1")
        self.view.top_tree.scrollToItem(old_item)
        self.app.processEvents()
        pos = self.view.top_tree.visualItemRect(old_item).center()
        emitted_positions = []
        self.view.top_tree.customContextMenuRequested.disconnect()
        self.view.top_tree.customContextMenuRequested.connect(
            lambda emitted_pos: emitted_positions.append(emitted_pos)
        )
        QtTest.QTest.mousePress(
            self.view.top_tree.viewport(),
            QtCore.Qt.MouseButton.RightButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
            pos,
        )
        self.view.build_complete_structure(self._loaded_file(["bid-2"]))
        self.view.top_tree.expandAll()
        self.app.processEvents()
        QtTest.QTest.mouseRelease(
            self.view.top_tree.viewport(),
            QtCore.Qt.MouseButton.RightButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
            pos,
        )
        self.assertEqual(emitted_positions, [])

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

    def test_stale_project_context_rename_is_rejected_after_tree_rebuild(self):
        self.view.build_complete_structure(self._loaded_file([]))
        original_item = self._find_item("project-1")
        context = self.view._context_for_item(original_item)
        replacement_files = self._loaded_file([])
        replacement_files[0].projects[0].name = "Replacement"
        self.view.build_complete_structure(replacement_files)
        self.view._rename_context(context)
        self.assertIsNone(self.view._rename_item)
        self.assertEqual(self._find_item("project-1").text(0), "Replacement")

    def test_context_rename_uses_right_clicked_project_permission(self):
        self.view.set_ui_access_manager(
            SimpleNamespace(
                is_allowed=lambda _feature: True,
                can_edit_project=lambda file_path, _project_uid: (
                    file_path == "C:/jobs/active.mdb"
                ),
            )
        )
        files = self._loaded_file([], file_path="C:/jobs/active.mdb")
        other_files = self._loaded_file([], file_path="C:/jobs/other.mdb")
        other_files[0].projects[0].uid = "other-project"
        files.extend(other_files)
        self.view.build_complete_structure(files)
        other_project, _ = self.view._find_project_item(
            "other-project", "C:/jobs/other.mdb"
        )
        context = self.view._context_for_item(other_project)
        self.assertFalse(self.view._can_rename_context(context))

    def test_project_tree_rebuild_cancels_active_drag_items(self):
        self.view.build_complete_structure(self._loaded_file(["bid-1"]))
        self.view.top_tree._drag_items = [self._find_item("bid-1")]
        self.view.top_tree._drag_file_path = "C:/jobs/test.mdb"
        self.view.build_complete_structure(self._loaded_file(["bid-1"]))
        self.assertEqual(self.view.top_tree._drag_items, [])
        self.assertIsNone(self.view.top_tree._drag_file_path)

    def test_project_drop_after_model_rebuild_is_ignored_without_mutation(self):
        self.view.build_complete_structure(self._loaded_file(["bid-1"]))
        tree = self.view.top_tree
        tree._drag_items = [self._find_item("bid-1")]
        tree._drag_file_path = "C:/jobs/test.mdb"
        moved = []
        tree.on_move_bids = lambda refs, project_uid: moved.append(
            (list(refs), project_uid)
        )
        self.view.build_complete_structure(self._loaded_file(["bid-1"]))
        target, _file_item = self.view._find_project_item(
            "project-2",
            "C:/jobs/test.mdb",
        )
        tree.itemAt = lambda _position: target
        accepted = []
        ignored = []
        event = SimpleNamespace(
            position=lambda: QtCore.QPointF(),
            acceptProposedAction=lambda: accepted.append(True),
            ignore=lambda: ignored.append(True),
        )
        tree.dropEvent(event)
        self.assertEqual(accepted, [])
        self.assertEqual(ignored, [True])
        self.assertEqual(moved, [])

    def test_project_context_command_rejects_replaced_tree_owner(self):
        commands = []
        self.view.on_menu_command = commands.append
        self.view.on_menu_command_enabled = lambda _key: True
        self.view.build_complete_structure(self._loaded_file(["bid-1"]))
        bid_item = self._find_item("bid-1")
        self.view._prepare_context_menu_selection(bid_item)
        context = self.view._context_for_item(bid_item)
        menu = QtWidgets.QMenu()
        self.view._build_project_context_menu(menu, context)
        delete_action = next(
            action for action in menu.actions() if action.text() == "Delete"
        )
        self.view.build_complete_structure(self._loaded_file(["bid-1"]))
        delete_action.trigger()
        self.assertEqual(commands, [])

    def test_project_context_command_rejects_changed_selection(self):
        commands = []
        self.view.on_menu_command = commands.append
        self.view.on_menu_command_enabled = lambda _key: True
        self.view.build_complete_structure(self._loaded_file(["bid-1", "bid-2"]))
        bid_1 = self._find_item("bid-1")
        self.view._prepare_context_menu_selection(bid_1)
        context = self.view._context_for_item(bid_1)
        menu = QtWidgets.QMenu()
        self.view._build_project_context_menu(menu, context)
        delete_action = next(
            action for action in menu.actions() if action.text() == "Delete"
        )
        bid_2 = self._find_item("bid-2")
        self.view.top_tree.clearSelection()
        self.view.top_tree.setCurrentItem(bid_2)
        bid_2.setSelected(True)
        delete_action.trigger()
        self.assertEqual(commands, [])

    def test_project_context_expand_action_ignores_qaction_checked_argument(self):
        self.view.build_complete_structure(self._loaded_file(["bid-1"]))
        bid_item = self._find_item("bid-1")
        self.view._prepare_context_menu_selection(bid_item)
        context = self.view._context_for_item(bid_item)
        menu = QtWidgets.QMenu()
        self.view._build_project_context_menu(menu, context)
        expand_action = next(
            action for action in menu.actions() if action.text() == "Expand All"
        )
        expand_action.trigger()
        self.assertTrue(bid_item.parent().isExpanded())

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
