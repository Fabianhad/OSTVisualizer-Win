import unittest
from ost_visualizer.domain.services.annotation_text_storage import (
    first_unstorable_annotation_character,
    first_unstorable_character_in_annotations,
)


class FirstUnstorableAnnotationCharacterTests(unittest.TestCase):
    def test_latin_1_text_and_empty_values_are_storable(self):
        for text in ("", None, "Café ° ÿ", "plain"):
            with self.subTest(text=text):
                self.assertIsNone(first_unstorable_annotation_character(text))

    def test_the_first_character_outside_latin_1_is_named(self):
        cases = (
            ("Cost 5 €", "€"),
            ("‘quoted’", "‘"),
            ("aα€", "α"),
            ("pin \U0001f4cd", "\U0001f4cd"),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(first_unstorable_annotation_character(text), expected)

    def test_only_text_and_callout_annotations_are_checked(self):
        self.assertIsNone(
            first_unstorable_character_in_annotations(
                [("rect", {"Text": "€"}), ("namedview", {"Text": "€"})]
            )
        )
        self.assertEqual(
            first_unstorable_character_in_annotations(
                [("text", {"Text": "ok"}), ("callout", {"Text": "Ω"})]
            ),
            "Ω",
        )


if __name__ == "__main__":
    unittest.main()
