import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from ost_visualizer.presentation.components.menu_builder import MenuBuilder


class MenuBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_missing_check_and_radio_callbacks_are_safe_no_ops(self):
        builder = MenuBuilder(
            None,
            {},
            state_getters={
                "flag": lambda: False,
                "mode": lambda: "first",
            },
        )
        menu = QtWidgets.QMenu()
        builder._build_menu(
            menu,
            [
                ("check", "Flag", "flag", "missing_check"),
                ("radio", "First", "mode", "first", "missing_radio"),
                ("radio", "Second", "mode", "second", "missing_radio"),
            ],
        )

        for action in menu.actions():
            action.trigger()

        builder.cleanup()
        menu.deleteLater()

    def test_cleanup_is_idempotent(self):
        builder = MenuBuilder(None, {})
        menu = QtWidgets.QMenu()
        builder._build_menu(menu, [("cmd", "Missing", "missing_command")])

        builder.cleanup()
        builder.cleanup()

        menu.deleteLater()


if __name__ == "__main__":
    unittest.main()
