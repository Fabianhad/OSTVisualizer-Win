import os
import logging
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_RECT,
    ANNOTATION_TYPE_TEXT,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.coordinators.sidebar_coordinator import (
    SidebarCoordinator,
)
from ost_visualizer.presentation.controllers.menu_controller import MenuController
from ost_visualizer.presentation.dialogs.cover_sheet.context import CoverSheetContext
from ost_visualizer.presentation.config import TAB_INDEX_TAKEOFF
from ost_visualizer.presentation.handlers.file_operation_handler import (
    FileOperationHandler,
)
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.managers.deferred_persistence_manager import (
    DeferredPersistenceManager,
)
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
)


class FakeProjectWriteService:
    def __init__(self):
        self.calls = []
        self.fail_methods = set()
        self.expected_deferred_write_blocked = False

    def is_expected_deferred_write_blocked(self, db_path):
        return self.expected_deferred_write_blocked

    def save_page_view_state(self, db_path, page_uid, zoom_fac, current_x, current_y):
        self.calls.append(
            ("page_view_state", db_path, page_uid, zoom_fac, current_x, current_y)
        )
        return "save_page_view_state" not in self.fail_methods

    def save_bid_selected_page(self, db_path, bid_uid, page_uid):
        self.calls.append(("bid_selected_page", db_path, bid_uid, page_uid))
        return "save_bid_selected_page" not in self.fail_methods

    def update_layer_show(
        self,
        db_path,
        layer_uid,
        show,
        publish_database_refreshed_after_write=True,
    ):
        self.calls.append(
            (
                "layer_show",
                db_path,
                layer_uid,
                show,
                publish_database_refreshed_after_write,
            )
        )
        return "update_layer_show" not in self.fail_methods

    def save_page_show_mode(
        self,
        db_path,
        page_uid,
        show_mode,
        publish_database_refreshed_after_write=True,
    ):
        self.calls.append(
            (
                "page_show_mode",
                db_path,
                page_uid,
                show_mode,
                publish_database_refreshed_after_write,
            )
        )
        return "save_page_show_mode" not in self.fail_methods

    def save_page_area(
        self,
        db_path,
        page_uid,
        area_uid,
        publish_database_refreshed_after_write=True,
    ):
        self.calls.append(
            (
                "page_area",
                db_path,
                page_uid,
                area_uid,
                publish_database_refreshed_after_write,
            )
        )
        return "save_page_area" not in self.fail_methods

    def save_page_invert(self, db_path, page_uid, invert):
        self.calls.append(("page_invert", db_path, page_uid, invert))
        return "save_page_invert" not in self.fail_methods

    def save_page_bitonal(self, db_path, page_uid, bitonal):
        self.calls.append(("page_bitonal", db_path, page_uid, bitonal))
        return "save_page_bitonal" not in self.fail_methods

    def save_page_overlay_rect_result(
        self,
        db_path,
        page_uid,
        overlay_rect,
        publish_database_refreshed_after_write=True,
    ):
        self.calls.append(
            (
                "page_overlay_rect",
                db_path,
                page_uid,
                overlay_rect,
                publish_database_refreshed_after_write,
            )
        )
        success = "save_page_overlay_rect_result" not in self.fail_methods
        return SimpleNamespace(write_success=success)


class DeferredPersistenceManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.service = FakeProjectWriteService()
        self.logger = logging.getLogger("tests.deferred_persistence_manager")
        self.logger.disabled = True
        self.manager = DeferredPersistenceManager(self.service, logger_=self.logger)

    def tearDown(self):
        self.manager.cleanup()
        self.logger.disabled = False

    def test_queues_without_immediate_write(self):
        self.manager.schedule_page_view_state("a.mdb", "p1", 2.0, 10.0, 20.0)
        self.assertEqual(self.service.calls, [])
        self.assertEqual(self.manager.pending_count, 1)

    def test_coalesces_repeated_writes_by_key_and_last_write_wins(self):
        self.manager.schedule_page_view_state("a.mdb", "p1", 2.0, 10.0, 20.0)
        self.manager.schedule_page_view_state("a.mdb", "p1", 4.0, 30.0, 40.0)
        self.assertTrue(self.manager.flush())
        self.assertEqual(
            self.service.calls,
            [("page_view_state", "a.mdb", "p1", 4.0, 30.0, 40.0)],
        )
        self.assertEqual(self.manager.pending_count, 0)

    def test_flush_executes_all_successful_writes_and_clears_queue(self):
        self.manager.schedule_bid_selected_page("a.mdb", "b1", "p2")
        self.manager.schedule_page_invert("a.mdb", "p2", True)
        self.assertTrue(self.manager.flush())
        self.assertEqual(
            self.service.calls,
            [
                ("bid_selected_page", "a.mdb", "b1", "p2"),
                ("page_invert", "a.mdb", "p2", True),
            ],
        )
        self.assertEqual(self.manager.pending_count, 0)

    def test_failed_write_remains_pending_for_retry(self):
        self.service.fail_methods.add("save_page_bitonal")
        self.manager.schedule_page_bitonal("a.mdb", "p1", True)
        self.assertFalse(self.manager.flush())
        self.assertEqual(self.manager.pending_count, 1)
        self.service.fail_methods.clear()
        self.assertTrue(self.manager.flush())
        self.assertEqual(self.manager.pending_count, 0)
        self.assertEqual(
            self.service.calls,
            [
                ("page_bitonal", "a.mdb", "p1", True),
                ("page_bitonal", "a.mdb", "p1", True),
            ],
        )

    def test_expected_blocked_visual_write_is_skipped_without_warning(self):
        self.service.expected_deferred_write_blocked = True
        logger = logging.getLogger("tests.deferred_persistence_expected_block")
        manager = DeferredPersistenceManager(self.service, logger_=logger)
        self.addCleanup(manager.cleanup)
        manager.schedule_page_view_state("a.mdb", "p1", 2.0, 10.0, 20.0)
        with self.assertNoLogs(logger, level="WARNING"):
            self.assertTrue(manager.flush())
        self.assertEqual(manager.pending_count, 0)
        self.assertEqual(self.service.calls, [])

    def test_expected_blocked_visual_write_does_not_block_cleanup(self):
        self.service.expected_deferred_write_blocked = True
        manager = DeferredPersistenceManager(
            self.service, logger_=logging.getLogger(__name__)
        )
        manager.schedule_page_view_state("a.mdb", "p1", 2.0, 10.0, 20.0)
        self.assertTrue(manager.cleanup())
        self.assertEqual(manager.pending_count, 0)
        self.assertEqual(self.service.calls, [])

    def test_expected_block_does_not_skip_critical_deferred_write(self):
        self.service.expected_deferred_write_blocked = True
        logger = logging.getLogger("tests.deferred_persistence_critical_block")
        manager = DeferredPersistenceManager(self.service, logger_=logger)
        self.addCleanup(manager.cleanup)
        manager.schedule(
            "critical_data",
            ("critical_data", "a.mdb"),
            "critical data write",
            lambda: False,
        )
        with self.assertLogs(logger, level="WARNING"):
            self.assertFalse(manager.flush())
        self.assertEqual(manager.pending_count, 1)

    def test_cancel_for_file_removes_only_matching_file_writes(self):
        self.manager.schedule_layer_show("a.mdb", "l1", False)
        self.manager.schedule_page_show_mode("b.mdb", "p1", 2)
        self.manager.cancel_for_file("a.mdb")
        self.assertEqual(self.manager.pending_count, 1)
        self.assertTrue(self.manager.flush())
        self.assertEqual(
            self.service.calls,
            [("page_show_mode", "b.mdb", "p1", 2, False)],
        )

    def test_cleanup_flushes_pending_writes(self):
        self.manager.schedule_page_overlay_rect("a.mdb", "p1", (1, 2.5, 3, 4.25))
        self.assertTrue(self.manager.cleanup())
        self.assertEqual(
            self.service.calls,
            [
                (
                    "page_overlay_rect",
                    "a.mdb",
                    "p1",
                    (1.0, 2.5, 3.0, 4.25),
                    False,
                )
            ],
        )
        self.assertEqual(self.manager.pending_count, 0)

    def test_cleanup_flushes_all_pending_deferred_operation_kinds(self):
        self.manager.schedule_page_view_state("a.mdb", "p1", 2.0, 10.0, 20.0)
        self.manager.schedule_bid_selected_page("a.mdb", "b1", "p1")
        self.manager.schedule_layer_show("a.mdb", "l1", False)
        self.manager.schedule_page_show_mode("a.mdb", "p1", 2)
        self.manager.schedule_page_area_selection("a.mdb", "p1", "area-1")
        self.manager.schedule_page_invert("a.mdb", "p1", True)
        self.manager.schedule_page_bitonal("a.mdb", "p1", True)
        self.manager.schedule_page_overlay_rect("a.mdb", "p1", (1, 2, 3, 4))
        self.assertTrue(self.manager.cleanup())
        self.assertEqual(
            self.service.calls,
            [
                ("page_view_state", "a.mdb", "p1", 2.0, 10.0, 20.0),
                ("bid_selected_page", "a.mdb", "b1", "p1"),
                ("layer_show", "a.mdb", "l1", False, False),
                ("page_show_mode", "a.mdb", "p1", 2, False),
                ("page_area", "a.mdb", "p1", "area-1", False),
                ("page_invert", "a.mdb", "p1", True),
                ("page_bitonal", "a.mdb", "p1", True),
                ("page_overlay_rect", "a.mdb", "p1", (1.0, 2.0, 3.0, 4.0), False),
            ],
        )
        self.assertEqual(self.manager.pending_count, 0)

    def test_cleanup_failure_keeps_pending_write_retryable(self):
        self.service.fail_methods.add("update_layer_show")
        self.manager.schedule_layer_show("a.mdb", "l1", False)
        self.assertFalse(self.manager.cleanup())
        self.assertEqual(self.manager.pending_count, 1)
        self.service.fail_methods.clear()
        self.assertTrue(self.manager.cleanup())
        self.assertEqual(self.manager.pending_count, 0)
        self.assertEqual(
            self.service.calls,
            [
                ("layer_show", "a.mdb", "l1", False, False),
                ("layer_show", "a.mdb", "l1", False, False),
            ],
        )

    def test_cleanup_ignores_later_schedules(self):
        self.assertTrue(self.manager.cleanup())
        self.manager.schedule_page_invert("a.mdb", "p1", True)
        self.assertEqual(self.manager.pending_count, 0)
        self.assertEqual(self.service.calls, [])

    def test_deferred_visual_writes_do_not_request_full_reload(self):
        self.manager.schedule_layer_show("a.mdb", "l1", True)
        self.manager.schedule_page_show_mode("a.mdb", "p1", 1)
        self.manager.schedule_page_overlay_rect("a.mdb", "p1", (0, 0, 10, 10))
        self.assertTrue(self.manager.flush())
        self.assertEqual(
            self.service.calls,
            [
                ("layer_show", "a.mdb", "l1", True, False),
                ("page_show_mode", "a.mdb", "p1", 1, False),
                (
                    "page_overlay_rect",
                    "a.mdb",
                    "p1",
                    (0.0, 0.0, 10.0, 10.0),
                    False,
                ),
            ],
        )

    def test_page_area_selection_coalesces_and_does_not_request_full_reload(self):
        self.manager.schedule_page_area_selection("a.mdb", "p1", "1")
        self.manager.schedule_page_area_selection("a.mdb", "p1", "2")
        self.assertEqual(self.manager.pending_count, 1)
        self.assertTrue(self.manager.flush())
        self.assertEqual(
            self.service.calls,
            [("page_area", "a.mdb", "p1", "2", False)],
        )

    def test_page_area_selection_retry_clears_after_write_succeeds(self):
        self.service.fail_methods.add("save_page_area")
        self.manager.schedule_page_area_selection("a.mdb", "452", "95")
        self.assertFalse(self.manager.flush())
        self.assertEqual(self.manager.pending_count, 1)
        self.service.fail_methods.clear()
        self.assertTrue(self.manager.flush())
        self.assertEqual(self.manager.pending_count, 0)
        self.assertEqual(
            self.service.calls,
            [
                ("page_area", "a.mdb", "452", "95", False),
                ("page_area", "a.mdb", "452", "95", False),
            ],
        )


