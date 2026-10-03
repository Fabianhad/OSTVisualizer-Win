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
        # Positive control: while the detached window is open the same call
        # re-reads the page data for it.
        with patch.object(
            case.manager, "_get_page_data", return_value=case.detached.page_data
        ) as open_capture:
            case.manager.refresh_page_area_selection(case.data.page.uid)
        open_capture.assert_called_once()
        case.manager.close_view()
        self.assertIsNone(case.manager._window)
        with patch.object(case.manager, "_get_page_data") as capture:
            case.manager.refresh_page_area_selection(case.data.page.uid)
        capture.assert_not_called()

    def test_page_area_assignment_does_not_touch_same_uid_in_another_bid(self):
        case = self.case
        view = case.manager.repository.get_active_view()
        with patch.object(
            case.manager, "_get_page_data", return_value=case.detached.page_data
        ) as capture:
            # Positive control: the matching Bid reads the page data once.
            case.manager.refresh_page_area_selection(case.data.page.uid)
            capture.assert_called_once()
            capture.reset_mock()
            view.bid_uid = "different-bid"
            case.manager.refresh_page_area_selection(case.data.page.uid)
        capture.assert_not_called()

    def test_delayed_metadata_event_cannot_read_same_page_uid_from_new_active_bid(self):
        case = self.case
        page = case.data.page
        original_text = case.detached._page_combo._page_items[page.uid].text()
        # Positive control: for the still-current Bid the scale event does reach
        # the detached surface's page-data read and scale update.
        with patch.object(
            case.manager, "_get_page_data", return_value=case.detached.page_data
        ) as control_capture, patch.object(
            case.detached, "update_page_scale"
        ) as control_scale:
            case.bus.publish(
                AppEvents.PAGE_METADATA_CHANGED,
                database_id=case.bid_ref.file_path,
                bid_uid=case.bid_ref.bid_uid,
                page_uids=(page.uid,),
                changed_fields=("scale",),
            )
        control_capture.assert_called_once()
        control_scale.assert_called_once()
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

    def test_area_picker_close_without_save_keeps_a_newer_projection(self):
        case = self.case
        bar = case.bar
        area_type = surface_fixture.BidArea
        stale = [area_type("a1", "1", "", "Stale name", 1)]
        newer = [area_type("a2", "1", "", "Later authoritative name", 1)]
        bar._load_areas_fn = Mock(return_value=stale)
        bar._save_areas_fn = lambda *_args, **_kwargs: {}
        bar._refresh_areas_fn = Mock(return_value=stale)

        class Picker(QtWidgets.QDialog):
            def __init__(self, *, parent, **_kwargs):
                super().__init__(parent)

            def cleanup(self):
                pass

        def execute(picker, _bus):
            # A newer authoritative projection arrives while the modal is open and
            # nothing was saved from the picker.
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
        self.assertEqual(load.call_count, 1)

    def test_area_picker_cannot_assign_area_removed_by_later_projection(self):
        self._assert_picker_rejects_obsolete_selection(reuse_uid=False)

    def test_area_picker_cannot_assign_reused_uid_from_later_projection(self):
        self._assert_picker_rejects_obsolete_selection(reuse_uid=True)

    def test_reentrant_area_projection_cannot_be_adopted_as_pickers_own_save(self):
        self._assert_picker_rejects_obsolete_selection(reuse_uid=True, reentrant=True)

    def test_area_picker_assigns_its_selection_when_no_later_projection_arrives(self):
        # Positive control for the obsolete-selection tests below: with the same
        # picker flow but no later authoritative projection, the assignment is
        # requested for the picked area.
        self._assert_picker_rejects_obsolete_selection(
            reuse_uid=False, late_projection=False
        )

    def test_cancel_after_external_area_clear_does_not_repeat_assignment(self):
        self._assert_picker_rejects_obsolete_selection(
            reuse_uid=False, cancel_empty=True
        )

    def _run_area_picker(self, *, preselect, deleted, refreshed, accepted, picked=""):
        """Open the Areas picker over the real page-settings bar, save `deleted`
        (the authoritative list becomes `refreshed`), then close it; returns the
        recorded area-change requests."""
        case = self.case
        bar = case.bar
        original = [
            surface_fixture.BidArea("a1", "1", "", "Area A", 1),
            surface_fixture.BidArea("a2", "1", "", "Area B", 2),
        ]
        bar._load_areas_fn = Mock(return_value=original)
        bar._save_areas_fn = lambda *_args, **_kwargs: {}
        bar._refresh_areas_fn = Mock(return_value=refreshed)
        bar.area_combo.set_current_area_uid(preselect)
        self.assertEqual(bar.area_combo.get_current_area_uid(), preselect)
        bar.area_change_requested.disconnect(case.coordinator._on_page_area_changed)
        assignment = Mock()
        bar.area_change_requested.connect(assignment)

        class Picker(QtWidgets.QDialog):
            def __init__(self, *, parent, save_fn, on_saved_fn, **_kwargs):
                super().__init__(parent)
                self.save_fn = save_fn
                self.on_saved_fn = on_saved_fn

            def get_selected_uid(self):
                return picked

            def cleanup(self):
                pass

        def execute(picker, _bus):
            picker.save_fn(SimpleNamespace(deleted_uids=deleted))
            picker.on_saved_fn()
            return (
                QtWidgets.QDialog.DialogCode.Accepted
                if accepted
                else QtWidgets.QDialog.DialogCode.Rejected
            )

        module = "ost_visualizer.presentation.components.page_settings_bar"
        with patch(module + ".BidAreaPickerDialog", Picker), patch(
            module + ".exec_with_ost_blocking", execute
        ):
            bar._on_area_browse()
        return assignment

    def test_area_picker_cancel_without_deletion_keeps_area_and_assigns_nothing(self):
        case = self.case
        remaining = [
            surface_fixture.BidArea("a1", "1", "", "Area A", 1),
            surface_fixture.BidArea("a2", "1", "", "Area B", 2),
        ]
        assignment = self._run_area_picker(
            preselect="a2", deleted=[], refreshed=remaining, accepted=False
        )
        assignment.assert_not_called()
        self.assertEqual(case.bar.area_combo.get_current_area_uid(), "a2")

    def test_area_picker_cancel_after_deleting_current_area_clears_assignment(self):
        case = self.case
        assignment = self._run_area_picker(
            preselect="a2",
            deleted=["a2"],
            refreshed=[surface_fixture.BidArea("a1", "1", "", "Area A", 1)],
            accepted=False,
        )
        self.assertEqual(case.bar.area_combo.get_current_area_uid(), "")
        assignment.assert_called_once_with(
            case.bid_ref.file_path, case.data.page.uid, ""
        )

    def test_area_picker_selection_removed_by_its_own_save_is_not_assigned(self):
        case = self.case
        assignment = self._run_area_picker(
            preselect="",
            deleted=["a1"],
            refreshed=[surface_fixture.BidArea("a2", "1", "", "Area B", 2)],
            accepted=True,
            picked="a1",
        )
        assignment.assert_not_called()
        self.assertEqual(case.bar.area_combo.get_current_area_uid(), "")

    def _assert_picker_rejects_obsolete_selection(
        self, *, reuse_uid, reentrant=False, cancel_empty=False, late_projection=True
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

            if reentrant and late_projection:
                bar.presentation_state_changed.connect(project_later_state)
            picker.on_saved_fn()
            if not reentrant and late_projection:
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
        if not late_projection:
            assignment.assert_called_once_with(
                case.bid_ref.file_path, case.data.page.uid, "a1"
            )
            return
        assignment.assert_not_called()
        self.assertEqual(
            bar.area_combo.get_current_area_uid(), "" if cancel_empty else "a2"
        )
