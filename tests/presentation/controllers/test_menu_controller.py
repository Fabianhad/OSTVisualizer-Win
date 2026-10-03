from tests.presentation.dialogs.options.preference_support import (
    _app as _preferences_support__app,
)
from tests.helpers.workspace_state import make_workspace_state_model
from shiboken6 import delete, isValid
from PySide6 import QtCore, QtGui, QtWidgets
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from ost_visualizer.presentation.managers.ui_access_manager import UIAccessManager
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.cover_sheet import CoverSheetPage
from ost_visualizer.presentation.actions import action_ids
from ost_visualizer.presentation.dialogs.cover_sheet.dialog import CoverSheetDialog
from ost_visualizer.presentation.components.menu_builder import MenuBuilder
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.handlers.cover_sheet_handler import CoverSheetHandler
from ost_visualizer.presentation.handlers.export_handler import ExportHandler
from ost_visualizer.presentation.handlers.file_operation_handler import (
    FileOperationHandler,
)
from ost_visualizer.presentation.handlers.import_handler import ImportHandler
from ost_visualizer.presentation.handlers.project_write_handler import (
    ProjectWriteHandler,
)
from tests.presentation.managers.surface_access_support import (
    _Capabilities as _surface_access_support__Capabilities,
    _EventBus as _surface_access_support__EventBus,
    _License as _surface_access_support__License,
    _TransactionMonitor as _surface_access_support__TransactionMonitor,
)
from unittest import mock
from pathlib import Path
import datetime
import inspect
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.presentation.controllers.menu_controller import MenuController
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.actions.action_ids import (
    ACTION_SHOW_ORIGINAL_IMAGE,
    ACTION_SHOW_OVERLAY_IMAGE,
)
from ost_visualizer.presentation.interfaces.i_workspace_shell import (
    CurrentAreaSelectionContext,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
    credential_target_for,
)
from PySide6 import QtCore, QtWidgets
from tests.helpers.sql.database_foundation_support import (
    _IconProvider as _database_foundation_support__IconProvider,
    _app as _database_foundation_support__app,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.presentation.utils.messagebox import DB_LOCKED_HINT
from ost_visualizer.application.services.project_write_service import (
    DeleteValidationResult,
    ProjectWriteService,
    WriteReloadResult,
)
from tests.presentation.handlers.project_command_support import (
    _FakeDeferredPersistence as _permissions__FakeDeferredPersistence,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _Action:
    def __init__(self, callback=None):
        self.enabled = True
        self._callback = callback

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)

    def isEnabled(self):
        return self.enabled

    def trigger(self):
        if self._callback:
            self._callback()


class _Menu(_Action):
    pass


class _Access:
    def __init__(self, allowed=True, denied=()):
        self.allowed = allowed
        self.denied = frozenset(denied)

    def is_allowed(self, feature: Feature) -> bool:
        return self.allowed and feature not in self.denied


class _UiState:
    def __init__(self, bid_ref=None):
        self._bid_ref = bid_ref
        self.selected_project_uid = None
        self.active_page_uid = None

    def get_selected_bid_ref(self):
        return self._bid_ref


class _ProjectData:
    def __init__(self, current_bid_ref=None):
        self.current_bid_ref = current_bid_ref
        self.selected_page_uids = ["page-1"]
        self.conditions = {"condition-1": object()}
        self.takeoffs = [object()]
        self.page = Page(uid="page-1", name="A1", width_pts=612.0, height_pts=792.0)

    def get_current_bid_ref(self):
        return self.current_bid_ref

    def get_selected_page_uids(self):
        return list(self.selected_page_uids)

    def has_takeoffs_for_pages(self, page_uids):
        return bool(page_uids and self.takeoffs)

    def get_page(self, _page_uid):
        return self.page

    def get_bid_conditions(self):
        return self.conditions

    def get_all_takeoffs(self):
        return self.takeoffs


def _controller(ui_state, project_data, csv_calls=None):
    controller = MenuController.__new__(MenuController)
    controller.menu_bar = object()
    controller._export_formats = ["html"]
    controller._actions = {
        "export_as_html": _Action(),
        "export_as_pdf": _Action(),
        "export_summary_csv": _Action(
            callback=(
                (lambda: csv_calls.append("csv")) if csv_calls is not None else None
            )
        ),
        "export_as_ost": _Action(),
        "export_as_osp": _Action(),
    }
    controller._menus = {
        "import": _Menu(),
        "export": _Menu(),
        "html export options": _Menu(),
    }
    controller._variable_actions = {}
    controller._tool_action_enabled_state = {}
    controller.window = SimpleNamespace(
        is_takeoff_tab_active=lambda: False,
        is_summary_tab_active=lambda: False,
        get_takeoff_plan_view=lambda: None,
    )
    controller.ui_state_manager = ui_state
    controller.project_data = project_data
    controller.ui_access_manager = _Access()
    controller.handlers = SimpleNamespace(ui_event=SimpleNamespace())
    controller._sync_variable_actions = lambda *_args: None
    controller._should_enable_project_tree_creation = lambda: False
    controller._can_open_master_data_dialog = lambda: False
    return controller


class MenuControllerShutdownTests(unittest.TestCase):
    def setUp(self):
        # These partial MainWindow fixtures do not construct detached managers.
        for name, result in (("_detached_plan_windows", ()), ("get_mesh_window", None)):
            patcher = patch.object(MainWindow, name, return_value=result)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_file_exit_uses_window_close_path(self):
        close_calls = []
        controller = MenuController.__new__(MenuController)
        controller.window = SimpleNamespace(close=lambda: close_calls.append("close"))
        MenuController._on_quit(controller)
        self.assertEqual(close_calls, ["close"])


class MenuControllerPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_access_new_project_dialog_does_not_install_sql_save_callbacks(self):
        captured = {}

        class FakeDialog:
            def __init__(
                self,
                icon_provider,
                parent,
                cover_sheet_data,
                workspace_state_model,
                used_employee_uids=None,
                has_license=True,
                context=None,
                save_job_statuses_fn=None,
                save_job_statuses_async_fn=None,
                reload_job_statuses_fn=None,
                save_employees_fn=None,
                save_employees_async_fn=None,
                save_pay_classes_fn=None,
                save_pay_classes_async_fn=None,
                reload_employees_fn=None,
                save_bid_areas_fn=None,
                save_bid_areas_async_fn=None,
                reload_bid_areas_fn=None,
                refresh_fn=None,
                save_cover_sheet_async_fn=None,
                get_used_area_uids_fn=None,
                pdf_page_sizes_fn=None,
                bid_ref=None,
                create_mode=False,
                pages_with_takeoffs=None,
                pages_requiring_delete_confirmation=None,
                pdf_metadata_pool=None,
                employee_usage_fn=None,
                pay_class_usage_fn=None,
                job_status_usage_fn=None,
                event_bus=None,
                database_id="",
            ):
                captured.update(
                    save_job_statuses_fn=save_job_statuses_fn,
                    save_job_statuses_async_fn=save_job_statuses_async_fn,
                    save_employees_async_fn=save_employees_async_fn,
                    save_pay_classes_async_fn=save_pay_classes_async_fn,
                    save_cover_sheet_async_fn=save_cover_sheet_async_fn,
                    create_mode=create_mode,
                    database_id=database_id,
                )

            def deleteLater(self):
                pass

        controller = MenuController.__new__(MenuController)
        controller._resolve_project_tree_file_path = lambda: "projects.mdb"
        controller._resolve_target_project_uid = lambda: "project-1"
        target_identity = (object(), object())
        controller._resolve_project_tree_target_identity = (
            lambda _file_path, _project_uid: target_identity
        )
        controller.ui_access_manager = SimpleNamespace(
            can_create_project_tree_items=lambda _has_file: True,
            can_create_bid=lambda _file_path, _project_uid: True,
            has_license=lambda: True,
            is_allowed=lambda _feature: True,
        )
        saved_job_statuses = []
        controller._deferred_persistence = _permissions__FakeDeferredPersistence()
        controller._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _file_path: False,
            save_job_statuses=lambda file_path, changes: (
                saved_job_statuses.append((file_path, changes)) or True
            ),
        )
        controller._project_read_service = SimpleNamespace(
            get_settings_defaults=lambda _file_path: {},
            get_job_statuses=lambda _file_path: [],
            get_employees_and_pay_classes=lambda _file_path: ([], []),
        )
        controller.icon_provider = object()
        controller.window = object()
        controller._infrastructure_provider = SimpleNamespace(
            get_pdf_page_sizes=lambda _path: []
        )
        controller._workspace_state_model = make_workspace_state_model()
        controller._event_bus = object()
        with (
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller.CoverSheetDialog",
                FakeDialog,
            ),
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "exec_with_ost_blocking",
                return_value=QtWidgets.QDialog.DialogCode.Rejected,
            ),
        ):
            controller._new_project()
        self.assertIsNone(captured["save_job_statuses_async_fn"])
        self.assertIsNone(captured["save_employees_async_fn"])
        self.assertIsNone(captured["save_pay_classes_async_fn"])
        self.assertIsNone(captured["save_cover_sheet_async_fn"])
        self.assertTrue(captured["create_mode"])
        self.assertEqual(captured["database_id"], "projects.mdb")
        # The synchronous Access save path stays wired to the write service.
        self.assertTrue(captured["save_job_statuses_fn"]({"updated": []}))
        self.assertEqual(saved_job_statuses, [("projects.mdb", {"updated": []})])
        self.assertEqual(controller._deferred_persistence.flushes, ["projects.mdb"])

    def test_access_new_project_stops_after_main_window_destruction(self):
        continued = []
        window = QtWidgets.QWidget()

        class DestroyedWithParentDialog(QtWidgets.QDialog):
            def __init__(self, *args, **_kwargs):
                super().__init__(args[1])

            def get_updates(self):
                continued.append("updates")
                return {}

        controller = MenuController.__new__(MenuController)
        controller._resolve_project_tree_file_path = lambda: "projects.mdb"
        controller._resolve_target_project_uid = lambda: "project-1"
        target_identity = (object(), object())
        controller._resolve_project_tree_target_identity = (
            lambda _file_path, _project_uid: target_identity
        )
        controller.ui_access_manager = SimpleNamespace(
            can_create_project_tree_items=lambda _has_file: True,
            can_create_bid=lambda _file_path, _project_uid: True,
            has_license=lambda: True,
            is_allowed=lambda _feature: True,
        )
        controller._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _file_path: False,
            create_bid_result=lambda *_args: continued.append("create"),
        )
        controller._project_read_service = SimpleNamespace(
            get_settings_defaults=lambda _file_path: {},
            get_job_statuses=lambda _file_path: [],
            get_employees_and_pay_classes=lambda _file_path: ([], []),
        )
        controller.icon_provider = None
        controller.window = window
        controller._infrastructure_provider = SimpleNamespace(
            get_pdf_page_sizes=lambda _path: []
        )
        controller._workspace_state_model = make_workspace_state_model()
        controller._event_bus = object()

        def destroy_parent(_dialog, _event_bus):
            delete(window)
            return QtWidgets.QDialog.DialogCode.Accepted

        with (
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "CoverSheetDialog",
                DestroyedWithParentDialog,
            ),
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "exec_with_ost_blocking",
                side_effect=destroy_parent,
            ),
        ):
            controller._new_project()
        self.assertEqual(continued, [])

    def _run_access_new_project(self, *, result, create_result=None, during_exec=None):
        """Run the Access new-project flow against a live window and dialog."""
        window = QtWidgets.QWidget()
        self.addCleanup(window.deleteLater)
        created = []
        state = {
            "file_path": "projects.mdb",
            "project_uid": "project-1",
            "can_create": True,
            "flush_ok": True,
        }
        original_identity = (object(), object())
        state["identity"] = original_identity

        class AcceptedDialog(QtWidgets.QDialog):
            def __init__(self, *args, **_kwargs):
                super().__init__(args[1])

            def get_updates(self):
                return {"job_name": "Accepted"}

        controller = MenuController.__new__(MenuController)
        controller._resolve_project_tree_file_path = lambda: state["file_path"]
        controller._resolve_target_project_uid = lambda: state["project_uid"]
        controller._resolve_project_tree_target_identity = (
            lambda _file_path, _project_uid: state["identity"]
        )
        controller.ui_access_manager = SimpleNamespace(
            can_create_bid=lambda _file_path, _project_uid: state["can_create"],
            has_license=lambda: True,
            is_allowed=lambda _feature: True,
        )
        controller._deferred_persistence = SimpleNamespace(
            flush_for_file=lambda _file_path: state["flush_ok"]
        )
        controller._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _file_path: False,
            create_bid_result=lambda file_path, project_uid, updates: (
                created.append((file_path, project_uid, updates)) or create_result
            ),
        )
        controller._project_read_service = SimpleNamespace(
            get_settings_defaults=lambda _file_path: {},
            get_job_statuses=lambda _file_path: [],
            get_employees_and_pay_classes=lambda _file_path: ([], []),
        )
        controller.icon_provider = None
        controller.window = window
        controller._infrastructure_provider = SimpleNamespace(
            get_pdf_page_sizes=lambda _path: []
        )
        controller._workspace_state_model = make_workspace_state_model()
        controller._event_bus = object()

        def execute(_dialog, _event_bus):
            if during_exec is not None:
                during_exec(state)
            return result

        with (
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "CoverSheetDialog",
                AcceptedDialog,
            ),
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "exec_with_ost_blocking",
                side_effect=execute,
            ),
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "show_warning"
            ) as warning,
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "show_critical"
            ) as critical,
        ):
            controller._new_project()
        return created, warning, critical, window

    def test_access_new_project_accepted_creates_bid_from_dialog_updates(self):
        created, warning, critical, _window = self._run_access_new_project(
            result=QtWidgets.QDialog.DialogCode.Accepted,
            create_result=WriteReloadResult(
                "bid-new", write_success=True, reload_success=True
            ),
        )
        self.assertEqual(
            created, [("projects.mdb", "project-1", {"job_name": "Accepted"})]
        )
        warning.assert_not_called()
        critical.assert_not_called()

    def test_access_new_project_reports_refresh_and_create_failures(self):
        created, warning, critical, window = self._run_access_new_project(
            result=QtWidgets.QDialog.DialogCode.Accepted,
            create_result=WriteReloadResult(write_success=True, reload_success=False),
        )
        self.assertEqual(len(created), 1)
        warning.assert_called_once_with(
            window,
            "Refresh Error",
            "The bid was created, but the project tree could not be refreshed. "
            "Reopen the database to see the created bid.",
        )
        critical.assert_not_called()
        created, warning, critical, window = self._run_access_new_project(
            result=QtWidgets.QDialog.DialogCode.Accepted,
            create_result=WriteReloadResult(),
        )
        self.assertEqual(len(created), 1)
        warning.assert_not_called()
        critical.assert_called_once_with(window, "New Project", "Failed to create bid.")

    def test_access_new_project_does_not_create_when_context_changes_or_is_declined(
        self,
    ):
        def change_file(state):
            state["file_path"] = "other.mdb"

        def change_project(state):
            state["project_uid"] = "project-2"

        def replace_identity(state):
            state["identity"] = (object(), object())

        def lose_permission(state):
            state["can_create"] = False

        def fail_flush(state):
            state["flush_ok"] = False

        ok = WriteReloadResult("bid-new", write_success=True, reload_success=True)
        cases = {
            "rejected": (QtWidgets.QDialog.DialogCode.Rejected, None),
            "file_changed": (QtWidgets.QDialog.DialogCode.Accepted, change_file),
            "project_changed": (QtWidgets.QDialog.DialogCode.Accepted, change_project),
            "target_replaced": (
                QtWidgets.QDialog.DialogCode.Accepted,
                replace_identity,
            ),
            "permission_lost": (
                QtWidgets.QDialog.DialogCode.Accepted,
                lose_permission,
            ),
            "deferred_flush_failed": (
                QtWidgets.QDialog.DialogCode.Accepted,
                fail_flush,
            ),
        }
        for name, (result, during_exec) in cases.items():
            with self.subTest(case=name):
                created, warning, critical, _window = self._run_access_new_project(
                    result=result, create_result=ok, during_exec=during_exec
                )
                self.assertEqual(created, [])
                warning.assert_not_called()
                critical.assert_not_called()

    def test_sql_new_project_denied_initial_lease_closes_session_without_dialog(
        self,
    ):
        deleted = []
        closed = []

        class FakeDialog:
            def __init__(self, *_args, **_kwargs):
                pass

            def deleteLater(self):
                deleted.append(True)

        class DeniedLeaseSession:
            def bind_dialog(self, _dialog):
                pass

            def request_initial(self, completed):
                completed(SimpleNamespace(granted=False))

            def close(self):
                closed.append(True)

        controller = MenuController.__new__(MenuController)
        controller.ui_access_manager = SimpleNamespace(
            can_create_bid=lambda _file_path, _project_uid: True,
            has_license=lambda: True,
        )
        controller._resolve_project_tree_target_identity = (
            lambda _file_path, _project_uid: (object(), object())
        )
        controller._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _file_path: True
        )
        controller.project_data = SimpleNamespace(
            get_settings_defaults_snapshot=lambda _file_path: {},
            get_job_status_snapshot=lambda _file_path: [],
            get_employee_snapshot=lambda _file_path: [],
            get_pay_class_snapshot=lambda _file_path: [],
        )
        controller.handlers = SimpleNamespace(
            cover_sheet=SimpleNamespace(
                create_new_bid_lease_session=(
                    lambda _file_path, _project_uid, _data: DeniedLeaseSession()
                )
            )
        )
        controller.icon_provider = object()
        controller.window = object()
        controller._infrastructure_provider = SimpleNamespace(
            get_pdf_page_sizes=lambda _path: []
        )
        controller._workspace_state_model = make_workspace_state_model()
        controller._event_bus = object()
        with (
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller.CoverSheetDialog",
                FakeDialog,
            ),
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "exec_with_ost_blocking",
                side_effect=AssertionError("denied lease must not run the dialog"),
            ),
        ):
            controller._new_project_at("sql-database", "project-1")
        self.assertEqual(deleted, [True])
        self.assertEqual(closed, [True])

    def test_sql_new_project_nested_and_outer_saves_transfer_dialog_ownership(self):
        captured = {}
        transferred = []
        completions = []
        queue_job_statuses_save = object()
        queue_employees_save = object()
        queue_pay_classes_save = object()

        class FakeDialog:
            def __init__(self, *_args, **kwargs):
                captured.update(kwargs)

            def deleteLater(self):
                pass

        class FakeLeaseSession:
            def __init__(self):
                self.next_handle = 1
                self.closed = False

            def bind_dialog(self, _dialog):
                pass

            def request_initial(self, completed):
                completed(SimpleNamespace(granted=True))

            def submit_mutation(self, submit, completed):
                handle = f"handle-{self.next_handle}"
                self.next_handle += 1
                return submit(handle, completed)

            def close(self):
                self.closed = True

        lease_session = FakeLeaseSession()

        class FakeCoverSheetHandler:
            @staticmethod
            def create_new_bid_lease_session(_file_path, _project_uid, _data):
                return lease_session

            @staticmethod
            def save_master_data_async(
                file_path,
                title,
                queue_fn,
                changes,
                completed,
                result_family,
                *,
                edit_lease_handle,
            ):
                transferred.append(
                    (
                        "master",
                        edit_lease_handle,
                        file_path,
                        title,
                        queue_fn,
                        changes,
                        result_family,
                    )
                )
                completed(True, {"family": result_family})
                return True

            @staticmethod
            def create_bid_async(
                file_path,
                project_uid,
                updates,
                completed,
                *,
                edit_lease_handle,
            ):
                transferred.append(
                    ("bid", edit_lease_handle, file_path, project_uid, updates)
                )
                completed(True)
                return True

        controller = MenuController.__new__(MenuController)
        controller._resolve_project_tree_file_path = lambda: "sql-database"
        controller._resolve_target_project_uid = lambda: "project-1"
        target_identity = (object(), object())
        controller._resolve_project_tree_target_identity = (
            lambda _file_path, _project_uid: target_identity
        )
        controller.ui_access_manager = SimpleNamespace(
            can_create_project_tree_items=lambda _has_file: True,
            can_create_bid=lambda _file_path, _project_uid: True,
            has_license=lambda: True,
            is_allowed=lambda _feature: True,
        )
        controller._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _file_path: True,
            queue_job_statuses_save=queue_job_statuses_save,
            queue_employees_save=queue_employees_save,
            queue_pay_classes_save=queue_pay_classes_save,
        )
        controller.project_data = SimpleNamespace(
            get_settings_defaults_snapshot=lambda _file_path: {},
            get_job_status_snapshot=lambda _file_path: [],
            get_employee_snapshot=lambda _file_path: [],
            get_pay_class_snapshot=lambda _file_path: [],
        )
        controller.handlers = SimpleNamespace(
            cover_sheet=FakeCoverSheetHandler(),
        )
        controller.icon_provider = object()
        controller.window = object()
        controller._infrastructure_provider = SimpleNamespace(
            get_pdf_page_sizes=lambda _path: []
        )
        controller._workspace_state_model = make_workspace_state_model()
        controller._event_bus = object()

        def execute(dialog, _event_bus):
            self.assertIsNotNone(dialog)
            self.assertTrue(
                captured["save_job_statuses_async_fn"](
                    {"updated": ["job"]},
                    lambda success, mapping: completions.append(
                        ("job_statuses", success, mapping)
                    ),
                )
            )
            self.assertTrue(
                captured["save_cover_sheet_async_fn"](
                    {"job_name": "New"},
                    lambda success: completions.append(("cover_sheet", success)),
                )
            )
            self.assertTrue(
                captured["save_employees_async_fn"](
                    {"updated": ["employee"]},
                    lambda success, mapping: completions.append(
                        ("employees", success, mapping)
                    ),
                )
            )
            self.assertTrue(
                captured["save_pay_classes_async_fn"](
                    {"updated": ["pay class"]},
                    lambda success, mapping: completions.append(
                        ("pay_classes", success, mapping)
                    ),
                )
            )
            return QtWidgets.QDialog.DialogCode.Rejected

        with (
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller.CoverSheetDialog",
                FakeDialog,
            ),
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "exec_with_ost_blocking",
                side_effect=execute,
            ),
        ):
            controller._new_project()
        self.assertEqual(
            transferred,
            [
                (
                    "master",
                    "handle-1",
                    "sql-database",
                    "Job Statuses",
                    queue_job_statuses_save,
                    {"updated": ["job"]},
                    "job_statuses",
                ),
                (
                    "bid",
                    "handle-2",
                    "sql-database",
                    "project-1",
                    {"job_name": "New"},
                ),
                (
                    "master",
                    "handle-3",
                    "sql-database",
                    "Employees",
                    queue_employees_save,
                    {"updated": ["employee"]},
                    "employees",
                ),
                (
                    "master",
                    "handle-4",
                    "sql-database",
                    "Payroll Classes",
                    queue_pay_classes_save,
                    {"updated": ["pay class"]},
                    "pay_classes",
                ),
            ],
        )
        self.assertEqual(
            completions,
            [
                ("job_statuses", True, {"family": "job_statuses"}),
                ("cover_sheet", True),
                ("employees", True, {"family": "employees"}),
                ("pay_classes", True, {"family": "pay_classes"}),
            ],
        )
        self.assertTrue(lease_session.closed)

    def test_menu_variable_sync_uses_registered_getter_and_restores_signal_block(self):
        action = QtGui.QAction()
        action.setCheckable(True)
        action.blockSignals(True)
        controller = MenuController.__new__(MenuController)
        controller._variable_actions = {"display_mode_3d": [action]}
        controller._state_getters = {"display_mode_3d": lambda: True}
        controller._sync_variable_actions(takeoff_active=True)
        self.assertTrue(action.isChecked())
        self.assertTrue(action.signalsBlocked())

    def test_menu_variable_sync_unchecks_when_getter_is_false(self):
        action = QtGui.QAction()
        action.setCheckable(True)
        action.setChecked(True)
        action.blockSignals(True)
        controller = MenuController.__new__(MenuController)
        controller._variable_actions = {"grayscale": [action]}
        controller._state_getters = {"grayscale": lambda: False}
        controller._sync_variable_actions(takeoff_active=True)
        self.assertFalse(action.isChecked())
        self.assertTrue(action.signalsBlocked())

    def test_menu_variable_sync_clears_only_takeoff_scoped_actions_outside_takeoff(
        self,
    ):
        scoped = QtGui.QAction()
        unscoped = QtGui.QAction()
        for action in (scoped, unscoped):
            action.setCheckable(True)
        scoped.setChecked(True)
        controller = MenuController.__new__(MenuController)
        controller.window = SimpleNamespace(is_takeoff_tab_active=lambda: False)
        controller._variable_actions = {
            "grayscale": [scoped],
            "toolbar_visible": [unscoped],
        }
        controller._state_getters = {
            "grayscale": lambda: True,
            "toolbar_visible": lambda: True,
        }
        controller._sync_variable_actions()
        self.assertFalse(scoped.isChecked())
        self.assertTrue(unscoped.isChecked())

    def test_menu_radio_sync_updates_exclusive_group_ownership(self):
        first = QtGui.QAction()
        second = QtGui.QAction()
        for action, value in ((first, "first"), (second, "second")):
            action.setCheckable(True)
            action.setData(value)
        group = QtGui.QActionGroup(None)
        group.setExclusive(True)
        group.addAction(first)
        group.addAction(second)
        first.setChecked(True)
        triggered = []
        second.triggered.connect(triggered.append)
        controller = MenuController.__new__(MenuController)
        controller._variable_actions = {"display_mode_3d": [first, second]}
        controller._state_getters = {"display_mode_3d": lambda: "second"}
        controller._sync_variable_actions(takeoff_active=True)
        controller._sync_variable_actions(takeoff_active=True)
        self.assertFalse(first.isChecked())
        self.assertTrue(second.isChecked())
        self.assertIs(group.checkedAction(), second)
        self.assertEqual(triggered, [])
        first.trigger()
        self.assertTrue(first.isChecked())
        self.assertFalse(second.isChecked())
        self.assertIs(group.checkedAction(), first)

    def test_menu_radio_clear_releases_exclusive_group_ownership(self):
        first = QtGui.QAction()
        second = QtGui.QAction()
        for action, value in ((first, "first"), (second, "second")):
            action.setCheckable(True)
            action.setData(value)
        group = QtGui.QActionGroup(None)
        group.setExclusive(True)
        group.addAction(first)
        group.addAction(second)
        first.setChecked(True)
        controller = MenuController.__new__(MenuController)
        controller._variable_actions = {"display_mode_3d": [first, second]}
        controller._state_getters = {"display_mode_3d": lambda: "first"}
        controller._sync_variable_actions(takeoff_active=False)
        controller._sync_variable_actions(takeoff_active=False)
        self.assertFalse(first.isChecked())
        self.assertFalse(second.isChecked())
        self.assertIsNone(group.checkedAction())
        self.assertTrue(group.isExclusive())
        controller._sync_variable_actions(takeoff_active=True)
        self.assertTrue(first.isChecked())
        self.assertFalse(second.isChecked())
        self.assertIs(group.checkedAction(), first)

    def test_summary_tab_disables_project_tree_creation_but_allows_import(self):
        controller = MenuController.__new__(MenuController)
        controller.window = SimpleNamespace(is_summary_tab_active=lambda: True)
        controller.ui_state_manager = SimpleNamespace(selected_project_uid="2")
        permission_checks = []
        controller.ui_access_manager = SimpleNamespace(
            can_create_project_tree_items=lambda *_args: (_ for _ in ()).throw(
                AssertionError("project selection should not be queried")
            ),
            is_allowed=lambda feature: permission_checks.append(feature) or True,
        )
        self.assertFalse(controller._should_enable_project_tree_creation())
        self.assertTrue(controller._should_enable_import())
        self.assertEqual(permission_checks, [Feature.IMPORT])

    def test_import_is_disabled_for_database_root_project_selection(self):
        controller = MenuController.__new__(MenuController)
        controller.ui_state_manager = SimpleNamespace(selected_project_uid="1")
        controller.ui_access_manager = SimpleNamespace(is_allowed=lambda _feature: True)
        self.assertFalse(controller._should_enable_import())
        controller.ui_state_manager = SimpleNamespace(selected_project_uid="2")
        self.assertTrue(controller._should_enable_import())

    def test_import_stays_disabled_when_context_permission_is_unavailable(self):
        controller = MenuController.__new__(MenuController)
        controller.window = SimpleNamespace(is_summary_tab_active=lambda: True)
        controller.ui_state_manager = SimpleNamespace(selected_project_uid=None)
        controller.ui_access_manager = SimpleNamespace(
            is_allowed=lambda feature: feature != Feature.IMPORT
        )
        self.assertIs(controller._should_enable_import(), False)
        controller.ui_access_manager = SimpleNamespace(is_allowed=lambda _feature: True)
        self.assertIs(controller._should_enable_import(), True)

    def test_menu_refresh_uses_explicit_backout_refresh_method(self):
        _preferences_support__app()
        action = QtGui.QAction()
        explicit_refresh_calls = []
        controller = MenuController.__new__(MenuController)
        controller._actions = {"backout_mode": action}
        controller._tool_action_enabled_state = {"backout_mode": True}
        controller.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(
                refresh_backout_action=lambda: explicit_refresh_calls.append(1)
            )
        )
        MenuController._sync_tool_action_states(controller, True)
        self.assertEqual(explicit_refresh_calls, [1])
        self.assertEqual(controller._tool_action_enabled_state, {})
        controller._actions = {}
        MenuController._sync_tool_action_states(controller, True)
        self.assertEqual(explicit_refresh_calls, [1])

    def test_tool_actions_disable_outside_takeoff_and_restore_prior_state(self):
        select_tool = _Action()
        place_tool = _Action()
        place_tool.setEnabled(False)
        pan_tool = _Action()
        controller = MenuController.__new__(MenuController)
        controller._actions = {
            "select_tool": select_tool,
            "place_tool": place_tool,
            "pan_tool": pan_tool,
        }
        controller._tool_action_enabled_state = {}
        controller.window = SimpleNamespace(
            opengl_viewer=None,
            get_view_stack=lambda: None,
            get_takeoff_plan_view=lambda: None,
        )
        with patch(
            "ost_visualizer.presentation.controllers.menu_controller."
            "scene_navigation_available",
            return_value=True,
        ):
            MenuController._sync_tool_action_states(controller, False)
            self.assertFalse(select_tool.isEnabled())
            self.assertFalse(place_tool.isEnabled())
            self.assertFalse(pan_tool.isEnabled())
            self.assertEqual(
                controller._tool_action_enabled_state,
                {"select_tool": True, "place_tool": False},
            )
            # Repeating while disabled must not overwrite the remembered state.
            MenuController._sync_tool_action_states(controller, False)
            self.assertEqual(
                controller._tool_action_enabled_state,
                {"select_tool": True, "place_tool": False},
            )
            MenuController._sync_tool_action_states(controller, True)
        self.assertTrue(select_tool.isEnabled())
        self.assertFalse(place_tool.isEnabled())
        self.assertTrue(pan_tool.isEnabled())
        self.assertEqual(controller._tool_action_enabled_state, {})