class RecordingDeferredPersistence:
    def __init__(self):
        self.layer_calls = []
        self.page_view_calls = []
        self.selected_page_calls = []
        self.page_area_calls = []
        self.page_show_mode_calls = []
        self.flush_calls = []
        self.cancel_calls = []
        self.flush_all_calls = 0
        self.flush_result = True

    def schedule_layer_show(self, db_path, layer_uid, show):
        self.layer_calls.append((db_path, layer_uid, show))

    def schedule_page_view_state(
        self, db_path, page_uid, zoom_fac, current_x, current_y
    ):
        self.page_view_calls.append((db_path, page_uid, zoom_fac, current_x, current_y))

    def schedule_bid_selected_page(self, db_path, bid_uid, page_uid):
        self.selected_page_calls.append((db_path, bid_uid, page_uid))

    def schedule_page_area_selection(self, db_path, page_uid, area_uid):
        self.page_area_calls.append((db_path, page_uid, area_uid))

    def schedule_page_show_mode(self, db_path, page_uid, show_mode):
        self.page_show_mode_calls.append((db_path, page_uid, show_mode))

    def flush(self):
        self.flush_all_calls += 1
        return self.flush_result

    def flush_for_file(self, db_path):
        self.flush_calls.append(db_path)
        return self.flush_result

    def cancel_for_file(self, db_path):
        self.cancel_calls.append(db_path)


class FakeCloseEvent:
    def __init__(self):
        self.ignored = False

    def ignore(self):
        self.ignored = True


class DeferredPersistenceShutdownTests(unittest.TestCase):
    def test_app_close_flushes_current_page_state_and_cleans_deferred_manager(self):
        calls = []
        window = MainWindow.__new__(MainWindow)
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(
                flush_current_page_state=lambda: calls.append("flush_state") or True
            )
        )
        window._deferred_persistence_manager = SimpleNamespace(
            cleanup=lambda: calls.append("cleanup") or True
        )
        self.assertTrue(MainWindow._flush_deferred_persistence_before_close(window))
        self.assertEqual(calls, ["flush_state", "cleanup"])

    def test_app_close_does_not_cleanup_when_current_page_flush_fails(self):
        calls = []
        window = MainWindow.__new__(MainWindow)
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(
                flush_current_page_state=lambda: calls.append("flush_state") or False
            )
        )
        window._deferred_persistence_manager = SimpleNamespace(
            cleanup=lambda: calls.append("cleanup") or True
        )
        self.assertFalse(MainWindow._flush_deferred_persistence_before_close(window))
        self.assertEqual(calls, ["flush_state"])

    def test_app_close_rejects_close_when_deferred_cleanup_fails(self):
        window = MainWindow.__new__(MainWindow)
        window._flush_deferred_persistence_before_close = lambda: False
        event = FakeCloseEvent()
        MainWindow.closeEvent(window, event)
        self.assertTrue(event.ignored)

    def test_file_exit_uses_window_close_path(self):
        close_calls = []
        controller = MenuController.__new__(MenuController)
        controller.window = SimpleNamespace(close=lambda: close_calls.append("close"))
        MenuController._on_quit(controller)
        self.assertEqual(close_calls, ["close"])

    def test_project_unload_flushes_pending_writes_before_unload(self):
        deferred = RecordingDeferredPersistence()
        unload_calls = []
        updates = []
        entries = [SimpleNamespace(normalized_path="a.mdb", is_checked=True)]
        handler = FileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=None,
            file_state_model=SimpleNamespace(
                file_entries=entries,
                update_entries=lambda next_entries: updates.append(next_entries),
            ),
            cleanup_deleted_files_use_case=None,
            file_loading_service=None,
            working_directory_service=None,
            unload_file_fn=lambda file_path: unload_calls.append(file_path) or True,
            deferred_persistence_manager=deferred,
            ui_state_manager=SimpleNamespace(selected_file_path="a.mdb"),
        )
        handler.unload_file()
        self.assertEqual(deferred.flush_calls, ["a.mdb"])
        self.assertEqual(unload_calls, ["a.mdb"])
        self.assertEqual(deferred.cancel_calls, ["a.mdb"])
        self.assertEqual(len(updates), 1)

    def test_project_unload_stops_when_deferred_flush_fails(self):
        deferred = RecordingDeferredPersistence()
        deferred.flush_result = False
        unload_calls = []
        handler = FileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=None,
            file_state_model=SimpleNamespace(
                file_entries=[],
                update_entries=lambda _: None,
            ),
            cleanup_deleted_files_use_case=None,
            file_loading_service=None,
            working_directory_service=None,
            unload_file_fn=lambda file_path: unload_calls.append(file_path) or True,
            deferred_persistence_manager=deferred,
            ui_state_manager=SimpleNamespace(selected_file_path="a.mdb"),
        )
        handler.unload_file()
        self.assertEqual(deferred.flush_calls, ["a.mdb"])
        self.assertEqual(unload_calls, [])


class RecordingPlanView:
    def __init__(self):
        self.current_page_uid = "p1"
        self.cursor_mode = "select"
        self.annotation_place_type = None
        self.place_condition_uid = None
        self.image_visibility_pages = []
        self.layer_visibility_calls = []
        self.all_layer_visibility_calls = []
        self.cursor_modes = []
        self.annotation_placements = []

    def apply_page_image_layer_visibility(self, page):
        self.image_visibility_pages.append(page.uid)
        return True

    def apply_layer_visibility(self, layer_uid, show, conditions):
        self.layer_visibility_calls.append((layer_uid, show, conditions))
        return True

    def apply_all_layer_visibility(self, show, conditions):
        self.all_layer_visibility_calls.append((show, conditions))
        return True

    def reset_ctrl_held(self):
        pass

    def set_cursor_mode(self, mode):
        self.cursor_mode = mode
        self.cursor_modes.append(mode)
        if mode != "place":
            self.place_condition_uid = None
        if mode != "annotation_place":
            self.annotation_place_type = None

    def activate_annotation_placement(self, annotation_type):
        self.cursor_mode = "annotation_place"
        self.annotation_place_type = annotation_type
        self.annotation_placements.append(annotation_type)
        return True


class FakeIndexWidget:
    def __init__(self, index):
        self.index = index

    def currentIndex(self):
        return self.index


