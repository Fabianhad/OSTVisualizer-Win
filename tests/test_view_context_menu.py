import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.presentation.utils.view_context_menu import (
    add_common_context_submenus,
    add_reassign_condition_submenu,
)


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class ViewContextMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        self.app.processEvents()

    def test_reassign_condition_submenu_lists_conditions_by_ref_no(self):
        menu = QtWidgets.QMenu()
        try:
            reassign_menu = add_reassign_condition_submenu(
                menu,
                {
                    "20": Condition(uid="20", name="Second", ref_no=2),
                    "10": Condition(uid="10", name="First", ref_no=1),
                },
            )
            self.assertEqual(menu.actions()[0].text(), "Reassign Condition")
            self.assertEqual(
                [action.text() for action in reassign_menu.submenu.actions()],
                [
                    "1 - First",
                    "2 - Second",
                ],
            )
            self.assertEqual(
                [
                    reassign_menu.actions[action]
                    for action in reassign_menu.submenu.actions()
                ],
                ["10", "20"],
            )
            self.assertTrue(
                all(
                    not action.icon().isNull()
                    for action in reassign_menu.submenu.actions()
                )
            )
        finally:
            menu.deleteLater()

    def test_plan_tools_context_submenu_uses_shared_tool_registry(self):
        menu = QtWidgets.QMenu()
        try:
            add_common_context_submenus(
                menu,
                current_mode=0,
                trigger_fn=lambda _key: None,
                action_state_fn=lambda _key: {
                    "enabled": True,
                },
                has_overlay_image=False,
            )
            tools_menu = menu.actions()[0].menu()
            self.assertEqual(tools_menu.title(), "Tools")
            self.assertEqual(
                [action.text() for action in tools_menu.actions()],
                [
                    "Select",
                    "Place",
                    "Pan",
                    "Zoom",
                    "Dimension",
                    "Text",
                    "Highlight",
                    "Arrow",
                    "Line",
                    "Rectangle",
                    "Oval",
                    "Polygon",
                    "Cloud",
                    "",
                    "Backout",
                ],
            )
        finally:
            menu.deleteLater()


if __name__ == "__main__":
    unittest.main()
