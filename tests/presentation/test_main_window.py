from __future__ import annotations
import ast
from ost_visualizer.presentation.config import MAIN_WINDOW_TITLE
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.bid import Bid
from tests.helpers.workspace_state import make_workspace_state_model
from PySide6 import QtCore, QtWidgets
from ost_visualizer.presentation.utils.persistent_header import (
    PersistentHeaderController,
)
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.config import (
    TAB_INDEX_PROJECTS,
    TAB_INDEX_SUMMARY,
    TAB_INDEX_TAKEOFF,
)
from ost_visualizer.presentation.components.condition_summary import ConditionSummaryTab
from ost_visualizer.domain.services.uom_service import CALC_COUNT, UOM_EACH
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.application.use_cases.project.condition_summary_service import (
    ConditionSummaryService,
)
from types import SimpleNamespace
import os
import unittest
from pathlib import Path
import logging
from unittest.mock import patch
from ost_visualizer.application.dtos.collaboration_dtos import (
    CollaborationShutdownState,
    DatabaseMutationResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
    WriteReloadResult,
)
from ost_visualizer.presentation.managers.deferred_persistence_manager import (
    DeferredPersistenceManager,
)
from tests.presentation.managers.deferred_persistence_support import (
    FakeCloseEvent,
    FakeProjectWriteService,
    FakeSqlWorkspaceService,
    _workspace_service,
)
from ost_visualizer.application.dtos.snap_preferences_dto import SnapPreferencesDto
from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
from ost_visualizer.domain.entities.config import Config
from PySide6 import QtCore, QtGui, QtWidgets
from tests.presentation.dialogs.options.preference_support import (
    FakeConfigRepository as _preferences_support_FakeConfigRepository,
    SNAP_PREF_UPDATE as _preferences_support_SNAP_PREF_UPDATE,
    _app as _preferences_support__app,
)
import tempfile
from ost_visualizer.application.dtos.file_import_args import (
    PROJECT_IMPORT_EXTENSION_OSP,
    PROJECT_IMPORT_EXTENSION_OST,
    parse_project_file_args,
)
from ost_visualizer.application.use_cases.project import (
    import_project_files_from_args_use_case as import_args_use_case,
)
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.domain.entities.project_constants import (
    DELETED_BIDS_PROJECT_NAME,
    DELETED_BIDS_PROJECT_UID,
)
from ost_visualizer.presentation import main_window as main_window_module
from PySide6 import QtWidgets
from tests.helpers.startup_import import (
    FakeProjectView as _startup_import_FakeProjectView,
    FakeStartupProgressDialog as _startup_import_FakeStartupProgressDialog,
    FakeTimerQueue as _startup_import_FakeTimerQueue,
    _project_file_args as _startup_import__project_file_args,
    _startup_import_window as _startup_import__startup_import_window,
)
from unittest.mock import Mock, patch
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from ost_visualizer.domain.entities.cover_sheet import JobStatus
from shiboken6 import delete
from tests.presentation.utils.dialog_lifecycle_support import (
    FakeProgressDialog as _dialog_lifecycle_support_FakeProgressDialog,
    _app as _dialog_lifecycle_support__app,
)
from ost_visualizer.presentation.managers.ui_state_manager import UIStateManager

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.workspace_state import (
    HeaderLayoutState,
    WorkspaceState,
)
from tests.presentation.coordinators.workspace_restore_support import (
    FakeCheckAction as _detached_support_FakeCheckAction,
    FakeSplitterForSidebarSizes as _detached_support_FakeSplitterForSidebarSizes,
    _encoded_geometry as _detached_support__encoded_geometry,
)
from ost_visualizer.presentation.config import (
    TAB_INDEX_TAKEOFF,
    VIEWER_SCALE_COMBO_WIDTH,
)
from ost_visualizer.presentation.windows.components.window import DetachedPageViewWindow
from tests.presentation.coordinators.workspace_restore_support import (
    FakeCheckAction as _detached_support_FakeCheckAction,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TEST_DB_NAME = "OST Projects.mdb"
TEST_DB_PATH = rf"C:\jobs\{TEST_DB_NAME}"
TEST_BID_UID = "bid-24"
TEST_BID_NO = 24
TEST_BID_NAME = "26-040 Dulles Plaza, VA"


def _database_title(database_name=TEST_DB_NAME):
    return f"{database_name} - {MAIN_WINDOW_TITLE}"


def _bid_title(bid_label, database_name=TEST_DB_NAME):
    return f"{bid_label}; {_database_title(database_name)}"


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _attach_summary_header(tab):
    controller = PersistentHeaderController(
        tab.tree,
        "condition_summary_test",
        tab.column_keys,
        make_workspace_state_model(),
        sorting=True,
        movable=True,
        default_sort_column="name",
    )
    tab.columns_about_to_change.connect(controller.begin_columns_update)
    tab.columns_changed.connect(controller.end_columns_update)
    return controller


class MainWindowHandlerCompositionTests(unittest.TestCase):
    def test_main_window_handler_factory_uses_owned_app_controller(self):
        tree = ast.parse(
            Path("ost_visualizer/presentation/main_window.py").read_text(
                encoding="utf-8"
            )
        )
        handler_factory = next(
            node
            for class_node in ast.walk(tree)
            if isinstance(class_node, ast.ClassDef) and class_node.name == "MainWindow"
            for node in class_node.body
            if isinstance(node, ast.FunctionDef) and node.name == "_create_handlers"
        )
        bare_app_controller_names = [
            node
            for node in ast.walk(handler_factory)
            if isinstance(node, ast.Name) and node.id == "app_controller"
        ]
        owned_app_controller_reads = [
            node
            for node in ast.walk(handler_factory)
            if isinstance(node, ast.Attribute)
            and node.attr == "app_controller"
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        ]
        self.assertEqual(bare_app_controller_names, [])
        self.assertGreaterEqual(len(owned_app_controller_reads), 4)


class MainWindowSummaryActionTests(unittest.TestCase):
    def setUp(self):
        _app()
        self.service = ConditionSummaryService()
        self.condition = Condition(
            uid="c1",
            name="Fdn1",
            condition_type=Condition.TYPE_COUNT,
            height=24.0,
            color_fill=0x336699,
            cdn_type_uid="t1",
            cdn_type_name="AB - Spread Interior FTG",
            uom1=UOM_EACH,
            calc_type1=CALC_COUNT,
            ref_no=1,
        )
        self.conditions = {"c1": self.condition}
        self.pages = [Page(uid="p1", name="S-100.pdf", sequence=1)]
        self.areas = [
            BidArea(uid="a1", bid_uid="b1", parent_uid="", name="L-0 FDN", sequence=1),
            BidArea(uid="a2", bid_uid="b1", parent_uid="", name="L-2 FDN", sequence=2),
        ]
        self.takeoffs = [
            Takeoff(uid="tk1", condition_uid="c1", page_uid="p1", area_uid="a1"),
            Takeoff(uid="tk2", condition_uid="c1", page_uid="p1", area_uid="a2"),
        ]
        self.tab = ConditionSummaryTab(
            None,
            uom_label_fn=lambda code: "EA" if code == UOM_EACH else "",
            copy_allowed_fn=lambda: True,
            delete_allowed_fn=lambda: True,
        )
        self.header_controller = _attach_summary_header(self.tab)

    def tearDown(self):
        self.tab.deleteLater()

    def test_main_window_summary_delete_routes_to_summary_tab(self):
        calls = []
        window = MainWindow.__new__(MainWindow)
        window._handle_inline_text_shortcut = lambda _action: False
        window.tab_widget = SimpleNamespace(currentIndex=lambda: TAB_INDEX_SUMMARY)
        window._condition_summary_tab = SimpleNamespace(
            delete_current_row=lambda: calls.append("summary-delete")
        )
        window.ui_access_manager = SimpleNamespace(
            is_allowed=lambda feature: feature == Feature.DELETE_CONDITION
        )
        window.project_view = SimpleNamespace(
            get_delete_replacement_selection_state=lambda: (_ for _ in ()).throw(
                AssertionError("project tree delete should not run")
            )
        )
        window.handlers = SimpleNamespace(
            delete=SimpleNamespace(
                delete_selected=lambda *_args: (_ for _ in ()).throw(
                    AssertionError("bid delete should not run")
                )
            )
        )
        MainWindow._delete_selected(window)
        self.assertEqual(calls, ["summary-delete"])

    def test_main_window_summary_delete_is_blocked_without_delete_condition_access(
        self,
    ):
        window = MainWindow.__new__(MainWindow)
        window._handle_inline_text_shortcut = lambda _action: False
        window.tab_widget = SimpleNamespace(currentIndex=lambda: TAB_INDEX_SUMMARY)
        window._condition_summary_tab = SimpleNamespace(
            delete_current_row=lambda: self.fail("Denied access must not delete")
        )
        window.ui_access_manager = SimpleNamespace(
            is_allowed=lambda feature: feature != Feature.DELETE_CONDITION
        )
        window.handlers = SimpleNamespace(
            delete=SimpleNamespace(
                delete_selected=lambda *_args: self.fail("bid delete should not run")
            )
        )
        MainWindow._delete_selected(window)

    def test_main_window_summary_paste_does_nothing(self):
        window = MainWindow.__new__(MainWindow)
        window._handle_inline_text_shortcut = lambda _action: False
        window.tab_widget = SimpleNamespace(currentIndex=lambda: TAB_INDEX_SUMMARY)
        window.plan_view = SimpleNamespace(
            paste_clipboard=lambda: self.fail("plan paste must not run on Summary")
        )
        MainWindow._paste_clipboard(window)

    def test_main_window_inline_text_shortcut_consumes_delete_copy_and_paste(self):
        window = MainWindow.__new__(MainWindow)
        window._handle_inline_text_shortcut = lambda _action: True
        window.tab_widget = SimpleNamespace(
            currentIndex=lambda: self.fail("a consumed shortcut must not route tabs")
        )
        MainWindow._delete_selected(window)
        MainWindow._copy_selected(window)
        MainWindow._paste_clipboard(window)

    def test_main_window_summary_copy_routes_to_summary_tab(self):
        calls = []
        window = MainWindow.__new__(MainWindow)
        window._handle_inline_text_shortcut = lambda _action: False
        window.tab_widget = SimpleNamespace(currentIndex=lambda: TAB_INDEX_SUMMARY)
        window._condition_summary_tab = SimpleNamespace(
            copy_current_row=lambda: calls.append("summary-copy")
        )
        window.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: (_ for _ in ()).throw(
                AssertionError("bid copy should not be queried")
            )
        )
        window.ui_state_manager = SimpleNamespace(
            get_selected_bid_refs=lambda: (_ for _ in ()).throw(
                AssertionError("project selection should not be read")
            )
        )
        window._bid_clipboard = SimpleNamespace(
            copy=lambda *_args: (_ for _ in ()).throw(
                AssertionError("bid clipboard should not be used")
            )
        )
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(refresh_toolbar=lambda: None)
        )
        MainWindow._copy_selected(window)
        self.assertEqual(calls, ["summary-copy"])

    def test_main_window_plan_paste_delegates_without_broad_edit_gate(self):
        calls = []
        window = MainWindow.__new__(MainWindow)
        window._handle_inline_text_shortcut = lambda _action: False
        window.tab_widget = SimpleNamespace(currentIndex=lambda: TAB_INDEX_TAKEOFF)
        window.plan_view = SimpleNamespace(
            paste_clipboard=lambda: calls.append("plan-paste")
        )
        window.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: (_ for _ in ()).throw(
                AssertionError("plan paste must use its content-specific predicate")
            )
        )
        window._plan_view_handler = SimpleNamespace(
            can_paste_to_current_bid=lambda: (_ for _ in ()).throw(
                AssertionError("the plan view owns paste availability")
            )
        )
        MainWindow._paste_clipboard(window)
        self.assertEqual(calls, ["plan-paste"])


