import os
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.coordinators.viewer_sync_coordinator import (
    _RemotePlanIdentity,
)
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from PySide6 import QtCore, QtWidgets
import tests.integration.surfaces.test_presentation as presentation_tests

VIEW_SIZE = (500, 400)
CENTER_TOLERANCE = 1.5


class ViewportHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    refresh = presentation_tests.CrossSurfacePresentationTests.refresh
    _wait_until = presentation_tests.CrossSurfacePresentationTests._wait_until
    _wait_for_pages_loaded = (
        presentation_tests.CrossSurfacePresentationTests._wait_for_pages_loaded
    )

    def setUp(self):
        presentation_tests.CrossSurfacePresentationTests.setUp(self)
        self.data.page.width_pts = 612.0
        self.data.page.height_pts = 792.0
        self.refresh()
        self.coordinator._sidebar = SimpleNamespace(
            update_conditions_quantities=lambda: None,
            load_condition_summary_from_memory=lambda: None,
        )
        self.coordinator._update_page_settings_bar = lambda _page_uid: None
        self.state.active_page_uid = self.data.page.uid
        self.main = self.main_plan
        self.side = self.detached.plan_view
        self.main.resize(*VIEW_SIZE)
        self.main.show()
        self.detached.resize(*VIEW_SIZE)
        self.detached.show()
        self._wait_for_pages_loaded()
        self.app.processEvents()

    @staticmethod
    def viewport_of(view):
        center = view.get_precise_viewport_scene_center()
        return {
            "m11": view.transform().m11(),
            "h": view.horizontalScrollBar().value(),
            "v": view.verticalScrollBar().value(),
            "x": center.x(),
            "y": center.y(),
        }

    def assert_same_viewport(self, before, after, label):
        self.assertAlmostEqual(before["m11"], after["m11"], places=6, msg=label)
        self.assertAlmostEqual(
            before["x"], after["x"], delta=CENTER_TOLERANCE, msg=label
        )
        self.assertAlmostEqual(
            before["y"], after["y"], delta=CENTER_TOLERANCE, msg=label
        )
        self.assertLessEqual(abs(before["h"] - after["h"]), 2, label)
        self.assertLessEqual(abs(before["v"] - after["v"]), 2, label)

    def scroll_without_publishing(self, view, zoom_steps=3):
        for _ in range(zoom_steps):
            view.zoom_in()
        view.verticalScrollBar().setValue(view.verticalScrollBar().maximum() // 2)
        view.horizontalScrollBar().setValue(view.horizontalScrollBar().maximum() // 3)
        self.app.processEvents()

    def zoom_detached_to_a_section(self):
        for _ in range(7):
            self.side.zoom_in()
        self.side.verticalScrollBar().setValue(
            self.side.verticalScrollBar().maximum() // 4
        )
        self.side.horizontalScrollBar().setValue(
            self.side.horizontalScrollBar().maximum() // 2
        )
        self.app.processEvents()

    def write_scale(self, sf1, sf2):
        page = self.data.page
        page.scale_factor1 = sf1
        page.scale_factor2 = sf2
        return page

    def publish_scale_event(self, *, main_first=True):
        event = dict(
            database_id=self.bid_ref.file_path,
            bid_uid=self.bid_ref.bid_uid,
            page_uids=(self.data.page.uid,),
            changed_fields=("scale",),
        )
        if main_first:
            self.coordinator._on_page_metadata_changed(**event)
            self.bus.publish(AppEvents.PAGE_METADATA_CHANGED, **event)
        else:
            self.bus.publish(AppEvents.PAGE_METADATA_CHANGED, **event)
            self.coordinator._on_page_metadata_changed(**event)
        self._wait_for_pages_loaded()
        self.app.processEvents()


class MainViewKeepsItsViewportOnScaleChangeTests(ViewportHarness):
    def test_scrolled_main_view_does_not_jump_back_after_a_scale_change(self):
        self.detached.hide()
        self.manager._window = None
        self.scroll_without_publishing(self.main)
        before = self.viewport_of(self.main)
        self.assertGreater(before["v"], 0)
        self.write_scale(1.0, 144.0)
        self.coordinator._on_page_metadata_changed(
            database_id=self.bid_ref.file_path,
            bid_uid=self.bid_ref.bid_uid,
            page_uids=(self.data.page.uid,),
            changed_fields=("scale",),
        )
        self._wait_for_pages_loaded()
        self.assert_same_viewport(before, self.viewport_of(self.main), "main")

    def test_main_view_keeps_its_viewport_while_a_detached_window_shows_a_section(
        self,
    ):
        self.scroll_without_publishing(self.main)
        self.zoom_detached_to_a_section()
        before_main = self.viewport_of(self.main)
        before_side = self.viewport_of(self.side)
        self.assertNotAlmostEqual(before_main["m11"], before_side["m11"], places=3)
        self.write_scale(1.0, 144.0)
        self.publish_scale_event(main_first=True)
        self.assert_same_viewport(before_main, self.viewport_of(self.main), "main")
        self.assert_same_viewport(before_side, self.viewport_of(self.side), "detached")

    def test_viewports_are_kept_when_the_detached_window_refreshes_first(self):
        self.scroll_without_publishing(self.main)
        self.zoom_detached_to_a_section()
        before_main = self.viewport_of(self.main)
        before_side = self.viewport_of(self.side)
        self.write_scale(1.0, 144.0)
        self.publish_scale_event(main_first=False)
        self.assert_same_viewport(before_main, self.viewport_of(self.main), "main")
        self.assert_same_viewport(before_side, self.viewport_of(self.side), "detached")

    def test_scale_change_started_from_the_detached_window_moves_neither_view(self):
        self.scroll_without_publishing(self.main)
        self.zoom_detached_to_a_section()
        before_main = self.viewport_of(self.main)
        before_side = self.viewport_of(self.side)
        requested = []

        def write_like_the_coordinator(page_uid, sf1, sf2):
            requested.append((page_uid, sf1, sf2))
            self.write_scale(sf1, sf2)
            self.publish_scale_event(main_first=True)

        self.detached._on_scale_changed = write_like_the_coordinator
        self.detached._on_scale_changed(self.data.page.uid, 1.0, 144.0)
        self.assertEqual(requested, [(self.data.page.uid, 1.0, 144.0)])
        self.assert_same_viewport(before_main, self.viewport_of(self.main), "main")
        self.assert_same_viewport(before_side, self.viewport_of(self.side), "detached")

    def test_repeated_scale_changes_keep_both_viewports(self):
        self.scroll_without_publishing(self.main)
        self.zoom_detached_to_a_section()
        before_main = self.viewport_of(self.main)
        before_side = self.viewport_of(self.side)
        for sf2 in (144.0, 96.0, 72.0):
            self.write_scale(1.0, sf2)
            self.publish_scale_event(main_first=True)
        self.assert_same_viewport(before_main, self.viewport_of(self.main), "main")
        self.assert_same_viewport(before_side, self.viewport_of(self.side), "detached")

    def test_main_view_ignores_state_written_to_the_shared_page_during_a_reload(self):
        self.scroll_without_publishing(self.main)
        before_main = self.viewport_of(self.main)
        page = self.write_scale(1.0, 144.0)
        self.main.setVisible(False)
        self.coordinator._on_page_metadata_changed(
            database_id=self.bid_ref.file_path,
            bid_uid=self.bid_ref.bid_uid,
            page_uids=(page.uid,),
            changed_fields=("scale",),
        )
        page.zoom_fac = 0.9
        page.current_x = 100.0
        page.current_y = 100.0
        self.main.setVisible(True)
        self._wait_for_pages_loaded()
        self.app.processEvents()
        self.assert_same_viewport(before_main, self.viewport_of(self.main), "main")


class AppearanceChangesKeepTheViewportTests(ViewportHarness):
    def reload_main_with(self, **page_changes):
        page = self.data.page
        for name, value in page_changes.items():
            setattr(page, name, value)
        self.viewer.update_plan_view(page.uid, force_overlay_refresh=True)
        self._wait_for_pages_loaded()
        self.app.processEvents()

    def assert_change_keeps_the_viewport(self, **changes):
        self.scroll_without_publishing(self.main)
        before = self.viewport_of(self.main)
        self.assertGreater(before["v"], 0)
        self.reload_main_with(**changes)
        self.assert_same_viewport(before, self.viewport_of(self.main), "main")

    def test_invert_keeps_the_viewport(self):
        self.assert_change_keeps_the_viewport(invert=True)

    def test_bitonal_keeps_the_viewport(self):
        self.assert_change_keeps_the_viewport(bitonal=True)

    def test_show_mode_keeps_the_viewport(self):
        self.assert_change_keeps_the_viewport(image_show_mode=1)

    def test_overlay_rect_keeps_the_viewport(self):
        self.assert_change_keeps_the_viewport(overlay_rect=(1.0, 2.0, 30.0, 40.0))

    def test_overlay_rotation_keeps_the_viewport(self):
        self.assert_change_keeps_the_viewport(overlay_rotation=1.5)

    def test_page_switch_still_restores_the_stored_page_state(self):
        page = self.data.page
        self.scroll_without_publishing(self.main)
        stored = self.main.get_view_state()
        self.main.clear()
        page.zoom_fac, page.current_x, page.current_y = stored
        self.viewer.update_plan_view(page.uid)
        self._wait_for_pages_loaded()
        restored = self.main.get_view_state()
        self.assertAlmostEqual(restored[0], stored[0], places=5)
        self.assertAlmostEqual(restored[1], stored[1], delta=1.0)
        self.assertAlmostEqual(restored[2], stored[2], delta=1.0)

    def test_geometry_changing_reloads_still_use_the_stored_page_state(self):
        page = self.data.page
        self.scroll_without_publishing(self.main)
        page.zoom_fac, page.current_x, page.current_y = self.main.get_view_state()
        stored = (page.zoom_fac, page.current_x, page.current_y)
        self.main.verticalScrollBar().setValue(0)
        self.app.processEvents()
        page.flip_x = True
        self.viewer.update_plan_view(page.uid, force_overlay_refresh=True)
        self._wait_for_pages_loaded()
        restored = self.main.get_view_state()
        self.assertAlmostEqual(restored[0], stored[0], places=5)
        self.assertAlmostEqual(restored[2], stored[2], delta=1.0)


class DetachedWindowDoesNotWriteIntoTheSharedPageTests(ViewportHarness):
    def stored(self):
        page = self.data.page
        return (page.zoom_fac, page.current_x, page.current_y)

    def test_detached_zoom_does_not_change_the_page_state_the_main_view_restores(
        self,
    ):
        page = self.data.page
        self.scroll_without_publishing(self.main)
        page.zoom_fac, page.current_x, page.current_y = self.main.get_view_state()
        saved = self.stored()
        self.zoom_detached_to_a_section()
        self.assertEqual(self.stored(), saved)

    def test_main_view_returns_to_its_own_camera_after_a_page_switch(self):
        page = self.data.page
        other = Page(uid="page-2", name="Page 2", width_pts=612.0, height_pts=792.0)
        self.data.get_page = lambda uid: page if uid == page.uid else other
        self.scroll_without_publishing(self.main)
        own = self.main.get_view_state()
        page.zoom_fac, page.current_x, page.current_y = own
        self.main.load_page(
            page=other, takeoffs=[], conditions={}, color_map={}, bid_ref=self.bid_ref
        )
        self._wait_for_pages_loaded()
        self.zoom_detached_to_a_section()
        self.main.load_page(
            page=page, takeoffs=[], conditions={}, color_map={}, bid_ref=self.bid_ref
        )
        self._wait_for_pages_loaded()
        returned = self.main.get_view_state()
        self.assertAlmostEqual(returned[0], own[0], places=5)
        self.assertAlmostEqual(returned[1], own[1], delta=1.0)
        self.assertAlmostEqual(returned[2], own[2], delta=1.0)

    def test_detached_window_keeps_its_camera_across_a_geometry_changing_refresh(
        self,
    ):
        self.zoom_detached_to_a_section()
        before = self.viewport_of(self.side)
        saved = self.stored()
        self.data.page.flip_x = True
        self.manager.refresh_active_view()
        self._wait_for_pages_loaded()
        self.assertEqual(self.stored(), saved)
        self.assert_same_viewport(before, self.viewport_of(self.side), "detached")

    def test_main_view_state_is_still_stored_on_the_page_when_the_main_view_moves(
        self,
    ):
        self.scroll_without_publishing(self.main)
        self.main.zoom_in()
        stored = self.stored()
        self.assertEqual(stored[0], self.main.get_view_state()[0])
        self.assertGreater(stored[0], 0)


class ViewStateOwnershipContractTests(ViewportHarness):
    def identity(self, **overrides):
        identity = dict(self.main._current_render_identity)
        identity.update(overrides)
        return identity

    def test_only_appearance_and_calibration_changes_keep_the_view(self):
        keeping = {
            "show_mode": 1,
            "invert": True,
            "bitonal": True,
            "overlay_units_per_sheet_inch": 99.0,
            "overlay_rect": (9.0, 9.0, 9.0, 9.0),
            "overlay_rotation": 3.0,
            "overlay_deskew": 1.0,
        }
        for key, value in keeping.items():
            with self.subTest(keeping=key):
                self.assertTrue(
                    self.main._identity_change_keeps_view(self.identity(**{key: value}))
                )
        changing = {
            "page_uid": "other",
            "page_index": 9,
            "image_path": "other.pdf",
            "overlay_image_path": "overlay.tif",
            "image_signature": "changed",
            "overlay_signature": "changed",
            "rotation": 90,
            "flip_x": True,
            "flip_y": True,
            "width_pts": 1.0,
            "height_pts": 1.0,
            "bid_ref": None,
        }
        for key, value in changing.items():
            with self.subTest(changing=key):
                self.assertFalse(
                    self.main._identity_change_keeps_view(self.identity(**{key: value}))
                )
        self.assertTrue(self.main._identity_change_keeps_view(self.identity()))

    def test_identity_comparison_needs_a_loaded_page_with_the_same_fields(self):
        identity = self.identity()
        loaded = dict(identity)
        identity.pop("invert")
        self.assertFalse(self.main._identity_change_keeps_view(identity))
        self.main.clear()
        self.assertFalse(self.main._identity_change_keeps_view(loaded))

    def test_a_view_that_does_not_own_the_page_state_publishes_without_storing_it(
        self,
    ):
        page = self.data.page
        page.zoom_fac, page.current_x, page.current_y = 0.5, 11.0, 12.0
        published = []
        self.side.page_view_state_changed.connect(
            lambda *state: published.append(state)
        )
        self.side.zoom_in()
        self.assertEqual(
            (page.zoom_fac, page.current_x, page.current_y), (0.5, 11.0, 12.0)
        )
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0][0], page.uid)
        self.assertEqual(published[0][1:], self.side.get_view_state())

    def test_an_owning_view_stores_the_state_it_publishes(self):
        page = self.data.page
        published = []
        self.main.page_view_state_changed.connect(
            lambda *state: published.append(state)
        )
        self.main.zoom_in()
        self.assertEqual(
            (page.zoom_fac, page.current_x, page.current_y), published[-1][1:]
        )
        self.assertEqual(published[-1][1:], self.main.get_view_state())

    def test_state_handed_to_the_next_load_wins_once_and_is_then_consumed(self):
        page = self.data.page
        self.zoom_detached_to_a_section()
        handed = self.side.get_view_state()
        for _ in range(4):
            self.side.zoom_out()
        self.side.set_view_state_for_next_load(handed)
        page.flip_x = True
        self.side.load_page(
            page=page, takeoffs=[], conditions={}, color_map={}, bid_ref=self.bid_ref
        )
        self._wait_for_pages_loaded()
        restored = self.side.get_view_state()
        self.assertAlmostEqual(restored[0], handed[0], places=5)
        self.assertIsNone(self.side._pending_load_view_state)
        self.assertIsNone(self.side._preserved_view_state)

    def test_a_non_positive_state_handed_to_the_next_load_is_ignored(self):
        self.side.set_view_state_for_next_load((0.0, 1.0, 1.0))
        self.main.set_view_state_for_next_load((0.0, 1.0, 1.0))
        self.data.page.flip_x = True
        self.viewer.update_plan_view(self.data.page.uid, force_overlay_refresh=True)
        self._wait_for_pages_loaded()
        self.assertIsNone(self.main._pending_load_view_state)
        self.assertIsNone(self.main._preserved_view_state)

    def test_the_preserved_state_is_dropped_by_the_next_load_that_does_not_keep_it(
        self,
    ):
        self.scroll_without_publishing(self.main)
        self.write_scale(1.0, 144.0)
        self.viewer.update_plan_view(self.data.page.uid, force_overlay_refresh=True)
        self._wait_for_pages_loaded()
        self.assertIsNone(self.main._preserved_view_state)
        self.main._preserved_view_state = (9.0, 9.0, 9.0)
        self.main.clear()
        self.viewer.update_plan_view(self.data.page.uid)
        self._wait_for_pages_loaded()
        self.assertIsNone(self.main._preserved_view_state)