class ExportMenuStateTests(unittest.TestCase):
    def test_page_image_visibility_actions_follow_available_sources(self):
        bid_ref = BidRef("db.mdb", "bid-1")
        ui_state = _UiState(bid_ref)
        ui_state.active_page_uid = "page-1"
        project_data = _ProjectData(bid_ref)
        controller = _controller(ui_state, project_data)
        controller.window = SimpleNamespace(
            is_takeoff_tab_active=lambda: True,
            is_summary_tab_active=lambda: False,
            get_takeoff_plan_view=lambda: None,
        )
        controller._actions.update(
            {
                ACTION_SHOW_ORIGINAL_IMAGE: _Action(),
                ACTION_SHOW_OVERLAY_IMAGE: _Action(),
                "set_scale": _Action(),
                "rename_page": _Action(),
            }
        )
        project_data.page.image_path = ""
        project_data.page.overlay_image_path = "overlay.pdf"
        controller.update_menu_states()
        self.assertFalse(controller._actions[ACTION_SHOW_ORIGINAL_IMAGE].isEnabled())
        self.assertTrue(controller._actions[ACTION_SHOW_OVERLAY_IMAGE].isEnabled())
        project_data.page.image_path = "original.pdf"
        project_data.page.overlay_image_path = ""
        controller.update_menu_states()
        self.assertTrue(controller._actions[ACTION_SHOW_ORIGINAL_IMAGE].isEnabled())
        self.assertFalse(controller._actions[ACTION_SHOW_OVERLAY_IMAGE].isEnabled())
        project_data.page.overlay_image_path = "overlay.pdf"
        controller.update_menu_states()
        self.assertTrue(controller._actions[ACTION_SHOW_ORIGINAL_IMAGE].isEnabled())
        self.assertTrue(controller._actions[ACTION_SHOW_OVERLAY_IMAGE].isEnabled())
        self.assertTrue(controller._actions["set_scale"].isEnabled())
        self.assertTrue(controller._actions["rename_page"].isEnabled())
        # Both sources exist, but the image actions still follow page context.
        ui_state.active_page_uid = None
        controller.update_menu_states()
        self.assertFalse(controller._actions["set_scale"].isEnabled())
        self.assertFalse(controller._actions["rename_page"].isEnabled())
        self.assertFalse(controller._actions[ACTION_SHOW_ORIGINAL_IMAGE].isEnabled())
        self.assertFalse(controller._actions[ACTION_SHOW_OVERLAY_IMAGE].isEnabled())
        ui_state.active_page_uid = "page-1"
        controller.ui_access_manager = _Access(denied={Feature.EDIT_PAGE_SETTINGS})
        controller.update_menu_states()
        self.assertFalse(controller._actions[ACTION_SHOW_ORIGINAL_IMAGE].isEnabled())
        self.assertFalse(controller._actions[ACTION_SHOW_OVERLAY_IMAGE].isEnabled())
        controller.ui_access_manager = _Access()
        controller.window = SimpleNamespace(
            is_takeoff_tab_active=lambda: False,
            is_summary_tab_active=lambda: False,
            get_takeoff_plan_view=lambda: None,
        )
        controller.update_menu_states()
        self.assertFalse(controller._actions[ACTION_SHOW_ORIGINAL_IMAGE].isEnabled())
        self.assertFalse(controller._actions[ACTION_SHOW_OVERLAY_IMAGE].isEnabled())

    def test_import_menu_remains_enabled_when_switching_across_all_tabs(self):
        bid_ref = BidRef("db.mdb", "bid-1")
        controller = _controller(_UiState(bid_ref), _ProjectData(bid_ref))
        tab_state = {"takeoff": False, "summary": False}
        controller.window = SimpleNamespace(
            is_takeoff_tab_active=lambda: tab_state["takeoff"],
            is_summary_tab_active=lambda: tab_state["summary"],
            get_takeoff_plan_view=lambda: None,
        )
        for takeoff, summary in ((False, False), (True, False), (False, True)):
            tab_state.update(takeoff=takeoff, summary=summary)
            controller.update_menu_states()
            self.assertTrue(controller._menus["import"].isEnabled())

    def test_import_menu_is_disabled_without_import_capability(self):
        controller = _controller(_UiState(), _ProjectData())
        controller.ui_access_manager = _Access(allowed=False)
        controller.update_menu_states()
        self.assertFalse(controller._menus["import"].isEnabled())

    def test_bid_exports_disable_when_loaded_bid_is_not_selected(self):
        old_bid = BidRef("db.mdb", "old-bid")
        csv_calls = []
        controller = _controller(
            _UiState(bid_ref=None), _ProjectData(old_bid), csv_calls
        )
        controller.update_menu_states()
        self.assertFalse(controller._actions["export_as_html"].isEnabled())
        self.assertFalse(controller._actions["export_as_pdf"].isEnabled())
        self.assertFalse(controller._actions["export_summary_csv"].isEnabled())
        self.assertFalse(controller._actions["export_as_ost"].isEnabled())
        self.assertFalse(controller._actions["export_as_osp"].isEnabled())
        self.assertFalse(controller._menus["export"].isEnabled())
        controller.trigger_menu_action("export_summary_csv")
        self.assertEqual(csv_calls, [])

    def test_bid_exports_disable_when_selected_bid_differs_from_loaded_bid(self):
        for selected_bid in (BidRef("db.mdb", "new-bid"), BidRef("other.mdb", "old")):
            with self.subTest(selected_bid=selected_bid):
                csv_calls = []
                controller = _controller(
                    _UiState(selected_bid),
                    _ProjectData(BidRef("db.mdb", "old")),
                    csv_calls,
                )
                controller.update_menu_states()
                for key in (
                    "export_as_html",
                    "export_as_pdf",
                    "export_summary_csv",
                    "export_as_ost",
                    "export_as_osp",
                ):
                    self.assertFalse(controller._actions[key].isEnabled(), key)
                self.assertFalse(controller._menus["export"].isEnabled())
                controller.trigger_menu_action("export_summary_csv")
                self.assertEqual(csv_calls, [])

    def test_bid_exports_follow_export_permissions_and_available_content(self):
        bid_ref = BidRef("db.mdb", "bid-1")
        cases = {
            "export_denied": {
                "access": _Access(denied={Feature.EXPORT}),
                "expected": {"html": False, "pdf": False, "csv": False, "bid": True},
            },
            "bid_file_export_denied": {
                "access": _Access(denied={Feature.EXPORT_BID_FILE}),
                "expected": {"html": True, "pdf": True, "csv": True, "bid": False},
            },
            "no_takeoffs": {
                "takeoffs": [],
                "expected": {"html": False, "pdf": True, "csv": False, "bid": True},
            },
            "no_conditions": {
                "conditions": {},
                "expected": {"html": True, "pdf": True, "csv": False, "bid": True},
            },
            "no_selected_pages": {
                "selected": [],
                "expected": {"html": False, "pdf": False, "csv": True, "bid": True},
            },
        }
        for name, case in cases.items():
            with self.subTest(case=name):
                project_data = _ProjectData(bid_ref)
                if "takeoffs" in case:
                    project_data.takeoffs = case["takeoffs"]
                if "conditions" in case:
                    project_data.conditions = case["conditions"]
                if "selected" in case:
                    project_data.selected_page_uids = case["selected"]
                controller = _controller(_UiState(bid_ref), project_data)
                if "access" in case:
                    controller.ui_access_manager = case["access"]
                controller.update_menu_states()
                expected = case["expected"]
                actions = controller._actions
                self.assertEqual(
                    actions["export_as_html"].isEnabled(), expected["html"]
                )
                self.assertEqual(actions["export_as_pdf"].isEnabled(), expected["pdf"])
                self.assertEqual(
                    actions["export_summary_csv"].isEnabled(), expected["csv"]
                )
                self.assertEqual(actions["export_as_ost"].isEnabled(), expected["bid"])
                self.assertEqual(actions["export_as_osp"].isEnabled(), expected["bid"])
                self.assertEqual(
                    controller._menus["export"].isEnabled(), any(expected.values())
                )

    def test_bid_exports_enable_from_matching_selected_loaded_bid(self):
        bid_ref = BidRef("db.mdb", "bid-1")
        csv_calls = []
        ui_state = _UiState(bid_ref)
        controller = _controller(ui_state, _ProjectData(bid_ref), csv_calls)
        controller.update_menu_states()
        self.assertTrue(controller._actions["export_as_html"].isEnabled())
        self.assertTrue(controller._actions["export_as_pdf"].isEnabled())
        self.assertTrue(controller._actions["export_summary_csv"].isEnabled())
        self.assertTrue(controller._actions["export_as_ost"].isEnabled())
        self.assertTrue(controller._actions["export_as_osp"].isEnabled())
        self.assertTrue(controller._menus["export"].isEnabled())
        controller.trigger_menu_action("export_summary_csv")
        self.assertEqual(csv_calls, ["csv"])
        # Triggering refreshes menu state first, so a stale enabled action is blocked.
        ui_state._bid_ref = None
        controller.trigger_menu_action("export_summary_csv")
        self.assertEqual(csv_calls, ["csv"])

    def test_pdf_export_accepts_tiff_pages_supported_by_raster_export(self):
        bid_ref = BidRef("db.mdb", "bid-1")
        project_data = _ProjectData(bid_ref)
        project_data.page.image_path = "drawing.tif"
        controller = _controller(_UiState(bid_ref), project_data)
        self.assertTrue(controller._should_enable_pdf_export())

    def test_pdf_export_enables_when_any_selected_page_is_valid(self):
        bid_ref = BidRef("db.mdb", "bid-1")
        project_data = _ProjectData(bid_ref)
        project_data.selected_page_uids = ["invalid", "valid"]
        pages = {
            "invalid": Page(uid="invalid", name="Invalid", width_pts=0, height_pts=0),
            "valid": Page(uid="valid", name="Valid", width_pts=612, height_pts=792),
        }
        project_data.get_page = pages.get
        controller = _controller(_UiState(bid_ref), project_data)
        self.assertTrue(controller._should_enable_pdf_export())

    def test_pdf_export_disables_without_a_valid_selected_page(self):
        bid_ref = BidRef("db.mdb", "bid-1")
        project_data = _ProjectData(bid_ref)
        pages = {
            "zero-width": Page(uid="zero-width", name="A", width_pts=0, height_pts=792),
            "zero-height": Page(
                uid="zero-height", name="B", width_pts=612, height_pts=0
            ),
        }
        project_data.selected_page_uids = ["zero-width", "zero-height", "missing"]
        project_data.get_page = pages.get
        controller = _controller(_UiState(bid_ref), project_data)
        self.assertFalse(controller._should_enable_pdf_export())
        project_data.selected_page_uids = []
        self.assertFalse(controller._should_enable_pdf_export())
        project_data.selected_page_uids = ["page-1"]
        project_data.get_page = lambda _uid: Page(
            uid="page-1", name="A1", width_pts=612, height_pts=792
        )
        self.assertTrue(controller._should_enable_pdf_export())
        controller = _controller(_UiState(None), project_data)
        self.assertFalse(controller._should_enable_pdf_export())

    def test_select_current_area_menu_and_handler_require_selection_access(self):
        bid_ref = BidRef("db.mdb", "bid-1")
        controller = _controller(_UiState(bid_ref), _ProjectData(bid_ref))
        selected = []
        plan_view = SimpleNamespace(
            current_page_uid="page-1",
            has_takeoff_objects=True,
            has_selected_takeoffs=False,
            select_takeoffs_in_area=lambda area_uid: selected.append(area_uid),
        )
        controller._actions["select_objects_in_current_area"] = _Action()
        controller.window = SimpleNamespace(
            is_takeoff_tab_active=lambda: True,
            is_summary_tab_active=lambda: False,
            get_takeoff_plan_view=lambda: plan_view,
            get_page_settings_bar=lambda: SimpleNamespace(
                get_selected_area_uid=lambda: "area-1"
            ),
            resolve_current_area_selection_context=lambda: CurrentAreaSelectionContext(
                parent=plan_view,
                plan_view=plan_view,
                area_uid="area-1",
            ),
        )
        controller.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(refresh_toolbar=lambda: None)
        )
        controller.ui_access_manager = _Access(allowed=False)
        controller.update_menu_states()
        controller._select_objects_in_current_area()
        self.assertFalse(
            controller._actions["select_objects_in_current_area"].isEnabled()
        )
        self.assertEqual(selected, [])

    def _select_area_controller(self, plan_view, access):
        bid_ref = BidRef("db.mdb", "bid-1")
        controller = _controller(_UiState(bid_ref), _ProjectData(bid_ref))
        toolbar_refreshes = []
        controller._actions["select_objects_in_current_area"] = _Action()
        controller.window = SimpleNamespace(
            is_takeoff_tab_active=lambda: True,
            is_summary_tab_active=lambda: False,
            get_takeoff_plan_view=lambda: plan_view,
            resolve_current_area_selection_context=lambda: CurrentAreaSelectionContext(
                parent="parent-window",
                plan_view=plan_view,
                area_uid="area-1",
            ),
        )
        controller.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(
                refresh_toolbar=lambda: toolbar_refreshes.append(1)
            )
        )
        controller.ui_access_manager = access
        return controller, toolbar_refreshes

    def test_select_current_area_runs_with_selection_access_and_takeoff_objects(self):
        selected = []
        plan_view = SimpleNamespace(
            current_page_uid="page-1",
            has_takeoff_objects=True,
            has_selected_takeoffs=False,
            select_takeoffs_in_area=lambda area_uid: selected.append(area_uid),
        )
        controller, toolbar_refreshes = self._select_area_controller(
            plan_view, _Access()
        )
        controller.update_menu_states()
        action = controller._actions["select_objects_in_current_area"]
        self.assertTrue(action.isEnabled())
        controller._select_objects_in_current_area()
        self.assertEqual(selected, ["area-1"])
        self.assertEqual(toolbar_refreshes, [1])
        for empty_view in (
            SimpleNamespace(
                current_page_uid="",
                has_takeoff_objects=True,
                has_selected_takeoffs=False,
            ),
            SimpleNamespace(
                current_page_uid="page-1",
                has_takeoff_objects=False,
                has_selected_takeoffs=False,
            ),
        ):
            with self.subTest(plan_view=empty_view):
                controller, _ = self._select_area_controller(empty_view, _Access())
                controller.update_menu_states()
                self.assertFalse(
                    controller._actions["select_objects_in_current_area"].isEnabled()
                )

    def test_select_current_area_warns_when_plan_view_is_gone(self):
        controller, toolbar_refreshes = self._select_area_controller(None, _Access())
        with patch(
            "ost_visualizer.presentation.controllers.menu_controller.show_warning"
        ) as warning:
            controller._select_objects_in_current_area()
        warning.assert_called_once_with(
            "parent-window",
            "Select Objects in Current Area",
            "The active plan view is no longer available. Activate an open plan "
            "view and try again.",
        )
        self.assertEqual(toolbar_refreshes, [])


class MenuControllerSqlDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _database_foundation_support__app()
        cls.icon_provider = _database_foundation_support__IconProvider()

    def test_new_database_type_routes_sql_and_preserves_access_name_flow(self):
        class _TypeDialog:
            backend = DatabaseBackend.SQL_SERVER

            def __init__(self, _icon_provider, _parent=None):
                pass

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def selected_backend(self):
                return self.backend

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        sql_calls = []
        controller = SimpleNamespace(
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            icon_provider=self.icon_provider,
            window=None,
            handlers=SimpleNamespace(
                file_ops=SimpleNamespace(
                    create_sql_database=lambda: sql_calls.append("sql")
                )
            ),
        )

        class _ForbiddenNameDialog:
            def __init__(self, *_args):
                raise AssertionError("the SQL backend must not ask for a file name")

        with (
            patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "NewDatabaseTypeDialog",
                _TypeDialog,
            ),
            patch.object(QtWidgets, "QInputDialog", _ForbiddenNameDialog),
        ):
            MenuController._new_database(controller)
        self.assertEqual(sql_calls, ["sql"])

        class _AccessNameDialog:
            instances = []
            result = QtWidgets.QDialog.DialogCode.Accepted

            def __init__(self, _parent):
                self.title = ""
                self.label = ""
                self.deleted = False
                self.instances.append(self)

            def setWindowTitle(self, title):
                self.title = title

            def setLabelText(self, label):
                self.label = label

            def setTextValue(self, _value):
                pass

            def setModal(self, _modal):
                pass

            def exec(self):
                return self.result

            def textValue(self):
                return "Access Database"

            def deleteLater(self):
                self.deleted = True

        _TypeDialog.backend = DatabaseBackend.ACCESS
        created_names = []
        loaded_paths = []
        controller._create_new_database_fn = lambda name: (
            created_names.append(name) or "access.mdb"
        )
        controller._file_loading_service = SimpleNamespace(
            load_file=lambda path: (
                loaded_paths.append(path)
                or SimpleNamespace(success=True, file_path=path)
            )
        )
        published = []
        controller._event_bus = SimpleNamespace(
            publish=lambda *args, **kwargs: published.append((args, kwargs))
        )
        with (
            patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "NewDatabaseTypeDialog",
                _TypeDialog,
            ),
            patch.object(QtWidgets, "QInputDialog", _AccessNameDialog),
            patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "remove_minimize_maximize"
            ),
            patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "show_critical",
                side_effect=AssertionError("a created database is not an error"),
            ),
        ):
            MenuController._new_database(controller)
        self.assertEqual(created_names, ["Access Database"])
        self.assertEqual(loaded_paths, ["access.mdb"])
        self.assertEqual(
            published,
            [((AppEvents.FILE_OPENED,), {"file_path": "access.mdb"})],
        )
        self.assertEqual(_AccessNameDialog.instances[0].title, "New Database")
        self.assertEqual(_AccessNameDialog.instances[0].label, "Database name:")
        self.assertTrue(_AccessNameDialog.instances[0].deleted)
        _AccessNameDialog.result = QtWidgets.QDialog.DialogCode.Rejected
        with (
            patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "NewDatabaseTypeDialog",
                _TypeDialog,
            ),
            patch.object(QtWidgets, "QInputDialog", _AccessNameDialog),
            patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "remove_minimize_maximize"
            ),
        ):
            MenuController._new_database(controller)
        self.assertEqual(created_names, ["Access Database"])
        self.assertEqual(loaded_paths, ["access.mdb"])
        self.assertEqual(len(published), 1)
        self.assertTrue(_AccessNameDialog.instances[1].deleted)
        original_icon_provider = controller.icon_provider
        controller.icon_provider = SimpleNamespace(
            set_window_icon=lambda _dialog: (_ for _ in ()).throw(
                RuntimeError("icon setup failed")
            )
        )
        _AccessNameDialog.result = QtWidgets.QDialog.DialogCode.Accepted
        with (
            patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "NewDatabaseTypeDialog",
                _TypeDialog,
            ),
            patch.object(QtWidgets, "QInputDialog", _AccessNameDialog),
        ):
            with self.assertRaisesRegex(RuntimeError, "icon setup failed"):
                MenuController._new_database(controller)
        self.assertTrue(_AccessNameDialog.instances[2].deleted)
        controller.icon_provider = original_icon_provider

    def test_new_database_stops_when_type_dialog_is_rejected_or_access_denied(self):
        class _RejectedTypeDialog:
            def __init__(self, _icon_provider, _parent=None):
                pass

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Rejected

            def selected_backend(self):
                raise AssertionError("rejected type dialog must not be read")

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        controller = SimpleNamespace(
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            icon_provider=self.icon_provider,
            window=None,
            handlers=SimpleNamespace(
                file_ops=SimpleNamespace(
                    create_sql_database=lambda: self.fail("rejected type dialog")
                )
            ),
            _create_new_database_fn=lambda _name: self.fail("rejected type dialog"),
        )

        class _ForbiddenNameDialog:
            def __init__(self, *_args):
                raise AssertionError("no name dialog without a chosen backend")

        with (
            patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "NewDatabaseTypeDialog",
                _RejectedTypeDialog,
            ),
            patch.object(QtWidgets, "QInputDialog", _ForbiddenNameDialog),
        ):
            MenuController._new_database(controller)
        controller.ui_access_manager = SimpleNamespace(
            is_allowed=lambda feature: feature != Feature.CREATE_DATABASE
        )
        with patch(
            "ost_visualizer.presentation.controllers.menu_controller."
            "NewDatabaseTypeDialog",
            side_effect=AssertionError("denied access must not open the dialog"),
        ):
            MenuController._new_database(controller)

    def _run_access_new_database(self, *, created_path, load_result):
        class _AccessTypeDialog:
            def __init__(self, _icon_provider, _parent=None):
                pass

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def selected_backend(self):
                return DatabaseBackend.ACCESS

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        class _NameDialog:
            def __init__(self, _parent):
                pass

            def setWindowTitle(self, _title):
                pass

            def setLabelText(self, _label):
                pass

            def setTextValue(self, _value):
                pass

            def setModal(self, _modal):
                pass

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def textValue(self):
                return "  "

            def deleteLater(self):
                pass

        created_names = []
        loaded_paths = []
        published = []
        controller = SimpleNamespace(
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            icon_provider=self.icon_provider,
            window="main-window",
            handlers=SimpleNamespace(file_ops=SimpleNamespace()),
            _create_new_database_fn=lambda name: (
                created_names.append(name) or created_path
            ),
            _file_loading_service=SimpleNamespace(
                load_file=lambda path: loaded_paths.append(path) or load_result
            ),
            _event_bus=SimpleNamespace(
                publish=lambda *args, **kwargs: published.append((args, kwargs))
            ),
        )
        with (
            patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "NewDatabaseTypeDialog",
                _AccessTypeDialog,
            ),
            patch.object(QtWidgets, "QInputDialog", _NameDialog),
            patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "remove_minimize_maximize"
            ),
            patch(
                "ost_visualizer.presentation.controllers.menu_controller.isValid",
                return_value=True,
            ),
            patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "show_critical"
            ) as critical,
        ):
            MenuController._new_database(controller)
        return created_names, loaded_paths, published, critical

    def test_new_access_database_reports_creation_failure_without_loading(self):
        created_names, loaded_paths, published, critical = (
            self._run_access_new_database(created_path=None, load_result=None)
        )
        self.assertEqual(created_names, [None])
        self.assertEqual(loaded_paths, [])
        self.assertEqual(published, [])
        critical.assert_called_once_with(
            "main-window",
            "New Database",
            "Failed to create database. Check logs for details.",
        )

    def test_new_access_database_does_not_announce_file_when_load_fails(self):
        created_names, loaded_paths, published, critical = (
            self._run_access_new_database(
                created_path="new.mdb",
                load_result=SimpleNamespace(success=False, file_path="new.mdb"),
            )
        )
        self.assertEqual(created_names, [None])
        self.assertEqual(loaded_paths, ["new.mdb"])
        self.assertEqual(published, [])
        critical.assert_not_called()

    def test_new_database_stops_when_type_dialog_destroys_main_window(self):
        window = QtWidgets.QWidget()

        class _DestroyingTypeDialog(QtWidgets.QDialog):
            def __init__(self, _icon_provider, parent=None):
                super().__init__(parent)

            def exec(self):
                delete(self.parent())
                return QtWidgets.QDialog.DialogCode.Accepted

            def selected_backend(self):
                raise AssertionError("destroyed type dialog must not be read")

            def cleanup(self):
                pass

        controller = SimpleNamespace(
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            icon_provider=self.icon_provider,
            window=window,
            handlers=SimpleNamespace(
                file_ops=SimpleNamespace(
                    create_sql_database=lambda: self.fail(
                        "destroyed window must not continue database creation"
                    )
                )
            ),
        )
        with patch(
            "ost_visualizer.presentation.controllers.menu_controller."
            "NewDatabaseTypeDialog",
            _DestroyingTypeDialog,
        ):
            MenuController._new_database(controller)

    def test_new_access_database_stops_when_name_dialog_destroys_main_window(self):
        window = QtWidgets.QWidget()

        class _AccessTypeDialog:
            def __init__(self, _icon_provider, _parent=None):
                pass

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def selected_backend(self):
                return DatabaseBackend.ACCESS

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        class _DestroyingNameDialog(QtWidgets.QInputDialog):
            def exec(self):
                delete(self.parent())
                return QtWidgets.QDialog.DialogCode.Accepted

            def textValue(self):
                raise AssertionError("destroyed name dialog must not be read")

        controller = SimpleNamespace(
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            icon_provider=self.icon_provider,
            window=window,
            handlers=SimpleNamespace(file_ops=SimpleNamespace()),
            _create_new_database_fn=lambda _name: self.fail(
                "destroyed window must not create a database"
            ),
        )
        with (
            patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "NewDatabaseTypeDialog",
                _AccessTypeDialog,
            ),
            patch.object(QtWidgets, "QInputDialog", _DestroyingNameDialog),
        ):
            MenuController._new_database(controller)


class BidLockPermissionTests(unittest.TestCase):
    def test_shared_menu_callback_respects_enabled_state(self):
        controller = MenuController.__new__(MenuController)
        calls = []
        controller._get_menu_callbacks = lambda: {"blocked": lambda: calls.append(1)}
        controller.is_context_command_enabled = lambda _key: False
        MenuController.trigger_menu_callback(controller, "blocked")
        self.assertEqual(calls, [])
        controller.is_context_command_enabled = lambda key: key == "blocked"
        MenuController.trigger_menu_callback(controller, "blocked")
        self.assertEqual(calls, [1])
        MenuController.trigger_menu_callback(controller, "unknown")
        self.assertEqual(calls, [1])

    def test_new_folder_warns_when_create_succeeds_but_refresh_fails(self):
        warnings = []
        criticals = []
        renames = []
        controller = MenuController.__new__(MenuController)
        controller.window = SimpleNamespace(
            project_view=SimpleNamespace(
                schedule_rename=lambda uid, file_path: renames.append((uid, file_path))
            )
        )
        controller.ui_access_manager = SimpleNamespace(
            can_create_project_tree_items=lambda has_file: has_file,
            can_create_project=lambda file_path: file_path == "db.mdb",
        )
        controller.ui_state_manager = SimpleNamespace(
            selected_file_path="db.mdb",
            selected_project_uid=None,
        )
        controller.project_data = SimpleNamespace()
        controller._deferred_persistence = _permissions__FakeDeferredPersistence()
        controller._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _database_id: False,
            create_project_result=lambda _path, _name: WriteReloadResult(
                "project-new", write_success=True, reload_success=False
            ),
        )
        with (
            patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "show_warning",
                side_effect=lambda *args: warnings.append(args),
            ),
            patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "show_critical",
                side_effect=lambda *args: criticals.append(args),
            ),
        ):
            MenuController._new_folder(controller)
        self.assertEqual(
            warnings,
            [
                (
                    controller.window,
                    "Refresh Error",
                    "The project was created, but the project tree could not be "
                    "refreshed. Reopen the database to see the created project.",
                )
            ],
        )
        self.assertEqual(criticals, [])
        self.assertEqual(renames, [])

    def test_new_folder_schedules_rename_with_target_database(self):
        renames = []
        controller = MenuController.__new__(MenuController)
        controller.window = SimpleNamespace(
            project_view=SimpleNamespace(
                schedule_rename=lambda uid, file_path: renames.append((uid, file_path))
            )
        )
        controller.ui_access_manager = SimpleNamespace(
            can_create_project_tree_items=lambda has_file: has_file,
            can_create_project=lambda file_path: file_path == "db.mdb",
        )
        controller.ui_state_manager = SimpleNamespace(
            selected_file_path="db.mdb",
            selected_project_uid=None,
        )
        controller.project_data = SimpleNamespace()
        controller._deferred_persistence = _permissions__FakeDeferredPersistence()
        create_calls = []
        controller._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _database_id: False,
            create_project_result=lambda path, name: (
                create_calls.append((path, name))
                or WriteReloadResult(
                    "project-new", write_success=True, reload_success=True
                )
            ),
        )
        MenuController._new_folder(controller)
        self.assertEqual(create_calls, [("db.mdb", "New Project")])
        self.assertEqual(controller._deferred_persistence.flushes, ["db.mdb"])
        self.assertEqual(renames, [("project-new", "db.mdb")])

    def test_new_folder_reports_write_failure_without_scheduling_rename(self):
        renames = []
        controller = MenuController.__new__(MenuController)
        controller.window = SimpleNamespace(
            project_view=SimpleNamespace(
                schedule_rename=lambda uid, file_path: renames.append((uid, file_path))
            )
        )
        controller.ui_access_manager = SimpleNamespace(
            can_create_project_tree_items=lambda has_file: has_file,
            can_create_project=lambda file_path: file_path == "db.mdb",
        )
        controller.ui_state_manager = SimpleNamespace(
            selected_file_path="db.mdb",
            selected_project_uid=None,
        )
        controller.project_data = SimpleNamespace()
        controller._deferred_persistence = _permissions__FakeDeferredPersistence()
        controller._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _database_id: False,
            create_project_result=lambda _path, _name: WriteReloadResult(),
        )
        with (
            patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "show_warning"
            ) as warning,
            patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "show_critical"
            ) as critical,
        ):
            MenuController._new_folder(controller)
        warning.assert_not_called()
        critical.assert_called_once_with(
            controller.window,
            "New Project",
            f"Failed to create project. {DB_LOCKED_HINT}",
        )
        self.assertEqual(renames, [])

    def test_new_folder_blocked_without_permission_or_deferred_flush(self):
        for name, can_create, flush_ok in (
            ("permission_denied", False, True),
            ("deferred_flush_failed", True, False),
        ):
            with self.subTest(case=name):
                created = []
                controller = MenuController.__new__(MenuController)
                controller.window = SimpleNamespace(project_view=SimpleNamespace())
                controller.ui_access_manager = SimpleNamespace(
                    can_create_project=lambda _file_path, allowed=can_create: allowed
                )
                controller._deferred_persistence = SimpleNamespace(
                    flush_for_file=lambda _file_path, ok=flush_ok: ok
                )
                controller._project_write_service = SimpleNamespace(
                    uses_sql_collaboration_mutations=lambda _file_path: False,
                    create_project_result=lambda *_args: created.append(1),
                )
                controller.new_folder_in("db.mdb")
                self.assertEqual(created, [])

    def test_new_folder_on_sql_database_creates_through_delete_handler(self):
        renames = []
        sql_creates = []
        controller = MenuController.__new__(MenuController)
        controller.window = SimpleNamespace(
            project_view=SimpleNamespace(
                schedule_rename=lambda uid, file_path: renames.append((uid, file_path))
            )
        )
        controller.ui_access_manager = SimpleNamespace(
            can_create_project=lambda _file_path: True
        )
        controller._deferred_persistence = _permissions__FakeDeferredPersistence()
        controller.handlers = SimpleNamespace(
            delete=SimpleNamespace(
                create_project=lambda file_path, name, on_created: sql_creates.append(
                    (file_path, name, on_created)
                )
            )
        )
        controller._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _file_path: True,
            create_project_result=lambda *_args: self.fail("SQL uses the handler"),
        )
        controller.new_folder_in("sql-database")
        self.assertEqual(len(sql_creates), 1)
        file_path, name, on_created = sql_creates[0]
        self.assertEqual((file_path, name), ("sql-database", "New Project"))
        self.assertEqual(renames, [])
        on_created("project-sql")
        self.assertEqual(renames, [("project-sql", "sql-database")])


_REAL_MENU_FORMATS = ["html", "xlsx"]
_REAL_MENU_TOOL_KEYS = (
    "select_tool",
    "place_tool",
    "pan_tool",
    "zoom_tool",
    "dimension_tool",
    "text_annotation_tool",
    "highlight_annotation_tool",
    "arrow_annotation_tool",
    "line_annotation_tool",
    "rectangle_annotation_tool",
    "oval_annotation_tool",
    "polygon_annotation_tool",
    "cloud_annotation_tool",
    "ink_annotation_tool",
    "hotlink_tool",
    "named_view_tool",
)
_REAL_MENU_UI_EVENT_NAMES = (
    "toggle_page_invert",
    "toggle_page_bitonal",
    "rotate_selected_takeoffs_left",
    "rotate_selected_takeoffs_right",
    "flip_selected_takeoffs_horizontal",
    "flip_selected_takeoffs_vertical",
    "rotate_image_left",
    "rotate_image_right",
    "flip_image_horizontal",
    "flip_image_vertical",
    "select_overlay_image",
    "remove_overlay_image",
    "show_overlay_image",
    "show_original_image",
    "delete_current_page",
    "open_areas_dialog",
    "renumber_conditions",
    "open_employees_dialog",
    "open_job_statuses_dialog",
    "open_condition_types_dialog",
    "open_payroll_classes_dialog",
    "open_default_layers_dialog",
    "open_set_scale_dialog",
    "open_rename_page_dialog",
    "open_adjust_images_dialog",
    "can_renumber_conditions",
    "can_delete_current_page",
    "refresh_backout_action",
    "refresh_toolbar",
)
_REAL_MENU_HANDLER_NAMES = {
    "file_ops": (
        FileOperationHandler,
        ("open_files", "unload_file", "create_sql_database"),
    ),
    "import_": (ImportHandler, ("import_ost", "import_osp")),
    "export": (
        ExportHandler,
        (
            "export_as_pdf",
            "export_summary_csv",
            "export_as_ost",
            "export_as_osp",
            "export_format",
        ),
    ),
    "ui_event": (UIEventCoordinator, _REAL_MENU_UI_EVENT_NAMES),
    "cover_sheet": (CoverSheetHandler, ("open_cover_sheet",)),
    "delete": (ProjectWriteHandler, ("create_project",)),
}
_REAL_MENU_WINDOW_NAMES = (
    "is_takeoff_tab_active",
    "is_summary_tab_active",
    "get_takeoff_plan_view",
    "is_annotation_window_open",
    "can_open_annotation_window",
    "get_view_stack",
    "can_go_previous_takeoff_page",
    "can_go_next_takeoff_page",
    "get_selected_database_context_file_path",
    "resolve_current_area_selection_context",
    "is_takeoff_2d_tab_visible",
    "is_takeoff_3d_tab_visible",
    "set_takeoff_2d_tab_visible",
    "set_takeoff_3d_tab_visible",
    "get_workspace_toolbar_visibility_state",
    "set_workspace_toolbar_preference",
    "show_license_dialog",
    "reset_workspace_state_to_defaults",
)


class _RealMenuEnv:
    """Mutable inputs read by the fakes around the real MenuController."""

    def __init__(self):
        self.bid_ref = BidRef("db.mdb", "7")
        self.selected_bid_ref = self.bid_ref
        self.current_bid_ref = self.bid_ref
        self.selected_project_uid = "5"
        self.selected_file_path = "db.mdb"
        self.active_page_uid = "page-1"
        self.page = Page(uid="page-1", name="A1", width_pts=612.0, height_pts=792.0)
        self.page.image_path = "original.pdf"
        self.page.overlay_image_path = "overlay.pdf"
        self.selected_page_uids = ["page-1"]
        self.takeoffs = [object()]
        self.conditions = {"condition-1": object()}
        self.takeoff_active = True
        self.summary_active = False
        self.plan_view = SimpleNamespace(
            has_selected_takeoffs=True,
            has_takeoff_objects=True,
            current_page_uid="page-1",
        )
        self.annotation_window_open = False
        self.can_open_annotation_window = True
        self.viewer_renderable = True
        self.view_stack = None
        self.can_previous = True
        self.can_next = True
        self.master_file_path = "db.mdb"
        self.can_renumber = True
        self.can_delete_page = True
        self.tab_2d_visible = True
        self.tab_3d_visible = False
        self.toolbar_visibility = {"main_toolbar": True, "view_toolbar": False}
        self.loaded_files = []
        self.config = Config()
        self.state = SimpleNamespace(
            display_modes_synced=True,
            display_mode_3d=Config.DISPLAY_MODE_SOLID,
            display_mode_2d=Config.DISPLAY_MODE_ORIGINAL,
            grayscale_enabled=True,
        )


class _RealMenuCalls:
    def __init__(self):
        self.log = []

    def namespace(self, prefix, names):
        namespace = SimpleNamespace()
        for name in names:
            setattr(namespace, name, self._recorder(f"{prefix}.{name}"))
        return namespace

    def _recorder(self, label):
        def record(*args, **kwargs):
            self.log.append((label, args, kwargs))

        return record


class _RealMenuViewer:
    def __init__(self, env):
        self._env = env

    @property
    def has_renderable_content(self):
        return self._env.viewer_renderable


