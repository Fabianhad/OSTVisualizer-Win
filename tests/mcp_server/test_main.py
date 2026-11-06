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


class McpLoggingContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(McpMainTests.close_handlers)
        self.app_data_dir = Path(self.tmp.name) / "nested" / "app_data"

    def test_every_documented_level_is_accepted_and_mapped_in_either_case(self):
        expected = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }
        for name, level in expected.items():
            for spelling in (name, name.lower()):
                with self.subTest(level=spelling):
                    self.assertEqual(_parse_args(["--log-level", name]).log_level, name)
                    McpMainTests.close_handlers()
                    with contextlib.redirect_stderr(io.StringIO()):
                        logger = _configure_logging(self.app_data_dir, spelling)
                    self.assertEqual(logger.level, level)
                    self.assertEqual({h.level for h in logger.handlers}, {level})

    def test_the_log_folder_is_created_with_its_parents(self):
        with contextlib.redirect_stderr(io.StringIO()):
            _configure_logging(self.app_data_dir, "INFO")
        self.assertTrue((self.app_data_dir / "mcp_server.log").exists())

    def test_both_handlers_use_the_timestamped_level_name_message_format(self):
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            logger = _configure_logging(self.app_data_dir, "INFO")
        logger.warning("recorded")
        for handler in logger.handlers:
            handler.flush()
        pattern = (
            r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} "
            r"WARNING ost_visualizer\.mcp: recorded$"
        )
        self.assertRegex(captured.getvalue().strip(), pattern)
        file_text = (self.app_data_dir / "mcp_server.log").read_text(encoding="utf-8")
        self.assertRegex(file_text.strip(), pattern)

    def test_the_parser_describes_itself_and_its_only_option(self):
        import os

        stdout = io.StringIO()
        with patch.dict(os.environ, {"COLUMNS": "300"}), contextlib.redirect_stdout(
            stdout
        ), self.assertRaises(SystemExit):
            _parse_args(["--help"])
        lines = [line.strip() for line in stdout.getvalue().splitlines()]
        self.assertIn("Run the OST Visualizer read-only MCP stdio server.", lines)
        self.assertIn("--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}", lines)
        self.assertIn(
            "Logging level. Logs go to stderr and the app data log file.", lines
        )

    def test_running_the_module_as_a_script_parses_its_arguments(self):
        import subprocess

        from tests.paths import REPO_ROOT

        completed = subprocess.run(
            [sys.executable, "-m", "ost_visualizer.mcp_server.main", "--help"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("--log-level", completed.stdout)


if __name__ == "__main__":
    unittest.main()
