import unittest
from ost_visualizer.application.render_quality import (
    CONSTRAINED_RENDER_SCALE_FLOOR,
    INTERACTIVE_PDF_RENDER_SCALE,
    RASTER_NATIVE_RENDER_SCALE,
    RENDER_SCALE_DECIMAL_PLACES,
    ZOOM_PDF_RENDER_SCALE_MIN,
    align_rendered_frame_origin,
    baseline_render_scale,
    quantize_constrained_render_scale,
    quantize_render_frame_coordinate,
    truncate_constrained_render_scale,
)


class RenderQualityContractTests(unittest.TestCase):
    def test_pdf_and_raster_baselines_keep_distinct_semantics(self):
        self.assertEqual(baseline_render_scale(is_pdf=True), 3.0)
        self.assertEqual(
            baseline_render_scale(is_pdf=True), INTERACTIVE_PDF_RENDER_SCALE
        )
        self.assertEqual(baseline_render_scale(is_pdf=False), 1.0)
        self.assertEqual(
            baseline_render_scale(is_pdf=False), RASTER_NATIVE_RENDER_SCALE
        )
        self.assertEqual(INTERACTIVE_PDF_RENDER_SCALE * 72.0, 216.0)

    def test_constrained_floor_is_not_the_interactive_pdf_baseline(self):
        self.assertEqual(CONSTRAINED_RENDER_SCALE_FLOOR, 0.1)
        self.assertLess(
            CONSTRAINED_RENDER_SCALE_FLOOR,
            INTERACTIVE_PDF_RENDER_SCALE,
        )
        self.assertEqual(quantize_constrained_render_scale(0.01), 0.1)
        self.assertEqual(truncate_constrained_render_scale(0.01), 0.1)

    def test_zoom_pdf_lower_bound_is_separate_from_baseline_and_floor(self):
        self.assertEqual(ZOOM_PDF_RENDER_SCALE_MIN, 1.0)
        self.assertGreater(ZOOM_PDF_RENDER_SCALE_MIN, CONSTRAINED_RENDER_SCALE_FLOOR)
        self.assertLess(ZOOM_PDF_RENDER_SCALE_MIN, INTERACTIVE_PDF_RENDER_SCALE)
        self.assertEqual(RENDER_SCALE_DECIMAL_PLACES, 3)

    def test_cache_safe_truncation_does_not_round_a_constraint_up(self):
        self.assertEqual(quantize_constrained_render_scale(1.2346), 1.235)
        self.assertEqual(truncate_constrained_render_scale(1.2346), 1.234)

    def test_frame_origin_alignment_uses_rendered_pixel_boundaries(self):
        self.assertEqual(align_rendered_frame_origin(0.26, 2.0), 0.5)
        self.assertEqual(align_rendered_frame_origin(-0.26, 2.0), -0.5)
        self.assertEqual(align_rendered_frame_origin(4.25, 0.0), 4.25)
        self.assertEqual(align_rendered_frame_origin(-4.25, -2.0), -4.25)
        self.assertEqual(quantize_render_frame_coordinate(4.1236), 4.124)


class RenderQualityNumericCoercionTests(unittest.TestCase):
    def test_quantizers_return_floats_even_for_whole_number_inputs(self):
        # Cache keys and Qt geometry expect floats, never the int that round() returns.
        for result, expected in (
            (quantize_constrained_render_scale(2), 2.0),
            (quantize_constrained_render_scale(0), CONSTRAINED_RENDER_SCALE_FLOOR),
            (quantize_render_frame_coordinate(4), 4.0),
            (quantize_render_frame_coordinate(-4), -4.0),
        ):
            with self.subTest(expected=expected):
                self.assertIsInstance(result, float)
                self.assertEqual(result, expected)


class RenderFrameAlignmentTests(unittest.TestCase):
    def test_frame_origins_snap_to_the_render_pixel_grid_for_any_positive_scale(self):
        from ost_visualizer.application import render_quality as rq

        self.assertEqual(rq.align_rendered_frame_origin(3.0, 0.5), 4.0)
        self.assertEqual(rq.align_rendered_frame_origin(2.9, 0.5), 2.0)
        self.assertEqual(rq.align_rendered_frame_origin(3.0, 2.0), 3.0)
        self.assertAlmostEqual(rq.align_rendered_frame_origin(3.3, 2.0), 3.5)
        self.assertEqual(rq.align_rendered_frame_origin(-3.0, 0.5), -2.0)

    def test_a_non_positive_scale_leaves_the_origin_untouched(self):
        from ost_visualizer.application import render_quality as rq

        for scale in (0.0, -1.0, -0.5):
            self.assertEqual(rq.align_rendered_frame_origin(3.3, scale), 3.3)


if __name__ == "__main__":
    unittest.main()
