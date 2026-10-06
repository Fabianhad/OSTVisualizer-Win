import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.components.pan_sidebar import PanSidebar
from PySide6 import QtCore, QtTest
from shiboken6 import delete, isValid
from tests.integration.surfaces.test_page_scale_viewport import ViewportHarness


class PanSidebarFollowsOnlyTheMainViewTests(ViewportHarness):
    def setUp(self):
        super().setUp()
        self.sidebar = PanSidebar()
        self.addCleanup(lambda: delete(self.sidebar) if isValid(self.sidebar) else None)
        self.sidebar.resize(220, 180)
        self.sidebar.bind_plan_view(self.main)
        self.sidebar.show()
        self.app.processEvents()
        self.sidebar.flush_scheduled_refresh()
        self.scroll_without_publishing(self.main, zoom_steps=9)
        self.assertTrue(self.sidebar.is_interactive)

    def visible_rect(self):
        rect = self.sidebar.visible_map_rect()
        return (rect.x(), rect.y(), rect.width(), rect.height())

    def test_the_mini_map_tracks_the_main_view(self):
        before = self.visible_rect()
        self.main.verticalScrollBar().setValue(
            self.main.verticalScrollBar().maximum() // 8
        )
        self.app.processEvents()
        self.assertNotEqual(self.visible_rect(), before)

    def test_scrolling_and_zooming_a_detached_window_does_not_move_the_mini_map(self):
        before = self.visible_rect()
        renders = self.sidebar.thumbnail_render_count
        main_before = self.viewport_of(self.main)
        self.zoom_detached_to_a_section()
        self.side.verticalScrollBar().setValue(0)
        self.side.horizontalScrollBar().setValue(0)
        self.side.zoom_out()
        self.app.processEvents()
        self.assertEqual(self.visible_rect(), before)
        self.assertEqual(self.sidebar.thumbnail_render_count, renders)
        self.assert_same_viewport(main_before, self.viewport_of(self.main), "main")

    def test_dragging_the_mini_map_pans_the_main_view_and_not_the_detached_window(
        self,
    ):
        self.zoom_detached_to_a_section()
        side_before = self.viewport_of(self.side)
        main_before = self.viewport_of(self.main)
        visible = self.sidebar.visible_map_rect()
        start = QtCore.QPoint(round(visible.center().x()), round(visible.center().y()))
        target = start + QtCore.QPoint(-20, -20)
        QtTest.QTest.mousePress(
            self.sidebar, QtCore.Qt.MouseButton.LeftButton, pos=start
        )
        QtTest.QTest.mouseMove(self.sidebar, target)
        QtTest.QTest.mouseRelease(
            self.sidebar, QtCore.Qt.MouseButton.LeftButton, pos=target
        )
        self.app.processEvents()
        main_after = self.viewport_of(self.main)
        self.assertNotEqual(
            (main_before["h"], main_before["v"]), (main_after["h"], main_after["v"])
        )
        self.assertAlmostEqual(main_before["m11"], main_after["m11"], places=6)
        self.assert_same_viewport(side_before, self.viewport_of(self.side), "detached")

    def test_switching_the_detached_window_page_does_not_refresh_the_thumbnail(self):
        renders = self.sidebar.thumbnail_render_count
        self.side.page_cleared.emit()
        self.app.processEvents()
        self.sidebar.flush_scheduled_refresh()
        self.assertEqual(self.sidebar.thumbnail_render_count, renders)
        self.assertTrue(self.sidebar.has_page)


if __name__ == "__main__":
    unittest.main()
