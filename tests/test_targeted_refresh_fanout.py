import unittest
from unittest.mock import Mock, patch, MagicMock
from types import SimpleNamespace
import logging
from contextlib import nullcontext
import pyodbc

from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.project_read_service import ProjectReadService
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.sql.reader import SqlProjectReader
from PySide6 import QtWidgets
from ost_visualizer.presentation.components.page_settings_bar import PageSettingsBar
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.application.dtos.collaboration_dtos import ChangeOperation
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.managers.detached_page_view_manager import (
    DetachedPageViewManager,
)
from tests import test_refresh_scope_regressions as scope_fixture
from tests import test_cross_surface_presentation as surface_fixture


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

    def test_local_area_event_updates_summary_and_mesh_without_repeating_picker_projection(
        self,
    ):
        fixture = self.case.fixture
        main = UIEventCoordinator.__new__(UIEventCoordinator)
        main.ui_state_manager = fixture.coordinator.ui_state_manager
        main.project_data = fixture.data
        main._page_settings_bar = Mock()
        main._sidebar = Mock()
        main._undo_service = Mock()
        main._request_or_defer_mesh_refresh = Mock()
        main._is_summary_tab_active = lambda: True
        main._on_remote_areas_changed(
            "test.mdb", "7", local_completion=True, page_controls_projected=True
        )
        main._page_settings_bar.load_bid_areas.assert_not_called()
        main._sidebar.load_condition_summary_from_memory.assert_called_once_with()
        main._request_or_defer_mesh_refresh.assert_called_once()
        main._undo_service.clear.assert_not_called()


class TargetedRefreshSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        surface_fixture.CrossSurfacePresentationTests.setUpClass()

    def setUp(self):
        self.case = surface_fixture.CrossSurfacePresentationTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def test_detached_scale_refresh_falls_back_when_overlay_identity_changes(self):
        case = self.case
        page = case.data.page
        # Rescaling a calibrated overlay changes the accepted composition identity.
        page.overlay_rect = (10, 20, 30, 40)
        page.scale_factor2 *= 2
        with patch.object(
            case.detached, "update_page", wraps=case.detached.update_page
        ) as reload_page:
            case.bus.publish(
                AppEvents.PAGE_METADATA_CHANGED,
                database_id=case.bid_ref.file_path,
                bid_uid=case.bid_ref.bid_uid,
                page_uids=(page.uid,),
                changed_fields=("scale",),
            )
        reload_page.assert_called_once()
        self.assertEqual(
            case.detached.plan_view._current_render_identity["overlay_rect"],
            page.overlay_rect,
        )

    def test_rename_preserves_native_scene_selection_and_viewport(self):
        case = self.case
        page = case.data.page
        case.data.annotations = [
            surface_fixture.BidAnnotation(
                "rect-1", "rect", page_uid=page.uid, position=[10, 10, 50, 50]
            )
        ]
        case.refresh()
        plan = case.detached.plan_view
        plan.set_selection_enabled(True)
        plan.set_selected_uids({"rect-1"})
        plan.set_zoom_percent(175)
        before_items = {id(item) for item in plan._scene.items()}
        before_selection = set(plan._selected_uids)
        before_transform = plan.viewportTransform()
        item = case.detached._page_combo._page_items[page.uid]
        page.name = "Renamed"
        with patch.object(
            plan, "load_page", wraps=plan.load_page
        ) as load, patch.object(
            case.manager, "_get_page_data", wraps=case.manager._get_page_data
        ) as capture:
            case.bus.publish(
                AppEvents.PAGE_METADATA_CHANGED,
                database_id=case.bid_ref.file_path,
                bid_uid=case.bid_ref.bid_uid,
                page_uids=(page.uid,),
                changed_fields=("name",),
            )
        self.assertEqual({id(item) for item in plan._scene.items()}, before_items)
        self.assertEqual(plan._selected_uids, before_selection)
        self.assertEqual(plan.viewportTransform(), before_transform)
        self.assertIs(case.detached._page_combo._page_items[page.uid], item)
        self.assertEqual(item.text(), "Renamed")
        load.assert_not_called()
        capture.assert_not_called()

    def test_detached_scale_refresh_does_not_reload_accepted_surface(self):
        case = self.case
        page = case.data.page
        # Reapplying the same scale retains the accepted composition identity.
        with patch.object(
            case.detached, "update_page", wraps=case.detached.update_page
        ) as reload_page:
            case.bus.publish(
                AppEvents.PAGE_METADATA_CHANGED,
                database_id=case.bid_ref.file_path,
                bid_uid=case.bid_ref.bid_uid,
                page_uids=(page.uid,),
                changed_fields=("scale",),
            )
        reload_page.assert_not_called()

    def test_reentrant_rename_then_closed_window_event_preserves_latest_labels(self):
        case = self.case
        page = case.data.page
        # Use the production EventBus with the reentrant consumer preceding the view.
        bus = type(case.bus)()
        payload = dict(
            database_id=case.bid_ref.file_path,
            bid_uid=case.bid_ref.bid_uid,
            page_uids=(page.uid,),
            changed_fields=("name",),
        )

        def rename_again(**_event):
            bus.unsubscribe(AppEvents.PAGE_METADATA_CHANGED, rename_again)
            page.name = "Latest rename"
            bus.publish(AppEvents.PAGE_METADATA_CHANGED, **payload)

        bus.subscribe(AppEvents.PAGE_METADATA_CHANGED, rename_again)
        bus.subscribe(
            AppEvents.PAGE_METADATA_CHANGED, case.manager._on_page_metadata_changed
        )
        with patch.object(case.manager, "_get_page_data") as capture:
            page.name = "First rename"
            bus.publish(AppEvents.PAGE_METADATA_CHANGED, **payload)
            self.assertEqual(
                case.detached._page_combo._page_items[page.uid].text(), "Latest rename"
            )
            case.manager.close_view()
            bus.publish(AppEvents.PAGE_METADATA_CHANGED, **payload)
        capture.assert_not_called()

    def test_page_area_assignment_does_not_touch_closed_detached_window(self):
        case = self.case
        case.manager.close_view()
        self.assertIsNone(case.manager._window)
        with patch.object(case.manager, "_get_page_data") as capture:
            case.manager.refresh_page_area_selection(case.data.page.uid)
        capture.assert_not_called()

    def test_page_area_assignment_does_not_touch_same_uid_in_another_bid(self):
        case = self.case
        view = case.manager.repository.get_active_view()
        view.bid_uid = "different-bid"
        with patch.object(
            case.manager, "_get_page_data", return_value=case.detached.page_data
        ) as capture:
            case.manager.refresh_page_area_selection(case.data.page.uid)
        capture.assert_not_called()

    def test_delayed_metadata_event_cannot_read_same_page_uid_from_new_active_bid(self):
        case = self.case
        page = case.data.page
        original_text = case.detached._page_combo._page_items[page.uid].text()
        # The old detached target is still present during a Bid transition.
        case.data.get_current_bid_ref = lambda: BidRef("bid.mdb", "other-bid")
        case.data.page = Page(page.uid, "Unrelated Page with reused UID")
        for field in ("name", "scale"):
            with self.subTest(field=field), patch.object(
                case.manager, "_get_page_data"
            ) as capture, patch.object(case.detached, "update_page_scale") as scale:
                case.bus.publish(
                    AppEvents.PAGE_METADATA_CHANGED,
                    database_id=case.bid_ref.file_path,
                    bid_uid=case.bid_ref.bid_uid,
                    page_uids=(page.uid,),
                    changed_fields=(field,),
                )
                self.assertEqual(
                    case.detached._page_combo._page_items[page.uid].text(),
                    original_text,
                )
                capture.assert_not_called()
                scale.assert_not_called()

    def test_area_projection_failure_is_reported_without_assignment_or_success_event(
        self,
    ):
        case = self.case
        bar = case.bar
        bar._load_areas_fn = lambda *_args: []
        bar._save_areas_fn = lambda *_args, **_kwargs: {}
        bar._refresh_areas_fn = Mock(return_value=None)
        published = Mock()
        assignment = Mock()
        case.bus.subscribe(AppEvents.REMOTE_AREAS_CHANGED, published)
        bar.area_change_requested.connect(assignment)
        result = []

        class Picker(QtWidgets.QDialog):
            def __init__(self, *, parent, save_fn, **_kwargs):
                super().__init__(parent)
                self.save_fn = save_fn

            def get_selected_uid(self):
                return "a2"

            def cleanup(self):
                pass

        def execute(picker, _bus):
            result.append(picker.save_fn(SimpleNamespace(deleted_uids=[])))
            return QtWidgets.QDialog.DialogCode.Accepted

        module = "ost_visualizer.presentation.components.page_settings_bar"
        with patch(module + ".BidAreaPickerDialog", Picker), patch(
            module + ".exec_with_ost_blocking", execute
        ), patch(module + ".show_warning") as warning:
            bar._on_area_browse()
        self.assertTrue(result[0].write_success)
        self.assertFalse(result[0].reload_success)
        published.assert_not_called()
        assignment.assert_not_called()
        warning.assert_called_once()

    def test_area_picker_close_does_not_reapply_snapshot_older_than_scoped_event(self):
        case = self.case
        bar = case.bar
        area_type = surface_fixture.BidArea
        saved = [area_type("a1", "1", "", "Saved name", 1)]
        newer = [area_type("a2", "1", "", "Later authoritative name", 1)]
        bar._load_areas_fn = Mock(return_value=saved)
        bar._save_areas_fn = lambda *_args, **_kwargs: {}
        bar._refresh_areas_fn = Mock(return_value=saved)

        class Picker(QtWidgets.QDialog):
            def __init__(self, *, parent, save_fn, on_saved_fn, **_kwargs):
                super().__init__(parent)
                self.save_fn = save_fn
                self.on_saved_fn = on_saved_fn

            def cleanup(self):
                pass

        def execute(picker, _bus):
            picker.save_fn(SimpleNamespace(deleted_uids=[]))
            picker.on_saved_fn()
            # A later authoritative event arrives while the modal editor remains open.
            bar.load_bid_areas(case.bid_ref, newer, selected_uid="a2")
            return QtWidgets.QDialog.DialogCode.Rejected

        module = "ost_visualizer.presentation.components.page_settings_bar"
        with patch(module + ".BidAreaPickerDialog", Picker), patch(
            module + ".exec_with_ost_blocking", execute
        ), patch.object(
            bar.area_combo, "load_areas", wraps=bar.area_combo.load_areas
        ) as load:
            bar._on_area_browse()
        self.assertEqual(bar.area_combo.currentText(), "Later authoritative name")
        self.assertEqual(bar.area_combo.get_current_area_uid(), "a2")
        self.assertEqual(load.call_count, 2)

    def test_area_picker_cannot_assign_area_removed_by_later_projection(self):
        self._assert_picker_rejects_obsolete_selection(reuse_uid=False)

    def test_area_picker_cannot_assign_reused_uid_from_later_projection(self):
        self._assert_picker_rejects_obsolete_selection(reuse_uid=True)

    def test_reentrant_area_projection_cannot_be_adopted_as_pickers_own_save(self):
        self._assert_picker_rejects_obsolete_selection(reuse_uid=True, reentrant=True)

    def test_cancel_after_external_area_clear_does_not_repeat_assignment(self):
        self._assert_picker_rejects_obsolete_selection(
            reuse_uid=False, cancel_empty=True
        )

    def _assert_picker_rejects_obsolete_selection(
        self, *, reuse_uid, reentrant=False, cancel_empty=False
    ):
        case = self.case
        bar = case.bar
        saved = [surface_fixture.BidArea("a1", "1", "", "Original", 1)]
        bar._load_areas_fn = Mock(return_value=saved)
        bar._save_areas_fn = lambda *_args, **_kwargs: {}
        bar._refresh_areas_fn = Mock(return_value=saved)
        bar.area_change_requested.disconnect(case.coordinator._on_page_area_changed)
        assignment = Mock()
        bar.area_change_requested.connect(assignment)

        class Picker(QtWidgets.QDialog):
            def __init__(self, *, parent, save_fn, on_saved_fn, **_kwargs):
                super().__init__(parent)
                self.save_fn = save_fn
                self.on_saved_fn = on_saved_fn

            def get_selected_uid(self):
                return "a1"

            def cleanup(self):
                pass

        def execute(picker, _bus):
            picker.save_fn(SimpleNamespace(deleted_uids=[]))
            current = [surface_fixture.BidArea("a2", "1", "", "Current", 1)]
            if cancel_empty:
                current = []
            if reuse_uid:
                current.append(
                    surface_fixture.BidArea("a1", "1", "", "Different lifetime", 2)
                )

            def project_later_state():
                if reentrant:
                    bar.presentation_state_changed.disconnect(project_later_state)
                bar.load_bid_areas(case.bid_ref, current, selected_uid="a2")

            if reentrant:
                bar.presentation_state_changed.connect(project_later_state)
            picker.on_saved_fn()
            if not reentrant:
                project_later_state()
            return (
                QtWidgets.QDialog.DialogCode.Rejected
                if cancel_empty
                else QtWidgets.QDialog.DialogCode.Accepted
            )

        module = "ost_visualizer.presentation.components.page_settings_bar"
        with patch(module + ".BidAreaPickerDialog", Picker), patch(
            module + ".exec_with_ost_blocking", execute
        ):
            bar._on_area_browse()
        assignment.assert_not_called()
        self.assertEqual(
            bar.area_combo.get_current_area_uid(), "" if cancel_empty else "a2"
        )


class AreaProjectionFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        surface_fixture.SceneControlPresentationTests.setUpClass()

    def test_failed_area_read_cannot_replace_authoritative_family_with_empty_list(self):
        reader = MdbReader.__new__(MdbReader)
        reader.logger = logging.getLogger(__name__)
        reader._connection = Mock(side_effect=OSError("Database read failed"))
        read_service = ProjectReadService.__new__(ProjectReadService)
        read_service._reader = reader
        read_service.logger = reader.logger
        writes = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda *_args: False,
            save_bid_areas_result=lambda *_args: None,
            reload_and_notify=Mock(return_value=False),
        )
        case = surface_fixture.SceneControlPresentationTests()
        self.addCleanup(case.doCleanups)
        bundle, _combo = case._main_components(read_service, writes)
        case.main_data.replace_bid_areas_after_local_save = Mock(return_value=True)
        bar = bundle.central_widget.findChild(PageSettingsBar)
        with self.assertLogs(level="WARNING"):
            result = bar._refresh_areas_fn("bid.mdb", "1", ())
        case.main_data.replace_bid_areas_after_local_save.assert_not_called()
        self.assertIsNone(result)
        writes.reload_and_notify.assert_not_called()

    def test_condition_folder_query_failure_cannot_publish_incomplete_family(self):
        for reader_type in (MdbReader, SqlProjectReader):
            reader = reader_type.__new__(reader_type)
            connection = MagicMock()
            connection.cursor.return_value.__enter__.return_value.execute.side_effect = pyodbc.Error(
                "Read failed"
            )
            reader._connection = lambda _path: nullcontext(connection)
            schema = Mock()
            schema.optional_table_missing.return_value = False
            reader._schema = lambda _conn: schema
            reader._parse_bid_layers_for_bid = Mock(return_value={})
            reader._parse_cdn_types = Mock(return_value={})
            reader._parse_bid_conditions_for_bid = Mock(return_value={})
            for read in (reader.get_condition_family, reader.get_area_family):
                with self.subTest(reader=reader_type, read=read.__name__):
                    with patch(
                        "ost_visualizer.infrastructure.mdb.components.bid_data_reader.require_existing_unique_bid_owned_uid_matches"
                    ):
                        with self.assertRaises(pyodbc.Error):
                            read("bid.mdb", "1")


if __name__ == "__main__":
    unittest.main()