class MainWindowDeferredShutdownTests(unittest.TestCase):
    def setUp(self):
        # These partial MainWindow fixtures do not construct detached managers.
        for name, result in (("_detached_plan_windows", ()), ("get_mesh_window", None)):
            patcher = patch.object(MainWindow, name, return_value=result)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_tentative_shutdown_hides_owned_windows_and_abort_restores_visibility(self):
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        window = MainWindow.__new__(MainWindow)
        QtWidgets.QMainWindow.__init__(window)
        window.showEvent = lambda event: QtWidgets.QMainWindow.showEvent(window, event)
        plan, mesh, hidden_plan = [QtWidgets.QWidget() for _ in range(3)]
        for widget in (window, plan, mesh, hidden_plan):
            self.addCleanup(widget.deleteLater)
        window.handlers = SimpleNamespace(
            file_ops=SimpleNamespace(
                maintenance_pending=False, sql_creation_pending=False
            )
        )
        window._collaboration_shutdown_pending = False
        window._collaboration_shutdown_complete = False
        window._collaboration_shutdown_failed = False
        window._shutdown_deferred_callbacks = {}
        window._begin_application_shutdown = lambda: None
        window._detached_plan_windows = lambda: (plan, hidden_plan)
        window.get_mesh_window = lambda: mesh
        for widget in (window, plan, mesh):
            widget.show()
        app.processEvents()
        scheduled = []
        with patch.object(
            QtCore.QTimer, "singleShot", side_effect=lambda _, fn: scheduled.append(fn)
        ):
            window.close()
            self.assertTrue(window._collaboration_shutdown_pending)
            self.assertEqual(len(scheduled), 1)
            self.assertFalse(window.isVisible())
            self.assertFalse(plan.isVisible())
            self.assertFalse(mesh.isVisible())
            self.assertIs(window.get_mesh_window(), mesh)
            self.assertEqual(window._detached_plan_windows(), (plan, hidden_plan))
            window._collaboration_shutdown_pending = False
            window.show()
            window._resume_shutdown_deferred_callbacks()
            self.assertTrue(plan.isVisible())
            self.assertTrue(mesh.isVisible())
            self.assertFalse(hidden_plan.isVisible())
            window.close()
            window.get_mesh_window = lambda: None
            window._collaboration_shutdown_pending = False
            window.show()
            window._resume_shutdown_deferred_callbacks()
            self.assertTrue(plan.isVisible())
            self.assertFalse(mesh.isVisible())
        for widget in (window, plan, mesh):
            widget.hide()

    @staticmethod
    def _guarded_shutdown_callback(window, key, calls):
        def callback():
            if MainWindow._defer_during_application_shutdown(window, key, callback):
                return
            calls.append(key)

        return callback

    def test_callbacks_crossing_repeated_tentative_shutdown_run_once_in_order(self):
        window = MainWindow.__new__(MainWindow)
        window._collaboration_shutdown_pending = True
        window._collaboration_shutdown_complete = False
        window._application_shutdown_finalized = False
        window._shutdown_deferred_callbacks = {}
        calls = []
        callbacks = [
            self._guarded_shutdown_callback(window, key, calls)
            for key in ("first", "second", "third")
        ]
        for callback in callbacks:
            callback()
        scheduled = []
        with patch.object(
            QtCore.QTimer,
            "singleShot",
            side_effect=lambda _delay, callback: scheduled.append(callback),
        ):
            window._collaboration_shutdown_pending = False
            MainWindow._resume_shutdown_deferred_callbacks(window)
            window._collaboration_shutdown_pending = True
            while scheduled:
                scheduled.pop(0)()
            self.assertEqual(calls, [])
            window._collaboration_shutdown_pending = False
            MainWindow._resume_shutdown_deferred_callbacks(window)
            while scheduled:
                scheduled.pop(0)()
            self.assertEqual(calls, ["first", "second", "third"])
            self.assertEqual(window._shutdown_deferred_callbacks, {})
            MainWindow._resume_shutdown_deferred_callbacks(window)
            self.assertEqual(scheduled, [])
        self.assertEqual(calls, ["first", "second", "third"])

    def test_callbacks_crossing_repeated_tentative_shutdown_stay_discarded(self):
        window = MainWindow.__new__(MainWindow)
        window._collaboration_shutdown_pending = True
        window._collaboration_shutdown_complete = False
        window._application_shutdown_finalized = False
        window._shutdown_deferred_callbacks = {}
        calls = []
        callback = self._guarded_shutdown_callback(window, "work", calls)
        callback()
        scheduled = []
        with patch.object(
            QtCore.QTimer,
            "singleShot",
            side_effect=lambda _delay, queued: scheduled.append(queued),
        ):
            window._collaboration_shutdown_pending = False
            MainWindow._resume_shutdown_deferred_callbacks(window)
            window._collaboration_shutdown_pending = True
            scheduled.pop(0)()
            window._collaboration_shutdown_complete = True
            self.assertEqual(list(window._shutdown_deferred_callbacks), ["work"])
            MainWindow._discard_shutdown_deferred_callbacks(window)
            self.assertEqual(window._shutdown_deferred_callbacks, {})
            window._collaboration_shutdown_pending = False
            MainWindow._resume_shutdown_deferred_callbacks(window)
            while scheduled:
                scheduled.pop(0)()
        self.assertEqual(calls, [])

    def test_update_check_completion_before_shutdown_emits(self):
        emitted = []
        window = SimpleNamespace(
            _update_service=SimpleNamespace(
                check_for_updates=lambda: (True, {"version": "2.0"})
            ),
            _collaboration_shutdown_pending=False,
            _collaboration_shutdown_complete=False,
            _application_shutdown_finalized=False,
            _shutdown_deferred_callbacks={},
            update_dialog_requested=SimpleNamespace(emit=emitted.append),
        )
        window._application_shutdown_terminal = lambda: (
            MainWindow._application_shutdown_terminal(window)
        )
        window._defer_during_application_shutdown = lambda key, callback: (
            MainWindow._defer_during_application_shutdown(window, key, callback)
        )
        window._check_for_updates = lambda: MainWindow._check_for_updates(window)
        started = []
        thread = SimpleNamespace(start=lambda: started.append(True))
        with patch(
            "ost_visualizer.presentation.main_window.threading.Thread",
            return_value=thread,
        ) as thread_factory:
            MainWindow._check_for_updates(window)
        self.assertEqual(started, [True])
        self.assertTrue(thread_factory.call_args.kwargs["daemon"])
        self.assertEqual(emitted, [])
        thread_factory.call_args.kwargs["target"]()
        self.assertEqual(emitted, [{"version": "2.0"}])

    def _update_check_window(self, check_for_updates):
        window = SimpleNamespace(
            _update_service=SimpleNamespace(check_for_updates=check_for_updates),
            _collaboration_shutdown_pending=False,
            _collaboration_shutdown_complete=False,
            _application_shutdown_finalized=False,
            _shutdown_deferred_callbacks={},
            update_dialog_requested=SimpleNamespace(
                emit=lambda info: self.fail(f"Unexpected update dialog: {info}")
            ),
        )
        window._application_shutdown_terminal = lambda: (
            MainWindow._application_shutdown_terminal(window)
        )
        window._defer_during_application_shutdown = lambda key, callback: (
            MainWindow._defer_during_application_shutdown(window, key, callback)
        )
        window._check_for_updates = lambda: MainWindow._check_for_updates(window)
        return window

    def test_update_check_without_available_update_does_not_emit(self):
        for result in ((False, {"version": "2.0"}), (True, None), (True, {})):
            with self.subTest(result=result):
                window = self._update_check_window(lambda result=result: result)
                with patch(
                    "ost_visualizer.presentation.main_window.threading.Thread"
                ) as thread_factory:
                    MainWindow._check_for_updates(window)
                thread_factory.call_args.kwargs["target"]()

    def test_update_check_failure_is_logged_and_not_raised(self):
        def explode():
            raise RuntimeError("update server down")

        window = self._update_check_window(explode)
        with patch(
            "ost_visualizer.presentation.main_window.threading.Thread"
        ) as thread_factory:
            MainWindow._check_for_updates(window)
        with self.assertLogs(
            "ost_visualizer.presentation.main_window", level="ERROR"
        ) as captured:
            thread_factory.call_args.kwargs["target"]()
        self.assertIn("update server down", captured.output[0])

    def test_update_check_without_service_starts_no_thread(self):
        window = self._update_check_window(lambda: (True, {"version": "2.0"}))
        window._update_service = None
        with patch(
            "ost_visualizer.presentation.main_window.threading.Thread"
        ) as thread_factory:
            MainWindow._check_for_updates(window)
        thread_factory.assert_not_called()

    def test_update_check_requested_during_tentative_shutdown_is_queued_not_started(
        self,
    ):
        window = MainWindow.__new__(MainWindow)
        window._collaboration_shutdown_pending = True
        window._collaboration_shutdown_complete = False
        window._application_shutdown_finalized = False
        window._shutdown_deferred_callbacks = {}
        window._update_service = SimpleNamespace(
            check_for_updates=lambda: self.fail("must not check during shutdown")
        )
        with patch(
            "ost_visualizer.presentation.main_window.threading.Thread"
        ) as thread_factory:
            MainWindow._check_for_updates(window)
        thread_factory.assert_not_called()
        self.assertEqual(
            list(window._shutdown_deferred_callbacks), ["check_for_updates"]
        )

    def test_update_check_completion_after_shutdown_does_not_emit(self):
        emitted = []
        window = SimpleNamespace(
            _update_service=SimpleNamespace(
                check_for_updates=lambda: (True, {"version": "2.0"})
            ),
            _collaboration_shutdown_pending=False,
            _collaboration_shutdown_complete=False,
            _application_shutdown_finalized=False,
            _shutdown_deferred_callbacks={},
            update_dialog_requested=SimpleNamespace(emit=emitted.append),
        )
        window._application_shutdown_terminal = lambda: (
            MainWindow._application_shutdown_terminal(window)
        )
        window._defer_during_application_shutdown = lambda key, callback: (
            MainWindow._defer_during_application_shutdown(window, key, callback)
        )
        window._check_for_updates = lambda: MainWindow._check_for_updates(window)
        thread = SimpleNamespace(start=lambda: None)
        with patch(
            "ost_visualizer.presentation.main_window.threading.Thread",
            return_value=thread,
        ) as thread_factory:
            MainWindow._check_for_updates(window)
        check_updates = thread_factory.call_args.kwargs["target"]
        window._collaboration_shutdown_complete = True
        check_updates()
        self.assertEqual(emitted, [])

    def test_queued_update_dialog_is_ignored_after_shutdown_starts(self):
        window = MainWindow.__new__(MainWindow)
        window._collaboration_shutdown_pending = True
        window._collaboration_shutdown_complete = False
        window._application_shutdown_finalized = False
        window._shutdown_deferred_callbacks = {}
        window._visualization_service = SimpleNamespace(
            set_update_dialog_active=lambda _active: self.fail(
                "A queued update dialog must not alter shutdown state"
            )
        )
        with patch(
            "ost_visualizer.presentation.main_window.UpdateDialog",
            side_effect=AssertionError("A queued update dialog must not open"),
        ):
            MainWindow._show_update_dialog(window, object())
        self.assertEqual(
            list(window._shutdown_deferred_callbacks), ["show_update_dialog"]
        )

    def test_queued_update_dialog_replays_when_shutdown_is_aborted(self):
        active_states = []
        calls = []
        shown = []
        window = MainWindow.__new__(MainWindow)
        window._collaboration_shutdown_pending = True
        window._collaboration_shutdown_complete = False
        window._collaboration_shutdown_failed = False
        window._application_shutdown_finalized = False
        window._shutdown_deferred_callbacks = {}
        window._deferred_persistence_manager = SimpleNamespace(
            abort_shutdown=lambda: None
        )
        window._visualization_service = SimpleNamespace(
            set_update_dialog_active=active_states.append
        )
        window.icon_provider = object()
        window.show = lambda: shown.append(True)
        dialog = SimpleNamespace(
            show_dialog=lambda: calls.append("show"),
            deleteLater=lambda: calls.append("delete"),
        )
        scheduled = []
        with patch(
            "ost_visualizer.presentation.main_window.UpdateDialog",
            return_value=dialog,
        ), patch.object(
            QtCore.QTimer,
            "singleShot",
            side_effect=lambda _delay, callback: scheduled.append(callback),
        ), patch(
            "ost_visualizer.presentation.main_window.show_critical"
        ) as critical:
            MainWindow._show_update_dialog(window, {"version": "2.0"})
            self.assertEqual(calls, [])
            MainWindow._on_shutdown_mutation_drain_complete(
                window, False, "shutdown aborted"
            )
            for callback in list(scheduled):
                callback()
        critical.assert_called_once_with(
            window, "Shutdown Incomplete", "shutdown aborted"
        )
        self.assertFalse(window._collaboration_shutdown_pending)
        self.assertEqual(shown, [True])
        self.assertEqual(calls, ["show", "delete"])
        self.assertEqual(active_states, [True, False])

    def test_update_dialog_completes_normally_before_shutdown(self):
        active_states = []
        calls = []
        window = MainWindow.__new__(MainWindow)
        window._collaboration_shutdown_pending = False
        window._collaboration_shutdown_complete = False
        window._application_shutdown_finalized = False
        window._visualization_service = SimpleNamespace(
            set_update_dialog_active=active_states.append
        )
        window.icon_provider = object()
        dialog = SimpleNamespace(
            show_dialog=lambda: calls.append("show"),
            deleteLater=lambda: calls.append("delete"),
        )
        with patch(
            "ost_visualizer.presentation.main_window.UpdateDialog",
            return_value=dialog,
        ):
            MainWindow._show_update_dialog(window, {"version": "2.0"})
        self.assertEqual(calls, ["show", "delete"])
        self.assertEqual(active_states, [True, False])

    def test_update_dialog_failure_always_clears_monitor_state(self):
        active_states = []
        deleted = []
        window = MainWindow.__new__(MainWindow)
        window._collaboration_shutdown_pending = False
        window._collaboration_shutdown_complete = False
        window._application_shutdown_finalized = False
        window._visualization_service = SimpleNamespace(
            set_update_dialog_active=lambda active: active_states.append(active)
        )
        window.icon_provider = object()

        def fail_to_show():
            raise RuntimeError("dialog failed")

        dialog = SimpleNamespace(
            show_dialog=fail_to_show,
            deleteLater=lambda: deleted.append(True),
        )
        with patch(
            "ost_visualizer.presentation.main_window.UpdateDialog",
            return_value=dialog,
        ), self.assertRaisesRegex(RuntimeError, "dialog failed"):
            MainWindow._show_update_dialog(window, object())
        self.assertEqual(active_states, [True, False])
        self.assertEqual(deleted, [True])

    def test_update_dialog_constructor_failure_always_clears_monitor_state(self):
        active_states = []
        window = MainWindow.__new__(MainWindow)
        window._collaboration_shutdown_pending = False
        window._collaboration_shutdown_complete = False
        window._application_shutdown_finalized = False
        window._visualization_service = SimpleNamespace(
            set_update_dialog_active=lambda active: active_states.append(active)
        )
        window.icon_provider = object()
        with patch(
            "ost_visualizer.presentation.main_window.UpdateDialog",
            side_effect=RuntimeError("constructor failed"),
        ), self.assertRaisesRegex(RuntimeError, "constructor failed"):
            MainWindow._show_update_dialog(window, object())
        self.assertEqual(active_states, [True, False])

    def test_update_dialog_return_after_terminal_shutdown_does_not_touch_service(self):
        active_states = []
        window = MainWindow.__new__(MainWindow)
        window._collaboration_shutdown_pending = False
        window._collaboration_shutdown_complete = False
        window._application_shutdown_finalized = False

        def set_update_dialog_active(active):
            if not active and window._collaboration_shutdown_complete:
                raise AssertionError("Cleaned visualization service was reused")
            active_states.append(active)

        window._visualization_service = SimpleNamespace(
            set_update_dialog_active=set_update_dialog_active
        )
        window.icon_provider = object()

        def close_during_dialog():
            window._collaboration_shutdown_complete = True

        dialog = SimpleNamespace(
            show_dialog=close_during_dialog,
            deleteLater=lambda: None,
        )
        with patch(
            "ost_visualizer.presentation.main_window.UpdateDialog",
            return_value=dialog,
        ):
            MainWindow._show_update_dialog(window, object())
        self.assertEqual(active_states, [True])

    def test_update_dialog_return_tolerates_parent_destroying_dialog(self):
        from shiboken6 import delete

        active_states = []
        window = MainWindow.__new__(MainWindow)
        window._collaboration_shutdown_pending = False
        window._collaboration_shutdown_complete = False
        window._application_shutdown_finalized = False
        window._visualization_service = SimpleNamespace(
            set_update_dialog_active=active_states.append
        )
        window.icon_provider = object()

        class DestroyedUpdateDialog(QtWidgets.QDialog):
            def __init__(self, *_args):
                super().__init__()

            def show_dialog(self):
                delete(self)

        with patch(
            "ost_visualizer.presentation.main_window.UpdateDialog",
            DestroyedUpdateDialog,
        ):
            MainWindow._show_update_dialog(window, object())
        self.assertEqual(active_states, [True, False])

    def test_app_close_captures_current_page_state_before_shutdown_cleanup(self):
        calls = []
        window = MainWindow.__new__(MainWindow)
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(
                capture_current_page_state_for_shutdown=lambda: calls.append(
                    "capture_state"
                )
            )
        )
        window._deferred_persistence_manager = SimpleNamespace(
            begin_shutdown=lambda: calls.append("begin_shutdown"),
            prepare_shutdown=lambda: calls.append("prepare_shutdown") or True,
        )
        self.assertTrue(MainWindow._flush_deferred_persistence_before_close(window))
        self.assertEqual(calls, ["capture_state", "begin_shutdown", "prepare_shutdown"])

    def test_app_close_reports_critical_deferred_cleanup_failure(self):
        calls = []
        window = MainWindow.__new__(MainWindow)
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(
                capture_current_page_state_for_shutdown=lambda: calls.append(
                    "capture_state"
                )
            )
        )
        window._deferred_persistence_manager = SimpleNamespace(
            begin_shutdown=lambda: calls.append("begin_shutdown"),
            prepare_shutdown=lambda: calls.append("prepare_shutdown") or False,
        )
        self.assertFalse(MainWindow._flush_deferred_persistence_before_close(window))
        self.assertEqual(calls, ["capture_state", "begin_shutdown", "prepare_shutdown"])

    def test_app_close_abandons_noncritical_page_view_without_blocking_shutdown(self):
        service = FakeProjectWriteService()
        service.fail_methods.add("save_page_view_state")
        manager = DeferredPersistenceManager(
            service,
            _workspace_service(service),
            logger_=logging.getLogger("tests.close_pending_page_view"),
        )
        shutdown_requests = []
        collaboration = SimpleNamespace(
            shutdown_state=CollaborationShutdownState.RUNNING,
            drain_all_mutations_async=lambda callback: callback(True, ""),
            request_shutdown=lambda callback: shutdown_requests.append(callback),
        )
        window = MainWindow.__new__(MainWindow)
        window._collaboration_shutdown_pending = True
        window._collaboration_shutdown_complete = False
        window._collaboration_shutdown_failed = False
        pending_after_capture = []

        def capture_page_state():
            manager.schedule_page_view_state("a.mdb", "b1", "p1", 2.0, 10.0, 20.0)
            pending_after_capture.append(manager.pending_count)

        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(
                capture_current_page_state_for_shutdown=capture_page_state
            )
        )
        window._deferred_persistence_manager = manager
        window.app_controller = SimpleNamespace(get_service=lambda _name: collaboration)
        window.show = lambda: self.fail("A noncritical view-state failure reopened UI")
        with self.assertNoLogs("tests.close_pending_page_view", level="WARNING"):
            MainWindow._begin_application_shutdown(window)
        self.assertEqual(pending_after_capture, [1])
        self.assertEqual(manager.pending_count, 0)
        self.assertEqual(service.calls, [])
        self.assertEqual(len(shutdown_requests), 1)

    def test_app_close_rejects_close_when_deferred_cleanup_fails(self):
        scheduled = []
        window = MainWindow.__new__(MainWindow)
        window._collaboration_shutdown_pending = False
        window._collaboration_shutdown_complete = False
        window._collaboration_shutdown_failed = False
        window._shutdown_deferred_callbacks = {}
        aborts = []
        shows = []
        window._deferred_persistence_manager = SimpleNamespace(
            abort_shutdown=lambda: aborts.append(True)
        )
        window.hide = lambda: None
        window.show = lambda: shows.append(True)
        window._flush_deferred_persistence_before_close = lambda: False
        event = FakeCloseEvent()
        with patch.object(
            QtCore.QTimer,
            "singleShot",
            side_effect=lambda _delay, callback: scheduled.append(callback),
        ):
            window.handlers = SimpleNamespace(
                file_ops=SimpleNamespace(
                    maintenance_pending=False, sql_creation_pending=False
                )
            )
            MainWindow.closeEvent(window, event)
            scheduled.pop()()
        self.assertTrue(event.ignored)
        self.assertFalse(window._collaboration_shutdown_pending)
        self.assertFalse(window._collaboration_shutdown_complete)
        self.assertEqual(aborts, [True])
        self.assertEqual(shows, [True])

    def test_failed_sql_drain_restores_deferred_persistence_after_close_abort(self):
        service = FakeProjectWriteService()
        manager = DeferredPersistenceManager(
            service,
            _workspace_service(service),
            logger_=logging.getLogger("tests.close_abort_deferred_persistence"),
        )
        drain_callbacks = []
        collaboration = SimpleNamespace(
            shutdown_state=CollaborationShutdownState.RUNNING,
            drain_all_mutations_async=drain_callbacks.append,
            request_shutdown=lambda _callback: None,
        )
        window = MainWindow.__new__(MainWindow)
        window._collaboration_shutdown_pending = True
        window._collaboration_shutdown_complete = False
        window._collaboration_shutdown_failed = False
        window._application_shutdown_finalized = False
        window._shutdown_deferred_callbacks = {}
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(
                capture_current_page_state_for_shutdown=lambda: None
            )
        )
        window._deferred_persistence_manager = manager
        window.app_controller = SimpleNamespace(get_service=lambda _name: collaboration)
        window.show = lambda: None
        with patch("ost_visualizer.presentation.main_window.show_critical") as critical:
            MainWindow._begin_application_shutdown(window)
            self.assertFalse(
                manager.schedule(
                    "setting",
                    ("setting", "during-shutdown.mdb"),
                    "setting",
                    lambda: True,
                )
            )
            drain_callbacks.pop()(False, "drain failed")
        critical.assert_called_once_with(window, "Shutdown Incomplete", "drain failed")
        self.assertFalse(window._collaboration_shutdown_pending)
        self.assertTrue(
            manager.schedule(
                "setting",
                ("setting", "target.mdb"),
                "setting",
                lambda: True,
            )
        )

    def test_first_close_hides_immediately_and_defers_all_shutdown_work(self):
        scheduled = []
        calls = []
        collaboration = SimpleNamespace(
            shutdown_state=CollaborationShutdownState.RUNNING,
            drain_all_mutations_async=lambda callback: callback(True, ""),
            request_shutdown=lambda callback: calls.append(("shutdown", callback)),
        )
        window = MainWindow.__new__(MainWindow)
        window._collaboration_shutdown_pending = False
        window._collaboration_shutdown_complete = False
        window._collaboration_shutdown_failed = False
        window.app_controller = SimpleNamespace(get_service=lambda _name: collaboration)
        window.hide = lambda: calls.append("hide")
        window.show = lambda: calls.append("show")
        window.setEnabled = lambda _enabled: self.fail(
            "normal shutdown must not darken the window"
        )
        window._flush_deferred_persistence_before_close = (
            lambda: calls.append("flush") or True
        )
        event = FakeCloseEvent()
        with patch.object(
            QtCore.QTimer,
            "singleShot",
            side_effect=lambda _delay, callback: scheduled.append(callback),
        ):
            window.handlers = SimpleNamespace(
                file_ops=SimpleNamespace(
                    maintenance_pending=False, sql_creation_pending=False
                )
            )
            MainWindow.closeEvent(window, event)
            self.assertEqual(calls, ["hide"])
            self.assertEqual(len(scheduled), 1)
            scheduled.pop()()
        self.assertTrue(event.ignored)
        self.assertEqual(calls[:2], ["hide", "flush"])
        self.assertEqual(calls[2][0], "shutdown")

    def test_app_close_waits_asynchronously_for_critical_sql_mutations(self):
        drain_callbacks = []
        shutdown_requests = []
        collaboration = SimpleNamespace(
            shutdown_state=CollaborationShutdownState.RUNNING,
            drain_all_mutations_async=drain_callbacks.append,
            request_shutdown=shutdown_requests.append,
        )
        window = MainWindow.__new__(MainWindow)
        window._collaboration_shutdown_pending = True
        window._collaboration_shutdown_complete = False
        window._collaboration_shutdown_failed = False
        window._flush_deferred_persistence_before_close = lambda: True
        window.app_controller = SimpleNamespace(get_service=lambda _name: collaboration)
        window.show = lambda: self.fail("A healthy asynchronous drain must stay hidden")
        MainWindow._begin_application_shutdown(window)
        self.assertEqual(len(drain_callbacks), 1)
        self.assertEqual(shutdown_requests, [])
        drain_callbacks[0](True, "")
        self.assertEqual(len(shutdown_requests), 1)

    def test_repeated_close_does_not_schedule_duplicate_shutdown(self):
        scheduled = []
        hidden = []
        window = MainWindow.__new__(MainWindow)
        window._collaboration_shutdown_pending = False
        window._collaboration_shutdown_complete = False
        window._collaboration_shutdown_failed = False
        window.hide = lambda: hidden.append(True)
        first = FakeCloseEvent()
        second = FakeCloseEvent()
        with patch.object(
            QtCore.QTimer,
            "singleShot",
            side_effect=lambda _delay, callback: scheduled.append(callback),
        ):
            window.handlers = SimpleNamespace(
                file_ops=SimpleNamespace(
                    maintenance_pending=False, sql_creation_pending=False
                )
            )
            MainWindow.closeEvent(window, first)
            window.handlers = SimpleNamespace(
                file_ops=SimpleNamespace(
                    maintenance_pending=False, sql_creation_pending=False
                )
            )
            MainWindow.closeEvent(window, second)
        self.assertTrue(first.ignored)
        self.assertTrue(second.ignored)
        self.assertEqual(hidden, [True])
        self.assertEqual(len(scheduled), 1)

    def test_completed_shutdown_exits_the_qt_event_loop_after_resource_cleanup(self):
        calls = []
        lifecycle = SimpleNamespace(shutdown=lambda: calls.append("lifecycle"))
        window = MainWindow.__new__(MainWindow)
        window._collaboration_shutdown_pending = False
        window._collaboration_shutdown_complete = True
        window._collaboration_shutdown_failed = False
        window._shutdown_deferred_callbacks = {}
        window._deferred_persistence_manager = SimpleNamespace(
            cleanup=lambda: calls.append("deferred_cleanup") or True
        )
        window._workspace_state_coordinator = SimpleNamespace(
            flush=lambda: calls.append("workspace_flush"),
            cleanup=lambda: calls.append("workspace_cleanup"),
        )
        window.event_coordinator = SimpleNamespace(
            cleanup=lambda: calls.append("event_cleanup")
        )
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(cleanup=lambda: calls.append("ui_cleanup"))
        )
        window.license_coordinator = SimpleNamespace(
            cleanup=lambda: calls.append("license_cleanup")
        )
        window.ui_access_manager = SimpleNamespace(
            cleanup=lambda: calls.append("access_cleanup")
        )
        window._mcp_context_bridge = SimpleNamespace(
            cleanup=lambda: calls.append("mcp_cleanup")
        )
        window._ai_takeoff_bridge = SimpleNamespace(
            cleanup=lambda: calls.append("takeoff_cleanup")
        )
        window._ai_approval = SimpleNamespace(
            cleanup=lambda: calls.append("ai_review_cleanup")
        )
        window._ai_rebind_prompt = SimpleNamespace(
            cleanup=lambda: calls.append("ai_rebind_cleanup")
        )
        window._ai_pdf_source = SimpleNamespace(
            release=lambda: calls.append("ai_pdf_release")
        )
        window.app_controller = SimpleNamespace(
            get_service=lambda service: (
                lifecycle
                if service == "lifecycle_orchestrator"
                else self.fail(f"unexpected service: {service}")
            )
        )
        event = FakeCloseEvent()
        with patch.object(
            MainWindow.__mro__[1],
            "closeEvent",
            side_effect=lambda _event: calls.append("window_close"),
        ), patch.object(
            QtCore.QCoreApplication,
            "quit",
            side_effect=lambda: calls.append("qt_quit"),
        ):
            window.handlers.file_ops = SimpleNamespace(
                maintenance_pending=False, sql_creation_pending=False
            )
            MainWindow.closeEvent(window, event)
        self.assertEqual(
            calls,
            [
                "deferred_cleanup",
                "workspace_flush",
                "workspace_cleanup",
                "event_cleanup",
                "ui_cleanup",
                "license_cleanup",
                "access_cleanup",
                "mcp_cleanup",
                "takeoff_cleanup",
                "ai_review_cleanup",
                "ai_rebind_cleanup",
                "ai_pdf_release",
                "lifecycle",
                "window_close",
                "qt_quit",
            ],
        )

    def test_completed_shutdown_finalization_is_idempotent(self):
        calls = []
        lifecycle = SimpleNamespace(shutdown=lambda: calls.append("lifecycle"))
        window = MainWindow.__new__(MainWindow)
        window._application_shutdown_finalized = False
        window._collaboration_shutdown_pending = False
        window._collaboration_shutdown_complete = True
        window._collaboration_shutdown_failed = False
        window._shutdown_deferred_callbacks = {}
        window._deferred_persistence_manager = SimpleNamespace(
            cleanup=lambda: calls.append("deferred_cleanup") or True
        )
        window._workspace_state_coordinator = SimpleNamespace(
            flush=lambda: calls.append("workspace_flush"),
            cleanup=lambda: calls.append("workspace_cleanup"),
        )
        window.event_coordinator = SimpleNamespace(
            cleanup=lambda: calls.append("event_cleanup")
        )
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(cleanup=lambda: calls.append("ui_cleanup"))
        )
        window.license_coordinator = SimpleNamespace(
            cleanup=lambda: calls.append("license_cleanup")
        )
        window.ui_access_manager = SimpleNamespace(
            cleanup=lambda: calls.append("access_cleanup")
        )
        window._mcp_context_bridge = SimpleNamespace(
            cleanup=lambda: calls.append("mcp_cleanup")
        )
        window._ai_takeoff_bridge = SimpleNamespace(
            cleanup=lambda: calls.append("takeoff_cleanup")
        )
        window._ai_approval = SimpleNamespace(
            cleanup=lambda: calls.append("ai_review_cleanup")
        )
        window._ai_rebind_prompt = SimpleNamespace(
            cleanup=lambda: calls.append("ai_rebind_cleanup")
        )
        window._ai_pdf_source = SimpleNamespace(
            release=lambda: calls.append("ai_pdf_release")
        )
        window.app_controller = SimpleNamespace(get_service=lambda _service: lifecycle)
        first = FakeCloseEvent()
        second = FakeCloseEvent()
        with patch.object(
            MainWindow.__mro__[1],
            "closeEvent",
            side_effect=lambda _event: calls.append("window_close"),
        ), patch.object(
            QtCore.QCoreApplication,
            "quit",
            side_effect=lambda: calls.append("qt_quit"),
        ):
            window.handlers.file_ops = SimpleNamespace(
                maintenance_pending=False, sql_creation_pending=False
            )
            MainWindow.closeEvent(window, first)
            window.handlers.file_ops = SimpleNamespace(
                maintenance_pending=False, sql_creation_pending=False
            )
            MainWindow.closeEvent(window, second)
        self.assertTrue(second.accepted)
        self.assertEqual(
            calls,
            [
                "deferred_cleanup",
                "workspace_flush",
                "workspace_cleanup",
                "event_cleanup",
                "ui_cleanup",
                "license_cleanup",
                "access_cleanup",
                "mcp_cleanup",
                "takeoff_cleanup",
                "ai_review_cleanup",
                "ai_rebind_cleanup",
                "ai_pdf_release",
                "lifecycle",
                "window_close",
                "qt_quit",
            ],
        )

    def test_completed_shutdown_continues_after_independent_cleanup_failures(self):
        calls = []

        def cleanup(name, *, fail=False):
            def run():
                calls.append(name)
                if fail:
                    raise RuntimeError(f"{name} failed")

            return run

        lifecycle = SimpleNamespace(shutdown=cleanup("lifecycle", fail=True))
        window = MainWindow.__new__(MainWindow)
        window._application_shutdown_finalized = False
        window._collaboration_shutdown_pending = False
        window._collaboration_shutdown_complete = True
        window._collaboration_shutdown_failed = False
        window._shutdown_deferred_callbacks = {}
        window._deferred_persistence_manager = SimpleNamespace(
            cleanup=cleanup("deferred_cleanup")
        )
        window._workspace_state_coordinator = SimpleNamespace(
            flush=cleanup("workspace_flush", fail=True),
            cleanup=cleanup("workspace_cleanup"),
        )
        window.event_coordinator = SimpleNamespace(cleanup=cleanup("event_cleanup"))
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(cleanup=cleanup("ui_cleanup", fail=True))
        )
        window.license_coordinator = SimpleNamespace(cleanup=cleanup("license_cleanup"))
        window.ui_access_manager = SimpleNamespace(cleanup=cleanup("access_cleanup"))
        window._mcp_context_bridge = SimpleNamespace(cleanup=cleanup("mcp_cleanup"))
        window._ai_takeoff_bridge = SimpleNamespace(cleanup=cleanup("takeoff_cleanup"))
        window._ai_approval = SimpleNamespace(cleanup=cleanup("ai_review_cleanup"))
        window._ai_rebind_prompt = SimpleNamespace(cleanup=cleanup("ai_rebind_cleanup"))
        window._ai_pdf_source = SimpleNamespace(release=cleanup("ai_pdf_release"))
        window.app_controller = SimpleNamespace(get_service=lambda _service: lifecycle)
        event = FakeCloseEvent()
        with self.assertLogs(
            "ost_visualizer.presentation.main_window", level="ERROR"
        ) as captured, patch.object(
            MainWindow.__mro__[1],
            "closeEvent",
            side_effect=lambda _event: calls.append("window_close"),
        ), patch.object(
            QtCore.QCoreApplication,
            "quit",
            side_effect=lambda: calls.append("qt_quit"),
        ):
            window.handlers.file_ops = SimpleNamespace(
                maintenance_pending=False, sql_creation_pending=False
            )
            MainWindow.closeEvent(window, event)
        self.assertEqual(len(captured.output), 3)
        for description in (
            "flush workspace state",
            "clean up UI event coordinator",
            "shut down application lifecycle services",
        ):
            self.assertTrue(
                any(description in line for line in captured.output), description
            )
        self.assertEqual(
            calls,
            [
                "deferred_cleanup",
                "workspace_flush",
                "workspace_cleanup",
                "event_cleanup",
                "ui_cleanup",
                "license_cleanup",
                "access_cleanup",
                "mcp_cleanup",
                "takeoff_cleanup",
                "ai_review_cleanup",
                "ai_rebind_cleanup",
                "ai_pdf_release",
                "lifecycle",
                "window_close",
                "qt_quit",
            ],
        )
        self.assertTrue(window._application_shutdown_finalized)

    def test_access_only_close_flushes_page_state_before_collaboration_shutdown(self):
        requests = []
        calls = []
        scheduled = []
        collaboration = SimpleNamespace(
            shutdown_state=CollaborationShutdownState.RUNNING,
            drain_all_mutations_async=lambda callback: callback(True, ""),
            request_shutdown=lambda callback: (
                calls.append("shutdown"),
                requests.append(callback),
            ),
        )
        window = MainWindow.__new__(MainWindow)
        window._collaboration_shutdown_pending = False
        window._collaboration_shutdown_complete = False
        window._collaboration_shutdown_failed = False
        window.app_controller = SimpleNamespace(get_service=lambda _name: collaboration)
        window._deferred_persistence_manager = SimpleNamespace(
            begin_shutdown=lambda: calls.append("begin_shutdown"),
            cancel_for_file=lambda _database_id: calls.append("cancel"),
        )
        window._flush_deferred_persistence_before_close = (
            lambda: calls.append("flush") or True
        )
        window.hide = lambda: calls.append("hide")
        window.show = lambda: calls.append("show")
        event = FakeCloseEvent()
        with patch.object(
            QtCore.QTimer,
            "singleShot",
            side_effect=lambda _delay, callback: scheduled.append(callback),
        ):
            window.handlers = SimpleNamespace(
                file_ops=SimpleNamespace(
                    maintenance_pending=False, sql_creation_pending=False
                )
            )
            MainWindow.closeEvent(window, event)
            scheduled.pop()()
        self.assertTrue(event.ignored)
        self.assertEqual(len(requests), 1)
        self.assertEqual(calls, ["hide", "flush", "shutdown"])

    def test_collaboration_cleanup_failure_cannot_be_bypassed_by_a_second_close(self):
        enabled_states = []
        close_calls = []
        warnings = []
        window = MainWindow.__new__(MainWindow)
        window._collaboration_shutdown_pending = True
        window._collaboration_shutdown_complete = False
        window._collaboration_shutdown_failed = False
        window._shutdown_deferred_callbacks = {}
        window._deferred_persistence_manager = SimpleNamespace(
            abort_shutdown=lambda: None
        )
        window.show = lambda: enabled_states.append(True)
        window.close = lambda: close_calls.append(True)
        from ost_visualizer.presentation import main_window

        old_critical = main_window.show_critical
        main_window.show_critical = lambda _parent, _title, _message: warnings.append(
            True
        )
        try:
            MainWindow._on_collaboration_shutdown_complete(
                window, False, "cleanup failed"
            )
            event = FakeCloseEvent()
            window.handlers = SimpleNamespace(
                file_ops=SimpleNamespace(
                    maintenance_pending=False, sql_creation_pending=False
                )
            )
            MainWindow.closeEvent(window, event)
        finally:
            main_window.show_critical = old_critical
        self.assertTrue(window._collaboration_shutdown_failed)
        self.assertTrue(event.ignored)
        self.assertEqual(enabled_states, [True])
        self.assertEqual(close_calls, [])
        self.assertEqual(warnings, [True])


