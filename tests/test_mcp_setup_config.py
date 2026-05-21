import json
import unittest
from pathlib import Path
from ost_visualizer.presentation.dialogs.mcp_setup_config import (
    MCP_HELPER_EXE_NAME,
    MCP_SERVER_NAME,
    build_claude_desktop_config,
    build_codex_mcp_add_command,
    default_mcp_helper_path,
)


class McpSetupConfigTests(unittest.TestCase):
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
        self.assertNotIn("--database", text)
        self.assertNotIn("PYTHONPATH", text)

    def test_codex_command_uses_helper_without_database_override(self):
        command = build_codex_mcp_add_command(
            Path(r"C:\Program Files\OST Visualizer\ostv-mcp.exe")
        )
        self.assertEqual(
            command,
            "codex mcp add ost-visualizer -- "
            r"'C:\Program Files\OST Visualizer\ostv-mcp.exe'",
        )
        self.assertNotIn("--database", command)
        self.assertNotIn("python", command.lower())


if __name__ == "__main__":
    unittest.main()
