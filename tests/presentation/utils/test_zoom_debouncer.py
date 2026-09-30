import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.utils.zoom_debouncer import (
    ZOOM_SETTLE_DELAY_MS,
    ZoomDebouncer,
)
from PySide6 import QtCore, QtGui, QtWidgets
from tests.presentation.dialogs.options.preference_support import (
    _app as _preferences_support__app,
)


class ZoomDebouncerPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_zoom_debouncer_uses_default_settle_delay_and_coalesces(self):
        _preferences_support__app()
        debouncer = ZoomDebouncer()
        custom_debouncer = ZoomDebouncer(delay_ms=250)
        settled = []
        debouncer.zoom_settled.connect(settled.append)
        self.assertEqual(debouncer._timer.interval(), ZOOM_SETTLE_DELAY_MS)
        self.assertEqual(ZOOM_SETTLE_DELAY_MS, 125)
        self.assertEqual(custom_debouncer._timer.interval(), 250)
        debouncer.handle_scale_changed(1.25)
        debouncer.handle_scale_changed(2.5)
        debouncer._on_settled()
        self.assertEqual(settled, [2.5])
