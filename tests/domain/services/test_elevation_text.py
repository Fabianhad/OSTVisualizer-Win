import unittest
from ost_visualizer.domain.services.elevation_text import (
    ELEVATION_TEXT_PATTERNS,
    is_elevation_text,
    is_strippable_elevation_text,
)


class ElevationTextTests(unittest.TestCase):
    def test_the_six_published_patterns_drive_the_validity_check(self):
        self.assertEqual(len(ELEVATION_TEXT_PATTERNS), 6)
        for text in ("745' 0\"", '6"', "1m 20cm", "2 m", "30 cm", "5'x"):
            with self.subTest(text=text):
                self.assertTrue(is_elevation_text(text))

    def test_feet_alone_is_not_valid_for_derivation_but_is_strippable(self):
        for text in ("5'", "-4'", "5′", "5' "):
            with self.subTest(text=text):
                self.assertFalse(is_elevation_text(text))
                self.assertTrue(is_strippable_elevation_text(text))

    def test_everything_valid_is_strippable(self):
        for text in ("745' 0\"", "12' 6 1/2\"", "1m+20cm"):
            with self.subTest(text=text):
                self.assertTrue(is_strippable_elevation_text(text))

    def test_text_that_is_not_an_elevation_is_neither(self):
        for text in ("", "later", "5pm", "5' wall", "@T 5'", "m"):
            with self.subTest(text=text):
                self.assertFalse(is_elevation_text(text))
                self.assertFalse(is_strippable_elevation_text(text))


if __name__ == "__main__":
    unittest.main()
