import os
import unittest
from dataclasses import replace
from pathlib import Path
from types import MethodType, SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.remote_projection_dtos import (
    RemoteProjectionBarrier,
)
from ost_visualizer.presentation.coordinators.toolbar_state_coordinator import (
    ToolbarStateCoordinator,
)
from ost_visualizer.presentation.coordinators.viewer_sync_coordinator import (
    ViewerSyncCoordinator,
)
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from ost_visualizer.presentation.utils.plan_tool_registry import (
    PAGE_SELECTOR_ITEM,
    PAGE_SETTINGS_ITEM,
    PLAN_ANNOTATION_TOOL_SPECS,
    TAKEOFF_TOOLBAR_ITEMS,
    ZOOM_SELECTOR_ITEM,
)
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
import tests.integration.surfaces.test_presentation as cross_surface
import tests.presentation.coordinators.test_remote_plan_update_pipeline as remote_tests
import tests.presentation.coordinators.test_toolbar_state_coordinator as state_tests
from tests.presentation.components.toolbar_visibility_support import (
    register_test_fonts as _toolbar_visibility_support_register_test_fonts,
)


class TakeoffToolbarVisibilityTests(unittest.TestCase):
    _main_components = cross_surface.SceneControlPresentationTests._main_components

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        _toolbar_visibility_support_register_test_fonts()

    def setUp(self):
        self.bundle, self.zoom = self._main_components()
        self.controller = self.bundle.takeoff_toolbar_visibility
        self.toolbar = self.controller.parent()
        self.controller.apply_hidden_items(())

    def item(self, key):
        result = self.toolbar.findChild(QtWidgets.QWidgetAction, key)
        self.assertIsNotNone(result)
        return result

    def assert_only_hidden_items_are_invisible(self, hidden):
        # Exact oracle for every catalog item: hidden ones are gone and, as the
        # positive control, every other item is still visible.
        self.assertEqual(
            {
                spec.key: self.item(spec.key).isVisible()
                for spec in TAKEOFF_TOOLBAR_ITEMS
            },
            {spec.key: spec.key not in hidden for spec in TAKEOFF_TOOLBAR_ITEMS},
        )
        self.assertFalse(self.toolbar.isHidden())

    def test_navigation_replacement_clear_and_view_refresh_retain_visibility(self):
        hidden = ("line_annotation_tool", PAGE_SETTINGS_ITEM, ZOOM_SELECTOR_ITEM)
        self.controller.apply_hidden_items(hidden)
        for transition in ("page", "bid", "clear", "reload"):
            with self.subTest(transition=transition):
                if transition == "page":
                    self.main_data.page = replace(self.main_data.page, uid="page-2")
                if transition == "bid":
                    self.main_data.bid = replace(self.main_data.bid)
                if transition == "clear":
                    self.main_sync.clear_plan_view()
                else:
                    self.main_data.bid.pages_without_folder = [self.main_data.page]
                    self.main_state.active_page_uid = self.main_data.page.uid
                    self.main_sync.update_plan_view(self.main_data.page.uid)
                self.bundle.view_stack.setCurrentIndex(1)
                self.bundle.view_stack.setCurrentIndex(0)
                self.app.processEvents()
                self.assert_only_hidden_items_are_invisible(hidden)

    def test_access_and_tool_refresh_keep_visibility_independent(self):
        access = state_tests._SelectiveAccess(
            {Feature.PLACE_ANNOTATIONS, Feature.SELECT_PLAN_ITEMS}
        )
        coordinator = ToolbarStateCoordinator(
            state_tests._UiState(
                active_page_uid=self.bundle.plan_view.current_page_uid
            ),
            access,
            state_tests._ProjectData(),
        )
        self.addCleanup(coordinator.cleanup)
        coordinator.set_plan_view(self.bundle.plan_view)
        coordinator.set_tab_widget(
            state_tests._IndexWidget(state_tests.TAB_INDEX_TAKEOFF)
        )
        coordinator.set_view_stack(state_tests._IndexWidget(1))
        line = self.bundle.plan_tool_actions["line_annotation_tool"]
        coordinator.set_annotation_tool_actions([line])
        coordinator.set_select_action(self.bundle.plan_tool_actions["select_tool"])
        self.controller.apply_hidden_items(("line_annotation_tool",))
        coordinator.refresh()
        self.assertTrue(line.isEnabled())
        access.allowed.clear()
        coordinator.refresh()
        self.assertFalse(line.isEnabled())
        self.assert_only_hidden_items_are_invisible(("line_annotation_tool",))
        self.controller.apply_hidden_items(())
        self.assert_only_hidden_items_are_invisible(())
        self.assertFalse(line.isEnabled())
        access.allowed.update({Feature.PLACE_ANNOTATIONS, Feature.SELECT_PLAN_ITEMS})
        coordinator.refresh()
        self.assertTrue(line.isEnabled())

    def test_hiding_every_item_hides_the_toolbar_and_any_item_restores_it(self):
        every_key = tuple(spec.key for spec in TAKEOFF_TOOLBAR_ITEMS)
        self.controller.apply_hidden_items(every_key)
        self.assertTrue(self.toolbar.isHidden())
        self.assertTrue(all(not self.item(key).isVisible() for key in every_key))
        self.controller.apply_hidden_items(every_key[:-1])
        self.assertFalse(self.toolbar.isHidden())
        self.assertTrue(self.item(every_key[-1]).isVisible())
        self.controller.apply_hidden_items(())
        self.assert_only_hidden_items_are_invisible(())

    def test_navigation_spacer_needs_visible_items_on_both_sides(self):
        spacer = self.controller._navigation_spacer
        group = "Page navigation"
        navigation = tuple(s.key for s in TAKEOFF_TOOLBAR_ITEMS if s.group == group)
        others = tuple(s.key for s in TAKEOFF_TOOLBAR_ITEMS if s.group != group)
        self.assertTrue(navigation and others)
        self.assertTrue(spacer.isVisible())
        self.controller.apply_hidden_items(navigation)
        self.assertFalse(spacer.isVisible())
        self.controller.apply_hidden_items(others)
        self.assertFalse(spacer.isVisible())
        self.controller.apply_hidden_items(navigation[:-1] + others[:-1])
        self.assertTrue(spacer.isVisible())

    @staticmethod
    def held_widgets(action):
        held = action.createdWidgets()
        if action.defaultWidget() is not None:
            held.append(action.defaultWidget())
        return held

    def widget_states(self):
        return {
            spec.key: tuple(
                widget.isEnabled() for widget in self.held_widgets(self.item(spec.key))
            )
            for spec in TAKEOFF_TOOLBAR_ITEMS
        }

    def test_hiding_and_showing_keeps_widget_level_disabled_state(self):
        # A plain widget action and an overflow action: the widget itself, not
        # the action, is disabled and must come back disabled, while the enabled
        # state of every other item is untouched by the cycle.
        baseline = self.widget_states()
        for key in ("page_selector", "line_annotation_tool"):
            with self.subTest(item=key):
                widget = self.held_widgets(self.item(key))[0]
                self.assertTrue(baseline[key][0])
                widget.setEnabled(False)
                self.controller.apply_hidden_items((key,))
                self.assertFalse(self.item(key).isVisible())
                self.controller.apply_hidden_items(())
                self.assertTrue(self.item(key).isVisible())
                states = self.widget_states()
                self.assertFalse(widget.isEnabled())
                self.assertEqual(
                    {k: v for k, v in states.items() if k != key},
                    {k: v for k, v in baseline.items() if k != key},
                )
                widget.setEnabled(True)
                self.assertEqual(self.widget_states(), baseline)

    def test_deferred_remote_projection_retains_hidden_widgets(self):
        bridge = remote_tests._QueuedBridge()
        pool = remote_tests._ManualThreadPool()
        viewer = ViewerSyncCoordinator(
            self.main_state,
            SimpleNamespace(is_allowed=lambda _feature: True),
            cross_surface.FakeColorService(),
            self.main_data,
            bridge,
            pool,
        )
        viewer.plan_view = self.bundle.plan_view
        self.addCleanup(viewer.cleanup)
        ref = self.main_state.get_selected_bid_ref()
        completed = []
        barrier = RemoteProjectionBarrier(
            database_id=ref.file_path,
            runtime_generation=1,
            is_runtime_current=lambda _database, _generation: True,
            on_complete=lambda _success: None,
        )
        self.assertTrue(
            viewer.request_remote_plan_update(
                database_id=ref.file_path,
                bid_uid=ref.bid_uid,
                runtime_generation=1,
                resource_uids_by_family={"takeoffs": ()},
                barrier=barrier,
                completion=completed.append,
            )
        )
        hidden = (PAGE_SELECTOR_ITEM, ZOOM_SELECTOR_ITEM, "line_annotation_tool")
        self.controller.apply_hidden_items(hidden)
        pool.run_next()
        callback, payload = bridge.callbacks.pop(0)
        callback(payload)
        self.assertEqual(completed, [True])
        self.assert_only_hidden_items_are_invisible(hidden)
