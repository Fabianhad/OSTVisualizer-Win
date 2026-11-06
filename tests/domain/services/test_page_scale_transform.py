import unittest
from ost_visualizer.domain.services.page_scale_transform import (
    position_rescale_factor_between_page_scales,
    rescale_position_between_page_scales,
    rescale_position_values,
)


class PageScaleTransformTests(unittest.TestCase):
    def test_position_factor_matches_page_scale_rescale_rule(self):
        factor = position_rescale_factor_between_page_scales(
            (0.125, 12.0), (0.1875, 12.0)
        )
        self.assertAlmostEqual(factor, 2.0 / 3.0)

    def test_zero_source_scale_uses_fallback_identity_source_ratio(self):
        factor = position_rescale_factor_between_page_scales((0.0, 12.0), (0.25, 12.0))
        self.assertEqual(factor, 48.0)

    def test_rescale_position_preserves_non_numeric_values(self):
        self.assertEqual(
            rescale_position_values(["6", "label", 12.0], 0.5),
            [3.0, "label", 6.0],
        )

    def test_rescale_position_between_page_scales_returns_copy_when_unchanged(self):
        position = [1.0, 2.0, 3.0, 4.0]
        scaled = rescale_position_between_page_scales(
            position, (1.0, 12.0), (1.0, 12.0)
        )
        self.assertEqual(scaled, position)
        self.assertIsNot(scaled, position)


class AnnotationSnapshotTransformTests(unittest.TestCase):
    def test_round_trip_preserves_angles_and_does_not_mutate_snapshots(self):
        from ost_visualizer.domain.services.page_scale_transform import (
            rescale_annotation_position_between_page_scales,
        )

        for kind, values, expected_scaled in (
            (
                "ink",
                [0.123456789, 96.0, 48.0, 192.0, 96.0],
                [0.123456789, 48.0, 24.0, 96.0, 48.0],
            ),
            (
                "rect",
                [96.0, 48.0, 192.0, 96.0, 0.123456789],
                [48.0, 24.0, 96.0, 48.0, 0.123456789],
            ),
            (
                "text",
                [96.0, 48.0, 192.0, 96.0, 0.123456789, 7.25],
                [48.0, 24.0, 96.0, 48.0, 0.123456789, 7.25],
            ),
        ):
            with self.subTest(kind=kind):
                original = list(values)
                for _ in range(20):
                    scaled = rescale_annotation_position_between_page_scales(
                        kind, values, (1, 96), (1, 48)
                    )
                    self.assertEqual(values, original)
                    self.assertIsNot(scaled, values)
                    self.assertEqual(scaled, expected_scaled)
                    values = rescale_annotation_position_between_page_scales(
                        kind, scaled, (1, 48), (1, 96)
                    )
                    self.assertEqual(scaled, expected_scaled)
                    self.assertIsNot(values, scaled)
                    self.assertEqual(values, original)



class PageScaleRatioTests(unittest.TestCase):
    def test_ratio_is_second_over_first_with_identity_for_missing_or_unusable_scales(self):
        from ost_visualizer.domain.services.page_scale_transform import page_scale_ratio

        self.assertEqual(page_scale_ratio((0.125, 12.0)), 96.0)
        self.assertEqual(page_scale_ratio((2, 1)), 0.5)
        self.assertEqual(page_scale_ratio(None), 1.0)
        self.assertEqual(page_scale_ratio((0.0, 12.0)), 1.0)
        self.assertEqual(page_scale_ratio((None, 12.0)), 1.0)
        self.assertEqual(page_scale_ratio(("bad", 12.0)), 1.0)
        self.assertEqual(page_scale_ratio((1.0, "bad")), 1.0)
        self.assertEqual(page_scale_ratio((1.0, [])), 0.0)
        self.assertEqual(page_scale_ratio(("0.5", "2")), 4.0)

    def test_a_missing_second_scale_collapses_the_ratio_to_zero_not_identity(self):
        from ost_visualizer.domain.services.page_scale_transform import page_scale_ratio

        self.assertEqual(page_scale_ratio((1.0, None)), 0.0)
        self.assertEqual(page_scale_ratio((1.0, 0.0)), 0.0)

    def test_factor_between_scales_is_target_over_source_with_identity_for_degenerate_source(self):
        factor = position_rescale_factor_between_page_scales
        self.assertEqual(factor((1, 96), (1, 48)), 0.5)
        self.assertEqual(factor(None, (1, 2)), 2.0)
        self.assertEqual(factor((1, 2), None), 0.5)
        self.assertEqual(factor(None, None), 1.0)
        # A source whose second scale is missing has ratio 0: no meaningful factor.
        self.assertEqual(factor((1, 0), (1, 48)), 1.0)
        self.assertEqual(factor((1, None), (1, 48)), 1.0)
        # A target ratio of zero scales every coordinate to zero.
        self.assertEqual(factor((1, 96), (1, 0)), 0.0)


class PageScaleRescaleTests(unittest.TestCase):
    def test_unchanged_scales_return_an_untouched_copy_even_for_text_numbers(self):
        position = ["6", 2, "x"]
        scaled = rescale_position_between_page_scales(position, (1, 12), (1, 12))
        self.assertEqual(scaled, ["6", 2, "x"])
        self.assertIsNot(scaled, position)
        self.assertEqual(
            rescale_position_between_page_scales(iter([1, 2]), None, None), [1, 2]
        )

    def test_changed_scales_multiply_every_numeric_value_and_keep_others(self):
        scaled = rescale_position_between_page_scales([2, "4", None, "n"], (1, 12), (1, 6))
        self.assertEqual(scaled, [1.0, 2.0, None, "n"])
        self.assertEqual(
            rescale_position_between_page_scales([1.0, 2.0], (1, 1), (1, 3)), [3.0, 6.0]
        )
        self.assertEqual(rescale_position_between_page_scales([], (1, 1), (1, 3)), [])

    def test_a_tiny_factor_difference_is_treated_as_unchanged(self):
        scaled = rescale_position_between_page_scales(["5"], (1.0, 1.0), (1.0, 1.0 + 1e-12))
        self.assertEqual(scaled, ["5"])
        scaled = rescale_position_between_page_scales([5], (1.0, 1.0), (1.0, 1.0 + 1e-6))
        self.assertAlmostEqual(scaled[0], 5 * (1.0 + 1e-6))

    def test_scale_values_are_not_mutated_for_unknown_annotation_types(self):
        from ost_visualizer.domain.services.page_scale_transform import (
            rescale_annotation_position_between_page_scales,
        )

        values = [10.0, 20.0, 30.0, 40.0]
        self.assertEqual(
            rescale_annotation_position_between_page_scales("hotlink", values, (1, 2), (1, 4)),
            [20.0, 40.0, 60.0, 80.0],
        )
        self.assertEqual(values, [10.0, 20.0, 30.0, 40.0])
        self.assertEqual(
            rescale_annotation_position_between_page_scales("rect", values, (1, 2), (1, 2)),
            values,
        )


if __name__ == "__main__":
    unittest.main()
