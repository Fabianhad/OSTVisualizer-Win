import dataclasses
import errno
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ost_visualizer.application.utils import path_probe
from ost_visualizer.application.utils.path_probe import (
    PathProbeResult,
    PathProbeState,
    known_inaccessible_reason,
    probe_path,
)

LOGGER = "ost_visualizer.application.utils.path_probe"
SHARE_PDF = "\\\\AC-SERVER\\Estimating\\Drawings\\S-100.pdf"


def windows_error(winerror, path=SHARE_PDF, message="Windows error"):
    return OSError(None, message, path, winerror)


class _ProbeStateFixture(unittest.TestCase):
    def setUp(self):
        path_probe._inaccessible_reasons.clear()
        self.addCleanup(path_probe._inaccessible_reasons.clear)

    def stat_raising(self, error):
        return patch.object(path_probe, "_stat_file", side_effect=error)


class ProbePathStateTests(_ProbeStateFixture):
    def test_an_existing_file_reports_its_kind_and_size(self):
        with tempfile.TemporaryDirectory() as folder:
            file_path = Path(folder) / "sheet.pdf"
            file_path.write_bytes(b"12345")
            self.assertEqual(
                probe_path(str(file_path)),
                PathProbeResult(PathProbeState.EXISTS, is_file=True, size=5),
            )
            self.assertEqual(
                probe_path(file_path),
                PathProbeResult(PathProbeState.EXISTS, is_file=True, size=5),
            )
            folder_result = probe_path(folder)
            self.assertIs(folder_result.state, PathProbeState.EXISTS)
            self.assertTrue(folder_result.exists)
            self.assertFalse(folder_result.is_file)

    def test_absent_paths_and_unusable_names_are_missing_without_a_reason(self):
        with tempfile.TemporaryDirectory() as folder:
            absent = os.path.join(folder, "absent.pdf")
            with self.assertNoLogs(LOGGER, "WARNING"):
                for path in (absent, os.path.join(absent, "child.pdf"), "", None):
                    with self.subTest(path=path):
                        result = probe_path(path)
                        self.assertEqual(
                            result, PathProbeResult(PathProbeState.MISSING)
                        )
                        self.assertFalse(result.exists)
                        self.assertFalse(result.is_file)
                        self.assertEqual(result.size, 0)
                        with self.assertRaises(dataclasses.FrozenInstanceError):
                            result.state = PathProbeState.EXISTS
                self.assertEqual(
                    probe_path("bad\0name.pdf"), PathProbeResult(PathProbeState.MISSING)
                )

    def test_not_found_and_invalid_name_errors_stay_missing(self):
        with self.assertNoLogs(LOGGER, "WARNING"):
            for winerror in (2, 3, 21, 123, 1921):
                with self.subTest(winerror=winerror):
                    with self.stat_raising(windows_error(winerror)):
                        self.assertIs(
                            probe_path(SHARE_PDF).state, PathProbeState.MISSING
                        )
            for error in (
                FileNotFoundError(2, "gone"),
                NotADirectoryError(20, "not a folder"),
            ):
                with self.subTest(error=type(error).__name__):
                    with self.stat_raising(error):
                        self.assertIs(probe_path("x.pdf").state, PathProbeState.MISSING)

    def test_network_and_permission_failures_are_inaccessible_with_a_reason(self):
        expected = {
            1326: "the network credentials for \\\\AC-SERVER were rejected.",
            1219: "\\\\AC-SERVER is already connected with different network "
            "credentials.",
            1311: "no logon server is available to check the network credentials "
            "for \\\\AC-SERVER.",
            5: "access is denied.",
            53: "the network path \\\\AC-SERVER was not found.",
            64: "the network connection to \\\\AC-SERVER was lost.",
            67: "the network share on \\\\AC-SERVER was not found.",
        }
        for winerror, reason in expected.items():
            with self.subTest(winerror=winerror):
                path_probe._inaccessible_reasons.clear()
                with (
                    self.stat_raising(windows_error(winerror)),
                    self.assertLogs(LOGGER, "WARNING"),
                ):
                    result = probe_path(SHARE_PDF)
                self.assertEqual(
                    result,
                    PathProbeResult(
                        PathProbeState.INACCESSIBLE,
                        reason=f"Cannot access the file: {reason}",
                    ),
                )
                self.assertFalse(result.exists)

    def test_any_other_os_error_is_inaccessible_with_the_system_text(self):
        for error, reason in (
            (
                windows_error(59, message="An unexpected network error occurred"),
                "Cannot access the file: An unexpected network error occurred",
            ),
            (
                OSError(errno.EIO, "Input/output error"),
                "Cannot access the file: Input/output error",
            ),
            (OSError(), "Cannot access the file: OSError"),
        ):
            with self.subTest(error=error):
                path_probe._inaccessible_reasons.clear()
                with self.stat_raising(error), self.assertLogs(LOGGER, "WARNING"):
                    result = probe_path(SHARE_PDF)
                self.assertEqual(result.state, PathProbeState.INACCESSIBLE)
                self.assertEqual(result.reason, reason)

    def test_unexpected_exceptions_never_escape(self):
        with self.stat_raising(RuntimeError("driver bug")):
            with self.assertLogs(LOGGER, "WARNING"):
                result = probe_path(SHARE_PDF)
        self.assertEqual(
            result,
            PathProbeResult(
                PathProbeState.INACCESSIBLE,
                reason="Cannot access the file: RuntimeError",
            ),
        )
        with self.stat_raising(KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                probe_path(SHARE_PDF)

    def test_reason_names_the_server_drive_or_a_generic_location(self):
        for path, location in (
            ("\\\\AC-SERVER\\Estimating\\a.pdf", "\\\\AC-SERVER"),
            ("\\\\?\\UNC\\AC-SERVER\\Estimating\\a.pdf", "\\\\AC-SERVER"),
            ("Z:\\Estimating\\a.pdf", "Z:"),
            # No server name after the UNC prefix: the drive itself is named.
            ("\\\\?\\UNC\\\\share\\a.pdf", "\\\\?\\UNC"),
        ):
            with self.subTest(path=path):
                path_probe._inaccessible_reasons.clear()
                with (
                    self.stat_raising(windows_error(1326, path)),
                    self.assertLogs(LOGGER, "WARNING"),
                ):
                    reason = probe_path(path).reason
                self.assertEqual(
                    reason,
                    f"Cannot access the file: the network credentials for {location} "
                    "were rejected.",
                )

    def test_a_path_without_a_server_or_drive_gets_a_full_sentence_per_error(self):
        expected = {
            1326: "the network credentials were rejected.",
            1219: "the file location is already connected with different network "
            "credentials.",
            1311: "no logon server is available to check the network credentials.",
            5: "access is denied.",
            53: "the network path was not found.",
            64: "the network connection was lost.",
            67: "the network share was not found.",
        }
        for winerror, reason in expected.items():
            with self.subTest(winerror=winerror):
                path_probe._inaccessible_reasons.clear()
                with (
                    self.stat_raising(windows_error(winerror, "relative\\a.pdf")),
                    self.assertLogs(LOGGER, "WARNING"),
                ):
                    result = probe_path("relative\\a.pdf")
                self.assertEqual(result.reason, f"Cannot access the file: {reason}")


class ProbePathLoggingTests(_ProbeStateFixture):
    def test_an_inaccessible_path_is_logged_once_until_it_recovers(self):
        with self.stat_raising(windows_error(1326)):
            with self.assertLogs(LOGGER, "WARNING") as logs:
                for _attempt in range(3):
                    probe_path(SHARE_PDF)
                probe_path(SHARE_PDF.replace("S-100.pdf", "s-100.PDF"))
        self.assertEqual(
            logs.output,
            [
                f"WARNING:{LOGGER}:Cannot access {SHARE_PDF} (WinError 1326): Cannot "
                "access the file: the network credentials for \\\\AC-SERVER were "
                "rejected."
            ],
        )
        self.assertEqual(
            known_inaccessible_reason(SHARE_PDF),
            "Cannot access the file: the network credentials for \\\\AC-SERVER were "
            "rejected.",
        )
        with self.stat_raising(windows_error(53)):
            with self.assertLogs(LOGGER, "WARNING") as changed:
                probe_path(SHARE_PDF)
        self.assertEqual(len(changed.records), 1)
        with patch.object(
            path_probe, "_stat_file", return_value=os.stat(__file__)
        ), self.assertNoLogs(LOGGER, "WARNING"):
            self.assertIs(probe_path(SHARE_PDF).state, PathProbeState.EXISTS)
        self.assertEqual(known_inaccessible_reason(SHARE_PDF), "")
        with self.stat_raising(windows_error(1326)):
            with self.assertLogs(LOGGER, "WARNING") as again:
                probe_path(SHARE_PDF)
        self.assertEqual(len(again.records), 1)
        with self.stat_raising(windows_error(2)):
            self.assertIs(probe_path(SHARE_PDF).state, PathProbeState.MISSING)
        self.assertEqual(known_inaccessible_reason(SHARE_PDF), "")

    def test_non_windows_errors_are_logged_with_their_type(self):
        with self.stat_raising(OSError(errno.EIO, "Input/output error")):
            with self.assertLogs(LOGGER, "WARNING") as logs:
                probe_path("x.pdf")
        self.assertEqual(
            logs.output,
            [
                f"WARNING:{LOGGER}:Cannot access x.pdf (OSError): Cannot access the "
                "file: Input/output error"
            ],
        )

    def test_known_reasons_are_bounded_and_need_no_file_access(self):
        with patch.object(path_probe, "_MAX_KNOWN_INACCESSIBLE_PATHS", 2):
            with self.stat_raising(windows_error(1326)), self.assertLogs(LOGGER):
                for name in ("a.pdf", "b.pdf", "c.pdf"):
                    probe_path(name)
                probe_path("b.pdf")
                probe_path("d.pdf")
        with patch.object(
            path_probe, "_stat_file", side_effect=AssertionError("no file access")
        ):
            self.assertEqual(known_inaccessible_reason("a.pdf"), "")
            self.assertEqual(known_inaccessible_reason("c.pdf"), "")
            self.assertNotEqual(known_inaccessible_reason("b.pdf"), "")
            self.assertNotEqual(known_inaccessible_reason("d.pdf"), "")
            self.assertEqual(known_inaccessible_reason(""), "")
            self.assertEqual(known_inaccessible_reason(None), "")


if __name__ == "__main__":
    unittest.main()
