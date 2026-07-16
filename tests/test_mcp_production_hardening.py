import unittest
from pathlib import Path


class McpProductionHardeningTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent.parent

    def test_helper_entrypoint_routes_to_canonical_main(self):
        text = (self.root / "McpServer.py").read_text(encoding="utf-8")
        self.assertIn("from ost_visualizer.mcp_server.main import main", text)
        self.assertIn("raise SystemExit(main())", text)

    def test_helper_path_does_not_import_qt_or_presentation(self):
        files = [self.root / "McpServer.py"]
        files.extend((self.root / "ost_visualizer" / "mcp_server").glob("*.py"))
        forbidden = (
            "PySide6",
            "ost_visualizer.presentation",
            "from ..presentation",
            "from ...presentation",
            "ost_visualizer.config.di_config",
        )
        for path in files:
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, f"{token} should not appear in {path}")

    def test_build_script_copies_helper_next_to_desktop_exe(self):
        text = (self.root / "scripts" / "build.ps1").read_text(encoding="utf-8")
        self.assertIn("'--output-filename=ostv-mcp.exe'", text)
        self.assertNotIn("'--onefile'", text)
        self.assertIn("$McpBuildDir = Join-Path $McpOutDir 'McpServer.dist'", text)
        self.assertIn("$McpHelperExe = Join-Path $McpBuildDir 'ostv-mcp.exe'", text)
        self.assertIn("$DesktopBuildDir = Join-Path $OutDir 'Visualizer.dist'", text)
        self.assertIn(
            "Copy-Item (Join-Path $McpBuildDir '*') -Destination $DesktopBuildDir", text
        )

    def test_component_build_scripts_keep_outputs_independent(self):
        visualizer_text = (self.root / "scripts" / "build-visualizer.ps1").read_text(
            encoding="utf-8"
        )
        mcp_text = (self.root / "scripts" / "build-mcp.ps1").read_text(encoding="utf-8")
        self.assertIn(
            "$MainScript = Join-Path $ProjectRoot 'Visualizer.py'", visualizer_text
        )
        self.assertIn(
            "$OutDir = Join-Path $ProjectRoot 'dist_visualizer'", visualizer_text
        )
        self.assertNotIn("McpServer.py", visualizer_text)
        self.assertNotIn("dist_mcp", visualizer_text)
        self.assertIn("$McpScript = Join-Path $ProjectRoot 'McpServer.py'", mcp_text)
        self.assertIn("$McpOutDir = Join-Path $ProjectRoot 'dist_mcp'", mcp_text)
        self.assertIn("'--output-filename=ostv-mcp.exe'", mcp_text)
        self.assertNotIn("Visualizer.py", mcp_text)
        self.assertNotIn("dist_visualizer", mcp_text)
        self.assertNotIn("Copy-Item", mcp_text)

    def test_obsolete_mcp_dependency_files_are_removed(self):
        requirements_name = "-".join(("requirements", "mcp")) + ".txt"
        setup_name = "-".join(("setup", "mcp")) + ".ps1"
        self.assertFalse((self.root / requirements_name).exists())
        self.assertFalse((self.root / "scripts" / setup_name).exists())

    def test_no_fastmcp_or_sdk_imports_remain_in_helper_path(self):
        paths = [
            self.root / "McpServer.py",
            self.root / "scripts" / "build.ps1",
            self.root / "scripts" / "build-mcp.ps1",
        ]
        paths.extend((self.root / "ost_visualizer" / "mcp_server").glob("*.py"))
        forbidden = (
            "Fast" + "MCP",
            "mcp" + "[cli]",
            "from " + "mcp",
            "import " + "mcp.server",
        )
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, f"{token} should not appear in {path}")


if __name__ == "__main__":
    unittest.main()