class LoadCycleViewStateTests(ViewportHarness):
    def begin(self, *, preserve):
        self.main._begin_load_cycle(self.data.page, preserve_current_view=preserve)

    def test_preserving_captures_the_live_state_of_this_view(self):
        self.scroll_without_publishing(self.main)
        live = self.main.get_view_state()
        self.begin(preserve=True)
        self.assertEqual(self.main._preserved_view_state, live)
        self.assertEqual(self.main._load_initial_view_mode, "restore")

    def test_state_handed_in_beats_the_live_state_when_preserving(self):
        self.scroll_without_publishing(self.main)
        handed = (0.5, 11.0, 12.0)
        self.main.set_view_state_for_next_load(handed)
        self.begin(preserve=True)
        self.assertEqual(self.main._preserved_view_state, handed)
        self.assertIsNone(self.main._pending_load_view_state)

    def test_state_handed_in_applies_without_preserving(self):
        handed = (0.5, 11.0, 12.0)
        self.main.set_view_state_for_next_load(handed)
        self.begin(preserve=False)
        self.assertEqual(self.main._preserved_view_state, handed)
        self.assertEqual(self.main._load_initial_view_mode, "restore")

    def test_a_non_positive_state_handed_in_is_discarded_and_the_page_state_is_used(
        self,
    ):
        page = self.data.page
        page.zoom_fac, page.current_x, page.current_y = 0.4, 5.0, 6.0
        self.main.set_view_state_for_next_load((0.0, 1.0, 1.0))
        self.begin(preserve=False)
        self.assertIsNone(self.main._preserved_view_state)
        self.assertIsNone(self.main._pending_load_view_state)
        self.assertEqual(self.main._load_initial_view_mode, "restore")
        self.assertEqual(self.main._view_state_to_restore(), (0.4, 5.0, 6.0))

    def test_a_snapshot_left_by_an_earlier_load_never_reaches_the_next_one(self):
        self.main._preserved_view_state = (9.0, 9.0, 9.0)
        self.begin(preserve=False)
        self.assertIsNone(self.main._preserved_view_state)

    def test_an_unreadable_live_state_falls_back_to_the_stored_page_state(self):
        page = self.data.page
        page.zoom_fac, page.current_x, page.current_y = 0.4, 5.0, 6.0
        with patch.object(
            self.main, "get_precise_viewport_scene_center", return_value=None
        ):
            self.begin(preserve=True)
        self.assertIsNone(self.main._preserved_view_state)
        self.assertEqual(self.main._view_state_to_restore(), (0.4, 5.0, 6.0))
        self.assertEqual(self.main._load_initial_view_mode, "restore")


