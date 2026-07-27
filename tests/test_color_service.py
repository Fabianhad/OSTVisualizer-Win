import unittest

from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)


class ColorServiceTests(unittest.TestCase):
    def test_condition_color_preserves_black_fill(self):
        condition = Condition(uid="condition-1", color_fill=0)

        self.assertEqual(ColorService().get_condition_color(condition), [0, 0, 0])


if __name__ == "__main__":
    unittest.main()
