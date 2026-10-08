import json
import sys
import unittest
from pathlib import Path
from ost_visualizer.presentation.utils.mcp_setup_config import (
    MCP_HELPER_EXE_NAME,
    MCP_SERVER_NAME,
    TAKEOFF_MCP_HELPER_EXE_NAME,
    TAKEOFF_MCP_SERVER_NAME,
    build_claude_desktop_config,
    build_codex_config_toml,
    build_codex_mcp_add_command,
    default_mcp_helper_path,
    default_takeoff_helper_path,
)

PRIVATE_MCP_SETUP_MARKERS = (
    "--database",
    "--app-data-dir",
    "file_state.json",
    ".mdb",
    "license",
    "secret",
    "env",
    "cwd",
    "PYTHONPATH",
)


class McpSetupConfigTests(unittest.TestCase):
    def assert_no_private_mcp_setup_fields(self, text):
        lower_text = text.lower()
        for marker in PRIVATE_MCP_SETUP_MARKERS:
            self.assertNotIn(marker.lower(), lower_text)

    def test_default_helper_path_sits_next_to_app_executable(self):
        helper_path = default_mcp_helper_path(
            r"C:\Program Files\OST Visualizer\OSTVisualizer.exe"
        )
        self.assertEqual(helper_path.name, MCP_HELPER_EXE_NAME)
        self.assertEqual(str(helper_path.parent), r"C:\Program Files\OST Visualizer")
        self.assertEqual(MCP_HELPER_EXE_NAME, "ostv-mcp.exe")

    def test_default_helper_path_without_argument_uses_current_executable(self):
        helper_path = default_mcp_helper_path()
        self.assertEqual(helper_path.name, MCP_HELPER_EXE_NAME)
        self.assertEqual(helper_path.parent, Path(sys.executable).resolve().parent)

    def test_claude_config_uses_packaged_helper_only(self):
        helper_path = Path(r"C:\Program Files\OST Visualizer\ostv-mcp.exe")
        text = build_claude_desktop_config(helper_path)
        self.assertEqual(
            text,
            "{\n"
            '  "mcpServers": {\n'
            '    "ost-visualizer": {\n'
            '      "command": "C:\\\\Program Files\\\\OST Visualizer\\\\ostv-mcp.exe",\n'
            '      "args": []\n'
            "    }\n"
            "  }\n"
            "}",
        )
        config = json.loads(text)
        server = config["mcpServers"][MCP_SERVER_NAME]
        self.assertEqual(server["command"], str(helper_path))
        self.assertEqual(server["args"], [])
        self.assert_no_private_mcp_setup_fields(text)

    def test_codex_config_uses_toml_stdio_helper_without_private_paths(self):
        helper_path = Path(r"C:\Program Files\OST Visualizer\ostv-mcp.exe")
        text = build_codex_config_toml(helper_path)
        self.assertEqual(
            text,
            '[mcp_servers."ost-visualizer"]\n'
            'command = "C:\\\\Program Files\\\\OST Visualizer\\\\ostv-mcp.exe"\n'
            "args = []",
        )
        self.assertIn(str(helper_path).replace("\\", "\\\\"), text)
        self.assertNotIn("mcpServers", text)
        self.assert_no_private_mcp_setup_fields(text)

    def test_codex_config_escapes_toml_basic_string_values(self):
        text = build_codex_config_toml(Path('C:/Tools/OST "Preview"/ostv-mcp.exe'))
        self.assertIn(
            'command = "C:\\\\Tools\\\\OST \\"Preview\\"\\\\ostv-mcp.exe"',
            text,
        )

    def test_codex_command_uses_helper_without_database_override(self):
        command = build_codex_mcp_add_command(
            Path(r"C:\Program Files\OST Visualizer\ostv-mcp.exe")
        )
        self.assertEqual(
            command,
            "codex mcp add ost-visualizer -- "
            r"'C:\Program Files\OST Visualizer\ostv-mcp.exe'",
        )
        self.assert_no_private_mcp_setup_fields(command)
        self.assertNotIn("python", command.lower())

    def test_codex_config_escapes_control_characters(self):
        text = build_codex_config_toml(Path("C:/Tools/a\tb\nc/ostv-mcp.exe"))
        self.assertEqual(
            text.splitlines()[1],
            'command = "C:\\\\Tools\\\\a\\tb\\nc\\\\ostv-mcp.exe"',
        )
        self.assertEqual(len(text.splitlines()), 3)

    def test_codex_config_escapes_backspace_formfeed_and_carriage_return(self):
        text = build_codex_config_toml(Path("C:/Tools/a\bb\fc\rd/ostv-mcp.exe"))
        self.assertEqual(
            text,
            '[mcp_servers."ost-visualizer"]\n'
            'command = "C:\\\\Tools\\\\a\\bb\\fc\\rd\\\\ostv-mcp.exe"\n'
            "args = []",
        )

    def test_codex_command_doubles_single_quotes_in_helper_path(self):
        command = build_codex_mcp_add_command(
            Path(r"C:\Users\O'Neil\ostv-mcp.exe"), codex_command="codex.cmd"
        )
        self.assertEqual(
            command,
            "codex.cmd mcp add ost-visualizer -- " r"'C:\Users\O''Neil\ostv-mcp.exe'",
        )


class TakeoffMcpSetupConfigTests(unittest.TestCase):
    HELPER = Path(r"C:\Program Files\OST Visualizer\ostv-takeoff-mcp.exe")

    def test_takeoff_helper_is_a_second_packaged_exe_next_to_the_app(self):
        self.assertEqual(TAKEOFF_MCP_SERVER_NAME, "ost-takeoff")
        self.assertEqual(TAKEOFF_MCP_HELPER_EXE_NAME, "ostv-takeoff-mcp.exe")
        helper_path = default_takeoff_helper_path(
            r"C:\Program Files\OST Visualizer\OSTVisualizer.exe"
        )
        self.assertEqual(helper_path, self.HELPER)
        self.assertEqual(
            default_takeoff_helper_path().parent, Path(sys.executable).resolve().parent
        )

    def test_takeoff_entries_name_the_takeoff_server_without_private_fields(self):
        claude = json.loads(
            build_claude_desktop_config(self.HELPER, TAKEOFF_MCP_SERVER_NAME)
        )
        self.assertEqual(
            claude,
            {"mcpServers": {"ost-takeoff": {"command": str(self.HELPER), "args": []}}},
        )
        toml = build_codex_config_toml(self.HELPER, TAKEOFF_MCP_SERVER_NAME)
        self.assertEqual(toml.splitlines()[0], '[mcp_servers."ost-takeoff"]')
        command = build_codex_mcp_add_command(
            self.HELPER, server_name=TAKEOFF_MCP_SERVER_NAME
        )
        self.assertTrue(command.startswith("codex mcp add ost-takeoff -- "))
        for text in (json.dumps(claude), toml, command):
            lower_text = text.lower()
            for marker in PRIVATE_MCP_SETUP_MARKERS + ("token",):
                self.assertNotIn(marker.lower(), lower_text)

    def test_read_server_entries_are_unchanged_by_default(self):
        self.assertIn('"ost-visualizer": {', build_claude_desktop_config(self.HELPER))
        self.assertEqual(
            build_codex_config_toml(self.HELPER).splitlines()[0],
            '[mcp_servers."ost-visualizer"]',
        )
        self.assertTrue(
            build_codex_mcp_add_command(self.HELPER).startswith(
                "codex mcp add ost-visualizer -- "
            )
        )


if __name__ == "__main__":
    unittest.main()
