import os
import logging
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication

from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.dialogs.cover_sheet.context import CoverSheetContext
from ost_visualizer.presentation.managers.deferred_persistence_manager import (
    DeferredPersistenceManager,
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

    def update_layer_show(self, db_path, layer_uid, show, reload_database=True):
        self.calls.append(("layer_show", db_path, layer_uid, show, reload_database))
        return "update_layer_show" not in self.fail_methods

    def save_page_show_mode(self, db_path, page_uid, show_mode, reload_database=True):
        self.calls.append(
            ("page_show_mode", db_path, page_uid, show_mode, reload_database)
        )
        return "save_page_show_mode" not in self.fail_methods

    def save_page_invert(self, db_path, page_uid, invert):
        self.calls.append(("page_invert", db_path, page_uid, invert))
        return "save_page_invert" not in self.fail_methods

    def save_page_bitonal(self, db_path, page_uid, bitonal):
        self.calls.append(("page_bitonal", db_path, page_uid, bitonal))
        return "save_page_bitonal" not in self.fail_methods

    def save_page_overlay_rect_result(
        self, db_path, page_uid, overlay_rect, reload_database=True
    ):
        self.calls.append(
            ("page_overlay_rect", db_path, page_uid, overlay_rect, reload_database)
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
        self.manager.schedule_page_overlay_rect(
            "a.mdb", "p1", (1, 2.5, 3, 4.25)
        )

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


class RecordingDeferredPersistence:
    def __init__(self):
        self.layer_calls = []

    def schedule_layer_show(self, db_path, layer_uid, show):
        self.layer_calls.append((db_path, layer_uid, show))


class DeferredPersistenceCoordinatorTests(unittest.TestCase):
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


class DeferredPersistenceBoundaryTests(unittest.TestCase):
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