class OtherPageUpdatePathsKeepTheViewportTests(ViewportHarness):
    def test_a_remote_sql_page_update_keeps_the_viewport_and_the_detached_camera(self):
        self.scroll_without_publishing(self.main)
        self.zoom_detached_to_a_section()
        before_main = self.viewport_of(self.main)
        before_side = self.viewport_of(self.side)
        self.write_scale(1.0, 144.0)
        identity = _RemotePlanIdentity(
            database_id=self.bid_ref.file_path,
            bid_uid=self.bid_ref.bid_uid,
            page_uid=self.data.page.uid,
            surface_id="main-plan",
            update_generation=1,
            barrier=SimpleNamespace(),
        )
        snapshot = self.viewer._capture_plan_update(
            self.data.page.uid, remote_identity=identity
        )
        self.assertIsNot(snapshot.page, self.data.page)
        self.viewer._apply_plan_update(self.viewer._prepare_plan_update(snapshot))
        self.bus.publish(
            AppEvents.PAGE_METADATA_CHANGED,
            database_id=self.bid_ref.file_path,
            bid_uid=self.bid_ref.bid_uid,
            page_uids=(self.data.page.uid,),
            changed_fields=("scale",),
        )
        self._wait_for_pages_loaded()
        self.assert_same_viewport(before_main, self.viewport_of(self.main), "main")
        self.assert_same_viewport(before_side, self.viewport_of(self.side), "detached")

    def test_a_reloaded_page_object_with_stale_stored_state_keeps_the_viewport(self):
        self.scroll_without_publishing(self.main)
        before = self.viewport_of(self.main)
        reloaded = deepcopy(self.data.page)
        reloaded.zoom_fac, reloaded.current_x, reloaded.current_y = 0.9, 50.0, 60.0
        reloaded.scale_factor1, reloaded.scale_factor2 = 1.0, 144.0
        self.data.page = reloaded
        self.viewer.update_plan_view(reloaded.uid)
        self._wait_for_pages_loaded()
        self.assert_same_viewport(before, self.viewport_of(self.main), "main")

    def test_zoom_and_fit_after_a_scale_change_work_from_the_kept_viewport(self):
        self.scroll_without_publishing(self.main)
        self.write_scale(1.0, 144.0)
        self.publish_scale_event()
        kept = self.viewport_of(self.main)
        self.main.zoom_in()
        zoomed = self.viewport_of(self.main)
        self.assertGreater(zoomed["m11"], kept["m11"])
        self.assertAlmostEqual(zoomed["x"], kept["x"], delta=3.0)
        self.assertAlmostEqual(zoomed["y"], kept["y"], delta=3.0)
        self.main.reset_view()
        self.assertLess(self.main.transform().m11(), kept["m11"])

    def test_renaming_a_page_does_not_touch_either_viewport(self):
        self.scroll_without_publishing(self.main)
        self.zoom_detached_to_a_section()
        before_main = self.viewport_of(self.main)
        before_side = self.viewport_of(self.side)
        self.data.page.name = "Renamed"
        self.viewer.update_plan_view(self.data.page.uid, force_overlay_refresh=True)
        self.manager.refresh_active_view()
        self._wait_for_pages_loaded()
        self.assert_same_viewport(before_main, self.viewport_of(self.main), "main")
        self.assert_same_viewport(before_side, self.viewport_of(self.side), "detached")


if __name__ == "__main__":
    unittest.main()
