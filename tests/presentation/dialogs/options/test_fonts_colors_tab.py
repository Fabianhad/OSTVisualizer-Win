import os
import unittest
from pathlib import Path
from unittest import mock
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.font_definition import FontDefinition
from ost_visualizer.presentation.dialogs.options.font_dialog import FontDialog
from ost_visualizer.presentation.dialogs.options.fonts_colors_tab import (
    COLOR_CATEGORIES,
    COLOR_CATEGORY_INACTIVE_OBJECTS,
    FONT_CATEGORIES,
    FONT_CATEGORY_TEXT,
    FontsColorsTab,
)
from ost_visualizer.presentation.utils.annotation_defaults import (
    apply_config_owned_annotation_defaults,
    build_placed_annotation_spec,
    set_annotation_styles_by_tool,
)
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import delete


class FontsColorsTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        set_annotation_styles_by_tool({}, Config())
        self.app.processEvents()

    def test_category_selection_refreshes_matching_previews(self):
        config = Config(
            default_area_label_font=FontDefinition(
                "Arial", "Bold", 10, 700, False, False
            ),
            inactive_object_color="#123456",
        )
        tab = FontsColorsTab()
        try:
            tab.load_config(config)
            tab.font_list.setCurrentRow(1)
            self.assertIn("10 pt", tab.font_preview.text())
            tab.color_list.setCurrentRow(5)
            self.assertEqual(tab.color_preview.toolTip(), "#123456")
        finally:
            tab.close()

    def test_change_color_accepts_and_cancels_with_button_parent(self):
        tab = FontsColorsTab()
        tab.load_config(Config())
        observed_parents = []
        real_color_dialog = QtWidgets.QColorDialog

        def create_color_dialog(color, parent):
            observed_parents.append(parent)
            return real_color_dialog(color, parent)

        try:
            original = tab.apply_to_config(Config()).inactive_object_color
            tab.color_list.setCurrentRow(5)
            with mock.patch(
                "ost_visualizer.presentation.dialogs.options.fonts_colors_tab."
                "QtWidgets.QColorDialog",
                side_effect=create_color_dialog,
            ), mock.patch.object(
                real_color_dialog,
                "exec",
                return_value=QtWidgets.QDialog.DialogCode.Rejected,
            ):
                tab.change_color_button.click()
                self.assertEqual(
                    tab.apply_to_config(Config()).inactive_object_color, original
                )
            with mock.patch(
                "ost_visualizer.presentation.dialogs.options.fonts_colors_tab."
                "QtWidgets.QColorDialog",
                side_effect=create_color_dialog,
            ), mock.patch.object(
                real_color_dialog,
                "exec",
                return_value=QtWidgets.QDialog.DialogCode.Accepted,
            ), mock.patch.object(
                real_color_dialog,
                "currentColor",
                return_value=QtGui.QColor("#123456"),
            ):
                tab.change_color_button.click()
            self.assertEqual(
                tab.apply_to_config(Config()).inactive_object_color, "#123456"
            )
            self.assertTrue(
                all(parent is tab.change_color_button for parent in observed_parents)
            )
        finally:
            tab.close()

    def test_change_color_stops_when_owning_button_is_destroyed(self):
        tab = FontsColorsTab()
        tab.load_config(Config())
        tab.color_list.setCurrentRow(5)

        class DestroyingColorDialog(QtWidgets.QColorDialog):
            def exec(self):
                delete(self.parent())
                return QtWidgets.QDialog.DialogCode.Accepted

            def currentColor(self):
                raise AssertionError("destroyed color dialog must not be read")

        with mock.patch(
            "ost_visualizer.presentation.dialogs.options.fonts_colors_tab."
            "QtWidgets.QColorDialog",
            DestroyingColorDialog,
        ):
            tab._change_color()
        tab.close()

    def test_change_font_accepts_and_cancels_with_button_parent(self):
        tab = FontsColorsTab()
        tab.load_config(Config())
        observed_parents = []
        real_font_dialog = FontDialog

        def create_rejected_dialog(definition, parent):
            observed_parents.append(parent)
            font_dialog = real_font_dialog(definition, parent)
            QtCore.QTimer.singleShot(0, font_dialog.reject)
            return font_dialog

        def create_accepted_dialog(definition, parent):
            observed_parents.append(parent)
            font_dialog = real_font_dialog(definition, parent)
            size_item = font_dialog.size_list.findItems(
                "72", QtCore.Qt.MatchFlag.MatchFixedString
            )[0]
            font_dialog.size_list.setCurrentItem(size_item)
            QtCore.QTimer.singleShot(0, font_dialog.accept)
            return font_dialog

        try:
            original = tab.apply_to_config(Config()).default_text_font
            with mock.patch(
                "ost_visualizer.presentation.dialogs.options.fonts_colors_tab."
                "FontDialog",
                side_effect=create_rejected_dialog,
            ):
                tab.change_font_button.click()
                self.assertEqual(
                    tab.apply_to_config(Config()).default_text_font, original
                )
            with mock.patch(
                "ost_visualizer.presentation.dialogs.options.fonts_colors_tab."
                "FontDialog",
                side_effect=create_accepted_dialog,
            ):
                tab.change_font_button.click()
            self.assertEqual(
                tab.apply_to_config(Config()).default_text_font.point_size,
                72,
            )
            self.assertTrue(
                all(parent is tab.change_font_button for parent in observed_parents)
            )
        finally:
            tab.close()

    def test_change_font_stops_when_owning_button_is_destroyed(self):
        tab = FontsColorsTab()
        tab.load_config(Config())

        class DestroyingFontDialog(QtWidgets.QDialog):
            def __init__(self, _definition, parent=None):
                super().__init__(parent)

            def exec(self):
                delete(self.parent())
                return QtWidgets.QDialog.DialogCode.Accepted

            def selected_font(self):
                raise AssertionError("destroyed font dialog must not be read")

        with mock.patch(
            "ost_visualizer.presentation.dialogs.options.fonts_colors_tab."
            "FontDialog",
            DestroyingFontDialog,
        ):
            tab._change_font()
        tab.close()

    def test_repeated_font_and_color_cancellation_releases_nested_dialogs(self):
        tab = FontsColorsTab()
        tab.load_config(Config())
        tab.color_list.setCurrentRow(5)
        real_color_dialog = QtWidgets.QColorDialog
        real_font_dialog = FontDialog

        def create_color_dialog(color, parent):
            return real_color_dialog(color, parent)

        def create_font_dialog(definition, parent):
            dialog = real_font_dialog(definition, parent)
            QtCore.QTimer.singleShot(0, dialog.reject)
            return dialog

        try:
            with mock.patch(
                "ost_visualizer.presentation.dialogs.options.fonts_colors_tab."
                "QtWidgets.QColorDialog",
                side_effect=create_color_dialog,
            ), mock.patch.object(
                real_color_dialog,
                "exec",
                return_value=QtWidgets.QDialog.DialogCode.Rejected,
            ):
                for _ in range(100):
                    tab._change_color()
            with mock.patch(
                "ost_visualizer.presentation.dialogs.options.fonts_colors_tab."
                "FontDialog",
                side_effect=create_font_dialog,
            ):
                for _ in range(100):
                    tab._change_font()
            self.app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
            self.app.processEvents()
            self.assertEqual(
                tab.change_color_button.findChildren(real_color_dialog), []
            )
            self.assertEqual(tab.change_font_button.findChildren(real_font_dialog), [])
        finally:
            tab.deleteLater()
