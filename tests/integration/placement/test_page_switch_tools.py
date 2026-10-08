import os
import unittest
import uuid
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.config import TAB_INDEX_TAKEOFF
from ost_visualizer.presentation.modes.cursor import (
    CURSOR_MODE_PAN,
    CURSOR_MODE_PLACE,
    CURSOR_MODE_SELECT,
    CURSOR_MODE_ZOOM,
)
from PySide6 import QtWidgets
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


if __name__ == "__main__":
    unittest.main()
