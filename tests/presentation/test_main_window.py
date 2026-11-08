from __future__ import annotations
import ast
import gc
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
import json
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
from ost_visualizer.infrastructure.persistence.ai_takeoff_audit_log import (
    AiTakeoffAuditLog,
)
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


def _strict_service(expected_name, service):
    """get_service double that serves exactly one registered name."""

    def get_service(name):
        if name != expected_name:
            raise KeyError(name)
        return service

    return get_service


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
        # The worker body swallows exceptions, so a ``self.fail`` raised from the
        # emit hook would be logged and lost; record emissions and assert on them.
        emitted = []
        window = SimpleNamespace(
            emitted=emitted,
            _update_service=SimpleNamespace(check_for_updates=check_for_updates),
            _collaboration_shutdown_pending=False,
            _collaboration_shutdown_complete=False,
            _application_shutdown_finalized=False,
            _shutdown_deferred_callbacks={},
            update_dialog_requested=SimpleNamespace(
                emit=lambda info: emitted.append(info)
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
                with self.assertNoLogs(
                    "ost_visualizer.presentation.main_window", level="ERROR"
                ):
                    thread_factory.call_args.kwargs["target"]()
                self.assertEqual(window.emitted, [])

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
        window.app_controller = SimpleNamespace(
            get_service=_strict_service("sql_collaboration_coordinator", collaboration)
        )
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
        window.app_controller = SimpleNamespace(
            get_service=_strict_service("sql_collaboration_coordinator", collaboration)
        )
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
        window.app_controller = SimpleNamespace(
            get_service=_strict_service("sql_collaboration_coordinator", collaboration)
        )
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
        window.app_controller = SimpleNamespace(
            get_service=_strict_service("sql_collaboration_coordinator", collaboration)
        )
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
        window._ai_undo_notice = SimpleNamespace(
            cleanup=lambda: calls.append("ai_undo_notice_cleanup")
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
                "ai_undo_notice_cleanup",
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
        window._ai_undo_notice = SimpleNamespace(
            cleanup=lambda: calls.append("ai_undo_notice_cleanup")
        )
        window._ai_pdf_source = SimpleNamespace(
            release=lambda: calls.append("ai_pdf_release")
        )
        window.app_controller = SimpleNamespace(
            get_service=_strict_service("lifecycle_orchestrator", lifecycle)
        )
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
                "ai_undo_notice_cleanup",
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
        window._shutdown_deferred_callbacks = {"late": lambda: None}
        window._shutdown_hidden_windows = (object(),)
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
        window._ai_undo_notice = SimpleNamespace(
            cleanup=cleanup("ai_undo_notice_cleanup")
        )
        window._ai_pdf_source = SimpleNamespace(release=cleanup("ai_pdf_release"))
        window.app_controller = SimpleNamespace(
            get_service=_strict_service("lifecycle_orchestrator", lifecycle)
        )
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
                any(
                    f"Failed to {description} during application shutdown" in line
                    for line in captured.output
                ),
                description,
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
                "ai_undo_notice_cleanup",
                "ai_pdf_release",
                "lifecycle",
                "window_close",
                "qt_quit",
            ],
        )
        self.assertTrue(window._application_shutdown_finalized)
        self.assertEqual(window._shutdown_deferred_callbacks, {})
        self.assertEqual(window._shutdown_hidden_windows, ())

    def test_every_failing_shutdown_step_is_logged_with_its_exact_description(self):
        names = (
            ("deferred_persistence", "clean up deferred persistence"),
            ("workspace_flush", "flush workspace state"),
            ("workspace_cleanup", "clean up workspace state"),
            ("event_cleanup", "clean up event coordinator"),
            ("ui_cleanup", "clean up UI event coordinator"),
            ("license_cleanup", "clean up license coordinator"),
            ("access_cleanup", "clean up UI access manager"),
            ("mcp_cleanup", "clean up MCP context bridge"),
            ("takeoff_cleanup", "clean up AI takeoff bridge"),
            ("ai_review_cleanup", "clean up AI changeset review"),
            ("ai_rebind_cleanup", "clean up AI sidecar prompt"),
            ("ai_undo_notice_cleanup", "clean up AI undo notice"),
            ("ai_pdf_release", "release AI takeoff PDF files"),
            ("lifecycle", "shut down application lifecycle services"),
        )

        def failing(name):
            def run():
                raise RuntimeError(f"{name} failed")

            return run

        window = MainWindow.__new__(MainWindow)
        window._application_shutdown_finalized = False
        window._collaboration_shutdown_pending = False
        window._collaboration_shutdown_complete = True
        window._collaboration_shutdown_failed = False
        window._shutdown_deferred_callbacks = {}
        window._shutdown_hidden_windows = ()
        window._deferred_persistence_manager = SimpleNamespace(
            cleanup=failing("deferred_persistence")
        )
        window._workspace_state_coordinator = SimpleNamespace(
            flush=failing("workspace_flush"), cleanup=failing("workspace_cleanup")
        )
        window.event_coordinator = SimpleNamespace(cleanup=failing("event_cleanup"))
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(cleanup=failing("ui_cleanup")),
            file_ops=SimpleNamespace(
                maintenance_pending=False, sql_creation_pending=False
            ),
        )
        window.license_coordinator = SimpleNamespace(cleanup=failing("license_cleanup"))
        window.ui_access_manager = SimpleNamespace(cleanup=failing("access_cleanup"))
        window._mcp_context_bridge = SimpleNamespace(cleanup=failing("mcp_cleanup"))
        window._ai_takeoff_bridge = SimpleNamespace(cleanup=failing("takeoff_cleanup"))
        window._ai_approval = SimpleNamespace(cleanup=failing("ai_review_cleanup"))
        window._ai_rebind_prompt = SimpleNamespace(cleanup=failing("ai_rebind_cleanup"))
        window._ai_undo_notice = SimpleNamespace(
            cleanup=failing("ai_undo_notice_cleanup")
        )
        window._ai_pdf_source = SimpleNamespace(release=failing("ai_pdf_release"))
        window.app_controller = SimpleNamespace(
            get_service=_strict_service(
                "lifecycle_orchestrator", SimpleNamespace(shutdown=failing("lifecycle"))
            )
        )
        with self.assertLogs(
            "ost_visualizer.presentation.main_window", level="ERROR"
        ) as captured, patch.object(MainWindow.__mro__[1], "closeEvent"), patch.object(
            QtCore.QCoreApplication, "quit"
        ):
            MainWindow.closeEvent(window, FakeCloseEvent())
        self.assertEqual(
            [record.getMessage() for record in captured.records],
            [
                f"Failed to {description} during application shutdown"
                for _name, description in names
            ],
        )

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
        window.app_controller = SimpleNamespace(
            get_service=_strict_service("sql_collaboration_coordinator", collaboration)
        )
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


class MainWindowShutdownSequenceTests(unittest.TestCase):
    """The order in which a closing window flushes, drains, aborts or finishes."""

    def host(
        self,
        *,
        flush_result=True,
        state=None,
        pending=True,
        complete=False,
        failed=False,
    ):
        events = []
        manager = SimpleNamespace(
            begin_shutdown=lambda: events.append("begin_shutdown"),
            prepare_shutdown=lambda: events.append("prepare_shutdown") or flush_result,
            abort_shutdown=lambda: events.append("abort_shutdown"),
        )
        collaboration = SimpleNamespace(
            shutdown_state=state,
            drain_all_mutations_async=lambda callback: events.append(
                ("drain", callback)
            ),
            request_shutdown=lambda callback: events.append(
                ("request_shutdown", callback)
            ),
        )
        host = SimpleNamespace(
            events=events,
            collaboration=collaboration,
            _collaboration_shutdown_pending=pending,
            _collaboration_shutdown_complete=complete,
            _collaboration_shutdown_failed=failed,
            _deferred_persistence_manager=manager,
            handlers=SimpleNamespace(
                ui_event=SimpleNamespace(
                    capture_current_page_state_for_shutdown=lambda: events.append(
                        "capture"
                    )
                )
            ),
            app_controller=SimpleNamespace(
                get_service=_strict_service(
                    "sql_collaboration_coordinator", collaboration
                )
            ),
            show=lambda: events.append("show"),
            close=lambda: events.append("close"),
            _resume_shutdown_deferred_callbacks=lambda: events.append("resume"),
            _discard_shutdown_deferred_callbacks=lambda: events.append("discard"),
            _flush_deferred_persistence_before_close=lambda: MainWindow._flush_deferred_persistence_before_close(
                host
            ),
            _on_shutdown_mutation_drain_complete=lambda *args: None,
            _on_collaboration_shutdown_complete=lambda *args: events.append(
                ("complete", args)
            ),
        )
        return host

    def test_shutdown_state_is_flushed_in_order_before_it_is_prepared(self):
        host = self.host(flush_result=1)
        self.assertIs(MainWindow._flush_deferred_persistence_before_close(host), True)
        self.assertEqual(host.events, ["capture", "begin_shutdown", "prepare_shutdown"])
        failing = self.host(flush_result=0)
        self.assertIs(
            MainWindow._flush_deferred_persistence_before_close(failing), False
        )

    def test_beginning_shutdown_only_acts_while_one_is_pending_and_unfinished(self):
        for options in (
            {"pending": False},
            {"complete": True},
            {"failed": True},
            {"pending": False, "complete": True},
        ):
            with self.subTest(options=options):
                host = self.host(**options)
                MainWindow._begin_application_shutdown(host)
                self.assertEqual(host.events, [])

    def test_a_failed_flush_restores_the_window_and_the_deferred_callbacks(self):
        host = self.host(flush_result=False)
        MainWindow._begin_application_shutdown(host)
        self.assertFalse(host._collaboration_shutdown_pending)
        self.assertEqual(
            host.events,
            [
                "capture",
                "begin_shutdown",
                "prepare_shutdown",
                "abort_shutdown",
                "show",
                "resume",
            ],
        )

    def test_a_flushed_window_hands_its_pending_mutations_to_the_collaboration_drain(
        self,
    ):
        host = self.host(flush_result=True)
        MainWindow._begin_application_shutdown(host)
        self.assertTrue(host._collaboration_shutdown_pending)
        self.assertEqual(
            host.events,
            [
                "capture",
                "begin_shutdown",
                "prepare_shutdown",
                ("drain", host._on_shutdown_mutation_drain_complete),
            ],
        )

    def test_a_drain_result_is_ignored_unless_a_shutdown_is_pending(self):
        host = self.host(pending=False)
        MainWindow._on_shutdown_mutation_drain_complete(host, False, "late")
        MainWindow._on_shutdown_mutation_drain_complete(host, True, "")
        self.assertEqual(host.events, [])

    def test_a_failed_drain_aborts_shows_the_message_and_resumes(self):
        for message, shown in (
            ("disk full", "disk full"),
            ("", "A critical database setting could not be saved before shutdown."),
        ):
            with self.subTest(message=message):
                host = self.host()
                with patch(
                    "ost_visualizer.presentation.main_window.show_critical",
                    side_effect=lambda *args: host.events.append(("critical", args)),
                ):
                    MainWindow._on_shutdown_mutation_drain_complete(
                        host, False, message
                    )
                self.assertFalse(host._collaboration_shutdown_pending)
                self.assertEqual(
                    host.events,
                    [
                        "abort_shutdown",
                        "show",
                        ("critical", (host, "Shutdown Incomplete", shown)),
                        "resume",
                    ],
                )

    def test_a_successful_drain_requests_the_collaboration_shutdown_unless_it_is_closed(
        self,
    ):
        from ost_visualizer.application.dtos.collaboration_dtos import (
            CollaborationShutdownState,
        )

        host = self.host(state=CollaborationShutdownState.CLOSED)
        MainWindow._on_shutdown_mutation_drain_complete(host, True, "")
        self.assertEqual(host.events, [("complete", (True, ""))])
        host = self.host(state=None)
        MainWindow._on_shutdown_mutation_drain_complete(host, True, "")
        self.assertEqual(
            host.events,
            [("request_shutdown", host._on_collaboration_shutdown_complete)],
        )

    def test_a_failed_collaboration_shutdown_is_final_and_reopens_the_window(self):
        for message, shown in (
            ("busy", "busy"),
            ("", "SQL collaboration resources could not be closed safely."),
        ):
            with self.subTest(message=message):
                host = self.host()
                with patch(
                    "ost_visualizer.presentation.main_window.show_critical",
                    side_effect=lambda *args: host.events.append(("critical", args)),
                ):
                    MainWindow._on_collaboration_shutdown_complete(host, False, message)
                self.assertFalse(host._collaboration_shutdown_pending)
                self.assertTrue(host._collaboration_shutdown_failed)
                self.assertFalse(host._collaboration_shutdown_complete)
                self.assertEqual(
                    host.events,
                    [
                        "abort_shutdown",
                        "show",
                        ("critical", (host, "Shutdown Incomplete", shown)),
                        "resume",
                    ],
                )

    def test_a_finished_collaboration_shutdown_drops_deferred_work_and_closes_the_window(
        self,
    ):
        host = self.host()
        scheduled = []
        with patch.object(
            QtCore.QTimer,
            "singleShot",
            side_effect=lambda *args: scheduled.append(args),
        ):
            MainWindow._on_collaboration_shutdown_complete(host, True, "")
        self.assertFalse(host._collaboration_shutdown_pending)
        self.assertTrue(host._collaboration_shutdown_complete)
        self.assertFalse(host._collaboration_shutdown_failed)
        self.assertEqual(host.events, ["discard"])
        self.assertEqual(scheduled, [(0, host.close)])

    def test_the_first_close_hides_the_window_and_schedules_the_shutdown_immediately(
        self,
    ):
        events = []
        window = MainWindow.__new__(MainWindow)
        window.handlers = SimpleNamespace(
            file_ops=SimpleNamespace(
                maintenance_pending=False, sql_creation_pending=False
            )
        )
        window._application_shutdown_finalized = False
        window._collaboration_shutdown_pending = False
        window._collaboration_shutdown_complete = False
        window._collaboration_shutdown_failed = False
        window._detached_plan_windows = lambda: ()
        window.get_mesh_window = lambda: None
        window._begin_application_shutdown = lambda: None
        window.hide = lambda: events.append("hide")
        event = FakeCloseEvent()
        scheduled = []
        with patch.object(
            QtCore.QTimer,
            "singleShot",
            side_effect=lambda *args: scheduled.append(args),
        ):
            MainWindow.closeEvent(window, event)
        self.assertEqual(events, ["hide"])
        self.assertTrue(window._collaboration_shutdown_pending)
        self.assertEqual(scheduled, [(0, window._begin_application_shutdown)])
        self.assertFalse(event.accepted)


class MainWindowSplitterBoundaryTests(unittest.TestCase):
    @staticmethod
    def window(**splitters):
        window = MainWindow.__new__(MainWindow)
        for name, splitter in splitters.items():
            setattr(window, name, splitter)
        return window

    @staticmethod
    def splitter(sizes, **options):
        return _detached_support_FakeSplitterForSidebarSizes(sizes, **options)

    def test_saved_left_sizes_are_usable_only_with_two_positive_panes(self):
        valid = MainWindow._has_valid_left_splitter_sizes
        self.assertTrue(valid([1, 1]))
        self.assertTrue(valid([300, 200, 0]))
        for sizes in ([], [5], [0, 5], [5, 0], [-1, 5], [5, -1], [0, 0]):
            with self.subTest(sizes=sizes):
                self.assertFalse(valid(sizes))

    def test_saved_left_sizes_scale_to_the_current_total_keeping_both_panes_visible(
        self,
    ):
        scale = MainWindow._scale_left_splitter_sizes
        self.assertEqual(scale([100, 300], 400), [100, 300])
        self.assertEqual(scale([100, 300], 800), [200, 600])
        self.assertEqual(scale([1, 2], 10), [3, 7])
        self.assertEqual(scale([1, 1000], 10), [1, 9])
        self.assertEqual(scale([1000, 1], 10), [9, 1])
        self.assertEqual(scale([1, 1], 1), [1, 1])
        self.assertEqual(scale([1, 1], 0), [1, 1])
        self.assertEqual(scale([3, 1], 2.9), [1, 1])

    def test_a_one_pixel_sidebar_column_counts_as_visible(self):
        window = self.window(_takeoff_splitter=self.splitter([1, 1999], width=2000))
        window._last_takeoff_splitter_sizes = [360, 1640]
        MainWindow._ensure_sidebar_column_visible(window)
        self.assertEqual(window._takeoff_splitter.applied_sizes, [])

    def test_the_restored_sidebar_width_never_exceeds_the_splitter(self):
        window = self.window(_takeoff_splitter=self.splitter([0, 2000], width=2000))
        window._last_takeoff_splitter_sizes = [5000, 1]
        MainWindow._ensure_sidebar_column_visible(window)
        self.assertEqual(window._takeoff_splitter.applied_sizes, [[1999, 1]])

    def test_a_missing_saved_width_restores_a_quarter_but_at_least_the_minimum_width(
        self,
    ):
        wide = self.window(_takeoff_splitter=self.splitter([0, 4000], width=4000))
        wide._last_takeoff_splitter_sizes = []
        MainWindow._ensure_sidebar_column_visible(wide)
        self.assertEqual(wide._takeoff_splitter.applied_sizes, [[1000, 3000]])
        narrow = self.window(_takeoff_splitter=self.splitter([0, 1000], width=1000))
        narrow._last_takeoff_splitter_sizes = [0, 1000]
        MainWindow._ensure_sidebar_column_visible(narrow)
        self.assertEqual(narrow._takeoff_splitter.applied_sizes, [[320, 680]])

    def test_the_sidebar_total_is_the_larger_of_the_pane_sizes_and_the_splitter_width(
        self,
    ):
        window = self.window(_takeoff_splitter=self.splitter([0, 3000], width=1000))
        window._last_takeoff_splitter_sizes = []
        MainWindow._ensure_sidebar_column_visible(window)
        self.assertEqual(window._takeoff_splitter.applied_sizes, [[750, 2250]])
        tiny = self.window(_takeoff_splitter=self.splitter([0, 0], width=0))
        tiny._last_takeoff_splitter_sizes = []
        MainWindow._ensure_sidebar_column_visible(tiny)
        self.assertEqual(tiny._takeoff_splitter.applied_sizes, [[1, 1]])

    def test_a_hidden_left_pane_comes_back_at_half_the_height_when_nothing_was_saved(
        self,
    ):
        for index in (0, 1):
            with self.subTest(index=index):
                sizes = [0, 898] if index == 0 else [898, 0]
                window = self.window(_left_splitter=self.splitter(sizes, height=898))
                window._last_left_splitter_sizes = []
                MainWindow._ensure_left_splitter_pane_visible(window, index)
                self.assertEqual(window._left_splitter.applied_sizes, [[449, 449]])
        window = self.window(_left_splitter=self.splitter([1, 897], height=898))
        window._last_left_splitter_sizes = []
        MainWindow._ensure_left_splitter_pane_visible(window, 0)
        self.assertEqual(window._left_splitter.applied_sizes, [])
        tiny = self.window(_left_splitter=self.splitter([0, 0], height=0))
        tiny._last_left_splitter_sizes = []
        MainWindow._ensure_left_splitter_pane_visible(tiny, 0)
        self.assertEqual(tiny._left_splitter.applied_sizes, [[1, 1]])

    def test_a_hidden_left_pane_uses_the_saved_proportions_when_they_are_usable(self):
        window = self.window(_left_splitter=self.splitter([0, 800], height=800))
        window._last_left_splitter_sizes = [100, 300]
        MainWindow._ensure_left_splitter_pane_visible(window, 0)
        self.assertEqual(window._left_splitter.applied_sizes, [[200, 600]])
        window = self.window(_left_splitter=self.splitter([0, 800], height=800))
        window._last_left_splitter_sizes = [0, 300]
        MainWindow._ensure_left_splitter_pane_visible(window, 0)
        self.assertEqual(window._left_splitter.applied_sizes, [[400, 400]])


class MainWindowTakeoffPageNavigationTests(unittest.TestCase):
    def window(
        self, order, active, *, add_allowed=False, tab_active=False, add_result=True
    ):
        calls = []
        sidebar = SimpleNamespace(
            get_page_order=lambda: list(order),
            get_active_page_uid=lambda: active,
            go_next=lambda: calls.append("go_next"),
        )
        window = SimpleNamespace(
            takeoff_sidebar=sidebar,
            calls=calls,
            can_add_page_from_takeoff_tab=lambda: add_allowed,
            is_takeoff_tab_active=lambda: tab_active,
            handlers=SimpleNamespace(
                cover_sheet=SimpleNamespace(
                    add_blank_page_from_takeoff_tab=lambda: calls.append("add")
                    or add_result
                ),
                ui_event=SimpleNamespace(
                    navigate_to_takeoff_page=lambda uid: calls.append(("navigate", uid))
                ),
            ),
        )
        window._can_go_takeoff_page = lambda direction: MainWindow._can_go_takeoff_page(
            window, direction
        )
        window._is_on_last_takeoff_page = lambda: MainWindow._is_on_last_takeoff_page(
            window
        )
        window.can_go_next_takeoff_page = lambda: MainWindow.can_go_next_takeoff_page(
            window
        )
        return window

    def test_paging_is_possible_only_inside_the_page_order(self):
        order = ["a", "b", "c"]
        for active, previous, following in (
            ("a", False, True),
            ("b", True, True),
            ("c", True, False),
            ("missing", False, False),
            (None, False, False),
        ):
            with self.subTest(active=active):
                window = self.window(order, active)
                self.assertIs(MainWindow._can_go_takeoff_page(window, -1), previous)
                self.assertIs(MainWindow._can_go_takeoff_page(window, 1), following)
                self.assertIs(MainWindow.can_go_previous_takeoff_page(window), previous)
        self.assertFalse(MainWindow._can_go_takeoff_page(self.window([], "a"), 1))
        self.assertFalse(MainWindow._can_go_takeoff_page(self.window(["a"], "a"), -1))
        self.assertFalse(MainWindow._can_go_takeoff_page(self.window(["a"], "a"), 1))

    def test_only_the_last_page_of_a_non_empty_order_is_last(self):
        last = MainWindow._is_on_last_takeoff_page
        self.assertIs(last(self.window(["a", "b"], "b")), True)
        self.assertIs(last(self.window(["a", "b"], "a")), False)
        self.assertIs(last(self.window(["a", "b"], "x")), False)
        self.assertIs(last(self.window([], "a")), False)
        self.assertIs(last(self.window(["a"], "a")), True)

    def test_next_on_the_last_page_needs_permission_and_the_takeoff_tab(self):
        cases = (
            (True, True, True),
            (True, False, False),
            (False, True, False),
            (False, False, False),
        )
        for add_allowed, tab_active, expected in cases:
            with self.subTest(add_allowed=add_allowed, tab_active=tab_active):
                window = self.window(
                    ["a", "b"], "b", add_allowed=add_allowed, tab_active=tab_active
                )
                self.assertIs(MainWindow.can_go_next_takeoff_page(window), expected)
        window = self.window(["a", "b"], "a")
        self.assertIs(MainWindow.can_go_next_takeoff_page(window), True)
        window = self.window(["a", "b"], "x", add_allowed=True, tab_active=True)
        self.assertIs(MainWindow.can_go_next_takeoff_page(window), False)

    def test_going_next_moves_on_adds_a_page_at_the_end_or_does_nothing(self):
        window = self.window(["a", "b"], "a")
        MainWindow.go_next_takeoff_page(window)
        self.assertEqual(window.calls, ["go_next"])
        window = self.window(["a", "b"], "b")
        MainWindow.go_next_takeoff_page(window)
        self.assertEqual(window.calls, [])
        window = self.window(["a", "b"], "b", add_allowed=True, tab_active=True)
        order = ["a", "b"]
        window.takeoff_sidebar.get_page_order = lambda: list(order)
        window.handlers.cover_sheet.add_blank_page_from_takeoff_tab = lambda: (
            window.calls.append("add") or order.append("c") or True
        )
        MainWindow.go_next_takeoff_page(window)
        self.assertEqual(window.calls, ["add", ("navigate", "c")])
        window = self.window(
            ["a", "b"], "b", add_allowed=True, tab_active=True, add_result=False
        )
        MainWindow.go_next_takeoff_page(window)
        self.assertEqual(window.calls, ["add"])


class MainWindowImportProgressLabelTests(unittest.TestCase):
    def test_the_progress_label_names_a_single_file_or_counts_several(self):
        def args(*paths):
            return SimpleNamespace(files=[SimpleNamespace(path=path) for path in paths])

        label = MainWindow._project_file_import_progress_label
        self.assertEqual(label(args("C:/bids/a.ost")), "C:/bids/a.ost")
        self.assertEqual(label(args("a.ost", "b.ost")), "2 project files")
        self.assertEqual(label(args("a", "b", "c")), "3 project files")


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
                # A dialog destroyed with its parent can still report Accepted;
                # only the validity guard keeps that from creating a database.
                return QtWidgets.QDialog.DialogCode.Accepted

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


