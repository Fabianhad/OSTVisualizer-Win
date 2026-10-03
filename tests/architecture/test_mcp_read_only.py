import unittest
from tests.paths import REPO_ROOT

_MCP_SERVER_MODULES = {
    "bridge_client.py",
    "internal_server.py",
    "main.py",
    "output_artifacts.py",
    "registry.py",
    "serializers.py",
    "server.py",
}


def _mcp_server_sources(test_case, root):
    files = sorted((root / "mcp_server").glob("*.py"))
    # Positive control: the glob must reach the real MCP modules, otherwise
    # every token scan below would pass over an empty file list.
    test_case.assertTrue(
        _MCP_SERVER_MODULES <= {path.name for path in files},
        sorted(path.name for path in files),
    )
    return files


class McpReadOnlyEnforcementTests(unittest.TestCase):
    def test_mcp_server_does_not_import_write_paths(self):
        root = REPO_ROOT / "ost_visualizer"
        files = _mcp_server_sources(self, root) + [
            root / "application" / "services" / "mcp_read_service.py",
            root / "presentation" / "services" / "mcp_context_bridge.py",
        ]
        forbidden = (
            "MdbWriter",
            "ProjectWriteService",
            "project_write_service",
            "execute_command",
            "SummaryCsvExportService",
            "summary_csv_export_service",
            "export_handler",
        )
        for path in files:
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, f"{token} should not appear in {path}")

    def test_mcp_server_does_not_expose_temporary_csv_paths(self):
        root = REPO_ROOT / "ost_visualizer"
        files = _mcp_server_sources(self, root) + [
            root / "application" / "services" / "mcp_read_service.py",
        ]
        for path in files:
            text = path.read_text(encoding="utf-8").lower()
            self.assertNotIn("csv", text, f"CSV should not appear in {path}")

    def test_mcp_server_does_not_import_qt_or_presentation(self):
        root = REPO_ROOT / "ost_visualizer"
        files = _mcp_server_sources(self, root)
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