class _RealMenuWindow(QtWidgets.QMainWindow):
    MAIN_TOOLBAR_KEY = "main_toolbar"
    VIEW_TOOLBAR_KEY = "view_toolbar"
    PLAN_TOOLS_TOOLBAR_KEY = "plan_tools_toolbar"

    def __init__(self, env, calls):
        super().__init__()
        self._env = env
        self._calls = calls
        self.opengl_viewer = _RealMenuViewer(env)
        self.project_view = SimpleNamespace(
            schedule_rename=lambda uid, path: calls.log.append(
                ("window.project_view.schedule_rename", (uid, path), {})
            )
        )

    def is_takeoff_tab_active(self):
        return self._env.takeoff_active

    def is_summary_tab_active(self):
        return self._env.summary_active

    def get_takeoff_plan_view(self):
        return self._env.plan_view

    def is_annotation_window_open(self):
        return self._env.annotation_window_open

    def can_open_annotation_window(self):
        return self._env.can_open_annotation_window

    def get_view_stack(self):
        return self._env.view_stack

    def can_go_previous_takeoff_page(self):
        return self._env.can_previous

    def can_go_next_takeoff_page(self):
        return self._env.can_next

    def get_selected_database_context_file_path(self):
        return self._env.master_file_path

    def resolve_current_area_selection_context(self):
        return CurrentAreaSelectionContext(
            parent=self, plan_view=self._env.plan_view, area_uid="area-1"
        )

    def is_takeoff_2d_tab_visible(self):
        return self._env.tab_2d_visible

    def is_takeoff_3d_tab_visible(self):
        return self._env.tab_3d_visible

    def set_takeoff_2d_tab_visible(self, visible):
        self._calls.log.append(("window.set_takeoff_2d_tab_visible", (visible,), {}))
        self._env.tab_2d_visible = visible

    def set_takeoff_3d_tab_visible(self, visible):
        self._calls.log.append(("window.set_takeoff_3d_tab_visible", (visible,), {}))
        self._env.tab_3d_visible = visible

    def get_workspace_toolbar_visibility_state(self):
        return dict(self._env.toolbar_visibility)

    def set_workspace_toolbar_preference(self, key, visible):
        self._calls.log.append(
            ("window.set_workspace_toolbar_preference", (key, visible), {})
        )

    def show_license_dialog(self):
        self._calls.log.append(("window.show_license_dialog", (), {}))

    def reset_workspace_state_to_defaults(self):
        self._calls.log.append(("window.reset_workspace_state_to_defaults", (), {}))

    def close(self):
        self._calls.log.append(("window.close", (), {}))
        return True


class _RealMenuUiState:
    def __init__(self, env):
        self._env = env
        self.place_condition_uid = None
        self.highlighted_condition_uids = set()

    @property
    def state(self):
        return self._env.state

    @property
    def selected_project_uid(self):
        return self._env.selected_project_uid

    @property
    def selected_file_path(self):
        return self._env.selected_file_path

    @property
    def active_page_uid(self):
        return self._env.active_page_uid

    def get_selected_bid_ref(self):
        return self._env.selected_bid_ref

    def is_database_selected(self):
        return bool(self._env.selected_file_path)


class _RealMenuProjectData:
    def __init__(self, env):
        self._env = env
        self.locked = False
        self.annotation_layer_visible = True

    def is_current_bid_locked(self):
        return self.locked

    def is_annotation_layer_visible(self):
        return self.annotation_layer_visible

    def get_current_bid_ref(self):
        return self._env.current_bid_ref

    def get_selected_page_uids(self):
        return list(self._env.selected_page_uids)

    def has_takeoffs_for_pages(self, page_uids):
        return bool(page_uids and self._env.takeoffs)

    def get_page(self, page_uid):
        return self._env.page if page_uid == self._env.page.uid else None

    def get_bid_conditions(self):
        return self._env.conditions

    def get_all_takeoffs(self):
        return self._env.takeoffs

    def get_hierarchy(self):
        return SimpleNamespace(
            loaded_files=self._env.loaded_files,
            find_file_path_for_project=lambda uid: None,
        )

    def find_project_uid_for_bid(self, bid_ref):
        return "5" if bid_ref == self._env.bid_ref else None


class _RealMenuHarness:
    """A real MenuController (real __init__, MenuBuilder and UIAccessManager)."""

    def __init__(self, test_case, configure=None):
        self.env = _RealMenuEnv()
        if configure is not None:
            configure(self.env)
        self.calls = _RealMenuCalls()
        self.env.plan_view.select_takeoffs_in_area = self.calls._recorder(
            "plan_view.select_takeoffs_in_area"
        )
        self.window = _RealMenuWindow(self.env, self.calls)
        test_case.addCleanup(
            lambda: delete(self.window) if isValid(self.window) else None
        )
        self.project_data = _RealMenuProjectData(self.env)
        self.ui_state = _RealMenuUiState(self.env)
        self.license = _surface_access_support__License()
        self.monitor = _surface_access_support__TransactionMonitor()
        self.capabilities = _surface_access_support__Capabilities()
        self.access = UIAccessManager(
            _surface_access_support__EventBus(),
            self.license,
            self.monitor,
            self.project_data,
            self.ui_state,
            self.capabilities,
        )
        test_case.addCleanup(self.access.cleanup)
        self.handlers = SimpleNamespace(
            **{
                attribute: self.calls.namespace(attribute, names)
                for attribute, (_cls, names) in _REAL_MENU_HANDLER_NAMES.items()
            }
        )
        self.backout_refreshes = []
        self.handlers.ui_event.refresh_backout_action = (
            lambda: self.backout_refreshes.append(1)
        )
        self.handlers.ui_event.can_renumber_conditions = lambda: self.env.can_renumber
        self.handlers.ui_event.can_delete_current_page = (
            lambda: self.env.can_delete_page
        )
        self.config_updates = []
        self.config_service = SimpleNamespace(
            get_config_snapshot=lambda: self.env.config,
            update_app_options=self._update_app_options,
        )
        self.shared_actions = {
            key: QtGui.QAction(key, self.window) for key in self._shared_keys()
        }
        self.icon_provider = SimpleNamespace(name="icons")
        self.read_service = SimpleNamespace(name="read")
        self.write_service = SimpleNamespace(name="write")
        self.infrastructure = SimpleNamespace(name="infrastructure")
        self.event_bus = SimpleNamespace(name="events")
        self.file_loading = SimpleNamespace(name="loading")
        self.created_databases = []
        self.deferred = SimpleNamespace(name="deferred")
        self.workspace_model = SimpleNamespace(name="workspace")
        self.export_service = SimpleNamespace(
            get_available_formats=lambda: list(_REAL_MENU_FORMATS)
        )
        self.controller = MenuController(
            self.window,
            self.icon_provider,
            self.config_service,
            self.ui_state,
            self.handlers,
            self.access,
            project_data_service=self.project_data,
            export_service=self.export_service,
            project_read_service=self.read_service,
            project_write_service=self.write_service,
            infrastructure_provider=self.infrastructure,
            event_bus=self.event_bus,
            file_loading_service=self.file_loading,
            create_new_database_fn=self.created_databases.append,
            deferred_persistence_manager=self.deferred,
            workspace_state_model=self.workspace_model,
            shared_actions=self.shared_actions,
        )
        self.menu_bar = self.controller.create_menu()
        self.window.setMenuBar(self.menu_bar)

    def _update_app_options(self, update):
        self.config_updates.append(update)
        if isinstance(update, Config):
            self.env.config = update
        else:
            for key, value in update.items():
                setattr(self.env.config, key, value)

    @staticmethod
    def _shared_keys():
        keys = []

        def walk(items):
            for item in items:
                if item[0] == "shared":
                    keys.append(item[1])
                elif item[0] == "cascade":
                    walk(item[2])

        for items in MenuBuilder(None, {})._get_menu_definition().values():
            walk(items)
        return keys

    def enabled(self, keys=None):
        actions = self.controller._actions
        return {key: actions[key].isEnabled() for key in (keys or sorted(actions))}


_REAL_MENU_TAKEOFF_KEYS = frozenset(
    {
        "toggle_view_toolbar",
        "toggle_plan_tools_toolbar",
        "toggle_2d_tab",
        "toggle_3d_tab",
        "zoom_in",
        "zoom_out",
        "reset_view",
        "layers_sidebar",
        "conditions_sidebar",
        "annotation_window",
        "previous_page",
        "next_page",
        "toggle_takeoff_display_modes_sync",
        "toggle_takeoff_grayscale",
        "set_takeoff_display_mode_3d",
        "set_takeoff_display_mode_2d",
        "var:display_mode_3d:1",
        "var:display_mode_3d:2",
        "var:display_mode_2d:1",
        "var:display_mode_2d:2",
        *_REAL_MENU_TOOL_KEYS,
    }
)
_REAL_MENU_PAGE_IMAGE_KEYS = frozenset(
    {
        "adjust_images",
        "toggle_page_invert",
        "toggle_page_bitonal",
        "rotate_image_left",
        "rotate_image_right",
        "flip_image_horizontal",
        "flip_image_vertical",
        "select_overlay_image",
        "set_scale",
        "rename_page",
        "show_original_image",
        "remove_overlay_image",
        "show_overlay_image",
    }
)
_REAL_MENU_TRANSFORM_KEYS = frozenset(
    {
        "rotate_takeoff_left",
        "rotate_takeoff_right",
        "flip_takeoff_horizontal",
        "flip_takeoff_vertical",
    }
)
_REAL_MENU_MASTER_KEYS = frozenset(
    {
        "employees",
        "job_statuses",
        "payroll_classes",
        "condition_types",
        "default_layers",
    }
)
_REAL_MENU_EXPORT_KEYS = frozenset(
    {
        "export_as_html",
        "export_as_xlsx",
        "export_as_pdf",
        "export_summary_csv",
        "export_as_ost",
        "export_as_osp",
        "menu:export",
    }
)
_REAL_MENU_TREE_KEYS = frozenset({"new_project", "new_folder"})
_REAL_MENU_ROTATE_FLIP_MENU = frozenset({"menu:rotate/flip"})
_REAL_MENU_TAKEOFF_ONLY_GATED = (
    _REAL_MENU_TAKEOFF_KEYS
    | _REAL_MENU_PAGE_IMAGE_KEYS
    | _REAL_MENU_TRANSFORM_KEYS
    | _REAL_MENU_ROTATE_FLIP_MENU
)
_REAL_MENU_EDIT_BLOCKED_BY_PLACEMENT = (
    _REAL_MENU_TREE_KEYS
    | _REAL_MENU_EXPORT_KEYS
    | _REAL_MENU_PAGE_IMAGE_KEYS
    | _REAL_MENU_TRANSFORM_KEYS
    | _REAL_MENU_MASTER_KEYS
    | _REAL_MENU_ROTATE_FLIP_MENU
    | {
        "unload_file",
        "new_database",
        "menu:import",
        "show_cover_sheet",
        "show_areas",
        "select_objects_in_current_area",
    }
)


def _real_menu_snapshot(harness):
    controller = harness.controller
    controller.update_menu_states()
    snapshot = {key: action.isEnabled() for key, action in controller._actions.items()}
    registered = {id(action) for action in controller._actions.values()}
    for variable, actions in controller._variable_actions.items():
        for index, action in enumerate(actions):
            if id(action) not in registered:
                snapshot[f"var:{variable}:{index}"] = action.isEnabled()
    for name, menu in controller._menus.items():
        snapshot[f"menu:{name}"] = menu.isEnabled()
    return snapshot


def _real_menu_stack(index):
    stack = QtWidgets.QStackedWidget()
    stack.addWidget(QtWidgets.QWidget())
    stack.addWidget(QtWidgets.QWidget())
    stack.setCurrentIndex(index)
    return stack


class MenuControllerRealMenuProjectionTests(unittest.TestCase):
    """The real MenuController (real __init__, MenuBuilder menus and
    UIAccessManager with its Feature matrix) over fakes of the window, the handlers
    and project data.  The fakes only offer the methods the production code calls
    (a renamed production call raises AttributeError) and the handler and window
    names are checked against the real classes below."""

    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()

    def tearDown(self):
        self.app.processEvents()

    def _scenarios(self):
        def ost_active(h):
            h.monitor.active = True
            h.access.refresh()

        def locked(h):
            h.project_data.locked = True

        def read_only(h):
            h.capabilities.database_editable = False

        def page_locked(h):
            h.capabilities.locked_pages = {"page-1"}

        def no_license(h):
            h.license.valid = False

        def area_placement(h):
            h.access.set_area_placement_active(True, surface_id="main-plan")

        def inline_text(h):
            h.access.set_text_annotation_edit_active(True, surface_id="main-plan")

        def hidden_annotation_layer(h):
            h.project_data.annotation_layer_visible = False

        def no_selected_bid(h):
            h.env.selected_bid_ref = None

        def bid_not_loaded(h):
            h.env.current_bid_ref = BidRef("db.mdb", "99")

        def summary(h):
            h.env.takeoff_active = False
            h.env.summary_active = True

        def not_takeoff(h):
            h.env.takeoff_active = False

        def root_project(h):
            h.env.selected_project_uid = "1"

        def no_page(h):
            h.env.active_page_uid = None

        def no_images(h):
            h.env.page.image_path = ""
            h.env.page.overlay_image_path = ""

        def no_overlay(h):
            h.env.page.overlay_image_path = ""

        def no_original(h):
            h.env.page.image_path = ""

        def no_plan_view(h):
            h.env.plan_view = None

        def no_selected_takeoffs(h):
            h.env.plan_view.has_selected_takeoffs = False

        def no_objects(h):
            h.env.plan_view.has_takeoff_objects = False

        def plan_without_page(h):
            h.env.plan_view.current_page_uid = ""

        def nothing_to_navigate(h):
            h.env.viewer_renderable = False

        def stack_on_plan(h):
            h.env.viewer_renderable = False
            h.env.view_stack = _real_menu_stack(1)

        def stack_on_plan_without_page(h):
            h.env.view_stack = _real_menu_stack(1)
            h.env.plan_view.current_page_uid = ""

        def stack_on_3d(h):
            h.env.view_stack = _real_menu_stack(0)
            h.env.viewer_renderable = False

        def annotation_window_unavailable(h):
            h.env.can_open_annotation_window = False

        def annotation_window_open(h):
            h.env.can_open_annotation_window = False
            h.env.annotation_window_open = True

        def first_page(h):
            h.env.can_previous = False

        def last_page(h):
            h.env.can_next = False

        def no_master_database(h):
            h.env.master_file_path = None

        def nothing_to_renumber(h):
            h.env.can_renumber = False

        def no_selected_pages(h):
            h.env.selected_page_uids = []

        def no_takeoffs(h):
            h.env.takeoffs = []

        def no_conditions(h):
            h.env.conditions = {}

        def zero_size_page(h):
            h.env.page.width_pts = 0

        no_export_content = {"export_as_html", "export_as_xlsx"}
        all_exports = set(_REAL_MENU_EXPORT_KEYS)
        # (label, setup, disabled keys, annotation tools placeable)
        return [
            ("baseline", lambda h: None, set(), True),
            (
                "summary tab",
                summary,
                _REAL_MENU_TAKEOFF_ONLY_GATED | _REAL_MENU_TREE_KEYS,
                False,
            ),
            ("other takeoff tab", not_takeoff, _REAL_MENU_TAKEOFF_ONLY_GATED, False),
            (
                "no license",
                no_license,
                {
                    "new_database",
                    "menu:import",
                    "show_cover_sheet",
                    "show_areas",
                    "select_objects_in_current_area",
                }
                | _REAL_MENU_TREE_KEYS
                | _REAL_MENU_EXPORT_KEYS
                | _REAL_MENU_PAGE_IMAGE_KEYS
                | _REAL_MENU_TRANSFORM_KEYS
                | _REAL_MENU_MASTER_KEYS
                | _REAL_MENU_ROTATE_FLIP_MENU,
                False,
            ),
            (
                "OST active",
                ost_active,
                {
                    "menu:import",
                    "show_cover_sheet",
                    "show_areas",
                    "select_objects_in_current_area",
                }
                | _REAL_MENU_TREE_KEYS
                | _REAL_MENU_PAGE_IMAGE_KEYS
                | _REAL_MENU_TRANSFORM_KEYS
                | _REAL_MENU_MASTER_KEYS
                | _REAL_MENU_ROTATE_FLIP_MENU,
                False,
            ),
            (
                "locked active Bid",
                locked,
                {"show_areas", "select_objects_in_current_area"}
                | _REAL_MENU_PAGE_IMAGE_KEYS
                | _REAL_MENU_TRANSFORM_KEYS
                | _REAL_MENU_ROTATE_FLIP_MENU,
                False,
            ),
            (
                "read-only SQL database",
                read_only,
                {"menu:import", "show_cover_sheet", "show_areas"}
                | _REAL_MENU_TREE_KEYS
                | _REAL_MENU_PAGE_IMAGE_KEYS
                | _REAL_MENU_TRANSFORM_KEYS
                | _REAL_MENU_MASTER_KEYS
                | _REAL_MENU_ROTATE_FLIP_MENU,
                False,
            ),
            (
                "Page locked by another client",
                page_locked,
                {"show_areas"} | _REAL_MENU_PAGE_IMAGE_KEYS,
                True,
            ),
            (
                "area placement in progress",
                area_placement,
                _REAL_MENU_EDIT_BLOCKED_BY_PLACEMENT,
                False,
            ),
            (
                "inline text edit in progress",
                inline_text,
                _REAL_MENU_EDIT_BLOCKED_BY_PLACEMENT,
                False,
            ),
            ("annotation layer hidden", hidden_annotation_layer, set(), False),
            (
                "no selected Bid",
                no_selected_bid,
                {
                    "show_cover_sheet",
                    "show_areas",
                    "select_objects_in_current_area",
                }
                | _REAL_MENU_EXPORT_KEYS
                | _REAL_MENU_PAGE_IMAGE_KEYS
                | _REAL_MENU_TRANSFORM_KEYS
                | _REAL_MENU_ROTATE_FLIP_MENU,
                False,
            ),
            (
                "selected Bid is not the loaded Bid",
                bid_not_loaded,
                _REAL_MENU_EXPORT_KEYS,
                True,
            ),
            ("database root selected", root_project, {"menu:import"}, True),
            (
                "no active Page",
                no_page,
                _REAL_MENU_PAGE_IMAGE_KEYS,
                True,
            ),
            (
                "Page without sources",
                no_images,
                {"show_original_image", "remove_overlay_image", "show_overlay_image"},
                True,
            ),
            (
                "Page without overlay",
                no_overlay,
                {"remove_overlay_image", "show_overlay_image"},
                True,
            ),
            ("Page without original", no_original, {"show_original_image"}, True),
            (
                "no plan view",
                no_plan_view,
                _REAL_MENU_TRANSFORM_KEYS | {"select_objects_in_current_area"},
                True,
            ),
            (
                "no selected takeoffs",
                no_selected_takeoffs,
                _REAL_MENU_TRANSFORM_KEYS,
                True,
            ),
            (
                "no takeoff objects",
                no_objects,
                {"select_objects_in_current_area"},
                True,
            ),
            (
                "plan view without Page",
                plan_without_page,
                {"select_objects_in_current_area"},
                True,
            ),
            (
                "nothing renderable",
                nothing_to_navigate,
                {"zoom_in", "zoom_out", "reset_view", "pan_tool", "zoom_tool"},
                True,
            ),
            ("plan stack with Page", stack_on_plan, set(), True),
            (
                "plan stack without Page",
                stack_on_plan_without_page,
                {
                    "zoom_in",
                    "zoom_out",
                    "reset_view",
                    "pan_tool",
                    "zoom_tool",
                    "select_objects_in_current_area",
                },
                True,
            ),
            (
                "3D stack without content",
                stack_on_3d,
                {"zoom_in", "zoom_out", "reset_view", "pan_tool", "zoom_tool"},
                True,
            ),
            (
                "annotation window unavailable",
                annotation_window_unavailable,
                {"annotation_window"},
                True,
            ),
            ("annotation window open", annotation_window_open, set(), True),
            ("first Page", first_page, {"previous_page"}, True),
            ("last Page", last_page, {"next_page"}, True),
            (
                "no database context for master data",
                no_master_database,
                set(_REAL_MENU_MASTER_KEYS),
                True,
            ),
            ("nothing to renumber", nothing_to_renumber, {"renumber_conditions"}, True),
            (
                "no selected Pages",
                no_selected_pages,
                no_export_content | {"export_as_pdf"},
                True,
            ),
            (
                "no takeoffs",
                no_takeoffs,
                no_export_content | {"export_summary_csv"},
                True,
            ),
            ("no conditions", no_conditions, {"export_summary_csv"}, True),
            ("Page without size", zero_size_page, {"export_as_pdf"}, True),
        ]

    def test_menu_projection_follows_access_matrix_and_context(self):
        for label, setup, disabled, annotation_tools in self._scenarios():
            with self.subTest(scenario=label):
                harness = _RealMenuHarness(self)
                setup(harness)
                snapshot = _real_menu_snapshot(harness)
                self.assertLessEqual(disabled, set(snapshot), "unknown key")
                expected = {key: key not in disabled for key in snapshot}
                disabled_actual = sorted(k for k, v in snapshot.items() if not v)
                self.assertEqual(
                    disabled_actual,
                    sorted(k for k, v in expected.items() if not v),
                )
                self.assertEqual(
                    harness.controller.is_context_command_enabled("dimension_tool"),
                    annotation_tools,
                )

    def test_menu_projection_has_no_stale_enabled_state_across_context_changes(self):
        harness = _RealMenuHarness(self)
        baseline = _real_menu_snapshot(harness)
        self.assertTrue(all(baseline.values()))
        for setup in (
            lambda: setattr(harness.env, "takeoff_active", False),
            lambda: setattr(harness.project_data, "locked", True),
        ):
            setup()
            changed = _real_menu_snapshot(harness)
            self.assertFalse(all(changed.values()))
            self.assertFalse(changed["adjust_images"])
            harness.env.takeoff_active = True
            harness.project_data.locked = False
            self.assertEqual(_real_menu_snapshot(harness), baseline)
        harness.monitor.active = True
        harness.access.refresh()
        blocked = _real_menu_snapshot(harness)
        self.assertFalse(blocked["menu:import"])
        harness.monitor.active = False
        harness.access.refresh()
        self.assertEqual(_real_menu_snapshot(harness), baseline)
        harness.env.takeoff_active = False
        away = _real_menu_snapshot(harness)
        self.assertFalse(away["select_tool"])
        harness.env.takeoff_active = True
        returned = _real_menu_snapshot(harness)
        self.assertTrue(returned["select_tool"])
        self.assertEqual(harness.controller._tool_action_enabled_state, {})


