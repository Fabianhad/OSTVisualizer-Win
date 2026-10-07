import io
import json
import logging
import subprocess
import sys
import tempfile
import tokenize
import unittest
from pathlib import Path
from ost_visualizer.application.dtos.ai_takeoff_dtos import (
    M1A_COMMANDS,
    MAX_EXPOSED_TOOLS,
)
from tests.paths import REPO_ROOT

PACKAGE = REPO_ROOT / "ost_visualizer"
_PROXY_MODULES = {
    "__init__.py",
    "main.py",
    "pipe_client.py",
    "protocol.py",
    "proxy.py",
    "tool_catalog.py",
}
M1A_PRODUCTION_FILES = (
    "application/dtos/ai_takeoff_dtos.py",
    "application/interfaces/i_ai_takeoff_sidecar_repository.py",
    "application/services/ai_takeoff_read_service.py",
    "domain/entities/ai_takeoff.py",
    "infrastructure/persistence/repositories/json_ai_takeoff_sidecar_repository.py",
    "presentation/services/ai_takeoff_bridge.py",
    "presentation/services/ai_takeoff_crop_renderer.py",
    "presentation/services/ai_takeoff_pdf_source.py",
)
WRITE_PATH_TOKENS = (
    "ProjectWriteService",
    "project_write_service",
    "MdbWriter",
    "execute_command",
    "UndoRedoService",
    "insert_takeoffs",
    "save_page_scale",
)


def _proxy_sources(test_case):
    files = sorted((PACKAGE / "mcp_takeoff").glob("*.py"))
    test_case.assertEqual({path.name for path in files}, _PROXY_MODULES)
    return files


def _m1a_sources(test_case):
    files = [PACKAGE / relative for relative in M1A_PRODUCTION_FILES]
    for path in files:
        test_case.assertTrue(path.is_file(), path)
    return files + _proxy_sources(test_case) + [REPO_ROOT / "McpTakeoffServer.py"]


