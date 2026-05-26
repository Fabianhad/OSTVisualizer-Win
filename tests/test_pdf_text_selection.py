import math
import unittest
from types import SimpleNamespace
from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGraphicsScene
from ost_visualizer.application.dtos.render_result_dto import RenderResult
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView


def _raw_char(text, left, right, bottom, top):
    return SimpleNamespace(
        text=text,
        left=left,
        right=right,
        bottom=bottom,
        top=top,
    )


def _raw_run(text, left, right, bottom, top, chars):
    return SimpleNamespace(
        text=text,
        left=left,
        right=right,
        bottom=bottom,
        top=top,
        chars=chars,
    )


class FakeRenderingService:
    def __init__(self):
        self.cancelled = []
        self.requests = []

    def extract_pdf_text_async(self, file_path, page_index, callback, priority=2):
        self.requests.append((file_path, page_index, callback, priority))
        return "text-request-1"

    def cancel_request(self, request_id):
        self.cancelled.append(request_id)


class FakeTrackingViewport:
    def __init__(self):
        self.tracking = []
        self.updates = 0
        self.cursor = None

    def setMouseTracking(self, enabled):
        self.tracking.append(enabled)

    def update(self):
        self.updates += 1

    def setCursor(self, cursor):
        self.cursor = cursor


def _page_info(
    *,
    pdf_width=200.0,
    pdf_height=100.0,
    media_width=200.0,
    media_height=100.0,
    crop_width=0.0,
    crop_height=0.0,
    rotation=0,
):
    return {
        "pdf_width": pdf_width,
        "pdf_height": pdf_height,
        "media_width_pts": media_width,
        "media_height_pts": media_height,
        "crop_width_pts": crop_width,
        "crop_height_pts": crop_height,
        "intrinsic_rotation": rotation,
    }


class PdfTextSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _make_view(self):
        view = TakeoffPlanView.__new__(TakeoffPlanView)
        view._scene = QGraphicsScene()
        view._current_page = Page(
            uid="page-1",
            name="Page 1",
            image_path="drawing.pdf",
            width_pts=200.0,
            height_pts=100.0,
            page_index=0,
        )
        view._pdf_width_pts = 200.0
        view._pdf_height_pts = 100.0
        view._scene_scale = 2.0
        view._pdf_text_runs = []
        view._pdf_text_cache_key = None
        view._pdf_text_request_id = None
        view._pdf_text_request_source = None
        view._pdf_text_highlight_items = []
        view._selected_pdf_text_selection = None
        view._pdf_text_drag_anchor = None
        view._pdf_text_drag_focus = None
        view._selection_enabled = True
        view._cursor_mode = "select"
        view._panning = False
        view._right_pan_active = False
        view._ctrl_held = False
        view._rotation_drag_active = False
        view._select_band_origin = None
        view._drag_handle_index = -2
        view._handle_infos = []
        view._zoom_press_ctrl = False
        view._current_annotations = {}
        view._takeoff_items = []
        view._hotlink_items = []
        view._uid_to_items = {}
        view._selected_uids = set()
        view._current_page_transform = lambda: None
        view.mapToScene = lambda point: QtCore.QPointF(point.x(), point.y())
        view.viewport = lambda: FakeTrackingViewport()
        view._rendering_service = FakeRenderingService()
        view._context_menu_command_trigger = lambda _action_key: None
        view._context_menu_action_state = lambda action_key: {
            "text": action_key.replace("_", " ").title(),
            "enabled": False,
        }
        view._use_full_window_crosshairs = False
        return view

    def test_maps_pdfium_text_box_to_plan_view_page_coordinates(self):
        view = self._make_view()
        raw_runs = [
            _raw_run(
                "Hello",
                10.0,
                20.0,
                70.0,
                80.0,
                [_raw_char("H", 10.0, 12.0, 70.0, 80.0)],
            )
        ]
        mapped = view._map_pdf_text_runs(raw_runs, _page_info())
        self.assertEqual(len(mapped), 1)
        self.assertEqual(mapped[0].text, "Hello")
        self.assertEqual(
            (mapped[0].left, mapped[0].top, mapped[0].right, mapped[0].bottom),
            (20.0, 40.0, 40.0, 60.0),
        )
        self.assertEqual(
            (
                mapped[0].chars[0].left,
                mapped[0].chars[0].top,
                mapped[0].chars[0].right,
                mapped[0].chars[0].bottom,
            ),
            (20.0, 40.0, 24.0, 60.0),
        )

    def test_pdf_text_click_selects_character_and_copies_text(self):
        view = self._make_view()
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _raw_run(
                    "Beam",
                    10.0,
                    20.0,
                    70.0,
                    80.0,
                    [_raw_char("B", 10.0, 12.0, 70.0, 80.0)],
                )
            ],
            _page_info(),
        )
        selected = view.select_pdf_text_at(QtCore.QPointF(21.0, 45.0))
        copied = view.copy_selected_pdf_text()
        self.assertTrue(selected)
        self.assertTrue(copied)
        self.assertEqual(QtWidgets.QApplication.clipboard().text(), "B")
        self.assertEqual(len(view._pdf_text_highlight_items), 1)
        self.assertIs(view._pdf_text_highlight_items[0].scene(), view._scene)

    def test_dragging_within_pdf_text_selects_partial_range(self):
        view = self._make_view()
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _raw_run(
                    "Beam",
                    10.0,
                    18.0,
                    70.0,
                    80.0,
                    [
                        _raw_char("B", 10.0, 12.0, 70.0, 80.0),
                        _raw_char("e", 12.0, 14.0, 70.0, 80.0),
                        _raw_char("a", 14.0, 16.0, 70.0, 80.0),
                        _raw_char("m", 16.0, 18.0, 70.0, 80.0),
                    ],
                )
            ],
            _page_info(),
        )
        self.assertTrue(view._begin_pdf_text_selection(QtCore.QPointF(21.0, 45.0)))
        self.assertTrue(
            view._update_pdf_text_selection_drag(QtCore.QPointF(31.0, 45.0))
        )
        self.assertTrue(view._finish_pdf_text_selection_drag())
        self.assertTrue(view.copy_selected_pdf_text())
        self.assertEqual(QtWidgets.QApplication.clipboard().text(), "Bea")
        self.assertEqual(len(view._pdf_text_highlight_items), 1)

    def test_dragging_across_pdf_text_runs_copies_reading_order(self):
        view = self._make_view()
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _raw_run(
                    "Beam",
                    10.0,
                    14.0,
                    70.0,
                    80.0,
                    [
                        _raw_char("B", 10.0, 12.0, 70.0, 80.0),
                        _raw_char("e", 12.0, 14.0, 70.0, 80.0),
                    ],
                ),
                _raw_run(
                    "Tag",
                    20.0,
                    26.0,
                    70.0,
                    80.0,
                    [
                        _raw_char("T", 20.0, 22.0, 70.0, 80.0),
                        _raw_char("a", 22.0, 24.0, 70.0, 80.0),
                        _raw_char("g", 24.0, 26.0, 70.0, 80.0),
                    ],
                ),
            ],
            _page_info(),
        )
        self.assertTrue(view._begin_pdf_text_selection(QtCore.QPointF(21.0, 45.0)))
        self.assertTrue(
            view._update_pdf_text_selection_drag(QtCore.QPointF(51.0, 45.0))
        )
        self.assertTrue(view.copy_selected_pdf_text())
        self.assertEqual(QtWidgets.QApplication.clipboard().text(), "Be Tag")
        self.assertEqual(len(view._pdf_text_highlight_items), 2)

    def test_copy_selected_uses_pdf_text_when_no_takeoffs_are_selected(self):
        view = self._make_view()
        view._selected_uids = set()
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _raw_run(
                    "Beam",
                    10.0,
                    20.0,
                    70.0,
                    80.0,
                    [_raw_char("B", 10.0, 12.0, 70.0, 80.0)],
                )
            ],
            _page_info(),
        )
        view.select_pdf_text_at(QtCore.QPointF(21.0, 45.0))
        view.copy_selected()
        self.assertEqual(QtWidgets.QApplication.clipboard().text(), "B")

    def test_pdf_text_selection_is_ignored_outside_select_mode(self):
        view = self._make_view()
        view._cursor_mode = "place"
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _raw_run(
                    "Beam",
                    10.0,
                    20.0,
                    70.0,
                    80.0,
                    [_raw_char("B", 10.0, 12.0, 70.0, 80.0)],
                )
            ],
            _page_info(),
        )
        self.assertFalse(view.select_pdf_text_at(QtCore.QPointF(25.0, 45.0)))
        self.assertIsNone(view._selected_pdf_text_selection)

    def test_pdf_text_hover_uses_text_cursor_in_select_mode(self):
        view = self._make_view()
        view._selected_uids = set()
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _raw_run(
                    "Beam",
                    10.0,
                    20.0,
                    70.0,
                    80.0,
                    [_raw_char("B", 10.0, 12.0, 70.0, 80.0)],
                )
            ],
            _page_info(),
        )
        cursor = view._resolve_select_cursor(QtCore.QPoint(25, 45))
        self.assertEqual(cursor, Qt.CursorShape.IBeamCursor)

    def test_pdf_text_hover_cursor_resets_when_mouse_moves_away(self):
        view = self._make_view()
        viewport = FakeTrackingViewport()
        view.viewport = lambda: viewport
        view._last_mouse_vp_pos = QtCore.QPoint(25, 45)
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _raw_run(
                    "Beam",
                    10.0,
                    20.0,
                    70.0,
                    80.0,
                    [_raw_char("B", 10.0, 12.0, 70.0, 80.0)],
                )
            ],
            _page_info(),
        )
        view._update_cursor(QtCore.QPoint(25, 45))
        self.assertEqual(viewport.cursor, Qt.CursorShape.IBeamCursor)
        view._update_cursor(QtCore.QPoint(100, 100))
        self.assertEqual(viewport.cursor, Qt.CursorShape.ArrowCursor)

    def test_selected_pdf_text_does_not_force_hover_ibeam_elsewhere(self):
        view = self._make_view()
        viewport = FakeTrackingViewport()
        view.viewport = lambda: viewport
        view._last_mouse_vp_pos = QtCore.QPoint(25, 45)
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _raw_run(
                    "Beam",
                    10.0,
                    20.0,
                    70.0,
                    80.0,
                    [_raw_char("B", 10.0, 12.0, 70.0, 80.0)],
                )
            ],
            _page_info(),
        )
        self.assertTrue(view.select_pdf_text_at(QtCore.QPointF(21.0, 45.0)))
        view._update_cursor(QtCore.QPoint(100, 100))
        self.assertEqual(viewport.cursor, Qt.CursorShape.ArrowCursor)

    def test_select_mode_enables_passive_mouse_tracking_for_pdf_text_hover(self):
        view = self._make_view()
        viewport = FakeTrackingViewport()
        view.viewport = lambda: viewport
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _raw_run(
                    "Beam",
                    10.0,
                    20.0,
                    70.0,
                    80.0,
                    [_raw_char("B", 10.0, 12.0, 70.0, 80.0)],
                )
            ],
            _page_info(),
        )
        view._update_viewport_mouse_tracking()
        self.assertEqual(viewport.tracking, [True])

    def test_select_mode_does_not_enable_mouse_tracking_without_pdf_text(self):
        view = self._make_view()
        viewport = FakeTrackingViewport()
        view.viewport = lambda: viewport
        view._update_viewport_mouse_tracking()
        self.assertEqual(viewport.tracking, [False])

    def test_takeoff_hover_priority_beats_pdf_text_cursor(self):
        view = self._make_view()
        view._selected_uids = {"takeoff-1"}
        view._handle_infos = []
        view.find_selected_movable_at = lambda _scene_pos: "takeoff-1"
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _raw_run(
                    "Beam",
                    10.0,
                    20.0,
                    70.0,
                    80.0,
                    [_raw_char("B", 10.0, 12.0, 70.0, 80.0)],
                )
            ],
            _page_info(),
        )
        cursor = view._resolve_select_cursor(QtCore.QPoint(25, 45))
        self.assertEqual(cursor, Qt.CursorShape.SizeAllCursor)

    def test_pdf_text_context_menu_copy_is_enabled_for_selection(self):
        view = self._make_view()
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _raw_run(
                    "Beam",
                    10.0,
                    20.0,
                    70.0,
                    80.0,
                    [_raw_char("B", 10.0, 12.0, 70.0, 80.0)],
                )
            ],
            _page_info(),
        )
        view.select_pdf_text_at(QtCore.QPointF(21.0, 45.0))
        menu = QtWidgets.QMenu()
        view._add_pdf_text_context_clipboard_actions(menu)
        actions = menu.actions()
        self.assertEqual(actions[0].text().replace("&", ""), "Copy")
        self.assertTrue(actions[0].isEnabled())

    def test_pdf_text_extraction_runs_through_rendering_worker_service(self):
        view = self._make_view()
        view._request_pdf_text_extraction()
        self.assertEqual(
            view._rendering_service.requests[0][:2],
            ("drawing.pdf", 0),
        )
        self.assertEqual(view._pdf_text_request_id, "text-request-1")

    def test_composite_pdf_text_extraction_uses_overlay_source(self):
        view = self._make_view()
        view._current_page.overlay_image_path = "overlay.pdf"
        view._current_page.image_show_mode = 2
        view._request_pdf_text_extraction()
        self.assertEqual(
            view._rendering_service.requests[0][:2],
            ("overlay.pdf", 0),
        )
        self.assertEqual(view._pdf_text_cache_key[1], "overlay")

    def test_raster_overlay_falls_back_to_main_pdf_text_source(self):
        view = self._make_view()
        view._current_page.overlay_image_path = "overlay.tif"
        view._current_page.image_show_mode = 2
        view._request_pdf_text_extraction()
        self.assertEqual(
            view._rendering_service.requests[0][:2],
            ("drawing.pdf", 0),
        )
        self.assertEqual(view._pdf_text_cache_key[1], "main")

    def test_overlay_pdf_text_boxes_map_through_overlay_offset(self):
        view = self._make_view()
        view._current_page.overlay_image_path = "overlay.pdf"
        view._current_page.image_show_mode = 2
        view._current_page.overlay_offset_x = 1.0
        view._current_page.overlay_offset_y = 0.5
        raw_runs = [
            _raw_run(
                "B",
                10.0,
                20.0,
                70.0,
                80.0,
                [_raw_char("B", 10.0, 12.0, 70.0, 80.0)],
            )
        ]
        mapped = view._map_pdf_text_runs(
            raw_runs,
            _page_info(),
            ("overlay", "overlay.pdf", 0),
        )
        self.assertEqual(len(mapped), 1)
        self.assertEqual(
            (mapped[0].left, mapped[0].top, mapped[0].right, mapped[0].bottom),
            (164.0, 112.0, 184.0, 132.0),
        )

    def test_overlay_pdf_text_boxes_map_through_overlay_scale_and_rotation(self):
        view = self._make_view()
        view._current_page.overlay_image_path = "overlay.pdf"
        view._current_page.image_show_mode = 2
        view._current_page.overlay_offset_x = 1.0
        view._current_page.overlay_offset_y = 0.5
        view._current_page.overlay_rotation = math.pi / 2.0
        raw_runs = [
            _raw_run(
                "R",
                10.0,
                20.0,
                30.0,
                40.0,
                [_raw_char("R", 10.0, 20.0, 30.0, 40.0)],
            )
        ]
        mapped = view._map_pdf_text_runs(
            raw_runs,
            _page_info(
                pdf_width=100.0,
                pdf_height=50.0,
                media_width=100.0,
                media_height=50.0,
            ),
            ("overlay", "overlay.pdf", 0),
        )
        self.assertEqual(len(mapped), 1)
        self.assertEqual(
            (mapped[0].left, mapped[0].top, mapped[0].right, mapped[0].bottom),
            (64.0, 112.0, 104.0, 152.0),
        )

    def test_pdf_text_request_is_cancelled_when_page_clears(self):
        view = self._make_view()
        view._pdf_text_request_id = "old-text-request"
        view._clear_pdf_text_cache()
        self.assertEqual(view._rendering_service.cancelled, ["old-text-request"])
        self.assertEqual(view._pdf_text_runs, [])

    def test_pdf_text_cache_clear_tolerates_scene_deleted_highlights(self):
        view = self._make_view()
        view._pdf_text_runs = view._map_pdf_text_runs(
            [
                _raw_run(
                    "A",
                    10.0,
                    20.0,
                    70.0,
                    80.0,
                    [_raw_char("A", 10.0, 20.0, 70.0, 80.0)],
                )
            ],
            _page_info(),
        )
        self.assertTrue(view.select_pdf_text_at(QtCore.QPointF(21.0, 45.0)))
        self.assertEqual(len(view._pdf_text_highlight_items), 1)
        view._scene.clear()
        view._clear_pdf_text_cache()
        self.assertEqual(view._pdf_text_highlight_items, [])
        self.assertIsNone(view._selected_pdf_text_selection)

    def test_pdf_text_extraction_result_ignores_stale_request(self):
        view = self._make_view()
        view._pdf_text_request_id = "current"
        view._on_pdf_text_extracted(
            RenderResult(
                "stale",
                True,
                {"text_runs": [], "page_info": _page_info()},
                None,
            )
        )
        self.assertEqual(view._pdf_text_request_id, "current")
        self.assertEqual(view._pdf_text_runs, [])


if __name__ == "__main__":
    unittest.main()
