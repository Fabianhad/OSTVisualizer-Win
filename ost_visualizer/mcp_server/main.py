import argparse
import logging
import sys
from pathlib import Path
from ..infrastructure.app_paths import get_app_data_dir

LOGGER = logging.getLogger("ost_visualizer.mcp")


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run the OST Visualizer read-only MCP stdio server."
    )
    parser.add_argument(
        "--app-data-dir",
        default=None,
        help="Override the OST Visualizer app data directory for testing.",
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
    level = getattr(logging, level_name.upper(), logging.WARNING)
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
    app_data_dir = Path(args.app_data_dir) if args.app_data_dir else get_app_data_dir()
    logger = _configure_logging(app_data_dir, args.log_level)
    try:
        from .server import run_stdio_server
    except ImportError as exc:
        print(
            "OST Visualizer MCP dependencies are not installed. "
            "Run scripts\\setup-mcp.ps1 or install requirements-mcp.txt.",
            file=sys.stderr,
        )
        logger.exception("Failed to import MCP server: %s", exc)
        return 1
    run_stdio_server(
        app_data_dir=app_data_dir,
        logger=logger,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
