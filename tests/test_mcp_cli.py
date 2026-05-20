import contextlib
import io
import unittest
from ost_visualizer.mcp_server.main import _parse_args


class McpCliTests(unittest.TestCase):
    def test_database_argument_is_not_supported(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            _parse_args(["--database", "demo.mdb"])


if __name__ == "__main__":
    unittest.main()
