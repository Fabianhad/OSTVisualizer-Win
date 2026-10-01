import os
import unittest
from pathlib import Path
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.font_definition import FontDefinition
from ost_visualizer.presentation.config import COMPACT_SPACING, FONT_DIALOG_WIDTH
from ost_visualizer.presentation.dialogs.options.font_dialog import FontDialog
from ost_visualizer.presentation.utils.annotation_defaults import (
    apply_config_owned_annotation_defaults,
    build_placed_annotation_spec,
    set_annotation_styles_by_tool,
)
from ost_visualizer.presentation.utils.annotation_style_controls import TEXT_FONT_SIZES
from PySide6 import QtCore, QtGui, QtWidgets


class FontDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        set_annotation_styles_by_tool({}, Config())
        self.app.processEvents()

    def test_font_dialog_contract_and_shared_size_list(self):
        dialog = FontDialog(FontDefinition("Arial", "Bold", 12, 700, False, True))
        try:
            self.assertEqual(dialog.width(), FONT_DIALOG_WIDTH)
            self.assertEqual(dialog.minimumSize(), dialog.maximumSize())
            self.assertTrue(dialog.isModal())
            self.assertEqual(
                dialog.windowModality(), QtCore.Qt.WindowModality.ApplicationModal
            )
            flags = dialog.windowFlags()
            self.assertFalse(
                bool(flags & QtCore.Qt.WindowType.WindowMinimizeButtonHint)
            )
            self.assertFalse(
                bool(flags & QtCore.Qt.WindowType.WindowMaximizeButtonHint)
            )
            self.assertEqual(
                [
                    dialog.size_list.item(i).text()
                    for i in range(dialog.size_list.count())
                ],
                [str(size) for size in TEXT_FONT_SIZES],
            )
            self.assertIn("48", [str(size) for size in TEXT_FONT_SIZES])
            self.assertIn("72", [str(size) for size in TEXT_FONT_SIZES])
            visible_text = {
                label.text() for label in dialog.findChildren(QtWidgets.QLabel)
            }
            self.assertNotIn("Script", visible_text)
            self.assertEqual(dialog.findChildren(QtWidgets.QComboBox), [])
            size_48 = dialog.size_list.findItems(
                "48", QtCore.Qt.MatchFlag.MatchFixedString
            )[0]
            dialog.size_list.setCurrentItem(size_48)
            self.assertEqual(dialog.size_edit.text(), "48")
            self.assertEqual(dialog.sample_label.font().pointSize(), 48)
            dialog.ok_button.click()
            selected = dialog.selected_font()
            self.assertEqual(
                selected,
                FontDefinition("Arial", "Bold", 48, 700, False, True),
            )
        finally:
            dialog.close()

    def test_font_dialog_cancel_and_title_close_return_no_change(self):
        definition = FontDefinition("Arial", "Bold", 12, 700, False, False)
        cancel_dialog = FontDialog(definition)
        cancel_dialog.cancel_button.click()
        self.assertIsNone(cancel_dialog.selected_font())
        cancel_dialog.close()
        close_dialog = FontDialog(definition)
        close_dialog.show()
        close_dialog.close()
        self.app.processEvents()
        self.assertIsNone(close_dialog.selected_font())

    def test_font_dialog_fixed_layout_contains_controls_with_long_names(self):
        dialog = FontDialog(FontDefinition("Arial", "Bold", 12, 700, False, False))
        long_name = "A deliberately long installed font family or style name"
        try:
            self.assertEqual(dialog.sample_group.layout().spacing(), COMPACT_SPACING)
            dialog.font_list.addItem(long_name)
            dialog.style_list.addItem(long_name)
            dialog.font_edit.setText(long_name)
            dialog.style_edit.setText(long_name)
            dialog.show()
            self.app.processEvents()
            for widget in (
                dialog.font_edit,
                dialog.style_edit,
                dialog.size_edit,
                dialog.font_list,
                dialog.style_list,
                dialog.size_list,
                dialog.ok_button,
                dialog.cancel_button,
                dialog.sample_label,
            ):
                top_left = widget.mapTo(dialog, QtCore.QPoint())
                self.assertTrue(
                    dialog.rect().contains(QtCore.QRect(top_left, widget.size())),
                    f"{type(widget).__name__} extends outside the fixed dialog",
                )
        finally:
            dialog.close()

    def test_font_dialog_cancel_is_stacked_directly_below_ok(self):
        dialog = FontDialog(FontDefinition("Arial", "Bold", 12, 700, False, False))
        try:
            dialog.show()
            self.app.processEvents()
            self.assertEqual(dialog.cancel_button.x(), dialog.ok_button.x())
            self.assertGreaterEqual(
                dialog.cancel_button.y(), dialog.ok_button.geometry().bottom()
            )
            self.assertLess(dialog.cancel_button.y(), dialog.font_list.y())
        finally:
            dialog.close()

    def test_font_dialog_size_changes_do_not_resize_sample_group(self):
        dialog = FontDialog(FontDefinition("Arial", "Bold", 12, 700, False, False))
        try:
            dialog.show()
            self.app.processEvents()
            sample_size = dialog.sample_group.size()
            list_geometry = dialog.font_list.geometry()
            for point_size in (72, 8):
                size_item = dialog.size_list.findItems(
                    str(point_size), QtCore.Qt.MatchFlag.MatchFixedString
                )[0]
                dialog.size_list.setCurrentItem(size_item)
                self.app.processEvents()
                self.assertEqual(dialog.sample_group.size(), sample_size)
                self.assertEqual(dialog.font_list.geometry(), list_geometry)
                self.assertEqual(dialog.sample_label.font().pointSize(), point_size)
        finally:
            dialog.close()

    def test_font_dialog_invalid_size_blocks_ok_and_keeps_no_selection(self):
        dialog = FontDialog(FontDefinition("Arial", "Bold", 12, 700, False, False))
        try:
            dialog.size_edit.setText("200")
            self.assertFalse(dialog.size_edit.hasAcceptableInput())
            dialog.ok_button.click()
            self.assertFalse(dialog.ok_button.isEnabled())
            self.assertNotEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertIsNone(dialog.selected_font())
        finally:
            dialog.close()

    def test_font_dialog_typed_size_and_style_commit_into_selection(self):
        dialog = FontDialog(FontDefinition("Arial", "Bold", 12, 700, False, True))
        try:
            dialog.size_edit.setText("36")
            self.assertEqual(dialog.size_list.currentItem().text(), "36")
            dialog.size_edit.setText("30")
            self.assertIsNone(dialog.size_list.currentItem())
            italic = dialog.style_list.findItems(
                "Italic", QtCore.Qt.MatchFlag.MatchFixedString
            )[0]
            dialog.style_list.setCurrentItem(italic)
            self.assertEqual(dialog.style_edit.text(), "Italic")
            self.assertEqual(dialog.sample_label.font().pointSize(), 30)
            self.assertTrue(dialog.sample_label.font().italic())
            self.assertFalse(dialog.sample_label.font().bold())
            dialog.ok_button.click()
            self.assertEqual(
                dialog.selected_font(),
                FontDefinition("Arial", "Italic", 30, 400, True, True),
            )
        finally:
            dialog.close()

    def test_font_dialog_family_edit_rejects_unknown_and_canonicalizes_case(self):
        dialog = FontDialog(FontDefinition("Arial", "Bold", 12, 700, False, False))
        try:
            dialog.font_edit.setText("No Such Installed Family")
            dialog.font_edit.editingFinished.emit()
            self.assertEqual(dialog.font_edit.text(), "Arial")
            dialog.font_edit.setText("aRiAl")
            dialog.font_edit.editingFinished.emit()
            self.assertEqual(dialog.font_edit.text(), "Arial")
            self.assertEqual(dialog.font_list.currentItem().text(), "Arial")
            dialog.ok_button.click()
            self.assertEqual(
                dialog.selected_font(),
                FontDefinition("Arial", "Bold", 12, 700, False, False),
            )
        finally:
            dialog.close()