class MenuControllerRealMenuWiringTests(unittest.TestCase):
    """Construction, menu publication, callback routing and the trigger API of the
    real MenuController (see MenuControllerRealMenuProjectionTests)."""

    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()

    def tearDown(self):
        self.app.processEvents()

    def test_recording_fakes_only_offer_names_of_the_real_collaborators(self):
        for attribute, (real_class, names) in _REAL_MENU_HANDLER_NAMES.items():
            for name in names:
                with self.subTest(handler=attribute, name=name):
                    self.assertTrue(
                        callable(getattr(real_class, name, None)),
                        f"{real_class.__name__} has no {name}",
                    )
        for name in _REAL_MENU_WINDOW_NAMES:
            with self.subTest(window=name):
                self.assertTrue(callable(getattr(MainWindow, name, None)), name)

    def test_constructor_keeps_every_collaborator_and_starts_empty(self):
        harness = _RealMenuHarness(self)
        controller = harness.controller
        self.assertIs(controller.window, harness.window)
        self.assertIs(controller.icon_provider, harness.icon_provider)
        self.assertIs(controller.config_service, harness.config_service)
        self.assertIs(controller.ui_state_manager, harness.ui_state)
        self.assertIs(controller.handlers, harness.handlers)
        self.assertIs(controller.ui_access_manager, harness.access)
        self.assertIs(controller.project_data, harness.project_data)
        self.assertIs(controller._project_read_service, harness.read_service)
        self.assertIs(controller._project_write_service, harness.write_service)
        self.assertIs(controller._infrastructure_provider, harness.infrastructure)
        self.assertIs(controller._event_bus, harness.event_bus)
        self.assertIs(controller._file_loading_service, harness.file_loading)
        controller._create_new_database_fn("name")
        self.assertEqual(harness.created_databases, ["name"])
        self.assertIs(controller._deferred_persistence, harness.deferred)
        self.assertIs(controller._workspace_state_model, harness.workspace_model)
        self.assertEqual(controller._shared_actions, harness.shared_actions)
        self.assertIsNot(controller._shared_actions, harness.shared_actions)
        self.assertEqual(controller.get_export_formats(), ["html", "xlsx"])
        controller.get_export_formats().append("extra")
        self.assertEqual(controller.get_export_formats(), ["html", "xlsx"])
        bare = MenuController(
            SimpleNamespace(),
            None,
            harness.config_service,
            harness.ui_state,
            harness.handlers,
            harness.access,
            project_data_service=harness.project_data,
            export_service=harness.export_service,
            project_read_service=None,
            project_write_service=None,
            infrastructure_provider=None,
            event_bus=None,
            file_loading_service=None,
            create_new_database_fn=None,
            deferred_persistence_manager=None,
            workspace_state_model=None,
        )
        self.assertEqual(bare._shared_actions, {})
        self.assertIsNone(bare.menu_bar)
        for collection in (
            bare._actions,
            bare._menus,
            bare._variable_actions,
            bare._state_getters,
            bare._tool_action_enabled_state,
        ):
            self.assertEqual(collection, {})
        bare.update_menu_states()
        controller.cleanup()
        self.assertIsNone(controller.icon_provider)

    def test_create_menu_publishes_the_built_menus_and_initial_check_state(self):
        harness = _RealMenuHarness(self)
        controller = harness.controller
        self.assertIs(controller.menu_bar, harness.menu_bar)
        self.assertIsInstance(harness.menu_bar, QtWidgets.QMenuBar)
        self.assertEqual(
            [action.text() for action in harness.menu_bar.actions()],
            ["File", "Edit", "View", "Tools", "Image", "Project", "Master", "Help"],
        )
        self.assertEqual(
            set(controller._menus),
            {
                "file",
                "new",
                "import",
                "export",
                "edit",
                "view",
                "toolbars",
                "takeoff",
                "3d display mode",
                "2d display mode",
                "tabs",
                "tools",
                "image",
                "rotate/flip",
                "project",
                "master",
                "help",
            },
        )
        self.assertEqual(
            set(controller._state_getters),
            {
                "display_modes_synced",
                "display_mode_3d",
                "display_mode_2d",
                "grayscale",
                "main_toolbar_visible",
                "view_toolbar_visible",
                "plan_tools_toolbar_visible",
                "page_invert",
                "page_bitonal",
                "show_overlay_image",
                "show_original_image",
                "takeoff_2d_tab_visible",
                "takeoff_3d_tab_visible",
            },
        )
        self.assertEqual(
            set(controller._variable_actions), set(controller._state_getters)
        )
        actions = controller._actions
        self.assertEqual(
            {
                key: actions[key].isChecked()
                for key in (
                    "toggle_main_toolbar",
                    "toggle_view_toolbar",
                    "toggle_plan_tools_toolbar",
                    "toggle_2d_tab",
                    "toggle_3d_tab",
                    "toggle_takeoff_display_modes_sync",
                    "toggle_takeoff_grayscale",
                    "toggle_page_invert",
                    "toggle_page_bitonal",
                    "show_original_image",
                    "show_overlay_image",
                )
            },
            {
                "toggle_main_toolbar": True,
                "toggle_view_toolbar": False,
                "toggle_plan_tools_toolbar": True,
                "toggle_2d_tab": True,
                "toggle_3d_tab": False,
                "toggle_takeoff_display_modes_sync": True,
                "toggle_takeoff_grayscale": True,
                "toggle_page_invert": False,
                "toggle_page_bitonal": False,
                "show_original_image": True,
                "show_overlay_image": False,
            },
        )
        for variable, expected in (
            ("display_mode_3d", Config.DISPLAY_MODE_SOLID),
            ("display_mode_2d", Config.DISPLAY_MODE_ORIGINAL),
        ):
            checked = [
                action.data()
                for action in controller._variable_actions[variable]
                if action.isChecked()
            ]
            self.assertEqual(checked, [expected], variable)

    def test_every_menu_refreshes_the_enabled_state_when_it_is_about_to_show(self):
        harness = _RealMenuHarness(self)
        controller = harness.controller
        for name, menu in controller._menus.items():
            with self.subTest(menu=name):
                harness.env.takeoff_active = False
                menu.aboutToShow.emit()
                self.assertFalse(controller._actions["zoom_in"].isEnabled())
                harness.env.takeoff_active = True
                menu.aboutToShow.emit()
                self.assertTrue(controller._actions["zoom_in"].isEnabled())

    def _callback_table(self):
        pages = ["page-1", "page-2"]
        return {
            "open_files": [("file_ops.open_files", (), {})],
            "unload_file": [("file_ops.unload_file", (), {})],
            "check_license": [("window.show_license_dialog", (), {})],
            "quit": [("window.close", (), {})],
            "import_ost": [("import_.import_ost", (), {})],
            "import_osp": [("import_.import_osp", (), {})],
            "export_as_pdf": [("export.export_as_pdf", (pages,), {})],
            "export_summary_csv": [("export.export_summary_csv", (), {})],
            "export_as_ost": [("export.export_as_ost", (), {})],
            "export_as_osp": [("export.export_as_osp", (), {})],
            "export_as_html": [("export.export_format", ("html", pages, "page-1"), {})],
            "export_as_xlsx": [("export.export_format", ("xlsx", pages, "page-1"), {})],
            "toggle_page_invert": [("ui_event.toggle_page_invert", (), {})],
            "toggle_page_bitonal": [("ui_event.toggle_page_bitonal", (), {})],
            "rotate_takeoff_left": [("ui_event.rotate_selected_takeoffs_left", (), {})],
            "rotate_takeoff_right": [
                ("ui_event.rotate_selected_takeoffs_right", (), {})
            ],
            "flip_takeoff_horizontal": [
                ("ui_event.flip_selected_takeoffs_horizontal", (), {})
            ],
            "flip_takeoff_vertical": [
                ("ui_event.flip_selected_takeoffs_vertical", (), {})
            ],
            "rotate_image_left": [("ui_event.rotate_image_left", (), {})],
            "rotate_image_right": [("ui_event.rotate_image_right", (), {})],
            "flip_image_horizontal": [("ui_event.flip_image_horizontal", (), {})],
            "flip_image_vertical": [("ui_event.flip_image_vertical", (), {})],
            "select_overlay_image": [("ui_event.select_overlay_image", (), {})],
            "remove_overlay_image": [("ui_event.remove_overlay_image", (), {})],
            "show_overlay_image": [("ui_event.show_overlay_image", (), {})],
            "show_original_image": [("ui_event.show_original_image", (), {})],
            "delete_page": [("ui_event.delete_current_page", (), {})],
            "show_areas": [("ui_event.open_areas_dialog", (), {})],
            "renumber_conditions": [("ui_event.renumber_conditions", (), {})],
            "employees": [("ui_event.open_employees_dialog", (), {})],
            "job_statuses": [("ui_event.open_job_statuses_dialog", (), {})],
            "condition_types": [("ui_event.open_condition_types_dialog", (), {})],
            "payroll_classes": [("ui_event.open_payroll_classes_dialog", (), {})],
            "default_layers": [("ui_event.open_default_layers_dialog", (), {})],
            "set_scale": [("ui_event.open_set_scale_dialog", (), {})],
            "rename_page": [("ui_event.open_rename_page_dialog", (), {})],
            "adjust_images": [("ui_event.open_adjust_images_dialog", (), {})],
            "select_objects_in_current_area": [
                ("plan_view.select_takeoffs_in_area", ("area-1",), {}),
                ("ui_event.refresh_toolbar", (), {}),
            ],
            "show_cover_sheet": [("cover_sheet.open_cover_sheet", (), {})],
        }

    def test_menu_callbacks_route_every_command_to_its_collaborator(self):
        harness = _RealMenuHarness(self)
        harness.env.selected_page_uids = ["page-1", "page-2"]
        controller = harness.controller
        callbacks = controller._get_menu_callbacks()
        table = self._callback_table()
        bound = {
            "new_project": controller._new_project,
            "new_folder": controller._new_folder,
            "new_database": controller._new_database,
            "set_takeoff_display_mode_3d": controller._set_takeoff_display_mode_3d,
            "set_takeoff_display_mode_2d": controller._set_takeoff_display_mode_2d,
            "toggle_takeoff_display_modes_sync": (
                controller._toggle_takeoff_display_modes_sync
            ),
            "toggle_takeoff_grayscale": controller._toggle_takeoff_grayscale,
            "toggle_main_toolbar": controller._set_main_toolbar_visible,
            "toggle_view_toolbar": controller._set_view_toolbar_visible,
            "toggle_plan_tools_toolbar": controller._set_plan_tools_toolbar_visible,
            "toggle_2d_tab": controller._set_2d_tab_visible,
            "toggle_3d_tab": controller._set_3d_tab_visible,
            "options": controller._show_options_dialog,
            "show_about": controller._show_about_dialog,
        }
        self.assertEqual(set(callbacks), set(table) | set(bound))
        for key, method in bound.items():
            with self.subTest(command=key):
                self.assertEqual(callbacks[key], method)
        for key, expected in table.items():
            with self.subTest(command=key):
                harness.calls.log.clear()
                callbacks[key]()
                self.assertEqual(harness.calls.log, expected)

    def test_export_format_command_accepts_the_triggered_checked_flag(self):
        harness = _RealMenuHarness(self)
        harness.env.selected_page_uids = ["page-1"]
        harness.controller._get_menu_callbacks()["export_as_xlsx"](True)
        self.assertEqual(
            harness.calls.log,
            [("export.export_format", ("xlsx", ["page-1"], "page-1"), {})],
        )

    def test_real_menu_actions_trigger_their_handlers(self):
        harness = _RealMenuHarness(self)
        controller = harness.controller
        harness.env.selected_page_uids = ["page-1", "page-2"]
        expected = {
            "unload_file": [("file_ops.unload_file", (), {})],
            "import_ost": [("import_.import_ost", (), {})],
            "export_as_pdf": [("export.export_as_pdf", (["page-1", "page-2"],), {})],
            "export_as_xlsx": [
                ("export.export_format", ("xlsx", ["page-1", "page-2"], "page-1"), {})
            ],
            "rotate_takeoff_left": [("ui_event.rotate_selected_takeoffs_left", (), {})],
            "show_areas": [("ui_event.open_areas_dialog", (), {})],
            "employees": [("ui_event.open_employees_dialog", (), {})],
            "set_scale": [("ui_event.open_set_scale_dialog", (), {})],
            "quit": [("window.close", (), {})],
        }
        for key, calls in expected.items():
            with self.subTest(action=key):
                harness.calls.log.clear()
                controller._actions[key].trigger()
                self.assertEqual(harness.calls.log, calls)
        harness.calls.log.clear()
        controller._actions["toggle_page_invert"].trigger()
        self.assertEqual(
            harness.calls.log, [("ui_event.toggle_page_invert", (True,), {})]
        )
        harness.calls.log.clear()
        controller._actions["toggle_view_toolbar"].trigger()
        self.assertEqual(
            harness.calls.log,
            [("window.set_workspace_toolbar_preference", ("view_toolbar", True), {})],
        )

    def test_state_getters_read_the_ui_state_page_and_window(self):
        harness = _RealMenuHarness(self)
        getters = harness.controller._state_getters
        env = harness.env
        env.page.invert = True
        env.page.bitonal = False
        env.page.image_show_mode = 2
        values = {name: getter() for name, getter in getters.items()}
        self.assertEqual(
            values,
            {
                "display_modes_synced": True,
                "display_mode_3d": Config.DISPLAY_MODE_SOLID,
                "display_mode_2d": Config.DISPLAY_MODE_ORIGINAL,
                "grayscale": True,
                "main_toolbar_visible": True,
                "view_toolbar_visible": False,
                "plan_tools_toolbar_visible": True,
                "page_invert": True,
                "page_bitonal": False,
                "show_overlay_image": True,
                "show_original_image": True,
                "takeoff_2d_tab_visible": True,
                "takeoff_3d_tab_visible": False,
            },
        )
        env.page.invert = False
        env.page.bitonal = True
        env.page.image_show_mode = 1
        env.state.display_modes_synced = False
        env.state.grayscale_enabled = False
        env.tab_2d_visible = False
        env.tab_3d_visible = True
        env.toolbar_visibility = {
            "main_toolbar": False,
            "view_toolbar": True,
            "plan_tools_toolbar": False,
        }
        values = {name: getter() for name, getter in getters.items()}
        self.assertEqual(
            values,
            {
                "display_modes_synced": False,
                "display_mode_3d": Config.DISPLAY_MODE_SOLID,
                "display_mode_2d": Config.DISPLAY_MODE_ORIGINAL,
                "grayscale": False,
                "main_toolbar_visible": False,
                "view_toolbar_visible": True,
                "plan_tools_toolbar_visible": False,
                "page_invert": False,
                "page_bitonal": True,
                "show_overlay_image": True,
                "show_original_image": False,
                "takeoff_2d_tab_visible": False,
                "takeoff_3d_tab_visible": True,
            },
        )
        env.page.image_show_mode = 0
        self.assertEqual(
            (getters["show_overlay_image"](), getters["show_original_image"]()),
            (False, True),
        )
        env.active_page_uid = None
        self.assertEqual(
            [
                getters[name]()
                for name in (
                    "page_invert",
                    "page_bitonal",
                    "show_overlay_image",
                    "show_original_image",
                )
            ],
            [False, False, False, False],
        )

    def test_display_mode_commands_follow_the_other_mode_only_when_synced(self):
        harness = _RealMenuHarness(self)
        controller = harness.controller
        harness.env.config.display_modes_synced = False
        controller._set_takeoff_display_mode_3d(Config.DISPLAY_MODE_SOLID)
        controller._set_takeoff_display_mode_2d(Config.DISPLAY_MODE_TRANSPARENT)
        self.assertEqual(
            harness.config_updates,
            [
                {"display_mode_3d": Config.DISPLAY_MODE_SOLID},
                {"display_mode_2d": Config.DISPLAY_MODE_TRANSPARENT},
            ],
        )
        harness.config_updates.clear()
        harness.env.config.display_modes_synced = True
        controller._set_takeoff_display_mode_3d(Config.DISPLAY_MODE_ORIGINAL)
        controller._set_takeoff_display_mode_2d(Config.DISPLAY_MODE_SOLID)
        self.assertEqual(
            harness.config_updates,
            [
                {
                    "display_mode_3d": Config.DISPLAY_MODE_ORIGINAL,
                    "display_mode_2d": Config.DISPLAY_MODE_ORIGINAL,
                },
                {
                    "display_mode_2d": Config.DISPLAY_MODE_SOLID,
                    "display_mode_3d": Config.DISPLAY_MODE_SOLID,
                },
            ],
        )

    def test_sync_and_grayscale_toggles_report_the_stored_value(self):
        harness = _RealMenuHarness(self)
        controller = harness.controller
        config = harness.env.config
        config.display_modes_synced = False
        config.display_mode_3d = Config.DISPLAY_MODE_SOLID
        config.display_mode_2d = Config.DISPLAY_MODE_TRANSPARENT
        self.assertIs(controller._toggle_takeoff_display_modes_sync(), True)
        self.assertEqual(
            harness.config_updates,
            [
                {
                    "display_modes_synced": True,
                    "display_mode_2d": Config.DISPLAY_MODE_SOLID,
                }
            ],
        )
        self.assertIs(controller._toggle_takeoff_display_modes_sync(True), False)
        self.assertEqual(harness.config_updates[-1], {"display_modes_synced": False})
        self.assertEqual(len(harness.config_updates), 2)
        config.grayscale_enabled = False
        self.assertIs(controller._toggle_takeoff_grayscale(), True)
        self.assertEqual(harness.config_updates[-1], {"grayscale_enabled": True})
        self.assertIs(controller._toggle_takeoff_grayscale(False), False)
        self.assertEqual(harness.config_updates[-1], {"grayscale_enabled": False})

    def test_toolbar_and_tab_commands_reach_the_window_and_resync_the_checks(self):
        harness = _RealMenuHarness(self)
        controller = harness.controller
        callbacks = controller._get_menu_callbacks()
        callbacks["toggle_main_toolbar"](False)
        callbacks["toggle_view_toolbar"](True)
        callbacks["toggle_plan_tools_toolbar"](False)
        self.assertEqual(
            harness.calls.log,
            [
                (
                    "window.set_workspace_toolbar_preference",
                    ("main_toolbar", False),
                    {},
                ),
                ("window.set_workspace_toolbar_preference", ("view_toolbar", True), {}),
                (
                    "window.set_workspace_toolbar_preference",
                    ("plan_tools_toolbar", False),
                    {},
                ),
            ],
        )
        harness.calls.log.clear()
        actions = controller._actions
        self.assertTrue(actions["toggle_2d_tab"].isChecked())
        self.assertFalse(actions["toggle_3d_tab"].isChecked())
        harness.env.tab_2d_visible = False
        harness.env.tab_3d_visible = False
        callbacks["toggle_2d_tab"](True)
        self.assertEqual(
            harness.calls.log, [("window.set_takeoff_2d_tab_visible", (True,), {})]
        )
        self.assertTrue(actions["toggle_2d_tab"].isChecked())
        self.assertFalse(actions["toggle_3d_tab"].isChecked())
        harness.calls.log.clear()
        callbacks["toggle_3d_tab"](True)
        self.assertEqual(
            harness.calls.log, [("window.set_takeoff_3d_tab_visible", (True,), {})]
        )
        self.assertTrue(actions["toggle_3d_tab"].isChecked())

    def test_show_cover_sheet_requires_access_and_a_selected_bid(self):
        harness = _RealMenuHarness(self)
        controller = harness.controller
        controller._show_cover_sheet()
        self.assertEqual(harness.calls.log, [("cover_sheet.open_cover_sheet", (), {})])
        harness.calls.log.clear()
        harness.monitor.active = True
        harness.access.refresh()
        controller._show_cover_sheet()
        harness.monitor.active = False
        harness.access.refresh()
        harness.env.selected_bid_ref = None
        controller._show_cover_sheet()
        self.assertEqual(harness.calls.log, [])

    def test_select_objects_in_current_area_is_gated_by_access_and_plan_view(self):
        harness = _RealMenuHarness(self)
        controller = harness.controller
        harness.project_data.locked = True
        controller._select_objects_in_current_area()
        self.assertEqual(harness.calls.log, [])
        harness.project_data.locked = False
        harness.env.plan_view = None
        with patch(
            "ost_visualizer.presentation.controllers.menu_controller.show_warning"
        ) as warning:
            controller._select_objects_in_current_area()
        warning.assert_called_once_with(
            harness.window,
            "Select Objects in Current Area",
            "The active plan view is no longer available. Activate an open plan "
            "view and try again.",
        )
        self.assertEqual(harness.calls.log, [])

    def test_trigger_api_refreshes_state_and_blocks_disabled_or_forbidden_commands(
        self,
    ):
        harness = _RealMenuHarness(self)
        controller = harness.controller
        fired = []
        harness.shared_actions["zoom_in"].triggered.connect(
            lambda *_args: fired.append("zoom_in")
        )
        harness.shared_actions["dimension_tool"].triggered.connect(
            lambda *_args: fired.append("dimension_tool")
        )
        controller.trigger_menu_action("zoom_in")
        controller.trigger_menu_action("dimension_tool")
        self.assertEqual(fired, ["zoom_in", "dimension_tool"])
        harness.project_data.annotation_layer_visible = False
        controller.trigger_menu_action("dimension_tool")
        self.assertEqual(fired, ["zoom_in", "dimension_tool"])
        harness.project_data.annotation_layer_visible = True
        harness.env.takeoff_active = False
        controller.trigger_menu_action("zoom_in")
        self.assertEqual(fired, ["zoom_in", "dimension_tool"])
        harness.env.takeoff_active = True
        controller.trigger_menu_callback("import_ost")
        self.assertEqual(harness.calls.log, [("import_.import_ost", (), {})])
        harness.calls.log.clear()
        harness.monitor.active = True
        harness.access.refresh()
        controller.trigger_menu_callback("import_ost")
        controller.trigger_menu_callback("show_cover_sheet")
        controller.trigger_menu_callback("not_a_command")
        self.assertEqual(harness.calls.log, [])
        harness.monitor.active = False
        harness.access.refresh()
        controller.trigger_menu_callback("show_cover_sheet")
        self.assertEqual(harness.calls.log, [("cover_sheet.open_cover_sheet", (), {})])

    def test_trigger_menu_action_runs_callback_only_commands_when_enabled(self):
        harness = _RealMenuHarness(self)
        controller = harness.controller
        harness.calls.log.clear()
        controller.trigger_menu_action("delete_page")
        self.assertEqual(harness.calls.log, [("ui_event.delete_current_page", (), {})])
        harness.calls.log.clear()
        harness.env.can_delete_page = False
        controller.trigger_menu_action("delete_page")
        self.assertEqual(harness.calls.log, [])

    def test_context_command_enabled_state_per_command_family(self):
        harness = _RealMenuHarness(self)
        controller = harness.controller
        enabled = controller.is_context_command_enabled
        self.assertTrue(enabled("import_ost"))
        self.assertTrue(enabled("import_osp"))
        self.assertTrue(enabled("delete_page"))
        self.assertTrue(enabled("export_as_html"))
        self.assertTrue(enabled("export_as_osp"))
        self.assertTrue(enabled("export_summary_csv"))
        self.assertTrue(enabled("rotate_takeoff_left"))
        self.assertTrue(enabled("quit"))
        self.assertFalse(enabled("no_such_command"))
        harness.env.can_delete_page = False
        self.assertFalse(enabled("delete_page"))
        harness.env.selected_project_uid = "1"
        self.assertFalse(enabled("import_ost"))
        self.assertFalse(enabled("import_osp"))
        self.assertTrue(enabled("export_as_html"))
        harness.env.selected_project_uid = "5"
        harness.monitor.active = True
        harness.access.refresh()
        self.assertFalse(enabled("import_osp"))
        self.assertFalse(enabled("rotate_takeoff_left"))
        self.assertTrue(enabled("export_as_html"))
        harness.monitor.active = False
        harness.access.refresh()
        harness.env.selected_bid_ref = None
        self.assertFalse(enabled("export_as_html"))
        self.assertFalse(enabled("export_as_ost"))
        self.assertFalse(enabled("export_summary_csv"))

    def test_menu_action_state_describes_actions_and_callback_only_commands(self):
        harness = _RealMenuHarness(self)
        controller = harness.controller
        state = controller.get_menu_action_state("toggle_page_invert")
        self.assertEqual(
            state,
            {
                "text": controller._actions["toggle_page_invert"].text(),
                "enabled": True,
                "checkable": True,
                "checked": False,
            },
        )
        self.assertEqual(state["text"], "Invert")
        harness.env.takeoff_active = False
        state = controller.get_menu_action_state("toggle_page_invert")
        self.assertEqual(
            (state["enabled"], state["checkable"], state["checked"]),
            (False, True, False),
        )
        harness.env.takeoff_active = True
        harness.project_data.annotation_layer_visible = False
        dimension = controller.get_menu_action_state("dimension_tool")
        self.assertEqual(dimension["enabled"], False)
        harness.project_data.annotation_layer_visible = True
        self.assertTrue(controller.get_menu_action_state("dimension_tool")["enabled"])
        self.assertEqual(
            controller.get_menu_action_state("delete_page"),
            {
                "text": "Delete Page",
                "enabled": True,
                "checkable": False,
                "checked": False,
            },
        )
        harness.env.can_delete_page = False
        self.assertFalse(controller.get_menu_action_state("delete_page")["enabled"])
        self.assertEqual(
            controller.get_menu_action_state("quit_now_please"),
            {
                "text": "Quit Now Please",
                "enabled": False,
                "checkable": False,
                "checked": False,
            },
        )


