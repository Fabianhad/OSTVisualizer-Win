import ctypes
import sys
from pathlib import Path
from PySide6 import QtGui, QtWidgets
from ...application.services.update_check_service import UpdateCheckService
from ..utils.windows import set_initial_window_size

APP_VERSION = UpdateCheckService.CURRENT_VERSION
MY_APP_ID = f"fabian.ost.3d.v{APP_VERSION}"
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(MY_APP_ID)


def resource_path(*parts: str) -> str:
    if hasattr(sys, "frozen"):
        base = Path(sys.executable).resolve().parent / "ost_visualizer"
    else:
        base = Path(__file__).resolve().parents[2]
    return str((base.joinpath(*parts)).resolve())


def set_window_icon(window: QtWidgets.QWidget) -> None:
    icon_path = resource_path("resources", "icon.ico")
    window.setWindowIcon(QtGui.QIcon(icon_path))


class WindowConfigurator:
    def __init__(self, width: int, height: int, title: str = "OST Visualizer"):
        self.width = width
        self.height = height
        self.title = title

    def configure(self, window: QtWidgets.QMainWindow) -> None:
        window.setWindowTitle(self.title)
        set_initial_window_size(window, self.width, self.height)
        set_window_icon(window)
