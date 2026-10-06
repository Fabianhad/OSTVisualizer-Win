import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.actions.action_ids import (
    ACTION_PAN_SIDEBAR,
    ACTION_RESET_VIEW,
)
from ost_visualizer.presentation.configurators.window_configurator import (
    resource_path,
)
from ost_visualizer.presentation.utils import themed_icon
from ost_visualizer.presentation.managers.icon_manager import (
    ACTION_ICONS,
    ICON_SPECS,
    IconId,
    IconManager,
)
from PySide6 import QtCore, QtGui, QtWidgets
from tests.presentation.dialogs.options.preference_support import (
    _app as _preferences_support__app,
)


class IconManagerPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_text_format_icons_are_registered(self):
        _preferences_support__app()
        expected_icons = {
            IconId.FORMAT_BOLD: (
                "format_bold_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
            IconId.FORMAT_ITALIC: (
                "format_italic_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
            IconId.FORMAT_UNDERLINE: (
                "format_underlined_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
            IconId.FORMAT_ALIGN_LEFT: (
                "format_align_left_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
            IconId.FORMAT_ALIGN_CENTER: (
                "format_align_center_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
            IconId.FORMAT_ALIGN_RIGHT: (
                "format_align_right_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
            IconId.PROJECT_TREE_DATABASE: (
                "database_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
            IconId.FOLDER: ("folder_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
            IconId.PROJECT_TREE_BID: (
                "request_page_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
            IconId.PAGE_TAKEOFF_INDICATOR: (
                "draft_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
        }
        for icon_id, svg_name in expected_icons.items():
            with self.subTest(icon_id=icon_id):
                self.assertEqual(ICON_SPECS[icon_id].svg_name, svg_name)
                icon = IconManager.icon(icon_id)
                self.assertFalse(icon.isNull())
                image = icon.pixmap(24, 24).toImage()
                self.assertFalse(image.isNull())
                self.assertTrue(
                    any(
                        image.pixelColor(x, y).alpha() > 0
                        for x in range(image.width())
                        for y in range(image.height())
                    ),
                    "icon renders no visible pixels",
                )

    def test_every_registered_icon_has_an_existing_svg_that_renders(self):
        for icon_id, spec in ICON_SPECS.items():
            with self.subTest(icon_id=icon_id):
                self.assertTrue(
                    Path(resource_path("resources", "icons", spec.svg_name)).is_file()
                )
                self.assertFalse(IconManager.icon(icon_id).isNull())

    def test_colored_icon_recolors_every_visible_pixel(self):
        icon = IconManager.colored_icon(IconId.FOLDER, "#ff0000")
        image = icon.pixmap(24, 24).toImage()
        visible = [
            image.pixelColor(x, y)
            for x in range(image.width())
            for y in range(image.height())
            if image.pixelColor(x, y).alpha() > 0
        ]
        self.assertTrue(visible)
        for color in visible:
            self.assertEqual((color.red(), color.green(), color.blue()), (255, 0, 0))

    def test_pan_sidebar_icon_exists_loads_is_registered_for_its_action_and_recolors(
        self,
    ):
        svg_name = "panorama_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
        path = Path(resource_path("resources", "icons", svg_name))
        self.assertTrue(path.is_file())
        self.assertIn('fill="#e3e3e3"', path.read_text(encoding="utf-8"))
        self.assertEqual(ICON_SPECS[IconId.PAN_SIDEBAR].svg_name, svg_name)
        self.assertEqual(ACTION_ICONS[ACTION_PAN_SIDEBAR], IconId.PAN_SIDEBAR)
        self.assertFalse(IconManager.icon(IconId.PAN_SIDEBAR).isNull())
        action = QtGui.QAction("Pan Sidebar")
        IconManager.apply_to_action(action, ACTION_PAN_SIDEBAR)
        self.assertFalse(action.icon().isNull())
        self.assertEqual(
            action.icon().cacheKey(), IconManager.icon(IconId.PAN_SIDEBAR).cacheKey()
        )
        red = IconManager.colored_icon(IconId.PAN_SIDEBAR, "#ff0000")
        image = red.pixmap(24, 24).toImage()
        visible = [
            image.pixelColor(x, y)
            for x in range(image.width())
            for y in range(image.height())
            if image.pixelColor(x, y).alpha() > 0
        ]
        self.assertTrue(visible)
        for color in visible:
            self.assertEqual((color.red(), color.green(), color.blue()), (255, 0, 0))

    def test_pan_sidebar_icon_follows_the_palette_for_light_and_dark_themes(self):
        original = self.app.palette()

        def restore():
            self.app.setPalette(original)
            themed_icon.rebuild_all_icons()

        self.addCleanup(restore)
        action = QtGui.QAction("Pan Sidebar")
        IconManager.apply_to_action(action, ACTION_PAN_SIDEBAR)
        for text_color in ("#101010", "#f0f0f0", "#101010"):
            with self.subTest(text_color=text_color):
                palette = QtGui.QPalette(original)
                palette.setColor(
                    QtGui.QPalette.ColorRole.WindowText, QtGui.QColor(text_color)
                )
                self.app.setPalette(palette)
                themed_icon.rebuild_all_icons()
                image = action.icon().pixmap(24, 24).toImage()
                solid = {
                    image.pixelColor(x, y).name()
                    for x in range(image.width())
                    for y in range(image.height())
                    if image.pixelColor(x, y).alpha() == 255
                }
                self.assertEqual(solid, {text_color})

    def test_apply_to_action_uses_registered_icon_and_ignores_unknown_keys(self):
        action = QtGui.QAction("Undo")
        IconManager.apply_to_action(action, ACTION_RESET_VIEW)
        self.assertFalse(action.icon().isNull())
        self.assertEqual(
            action.icon().cacheKey(), IconManager.icon(IconId.RESET_VIEW).cacheKey()
        )
        unknown = QtGui.QAction("Unknown")
        IconManager.apply_to_action(unknown, "not_a_registered_action")
        self.assertTrue(unknown.icon().isNull())