class DeferredPersistenceCoordinatorTests(unittest.TestCase):
    def _install_hidden_2d_mesh_state(self, coordinator):
        mesh_refresh_calls = []
        coordinator._tab_widget = FakeIndexWidget(TAB_INDEX_TAKEOFF)
        coordinator._view_stack = FakeIndexWidget(1)
        coordinator._mesh_window = None
        coordinator.opengl_viewer = None
        coordinator._mesh_scene_dirty = False
        coordinator._dirty_mesh_page_uids = set()
        coordinator._pending_dirty_mesh_refresh = False
        coordinator.visualization_service = SimpleNamespace(
            refresh_mesh_view=lambda page_uids: mesh_refresh_calls.append(
                list(page_uids)
            )
        )
        coordinator.mesh_refresh_calls = mesh_refresh_calls
        return mesh_refresh_calls

    def _make_view_state_coordinator(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("a.mdb", "bid-1"),
            active_page_uid="p1",
        )
        pages = {
            "p1": Page(uid="p1", name="P1"),
            "p2": Page(uid="p2", name="P2"),
        }
        coordinator.project_data = SimpleNamespace(
            get_page=lambda page_uid: pages.get(page_uid),
        )
        coordinator.plan_view = SimpleNamespace(
            current_page_uid="p1",
            is_view_state_stable=True,
            get_view_state=lambda: (2.5, 10.0, 20.0),
        )
        coordinator._deferred_persistence = RecordingDeferredPersistence()
        coordinator._nav = SimpleNamespace(is_refreshing=False)
        return coordinator, pages

    def test_plan_view_state_change_updates_model_and_defers_write(self):
        coordinator, pages = self._make_view_state_coordinator()
        direct_writes = []
        coordinator._project_write_service = SimpleNamespace(
            save_page_view_state=lambda *_args: direct_writes.append(_args)
        )
        coordinator._on_plan_view_state_changed("p1", 3.0, 30.0, 40.0)
        self.assertEqual(pages["p1"].zoom_fac, 3.0)
        self.assertEqual(pages["p1"].current_x, 30.0)
        self.assertEqual(pages["p1"].current_y, 40.0)
        self.assertEqual(
            coordinator._deferred_persistence.page_view_calls,
            [("a.mdb", "p1", 3.0, 30.0, 40.0)],
        )
        self.assertEqual(direct_writes, [])

    def test_reset_or_current_state_capture_defers_page_view_persistence(self):
        coordinator, pages = self._make_view_state_coordinator()
        coordinator._save_current_page_view_state()
        self.assertEqual(pages["p1"].zoom_fac, 2.5)
        self.assertEqual(
            coordinator._deferred_persistence.page_view_calls,
            [("a.mdb", "p1", 2.5, 10.0, 20.0)],
        )

    def test_active_page_switch_defers_selected_page_and_outgoing_view_state(self):
        coordinator, _pages = self._make_view_state_coordinator()
        coordinator._update_page_settings_bar = lambda _page_uid: None
        coordinator._sync_overlay_display_mode = lambda _page_uid: None
        coordinator._update_plan_view = lambda _page_uid: None
        coordinator._sidebar = SimpleNamespace(
            update_conditions_quantities=lambda: None
        )
        coordinator._placement = SimpleNamespace(is_active=False)
        coordinator._update_page_info_status = lambda: None
        coordinator._update_export_menu_state = lambda: None
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        coordinator.handle_active_page_changed("p2")
        self.assertEqual(
            coordinator._deferred_persistence.page_view_calls,
            [("a.mdb", "p1", 2.5, 10.0, 20.0)],
        )
        self.assertEqual(
            coordinator._deferred_persistence.selected_page_calls,
            [("a.mdb", "bid-1", "p2")],
        )
        self.assertEqual(coordinator.ui_state_manager.active_page_uid, "p2")

    def test_active_page_switch_recovers_stale_placement_cursor_mismatch(self):
        coordinator, _pages = self._make_view_state_coordinator()
        coordinator.plan_view.cursor_mode = "rotate"
        coordinator._update_page_settings_bar = lambda _page_uid: None
        coordinator._sync_overlay_display_mode = lambda _page_uid: None
        coordinator._update_plan_view = lambda _page_uid: None
        coordinator._sidebar = SimpleNamespace(
            update_conditions_quantities=lambda: None
        )
        force_exit_calls = []
        coordinator._placement = SimpleNamespace(
            is_active=True,
            force_exit=lambda: force_exit_calls.append("force_exit"),
        )
        coordinator._update_page_info_status = lambda: None
        coordinator._update_export_menu_state = lambda: None
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        with self.assertLogs(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator",
            level="WARNING",
        ) as logs:
            coordinator.handle_active_page_changed("p2")
        self.assertEqual(force_exit_calls, ["force_exit"])
        self.assertEqual(coordinator.ui_state_manager.active_page_uid, "p2")
        self.assertIn("stale placement state", logs.output[0])

    def test_overlay_display_mode_captures_current_camera_before_reload(self):
        coordinator, pages = self._make_view_state_coordinator()
        calls = []
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )
        coordinator._sync_overlay_display_mode = lambda page_uid: calls.append(
            ("sync", page_uid, pages[page_uid].zoom_fac)
        )
        coordinator._update_plan_view = lambda page_uid: calls.append(
            ("update", page_uid, pages[page_uid].zoom_fac)
        )
        coordinator._update_export_menu_state = lambda: calls.append("export")
        coordinator._on_overlay_display_mode_requested(2)
        self.assertEqual(pages["p1"].image_show_mode, 2)
        self.assertEqual(pages["p1"].zoom_fac, 2.5)
        self.assertEqual(pages["p1"].current_x, 10.0)
        self.assertEqual(pages["p1"].current_y, 20.0)
        self.assertEqual(
            coordinator._deferred_persistence.page_view_calls,
            [("a.mdb", "p1", 2.5, 10.0, 20.0)],
        )
        self.assertEqual(
            coordinator._deferred_persistence.selected_page_calls,
            [("a.mdb", "bid-1", "p1")],
        )
        self.assertEqual(
            coordinator._deferred_persistence.page_show_mode_calls,
            [("a.mdb", "p1", 2)],
        )
        self.assertEqual(calls, [("sync", "p1", 2.5), ("update", "p1", 2.5), "export"])

    def test_close_flushes_latest_page_view_and_selected_page_writes(self):
        coordinator, _pages = self._make_view_state_coordinator()
        self.assertTrue(coordinator.flush_current_page_state())
        self.assertEqual(
            coordinator._deferred_persistence.page_view_calls,
            [("a.mdb", "p1", 2.5, 10.0, 20.0)],
        )
        self.assertEqual(
            coordinator._deferred_persistence.selected_page_calls,
            [("a.mdb", "bid-1", "p1")],
        )
        self.assertEqual(coordinator._deferred_persistence.flush_all_calls, 1)

    def test_failed_close_time_flush_keeps_pending_writes_available(self):
        service = FakeProjectWriteService()
        service.fail_methods.add("save_page_view_state")
        manager = DeferredPersistenceManager(
            service, logger_=logging.getLogger(__name__)
        )
        self.addCleanup(manager.cleanup)
        self.addCleanup(lambda: service.fail_methods.clear())
        manager.schedule_page_view_state("a.mdb", "p1", 2.0, 10.0, 20.0)
        self.assertFalse(manager.flush())
        self.assertEqual(manager.pending_count, 1)

    def _make_visibility_coordinator(
        self,
        *,
        layer_name="Layer 1",
        selected_page_uids=None,
        active_page_uid="p1",
        condition_layer_uid="l1",
        page_layer_uid=None,
    ):
        selected_page_uids = selected_page_uids or [active_page_uid]
        page_layer_uid = (
            "l1" if page_layer_uid is None and layer_name == "Image" else page_layer_uid
        )
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("a.mdb", "bid-1"),
            active_page_uid=active_page_uid,
            state=SimpleNamespace(grayscale_enabled=False),
        )
        pages = {
            "p1": Page(uid="p1", name="P1"),
            "p2": Page(uid="p2", name="P2"),
        }
        conditions = {
            "c1": Condition(uid="c1", name="C1", layer_uid=condition_layer_uid),
        }
        annotation_layer_uid = "annotation-layer"
        coordinator.quantity_update_calls = []
        quantity_calls = coordinator.quantity_update_calls

        def is_page_layer_uid(layer_uid):
            return page_layer_uid is not None and str(layer_uid) == str(page_layer_uid)

        coordinator.project_data = SimpleNamespace(
            is_image_layer_uid=is_page_layer_uid,
            update_layer_visibility=lambda layer_uid, _show: (
                [
                    "p1",
                    "p2",
                ]
                if is_page_layer_uid(layer_uid)
                else []
            ),
            update_all_layer_visibility=lambda _show: ["p1", "p2"],
            set_bid_layer_visibility=lambda _layers: None,
            get_hidden_layer_uids=lambda: set(),
            is_annotation_layer_visible=lambda: True,
            get_selected_page_uids=lambda: list(selected_page_uids),
            get_bid=lambda _bid_ref: None,
            get_page=lambda page_uid: pages.get(page_uid),
            get_bid_conditions=lambda: conditions,
            get_annotation_layer_uid=lambda: annotation_layer_uid,
        )
        coordinator._project_read_service = SimpleNamespace(
            get_merged_bid_layers=lambda _db_path, _bid_uid: [
                SimpleNamespace(uid="l1", name=layer_name)
            ]
        )
        coordinator._sidebar = SimpleNamespace(
            bid_layers_sidebar=SimpleNamespace(
                get_layer=lambda _uid: SimpleNamespace(uid="l1", name=layer_name),
                get_layers=lambda: [SimpleNamespace(uid="l1", name=layer_name)],
                set_layer_visible=lambda *_args: None,
                set_all_layers_visible=lambda *_args: None,
            ),
            update_conditions_quantities=lambda: quantity_calls.append("quantity"),
            load_condition_summary=lambda: None,
        )
        coordinator.conditions_sidebar = None
        coordinator.condition_summary_tab = None
        coordinator.layer_events = []
        coordinator.event_bus = SimpleNamespace(
            publish=lambda event, **kwargs: coordinator.layer_events.append(
                (event, kwargs)
            )
        )
        coordinator._viewer = SimpleNamespace(update_viewers=lambda page_uids: None)
        coordinator._update_plan_view_calls = []
        coordinator._update_plan_view = (
            lambda page_uid: coordinator._update_plan_view_calls.append(page_uid)
        )
        coordinator._update_export_menu_state = lambda: None
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )

        def enter_place(condition_uid, _selected):
            coordinator.plan_view.cursor_mode = "place"
            coordinator.plan_view.place_condition_uid = condition_uid
            return True

        coordinator._placement = SimpleNamespace(enter=enter_place)
        coordinator.select_checked_calls = []
        coordinator.toolbar_refresh_calls = []
        coordinator._toolbar = SimpleNamespace(
            refresh=lambda: coordinator.toolbar_refresh_calls.append("refresh"),
            set_select_checked=lambda: coordinator.select_checked_calls.append(
                "select"
            ),
            is_takeoff_2d_view_active=lambda: True,
        )
        coordinator._suspended_layer_tool = None
        coordinator.plan_view = RecordingPlanView()
        coordinator._deferred_persistence = RecordingDeferredPersistence()
        self._install_hidden_2d_mesh_state(coordinator)
        return coordinator

    def _install_conditions_sidebar_recorder(self, coordinator):
        calls = []
        coordinator.conditions_sidebar = SimpleNamespace(
            apply_layer_visibility_state=(
                lambda conditions, grayscale, layer_uid=None: calls.append(
                    ("apply", list(conditions), grayscale, layer_uid)
                )
            ),
            load_conditions=lambda *_args: self.fail(
                "visibility-only toggle should not reload condition tree"
            ),
        )
        return calls

    def test_show_all_without_sidebar_queues_all_layers_from_read_service(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("a.mdb", "bid-1"),
            active_page_uid="p1",
            state=SimpleNamespace(grayscale_enabled=False),
        )
        coordinator.project_data = SimpleNamespace(
            update_all_layer_visibility=lambda _show: ["p1"],
            set_bid_layer_visibility=lambda _layers: None,
            get_hidden_layer_uids=lambda: set(),
            is_annotation_layer_visible=lambda: True,
            get_selected_page_uids=lambda: ["p1"],
            get_bid=lambda _bid_ref: None,
            get_page=lambda _page_uid: None,
            get_bid_conditions=lambda: {},
            get_annotation_layer_uid=lambda: "annotation-layer",
        )
        coordinator._project_read_service = SimpleNamespace(
            get_merged_bid_layers=lambda _db_path, _bid_uid: [
                SimpleNamespace(uid="l1"),
                SimpleNamespace(uid="l2"),
            ]
        )
        quantity_calls = []
        coordinator._sidebar = SimpleNamespace(
            bid_layers_sidebar=None,
            update_conditions_quantities=lambda: quantity_calls.append("quantity"),
            load_condition_summary=lambda: None,
        )
        coordinator.conditions_sidebar = None
        coordinator.condition_summary_tab = None
        coordinator.event_bus = SimpleNamespace(publish=lambda *_args, **_kwargs: None)
        coordinator.plan_view = None
        self._install_hidden_2d_mesh_state(coordinator)
        coordinator._viewer = SimpleNamespace(update_viewers=lambda _page_uids: None)
        coordinator._update_plan_view = lambda _page_uid: None
        coordinator._update_export_menu_state = lambda: None
        coordinator.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: True
        )

        def enter_place(_condition_uid, _selected):
            return False

        coordinator._placement = SimpleNamespace(enter=enter_place)
        coordinator._toolbar = SimpleNamespace(
            refresh=lambda: None,
            set_select_checked=lambda: None,
            is_takeoff_2d_view_active=lambda: True,
        )
        coordinator._suspended_layer_tool = None
        deferred = RecordingDeferredPersistence()
        coordinator._deferred_persistence = deferred
        self.assertTrue(coordinator.update_all_layers_visibility_deferred(False))
        self.assertEqual(
            deferred.layer_calls,
            [
                ("a.mdb", "l1", False),
                ("a.mdb", "l2", False),
            ],
        )
        self.assertEqual(coordinator.mesh_refresh_calls, [])
        self.assertTrue(coordinator._mesh_scene_dirty)
        self.assertEqual(coordinator._dirty_mesh_page_uids, {"p1"})
        self.assertEqual(quantity_calls, [])

    def test_image_layer_disable_queues_write_and_does_not_reload_pages(self):
        coordinator = self._make_visibility_coordinator(
            layer_name="Image",
            condition_layer_uid="other-layer",
        )
        mesh_calls = []
        coordinator._viewer = SimpleNamespace(
            update_viewers=lambda page_uids: mesh_calls.append(page_uids)
        )
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", False))
        self.assertEqual(
            coordinator._deferred_persistence.layer_calls,
            [("a.mdb", "l1", False)],
        )
        self.assertEqual(coordinator._update_plan_view_calls, [])
        self.assertEqual(coordinator.plan_view.image_visibility_pages, ["p1"])
        self.assertEqual(mesh_calls, [])
        self.assertEqual(coordinator.quantity_update_calls, [])

    def test_condition_layer_visibility_uses_loaded_item_path(self):
        coordinator = self._make_visibility_coordinator(layer_name="Layer 1")
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", False))
        self.assertEqual(coordinator._update_plan_view_calls, [])
        self.assertEqual(len(coordinator.plan_view.layer_visibility_calls), 1)
        self.assertEqual(coordinator.mesh_refresh_calls, [])
        self.assertTrue(coordinator._mesh_scene_dirty)
        self.assertEqual(coordinator._dirty_mesh_page_uids, {"p1"})
        self.assertEqual(coordinator.quantity_update_calls, [])

    def test_layer_visibility_updates_conditions_sidebar_without_full_reload(self):
        coordinator = self._make_visibility_coordinator(layer_name="Layer 1")
        calls = self._install_conditions_sidebar_recorder(coordinator)
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", False))
        self.assertEqual(calls, [("apply", ["c1"], False, "l1")])

    def test_layers_without_condition_rows_skip_conditions_sidebar_refresh(self):
        for layer_name in ("Annotation", "Image", "Future Visual", "Custom Empty"):
            with self.subTest(layer_name=layer_name):
                coordinator = self._make_visibility_coordinator(
                    layer_name=layer_name,
                    condition_layer_uid="other-layer",
                )
                calls = self._install_conditions_sidebar_recorder(coordinator)
                self.assertTrue(
                    coordinator.update_layer_visibility_deferred("l1", False)
                )
                self.assertEqual(calls, [])
                self.assertEqual(coordinator.mesh_refresh_calls, [])
                self.assertEqual(coordinator.quantity_update_calls, [])

    def test_layer_visibility_uses_same_deferred_path_for_all_layer_names(self):
        cases = (
            ("Annotation", False),
            ("Image", True),
            ("Future Visual", False),
            ("Custom Empty", False),
        )
        for layer_name, page_layer_changed in cases:
            with self.subTest(layer_name=layer_name):
                coordinator = self._make_visibility_coordinator(
                    layer_name=layer_name,
                    condition_layer_uid="other-layer",
                )
                self.assertTrue(
                    coordinator.update_layer_visibility_deferred("l1", False)
                )
                self.assertEqual(
                    coordinator._deferred_persistence.layer_calls,
                    [("a.mdb", "l1", False)],
                )
                self.assertEqual(
                    coordinator.layer_events[0][1]["layer_uid"],
                    "l1",
                )
                if page_layer_changed:
                    self.assertEqual(
                        coordinator.plan_view.image_visibility_pages, ["p1"]
                    )
                    self.assertEqual(coordinator.plan_view.layer_visibility_calls, [])
                else:
                    self.assertEqual(coordinator.plan_view.image_visibility_pages, [])
                    self.assertEqual(
                        len(coordinator.plan_view.layer_visibility_calls),
                        1,
                    )

    def test_condition_layer_without_condition_rows_skips_conditions_sidebar_refresh(
        self,
    ):
        coordinator = self._make_visibility_coordinator(
            layer_name="Layer 1",
            condition_layer_uid="other-layer",
        )
        calls = self._install_conditions_sidebar_recorder(coordinator)
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", False))
        self.assertEqual(calls, [])
        self.assertEqual(coordinator.quantity_update_calls, [])

    def test_default_named_layer_with_condition_rows_refreshes_conditions_sidebar(self):
        coordinator = self._make_visibility_coordinator(layer_name="Annotation")
        calls = self._install_conditions_sidebar_recorder(coordinator)
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", False))
        self.assertEqual(calls, [("apply", ["c1"], False, "l1")])
        self.assertEqual(coordinator.quantity_update_calls, [])

    def test_repeated_layer_toggles_refresh_view_immediately(self):
        coordinator = self._make_visibility_coordinator(layer_name="Layer 1")
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", False))
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", True))
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", False))
        self.assertEqual(coordinator.quantity_update_calls, [])
        self.assertEqual(coordinator.mesh_refresh_calls, [])
        self.assertTrue(coordinator._mesh_scene_dirty)
        self.assertEqual(coordinator._dirty_mesh_page_uids, {"p1"})

    def test_hiding_annotation_layer_temporarily_selects_then_restores_tool(self):
        coordinator = self._make_visibility_coordinator(
            layer_name="Annotation",
            condition_layer_uid="condition-layer",
        )
        coordinator.plan_view.cursor_mode = "annotation_place"
        coordinator.plan_view.annotation_place_type = ANNOTATION_TYPE_RECT
        self.assertTrue(
            coordinator.update_layer_visibility_deferred("annotation-layer", False)
        )
        self.assertEqual(coordinator.plan_view.cursor_mode, "select")
        self.assertEqual(coordinator.plan_view.cursor_modes, ["select"])
        self.assertEqual(coordinator.select_checked_calls, ["select"])
        self.assertTrue(
            coordinator.update_layer_visibility_deferred("annotation-layer", True)
        )
        self.assertEqual(coordinator.plan_view.cursor_mode, "annotation_place")
        self.assertEqual(
            coordinator.plan_view.annotation_placements, [ANNOTATION_TYPE_RECT]
        )

    def test_hiding_unrelated_layer_keeps_active_annotation_tool(self):
        coordinator = self._make_visibility_coordinator(
            layer_name="Layer 1",
            condition_layer_uid="condition-layer",
        )
        coordinator.plan_view.cursor_mode = "annotation_place"
        coordinator.plan_view.annotation_place_type = ANNOTATION_TYPE_RECT
        self.assertTrue(coordinator.update_layer_visibility_deferred("other", False))
        self.assertEqual(coordinator.plan_view.cursor_mode, "annotation_place")
        self.assertEqual(
            coordinator.plan_view.annotation_place_type, ANNOTATION_TYPE_RECT
        )
        self.assertEqual(coordinator.plan_view.cursor_modes, [])
        self.assertEqual(coordinator.select_checked_calls, [])

    def test_hiding_condition_layer_temporarily_selects_then_restores_place_tool(self):
        coordinator = self._make_visibility_coordinator(layer_name="Layer 1")
        coordinator.plan_view.cursor_mode = "place"
        coordinator.plan_view.place_condition_uid = "c1"
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", False))
        self.assertEqual(coordinator.plan_view.cursor_mode, "select")
        self.assertEqual(coordinator.plan_view.cursor_modes, ["select"])
        self.assertEqual(coordinator.select_checked_calls, ["select"])
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", True))
        self.assertEqual(coordinator.plan_view.cursor_mode, "place")
        self.assertEqual(coordinator.plan_view.place_condition_uid, "c1")

    def test_hide_all_temporarily_selects_then_show_all_restores_annotation_tool(self):
        coordinator = self._make_visibility_coordinator(
            layer_name="Annotation",
            condition_layer_uid="condition-layer",
        )
        coordinator.plan_view.cursor_mode = "annotation_place"
        coordinator.plan_view.annotation_place_type = ANNOTATION_TYPE_TEXT
        self.assertTrue(coordinator.update_all_layers_visibility_deferred(False))
        self.assertEqual(coordinator.plan_view.cursor_mode, "select")
        self.assertTrue(coordinator.update_all_layers_visibility_deferred(True))
        self.assertEqual(coordinator.plan_view.cursor_mode, "annotation_place")
        self.assertEqual(
            coordinator.plan_view.annotation_placements, [ANNOTATION_TYPE_TEXT]
        )

    def test_show_all_uses_shared_page_and_layer_visibility_refresh(self):
        coordinator = self._make_visibility_coordinator(layer_name="Image")
        self.assertTrue(coordinator.update_all_layers_visibility_deferred(False))
        self.assertEqual(coordinator._update_plan_view_calls, [])
        self.assertEqual(coordinator.plan_view.image_visibility_pages, ["p1"])
        self.assertEqual(
            coordinator.plan_view.all_layer_visibility_calls,
            [(False, coordinator.project_data.get_bid_conditions())],
        )
        self.assertEqual(coordinator.plan_view.layer_visibility_calls, [])

    def test_repeated_layer_toggles_coalesce_to_last_write(self):
        service = FakeProjectWriteService()
        manager = DeferredPersistenceManager(
            service, logger_=logging.getLogger(__name__)
        )
        self.addCleanup(manager.cleanup)
        manager.schedule_layer_show("a.mdb", "l1", False)
        manager.schedule_layer_show("a.mdb", "l1", True)
        self.assertEqual(manager.pending_count, 1)
        self.assertTrue(manager.flush())
        self.assertEqual(
            service.calls,
            [("layer_show", "a.mdb", "l1", True, False)],
        )

    def test_database_refresh_flushes_pending_visual_state_before_reload(self):
        calls = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._deferred_persistence = SimpleNamespace(
            flush_for_file=lambda file_path: calls.append(("flush", file_path)) or True
        )
        coordinator._nav = SimpleNamespace(
            start_refresh=lambda *_args, **_kwargs: calls.append("start") or True
        )
        coordinator.ui_state_manager = SimpleNamespace(selected_area_uid="")
        coordinator._placement = SimpleNamespace()
        coordinator._do_file_refresh = lambda: calls.append("refresh")
        coordinator._finish_refresh = lambda: calls.append("finish")
        coordinator._on_database_refreshed(file_path="a.mdb")
        self.assertEqual(calls, [("flush", "a.mdb"), "start", "refresh", "finish"])

    def test_database_refresh_stops_when_deferred_flush_fails(self):
        calls = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator._deferred_persistence = SimpleNamespace(
            flush_for_file=lambda file_path: calls.append(("flush", file_path)) or False
        )
        coordinator._nav = SimpleNamespace(
            start_refresh=lambda *_args, **_kwargs: calls.append("start") or True
        )
        coordinator._do_file_refresh = lambda: calls.append("refresh")
        coordinator._finish_refresh = lambda: calls.append("finish")
        coordinator._on_database_refreshed(file_path="a.mdb")
        self.assertEqual(calls, [("flush", "a.mdb")])

    def test_sidebar_quantities_include_hidden_layer_conditions(self):
        quantity_payloads = []
        visible = Condition(uid="c1", name="Visible", layer_uid="l1")
        hidden = Condition(uid="c2", name="Hidden", layer_uid="l2")
        hidden.layer_visible = False
        project_data = SimpleNamespace(
            get_selected_page_uids=lambda: ["p1"],
            get_bid_conditions=lambda: {"c1": visible, "c2": hidden},
            compute_quantities_for_pages=lambda page_uids: {
                "c1": (1.0, 0.0, 0.0),
                "c2": (2.0, 0.0, 0.0),
            },
        )
        sidebar = SidebarCoordinator(
            project_read_service=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(active_page_uid="p1"),
            project_data=project_data,
        )
        sidebar.conditions_sidebar = SimpleNamespace(
            update_quantities=lambda quantities: quantity_payloads.append(quantities)
        )
        sidebar.update_conditions_quantities()
        self.assertEqual(
            quantity_payloads,
            [{"c1": (1.0, 0.0, 0.0), "c2": (2.0, 0.0, 0.0)}],
        )

    def test_sidebar_quantity_update_accepts_partial_condition_uids(self):
        quantity_calls = []
        sidebar_calls = []

        def compute_quantities(page_uids, only_condition_uids=None):
            quantity_calls.append((list(page_uids), set(only_condition_uids or [])))
            return {uid: (3.0, 0.0, 0.0) for uid in only_condition_uids or []}

        project_data = SimpleNamespace(
            get_selected_page_uids=lambda: ["p1"],
            compute_quantities_for_pages=compute_quantities,
        )
        sidebar = SidebarCoordinator(
            project_read_service=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(active_page_uid="p1"),
            project_data=project_data,
        )
        sidebar.conditions_sidebar = SimpleNamespace(
            update_quantities=lambda quantities, partial=False: sidebar_calls.append(
                (dict(quantities), partial)
            )
        )
        sidebar.update_conditions_quantities(condition_uids=["c2"])
        self.assertEqual(quantity_calls, [(["p1"], {"c2"})])
        self.assertEqual(sidebar_calls, [({"c2": (3.0, 0.0, 0.0)}, True)])

    def test_page_area_change_updates_model_immediately_and_defers_write(self):
        area_selections = {"p1": None}
        direct_writes = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        selected_page_reads = []

        def selected_page_uids():
            selected_page_reads.append(area_selections["p1"])
            return ["p1"]

        coordinator.project_data = SimpleNamespace(
            get_page_area_selections=lambda: area_selections,
            get_selected_page_uids=selected_page_uids,
        )
        coordinator.ui_state_manager = SimpleNamespace(active_page_uid="p1")
        coordinator._deferred_persistence = RecordingDeferredPersistence()
        coordinator._project_write_service = SimpleNamespace(
            save_page_area=lambda *_args, **_kwargs: direct_writes.append(_args)
        )
        plan_updates = []
        self._install_hidden_2d_mesh_state(coordinator)
        coordinator._viewer = SimpleNamespace(
            update_plan_view=lambda page_uid: plan_updates.append(page_uid),
            update_viewers=lambda _page_uids: None,
        )
        hotlink_updates = []
        coordinator._apply_pending_hotlink_named_view_focus = (
            lambda require_stable: hotlink_updates.append(require_stable)
        )
        coordinator._refresh_takeoff_dependent_page_controls = (
            lambda page_uid: self.fail(f"unexpected inactive page refresh {page_uid}")
        )
        coordinator._on_page_area_changed("a.mdb", "p1", "2")
        self.assertEqual(coordinator.ui_state_manager.selected_area_uid, "2")
        self.assertEqual(area_selections["p1"], "2")
        self.assertEqual(
            coordinator._deferred_persistence.page_area_calls,
            [("a.mdb", "p1", "2")],
        )
        self.assertEqual(plan_updates, ["p1"])
        self.assertEqual(coordinator.mesh_refresh_calls, [])
        self.assertTrue(coordinator._mesh_scene_dirty)
        self.assertEqual(coordinator._dirty_mesh_page_uids, {"p1"})
        self.assertEqual(selected_page_reads, ["2"])
        self.assertEqual(hotlink_updates, [True])
        self.assertEqual(direct_writes, [])

    def test_page_area_clear_updates_model_to_no_filter(self):
        area_selections = {"p1": "2"}
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.project_data = SimpleNamespace(
            get_page_area_selections=lambda: area_selections,
            get_selected_page_uids=lambda: ["p1"],
        )
        coordinator.ui_state_manager = SimpleNamespace(active_page_uid="p1")
        coordinator._deferred_persistence = RecordingDeferredPersistence()
        self._install_hidden_2d_mesh_state(coordinator)
        coordinator._viewer = SimpleNamespace(
            update_plan_view=lambda _page_uid: None,
            update_viewers=lambda _page_uids: None,
        )
        coordinator._apply_pending_hotlink_named_view_focus = (
            lambda require_stable: None
        )
        coordinator._refresh_takeoff_dependent_page_controls = lambda _page_uid: None
        coordinator._on_page_area_changed("a.mdb", "p1", "")
        self.assertEqual(coordinator.ui_state_manager.selected_area_uid, "")
        self.assertIsNone(area_selections["p1"])
        self.assertEqual(
            coordinator._deferred_persistence.page_area_calls,
            [("a.mdb", "p1", "")],
        )
        self.assertEqual(coordinator.mesh_refresh_calls, [])
        self.assertTrue(coordinator._mesh_scene_dirty)
        self.assertEqual(coordinator._dirty_mesh_page_uids, {"p1"})


