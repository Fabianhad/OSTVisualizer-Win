import json
import logging
import os
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.config.di_config import configure_application
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.infrastructure.logging.logger_factory import LoggerFactory
from ost_visualizer.presentation.actions.action_ids import (
    ACTION_CONDITIONS_SIDEBAR,
    ACTION_LAYERS_SIDEBAR,
    ACTION_PAN_SIDEBAR,
)
from ost_visualizer.presentation.config import (
    PAN_SIDEBAR_DEFAULT_HEIGHT,
    TAB_INDEX_TAKEOFF,
)
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.managers.icon_manager import IconId, IconManager
from PySide6 import QtCore, QtGui, QtWidgets


def view_menu_actions(window):
    for action in window.menuBar().actions():
        if action.text().replace("&", "") == "View":
            return [item for item in action.menu().actions() if not item.isSeparator()]
    raise AssertionError("View menu not found")


class PanSidebarWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.state_path = self.home / ".ost_visualizer" / "workspace_state.json"

    @contextmanager
    def window(self):
        win = None
        controller = None
        with ExitStack() as stack:
            stack.enter_context(patch.object(Path, "home", return_value=self.home))
            stack.enter_context(patch.object(LoggerFactory, "configure"))
            stack.enter_context(
                patch.object(
                    LoggerFactory,
                    "get_logger",
                    return_value=logging.getLogger("test.pan_sidebar.workspace"),
                )
            )
            stack.enter_context(patch.object(QtCore.QTimer, "singleShot"))
            stack.enter_context(
                patch(
                    "ost_visualizer.presentation.utils.annotation_defaults."
                    "resolve_font_definition",
                    side_effect=lambda definition: definition,
                )
            )
            try:
                container = configure_application(log_dir=self.home / "logs")
                controller = container.get("app_controller")
                win = MainWindow(controller)
                win.resize(1200, 800)
                yield win
            finally:
                if win is not None:
                    win._workspace_state_coordinator.cleanup()
                    win.event_coordinator.cleanup()
                    win.handlers.ui_event.cleanup()
                    win.license_coordinator.cleanup()
                    win.ui_access_manager.cleanup()
                    win._mcp_context_bridge.cleanup()
                    win.hide()
                    win.deleteLater()
                if controller is not None:
                    controller.cleanup()
                if win is not None:
                    self.app.sendPostedEvents(win, QtCore.QEvent.Type.DeferredDelete)

    def saved_takeoff_workspace(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))[
            "takeoff_workspace"
        ]

    def test_the_main_plan_view_is_bound_and_the_pan_sidebar_starts_hidden(self):
        with self.window() as win:
            self.assertFalse(win.is_pan_sidebar_visible())
            self.assertFalse(win.get_pan_toggle_action().isChecked())
            self.assertIs(win._pan_sidebar._plan_view, win.plan_view)
            self.assertIs(win.get_left_column_splitter().widget(0), win._pan_sidebar)
            left = win.get_left_splitter()
            self.assertIs(win.get_left_column_splitter().widget(1), left)
            self.assertIs(left.widget(0), win._conditions_sidebar)
            self.assertIs(left.widget(1), win._bid_layers_sidebar)
            self.assertEqual(left.minimumWidth(), 320)

    def test_the_button_the_menu_and_the_setter_stay_in_sync(self):
        with self.window() as win:
            win.show()
            self.app.processEvents()
            toggle = win.get_pan_toggle_action()
            menu_items = view_menu_actions(win)
            menu_pan = [item for item in menu_items if item is toggle]
            self.assertEqual(len(menu_pan), 1)
            toggle.setChecked(True)
            self.assertTrue(win.is_pan_sidebar_visible())
            self.assertFalse(win._pan_sidebar.isHidden())
            self.assertTrue(menu_pan[0].isChecked())
            menu_pan[0].setChecked(False)
            self.assertFalse(win.is_pan_sidebar_visible())
            self.assertFalse(toggle.isChecked())
            win.set_pan_sidebar_visible(True)
            self.assertTrue(toggle.isChecked())
            self.assertFalse(win._pan_sidebar.isHidden())
            win.set_pan_sidebar_visible(False)
            self.assertFalse(toggle.isChecked())
            self.assertTrue(win._pan_sidebar.isHidden())

    def test_the_view_menu_lists_the_sidebars_in_the_toolbar_order(self):
        with self.window() as win:
            by_action = {
                id(win.get_conditions_toggle_action()): ACTION_CONDITIONS_SIDEBAR,
                id(win.get_layers_toggle_action()): ACTION_LAYERS_SIDEBAR,
                id(win.get_pan_toggle_action()): ACTION_PAN_SIDEBAR,
            }
            order = [
                by_action[id(item)]
                for item in view_menu_actions(win)
                if id(item) in by_action
            ]
            self.assertEqual(
                order,
                [ACTION_PAN_SIDEBAR, ACTION_CONDITIONS_SIDEBAR, ACTION_LAYERS_SIDEBAR],
            )

    def test_showing_the_pan_sidebar_with_the_other_sidebars_hidden_shows_the_column(
        self,
    ):
        with self.window() as win:
            win.show()
            win.set_conditions_sidebar_visible(False)
            win.set_layers_sidebar_visible(False)
            self.app.processEvents()
            self.assertTrue(win.get_left_splitter().isHidden())
            self.assertTrue(win.get_left_column_splitter().isHidden())
            win.set_pan_sidebar_visible(True)
            self.app.processEvents()
            self.assertFalse(win.get_left_column_splitter().isHidden())
            self.assertFalse(win._pan_sidebar.isHidden())
            self.assertTrue(win.get_left_splitter().isHidden())
            win.set_pan_sidebar_visible(False)
            self.app.processEvents()
            self.assertTrue(win.get_left_column_splitter().isHidden())

    def test_showing_the_pan_sidebar_restores_a_usable_height(self):
        with self.window() as win:
            win.show()
            win.tab_widget.setCurrentIndex(TAB_INDEX_TAKEOFF)
            self.app.processEvents()
            win.set_pan_sidebar_visible(True)
            self.app.processEvents()
            pan, top = win.get_left_column_splitter_sizes()
            self.assertGreater(top, 0)
            self.assertAlmostEqual(pan, PAN_SIDEBAR_DEFAULT_HEIGHT, delta=2)

    def test_the_pan_sidebar_alone_takes_the_whole_column_height(self):
        with self.window() as win:
            win.show()
            win.tab_widget.setCurrentIndex(TAB_INDEX_TAKEOFF)
            win.set_conditions_sidebar_visible(False)
            win.set_layers_sidebar_visible(False)
            self.app.processEvents()
            win.set_pan_sidebar_visible(True)
            self.app.processEvents()
            pan, top = win.get_left_column_splitter_sizes()
            self.assertEqual(top, 0)
            self.assertGreaterEqual(pan, win.get_left_column_splitter().height() - 2)

    def test_showing_the_pan_sidebar_again_restores_its_last_height(self):
        with self.window() as win:
            win.show()
            win.tab_widget.setCurrentIndex(TAB_INDEX_TAKEOFF)
            self.app.processEvents()
            win.set_pan_sidebar_visible(True)
            self.app.processEvents()
            total = sum(win.get_left_column_splitter_sizes())
            win.set_left_column_splitter_sizes([300, total - 300])
            win.set_pan_sidebar_visible(False)
            self.app.processEvents()
            win.set_pan_sidebar_visible(True)
            self.app.processEvents()
            pan, _top = win.get_left_column_splitter_sizes()
            self.assertAlmostEqual(pan, 300, delta=4)

    def test_visibility_and_vertical_size_persist_across_a_restart(self):
        with self.window() as first:
            first.show()
            self.app.processEvents()
            first.set_pan_sidebar_visible(True)
            self.app.processEvents()
            total = sum(first.get_left_column_splitter_sizes())
            first.set_left_column_splitter_sizes([260, total - 260])
            self.app.processEvents()
            first._workspace_state_coordinator.flush()
            saved = self.saved_takeoff_workspace()
        self.assertIs(saved["pan_sidebar_visible"], True)
        self.assertEqual(len(saved["left_column_pan_first_sizes"]), 2)
        self.assertGreater(saved["left_column_pan_first_sizes"][0], 0)
        with self.window() as second:
            self.assertTrue(second.is_pan_sidebar_visible())
            self.assertTrue(second.get_pan_toggle_action().isChecked())
            second.show()
            self.app.processEvents()
            sizes = second.get_left_column_splitter_sizes()
            self.assertGreater(sizes[0], 0)
            self.assertAlmostEqual(
                sizes[0] / sum(sizes),
                saved["left_column_pan_first_sizes"][0]
                / sum(saved["left_column_pan_first_sizes"]),
                delta=0.15,
            )

    def test_a_hidden_pan_sidebar_persists_as_hidden_and_keeps_its_last_size(self):
        with self.window() as first:
            first.show()
            first.set_pan_sidebar_visible(True)
            self.app.processEvents()
            first._workspace_state_coordinator.flush()
            visible_sizes = self.saved_takeoff_workspace()[
                "left_column_pan_first_sizes"
            ]
            first.set_pan_sidebar_visible(False)
            self.app.processEvents()
            first._workspace_state_coordinator.flush()
            saved = self.saved_takeoff_workspace()
        self.assertIs(saved["pan_sidebar_visible"], False)
        self.assertEqual(saved["left_column_pan_first_sizes"], visible_sizes)
        with self.window() as second:
            self.assertFalse(second.is_pan_sidebar_visible())
            second.set_pan_sidebar_visible(True)
            second.show()
            self.app.processEvents()
            self.assertGreater(second.get_left_column_splitter_sizes()[0], 0)

    def test_old_workspace_files_without_the_keys_start_with_the_sidebar_hidden(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "takeoff_workspace": {
                        "conditions_sidebar_visible": True,
                        "layers_sidebar_visible": False,
                        "left_splitter_sizes": [400, 300],
                    },
                }
            ),
            encoding="utf-8",
        )
        with self.window() as win:
            self.assertFalse(win.is_pan_sidebar_visible())
            self.assertTrue(win.is_conditions_sidebar_visible())
            self.assertFalse(win.is_layers_sidebar_visible())

    def test_toggling_the_pan_toggle_requests_a_workspace_save(self):
        with self.window() as win:
            requests = []
            coordinator = win._workspace_state_coordinator
            with patch.object(
                coordinator._save_timer,
                "start",
                side_effect=lambda *a: requests.append(a),
            ):
                win.get_pan_toggle_action().setChecked(True)
            self.assertTrue(requests)

    def test_moving_the_column_splitter_requests_a_workspace_save(self):
        with self.window() as win:
            requests = []
            coordinator = win._workspace_state_coordinator
            with patch.object(
                coordinator._save_timer,
                "start",
                side_effect=lambda *a: requests.append(a),
            ):
                win.get_left_column_splitter().splitterMoved.emit(10, 1)
            self.assertTrue(requests)

    def test_reset_to_defaults_hides_the_pan_sidebar(self):
        with self.window() as win:
            win.show()
            win.set_pan_sidebar_visible(True)
            self.app.processEvents()
            win._workspace_state_coordinator.reset_to_defaults()
            self.app.processEvents()
            self.assertFalse(win.is_pan_sidebar_visible())

    def write_workspace(self, **takeoff):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps({"schema_version": 3, "takeoff_workspace": takeoff}),
            encoding="utf-8",
        )

    def show_like_startup_then_open_takeoff(self, win):
        with patch.object(
            QtCore.QTimer, "singleShot", side_effect=lambda _delay, callback: callback()
        ):
            win._workspace_state_coordinator.show_main_window()
        self.app.processEvents()
        win.tab_widget.setCurrentIndex(TAB_INDEX_TAKEOFF)
        self.app.processEvents()

    def test_a_file_saved_with_the_pre_reorder_size_key_is_not_read_swapped(self):
        self.write_workspace(
            pan_sidebar_visible=True, left_column_splitter_sizes=[600, 220]
        )
        with self.window() as win:
            self.show_like_startup_then_open_takeoff(win)
            pan, top = win.get_left_column_splitter_sizes()
            self.assertLess(pan, 300)
            self.assertGreater(top, pan)
            win._workspace_state_coordinator.flush()
            saved = self.saved_takeoff_workspace()
        self.assertNotIn("left_column_splitter_sizes", saved)
        self.assertEqual(len(saved["left_column_pan_first_sizes"]), 2)

    def test_short_or_corrupt_size_lists_never_collapse_the_top_sidebars(self):
        for sizes in ([500], ["a", 5], [], [0, 0], [-4]):
            with self.subTest(sizes=sizes):
                self.write_workspace(
                    pan_sidebar_visible=True, left_column_pan_first_sizes=sizes
                )
                with self.window() as win:
                    self.show_like_startup_then_open_takeoff(win)
                    pan, top = win.get_left_column_splitter_sizes()
                    self.assertGreater(pan, 0)
                    self.assertGreater(top, 0)

    def test_oversized_size_lists_use_only_the_two_panes(self):
        self.write_workspace(
            pan_sidebar_visible=True, left_column_pan_first_sizes=[100, 200, 300]
        )
        with self.window() as win:
            self.show_like_startup_then_open_takeoff(win)
            pan, top = win.get_left_column_splitter_sizes()
            self.assertGreater(pan, 0)
            self.assertGreater(top, 0)

    def test_saved_sizes_survive_a_startup_where_the_takeoff_tab_is_inactive(self):
        self.write_workspace(
            pan_sidebar_visible=True, left_column_pan_first_sizes=[260, 440]
        )
        with self.window() as win:
            self.show_like_startup_then_open_takeoff(win)
            pan, top = win.get_left_column_splitter_sizes()
            self.assertAlmostEqual(pan, 260, delta=4)
            win.resize(1300, 900)
            self.app.processEvents()
            self.assertAlmostEqual(
                win.get_left_column_splitter_sizes()[0], 260, delta=4
            )

    def test_showing_the_pan_sidebar_alone_restores_the_sidebar_column_width(self):
        with self.window() as win:
            win.show()
            win.tab_widget.setCurrentIndex(TAB_INDEX_TAKEOFF)
            self.app.processEvents()
            total = sum(win.get_takeoff_splitter_sizes())
            win.set_takeoff_splitter_sizes([410, total - 410])
            self.app.processEvents()
            win.set_conditions_sidebar_visible(False)
            win.set_layers_sidebar_visible(False)
            self.app.processEvents()
            self.assertEqual(win.get_takeoff_splitter_sizes()[0], 0)
            win.set_pan_sidebar_visible(True)
            self.app.processEvents()
            self.assertAlmostEqual(win.get_takeoff_splitter_sizes()[0], 410, delta=4)
            self.assertFalse(win.get_left_column_splitter().isHidden())

    def test_showing_the_pan_sidebar_expands_a_column_the_user_collapsed(self):
        with self.window() as win:
            win.show()
            win.tab_widget.setCurrentIndex(TAB_INDEX_TAKEOFF)
            self.app.processEvents()
            total = sum(win.get_takeoff_splitter_sizes())
            win.set_takeoff_splitter_sizes([0, total])
            self.app.processEvents()
            self.assertEqual(win.get_takeoff_splitter_sizes()[0], 0)
            win.set_pan_sidebar_visible(True)
            self.app.processEvents()
            self.assertGreater(win.get_takeoff_splitter_sizes()[0], 0)
            self.assertGreater(win.get_left_column_splitter_sizes()[0], 0)

    def test_a_size_list_with_the_wrong_length_leaves_the_column_unchanged(self):
        with self.window() as win:
            win.show()
            win.tab_widget.setCurrentIndex(TAB_INDEX_TAKEOFF)
            win.set_pan_sidebar_visible(True)
            self.app.processEvents()
            before = win.get_left_column_splitter_sizes()
            for sizes in ([], [300], [50, 60, 70], [0, 0]):
                with self.subTest(sizes=sizes):
                    win.set_left_column_splitter_sizes(sizes)
                    self.app.processEvents()
                    self.assertEqual(win.get_left_column_splitter_sizes(), before)

    def test_hiding_all_three_sidebars_keeps_the_saved_column_width(self):
        with self.window() as win:
            win.show()
            win.tab_widget.setCurrentIndex(TAB_INDEX_TAKEOFF)
            win.set_pan_sidebar_visible(True)
            self.app.processEvents()
            win._workspace_state_coordinator.flush()
            width = self.saved_takeoff_workspace()["takeoff_splitter_sizes"][0]
            self.assertGreater(width, 0)
            win.set_pan_sidebar_visible(False)
            win.set_conditions_sidebar_visible(False)
            win.set_layers_sidebar_visible(False)
            self.app.processEvents()
            self.assertTrue(win.get_left_column_splitter().isHidden())
            win._workspace_state_coordinator.flush()
            saved = self.saved_takeoff_workspace()
        self.assertEqual(saved["takeoff_splitter_sizes"][0], width)
        self.assertIs(saved["pan_sidebar_visible"], False)

    def test_the_pan_toggle_keeps_its_state_across_tab_switches_and_follows_the_tab(
        self,
    ):
        with self.window() as win:
            win.show()
            toggle = win.get_pan_toggle_action()
            win.tab_widget.setCurrentIndex(TAB_INDEX_TAKEOFF)
            self.app.processEvents()
            self.assertTrue(toggle.isEnabled())
            toggle.setChecked(True)
            win.tab_widget.setCurrentIndex(0)
            self.app.processEvents()
            self.assertFalse(toggle.isEnabled())
            self.assertTrue(toggle.isChecked())
            self.assertTrue(win.is_pan_sidebar_visible())
            win.tab_widget.setCurrentIndex(TAB_INDEX_TAKEOFF)
            self.app.processEvents()
            self.assertTrue(toggle.isEnabled())
            self.assertTrue(toggle.isChecked())

    def test_the_sidebar_toggles_have_distinct_accessible_names_and_no_shortcuts(self):
        with self.window() as win:
            actions = (
                win.get_pan_toggle_action(),
                win.get_conditions_toggle_action(),
                win.get_layers_toggle_action(),
            )
            names = [
                win._view_toolbar.widgetForAction(action).accessibleName()
                or action.text()
                for action in actions
            ]
            self.assertEqual(len(set(names)), 3)
            self.assertTrue(win.get_pan_toggle_action().shortcut().isEmpty())
            shortcuts = [
                action.shortcut().toString()
                for action in win.findChildren(QtGui.QAction)
                if not action.shortcut().isEmpty()
            ]
            self.assertEqual(len(shortcuts), len(set(shortcuts)))

    def test_switching_pages_on_the_3d_view_still_shows_the_2d_viewport(self):
        bid_ref = BidRef("bid.mdb", "1")

        def load(win, uid):
            win.plan_view.load_page(
                page=Page(uid=uid, name=uid, width_pts=612.0, height_pts=792.0),
                takeoffs=[],
                conditions={},
                color_map={},
                bid_ref=bid_ref,
            )
            self.app.processEvents()
            self.app.processEvents()

        with self.window() as win:
            win.show()
            win.tab_widget.setCurrentIndex(TAB_INDEX_TAKEOFF)
            win.set_pan_sidebar_visible(True)
            win.set_active_takeoff_view("2d")
            self.app.processEvents()
            load(win, "first")
            self.assertTrue(win.plan_view.is_view_state_stable)
            win.set_active_takeoff_view("3d")
            self.app.processEvents()
            load(win, "second")
            sidebar = win._pan_sidebar
            self.assertFalse(sidebar.is_interactive)
            predicted = sidebar.visible_map_rect()
            self.assertFalse(predicted.isEmpty())
            win.set_active_takeoff_view("2d")
            self.app.processEvents()
            self.app.processEvents()
            self.assertTrue(sidebar.is_interactive)
            actual = sidebar.visible_map_rect()
            self.assertAlmostEqual(predicted.x(), actual.x(), delta=2.0)
            self.assertAlmostEqual(predicted.y(), actual.y(), delta=2.0)
            self.assertAlmostEqual(predicted.width(), actual.width(), delta=2.0)
            self.assertAlmostEqual(predicted.height(), actual.height(), delta=2.0)

    def test_the_menu_actions_use_the_shared_toggle_icon(self):
        with self.window() as win:
            toggle = win.get_pan_toggle_action()
            self.assertEqual(
                toggle.icon().cacheKey(),
                IconManager.icon(IconId.PAN_SIDEBAR).cacheKey(),
            )


if __name__ == "__main__":
    unittest.main()
