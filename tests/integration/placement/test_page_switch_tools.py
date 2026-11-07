import os
import unittest
import uuid
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.config import TAB_INDEX_TAKEOFF
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_DIMENSION,
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_TEXT,
)
from ost_visualizer.presentation.utils.plan_tool_registry import (
    PLAN_ANNOTATION_TOOL_SPECS,
)
from ost_visualizer.presentation.modes.cursor import (
    CURSOR_MODE_ANNOTATION_PLACE,
    CURSOR_MODE_PAN,
    CURSOR_MODE_PLACE,
    CURSOR_MODE_SELECT,
    CURSOR_MODE_ZOOM,
)
from PySide6 import QtCore, QtTest, QtWidgets
from tests.integration.ai_takeoff import test_m1b_golden_end_to_end as m1b
from tests.integration.ai_takeoff.access_app_support import (
    run_in_access_child,
    seed_access_bid,
    temporary_home,
)
from tests.presentation.services.ai_takeoff_pdf_support import write_takeoff_pdf

TOOL_ACTIONS = {
    CURSOR_MODE_SELECT: "select_tool",
    CURSOR_MODE_PLACE: "place_tool",
    CURSOR_MODE_PAN: "pan_tool",
    CURSOR_MODE_ZOOM: "zoom_tool",
}


