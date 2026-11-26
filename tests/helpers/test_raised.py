import unittest
from unittest.mock import Mock, call
from tests.helpers.raised import Raised


class RaisedTests(unittest.TestCase):
    def test_equal_only_to_the_same_type_and_text(self):
        self.assertEqual(Raised(RuntimeError, "queue full"), RuntimeError("queue full"))
        self.assertEqual(Raised("OSError", "disk"), OSError("disk"))
        self.assertNotEqual(
            Raised(RuntimeError, "queue full"), RuntimeError("queue closed")
        )
        self.assertNotEqual(
            Raised(RuntimeError, "queue full"), ValueError("queue full")
        )
        self.assertNotEqual(Raised(OSError, "disk"), FileNotFoundError("disk"))
        self.assertNotEqual(Raised(RuntimeError, "queue full"), "queue full")

    def test_works_inside_mock_call_assertions(self):
        shown = Mock()
        shown("window", "Title", "queue full", RuntimeError("queue full"))
        shown.assert_called_once_with(
            "window", "Title", "queue full", Raised(RuntimeError, "queue full")
        )
        with self.assertRaises(AssertionError):
            shown.assert_called_once_with(
                "window", "Title", "queue full", Raised(ValueError, "queue full")
            )
        self.assertEqual(
            shown.call_args,
            call("window", "Title", "queue full", Raised(RuntimeError, "queue full")),
        )


if __name__ == "__main__":
    unittest.main()
