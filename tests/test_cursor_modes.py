import unittest
from ost_visualizer.presentation.modes.cursor import (
    CURSOR_MODE_ANNOTATION_PLACE,
    CURSOR_MODE_DEFAULT,
    CURSOR_MODE_MOVE_OVERLAY,
    CURSOR_MODE_MOVE_OVERLAY_HANDLE,
    CURSOR_MODE_PAN,
    CURSOR_MODE_PASTE_BACKOUT,
    CURSOR_MODE_PLACE,
    CURSOR_MODE_ROTATE,
    CURSOR_MODE_SELECT,
    CURSOR_MODE_SLOPE_ROTATE,
    CURSOR_MODE_ZOOM,
    PASSIVE_MOUSE_TRACKING_CURSOR_MODES,
)


class CursorModeConstantsTest(unittest.TestCase):
    def test_cursor_mode_values_remain_compatible(self):
        self.assertEqual(CURSOR_MODE_DEFAULT, "default")
        self.assertEqual(CURSOR_MODE_SELECT, "select")
        self.assertEqual(CURSOR_MODE_PLACE, "place")
        self.assertEqual(CURSOR_MODE_ANNOTATION_PLACE, "annotation_place")
        self.assertEqual(CURSOR_MODE_PAN, "pan")
        self.assertEqual(CURSOR_MODE_ZOOM, "zoom")
        self.assertEqual(CURSOR_MODE_ROTATE, "rotate")
        self.assertEqual(CURSOR_MODE_SLOPE_ROTATE, "slope_rotate")
        self.assertEqual(CURSOR_MODE_PASTE_BACKOUT, "paste_backout")
        self.assertEqual(CURSOR_MODE_MOVE_OVERLAY, "move_overlay")
        self.assertEqual(CURSOR_MODE_MOVE_OVERLAY_HANDLE, "move_overlay_handle")

    def test_passive_mouse_tracking_modes_include_select_and_preview_modes(self):
        self.assertEqual(
            PASSIVE_MOUSE_TRACKING_CURSOR_MODES,
            {
                CURSOR_MODE_SELECT,
                CURSOR_MODE_PLACE,
                CURSOR_MODE_ANNOTATION_PLACE,
                CURSOR_MODE_PASTE_BACKOUT,
                CURSOR_MODE_ROTATE,
                CURSOR_MODE_SLOPE_ROTATE,
                CURSOR_MODE_MOVE_OVERLAY,
                CURSOR_MODE_MOVE_OVERLAY_HANDLE,
            },
        )


if __name__ == "__main__":
    unittest.main()
