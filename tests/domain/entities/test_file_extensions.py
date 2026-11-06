import unittest
from ost_visualizer.domain.entities.file_extensions import (
    CSV_EXTENSION,
    OSP_IMAGE_EXTENSIONS,
    is_csv_suffix,
    is_pdf_suffix,
)


class FileExtensionsTest(unittest.TestCase):
    def test_pdf_suffix_matches_suffix_or_path_case_insensitively(self):
        self.assertTrue(is_pdf_suffix(".PDF"))
        self.assertTrue(is_pdf_suffix(r"C:\jobs\plans\A101.Pdf"))
        self.assertFalse(is_pdf_suffix("A101.tif"))

    def test_csv_suffix_matches_suffix_or_path_case_insensitively(self):
        self.assertTrue(is_csv_suffix(".CSV"))
        self.assertTrue(is_csv_suffix(r"C:\jobs\summary.Csv"))
        self.assertFalse(is_csv_suffix("summary.pdf"))
        self.assertEqual(CSV_EXTENSION, ".csv")

    def test_osp_image_extensions_are_shared_domain_set(self):
        self.assertEqual(
            OSP_IMAGE_EXTENSIONS,
            frozenset({".pdf", ".tif", ".tiff"}),
        )


class FileExtensionHelperTests(unittest.TestCase):
    def test_constants_are_exact_lowercase_dotted_suffixes(self):
        from ost_visualizer.domain.entities import file_extensions as fx

        self.assertEqual(
            (fx.PDF_EXTENSION, fx.CSV_EXTENSION, fx.TIF_EXTENSION, fx.TIFF_EXTENSION),
            (".pdf", ".csv", ".tif", ".tiff"),
        )
        self.assertEqual(fx.TIFF_EXTENSIONS, frozenset({".tif", ".tiff"}))
        self.assertIsInstance(fx.TIFF_EXTENSIONS, frozenset)

    def test_normalized_suffix_lowercases_only_the_last_suffix_of_a_path(self):
        from ost_visualizer.domain.entities.file_extensions import normalized_suffix

        self.assertEqual(normalized_suffix("a/b/Plan.TIFF"), ".tiff")
        self.assertEqual(normalized_suffix("archive.tar.GZ"), ".gz")
        self.assertEqual(normalized_suffix("noext"), "")

    def test_a_bare_suffix_with_no_separator_is_used_as_is(self):
        for value in (".pdf", ".PDF", ".Pdf"):
            self.assertIs(is_pdf_suffix(value), True)
        self.assertIs(is_csv_suffix(".Csv"), True)
        self.assertIs(is_pdf_suffix(".csv"), False)
        self.assertIs(is_csv_suffix(".pdf"), False)

    def test_dotted_paths_with_separators_use_the_real_file_suffix(self):
        for value in ("./plans/A1.pdf", r".\plans\A1.pdf", ".hidden/dir.PDF"):
            with self.subTest(value=value):
                self.assertIs(is_pdf_suffix(value), True)
        for value in ("./plans/A1.csv", r".\plans\A1.csv", ".hidden/dir.csv"):
            with self.subTest(value=value):
                self.assertIs(is_csv_suffix(value), True)
        self.assertIs(is_pdf_suffix("./plans.pdf/notes.txt"), False)
        self.assertIs(is_pdf_suffix(r".\plans.pdf\notes.txt"), False)

    def test_empty_none_and_extensionless_values_match_nothing(self):
        for value in (None, "", "pdf", "csv", "A101", "A101.pdf.bak"):
            with self.subTest(value=value):
                self.assertIs(is_pdf_suffix(value), False)
                self.assertIs(is_csv_suffix(value), False)

    def test_path_objects_are_accepted(self):
        from pathlib import PurePath

        self.assertIs(is_pdf_suffix(PurePath("plans") / "A1.PDF"), True)
        self.assertIs(is_csv_suffix(PurePath("out") / "s.csv"), True)

    def test_plain_file_names_without_a_separator_use_their_suffix(self):
        self.assertIs(is_pdf_suffix("A101.PDF"), True)
        self.assertIs(is_csv_suffix("summary.CSV"), True)
        self.assertIs(is_pdf_suffix("summary.CSV"), False)


if __name__ == "__main__":
    unittest.main()