class PageSwitchToolTests(unittest.TestCase):
    window = m1b.M1bGoldenEndToEndTests.window

    def setUp(self):
        if run_in_access_child(self):
            self.skip_body = True
            return
        self.skip_body = False
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        directory = temporary_home()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        self.server_name = f"OstvPageTools-{uuid.uuid4().hex[:12]}"
        self.db_path = self.home / "tools.mdb"

    def pump(self, count=200):
        for _ in range(count):
            self.app.processEvents()

    def checked_tools(self, win):
        return [
            key for key, action in win._plan_tool_actions.items() if action.isChecked()
        ]

    def test_every_tool_survives_a_page_switch_while_a_condition_is_selected(self):
        if self.skip_body:
            return
        pdf = write_takeoff_pdf(self.home / "plan.pdf", lines=[(100, 100, 400, 100)])
        bid_uid, page_uids, condition_uid = seed_access_bid(
            self.db_path,
            [("S-101", 8.5, 11.0, 0.125, 12.0), ("S-102", 8.5, 11.0, 0.125, 12.0)],
            image_path=str(pdf),
        )
        with self.window(bid_uid) as (win, _controller):
            ui = win.handlers.ui_event
            plan = ui.plan_view
            win.tab_widget.setCurrentIndex(TAB_INDEX_TAKEOFF)
            win.set_active_takeoff_view("2d")
            win.resize(1200, 800)
            win.show()
            self.pump(60)
            ui.sync_after_startup_load()
            ui.handle_bid_selection(BidRef(str(self.db_path), str(bid_uid)), force=True)
            self.pump()
            ui.handle_page_selection([page_uids[0]])
            ui.handle_active_page_changed(page_uids[0])
            self.pump()
            sidebar = ui.conditions_sidebar
            sidebar.tree.setCurrentItem(sidebar._condition_items[condition_uid])
            self.pump(50)
            self.assertEqual(plan.cursor_mode, CURSOR_MODE_PLACE)
            page = 0
            for mode in (
                CURSOR_MODE_PLACE,
                CURSOR_MODE_PAN,
                CURSOR_MODE_ZOOM,
                CURSOR_MODE_PLACE,
                CURSOR_MODE_SELECT,
            ):
                with self.subTest(mode=mode):
                    win._plan_tool_actions[TOOL_ACTIONS[mode]].trigger()
                    self.pump(30)
                    self.assertEqual(plan.cursor_mode, mode)
                    page = 1 - page
                    ui.handle_active_page_changed(page_uids[page])
                    self.pump()
                    self.assertEqual(plan.current_page_uid, page_uids[page])
                    self.assertEqual(plan.cursor_mode, mode)
                    self.assertEqual(self.checked_tools(win), [TOOL_ACTIONS[mode]])
                    self.assertEqual(ui.placement.is_active, mode == CURSOR_MODE_PLACE)
                    self.assertEqual(
                        sidebar.get_selected_condition_uids(), [condition_uid]
                    )

    def test_annotation_tools_survive_a_page_switch(self):
        if self.skip_body:
            return
        pdf = write_takeoff_pdf(self.home / "plan.pdf", lines=[(100, 100, 400, 100)])
        bid_uid, page_uids, _condition_uid = seed_access_bid(
            self.db_path,
            [("S-101", 8.5, 11.0, 0.125, 12.0), ("S-102", 8.5, 11.0, 0.125, 12.0)],
            image_path=str(pdf),
        )
        with self.window(bid_uid) as (win, _controller):
            ui = win.handlers.ui_event
            plan = ui.plan_view
            win.tab_widget.setCurrentIndex(TAB_INDEX_TAKEOFF)
            win.set_active_takeoff_view("2d")
            win.resize(1200, 800)
            win.show()
            self.pump(60)
            ui.sync_after_startup_load()
            ui.handle_bid_selection(BidRef(str(self.db_path), str(bid_uid)), force=True)
            self.pump()
            ui.handle_page_selection([page_uids[0]])
            ui.handle_active_page_changed(page_uids[0])
            self.pump()
            page = 0
            for spec in PLAN_ANNOTATION_TOOL_SPECS:
                if spec.annotation_type not in (
                    ANNOTATION_TYPE_TEXT,
                    ANNOTATION_TYPE_DIMENSION,
                    ANNOTATION_TYPE_HOTLINK,
                ):
                    continue
                with self.subTest(tool=spec.annotation_type):
                    win._plan_tool_actions[spec.action_key].trigger()
                    self.pump(30)
                    self.assertEqual(plan.cursor_mode, CURSOR_MODE_ANNOTATION_PLACE)
                    self.assertEqual(plan.annotation_place_type, spec.annotation_type)
                    half_drawn = spec.annotation_type == ANNOTATION_TYPE_DIMENSION
                    if half_drawn:
                        # Start a two-point dimension: the first point is placed and
                        # the drag is in progress when the page changes.
                        QtTest.QTest.mousePress(
                            plan.viewport(),
                            QtCore.Qt.MouseButton.LeftButton,
                            pos=plan.viewport().rect().center(),
                        )
                        self.pump(10)
                        self.assertEqual(len(plan._annotation_place_points), 1)
                        self.assertTrue(plan._annotation_place_dragging)
                    page = 1 - page
                    ui.handle_active_page_changed(page_uids[page])
                    self.pump()
                    self.assertEqual(plan.current_page_uid, page_uids[page])
                    self.assertEqual(plan.cursor_mode, CURSOR_MODE_ANNOTATION_PLACE)
                    self.assertEqual(plan.annotation_place_type, spec.annotation_type)
                    self.assertEqual(self.checked_tools(win), [spec.action_key])
                    if half_drawn:
                        # The partial drawing belongs to the old page and is discarded;
                        # only the tool itself carries over.
                        self.assertEqual(plan._annotation_place_points, [])
                        self.assertFalse(plan._annotation_place_dragging)
            dimension = next(
                spec
                for spec in PLAN_ANNOTATION_TOOL_SPECS
                if spec.annotation_type == ANNOTATION_TYPE_DIMENSION
            )
            win._plan_tool_actions[dimension.action_key].trigger()
            self.pump(30)
            self.assertEqual(plan.annotation_place_type, ANNOTATION_TYPE_DIMENSION)
            # A page load that does not go through the authoritative-refresh
            # preparation still drops the half-drawn item but keeps the tool.
            QtTest.QTest.mousePress(
                plan.viewport(),
                QtCore.Qt.MouseButton.LeftButton,
                pos=plan.viewport().rect().center(),
            )
            self.pump(10)
            self.assertEqual(len(plan._annotation_place_points), 1)
            plan.clear(
                preserve_place_session=True,
                notify_page_cleared=False,
                report_selection_cleared=False,
            )
            self.assertEqual(plan._annotation_place_points, [])
            self.assertFalse(plan._annotation_place_dragging)
            self.assertEqual(plan.annotation_place_type, ANNOTATION_TYPE_DIMENSION)
            self.assertEqual(plan.cursor_mode, CURSOR_MODE_ANNOTATION_PLACE)
            # Without the preserve flag the tool is left entirely.
            plan.clear(notify_page_cleared=False, report_selection_cleared=False)
            self.assertIsNone(plan.annotation_place_type)

    def test_pan_zoom_and_select_survive_a_page_switch_without_a_condition(self):
        if self.skip_body:
            return
        pdf = write_takeoff_pdf(self.home / "plan.pdf", lines=[(100, 100, 400, 100)])
        bid_uid, page_uids, _condition_uid = seed_access_bid(
            self.db_path,
            [("S-101", 8.5, 11.0, 0.125, 12.0), ("S-102", 8.5, 11.0, 0.125, 12.0)],
            image_path=str(pdf),
        )
        with self.window(bid_uid) as (win, _controller):
            ui = win.handlers.ui_event
            plan = ui.plan_view
            win.tab_widget.setCurrentIndex(TAB_INDEX_TAKEOFF)
            win.set_active_takeoff_view("2d")
            win.resize(1200, 800)
            win.show()
            self.pump(60)
            ui.sync_after_startup_load()
            ui.handle_bid_selection(BidRef(str(self.db_path), str(bid_uid)), force=True)
            self.pump()
            ui.handle_page_selection([page_uids[0]])
            ui.handle_active_page_changed(page_uids[0])
            self.pump()
            self.assertEqual(ui.conditions_sidebar.get_selected_condition_uids(), [])
            page = 0
            for mode in (
                CURSOR_MODE_PAN,
                CURSOR_MODE_ZOOM,
                CURSOR_MODE_SELECT,
                CURSOR_MODE_PAN,
            ):
                with self.subTest(mode=mode):
                    win._plan_tool_actions[TOOL_ACTIONS[mode]].trigger()
                    self.pump(30)
                    self.assertEqual(plan.cursor_mode, mode)
                    page = 1 - page
                    ui.handle_active_page_changed(page_uids[page])
                    self.pump()
                    self.assertEqual(plan.current_page_uid, page_uids[page])
                    self.assertEqual(plan.cursor_mode, mode)
                    self.assertEqual(self.checked_tools(win), [TOOL_ACTIONS[mode]])
                    self.assertFalse(ui.placement.is_active)


if __name__ == "__main__":
    unittest.main()
