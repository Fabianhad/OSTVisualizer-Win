import unittest

from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)


class ColorServiceTests(unittest.TestCase):
    def test_numeric_rgb_sequence_is_not_treated_as_color_opacity_pair(self):
        self.assertEqual(
            ColorService().convert_to_rgba((255, 128, 0)),
            (1.0, 128 / 255.0, 0.0, 1.0),
        )

    def test_numeric_rgba_sequence_converts_to_hex_with_opacity(self):
        self.assertEqual(
            ColorService().as_hex_with_opacity((255, 128, 0, 0.25)),
            ("#ff8000", 0.25),
        )

    def test_condition_color_preserves_black_fill(self):
        condition = Condition(uid="condition-1", color_fill=0)

        self.assertEqual(ColorService().get_condition_color(condition), [0, 0, 0])


if __name__ == "__main__":
    unittest.main()
