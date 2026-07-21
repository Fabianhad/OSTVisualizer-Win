import unittest
from ost_visualizer.presentation.components.mesh_view import OpenGLViewer
from ost_visualizer.presentation.visualization.render_surface_metrics import (
    RenderSurfaceMetrics,
)


class _Camera:
    aspect_ratio = 1.0


class _Renderer:
    def __init__(self):
        self.resize_calls = []
        self.camera = _Camera()

    def resize(self, width_px, height_px):
        self.resize_calls.append((width_px, height_px))
        self.camera.aspect_ratio = width_px / height_px


class _Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def disconnect(self, callback):
        self.callbacks.remove(callback)


class _Screen:
    def __init__(self):
        self.logicalDotsPerInchChanged = _Signal()


class _Window:
    def __init__(self, screen):
        self.screenChanged = _Signal()
        self._screen = screen

    def screen(self):
        return self._screen


class _Timer:
    def __init__(self):
        self.active = False
        self.starts = 0

    def isActive(self):
        return self.active

    def start(self, _interval):
        self.active = True
        self.starts += 1


class RenderSurfaceSizingTests(unittest.TestCase):
    def test_logical_dimensions_convert_to_physical_pixels_once(self):
        expected = {
            1.0: (801, 603),
            1.25: (1001, 754),
            1.5: (1202, 905),
            1.75: (1402, 1055),
            2.0: (1602, 1206),
        }
        for dpr, physical_size in expected.items():
            with self.subTest(dpr=dpr):
                metrics = RenderSurfaceMetrics.from_logical_size(801, 603, dpr)
                self.assertEqual(metrics.logical_width, 801)
                self.assertEqual(metrics.logical_height, 603)
                self.assertEqual(metrics.device_pixel_ratio, dpr)
                self.assertEqual(metrics.physical_size, physical_size)

    def test_one_hundred_percent_scaling_is_unchanged(self):
        metrics = RenderSurfaceMetrics.from_logical_size(1920, 1080, 1.0)
        self.assertEqual(metrics.physical_size, (1920, 1080))
        self.assertEqual(metrics.to_physical_point(319, 241), (319, 241))

    def test_camera_aspect_ratio_matches_rounded_physical_viewport(self):
        metrics = RenderSurfaceMetrics.from_logical_size(801, 603, 1.25)
        renderer = _Renderer()
        renderer.resize(*metrics.physical_size)
        self.assertAlmostEqual(renderer.camera.aspect_ratio, 1001 / 754)

    def test_fractional_input_coordinates_map_to_framebuffer_pixels(self):
        metrics = RenderSurfaceMetrics.from_logical_size(801, 603, 1.25)
        self.assertEqual(metrics.to_physical_point(13, 17), (16, 21))
        self.assertEqual(metrics.to_physical_point(-0.1, -0.1), (-1, -1))

    def test_zero_size_has_no_render_target(self):
        for logical_size in ((0, 0), (0, 100), (100, 0)):
            with self.subTest(logical_size=logical_size):
                metrics = RenderSurfaceMetrics.from_logical_size(
                    *logical_size, device_pixel_ratio=2.0
                )
                self.assertFalse(metrics.has_render_target)

    def test_invalid_dimensions_and_ratios_are_rejected(self):
        for args in ((-1, 10, 1.0), (10, -1, 1.0), (10, 10, 0.0)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                RenderSurfaceMetrics.from_logical_size(*args)

    @staticmethod
    def _viewer(logical_size=(640, 480), dpr=1.0, visible=True):
        state = {
            "logical_size": logical_size,
            "dpr": dpr,
            "visible": visible,
        }
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        viewer._renderer = _Renderer()
        viewer._render_surface_size = None
        viewer.width = lambda: state["logical_size"][0]
        viewer.height = lambda: state["logical_size"][1]
        viewer.devicePixelRatioF = lambda: state["dpr"]
        viewer.isVisible = lambda: state["visible"]
        return viewer, viewer._renderer, state

    def test_resize_maximize_restore_and_splitter_sizes_update_renderer(self):
        viewer, renderer, state = self._viewer(dpr=1.5)
        for logical_size in ((640, 480), (1600, 900), (900, 700), (731, 700)):
            state["logical_size"] = logical_size
            self.assertTrue(OpenGLViewer._resize_render_surface(viewer))
        self.assertEqual(
            renderer.resize_calls,
            [(960, 720), (2400, 1350), (1350, 1050), (1097, 1050)],
        )
        self.assertAlmostEqual(renderer.camera.aspect_ratio, 1097 / 1050)

    def test_repeated_resize_does_not_apply_scale_twice(self):
        viewer, renderer, _state = self._viewer((800, 600), dpr=1.5)
        OpenGLViewer._resize_render_surface(viewer)
        OpenGLViewer._resize_render_surface(viewer)
        self.assertEqual(renderer.resize_calls, [(1200, 900)])

    def test_monitor_dpr_change_reallocates_at_new_physical_size(self):
        viewer, renderer, state = self._viewer((800, 600), dpr=1.25)
        OpenGLViewer._resize_render_surface(viewer)
        state["dpr"] = 1.75
        connected_screens = []
        screen = object()
        viewer._connect_surface_screen = connected_screens.append
        viewer._queue_surface_metrics_refresh = lambda: (
            OpenGLViewer._resize_render_surface(viewer)
        )
        OpenGLViewer._on_surface_screen_changed(viewer, screen)
        self.assertEqual(connected_screens, [screen])
        self.assertEqual(renderer.resize_calls, [(1000, 750), (1400, 1050)])

    def test_hidden_or_zero_sized_widget_does_not_resize_renderer(self):
        viewer, renderer, state = self._viewer(visible=False, dpr=2.0)
        self.assertFalse(OpenGLViewer._resize_render_surface(viewer))
        state["visible"] = True
        state["logical_size"] = (0, 480)
        self.assertFalse(OpenGLViewer._resize_render_surface(viewer))
        self.assertEqual(renderer.resize_calls, [])
        state["logical_size"] = (640, 480)
        self.assertTrue(OpenGLViewer._resize_render_surface(viewer))
        self.assertEqual(renderer.resize_calls, [(1280, 960)])

    def test_surface_notification_subscriptions_are_unique_and_released(self):
        viewer, _renderer, _state = self._viewer()
        screen = _Screen()
        window = _Window(screen)
        top_level = type(
            "TopLevel",
            (),
            {
                "isWindow": lambda _self: True,
                "isVisible": lambda _self: True,
                "windowHandle": lambda _self: window,
            },
        )()
        viewer._surface_window = None
        viewer._surface_screen = None
        viewer.window = lambda: top_level
        OpenGLViewer._connect_surface_notifications(viewer)
        OpenGLViewer._connect_surface_notifications(viewer)
        self.assertEqual(len(window.screenChanged.callbacks), 1)
        self.assertEqual(len(screen.logicalDotsPerInchChanged.callbacks), 1)
        OpenGLViewer._disconnect_surface_notifications(viewer)
        self.assertEqual(window.screenChanged.callbacks, [])
        self.assertEqual(screen.logicalDotsPerInchChanged.callbacks, [])
        self.assertIsNone(viewer._surface_window)
        self.assertIsNone(viewer._surface_screen)

    def test_invisible_top_level_does_not_request_native_window_handle(self):
        viewer, _renderer, _state = self._viewer()
        top_level = type(
            "HiddenTopLevel",
            (),
            {
                "isWindow": lambda _self: True,
                "isVisible": lambda _self: False,
                "windowHandle": lambda _self: (_ for _ in ()).throw(
                    AssertionError("native handle requested before show")
                ),
            },
        )()
        viewer._surface_window = None
        viewer._surface_screen = None
        viewer.window = lambda: top_level
        OpenGLViewer._connect_surface_notifications(viewer)
        self.assertIsNone(viewer._surface_window)

    def test_surface_metric_refresh_requests_are_coalesced_and_stop_after_cleanup(self):
        viewer, _renderer, _state = self._viewer()
        viewer._destroyed = False
        viewer._surface_metrics_timer = _Timer()
        OpenGLViewer._queue_surface_metrics_refresh(viewer)
        OpenGLViewer._queue_surface_metrics_refresh(viewer)
        self.assertEqual(viewer._surface_metrics_timer.starts, 1)
        viewer._destroyed = True
        viewer._surface_metrics_timer.active = False
        OpenGLViewer._queue_surface_metrics_refresh(viewer)
        self.assertEqual(viewer._surface_metrics_timer.starts, 1)


if __name__ == "__main__":
    unittest.main()