class AiTakeoffProxyIsolationTests(unittest.TestCase):
    def test_entrypoint_routes_to_the_takeoff_main(self):
        text = (REPO_ROOT / "McpTakeoffServer.py").read_text(encoding="utf-8")
        self.assertIn("from ost_visualizer.mcp_takeoff.main import main", text)
        self.assertIn("raise SystemExit(main())", text)

    def test_proxy_sources_never_name_qt_presentation_or_the_app_graph(self):
        forbidden = (
            "PySide6",
            "shiboken6",
            "ost_visualizer.presentation",
            "presentation.",
            "di_config",
            "configure_application",
            "mcp_server",
        )
        for path in _proxy_sources(self) + [REPO_ROOT / "McpTakeoffServer.py"]:
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, f"{token} should not appear in {path}")

    def test_a_fresh_interpreter_imports_only_stdlib_and_the_takeoff_dtos(self):
        probe = (
            "import json, sys\n"
            "import ost_visualizer.mcp_takeoff.main\n"
            "print(json.dumps(sorted(sys.modules)))\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        modules = json.loads(completed.stdout)
        project = {name for name in modules if name.split(".")[0] == "ost_visualizer"}
        proxy_modules = {
            f"ost_visualizer.mcp_takeoff.{path.stem}"
            for path in _proxy_sources(self)
            if path.stem != "__init__"
        }
        self.assertIn("ost_visualizer.mcp_takeoff.proxy", proxy_modules)
        self.assertEqual(
            project,
            proxy_modules
            | {
                "ost_visualizer",
                "ost_visualizer.mcp_takeoff",
                "ost_visualizer.application",
                "ost_visualizer.application.dtos",
                "ost_visualizer.application.dtos.ai_takeoff_dtos",
            },
        )
        third_party = (
            "PySide6",
            "shiboken6",
            "win32api",
            "pywintypes",
            "numpy",
            "ost_pdf",
        )
        for name in modules:
            self.assertFalse(name.startswith(third_party), name)


class AiTakeoffReadOnlySliceTests(unittest.TestCase):
    def test_m1a_modules_import_no_write_path(self):
        for path in _m1a_sources(self):
            text = path.read_text(encoding="utf-8")
            for token in WRITE_PATH_TOKENS:
                self.assertNotIn(token, text, f"{token} should not appear in {path}")

    def test_m1a_production_code_has_no_comments_or_reflection(self):
        for path in _m1a_sources(self):
            source = path.read_text(encoding="utf-8")
            for token in tokenize.generate_tokens(io.StringIO(source).readline):
                with self.subTest(path=path.name, line=token.start[0]):
                    self.assertNotEqual(token.type, tokenize.COMMENT)
                    if token.type == tokenize.NAME:
                        self.assertNotIn(
                            token.string, ("getattr", "setattr", "hasattr")
                        )

    def test_the_takeoff_surface_is_the_seven_read_tools_under_the_cap(self):
        self.assertEqual(
            M1A_COMMANDS,
            (
                "list_sheets",
                "render_sheet",
                "list_text",
                "list_segments",
                "get_quantities",
                "list_levels",
                "list_assumptions",
            ),
        )
        self.assertLessEqual(len(M1A_COMMANDS), MAX_EXPOSED_TOOLS)

    def test_the_read_server_is_untouched_by_the_takeoff_slice(self):
        from ost_visualizer.mcp_server.registry import DatabaseRegistry
        from ost_visualizer.mcp_server.server import build_mcp_server

        for path in sorted((PACKAGE / "mcp_server").glob("*.py")):
            text = path.read_text(encoding="utf-8").lower()
            self.assertNotIn("takeoff_bridge", text, path)
            self.assertNotIn("mcp_takeoff", text, path)
        logger = logging.getLogger("test_ai_takeoff_rules.read_server")
        logger.handlers.clear()
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        with tempfile.TemporaryDirectory() as directory:
            server = build_mcp_server(
                DatabaseRegistry(app_data_dir=Path(directory), logger=logger),
                logger=logger,
            )
            self.assertEqual(len(server.list_tools()), 38)
            self.assertEqual(len(server.list_prompts()), 7)
            self.assertEqual(len(server.list_resources()), 1)
            self.assertEqual(len(server.list_resource_templates()), 4)


class AiTakeoffPackagingTests(unittest.TestCase):
    def test_component_script_builds_the_takeoff_helper_on_its_own(self):
        text = (REPO_ROOT / "scripts" / "build-takeoff-mcp.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "$TakeoffScript = Join-Path $ProjectRoot 'McpTakeoffServer.py'", text
        )
        self.assertIn(
            "$TakeoffOutDir = Join-Path $ProjectRoot 'dist_takeoff_mcp'", text
        )
        self.assertIn("'--output-filename=ostv-takeoff-mcp.exe'", text)
        self.assertIn(
            "--nofollow-import-to=PySide6,shiboken6,ost_visualizer.presentation,"
            "ost_visualizer.config.di_config,ost_visualizer.mcp_server",
            text,
        )
        self.assertNotIn("'--onefile'", text)
        self.assertNotIn("Visualizer.py", text)
        self.assertNotIn("McpServer.py", text)
        self.assertNotIn("Copy-Item", text)

    def test_release_build_copies_the_takeoff_helper_next_to_the_desktop_exe(self):
        text = (REPO_ROOT / "scripts" / "build.ps1").read_text(encoding="utf-8")
        self.assertIn(
            "$TakeoffScript = Join-Path $ProjectRoot 'McpTakeoffServer.py'", text
        )
        self.assertIn("'--output-filename=ostv-takeoff-mcp.exe'", text)
        self.assertIn(
            "$TakeoffBuildDir = Join-Path $TakeoffOutDir 'McpTakeoffServer.dist'", text
        )
        self.assertIn(
            "$TakeoffHelperExe = Join-Path $TakeoffBuildDir 'ostv-takeoff-mcp.exe'",
            text,
        )
        self.assertIn(
            "Copy-Item (Join-Path $TakeoffBuildDir '*') -Destination $DesktopBuildDir",
            text,
        )
        self.assertLess(
            text.index("$TakeoffHelperExe = Join-Path"),
            text.index("Copy-Item (Join-Path $TakeoffBuildDir '*')"),
        )


if __name__ == "__main__":
    unittest.main()