class MainWindowTitleRefreshTests(unittest.TestCase):
    def _window(self, selected_file_path=None, bid_ref=None, bid=None):
        titles = []

        class UiState:
            @property
            def selected_file_path(self):
                return selected_file_path

            def get_selected_bid_ref(self):
                return bid_ref

        class ProjectData:
            def __init__(self):
                self.get_bid_calls = []

            def get_bid(self, ref):
                self.get_bid_calls.append(ref)
                return bid

        project_data = ProjectData()
        window = SimpleNamespace(
            ui_state_manager=UiState(),
            _project_data_service=project_data,
            setWindowTitle=titles.append,
        )
        return window, titles, project_data

    def test_refresh_uses_default_when_nothing_selected(self):
        window, titles, _project_data = self._window()
        MainWindow.refresh_window_title(window)
        self.assertEqual(titles, [MAIN_WINDOW_TITLE])

    def test_refresh_uses_selected_database_for_database_or_folder(self):
        window, titles, _project_data = self._window(
            selected_file_path=TEST_DB_PATH,
        )
        MainWindow.refresh_window_title(window)
        self.assertEqual(titles, [_database_title()])

    def test_refresh_uses_selected_bid_ref_and_loaded_bid_metadata(self):
        bid_ref = BidRef(TEST_DB_PATH, TEST_BID_UID)
        bid = Bid(uid=TEST_BID_UID, name=TEST_BID_NAME, bid_no=TEST_BID_NO)
        window, titles, project_data = self._window(bid_ref=bid_ref, bid=bid)
        MainWindow.refresh_window_title(window)
        self.assertEqual(project_data.get_bid_calls, [bid_ref])
        self.assertEqual(
            titles,
            [_bid_title(f"[{TEST_BID_NO}] {TEST_BID_NAME}")],
        )

    def test_orphaned_bid_uses_same_bid_title_format(self):
        bid_ref = BidRef(TEST_DB_PATH, "orphan-bid")
        bid = Bid(uid="orphan-bid", name="Orphaned Project", bid_no=7)
        window, titles, _project_data = self._window(bid_ref=bid_ref, bid=bid)
        MainWindow.refresh_window_title(window)
        self.assertEqual(titles, [_bid_title("[7] Orphaned Project")])

    def test_refresh_falls_back_to_database_title_when_bid_metadata_missing(self):
        bid_ref = BidRef(TEST_DB_PATH, "missing-bid")
        window, titles, _project_data = self._window(bid_ref=bid_ref, bid=None)
        MainWindow.refresh_window_title(window)
        self.assertEqual(titles, [_database_title()])

    def test_switching_from_bid_to_folder_removes_bid_prefix(self):
        titles = []
        bid_ref = BidRef(TEST_DB_PATH, TEST_BID_UID)
        bid = Bid(uid=TEST_BID_UID, name=TEST_BID_NAME, bid_no=TEST_BID_NO)

        class UiState:
            selected_file_path = TEST_DB_PATH

            def __init__(self):
                self.bid_ref = bid_ref

            def get_selected_bid_ref(self):
                return self.bid_ref

        class ProjectData:
            def get_bid(self, _ref):
                return bid

        window = SimpleNamespace(
            ui_state_manager=UiState(),
            _project_data_service=ProjectData(),
            setWindowTitle=titles.append,
        )
        MainWindow.refresh_window_title(window)
        window.ui_state_manager.bid_ref = None
        MainWindow.refresh_window_title(window)
        self.assertEqual(
            titles,
            [
                _bid_title(f"[{TEST_BID_NO}] {TEST_BID_NAME}"),
                _database_title(),
            ],
        )

    def test_bid_title_omits_zero_bid_number_and_blank_name(self):
        bid_ref = BidRef(TEST_DB_PATH, TEST_BID_UID)
        for bid, label in (
            (Bid(uid=TEST_BID_UID, name="Only Name", bid_no=0), "Only Name"),
            (Bid(uid=TEST_BID_UID, name="  ", bid_no=24), "[24]"),
            (Bid(uid=TEST_BID_UID, name="", bid_no=0), None),
        ):
            with self.subTest(bid_no=bid.bid_no, name=bid.name):
                window, titles, _project_data = self._window(bid_ref=bid_ref, bid=bid)
                MainWindow.refresh_window_title(window)
                self.assertEqual(
                    titles,
                    [_database_title() if label is None else _bid_title(label)],
                )

    def test_bid_title_uses_bid_database_not_selected_file_path(self):
        bid_ref = BidRef(r"C:\jobs\Other.mdb", TEST_BID_UID)
        bid = Bid(uid=TEST_BID_UID, name=TEST_BID_NAME, bid_no=TEST_BID_NO)
        window, titles, _project_data = self._window(
            selected_file_path=TEST_DB_PATH, bid_ref=bid_ref, bid=bid
        )
        MainWindow.refresh_window_title(window)
        self.assertEqual(
            titles,
            [_bid_title(f"[{TEST_BID_NO}] {TEST_BID_NAME}", "Other.mdb")],
        )

    def test_opened_database_title_uses_event_file_path(self):
        titles = []
        window = SimpleNamespace(setWindowTitle=titles.append)
        MainWindow.set_database_window_title(window, TEST_DB_PATH)
        MainWindow.set_database_window_title(window, None)
        self.assertEqual(titles, [_database_title(), MAIN_WINDOW_TITLE])


class MainWindowPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_decode_workspace_geometry_rejects_corrupted_non_string_state(self):
        decoded = MainWindow._decode_workspace_geometry(123)
        self.assertTrue(decoded.isEmpty())
        self.assertTrue(MainWindow._decode_workspace_geometry("g\u00e9om").isEmpty())

    def test_decode_workspace_geometry_keeps_missing_state_and_decodes_base64(self):
        self.assertIsNone(MainWindow._decode_workspace_geometry(None))
        self.assertEqual(
            bytes(MainWindow._decode_workspace_geometry("c2F2ZWQ=")), b"saved"
        )

    def _page_navigation_window(self, *, allow_add, locked=False, bid=True, tab=1):
        window = MainWindow.__new__(MainWindow)
        window._config_model = SimpleNamespace(
            allow_add_page_from_takeoff_tab=allow_add
        )
        window.tab_widget = SimpleNamespace(currentIndex=lambda: tab)
        window.ui_access_manager = SimpleNamespace(is_allowed=lambda _feature: True)
        window._project_data_service = SimpleNamespace(
            is_current_bid_locked=lambda: locked
        )
        window.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: object() if bid else None
        )
        window.takeoff_sidebar = SimpleNamespace(
            get_page_order=lambda: ["p1", "p2"],
            get_active_page_uid=lambda: "p2",
        )
        return window

    def test_takeoff_next_page_add_requires_unlocked_selected_bid_on_takeoff_tab(self):
        self.assertTrue(
            MainWindow.can_go_next_takeoff_page(
                self._page_navigation_window(allow_add=True)
            )
        )
        for label, window in (
            ("locked bid", self._page_navigation_window(allow_add=True, locked=True)),
            ("no bid", self._page_navigation_window(allow_add=True, bid=False)),
            ("other tab", self._page_navigation_window(allow_add=True, tab=0)),
        ):
            with self.subTest(label):
                self.assertFalse(MainWindow.can_go_next_takeoff_page(window))

    def test_takeoff_next_page_does_not_navigate_when_add_page_fails(self):
        window = self._page_navigation_window(allow_add=True)
        window.handlers = SimpleNamespace(
            cover_sheet=SimpleNamespace(add_blank_page_from_takeoff_tab=lambda: False),
            ui_event=SimpleNamespace(
                navigate_to_takeoff_page=lambda _page_uid: self.fail(
                    "A failed add must not navigate"
                )
            ),
        )
        MainWindow.go_next_takeoff_page(window)

    def test_takeoff_next_page_allows_add_only_on_last_page_when_enabled(self):
        class FakePageCombo:
            def __init__(self, active_uid):
                self.active_uid = active_uid
                self.next_calls = 0

            def get_page_order(self):
                return ["p1", "p2"]

            def get_active_page_uid(self):
                return self.active_uid

            def go_next(self):
                self.next_calls += 1

        add_calls = []
        window = MainWindow.__new__(MainWindow)
        window._config_model = SimpleNamespace(allow_add_page_from_takeoff_tab=True)
        window.tab_widget = SimpleNamespace(currentIndex=lambda: 1)
        window.ui_access_manager = SimpleNamespace(is_allowed=lambda _feature: True)
        window._project_data_service = SimpleNamespace(
            is_current_bid_locked=lambda: False
        )
        window.ui_state_manager = SimpleNamespace(get_selected_bid_ref=lambda: object())
        window.handlers = SimpleNamespace(
            cover_sheet=SimpleNamespace(
                add_blank_page_from_takeoff_tab=lambda: add_calls.append("add")
            )
        )
        window.takeoff_sidebar = FakePageCombo("p2")
        self.assertTrue(MainWindow.can_go_next_takeoff_page(window))
        MainWindow.go_next_takeoff_page(window)
        self.assertEqual(add_calls, ["add"])
        self.assertEqual(window.takeoff_sidebar.next_calls, 0)
        add_calls.clear()
        window.takeoff_sidebar = FakePageCombo("p1")
        MainWindow.go_next_takeoff_page(window)
        self.assertEqual(add_calls, [])
        self.assertEqual(window.takeoff_sidebar.next_calls, 1)

    def test_takeoff_next_page_does_not_offer_add_when_preference_disabled(self):
        window = MainWindow.__new__(MainWindow)
        window._config_model = SimpleNamespace(allow_add_page_from_takeoff_tab=False)
        window.tab_widget = SimpleNamespace(currentIndex=lambda: 1)
        window.ui_access_manager = SimpleNamespace(is_allowed=lambda _feature: True)
        window._project_data_service = SimpleNamespace(
            is_current_bid_locked=lambda: False
        )
        window.ui_state_manager = SimpleNamespace(get_selected_bid_ref=lambda: object())
        window.takeoff_sidebar = SimpleNamespace(
            get_page_order=lambda: ["p1"],
            get_active_page_uid=lambda: "p1",
        )
        self.assertFalse(MainWindow.can_go_next_takeoff_page(window))

    def test_takeoff_next_page_adds_and_navigates_to_new_last_page(self):
        class FakePageCombo:
            def __init__(self):
                self.order = ["p1", "p2"]

            def get_page_order(self):
                return list(self.order)

            def get_active_page_uid(self):
                return "p2"

            def go_next(self):
                raise AssertionError("Last-page add path should not call go_next")

        navigations = []
        window = MainWindow.__new__(MainWindow)
        window._config_model = SimpleNamespace(allow_add_page_from_takeoff_tab=True)
        window.tab_widget = SimpleNamespace(currentIndex=lambda: 1)
        window.ui_access_manager = SimpleNamespace(is_allowed=lambda _feature: True)
        window._project_data_service = SimpleNamespace(
            is_current_bid_locked=lambda: False
        )
        window.ui_state_manager = SimpleNamespace(get_selected_bid_ref=lambda: object())
        window.takeoff_sidebar = FakePageCombo()

        def add_page():
            window.takeoff_sidebar.order.append("p3")
            return True

        window.handlers = SimpleNamespace(
            cover_sheet=SimpleNamespace(add_blank_page_from_takeoff_tab=add_page),
            ui_event=SimpleNamespace(
                navigate_to_takeoff_page=lambda page_uid: navigations.append(page_uid)
            ),
        )
        MainWindow.go_next_takeoff_page(window)
        self.assertEqual(navigations, ["p3"])

    def test_main_window_applies_new_plan_view_preferences(self):
        class FakePlanView:
            def __init__(self):
                self.calls = []

            def set_roping_selection_method(self, value):
                self.calls.append(("roping", value))

            def set_inactive_object_color(self, value):
                self.calls.append(("inactive", value))

            def set_disable_high_resolution_images(self, value):
                self.calls.append(("high_res", value))

            def set_intelligent_paste_enabled(self, value):
                self.calls.append(("paste", value))

            def set_advanced_mouse_controls_enabled(self, value):
                self.calls.append(("mouse", value))

            def set_default_auto_zoom_level(self, value):
                self.calls.append(("auto_zoom", value))

            def set_full_window_crosshairs(self, enabled, color, line_thickness):
                self.calls.append(("crosshair", enabled, color, line_thickness))

            def set_mouse_snap_angles(self, unpressed_angle, pressed_angle):
                self.calls.append(("snap_angles", unpressed_angle, pressed_angle))

            def set_snap_preferences(
                self,
                *,
                snap_to_grid_enabled,
                snap_to_grid_threshold_px,
                snap_to_pdf_lines_enabled,
                snap_to_pdf_lines_threshold_px,
                snap_to_takeoffs_enabled,
                snap_to_takeoffs_threshold_px,
                snap_to_right_angle_enabled,
                snap_to_right_angle_threshold_px,
            ):
                snap_options = {
                    "snap_to_grid_enabled": snap_to_grid_enabled,
                    "snap_to_grid_threshold_px": snap_to_grid_threshold_px,
                    "snap_to_pdf_lines_enabled": snap_to_pdf_lines_enabled,
                    "snap_to_pdf_lines_threshold_px": snap_to_pdf_lines_threshold_px,
                    "snap_to_takeoffs_enabled": snap_to_takeoffs_enabled,
                    "snap_to_takeoffs_threshold_px": snap_to_takeoffs_threshold_px,
                    "snap_to_right_angle_enabled": snap_to_right_angle_enabled,
                    "snap_to_right_angle_threshold_px": snap_to_right_angle_threshold_px,
                }
                self.calls.append(("snap_preferences", snap_options))

        class FakeDetachedWindow:
            def __init__(self):
                self.calls = []

            def apply_config_preferences(
                self,
                *,
                show_page_index,
                show_sheet_number,
                roping_selection_method,
                inactive_object_color,
                disable_high_resolution_images,
                intelligent_paste_enabled,
                advanced_mouse_controls_enabled,
                default_auto_zoom_level,
                use_full_window_crosshairs,
                crosshair_color,
                crosshair_line_thickness,
                mouse_unpressed_snap_angle,
                mouse_pressed_snap_angle,
                snap_to_grid_enabled,
                snap_to_grid_threshold_px,
                snap_to_pdf_lines_enabled,
                snap_to_pdf_lines_threshold_px,
                snap_to_takeoffs_enabled,
                snap_to_takeoffs_threshold_px,
                snap_to_right_angle_enabled,
                snap_to_right_angle_threshold_px,
            ):
                config_options = {
                    "show_page_index": show_page_index,
                    "show_sheet_number": show_sheet_number,
                    "roping_selection_method": roping_selection_method,
                    "inactive_object_color": inactive_object_color,
                    "disable_high_resolution_images": disable_high_resolution_images,
                    "intelligent_paste_enabled": intelligent_paste_enabled,
                    "advanced_mouse_controls_enabled": advanced_mouse_controls_enabled,
                    "default_auto_zoom_level": default_auto_zoom_level,
                    "use_full_window_crosshairs": use_full_window_crosshairs,
                    "crosshair_color": crosshair_color,
                    "crosshair_line_thickness": crosshair_line_thickness,
                    "mouse_unpressed_snap_angle": mouse_unpressed_snap_angle,
                    "mouse_pressed_snap_angle": mouse_pressed_snap_angle,
                    "snap_to_grid_enabled": snap_to_grid_enabled,
                    "snap_to_grid_threshold_px": snap_to_grid_threshold_px,
                    "snap_to_pdf_lines_enabled": snap_to_pdf_lines_enabled,
                    "snap_to_pdf_lines_threshold_px": snap_to_pdf_lines_threshold_px,
                    "snap_to_takeoffs_enabled": snap_to_takeoffs_enabled,
                    "snap_to_takeoffs_threshold_px": snap_to_takeoffs_threshold_px,
                    "snap_to_right_angle_enabled": snap_to_right_angle_enabled,
                    "snap_to_right_angle_threshold_px": snap_to_right_angle_threshold_px,
                }
                self.calls.append(config_options)

        annotation_window = FakeDetachedWindow()
        view_window = FakeDetachedWindow()
        config_model = ConfigAggregate(
            _preferences_support_FakeConfigRepository(
                Config(
                    show_toolbar_text=False,
                    display_page_index_with_sheet_name=True,
                    display_sheet_number_with_sheet_name=True,
                    roping_selection_method="inclusive",
                    inactive_object_color="#2468ac",
                    disable_high_resolution_images=True,
                    enable_intelligent_paste=False,
                    enable_advanced_mouse_controls=False,
                    use_full_window_crosshairs=True,
                    crosshair_color="#123456",
                    crosshair_line_thickness=4,
                    mouse_unpressed_snap_angle=30,
                    mouse_pressed_snap_angle=45,
                    **_preferences_support_SNAP_PREF_UPDATE,
                    default_auto_zoom_level=125,
                )
            )
        )

        class FakeWindow:
            def __init__(self):
                self._config_model = config_model
                self.takeoff_sidebar = None
                self.plan_view = FakePlanView()
                self.cover_sheet_button = QtWidgets.QToolButton()
                self.cover_sheet_button.setToolButtonStyle(
                    QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon
                )
                self.annotation_style_refreshes = 0

            def apply_takeoff_toolbar_visibility(self, hidden_items):
                self.hidden_toolbar_items = hidden_items

            def get_workspace_toolbars(self):
                return []

            def get_toolbar_text_buttons(self):
                return [self.cover_sheet_button]

            def get_annotation_window(self):
                return annotation_window

            def get_view_window(self):
                return view_window

            def _refresh_annotation_style_controls(self):
                self.annotation_style_refreshes += 1

        window = FakeWindow()
        MainWindow.apply_config_preferences(window)
        self.assertEqual(window.annotation_style_refreshes, 1)
        self.assertEqual(window.hidden_toolbar_items, ())
        self.assertEqual(
            window.cover_sheet_button.toolButtonStyle(),
            QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly,
        )
        self.assertEqual(
            window.plan_view.calls,
            [
                ("roping", "inclusive"),
                ("inactive", "#2468ac"),
                ("high_res", True),
                ("paste", False),
                ("mouse", False),
                ("auto_zoom", 125),
                ("crosshair", True, "#123456", 4),
                ("snap_angles", 30, 45),
                (
                    "snap_preferences",
                    _preferences_support_SNAP_PREF_UPDATE,
                ),
            ],
        )
        expected_detached = {
            "show_page_index": True,
            "show_sheet_number": True,
            "roping_selection_method": "inclusive",
            "inactive_object_color": "#2468ac",
            "disable_high_resolution_images": True,
            "intelligent_paste_enabled": False,
            "advanced_mouse_controls_enabled": False,
            "default_auto_zoom_level": 125,
            "use_full_window_crosshairs": True,
            "crosshair_color": "#123456",
            "crosshair_line_thickness": 4,
            "mouse_unpressed_snap_angle": 30,
            "mouse_pressed_snap_angle": 45,
            **_preferences_support_SNAP_PREF_UPDATE,
        }
        self.assertEqual(annotation_window.calls, [expected_detached])
        self.assertEqual(view_window.calls, [expected_detached])


class MainWindowCreationDialogIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_shutdown_cannot_destroy_creation_owner_while_setup_is_pending(self):
        from ost_visualizer.presentation.main_window import MainWindow
        from PySide6 import QtGui

        host = SimpleNamespace(
            handlers=SimpleNamespace(
                file_ops=SimpleNamespace(
                    maintenance_pending=False,
                    sql_creation_pending=True,
                )
            )
        )
        event = QtGui.QCloseEvent()
        MainWindow.closeEvent(host, event)
        self.assertFalse(event.isAccepted())


class MainWindowStartupImportTests(unittest.TestCase):
    def test_current_project_import_target_uses_selected_database_for_duplicate_uid(
        self,
    ):
        hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path="first.mdb",
                    bid_projects={"1": HierarchyProjectInfo(name="First")},
                ),
                HierarchyFileEntry(
                    file_path="second.mdb",
                    bid_projects={"1": HierarchyProjectInfo(name="Second")},
                ),
            ]
        )
        window = SimpleNamespace(
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: None,
                selected_project_uid="1",
                selected_file_path="second.mdb",
            ),
            _project_data_service=SimpleNamespace(
                get_hierarchy=lambda: hierarchy,
                get_current_file_path=lambda: "first.mdb",
            ),
        )
        target = MainWindow._current_project_import_target(window)
        self.assertEqual(target.file_path, "second.mdb")
        self.assertEqual(target.project_uid, "1")

    def test_current_project_import_target_prefers_bid_then_file_then_loaded_file(
        self,
    ):
        hierarchy = HierarchyData(loaded_files=[])
        bid_ref = BidRef("bid.mdb", "7")

        def window(selected_bid_ref, selected_project_uid, selected_file_path):
            return SimpleNamespace(
                ui_state_manager=SimpleNamespace(
                    get_selected_bid_ref=lambda: selected_bid_ref,
                    selected_project_uid=selected_project_uid,
                    selected_file_path=selected_file_path,
                ),
                _project_data_service=SimpleNamespace(
                    get_hierarchy=lambda: hierarchy,
                    get_current_file_path=lambda: "current.mdb",
                    find_project_uid_for_bid=lambda _ref: "bid-project",
                ),
            )

        bid_target = MainWindow._current_project_import_target(
            window(bid_ref, "ignored", "selected.mdb")
        )
        self.assertEqual(
            (bid_target.file_path, bid_target.project_uid), ("bid.mdb", "bid-project")
        )
        file_target = MainWindow._current_project_import_target(
            window(None, None, "selected.mdb")
        )
        self.assertEqual(
            (file_target.file_path, file_target.project_uid), ("selected.mdb", None)
        )
        unresolved_project_target = MainWindow._current_project_import_target(
            window(None, "missing-project", "selected.mdb")
        )
        self.assertEqual(
            (
                unresolved_project_target.file_path,
                unresolved_project_target.project_uid,
            ),
            ("selected.mdb", None),
        )
        current_target = MainWindow._current_project_import_target(
            window(None, None, None)
        )
        self.assertEqual(
            (current_target.file_path, current_target.project_uid),
            ("current.mdb", None),
        )

    def test_startup_import_waits_for_config_load_and_main_window_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.ost"
            source.write_text("ost")
            window = _startup_import__startup_import_window()
            window._pending_project_file_args.append(
                _startup_import__project_file_args(source)
            )
            timer = _startup_import_FakeTimerQueue()
            original_single_shot = main_window_module.QtCore.QTimer.singleShot
            try:
                main_window_module.QtCore.QTimer.singleShot = timer.singleShot
                MainWindow._schedule_pending_project_file_imports(window)
                self.assertEqual(timer.callbacks, [])
                window._startup_load_complete = True
                MainWindow._schedule_pending_project_file_imports(window)
                self.assertEqual(timer.callbacks, [])
                MainWindow._mark_main_window_ready(window)
            finally:
                main_window_module.QtCore.QTimer.singleShot = original_single_shot
            self.assertTrue(window._main_window_ready)
            self.assertEqual(
                timer.callbacks, [window._run_pending_project_file_imports]
            )
            self.assertTrue(window._project_file_import_scheduled)

    def test_startup_load_does_not_schedule_import_before_main_window_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.ost"
            source.write_text("ost")
            window = _startup_import__startup_import_window()
            window._pending_project_file_args.append(
                _startup_import__project_file_args(source)
            )
            window.app_controller = SimpleNamespace(
                load_files_from_config=lambda: ["target.mdb"],
                has_any_databases=lambda: True,
            )
            window.handlers = SimpleNamespace(
                ui_event=SimpleNamespace(sync_after_startup_load=lambda: None)
            )
            window._workspace_state_coordinator = SimpleNamespace(
                restore_deferred_state=lambda: None
            )
            timer = _startup_import_FakeTimerQueue()
            original_single_shot = main_window_module.QtCore.QTimer.singleShot
            try:
                main_window_module.QtCore.QTimer.singleShot = timer.singleShot
                MainWindow._load_files_from_config(window)
            finally:
                main_window_module.QtCore.QTimer.singleShot = original_single_shot
            self.assertTrue(window._startup_load_complete)
            self.assertEqual(
                timer.callbacks,
                [window._restore_deferred_workspace_state],
            )
            self.assertFalse(window._project_file_import_scheduled)

    def test_ready_startup_import_batches_pending_args_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.ost"
            second = root / "second.osp"
            first.write_text("ost")
            second.write_text("osp")
            window = _startup_import__startup_import_window()
            window._startup_load_complete = True
            window._main_window_ready = True
            execute_calls = []
            refresh_calls = []
            flush_calls = []
            selections = []
            summaries = []
            target = import_args_use_case.ProjectImportTarget("target.mdb")
            window._import_project_files_from_args = SimpleNamespace(
                resolve_target=lambda _current_target: target,
                uses_async_import=lambda _target: False,
                execute_imports=lambda args, target, refresh_after_import=True: (
                    execute_calls.append((args, target, refresh_after_import))
                    or import_args_use_case.ProjectFileImportBatchResult(
                        results=[
                            import_args_use_case.ProjectFileImportResult(
                                source_path=args.files[0].path,
                                success=True,
                                message="Imported successfully.",
                            )
                        ],
                        target_db_path=target.file_path,
                        refresh_pending=True,
                    )
                ),
                refresh_import_result=lambda result: refresh_calls.append(result)
                or import_args_use_case.ProjectFileImportBatchResult(
                    target_db_path=result.target_db_path
                ),
            )
            window._current_project_import_target = lambda: None
            window._deferred_persistence_manager = SimpleNamespace(
                flush_for_file=lambda path: flush_calls.append(path) or True
            )
            window._select_project_file_import_result = selections.append
            window._show_project_file_import_result = summaries.append
            timer = _startup_import_FakeTimerQueue()
            original_single_shot = main_window_module.QtCore.QTimer.singleShot
            original_progress_dialog = main_window_module.ProgressDialog
            try:
                _startup_import_FakeStartupProgressDialog.instances = []
                main_window_module.ProgressDialog = (
                    _startup_import_FakeStartupProgressDialog
                )
                main_window_module.QtCore.QTimer.singleShot = timer.singleShot
                MainWindow.enqueue_project_file_args(
                    window, _startup_import__project_file_args(first)
                )
                MainWindow.enqueue_project_file_args(
                    window, _startup_import__project_file_args(second)
                )
                self.assertEqual(
                    timer.callbacks, [window._run_pending_project_file_imports]
                )
                timer.callbacks.pop(0)()
            finally:
                main_window_module.ProgressDialog = original_progress_dialog
                main_window_module.QtCore.QTimer.singleShot = original_single_shot
            self.assertEqual(len(execute_calls), 1)
            self.assertIs(execute_calls[0][1], target)
            self.assertFalse(execute_calls[0][2])
            self.assertEqual(
                [item.path for item in execute_calls[0][0].files],
                [str(first), str(second)],
            )
            self.assertEqual(flush_calls, ["target.mdb"])
            self.assertEqual(len(refresh_calls), 1)
            self.assertEqual(len(selections), 1)
            self.assertEqual(len(summaries), 1)
            self.assertEqual(
                len(_startup_import_FakeStartupProgressDialog.instances), 1
            )
            self.assertIs(
                _startup_import_FakeStartupProgressDialog.instances[0].parent, window
            )
            self.assertEqual(
                _startup_import_FakeStartupProgressDialog.instances[0].action_text,
                "Importing",
            )
            self.assertFalse(window._pending_project_file_args)
            self.assertFalse(window._project_file_import_scheduled)
            self.assertFalse(window._project_file_import_running)

    def test_queued_startup_load_is_ignored_after_shutdown_starts(self):
        window = _startup_import__startup_import_window()
        window._collaboration_shutdown_pending = True
        window.app_controller = SimpleNamespace(
            load_files_from_config=lambda: self.fail(
                "Startup database loading must not begin during shutdown"
            )
        )
        MainWindow._load_files_from_config(window)
        self.assertFalse(window._startup_load_complete)
        self.assertEqual(
            list(window._shutdown_deferred_callbacks), ["load_files_from_config"]
        )

    def test_queued_startup_load_replays_when_shutdown_is_aborted(self):
        window = _startup_import__startup_import_window()
        window._collaboration_shutdown_pending = True
        loads = []
        shown = []
        restores = []
        window.app_controller = SimpleNamespace(
            load_files_from_config=lambda: loads.append(True) or ["target.mdb"],
            has_any_databases=lambda: True,
        )
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(sync_after_startup_load=lambda: None)
        )
        window._workspace_state_coordinator = SimpleNamespace(
            restore_deferred_state=lambda: restores.append(True)
        )
        window.show = lambda: shown.append(True)
        timer = _startup_import_FakeTimerQueue()
        original_single_shot = main_window_module.QtCore.QTimer.singleShot
        original_show_critical = main_window_module.show_critical
        try:
            main_window_module.QtCore.QTimer.singleShot = timer.singleShot
            main_window_module.show_critical = lambda *_args: None
            MainWindow._load_files_from_config(window)
            self.assertEqual(loads, [])
            MainWindow._on_shutdown_mutation_drain_complete(
                window, False, "shutdown aborted"
            )
            while timer.callbacks:
                timer.callbacks.pop(0)()
        finally:
            main_window_module.QtCore.QTimer.singleShot = original_single_shot
            main_window_module.show_critical = original_show_critical
        self.assertEqual(shown, [True])
        self.assertEqual(loads, [True])
        self.assertEqual(restores, [True])
        self.assertTrue(window._startup_load_complete)

    def test_aborted_shutdown_replays_startup_load_before_main_window_show(self):
        window = _startup_import__startup_import_window()
        window._collaboration_shutdown_pending = True
        calls = []
        window._needs_create_database_prompt = False
        window._update_service = None
        window.app_controller = SimpleNamespace(
            load_files_from_config=lambda: calls.append("load") or [],
            has_any_databases=lambda: False,
        )
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(sync_after_startup_load=lambda: None)
        )
        window._workspace_state_coordinator = SimpleNamespace(
            show_main_window=lambda: calls.append("show"),
            restore_deferred_state=lambda: calls.append("restore"),
        )
        window.raise_ = lambda: None
        window.activateWindow = lambda: None
        window._prompt_create_database = lambda: calls.append("prompt")
        timer = _startup_import_FakeTimerQueue()
        original_single_shot = main_window_module.QtCore.QTimer.singleShot
        try:
            main_window_module.QtCore.QTimer.singleShot = timer.singleShot
            MainWindow._show_main_window(window)
            MainWindow._load_files_from_config(window)
            window._collaboration_shutdown_pending = False
            MainWindow._resume_shutdown_deferred_callbacks(window)
            while timer.callbacks:
                timer.callbacks.pop(0)()
        finally:
            main_window_module.QtCore.QTimer.singleShot = original_single_shot
        self.assertEqual(calls[:2], ["load", "show"])
        self.assertEqual(calls.count("prompt"), 1)

    def test_deferred_workspace_restore_waits_for_tentative_shutdown(self):
        window = _startup_import__startup_import_window()
        restores = []
        window.app_controller = SimpleNamespace(
            load_files_from_config=lambda: ["target.mdb"],
            has_any_databases=lambda: True,
        )
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(sync_after_startup_load=lambda: None)
        )
        window._workspace_state_coordinator = SimpleNamespace(
            restore_deferred_state=lambda: restores.append(True)
        )
        timer = _startup_import_FakeTimerQueue()
        original_single_shot = main_window_module.QtCore.QTimer.singleShot
        try:
            main_window_module.QtCore.QTimer.singleShot = timer.singleShot
            MainWindow._load_files_from_config(window)
            window._collaboration_shutdown_pending = True
            timer.callbacks.pop(0)()
        finally:
            main_window_module.QtCore.QTimer.singleShot = original_single_shot
        self.assertEqual(restores, [])
        self.assertEqual(
            list(window._shutdown_deferred_callbacks),
            ["restore_deferred_workspace_state"],
        )

    def test_queued_main_window_show_is_ignored_after_shutdown_starts(self):
        window = _startup_import__startup_import_window()
        window._collaboration_shutdown_pending = True
        window._workspace_state_coordinator = SimpleNamespace(
            show_main_window=lambda: self.fail(
                "A queued startup callback must not reshow the closing window"
            )
        )
        MainWindow._show_main_window(window)
        self.assertEqual(
            list(window._shutdown_deferred_callbacks), ["show_main_window"]
        )

    def test_main_window_show_without_update_service_or_prompt_schedules_nothing(
        self,
    ):
        window = _startup_import__startup_import_window()
        window._workspace_state_coordinator = SimpleNamespace(
            show_main_window=lambda: None
        )
        window.raise_ = lambda: None
        window.activateWindow = lambda: None
        window._update_service = None
        window._needs_create_database_prompt = False
        timer = _startup_import_FakeTimerQueue()
        with patch.object(QtCore.QTimer, "singleShot", timer.singleShot):
            MainWindow._show_main_window(window)
        self.assertEqual(timer.callbacks, [])

    def test_normal_main_window_show_schedules_update_and_database_prompt(self):
        window = _startup_import__startup_import_window()
        calls = []
        window._workspace_state_coordinator = SimpleNamespace(
            show_main_window=lambda: calls.append("show")
        )
        window.raise_ = lambda: calls.append("raise")
        window.activateWindow = lambda: calls.append("activate")
        window._update_service = object()
        window._needs_create_database_prompt = True
        timer = _startup_import_FakeTimerQueue()
        original_single_shot = main_window_module.QtCore.QTimer.singleShot
        try:
            main_window_module.QtCore.QTimer.singleShot = timer.singleShot
            MainWindow._show_main_window(window)
        finally:
            main_window_module.QtCore.QTimer.singleShot = original_single_shot
        self.assertEqual(calls, ["show", "raise", "activate"])
        self.assertEqual(
            timer.callbacks,
            [window._check_for_updates, window._prompt_create_database],
        )
        self.assertFalse(window._needs_create_database_prompt)

    def test_queued_create_database_prompt_is_ignored_after_shutdown_starts(self):
        window = _startup_import__startup_import_window()
        window._collaboration_shutdown_pending = True
        window.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: self.fail(
                "A queued database prompt must not inspect access during shutdown"
            )
        )
        MainWindow._prompt_create_database(window)
        self.assertEqual(
            list(window._shutdown_deferred_callbacks), ["prompt_create_database"]
        )

    def test_create_database_prompt_without_access_never_opens_the_dialog(self):
        window = _startup_import__startup_import_window()
        window.ui_access_manager = SimpleNamespace(is_allowed=lambda _feature: False)
        with patch.object(
            main_window_module,
            "CreateDatabaseDialog",
            side_effect=AssertionError("Denied access must not open the dialog"),
        ):
            MainWindow._prompt_create_database(window)

    def test_create_database_prompt_does_not_continue_when_shutdown_starts_in_dialog(
        self,
    ):
        window = _startup_import__startup_import_window()
        window.ui_access_manager = SimpleNamespace(is_allowed=lambda _feature: True)
        window.icon_provider = object()
        window._create_database_with_progress = lambda: self.fail(
            "Database creation must not begin after shutdown starts"
        )

        class ShutdownDialog:
            deleted = False

            def __init__(self, _icon_provider, _parent):
                pass

            def exec(self):
                window._collaboration_shutdown_pending = True
                return main_window_module.QtWidgets.QDialog.DialogCode.Accepted

            def deleteLater(self):
                type(self).deleted = True

        original_dialog = main_window_module.CreateDatabaseDialog
        try:
            main_window_module.CreateDatabaseDialog = ShutdownDialog
            MainWindow._prompt_create_database(window)
        finally:
            main_window_module.CreateDatabaseDialog = original_dialog
        self.assertTrue(ShutdownDialog.deleted)
        self.assertEqual(
            list(window._shutdown_deferred_callbacks),
            ["create_database_after_prompt"],
        )

    def test_create_database_prompt_completes_normally_before_shutdown(self):
        window = _startup_import__startup_import_window()
        window.icon_provider = object()
        window._create_database_with_progress = lambda: "new.mdb"
        window._file_loading_service = SimpleNamespace(
            load_file=lambda path: SimpleNamespace(success=True, file_path=path)
        )
        published = []
        window.event_bus = SimpleNamespace(
            publish=lambda event, **payload: published.append((event, payload))
        )

        class AcceptedDialog:
            deleted = False

            def __init__(self, _icon_provider, _parent):
                pass

            def exec(self):
                return main_window_module.QtWidgets.QDialog.DialogCode.Accepted

            def deleteLater(self):
                type(self).deleted = True

        original_dialog = main_window_module.CreateDatabaseDialog
        try:
            main_window_module.CreateDatabaseDialog = AcceptedDialog
            MainWindow._prompt_create_database(window)
        finally:
            main_window_module.CreateDatabaseDialog = original_dialog
        self.assertTrue(AcceptedDialog.deleted)
        self.assertEqual(
            published,
            [(main_window_module.AppEvents.FILE_OPENED, {"file_path": "new.mdb"})],
        )

    def test_deferred_database_creation_revalidates_a_second_shutdown(self):
        window = _startup_import__startup_import_window()
        window._collaboration_shutdown_pending = True
        window._create_database_with_progress = lambda: self.fail(
            "Deferred database creation must revalidate shutdown ownership"
        )
        MainWindow._complete_create_database_prompt(window)
        self.assertIn(
            "create_database_after_prompt", window._shutdown_deferred_callbacks
        )

    def test_database_creation_does_not_load_when_shutdown_starts_in_progress(self):
        window = _startup_import__startup_import_window()
        loads = []

        def create_database():
            window._collaboration_shutdown_pending = True
            return "new.mdb"

        window._create_database_with_progress = create_database
        window._file_loading_service = SimpleNamespace(load_file=loads.append)
        MainWindow._complete_create_database_prompt(window)
        self.assertEqual(loads, [])
        self.assertEqual(
            list(window._shutdown_deferred_callbacks), ["complete_created_database"]
        )

    def test_database_creation_failure_notice_waits_when_shutdown_starts_in_progress(
        self,
    ):
        window = _startup_import__startup_import_window()
        warnings = []

        def create_database():
            window._collaboration_shutdown_pending = True
            return None

        window._create_database_with_progress = create_database
        original_show_warning = main_window_module.show_warning
        try:
            main_window_module.show_warning = lambda *_args: warnings.append(True)
            MainWindow._complete_create_database_prompt(window)
        finally:
            main_window_module.show_warning = original_show_warning
        self.assertEqual(warnings, [])
        self.assertEqual(
            list(window._shutdown_deferred_callbacks), ["complete_created_database"]
        )

    def test_database_creation_failure_warns_and_does_not_load(self):
        window = _startup_import__startup_import_window()
        warnings = []
        window._create_database_with_progress = lambda: None
        window._file_loading_service = SimpleNamespace(
            load_file=lambda _path: self.fail("A failed creation must not load")
        )
        with patch.object(
            main_window_module,
            "show_warning",
            lambda parent, title, message: warnings.append((parent, title, message)),
        ):
            MainWindow._complete_create_database_prompt(window)
        self.assertEqual(
            warnings,
            [(window, "Error", "Failed to create database. Check logs for details.")],
        )

    def test_database_creation_that_cannot_be_loaded_publishes_no_file_opened(self):
        window = _startup_import__startup_import_window()
        window._create_database_with_progress = lambda: "new.mdb"
        window._file_loading_service = SimpleNamespace(
            load_file=lambda path: SimpleNamespace(success=False, file_path=path)
        )
        window.event_bus = SimpleNamespace(
            publish=lambda *_args, **_kwargs: self.fail(
                "A failed load must not publish"
            )
        )
        MainWindow._complete_create_database_prompt(window)

    def test_database_prompt_tolerates_parent_destroying_dialog(self):
        from shiboken6 import delete

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.assertIsNotNone(app)
        window = _startup_import__startup_import_window()
        window.icon_provider = object()
        window.ui_access_manager = SimpleNamespace(is_allowed=lambda _feature: True)
        window._complete_create_database_prompt = lambda: self.fail(
            "A rejected prompt must not create a database"
        )

        class DestroyedCreateDatabaseDialog(QtWidgets.QDialog):
            def __init__(self, *_args):
                super().__init__()

            def exec(self):
                delete(self)
                return QtWidgets.QDialog.DialogCode.Rejected

        original_dialog = main_window_module.CreateDatabaseDialog
        try:
            main_window_module.CreateDatabaseDialog = DestroyedCreateDatabaseDialog
            MainWindow._prompt_create_database(window)
        finally:
            main_window_module.CreateDatabaseDialog = original_dialog

    def test_queued_startup_import_does_not_begin_after_shutdown_starts(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.ost"
            source.write_text("ost")
            window = _startup_import__startup_import_window()
            window._startup_load_complete = True
            window._main_window_ready = True
            window._pending_project_file_args.append(
                _startup_import__project_file_args(source)
            )
            window._import_project_files_with_progress = lambda _args: self.fail(
                "A queued startup import must not begin during shutdown"
            )
            timer = _startup_import_FakeTimerQueue()
            original_single_shot = main_window_module.QtCore.QTimer.singleShot
            try:
                main_window_module.QtCore.QTimer.singleShot = timer.singleShot
                MainWindow._schedule_pending_project_file_imports(window)
                self.assertEqual(
                    timer.callbacks, [window._run_pending_project_file_imports]
                )
                window._collaboration_shutdown_pending = True
                timer.callbacks.pop()()
            finally:
                main_window_module.QtCore.QTimer.singleShot = original_single_shot
            self.assertFalse(window._project_file_import_scheduled)
            self.assertFalse(window._project_file_import_running)
            self.assertEqual(len(window._pending_project_file_args), 1)

    def test_async_startup_import_completion_does_not_project_during_shutdown(self):
        window = _startup_import__startup_import_window()
        window._project_file_import_running = True
        window._collaboration_shutdown_pending = True
        window._select_project_file_import_result = lambda _result: self.fail(
            "A shutdown completion must not change project selection"
        )
        window._show_project_file_import_result = lambda _result: self.fail(
            "A shutdown completion must not open a result dialog"
        )
        window._schedule_pending_project_file_imports = lambda: self.fail(
            "Shutdown must not schedule another startup import"
        )
        result = import_args_use_case.ProjectFileImportBatchResult(
            target_db_path="sql-database"
        )
        original_is_valid = main_window_module.isValid
        try:
            main_window_module.isValid = lambda _window: True
            MainWindow._complete_async_project_file_imports(window, result)
        finally:
            main_window_module.isValid = original_is_valid
        self.assertFalse(window._project_file_import_running)
        self.assertIn(
            "complete_project_file_imports", window._shutdown_deferred_callbacks
        )

    def test_sync_startup_import_completion_waits_when_shutdown_starts_in_progress(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.ost"
            source.write_text("ost")
            window = _startup_import__startup_import_window()
            window._startup_load_complete = True
            window._main_window_ready = True
            window._pending_project_file_args.append(
                _startup_import__project_file_args(source)
            )
            selections = []
            summaries = []
            result = import_args_use_case.ProjectFileImportBatchResult(
                target_db_path="target.mdb"
            )

            def import_with_progress(_args):
                window._collaboration_shutdown_pending = True
                return result

            window._import_project_files_with_progress = import_with_progress
            window._select_project_file_import_result = selections.append
            window._show_project_file_import_result = summaries.append
            MainWindow._run_pending_project_file_imports(window)
            self.assertEqual(selections, [])
            self.assertEqual(summaries, [])
            self.assertIn(
                "complete_project_file_imports",
                window._shutdown_deferred_callbacks,
            )

    def test_sync_startup_import_does_not_refresh_after_terminal_modal_shutdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.ost"
            source.write_text("ost")
            window = _startup_import__startup_import_window()
            window._startup_load_complete = True
            window._main_window_ready = True
            window._pending_project_file_args.append(
                _startup_import__project_file_args(source)
            )
            target = import_args_use_case.ProjectImportTarget("target.mdb")
            raw_result = import_args_use_case.ProjectFileImportBatchResult(
                results=[
                    import_args_use_case.ProjectFileImportResult(
                        source_path=str(source),
                        success=True,
                        message="Imported successfully.",
                    )
                ],
                target_db_path=target.file_path,
                refresh_pending=True,
            )
            refreshes = []
            window._current_project_import_target = lambda: None
            window._deferred_persistence_manager = SimpleNamespace(
                flush_for_file=lambda _path: True
            )
            window._import_project_files_from_args = SimpleNamespace(
                resolve_target=lambda _current: target,
                uses_async_import=lambda _target: False,
                execute_imports=lambda *_args, **_kwargs: raw_result,
                refresh_import_result=lambda result: refreshes.append(result) or result,
            )
            window._select_project_file_import_result = lambda _result: self.fail(
                "Terminal shutdown must not project the imported project"
            )
            window._show_project_file_import_result = lambda _result: self.fail(
                "Terminal shutdown must not show an import result"
            )

            class ClosingProgressDialog(_startup_import_FakeStartupProgressDialog):
                def exec(self):
                    window._collaboration_shutdown_complete = True
                    return self.result_code

            original_progress_dialog = main_window_module.ProgressDialog
            try:
                main_window_module.ProgressDialog = ClosingProgressDialog
                MainWindow._run_pending_project_file_imports(window)
            finally:
                main_window_module.ProgressDialog = original_progress_dialog
            self.assertEqual(refreshes, [])
            self.assertFalse(window._project_file_import_running)

    def test_terminal_shutdown_discards_deferred_startup_import_completion(self):
        window = _startup_import__startup_import_window()
        window._project_file_import_running = True
        window._collaboration_shutdown_pending = True
        window._select_project_file_import_result = lambda _result: self.fail(
            "Terminal shutdown must not project a deferred import"
        )
        window._show_project_file_import_result = lambda _result: self.fail(
            "Terminal shutdown must not show a deferred import result"
        )
        window._schedule_pending_project_file_imports = lambda: self.fail(
            "Terminal shutdown must not schedule another import"
        )
        window.close = lambda: None
        result = import_args_use_case.ProjectFileImportBatchResult(
            target_db_path="sql-database"
        )
        timer = _startup_import_FakeTimerQueue()
        original_is_valid = main_window_module.isValid
        original_single_shot = main_window_module.QtCore.QTimer.singleShot
        try:
            main_window_module.isValid = lambda _window: True
            main_window_module.QtCore.QTimer.singleShot = timer.singleShot
            MainWindow._complete_async_project_file_imports(window, result)
            MainWindow._on_collaboration_shutdown_complete(window, True, "")
        finally:
            main_window_module.isValid = original_is_valid
            main_window_module.QtCore.QTimer.singleShot = original_single_shot
        self.assertTrue(window._collaboration_shutdown_complete)
        self.assertEqual(window._shutdown_deferred_callbacks, {})

    def test_async_startup_import_completion_replays_when_shutdown_is_aborted(self):
        window = _startup_import__startup_import_window()
        window._project_file_import_running = True
        window._collaboration_shutdown_pending = True
        selections = []
        summaries = []
        scheduled_imports = []
        shown = []
        window._select_project_file_import_result = selections.append
        window._show_project_file_import_result = summaries.append
        window._schedule_pending_project_file_imports = (
            lambda: scheduled_imports.append(True)
        )
        window.show = lambda: shown.append(True)
        result = import_args_use_case.ProjectFileImportBatchResult(
            target_db_path="sql-database"
        )
        timer = _startup_import_FakeTimerQueue()
        original_is_valid = main_window_module.isValid
        original_single_shot = main_window_module.QtCore.QTimer.singleShot
        original_show_critical = main_window_module.show_critical
        try:
            main_window_module.isValid = lambda _window: True
            main_window_module.QtCore.QTimer.singleShot = timer.singleShot
            main_window_module.show_critical = lambda *_args: None
            MainWindow._complete_async_project_file_imports(window, result)
            self.assertEqual(selections, [])
            self.assertFalse(window._project_file_import_running)
            MainWindow._on_shutdown_mutation_drain_complete(
                window, False, "shutdown aborted"
            )
            for callback in list(timer.callbacks):
                callback()
        finally:
            main_window_module.isValid = original_is_valid
            main_window_module.QtCore.QTimer.singleShot = original_single_shot
            main_window_module.show_critical = original_show_critical
        self.assertEqual(shown, [True])
        self.assertEqual(selections, [result])
        self.assertEqual(summaries, [result])
        self.assertEqual(scheduled_imports, [True])
        self.assertFalse(window._project_file_import_running)

    def test_startup_import_summary_uses_main_window_parent(self):
        window = _startup_import__startup_import_window()
        calls = []
        result = import_args_use_case.ProjectFileImportBatchResult(
            results=[
                import_args_use_case.ProjectFileImportResult(
                    source_path="source.ost",
                    success=True,
                    message="Imported successfully.",
                    project_name="Imported Project",
                )
            ],
            target_db_path="target.mdb",
            selected_project_uid="project-1",
        )
        original_show_info = main_window_module.show_info
        try:
            main_window_module.show_info = lambda parent, title, details: calls.append(
                (parent, title, details)
            )
            MainWindow._show_project_file_import_result(window, result)
        finally:
            main_window_module.show_info = original_show_info
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0][0], window)
        self.assertEqual(calls[0][1], "Import Complete")
        self.assertEqual(
            calls[0][2], "Successfully imported 'source.ost' into the database."
        )

    def test_startup_import_summary_severity_follows_success_and_failure_mix(self):
        window = _startup_import__startup_import_window()
        ok = import_args_use_case.ProjectFileImportResult(
            source_path="ok.ost", success=True, message="Imported successfully."
        )
        bad = import_args_use_case.ProjectFileImportResult(
            source_path="bad.ost", success=False, message="Corrupt file."
        )
        calls = []
        recorder = lambda level: (
            lambda parent, title, details: calls.append((level, title, details))
        )
        with patch.object(
            main_window_module, "show_info", recorder("info")
        ), patch.object(
            main_window_module, "show_warning", recorder("warning")
        ), patch.object(
            main_window_module, "show_critical", recorder("critical")
        ):
            for results in ([ok], [ok, bad], [bad]):
                MainWindow._show_project_file_import_result(
                    window,
                    import_args_use_case.ProjectFileImportBatchResult(
                        results=results, target_db_path="target.mdb"
                    ),
                )
            MainWindow._show_project_file_import_result(
                window,
                import_args_use_case.ProjectFileImportBatchResult(
                    target_db_path="target.mdb"
                ),
            )
        self.assertEqual(
            calls,
            [
                (
                    "info",
                    "Import Complete",
                    "Successfully imported 'ok.ost' into the database.",
                ),
                (
                    "warning",
                    "Import Complete",
                    "Successfully imported 'ok.ost' into the database.\nbad.ost: Corrupt file.",
                ),
                ("critical", "Import Error", "bad.ost: Corrupt file."),
            ],
        )

    def test_startup_import_multi_file_message_counts_successes(self):
        results = [
            import_args_use_case.ProjectFileImportResult(
                source_path=f"{name}.ost",
                success=True,
                message="Imported successfully.",
            )
            for name in ("a", "b")
        ]
        details = MainWindow._format_project_file_import_details(
            _startup_import__startup_import_window(),
            import_args_use_case.ProjectFileImportBatchResult(
                results=results, target_db_path="target.mdb"
            ),
        )
        self.assertEqual(
            details, "Successfully imported 2 project files into the database."
        )

    def test_startup_import_success_message_uses_source_path(self):
        source = "C:/Users/fabia/Downloads/Woodside Village.osp"
        result = import_args_use_case.ProjectFileImportBatchResult(
            results=[
                import_args_use_case.ProjectFileImportResult(
                    source_path=source,
                    success=True,
                    message="Imported successfully.",
                    project_name=DELETED_BIDS_PROJECT_NAME,
                )
            ],
            target_db_path="target.mdb",
            selected_project_uid=DELETED_BIDS_PROJECT_UID,
        )
        details = MainWindow._format_project_file_import_details(
            _startup_import__startup_import_window(), result
        )
        self.assertEqual(
            details,
            f"Successfully imported '{source}' into the database.",
        )

    def test_startup_import_orphan_message_explains_deleted_bids_fallback(self):
        source = "C:/Users/fabia/Downloads/Woodside Village.osp"
        result = import_args_use_case.ProjectFileImportBatchResult(
            results=[
                import_args_use_case.ProjectFileImportResult(
                    source_path=source,
                    success=True,
                    message="Imported successfully.",
                )
            ],
            target_db_path="target.mdb",
            import_as_orphaned_due_to_deleted_target=True,
        )
        details = MainWindow._format_project_file_import_details(
            _startup_import__startup_import_window(), result
        )
        self.assertEqual(
            details,
            f"Successfully imported '{source}' as orphaned because "
            f"{DELETED_BIDS_PROJECT_NAME} cannot be used as an import target.",
        )

    def test_main_window_selects_batch_project_or_database_once(self):
        window = SimpleNamespace(
            project_view=_startup_import_FakeProjectView(),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: None),
            _project_data_service=SimpleNamespace(get_bid=lambda _bid_ref: None),
        )
        project_result = import_args_use_case.ProjectFileImportBatchResult(
            target_db_path="target.mdb",
            selected_project_uid="project-1",
        )
        database_result = import_args_use_case.ProjectFileImportBatchResult(
            target_db_path="target.mdb",
        )
        MainWindow._select_project_file_import_result(window, project_result)
        MainWindow._select_project_file_import_result(window, database_result)
        self.assertEqual(
            window.project_view.project_selections, [("project-1", "target.mdb")]
        )
        self.assertEqual(window.project_view.file_selections, ["target.mdb"])

    def test_main_window_preserves_active_bid_after_import_into_project(self):
        selected_bid_ref = BidRef("target.mdb", "38")
        window = SimpleNamespace(
            project_view=_startup_import_FakeProjectView(),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: selected_bid_ref
            ),
            _project_data_service=SimpleNamespace(
                get_bid=lambda bid_ref: (
                    object() if bid_ref == selected_bid_ref else None
                )
            ),
        )
        result = import_args_use_case.ProjectFileImportBatchResult(
            target_db_path="target.mdb",
            selected_project_uid="comparison",
        )
        MainWindow._select_project_file_import_result(window, result)
        self.assertEqual(window.project_view.bid_selections, [selected_bid_ref])
        self.assertEqual(window.project_view.project_selections, [])
        self.assertEqual(window.project_view.file_selections, [])

    def test_main_window_ignores_selected_bid_that_is_no_longer_loaded(self):
        window = SimpleNamespace(
            project_view=_startup_import_FakeProjectView(),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: BidRef("target.mdb", "gone")
            ),
            _project_data_service=SimpleNamespace(get_bid=lambda _bid_ref: None),
        )
        MainWindow._select_project_file_import_result(
            window,
            import_args_use_case.ProjectFileImportBatchResult(
                target_db_path="target.mdb", selected_project_uid="comparison"
            ),
        )
        MainWindow._select_project_file_import_result(
            window, import_args_use_case.ProjectFileImportBatchResult()
        )
        self.assertEqual(window.project_view.bid_selections, [])
        self.assertEqual(
            window.project_view.project_selections, [("comparison", "target.mdb")]
        )
        self.assertEqual(window.project_view.file_selections, [])


class MainWindowMaintenanceShutdownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_shutdown_does_not_start_during_maintenance(self):
        host = SimpleNamespace(
            _application_shutdown_finalized=False,
            _collaboration_shutdown_pending=False,
            _collaboration_shutdown_failed=False,
            _collaboration_shutdown_complete=False,
            handlers=SimpleNamespace(
                file_ops=SimpleNamespace(maintenance_pending=True)
            ),
            hide=Mock(),
            _begin_application_shutdown=Mock(),
        )
        event = QtGui.QCloseEvent()
        with patch(
            "ost_visualizer.presentation.main_window.QtCore.QTimer.singleShot"
        ) as queued:
            MainWindow.closeEvent(host, event)
        self.assertFalse(event.isAccepted())
        host.hide.assert_not_called()
        queued.assert_not_called()


class ProjectTreeMasterDataReadTests(unittest.TestCase):
    def test_sql_job_status_menu_uses_authoritative_model_snapshot(self):
        expected = [JobStatus(uid="status-1", name="Open")]

        class ReadService:
            def get_job_statuses(self, _file_path):
                raise AssertionError(
                    "SQL job statuses must not be read on the Qt thread"
                )

        owner = SimpleNamespace(
            _project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _file_path: True
            ),
            _project_data_service=SimpleNamespace(
                get_job_status_snapshot=lambda _file_path: expected
            ),
            _project_read_service=ReadService(),
        )
        self.assertEqual(
            MainWindow._get_project_tree_job_statuses(owner, "sql-database"),
            expected,
        )

    def test_mdb_job_status_menu_reads_the_database_synchronously(self):
        expected = [JobStatus(uid="status-1", name="Open")]
        reads = []
        owner = SimpleNamespace(
            _project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _file_path: False
            ),
            _project_data_service=SimpleNamespace(
                get_job_status_snapshot=lambda _file_path: self.fail(
                    "MDB job statuses are not model snapshots"
                )
            ),
            _project_read_service=SimpleNamespace(
                get_job_statuses=lambda file_path: reads.append(file_path) or expected
            ),
        )
        self.assertEqual(
            MainWindow._get_project_tree_job_statuses(owner, "access.mdb"), expected
        )
        self.assertEqual(reads, ["access.mdb"])


