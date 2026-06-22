import unittest
from ost_visualizer.domain.entities.file_extensions import (
    CSV_EXTENSION,
    OSP_IMAGE_EXTENSIONS,
    PDF_EXTENSION,
    TIF_EXTENSION,
    TIFF_EXTENSION,
    is_csv_suffix,
    is_pdf_suffix,
    is_tiff_suffix,
)


class FileExtensionsTest(unittest.TestCase):
    def test_pdf_suffix_matches_suffix_or_path_case_insensitively(self):
        self.assertTrue(is_pdf_suffix(".PDF"))
        self.assertTrue(is_pdf_suffix(r"C:\jobs\plans\A101.Pdf"))
        self.assertFalse(is_pdf_suffix("A101.tif"))

    def test_tiff_suffix_matches_both_tif_extensions(self):
        self.assertTrue(is_tiff_suffix(".TIF"))
        self.assertTrue(is_tiff_suffix("overlay.TIFF"))
        self.assertFalse(is_tiff_suffix("overlay.pdf"))

    def test_csv_suffix_matches_suffix_or_path_case_insensitively(self):
        self.assertTrue(is_csv_suffix(".CSV"))
        self.assertTrue(is_csv_suffix(r"C:\jobs\summary.Csv"))
        self.assertFalse(is_csv_suffix("summary.pdf"))
        self.assertEqual(CSV_EXTENSION, ".csv")

    def test_osp_image_extensions_are_shared_domain_set(self):
        self.assertEqual(
            OSP_IMAGE_EXTENSIONS,
            frozenset({PDF_EXTENSION, TIF_EXTENSION, TIFF_EXTENSION}),
        )


if __name__ == "__main__":
    unittest.main()
