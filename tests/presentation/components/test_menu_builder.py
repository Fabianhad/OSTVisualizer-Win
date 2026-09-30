from tests.presentation.dialogs.options.preference_support import (
    _app as _preferences_support__app,
)
from tests.paths import REPO_ROOT
from PySide6 import QtCore, QtGui, QtWidgets
from ost_visualizer.presentation.managers.icon_manager import (
    ICON_SPECS,
    IconId,
    IconManager,
)
from ost_visualizer.presentation.components.menu_builder import MenuBuilder
from ost_visualizer.presentation.actions.action_ids import (
    ACTION_ANNOTATION_WINDOW,
    ACTION_BACKOUT_MODE,
    ACTION_CONDITIONS_SIDEBAR,
    ACTION_COPY,
    ACTION_CUT,
    ACTION_DEFAULT_LAYERS,
    ACTION_DELETE,
    ACTION_DUPLICATE,
    ACTION_LAYERS_SIDEBAR,
    ACTION_NEW_DATABASE,
    ACTION_NEW_FOLDER,
    ACTION_NEW_PROJECT,
    ACTION_NEXT_PAGE,
    ACTION_OPEN_FILES,
    ACTION_PASTE,
    ACTION_PREVIOUS_PAGE,
    ACTION_REDO,
    ACTION_RESET_VIEW,
    ACTION_SELECT_ALL,
    ACTION_STATUS_BAR,
    ACTION_UNDO,
    ACTION_ZOOM_IN,
    ACTION_ZOOM_OUT,
)
from pathlib import Path
import unittest
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class MenuBuilderPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_menu_builder_no_longer_exposes_mcp_setup_action(self):
        builder = MenuBuilder(None, {})
        tools_items = builder._get_menu_definition()["Tools"]
        old_label = "MCP " + "Setup..."
        old_key = "mcp_" + "setup"
        self.assertIn(("cmd", "Options...", "options"), tools_items)
        self.assertNotIn(("cmd", old_label, old_key), tools_items)

    def test_master_menu_lists_default_layers_below_payroll_classes(self):
        builder = MenuBuilder(None, {})
        master_items = builder._get_menu_definition()["Master"]
        payroll_index = master_items.index(
            ("cmd", "Payroll Classes", "payroll_classes")
        )
        self.assertEqual(master_items[payroll_index + 1], ("sep",))
        self.assertEqual(
            master_items[payroll_index + 2],
            ("cmd", "Default Layers", ACTION_DEFAULT_LAYERS),
        )

    def test_tools_menu_lists_text_after_dimension_with_serif_icon(self):
        labels = {
            "select_tool": "Select",
            "place_tool": "Place",
            "pan_tool": "Pan",
            "zoom_tool": "Zoom",
            "dimension_tool": "Dimension",
            "text_annotation_tool": "Text",
            "highlight_annotation_tool": "Highlight",
            "arrow_annotation_tool": "Arrow",
            "line_annotation_tool": "Line",
            "rectangle_annotation_tool": "Rectangle",
            "oval_annotation_tool": "Oval",
            "polygon_annotation_tool": "Polygon",
            "cloud_annotation_tool": "Cloud",
            "ink_annotation_tool": "Ink",
            "hotlink_tool": "Hotlink",
            "named_view_tool": "Named View",
        }
        shared_actions = {
            key: QtGui.QAction(labels.get(key, key), None)
            for key in (
                ACTION_NEW_PROJECT,
                ACTION_NEW_FOLDER,
                ACTION_NEW_DATABASE,
                ACTION_OPEN_FILES,
                ACTION_UNDO,
                ACTION_REDO,
                ACTION_CUT,
                ACTION_COPY,
                ACTION_PASTE,
                ACTION_DUPLICATE,
                ACTION_DELETE,
                ACTION_SELECT_ALL,
                ACTION_ZOOM_IN,
                ACTION_ZOOM_OUT,
                ACTION_RESET_VIEW,
                ACTION_NEXT_PAGE,
                ACTION_PREVIOUS_PAGE,
                ACTION_LAYERS_SIDEBAR,
                ACTION_CONDITIONS_SIDEBAR,
                ACTION_STATUS_BAR,
                ACTION_ANNOTATION_WINDOW,
                "select_tool",
                "place_tool",
                "pan_tool",
                "zoom_tool",
                "dimension_tool",
                "text_annotation_tool",
                "highlight_annotation_tool",
                "arrow_annotation_tool",
                "line_annotation_tool",
                "rectangle_annotation_tool",
                "oval_annotation_tool",
                "polygon_annotation_tool",
                "cloud_annotation_tool",
                "ink_annotation_tool",
                "hotlink_tool",
                "named_view_tool",
                ACTION_BACKOUT_MODE,
            )
        }
        result = MenuBuilder(None, {}, shared_actions=shared_actions).create_menu()
        try:
            tools_menu = result.menus["tools"]
            action_texts = [
                action.text()
                for action in tools_menu.actions()
                if not action.isSeparator()
            ]
            self.assertEqual(
                action_texts[:16],
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
                    "Ink",
                    "Hotlink",
                    "Named View",
                ],
            )
            self.assertIs(tools_menu.actions()[4], shared_actions["dimension_tool"])
            self.assertIs(
                tools_menu.actions()[5], shared_actions["text_annotation_tool"]
            )
            self.assertIs(
                tools_menu.actions()[6], shared_actions["highlight_annotation_tool"]
            )
            self.assertIs(tools_menu.actions()[14], shared_actions["hotlink_tool"])
            self.assertIs(tools_menu.actions()[15], shared_actions["named_view_tool"])
        finally:
            result.menu_bar.deleteLater()
        self.assertEqual(
            ICON_SPECS[IconId.HOTLINK_TOOL].svg_name,
            "hotlink_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg",
        )
        self.assertTrue(
            (
                REPO_ROOT
                / "ost_visualizer"
                / "resources"
                / "icons"
                / ICON_SPECS[IconId.HOTLINK_TOOL].svg_name
            ).exists()
        )
        self.assertEqual(
            ICON_SPECS[IconId.NAMED_VIEW_TOOL].svg_name,
            "named_view_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg",
        )
        self.assertTrue(
            (
                REPO_ROOT
                / "ost_visualizer"
                / "resources"
                / "icons"
                / ICON_SPECS[IconId.NAMED_VIEW_TOOL].svg_name
            ).exists()
        )
        self.assertEqual(
            ICON_SPECS[IconId.DIMENSION_TOOL].svg_name,
            "square_foot_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg",
        )
        self.assertEqual(
            ICON_SPECS[IconId.TEXT_ANNOTATION_TOOL].svg_name,
            "serif_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg",
        )
        self.assertEqual(
            ICON_SPECS[IconId.HIGHLIGHT_ANNOTATION_TOOL].svg_name,
            "ink_marker_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg",
        )
        self.assertEqual(
            ICON_SPECS[IconId.INK_ANNOTATION_TOOL].svg_name,
            "gesture_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg",
        )


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
