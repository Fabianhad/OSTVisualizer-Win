import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, TextIO
from ..application.dtos.ai_takeoff_dtos import (
    AI_TAKEOFF_DIR_NAME,
    AI_TAKEOFF_OUTPUT_DIR_NAME,
    AI_TAKEOFF_SESSION_TOKEN_FILE_NAME,
    APP_DATA_DIR_NAME,
)
from .pipe_client import TakeoffPipeClient
from .protocol import JsonRpcStdioServer
from .proxy import TakeoffProxy

SERVER_NAME = "ost-visualizer-takeoff"
LOG_FILE_NAME = "mcp_takeoff.log"
LOGGER = logging.getLogger("ost_visualizer.mcp_takeoff")
_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def app_data_dir() -> Path:
    return Path.home() / APP_DATA_DIR_NAME


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run the OST Visualizer AI takeoff MCP stdio proxy."
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=_LEVELS,
        help="Logging level. Logs go to stderr and the app data log file.",
    )
    return parser.parse_args(argv)


def _configure_logging(directory: Path, level_name: str) -> logging.Logger:
    directory.mkdir(parents=True, exist_ok=True)
    level = logging.getLevelName(level_name)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    LOGGER.setLevel(level)
    for handler in list(LOGGER.handlers):
        LOGGER.removeHandler(handler)
        handler.close()
    stderr_handler = logging.StreamHandler(sys.stderr)
    file_handler = logging.FileHandler(directory / LOG_FILE_NAME, encoding="utf-8")
    for handler in (stderr_handler, file_handler):
        handler.setFormatter(formatter)
        handler.setLevel(level)
        LOGGER.addHandler(handler)
    LOGGER.propagate = False
    return LOGGER


def main(
    argv=None, stdin: Optional[TextIO] = None, stdout: Optional[TextIO] = None
) -> int:
    args = parse_args(argv)
    directory = app_data_dir()
    logger = _configure_logging(directory, args.log_level)
    client = TakeoffPipeClient(
        directory / AI_TAKEOFF_DIR_NAME / AI_TAKEOFF_SESSION_TOKEN_FILE_NAME
    )
    proxy = TakeoffProxy(client, directory / AI_TAKEOFF_OUTPUT_DIR_NAME)
    server = JsonRpcStdioServer(SERVER_NAME, proxy.list_tools, proxy.call_tool)
    if stdin is None:
        sys.stdin.reconfigure(encoding="utf-8-sig", errors="replace")
    logger.info("AI takeoff MCP proxy started")
    try:
        server.run(stdin, stdout)
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
