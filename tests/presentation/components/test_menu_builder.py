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
    ACTION_PAN_SIDEBAR,
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

        def flatten(items):
            for item in items:
                yield item
                if item[0] == "cascade":
                    yield from flatten(item[2])

        for menu_name, items in builder._get_menu_definition().items():
            for item in flatten(items):
                self.assertNotIn("mcp", " ".join(map(str, item)).lower(), menu_name)

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

    def test_master_menu_default_layers_command_invokes_its_callback(self):
        calls = []
        builder = MenuBuilder(None, {ACTION_DEFAULT_LAYERS: lambda: calls.append(True)})
        menu = QtWidgets.QMenu()
        builder._build_menu(menu, builder._get_menu_definition()["Master"])
        try:
            self.assertEqual(
                [
                    action.text()
                    for action in menu.actions()
                    if not action.isSeparator()
                ],
                [
                    "Employees",
                    "Job Statuses",
                    "Condition Types",
                    "Payroll Classes",
                    "Default Layers",
                ],
            )
            default_layers = [
                action for action in menu.actions() if action.text() == "Default Layers"
            ]
            self.assertEqual(len(default_layers), 1)
            self.assertIs(builder.actions[ACTION_DEFAULT_LAYERS], default_layers[0])
            default_layers[0].trigger()
            self.assertEqual(calls, [True])
        finally:
            builder.cleanup()
            menu.deleteLater()

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
                ACTION_PAN_SIDEBAR,
                ACTION_CONDITIONS_SIDEBAR,
                ACTION_LAYERS_SIDEBAR,
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
            for action_key, icon_id in (
                ("dimension_tool", IconId.DIMENSION_TOOL),
                ("text_annotation_tool", IconId.TEXT_ANNOTATION_TOOL),
                ("highlight_annotation_tool", IconId.HIGHLIGHT_ANNOTATION_TOOL),
                ("ink_annotation_tool", IconId.INK_ANNOTATION_TOOL),
                ("hotlink_tool", IconId.HOTLINK_TOOL),
                ("named_view_tool", IconId.NAMED_VIEW_TOOL),
            ):
                action_icon = shared_actions[action_key].icon()
                self.assertFalse(action_icon.isNull(), action_key)
                self.assertEqual(
                    action_icon.cacheKey(),
                    IconManager.icon(icon_id).cacheKey(),
                    action_key,
                )
            self.assertNotEqual(
                shared_actions["text_annotation_tool"].icon().cacheKey(),
                shared_actions["dimension_tool"].icon().cacheKey(),
            )
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
        for icon_id in (
            IconId.DIMENSION_TOOL,
            IconId.TEXT_ANNOTATION_TOOL,
            IconId.HIGHLIGHT_ANNOTATION_TOOL,
            IconId.INK_ANNOTATION_TOOL,
        ):
            self.assertTrue(
                (
                    REPO_ROOT
                    / "ost_visualizer"
                    / "resources"
                    / "icons"
                    / ICON_SPECS[icon_id].svg_name
                ).exists(),
                icon_id,
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
        flag, first, second = menu.actions()
        self.assertFalse(flag.isChecked())
        self.assertTrue(first.isChecked())
        self.assertFalse(second.isChecked())
        for action in menu.actions():
            action.trigger()
        # The no-op callbacks must not break the actions' own check state: the
        # flag toggled and the exclusive radio group moved to the triggered entry.
        self.assertTrue(flag.isChecked())
        self.assertFalse(first.isChecked())
        self.assertTrue(second.isChecked())
        self.assertEqual(builder.variable_actions["mode"], [first, second])
        self.assertEqual(builder.variable_actions["flag"], [flag])
        builder.cleanup()
        menu.deleteLater()

    def test_check_and_radio_actions_pass_state_and_value_to_callbacks(self):
        received = []
        builder = MenuBuilder(
            None,
            {
                "flag_cb": lambda checked: received.append(("flag", checked)),
                "mode_cb": lambda value: received.append(("mode", value)),
            },
            state_getters={"flag": lambda: True, "mode": lambda: "second"},
        )
        menu = QtWidgets.QMenu()
        builder._build_menu(
            menu,
            [
                ("check", "Flag", "flag", "flag_cb"),
                ("radio", "First", "mode", "first", "mode_cb"),
                ("radio", "Second", "mode", "second", "mode_cb"),
            ],
        )
        flag, first, second = menu.actions()
        self.assertTrue(flag.isChecked())
        self.assertFalse(first.isChecked())
        self.assertTrue(second.isChecked())
        self.assertEqual(first.data(), "first")
        self.assertEqual(second.data(), "second")
        flag.trigger()
        first.trigger()
        self.assertEqual(received, [("flag", False), ("mode", "first")])
        self.assertTrue(first.isChecked())
        self.assertFalse(second.isChecked())
        builder.cleanup()
        menu.deleteLater()

    def test_cleanup_is_idempotent(self):
        calls = []
        builder = MenuBuilder(None, {"command": lambda: calls.append(True)})
        menu = QtWidgets.QMenu()
        builder._build_menu(menu, [("cmd", "Command", "command")])
        action = menu.actions()[0]
        action.trigger()
        self.assertEqual(calls, [True])
        builder.cleanup()
        builder.cleanup()
        action.trigger()
        self.assertEqual(calls, [True])
        self.assertIsNone(builder.actions)
        self.assertIsNone(builder.menus)
        self.assertIsNone(builder.variable_actions)
        self.assertIsNone(builder.callbacks)
        self.assertIsNone(builder.state_getters)
        self.assertIsNone(builder.parent)
        menu.deleteLater()