class MainWindowAiTakeoffTests(unittest.TestCase):
    def ai_window(self, enabled=True, allowed=()):
        window = MainWindow.__new__(MainWindow)
        window._config_model = SimpleNamespace(
            snapshot=lambda: SimpleNamespace(ai_takeoff_enabled=enabled)
        )
        granted = set(allowed)
        window.ui_access_manager = SimpleNamespace(
            is_allowed=lambda feature: feature in granted
        )
        return window

    def audited_window(self, bid_key=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.audit_dir = Path(directory.name) / "audit"
        window = MainWindow.__new__(MainWindow)
        window._ai_audit_log = AiTakeoffAuditLog(
            self.audit_dir, secure_directory=lambda _path: None
        )
        window._ai_sidecars = SimpleNamespace(bid_key=lambda: bid_key)
        return window

    def audit_entries(self, name="unkeyed"):
        path = self.audit_dir / f"{name}.jsonl"
        return [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        ]

    def test_ai_takeoff_access_needs_the_toggle_and_the_feature(self):
        cases = (
            (True, (Feature.AI_TAKEOFF,), True),
            (False, (Feature.AI_TAKEOFF,), False),
            (True, (), False),
            (False, (), False),
        )
        for enabled, allowed, expected in cases:
            with self.subTest(enabled=enabled, allowed=allowed):
                window = self.ai_window(enabled, allowed)
                self.assertIs(window._ai_takeoff_access_allowed(), expected)

    def test_ai_write_denial_follows_the_permission_matrix(self):
        everything = (
            Feature.AI_TAKEOFF,
            Feature.EDIT_PAGE_SETTINGS,
            Feature.PLACE_PLAN_ITEMS,
            Feature.EDIT_CONDITION_STRUCTURE,
        )
        refused = "You cannot make this change in the open bid."
        cases = (
            ("scale", everything, ""),
            ("scale", (Feature.AI_TAKEOFF, Feature.EDIT_PAGE_SETTINGS), ""),
            (
                "scale",
                (
                    Feature.AI_TAKEOFF,
                    Feature.PLACE_PLAN_ITEMS,
                    Feature.EDIT_CONDITION_STRUCTURE,
                ),
                refused,
            ),
            ("elements", everything, ""),
            (
                "elements",
                (
                    Feature.AI_TAKEOFF,
                    Feature.PLACE_PLAN_ITEMS,
                    Feature.EDIT_CONDITION_STRUCTURE,
                ),
                "",
            ),
            ("elements", (Feature.AI_TAKEOFF, Feature.PLACE_PLAN_ITEMS), refused),
            (
                "elements",
                (Feature.AI_TAKEOFF, Feature.EDIT_CONDITION_STRUCTURE),
                refused,
            ),
            ("elements", (Feature.AI_TAKEOFF, Feature.EDIT_PAGE_SETTINGS), refused),
        )
        for kind, allowed, expected in cases:
            with self.subTest(kind=kind, allowed=allowed):
                window = self.ai_window(True, allowed)
                self.assertEqual(
                    window._ai_takeoff_write_denial(SimpleNamespace(kind=kind)),
                    expected,
                )

    def test_ai_write_denial_puts_the_toggle_first(self):
        for enabled, allowed in ((False, (Feature.EDIT_PAGE_SETTINGS,)), (True, ())):
            with self.subTest(enabled=enabled):
                window = self.ai_window(enabled, allowed)
                self.assertEqual(
                    window._ai_takeoff_write_denial(SimpleNamespace(kind="scale")),
                    "AI takeoff is turned off or unavailable for the open bid. Turn "
                    "it on in Tools > Options > MCP Setup.",
                )

    def test_ai_takeoffs_go_to_the_selected_layer_then_default_then_none(self):
        layers = [
            SimpleNamespace(uid="L1", name="Walls"),
            SimpleNamespace(uid="L2", name="Default"),
            SimpleNamespace(uid="L3", name="Default"),
        ]
        cases = (("L9", layers, "L9"), (None, layers, "L2"), ("", layers, "L2"))
        cases += ((None, layers[:1], None), (None, [], None))
        for selected, snapshot, expected in cases:
            with self.subTest(selected=selected, layers=len(snapshot)):
                window = MainWindow.__new__(MainWindow)
                window._bid_layers_sidebar = SimpleNamespace(
                    selected_layer_uid=lambda selected=selected: selected
                )
                window._project_data_service = SimpleNamespace(
                    get_bid_layer_snapshot=lambda snapshot=snapshot: snapshot
                )
                self.assertIs(window._ai_takeoff_layer_uid(), expected)

    def test_ai_takeoffs_use_the_page_area_or_unassigned(self):
        from ost_visualizer.domain.entities.area import UNASSIGNED_AREA_UID

        window = MainWindow.__new__(MainWindow)
        window._project_data_service = SimpleNamespace(
            get_page_area_selections=lambda: {"p1": "A1", "p2": ""}
        )
        self.assertEqual(window._ai_takeoff_area_uid("p1"), "A1")
        self.assertEqual(window._ai_takeoff_area_uid("p2"), UNASSIGNED_AREA_UID)
        self.assertEqual(window._ai_takeoff_area_uid("p3"), UNASSIGNED_AREA_UID)

    def test_ai_tool_calls_are_audited_with_hashed_arguments(self):
        from ost_visualizer.application.dtos.ai_takeoff_audit_dtos import (
            hash_arguments,
        )

        window = self.audited_window()
        window._record_ai_tool("apply_changeset", {"changeset_id": "c1"}, "ok")
        window._record_ai_tool("list_sheets", {"limit": 5}, "invalid_argument")
        first, second = self.audit_entries()
        self.assertEqual(
            (first["event"], first["tool"], first["changeset_id"], first["outcome"]),
            ("tool", "apply_changeset", "c1", "ok"),
        )
        self.assertEqual(first["input_hash"], hash_arguments({"changeset_id": "c1"}))
        self.assertEqual(first["approver"], "")
        self.assertEqual(
            (second["tool"], second["changeset_id"], second["outcome"]),
            ("list_sheets", "", "invalid_argument"),
        )
        self.assertEqual(second["input_hash"], hash_arguments({"limit": 5}))

    def test_ai_events_name_the_approver_only_for_applied_and_undone(self):
        import getpass

        window = self.audited_window()
        for event in ("applied", "undone", "proposed", "discarded"):
            window._record_ai_event(event, {"changeset_id": f"c-{event}"})
        window._record_ai_event("expired", {})
        entries = self.audit_entries()
        self.assertEqual(
            [
                (entry["event"], entry["changeset_id"], entry["approver"])
                for entry in entries
            ],
            [
                ("applied", "c-applied", getpass.getuser()),
                ("undone", "c-undone", getpass.getuser()),
                ("proposed", "c-proposed", ""),
                ("discarded", "c-discarded", ""),
                ("expired", "", ""),
            ],
        )
        self.assertEqual(
            [entry["outcome"] for entry in entries],
            ["applied", "undone", "proposed", "discarded", "expired"],
        )

    def test_ai_review_decisions_are_audited_with_the_approver(self):
        import getpass

        key = "0123456789abcdef0123456789abcdef"
        window = self.audited_window(bid_key=key)
        window._on_ai_changeset_finished("c7", "rejected")
        self.assertEqual(
            [
                (
                    entry["event"],
                    entry["changeset_id"],
                    entry["approver"],
                    entry["outcome"],
                )
                for entry in self.audit_entries(key)
            ],
            [("decision", "c7", getpass.getuser(), "rejected")],
        )

    def test_an_unwritable_ai_audit_is_logged_and_swallowed(self):
        window = self.audited_window(bid_key="not-a-key")
        with self.assertLogs(main_window_module.logger, logging.WARNING) as captured:
            window._on_ai_changeset_finished("c7", "rejected")
            window._record_ai_tool("list_sheets", {}, "ok")
            window._record_ai_event("applied", {"changeset_id": "c7"})
        self.assertEqual(
            captured.output,
            [
                "WARNING:ost_visualizer.presentation.main_window:"
                "AI takeoff audit entry not written: ValueError"
            ]
            * 3,
        )
        self.assertFalse(self.audit_dir.exists())


# ---------------------------------------------------------------------------
# Second-pass (A3) additions: negative paths and state transitions that a full
# in-memory mutation sweep of main_window.py showed no earlier test observed.
# ---------------------------------------------------------------------------
from PySide6.QtGui import QAction as _A3QAction
from shiboken6 import delete as _a3_delete, isValid as _a3_is_valid
from ost_visualizer.application.dtos.file_import_args import (
    RejectedProjectFileArg as _A3Rejected,
)
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo as _A3HierarchyBidInfo,
    HierarchyData as _A3HierarchyData,
    HierarchyFileEntry as _A3HierarchyFileEntry,
)
from ost_visualizer.domain.entities.project_constants import (
    DELETED_BIDS_PROJECT_UID as _A3_DELETED_UID,
)
from ost_visualizer.presentation.config import (
    PAN_SIDEBAR_DEFAULT_HEIGHT as _A3_PAN_DEFAULT_HEIGHT,
    SIDEBAR_MIN_WIDTH as _A3_SIDEBAR_MIN_WIDTH,
)
from ost_visualizer.presentation.services.bid_clipboard_service import (
    BidClipboardService as _A3BidClipboardService,
)
from ost_visualizer.domain.entities.workspace_state import (
    WORKSPACE_ACTIVE_VIEW_2D,
    WORKSPACE_ACTIVE_VIEW_3D,
)
from ost_visualizer.presentation.config import (
    MAIN_TOOLBAR_LABEL,
    OVERLAY_TOOLS_TOOLBAR_LABEL,
    PLAN_TOOLS_TOOLBAR_LABEL,
    SHOW_TOOLBARS_MENU_TITLE,
    VIEW_TOOLBAR_LABEL,
)


class _A3Access:
    """UiAccessManager double: every query is recorded and answers are explicit."""

    def __init__(
        self, allowed=(), *, delete_bids=True, delete_projects=True, clipboard=True
    ):
        self.allowed = set(allowed)
        self.delete_bids = delete_bids
        self.delete_projects = delete_projects
        self.clipboard = clipboard
        self.calls = []

    def is_allowed(self, feature):
        self.calls.append(("allowed", feature))
        return feature in self.allowed

    def can_delete_bids(self, bid_refs):
        self.calls.append(("delete_bids", list(bid_refs)))
        return self.delete_bids

    def can_delete_projects(self, file_path, project_uids):
        self.calls.append(("delete_projects", file_path, list(project_uids)))
        return self.delete_projects

    def is_project_bid_clipboard_allowed(self, feature, file_path, refs, target):
        self.calls.append(("clipboard", feature, file_path, list(refs), target))
        return self.clipboard


class MainWindowA3EditCommandTests(unittest.TestCase):
    """Copy / cut / paste / delete / duplicate / select-all routing per tab."""

    A = BidRef("C:/jobs/a.mdb", "b1")
    B = BidRef("C:/jobs/a.mdb", "b2")
    OTHER = BidRef("C:/jobs/other.mdb", "b3")

    def _window(self, tab=TAB_INDEX_PROJECTS, *, access=None, inline=None):
        window = MainWindow.__new__(MainWindow)
        log = []
        window.log = log
        window.tab_widget = SimpleNamespace(currentIndex=lambda: tab)
        window.ui_access_manager = access or _A3Access()
        window._bid_clipboard = _A3BidClipboardService()
        window.ui_state_manager = SimpleNamespace(
            get_selected_bid_refs=lambda: [self.A, self.B],
            selected_project_uids=[],
            selected_project_file_path=None,
        )

        def record(name):
            return lambda *args, **kwargs: log.append((name, args, kwargs))

        window.plan_view = SimpleNamespace(
            copy_selected=record("plan.copy"),
            paste_clipboard=record("plan.paste"),
            delete_selected=record("plan.delete"),
            duplicate_selected=record("plan.duplicate"),
            select_all=record("plan.select_all"),
            is_text_annotation_inline_edit_active=lambda: inline is not None,
            handle_inline_text_shortcut=lambda key: (
                log.append(("inline", (key,), {})) or bool(inline)
            ),
        )
        window._condition_summary_tab = SimpleNamespace(
            copy_current_row=record("summary.copy"),
            delete_current_row=record("summary.delete"),
        )
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(refresh_toolbar=record("toolbar")),
            delete=SimpleNamespace(
                delete_selected=record("tree.delete"),
                duplicate_selected=record("tree.duplicate"),
                paste_bids=record("tree.paste"),
            ),
        )
        window.project_view = SimpleNamespace(
            get_delete_replacement_selection_state=lambda: "replacement"
        )
        return window

    def test_copy_follows_the_tab_and_needs_the_matching_permission(self):
        window = self._window(TAB_INDEX_TAKEOFF, access=_A3Access())
        window._copy_selected()
        self.assertEqual(window.log, [])
        window = self._window(
            TAB_INDEX_TAKEOFF, access=_A3Access({Feature.SELECT_PLAN_ITEMS})
        )
        window._copy_selected()
        self.assertEqual([entry[0] for entry in window.log], ["plan.copy"])
        window = self._window(TAB_INDEX_SUMMARY)
        window._copy_selected()
        self.assertEqual([entry[0] for entry in window.log], ["summary.copy"])
        self.assertFalse(window._bid_clipboard.has_content())

    def test_project_tree_copy_stores_same_database_bids_and_refreshes_the_toolbar(
        self,
    ):
        window = self._window(access=_A3Access({Feature.COPY_BID}))
        window._copy_selected()
        self.assertEqual(window._bid_clipboard.bid_refs, [self.A, self.B])
        self.assertFalse(window._bid_clipboard.is_cut)
        self.assertEqual([entry[0] for entry in window.log], ["toolbar"])

    def test_project_tree_copy_is_refused_without_access_or_across_databases(self):
        denied = self._window(access=_A3Access())
        denied._copy_selected()
        self.assertFalse(denied._bid_clipboard.has_content())
        mixed = self._window(access=_A3Access({Feature.COPY_BID}))
        mixed.ui_state_manager.get_selected_bid_refs = lambda: [self.A, self.OTHER]
        mixed._copy_selected()
        empty = self._window(access=_A3Access({Feature.COPY_BID}))
        empty.ui_state_manager.get_selected_bid_refs = lambda: []
        empty._copy_selected()
        for window in (denied, mixed, empty):
            self.assertFalse(window._bid_clipboard.has_content())
            self.assertEqual(window.log, [])

    def test_copy_project_bids_obeys_the_same_rules_as_the_shortcut(self):
        window = self._window(access=_A3Access())
        window._copy_project_bids([self.A])
        self.assertFalse(window._bid_clipboard.has_content())
        window = self._window(access=_A3Access({Feature.COPY_BID}))
        window._copy_project_bids([self.A, self.OTHER])
        self.assertFalse(window._bid_clipboard.has_content())
        window._copy_project_bids([self.A])
        self.assertEqual(window._bid_clipboard.bid_refs, [self.A])
        self.assertEqual([entry[0] for entry in window.log], ["toolbar"])

    def test_cut_is_only_available_in_the_project_tree_with_delete_permission(self):
        for tab in (TAB_INDEX_TAKEOFF, TAB_INDEX_SUMMARY):
            window = self._window(tab)
            window._cut_selected()
            self.assertFalse(window._bid_clipboard.has_content())
            self.assertEqual(window.log, [])
        denied = self._window(access=_A3Access(delete_bids=False))
        denied._cut_selected()
        self.assertFalse(denied._bid_clipboard.has_content())
        mixed = self._window()
        mixed.ui_state_manager.get_selected_bid_refs = lambda: [self.A, self.OTHER]
        mixed._cut_selected()
        self.assertFalse(mixed._bid_clipboard.has_content())
        window = self._window()
        window._cut_selected()
        self.assertTrue(window._bid_clipboard.is_cut)
        self.assertEqual(window._bid_clipboard.bid_refs, [self.A, self.B])
        self.assertEqual([entry[0] for entry in window.log], ["toolbar"])

    def test_inline_text_editing_consumes_copy_cut_paste_and_delete(self):
        for action, method in (
            ("copy", "_copy_selected"),
            ("cut", "_cut_selected"),
            ("paste", "_paste_clipboard"),
            ("delete", "_delete_selected"),
        ):
            with self.subTest(action=action):
                window = self._window(
                    TAB_INDEX_TAKEOFF,
                    access=_A3Access(
                        {Feature.SELECT_PLAN_ITEMS, Feature.EDIT_PLAN_ITEMS}
                    ),
                    inline=True,
                )
                getattr(window, method)()
                self.assertEqual(window.log, [("inline", (action,), {})])
        window = self._window(
            TAB_INDEX_TAKEOFF,
            access=_A3Access({Feature.SELECT_PLAN_ITEMS}),
            inline=False,
        )
        window._copy_selected()
        self.assertEqual([entry[0] for entry in window.log], ["inline", "plan.copy"])

    def test_inline_shortcut_needs_the_takeoff_tab_a_plan_view_and_an_active_edit(self):
        window = self._window(TAB_INDEX_PROJECTS, inline=True)
        self.assertIs(window._handle_inline_text_shortcut("copy"), False)
        window = self._window(TAB_INDEX_TAKEOFF, inline=True)
        self.assertIs(window._handle_inline_text_shortcut("copy"), True)
        window.plan_view = None
        self.assertIs(window._handle_inline_text_shortcut("copy"), False)
        window = self._window(TAB_INDEX_TAKEOFF)
        self.assertIs(window._handle_inline_text_shortcut("copy"), False)
        self.assertEqual(window.log, [])

    def test_select_all_only_acts_on_the_takeoff_tab_with_selection_access(self):
        window = self._window(
            TAB_INDEX_PROJECTS, access=_A3Access({Feature.SELECT_PLAN_ITEMS})
        )
        window._select_all()
        self.assertEqual(window.log, [])
        window = self._window(TAB_INDEX_TAKEOFF, access=_A3Access())
        window._select_all()
        self.assertEqual(window.log, [])
        window = self._window(
            TAB_INDEX_TAKEOFF,
            access=_A3Access({Feature.SELECT_PLAN_ITEMS}),
            inline=True,
        )
        window._select_all()
        self.assertEqual(window.log, [("inline", ("select_all",), {})])
        window = self._window(
            TAB_INDEX_TAKEOFF, access=_A3Access({Feature.SELECT_PLAN_ITEMS})
        )
        window._select_all()
        self.assertEqual(
            [entry[0] for entry in window.log], ["plan.select_all", "toolbar"]
        )

    def test_delete_routes_by_tab_and_permission(self):
        window = self._window(TAB_INDEX_TAKEOFF, access=_A3Access())
        window._delete_selected()
        self.assertEqual(window.log, [])
        window = self._window(
            TAB_INDEX_TAKEOFF, access=_A3Access({Feature.EDIT_PLAN_ITEMS})
        )
        window._delete_selected()
        self.assertEqual([entry[0] for entry in window.log], ["plan.delete"])
        window = self._window(TAB_INDEX_SUMMARY, access=_A3Access())
        window._delete_selected()
        self.assertEqual(window.log, [])
        window = self._window(
            TAB_INDEX_SUMMARY, access=_A3Access({Feature.DELETE_CONDITION})
        )
        window._delete_selected()
        self.assertEqual([entry[0] for entry in window.log], ["summary.delete"])

    def test_project_tree_delete_requires_deletable_bids_or_projects(self):
        window = self._window(access=_A3Access(delete_bids=False))
        window._delete_selected()
        self.assertEqual(window.log, [])
        window = self._window()
        window._delete_selected()
        self.assertEqual(window.log, [("tree.delete", ("replacement",), {})])
        for path, allowed in ((None, True), ("C:/jobs/a.mdb", False)):
            with self.subTest(path=path, allowed=allowed):
                window = self._window(access=_A3Access(delete_projects=allowed))
                window.ui_state_manager.get_selected_bid_refs = lambda: []
                window.ui_state_manager.selected_project_uids = ["p1"]
                window.ui_state_manager.selected_project_file_path = path
                window._delete_selected()
                self.assertEqual(window.log, [])
        window = self._window()
        window.ui_state_manager.get_selected_bid_refs = lambda: []
        window.ui_state_manager.selected_project_uids = ["p1"]
        window.ui_state_manager.selected_project_file_path = "C:/jobs/a.mdb"
        window._delete_selected()
        self.assertEqual(window.log, [("tree.delete", ("replacement",), {})])
        self.assertIn(
            ("delete_projects", "C:/jobs/a.mdb", ["p1"]), window.ui_access_manager.calls
        )

    def test_duplicate_routes_by_tab_and_permission(self):
        window = self._window(TAB_INDEX_TAKEOFF, access=_A3Access())
        window._duplicate_selected()
        self.assertEqual(window.log, [])
        window = self._window(
            TAB_INDEX_TAKEOFF, access=_A3Access({Feature.EDIT_PLAN_ITEMS})
        )
        window._duplicate_selected()
        self.assertEqual([entry[0] for entry in window.log], ["plan.duplicate"])
        window = self._window(TAB_INDEX_SUMMARY, access=_A3Access(set(Feature)))
        window._duplicate_selected()
        self.assertEqual(window.log, [])
        window = self._window(access=_A3Access())
        window._duplicate_selected()
        self.assertEqual(window.log, [])
        window = self._window(access=_A3Access({Feature.DUPLICATE_BID}))
        window._duplicate_selected()
        self.assertEqual([entry[0] for entry in window.log], ["tree.duplicate"])

    def test_paste_routes_by_tab_and_resolves_the_project_tree_target(self):
        window = self._window(TAB_INDEX_TAKEOFF)
        window._paste_clipboard()
        self.assertEqual([entry[0] for entry in window.log], ["plan.paste"])
        window = self._window(TAB_INDEX_SUMMARY)
        window._get_bid_paste_target = lambda: self.fail("summary never pastes")
        window._paste_clipboard()
        self.assertEqual(window.log, [])
        window = self._window()
        pasted = []
        window._paste_project_bids = lambda *args: pasted.append(args)
        window._get_bid_paste_target = lambda: None
        window._paste_clipboard()
        window._get_bid_paste_target = lambda: ("C:/jobs/a.mdb", "proj")
        window._paste_clipboard()
        self.assertEqual(pasted, [("C:/jobs/a.mdb", "proj")])

    def _hierarchy(self, *bids):
        return _A3HierarchyData(
            loaded_files=[
                _A3HierarchyFileEntry(
                    file_path="C:/jobs/a.mdb",
                    orphan_bids=[_A3HierarchyBidInfo(uid=uid) for uid in bids],
                )
            ]
        )

    def _paste_window(self, *, access=None, hierarchy=None):
        window = self._window(access=access or _A3Access())
        window._project_data_service = SimpleNamespace(
            get_hierarchy=lambda: hierarchy or self._hierarchy("b1", "b2")
        )
        return window

    def test_paste_permission_depends_on_the_clipboard_mode_and_source_database(self):
        window = self._paste_window()
        self.assertIs(window._can_paste_project_bids("C:/jobs/a.mdb", None), False)
        window._bid_clipboard.copy([self.A])
        self.assertIs(
            window._can_paste_project_bids("C:/jobs/a.mdb", _A3_DELETED_UID), False
        )
        self.assertEqual(window.ui_access_manager.calls, [])
        self.assertIs(
            window._can_paste_project_bids("C:/jobs/other.mdb", "proj"), False
        )
        self.assertIs(window._can_paste_project_bids("", "proj"), False)
        self.assertEqual(window.ui_access_manager.calls, [])
        window.ui_access_manager.clipboard = False
        self.assertIs(window._can_paste_project_bids("C:/jobs/a.mdb", "proj"), False)
        window.ui_access_manager.clipboard = True
        self.assertIs(window._can_paste_project_bids("C:/jobs/a.mdb", "proj"), True)
        self.assertEqual(
            window.ui_access_manager.calls[-1],
            ("clipboard", Feature.DUPLICATE_BID, "C:/jobs/a.mdb", [self.A], "proj"),
        )
        window._bid_clipboard.cut([self.A])
        window._can_paste_project_bids("C:/jobs/a.mdb", None)
        self.assertEqual(
            window.ui_access_manager.calls[-1],
            ("clipboard", Feature.DELETE_BID, "C:/jobs/a.mdb", [self.A], None),
        )

    def test_paste_permission_drops_clipboard_bids_that_left_the_hierarchy(self):
        window = self._paste_window(hierarchy=self._hierarchy("b2"))
        window._bid_clipboard.copy([self.A])
        self.assertIs(window._can_paste_project_bids("C:/jobs/a.mdb", "proj"), False)
        self.assertFalse(window._bid_clipboard.has_content())
        self.assertEqual(window.ui_access_manager.calls, [])

    def test_a_copied_paste_duplicates_without_touching_the_clipboard(self):
        window = self._paste_window()
        window._bid_clipboard.copy([self.A, self.B])
        window._paste_project_bids("C:/jobs/a.mdb", "proj")
        self.assertEqual(
            window.log,
            [
                ("tree.paste", ([self.A, self.B], "proj"), {"is_cut": False}),
                ("toolbar", (), {}),
            ],
        )
        self.assertEqual(window._bid_clipboard.bid_refs, [self.A, self.B])

    def test_a_refused_paste_changes_nothing(self):
        window = self._paste_window(access=_A3Access(clipboard=False))
        window._bid_clipboard.copy([self.A])
        window._paste_project_bids("C:/jobs/a.mdb", "proj")
        self.assertEqual(window.log, [])

    def test_a_cut_paste_commits_the_cut_only_for_the_clipboard_it_started_with(self):
        window = self._paste_window()
        window._bid_clipboard.cut([self.A, self.B])
        window._paste_project_bids("C:/jobs/a.mdb", "proj")
        (_name, args, kwargs), toolbar = window.log
        self.assertEqual(args, ([self.A, self.B], "proj"))
        self.assertTrue(kwargs["is_cut"])
        self.assertEqual(toolbar[0], "toolbar")
        window.log.clear()
        kwargs["on_cut_committed"]()
        self.assertFalse(window._bid_clipboard.has_content())
        self.assertEqual([entry[0] for entry in window.log], ["toolbar"])
        stale = self._paste_window()
        stale._bid_clipboard.cut([self.A])
        stale._paste_project_bids("C:/jobs/a.mdb", "proj")
        callback = stale.log[0][2]["on_cut_committed"]
        stale._bid_clipboard.cut([self.B])
        stale.log.clear()
        callback()
        self.assertEqual(stale._bid_clipboard.bid_refs, [self.B])
        self.assertEqual(stale.log, [])

    def test_paste_target_needs_a_file_path_and_a_selected_bid_inside_the_selection(
        self,
    ):
        window = MainWindow.__new__(MainWindow)
        state = SimpleNamespace(
            selected_project_uids=["p1"],
            selected_project_file_path=None,
            get_selected_bid_refs=lambda: [],
            get_selected_bid_ref=lambda: None,
            selected_file_path=None,
        )
        window.ui_state_manager = state
        window._project_data_service = SimpleNamespace(
            find_project_uid_for_bid=lambda ref: "proj"
        )
        self.assertIsNone(window._get_bid_paste_target())
        state.selected_project_uids = []
        self.assertIsNone(window._get_bid_paste_target())
        state.selected_file_path = "C:/jobs/a.mdb"
        self.assertEqual(window._get_bid_paste_target(), ("C:/jobs/a.mdb", None))
        state.get_selected_bid_ref = lambda: self.A
        self.assertEqual(window._get_bid_paste_target(), ("C:/jobs/a.mdb", None))
        state.get_selected_bid_refs = lambda: [self.A]
        self.assertEqual(window._get_bid_paste_target(), ("C:/jobs/a.mdb", "proj"))
        state.selected_project_uids = ["p1", "p2"]
        self.assertIsNone(window._get_bid_paste_target())


class MainWindowA3ProjectTreeCommandTests(unittest.TestCase):
    def _window(self, access):
        window = MainWindow.__new__(MainWindow)
        calls = []
        window.calls = calls
        window.ui_access_manager = access
        window.handlers = SimpleNamespace(
            delete=SimpleNamespace(
                duplicate_bid=lambda ref: calls.append(("duplicate", ref)),
                update_bid_job_status=lambda ref, uid: calls.append(
                    ("status", ref, uid)
                ),
                restore_bids=lambda refs: calls.append(("restore", refs)),
                move_bids=lambda refs, target: calls.append(("move", refs, target)),
            )
        )
        return window

    def test_context_commands_are_dispatched_only_when_the_exact_permission_holds(self):
        ref = BidRef("C:/jobs/a.mdb", "b1")
        allowed = SimpleNamespace(
            can_duplicate_bid=lambda r: True,
            can_edit_bid_job_status=lambda r: True,
            can_edit_bid_structure=lambda refs: True,
            can_create_bid=lambda path, project: True,
        )
        denied = SimpleNamespace(
            can_duplicate_bid=lambda r: False,
            can_edit_bid_job_status=lambda r: False,
            can_edit_bid_structure=lambda refs: False,
            can_create_bid=lambda path, project: False,
        )
        window = self._window(allowed)
        window._duplicate_project_tree_bid(ref)
        window._update_project_tree_bid_job_status(ref, "js1")
        window._restore_project_bids([ref])
        window._move_project_bids([ref], "proj")
        self.assertEqual(
            window.calls,
            [
                ("duplicate", ref),
                ("status", ref, "js1"),
                ("restore", [ref]),
                ("move", [ref], "proj"),
            ],
        )
        window = self._window(denied)
        window._duplicate_project_tree_bid(ref)
        window._update_project_tree_bid_job_status(ref, "js1")
        window._restore_project_bids([ref])
        window._move_project_bids([ref], "proj")
        self.assertEqual(window.calls, [])

    def test_a_move_needs_bids_one_database_structure_access_and_a_creatable_target(
        self,
    ):
        ref = BidRef("C:/jobs/a.mdb", "b1")
        other = BidRef("C:/jobs/other.mdb", "b2")
        created = []

        def make(structure=True, create=True):
            window = MainWindow.__new__(MainWindow)
            window.ui_access_manager = SimpleNamespace(
                can_edit_bid_structure=lambda refs: structure,
                can_create_bid=lambda path, project: created.append((path, project))
                or create,
            )
            return window

        self.assertIs(make()._can_move_project_bids([], "proj"), False)
        self.assertIs(
            make(structure=False)._can_move_project_bids([ref], "proj"), False
        )
        self.assertIs(make()._can_move_project_bids([ref, other], "proj"), False)
        created.clear()
        self.assertIs(make(create=False)._can_move_project_bids([ref], "proj"), False)
        self.assertEqual(created, [("C:/jobs/a.mdb", "proj")])
        self.assertIs(make()._can_move_project_bids([ref], "proj"), True)

    def test_menu_commands_without_a_controller_do_nothing_and_report_disabled(self):
        window = MainWindow.__new__(MainWindow)
        window.menu_controller = None
        window._trigger_project_tree_menu_command("copy")
        window._create_project_tree_bid("C:/jobs/a.mdb", None)
        window._create_project_tree_project("C:/jobs/a.mdb")
        self.assertIs(window._is_project_tree_menu_command_enabled("copy"), False)
        self.assertEqual(window._project_tree_export_formats(), [])
        log = []
        window.menu_controller = SimpleNamespace(
            trigger_menu_action=lambda key: log.append(("trigger", key)),
            new_project_at=lambda path, project: log.append(("bid", path, project)),
            new_folder_in=lambda path: log.append(("folder", path)),
            is_context_command_enabled=lambda key: key == "copy",
            get_export_formats=lambda: ["csv"],
        )
        window._trigger_project_tree_menu_command("copy")
        window._create_project_tree_bid("C:/jobs/a.mdb", "proj")
        window._create_project_tree_project("C:/jobs/a.mdb")
        self.assertIs(window._is_project_tree_menu_command_enabled("copy"), True)
        self.assertIs(window._is_project_tree_menu_command_enabled("cut"), False)
        self.assertEqual(window._project_tree_export_formats(), ["csv"])
        self.assertEqual(
            log,
            [
                ("trigger", "copy"),
                ("bid", "C:/jobs/a.mdb", "proj"),
                ("folder", "C:/jobs/a.mdb"),
            ],
        )

    def test_multi_selection_is_stored_and_the_toolbar_refreshed(self):
        window = MainWindow.__new__(MainWindow)
        log = []
        window.ui_state_manager = SimpleNamespace(
            set_bid_multi_selection=lambda refs: log.append(("bids", refs)),
            set_project_multi_selection=lambda uids, path: log.append(
                ("projects", uids, path)
            ),
        )
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(refresh_toolbar=lambda: log.append(("toolbar",)))
        )
        window._on_project_multi_selection(["ref"], ["p1"], "C:/jobs/a.mdb")
        self.assertEqual(
            log,
            [("bids", ["ref"]), ("projects", ["p1"], "C:/jobs/a.mdb"), ("toolbar",)],
        )

    def test_the_context_bid_owns_the_active_bid_only_when_uid_and_path_all_match(self):
        selected = BidRef("C:/Jobs/A.mdb", "b1")
        current = BidRef("c:\\jobs\\a.mdb", "b1")
        window = MainWindow.__new__(MainWindow)
        window.ui_state_manager = SimpleNamespace(get_selected_bid_ref=lambda: selected)
        window._project_data_service = SimpleNamespace(
            get_current_bid_ref=lambda: current
        )
        self.assertIs(
            window._project_tree_context_owns_active_bid(BidRef("C:/jobs/a.mdb", "b1")),
            True,
        )
        self.assertIs(
            window._project_tree_context_owns_active_bid(BidRef("C:/jobs/a.mdb", "b2")),
            False,
        )
        self.assertIs(
            window._project_tree_context_owns_active_bid(BidRef("C:/jobs/z.mdb", "b1")),
            False,
        )
        window._project_data_service = SimpleNamespace(
            get_current_bid_ref=lambda: BidRef("C:/jobs/z.mdb", "b1")
        )
        self.assertIs(
            window._project_tree_context_owns_active_bid(BidRef("C:/jobs/a.mdb", "b1")),
            False,
        )
        window._project_data_service = SimpleNamespace(get_current_bid_ref=lambda: None)
        self.assertIs(
            window._project_tree_context_owns_active_bid(BidRef("C:/jobs/a.mdb", "b1")),
            False,
        )
        window.ui_state_manager = SimpleNamespace(get_selected_bid_ref=lambda: None)
        window._project_data_service = SimpleNamespace(
            get_current_bid_ref=lambda: current
        )
        self.assertIs(
            window._project_tree_context_owns_active_bid(BidRef("C:/jobs/a.mdb", "b1")),
            False,
        )


