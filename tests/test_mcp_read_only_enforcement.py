import unittest
from pathlib import Path


class McpReadOnlyEnforcementTests(unittest.TestCase):
    def test_mcp_server_does_not_import_write_paths(self):
        root = Path(__file__).resolve().parent.parent / "ost_visualizer"
        files = list((root / "mcp_server").glob("*.py")) + [
            root / "application" / "services" / "mcp_read_service.py",
            root / "presentation" / "services" / "mcp_context_bridge.py",
        ]
        forbidden = (
            "MdbWriter",
            "ProjectWriteService",
            "project_write_service",
            "execute_command",
        )
        for path in files:
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, f"{token} should not appear in {path}")

    def test_mcp_server_does_not_expose_temporary_csv_paths(self):
        root = Path(__file__).resolve().parent.parent / "ost_visualizer"
        files = list((root / "mcp_server").glob("*.py")) + [
            root / "application" / "services" / "mcp_read_service.py",
        ]
        for path in files:
            text = path.read_text(encoding="utf-8").lower()
            self.assertNotIn("csv", text, f"CSV should not appear in {path}")

    def test_mcp_server_does_not_import_qt_or_presentation(self):
        root = Path(__file__).resolve().parent.parent / "ost_visualizer"
        files = list((root / "mcp_server").glob("*.py"))
        forbidden = (
            "PySide6",
            "ost_visualizer.presentation",
            "from ..presentation",
            "from ...presentation",
            "MainWindow",
            "configure_application",
        )
        for path in files:
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, f"{token} should not appear in {path}")


if __name__ == "__main__":
    unittest.main()
