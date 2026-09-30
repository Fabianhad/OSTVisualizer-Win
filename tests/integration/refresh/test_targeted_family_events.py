import unittest
from unittest.mock import Mock, patch, MagicMock
from types import SimpleNamespace
from contextlib import nullcontext
import pyodbc
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.application.dtos.collaboration_dtos import ChangeOperation
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.managers.detached_page_view_manager import (
    DetachedPageViewManager,
)
import tests.integration.refresh.test_local_family_ownership as scope_fixture


class TargetedRefreshOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scope_fixture.RefreshScopeTests.setUpClass()

    def setUp(self):
        self.case = scope_fixture.RefreshScopeTests()
        self.case.setUp()

    def test_scale_projection_rejects_replaced_page_for_single_and_batch_save(self):
        for batch in (False, True):
            with self.subTest(batch=batch):
                self.case.setUp()
                fixture = self.case.fixture
                replacement = Page("42", "New incarnation", scale_factor2=96)

                def persist(*_args):
                    fixture.model.set_pages({"42": replacement})
                    return True

                fixture.service._save_page_scale.execute = persist
                fixture.service._reload_database = Mock(return_value=True)
                metadata = Mock()
                fixture.events.subscribe(AppEvents.PAGE_METADATA_CHANGED, metadata)
                if batch:
                    result = fixture.service.save_page_scales("test.mdb", ["42"], 1, 24)
                else:
                    result = fixture.service.save_page_scale("test.mdb", "42", 1, 24)
                self.assertTrue(result)
                self.assertEqual(replacement.scale_factor2, 96)
                fixture.service._reload_database.assert_called_once_with("test.mdb")
                metadata.assert_not_called()

    def test_scale_rename_condition_chain_preserves_unrelated_owners_and_emits_once(
        self,
    ):
        fixture = self.case.fixture
        page = fixture.original
        bid = fixture.model.current_bid
        page.zoom_fac, page.current_x, page.current_y = 2, 13, 17
        new_condition = Condition("12", "Updated", 0)
        fixture.service._condition_family_reader = Mock(
            return_value=({"12": new_condition}, {})
        )
        metadata, conditions, broad = Mock(), Mock(), Mock()
        fixture.events.subscribe(AppEvents.PAGE_METADATA_CHANGED, metadata)
        fixture.events.subscribe(AppEvents.CONDITIONS_CHANGED, conditions)
        fixture.events.subscribe(AppEvents.DATABASE_REFRESHED, broad)
        self.assertTrue(fixture.service.save_page_scale("test.mdb", "42", 1, 24))
        self.assertTrue(fixture.service.save_page_name("test.mdb", "42", "Renamed"))
        self.assertTrue(
            fixture.service.reload_conditions_and_notify(
                "test.mdb", "7", ["12"], ["notes"], [ChangeOperation.UPDATE]
            )
        )
        self.assertIs(fixture.data.get_page("42"), page)
        self.assertIs(fixture.model.current_bid, bid)
        self.assertEqual((page.name, page.scale_factor2), ("Renamed", 24))
        self.assertEqual((page.zoom_fac, page.current_x, page.current_y), (2, 13, 17))
        self.assertEqual(metadata.call_count, 2)
        conditions.assert_called_once()
        broad.assert_not_called()
        self.assertEqual(fixture.reloads, [])

    def test_failed_scale_then_retry_publishes_only_committed_projection(self):
        fixture = self.case.fixture
        metadata = Mock()
        fixture.events.subscribe(AppEvents.PAGE_METADATA_CHANGED, metadata)
        fixture.writer.save_page_scale.side_effect = [False, True]
        self.assertFalse(fixture.service.save_page_scale("test.mdb", "42", 1, 24))
        self.assertEqual(fixture.original.scale_factor2, 48)
        metadata.assert_not_called()
        self.assertTrue(fixture.service.save_page_scale("test.mdb", "42", 1, 24))
        self.assertEqual(fixture.original.scale_factor2, 24)
        metadata.assert_called_once()

    def test_condition_read_failure_cannot_fan_out_into_a_successful_reload_event(self):
        fixture = self.case.fixture
        fixture.service._condition_family_reader = Mock(
            side_effect=pyodbc.Error("Read failed")
        )
        fixture.service._reload_database = Mock(return_value=True)
        event = Mock()
        fixture.events.subscribe(AppEvents.CONDITIONS_CHANGED, event)
        with self.assertLogs(fixture.service.logger, level="WARNING"):
            success = fixture.service.reload_conditions_and_notify(
                "test.mdb", "7", ["12"], ["name"], [ChangeOperation.UPDATE]
            )
        self.assertFalse(success)
        event.assert_not_called()
        fixture.service._reload_database.assert_not_called()

    def test_rejected_condition_scope_announces_complete_authoritative_fallback(self):
        fixture = self.case.fixture
        takeoff = Takeoff("t1", "12", page_uid="42")
        fixture.original.takeoffs = [takeoff]
        fixture.model.bid_takeoffs = [takeoff]
        fixture.service._condition_family_reader = Mock(return_value=({}, {}))
        replacement = Page("42", "Authoritative replacement")

        def reload_database(_path):
            fixture.model.set_pages({"42": replacement})
            fixture.model.bid_takeoffs = []
            return True

        fixture.service._reload_database = Mock(side_effect=reload_database)
        full, scoped = Mock(), Mock()
        fixture.events.subscribe(AppEvents.DATABASE_REFRESHED, full)
        fixture.events.subscribe(AppEvents.CONDITIONS_CHANGED, scoped)
        self.assertTrue(
            fixture.service.reload_conditions_and_notify(
                "test.mdb", "7", ["12"], ["notes"], [ChangeOperation.UPDATE]
            )
        )
        self.assertIs(fixture.data.get_page("42"), replacement)
        full.assert_called_once()
        self.assertTrue(full.call_args.kwargs["external_change"])
        scoped.assert_not_called()
        fixture.service._reload_database.assert_called_once_with("test.mdb")

    def test_failed_condition_read_or_fallback_then_retry_emits_only_final_scope(self):
        for failed_read in (True, False):
            with self.subTest(failed_read=failed_read):
                self.case.setUp()
                fixture = self.case.fixture
                original = Condition("12", "Original", 0)
                fixture.model.bid_conditions = {"12": original}
                takeoff = Takeoff("t1", "12", page_uid="42")
                fixture.model.bid_takeoffs = [takeoff]
                fixture.original.takeoffs = [takeoff]
                reader = Mock(
                    side_effect=pyodbc.Error("Read failed") if failed_read else None,
                    return_value=({}, {}),
                )
                fixture.service._condition_family_reader = reader
                fixture.service._reload_database = Mock(return_value=False)
                full, scoped = Mock(), Mock()
                fixture.events.subscribe(AppEvents.DATABASE_REFRESHED, full)
                fixture.events.subscribe(AppEvents.CONDITIONS_CHANGED, scoped)
                with (
                    self.assertLogs(fixture.service.logger, level="WARNING")
                    if failed_read
                    else nullcontext()
                ):
                    self.assertFalse(
                        fixture.service.reload_conditions_and_notify(
                            "test.mdb", "7", ["12"], ["notes"], [ChangeOperation.UPDATE]
                        )
                    )
                self.assertIs(fixture.data.get_bid_conditions()["12"], original)
                full.assert_not_called()
                scoped.assert_not_called()
                current = Condition("12", "Current", 0)
                reader.side_effect = None
                reader.return_value = ({"12": current}, {})
                self.assertTrue(
                    fixture.service.reload_conditions_and_notify(
                        "test.mdb", "7", ["12"], ["notes"], [ChangeOperation.UPDATE]
                    )
                )
                self.assertIs(fixture.data.get_bid_conditions()["12"], current)
                self.assertIs(fixture.data.get_page("42"), fixture.original)
                scoped.assert_called_once()
                full.assert_not_called()

    def test_metadata_event_surface_matrix_has_no_generic_fanout(self):
        for field in ("name", "scale"):
            for target in ("42", "43"):
                for matching_bid in (True, False):
                    with self.subTest(
                        field=field, target=target, matching=matching_bid
                    ):
                        fixture = self.case.fixture
                        fixture.model.set_pages(
                            {"42": fixture.original, "43": Page("43", "Other")}
                        )
                        fixture.model.select_pages(["42"])
                        main = UIEventCoordinator.__new__(UIEventCoordinator)
                        main.ui_state_manager = fixture.coordinator.ui_state_manager
                        main.project_data = fixture.data
                        main.takeoff_sidebar = Mock()
                        main._sidebar = Mock()
                        main._viewer = Mock()
                        main._sync_page_info_status = Mock()
                        main._update_page_settings_bar = Mock()
                        main._apply_pending_hotlink_named_view_focus = Mock()
                        main._request_or_defer_mesh_refresh = Mock()
                        main._is_summary_tab_active = lambda: True
                        main._do_file_refresh = Mock()
                        detached = DetachedPageViewManager.__new__(
                            DetachedPageViewManager
                        )
                        detached._window = Mock()
                        detached.repository = SimpleNamespace(
                            get_active_view=lambda: SimpleNamespace(
                                bid_ref=fixture.bid_ref, target_page_uid="42"
                            )
                        )
                        detached.project_data = fixture.data
                        detached._get_page_data = Mock()
                        detached._refresh_signaler = Mock()
                        database = "test.mdb" if matching_bid else "other.mdb"
                        main._on_page_metadata_changed(
                            database, "7", (target,), (field,)
                        )
                        detached._on_page_metadata_changed(
                            database, "7", (target,), (field,)
                        )
                        scaled_surface = int(
                            matching_bid and field == "scale" and target == "42"
                        )
                        self.assertEqual(
                            main._viewer.update_plan_view.call_count, scaled_surface
                        )
                        self.assertEqual(
                            main._sidebar.update_conditions_quantities.call_count,
                            scaled_surface,
                        )
                        self.assertEqual(
                            main._request_or_defer_mesh_refresh.call_count,
                            scaled_surface,
                        )
                        self.assertEqual(
                            detached._window.update_page_scale.call_count,
                            scaled_surface,
                        )
                        self.assertEqual(
                            detached._get_page_data.call_count, scaled_surface
                        )
                        renamed = int(matching_bid and field == "name")
                        self.assertEqual(
                            main.takeoff_sidebar.refresh_page_labels.call_count, renamed
                        )
                        self.assertEqual(
                            detached._window.refresh_page_labels.call_count, renamed
                        )
                        self.assertEqual(
                            main._sidebar.load_condition_summary_from_memory.call_count,
                            int(matching_bid),
                        )
                        main._do_file_refresh.assert_not_called()
                        detached._refresh_signaler.request.assert_not_called()
