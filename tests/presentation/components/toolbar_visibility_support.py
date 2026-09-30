"""Font fixture shared by toolbar visibility and preference tests."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtGui


def register_test_fonts():
    font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
        QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))