class MainWindowA3ImportProgressDialogTests(unittest.TestCase):
    """The project-import progress dialog: modality, ownership and cleanup."""

    def setUp(self):
        _startup_import_FakeStartupProgressDialog.instances = []
        _startup_import_FakeStartupProgressDialog.result_code = (
            QtWidgets.QDialog.DialogCode.Accepted
        )
        self.addCleanup(
            setattr,
            _startup_import_FakeStartupProgressDialog,
            "result_code",
            QtWidgets.QDialog.DialogCode.Accepted,
        )

    def _window(self, executed, *, flush=True, result=None):
        window = _startup_import__startup_import_window()
        self.target = import_args_use_case.ProjectImportTarget("target.mdb")
        self.flushed = []
        window._current_project_import_target = lambda: None
        window._deferred_persistence_manager = SimpleNamespace(
            flush_for_file=lambda path: self.flushed.append(path) or flush
        )
        window._import_project_files_from_args = SimpleNamespace(
            resolve_target=lambda current: self.target,
            uses_async_import=lambda target: False,
            execute_imports=lambda args, target, refresh_after_import=True: (
                executed.append((args, target, refresh_after_import))
                or (
                    result
                    if result is not None
                    else import_args_use_case.ProjectFileImportBatchResult(
                        target_db_path=target.file_path
                    )
                )
            ),
            build_no_target_result=lambda args: "no-target",
            build_flush_failure_result=lambda args, target: ("flush-failure", target),
            queue_imports=lambda args, target, completed: self.queued.append(
                (args, target, completed)
            ),
        )
        self.queued = []
        return window

    def _args(self, *names):
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for name in names:
                path = Path(tmp) / name
                path.write_text("x")
                paths.append(path)
            return _startup_import__project_file_args(*paths)

    def _run(self, window, args):
        with patch.object(
            main_window_module,
            "ProgressDialog",
            _startup_import_FakeStartupProgressDialog,
        ):
            return MainWindow._import_project_files_with_progress(window, args)

    def test_the_dialog_is_application_modal_owned_by_the_window_and_released(self):
        executed = []
        window = self._window(executed)
        args = self._args("one.ost")
        result = self._run(window, args)
        (dialog,) = _startup_import_FakeStartupProgressDialog.instances
        self.assertIs(dialog.window_modality, QtCore.Qt.WindowModality.ApplicationModal)
        self.assertIs(dialog.parent, window)
        self.assertEqual(dialog.cleanup_calls, 1)
        self.assertEqual(dialog.delete_later_calls, 1)
        self.assertEqual(dialog.filename, args.files[0].path)
        self.assertEqual(len(executed), 1)
        self.assertFalse(executed[0][2])
        self.assertIs(result, dialog.result)
        self.assertEqual(self.flushed, ["target.mdb"])

    def test_a_rejected_dialog_reports_every_file_as_failed_and_is_still_released(self):
        executed = []
        window = self._window(executed)
        _startup_import_FakeStartupProgressDialog.result_code = (
            QtWidgets.QDialog.DialogCode.Rejected
        )
        args = self._args("one.ost", "two.osp")
        result = self._run(window, args)
        (dialog,) = _startup_import_FakeStartupProgressDialog.instances
        self.assertEqual(dialog.cleanup_calls, 1)
        self.assertEqual(dialog.delete_later_calls, 1)
        self.assertEqual(dialog.filename, "2 project files")
        self.assertEqual(
            [(item.source_path, item.success, item.message) for item in result.results],
            [
                (item.path, False, "The file could not be imported.")
                for item in args.files
            ],
        )
        self.assertEqual(result.target_db_path, "target.mdb")

    def test_an_accepted_dialog_without_a_batch_result_is_a_failure_and_logs_the_error(
        self,
    ):
        executed = []
        window = self._window(executed)

        class NoResult(_startup_import_FakeStartupProgressDialog):
            def exec(self):
                self.result = True
                self.error = RuntimeError("worker boom")
                return self.result_code

        args = self._args("one.ost")
        with patch.object(
            main_window_module, "ProgressDialog", NoResult
        ), self.assertLogs(
            "ost_visualizer.presentation.main_window", level="ERROR"
        ) as captured:
            result = MainWindow._import_project_files_with_progress(window, args)
        self.assertIn("worker boom", captured.output[0])
        self.assertEqual([item.success for item in result.results], [False])
        _startup_import_FakeStartupProgressDialog.result_code = (
            QtWidgets.QDialog.DialogCode.Rejected
        )
        with self.assertNoLogs(
            "ost_visualizer.presentation.main_window", level="ERROR"
        ):
            quiet = self._run(self._window(executed), args)
        self.assertEqual([item.success for item in quiet.results], [False])

    def test_a_dialog_that_raises_while_running_is_still_released(self):
        window = self._window([])

        class Exploding(_startup_import_FakeStartupProgressDialog):
            def exec(self):
                raise RuntimeError("exec failed")

        args = self._args("one.ost")
        with patch.object(main_window_module, "ProgressDialog", Exploding):
            with self.assertRaisesRegex(RuntimeError, "exec failed"):
                MainWindow._import_project_files_with_progress(window, args)
        (dialog,) = Exploding.instances[-1:]
        self.assertEqual(dialog.cleanup_calls, 1)
        self.assertEqual(dialog.delete_later_calls, 1)

    def test_every_early_exit_returns_before_a_dialog_is_created(self):
        executed = []
        window = self._window(executed)
        rejected = [_A3Rejected(value="bad.txt", reason="Unsupported file type.")]
        empty = import_args_use_case.ProjectFileArgs(files=[], rejected=rejected)
        result = self._run(window, empty)
        self.assertEqual(result.rejected, rejected)
        self.assertEqual(result.results, [])
        args = self._args("one.ost")
        window.ui_access_manager = SimpleNamespace(is_allowed=lambda feature: False)
        denied = self._run(window, args)
        self.assertEqual(
            [(item.success, item.message) for item in denied.results],
            [(False, "Import is not available for the selected database.")],
        )
        window = self._window(executed)
        window._import_project_files_from_args.resolve_target = lambda current: None
        self.assertEqual(self._run(window, args), "no-target")
        window = self._window(executed, flush=False)
        self.assertEqual(self._run(window, args), ("flush-failure", self.target))
        window = self._window(executed)
        window._import_project_files_from_args.uses_async_import = lambda target: True
        self.assertIsNone(self._run(window, args))
        self.assertEqual(len(self.queued), 1)
        self.assertEqual(self.queued[0][2], window._complete_async_project_file_imports)
        self.assertEqual(_startup_import_FakeStartupProgressDialog.instances, [])
        self.assertEqual(executed, [])

    def test_the_create_database_dialog_result_needs_both_acceptance_and_a_path(self):
        class Controller:
            def __init__(self, path):
                self.path = path

            def create_new_database(self, name=None, progress_callback=None):
                return self.path

        cases = (
            (QtWidgets.QDialog.DialogCode.Accepted, "created.mdb", "created.mdb"),
            (QtWidgets.QDialog.DialogCode.Rejected, "created.mdb", None),
            (QtWidgets.QDialog.DialogCode.Accepted, "", None),
            (QtWidgets.QDialog.DialogCode.Accepted, None, None),
        )
        for code, path, expected in cases:
            with self.subTest(code=code, path=path):
                window = MainWindow.__new__(MainWindow)
                window.app_controller = Controller(path)

                class Dialog(_dialog_lifecycle_support_FakeProgressDialog):
                    result_code = code

                with patch.object(main_window_module, "ProgressDialog", Dialog):
                    self.assertEqual(
                        MainWindow._create_database_with_progress(window), expected
                    )


class MainWindowA3ImportCompletionTests(unittest.TestCase):
    def _result(self, **kwargs):
        return import_args_use_case.ProjectFileImportBatchResult(**kwargs)

    def _recorders(self):
        calls = []
        patchers = [
            patch.object(
                main_window_module,
                name,
                lambda parent, title, details, level=level: calls.append(
                    (level, title, details)
                ),
            )
            for name, level in (
                ("show_info", "info"),
                ("show_warning", "warning"),
                ("show_critical", "critical"),
            )
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        return calls

    def test_rejected_only_batches_are_reported_as_errors(self):
        calls = self._recorders()
        window = _startup_import__startup_import_window()
        MainWindow._show_project_file_import_result(
            window,
            self._result(
                rejected=[_A3Rejected(value="bad.txt", reason="Unsupported.")]
            ),
        )
        self.assertEqual(calls, [("critical", "Import Error", "bad.txt: Unsupported.")])

    def test_a_committed_import_whose_projection_failed_is_a_warning_not_a_success(
        self,
    ):
        calls = self._recorders()
        window = _startup_import__startup_import_window()
        item = import_args_use_case.ProjectFileImportResult(
            source_path="a.ost",
            success=True,
            message="Imported but the view could not refresh.",
            outcome_status=MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
        )
        MainWindow._show_project_file_import_result(
            window, self._result(results=[item], target_db_path="t.mdb")
        )
        self.assertEqual(
            calls,
            [
                (
                    "warning",
                    "Import Complete",
                    "Successfully imported 'a.ost' into the database.\n"
                    "a.ost: Imported but the view could not refresh.",
                )
            ],
        )

    def test_selection_after_an_import_needs_a_loaded_bid_or_the_matching_target(self):
        window = _startup_import__startup_import_window()
        log = []
        window.project_view = SimpleNamespace(
            restore_bid_selection=lambda ref: log.append(("bid", ref)),
            restore_project_selection=lambda uid, path: log.append(
                ("project", uid, path)
            ),
            restore_file_selection=lambda path: log.append(("file", path)),
        )
        selected = {"ref": None, "loaded": True}
        window.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: selected["ref"]
        )
        window._project_data_service = SimpleNamespace(
            get_bid=lambda ref: (
                self.fail("a missing selection must not be looked up")
                if ref is None
                else selected["loaded"]
            )
        )
        select = lambda result: MainWindow._select_project_file_import_result(
            window, result
        )
        select(self._result(selected_project_uid="p1", target_db_path="t.mdb"))
        select(self._result(selected_project_uid="p1"))
        select(self._result(selected_project_uid=None, target_db_path="t.mdb"))
        select(self._result())
        self.assertEqual(log, [("project", "p1", "t.mdb"), ("file", "t.mdb")])
        log.clear()
        selected["ref"] = BidRef("t.mdb", "b1")
        select(self._result(selected_project_uid="p1", target_db_path="t.mdb"))
        self.assertEqual(log, [("bid", selected["ref"])])
        log.clear()
        selected["loaded"] = None
        select(self._result(selected_project_uid="p1", target_db_path="t.mdb"))
        self.assertEqual(log, [("project", "p1", "t.mdb")])

    def test_import_scheduling_waits_for_load_ready_and_no_other_import(self):
        window = _startup_import__startup_import_window()
        scheduled = []
        with patch.object(
            QtCore.QTimer,
            "singleShot",
            side_effect=lambda delay, callback: scheduled.append((delay, callback)),
        ):
            window._schedule_pending_project_file_imports()
            self.assertEqual(scheduled, [])
            window._pending_project_file_args = [object()]
            for loaded, ready, running, flag in (
                (False, True, False, False),
                (True, False, False, False),
                (True, True, True, False),
                (True, True, False, True),
            ):
                window._startup_load_complete = loaded
                window._main_window_ready = ready
                window._project_file_import_running = running
                window._project_file_import_scheduled = flag
                window._schedule_pending_project_file_imports()
                self.assertEqual(scheduled, [], (loaded, ready, running, flag))
            window._project_file_import_scheduled = False
            window._project_file_import_running = False
            window._schedule_pending_project_file_imports()
            self.assertEqual(scheduled, [(0, window._run_pending_project_file_imports)])
            self.assertTrue(window._project_file_import_scheduled)

    def test_a_pending_run_reschedules_instead_of_overlapping_a_running_import(self):
        window = _startup_import__startup_import_window()
        window._startup_load_complete = True
        window._main_window_ready = True
        window._pending_project_file_args = [object()]
        window._project_file_import_running = True
        window._project_file_import_scheduled = True
        scheduled = []
        with patch.object(
            QtCore.QTimer,
            "singleShot",
            side_effect=lambda delay, cb: scheduled.append(delay),
        ):
            window._run_pending_project_file_imports()
        self.assertFalse(window._project_file_import_scheduled)
        self.assertEqual(scheduled, [])
        self.assertEqual(len(window._pending_project_file_args), 1)

    def test_arguments_queued_during_an_import_are_scheduled_after_it_finishes(self):
        window = _startup_import__startup_import_window()
        window._startup_load_complete = True
        window._main_window_ready = True
        window._pending_project_file_args = [
            import_args_use_case.ProjectFileArgs(files=[], rejected=[])
        ]
        queued = import_args_use_case.ProjectFileArgs(files=[], rejected=[])

        def import_and_enqueue(args):
            window._pending_project_file_args.append(queued)
            return self._result()

        window._import_project_files_with_progress = import_and_enqueue
        window._select_project_file_import_result = lambda result: None
        window._show_project_file_import_result = lambda result: None
        scheduled = []
        with patch.object(
            QtCore.QTimer,
            "singleShot",
            side_effect=lambda delay, callback: scheduled.append((delay, callback)),
        ):
            window._run_pending_project_file_imports()
        self.assertEqual(scheduled, [(0, window._run_pending_project_file_imports)])
        self.assertEqual(window._pending_project_file_args, [queued])
        self.assertTrue(window._project_file_import_scheduled)
        self.assertFalse(window._project_file_import_running)

    def test_a_synchronous_run_marks_itself_running_until_the_projection_finished(self):
        window = _startup_import__startup_import_window()
        window._startup_load_complete = True
        window._main_window_ready = True
        window._pending_project_file_args = [
            import_args_use_case.ProjectFileArgs(files=[], rejected=[])
        ]
        seen = []
        result = self._result()
        window._import_project_files_with_progress = lambda args: result
        window._select_project_file_import_result = lambda r: seen.append(
            ("select", window._project_file_import_running)
        )
        window._show_project_file_import_result = lambda r: seen.append(
            ("show", window._project_file_import_running)
        )
        window._run_pending_project_file_imports()
        self.assertEqual(seen, [("select", True), ("show", True)])
        self.assertFalse(window._project_file_import_running)
        self.assertEqual(window._pending_project_file_args, [])
        # an asynchronous batch keeps the running flag until its completion callback
        window._pending_project_file_args = [
            import_args_use_case.ProjectFileArgs(files=[], rejected=[])
        ]
        window._import_project_files_with_progress = lambda args: None
        window._run_pending_project_file_imports()
        self.assertTrue(window._project_file_import_running)
        _app()
        QtWidgets.QMainWindow.__init__(window)
        self.addCleanup(window.deleteLater)
        window._select_project_file_import_result = lambda r: None
        window._show_project_file_import_result = lambda r: None
        with patch.object(QtCore.QTimer, "singleShot"):
            window._complete_async_project_file_imports(result)
        self.assertFalse(window._project_file_import_running)

    def test_import_steps_deferred_by_a_shutdown_are_keyed_by_their_own_names(self):
        window = _startup_import__startup_import_window()
        window._startup_load_complete = True
        window._main_window_ready = True
        window._pending_project_file_args = [
            import_args_use_case.ProjectFileArgs(files=[], rejected=[])
        ]
        window._collaboration_shutdown_pending = True
        window._schedule_pending_project_file_imports()
        self.assertEqual(
            list(window._shutdown_deferred_callbacks), ["schedule_project_file_imports"]
        )
        window._shutdown_deferred_callbacks.clear()
        window._run_pending_project_file_imports()
        self.assertEqual(
            list(window._shutdown_deferred_callbacks), ["run_project_file_imports"]
        )
        window._shutdown_deferred_callbacks.clear()
        window._collaboration_shutdown_pending = False
        result = self._result()

        def import_then_start_shutdown(args):
            window._collaboration_shutdown_pending = True
            return result

        window._import_project_files_with_progress = import_then_start_shutdown
        window._run_pending_project_file_imports()
        self.assertIn(
            "complete_project_file_imports", window._shutdown_deferred_callbacks
        )
        window._shutdown_deferred_callbacks.clear()
        window._collaboration_shutdown_pending = False
        refreshing = import_args_use_case.ProjectFileImportBatchResult(
            refresh_pending=True
        )
        window._pending_project_file_args = [
            import_args_use_case.ProjectFileArgs(files=[], rejected=[])
        ]
        window._import_project_files_with_progress = lambda args: refreshing

        def refresh(result):
            window._collaboration_shutdown_pending = True
            return result

        window._import_project_files_from_args = SimpleNamespace(
            refresh_import_result=refresh
        )
        window._run_pending_project_file_imports()
        self.assertIn(
            "complete_project_file_imports", window._shutdown_deferred_callbacks
        )

    def test_an_async_completion_deferred_by_a_shutdown_is_keyed_by_its_name(self):
        _app()
        window = _startup_import__startup_import_window()
        QtWidgets.QMainWindow.__init__(window)
        self.addCleanup(window.deleteLater)
        window._collaboration_shutdown_pending = True
        window._project_file_import_running = True
        window._complete_async_project_file_imports(self._result())
        self.assertEqual(
            list(window._shutdown_deferred_callbacks), ["complete_project_file_imports"]
        )
        self.assertIs(window._project_file_import_running, False)

    def test_a_refresh_that_starts_a_shutdown_defers_the_async_completion_under_its_name(
        self,
    ):
        _app()
        window = _startup_import__startup_import_window()
        QtWidgets.QMainWindow.__init__(window)
        self.addCleanup(window.deleteLater)

        def refresh(result):
            window._collaboration_shutdown_pending = True
            return result

        window._import_project_files_from_args = SimpleNamespace(
            refresh_import_result=refresh
        )
        window._complete_async_project_file_imports(
            import_args_use_case.ProjectFileImportBatchResult(refresh_pending=True)
        )
        self.assertIn(
            "complete_project_file_imports", window._shutdown_deferred_callbacks
        )

    def test_config_load_projects_a_loaded_catalog_or_asks_for_a_first_database(self):
        for loaded, has_databases, prompt in (
            (True, True, False),
            (False, True, False),
            (False, False, True),
        ):
            with self.subTest(loaded=loaded, has_databases=has_databases):
                window = _startup_import__startup_import_window()
                window._needs_create_database_prompt = False
                synced = []
                window.app_controller = SimpleNamespace(
                    load_files_from_config=lambda loaded=loaded: loaded,
                    has_any_databases=lambda has=has_databases: has,
                )
                window.handlers = SimpleNamespace(
                    ui_event=SimpleNamespace(
                        sync_after_startup_load=lambda: synced.append(True)
                    )
                )
                timers = []
                window._schedule_pending_project_file_imports = lambda: timers.append(
                    "schedule"
                )
                with patch.object(
                    QtCore.QTimer,
                    "singleShot",
                    side_effect=lambda delay, cb: timers.append((delay, cb)),
                ):
                    window._load_files_from_config()
                self.assertEqual(synced, [True] if loaded else [])
                self.assertIs(window._needs_create_database_prompt, prompt)
                self.assertTrue(window._startup_load_complete)
                self.assertEqual(
                    timers, [(0, window._restore_deferred_workspace_state), "schedule"]
                )

    def test_showing_the_main_window_schedules_update_check_and_first_database_prompt(
        self,
    ):
        window = _startup_import__startup_import_window()
        log = []
        window._workspace_state_coordinator = SimpleNamespace(
            show_main_window=lambda: log.append("show")
        )
        window.raise_ = lambda: log.append("raise")
        window.activateWindow = lambda: log.append("activate")
        window._update_service = object()
        window._needs_create_database_prompt = True
        timers = []
        with patch.object(
            QtCore.QTimer,
            "singleShot",
            side_effect=lambda delay, cb: timers.append((delay, cb)),
        ):
            window._show_main_window()
        self.assertEqual(log, ["show", "raise", "activate"])
        self.assertEqual(
            timers,
            [(0, window._check_for_updates), (0, window._prompt_create_database)],
        )
        self.assertFalse(window._needs_create_database_prompt)
        window._update_service = None
        timers.clear()
        with patch.object(
            QtCore.QTimer, "singleShot", side_effect=lambda delay, cb: timers.append(cb)
        ):
            window._show_main_window()
        self.assertEqual(timers, [])


class MainWindowA3ShutdownBookkeepingTests(unittest.TestCase):
    def _window(self, **flags):
        window = MainWindow.__new__(MainWindow)
        window._collaboration_shutdown_pending = flags.get("pending", False)
        window._collaboration_shutdown_complete = flags.get("complete", False)
        window._application_shutdown_finalized = flags.get("finalized", False)
        window._shutdown_deferred_callbacks = {}
        window._shutdown_hidden_windows = ()
        return window

    def test_the_shutdown_is_terminal_when_either_final_flag_is_set(self):
        self.assertIs(self._window()._application_shutdown_terminal(), False)
        self.assertIs(
            self._window(pending=True)._application_shutdown_terminal(), False
        )
        self.assertIs(
            self._window(complete=True)._application_shutdown_terminal(), True
        )
        self.assertIs(
            self._window(finalized=True)._application_shutdown_terminal(), True
        )

    def test_callbacks_are_deferred_only_while_a_shutdown_is_in_progress(self):
        callback = lambda: None
        idle = self._window()
        self.assertIs(idle._defer_during_application_shutdown("k", callback), False)
        self.assertEqual(idle._shutdown_deferred_callbacks, {})
        pending = self._window(pending=True)
        self.assertIs(pending._defer_during_application_shutdown("k", callback), True)
        self.assertEqual(pending._shutdown_deferred_callbacks, {"k": callback})
        terminal = self._window(complete=True)
        self.assertIs(terminal._defer_during_application_shutdown("k", callback), True)
        self.assertEqual(terminal._shutdown_deferred_callbacks, {})

    def test_resuming_after_an_abort_shows_hidden_windows_once_and_replays_with_zero_delay(
        self,
    ):
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        owned = QtWidgets.QWidget()
        stranger = QtWidgets.QWidget()
        destroyed = QtWidgets.QWidget()
        for widget in (owned, stranger):
            self.addCleanup(widget.deleteLater)
        window = self._window()
        window._detached_plan_windows = lambda: (owned,)
        window.get_mesh_window = lambda: None
        shown = []
        window._shutdown_hidden_windows = (owned, stranger, destroyed)
        _a3_delete(destroyed)
        owned.show = lambda: shown.append("owned")
        stranger.show = lambda: shown.append("stranger")
        calls = []
        window._shutdown_deferred_callbacks = {
            "other": lambda: calls.append("other"),
            "show_main_window": lambda: calls.append("show"),
            "load_files_from_config": lambda: calls.append("load"),
        }
        timers = []
        with patch.object(
            QtCore.QTimer,
            "singleShot",
            side_effect=lambda delay, cb: timers.append((delay, cb)),
        ):
            window._resume_shutdown_deferred_callbacks()
            window._resume_shutdown_deferred_callbacks()
        self.assertEqual(shown, ["owned"])
        self.assertEqual(window._shutdown_hidden_windows, ())
        self.assertEqual([delay for delay, _cb in timers], [0, 0, 0])
        for _delay, callback in timers:
            callback()
        self.assertEqual(calls, ["load", "show", "other"])
        app.processEvents()

    def test_update_check_reports_only_available_updates_with_version_information(self):
        for result, expected in (
            ((False, {"version": "2.0"}), []),
            ((True, None), []),
            ((True, {}), []),
            ((True, {"version": "2.0"}), [{"version": "2.0"}]),
        ):
            with self.subTest(result=result):
                emitted = []
                window = self._window()
                window._update_service = SimpleNamespace(
                    check_for_updates=lambda r=result: r
                )
                window.update_dialog_requested = SimpleNamespace(emit=emitted.append)
                with patch(
                    "ost_visualizer.presentation.main_window.threading.Thread"
                ) as thread_factory:
                    window._check_for_updates()
                with self.assertNoLogs(
                    "ost_visualizer.presentation.main_window", level="ERROR"
                ):
                    thread_factory.call_args.kwargs["target"]()
                self.assertEqual(emitted, expected)
        # an update found after the shutdown became terminal is not reported
        emitted = []
        window = self._window()
        window._update_service = SimpleNamespace(
            check_for_updates=lambda: (True, {"version": "2.0"})
        )
        window.update_dialog_requested = SimpleNamespace(emit=emitted.append)
        with patch(
            "ost_visualizer.presentation.main_window.threading.Thread"
        ) as thread_factory:
            window._check_for_updates()
        window._application_shutdown_finalized = True
        thread_factory.call_args.kwargs["target"]()
        self.assertEqual(emitted, [])

    def test_close_ignores_windows_that_are_hidden_destroyed_or_missing(self):
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        window = MainWindow.__new__(MainWindow)
        QtWidgets.QMainWindow.__init__(window)
        visible, hidden, destroyed = [QtWidgets.QWidget() for _ in range(3)]
        for widget in (window, visible, hidden):
            self.addCleanup(widget.deleteLater)
        window.handlers = SimpleNamespace(
            file_ops=SimpleNamespace(
                maintenance_pending=False, sql_creation_pending=False
            )
        )
        window._collaboration_shutdown_pending = False
        window._collaboration_shutdown_complete = False
        window._collaboration_shutdown_failed = False
        window._application_shutdown_finalized = False
        window._shutdown_deferred_callbacks = {}
        window._shutdown_hidden_windows = ()
        visible.show()
        _a3_delete(destroyed)
        window._detached_plan_windows = lambda: (visible, hidden, destroyed)
        window.get_mesh_window = lambda: None
        timers = []
        with patch.object(
            QtCore.QTimer,
            "singleShot",
            side_effect=lambda delay, cb: timers.append((delay, cb)),
        ):
            window.close()
        self.assertEqual(window._shutdown_hidden_windows, (visible,))
        self.assertFalse(visible.isVisible())
        self.assertEqual([delay for delay, _cb in timers], [0])
        self.assertTrue(window._collaboration_shutdown_pending)
        app.processEvents()