class MenuControllerSecondPassResolverTests(unittest.TestCase):
    """Direct tests of the small resolvers and predicates of MenuController
    (second pass: every boolean result is checked with assertIs, because the
    unit-level assertTrue/assertFalse accept None and truthy objects)."""

    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()

    def tearDown(self):
        self.app.processEvents()

    def _controller(self, **attributes):
        controller = MenuController.__new__(MenuController)
        for name, value in attributes.items():
            setattr(controller, name, value)
        return controller

    def test_flush_deferred_for_file_skips_unknown_files_and_reports_a_bool(self):
        flushed = []

        def flush(path):
            flushed.append(path)
            return {"db.mdb": object(), "bad.mdb": 0}.get(path)

        controller = self._controller(
            _deferred_persistence=SimpleNamespace(flush_for_file=flush)
        )
        self.assertIs(controller._flush_deferred_for_file(None), True)
        self.assertIs(controller._flush_deferred_for_file(""), True)
        self.assertEqual(flushed, [])
        self.assertIs(controller._flush_deferred_for_file("db.mdb"), True)
        self.assertIs(controller._flush_deferred_for_file("bad.mdb"), False)
        self.assertIs(controller._flush_deferred_for_file("missing.mdb"), False)
        self.assertEqual(flushed, ["db.mdb", "bad.mdb", "missing.mdb"])

    def test_resolve_project_tree_file_path_prefers_selection_then_project_then_only_file(
        self,
    ):
        asked = []
        hierarchy = SimpleNamespace(
            loaded_files=[],
            find_file_path_for_project=lambda uid: (
                asked.append(uid) or {"p-known": "found.mdb"}.get(uid)
            ),
        )
        ui_state = SimpleNamespace(selected_file_path=None, selected_project_uid=None)
        controller = self._controller(
            ui_state_manager=ui_state,
            project_data=SimpleNamespace(get_hierarchy=lambda: hierarchy),
        )
        self.assertIsNone(controller._resolve_project_tree_file_path())
        self.assertEqual(asked, [])
        ui_state.selected_file_path = "selected.mdb"
        ui_state.selected_project_uid = "p-known"
        self.assertEqual(controller._resolve_project_tree_file_path(), "selected.mdb")
        self.assertEqual(asked, [])
        ui_state.selected_file_path = None
        self.assertEqual(controller._resolve_project_tree_file_path(), "found.mdb")
        self.assertEqual(asked, ["p-known"])
        ui_state.selected_project_uid = "p-unknown"
        hierarchy.loaded_files = [SimpleNamespace(file_path="only.mdb")]
        self.assertEqual(controller._resolve_project_tree_file_path(), "only.mdb")
        hierarchy.loaded_files = [
            SimpleNamespace(file_path="one.mdb"),
            SimpleNamespace(file_path="two.mdb"),
        ]
        self.assertIsNone(controller._resolve_project_tree_file_path())
        hierarchy.loaded_files = []
        self.assertIsNone(controller._resolve_project_tree_file_path())
        ui_state.selected_project_uid = None
        hierarchy.loaded_files = [SimpleNamespace(file_path="only.mdb")]
        asked.clear()
        self.assertEqual(controller._resolve_project_tree_file_path(), "only.mdb")
        self.assertEqual(asked, [])

    def test_resolve_target_project_uid_ignores_the_database_root_selection(self):
        bid_ref = BidRef("db.mdb", "bid-1")
        lookups = []
        ui_state = SimpleNamespace(selected_project_uid="5", bid_ref=bid_ref)
        ui_state.get_selected_bid_ref = lambda: ui_state.bid_ref
        controller = self._controller(
            ui_state_manager=ui_state,
            project_data=SimpleNamespace(
                find_project_uid_for_bid=lambda ref: (
                    lookups.append(ref) or "owner-project"
                )
            ),
        )
        self.assertEqual(controller._resolve_target_project_uid(), "5")
        self.assertEqual(lookups, [])
        for root in ("1", "", None):
            with self.subTest(selected_project_uid=root):
                ui_state.selected_project_uid = root
                self.assertEqual(
                    controller._resolve_target_project_uid(), "owner-project"
                )
        self.assertEqual(lookups, [bid_ref] * 3)
        ui_state.bid_ref = None
        self.assertIsNone(controller._resolve_target_project_uid())
        self.assertEqual(len(lookups), 3)

    def test_project_tree_target_identity_matches_normalized_paths_and_projects(self):
        first_project = object()
        second_project = object()
        other_entry = SimpleNamespace(
            file_path="C:/Other/db.mdb", bid_projects={"p1": object()}
        )
        wanted_entry = SimpleNamespace(
            file_path="C:\\Jobs\\DB.mdb",
            bid_projects={"p1": first_project, "p2": second_project},
        )
        controller = self._controller(
            project_data=SimpleNamespace(
                get_hierarchy=lambda: SimpleNamespace(
                    loaded_files=[other_entry, wanted_entry]
                )
            )
        )
        resolve = controller._resolve_project_tree_target_identity
        self.assertEqual(resolve("c:/jobs/db.mdb", None), (wanted_entry, None))
        identity = resolve("c:/jobs/db.mdb", "p2")
        self.assertIs(identity[0], wanted_entry)
        self.assertIs(identity[1], second_project)
        self.assertIsNone(resolve("c:/jobs/db.mdb", "missing-project"))
        self.assertIsNone(resolve("c:/jobs/unknown.mdb", None))
        self.assertIsNone(resolve("c:/jobs/unknown.mdb", "p1"))
        self.assertEqual(resolve("c:/other/DB.MDB", "p1")[0], other_entry)

    def test_project_tree_target_identity_is_current_only_for_the_same_objects(self):
        entry = SimpleNamespace(file_path="db.mdb", bid_projects={"p1": object()})
        loaded = [entry]
        controller = self._controller(
            project_data=SimpleNamespace(
                get_hierarchy=lambda: SimpleNamespace(loaded_files=loaded)
            )
        )
        expected = (entry, entry.bid_projects["p1"])
        current = controller._project_tree_target_identity_is_current
        self.assertIs(current("db.mdb", "p1", expected), True)
        self.assertIs(current("db.mdb", "p1", (object(), expected[1])), False)
        self.assertIs(current("db.mdb", "p1", (entry, object())), False)
        self.assertIs(current("db.mdb", "gone", expected), False)
        loaded.clear()
        self.assertIs(current("db.mdb", "p1", expected), False)
        loaded.append(entry)
        self.assertIs(current("db.mdb", None, (entry, None)), True)
        self.assertIs(current("db.mdb", None, (entry, expected[1])), False)

    def test_master_data_dialog_needs_a_database_context_and_permission(self):
        for path, allowed, expected in (
            ("db.mdb", True, True),
            ("db.mdb", False, False),
            (None, True, False),
            (None, False, False),
        ):
            with self.subTest(path=path, allowed=allowed):
                controller = self._controller(
                    window=SimpleNamespace(
                        get_selected_database_context_file_path=lambda p=path: p
                    ),
                    ui_access_manager=_Access(
                        denied=() if allowed else (Feature.EDIT_MASTER_DATA,)
                    ),
                )
                self.assertIs(controller._can_open_master_data_dialog(), expected)

    def test_project_tree_creation_asks_the_access_manager_about_the_file_context(self):
        asked = []
        controller = self._controller(
            window=SimpleNamespace(is_summary_tab_active=lambda: False),
            ui_access_manager=SimpleNamespace(
                can_create_project_tree_items=lambda has_file: (
                    asked.append(has_file) or has_file
                )
            ),
            _resolve_project_tree_file_path=lambda: "db.mdb",
        )
        self.assertIs(controller._should_enable_project_tree_creation(), True)
        controller._resolve_project_tree_file_path = lambda: None
        self.assertIs(controller._should_enable_project_tree_creation(), False)
        self.assertEqual(asked, [True, False])

    def test_active_page_helpers_report_exact_values_and_do_not_query_without_a_page(
        self,
    ):
        queried = []
        page = Page(uid="page-1", name="A1")
        ui_state = _UiState()
        project_data = SimpleNamespace(get_page=lambda uid: queried.append(uid) or page)
        controller = self._controller(
            ui_state_manager=ui_state, project_data=project_data
        )
        self.assertIsNone(controller._active_page())
        self.assertIs(controller._active_page_invert(), False)
        self.assertIs(controller._active_page_bitonal(), False)
        self.assertEqual(controller._active_page_overlay_flags(), (False, False))
        self.assertEqual(queried, [])
        ui_state.active_page_uid = "page-1"
        self.assertIs(controller._active_page(), page)
        self.assertEqual(queried, ["page-1"])
        self.assertIs(controller._active_page_invert(), False)
        page.invert = True
        page.bitonal = True
        self.assertIs(controller._active_page_invert(), True)
        self.assertIs(controller._active_page_bitonal(), True)
        for mode, flags in ((0, (True, False)), (1, (False, True)), (2, (True, True))):
            page.image_show_mode = mode
            self.assertEqual(controller._active_page_overlay_flags(), flags)

    def test_export_predicates_return_booleans_for_every_context(self):
        bid_ref = BidRef("db.mdb", "bid-1")
        ui_state = _UiState(bid_ref)
        project_data = _ProjectData(bid_ref)
        controller = _controller(ui_state, project_data)
        self.assertIs(controller._should_enable_export(), True)
        self.assertIs(controller._should_enable_pdf_export(), True)
        self.assertIs(controller._should_enable_summary_csv_export(), True)
        self.assertEqual(controller._active_selected_bid_ref(), bid_ref)
        project_data.takeoffs = []
        self.assertIs(controller._should_enable_export(), False)
        self.assertIs(controller._should_enable_summary_csv_export(), False)
        project_data.takeoffs = [object()]
        project_data.selected_page_uids = []
        self.assertIs(controller._should_enable_export(), False)
        project_data.selected_page_uids = ["page-1"]
        project_data.conditions = {}
        self.assertIs(controller._should_enable_summary_csv_export(), False)
        project_data.conditions = {"c": object()}
        project_data.page.width_pts = 0.5
        project_data.page.height_pts = 0.5
        self.assertIs(controller._should_enable_pdf_export(), True)
        project_data.page.width_pts = 0
        self.assertIs(controller._should_enable_pdf_export(), False)
        project_data.page.width_pts = 612
        project_data.page.height_pts = 0
        self.assertIs(controller._should_enable_pdf_export(), False)
        project_data.current_bid_ref = BidRef("db.mdb", "other")
        self.assertIsNone(controller._active_selected_bid_ref())
        self.assertIs(controller._should_enable_export(), False)
        self.assertIs(controller._should_enable_pdf_export(), False)
        self.assertIs(controller._should_enable_summary_csv_export(), False)

    def test_export_command_enablement_is_a_strict_bool_for_every_family(self):
        bid_ref = BidRef("db.mdb", "bid-1")
        controller = _controller(_UiState(bid_ref), _ProjectData(bid_ref))
        controller._export_formats = ["html", "xlsx"]
        enabled = controller._export_command_enabled
        for key in (
            "export_summary_csv",
            "export_as_pdf",
            "export_as_ost",
            "export_as_osp",
            "export_as_html",
            "export_as_xlsx",
        ):
            with self.subTest(command=key):
                self.assertIs(enabled(key), True)
        self.assertIsNone(enabled("export_as_unknown"))
        self.assertIsNone(enabled("something_else"))
        controller.ui_access_manager = _Access(
            denied={Feature.EXPORT, Feature.EXPORT_BID_FILE}
        )
        for key in (
            "export_summary_csv",
            "export_as_pdf",
            "export_as_ost",
            "export_as_osp",
            "export_as_html",
        ):
            with self.subTest(denied=key):
                self.assertIs(enabled(key), False)
        states = controller._export_action_enabled_states()
        self.assertEqual(
            states,
            {
                "export_as_html": False,
                "export_as_xlsx": False,
                "export_summary_csv": False,
                "export_as_pdf": False,
                "export_as_ost": False,
                "export_as_osp": False,
            },
        )
        controller.ui_access_manager = SimpleNamespace(
            is_allowed=lambda feature: 0 if feature is Feature.EXPORT else 1
        )
        for value in controller._export_action_enabled_states().values():
            self.assertIsInstance(value, bool)
        self.assertIs(
            controller._export_action_enabled_states()["export_as_pdf"], False
        )
        self.assertIs(controller._export_action_enabled_states()["export_as_osp"], True)

    def test_context_command_without_a_menu_action_follows_the_export_rules(self):
        bid_ref = BidRef("db.mdb", "bid-1")
        controller = _controller(_UiState(bid_ref), _ProjectData(bid_ref))
        controller._actions = {}
        controller._export_formats = ["html"]
        controller._get_menu_callbacks = lambda: {
            "export_as_pdf": object(),
            "export_as_html": object(),
            "other": object(),
        }
        controller.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(can_delete_current_page=lambda: False)
        )
        controller.update_menu_states = lambda: None
        self.assertIs(controller.is_context_command_enabled("export_as_pdf"), True)
        controller.ui_access_manager = _Access(denied={Feature.EXPORT})
        self.assertIs(controller.is_context_command_enabled("export_as_pdf"), False)
        self.assertIs(controller.is_context_command_enabled("export_as_html"), False)
        self.assertIs(controller.is_context_command_enabled("other"), True)
        self.assertIs(controller.is_context_command_enabled("delete_page"), False)
        self.assertIs(controller.is_context_command_enabled("unknown"), False)

    def test_import_enablement_is_a_strict_bool(self):
        ui_state = SimpleNamespace(selected_project_uid="2")
        controller = self._controller(
            ui_state_manager=ui_state, ui_access_manager=_Access()
        )
        self.assertIs(controller._should_enable_import(), True)
        controller.ui_access_manager = _Access(denied={Feature.IMPORT})
        self.assertIs(controller._should_enable_import(), False)
        ui_state.selected_project_uid = "1"
        controller.ui_access_manager = _Access()
        self.assertIs(controller._should_enable_import(), False)
        ui_state.selected_project_uid = None
        self.assertIs(controller._should_enable_import(), True)

    def test_cover_sheet_command_needs_access_and_a_selected_bid(self):
        opened = []
        ui_state = _UiState(None)
        controller = self._controller(
            ui_state_manager=ui_state,
            ui_access_manager=_Access(),
            handlers=SimpleNamespace(
                cover_sheet=SimpleNamespace(
                    open_cover_sheet=lambda: opened.append("open")
                )
            ),
        )
        controller._show_cover_sheet()
        self.assertEqual(opened, [])
        ui_state._bid_ref = BidRef("db.mdb", "bid-1")
        controller.ui_access_manager = _Access(denied={Feature.COVER_SHEET})
        controller._show_cover_sheet()
        self.assertEqual(opened, [])
        controller.ui_access_manager = _Access()
        controller._show_cover_sheet()
        self.assertEqual(opened, ["open"])

    def test_cover_sheet_and_areas_actions_need_a_selected_bid_even_if_access_allows(
        self,
    ):
        bid_ref = BidRef("db.mdb", "bid-1")
        ui_state = _UiState(bid_ref)
        controller = _controller(ui_state, _ProjectData(bid_ref))
        controller.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(can_renumber_conditions=lambda: True)
        )
        controller._actions["show_cover_sheet"] = _Action()
        controller._actions["show_areas"] = _Action()
        controller.update_menu_states()
        self.assertTrue(controller._actions["show_cover_sheet"].isEnabled())
        self.assertTrue(controller._actions["show_areas"].isEnabled())
        ui_state._bid_ref = None
        controller.update_menu_states()
        self.assertFalse(controller._actions["show_cover_sheet"].isEnabled())
        self.assertFalse(controller._actions["show_areas"].isEnabled())

    def test_html_export_options_menu_follows_the_html_export_state(self):
        bid_ref = BidRef("db.mdb", "bid-1")
        project_data = _ProjectData(bid_ref)
        controller = _controller(_UiState(bid_ref), project_data)
        controller.update_menu_states()
        self.assertTrue(controller._menus["html export options"].isEnabled())
        project_data.takeoffs = []
        controller.update_menu_states()
        self.assertFalse(controller._menus["html export options"].isEnabled())
        self.assertFalse(controller._actions["export_as_html"].isEnabled())
        self.assertTrue(controller._menus["export"].isEnabled())

    def test_menus_that_are_always_available_are_re_enabled_by_every_update(self):
        harness = _RealMenuHarness(self)
        controller = harness.controller
        names = ("takeoff", "tools", "image", "project", "master")
        for name in names:
            controller._menus[name].setEnabled(False)
        controller.update_menu_states()
        for name in names:
            with self.subTest(menu=name):
                self.assertTrue(controller._menus[name].isEnabled())

    def test_tool_actions_drop_stale_navigation_state_and_follow_external_enabling(
        self,
    ):
        pan = _Action()
        select = _Action()
        select.setEnabled(False)
        controller = MenuController.__new__(MenuController)
        controller._actions = {"pan_tool": pan, "select_tool": select}
        controller._tool_action_enabled_state = {"pan_tool": False}
        controller.window = SimpleNamespace(
            opengl_viewer=None,
            get_view_stack=lambda: None,
            get_takeoff_plan_view=lambda: None,
        )
        with patch(
            "ost_visualizer.presentation.controllers.menu_controller."
            "scene_navigation_available",
            return_value=True,
        ):
            MenuController._sync_tool_action_states(controller, False)
            self.assertNotIn("pan_tool", controller._tool_action_enabled_state)
            self.assertFalse(pan.isEnabled())
            self.assertEqual(
                controller._tool_action_enabled_state, {"select_tool": False}
            )
            select.setEnabled(True)
            MenuController._sync_tool_action_states(controller, False)
            self.assertEqual(
                controller._tool_action_enabled_state, {"select_tool": True}
            )
            self.assertFalse(select.isEnabled())
            MenuController._sync_tool_action_states(controller, True)
        self.assertTrue(select.isEnabled())
        self.assertTrue(pan.isEnabled())
        self.assertEqual(controller._tool_action_enabled_state, {})

    def test_scoped_variables_are_cleared_outside_takeoff_and_others_follow_the_getter(
        self,
    ):
        scoped = (
            "display_modes_synced",
            "display_mode_3d",
            "display_mode_2d",
            "grayscale",
            "page_invert",
            "page_bitonal",
            "takeoff_2d_tab_visible",
            "takeoff_3d_tab_visible",
            action_ids.ACTION_SHOW_OVERLAY_IMAGE,
            action_ids.ACTION_SHOW_ORIGINAL_IMAGE,
        )
        actions = {}
        for name in (*scoped, "toolbar_visible"):
            action = QtGui.QAction()
            action.setCheckable(True)
            action.setChecked(True)
            actions[name] = action
        controller = MenuController.__new__(MenuController)
        controller._variable_actions = {name: [a] for name, a in actions.items()}
        controller._state_getters = {name: (lambda: True) for name in actions}
        controller._sync_variable_actions(takeoff_active=False)
        for name in scoped:
            with self.subTest(variable=name):
                self.assertFalse(actions[name].isChecked())
        self.assertTrue(actions["toolbar_visible"].isChecked())
        controller._sync_variable_actions(takeoff_active=True)
        for name in actions:
            with self.subTest(restored=name):
                self.assertTrue(actions[name].isChecked())

    def test_variable_action_without_data_checks_from_a_truthy_non_bool_value(self):
        action = QtGui.QAction()
        action.setCheckable(True)
        controller = MenuController.__new__(MenuController)
        controller._variable_actions = {"toolbar_visible": [action]}
        value = {"v": "yes"}
        controller._state_getters = {"toolbar_visible": lambda: value["v"]}
        controller._sync_variable_actions(takeoff_active=True)
        self.assertTrue(action.isChecked())
        value["v"] = ""
        controller._sync_variable_actions(takeoff_active=True)
        self.assertFalse(action.isChecked())

    def test_create_menu_applies_the_takeoff_context_to_the_freshly_built_menu(self):
        def not_in_takeoff(env):
            env.takeoff_active = False

        harness = _RealMenuHarness(self, configure=not_in_takeoff)
        controller = harness.controller
        self.assertFalse(controller._actions["zoom_in"].isEnabled())
        self.assertFalse(controller._actions["toggle_takeoff_grayscale"].isChecked())
        self.assertFalse(controller._actions["toggle_2d_tab"].isChecked())
        self.assertEqual(harness.backout_refreshes, [1])
        self.assertTrue(controller._actions["toggle_main_toolbar"].isChecked())

    def test_trigger_menu_callback_ignores_shared_actions_without_a_callback(self):
        harness = _RealMenuHarness(self)
        harness.calls.log.clear()
        harness.controller.trigger_menu_callback("undo")
        harness.controller.trigger_menu_callback("zoom_in")
        self.assertEqual(harness.calls.log, [])


