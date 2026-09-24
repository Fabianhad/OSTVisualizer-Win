import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


def _startup_probe(style, platform):
    """Run real Qt startup in isolation, without opening databases or changing OS settings."""
    import ctypes
    from ctypes import wintypes
    from unittest.mock import Mock, patch
    from PySide6 import QtCore, QtWidgets
    from shiboken6 import delete
    from ost_visualizer import main as bootstrap
    from ost_visualizer.presentation.main_window import MainWindow
    from ost_visualizer.presentation.windows.annotation_view_window import (
        AnnotationViewWindow,
    )
    from ost_visualizer.presentation.windows.view_window import ViewWindow

    class ProbeComplete(Exception):
        pass

    def inspect_before_splash():
        app = QtWidgets.QApplication.instance()
        snapshots = []
        windows = []
        # Exercise the actual top-level classes without unrelated project/service
        # construction. Native creation and palette events still use real Qt.
        for cls in (MainWindow, AnnotationViewWindow, ViewWindow):
            window = cls.__new__(cls)
            QtWidgets.QMainWindow.__init__(window)
            central = QtWidgets.QWidget()
            central.setAutoFillBackground(True)
            window.setCentralWidget(central)
            window.menuBar().addMenu("File")
            window.resize(320, 240)
            window.winId()
            windows.append(window)
        dialog = QtWidgets.QDialog(windows[0])
        dialog.winId()
        windows.append(dialog)
        if app.platformName() == "windows":
            get_attribute = ctypes.windll.dwmapi.DwmGetWindowAttribute
            get_attribute.argtypes = (
                wintypes.HWND,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.DWORD,
            )
            get_attribute.restype = ctypes.c_long
        for scheme in (
            QtCore.Qt.ColorScheme.Dark,
            QtCore.Qt.ColorScheme.Light,
            QtCore.Qt.ColorScheme.Dark,
        ):
            app.styleHints().setColorScheme(scheme)
            # Deliver exactly Qt's posted palette propagation, without sleeps or
            # blanket event draining, to already-created native windows.
            QtCore.QCoreApplication.sendPostedEvents(
                None, QtCore.QEvent.Type.ApplicationPaletteChange
            )
            for window in windows:
                surfaces = [window]
                if isinstance(window, QtWidgets.QMainWindow):
                    surfaces.extend((window.centralWidget(), window.menuBar()))
                colors = [
                    (
                        surface.palette().window().color().lightness(),
                        surface.palette().windowText().color().lightness(),
                    )
                    for surface in surfaces
                ]
                border = None
                if app.platformName() == "windows":
                    value = wintypes.BOOL()
                    result = get_attribute(
                        int(window.winId()),
                        20,
                        ctypes.byref(value),
                        ctypes.sizeof(value),
                    )
                    if result == 0:
                        border = bool(value.value)
                snapshots.append(
                    dict(
                        window=type(window).__name__,
                        requested=scheme.name,
                        detected=app.styleHints().colorScheme().name,
                        colors=colors,
                        dark_border=border,
                    )
                )
        print(json.dumps(dict(style=app.style().objectName(), snapshots=snapshots)))
        for window in reversed(windows):
            delete(window)
        raise ProbeComplete

    socket = Mock()
    socket.waitForConnected.return_value = False
    sys.argv = ["theme-probe", "-platform", platform, "-style", style]
    with (
        patch.object(bootstrap, "_install_runtime_logging", return_value=Mock()),
        patch.object(bootstrap, "QLocalSocket", return_value=socket),
        patch.object(bootstrap, "QLocalServer"),
        patch.object(bootstrap, "SplashScreen", side_effect=inspect_before_splash),
    ):
        try:
            bootstrap.main()
        except ProbeComplete:
            pass


@unittest.skipUnless(sys.platform == "win32", "Requires the native Windows Qt plugin")
class WindowsThemeTests(unittest.TestCase):
    def probe(self, style, platform="windows"):
        env = os.environ.copy()
        env.pop("QT_STYLE_OVERRIDE", None)
        result = subprocess.run(
            [
                sys.executable,
                "-X",
                "faulthandler",
                "-c",
                "from tests.test_windows_theme import _startup_probe; "
                f"_startup_probe({style!r}, {platform!r})",
            ],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def assert_theme_cycles(self, result):
        self.assertEqual(len(result["snapshots"]), 12)
        for state in result["snapshots"]:
            with self.subTest(window=state["window"], scheme=state["requested"]):
                dark = state["requested"] == "Dark"
                self.assertEqual(state["detected"], state["requested"])
                for background, foreground in state["colors"]:
                    self.assertEqual(background < foreground, dark)
                # Older Windows builds may not expose the DWM query attribute.
                # Client-area correctness remains required on those systems.
                if state["dark_border"] is not None:
                    self.assertEqual(state["dark_border"], dark)

    def test_windows_10_default_style_follows_dark_light_dark_on_all_windows(self):
        result = self.probe("windowsvista")
        self.assert_theme_cycles(result)
        self.assertEqual(result["style"], "fusion")

    def test_windows_11_style_keeps_native_theme_and_runtime_switching(self):
        result = self.probe("windows11")
        self.assertEqual(result["style"], "windows11")
        self.assert_theme_cycles(result)

    def test_explicit_platform_dark_mode_opt_out_is_respected(self):
        result = self.probe("windowsvista", "windows:darkmode=0")
        self.assertEqual(result["style"], "fusion")
        # This option disables Qt's dark style integration too. Do not promise
        # dark client-area palettes after an explicit platform-level opt-out.
        self.assertTrue(
            all(state["dark_border"] in (None, False) for state in result["snapshots"])
        )

    def test_platform_without_windows_theme_api_keeps_its_style_without_crashing(self):
        result = self.probe("fusion", "offscreen")
        self.assertEqual(result["style"], "fusion")
        self.assertTrue(
            all(state["dark_border"] is None for state in result["snapshots"])
        )