class MainWindowA3SplitterTests(unittest.TestCase):
    """Real splitters: reading, restoring and re-opening collapsed panes."""

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _splitter(self, orientation, sizes, extent=400):
        splitter = QtWidgets.QSplitter(orientation)
        splitter.setHandleWidth(0)
        for _ in sizes:
            splitter.addWidget(QtWidgets.QWidget())
        splitter.resize(
            extent if orientation == QtCore.Qt.Orientation.Horizontal else 200,
            200 if orientation == QtCore.Qt.Orientation.Horizontal else extent,
        )
        splitter.setSizes(sizes)
        self.addCleanup(splitter.deleteLater)
        return splitter

    def _window(self):
        window = MainWindow.__new__(MainWindow)
        window._last_takeoff_splitter_sizes = []
        window._last_left_splitter_sizes = []
        window._last_left_column_splitter_sizes = []
        window._takeoff_splitter = self._splitter(
            QtCore.Qt.Orientation.Horizontal, [100, 300], 400
        )
        window._left_splitter = self._splitter(
            QtCore.Qt.Orientation.Vertical, [100, 300], 400
        )
        window._left_column_splitter = self._splitter(
            QtCore.Qt.Orientation.Vertical, [100, 300], 400
        )
        return window

    def test_takeoff_splitter_reports_sizes_and_remembers_only_a_visible_sidebar(self):
        window = self._window()
        self.assertEqual(window.get_takeoff_splitter_sizes(), [100, 300])
        self.assertEqual(window._last_takeoff_splitter_sizes, [100, 300])
        window._takeoff_splitter.setSizes([0, 400])
        self.assertEqual(window.get_takeoff_splitter_sizes(), [0, 400])
        self.assertEqual(window._last_takeoff_splitter_sizes, [100, 300])

    def test_takeoff_splitter_restore_ignores_empty_and_all_zero_sizes(self):
        window = self._window()
        window.set_takeoff_splitter_sizes([])
        window.set_takeoff_splitter_sizes([0, 0])
        self.assertEqual(window._takeoff_splitter.sizes(), [100, 300])
        self.assertEqual(window._last_takeoff_splitter_sizes, [])
        window.set_takeoff_splitter_sizes([-5, 200])
        self.assertEqual(window._takeoff_splitter.sizes()[0], 0)
        self.assertEqual(window._last_takeoff_splitter_sizes, [])
        window.set_takeoff_splitter_sizes([150, 250])
        self.assertEqual(window._takeoff_splitter.sizes(), [150, 250])
        self.assertEqual(window._last_takeoff_splitter_sizes, [150, 250])

    def test_left_splitter_remembers_sizes_only_while_both_panes_are_visible(self):
        window = self._window()
        self.assertEqual(window.get_left_splitter_sizes(), [100, 300])
        self.assertEqual(window._last_left_splitter_sizes, [100, 300])
        window._left_splitter.setSizes([0, 400])
        self.assertEqual(window.get_left_splitter_sizes(), [0, 400])
        window._left_splitter.setSizes([400, 0])
        self.assertEqual(window.get_left_splitter_sizes(), [400, 0])
        self.assertEqual(window._last_left_splitter_sizes, [100, 300])

    def test_left_splitter_restore_validates_both_panes_before_remembering(self):
        window = self._window()
        window.set_left_splitter_sizes([])
        window.set_left_splitter_sizes([0, 0])
        self.assertEqual(window._left_splitter.sizes(), [100, 300])
        window.set_left_splitter_sizes([0, 200])
        self.assertEqual(window._last_left_splitter_sizes, [])
        window.set_left_splitter_sizes([200, 0])
        self.assertEqual(window._last_left_splitter_sizes, [])
        window.set_left_splitter_sizes([250, 150])
        self.assertEqual(window._last_left_splitter_sizes, [250, 150])
        self.assertEqual(window._left_splitter.sizes(), [250, 150])

    def test_left_column_splitter_requires_exactly_two_visible_panes(self):
        window = self._window()
        self.assertEqual(window.get_left_column_splitter_sizes(), [100, 300])
        self.assertEqual(window._last_left_column_splitter_sizes, [100, 300])
        window._left_column_splitter.setSizes([0, 400])
        window.get_left_column_splitter_sizes()
        self.assertEqual(window._last_left_column_splitter_sizes, [100, 300])
        window._last_left_column_splitter_sizes = []
        window.set_left_column_splitter_sizes([100])
        window.set_left_column_splitter_sizes([0, 0])
        window.set_left_column_splitter_sizes([1, 2, 3])
        self.assertEqual(window._left_column_splitter.sizes(), [0, 400])
        window.set_left_column_splitter_sizes([120, 280])
        self.assertEqual(window._left_column_splitter.sizes(), [120, 280])
        self.assertEqual(window._last_left_column_splitter_sizes, [120, 280])
        window.set_left_column_splitter_sizes([0, 400])
        self.assertEqual(window._last_left_column_splitter_sizes, [120, 280])

    def test_a_collapsed_left_pane_reopens_by_saved_ratio_or_half_the_height(self):
        window = self._window()
        window._left_splitter.setSizes([0, 400])
        window._last_left_splitter_sizes = [100, 300]
        window._ensure_left_splitter_pane_visible(0)
        self.assertEqual(window._left_splitter.sizes(), [100, 300])
        window._left_splitter.setSizes([400, 0])
        window._last_left_splitter_sizes = [300, 100]
        window._ensure_left_splitter_pane_visible(1)
        self.assertEqual(window._left_splitter.sizes(), [300, 100])
        window._left_splitter.setSizes([0, 400])
        window._last_left_splitter_sizes = []
        window._ensure_left_splitter_pane_visible(0)
        self.assertEqual(window._left_splitter.sizes(), [200, 200])
        window._left_splitter.setSizes([400, 0])
        window._ensure_left_splitter_pane_visible(1)
        self.assertEqual(window._left_splitter.sizes(), [200, 200])
        before = window._left_splitter.sizes()
        window._ensure_left_splitter_pane_visible(0)
        self.assertEqual(window._left_splitter.sizes(), before)

    def test_scaling_saved_left_sizes_keeps_each_pane_at_least_one_pixel(self):
        scale = MainWindow._scale_left_splitter_sizes
        self.assertEqual(scale([100, 300], 800), [200, 600])
        self.assertEqual(scale([1, 999], 10), [1, 9])
        self.assertEqual(scale([999, 1], 10), [9, 1])
        self.assertEqual(scale([5, 5], 0), [1, 1])
        self.assertEqual(scale([0, 0], 10), [1, 9])
        self.assertTrue(MainWindow._has_valid_left_splitter_sizes([1, 1]))
        self.assertFalse(MainWindow._has_valid_left_splitter_sizes([1]))
        self.assertFalse(MainWindow._has_valid_left_splitter_sizes([0, 1]))
        self.assertFalse(MainWindow._has_valid_left_splitter_sizes([1, 0]))

    def test_a_collapsed_pan_pane_reopens_by_saved_ratio_or_the_default_height(self):
        window = self._window()
        window._left_column_splitter.setSizes([0, 400])
        window._last_left_column_splitter_sizes = [100, 300]
        window._ensure_pan_pane_visible()
        self.assertEqual(window._left_column_splitter.sizes(), [100, 300])
        window._left_column_splitter.setSizes([0, 400])
        window._last_left_column_splitter_sizes = []
        window._ensure_pan_pane_visible()
        pan = min(max(1, _A3_PAN_DEFAULT_HEIGHT), 399)
        self.assertEqual(window._left_column_splitter.sizes(), [pan, 400 - pan])
        window._left_column_splitter.setSizes([0, 400])
        window._last_left_column_splitter_sizes = [0, 300]
        window._ensure_pan_pane_visible()
        self.assertEqual(window._left_column_splitter.sizes(), [pan, 400 - pan])
        before = window._left_column_splitter.sizes()
        window._ensure_pan_pane_visible()
        self.assertEqual(window._left_column_splitter.sizes(), before)

    def test_a_collapsed_sidebar_column_reopens_at_its_saved_width_or_a_quarter(self):
        window = self._window()
        window._takeoff_splitter.setSizes([0, 400])
        window._last_takeoff_splitter_sizes = [120, 280]
        window._ensure_sidebar_column_visible()
        self.assertEqual(window._takeoff_splitter.sizes(), [120, 280])
        window._takeoff_splitter.setSizes([0, 400])
        window._last_takeoff_splitter_sizes = [0, 400]
        window._ensure_sidebar_column_visible()
        expected = max(_A3_SIDEBAR_MIN_WIDTH, 400 // 4)
        self.assertEqual(window._takeoff_splitter.sizes(), [expected, 400 - expected])
        window._takeoff_splitter.setSizes([0, 400])
        window._last_takeoff_splitter_sizes = [10_000, 1]
        window._ensure_sidebar_column_visible()
        self.assertEqual(window._takeoff_splitter.sizes(), [399, 1])
        before = window._takeoff_splitter.sizes()
        window._ensure_sidebar_column_visible()
        self.assertEqual(window._takeoff_splitter.sizes(), before)

    def test_a_sidebar_pane_request_opens_the_column_before_the_pane(self):
        window = self._window()
        order = []
        window._ensure_sidebar_column_visible = lambda: order.append("column")
        window._ensure_left_splitter_pane_visible = lambda index: order.append(index)
        window._ensure_sidebar_pane_visible(1)
        self.assertEqual(order, ["column", 1])


class MainWindowA3DetachedWindowActionTests(unittest.TestCase):
    """Annotation / View window visibility, restore rules and action sync."""

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    BID = BidRef("C:/jobs/a.mdb", "b1")

    def _window(
        self,
        *,
        takeoff=True,
        bid=True,
        page="p1",
        annotation_open=False,
        view_open=False,
        view_lifecycle=False,
        annotation_lifecycle=False,
    ):
        window = MainWindow.__new__(MainWindow)
        self.log = []
        log = self.log
        window.tab_widget = SimpleNamespace(
            currentIndex=lambda: TAB_INDEX_TAKEOFF if takeoff else TAB_INDEX_PROJECTS
        )
        window.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: self.BID if bid else None,
            active_page_uid=page,
        )
        window.plan_view = None
        window._project_data_service = SimpleNamespace(
            get_page=lambda uid: object() if uid == "p1" else None
        )
        window._workspace_state_model = make_workspace_state_model()
        window._annotation_window_action = _A3QAction("annotation")
        window._view_window_action = _A3QAction("view")
        for action in (window._annotation_window_action, window._view_window_action):
            action.setCheckable(True)
            action.toggled.connect(lambda checked: log.append(("toggled", checked)))
        self.annotation_open = annotation_open
        self.view_open = view_open
        annotation_view = SimpleNamespace(
            bid_ref=BidRef("C:/jobs/other.mdb", "b9"),
            target_page_uid="p9",
            target_named_view_uid="nv9",
        )
        window._annotation_view_manager = SimpleNamespace(
            is_view_open=lambda: self.annotation_open,
            get_window=lambda: "annotation-window",
            has_active_view_lifecycle=lambda: annotation_lifecycle,
            get_active_view=lambda: annotation_view,
            open_view=lambda *args, **kwargs: log.append(
                ("annotation.open", args, kwargs)
            ),
            close_view=lambda: log.append(("annotation.close",)),
        )
        window._view_window_manager = SimpleNamespace(
            is_view_open=lambda: self.view_open,
            get_window=lambda: "view-window",
            has_active_view_lifecycle=lambda: view_lifecycle,
            open_view=lambda *args, **kwargs: log.append(("view.open", args, kwargs)),
            close_view=lambda: log.append(("view.close",)),
        )
        return window

    def test_restore_and_open_rules_follow_bid_page_tab_and_open_windows(self):
        window = self._window()
        self.assertTrue(window.can_open_annotation_window())
        self.assertTrue(window.can_restore_annotation_window())
        self.assertFalse(window.can_open_view_window())
        self.assertFalse(window.can_restore_view_window())
        self.assertIs(window.is_annotation_window_open(), False)
        self.assertIs(window.is_view_window_open(), False)
        self.assertEqual(window.get_annotation_window(), "annotation-window")
        self.assertEqual(window.get_view_window(), "view-window")
        window = self._window(annotation_open=True, view_open=True)
        self.assertIs(window.is_annotation_window_open(), True)
        self.assertIs(window.is_view_window_open(), True)
        self.assertTrue(window.can_open_view_window())
        self.assertTrue(window.can_restore_view_window())
        self.assertFalse(
            self._window(takeoff=False, annotation_open=True).can_restore_view_window()
        )
        self.assertFalse(self._window(takeoff=False).can_restore_annotation_window())
        self.assertTrue(self._window(takeoff=False).can_open_annotation_window())
        self.assertFalse(self._window(bid=False).can_open_annotation_window())
        self.assertFalse(self._window(page=None).can_open_annotation_window())
        self.assertFalse(self._window(page="missing").can_open_annotation_window())

    def test_showing_a_window_that_cannot_be_restored_only_unchecks_its_action(self):
        window = self._window(takeoff=False)
        window._annotation_window_action.setChecked(True)
        self.log.clear()
        window.set_annotation_window_visible(True)
        self.assertFalse(window._annotation_window_action.isChecked())
        self.assertFalse(window._annotation_window_action.signalsBlocked())
        self.assertEqual(self.log, [])
        window = self._window(annotation_open=False)
        window._view_window_action.setChecked(True)
        self.log.clear()
        window.set_view_window_visible(True)
        self.assertFalse(window._view_window_action.isChecked())
        self.assertFalse(window._view_window_action.signalsBlocked())
        self.assertEqual(self.log, [])

    def test_opening_the_annotation_window_checks_the_action_silently_and_opens_once(
        self,
    ):
        window = self._window()
        window.set_annotation_window_visible(True)
        self.assertTrue(window._annotation_window_action.isChecked())
        self.assertEqual(
            self.log,
            [
                (
                    "annotation.open",
                    (self.BID, "p1", None),
                    {
                        "initial_geometry": None,
                        "initial_is_maximized": False,
                        "initial_is_fullscreen": False,
                    },
                )
            ],
        )
        self.annotation_open = True
        self.log.clear()
        window.set_annotation_window_visible(True)
        self.assertEqual(self.log, [])

    def test_saved_detached_state_is_restored_only_when_no_explicit_state_is_given(
        self,
    ):
        for explicit in (False, True):
            with self.subTest(explicit=explicit):
                window = self._window()
                state = WorkspaceState()
                saved = state.detached_windows.annotation_view
                saved.geometry_b64 = _detached_support__encoded_geometry(b"saved")
                saved.is_maximized = True
                saved.is_fullscreen = True
                window._workspace_state_model = SimpleNamespace(state=state)
                if explicit:
                    window.set_annotation_window_visible(
                        True,
                        initial_geometry=QtCore.QByteArray(b"explicit"),
                        initial_is_maximized=False,
                        initial_is_fullscreen=False,
                    )
                else:
                    window.set_annotation_window_visible(True)
                _name, _args, kwargs = self.log[0]
                self.assertEqual(
                    bytes(kwargs["initial_geometry"]),
                    b"explicit" if explicit else b"saved",
                )
                self.assertIs(kwargs["initial_is_maximized"], not explicit)
                self.assertIs(kwargs["initial_is_fullscreen"], not explicit)

    def test_closing_the_annotation_window_closes_a_dependent_view_first(self):
        window = self._window(annotation_open=True, view_lifecycle=True)
        window._annotation_window_action.setChecked(True)
        self.log.clear()
        calls = []
        window.set_view_window_visible = lambda visible: calls.append(
            ("view.visible", visible)
        )
        window._annotation_view_manager.close_view = lambda: calls.append(
            "annotation.close"
        )
        window.set_annotation_window_visible(False)
        self.assertEqual(calls, [("view.visible", False), "annotation.close"])
        self.assertFalse(window._annotation_window_action.isChecked())
        window = self._window(annotation_open=True, view_lifecycle=False)
        calls = []
        window.set_view_window_visible = lambda visible: calls.append("never")
        window._annotation_view_manager.close_view = lambda: calls.append(
            "annotation.close"
        )
        window.set_annotation_window_visible(False)
        self.assertEqual(calls, ["annotation.close"])

    def test_opening_the_view_window_follows_the_annotation_window_target(self):
        window = self._window(annotation_open=True)
        window.set_view_window_visible(True)
        self.assertTrue(window._view_window_action.isChecked())
        self.assertEqual(
            self.log,
            [
                (
                    "view.open",
                    (BidRef("C:/jobs/other.mdb", "b9"), "p9", "nv9"),
                    {
                        "initial_geometry": None,
                        "initial_is_maximized": False,
                        "initial_is_fullscreen": False,
                    },
                )
            ],
        )
        self.view_open = True
        self.log.clear()
        window.set_view_window_visible(True)
        self.assertEqual(self.log, [])
        window.set_view_window_visible(False)
        self.assertEqual(self.log, [("view.close",)])
        self.assertFalse(window._view_window_action.isChecked())

    def test_the_view_window_falls_back_to_the_selection_without_an_annotation_view(
        self,
    ):
        window = self._window(annotation_open=True)
        window._annotation_view_manager.get_active_view = lambda: None
        window.set_view_window_visible(True)
        _name, args, _kwargs = self.log[0]
        self.assertEqual(args, (self.BID, "p1", None))
        window = self._window(annotation_open=True)
        window._annotation_view_manager.get_active_view = lambda: SimpleNamespace(
            bid_ref=None, target_page_uid="p9", target_named_view_uid=None
        )
        window.set_view_window_visible(True)
        _name, args, _kwargs = self.log[0]
        self.assertEqual(args, (self.BID, "p9", None))

    def test_the_action_state_mirrors_the_open_windows_without_emitting_toggles(self):
        window = self._window(annotation_open=True, view_open=False)
        window._sync_annotation_window_action()
        window._sync_view_window_action()
        self.assertTrue(window._annotation_window_action.isChecked())
        self.assertTrue(window._view_window_action.isEnabled())
        self.assertFalse(window._view_window_action.isChecked())
        self.annotation_open = False
        self.view_open = True
        window._sync_annotation_window_action()
        window._sync_view_window_action()
        self.assertFalse(window._annotation_window_action.isChecked())
        self.assertFalse(window._view_window_action.isEnabled())
        self.assertTrue(window._view_window_action.isChecked())
        self.assertEqual(self.log, [])


class MainWindowA3TabChangeTests(unittest.TestCase):
    def _window(self, *, view=False, annotation=False, mesh=None, menu=True):
        window = MainWindow.__new__(MainWindow)
        log = []
        window.log = log
        window._apply_workspace_toolbar_visibility = lambda: log.append("toolbar")
        window._view_window_manager = SimpleNamespace(
            has_active_view_lifecycle=lambda: view
        )
        window._annotation_view_manager = SimpleNamespace(
            has_active_view_lifecycle=lambda: annotation
        )
        window.get_mesh_window = lambda: mesh
        window.set_view_window_visible = lambda visible: log.append(("view", visible))
        window.set_annotation_window_visible = lambda visible: log.append(
            ("annotation", visible)
        )
        window.set_mesh_window_visible = lambda visible: log.append(("mesh", visible))
        window._workspace_state_coordinator = SimpleNamespace(
            request_view_restore=lambda: log.append("view-restore"),
            request_annotation_restore=lambda: log.append("annotation-restore"),
            request_mesh_restore=lambda: log.append("mesh-restore"),
            on_main_tab_changed=lambda: log.append("tab-changed"),
        )
        window.menu_controller = (
            SimpleNamespace(update_menu_states=lambda: log.append("menus"))
            if menu
            else None
        )
        return window

    def test_leaving_the_takeoff_tab_closes_active_detached_windows_in_order(self):
        window = self._window(view=True, annotation=True, mesh=object())
        window._on_tab_changed(TAB_INDEX_PROJECTS)
        self.assertEqual(
            window.log,
            [
                "toolbar",
                "view-restore",
                ("view", False),
                "annotation-restore",
                ("annotation", False),
                "mesh-restore",
                ("mesh", False),
                "tab-changed",
                "menus",
            ],
        )

    def test_idle_windows_and_the_takeoff_tab_leave_detached_windows_alone(self):
        window = self._window()
        window._on_tab_changed(TAB_INDEX_SUMMARY)
        self.assertEqual(window.log, ["toolbar", "tab-changed", "menus"])
        window = self._window(view=True, annotation=True, mesh=object(), menu=False)
        window._on_tab_changed(TAB_INDEX_TAKEOFF)
        self.assertEqual(window.log, ["toolbar", "tab-changed"])

    def test_contextual_shell_sync_reapplies_the_current_tab(self):
        window = self._window()
        window.tab_widget = SimpleNamespace(currentIndex=lambda: TAB_INDEX_SUMMARY)
        window.sync_contextual_shell_visibility()
        self.assertEqual(window.log, ["toolbar", "tab-changed", "menus"])


class MainWindowA3PassThroughAndStateTests(unittest.TestCase):
    """Delegating accessors, popup-size persistence and the database context."""

    def test_dropdown_popup_sizes_merge_every_open_surface_and_restore_to_each(self):
        window = MainWindow.__new__(MainWindow)
        restored = {}
        window.takeoff_sidebar = SimpleNamespace(
            get_popup_size=lambda: [300, 200],
            set_popup_size=lambda size: restored.setdefault("main_page", size),
        )
        window._page_settings_bar = SimpleNamespace(
            get_dropdown_popup_sizes=lambda: {"page_settings": [1, 2]},
            set_dropdown_popup_sizes=lambda sizes: restored.setdefault(
                "bar", dict(sizes)
            ),
        )

        def detached(name, sizes):
            return SimpleNamespace(
                get_dropdown_popup_sizes=lambda: sizes,
                set_dropdown_popup_sizes=lambda saved: restored.setdefault(
                    name, dict(saved)
                ),
            )

        windows = {
            "annotation": detached("annotation", {"annotation_named_views": [3, 4]})
        }
        window.get_annotation_window = lambda: windows["annotation"]
        window.get_view_window = lambda: None
        self.assertEqual(
            window.get_takeoff_dropdown_popup_sizes(),
            {
                "main_page": [300, 200],
                "page_settings": [1, 2],
                "annotation_named_views": [3, 4],
            },
        )
        saved = {"main_page": [5, 6], "other": [7, 8]}
        window.set_takeoff_dropdown_popup_sizes(saved)
        self.assertEqual(restored["main_page"], [5, 6])
        self.assertEqual(restored["bar"], saved)
        self.assertEqual(restored["annotation"], saved)
        restored.clear()
        window.set_takeoff_dropdown_popup_sizes({})
        self.assertEqual(restored["main_page"], [])

    def test_the_database_context_is_the_selected_nodes_loaded_database(self):
        window = MainWindow.__new__(MainWindow)
        node = {"file_path": "C:/Jobs/A.mdb"}
        window.project_view = SimpleNamespace(get_selected_node_state=lambda: node)
        window._project_data_service = SimpleNamespace(
            get_hierarchy=lambda: _A3HierarchyData(
                loaded_files=[_A3HierarchyFileEntry(file_path="c:\\jobs\\a.mdb")]
            )
        )
        self.assertEqual(
            window.get_selected_database_context_file_path(), "C:/Jobs/A.mdb"
        )
        node["file_path"] = "C:/Jobs/Other.mdb"
        self.assertIsNone(window.get_selected_database_context_file_path())
        node["file_path"] = ""
        self.assertIsNone(window.get_selected_database_context_file_path())
        window.project_view = SimpleNamespace(get_selected_node_state=lambda: None)
        self.assertIsNone(window.get_selected_database_context_file_path())

    def test_view_state_setters_forward_without_notifying(self):
        window = MainWindow.__new__(MainWindow)
        log = []
        window.project_view = SimpleNamespace(
            set_group_by_job_status=lambda enabled, notify: log.append(
                ("job", enabled, notify)
            )
        )
        window._conditions_sidebar = SimpleNamespace(
            set_group_by_type=lambda enabled, notify: log.append(
                ("type", enabled, notify)
            )
        )
        window._condition_summary_tab = SimpleNamespace(
            set_grouping=lambda grouping, notify: log.append(
                ("summary", grouping, notify)
            )
        )
        window.set_project_group_by_job_status(True)
        window.set_conditions_group_by_type(False)
        window.set_summary_grouping("by-type")
        self.assertEqual(
            log,
            [
                ("job", True, False),
                ("type", False, False),
                ("summary", "by-type", False),
            ],
        )

    def test_detached_refreshes_reach_both_managers(self):
        window = MainWindow.__new__(MainWindow)
        log = []
        for name in ("_annotation_view_manager", "_view_window_manager"):
            setattr(
                window,
                name,
                SimpleNamespace(
                    refresh_active_view=lambda name=name: log.append((name, "view")),
                    refresh_page_area_selection=lambda page, name=name: log.append(
                        (name, page)
                    ),
                ),
            )
        window.refresh_detached_plan_views()
        window.refresh_detached_plan_area_selection("p7")
        self.assertEqual(
            log,
            [
                ("_annotation_view_manager", "view"),
                ("_view_window_manager", "view"),
                ("_annotation_view_manager", "p7"),
                ("_view_window_manager", "p7"),
            ],
        )

    def test_palette_changes_rebuild_icons_but_other_changes_do_not(self):
        _app()
        window = MainWindow.__new__(MainWindow)
        QtWidgets.QMainWindow.__init__(window)
        self.addCleanup(window.deleteLater)
        with patch.object(main_window_module, "rebuild_all_icons") as rebuild:
            window.changeEvent(QtCore.QEvent(QtCore.QEvent.Type.PaletteChange))
            self.assertEqual(rebuild.call_count, 1)
            window.changeEvent(QtCore.QEvent(QtCore.QEvent.Type.EnabledChange))
            self.assertEqual(rebuild.call_count, 1)

    def test_workspace_state_save_requests_reach_the_coordinator(self):
        window = MainWindow.__new__(MainWindow)
        log = []
        window._workspace_state_coordinator = SimpleNamespace(
            request_save=lambda: log.append("save"),
            reset_to_defaults=lambda: log.append("reset"),
            on_takeoff_workspace_activated=lambda: log.append("activated"),
        )
        window._request_workspace_state_save()
        window.reset_workspace_state_to_defaults()
        window.notify_takeoff_workspace_activated()
        self.assertEqual(log, ["save", "reset", "activated"])


