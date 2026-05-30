import json
import sys
from pathlib import Path
from typing import Optional

MCP_SERVER_NAME = "ost-visualizer"
MCP_HELPER_EXE_NAME = "ostv-mcp.exe"


def default_mcp_helper_path(executable_path: Optional[str] = None) -> Path:
    app_executable = Path(executable_path or sys.executable).resolve()
    return app_executable.with_name(MCP_HELPER_EXE_NAME)


def default_file_state_path() -> Path:
    return Path.home() / ".ost_visualizer" / "file_state.json"


def build_claude_desktop_config(helper_path: Path) -> str:
    config = {
        "mcpServers": {
            MCP_SERVER_NAME: {
                "command": str(Path(helper_path)),
                "args": [],
            }
        }
    }
    return json.dumps(config, indent=2)


def _toml_basic_string(value: str) -> str:
    replacements = {
        "\\": "\\\\",
        '"': '\\"',
        "\b": "\\b",
        "\t": "\\t",
        "\n": "\\n",
        "\f": "\\f",
        "\r": "\\r",
    }
    escaped = "".join(replacements.get(char, char) for char in value)
    return f'"{escaped}"'


def build_codex_config_toml(helper_path: Path) -> str:
    command = _toml_basic_string(str(Path(helper_path)))
    return f'[mcp_servers."{MCP_SERVER_NAME}"]\n' f"command = {command}\n" "args = []"


def quote_powershell_arg(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_codex_mcp_add_command(
    helper_path: Path,
    codex_command: str = "codex",
) -> str:
    return (
        f"{codex_command} mcp add {MCP_SERVER_NAME} -- "
        f"{quote_powershell_arg(str(Path(helper_path)))}"
    )
