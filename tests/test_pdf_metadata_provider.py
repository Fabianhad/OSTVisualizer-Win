import logging
import tempfile
import unittest
from ost_visualizer.infrastructure.pdf_metadata_provider import (
    NativePdfMetadataProvider,
)


class FailingRenderer:
    def open(self, file_path):
        raise RuntimeError(f"{file_path} failed")

    def close(self):
        raise AssertionError("close should not be called when open fails")


class PdfMetadataProviderTests(unittest.TestCase):
    def test_pdf_failure_logs_do_not_include_source_path(self):
        logger = logging.getLogger("tests.pdf_metadata_provider")
        provider = NativePdfMetadataProvider(
            logger=logger,
            renderer_factory=FailingRenderer,
        )
        with tempfile.NamedTemporaryFile(suffix=".pdf") as pdf_file:
            with self.assertLogs(logger, level="WARNING") as captured:
                result = provider.get_page_info(pdf_file.name, 0)
        self.assertEqual(result.status, "unavailable")
        output = "\n".join(captured.output)
        self.assertIn("RuntimeError", output)
        self.assertNotIn(pdf_file.name, output)


if __name__ == "__main__":
    unittest.main()