class MainWindowA3PageAndAreaContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_adding_a_page_from_the_takeoff_tab_needs_every_condition(self):
        def make(allow=True, cover=True, locked=False, bid=True):
            window = MainWindow.__new__(MainWindow)
            window._config_model = SimpleNamespace(
                allow_add_page_from_takeoff_tab=allow
            )
            window.ui_access_manager = SimpleNamespace(
                is_allowed=lambda feature: cover and feature == Feature.COVER_SHEET
            )
            window._project_data_service = SimpleNamespace(
                is_current_bid_locked=lambda: locked
            )
            window.ui_state_manager = SimpleNamespace(
                get_selected_bid_ref=lambda: BidRef("a.mdb", "b1") if bid else None
            )
            return window

        self.assertTrue(make().can_add_page_from_takeoff_tab())
        self.assertFalse(make(allow=False).can_add_page_from_takeoff_tab())
        self.assertFalse(make(cover=False).can_add_page_from_takeoff_tab())
        self.assertFalse(make(locked=True).can_add_page_from_takeoff_tab())
        self.assertFalse(make(bid=False).can_add_page_from_takeoff_tab())

    def test_the_active_takeoff_page_prefers_the_ui_state_over_the_plan_view(self):
        window = MainWindow.__new__(MainWindow)
        window._project_data_service = SimpleNamespace(
            get_page=lambda uid: object() if uid in {"p1", "p2"} else None
        )
        window.plan_view = SimpleNamespace(current_page_uid="p2")
        window.ui_state_manager = SimpleNamespace(active_page_uid="p1")
        self.assertEqual(window.get_active_takeoff_page_uid(), "p1")
        window.ui_state_manager.active_page_uid = None
        self.assertEqual(window.get_active_takeoff_page_uid(), "p2")
        window.plan_view = None
        self.assertIsNone(window.get_active_takeoff_page_uid())
        window.plan_view = SimpleNamespace(current_page_uid="gone")
        self.assertIsNone(window.get_active_takeoff_page_uid())

    def test_restoring_detached_windows_also_needs_a_bid_and_page(self):
        window = MainWindow.__new__(MainWindow)
        window.tab_widget = SimpleNamespace(currentIndex=lambda: TAB_INDEX_TAKEOFF)
        window.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: None, active_page_uid="p1"
        )
        window._project_data_service = SimpleNamespace(get_page=lambda uid: object())
        window.plan_view = None
        window._annotation_view_manager = SimpleNamespace(is_view_open=lambda: True)
        self.assertFalse(window.can_restore_annotation_window())
        self.assertFalse(window.can_open_view_window())
        self.assertFalse(window.can_restore_view_window())

    def test_hiding_a_detached_window_works_even_when_it_cannot_be_restored(self):
        proxy = MainWindowA3DetachedWindowActionTests(
            "test_restore_and_open_rules_follow_bid_page_tab_and_open_windows"
        )
        window = MainWindowA3DetachedWindowActionTests._window(
            proxy, takeoff=False, annotation_open=True, view_open=True
        )
        window._annotation_window_action.setChecked(True)
        window._view_window_action.setChecked(True)
        proxy.log.clear()
        window.set_view_window_visible(False)
        window.set_annotation_window_visible(False)
        # the actions are unchecked silently: no toggled signal reaches handlers
        self.assertEqual(proxy.log, [("view.close",), ("annotation.close",)])
        self.assertFalse(window._annotation_window_action.isChecked())
        self.assertFalse(window._view_window_action.isChecked())
        self.assertFalse(window._annotation_window_action.signalsBlocked())
        self.assertFalse(window._view_window_action.signalsBlocked())

    def test_action_updates_never_leave_the_action_signals_blocked(self):
        proxy = MainWindowA3DetachedWindowActionTests(
            "test_restore_and_open_rules_follow_bid_page_tab_and_open_windows"
        )
        window = MainWindowA3DetachedWindowActionTests._window(
            proxy, annotation_open=True
        )
        actions = (window._annotation_window_action, window._view_window_action)
        window.set_annotation_window_visible(True)
        proxy.annotation_open = True
        window.set_view_window_visible(True)
        window.set_view_window_visible(False)
        window.set_annotation_window_visible(False)
        window._sync_annotation_window_action()
        window._sync_view_window_action()
        for action in actions:
            self.assertFalse(action.signalsBlocked())
        proxy.log.clear()
        for action in actions:
            action.setChecked(not action.isChecked())
        self.assertEqual(
            len([entry for entry in proxy.log if entry[0] == "toggled"]), 2
        )

    def test_visibility_notifications_track_windows_and_resync_the_actions(self):
        window = MainWindow.__new__(MainWindow)
        log = []
        window._sync_annotation_window_action = lambda: log.append("sync-annotation")
        window._sync_view_window_action = lambda: log.append("sync-view")
        window.set_view_window_visible = lambda visible: log.append(("view", visible))
        window._workspace_state_coordinator = SimpleNamespace(
            track_annotation_window=lambda: log.append("track-annotation"),
            track_view_window=lambda: log.append("track-view"),
        )
        lifecycle = {"active": False}
        window._view_window_manager = SimpleNamespace(
            has_active_view_lifecycle=lambda: lifecycle["active"],
            is_view_open=lambda: lifecycle["active"],
        )
        window._on_annotation_window_visibility_changed(True)
        self.assertEqual(log, ["sync-annotation", "track-annotation", "sync-view"])
        log.clear()
        window._on_annotation_window_visibility_changed(False)
        self.assertEqual(log, ["sync-annotation", "sync-view"])
        lifecycle["active"] = True
        log.clear()
        window._on_annotation_window_visibility_changed(False)
        self.assertEqual(log, ["sync-annotation", ("view", False)])
        log.clear()
        window._on_annotation_window_visibility_changed(True)
        self.assertEqual(log, ["sync-annotation", "track-annotation", "sync-view"])
        log.clear()
        window._on_view_window_visibility_changed(True)
        self.assertEqual(log, ["track-view", "sync-view"])
        lifecycle["active"] = False
        log.clear()
        window._on_view_window_visibility_changed(False)
        self.assertEqual(log, ["sync-view"])

    def test_the_mesh_window_follows_the_takeoff_tab_and_saved_geometry(self):
        window = MainWindow.__new__(MainWindow)
        calls = []
        window.tab_widget = SimpleNamespace(currentIndex=lambda: TAB_INDEX_PROJECTS)
        window._mesh_window_action = _A3QAction("mesh")
        window._mesh_window_action.setCheckable(True)
        toggles = []
        window._mesh_window_action.toggled.connect(toggles.append)
        state = WorkspaceState()
        saved = state.detached_windows.mesh_view
        saved.geometry_b64 = _detached_support__encoded_geometry(b"saved")
        saved.is_maximized = False
        window._workspace_state_model = SimpleNamespace(state=state)
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(
                set_mesh_window_visible=lambda visible, **kwargs: calls.append(
                    (visible, kwargs)
                )
            )
        )
        window._mesh_window_action.setChecked(True)
        toggles.clear()
        window.set_mesh_window_visible(True)
        self.assertEqual(calls, [])
        self.assertFalse(window._mesh_window_action.isChecked())
        self.assertFalse(window._mesh_window_action.signalsBlocked())
        self.assertEqual(toggles, [])
        window._mesh_window_action.setChecked(True)
        window.set_mesh_window_visible(False)
        self.assertEqual(
            calls, [(False, {"initial_geometry": None, "initial_is_maximized": True})]
        )
        calls.clear()
        toggles.clear()
        window.tab_widget = SimpleNamespace(currentIndex=lambda: TAB_INDEX_TAKEOFF)
        toggles.clear()
        window.set_mesh_window_visible(True)
        ((visible, kwargs),) = calls
        self.assertTrue(visible)
        self.assertEqual(bytes(kwargs["initial_geometry"]), b"saved")
        self.assertIs(kwargs["initial_is_maximized"], False)
        self.assertTrue(window._mesh_window_action.isChecked())
        self.assertEqual(toggles, [])
        self.assertFalse(window._mesh_window_action.signalsBlocked())
        calls.clear()
        window.set_mesh_window_visible(
            True,
            initial_geometry=QtCore.QByteArray(b"explicit"),
            initial_is_maximized=True,
        )
        self.assertEqual(bytes(calls[0][1]["initial_geometry"]), b"explicit")
        self.assertIs(calls[0][1]["initial_is_maximized"], True)
        calls.clear()
        window.set_mesh_window_visible(False)
        self.assertEqual(calls[0][0], False)
        self.assertFalse(window._mesh_window_action.isChecked())

    def _area_window(self, *, takeoff=True, plan_page="p1", area_uid="area-1"):
        window = MainWindow.__new__(MainWindow)
        QtWidgets.QMainWindow.__init__(window)
        self.addCleanup(window.deleteLater)
        window.tab_widget = SimpleNamespace(
            currentIndex=lambda: TAB_INDEX_TAKEOFF if takeoff else TAB_INDEX_PROJECTS
        )
        self.plan = QtWidgets.QWidget()
        self.plan.current_page_uid = plan_page
        self.bar = QtWidgets.QWidget()
        self.bar.get_selected_area_uid = lambda: area_uid
        for widget in (self.plan, self.bar):
            self.addCleanup(
                lambda w=widget: w.deleteLater() if _a3_is_valid(w) else None
            )
        window.plan_view = self.plan
        window._page_settings_bar = self.bar
        self.detached = []
        window._annotation_view_manager = SimpleNamespace(
            get_window=lambda: self.detached[0] if self.detached else None
        )
        window._view_window_manager = SimpleNamespace(get_window=lambda: None)
        return window

    def _resolve(self, window, *, focus=None, active=None):
        with patch.object(
            QtWidgets.QApplication, "focusWidget", return_value=focus
        ), patch.object(QtWidgets.QApplication, "activeWindow", return_value=active):
            return window.resolve_current_area_selection_context()

    def test_the_area_context_is_the_main_plan_when_the_main_window_has_focus(self):
        window = self._area_window()
        context = self._resolve(window, active=window)
        self.assertIs(context.parent, window)
        self.assertIs(context.plan_view, self.plan)
        self.assertEqual(context.area_uid, "area-1")
        self.assertIsNone(
            self._resolve(self._area_window(area_uid=""), active=None).plan_view
        )
        window = self._area_window(area_uid="")
        self.assertIsNone(self._resolve(window, active=window).area_uid)

    def test_the_area_context_has_no_plan_when_the_main_plan_is_not_current(self):
        for kwargs in ({"takeoff": False}, {"plan_page": ""}, {"plan_page": None}):
            with self.subTest(kwargs=kwargs):
                window = self._area_window(**kwargs)
                context = self._resolve(window, active=window)
                self.assertIs(context.parent, window)
                self.assertIsNone(context.plan_view)
        window = self._area_window()
        window.plan_view = None
        self.assertIsNone(self._resolve(window, active=window).plan_view)
        window = self._area_window()
        window._page_settings_bar = None
        self.assertIsNone(self._resolve(window, active=window).plan_view)
        window = self._area_window()
        _a3_delete(self.plan)
        self.assertIsNone(self._resolve(window, active=window).plan_view)
        window = self._area_window()
        _a3_delete(self.bar)
        self.assertIsNone(self._resolve(window, active=window).plan_view)

    def test_the_area_context_ignores_an_unrelated_focus_owner(self):
        window = self._area_window()
        other = QtWidgets.QWidget()
        self.addCleanup(other.deleteLater)
        context = self._resolve(window, focus=other, active=window)
        self.assertIs(context.parent, window)
        self.assertIsNone(context.plan_view)

    def test_a_detached_window_supplies_its_own_plan_and_area(self):
        window = self._area_window()
        detached = QtWidgets.QWidget()
        self.addCleanup(detached.deleteLater)
        target = {"value": (self.plan, "area-9")}
        detached.current_area_selection_target = lambda: target["value"]
        self.detached.append(detached)
        context = self._resolve(window, active=detached)
        self.assertIs(context.parent, detached)
        self.assertIs(context.plan_view, self.plan)
        self.assertEqual(context.area_uid, "area-9")
        target["value"] = None
        context = self._resolve(window, active=detached)
        self.assertIs(context.parent, window)
        self.assertIsNone(context.plan_view)

    def test_a_menu_focus_resolves_to_the_window_that_owns_the_menu_chain(self):
        window = self._area_window()
        outer = QtWidgets.QMenu(window)
        inner = QtWidgets.QMenu(outer)
        for menu in (outer, inner):
            self.addCleanup(menu.deleteLater)
        context = self._resolve(window, focus=inner, active=None)
        self.assertIs(context.parent, window)
        self.assertIs(context.plan_view, self.plan)
        orphan = QtWidgets.QMenu()
        self.addCleanup(orphan.deleteLater)
        context = self._resolve(window, focus=orphan, active=window)
        self.assertIs(context.parent, window)
        self.assertIs(context.plan_view, self.plan)
        other = self._area_window()
        context = self._resolve(window, focus=orphan, active=other)
        self.assertIs(context.parent, window)
        self.assertIsNone(context.plan_view)

    def test_a_widget_top_level_is_none_for_missing_destroyed_or_failing_widgets(self):
        top = QtWidgets.QWidget()
        child = QtWidgets.QWidget(top)
        self.addCleanup(top.deleteLater)
        self.assertIsNone(MainWindow._widget_top_level(None))
        self.assertIs(MainWindow._widget_top_level(child), top)
        destroyed = QtWidgets.QWidget()
        _a3_delete(destroyed)
        self.assertIsNone(MainWindow._widget_top_level(destroyed))

        class Failing:
            def window(self):
                raise RuntimeError("Internal C++ object already deleted.")

        self.assertIsNone(MainWindow._widget_top_level(Failing()))

        class Nothing:
            def window(self):
                return None

        self.assertIsNone(MainWindow._widget_top_level(Nothing()))
        gone = QtWidgets.QWidget()
        _a3_delete(gone)

        class Dangling:
            def window(self):
                return gone

        self.assertIsNone(MainWindow._widget_top_level(Dangling()))

    def test_detached_plan_windows_skips_missing_and_destroyed_windows(self):
        window = MainWindow.__new__(MainWindow)
        live = QtWidgets.QWidget()
        self.addCleanup(live.deleteLater)
        gone = QtWidgets.QWidget()
        _a3_delete(gone)
        window._annotation_view_manager = SimpleNamespace(get_window=lambda: gone)
        window._view_window_manager = SimpleNamespace(get_window=lambda: live)
        self.assertEqual(window._detached_plan_windows(), (live,))
        window._annotation_view_manager = SimpleNamespace(get_window=lambda: None)
        self.assertEqual(window._detached_plan_windows(), (live,))
        window._view_window_manager = SimpleNamespace(get_window=lambda: None)
        self.assertEqual(window._detached_plan_windows(), ())

    def test_a_menu_inside_another_menus_widget_resolves_to_the_active_window(self):
        window = self._area_window()
        outer = QtWidgets.QMenu(window)
        holder = QtWidgets.QWidget(outer)
        inner = QtWidgets.QMenu(holder)
        for widget in (outer, holder, inner):
            self.addCleanup(widget.deleteLater)
        self.assertIsInstance(MainWindow._widget_top_level(holder), QtWidgets.QMenu)
        context = self._resolve(window, focus=inner, active=window)
        self.assertIs(context.parent, window)
        self.assertIs(context.plan_view, self.plan)
        other = self._area_window()
        context = self._resolve(window, focus=inner, active=other)
        self.assertIs(context.parent, window)
        self.assertIsNone(context.plan_view)


class MainWindowA3ShellLayoutTests(unittest.TestCase):
    """Toolbars, workspace tabs, sidebars and the status panel on real widgets."""

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _window(self, tab=TAB_INDEX_TAKEOFF):
        window = MainWindow.__new__(MainWindow)
        QtWidgets.QMainWindow.__init__(window)
        self.addCleanup(window.deleteLater)
        self.holder = QtWidgets.QWidget()
        self.addCleanup(self.holder.deleteLater)
        self.tab = tab
        window.tab_widget = SimpleNamespace(currentIndex=lambda: self.tab)
        window._workspace_toolbar_visibility = {
            window.MAIN_TOOLBAR_KEY: True,
            window.VIEW_TOOLBAR_KEY: True,
            window.PLAN_TOOLS_TOOLBAR_KEY: True,
            window.OVERLAY_TOOLS_TOOLBAR_KEY: True,
        }
        window._syncing_toolbar_visibility = False
        for name in (
            "_main_toolbar",
            "_plan_tools_toolbar",
            "_overlay_tools_toolbar",
            "_view_toolbar",
        ):
            setattr(window, name, QtWidgets.QToolBar(self.holder))
        self.saves = []
        window._workspace_state_coordinator = SimpleNamespace(
            request_save=lambda: self.saves.append("save")
        )
        return window

    def test_toolbars_are_shown_by_preference_and_the_takeoff_ones_only_on_takeoff(
        self,
    ):
        window = self._window(TAB_INDEX_TAKEOFF)
        window._apply_workspace_toolbar_visibility()
        toolbars = (
            window._main_toolbar,
            window._plan_tools_toolbar,
            window._overlay_tools_toolbar,
            window._view_toolbar,
        )
        self.assertEqual([t.isHidden() for t in toolbars], [False] * 4)
        self.assertFalse(window._syncing_toolbar_visibility)
        window._workspace_toolbar_visibility[window.MAIN_TOOLBAR_KEY] = False
        window._workspace_toolbar_visibility[window.VIEW_TOOLBAR_KEY] = False
        window._apply_workspace_toolbar_visibility()
        self.assertEqual([t.isHidden() for t in toolbars], [True, False, False, True])
        self.tab = TAB_INDEX_PROJECTS
        window._workspace_toolbar_visibility[window.MAIN_TOOLBAR_KEY] = True
        window._apply_workspace_toolbar_visibility()
        self.assertEqual([t.isHidden() for t in toolbars], [False, True, True, True])

    def test_toolbars_are_applied_while_the_window_marks_itself_as_syncing(self):
        window = self._window()
        seen = []
        window._set_toolbar_visible = lambda toolbar, key, available: seen.append(
            (key, available, window._syncing_toolbar_visibility)
        )
        window._apply_workspace_toolbar_visibility()
        self.assertEqual(
            seen,
            [
                (window.MAIN_TOOLBAR_KEY, True, True),
                (window.PLAN_TOOLS_TOOLBAR_KEY, True, True),
                (window.OVERLAY_TOOLS_TOOLBAR_KEY, True, True),
                (window.VIEW_TOOLBAR_KEY, True, True),
            ],
        )
        self.assertFalse(window._syncing_toolbar_visibility)

    def test_toolbar_visibility_is_not_syncing_when_a_toolbar_update_fails(self):
        window = self._window()
        window._main_toolbar = None
        with self.assertRaises(AttributeError):
            window._apply_workspace_toolbar_visibility()
        self.assertFalse(window._syncing_toolbar_visibility)

    def test_user_toolbar_changes_are_remembered_unless_the_window_is_syncing(self):
        window = self._window()
        window._on_workspace_toolbar_visibility_changed(window.VIEW_TOOLBAR_KEY, False)
        self.assertIs(
            window._workspace_toolbar_visibility[window.VIEW_TOOLBAR_KEY], False
        )
        window._syncing_toolbar_visibility = True
        window._on_workspace_toolbar_visibility_changed(window.VIEW_TOOLBAR_KEY, True)
        self.assertIs(
            window._workspace_toolbar_visibility[window.VIEW_TOOLBAR_KEY], False
        )

    def test_a_toolbar_preference_is_applied_and_saved(self):
        window = self._window()
        window.set_workspace_toolbar_preference(window.PLAN_TOOLS_TOOLBAR_KEY, False)
        self.assertIs(
            window._workspace_toolbar_visibility[window.PLAN_TOOLS_TOOLBAR_KEY], False
        )
        self.assertTrue(window._plan_tools_toolbar.isHidden())
        self.assertEqual(self.saves, ["save"])
        window.set_workspace_toolbar_preference(window.PLAN_TOOLS_TOOLBAR_KEY, 1)
        self.assertIs(
            window._workspace_toolbar_visibility[window.PLAN_TOOLS_TOOLBAR_KEY], True
        )
        self.assertFalse(window._plan_tools_toolbar.isHidden())
        self.assertEqual(self.saves, ["save", "save"])

    def test_the_toolbar_state_snapshot_is_a_copy_and_restores_known_keys_only(self):
        window = self._window()
        snapshot = window.get_workspace_toolbar_visibility_state()
        snapshot[window.MAIN_TOOLBAR_KEY] = False
        self.assertIs(
            window._workspace_toolbar_visibility[window.MAIN_TOOLBAR_KEY], True
        )
        window.set_workspace_toolbar_visibility_state(
            {window.VIEW_TOOLBAR_KEY: 0, "unknown": True}
        )
        self.assertIs(
            window._workspace_toolbar_visibility[window.VIEW_TOOLBAR_KEY], False
        )
        self.assertNotIn("unknown", window._workspace_toolbar_visibility)
        self.assertTrue(window._view_toolbar.isHidden())
        self.assertEqual(self.saves, [])

    def test_the_toolbar_popup_menu_lists_every_toolbar_and_toggles_the_preference(
        self,
    ):
        window = self._window(TAB_INDEX_PROJECTS)
        window._workspace_toolbar_visibility[window.OVERLAY_TOOLS_TOOLBAR_KEY] = False
        menu = window.createPopupMenu()
        self.addCleanup(menu.deleteLater)
        self.assertEqual(menu.title(), SHOW_TOOLBARS_MENU_TITLE)
        actions = menu.actions()
        self.assertEqual(
            [a.text() for a in actions],
            [
                MAIN_TOOLBAR_LABEL,
                VIEW_TOOLBAR_LABEL,
                PLAN_TOOLS_TOOLBAR_LABEL,
                OVERLAY_TOOLS_TOOLBAR_LABEL,
            ],
        )
        self.assertTrue(all(a.isCheckable() for a in actions))
        self.assertEqual([a.isChecked() for a in actions], [True, True, True, False])
        self.assertEqual([a.isEnabled() for a in actions], [True, False, False, False])
        actions[0].setChecked(False)
        self.assertIs(
            window._workspace_toolbar_visibility[window.MAIN_TOOLBAR_KEY], False
        )
        self.assertTrue(window._main_toolbar.isHidden())
        self.assertEqual(self.saves, ["save"])
        self.tab = TAB_INDEX_TAKEOFF
        enabled = [a.isEnabled() for a in window.createPopupMenu().actions()]
        self.assertEqual(enabled, [True, True, True, True])

    def test_takeoff_view_tabs_can_never_both_be_hidden(self):
        window = self._window()
        window._view_2d_action = _A3QAction("2d")
        window._view_3d_action = _A3QAction("3d")
        for action in (window._view_2d_action, window._view_3d_action):
            action.setVisible(True)
        window.set_takeoff_2d_tab_visible(False)
        self.assertFalse(window.is_takeoff_2d_tab_visible())
        self.assertTrue(window.is_takeoff_3d_tab_visible())
        window.set_takeoff_3d_tab_visible(False)
        self.assertTrue(window.is_takeoff_3d_tab_visible())
        self.assertFalse(window.is_takeoff_2d_tab_visible())
        window.set_takeoff_2d_tab_visible(True)
        window.set_takeoff_3d_tab_visible(False)
        self.assertTrue(window.is_takeoff_2d_tab_visible())
        self.assertFalse(window.is_takeoff_3d_tab_visible())
        window.set_takeoff_2d_tab_visible(False)
        self.assertTrue(window.is_takeoff_2d_tab_visible())
        self.assertEqual(len(self.saves), 5)

    def test_view_tab_changes_request_a_workspace_save(self):
        window = self._window()
        window._view_2d_action = _A3QAction("2d")
        window._view_3d_action = _A3QAction("3d")
        window._view_2d_action.setVisible(True)
        window._view_3d_action.setVisible(True)
        window._request_workspace_state_save = lambda: self.saves.append("tab-save")
        window.set_takeoff_2d_tab_visible(True)
        window.set_takeoff_3d_tab_visible(True)
        self.assertEqual(self.saves, ["tab-save", "tab-save"])

    def test_the_active_takeoff_view_is_two_d_only_for_index_one(self):
        window = self._window()
        stack = QtWidgets.QStackedWidget()
        self.addCleanup(stack.deleteLater)
        stack.addWidget(QtWidgets.QWidget())
        stack.addWidget(QtWidgets.QWidget())
        window._view_stack = stack
        stack.setCurrentIndex(1)
        self.assertEqual(window.get_active_takeoff_view(), WORKSPACE_ACTIVE_VIEW_2D)
        window.set_active_takeoff_view(WORKSPACE_ACTIVE_VIEW_3D)
        self.assertEqual(stack.currentIndex(), 0)
        self.assertEqual(window.get_active_takeoff_view(), WORKSPACE_ACTIVE_VIEW_3D)
        window.set_active_takeoff_view(WORKSPACE_ACTIVE_VIEW_2D.upper())
        self.assertEqual(stack.currentIndex(), 1)
        changes = []
        stack.currentChanged.connect(changes.append)
        window.set_active_takeoff_view(WORKSPACE_ACTIVE_VIEW_2D)
        self.assertEqual(changes, [])

    def test_navigating_to_a_hotlink_selects_the_page_then_focuses_in_two_d(self):
        window = self._window()
        log = []
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(
                navigate_to_takeoff_page=lambda page, view: log.append(
                    ("go", page, view)
                ),
                apply_pending_hotlink_view_focus=lambda: log.append("focus"),
            )
        )
        window.set_active_takeoff_view = lambda view: log.append(("view", view))
        window.navigate_to_hotlink_page("p2", "nv1")
        window.navigate_to_hotlink_page("p3")
        self.assertEqual(
            log,
            [
                ("go", "p2", "nv1"),
                ("view", WORKSPACE_ACTIVE_VIEW_2D),
                "focus",
                ("go", "p3", ""),
                ("view", WORKSPACE_ACTIVE_VIEW_2D),
                "focus",
            ],
        )

    def _sidebar_window(self):
        window = self._window()
        window._conditions_sidebar = QtWidgets.QWidget(self.holder)
        window._bid_layers_sidebar = QtWidgets.QWidget(self.holder)
        window._pan_sidebar = QtWidgets.QWidget(self.holder)
        window._left_splitter = QtWidgets.QSplitter(self.holder)
        window._left_column_splitter = QtWidgets.QSplitter(self.holder)
        window.status_panel = QtWidgets.QWidget(self.holder)
        window._conditions_toggle_action = _A3QAction("conditions")
        window._layers_toggle_action = _A3QAction("layers")
        window._pan_toggle_action = _A3QAction("pan")
        window._status_bar_action = _A3QAction("status")
        for action in (
            window._conditions_toggle_action,
            window._layers_toggle_action,
            window._pan_toggle_action,
            window._status_bar_action,
        ):
            action.setCheckable(True)
        self.ensured = []
        window._ensure_sidebar_column_visible = lambda: self.ensured.append("column")
        window._ensure_pan_pane_visible = lambda: self.ensured.append("pan")
        window._ensure_sidebar_pane_visible = lambda index: self.ensured.append(index)
        return window

    def test_the_left_column_is_shown_for_any_visible_left_sidebar_or_the_pan(self):
        window = self._sidebar_window()
        for (
            conditions_hidden,
            layers_hidden,
            pan_hidden,
            left_hidden,
            column_hidden,
        ) in (
            (True, True, True, True, True),
            (False, True, True, False, False),
            (True, False, True, False, False),
            (True, True, False, True, False),
            (False, False, False, False, False),
        ):
            with self.subTest(
                conditions_hidden=conditions_hidden,
                layers_hidden=layers_hidden,
                pan_hidden=pan_hidden,
            ):
                window._conditions_sidebar.setHidden(conditions_hidden)
                window._bid_layers_sidebar.setHidden(layers_hidden)
                window._pan_sidebar.setHidden(pan_hidden)
                window._sync_left_splitter_visibility()
                self.assertEqual(window._left_splitter.isHidden(), left_hidden)
                self.assertEqual(window._left_column_splitter.isHidden(), column_hidden)

    def test_sidebar_toggles_change_the_action_first_and_only_then_the_pane(self):
        window = self._sidebar_window()
        for setter, getter, action_name, widget_name, ensured in (
            (
                "set_pan_sidebar_visible",
                "is_pan_sidebar_visible",
                "_pan_toggle_action",
                "_pan_sidebar",
                ["column", "pan"],
            ),
            (
                "set_layers_sidebar_visible",
                "is_layers_sidebar_visible",
                "_layers_toggle_action",
                "_bid_layers_sidebar",
                [1],
            ),
            (
                "set_conditions_sidebar_visible",
                "is_conditions_sidebar_visible",
                "_conditions_toggle_action",
                "_conditions_sidebar",
                [0],
            ),
        ):
            with self.subTest(setter=setter):
                action = getattr(window, action_name)
                widget = getattr(window, widget_name)
                for sidebar in (
                    window._conditions_sidebar,
                    window._bid_layers_sidebar,
                    window._pan_sidebar,
                ):
                    sidebar.setHidden(True)
                action.setChecked(False)
                self.ensured.clear()
                getattr(window, setter)(True)
                # the action owns the change: the pane waits for its toggled handler
                self.assertTrue(action.isChecked())
                self.assertTrue(widget.isHidden())
                self.assertEqual(self.ensured, [])
                window._left_splitter.setHidden(True)
                window._left_column_splitter.setHidden(True)
                getattr(window, setter)(True)
                self.assertFalse(widget.isHidden())
                self.assertIs(getattr(window, getter)(), True)
                self.assertEqual(self.ensured, ensured)
                self.assertFalse(window._left_column_splitter.isHidden())
                if setter != "set_pan_sidebar_visible":
                    self.assertFalse(window._left_splitter.isHidden())
                self.ensured.clear()
                getattr(window, setter)(False)
                self.assertFalse(action.isChecked())
                getattr(window, setter)(False)
                self.assertTrue(widget.isHidden())
                self.assertIs(getattr(window, getter)(), False)
                self.assertEqual(self.ensured, [])
                self.assertTrue(window._left_column_splitter.isHidden())

    def test_the_status_panel_follows_its_action_without_feeding_back(self):
        window = self._sidebar_window()
        toggles = []
        window._status_bar_action.toggled.connect(toggles.append)
        window.status_panel.setHidden(False)
        window._status_bar_action.setChecked(True)
        toggles.clear()
        window.set_status_bar_visible(False)
        self.assertTrue(window.status_panel.isHidden())
        self.assertIs(window.is_status_bar_visible(), False)
        self.assertFalse(window._status_bar_action.isChecked())
        self.assertFalse(window._status_bar_action.signalsBlocked())
        window.set_status_bar_visible(True)
        self.assertIs(window.is_status_bar_visible(), True)
        self.assertTrue(window._status_bar_action.isChecked())
        self.assertEqual(toggles, [])


class _A3Splitter:
    """Minimal QSplitter stand-in with exact integer sizes (no handle or layout)."""

    def __init__(self, sizes, extent=0):
        self._sizes = list(sizes)
        self.extent = extent
        self.applied = []

    def sizes(self):
        return list(self._sizes)

    def setSizes(self, sizes):
        self.applied.append(list(sizes))
        self._sizes = list(sizes)

    def height(self):
        return self.extent

    def width(self):
        return self.extent