class DialogLifecycleTests(unittest.TestCase):
    def test_create_database_uses_progress_dialog_worker_task(self):
        class FakeAppController:
            def __init__(self):
                self.calls = []

            def create_new_database(self, name=None, progress_callback=None):
                self.calls.append((name, progress_callback is not None))
                if progress_callback is not None:
                    progress_callback("schema tables")
                return "created.mdb"

        window = MainWindow.__new__(MainWindow)
        window.app_controller = FakeAppController()
        original_dialog = main_window_module.ProgressDialog
        _dialog_lifecycle_support_FakeProgressDialog.instances = []
        _dialog_lifecycle_support_FakeProgressDialog.result_code = (
            QtWidgets.QDialog.DialogCode.Accepted
        )
        try:
            main_window_module.ProgressDialog = (
                _dialog_lifecycle_support_FakeProgressDialog
            )
            result = MainWindow._create_database_with_progress(window, "Named DB")
        finally:
            main_window_module.ProgressDialog = original_dialog
        dialog = _dialog_lifecycle_support_FakeProgressDialog.instances[0]
        self.assertEqual(result, "created.mdb")
        self.assertEqual(dialog.filename, "new database")
        self.assertEqual(dialog.action_text, "Creating database")
        self.assertEqual(window.app_controller.calls, [("Named DB", True)])
        self.assertEqual(dialog.messages, ["schema tables"])
        self.assertEqual(dialog.exec_calls, 1)
        self.assertEqual(dialog.cleanup_calls, 1)
        self.assertEqual(dialog.delete_calls, 1)
        self.assertTrue(dialog.cleaned_up)
        self.assertTrue(dialog.deleted)

    def test_create_database_progress_dialog_failure_cleans_up(self):
        class FakeAppController:
            def create_new_database(self, name=None, progress_callback=None):
                return None

        window = MainWindow.__new__(MainWindow)
        window.app_controller = FakeAppController()
        original_dialog = main_window_module.ProgressDialog
        _dialog_lifecycle_support_FakeProgressDialog.instances = []
        _dialog_lifecycle_support_FakeProgressDialog.result_code = (
            QtWidgets.QDialog.DialogCode.Rejected
        )
        try:
            main_window_module.ProgressDialog = (
                _dialog_lifecycle_support_FakeProgressDialog
            )
            result = MainWindow._create_database_with_progress(window)
        finally:
            main_window_module.ProgressDialog = original_dialog
        dialog = _dialog_lifecycle_support_FakeProgressDialog.instances[0]
        self.assertIsNone(result)
        self.assertEqual(dialog.exec_calls, 1)
        self.assertEqual(dialog.cleanup_calls, 1)
        self.assertEqual(dialog.delete_calls, 1)
        self.assertTrue(dialog.cleaned_up)
        self.assertTrue(dialog.deleted)

    def test_create_database_worker_error_is_logged_and_reports_no_path(self):
        window = MainWindow.__new__(MainWindow)
        window.app_controller = SimpleNamespace(
            create_new_database=lambda *_args, **_kwargs: None
        )

        class FailingProgressDialog(_dialog_lifecycle_support_FakeProgressDialog):
            result_code = QtWidgets.QDialog.DialogCode.Rejected

            def exec(self):
                self.error = RuntimeError("schema failed")
                return self.result_code

        with patch.object(
            main_window_module, "ProgressDialog", FailingProgressDialog
        ), self.assertLogs(
            "ost_visualizer.presentation.main_window", level="ERROR"
        ) as captured:
            result = MainWindow._create_database_with_progress(window)
        self.assertIsNone(result)
        self.assertIn("schema failed", captured.output[0])

    def test_create_database_prompt_stops_after_main_window_destruction(self):
        _dialog_lifecycle_support__app()
        window = MainWindow.__new__(MainWindow)
        QtWidgets.QMainWindow.__init__(window)
        window._collaboration_shutdown_complete = False
        window._application_shutdown_finalized = False
        window._collaboration_shutdown_pending = False
        window._shutdown_deferred_callbacks = {}
        window.ui_access_manager = SimpleNamespace(is_allowed=lambda _feature: True)
        window.icon_provider = None
        continued = []
        window._complete_create_database_prompt = lambda: continued.append(True)

        class DestroyingDialog(QtWidgets.QDialog):
            def __init__(self, _icon_provider, parent):
                super().__init__(parent)

            def exec(self):
                delete(window)
                return QtWidgets.QDialog.DialogCode.Accepted

        with patch.object(main_window_module, "CreateDatabaseDialog", DestroyingDialog):
            MainWindow._prompt_create_database(window)
        self.assertEqual(continued, [])

    def test_create_database_progress_stops_after_main_window_destruction(self):
        _dialog_lifecycle_support__app()
        window = MainWindow.__new__(MainWindow)
        QtWidgets.QMainWindow.__init__(window)
        window.app_controller = SimpleNamespace(create_new_database=lambda *_args: "x")
        cleaned = []

        class DestroyingProgress(QtWidgets.QDialog):
            def __init__(self, *_args, parent=None, **_kwargs):
                super().__init__(parent)

            def exec(self):
                delete(window)
                return QtWidgets.QDialog.DialogCode.Accepted

            def cleanup(self):
                cleaned.append(True)

        with patch.object(main_window_module, "ProgressDialog", DestroyingProgress):
            result = MainWindow._create_database_with_progress(window)
        self.assertIsNone(result)
        self.assertEqual(cleaned, [])


class BidLockPermissionTests(unittest.TestCase):
    def test_shared_paste_has_no_target_for_multi_project_selection(self):
        ui_state = UIStateManager(
            SimpleNamespace(
                display_modes_synced=True,
                display_mode_3d="solid",
                display_mode_2d="solid",
                grayscale_enabled=False,
            )
        )
        active_ref = BidRef("C:/jobs/active.mdb", "7")
        ui_state.set_bid_selection(active_ref)
        ui_state.set_bid_multi_selection([])
        ui_state.set_project_multi_selection(
            ["project-8", "project-9"], "C:/jobs/other.mdb"
        )
        window = MainWindow.__new__(MainWindow)
        window.ui_state_manager = ui_state
        window._project_data_service = SimpleNamespace(
            find_project_uid_for_bid=lambda _ref: "active-project"
        )
        self.assertIsNone(MainWindow._get_bid_paste_target(window))

    def _paste_target_window(self):
        ui_state = UIStateManager(
            SimpleNamespace(
                display_modes_synced=True,
                display_mode_3d="solid",
                display_mode_2d="solid",
                grayscale_enabled=False,
            )
        )
        window = MainWindow.__new__(MainWindow)
        window.ui_state_manager = ui_state
        window._project_data_service = SimpleNamespace(
            find_project_uid_for_bid=lambda ref: (
                DELETED_BIDS_PROJECT_UID
                if ref.bid_uid == "deleted"
                else "active-project"
            )
        )
        return window, ui_state

    def test_shared_paste_targets_single_project_bid_or_database(self):
        window, ui_state = self._paste_target_window()
        ui_state.set_project_multi_selection(["project-8"], "C:/jobs/other.mdb")
        self.assertEqual(
            MainWindow._get_bid_paste_target(window), ("C:/jobs/other.mdb", "project-8")
        )
        ui_state.set_project_multi_selection(
            [DELETED_BIDS_PROJECT_UID], "C:/jobs/other.mdb"
        )
        self.assertIsNone(MainWindow._get_bid_paste_target(window))
        active_ref = BidRef("C:/jobs/active.mdb", "7")
        ui_state.set_bid_selection(active_ref)
        ui_state.set_bid_multi_selection([active_ref])
        self.assertEqual(
            MainWindow._get_bid_paste_target(window),
            ("C:/jobs/active.mdb", "active-project"),
        )
        deleted_ref = BidRef("C:/jobs/active.mdb", "deleted")
        ui_state.set_bid_selection(deleted_ref)
        ui_state.set_bid_multi_selection([deleted_ref])
        self.assertIsNone(MainWindow._get_bid_paste_target(window))

    def test_shared_paste_has_no_target_when_projects_and_bids_are_both_selected(self):
        window, ui_state = self._paste_target_window()
        active_ref = BidRef("C:/jobs/active.mdb", "7")
        ui_state.set_bid_selection(active_ref)
        ui_state.set_bid_multi_selection([active_ref])
        ui_state.set_project_multi_selection(["project-8"], "C:/jobs/other.mdb")
        self.assertIsNone(MainWindow._get_bid_paste_target(window))


