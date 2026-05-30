import faulthandler
import logging
import os
import platform
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from PySide6 import QtWidgets
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from .application.services.update_check_service import UpdateCheckService
from .config.di_config import configure_application
from .infrastructure.app_paths import get_app_data_dir
from .infrastructure.logging.logger_factory import LoggerFactory
from .presentation.components.splash_screen import SplashScreen
from .presentation.main_window import MainWindow
from .presentation.utils.qt_log_handler import install_qt_message_handler

APP_INSTANCE_NAME = "OSTVisualizer"
_CRASH_LOG_FILE = "crash.log"
_crash_log_stream = None
_app_version = "unknown"
_root_logger = logging.getLogger()


def _bootstrap_logging() -> logging.Logger:
    log_dir = get_app_data_dir()
    LoggerFactory.configure(log_dir)
    return LoggerFactory.get_logger("ost_visualizer.bootstrap")


def _enable_faulthandler(log_dir: Path, logger: logging.Logger) -> None:
    global _crash_log_stream
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        _crash_log_stream = open(
            log_dir / _CRASH_LOG_FILE,
            mode="a",
            encoding="utf-8",
            buffering=1,
        )
        faulthandler.enable(file=_crash_log_stream, all_threads=True)
    except (OSError, RuntimeError):
        logger.exception("Failed to enable faulthandler")


def _resolve_app_version() -> str:
    return UpdateCheckService.CURRENT_VERSION


def _write_crash_report(kind: str, details: str) -> None:
    if _crash_log_stream is None:
        return
    _crash_log_stream.write("\n" + "=" * 80 + "\n")
    _crash_log_stream.write(f"Crash type: {kind}\n")
    _crash_log_stream.write(
        f"Timestamp: {datetime.now().isoformat(timespec='seconds')}\n"
    )
    _crash_log_stream.write(f"App version: {_app_version}\n")
    _crash_log_stream.write(f"Python: {sys.version.replace(os.linesep, ' ')}\n")
    _crash_log_stream.write(f"Platform: {platform.platform()}\n")
    _crash_log_stream.write(f"Executable: {sys.executable}\n")
    _crash_log_stream.write(f"Working directory: {Path.cwd()}\n\n")
    _crash_log_stream.write(details)
    if not details.endswith("\n"):
        _crash_log_stream.write("\n")
    _crash_log_stream.flush()


def _flush_logging() -> None:
    for handler in _root_logger.handlers:
        handler.flush()


def _install_exception_hooks(logger: logging.Logger) -> None:
    def _format_exception(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback,
    ) -> str:
        return "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))

    def _sys_excepthook(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical(
            "Unhandled exception\n%s",
            _format_exception(exc_type, exc_value, exc_traceback),
        )
        _write_crash_report(
            "Unhandled Python exception",
            _format_exception(exc_type, exc_value, exc_traceback),
        )
        _flush_logging()
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    def _threading_excepthook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is KeyboardInterrupt:
            return
        thread_name = args.thread.name if args.thread else "<unknown>"
        formatted = _format_exception(args.exc_type, args.exc_value, args.exc_traceback)
        logger.critical(
            "Unhandled thread exception in %s\n%s",
            thread_name,
            formatted,
        )
        _write_crash_report(
            f"Unhandled thread exception in {thread_name}",
            formatted,
        )
        _flush_logging()
        threading.__excepthook__(args)

    def _unraisablehook(unraisable) -> None:
        formatted = "".join(
            traceback.format_exception(
                unraisable.exc_type,
                unraisable.exc_value,
                unraisable.exc_traceback,
            )
        )
        logger.critical(
            "Unraisable exception in %r\n%s",
            unraisable.object,
            formatted,
        )
        _write_crash_report(
            f"Unraisable exception in {unraisable.object!r}",
            formatted,
        )
        _flush_logging()
        sys.__unraisablehook__(unraisable)

    sys.excepthook = _sys_excepthook
    threading.excepthook = _threading_excepthook
    sys.unraisablehook = _unraisablehook


def _install_runtime_logging() -> logging.Logger:
    global _app_version
    logger = _bootstrap_logging()
    _enable_faulthandler(get_app_data_dir(), logger)
    _install_exception_hooks(logger)
    _app_version = _resolve_app_version()
    install_qt_message_handler()
    return logger


def main():
    logger = _install_runtime_logging()
    logger.info("Application startup")
    app = QtWidgets.QApplication(sys.argv)
    socket = QLocalSocket()
    socket.connectToServer(APP_INSTANCE_NAME)
    if socket.waitForConnected(200):
        logger.info("Existing application instance detected")
        socket.close()
        sys.exit(0)
    server = QLocalServer()
    server.removeServer(APP_INSTANCE_NAME)
    server.listen(APP_INSTANCE_NAME)
    app._single_instance_server = server
    splash = SplashScreen()
    splash.show()
    app.processEvents()
    container = configure_application()
    app_controller = container.get("app_controller")
    window = MainWindow(app_controller, splash_screen=splash)
    app.main_window = window
    exit_code = app.exec()
    logger.info("Application exiting with code %s", exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