class _NewProjectDialogRecorder:
    """Stands in for CoverSheetDialog and records how it was built and disposed."""

    instances = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.deleted = 0
        type(self).instances.append(self)

    def deleteLater(self):
        self.deleted += 1

    def get_updates(self):
        return {"job_name": "Accepted"}


class MenuControllerNewProjectContractTests(unittest.TestCase):
    """What MenuController builds for the New Project (cover sheet) dialog, on the
    Access (synchronous) and SQL (queued, lease-owning) paths."""

    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()

    def tearDown(self):
        self.app.processEvents()

    def _launch(
        self,
        *,
        sql=False,
        defaults=None,
        result=QtWidgets.QDialog.DialogCode.Rejected,
        access=None,
        flush_ok=True,
        window=None,
        dialog_class=_NewProjectDialogRecorder,
        lease_session=None,
        public=False,
        during_exec=None,
    ):
        _NewProjectDialogRecorder.instances = []
        log = []
        window = window if window is not None else QtWidgets.QWidget()
        if isValid(window):
            self.addCleanup(lambda: delete(window) if isValid(window) else None)
        target_identity = (object(), object())
        controller = MenuController.__new__(MenuController)
        controller.window = window
        controller.icon_provider = SimpleNamespace(name="icons")
        controller._event_bus = SimpleNamespace(name="events")
        controller._workspace_state_model = make_workspace_state_model()
        controller._infrastructure_provider = SimpleNamespace(
            get_pdf_page_sizes=lambda path: [path]
        )
        controller._resolve_project_tree_file_path = lambda: "db.mdb"
        controller._resolve_target_project_uid = lambda: "project-1"
        controller._resolve_project_tree_target_identity = lambda *args: (
            log.append(("identity", args)) or target_identity
        )
        controller.ui_access_manager = access or SimpleNamespace(
            can_create_bid=lambda *args: log.append(("can_create_bid", args)) or True,
            has_license=lambda: True,
            is_allowed=lambda _feature: True,
        )
        controller._deferred_persistence = SimpleNamespace(
            flush_for_file=lambda path: log.append(("flush", path)) or flush_ok
        )
        job_statuses = [SimpleNamespace(uid="status")]
        employees = [SimpleNamespace(uid="employee")]
        pay_classes = [SimpleNamespace(uid="pay-class")]
        controller._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda path: (
                log.append(("uses_sql", path)) or sql
            ),
            save_job_statuses=lambda path, changes: (
                log.append(("save_job_statuses", path, changes)) or "saved-statuses"
            ),
            save_employees_result=lambda path, changes: (
                log.append(("save_employees", path, changes)) or "saved-employees"
            ),
            save_pay_classes=lambda path, changes: (
                log.append(("save_pay_classes", path, changes)) or "saved-pay-classes"
            ),
            create_bid_result=lambda path, project, updates: (
                log.append(("create_bid", path, project, updates))
                or WriteReloadResult("bid-new", write_success=True, reload_success=True)
            ),
        )
        read_service = SimpleNamespace(
            get_settings_defaults=lambda path: (
                log.append(("read_defaults", path)) or dict(defaults or {})
            ),
            get_job_statuses=lambda path: (
                log.append(("read_job_statuses", path)) or job_statuses
            ),
            get_employees_and_pay_classes=lambda path: (
                log.append(("read_employees", path)) or (employees, pay_classes)
            ),
            get_master_data_uids_in_use=lambda path, family: (
                log.append(("read_usage", path, family)) or {"read-usage"}
            ),
        )
        controller._project_read_service = read_service
        controller.project_data = SimpleNamespace(
            get_settings_defaults_snapshot=lambda path: (
                log.append(("snapshot_defaults", path)) or dict(defaults or {})
            ),
            get_job_status_snapshot=lambda path: (
                log.append(("snapshot_job_statuses", path)) or job_statuses
            ),
            get_employee_snapshot=lambda path: (
                log.append(("snapshot_employees", path)) or employees
            ),
            get_pay_class_snapshot=lambda path: (
                log.append(("snapshot_pay_classes", path)) or pay_classes
            ),
            get_master_data_uids_in_use=lambda path, family: (
                log.append(("snapshot_usage", path, family)) or {"queue-usage"}
            ),
        )
        controller.handlers = SimpleNamespace(
            cover_sheet=SimpleNamespace(
                create_new_bid_lease_session=lambda *args: (
                    log.append(("lease_session", args)) or lease_session
                )
            )
        )
        executed = []

        def execute(dialog, event_bus):
            executed.append((dialog, event_bus))
            if during_exec is not None:
                during_exec(controller, dialog)
            return result

        fixed_now = datetime.datetime(2026, 3, 4, 15, 6, 59)
        with (
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "CoverSheetDialog",
                dialog_class,
            ),
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "exec_with_ost_blocking",
                side_effect=execute,
            ),
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller.datetime",
                SimpleNamespace(datetime=SimpleNamespace(now=lambda: fixed_now)),
            ),
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller.show_warning"
            ),
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller.show_critical"
            ),
        ):
            if public:
                controller.new_project_at("db.mdb", "project-1")
            else:
                controller._new_project()
        return SimpleNamespace(
            controller=controller,
            log=log,
            window=window,
            executed=executed,
            dialogs=list(_NewProjectDialogRecorder.instances),
            identity=target_identity,
            job_statuses=job_statuses,
            employees=employees,
            pay_classes=pay_classes,
        )

    def test_default_cover_sheet_data_for_a_new_project(self):
        run = self._launch()
        (dialog,) = run.dialogs
        data = dialog.args[2]
        self.assertEqual(dialog.args[:2], (run.controller.icon_provider, run.window))
        self.assertEqual(data.bid_uid, "")
        self.assertEqual(data.job_status_uid, "")
        self.assertEqual(data.job_name, "New Project 1")
        self.assertEqual(data.estimator_uid, "")
        self.assertEqual(data.notes, "")
        self.assertEqual(data.bid_date, "2026 03 04 15 06 0")
        self.assertEqual(data.bid_no, "1")
        self.assertEqual(data.job_id, "")
        self.assertEqual(
            (
                data.measure_base,
                data.takeoff_increments,
                data.scale_style,
                data.scale_factor1,
                data.scale_factor2,
                data.page_width,
                data.page_height,
            ),
            (0, 1.0, 1, 0.125, 12.0, 42.0, 30.0),
        )
        self.assertEqual(
            data.pages_without_folder,
            [
                CoverSheetPage(
                    uid="new_page_1",
                    sheet_no="00001",
                    name="Page 1",
                    width=42.0,
                    height=30.0,
                    scale_factor1=0.125,
                    scale_factor2=12.0,
                    image_path="",
                    overlay_image_path="",
                    index=1,
                    show_mode=0,
                )
            ],
        )
        self.assertIs(data.job_statuses, run.job_statuses)
        self.assertIs(data.employees, run.employees)
        self.assertIs(data.pay_classes, run.pay_classes)
        self.assertIn(("read_defaults", "db.mdb"), run.log)
        self.assertIn(("read_job_statuses", "db.mdb"), run.log)
        self.assertIn(("read_employees", "db.mdb"), run.log)

    def test_configured_defaults_flow_into_the_cover_sheet_data_and_its_first_page(
        self,
    ):
        run = self._launch(
            defaults={
                "scale_factor1": 0.5,
                "scale_factor2": 24.0,
                "page_width": 11.0,
                "page_height": 17.0,
                "next_bid_no": 42,
                "measure_base": 2,
                "takeoff_increments": 0.5,
                "scale_style": 3,
            }
        )
        data = run.dialogs[0].args[2]
        self.assertEqual(data.job_name, "New Project 42")
        self.assertEqual(data.bid_no, "42")
        self.assertEqual(
            (
                data.measure_base,
                data.takeoff_increments,
                data.scale_style,
                data.scale_factor1,
                data.scale_factor2,
                data.page_width,
                data.page_height,
            ),
            (2, 0.5, 3, 0.5, 24.0, 11.0, 17.0),
        )
        (page,) = data.pages_without_folder
        self.assertEqual(
            (page.width, page.height, page.scale_factor1, page.scale_factor2),
            (11.0, 17.0, 0.5, 24.0),
        )

    def test_sql_new_project_reads_defaults_and_master_data_from_the_snapshots(self):
        class Session:
            def __init__(self):
                self.bound = []
                self.closed = 0

            def bind_dialog(self, dialog):
                self.bound.append(dialog)

            def request_initial(self, completed):
                completed(SimpleNamespace(granted=True))

            def close(self):
                self.closed += 1

        session = Session()
        run = self._launch(sql=True, lease_session=session, defaults={"next_bid_no": 9})
        (dialog,) = run.dialogs
        data = dialog.args[2]
        self.assertEqual(data.job_name, "New Project 9")
        self.assertIs(data.job_statuses, run.job_statuses)
        self.assertIs(data.employees, run.employees)
        self.assertIs(data.pay_classes, run.pay_classes)
        kinds = [entry[0] for entry in run.log]
        for name in (
            "snapshot_defaults",
            "snapshot_job_statuses",
            "snapshot_employees",
            "snapshot_pay_classes",
        ):
            self.assertIn(name, kinds)
        for name in ("read_defaults", "read_job_statuses", "read_employees"):
            self.assertNotIn(name, kinds)
        self.assertEqual(session.bound, [dialog])
        self.assertEqual(session.closed, 1)
        self.assertEqual(dialog.deleted, 1)
        self.assertNotIn("create_bid", kinds)
        self.assertEqual(
            [entry for entry in run.log if entry[0] == "lease_session"],
            [("lease_session", ("db.mdb", "project-1", data))],
        )

    def test_dialog_receives_its_context_and_working_callbacks_on_access(self):
        run = self._launch()
        (dialog,) = run.dialogs
        options = dialog.kwargs
        self.assertIs(options["has_license"], True)
        self.assertIs(options["event_bus"], run.controller._event_bus)
        self.assertEqual(options["database_id"], "db.mdb")
        self.assertIs(options["create_mode"], True)
        self.assertIs(
            options["workspace_state_model"], run.controller._workspace_state_model
        )
        self.assertEqual(options["pdf_page_sizes_fn"]("x.pdf"), ["x.pdf"])
        self.assertEqual(options["employee_usage_fn"](), {"read-usage"})
        self.assertEqual(options["pay_class_usage_fn"](), {"read-usage"})
        self.assertEqual(options["job_status_usage_fn"](), {"read-usage"})
        usage_calls = [entry for entry in run.log if entry[0] == "read_usage"]
        self.assertEqual(
            usage_calls,
            [
                ("read_usage", "db.mdb", "employees"),
                ("read_usage", "db.mdb", "pay_classes"),
                ("read_usage", "db.mdb", "job_statuses"),
            ],
        )
        self.assertIs(options["reload_job_statuses_fn"](), run.job_statuses)
        reloaded = options["reload_employees_fn"]()
        self.assertEqual(reloaded, (run.employees, run.pay_classes))
        self.assertIsNone(options["save_job_statuses_async_fn"])
        self.assertIsNone(options["save_employees_async_fn"])
        self.assertIsNone(options["save_pay_classes_async_fn"])
        self.assertIsNone(options["save_cover_sheet_async_fn"])
        self.assertEqual(options["save_job_statuses_fn"]("ch-1"), "saved-statuses")
        self.assertEqual(options["save_employees_fn"]("ch-2"), "saved-employees")
        self.assertEqual(options["save_pay_classes_fn"]("ch-3"), "saved-pay-classes")
        saved = [entry for entry in run.log if entry[0].startswith("save_")]
        self.assertEqual(
            saved,
            [
                ("save_job_statuses", "db.mdb", "ch-1"),
                ("save_employees", "db.mdb", "ch-2"),
                ("save_pay_classes", "db.mdb", "ch-3"),
            ],
        )

    def test_dialog_saves_need_edit_permission_and_a_successful_deferred_flush(self):
        for case, allowed, flush_ok, expect_write in (
            ("allowed", True, True, True),
            ("denied", False, True, False),
            ("flush failed", True, False, False),
        ):
            with self.subTest(case=case):
                access = SimpleNamespace(
                    can_create_bid=lambda *_args: True,
                    has_license=lambda: True,
                    is_allowed=lambda feature, allowed=allowed: (
                        allowed or feature is not Feature.EDIT_MASTER_DATA
                    ),
                )
                run = self._launch(access=access, flush_ok=flush_ok)
                options = run.dialogs[0].kwargs
                results = [
                    options["save_job_statuses_fn"]("a"),
                    options["save_employees_fn"]("b"),
                    options["save_pay_classes_fn"]("c"),
                ]
                writes = [e for e in run.log if e[0].startswith("save_")]
                flushes = [e for e in run.log if e[0] == "flush"]
                if expect_write:
                    self.assertEqual(
                        results,
                        ["saved-statuses", "saved-employees", "saved-pay-classes"],
                    )
                    self.assertEqual(len(writes), 3)
                else:
                    self.assertEqual(results, [False, False, False])
                    self.assertEqual(writes, [])
                self.assertEqual(len(flushes), 3 if allowed else 0)

    def test_sql_dialog_callbacks_use_the_snapshots(self):
        class Session:
            def bind_dialog(self, _dialog):
                pass

            def request_initial(self, completed):
                completed(SimpleNamespace(granted=True))

            def close(self):
                pass

        run = self._launch(sql=True, lease_session=Session())
        options = run.dialogs[0].kwargs
        self.assertEqual(options["employee_usage_fn"](), {"queue-usage"})
        self.assertEqual(options["pay_class_usage_fn"](), {"queue-usage"})
        self.assertEqual(options["job_status_usage_fn"](), {"queue-usage"})
        self.assertIs(options["reload_job_statuses_fn"](), run.job_statuses)
        self.assertEqual(
            options["reload_employees_fn"](), (run.employees, run.pay_classes)
        )
        usage = [e for e in run.log if e[0] == "snapshot_usage"]
        self.assertEqual(
            usage,
            [
                ("snapshot_usage", "db.mdb", "employees"),
                ("snapshot_usage", "db.mdb", "pay_classes"),
                ("snapshot_usage", "db.mdb", "job_statuses"),
            ],
        )
        for name in (
            "save_job_statuses_async_fn",
            "save_employees_async_fn",
            "save_pay_classes_async_fn",
            "save_cover_sheet_async_fn",
        ):
            self.assertTrue(callable(options[name]), name)

    def test_license_state_is_read_at_dialog_creation(self):
        for licensed in (True, False):
            with self.subTest(licensed=licensed):
                access = SimpleNamespace(
                    can_create_bid=lambda *_args: True,
                    has_license=lambda licensed=licensed: licensed,
                    is_allowed=lambda _feature: True,
                )
                run = self._launch(access=access)
                self.assertIs(run.dialogs[0].kwargs["has_license"], licensed)

    def test_exec_is_called_with_the_dialog_and_the_event_bus_and_the_dialog_is_released(
        self,
    ):
        for result in (
            QtWidgets.QDialog.DialogCode.Rejected,
            QtWidgets.QDialog.DialogCode.Accepted,
        ):
            with self.subTest(result=result):
                run = self._launch(result=result)
                (dialog,) = run.dialogs
                self.assertEqual(run.executed, [(dialog, run.controller._event_bus)])
                self.assertEqual(dialog.deleted, 1)

    def test_target_is_validated_with_file_then_project_before_any_dialog(self):
        access_log = []

        def deny(file_path, project_uid):
            access_log.append((file_path, project_uid))
            return False

        access = SimpleNamespace(
            can_create_bid=deny, has_license=lambda: True, is_allowed=lambda _f: True
        )
        run = self._launch(access=access)
        self.assertEqual(access_log, [("db.mdb", "project-1")])
        self.assertEqual(run.dialogs, [])
        self.assertNotIn("identity", [entry[0] for entry in run.log])
        run = self._launch()
        self.assertIn(("identity", ("db.mdb", "project-1")), run.log)
        self.assertIn(("can_create_bid", ("db.mdb", "project-1")), run.log)
        controller = run.controller
        controller._resolve_project_tree_target_identity = lambda *_args: None
        _NewProjectDialogRecorder.instances = []
        with mock.patch(
            "ost_visualizer.presentation.controllers.menu_controller.CoverSheetDialog",
            _NewProjectDialogRecorder,
        ):
            controller._new_project_at("db.mdb", "project-1")
        self.assertEqual(_NewProjectDialogRecorder.instances, [])

    def test_new_project_without_a_resolvable_database_does_nothing(self):
        controller = MenuController.__new__(MenuController)
        controller._resolve_project_tree_file_path = lambda: None
        controller._resolve_target_project_uid = lambda: "project-1"
        started = []
        controller._new_project_at = lambda *args, **kwargs: started.append(args)
        controller._new_project()
        self.assertEqual(started, [])
        controller._resolve_project_tree_file_path = lambda: "db.mdb"
        controller._new_project()
        self.assertEqual(started, [("db.mdb", "project-1")])

    def test_public_new_project_at_does_not_require_the_tree_selection_to_stay(self):
        started = []
        controller = MenuController.__new__(MenuController)
        controller._new_project_at = lambda *args, **kwargs: started.append(
            (args, kwargs)
        )
        controller.new_project_at("db.mdb", "project-7")
        self.assertEqual(started, [(("db.mdb", "project-7"), {})])

    def test_public_new_project_creates_even_if_the_tree_selection_moved(self):
        def move_selection(controller, _dialog):
            controller._resolve_project_tree_file_path = lambda: "other.mdb"
            controller._resolve_target_project_uid = lambda: "project-2"

        run = self._launch(
            result=QtWidgets.QDialog.DialogCode.Accepted,
            public=True,
            during_exec=move_selection,
        )
        self.assertEqual(
            [entry for entry in run.log if entry[0] == "create_bid"],
            [("create_bid", "db.mdb", "project-1", {"job_name": "Accepted"})],
        )
        run = self._launch(
            result=QtWidgets.QDialog.DialogCode.Accepted, during_exec=move_selection
        )
        self.assertNotIn("create_bid", [entry[0] for entry in run.log])

    def test_sql_new_project_never_creates_through_the_synchronous_path(self):
        class Session:
            def __init__(self):
                self.closed = 0

            def bind_dialog(self, _dialog):
                pass

            def request_initial(self, completed):
                completed(SimpleNamespace(granted=True))

            def close(self):
                self.closed += 1

        session = Session()
        run = self._launch(
            sql=True,
            lease_session=session,
            result=QtWidgets.QDialog.DialogCode.Accepted,
        )
        self.assertNotIn("create_bid", [entry[0] for entry in run.log])
        self.assertEqual(session.closed, 1)
        self.assertEqual(run.dialogs[0].deleted, 1)

    def test_destroyed_window_stops_the_flow_even_when_the_dialog_is_not_its_child(
        self,
    ):
        window = QtWidgets.QWidget()
        updates = []

        class Recorder(_NewProjectDialogRecorder):
            def get_updates(self):
                updates.append(1)
                return {}

        run = self._launch(
            window=window,
            dialog_class=Recorder,
            result=QtWidgets.QDialog.DialogCode.Accepted,
            during_exec=lambda _controller, _dialog: delete(window),
        )
        self.assertEqual(updates, [])
        self.assertNotIn("create_bid", [entry[0] for entry in run.log])
        self.assertEqual(run.dialogs[0].deleted, 1)

    def test_destroyed_dialog_stops_the_flow_while_the_window_lives(self):
        updates = []
        closed = []

        class RealDialog(QtWidgets.QDialog):
            def __init__(self, *_args, **_kwargs):
                super().__init__()

            def get_updates(self):
                updates.append(1)
                return {}

        run = self._launch(
            dialog_class=RealDialog,
            result=QtWidgets.QDialog.DialogCode.Accepted,
            during_exec=lambda _controller, dialog: (
                closed.append(isValid(dialog)),
                delete(dialog),
            ),
        )
        self.assertEqual(closed, [True])
        self.assertEqual(updates, [])
        self.assertNotIn("create_bid", [entry[0] for entry in run.log])

    def test_reload_callbacks_use_the_service_of_the_backend(self):
        class Session:
            def bind_dialog(self, _dialog):
                pass

            def request_initial(self, completed):
                completed(SimpleNamespace(granted=True))

            def close(self):
                pass

        access_run = self._launch()
        access_run.log.clear()
        access_run.dialogs[0].kwargs["reload_job_statuses_fn"]()
        access_run.dialogs[0].kwargs["reload_employees_fn"]()
        self.assertEqual(
            access_run.log,
            [("read_job_statuses", "db.mdb"), ("read_employees", "db.mdb")],
        )
        sql_run = self._launch(sql=True, lease_session=Session())
        sql_run.log.clear()
        sql_run.dialogs[0].kwargs["reload_job_statuses_fn"]()
        sql_run.dialogs[0].kwargs["reload_employees_fn"]()
        self.assertEqual(
            sql_run.log,
            [
                ("snapshot_job_statuses", "db.mdb"),
                ("snapshot_employees", "db.mdb"),
                ("snapshot_pay_classes", "db.mdb"),
            ],
        )

    def test_accepted_dialog_revalidates_the_target_with_the_same_argument_order(self):
        run = self._launch(result=QtWidgets.QDialog.DialogCode.Accepted)
        checks = [entry for entry in run.log if entry[0] == "can_create_bid"]
        self.assertEqual(
            checks,
            [("can_create_bid", ("db.mdb", "project-1"))] * 2,
        )
        identities = [entry for entry in run.log if entry[0] == "identity"]
        self.assertEqual(
            identities,
            [("identity", ("db.mdb", "project-1"))] * 2,
        )

    def test_new_project_dialog_arguments_match_the_real_dialog_signature(self):
        run = self._launch()
        (dialog,) = run.dialogs
        signature = inspect.signature(CoverSheetDialog.__init__)
        bound = signature.bind(None, *dialog.args, **dialog.kwargs)
        self.assertIs(bound.arguments["create_mode"], True)
        self.assertEqual(bound.arguments["database_id"], "db.mdb")


