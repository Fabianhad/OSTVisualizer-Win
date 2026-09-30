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
    def __init__(self, allowed=True):
        self.allowed = allowed

    def is_allowed(self, _feature: Feature) -> bool:
        return self.allowed


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
                    save_job_statuses_async_fn=save_job_statuses_async_fn,
                    save_employees_async_fn=save_employees_async_fn,
                    save_pay_classes_async_fn=save_pay_classes_async_fn,
                    save_cover_sheet_async_fn=save_cover_sheet_async_fn,
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
        controller._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _file_path: False
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

    def test_sql_new_project_nested_and_outer_saves_transfer_dialog_ownership(self):
        captured = {}
        transferred = []

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
                _file_path,
                _title,
                _queue_fn,
                _changes,
                completed,
                _result_family,
                *,
                edit_lease_handle,
            ):
                transferred.append(("master", edit_lease_handle))
                completed(True, {})
                return True

            @staticmethod
            def create_bid_async(
                _file_path,
                _project_uid,
                _updates,
                completed,
                *,
                edit_lease_handle,
            ):
                transferred.append(("bid", edit_lease_handle))
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
            queue_job_statuses_save=object(),
            queue_employees_save=object(),
            queue_pay_classes_save=object(),
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
            self.assertTrue(
                dialog is not None
                and captured["save_job_statuses_async_fn"](
                    {"updated": []}, lambda _success, _mapping: None
                )
            )
            self.assertTrue(
                captured["save_cover_sheet_async_fn"](
                    {"job_name": "New"}, lambda _success: None
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
            [("master", "handle-1"), ("bid", "handle-2")],
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
        controller._tool_action_enabled_state = {}
        controller.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(
                refresh_backout_action=lambda: explicit_refresh_calls.append(1)
            )
        )
        MenuController._sync_tool_action_states(controller, True)
        self.assertEqual(explicit_refresh_calls, [1])


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

    def test_bid_exports_enable_from_matching_selected_loaded_bid(self):
        bid_ref = BidRef("db.mdb", "bid-1")
        controller = _controller(_UiState(bid_ref), _ProjectData(bid_ref))
        controller.update_menu_states()
        self.assertTrue(controller._actions["export_as_html"].isEnabled())
        self.assertTrue(controller._actions["export_as_pdf"].isEnabled())
        self.assertTrue(controller._actions["export_summary_csv"].isEnabled())
        self.assertTrue(controller._actions["export_as_ost"].isEnabled())
        self.assertTrue(controller._actions["export_as_osp"].isEnabled())
        self.assertTrue(controller._menus["export"].isEnabled())

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
        controller._event_bus = SimpleNamespace(publish=lambda *_args, **_kwargs: None)
        with patch(
            "ost_visualizer.presentation.controllers.menu_controller."
            "NewDatabaseTypeDialog",
            _TypeDialog,
        ), patch.object(QtWidgets, "QInputDialog", _AccessNameDialog), patch(
            "ost_visualizer.presentation.controllers.menu_controller."
            "remove_minimize_maximize"
        ):
            MenuController._new_database(controller)
        self.assertEqual(created_names, ["Access Database"])
        self.assertEqual(loaded_paths, ["access.mdb"])
        self.assertTrue(_AccessNameDialog.instances[0].deleted)
        _AccessNameDialog.result = QtWidgets.QDialog.DialogCode.Rejected
        with patch(
            "ost_visualizer.presentation.controllers.menu_controller."
            "NewDatabaseTypeDialog",
            _TypeDialog,
        ), patch.object(QtWidgets, "QInputDialog", _AccessNameDialog), patch(
            "ost_visualizer.presentation.controllers.menu_controller."
            "remove_minimize_maximize"
        ):
            MenuController._new_database(controller)
        self.assertEqual(created_names, ["Access Database"])
        self.assertTrue(_AccessNameDialog.instances[1].deleted)
        original_icon_provider = controller.icon_provider
        controller.icon_provider = SimpleNamespace(
            set_window_icon=lambda _dialog: (_ for _ in ()).throw(
                RuntimeError("icon setup failed")
            )
        )
        _AccessNameDialog.result = QtWidgets.QDialog.DialogCode.Accepted
        with patch(
            "ost_visualizer.presentation.controllers.menu_controller."
            "NewDatabaseTypeDialog",
            _TypeDialog,
        ), patch.object(QtWidgets, "QInputDialog", _AccessNameDialog):
            with self.assertRaisesRegex(RuntimeError, "icon setup failed"):
                MenuController._new_database(controller)
        self.assertTrue(_AccessNameDialog.instances[2].deleted)
        controller.icon_provider = original_icon_provider

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
        with patch(
            "ost_visualizer.presentation.controllers.menu_controller."
            "NewDatabaseTypeDialog",
            _AccessTypeDialog,
        ), patch.object(QtWidgets, "QInputDialog", _DestroyingNameDialog):
            MenuController._new_database(controller)


class BidLockPermissionTests(unittest.TestCase):
    def test_shared_menu_callback_respects_enabled_state(self):
        controller = MenuController.__new__(MenuController)
        calls = []
        controller._get_menu_callbacks = lambda: {"blocked": lambda: calls.append(1)}
        controller.is_context_command_enabled = lambda _key: False
        MenuController.trigger_menu_callback(controller, "blocked")
        self.assertEqual(calls, [])

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
        from ost_visualizer.presentation.controllers import menu_controller

        old_warning = menu_controller.show_warning
        old_critical = menu_controller.show_critical
        menu_controller.show_warning = lambda *_args: warnings.append(_args)
        menu_controller.show_critical = lambda *_args: criticals.append(_args)
        try:
            MenuController._new_folder(controller)
        finally:
            menu_controller.show_warning = old_warning
            menu_controller.show_critical = old_critical
        self.assertEqual(len(warnings), 1)
        self.assertIn(
            "created, but the project tree could not be refreshed", warnings[0][2]
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
        controller._project_write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _database_id: False,
            create_project_result=lambda _path, _name: WriteReloadResult(
                "project-new", write_success=True, reload_success=True
            ),
        )
        MenuController._new_folder(controller)
        self.assertEqual(renames, [("project-new", "db.mdb")])
