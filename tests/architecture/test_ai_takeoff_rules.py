import ast
import io
import json
import logging
import subprocess
import sys
import tempfile
import tokenize
import unicodedata
import unittest
from pathlib import Path
from ost_visualizer.application.dtos.ai_takeoff_dtos import (
    AI_TAKEOFF_COMMANDS,
    M1A_COMMANDS,
    M1B_COMMANDS,
    MAX_EXPOSED_TOOLS,
)
from ost_visualizer.application.services.ai_changeset_store import (
    AiChangesetProposals,
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
M1B_PRODUCTION_FILES = (
    "application/dtos/ai_changeset_write_dtos.py",
    "application/dtos/ai_takeoff_audit_dtos.py",
    "application/services/ai_changeset_store.py",
    "application/services/ai_takeoff_proposal_service.py",
    "application/services/ai_takeoff_sidecar_service.py",
    "application/services/ai_takeoff_tokens.py",
    "domain/entities/ai_changeset.py",
    "domain/services/ai_planar_regions.py",
    "infrastructure/persistence/ai_takeoff_audit_log.py",
    "presentation/dialogs/ai_changeset_review_dialog.py",
    "presentation/services/ai_changeset_applier.py",
    "presentation/services/ai_changeset_approval.py",
    "presentation/services/ai_region_raster.py",
    "presentation/services/ai_render_3d.py",
    "presentation/services/ai_sidecar_rebind_prompt.py",
    "presentation/services/ai_takeoff_write_commands.py",
)
PIPE_REACHABLE_FILES = (
    "presentation/services/ai_takeoff_bridge.py",
    "presentation/services/ai_takeoff_write_commands.py",
    "application/services/ai_takeoff_proposal_service.py",
    "mcp_takeoff/tool_catalog.py",
    "mcp_takeoff/proxy.py",
)
APPROVAL_NAMES = (
    "approve",
    "reject",
    "accept_assumption",
    "override_assumption",
    "mark_applied",
    "mark_failed",
    "mark_undone",
    "AiChangesetStore",
    "AiChangesetApplier",
    "AiChangesetApprovalController",
    "AiChangesetReviewDialog",
    "ProjectWriteService",
    "project_write_service",
)
BIDI_CONTROLS = frozenset(
    chr(code)
    for code in (
        0x061C,
        0x200E,
        0x200F,
        0x202A,
        0x202B,
        0x202C,
        0x202D,
        0x202E,
        0x2066,
        0x2067,
        0x2068,
        0x2069,
    )
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


def _m1b_sources(test_case):
    files = [PACKAGE / relative for relative in M1B_PRODUCTION_FILES]
    for path in files:
        test_case.assertTrue(path.is_file(), path)
    return files


def _name_tokens(path):
    source = path.read_text(encoding="utf-8")
    return {
        token.string
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.NAME
    }


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


class AiTakeoffApprovalSliceTests(unittest.TestCase):
    def test_m1b_production_code_has_no_comments_or_reflection(self):
        for path in _m1b_sources(self):
            source = path.read_text(encoding="utf-8")
            for token in tokenize.generate_tokens(io.StringIO(source).readline):
                with self.subTest(path=path.name, line=token.start[0]):
                    self.assertNotEqual(token.type, tokenize.COMMENT)
                    if token.type == tokenize.NAME:
                        self.assertNotIn(
                            token.string, ("getattr", "setattr", "hasattr")
                        )

    def test_ai_takeoff_sources_hold_no_raw_bidi_or_control_characters(self):
        for path in _m1a_sources(self) + _m1b_sources(self):
            text = path.read_text(encoding="utf-8")
            for index, character in enumerate(text):
                if character in BIDI_CONTROLS or (
                    unicodedata.category(character) == "Cc"
                    and character not in "\t\n\r"
                ):
                    self.fail(f"{path.name} has U+{ord(character):04X} at {index}")

    def test_no_pipe_reachable_module_names_an_approval_or_write_path(self):
        for relative in PIPE_REACHABLE_FILES:
            path = PACKAGE / relative
            self.assertTrue(path.is_file(), path)
            names = _name_tokens(path)
            for name in APPROVAL_NAMES:
                self.assertNotIn(name, names, f"{name} should not appear in {path}")

    def test_only_the_approval_controller_reaches_store_approval_methods(self):
        users = set()
        for path in PACKAGE.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in (
                    "approve",
                    "accept_assumption",
                    "override_assumption",
                ):
                    users.add(path.relative_to(PACKAGE).as_posix())
        self.assertEqual(users, {"presentation/services/ai_changeset_approval.py"})

    def test_main_window_gives_the_pipe_proposals_and_the_apply_request_only(self):
        tree = ast.parse(
            (PACKAGE / "presentation" / "main_window.py").read_text(encoding="utf-8")
        )
        bridges = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "TakeoffCommandBridge"
        ]
        self.assertEqual(len(bridges), 1)
        approval_uses = []
        attributes = []
        services = set()
        for node in ast.walk(bridges[0]):
            if isinstance(node, ast.Attribute):
                attributes.append(node.attr)
                if (
                    isinstance(node.value, ast.Attribute)
                    and node.value.attr == "_ai_approval"
                ):
                    approval_uses.append(node.attr)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get_service"
            ):
                services.add(node.args[0].value)
        self.assertEqual(approval_uses, ["on_apply_requested"])
        self.assertEqual(attributes.count("_ai_approval"), 1)
        self.assertNotIn("_ai_store", attributes)
        self.assertIn("ai_changeset_proposals", services)
        self.assertNotIn("ai_changeset_store", services)

    def test_the_proposal_facade_offers_no_approval_method(self):
        public = {
            name for name in vars(AiChangesetProposals) if not name.startswith("_")
        }
        self.assertEqual(
            public,
            {
                "add",
                "get",
                "discard",
                "request_apply",
                "add_assumption",
                "revise_assumption",
                "last_applied",
                "applied_record",
            },
        )

    def test_the_takeoff_surface_is_fifteen_tools_under_the_cap(self):
        self.assertEqual(
            M1B_COMMANDS,
            (
                "propose_scale",
                "find_regions",
                "propose_element",
                "apply_changeset",
                "discard_changeset",
                "undo_last_ai_changeset",
                "render_3d",
                "update_assumption",
            ),
        )
        self.assertEqual(AI_TAKEOFF_COMMANDS, M1A_COMMANDS + M1B_COMMANDS)
        self.assertLessEqual(len(AI_TAKEOFF_COMMANDS), MAX_EXPOSED_TOOLS)
        for name in AI_TAKEOFF_COMMANDS:
            self.assertNotIn("approve", name)
            self.assertNotIn("accept", name)


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