class MenuControllerDialogLifecycleTests(unittest.TestCase):
    """About, Options, New Database and New Folder: construction arguments, owner
    validity after the modal loop and disposal of every dialog on every path."""

    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()

    def tearDown(self):
        self.app.processEvents()

    def test_about_dialog_is_built_for_the_window_shown_and_disposed(self):
        events = []

        class FakeAbout:
            def __init__(self, icon_provider, parent):
                events.append(("init", icon_provider, parent))

            def exec(self):
                events.append("exec")

            def cleanup(self):
                events.append("cleanup")

            def deleteLater(self):
                events.append("deleteLater")

        controller = MenuController.__new__(MenuController)
        controller.icon_provider = "icons"
        controller.window = "window"
        with (
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller.AboutDialog",
                FakeAbout,
            ),
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller.delete_later_if_valid",
                side_effect=lambda dialog: dialog.deleteLater(),
            ),
        ):
            controller._show_about_dialog()
        self.assertEqual(
            events,
            [("init", "icons", "window"), "exec", "cleanup", "deleteLater"],
        )

    def test_about_dialog_skips_cleanup_of_an_invalid_dialog_but_still_deletes_it(self):
        events = []

        class FakeAbout:
            def __init__(self, *_args):
                pass

            def exec(self):
                events.append("exec")

            def cleanup(self):
                events.append("cleanup")

        controller = MenuController.__new__(MenuController)
        controller.icon_provider = None
        controller.window = None
        with (
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller.AboutDialog",
                FakeAbout,
            ),
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller.isValid",
                return_value=False,
            ),
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller.delete_later_if_valid",
                side_effect=lambda _dialog: events.append("delete"),
            ),
        ):
            controller._show_about_dialog()
        self.assertEqual(events, ["exec", "delete"])

    def test_about_dialog_is_deleted_even_when_cleanup_fails(self):
        events = []

        class FakeAbout:
            def __init__(self, *_args):
                pass

            def exec(self):
                raise RuntimeError("exec failed")

            def cleanup(self):
                events.append("cleanup")
                raise RuntimeError("cleanup failed")

        controller = MenuController.__new__(MenuController)
        controller.icon_provider = None
        controller.window = None
        with (
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller.AboutDialog",
                FakeAbout,
            ),
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller.delete_later_if_valid",
                side_effect=lambda _dialog: events.append("delete"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
                controller._show_about_dialog()
        self.assertEqual(events, ["cleanup", "delete"])

    def test_options_dialog_gets_the_config_window_and_both_callbacks(self):
        events = []
        config = Config()

        class FakeOptions:
            def __init__(self, snapshot, parent, apply_callback, reset_callback):
                events.append(
                    ("init", snapshot, parent, apply_callback, reset_callback)
                )

            def exec(self):
                events.append("exec")

        controller = MenuController.__new__(MenuController)
        controller.window = "window"
        controller.config_service = SimpleNamespace(
            get_config_snapshot=lambda: config, update_app_options="apply"
        )
        with (
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller.OptionsDialog",
                FakeOptions,
            ),
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller.delete_later_if_valid",
                side_effect=lambda _dialog: events.append("delete"),
            ),
        ):
            controller._show_options_dialog()
        self.assertEqual(
            events,
            [
                ("init", config, "window", "apply", controller._reset_all_settings),
                "exec",
                "delete",
            ],
        )

    def test_reset_all_settings_applies_default_options_resets_the_window_and_reports(
        self,
    ):
        events = []
        stored = Config()
        stored.grayscale_enabled = True
        controller = MenuController.__new__(MenuController)
        controller.window = SimpleNamespace(
            reset_workspace_state_to_defaults=lambda: events.append("window-reset")
        )
        controller.config_service = SimpleNamespace(
            update_app_options=lambda config: events.append(("update", config)),
            get_config_snapshot=lambda: stored,
        )
        result = controller._reset_all_settings()
        self.assertIs(result, stored)
        self.assertEqual(events[1], "window-reset")
        update_event, applied = events[0]
        self.assertEqual(update_event, "update")
        self.assertIsInstance(applied, Config)
        self.assertEqual(applied, Config())

    def _new_database_controller(self, backend, *, window=None, type_dialog_cls=None):
        events = []

        class TypeDialog:
            def __init__(self, icon_provider, parent=None):
                events.append(("type-init", icon_provider, parent))

            def exec(self):
                events.append("type-exec")
                return QtWidgets.QDialog.DialogCode.Accepted

            def selected_backend(self):
                return backend

            def cleanup(self):
                events.append("type-cleanup")

            def deleteLater(self):
                events.append("type-delete")

        class NameDialog:
            result = QtWidgets.QDialog.DialogCode.Accepted
            text = "Name"

            def __init__(self, parent):
                events.append(("name-init", parent))

            def setWindowTitle(self, title):
                events.append(("title", title))

            def setLabelText(self, text):
                events.append(("label", text))

            def setTextValue(self, text):
                events.append(("text", text))

            def setModal(self, modal):
                events.append(("modal", modal))

            def exec(self):
                events.append("name-exec")
                return self.result

            def textValue(self):
                return self.text

            def deleteLater(self):
                events.append("name-delete")

        controller = MenuController.__new__(MenuController)
        controller.ui_access_manager = _Access()
        controller.icon_provider = SimpleNamespace(
            set_window_icon=lambda dialog: events.append(
                ("icon", type(dialog).__name__)
            )
        )
        controller.window = window if window is not None else QtWidgets.QWidget()
        if isValid(controller.window):
            self.addCleanup(
                lambda: (
                    delete(controller.window) if isValid(controller.window) else None
                )
            )
        controller.handlers = SimpleNamespace(
            file_ops=SimpleNamespace(
                create_sql_database=lambda: events.append("create-sql")
            )
        )
        controller._create_new_database_fn = lambda name: (
            events.append(("create-access", name)) or "new.mdb"
        )
        controller._file_loading_service = SimpleNamespace(
            load_file=lambda path: (
                events.append(("load", path))
                or SimpleNamespace(success=True, file_path=path)
            )
        )
        controller._event_bus = SimpleNamespace(
            publish=lambda event, **payload: events.append(("publish", event, payload))
        )
        return controller, events, type_dialog_cls or TypeDialog, NameDialog

    def _run_new_database(self, controller, type_dialog, name_dialog, **patches):
        with (
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "NewDatabaseTypeDialog",
                type_dialog,
            ),
            mock.patch.object(QtWidgets, "QInputDialog", name_dialog),
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "remove_minimize_maximize",
                side_effect=lambda dialog: patches["events"].append("remove-buttons"),
            ),
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "delete_later_if_valid",
                side_effect=lambda dialog: (
                    dialog.deleteLater() if isValid(dialog) else None
                ),
            ),
        ):
            controller._new_database()

    def test_new_database_name_dialog_is_prepared_before_it_runs_and_disposed_after(
        self,
    ):
        controller, events, type_dialog, name_dialog = self._new_database_controller(
            DatabaseBackend.ACCESS
        )
        self._run_new_database(controller, type_dialog, name_dialog, events=events)
        self.assertEqual(
            events[:3],
            [
                ("type-init", controller.icon_provider, controller.window),
                "type-exec",
                "type-cleanup",
            ],
        )
        self.assertEqual(events[3], "type-delete")
        self.assertEqual(
            events[4:],
            [
                ("name-init", controller.window),
                ("title", "New Database"),
                ("label", "Database name:"),
                ("text", ""),
                ("modal", True),
                ("icon", "NameDialog"),
                "remove-buttons",
                "name-exec",
                ("create-access", "Name"),
                ("load", "new.mdb"),
                ("publish", AppEvents.FILE_OPENED, {"file_path": "new.mdb"}),
                "name-delete",
            ],
        )

    def test_new_database_type_dialog_is_cleaned_up_and_deleted_even_if_cleanup_fails(
        self,
    ):
        controller, events, type_dialog, name_dialog = self._new_database_controller(
            DatabaseBackend.ACCESS
        )

        class FailingCleanup(type_dialog):
            def cleanup(self):
                events.append("type-cleanup")
                raise RuntimeError("cleanup failed")

        with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
            self._run_new_database(
                controller, FailingCleanup, name_dialog, events=events
            )
        self.assertIn("type-cleanup", events)
        self.assertIn("type-delete", events)
        self.assertNotIn("create-sql", events)
        self.assertFalse(any(e == "name-exec" for e in events))

    def test_new_database_with_sql_backend_creates_through_file_operations_only(self):
        controller, events, type_dialog, name_dialog = self._new_database_controller(
            DatabaseBackend.SQL_SERVER
        )
        self._run_new_database(controller, type_dialog, name_dialog, events=events)
        self.assertIn("create-sql", events)
        self.assertEqual(events[-1], "create-sql")
        self.assertFalse(
            any(isinstance(e, tuple) and e[0] == "name-init" for e in events)
        )
        self.assertEqual(events.count("type-delete"), 1)

    def test_new_database_without_a_chosen_backend_stops_after_the_type_dialog(self):
        controller, events, type_dialog, name_dialog = self._new_database_controller(
            None
        )

        class NoChoice(type_dialog):
            def exec(self):
                events.append("type-exec")
                return QtWidgets.QDialog.DialogCode.Rejected

        class NoNameDialog(name_dialog):
            def __init__(self, parent):
                raise AssertionError("name dialog must not open without a backend")

        self._run_new_database(controller, NoChoice, NoNameDialog, events=events)
        self.assertNotIn("create-sql", events)
        self.assertEqual(events.count("type-delete"), 1)

    def test_new_database_accepted_type_dialog_without_backend_creates_nothing(self):
        controller, events, type_dialog, name_dialog = self._new_database_controller(
            None
        )

        class NoNameDialog(name_dialog):
            def __init__(self, parent):
                raise AssertionError("name dialog must not open without a backend")

        self._run_new_database(controller, type_dialog, NoNameDialog, events=events)
        self.assertNotIn("create-sql", events)
        self.assertFalse(
            any(isinstance(e, tuple) and e[0] == "create-access" for e in events)
        )

    def test_new_database_stops_when_the_window_dies_but_the_type_dialog_lives(self):
        window = QtWidgets.QWidget()
        controller, events, type_dialog, name_dialog = self._new_database_controller(
            DatabaseBackend.SQL_SERVER, window=window
        )

        class WindowKiller(type_dialog):
            def exec(self):
                events.append("type-exec")
                delete(window)
                return QtWidgets.QDialog.DialogCode.Accepted

        self._run_new_database(controller, WindowKiller, name_dialog, events=events)
        self.assertNotIn("create-sql", events)
        self.assertIn("type-delete", events)

    def test_new_database_stops_when_the_type_dialog_dies_but_the_window_lives(self):
        controller, events, type_dialog, name_dialog = self._new_database_controller(
            DatabaseBackend.SQL_SERVER
        )

        class SelfDestructing(QtWidgets.QDialog):
            def __init__(self, _icon_provider, parent=None):
                super().__init__(parent)

            def exec(self):
                events.append("type-exec")
                delete(self)
                return QtWidgets.QDialog.DialogCode.Accepted

            def selected_backend(self):
                raise AssertionError("a destroyed dialog must not be read")

            def cleanup(self):
                pass

        self._run_new_database(controller, SelfDestructing, name_dialog, events=events)
        self.assertNotIn("create-sql", events)

    def test_new_access_database_stops_when_the_window_dies_but_the_name_dialog_lives(
        self,
    ):
        window = QtWidgets.QWidget()
        controller, events, type_dialog, name_dialog = self._new_database_controller(
            DatabaseBackend.ACCESS, window=window
        )

        class WindowKiller(name_dialog):
            def exec(self):
                events.append("name-exec")
                delete(window)
                return QtWidgets.QDialog.DialogCode.Accepted

            def textValue(self):
                raise AssertionError("must not read after the window died")

        self._run_new_database(controller, type_dialog, WindowKiller, events=events)
        self.assertFalse(
            any(isinstance(e, tuple) and e[0] == "create-access" for e in events)
        )
        self.assertIn("name-delete", events)

    def test_new_access_database_stops_when_the_name_dialog_dies_but_the_window_lives(
        self,
    ):
        controller, events, type_dialog, name_dialog = self._new_database_controller(
            DatabaseBackend.ACCESS
        )

        class SelfDestructing(QtWidgets.QInputDialog):
            def exec(self):
                events.append("name-exec")
                delete(self)
                return QtWidgets.QDialog.DialogCode.Accepted

        with (
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "NewDatabaseTypeDialog",
                type_dialog,
            ),
            mock.patch.object(QtWidgets, "QInputDialog", SelfDestructing),
            mock.patch(
                "ost_visualizer.presentation.controllers.menu_controller."
                "remove_minimize_maximize"
            ),
        ):
            controller.icon_provider = SimpleNamespace(set_window_icon=lambda _d: None)
            controller._new_database()
        self.assertFalse(
            any(isinstance(e, tuple) and e[0] == "create-access" for e in events)
        )

    def test_new_access_database_with_a_blank_name_asks_for_a_generated_one(self):
        controller, events, type_dialog, name_dialog = self._new_database_controller(
            DatabaseBackend.ACCESS
        )
        name_dialog.text = "   "
        self._run_new_database(controller, type_dialog, name_dialog, events=events)
        self.assertIn(("create-access", None), events)
        name_dialog.text = "  Padded Name  "
        controller, events, type_dialog, name_dialog = self._new_database_controller(
            DatabaseBackend.ACCESS
        )
        name_dialog.text = "  Padded Name  "
        self._run_new_database(controller, type_dialog, name_dialog, events=events)
        self.assertIn(("create-access", "Padded Name"), events)

    def test_new_access_database_does_nothing_more_when_the_name_dialog_is_cancelled(
        self,
    ):
        controller, events, type_dialog, name_dialog = self._new_database_controller(
            DatabaseBackend.ACCESS
        )
        name_dialog.result = QtWidgets.QDialog.DialogCode.Rejected
        self._run_new_database(controller, type_dialog, name_dialog, events=events)
        self.assertFalse(
            any(isinstance(e, tuple) and e[0] == "create-access" for e in events)
        )
        self.assertEqual(events.count("name-delete"), 1)

    def test_new_access_database_reports_a_failed_creation(self):
        controller, events, type_dialog, name_dialog = self._new_database_controller(
            DatabaseBackend.ACCESS
        )
        controller._create_new_database_fn = lambda name: events.append(
            ("create-access", name)
        )
        with mock.patch(
            "ost_visualizer.presentation.controllers.menu_controller.show_critical"
        ) as critical:
            self._run_new_database(controller, type_dialog, name_dialog, events=events)
        critical.assert_called_once_with(
            controller.window,
            "New Database",
            "Failed to create database. Check logs for details.",
        )
        self.assertFalse(any(isinstance(e, tuple) and e[0] == "load" for e in events))

    def _new_folder_controller(self, file_path):
        calls = []
        controller = MenuController.__new__(MenuController)
        controller._resolve_project_tree_file_path = lambda: file_path
        controller.new_folder_in = lambda path: calls.append(path)
        return controller, calls

    def test_new_folder_command_needs_a_resolvable_database(self):
        controller, calls = self._new_folder_controller(None)
        controller._new_folder()
        self.assertEqual(calls, [])
        controller, calls = self._new_folder_controller("db.mdb")
        controller._new_folder()
        self.assertEqual(calls, ["db.mdb"])


class MenuControllerSecondPassResidualTests(unittest.TestCase):
    """Residual second-pass branches found by the mutation sweep."""

    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()

    def tearDown(self):
        self.app.processEvents()

    def test_every_state_refresh_re_syncs_the_checked_state_with_the_getters(self):
        harness = _RealMenuHarness(self)
        controller = harness.controller
        actions = controller._actions
        env = harness.env
        env.state.grayscale_enabled = False
        env.state.display_modes_synced = False
        env.state.display_mode_3d = Config.DISPLAY_MODE_ORIGINAL
        env.page.invert = True
        env.page.bitonal = True
        env.page.image_show_mode = 1
        env.tab_2d_visible = False
        env.tab_3d_visible = True
        env.toolbar_visibility = {"main_toolbar": False, "view_toolbar": True}
        controller.update_menu_states()
        self.assertEqual(
            {
                key: actions[key].isChecked()
                for key in (
                    "toggle_takeoff_grayscale",
                    "toggle_takeoff_display_modes_sync",
                    "toggle_page_invert",
                    "toggle_page_bitonal",
                    "show_original_image",
                    "show_overlay_image",
                    "toggle_2d_tab",
                    "toggle_3d_tab",
                    "toggle_main_toolbar",
                    "toggle_view_toolbar",
                    "toggle_plan_tools_toolbar",
                )
            },
            {
                "toggle_takeoff_grayscale": False,
                "toggle_takeoff_display_modes_sync": False,
                "toggle_page_invert": True,
                "toggle_page_bitonal": True,
                "show_original_image": False,
                "show_overlay_image": True,
                "toggle_2d_tab": False,
                "toggle_3d_tab": True,
                "toggle_main_toolbar": False,
                "toggle_view_toolbar": True,
                "toggle_plan_tools_toolbar": True,
            },
        )
        checked_modes = [
            action.data()
            for action in controller._variable_actions["display_mode_3d"]
            if action.isChecked()
        ]
        self.assertEqual(checked_modes, [Config.DISPLAY_MODE_ORIGINAL])

    def test_tab_visibility_commands_resync_the_check_even_when_it_was_unchecked_first(
        self,
    ):
        harness = _RealMenuHarness(self)
        controller = harness.controller
        harness.env.tab_2d_visible = False
        harness.env.tab_3d_visible = False
        controller._sync_variable_actions()
        self.assertFalse(controller._actions["toggle_2d_tab"].isChecked())
        controller._set_2d_tab_visible(True)
        self.assertTrue(controller._actions["toggle_2d_tab"].isChecked())
        self.assertFalse(controller._actions["toggle_3d_tab"].isChecked())
        controller._set_3d_tab_visible(True)
        self.assertTrue(controller._actions["toggle_3d_tab"].isChecked())

    def test_html_export_options_stay_disabled_when_no_html_format_is_available(self):
        bid_ref = BidRef("db.mdb", "bid-1")
        controller = _controller(_UiState(bid_ref), _ProjectData(bid_ref))
        controller._export_formats = []
        controller._actions = {
            key: action
            for key, action in controller._actions.items()
            if key != "export_as_html"
        }
        controller.update_menu_states()
        self.assertFalse(controller._menus["html export options"].isEnabled())
        self.assertTrue(controller._menus["export"].isEnabled())

    def test_new_folder_schedules_the_rename_with_the_text_of_the_created_uid(self):
        renames = []
        controller = MenuController.__new__(MenuController)
        controller.window = SimpleNamespace(
            project_view=SimpleNamespace(
                schedule_rename=lambda uid, path: renames.append((uid, path))
            )
        )
        controller.ui_access_manager = SimpleNamespace(
            can_create_project=lambda _path: True
        )
        controller._deferred_persistence = SimpleNamespace(
            flush_for_file=lambda _path: True
        )
        controller._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _path: False,
            create_project_result=lambda _path, _name: WriteReloadResult(
                7, write_success=True, reload_success=True
            ),
        )
        controller.new_folder_in("db.mdb")
        self.assertEqual(renames, [("7", "db.mdb")])
        self.assertIsInstance(renames[0][0], str)


class MenuControllerSecondPassSweepTests(unittest.TestCase):
    """Second pass 4 (sp4-t3): contracts the earlier tests could not observe
    (empty selection with a permissive project-data fake, shared toolbar actions,
    project tree creation guard against the real permission matrix)."""

    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()

    def tearDown(self):
        self.app.processEvents()

    def test_export_stays_disabled_for_an_empty_selection_whatever_the_project_data_says(
        self,
    ):
        class PermissiveProjectData(_ProjectData):
            def has_takeoffs_for_pages(self, page_uids):
                return True

        bid_ref = BidRef("db.mdb", "bid-1")
        project_data = PermissiveProjectData(bid_ref)
        project_data.selected_page_uids = []
        controller = _controller(_UiState(bid_ref), project_data)
        self.assertIs(controller._should_enable_export(), False)
        controller.update_menu_states()
        self.assertFalse(controller._actions["export_as_html"].isEnabled())
        self.assertTrue(controller._actions["export_as_ost"].isEnabled())
        self.assertTrue(controller._actions["export_summary_csv"].isEnabled())
        project_data.selected_page_uids = ["page-1"]
        self.assertIs(controller._should_enable_export(), True)
        controller.update_menu_states()
        self.assertTrue(controller._actions["export_as_html"].isEnabled())

    def test_menu_actions_for_shared_commands_are_the_shared_toolbar_actions(self):
        harness = _RealMenuHarness(self)
        controller = harness.controller
        self.assertIn("zoom_in", harness.shared_actions)
        self.assertIn("dimension_tool", harness.shared_actions)
        for key, shared in harness.shared_actions.items():
            with self.subTest(command=key):
                self.assertIs(controller._actions[key], shared)
        shortcut = QtGui.QKeySequence("Ctrl+Alt+Z")
        shared_zoom = harness.shared_actions["zoom_in"]
        shared_zoom.setShortcut(shortcut)
        harness.env.takeoff_active = False
        controller.update_menu_states()
        self.assertFalse(shared_zoom.isEnabled())
        harness.env.takeoff_active = True
        controller.update_menu_states()
        self.assertTrue(shared_zoom.isEnabled())
        self.assertEqual(shared_zoom.shortcut(), shortcut)
        self.assertEqual(controller._actions["zoom_in"].shortcut(), shortcut)

    def test_project_tree_creation_guard_follows_the_real_permission_matrix(self):
        def ost_active(harness):
            harness.monitor.active = True

        def locked_bid(harness):
            harness.project_data.locked = True

        def read_only(harness):
            harness.capabilities.database_editable = False

        def no_license(harness):
            harness.license.valid = False

        def area_placement(harness):
            harness.access.set_area_placement_active(True, surface_id="main-plan")

        scenarios = (
            ("baseline", lambda harness: None, True),
            ("locked active Bid", locked_bid, True),
            ("OST active", ost_active, False),
            ("read-only database", read_only, False),
            ("no licence", no_license, False),
            ("area placement in progress", area_placement, False),
        )
        for label, setup, allowed in scenarios:
            with self.subTest(scenario=label):
                harness = _RealMenuHarness(self)
                created = []
                controller = harness.controller
                controller._deferred_persistence = SimpleNamespace(
                    flush_for_file=lambda _path: True
                )
                controller._project_write_service = SimpleNamespace(
                    uses_sql_collaboration_mutations=lambda _path: False,
                    create_project_result=lambda path, name: (
                        created.append((path, name))
                        or WriteReloadResult(
                            "project-new", write_success=True, reload_success=True
                        )
                    ),
                )
                setup(harness)
                harness.access.refresh()
                controller.update_menu_states()
                self.assertEqual(controller._actions["new_folder"].isEnabled(), allowed)
                self.assertEqual(
                    controller._actions["new_project"].isEnabled(), allowed
                )
                controller.new_folder_in("db.mdb")
                self.assertEqual(
                    created, [("db.mdb", "New Project")] if allowed else []
                )
                self.assertEqual(
                    [
                        entry
                        for entry in harness.calls.log
                        if entry[0] == "window.project_view.schedule_rename"
                    ],
                    (
                        [
                            (
                                "window.project_view.schedule_rename",
                                ("project-new", "db.mdb"),
                                {},
                            )
                        ]
                        if allowed
                        else []
                    ),
                )