class MainWindowA3SplitterBoundaryTests(unittest.TestCase):
    """Exact pixel arithmetic at the one-pixel and tiny-total boundaries."""

    def _window(self, **splitters):
        window = MainWindow.__new__(MainWindow)
        window._last_takeoff_splitter_sizes = []
        window._last_left_splitter_sizes = []
        window._last_left_column_splitter_sizes = []
        window._takeoff_splitter = splitters.get("takeoff", _A3Splitter([0, 0]))
        window._left_splitter = splitters.get("left", _A3Splitter([0, 0]))
        window._left_column_splitter = splitters.get("column", _A3Splitter([0, 0]))
        return window

    def test_a_one_pixel_sidebar_is_remembered_and_negative_sizes_clamp_to_zero(self):
        window = self._window(takeoff=_A3Splitter([1, 399]))
        self.assertEqual(window.get_takeoff_splitter_sizes(), [1, 399])
        self.assertEqual(window._last_takeoff_splitter_sizes, [1, 399])
        window._takeoff_splitter = _A3Splitter([-4, 10])
        self.assertEqual(window.get_takeoff_splitter_sizes(), [0, 10])
        self.assertEqual(window._last_takeoff_splitter_sizes, [1, 399])
        window.set_takeoff_splitter_sizes([1, 0])
        self.assertEqual(window._last_takeoff_splitter_sizes, [1, 0])
        self.assertEqual(window._takeoff_splitter.applied, [[1, 0]])
        window.set_takeoff_splitter_sizes([0, 1])
        self.assertEqual(window._last_takeoff_splitter_sizes, [1, 0])
        self.assertEqual(window._takeoff_splitter.applied[-1], [0, 1])
        window.set_takeoff_splitter_sizes([-3, 0])
        self.assertEqual(len(window._takeoff_splitter.applied), 2)

    def test_the_left_splitter_boundaries_are_one_pixel_per_pane(self):
        window = self._window(left=_A3Splitter([1, 1]))
        self.assertEqual(window.get_left_splitter_sizes(), [1, 1])
        self.assertEqual(window._last_left_splitter_sizes, [1, 1])
        for sizes in ([0, 1], [1, 0], [7], [-2, 9]):
            window._left_splitter = _A3Splitter(sizes)
            window.get_left_splitter_sizes()
            self.assertEqual(window._last_left_splitter_sizes, [1, 1], sizes)
        window._left_splitter = _A3Splitter([-2, 9])
        self.assertEqual(window.get_left_splitter_sizes(), [0, 9])
        window = self._window()
        window.set_left_splitter_sizes([1, 1])
        self.assertEqual(window._last_left_splitter_sizes, [1, 1])
        for sizes in ([0, 1], [1, 0], [5]):
            window.set_left_splitter_sizes(sizes)
            self.assertEqual(window._last_left_splitter_sizes, [1, 1], sizes)
            self.assertEqual(window._left_splitter.applied[-1], sizes)
        window.set_left_splitter_sizes([-1, 1])
        self.assertEqual(window._left_splitter.applied[-1], [0, 1])
        applied = len(window._left_splitter.applied)
        window.set_left_splitter_sizes([-1, 0])
        self.assertEqual(len(window._left_splitter.applied), applied)

    def test_the_left_column_splitter_boundaries_are_exactly_two_one_pixel_panes(self):
        window = self._window(column=_A3Splitter([1, 1]))
        window.get_left_column_splitter_sizes()
        self.assertEqual(window._last_left_column_splitter_sizes, [1, 1])
        for sizes in ([0, 1], [1, 0], [3], [-1, 4]):
            window._left_column_splitter = _A3Splitter(sizes)
            result = window.get_left_column_splitter_sizes()
            self.assertEqual(result, [max(0, s) for s in sizes])
            self.assertEqual(window._last_left_column_splitter_sizes, [1, 1], sizes)
        window = self._window()
        window.set_left_column_splitter_sizes([1, 1])
        self.assertEqual(window._left_column_splitter.applied, [[1, 1]])
        self.assertEqual(window._last_left_column_splitter_sizes, [1, 1])
        window.set_left_column_splitter_sizes([0, 2])
        window.set_left_column_splitter_sizes([2, 0])
        window.set_left_column_splitter_sizes([1, 0])
        self.assertEqual(
            window._left_column_splitter.applied[-3:], [[0, 2], [2, 0], [1, 0]]
        )
        self.assertEqual(window._last_left_column_splitter_sizes, [1, 1])
        window.set_left_column_splitter_sizes([-1, 0])
        window.set_left_column_splitter_sizes([1])
        window.set_left_column_splitter_sizes([1, 1, 1])
        self.assertEqual(len(window._left_column_splitter.applied), 4)

    def test_reopening_a_left_pane_at_tiny_totals_keeps_both_panes_visible(self):
        cases = (
            # sizes, extent, saved, index -> expected
            ([0, 1], 0, [], 0, [1, 1]),
            ([0, 3], 0, [], 0, [1, 2]),
            ([3, 0], 0, [], 1, [2, 1]),
            ([0, 1], 9, [], 0, [4, 5]),
            ([0, 1], 9, [], 0, [4, 5]),
            ([0, 1], 0, [1, 1], 0, [1, 1]),
            ([0, 2], 0, [1, 1], 0, [1, 1]),
            ([0, 3], 0, [1, 1], 0, [2, 1]),
            ([0, 3], 0, [1, 2], 0, [1, 2]),
            ([0, 1], 12, [3, 1], 0, [9, 3]),
        )
        for sizes, extent, saved, index, expected in cases:
            with self.subTest(sizes=sizes, extent=extent, saved=saved, index=index):
                window = self._window(left=_A3Splitter(sizes, extent))
                window._last_left_splitter_sizes = saved
                window._ensure_left_splitter_pane_visible(index)
                self.assertEqual(window._left_splitter.sizes(), expected)
        window = self._window(left=_A3Splitter([5, 6]))
        window._ensure_left_splitter_pane_visible(1)
        self.assertEqual(window._left_splitter.applied, [])

    def test_reopening_the_pan_pane_clamps_to_the_available_height(self):
        cases = (
            # sizes, extent, saved -> expected
            ([0, 3], 0, [], [min(max(1, _A3_PAN_DEFAULT_HEIGHT), 2), 1]),
            ([0, 1], 0, [1, 1], [1, 1]),
            ([0, 2], 0, [1, 1], [1, 1]),
            ([0, 3], 0, [1, 1], [2, 1]),
            ([0, 3], 0, [1, 3], [1, 2]),
            ([0, 3], 0, [3, 1], [2, 1]),
            ([0, 200], 0, [1, 1], [100, 100]),
            (
                [0, 200],
                0,
                [0, 5],
                [
                    min(max(1, _A3_PAN_DEFAULT_HEIGHT), 199),
                    200 - min(max(1, _A3_PAN_DEFAULT_HEIGHT), 199),
                ],
            ),
            (
                [0, 200],
                0,
                [5, 0],
                [
                    min(max(1, _A3_PAN_DEFAULT_HEIGHT), 199),
                    200 - min(max(1, _A3_PAN_DEFAULT_HEIGHT), 199),
                ],
            ),
            ([0, 10], 500, [1, 3], [125, 375]),
            (
                [0, 1000],
                0,
                [5, 0],
                [_A3_PAN_DEFAULT_HEIGHT, 1000 - _A3_PAN_DEFAULT_HEIGHT],
            ),
            (
                [0, 1000],
                0,
                [0, 5],
                [_A3_PAN_DEFAULT_HEIGHT, 1000 - _A3_PAN_DEFAULT_HEIGHT],
            ),
            # saved ratio rounds up to the whole height: clamped to total - 1
            ([0, 2], 0, [3, 1], [1, 1]),
            ([0, 3], 0, [7, 1], [2, 1]),
        )
        for sizes, extent, saved, expected in cases:
            with self.subTest(sizes=sizes, extent=extent, saved=saved):
                window = self._window(column=_A3Splitter(sizes, extent))
                window._last_left_column_splitter_sizes = saved
                window._ensure_pan_pane_visible()
                self.assertEqual(window._left_column_splitter.sizes(), expected)
        for sizes in ([5, 6], [1, 0], [4]):
            window = self._window(column=_A3Splitter(sizes))
            window._ensure_pan_pane_visible()
            self.assertEqual(window._left_column_splitter.applied, [], sizes)
        window = self._window(column=_A3Splitter([0]))
        window._ensure_pan_pane_visible()
        self.assertEqual(window._left_column_splitter.applied, [])

    def test_reopening_the_sidebar_column_clamps_to_the_splitter_width(self):
        cases = (
            # sizes, width, saved -> expected
            ([0, 3], 0, [2, 1], [2, 1]),
            ([0, 3], 0, [1, 2], [1, 2]),
            ([0, 3], 0, [3, 0], [2, 1]),
            ([0, 3], 0, [9, 0], [2, 1]),
            ([0, 3], 0, [0, 3], [2, 1]),
            ([0, 2000], 0, [], [500, 1500]),
            ([0, 2002], 0, [], [500, 1502]),
            ([0, 2000], 0, [0, 5], [500, 1500]),
            ([0, 2000], 0, [-5, 5], [500, 1500]),
            ([0, 1], 4000, [], [1000, 3000]),
            ([0, 1], 0, [1, 1], [1, 1]),
        )
        for sizes, width, saved, expected in cases:
            with self.subTest(sizes=sizes, width=width, saved=saved):
                window = self._window(takeoff=_A3Splitter(sizes, width))
                window._last_takeoff_splitter_sizes = saved
                window._ensure_sidebar_column_visible()
                self.assertEqual(window._takeoff_splitter.sizes(), expected)
        window = self._window(takeoff=_A3Splitter([1, 0]))
        window._ensure_sidebar_column_visible()
        self.assertEqual(window._takeoff_splitter.applied, [])

    def test_scaling_keeps_each_saved_pane_at_least_one_pixel(self):
        scale = MainWindow._scale_left_splitter_sizes
        self.assertEqual(scale([1, 1], 2), [1, 1])
        self.assertEqual(scale([1, 1], 3), [2, 1])
        self.assertEqual(scale([3, 1], 4), [3, 1])
        self.assertEqual(scale([0, 5], 6), [1, 5])
        self.assertEqual(scale([5, 0], 6), [5, 1])
        self.assertEqual(scale([0, 0], 6), [1, 5])
        # a saved total of exactly one pixel is a real total, not the zero fallback
        self.assertEqual(scale([1, 0], 6), [5, 1])
        self.assertEqual(scale([0, 1], 6), [1, 5])


from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_DIMENSION as _A3_DIMENSION,
    ANNOTATION_TYPE_HIGHLIGHT as _A3_HIGHLIGHT,
    ANNOTATION_TYPE_HOTLINK as _A3_HOTLINK,
    ANNOTATION_TYPE_TEXT as _A3_TEXT,
)
from ost_visualizer.domain.entities.annotation_style import (
    AnnotationStyle as _A3AnnotationStyle,
)
from ost_visualizer.domain.entities.config import Config as _A3Config
from ost_visualizer.domain.entities.font_definition import (
    FontDefinition as _A3FontDefinition,
)


class MainWindowA3AnnotationStyleTests(unittest.TestCase):
    """Active annotation styles: controls refresh and the persisted defaults."""

    def _window(self):
        window = MainWindow.__new__(MainWindow)
        self.config = _A3Config()
        self.updates = []
        self.saves = []
        window._config_service = SimpleNamespace(
            get_config_snapshot=lambda: self.config,
            update_app_options=lambda update: self.updates.append(update),
        )
        window._workspace_state_coordinator = SimpleNamespace(
            request_save=lambda: self.saves.append("save")
        )
        return window

    def test_a_font_definition_names_bold_italic_and_regular_faces(self):
        for bold, italic, name, weight in (
            (False, False, "Regular", 400),
            (True, False, "Bold", 700),
            (False, True, "Italic", 400),
            (True, True, "Bold Italic", 700),
        ):
            with self.subTest(bold=bold, italic=italic):
                style = _A3AnnotationStyle(
                    font_name="Arial",
                    font_size=14,
                    font_bold=bold,
                    font_italic=italic,
                    font_underline=bold != italic,
                )
                self.assertEqual(
                    MainWindow._font_definition_for_style(style),
                    _A3FontDefinition(
                        family="Arial",
                        style_name=name,
                        point_size=14,
                        weight=weight,
                        italic=italic,
                        underline=bold != italic,
                    ),
                )

    def test_config_updates_only_carry_what_the_changed_tool_persists(self):
        window = self._window()
        style = _A3AnnotationStyle(color="#112233", font_name="Arial", font_size=12)
        font = MainWindow._font_definition_for_style(style)

        def update(kind, **kwargs):
            return window._config_update_for_annotation_style(kind, style, **kwargs)

        result = update(_A3_TEXT, color="#112233", font_changed=False)
        self.assertEqual(result.default_text_color, "#112233")
        self.assertEqual(result.default_text_font, self.config.default_text_font)
        result = update(_A3_TEXT, color=None, font_changed=True)
        self.assertEqual(result.default_text_font, font)
        self.assertEqual(result.default_text_color, self.config.default_text_color)
        result = update(_A3_DIMENSION, color="#112233", font_changed=True)
        self.assertEqual(result.default_dimension_annotation_color, "#112233")
        self.assertEqual(result.default_dimension_annotation_font, font)
        self.assertEqual(result.default_text_color, self.config.default_text_color)
        result = update(_A3_DIMENSION, color=None, font_changed=False)
        self.assertIsNone(result)
        result = update(_A3_HIGHLIGHT, color="#112233", font_changed=True)
        self.assertEqual(result.default_highlight_color, "#112233")
        self.assertEqual(
            result.default_hotlink_color, self.config.default_hotlink_color
        )
        result = update(_A3_HOTLINK, color="#112233", font_changed=False)
        self.assertEqual(result.default_hotlink_color, "#112233")
        self.assertEqual(
            result.default_highlight_color, self.config.default_highlight_color
        )
        self.assertIsNone(update(_A3_HIGHLIGHT, color=None, font_changed=True))
        self.assertIsNone(update(_A3_HOTLINK, color=None, font_changed=True))
        self.assertIsNone(update("rectangle", color="#112233", font_changed=True))

    def test_setting_a_style_refreshes_controls_and_persists_the_matching_default(self):
        window = self._window()
        refreshed = []
        window._refresh_annotation_style_controls = lambda kind=None: refreshed.append(
            kind
        )
        style = _A3AnnotationStyle(color="#445566")
        calls = []
        with patch.object(
            main_window_module,
            "set_active_annotation_style_for_tool",
            side_effect=lambda kind, **kwargs: calls.append((kind, kwargs)) or style,
        ):
            result = window.set_annotation_style_for_tool(
                _A3_HIGHLIGHT, color="#445566", line_width=3.0
            )
        self.assertIs(result, style)
        self.assertEqual(
            calls,
            [
                (
                    _A3_HIGHLIGHT,
                    {
                        "color": "#445566",
                        "line_width": 3.0,
                        "font_name": None,
                        "font_size": None,
                        "font_bold": None,
                        "font_italic": None,
                        "font_underline": None,
                        "text_align": None,
                    },
                )
            ],
        )
        self.assertEqual(refreshed, [_A3_HIGHLIGHT])
        (update,) = self.updates
        self.assertEqual(update.default_highlight_color, "#445566")
        self.assertEqual(self.saves, ["save"])

    def test_every_font_attribute_counts_as_a_font_change_and_persist_can_be_off(self):
        for field in (
            "font_name",
            "font_size",
            "font_bold",
            "font_italic",
            "font_underline",
        ):
            with self.subTest(field=field):
                window = self._window()
                window._refresh_annotation_style_controls = lambda kind=None: None
                style = _A3AnnotationStyle(font_name="Arial", font_size=9)
                value = {
                    "font_name": "Arial",
                    "font_size": 9,
                    "font_bold": False,
                    "font_italic": False,
                    "font_underline": False,
                }[field]
                with patch.object(
                    main_window_module,
                    "set_active_annotation_style_for_tool",
                    return_value=style,
                ):
                    window.set_annotation_style_for_tool(_A3_TEXT, **{field: value})
                (update,) = self.updates
                self.assertEqual(
                    update.default_text_font,
                    MainWindow._font_definition_for_style(style),
                )
                self.assertEqual(
                    update.default_text_color, self.config.default_text_color
                )
        window = self._window()
        window._refresh_annotation_style_controls = lambda kind=None: None
        with patch.object(
            main_window_module,
            "set_active_annotation_style_for_tool",
            return_value=_A3AnnotationStyle(),
        ):
            window.set_annotation_style_for_tool(
                _A3_TEXT, color="#000000", persist=False
            )
            self.assertEqual((self.updates, self.saves), ([], []))
            window.set_annotation_style_for_tool("rectangle", line_width=2.0)
        self.assertEqual((self.updates, self.saves), ([], ["save"]))

    def test_a_color_only_change_does_not_persist_the_font(self):
        window = self._window()
        window._refresh_annotation_style_controls = lambda kind=None: None
        style = _A3AnnotationStyle(
            color="#778899", font_name="Courier New", font_size=31
        )
        self.assertNotEqual(
            MainWindow._font_definition_for_style(style), self.config.default_text_font
        )
        with patch.object(
            main_window_module,
            "set_active_annotation_style_for_tool",
            return_value=style,
        ):
            window.set_annotation_style_for_tool(_A3_TEXT, color="#778899")
        (update,) = self.updates
        self.assertEqual(update.default_text_color, "#778899")
        self.assertEqual(update.default_text_font, self.config.default_text_font)

    def test_replacing_all_styles_refreshes_controls_and_saves_only_on_request(self):
        window = self._window()
        window._config_model = SimpleNamespace(snapshot=lambda: "config-snapshot")
        refreshed = []
        window._refresh_annotation_style_controls = lambda kind=None: refreshed.append(
            kind
        )
        applied = []
        styles = {_A3_TEXT: _A3AnnotationStyle()}
        with patch.object(
            main_window_module,
            "set_active_annotation_styles_by_tool",
            side_effect=lambda given, config: applied.append((given, config)),
        ):
            window.set_annotation_styles_by_tool(styles)
            self.assertEqual(self.saves, [])
            window.set_annotation_styles_by_tool(styles, persist=True)
        self.assertEqual(applied, [(styles, "config-snapshot")] * 2)
        self.assertEqual(refreshed, [None, None])
        self.assertEqual(self.saves, ["save"])

    def test_style_controls_refresh_the_toolbar_icons_and_every_open_detached_window(
        self,
    ):
        window = self._window()
        window._plan_tool_actions = {"actions": True}
        refreshed = []
        annotation = SimpleNamespace(
            refresh_annotation_style=lambda kind: refreshed.append(("annotation", kind))
        )
        window.get_annotation_window = lambda: annotation
        window.get_view_window = lambda: None
        with patch.object(
            main_window_module, "apply_annotation_tool_icon_color"
        ) as colors:
            window._refresh_annotation_style_controls(_A3_TEXT)
            window._refresh_annotation_style_controls()
        self.assertEqual(
            [call.args for call in colors.call_args_list],
            [({"actions": True}, _A3_TEXT), ({"actions": True}, None)],
        )
        self.assertEqual(refreshed, [("annotation", _A3_TEXT), ("annotation", None)])

    def test_style_getters_read_the_active_styles(self):
        window = MainWindow.__new__(MainWindow)
        with patch.object(
            main_window_module,
            "get_active_annotation_style_for_tool",
            return_value="one",
        ) as one, patch.object(
            main_window_module,
            "get_active_annotation_styles_by_tool",
            return_value="all",
        ):
            self.assertEqual(window.get_annotation_style_for_tool(_A3_TEXT), "one")
            self.assertEqual(window.get_annotation_styles_by_tool(), "all")
        one.assert_called_once_with(_A3_TEXT)


class MainWindowA3ShellAccessorTests(unittest.TestCase):
    """Splash, readiness and the small accessors other coordinators call."""

    def test_the_splash_screen_is_finished_once_when_the_window_is_shown(self):
        _app()
        window = MainWindow.__new__(MainWindow)
        QtWidgets.QMainWindow.__init__(window)
        self.addCleanup(window.deleteLater)
        finished = []
        window.splash_screen = SimpleNamespace(finish=lambda w: finished.append(w))
        scheduled = []
        with patch.object(
            QtCore.QTimer,
            "singleShot",
            side_effect=lambda delay, callback: scheduled.append((delay, callback)),
        ):
            window.showEvent(QtGui.QShowEvent())
            window.showEvent(QtGui.QShowEvent())
        self.assertEqual(finished, [window])
        self.assertIsNone(window.splash_screen)
        self.assertEqual(scheduled, [(0, window._mark_main_window_ready)] * 2)

    def test_marking_the_window_ready_releases_waiting_imports(self):
        window = MainWindow.__new__(MainWindow)
        window._main_window_ready = False
        released = []
        window._schedule_pending_project_file_imports = lambda: released.append(
            window._main_window_ready
        )
        window._mark_main_window_ready()
        self.assertEqual(released, [True])

    def test_the_update_service_is_optional(self):
        window = MainWindow.__new__(MainWindow)

        def missing(name):
            raise KeyError(name)

        window.app_controller = SimpleNamespace(get_service=missing)
        self.assertIsNone(window._resolve_update_service())
        window.app_controller = SimpleNamespace(get_service=lambda name: (name, "svc"))
        self.assertEqual(
            window._resolve_update_service(), ("update_check_service", "svc")
        )

    def test_delegating_accessors_return_the_owned_widgets_and_services(self):
        window = MainWindow.__new__(MainWindow)
        names = {
            "get_view_stack": "_view_stack",
            "get_left_splitter": "_left_splitter",
            "get_takeoff_splitter": "_takeoff_splitter",
            "get_left_column_splitter": "_left_column_splitter",
            "get_layers_toggle_action": "_layers_toggle_action",
            "get_conditions_toggle_action": "_conditions_toggle_action",
            "get_pan_toggle_action": "_pan_toggle_action",
            "get_mesh_window_action": "_mesh_window_action",
            "get_annotation_window_action": "_annotation_window_action",
            "get_view_window_action": "_view_window_action",
            "get_status_bar_action": "_status_bar_action",
            "get_conditions_sidebar": "_conditions_sidebar",
            "get_condition_summary_tab": "_condition_summary_tab",
        }
        for getter, attribute in names.items():
            marker = object()
            setattr(window, attribute, marker)
            self.assertIs(getattr(window, getter)(), marker, getter)
        window._plan_tools_toolbar = "plan"
        window._overlay_tools_toolbar = "overlay"
        window._view_toolbar = "view"
        window._main_toolbar = "main"
        window._cover_sheet_button = "cover"
        self.assertEqual(
            window.get_workspace_toolbars(), ["main", "plan", "overlay", "view"]
        )
        self.assertEqual(window.get_toolbar_text_buttons(), ["cover"])
        window.project_view = SimpleNamespace(
            top_tree="tree",
            get_expanded_node_keys=lambda: ["k"],
            set_expanded_node_keys=lambda keys: setattr(window, "_keys", keys),
            is_group_by_job_status=lambda: True,
            get_selected_node_state=lambda: {"n": 1},
            set_selected_node_state=lambda node: setattr(window, "_node", node),
        )
        self.assertEqual(window.get_project_tree(), "tree")
        self.assertEqual(window.get_project_expanded_node_keys(), ["k"])
        window.set_project_expanded_node_keys(["a"])
        self.assertEqual(window._keys, ["a"])
        self.assertIs(window.is_project_group_by_job_status(), True)
        self.assertEqual(window.get_project_selected_node(), {"n": 1})
        window.set_project_selected_node({"n": 2})
        self.assertEqual(window._node, {"n": 2})
        window._conditions_sidebar = SimpleNamespace(
            is_group_by_type_enabled=lambda: True
        )
        self.assertIs(window.is_conditions_group_by_type_enabled(), True)
        window._condition_summary_tab = SimpleNamespace(grouping="g")
        self.assertEqual(window.get_summary_grouping(), "g")

    def test_tab_state_questions_and_delegates(self):
        window = MainWindow.__new__(MainWindow)
        window.tab_widget = SimpleNamespace(currentIndex=lambda: TAB_INDEX_SUMMARY)
        self.assertIs(window.is_summary_tab_active(), True)
        self.assertIs(window.is_takeoff_tab_active(), False)
        window.tab_widget = SimpleNamespace(currentIndex=lambda: TAB_INDEX_PROJECTS)
        self.assertIs(window.is_summary_tab_active(), False)
        log = []
        window.license_coordinator = SimpleNamespace(
            show_dialog=lambda: log.append("dialog")
        )
        window.show_license_dialog()
        window._takeoff_toolbar_visibility = SimpleNamespace(
            apply_hidden_items=lambda items: log.append(items)
        )
        window.apply_takeoff_toolbar_visibility(("a", "b"))
        self.assertEqual(log, ["dialog", ("a", "b")])

    def test_several_imports_into_an_orphan_target_say_so_once(self):
        window = _startup_import__startup_import_window()
        results = [
            import_args_use_case.ProjectFileImportResult(
                source_path=f"{name}.ost", success=True, message="ok"
            )
            for name in ("a", "b")
        ]
        text = window._format_project_file_import_details(
            import_args_use_case.ProjectFileImportBatchResult(
                results=results, import_as_orphaned_due_to_deleted_target=True
            )
        )
        self.assertEqual(
            text.splitlines()[0],
            "Successfully imported 2 project files into the database.",
        )
        self.assertEqual(len(text.splitlines()), 2)
        self.assertIn("orphaned", text.splitlines()[1])
        plain = window._format_project_file_import_details(
            import_args_use_case.ProjectFileImportBatchResult(results=results)
        )
        self.assertEqual(
            plain, "Successfully imported 2 project files into the database."
        )
        single = window._format_project_file_import_details(
            import_args_use_case.ProjectFileImportBatchResult(
                results=results[:1], import_as_orphaned_due_to_deleted_target=True
            )
        )
        self.assertIn("'a.ost' as orphaned", single)


# ---------------------------------------------------------------------------
# Real-MainWindow composition wiring (A3 round 2): one real window is built from the
# configured application with spying wrappers installed on the MainWindow methods the
# constructor connects to Qt signals, then every connection is exercised.
# ---------------------------------------------------------------------------
import logging as _a3_logging
import tempfile as _a3_tempfile
from contextlib import ExitStack as _A3ExitStack
from pathlib import Path as _A3Path
from ost_visualizer.config.di_config import configure_application as _a3_configure
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.presentation.handlers.export_handler import ExportHandler
from ost_visualizer.presentation.actions.action_ids import (
    ACTION_NEW_DATABASE,
    ACTION_NEW_FOLDER,
    ACTION_NEW_PROJECT,
    ACTION_OPEN_FILES,
)
from ost_visualizer.presentation.config import MAIN_MARGINS, NO_SPACING
from ost_visualizer.presentation.utils.plan_tool_registry import (
    PLAN_ANNOTATION_TOOL_SPECS,
)
from ost_visualizer.infrastructure.logging.logger_factory import (
    LoggerFactory as _A3LoggerFactory,
)
from ost_visualizer.presentation.handlers.plan_view_action_handler import (
    PlanViewActionHandler as _A3PlanViewActionHandler,
)
from ost_visualizer.presentation.coordinators.license_ui_coordinator import (
    LicenseUICoordinator as _A3LicenseUICoordinator,
)
from ost_visualizer.presentation.coordinators.workspace_state_coordinator import (
    WorkspaceStateCoordinator as _A3WorkspaceStateCoordinator,
)
from ost_visualizer.presentation.services.mcp_context_bridge import (
    McpContextBridge as _A3McpContextBridge,
)
from ost_visualizer.presentation.services.ai_takeoff_bridge import (
    TakeoffCommandBridge as _A3TakeoffCommandBridge,
)
from ost_visualizer.presentation.managers.app_config_presentation_manager import (
    AppConfigPresentationManager as _A3AppConfigPresentationManager,
)
from ost_visualizer.presentation.configurators.window_configurator import (
    WindowConfigurator as _A3WindowConfigurator,
)
from ost_visualizer.presentation.handlers.cover_sheet_handler import (
    CoverSheetHandler as _A3CoverSheetHandler,
)
from ost_visualizer.presentation.services.ai_sidecar_rebind_prompt import (
    AiSidecarRebindPrompt as _A3AiSidecarRebindPrompt,
)


