import argparse
import logging
import sys
from pathlib import Path
from ..infrastructure.app_paths import get_app_data_dir
from .server import run_stdio_server

LOGGER = logging.getLogger("ost_visualizer.mcp")


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run the OST Visualizer read-only MCP stdio server."
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        help="Logging level. Logs go to stderr and the app data log file.",
    )
    return parser.parse_args(argv)


def _configure_logging(app_data_dir: Path, level_name: str) -> logging.Logger:
    app_data_dir.mkdir(parents=True, exist_ok=True)
    levels = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    level = levels.get(level_name.upper(), logging.WARNING)
    logger = LOGGER
    logger.setLevel(level)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    stderr_handler.setLevel(level)
    file_handler = logging.FileHandler(
        app_data_dir / "mcp_server.log", encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    logger.addHandler(stderr_handler)
    logger.addHandler(file_handler)
    logger.propagate = False
    return logger


def main(argv=None) -> int:
    args = _parse_args(argv)
    app_data_dir = get_app_data_dir()
    logger = _configure_logging(app_data_dir, args.log_level)
    run_stdio_server(
        app_data_dir=app_data_dir,
        logger=logger,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
