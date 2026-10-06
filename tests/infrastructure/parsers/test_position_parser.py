import unittest
from ost_visualizer.infrastructure.parsers import position_parser
from ost_visualizer.infrastructure.parsers.position_parser import (
    convert_elevation_in_name,
    extract_z_value_from_name,
)


class ElevationTextValidityCharacterizationTests(unittest.TestCase):
    def test_every_accepted_elevation_text_shape(self):
        accepted = (
            "745' 0\"",
            "12' 6 1/2\"",
            "12'-6\"",
            "5' 0\"",
            "5'x",
            '6"',
            '1/2"',
            '3 1/2"',
            "1m 20cm",
            "1m and 20cm",
            "1m+20cm",
            "2,5 m",
            "3 meters",
            "30 cm",
            "30 centimeters",
            "-4' 2\"",
        )
        for text in accepted:
            with self.subTest(text=text):
                self.assertTrue(position_parser._is_valid_elevation_text(text))

    def test_every_rejected_elevation_text_shape(self):
        rejected = (
            "",
            "later",
            "5pm",
            "abc 5'",
            "'",
            "m",
            "@T 5'",
            "5'",
            "-4'",
            "5' wall",
        )
        for text in rejected:
            with self.subTest(text=text):
                self.assertFalse(position_parser._is_valid_elevation_text(text))


class ExtractZValueCharacterizationTests(unittest.TestCase):
    def setUp(self):
        position_parser.clear_caches()
        self.addCleanup(position_parser.clear_caches)

    def test_top_and_bottom_imperial_values(self):
        self.assertEqual(extract_z_value_from_name("F9 @T 410' 3\""), (4923.0, True))
        self.assertEqual(extract_z_value_from_name("Wall @B 8' 0\""), (96.0, False))
        self.assertEqual(
            extract_z_value_from_name("Slab @T 12' 6 1/2\""), (150.5, True)
        )

    def test_metric_values_are_converted_to_inches(self):
        value, is_top = extract_z_value_from_name("Wall @T 2.54 m")
        self.assertTrue(is_top)
        self.assertAlmostEqual(value, 100.0, places=6)

    def test_names_without_a_valid_elevation_have_none(self):
        for name in ("", "Wall", "Wall @T later", "Wall @T 5pm", "Wall @T 5' 2 m"):
            with self.subTest(name=name):
                self.assertEqual(extract_z_value_from_name(name), (0.0, False))


class ConvertElevationInNameCharacterizationTests(unittest.TestCase):
    def test_imperial_to_metric_and_back(self):
        self.assertEqual(
            convert_elevation_in_name("Wall @B 8' 0\"", True), "Wall @B 243.84 cm"
        )
        self.assertEqual(
            convert_elevation_in_name("Wall @B 243.84 cm", False), "Wall @B 8' 0\""
        )

    def test_names_without_a_full_elevation_are_left_alone(self):
        for name in ("Wall", "Wall @T later", "Wall @T 5' junk"):
            with self.subTest(name=name):
                self.assertEqual(convert_elevation_in_name(name, True), name)


if __name__ == "__main__":
    unittest.main()
