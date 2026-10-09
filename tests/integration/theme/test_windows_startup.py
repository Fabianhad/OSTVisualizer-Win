import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tests.paths import REPO_ROOT

_INDICATORS = (
    ("checkbox", "PE_IndicatorCheckBox"),
    ("radio", "PE_IndicatorRadioButton"),
    ("item_check", "PE_IndicatorItemViewItemCheck"),
)


def _indicator_color(app, widget, element, active):
    """Dominant colour of a checked indicator drawn in an active or inactive window."""
    from collections import Counter
    from PySide6 import QtCore, QtGui, QtWidgets

    option = (
        QtWidgets.QStyleOptionViewItem()
        if element.endswith("ItemCheck")
        else QtWidgets.QStyleOptionButton()
    )
    option.initFrom(widget)
    option.rect = QtCore.QRect(0, 0, 20, 20)
    option.state = (
        QtWidgets.QStyle.StateFlag.State_Enabled | QtWidgets.QStyle.StateFlag.State_On
    )
    if active:
        option.state |= QtWidgets.QStyle.StateFlag.State_Active
    if element.endswith("ItemCheck"):
        option.checkState = QtCore.Qt.CheckState.Checked
    palette = QtGui.QPalette(widget.palette())
    palette.setCurrentColorGroup(
        QtGui.QPalette.ColorGroup.Active
        if active
        else QtGui.QPalette.ColorGroup.Inactive
    )
    option.palette = palette
    image = QtGui.QImage(20, 20, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor(0, 0, 0, 0))
    painter = QtGui.QPainter(image)
    app.style().drawPrimitive(
        getattr(QtWidgets.QStyle.PrimitiveElement, element), option, painter, widget
    )
    painter.end()
    colors = Counter(
        image.pixelColor(x, y).name()
        for x in range(20)
        for y in range(20)
        if image.pixelColor(x, y).alpha() == 255
    )
    return colors.most_common(1)[0][0] if colors else ""


def _startup_probe(style, platform):
    """Run real Qt startup in isolation, without opening databases or changing OS settings."""
    import ctypes
    from ctypes import wintypes
    from unittest.mock import Mock, patch
    from ost_visualizer import main as bootstrap
    from ost_visualizer.presentation.main_window import MainWindow
    from ost_visualizer.presentation.windows.annotation_view_window import (
        AnnotationViewWindow,
    )
    from ost_visualizer.presentation.windows.view_window import ViewWindow
    from PySide6 import QtCore, QtGui, QtWidgets
    from shiboken6 import delete

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
        checkbox = QtWidgets.QCheckBox("Option", dialog)
        checkbox.setChecked(True)
        dialog.winId()
        windows.append(dialog)
        accents = []
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
            app.processEvents()
            accents.append(
                dict(
                    requested=scheme.name,
                    indicators={
                        name: [
                            _indicator_color(app, checkbox, element, active)
                            for active in (True, False)
                        ]
                        for name, element in _INDICATORS
                    },
                    window=checkbox.palette()
                    .color(
                        QtGui.QPalette.ColorGroup.Active,
                        QtGui.QPalette.ColorRole.Window,
                    )
                    .lightness(),
                )
            )
        print(
            json.dumps(
                dict(
                    style=app.style().objectName(), snapshots=snapshots, accents=accents
                )
            )
        )
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
                "from tests.integration.theme.test_windows_startup import _startup_probe; "
                f"_startup_probe({style!r}, {platform!r})",
            ],
            cwd=REPO_ROOT,
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

    def assert_checkbox_accent_holds_when_inactive(self, result, follows_scheme):
        self.assertEqual(len(result["accents"]), 3)
        for state in result["accents"]:
            for name, (active, inactive) in state["indicators"].items():
                with self.subTest(scheme=state["requested"], indicator=name):
                    self.assertTrue(active)
                    self.assertEqual(inactive, active)
        dark, light, dark_again = result["accents"]
        self.assertEqual(dark["indicators"], dark_again["indicators"])
        if follows_scheme:
            self.assertLess(dark["window"], light["window"])
            self.assertNotEqual(
                dark["indicators"]["checkbox"][0], light["indicators"]["checkbox"][0]
            )

    def test_checked_boxes_keep_their_accent_in_inactive_windows(self):
        for style, platform in (
            ("windows11", "windows"),
            ("windowsvista", "windows"),
            ("fusion", "offscreen"),
        ):
            with self.subTest(style=style, platform=platform):
                self.assert_checkbox_accent_holds_when_inactive(
                    self.probe(style, platform), platform == "windows"
                )

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
        # Three theme changes on each of the four windows: not a vacuous all().
        self.assertEqual(len(result["snapshots"]), 12)
        # This option disables Qt's dark style integration too. Do not promise
        # dark client-area palettes after an explicit platform-level opt-out.
        self.assertTrue(
            all(state["dark_border"] in (None, False) for state in result["snapshots"])
        )

    def test_platform_without_windows_theme_api_keeps_its_style_without_crashing(self):
        result = self.probe("fusion", "offscreen")
        self.assertEqual(result["style"], "fusion")
        self.assertEqual(len(result["snapshots"]), 12)
        self.assertTrue(
            all(state["dark_border"] is None for state in result["snapshots"])
        )