class MainWindowA3RealWiringTests(unittest.TestCase):
    SPIED = (
        "_copy_selected",
        "_cut_selected",
        "_paste_clipboard",
        "_delete_selected",
        "_duplicate_selected",
        "_select_all",
        "_on_tab_changed",
        "set_layers_sidebar_visible",
        "set_conditions_sidebar_visible",
        "set_pan_sidebar_visible",
        "set_status_bar_visible",
        "_on_workspace_toolbar_visibility_changed",
        "_on_ai_changeset_finished",
    )

    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls.calls = []
        cls.timer_calls = []
        cls.stack = _A3ExitStack()
        cls.tmp = _a3_tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = _A3Path(cls.tmp.name)
        stack = cls.stack
        stack.enter_context(patch.object(_A3Path, "home", return_value=root))
        stack.enter_context(patch.object(_A3LoggerFactory, "configure"))
        stack.enter_context(
            patch.object(
                _A3LoggerFactory,
                "get_logger",
                return_value=_a3_logging.getLogger("test.main_window.wiring"),
            )
        )
        stack.enter_context(
            patch.object(
                QtCore.QTimer,
                "singleShot",
                side_effect=lambda delay, callback: cls.timer_calls.append(
                    (delay, callback)
                ),
            )
        )
        stack.enter_context(
            patch(
                "ost_visualizer.presentation.utils.annotation_defaults."
                "resolve_font_definition",
                side_effect=lambda definition: definition,
            )
        )
        stack.enter_context(
            patch.object(
                MainWindow,
                "_show_update_dialog",
                lambda self, info: cls.calls.append(("_show_update_dialog", (info,))),
            )
        )

        def spy(name):
            original = getattr(MainWindow, name)

            def wrapper(self, *args, **kwargs):
                cls.calls.append((name, args))
                return original(self, *args, **kwargs)

            return wrapper

        for name in cls.SPIED:
            stack.enter_context(patch.object(MainWindow, name, spy(name)))

        def handler_spy(name):
            original = getattr(_A3PlanViewActionHandler, name)

            def wrapper(self, *args, **kwargs):
                cls.calls.append(("handler." + name, args))
                return original(self, *args, **kwargs)

            return wrapper

        for name in (
            "on_elements_deleted",
            "on_assign_to_area",
            "on_reassign_condition",
            "on_set_negative",
            "on_set_curved",
        ):
            stack.enter_context(
                patch.object(_A3PlanViewActionHandler, name, handler_spy(name))
            )

        def class_spy(owner, name, tag):
            original = getattr(owner, name)

            def wrapper(self, *args, **kwargs):
                cls.calls.append((tag, args))
                return original(self, *args, **kwargs)

            return wrapper

        for owner, name, tag in (
            (_A3LicenseUICoordinator, "initialize", "license.initialize"),
            (
                _A3LicenseUICoordinator,
                "on_license_status_changed",
                "license.status_changed",
            ),
            (
                _A3WorkspaceStateCoordinator,
                "restore_initial_state",
                "workspace.restore_initial_state",
            ),
            (_A3McpContextBridge, "start", "mcp.start"),
            (_A3TakeoffCommandBridge, "start", "ai_bridge.start"),
            (_A3AppConfigPresentationManager, "apply", "config.apply"),
            (_A3WindowConfigurator, "configure", "configurator.configure"),
            (_A3CoverSheetHandler, "open_cover_sheet", "cover_sheet.open"),
            (_A3AiSidecarRebindPrompt, "offer", "ai_rebind.offer"),
        ):
            stack.enter_context(patch.object(owner, name, class_spy(owner, name, tag)))
        cls.container = _a3_configure(log_dir=root / "logs")
        cls.controller = cls.container.get("app_controller")
        cls.saved_rect_style = _A3AnnotationStyle(color="#123456", line_width=7.0)
        model = cls.controller.get_service("workspace_state_model")
        saved_state = model.state
        saved_state.takeoff_workspace.annotation_styles = {"rect": cls.saved_rect_style}
        model.update_state(saved_state)
        cls.window = MainWindow(cls.controller)
        cls.construction_log = list(cls.calls)
        cls.calls.clear()

    @classmethod
    def tearDownClass(cls):
        window = cls.window
        try:
            window._workspace_state_coordinator.cleanup()
            window.event_coordinator.cleanup()
            window.handlers.ui_event.cleanup()
            window.license_coordinator.cleanup()
            window.ui_access_manager.cleanup()
            window._mcp_context_bridge.cleanup()
            window._ai_takeoff_bridge.cleanup()
            window._ai_approval.cleanup()
            window._ai_rebind_prompt.cleanup()
            window._ai_undo_notice.cleanup()
            window._ai_pdf_source.release()
            window._deferred_persistence_manager.cleanup()
            window.hide()
            window.deleteLater()
        finally:
            cls.controller.cleanup()
            cls.app.sendPostedEvents(window, QtCore.QEvent.Type.DeferredDelete)
            cls.stack.close()
            cls.window = None
            cls.controller = None
            cls.container = None
            cls.calls = []
            cls.construction_log = []
            cls.timer_calls = []
            gc.collect()

    def setUp(self):
        self.calls.clear()

    def _toolbar(self):
        return self.window.handlers.ui_event._toolbar

    def test_edit_actions_run_the_matching_main_window_command(self):
        toolbar = self._toolbar()
        for action, name in (
            (toolbar._copy_action, "_copy_selected"),
            (toolbar._cut_action, "_cut_selected"),
            (toolbar._paste_action, "_paste_clipboard"),
            (toolbar._delete_action, "_delete_selected"),
            (toolbar._duplicate_action, "_duplicate_selected"),
            (toolbar._select_all_action, "_select_all"),
        ):
            with self.subTest(name=name):
                self.calls.clear()
                action.triggered.emit()
                self.assertEqual([call[0] for call in self.calls], [name])
        self.assertIs(self.window._select_all_action, toolbar._select_all_action)

    def test_undo_and_redo_actions_request_the_plan_view_history(self):
        toolbar = self._toolbar()
        seen = []
        self.window.plan_view.undo_requested.connect(lambda: seen.append("undo"))
        self.window.plan_view.redo_requested.connect(lambda: seen.append("redo"))
        toolbar._undo_action.triggered.emit()
        toolbar._redo_action.triggered.emit()
        self.assertEqual(seen, ["undo", "redo"])

    def test_sidebar_and_status_toggles_route_their_checked_state(self):
        window = self.window
        for action, name in (
            (window.get_layers_toggle_action(), "set_layers_sidebar_visible"),
            (window.get_conditions_toggle_action(), "set_conditions_sidebar_visible"),
            (window.get_pan_toggle_action(), "set_pan_sidebar_visible"),
            (window.get_status_bar_action(), "set_status_bar_visible"),
        ):
            with self.subTest(name=name):
                self.calls.clear()
                original = action.isChecked()
                action.setChecked(not original)
                self.assertEqual(self.calls[0], (name, (not original,)))
                action.setChecked(original)
                self.assertEqual(self.calls[-1], (name, (original,)))

    def test_every_workspace_toolbar_reports_its_own_visibility(self):
        window = self.window
        for toolbar, key in (
            (window._main_toolbar, window.MAIN_TOOLBAR_KEY),
            (window._plan_tools_toolbar, window.PLAN_TOOLS_TOOLBAR_KEY),
            (window._overlay_tools_toolbar, window.OVERLAY_TOOLS_TOOLBAR_KEY),
            (window._view_toolbar, window.VIEW_TOOLBAR_KEY),
        ):
            with self.subTest(key=key):
                self.calls.clear()
                toolbar.visibilityChanged.emit(False)
                toolbar.visibilityChanged.emit(True)
                self.assertEqual(
                    self.calls,
                    [
                        ("_on_workspace_toolbar_visibility_changed", (key, False)),
                        ("_on_workspace_toolbar_visibility_changed", (key, True)),
                    ],
                )

    def test_tab_changes_reach_the_tab_handler(self):
        self.window.tab_widget.currentChanged.emit(TAB_INDEX_SUMMARY)
        self.assertEqual(self.calls, [("_on_tab_changed", (TAB_INDEX_SUMMARY,))])

    def test_detached_window_managers_notify_the_main_window(self):
        window = self.window
        with patch.object(
            window, "_sync_annotation_window_action"
        ) as annotation_sync, patch.object(
            window, "_sync_view_window_action"
        ) as view_sync:
            window._annotation_view_manager._visibility_changed_callback(False)
            self.assertEqual(annotation_sync.call_count, 1)
            view_sync.reset_mock()
            window._view_window_manager._visibility_changed_callback(False)
            self.assertEqual(view_sync.call_count, 1)

    def test_project_tree_callbacks_are_the_main_window_and_handler_commands(self):
        window = self.window
        tree = window.project_view
        for attribute, expected in (
            ("on_restore_bid", window._restore_project_bids),
            ("on_copy_bids", window._copy_project_bids),
            ("on_paste_bids", window._paste_project_bids),
            ("on_can_paste_bids", window._can_paste_project_bids),
            ("on_duplicate_bid", window._duplicate_project_tree_bid),
            ("on_create_bid", window._create_project_tree_bid),
            ("on_create_project", window._create_project_tree_project),
            ("on_is_active_bid_context", window._project_tree_context_owns_active_bid),
            ("on_multi_selection", window._on_project_multi_selection),
            ("on_menu_command", window._trigger_project_tree_menu_command),
            ("on_menu_command_enabled", window._is_project_tree_menu_command_enabled),
            ("on_export_formats", window._project_tree_export_formats),
            ("on_get_job_statuses", window._get_project_tree_job_statuses),
            ("on_update_bid_job_status", window._update_project_tree_bid_job_status),
            ("on_project_view_options_changed", window._request_workspace_state_save),
            ("on_close_database", window.handlers.file_ops.unload_file_path),
            ("on_delete_bids", window.handlers.delete.delete_bids),
            ("on_empty_deleted_bids", window.handlers.delete.delete_bids),
            ("on_delete_projects", window.handlers.delete.delete_projects),
            ("on_import_project_file", window.handlers.import_.import_project_file),
            ("on_rename_project", window.handlers.delete.rename_project),
            ("on_renumber_conditions", window.handlers.ui_event.renumber_conditions),
            (
                "on_can_renumber_conditions",
                window.handlers.ui_event.can_renumber_conditions,
            ),
            ("on_can_duplicate_bid", window.ui_access_manager.can_duplicate_bid),
            ("on_can_close_database", window.ui_access_manager.can_close_database),
            ("on_can_delete_bids", window.ui_access_manager.can_delete_bids),
            ("on_can_delete_projects", window.ui_access_manager.can_delete_projects),
            ("on_can_create_bid", window.ui_access_manager.can_create_bid),
            ("on_can_create_project", window.ui_access_manager.can_create_project),
            (
                "on_can_update_bid_job_status",
                window.ui_access_manager.can_edit_bid_job_status,
            ),
        ):
            with self.subTest(attribute=attribute):
                self.assertEqual(getattr(tree, attribute), expected)
        self.assertEqual(tree.top_tree.on_move_bids, window._move_project_bids)
        self.assertEqual(tree.top_tree.on_can_move_bids, window._can_move_project_bids)
        self.assertTrue(
            tree.on_can_import_project_file("ost", "C:/x.mdb", None) in (True, False)
        )

    def test_ui_event_coordinator_receives_the_composed_widgets(self):
        window = self.window
        ui_event = window.handlers.ui_event
        self.assertIs(ui_event._tab_widget, window.tab_widget)
        self.assertIs(ui_event._bid_clipboard, window._bid_clipboard)
        self.assertIs(ui_event.plan_view, window.plan_view)
        self.assertIs(ui_event._view_stack, window.get_view_stack())
        self.assertIs(ui_event.takeoff_sidebar, window.takeoff_sidebar)
        self.assertIs(ui_event.opengl_viewer, window.opengl_viewer)
        self.assertIs(ui_event.conditions_sidebar, window._conditions_sidebar)
        self.assertIs(ui_event._plan_view_handler, window._plan_view_handler)

    def test_3d_viewer_requests_reach_the_plan_view_handler(self):
        viewer = self.window.opengl_viewer
        viewer.elements_deleted.emit(["u1"])
        viewer.assign_to_area_requested.emit(["u2"])
        viewer.reassign_condition_requested.emit(["u3"], "c9")
        viewer.set_negative_requested.emit(["u4"], True)
        viewer.set_curved_requested.emit(["u5"], False)
        self.assertEqual(
            self.calls,
            [
                ("handler.on_elements_deleted", (["u1"],)),
                ("handler.on_assign_to_area", (["u2"],)),
                ("handler.on_reassign_condition", (["u3"], "c9")),
                ("handler.on_set_negative", (["u4"], True)),
                ("handler.on_set_curved", (["u5"], False)),
            ],
        )

    def test_persistent_headers_cover_the_four_trees_with_their_semantic_columns(self):
        window = self.window
        controllers = window._header_controllers
        self.assertEqual(
            [
                (c._view_id, c._sorting, c._movable, c._default_sort_column)
                for c in controllers
            ],
            [
                ("project_tree", True, True, "number"),
                ("conditions_sidebar", True, False, "number"),
                ("layers_sidebar", False, True, None),
                ("condition_summary", True, True, "name"),
            ],
        )
        self.assertEqual(
            controllers[0]._column_keys,
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
        )
        self.assertEqual(
            controllers[1]._column_keys,
            ("number", "name", "quantity_1", "quantity_2", "quantity_3"),
        )
        self.assertEqual(controllers[2]._column_keys, ("visible", "layer"))
        self.assertEqual(controllers[2]._persisted_width_keys, frozenset({"layer"}))
        self.assertEqual(
            controllers[3]._column_keys, window._condition_summary_tab.column_keys
        )
        self.assertIs(controllers[0]._view, window.project_view.top_tree)
        self.assertIs(controllers[1]._view, window._conditions_sidebar.tree)
        self.assertIs(controllers[2]._view, window._bid_layers_sidebar.table)
        self.assertIs(controllers[3]._view, window._condition_summary_tab.tree)
        for controller in controllers:
            self.assertIs(
                controller._workspace_state_model, window._workspace_state_model
            )

    def test_the_layers_header_keeps_a_fixed_visibility_column_and_a_free_name_column(
        self,
    ):
        header = self.window._bid_layers_sidebar.table.header()
        self.assertFalse(header.stretchLastSection())
        self.assertEqual(
            header.sectionResizeMode(0), QtWidgets.QHeaderView.ResizeMode.Fixed
        )
        self.assertEqual(
            header.sectionResizeMode(1), QtWidgets.QHeaderView.ResizeMode.Interactive
        )

    def test_summary_column_updates_pause_and_resume_the_summary_header(self):
        window = self.window
        summary_controller = window._header_controllers[-1]
        window._condition_summary_tab.columns_about_to_change.emit(
            tuple(window._condition_summary_tab.column_keys)
        )
        self.assertTrue(summary_controller._columns_updating)
        window._condition_summary_tab.columns_changed.emit()
        self.assertFalse(summary_controller._columns_updating)
        for other in window._header_controllers[:-1]:
            self.assertFalse(other._columns_updating)

    # ---- constructor state and one-shot wiring ---------------------------------
    def test_a_new_window_starts_with_no_pending_startup_work(self):
        window = self.window
        self.assertIs(window._needs_create_database_prompt, False)
        self.assertIs(window._startup_load_complete, False)
        self.assertIs(window._main_window_ready, False)
        self.assertIs(window._project_file_import_scheduled, False)
        self.assertIs(window._project_file_import_running, False)
        self.assertEqual(window._pending_project_file_args, [])
        self.assertIs(window._collaboration_shutdown_pending, False)
        self.assertIs(window._collaboration_shutdown_complete, False)
        self.assertIs(window._collaboration_shutdown_failed, False)
        self.assertIsNone(window.splash_screen)
        self.assertEqual(window._last_left_column_splitter_sizes, [])
        self.assertIs(window._syncing_toolbar_visibility, False)
        self.assertEqual(
            window.get_workspace_toolbar_visibility_state(),
            {
                window.MAIN_TOOLBAR_KEY: True,
                window.VIEW_TOOLBAR_KEY: True,
                window.PLAN_TOOLS_TOOLBAR_KEY: True,
                window.OVERLAY_TOOLS_TOOLBAR_KEY: True,
            },
        )

    def test_ai_takeoffs_are_filed_in_a_dated_session_folder(self):
        import re

        self.assertRegex(
            self.window._ai_applier._session_folder_name,
            re.compile(r"^AI \d{4}-\d{2}-\d{2} \d{2}:\d{2}$"),
        )

    def test_startup_schedules_the_config_load_and_the_first_show(self):
        window = self.window
        self.assertIn((0, window._load_files_from_config), self.timer_calls)
        self.assertIn((0, window._show_main_window), self.timer_calls)

    def test_the_window_registers_itself_and_keeps_its_collaborators(self):
        window = self.window
        controller = self.controller
        self.assertIs(controller.container.get("main_window"), window)
        self.assertIsNotNone(controller.container.get("hotlink_event_adapter"))
        self.assertIs(
            window._import_project_files_from_args,
            controller.get_service("import_project_files_from_args_use_case"),
        )
        self.assertIs(window.takeoff_tab, window.tab_widget.widget(TAB_INDEX_TAKEOFF))
        self.assertIs(window.summary_tab, window.tab_widget.widget(TAB_INDEX_SUMMARY))
        self.assertIs(window._update_service, window._resolve_update_service())

    def test_detached_window_actions_start_in_sync_with_no_open_windows(self):
        window = self.window
        self.assertFalse(window.get_annotation_window_action().isChecked())
        self.assertFalse(window.get_view_window_action().isChecked())
        self.assertFalse(window.get_view_window_action().isEnabled())

    def test_select_all_has_its_shortcut_and_the_edit_actions_are_shared_with_handlers(
        self,
    ):
        window = self.window
        toolbar = self._toolbar()
        self.assertFalse(window._select_all_action.shortcut().isEmpty())
        self.assertIs(
            window.handlers.delete._duplicate_action, toolbar._duplicate_action
        )

    def test_toolbar_state_receives_the_composed_buttons_and_actions(self):
        window = self.window
        toolbar = self._toolbar()
        ui_event = window.handlers.ui_event
        self.assertIsNotNone(toolbar._cover_sheet_button)
        self.assertIsNotNone(toolbar._select_action)
        self.assertIsNotNone(toolbar._place_action)
        self.assertIsNotNone(toolbar._backout_action)
        self.assertIsNotNone(toolbar._move_overlay_action)
        self.assertEqual(
            len(toolbar._annotation_tool_actions), len(PLAN_ANNOTATION_TOOL_SPECS)
        )
        self.assertIs(toolbar._page_settings_bar, window._page_settings_bar)
        self.assertIs(ui_event._page_settings_bar, window._page_settings_bar)
        self.assertIs(toolbar._bid_layers_sidebar, window._bid_layers_sidebar)
        self.assertIs(ui_event._sidebar.bid_layers_sidebar, window._bid_layers_sidebar)
        self.assertIs(ui_event._undo_service, window._undo_service)
        self.assertIs(toolbar.undo_service, window._undo_service)
        self.assertIs(ui_event._status_panel, window.status_panel)

    def test_the_central_widget_stacks_the_workspace_above_the_status_panel(self):
        window = self.window
        layout = window.centralWidget().layout()
        self.assertEqual(layout.contentsMargins(), QtCore.QMargins(*MAIN_MARGINS))
        self.assertEqual(layout.spacing(), NO_SPACING)
        self.assertEqual(layout.count(), 2)
        self.assertIs(layout.itemAt(1).widget(), window.status_panel)

    def test_select_all_and_status_bar_actions_carry_their_labels(self):
        window = self.window
        self.assertEqual(window._select_all_action.text(), "Select All")
        self.assertEqual(window.get_status_bar_action().text(), "Status Bar")

    def test_the_status_bar_action_mirrors_the_panel(self):
        window = self.window
        self.assertEqual(
            window.get_status_bar_action().isChecked(), window.is_status_bar_visible()
        )

    def test_menu_actions_trigger_their_menu_callbacks(self):
        window = self.window
        shared = window.menu_controller._shared_actions
        for key in (
            ACTION_NEW_PROJECT,
            ACTION_NEW_FOLDER,
            ACTION_NEW_DATABASE,
            ACTION_OPEN_FILES,
        ):
            with self.subTest(key=key):
                with patch.object(
                    window.menu_controller, "trigger_menu_callback"
                ) as callback:
                    shared[key].triggered.emit()
                callback.assert_called_once_with(key)

    def test_context_menus_use_the_menu_controller_commands(self):
        window = self.window
        controller = window.menu_controller
        for view in (window.plan_view, window.opengl_viewer):
            self.assertEqual(
                view._context_menu_command_trigger, controller.trigger_menu_action
            )
        self.assertEqual(
            window.plan_view._context_menu_action_state,
            controller.get_menu_action_state,
        )

    def test_update_dialog_requests_reach_the_update_dialog(self):
        self.window.update_dialog_requested.emit({"version": "9.9"})
        self.assertEqual(self.calls, [("_show_update_dialog", ({"version": "9.9"},))])

    def test_the_ai_bridge_is_started_and_decisions_are_audited(self):
        window = self.window
        token = (
            _A3Path(self.tmp.name) / ".ost_visualizer" / "ai_takeoff" / "session.token"
        )
        self.assertTrue(token.is_file())
        window._ai_approval.changeset_finished.emit("c-1", "rejected")
        self.assertEqual(
            self.calls, [("_on_ai_changeset_finished", ("c-1", "rejected"))]
        )

    def test_saved_annotation_styles_become_the_active_styles_at_startup(self):
        style = self.window.get_annotation_style_for_tool("rect")
        self.assertEqual(style.color, "#123456")
        self.assertEqual(style.line_width, 7.0)

    def test_construction_runs_each_startup_collaborator_once(self):
        log = [call[0] for call in self.construction_log]
        for tag in (
            "license.initialize",
            "workspace.restore_initial_state",
            "mcp.start",
            "ai_bridge.start",
            "config.apply",
            "configurator.configure",
        ):
            with self.subTest(tag=tag):
                self.assertEqual(log.count(tag), 1)

    def test_license_status_events_reach_the_license_coordinator(self):
        window = self.window
        window.event_bus.publish(AppEvents.LICENSE_STATUS_CHANGED, has_license=True)
        self.assertIn("license.status_changed", [call[0] for call in self.calls])

    def test_the_cover_sheet_button_opens_the_cover_sheet_and_rebind_offers_reach_the_prompt(
        self,
    ):
        window = self.window
        self._toolbar()._cover_sheet_button.clicked.emit()
        self.assertIn("cover_sheet.open", [call[0] for call in self.calls])
        self.calls.clear()
        window._ai_takeoff_bridge.rebind_suggested.emit()
        self.assertEqual([call[0] for call in self.calls], ["ai_rebind.offer"])

    def test_the_composed_services_and_handlers_are_attached(self):
        window = self.window
        controller = self.controller
        self.assertIs(
            window._ai_audit_log, controller.get_service("ai_takeoff_audit_log")
        )
        self.assertIsInstance(window.handlers.export, ExportHandler)
        self.assertIs(
            window.handlers.delete._ui_event_coordinator, window.handlers.ui_event
        )
        self.assertIs(
            window.handlers.cover_sheet._ui_event_coordinator, window.handlers.ui_event
        )
        self.assertIs(window._pan_sidebar._plan_view, window.plan_view)
        self.assertIs(
            window.handlers.ui_event.condition_summary_tab,
            window._condition_summary_tab,
        )
        self.assertIs(
            window.handlers.ui_event._sidebar.condition_summary_tab,
            window._condition_summary_tab,
        )
        self.assertIs(
            window.project_view.top_tree._ui_access_manager, window.ui_access_manager
        )

    def test_transaction_monitor_messages_are_parented_to_the_window(self):
        window = self.window
        monitor = window._visualization_service._transaction_monitor
        self.assertIs(monitor._notifier._default_parent, window)

    def test_the_mesh_window_is_owned_by_the_ui_event_coordinator(self):
        window = self.window
        sentinel = object()
        with patch.object(
            window.handlers.ui_event, "get_mesh_window", return_value=sentinel
        ):
            self.assertIs(window.get_mesh_window(), sentinel)


class MainWindowA3BaseClassDelegationTests(unittest.TestCase):
    """showEvent/changeEvent keep delegating to QMainWindow before their own work."""

    def _window(self):
        _app()
        window = MainWindow.__new__(MainWindow)
        QtWidgets.QMainWindow.__init__(window)
        self.addCleanup(window.deleteLater)
        window.splash_screen = None
        return window

    def test_show_event_delegates_to_the_base_class_first(self):
        window = self._window()
        order = []
        window._finish_splash_screen = lambda: order.append("splash")
        with patch.object(
            QtWidgets.QMainWindow, "showEvent", lambda self, event: order.append("base")
        ), patch.object(QtCore.QTimer, "singleShot"):
            window.showEvent(QtGui.QShowEvent())
        self.assertEqual(order, ["base", "splash"])

    def test_change_event_delegates_to_the_base_class_for_every_event_type(self):
        window = self._window()
        seen = []
        with patch.object(
            QtWidgets.QMainWindow,
            "changeEvent",
            lambda self, event: seen.append(event.type()),
        ), patch.object(main_window_module, "rebuild_all_icons") as rebuild:
            window.changeEvent(QtCore.QEvent(QtCore.QEvent.Type.EnabledChange))
            window.changeEvent(QtCore.QEvent(QtCore.QEvent.Type.PaletteChange))
        self.assertEqual(
            seen,
            [QtCore.QEvent.Type.EnabledChange, QtCore.QEvent.Type.PaletteChange],
        )
        self.assertEqual(rebuild.call_count, 1)


class MainWindowA3StartupArgumentTests(unittest.TestCase):
    """A separately composed real window keeps its startup arguments and splash."""

    def _window(self, **kwargs):
        _app()
        stack = _A3ExitStack()
        tmp = _a3_tempfile.TemporaryDirectory()
        root = _A3Path(tmp.name)
        stack.enter_context(patch.object(_A3Path, "home", return_value=root))
        stack.enter_context(patch.object(_A3LoggerFactory, "configure"))
        stack.enter_context(
            patch.object(
                _A3LoggerFactory,
                "get_logger",
                return_value=_a3_logging.getLogger("test.main_window.startup_args"),
            )
        )
        stack.enter_context(patch.object(QtCore.QTimer, "singleShot"))
        stack.enter_context(
            patch(
                "ost_visualizer.presentation.utils.annotation_defaults."
                "resolve_font_definition",
                side_effect=lambda definition: definition,
            )
        )
        controller = _a3_configure(log_dir=root / "logs").get("app_controller")
        window = MainWindow(controller, **kwargs)

        def close():
            window._workspace_state_coordinator.cleanup()
            window.event_coordinator.cleanup()
            window.handlers.ui_event.cleanup()
            window.license_coordinator.cleanup()
            window.ui_access_manager.cleanup()
            window._mcp_context_bridge.cleanup()
            window._ai_takeoff_bridge.cleanup()
            window._ai_approval.cleanup()
            window._ai_rebind_prompt.cleanup()
            window._ai_undo_notice.cleanup()
            window._ai_pdf_source.release()
            window._deferred_persistence_manager.cleanup()
            window.hide()
            window.deleteLater()
            controller.cleanup()
            QtWidgets.QApplication.sendPostedEvents(
                window, QtCore.QEvent.Type.DeferredDelete
            )
            stack.close()
            tmp.cleanup()

        self.addCleanup(close)
        return window

    def test_startup_arguments_and_the_splash_screen_are_kept_by_a_new_window(self):
        splash = object()
        args = import_args_use_case.ProjectFileArgs(
            files=[], rejected=[_A3Rejected(value="bad.txt", reason="Unsupported.")]
        )
        self.assertTrue(args.has_file_args)
        window = self._window(splash_screen=splash, startup_project_file_args=args)
        self.assertIs(window.splash_screen, splash)
        self.assertEqual(window._pending_project_file_args, [args])

    def test_startup_arguments_without_files_or_rejections_are_not_queued(self):
        empty = import_args_use_case.ProjectFileArgs(files=[], rejected=[])
        self.assertFalse(empty.has_file_args)
        window = self._window(startup_project_file_args=empty)
        self.assertEqual(window._pending_project_file_args, [])
        self.assertIsNone(window.splash_screen)


# ---------------------------------------------------------------------------
# Second-pass (W3-IMPORTDLG): the project-file import progress flow.
# ---------------------------------------------------------------------------
import threading


class _ImportFlowHost(QtWidgets.QWidget):
    """A real QWidget parent carrying only what the import-progress flow reads."""

    _project_file_import_progress_label = staticmethod(
        MainWindow._project_file_import_progress_label
    )
    _project_file_import_progress_failure = staticmethod(
        MainWindow._project_file_import_progress_failure
    )

    def __init__(self, execute_imports, current_target=None):
        super().__init__()
        self.current_target = current_target
        self.ui_access_manager = SimpleNamespace(is_allowed=lambda _feature: True)
        self.target = import_args_use_case.ProjectImportTarget(
            "real-target.mdb", "project-1", True
        )
        self.resolved_from = []
        self.flushed = []
        self._deferred_persistence_manager = SimpleNamespace(
            flush_for_file=lambda path: self.flushed.append(path) or True
        )
        self._import_project_files_from_args = SimpleNamespace(
            resolve_target=lambda current: self.resolved_from.append(current)
            or self.target,
            uses_async_import=lambda _target: False,
            execute_imports=execute_imports,
        )

    def _current_project_import_target(self):
        return self.current_target


