import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.services.project_write_service import WriteReloadResult
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.loaded_file import LoadedFile
from ost_visualizer.domain.entities.project import Project
from ost_visualizer.presentation.components.project_tree_view import (
    _DELETED_PROJECT_UID,
    ProjectView,
)
from ost_visualizer.presentation.handlers.file_operation_handler import (
    FileOperationHandler,
)
from ost_visualizer.presentation.handlers.project_write_handler import (
    ProjectWriteHandler,
)
from ost_visualizer.presentation.managers.ui_state_manager import UIStateManager
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from tests.presentation.components.project_tree_support import (
    _EventBus as _project_tree_support__EventBus,
    _app as _project_tree_support__app,
)


class ProjectTreeCommandWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _project_tree_support__app()

    def tearDown(self):
        self.view.deleteLater()
        self.app.processEvents()

    def setUp(self):
        self.view = ProjectView(None, _project_tree_support__EventBus())
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
            duplicate_bid_result=lambda file_path, bid_uid, reload=False: (
                duplicate_calls.append((file_path, bid_uid, reload))
                or WriteReloadResult("new-bid", True, True)
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

    def test_context_close_targets_right_clicked_database(self):
        unloaded = []
        ui_state = SimpleNamespace(selected_file_path="C:/jobs/active.mdb")
        handler = FileOperationHandler(
            window=self.view,
            icon_provider=SimpleNamespace(),
            event_bus=_project_tree_support__EventBus(),
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
