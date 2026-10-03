import contextlib
import io
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ost_visualizer.mcp_server import main as mcp_main
from ost_visualizer.mcp_server.main import _configure_logging, _parse_args, main


class McpCliTests(unittest.TestCase):
    def parse_rejected(self, argv):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(
            SystemExit
        ) as raised:
            _parse_args(argv)
        self.assertEqual(raised.exception.code, 2)
        return stderr.getvalue()

    def test_database_argument_is_not_supported(self):
        message = self.parse_rejected(["--database", "demo.mdb"])
        self.assertIn("unrecognized arguments: --database demo.mdb", message)

    def test_app_data_dir_argument_is_not_supported(self):
        message = self.parse_rejected(["--app-data-dir", "alternate"])
        self.assertIn("unrecognized arguments: --app-data-dir alternate", message)

    def test_help_lists_only_the_log_level_option(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(
            SystemExit
        ) as raised:
            _parse_args(["--help"])
        self.assertEqual(raised.exception.code, 0)
        help_text = stdout.getvalue()
        self.assertIn("--log-level", help_text)
        self.assertNotIn("--database", help_text)
        self.assertNotIn("--app-data-dir", help_text)

    def test_log_level_defaults_to_warning_and_accepts_valid_levels(self):
        self.assertEqual(_parse_args([]).log_level, "WARNING")
        self.assertEqual(_parse_args(["--log-level", "DEBUG"]).log_level, "DEBUG")

    def test_invalid_log_level_is_rejected(self):
        message = self.parse_rejected(["--log-level", "VERBOSE"])
        self.assertIn("invalid choice: 'VERBOSE'", message)


class McpMainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.close_handlers)
        self.app_data_dir = Path(self.tmp.name) / "app_data"

    @staticmethod
    def close_handlers():
        for handler in list(mcp_main.LOGGER.handlers):
            handler.close()
            mcp_main.LOGGER.removeHandler(handler)

    def test_configure_logging_writes_to_stderr_and_app_data_file_only(self):
        captured_stderr = io.StringIO()
        with contextlib.redirect_stderr(captured_stderr):
            logger = _configure_logging(self.app_data_dir, "INFO")
        self.assertIs(logger, mcp_main.LOGGER)
        self.assertEqual(logger.level, logging.INFO)
        self.assertFalse(logger.propagate)
        self.assertTrue(self.app_data_dir.is_dir())
        stream_handlers = [
            h for h in logger.handlers if type(h) is logging.StreamHandler
        ]
        file_handlers = [
            h for h in logger.handlers if isinstance(h, logging.FileHandler)
        ]
        self.assertEqual(len(logger.handlers), 2)
        self.assertEqual([h.stream for h in stream_handlers], [captured_stderr])
        self.assertNotIn(sys.stdout, [h.stream for h in stream_handlers])
        self.assertEqual(
            [Path(h.baseFilename) for h in file_handlers],
            [(self.app_data_dir / "mcp_server.log").resolve()],
        )
        self.assertTrue(all(h.level == logging.INFO for h in logger.handlers))

    def test_configure_logging_replaces_handlers_and_unknown_level_warns(self):
        _configure_logging(self.app_data_dir, "DEBUG")
        self.close_handlers()
        with contextlib.redirect_stderr(io.StringIO()):
            logger = _configure_logging(self.app_data_dir, "bogus")
        self.assertEqual(len(logger.handlers), 2)
        self.assertEqual(logger.level, logging.WARNING)
        logger.warning("recorded")
        for handler in logger.handlers:
            handler.flush()
        log_text = (self.app_data_dir / "mcp_server.log").read_text(encoding="utf-8")
        self.assertIn("WARNING ost_visualizer.mcp: recorded", log_text)

    def test_configure_logging_clears_previously_attached_handlers(self):
        stale = logging.NullHandler()
        mcp_main.LOGGER.addHandler(stale)
        logger = _configure_logging(self.app_data_dir, "ERROR")
        self.assertNotIn(stale, logger.handlers)
        self.assertEqual(len(logger.handlers), 2)

    def test_main_runs_server_with_default_app_data_dir_and_returns_zero(self):
        calls = []

        def fake_run_stdio_server(app_data_dir=None, logger=None):
            calls.append((app_data_dir, logger))

        with patch.object(
            mcp_main, "get_app_data_dir", return_value=self.app_data_dir
        ), patch.object(mcp_main, "run_stdio_server", fake_run_stdio_server):
            result = main(["--log-level", "ERROR"])
        self.assertEqual(result, 0)
        self.assertEqual(calls, [(self.app_data_dir, mcp_main.LOGGER)])
        self.assertEqual(mcp_main.LOGGER.level, logging.ERROR)
        self.assertTrue((self.app_data_dir / "mcp_server.log").exists())


if __name__ == "__main__":
    unittest.main()