class DeferredPersistenceBoundaryTests(unittest.TestCase):
    def test_project_write_service_reports_ost_active_as_expected_deferred_block(self):
        service = ProjectWriteService.__new__(ProjectWriteService)
        service._connection_manager = SimpleNamespace(is_write_blocked=lambda: True)
        service._bid_write_guard = SimpleNamespace(
            is_active_locked_bid_write_blocked=lambda *_args: False
        )
        self.assertTrue(service.is_expected_deferred_write_blocked("a.mdb"))

    def test_project_write_service_reports_locked_bid_as_expected_deferred_block(self):
        service = ProjectWriteService.__new__(ProjectWriteService)
        service._connection_manager = SimpleNamespace(is_write_blocked=lambda: False)
        service._bid_write_guard = SimpleNamespace(
            is_active_locked_bid_write_blocked=lambda db_path, bid_uid=None: (
                db_path,
                bid_uid,
            )
            == ("a.mdb", None)
        )
        self.assertTrue(service.is_expected_deferred_write_blocked("a.mdb"))

    def test_page_area_write_can_skip_database_refresh(self):
        calls = []
        service = ProjectWriteService.__new__(ProjectWriteService)
        service._bid_write_guard = SimpleNamespace(
            blocks_active_locked_bid_write=lambda *_args: False
        )
        service._save_page_area = SimpleNamespace(
            execute=lambda db_path, page_uid, area_uid: calls.append(
                ("write", db_path, page_uid, area_uid)
            )
            or True
        )
        service._reload_after_success = lambda db_path, success, publish=True: (
            calls.append(("reload_after_success", db_path, success, publish)) or success
        )
        self.assertTrue(
            service.save_page_area(
                "a.mdb",
                "p1",
                "2",
                publish_database_refreshed_after_write=False,
            )
        )
        self.assertEqual(
            calls,
            [
                ("write", "a.mdb", "p1", "2"),
                ("reload_after_success", "a.mdb", True, False),
            ],
        )

    def test_cover_sheet_save_flushes_pending_visual_state_before_write(self):
        write_calls = []
        deferred = SimpleNamespace(flush_for_file=lambda _db_path: False)
        context = CoverSheetContext(
            project_read_service=SimpleNamespace(),
            project_write_service=SimpleNamespace(
                save_cover_sheet=lambda *_args: write_calls.append(_args) or True
            ),
            bid_ref=BidRef("a.mdb", "bid-1"),
            deferred_persistence_manager=deferred,
        )
        self.assertFalse(context.save_cover_sheet({"job_name": "A"}))
        self.assertEqual(write_calls, [])


if __name__ == "__main__":
    unittest.main()
