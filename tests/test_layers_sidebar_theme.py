import os
from pathlib import Path
import subprocess
import sys
import unittest


def _check_native_layers(style, dark):
    from PySide6 import QtCore, QtGui, QtWidgets
    from shiboken6 import delete
    from ost_visualizer.domain.entities.layer import BidLayer
    from ost_visualizer.presentation.components.layers_sidebar import BidLayersSidebar

    app = QtWidgets.QApplication(
        ["layers-theme", "-platform", "windows", "-style", style]
    )
    app.styleHints().setColorScheme(
        QtCore.Qt.ColorScheme.Dark if dark else QtCore.Qt.ColorScheme.Light
    )
    check = unittest.TestCase()
    window = QtWidgets.QMainWindow()
    central = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(central)
    sidebar = BidLayersSidebar(central)
    sidebar.load_layers(
        [BidLayer(uid="1", bid_uid="1", name="Layer", show=True, sequence=1)]
    )
    layout.addWidget(sidebar)
    ordinary = QtWidgets.QCheckBox("Unrelated", central)
    layout.addWidget(ordinary)
    window.setCentralWidget(central)
    window.resize(360, 260)
    window.show()
    dialog = QtWidgets.QDialog(window)
    dialog_layout = QtWidgets.QVBoxLayout(dialog)
    dialog_box = QtWidgets.QCheckBox("Dialog option", dialog)
    dialog_layout.addWidget(dialog_box)
    box = sidebar._checkboxes[0]
    toggles = []
    sidebar.set_toggle_callback(lambda *args: toggles.append(args))

    def option(widget):
        result = QtWidgets.QStyleOptionButton()
        widget.initStyleOption(result)
        return result

    def indicator(widget):
        opt = option(widget)
        rect = widget.style().subElementRect(
            QtWidgets.QStyle.SubElement.SE_CheckBoxIndicator, opt, widget
        )
        return widget.grab(rect).toImage()

    try:
        for enabled in (True, False):
            sidebar.set_interactive(enabled)
            ordinary.setEnabled(enabled)
            for state in QtCore.Qt.CheckState:
                box.setCheckState(state)
                ordinary.setCheckState(state)
                for modal in (False, True):
                    # Set Qt's activation synchronously, without depending on the
                    # desktop focus policy, sleeps, or draining the event queue.
                    app.setActiveWindow(window)
                    window.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
                    box.setAttribute(QtCore.Qt.WidgetAttribute.WA_UnderMouse, False)
                    ordinary.setAttribute(
                        QtCore.Qt.WidgetAttribute.WA_UnderMouse, False
                    )
                    check.assertTrue(window.isActiveWindow())
                    before = indicator(box)
                    ordinary_before = indicator(ordinary)
                    ordinary_palette = ordinary.palette()
                    dialog.setModal(modal)
                    dialog.show()
                    app.setActiveWindow(dialog)
                    check.assertFalse(window.isActiveWindow())
                    check.assertTrue(dialog.isActiveWindow())
                    check.assertEqual(box.isEnabled(), enabled)
                    after = indicator(box)
                    if not enabled:
                        check.assertEqual(after, indicator(ordinary))
                    if style == "fusion":
                        check.assertEqual(
                            before,
                            after,
                            f"Layers indicator changed: dark={dark}, enabled={enabled}, "
                            f"state={state.name}, modal={modal}",
                        )
                    else:
                        # A local Fusion policy must not alter Windows 11 rendering.
                        check.assertEqual(after, indicator(ordinary))
                    check.assertEqual(ordinary.palette(), ordinary_palette)
                    if style == "fusion" and dark and enabled:
                        check.assertNotEqual(ordinary_before, indicator(ordinary))
                    dialog.close()
                    app.setActiveWindow(window)
                    window.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
                    check.assertEqual(indicator(box), before)
                    check.assertEqual(indicator(ordinary), ordinary_before)
                    check.assertEqual(box.checkState(), state)
                    check.assertEqual(ordinary.checkState(), state)
        check.assertEqual(toggles, [])
        sidebar.set_interactive(True)
        ordinary.setEnabled(True)
        app.setActiveWindow(window)
        for hovered in (False, True):
            for focused in (False, True):
                for widget in (box, ordinary):
                    widget.setAttribute(
                        QtCore.Qt.WidgetAttribute.WA_UnderMouse, hovered
                    )
                    if focused:
                        widget.setFocus(QtCore.Qt.FocusReason.TabFocusReason)
                    else:
                        window.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
                    opt = option(widget)
                    standard = QtWidgets.QStyleOptionButton()
                    QtWidgets.QCheckBox.initStyleOption(widget, standard)
                    check.assertEqual(opt.state, standard.state)
                    check.assertEqual(
                        bool(opt.state & QtWidgets.QStyle.StateFlag.State_MouseOver),
                        hovered,
                    )
                    check.assertEqual(
                        bool(opt.state & QtWidgets.QStyle.StateFlag.State_HasFocus),
                        focused,
                    )
        # Existing widgets must take fresh brushes after a runtime theme change.
        themed_images = []
        for scheme in (QtCore.Qt.ColorScheme.Light, QtCore.Qt.ColorScheme.Dark):
            app.styleHints().setColorScheme(scheme)
            QtCore.QCoreApplication.sendPostedEvents(
                None, QtCore.QEvent.Type.ApplicationPaletteChange
            )
            box.setAttribute(QtCore.Qt.WidgetAttribute.WA_UnderMouse, False)
            app.setActiveWindow(window)
            window.setFocus()
            active = indicator(box)
            themed_images.append(active)
            dialog.show()
            app.setActiveWindow(dialog)
            if style == "fusion":
                check.assertEqual(indicator(box), active)
            dialog.close()
        check.assertNotEqual(themed_images[0], themed_images[1])
        check.assertEqual(toggles, [])
    finally:
        delete(dialog)
        delete(window)


@unittest.skipUnless(sys.platform == "win32", "Requires native Windows palettes")
class LayersSidebarThemeTests(unittest.TestCase):
    def run_native_check(self, style, dark):
        env = os.environ.copy()
        env.pop("QT_STYLE_OVERRIDE", None)
        result = subprocess.run(
            [
                sys.executable,
                "-X",
                "faulthandler",
                "-c",
                "from tests.test_layers_sidebar_theme import _check_native_layers; "
                f"_check_native_layers({style!r}, {dark!r})",
            ],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_fusion_dark_dialog_activation_and_indicator_states(self):
        self.run_native_check("fusion", True)

    def test_fusion_light_dialog_activation_and_indicator_states(self):
        self.run_native_check("fusion", False)

    def test_windows_11_dark_preserves_standard_checkbox_rendering(self):
        self.run_native_check("windows11", True)

    def test_windows_11_light_preserves_standard_checkbox_rendering(self):
        self.run_native_check("windows11", False)
