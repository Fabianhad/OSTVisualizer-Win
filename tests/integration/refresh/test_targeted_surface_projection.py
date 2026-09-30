import unittest
from unittest.mock import Mock, patch, MagicMock
from types import SimpleNamespace
from ost_visualizer.application.events.app_events import AppEvents
from PySide6 import QtWidgets
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.identity_refs import BidRef
import tests.integration.surfaces.test_presentation as surface_fixture


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
