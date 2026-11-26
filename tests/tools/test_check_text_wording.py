import contextlib
import io
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch
from tools import check_text_wording as wording


class RepositoryWordingTests(unittest.TestCase):
    def test_every_text_in_texts_py_follows_the_wording_rules(self):
        self.assertEqual(wording.check(), [])

    def test_the_command_line_check_reports_success(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(wording.main([]), 0)
        self.assertIn(
            "Wording in texts.py follows the AGENTS.md rules.", output.getvalue()
        )

    def test_every_capitalization_exemption_names_an_existing_text_and_a_reason(self):
        texts = wording.load_texts()
        for name, reason in wording.CASE_EXEMPTIONS.items():
            self.assertIn(name, texts)
            self.assertTrue(reason.strip())


class MechanicalRuleTests(unittest.TestCase):
    def test_each_mechanical_violation_is_caught(self):
        cases = {
            "British spelling": (
                "Use metres.",
                "British spelling 'metres' (use 'meters')",
            ),
            "hyphenated British form": (
                "Pre-defined scale",
                "British spelling 'Pre-defined' (use 'predefined')",
            ),
            "leading space": (" Saved.", "leading or trailing space"),
            "trailing space": ("Saved. ", "leading or trailing space"),
            "double space": ("Saved.  Reopen it.", "double space"),
            "ellipsis character": (
                "Loading…",
                "ellipsis character instead of three periods",
            ),
            "en dash": ("Cut north–south", "en or em dash instead of a hyphen"),
            "em dash": ("Saved—reopen it.", "en or em dash instead of a hyphen"),
            "HTML dash entity": (
                "Cut north&ndash;south",
                "en or em dash instead of a hyphen",
            ),
            "curly quote": ("Layer “{name}”", "curly quote"),
            "single-quoted placeholder": (
                "Imported '{filename}'.",
                "single quotes around a placeholder",
            ),
            "repeated word": ("Delete the the layer.", "repeated word 'the the'"),
            "space before question mark": (
                'Delete "{name}" ?',
                "space before punctuation",
            ),
            "space before period": ("Saved .", "space before punctuation"),
            "unit without space": ("{width}px", "no space before unit"),
            "number unit without space": ("12pt", "no space before unit"),
            "plural in parentheses": (
                "Exported {n} page(s).",
                "(s) instead of separate singular and plural strings",
            ),
            "unbalanced braces": (
                "Layer {name already exists.",
                "unbalanced placeholder braces",
            ),
            "positional placeholder": (
                "Layer {} already exists.",
                "placeholder {} is not a name",
            ),
            "numbered placeholder": (
                "Layer {0} already exists.",
                "placeholder {0} is not a name",
            ),
            "two-word hotlink": ("Hot Link History", "term 'Hot Link' (use 'hotlink')"),
            "plural two-word hotlink": (
                "Open Hot Links in:",
                "term 'Hot Links' (use 'hotlinks')",
            ),
            "unable to": (
                "Unable to activate license.",
                "term 'Unable to' (use 'failed to')",
            ),
            "error creating": (
                "Error creating PDF export: {error}",
                "term 'Error creating' (use 'failed to create')",
            ),
        }
        for label, (text, problem) in cases.items():
            with self.subTest(label):
                self.assertIn(problem, wording.mechanical_problems(text))

    def test_texts_that_follow_the_rules_have_no_mechanical_problem(self):
        for text in (
            "Loading...",
            "Cut north-south",
            'Layer "{layer_name}" was not found.',
            "{width} px",
            "AaBbYyZz\n{family}, {style_name}, {point_size} pt",
            "e.g. 3.2 m",
            "Successfully exported {page_count} pages to {filename}",
            "Display Size must be between 10% and 500%.",
            "Connect to SQL Server - Database Creator",
        ):
            with self.subTest(text):
                self.assertEqual(wording.mechanical_problems(text), [])


class CapitalizationRuleTests(unittest.TestCase):
    def test_title_kinds_require_title_case(self):
        for kind in sorted(wording.TITLE_KINDS):
            with self.subTest(kind):
                self.assertEqual(
                    wording.case_problems(kind, "Select image files"),
                    [f"{kind} is not Title Case"],
                )
                self.assertEqual(
                    wording.case_problems(kind, "Create a Database for Me"), []
                )
                self.assertEqual(wording.case_problems(kind, 'Delete "{name}"?'), [])
                self.assertEqual(wording.case_problems(kind, "{width} px"), [])

    def test_sentence_kinds_require_sentence_case(self):
        for kind in sorted(wording.SENTENCE_KINDS):
            with self.subTest(kind):
                self.assertEqual(
                    wording.case_problems(kind, "Detach 3D View"),
                    [f"{kind} is not sentence case"],
                )
                self.assertEqual(
                    wording.case_problems(kind, "show the crane"),
                    [f"{kind} is not sentence case"],
                )
                for text in (
                    "Detach 3D view",
                    "Draw object edges in the 3D view and in HTML exports.",
                    "Clear this to validate the certificate. Keep encryption enabled.",
                    "The crane is visual only; the footing counts as usual.",
                    "{label} was not found:\n{path}",
                    "Allow adding new page from Takeoff tab",
                ):
                    self.assertEqual(wording.case_problems(kind, text), [], text)

    def test_messages_start_with_a_capital_and_end_with_terminal_punctuation(self):
        self.assertEqual(
            wording.case_problems("message", "the layer was saved."),
            ["message does not start with a capital letter"],
        )
        self.assertEqual(
            wording.case_problems("message", "This cannot be undone"),
            ["message does not end with terminal punctuation or a placeholder"],
        )
        for text in (
            "Saved.",
            "Turn this option on?",
            "Failed to add page. {db_locked_hint}",
        ):
            self.assertEqual(wording.case_problems("message", text), [])

    def test_running_text_keeps_domain_nouns_lowercase(self):
        for kind in sorted(wording.RUNNING_TEXT_KINDS):
            with self.subTest(kind):
                self.assertEqual(
                    wording.case_problems(kind, "Refresh the Bid and verify its Page."),
                    [
                        "capitalized 'Bid' in running text",
                        "capitalized 'Page' in running text",
                    ],
                )
                self.assertEqual(
                    wording.case_problems(
                        kind, "Are you sure you want to Delete this condition?"
                    ),
                    ["capitalized 'Delete' in running text"],
                )
                self.assertEqual(
                    wording.case_problems(
                        kind, "Failed to move bids to Deleted Bids. Pages stay."
                    ),
                    [],
                )
        self.assertEqual(wording.case_problems("item", "New Folder"), [])

    def test_unknown_kind_texts_are_checked_for_domain_nouns_only_when_they_read_as_sentences(
        self,
    ):
        texts = {
            "SENTENCE": ("Deleting a Condition removes its takeoff.",),
            "NAME": ("New Folder",),
            "TITLED": ("Delete the Bid Area now",),
        }
        kinds = {"TITLED": {"title", "label"}}
        self.assertEqual(
            wording.check(texts, kinds),
            [
                (
                    "SENTENCE",
                    "Deleting a Condition removes its takeoff.",
                    "capitalized 'Condition' in running text",
                )
            ],
        )

    def test_labels_and_other_kinds_are_not_checked_for_capitalization(self):
        self.assertEqual(
            wording.case_problems("label", "Takeoff in Increments of:"), []
        )
        self.assertEqual(wording.case_problems("placeholder", "localhost, server"), [])


class UsageKindTests(unittest.TestCase):
    def scan(self, source):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder)
            texts = root / "texts.py"
            texts.write_text("SKIPPED = QLabel(INSIDE_TEXTS)\n", encoding="utf-8")
            (root / "module.py").write_text(textwrap.dedent(source), encoding="utf-8")
            return wording.usage_kinds(root, texts)

    def test_the_kind_comes_from_the_call_that_shows_the_constant(self):
        kinds = self.scan(
            """
            button.setToolTip(TIP)
            QtWidgets.QCheckBox(CHECK, self)
            show_warning(self, TITLE, MESSAGE.format(name=name))
            QtWidgets.QPushButton(BUTTON)
            menu.addAction(ACTION)
            ViewWindow(window_title=WINDOW)
            pick_color(dialog_title=COLOR_TITLE)
            tree.setHeaderLabels([HEADER_A, HEADER_B])
            """
        )
        self.assertEqual(kinds["TIP"], {"tooltip"})
        self.assertEqual(kinds["CHECK"], {"option"})
        self.assertEqual(kinds["TITLE"], {"title"})
        self.assertEqual(kinds["MESSAGE"], {"message"})
        self.assertEqual(kinds["BUTTON"], {"button"})
        self.assertEqual(kinds["ACTION"], {"action"})
        self.assertEqual(kinds["WINDOW"], {"title"})
        self.assertEqual(kinds["COLOR_TITLE"], {"title"})
        self.assertEqual(kinds["HEADER_A"], {"header"})
        self.assertNotIn("INSIDE_TEXTS", kinds)

    def test_a_constant_shown_as_two_kinds_is_not_checked_for_capitalization(self):
        texts = {"SHARED": ("Annotation Window",), "TIP": ("Annotation Window",)}
        kinds = {"SHARED": {"tooltip", "title"}, "TIP": {"tooltip"}}
        self.assertEqual(
            wording.check(texts, kinds),
            [("TIP", "Annotation Window", "tooltip is not sentence case")],
        )

    def test_the_command_line_check_fails_and_names_the_text(self):
        with patch.object(
            wording,
            "check",
            return_value=[
                ("NAME", "Loading…", "ellipsis character instead of three periods")
            ],
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(wording.main([]), 1)
        self.assertIn(
            "NAME: ellipsis character instead of three periods: 'Loading…'",
            output.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()
