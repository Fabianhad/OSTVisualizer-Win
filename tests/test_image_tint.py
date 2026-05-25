import unittest

from ost_visualizer.presentation.visualization.utils import ost_image


def _bgra_pixels(image):
    data = image.to_bytes()
    return [tuple(data[i : i + 4]) for i in range(0, len(data), 4)]


class ImageTintTests(unittest.TestCase):
    def test_tint_grayscale_preserves_antialias_alpha(self):
        tinted = ost_image.tint_grayscale(
            bytes([0, 128, 234, 235, 255]),
            5,
            1,
            255,
            80,
            40,
            235,
        )

        black, gray, near_paper, paper, white = _bgra_pixels(tinted)

        self.assertEqual(black, (40, 80, 255, 255))
        self.assertEqual(gray[:3], (40, 80, 255))
        self.assertEqual(near_paper[:3], (40, 80, 255))
        self.assertEqual(paper, (0, 0, 0, 0))
        self.assertEqual(white, (0, 0, 0, 0))
        self.assertGreater(black[3], gray[3])
        self.assertGreater(gray[3], near_paper[3])
        self.assertGreater(near_paper[3], paper[3])

    def test_tint_red_and_blue_keep_alpha_coverage_behavior(self):
        red = _bgra_pixels(ost_image.tint_red(bytes([0, 128, 235]), 3, 1))
        blue = _bgra_pixels(ost_image.tint_blue(bytes([0, 128, 235]), 3, 1))

        self.assertEqual(red[0], (80, 80, 255, 255))
        self.assertEqual(blue[0], (255, 80, 80, 255))
        self.assertEqual(red[1][:3], red[0][:3])
        self.assertEqual(blue[1][:3], blue[0][:3])
        self.assertTrue(0 < red[1][3] < red[0][3])
        self.assertTrue(0 < blue[1][3] < blue[0][3])
        self.assertEqual(red[2], (0, 0, 0, 0))
        self.assertEqual(blue[2], (0, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
