from tests.presentation.dialogs.options.preference_support import (
    _app as _preferences_support__app,
)
from tests.helpers.workspace_state import make_workspace_state_model
from shiboken6 import delete
from PySide6 import QtCore, QtGui, QtWidgets
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from unittest import mock
from pathlib import Path
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
        self.assertFalse(controller._should_enable_import())

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
        with patch(
            "ost_visualizer.presentation.controllers.menu_controller."
            "NewDatabaseTypeDialog",
            _TypeDialog,
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
        with patch(
            "ost_visualizer.presentation.controllers.menu_controller."
            "NewDatabaseTypeDialog",
            _RejectedTypeDialog,
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
