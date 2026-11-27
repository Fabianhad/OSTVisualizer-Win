import errno
import unittest
from ost_visualizer.domain.services.file_error_reasons import (
    describe_failure,
    file_error_reason,
    user_failure_message,
)

NOT_FOUND = "The file was not found. It may have been moved, renamed or deleted."
DENIED = (
    "Access to the file was denied. Check that you have permission to use the file "
    "and its folder."
)
IN_USE = "The file is open in another program. Close it there and try again."
DISK_FULL = "There is not enough space on the disk. Free up space and try again."
NETWORK = (
    "The network location is not available. Check the network connection and try "
    "again."
)


def _windows_error(winerror, error_class=OSError):
    error = error_class(errno.EIO, "system text")
    error.winerror = winerror
    return error


class FileErrorReasonTests(unittest.TestCase):
    def test_each_known_cause_has_its_own_sentence(self):
        cases = (
            ("missing file", FileNotFoundError(errno.ENOENT, "gone"), NOT_FOUND),
            ("missing by errno", OSError(errno.ENOENT, "gone"), NOT_FOUND),
            ("missing folder", _windows_error(3), NOT_FOUND),
            ("denied", PermissionError(errno.EACCES, "denied"), DENIED),
            ("not permitted", PermissionError(errno.EPERM, "not permitted"), DENIED),
            ("denied by code", _windows_error(5), DENIED),
            ("sharing violation", _windows_error(32, PermissionError), IN_USE),
            ("lock violation", _windows_error(33), IN_USE),
            ("disk full", OSError(errno.ENOSPC, "full"), DISK_FULL),
            ("disk full by code", _windows_error(112), DISK_FULL),
            ("network path", _windows_error(53), NETWORK),
            ("network lost", _windows_error(64), NETWORK),
            ("network share", _windows_error(67), NETWORK),
        )
        for label, error, expected in cases:
            with self.subTest(label):
                self.assertEqual(file_error_reason(error), expected)

    def test_unknown_errors_have_no_specific_sentence(self):
        for error in (
            OSError("[WinError 10054] connection reset"),
            _windows_error(10054),
            ValueError("bad value"),
            RuntimeError("database is locked"),
            KeyError("Bids"),
        ):
            with self.subTest(error=error):
                self.assertIsNone(file_error_reason(error))

    def test_describe_failure_puts_a_known_cause_into_the_template(self):
        template = "The bid could not be opened. {reason}"
        self.assertEqual(
            describe_failure(_windows_error(32), template, "Generic."),
            "The bid could not be opened. " + IN_USE,
        )
        self.assertEqual(
            describe_failure(RuntimeError("raw"), template, "Generic."), "Generic."
        )

    def test_user_failure_message_never_shows_the_raw_text(self):
        self.assertEqual(user_failure_message(_windows_error(5), "Failed."), DENIED)
        for error in (RuntimeError("Bids.UID 4"), ValueError("bad"), KeyError("x")):
            with self.subTest(error=error):
                self.assertEqual(user_failure_message(error, "Failed."), "Failed.")