class MainWindowImportProgressRealDialogTests(unittest.TestCase):
    """The import flow driven through the real ProgressDialog and a worker thread."""

    def setUp(self):
        _dialog_lifecycle_support__app()
        self._project_folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._project_folder.cleanup)
        self.host = None
        self.addCleanup(self._delete_host)

    def _delete_host(self):
        if self.host is not None and _a3_is_valid(self.host):
            _a3_delete(self.host)
        self.host = None

    def _args(self, *names):
        folder = Path(self._project_folder.name)
        paths = []
        for name in names:
            (folder / name).write_text("x")
            paths.append(folder / name)
        return _startup_import__project_file_args(*paths)

    def _run(self, execute_imports, args, current_target=None):
        instances = []

        class Recording(main_window_module.ProgressDialog):
            def __init__(self, *dialog_args, **dialog_kwargs):
                super().__init__(*dialog_args, **dialog_kwargs)
                self.started_thread = None
                instances.append(self)

            def _start(self):
                super()._start()
                self.started_thread = self._thread

        self._delete_host()
        self.host = _ImportFlowHost(execute_imports, current_target)
        guard_fired = []

        def force_close():
            # fail-safe: a broken completion path fails the test, not hangs it
            guard_fired.append(True)
            for dialog in instances:
                dialog.done(QtWidgets.QDialog.DialogCode.Rejected)

        guard = QtCore.QTimer(self.host)
        guard.setSingleShot(True)
        guard.timeout.connect(force_close)
        guard.start(10000)
        with patch.object(main_window_module, "ProgressDialog", Recording):
            result = MainWindow._import_project_files_with_progress(self.host, args)
        guard.stop()
        self.assertEqual(guard_fired, [])
        self.assertEqual(len(instances), 1)
        return result, instances[0]

    def _assert_released(self, dialog):
        thread = dialog.started_thread
        self.assertIsNone(QtWidgets.QApplication.activeModalWidget())
        self.assertFalse(dialog.isVisible())
        self.assertIsNotNone(thread)
        self.assertTrue(thread.isFinished())
        self.assertFalse(thread.isRunning())
        self.assertTrue(dialog._cleanup_complete)
        self.assertIsNone(dialog._thread)
        self.assertIsNone(dialog._task_fn)
        QtCore.QCoreApplication.sendPostedEvents(
            None, QtCore.QEvent.Type.DeferredDelete
        )
        self.assertFalse(_a3_is_valid(dialog))
        self.assertEqual(self.host.findChildren(QtWidgets.QDialog), [])

    def test_the_dialog_is_modal_and_visible_exactly_while_the_worker_runs(self):
        started = threading.Event()
        release = threading.Event()
        worker = {}
        observed = {}
        batch = import_args_use_case.ProjectFileImportBatchResult(
            target_db_path="real-target.mdb"
        )

        def execute_imports(args, target, refresh_after_import=True):
            worker["thread"] = threading.get_ident()
            worker["call"] = (args, target, refresh_after_import)
            started.set()
            worker["released"] = release.wait(10)
            return batch

        def observe():
            if not started.is_set() or observed:
                return
            poll.stop()
            dialog = QtWidgets.QApplication.activeModalWidget()
            observed["dialog"] = dialog
            observed["visible"] = dialog.isVisible()
            observed["modality"] = dialog.windowModality()
            observed["parent"] = dialog.parent()
            observed["label"] = dialog._label.text()
            observed["running"] = dialog._thread.isRunning()
            release.set()

        args = self._args("one.ost")
        poll = QtCore.QTimer()
        poll.setInterval(1)
        poll.timeout.connect(observe)
        poll.start()
        failsafe = QtCore.QTimer()
        failsafe.setSingleShot(True)
        failsafe.timeout.connect(release.set)
        failsafe.start(5000)
        try:
            result, dialog = self._run(execute_imports, args)
        finally:
            poll.stop()
            failsafe.stop()
            release.set()
        self.assertTrue(worker["released"])
        self.assertIs(observed["dialog"], dialog)
        self.assertIs(observed["visible"], True)
        self.assertIs(observed["modality"], QtCore.Qt.WindowModality.ApplicationModal)
        self.assertIs(observed["parent"], self.host)
        self.assertIs(observed["running"], True)
        self.assertEqual(observed["label"], "Importing <b>one.ost</b>...")
        self.assertNotEqual(worker["thread"], threading.get_ident())
        self.assertIs(worker["call"][0], args)
        self.assertIs(worker["call"][1], self.host.target)
        self.assertIs(worker["call"][2], False)
        self.assertIs(result, batch)
        self.assertEqual(self.host.flushed, ["real-target.mdb"])
        self._assert_released(dialog)

    def test_a_worker_exception_becomes_a_failure_result_with_the_error_logged(self):
        def execute_imports(args, target, refresh_after_import=True):
            raise RuntimeError("import boom")

        args = self._args("one.ost", "two.osp")
        with self.assertLogs(
            "ost_visualizer.presentation.components.progress_dialog", level="ERROR"
        ), self.assertLogs(
            "ost_visualizer.presentation.main_window", level="ERROR"
        ) as captured:
            result, dialog = self._run(execute_imports, args)
        self.assertIn("import boom", captured.output[0])
        self.assertIs(captured.records[0].exc_info[1], dialog.error)
        self.assertEqual(
            [(item.source_path, item.success, item.message) for item in result.results],
            [
                (item.path, False, "The file could not be imported.")
                for item in args.files
            ],
        )
        self.assertEqual(result.target_db_path, "real-target.mdb")
        self.assertEqual(result.selected_project_uid, "project-1")
        self.assertIs(result.import_as_orphaned_due_to_deleted_target, True)
        self.assertIsNone(dialog.result)
        self.assertIsInstance(dialog.error, RuntimeError)
        self._assert_released(dialog)

    def test_a_worker_result_that_is_not_a_batch_result_is_a_failure_without_an_error_log(
        self,
    ):
        for returned in (None, False, True, "done"):
            with self.subTest(returned=returned):
                args = self._args("one.ost")
                with self.assertNoLogs(
                    "ost_visualizer.presentation.main_window", level="ERROR"
                ):
                    result, dialog = self._run(
                        lambda a, t, refresh_after_import=True, value=returned: value,
                        args,
                    )
                self.assertEqual(
                    [(item.success, item.message) for item in result.results],
                    [(False, "The file could not be imported.")],
                )
                self.assertEqual(result.target_db_path, "real-target.mdb")
                self.assertIsNone(dialog.error)
                self._assert_released(dialog)

    def test_the_current_selection_target_is_what_resolve_target_receives(self):
        current = import_args_use_case.ProjectImportCurrentTarget(
            file_path="current.mdb", project_uid="p-current"
        )
        batch = import_args_use_case.ProjectFileImportBatchResult()
        result, _dialog = self._run(
            lambda a, t, refresh_after_import=True: batch,
            self._args("one.ost"),
            current_target=current,
        )
        self.assertEqual(len(self.host.resolved_from), 1)
        self.assertIs(self.host.resolved_from[0], current)
        self.assertIs(result, batch)


class MainWindowImportProgressFlowContractTests(unittest.TestCase):
    """Argument hand-off, release ordering and failure shape of the import flow."""

    def setUp(self):
        _startup_import_FakeStartupProgressDialog.instances = []
        _startup_import_FakeStartupProgressDialog.result_code = (
            QtWidgets.QDialog.DialogCode.Accepted
        )
        self.addCleanup(
            setattr,
            _startup_import_FakeStartupProgressDialog,
            "result_code",
            QtWidgets.QDialog.DialogCode.Accepted,
        )
        self._project_folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._project_folder.cleanup)
        self.events = []
        self.target = import_args_use_case.ProjectImportTarget(
            "target.mdb", "project-7", True
        )
        self.current = import_args_use_case.ProjectImportCurrentTarget("cur.mdb")

    def _window(self, *, uses_async=False, flush=True):
        window = _startup_import__startup_import_window()
        window._current_project_import_target = lambda: self.current
        window._deferred_persistence_manager = SimpleNamespace(
            flush_for_file=lambda path: self.events.append(("flush", path)) or flush
        )
        window._import_project_files_from_args = SimpleNamespace(
            resolve_target=lambda current: self.events.append(("resolve", current))
            or self.target,
            uses_async_import=lambda target: uses_async,
            execute_imports=lambda args, target, refresh_after_import=True: (
                self.events.append(("execute", args, target, refresh_after_import))
                or import_args_use_case.ProjectFileImportBatchResult()
            ),
            build_no_target_result=lambda args: self.events.append(("no-target", args))
            or "no-target",
            build_flush_failure_result=lambda args, target: self.events.append(
                ("flush-failure", args, target)
            )
            or "flush-failure",
            queue_imports=lambda args, target, completed: self.events.append(
                ("queue", args, target, completed)
            ),
        )
        return window

    def _args(self, *names):
        folder = Path(self._project_folder.name)
        paths = []
        for name in names:
            (folder / name).write_text("x")
            paths.append(folder / name)
        return _startup_import__project_file_args(*paths)

    def test_the_dialog_is_run_then_cleaned_up_then_scheduled_for_deletion(self):
        events = self.events

        class Ordered(_startup_import_FakeStartupProgressDialog):
            def exec(self):
                events.append("exec")
                return super().exec()

            def cleanup(self):
                events.append("cleanup")
                super().cleanup()

            def deleteLater(self):
                events.append("deleteLater")
                super().deleteLater()

        window = self._window()
        with patch.object(main_window_module, "ProgressDialog", Ordered):
            MainWindow._import_project_files_with_progress(window, self._args("a.ost"))
        names = [event if isinstance(event, str) else event[0] for event in events]
        self.assertEqual(
            names,
            ["resolve", "flush", "execute", "exec", "cleanup", "deleteLater"],
        )
        self.assertIs(events[0][1], self.current)

    def test_early_exits_hand_the_original_arguments_to_their_result_builders(self):
        args = self._args("a.ost")
        window = self._window(flush=False)
        self.assertEqual(
            MainWindow._import_project_files_with_progress(window, args),
            "flush-failure",
        )
        self.assertEqual(
            self.events,
            [
                ("resolve", self.current),
                ("flush", "target.mdb"),
                ("flush-failure", args, self.target),
            ],
        )
        self.events.clear()
        window = self._window()
        window._import_project_files_from_args.resolve_target = lambda current: (
            self.events.append(("resolve", current)) or None
        )
        self.assertEqual(
            MainWindow._import_project_files_with_progress(window, args), "no-target"
        )
        self.assertEqual(self.events, [("resolve", self.current), ("no-target", args)])

    def test_an_async_import_is_queued_with_the_flushed_target_and_no_dialog(self):
        args = self._args("a.ost")
        window = self._window(uses_async=True)
        result = MainWindow._import_project_files_with_progress(window, args)
        self.assertIsNone(result)
        self.assertEqual(
            [event[0] for event in self.events], ["resolve", "flush", "queue"]
        )
        _name, queued_args, queued_target, completed = self.events[2]
        self.assertIs(queued_args, args)
        self.assertIs(queued_target, self.target)
        self.assertEqual(completed, window._complete_async_project_file_imports)
        self.assertEqual(_startup_import_FakeStartupProgressDialog.instances, [])

    def test_the_failure_result_carries_the_target_and_copies_the_rejections(self):
        args = self._args("a.ost", "b.osp")
        rejected = [_A3Rejected(value="bad.txt", reason="Unsupported file type.")]
        args = import_args_use_case.ProjectFileArgs(files=args.files, rejected=rejected)
        result = MainWindow._project_file_import_progress_failure(args, self.target)
        self.assertEqual(
            [(item.source_path, item.success, item.message) for item in result.results],
            [
                (item.path, False, "The file could not be imported.")
                for item in args.files
            ],
        )
        self.assertEqual(result.rejected, rejected)
        self.assertIsNot(result.rejected, rejected)
        self.assertEqual(result.target_db_path, "target.mdb")
        self.assertEqual(result.selected_project_uid, "project-7")
        self.assertIs(result.import_as_orphaned_due_to_deleted_target, True)
        self.assertEqual(result.failed, 3)
        self.assertEqual(result.succeeded, 0)
        plain = MainWindow._project_file_import_progress_failure(
            args, import_args_use_case.ProjectImportTarget("plain.mdb")
        )
        self.assertIsNone(plain.selected_project_uid)
        self.assertIs(plain.import_as_orphaned_due_to_deleted_target, False)

    def test_the_worker_error_is_logged_with_its_own_traceback(self):
        error = RuntimeError("worker boom")
        window = self._window()

        class Failing(_startup_import_FakeStartupProgressDialog):
            def exec(self):
                self.result = None
                self.error = error
                return QtWidgets.QDialog.DialogCode.Rejected

        with patch.object(
            main_window_module, "ProgressDialog", Failing
        ), self.assertLogs(
            "ost_visualizer.presentation.main_window", level="ERROR"
        ) as captured:
            MainWindow._import_project_files_with_progress(window, self._args("a.ost"))
        (record,) = captured.records
        self.assertEqual(
            record.getMessage(),
            "Startup project file import worker raised: worker boom",
        )
        self.assertIs(record.exc_info[1], error)


def _scope_rejected(value):
    return _A3Rejected(value=value, reason="Unsupported file type.")


def _scope_file(path):
    return import_args_use_case.ParsedProjectFileArg(path=path, extension=".ost")


class MainWindowImportFlowCallArgumentTests(unittest.TestCase):
    """What the import flow hands to its collaborators, and when it defers."""

    def _window(self):
        window = _startup_import__startup_import_window()
        window._startup_load_complete = True
        window._main_window_ready = True
        return window

    def _live_window(self):
        _dialog_lifecycle_support__app()
        window = _startup_import__startup_import_window()
        QtWidgets.QMainWindow.__init__(window)
        self.addCleanup(window.deleteLater)
        return window

    def test_run_pending_merges_files_and_rejections_and_hands_the_result_on(self):
        window = self._window()
        first, second = _scope_rejected("a.txt"), _scope_rejected("b.txt")
        window._pending_project_file_args = [
            import_args_use_case.ProjectFileArgs(
                files=[_scope_file("1.ost")], rejected=[first]
            ),
            import_args_use_case.ProjectFileArgs(
                files=[_scope_file("2.ost")], rejected=[second]
            ),
        ]
        result = import_args_use_case.ProjectFileImportBatchResult()
        received, selected, shown = [], [], []
        window._import_project_files_with_progress = lambda args: (
            received.append(args) or result
        )
        window._select_project_file_import_result = selected.append
        window._show_project_file_import_result = shown.append
        window._run_pending_project_file_imports()
        self.assertEqual(len(received), 1)
        self.assertEqual([item.path for item in received[0].files], ["1.ost", "2.ost"])
        self.assertEqual(received[0].rejected, [first, second])
        self.assertEqual(len(selected), 1)
        self.assertIs(selected[0], result)
        self.assertEqual(len(shown), 1)
        self.assertIs(shown[0], result)
        self.assertEqual(window._pending_project_file_args, [])

    def test_run_pending_defers_itself_under_its_own_key_during_shutdown(self):
        window = self._window()
        window._collaboration_shutdown_pending = True
        window._pending_project_file_args = [
            import_args_use_case.ProjectFileArgs(files=[_scope_file("1.ost")])
        ]
        window._run_pending_project_file_imports()
        self.assertEqual(
            window._shutdown_deferred_callbacks,
            {"run_project_file_imports": window._run_pending_project_file_imports},
        )

    def test_a_shutdown_after_the_import_defers_the_completion_with_that_result(self):
        for refresh in (False, True):
            with self.subTest(refresh_pending=refresh):
                window = self._window()
                window._pending_project_file_args = [
                    import_args_use_case.ProjectFileArgs(files=[_scope_file("1.ost")])
                ]
                first = import_args_use_case.ProjectFileImportBatchResult(
                    refresh_pending=refresh
                )
                refreshed = import_args_use_case.ProjectFileImportBatchResult()
                refresh_arguments = []

                def import_with_progress(
                    args, window=window, refresh=refresh, first=first
                ):
                    if not refresh:
                        window._collaboration_shutdown_pending = True
                    return first

                def refresh_import_result(
                    result,
                    window=window,
                    refresh_arguments=refresh_arguments,
                    refreshed=refreshed,
                ):
                    refresh_arguments.append(result)
                    window._collaboration_shutdown_pending = True
                    return refreshed

                window._import_project_files_with_progress = import_with_progress
                window._import_project_files_from_args = SimpleNamespace(
                    refresh_import_result=refresh_import_result
                )
                completed = []
                window._complete_async_project_file_imports = completed.append
                window._select_project_file_import_result = lambda r: self.fail(
                    "must wait for the deferred completion"
                )
                window._show_project_file_import_result = lambda r: self.fail(
                    "must wait for the deferred completion"
                )
                window._run_pending_project_file_imports()
                self.assertIn(
                    "complete_project_file_imports", window._shutdown_deferred_callbacks
                )
                if refresh:
                    self.assertEqual(len(refresh_arguments), 1)
                    self.assertIs(refresh_arguments[0], first)
                window._shutdown_deferred_callbacks["complete_project_file_imports"]()
                self.assertEqual(len(completed), 1)
                self.assertIs(completed[0], refreshed if refresh else first)

    def test_the_access_check_asks_for_import_and_the_result_copies_the_rejections(
        self,
    ):
        window = _startup_import__startup_import_window()
        asked = []
        window.ui_access_manager = SimpleNamespace(
            is_allowed=lambda feature: asked.append(feature) or False
        )
        rejected = [_scope_rejected("bad.txt")]
        args = import_args_use_case.ProjectFileArgs(
            files=[_scope_file("1.ost")], rejected=rejected
        )
        result = MainWindow._import_project_files_with_progress(window, args)
        self.assertEqual(asked, [Feature.IMPORT])
        self.assertEqual(
            [(item.source_path, item.success, item.message) for item in result.results],
            [("1.ost", False, "Import is not available for the selected database.")],
        )
        self.assertEqual(result.rejected, rejected)
        self.assertIsNot(result.rejected, rejected)
        empty = import_args_use_case.ProjectFileArgs(files=[], rejected=rejected)
        result = MainWindow._import_project_files_with_progress(window, empty)
        self.assertEqual(result.rejected, rejected)
        self.assertIsNot(result.rejected, rejected)
        self.assertEqual(asked, [Feature.IMPORT])

    def test_the_async_decision_is_made_for_the_resolved_target(self):
        window = _startup_import__startup_import_window()
        window._current_project_import_target = lambda: None
        target = import_args_use_case.ProjectImportTarget("t.mdb")
        asked = []
        window._deferred_persistence_manager = SimpleNamespace(
            flush_for_file=lambda path: True
        )
        window._import_project_files_from_args = SimpleNamespace(
            resolve_target=lambda current: target,
            uses_async_import=lambda candidate: asked.append(candidate) or True,
            queue_imports=lambda *queued: None,
        )
        MainWindow._import_project_files_with_progress(
            window,
            import_args_use_case.ProjectFileArgs(files=[_scope_file("1.ost")]),
        )
        self.assertEqual(len(asked), 1)
        self.assertIs(asked[0], target)

    def test_the_current_target_of_a_selected_bid_asks_for_that_bids_project(self):
        window = _startup_import__startup_import_window()
        bid_ref = BidRef("f.mdb", "bid-1")
        seen = []
        window.ui_state_manager = SimpleNamespace(get_selected_bid_ref=lambda: bid_ref)
        window._project_data_service = SimpleNamespace(
            find_project_uid_for_bid=lambda ref: seen.append(ref) or "uid-9"
        )
        target = MainWindow._current_project_import_target(window)
        self.assertEqual(len(seen), 1)
        self.assertIs(seen[0], bid_ref)
        self.assertEqual((target.file_path, target.project_uid), ("f.mdb", "uid-9"))

    def test_an_async_completion_for_a_destroyed_window_does_nothing(self):
        window = _startup_import__startup_import_window()
        self.assertFalse(_a3_is_valid(window))
        window._import_project_files_from_args = SimpleNamespace(
            refresh_import_result=lambda result: self.fail("must not refresh")
        )
        window._select_project_file_import_result = lambda r: self.fail("no select")
        window._show_project_file_import_result = lambda r: self.fail("no show")
        window._project_file_import_running = True
        MainWindow._complete_async_project_file_imports(
            window,
            import_args_use_case.ProjectFileImportBatchResult(refresh_pending=True),
        )
        self.assertTrue(window._project_file_import_running)
        self.assertEqual(window._shutdown_deferred_callbacks, {})

    def test_an_async_completion_refreshes_the_result_it_was_given(self):
        window = self._live_window()
        first = import_args_use_case.ProjectFileImportBatchResult(refresh_pending=True)
        refreshed = import_args_use_case.ProjectFileImportBatchResult()
        refresh_arguments, selected, shown = [], [], []
        window._import_project_files_from_args = SimpleNamespace(
            refresh_import_result=lambda result: refresh_arguments.append(result)
            or refreshed
        )
        window._select_project_file_import_result = selected.append
        window._show_project_file_import_result = shown.append
        with patch.object(QtCore.QTimer, "singleShot"):
            window._complete_async_project_file_imports(first)
        self.assertEqual(len(refresh_arguments), 1)
        self.assertIs(refresh_arguments[0], first)
        self.assertEqual(len(selected), 1)
        self.assertIs(selected[0], refreshed)
        self.assertEqual(len(shown), 1)
        self.assertIs(shown[0], refreshed)

    def test_an_async_completion_deferred_by_shutdown_later_completes_that_result(
        self,
    ):
        window = self._live_window()
        selected, shown = [], []
        window._select_project_file_import_result = selected.append
        window._show_project_file_import_result = shown.append
        result = import_args_use_case.ProjectFileImportBatchResult()
        window._collaboration_shutdown_pending = True
        window._complete_async_project_file_imports(result)
        self.assertEqual((selected, shown), ([], []))
        window._collaboration_shutdown_pending = False
        with patch.object(QtCore.QTimer, "singleShot"):
            window._shutdown_deferred_callbacks["complete_project_file_imports"]()
        self.assertEqual(len(selected), 1)
        self.assertIs(selected[0], result)
        self.assertEqual(len(shown), 1)
        self.assertIs(shown[0], result)

    def test_a_shutdown_started_by_the_refresh_defers_the_refreshed_result(self):
        window = self._live_window()
        first = import_args_use_case.ProjectFileImportBatchResult(refresh_pending=True)
        refreshed = import_args_use_case.ProjectFileImportBatchResult()

        def refresh(result):
            window._collaboration_shutdown_pending = True
            return refreshed

        window._import_project_files_from_args = SimpleNamespace(
            refresh_import_result=refresh
        )
        selected, shown = [], []
        window._select_project_file_import_result = selected.append
        window._show_project_file_import_result = shown.append
        window._complete_async_project_file_imports(first)
        self.assertIn(
            "complete_project_file_imports", window._shutdown_deferred_callbacks
        )
        self.assertEqual((selected, shown), ([], []))
        window._collaboration_shutdown_pending = False
        with patch.object(QtCore.QTimer, "singleShot"):
            window._shutdown_deferred_callbacks["complete_project_file_imports"]()
        self.assertEqual(len(selected), 1)
        self.assertIs(selected[0], refreshed)
        self.assertIs(shown[0], refreshed)


class MainWindowSecondPassGapTests(unittest.TestCase):
    """Behaviour the second-pass mutation sweep showed no earlier test pinned."""

    A = BidRef("C:/jobs/a.mdb", "b1")
    B = BidRef("C:/jobs/a.mdb", "b2")
    OTHER = BidRef("C:/jobs/other.mdb", "b3")
    _edit_window = MainWindowA3EditCommandTests._window
    _update_check_window = MainWindowDeferredShutdownTests._update_check_window

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_copying_on_the_takeoff_tab_never_also_copies_the_selected_bids(self):
        access = _A3Access({Feature.SELECT_PLAN_ITEMS, Feature.COPY_BID})
        window = self._edit_window(TAB_INDEX_TAKEOFF, access=access)
        window._copy_selected()
        self.assertEqual([entry[0] for entry in window.log], ["plan.copy"])
        self.assertFalse(window._bid_clipboard.has_content())
        self.assertEqual(access.calls, [("allowed", Feature.SELECT_PLAN_ITEMS)])

    def test_only_a_missing_update_service_is_optional(self):
        window = MainWindow.__new__(MainWindow)

        def broken(name):
            raise RuntimeError(f"container failed for {name}")

        window.app_controller = SimpleNamespace(get_service=broken)
        with self.assertRaisesRegex(
            RuntimeError, "container failed for update_check_service"
        ):
            window._resolve_update_service()

    def test_a_failed_update_check_is_logged_with_its_message_and_traceback(self):
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
        (record,) = captured.records
        self.assertEqual(
            record.getMessage(), "Error checking for updates: update server down"
        )
        self.assertEqual(record.levelname, "ERROR")
        self.assertIs(record.exc_info[0], RuntimeError)
        self.assertEqual(window.emitted, [])

    def test_the_update_check_worker_does_not_swallow_interpreter_exits(self):
        def leave():
            raise SystemExit("interpreter leaving")

        window = self._update_check_window(leave)
        with patch(
            "ost_visualizer.presentation.main_window.threading.Thread"
        ) as thread_factory:
            MainWindow._check_for_updates(window)
        with self.assertNoLogs("ost_visualizer.presentation.main_window"):
            with self.assertRaises(SystemExit):
                thread_factory.call_args.kwargs["target"]()
        self.assertEqual(window.emitted, [])

    def test_resuming_never_shows_a_hidden_window_whose_widget_was_destroyed(self):
        dead = QtWidgets.QWidget()
        _a3_delete(dead)
        self.assertFalse(_a3_is_valid(dead))
        live = QtWidgets.QWidget()
        self.addCleanup(live.deleteLater)
        elsewhere = QtWidgets.QWidget()
        self.addCleanup(elsewhere.deleteLater)
        window = MainWindow.__new__(MainWindow)
        window._shutdown_hidden_windows = (dead, live, elsewhere)
        window._shutdown_deferred_callbacks = {}
        window._detached_plan_windows = lambda: (dead, live)
        window.get_mesh_window = lambda: None
        window._resume_shutdown_deferred_callbacks()
        self.assertEqual(window._shutdown_hidden_windows, ())
        self.assertFalse(live.isHidden())
        self.assertTrue(elsewhere.isHidden())

    def test_a_move_is_checked_against_the_database_of_the_first_bid(self):
        """Characterisation: refs of one database may spell its path differently."""
        first = BidRef("C:/Jobs/A.mdb", "b1")
        second = BidRef("c:\\jobs\\a.mdb", "b2")
        created = []
        window = MainWindow.__new__(MainWindow)
        window.ui_access_manager = SimpleNamespace(
            can_edit_bid_structure=lambda refs: True,
            can_create_bid=lambda path, project: created.append((path, project))
            or True,
        )
        self.assertIs(window._can_move_project_bids([first, second], "proj"), True)
        self.assertIs(window._can_move_project_bids([second, first], "proj"), True)
        self.assertEqual(
            created, [("C:/Jobs/A.mdb", "proj"), ("c:\\jobs\\a.mdb", "proj")]
        )

    def test_sidebar_setters_coerce_their_argument_to_a_real_boolean(self):
        for setter, getter, action_name, widget_name in (
            (
                "set_pan_sidebar_visible",
                "is_pan_sidebar_visible",
                "_pan_toggle_action",
                "_pan_sidebar",
            ),
            (
                "set_layers_sidebar_visible",
                "is_layers_sidebar_visible",
                "_layers_toggle_action",
                "_bid_layers_sidebar",
            ),
            (
                "set_conditions_sidebar_visible",
                "is_conditions_sidebar_visible",
                "_conditions_toggle_action",
                "_conditions_sidebar",
            ),
        ):
            with self.subTest(setter=setter):
                window = self._sidebar_window()
                action = getattr(window, action_name)
                widget = getattr(window, widget_name)
                widget.setHidden(True)
                action.setChecked(False)
                getattr(window, setter)("yes")
                self.assertTrue(action.isChecked())
                getattr(window, setter)("yes")
                self.assertFalse(widget.isHidden())
                self.assertIs(getattr(window, getter)(), True)
                getattr(window, setter)(None)
                self.assertFalse(action.isChecked())
                getattr(window, setter)(None)
                self.assertTrue(widget.isHidden())
                self.assertIs(getattr(window, getter)(), False)

    def test_status_panel_setter_coerces_and_leaves_a_matching_action_alone(self):
        window = self._sidebar_window()
        action = window._status_bar_action
        window.status_panel.setHidden(True)
        action.setChecked(False)
        window.set_status_bar_visible("yes")
        self.assertTrue(action.isChecked())
        self.assertFalse(window.status_panel.isHidden())
        window.set_status_bar_visible(None)
        self.assertFalse(action.isChecked())
        self.assertTrue(window.status_panel.isHidden())
        action.blockSignals(True)
        window.set_status_bar_visible(None)
        self.assertTrue(action.signalsBlocked())
        self.assertFalse(action.isChecked())
        self.assertTrue(window.status_panel.isHidden())
        action.blockSignals(False)

    _window = MainWindowA3ShellLayoutTests._window
    _sidebar_window = MainWindowA3ShellLayoutTests._sidebar_window
