import json
import unittest
from pathlib import Path
from ost_visualizer.presentation.utils.mcp_setup_config import (
    MCP_HELPER_EXE_NAME,
    MCP_SERVER_NAME,
    build_claude_desktop_config,
    build_codex_config_toml,
    build_codex_mcp_add_command,
    default_mcp_helper_path,
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


if __name__ == "__main__":
    unittest.main()
