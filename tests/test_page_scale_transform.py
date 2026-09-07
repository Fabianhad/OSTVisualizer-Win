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

    def test_zero_source_scale_uses_legacy_identity_source_ratio(self):
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

        for kind, values in (
            ("ink", [0.123456789, 96.0, 48.0, 192.0, 96.0]),
            ("rect", [96.0, 48.0, 192.0, 96.0, 0.123456789]),
            ("text", [96.0, 48.0, 192.0, 96.0, 0.123456789]),
        ):
            with self.subTest(kind=kind):
                original = list(values)
                for _ in range(20):
                    scaled = rescale_annotation_position_between_page_scales(
                        kind, values, (1, 96), (1, 48)
                    )
                    values = rescale_annotation_position_between_page_scales(
                        kind, scaled, (1, 48), (1, 96)
                    )
                self.assertEqual(values, original)
                self.assertIsNot(values, original)


if __name__ == "__main__":
    unittest.main()