class WorkspaceStateCoordinatorDetachedWindowTests(unittest.TestCase):
    def test_explicit_annotation_window_state_overrides_saved_fullscreen(self):
        calls = []
        state = WorkspaceState()
        saved = state.detached_windows.annotation_view
        saved.geometry_b64 = _detached_support__encoded_geometry(b"saved")
        saved.is_maximized = True
        saved.is_fullscreen = True
        window = MainWindow.__new__(MainWindow)
        window._workspace_state_model = SimpleNamespace(state=state)
        window._annotation_window_action = _detached_support_FakeCheckAction()
        window._annotation_view_manager = SimpleNamespace(
            is_view_open=lambda: False,
            open_view=lambda *args, **kwargs: calls.append((args, kwargs)),
        )
        window._view_window_manager = SimpleNamespace(is_view_open=lambda: False)
        window.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("job.mdb", "bid-1")
        )
        window.can_restore_annotation_window = lambda: True
        window.get_active_takeoff_page_uid = lambda: "page-1"
        explicit_geometry = QtCore.QByteArray(b"explicit")
        MainWindow.set_annotation_window_visible(
            window,
            True,
            initial_geometry=explicit_geometry,
            initial_is_maximized=False,
            initial_is_fullscreen=False,
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], (BidRef("job.mdb", "bid-1"), "page-1", None))
        self.assertEqual(calls[0][1]["initial_geometry"], explicit_geometry)
        self.assertFalse(calls[0][1]["initial_is_maximized"])
        self.assertFalse(calls[0][1]["initial_is_fullscreen"])
        self.assertTrue(window._annotation_window_action.checked)

    def test_annotation_window_without_explicit_state_restores_saved_state(self):
        calls = []
        state = WorkspaceState()
        saved = state.detached_windows.annotation_view
        saved.geometry_b64 = _detached_support__encoded_geometry(b"saved")
        saved.is_maximized = True
        saved.is_fullscreen = True
        window = MainWindow.__new__(MainWindow)
        window._workspace_state_model = SimpleNamespace(state=state)
        window._annotation_window_action = _detached_support_FakeCheckAction()
        window._annotation_view_manager = SimpleNamespace(
            is_view_open=lambda: False,
            open_view=lambda *args, **kwargs: calls.append((args, kwargs)),
        )
        window._view_window_manager = SimpleNamespace(is_view_open=lambda: False)
        window.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("job.mdb", "bid-1")
        )
        window.can_restore_annotation_window = lambda: True
        window.get_active_takeoff_page_uid = lambda: "page-1"
        MainWindow.set_annotation_window_visible(window, True)
        self.assertEqual(bytes(calls[0][1]["initial_geometry"]), b"saved")
        self.assertTrue(calls[0][1]["initial_is_maximized"])
        self.assertTrue(calls[0][1]["initial_is_fullscreen"])

    def test_annotation_window_stays_closed_when_it_cannot_be_restored(self):
        window = MainWindow.__new__(MainWindow)
        window._annotation_window_action = _detached_support_FakeCheckAction()
        window._annotation_window_action.checked = True
        window._annotation_view_manager = SimpleNamespace(
            open_view=lambda *_args, **_kwargs: self.fail("must not open")
        )
        window.can_restore_annotation_window = lambda: False
        MainWindow.set_annotation_window_visible(window, True)
        self.assertFalse(window._annotation_window_action.checked)

    def test_explicit_view_window_state_overrides_saved_fullscreen(self):
        calls = []
        state = WorkspaceState()
        saved = state.detached_windows.view_window
        saved.geometry_b64 = _detached_support__encoded_geometry(b"saved")
        saved.is_maximized = True
        saved.is_fullscreen = True
        window = MainWindow.__new__(MainWindow)
        window._workspace_state_model = SimpleNamespace(state=state)
        window._view_window_action = _detached_support_FakeCheckAction()
        window._view_window_manager = SimpleNamespace(
            is_view_open=lambda: False,
            open_view=lambda *args, **kwargs: calls.append((args, kwargs)),
        )
        window._annotation_view_manager = SimpleNamespace(get_active_view=lambda: None)
        window.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("job.mdb", "bid-1")
        )
        window.can_restore_view_window = lambda: True
        window.get_active_takeoff_page_uid = lambda: "page-1"
        explicit_geometry = QtCore.QByteArray(b"explicit")
        MainWindow.set_view_window_visible(
            window,
            True,
            initial_geometry=explicit_geometry,
            initial_is_maximized=False,
            initial_is_fullscreen=False,
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], (BidRef("job.mdb", "bid-1"), "page-1", None))
        self.assertEqual(calls[0][1]["initial_geometry"], explicit_geometry)
        self.assertFalse(calls[0][1]["initial_is_maximized"])
        self.assertFalse(calls[0][1]["initial_is_fullscreen"])
        self.assertTrue(window._view_window_action.checked)

    def test_view_window_without_explicit_state_restores_saved_state(self):
        calls = []
        state = WorkspaceState()
        saved = state.detached_windows.view_window
        saved.geometry_b64 = _detached_support__encoded_geometry(b"saved")
        saved.is_maximized = True
        saved.is_fullscreen = True
        window = MainWindow.__new__(MainWindow)
        window._workspace_state_model = SimpleNamespace(state=state)
        window._view_window_action = _detached_support_FakeCheckAction()
        window._view_window_manager = SimpleNamespace(
            is_view_open=lambda: False,
            open_view=lambda *args, **kwargs: calls.append((args, kwargs)),
        )
        window._annotation_view_manager = SimpleNamespace(
            get_active_view=lambda: SimpleNamespace(
                bid_ref=BidRef("annotation.mdb", "bid-9"),
                target_page_uid="annotation-page",
                target_named_view_uid="named-view",
            )
        )
        window.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("job.mdb", "bid-1")
        )
        window.can_restore_view_window = lambda: True
        window.get_active_takeoff_page_uid = lambda: "page-1"
        MainWindow.set_view_window_visible(window, True)
        self.assertEqual(
            calls[0][0],
            (BidRef("annotation.mdb", "bid-9"), "annotation-page", "named-view"),
        )
        self.assertEqual(bytes(calls[0][1]["initial_geometry"]), b"saved")
        self.assertTrue(calls[0][1]["initial_is_maximized"])
        self.assertTrue(calls[0][1]["initial_is_fullscreen"])

    def test_hidden_left_splitter_size_does_not_replace_last_good_layout(self):
        window = MainWindow.__new__(MainWindow)
        window._left_splitter = _detached_support_FakeSplitterForSidebarSizes()
        window._last_left_splitter_sizes = [220, 380]
        MainWindow.set_left_splitter_sizes(window, [600, 0])
        self.assertEqual(window._last_left_splitter_sizes, [220, 380])
        self.assertEqual(window._left_splitter.applied_sizes, [[600, 0]])

    def test_visible_left_splitter_size_replaces_last_good_layout(self):
        window = MainWindow.__new__(MainWindow)
        window._left_splitter = _detached_support_FakeSplitterForSidebarSizes()
        window._last_left_splitter_sizes = [220, 380]
        MainWindow.set_left_splitter_sizes(window, [260, 340])
        self.assertEqual(window._last_left_splitter_sizes, [260, 340])
        self.assertEqual(window._left_splitter.applied_sizes, [[260, 340]])

    def test_empty_or_zero_total_splitter_sizes_are_not_applied(self):
        window = MainWindow.__new__(MainWindow)
        window._left_splitter = _detached_support_FakeSplitterForSidebarSizes()
        window._takeoff_splitter = _detached_support_FakeSplitterForSidebarSizes()
        window._last_left_splitter_sizes = [220, 380]
        window._last_takeoff_splitter_sizes = [360, 1640]
        for sizes in ([], [0, 0], [-5, -7]):
            MainWindow.set_left_splitter_sizes(window, sizes)
            MainWindow.set_takeoff_splitter_sizes(window, sizes)
        self.assertEqual(window._left_splitter.applied_sizes, [])
        self.assertEqual(window._takeoff_splitter.applied_sizes, [])
        self.assertEqual(window._last_left_splitter_sizes, [220, 380])
        self.assertEqual(window._last_takeoff_splitter_sizes, [360, 1640])

    def test_hidden_takeoff_sidebar_size_does_not_replace_last_good_width(self):
        window = MainWindow.__new__(MainWindow)
        window._takeoff_splitter = _detached_support_FakeSplitterForSidebarSizes()
        window._last_takeoff_splitter_sizes = [360, 1640]
        MainWindow.set_takeoff_splitter_sizes(window, [0, 2000])
        self.assertEqual(window._takeoff_splitter.applied_sizes, [[0, 2000]])
        self.assertEqual(window._last_takeoff_splitter_sizes, [360, 1640])

    def test_restart_restore_applies_saved_sidebar_column_width_exactly(self):
        window = MainWindow.__new__(MainWindow)
        window._takeoff_splitter = _detached_support_FakeSplitterForSidebarSizes(
            [0, 0], width=2000
        )
        window._last_takeoff_splitter_sizes = []
        MainWindow.set_takeoff_splitter_sizes(window, [360, 1640])
        self.assertEqual(window._takeoff_splitter.applied_sizes, [[360, 1640]])
        self.assertEqual(window._last_takeoff_splitter_sizes, [360, 1640])

    def test_showing_hidden_layer_restores_saved_splitter_ratio(self):
        window = MainWindow.__new__(MainWindow)
        window._left_splitter = _detached_support_FakeSplitterForSidebarSizes(
            [898, 0], height=898
        )
        window._last_left_splitter_sizes = [651, 242]
        MainWindow._ensure_left_splitter_pane_visible(window, 1)
        self.assertEqual(window._left_splitter.applied_sizes, [[655, 243]])

    def test_showing_hidden_layer_without_saved_layout_splits_evenly(self):
        for hidden_index, sizes in ((1, [898, 0]), (0, [0, 898])):
            with self.subTest(hidden_index=hidden_index):
                window = MainWindow.__new__(MainWindow)
                window._left_splitter = _detached_support_FakeSplitterForSidebarSizes(
                    sizes, height=898
                )
                window._last_left_splitter_sizes = []
                MainWindow._ensure_left_splitter_pane_visible(window, hidden_index)
                self.assertEqual(window._left_splitter.applied_sizes, [[449, 449]])

    def test_showing_visible_layer_pane_does_not_resize(self):
        window = MainWindow.__new__(MainWindow)
        window._left_splitter = _detached_support_FakeSplitterForSidebarSizes(
            [500, 398], height=898
        )
        window._last_left_splitter_sizes = [651, 242]
        MainWindow._ensure_left_splitter_pane_visible(window, 1)
        self.assertEqual(window._left_splitter.applied_sizes, [])

    def test_showing_single_hidden_sidebar_keeps_visible_column_width(self):
        window = MainWindow.__new__(MainWindow)
        window._takeoff_splitter = _detached_support_FakeSplitterForSidebarSizes(
            [360, 1640], width=2000
        )
        window._last_takeoff_splitter_sizes = [360, 1640]
        MainWindow._ensure_sidebar_column_visible(window)
        self.assertEqual(window._takeoff_splitter.applied_sizes, [])
        self.assertEqual(window._last_takeoff_splitter_sizes, [360, 1640])

    def test_showing_hidden_sidebar_column_restores_exact_saved_width(self):
        window = MainWindow.__new__(MainWindow)
        window._takeoff_splitter = _detached_support_FakeSplitterForSidebarSizes(
            [0, 2000], width=2000
        )
        window._last_takeoff_splitter_sizes = [360, 1640]
        MainWindow._ensure_sidebar_column_visible(window)
        self.assertEqual(window._takeoff_splitter.applied_sizes, [[360, 1640]])
        self.assertEqual(window._last_takeoff_splitter_sizes, [360, 1640])

    def test_showing_hidden_sidebar_column_without_saved_width_uses_default(self):
        window = MainWindow.__new__(MainWindow)
        window._takeoff_splitter = _detached_support_FakeSplitterForSidebarSizes(
            [0, 2000], width=2000
        )
        window._last_takeoff_splitter_sizes = []
        MainWindow._ensure_sidebar_column_visible(window)
        self.assertEqual(window._takeoff_splitter.applied_sizes, [[500, 1500]])

    def test_repeated_hidden_sidebar_column_restore_keeps_exact_saved_width(self):
        window = MainWindow.__new__(MainWindow)
        window._takeoff_splitter = _detached_support_FakeSplitterForSidebarSizes(
            [0, 2000], width=2000
        )
        window._last_takeoff_splitter_sizes = [360, 1640]
        MainWindow._ensure_sidebar_column_visible(window)
        window._takeoff_splitter._sizes = [0, 2000]
        MainWindow._ensure_sidebar_column_visible(window)
        self.assertEqual(
            window._takeoff_splitter.applied_sizes,
            [[360, 1640], [360, 1640]],
        )

    def test_showing_pane_after_both_sidebars_hidden_restores_saved_column_width(self):
        window = MainWindow.__new__(MainWindow)
        window._takeoff_splitter = _detached_support_FakeSplitterForSidebarSizes(
            [0, 2000], width=2000
        )
        window._last_takeoff_splitter_sizes = [360, 1640]
        window._left_splitter = _detached_support_FakeSplitterForSidebarSizes(
            [898, 0], height=898
        )
        window._last_left_splitter_sizes = [651, 242]
        MainWindow._ensure_sidebar_pane_visible(window, 1)
        self.assertEqual(window._takeoff_splitter.applied_sizes, [[360, 1640]])
        self.assertEqual(window._left_splitter.applied_sizes, [[655, 243]])


class DetachedPageViewManagerLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        cls.app.processEvents()

    def test_named_view_timeout_callback_is_dropped_after_window_destruction(self):
        window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
        QtWidgets.QMainWindow.__init__(window)
        window._is_closing = False
        calls = []
        window._focus_on_named_view = lambda: calls.append("focus")
        window._reveal_named_view_blank_canvas = lambda: calls.append("reveal")
        delete(window)
        DetachedPageViewWindow._focus_named_view_timeout_fallback(window)
        self.assertEqual(calls, [])

    def test_named_view_timeout_callback_runs_only_for_a_live_open_window(self):
        for is_closing, expected in ((False, ["focus", "reveal"]), (True, [])):
            with self.subTest(is_closing=is_closing):
                window = DetachedPageViewWindow.__new__(DetachedPageViewWindow)
                QtWidgets.QMainWindow.__init__(window)
                self.addCleanup(window.deleteLater)
                window._is_closing = is_closing
                calls = []
                window._focus_on_named_view = lambda: calls.append("focus")
                window._reveal_named_view_blank_canvas = lambda: calls.append("reveal")
                DetachedPageViewWindow._focus_named_view_timeout_fallback(window)
                self.assertEqual(calls, expected)

    def test_projects_transition_cancels_an_inflight_detached_window_lifecycle(self):
        calls = []

        class FakeLifecycleManager:
            def __init__(self, name, active):
                self.name = name
                self.active = active

            def has_active_view_lifecycle(self):
                return self.active

            def is_view_open(self):
                return False

        window = MainWindow.__new__(MainWindow)
        window._view_window_manager = FakeLifecycleManager("view", False)
        window._annotation_view_manager = FakeLifecycleManager("annotation", True)
        window._apply_workspace_toolbar_visibility = lambda: None
        window._workspace_state_coordinator = SimpleNamespace(
            request_view_restore=lambda: calls.append("restore-view"),
            request_annotation_restore=lambda: calls.append("restore-annotation"),
            request_mesh_restore=lambda: calls.append("restore-mesh"),
            on_main_tab_changed=lambda: calls.append("tab-changed"),
        )
        window.set_view_window_visible = lambda visible: calls.append(
            ("view-visible", visible)
        )
        window.set_annotation_window_visible = lambda visible: calls.append(
            ("annotation-visible", visible)
        )
        window.get_mesh_window = lambda: None
        window.menu_controller = None
        MainWindow._on_tab_changed(window, TAB_INDEX_TAKEOFF - 1)
        self.assertEqual(
            calls,
            [
                "restore-annotation",
                ("annotation-visible", False),
                "tab-changed",
            ],
        )

    def _tab_change_window(self, calls, *, view_active, annotation_active, mesh=None):
        class FakeLifecycleManager:
            def __init__(self, active):
                self.active = active

            def has_active_view_lifecycle(self):
                return self.active

        window = MainWindow.__new__(MainWindow)
        window._view_window_manager = FakeLifecycleManager(view_active)
        window._annotation_view_manager = FakeLifecycleManager(annotation_active)
        window._apply_workspace_toolbar_visibility = lambda: None
        window._workspace_state_coordinator = SimpleNamespace(
            request_view_restore=lambda: calls.append("restore-view"),
            request_annotation_restore=lambda: calls.append("restore-annotation"),
            request_mesh_restore=lambda: calls.append("restore-mesh"),
            on_main_tab_changed=lambda: calls.append("tab-changed"),
        )
        window.set_view_window_visible = lambda visible: calls.append(
            ("view-visible", visible)
        )
        window.set_annotation_window_visible = lambda visible: calls.append(
            ("annotation-visible", visible)
        )
        window.set_mesh_window_visible = lambda visible: calls.append(
            ("mesh-visible", visible)
        )
        window.get_mesh_window = lambda: mesh
        window.menu_controller = None
        return window

    def test_leaving_takeoff_tab_closes_every_detached_window_in_order(self):
        calls = []
        window = self._tab_change_window(
            calls, view_active=True, annotation_active=True, mesh=object()
        )
        MainWindow._on_tab_changed(window, TAB_INDEX_PROJECTS)
        self.assertEqual(
            calls,
            [
                "restore-view",
                ("view-visible", False),
                "restore-annotation",
                ("annotation-visible", False),
                "restore-mesh",
                ("mesh-visible", False),
                "tab-changed",
            ],
        )

    def test_switching_to_takeoff_tab_keeps_detached_windows_open(self):
        calls = []
        window = self._tab_change_window(
            calls, view_active=True, annotation_active=True, mesh=object()
        )
        MainWindow._on_tab_changed(window, TAB_INDEX_TAKEOFF)
        self.assertEqual(calls, ["tab-changed"])

    def test_closing_annotation_cancels_inflight_dependent_view_lifecycle(self):
        calls = []
        window = MainWindow.__new__(MainWindow)
        window._annotation_window_action = _detached_support_FakeCheckAction()
        window._view_window_manager = SimpleNamespace(
            is_view_open=lambda: False,
            has_active_view_lifecycle=lambda: True,
        )
        window._annotation_view_manager = SimpleNamespace(
            close_view=lambda: calls.append("close-annotation")
        )
        window.set_view_window_visible = lambda visible: calls.append(
            ("view-visible", visible)
        )
        MainWindow.set_annotation_window_visible(window, False)
        self.assertEqual(
            calls,
            [("view-visible", False), "close-annotation"],
        )

    def test_closing_annotation_without_view_lifecycle_only_closes_annotation(self):
        calls = []
        window = MainWindow.__new__(MainWindow)
        window._annotation_window_action = _detached_support_FakeCheckAction()
        window._view_window_manager = SimpleNamespace(
            is_view_open=lambda: False,
            has_active_view_lifecycle=lambda: False,
        )
        window._annotation_view_manager = SimpleNamespace(
            close_view=lambda: calls.append("close-annotation")
        )
        window.set_view_window_visible = lambda visible: self.fail(
            "An idle view window must not be touched"
        )
        MainWindow.set_annotation_window_visible(window, False)
        self.assertEqual(calls, ["close-annotation"])
