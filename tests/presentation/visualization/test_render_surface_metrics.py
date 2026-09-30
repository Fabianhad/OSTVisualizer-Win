import unittest
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
