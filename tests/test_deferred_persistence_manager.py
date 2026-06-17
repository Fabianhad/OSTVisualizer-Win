import os
import logging
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.dialogs.cover_sheet.context import CoverSheetContext
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
        self.manager.cleanup()
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

    def test_cleanup_ignores_later_schedules(self):
        self.manager.cleanup()
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


class RecordingDeferredPersistence:
    def __init__(self):
        self.layer_calls = []
        self.page_area_calls = []
        self.flush_calls = []

    def schedule_layer_show(self, db_path, layer_uid, show):
        self.layer_calls.append((db_path, layer_uid, show))

    def schedule_page_area_selection(self, db_path, page_uid, area_uid):
        self.page_area_calls.append((db_path, page_uid, area_uid))

    def flush_for_file(self, db_path):
        self.flush_calls.append(db_path)
        return True


class RecordingPlanView:
    def __init__(self):
        self.current_page_uid = "p1"
        self.image_visibility_pages = []
        self.layer_visibility_calls = []
        self.all_layer_visibility_calls = []

    def apply_page_image_layer_visibility(self, page):
        self.image_visibility_pages.append(page.uid)
        return True

    def apply_layer_visibility(self, layer_uid, show, conditions):
        self.layer_visibility_calls.append((layer_uid, show, conditions))
        return True

    def apply_all_layer_visibility(self, show, conditions):
        self.all_layer_visibility_calls.append((show, conditions))
        return True


class DeferredPersistenceCoordinatorTests(unittest.TestCase):
    def _make_visibility_coordinator(
        self,
        *,
        layer_name="Layer 1",
        selected_page_uids=None,
        active_page_uid="p1",
    ):
        selected_page_uids = selected_page_uids or [active_page_uid]
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("a.mdb", "bid-1"),
            active_page_uid=active_page_uid,
        )
        pages = {
            "p1": Page(uid="p1", name="P1"),
            "p2": Page(uid="p2", name="P2"),
        }
        conditions = {
            "c1": Condition(uid="c1", name="C1", layer_uid="l1"),
        }
        coordinator.project_data = SimpleNamespace(
            update_layer_visibility=lambda _layer_uid, show, image_layer=False: (
                [
                    "p1",
                    "p2",
                ]
                if image_layer
                else []
            ),
            update_all_layer_visibility=lambda _show: ["p1", "p2"],
            get_selected_page_uids=lambda: list(selected_page_uids),
            get_bid=lambda _bid_ref: None,
            get_page=lambda page_uid: pages.get(page_uid),
            get_bid_conditions=lambda: conditions,
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
            update_conditions_quantities=lambda: None,
        )
        coordinator.conditions_sidebar = None
        coordinator._viewer = SimpleNamespace(update_viewers=lambda page_uids: None)
        coordinator._update_plan_view_calls = []
        coordinator._update_plan_view = (
            lambda page_uid: coordinator._update_plan_view_calls.append(page_uid)
        )
        coordinator._update_export_menu_state = lambda: None
        coordinator.ensure_select_mode = lambda: None
        coordinator.plan_view = RecordingPlanView()
        coordinator._deferred_persistence = RecordingDeferredPersistence()
        return coordinator

    def test_show_all_without_sidebar_queues_all_layers_from_read_service(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("a.mdb", "bid-1"),
            active_page_uid="p1",
        )
        coordinator.project_data = SimpleNamespace(
            update_all_layer_visibility=lambda _show: ["p1"],
            get_selected_page_uids=lambda: ["p1"],
            get_bid=lambda _bid_ref: None,
        )
        coordinator._project_read_service = SimpleNamespace(
            get_merged_bid_layers=lambda _db_path, _bid_uid: [
                SimpleNamespace(uid="l1"),
                SimpleNamespace(uid="l2"),
            ]
        )
        coordinator._sidebar = SimpleNamespace(
            bid_layers_sidebar=None,
            update_conditions_quantities=lambda: None,
        )
        coordinator.conditions_sidebar = None
        coordinator.plan_view = None
        coordinator._viewer = SimpleNamespace(update_viewers=lambda _page_uids: None)
        coordinator._update_plan_view = lambda _page_uid: None
        coordinator._update_export_menu_state = lambda: None
        coordinator.ensure_select_mode = lambda: None
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

    def test_image_layer_disable_queues_write_and_does_not_reload_pages(self):
        coordinator = self._make_visibility_coordinator(layer_name="Image")
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

    def test_condition_layer_visibility_uses_loaded_item_path(self):
        coordinator = self._make_visibility_coordinator(layer_name="Layer 1")
        mesh_calls = []
        coordinator._viewer = SimpleNamespace(
            update_viewers=lambda page_uids: mesh_calls.append(list(page_uids))
        )
        self.assertTrue(coordinator.update_layer_visibility_deferred("l1", False))
        self.assertEqual(coordinator._update_plan_view_calls, [])
        self.assertEqual(len(coordinator.plan_view.layer_visibility_calls), 1)
        self.assertEqual(mesh_calls, [["p1"]])

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

    def test_page_area_change_updates_model_immediately_and_defers_write(self):
        area_selections = {"p1": None}
        direct_writes = []
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.project_data = SimpleNamespace(
            get_page_area_selections=lambda: area_selections
        )
        coordinator.ui_state_manager = SimpleNamespace(active_page_uid="p1")
        coordinator._deferred_persistence = RecordingDeferredPersistence()
        coordinator._project_write_service = SimpleNamespace(
            save_page_area=lambda *_args, **_kwargs: direct_writes.append(_args)
        )
        plan_updates = []
        coordinator._viewer = SimpleNamespace(
            update_plan_view=lambda page_uid: plan_updates.append(page_uid)
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
        self.assertEqual(hotlink_updates, [True])
        self.assertEqual(direct_writes, [])

    def test_page_area_clear_updates_model_to_no_filter(self):
        area_selections = {"p1": "2"}
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.project_data = SimpleNamespace(
            get_page_area_selections=lambda: area_selections
        )
        coordinator.ui_state_manager = SimpleNamespace(active_page_uid="p1")
        coordinator._deferred_persistence = RecordingDeferredPersistence()
        coordinator._viewer = SimpleNamespace(update_plan_view=lambda _page_uid: None)
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


class DeferredPersistenceBoundaryTests(unittest.TestCase):
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
