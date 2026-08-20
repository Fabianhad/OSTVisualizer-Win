import unittest
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from PySide6 import QtCore, QtGui, QtWidgets
from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.font_definition import FontDefinition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.workspace_state import TakeoffWorkspaceState
from ost_visualizer.infrastructure.persistence.repositories.json_config_repository import (
    JsonConfigRepository,
)
from ost_visualizer.presentation.config import FONT_DIALOG_WIDTH
from ost_visualizer.presentation.dialogs.options.dialog import OptionsDialog
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
from ost_visualizer.presentation.utils.annotation_style_controls import TEXT_FONT_SIZES
from ost_visualizer.presentation.utils.font_catalog import (
    installed_font_families,
    lossless_font_styles,
    resolve_font_definition,
)
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)


class _ConfigRepository:
    config_path = "config.json"

    def __init__(self, config):
        self.config = config
        self.saved = []

    def load(self):
        return self.config

    def save(self, config):
        self.config = Config.from_dict(config.to_dict())
        self.saved.append(self.config)


class FontColorOptionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        set_annotation_styles_by_tool({}, Config())
        self.app.processEvents()

    def test_canonical_defaults_match_original_ost_contract(self):
        config = Config()
        self.assertEqual(
            config.default_text_font,
            FontDefinition("Arial", "Bold", 12, 700, False, False),
        )
        self.assertEqual(config.default_area_label_font.point_size, 10)
        self.assertEqual(config.default_dimension_annotation_font.weight, 700)
        self.assertEqual(config.default_style_label_font.style_name, "Bold")
        self.assertEqual(
            (
                config.default_text_color,
                config.default_area_label_color,
                config.default_dimension_annotation_color,
                config.default_style_label_color,
                config.default_highlight_color,
                config.default_hotlink_color,
                config.inactive_object_color,
            ),
            (
                "#ff0000",
                "#0000ff",
                "#000080",
                "#000080",
                "#ffff00",
                "#ff0000",
                "#d0d0d0",
            ),
        )

    def test_config_round_trip_and_missing_key_schema_evolution(self):
        changed = Config(
            default_text_font=FontDefinition(
                "Arial", "Bold Italic", 48, 700, True, True
            ),
            inactive_object_color="#123456",
        )
        self.assertEqual(Config.from_dict(changed.to_dict()), changed)
        old = Config.from_dict({"show_toolbar_text": False})
        self.assertFalse(old.show_toolbar_text)
        self.assertEqual(old.default_text_font, Config.DEFAULT_TEXT_FONT)
        self.assertEqual(
            old.inactive_object_color, Config.DEFAULT_INACTIVE_OBJECT_COLOR
        )

    def test_config_repository_round_trip_uses_only_the_canonical_file(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            repository = JsonConfigRepository(config_path)
            expected = Config(
                default_area_label_color="#123456",
                inactive_object_color="#abcdef",
            )
            repository.save(expected)
            self.assertEqual(repository.load(), expected)
            self.assertEqual(
                sorted(path.name for path in Path(temp_dir).iterdir()),
                ["config.json"],
            )

    def test_invalid_new_fields_are_corrected_independently(self):
        config = Config(
            default_text_font=FontDefinition("", "Bold", 12, 700, False, False),
            default_area_label_color="blue",
            default_hotlink_color="#ABCDEF",
            show_toolbar_text=False,
        )
        repository = _ConfigRepository(config)
        aggregate = ConfigAggregate(repository)
        snapshot = aggregate.snapshot()
        self.assertEqual(snapshot.default_text_font, Config.DEFAULT_TEXT_FONT)
        self.assertEqual(
            snapshot.default_area_label_color, Config.DEFAULT_AREA_LABEL_COLOR
        )
        self.assertEqual(snapshot.default_hotlink_color, "#abcdef")
        self.assertFalse(snapshot.show_toolbar_text)
        self.assertEqual(len(repository.saved), 1)

    def test_options_tab_order_rows_and_stable_ids(self):
        dialog = OptionsDialog(Config())
        try:
            self.assertEqual(
                [dialog._tabs.tabText(i) for i in range(dialog._tabs.count())],
                ["Options", "Fonts/Colors", "Export", "MCP Setup"],
            )
            tab = dialog._fonts_colors_tab
            self.assertEqual(
                [tab.font_list.item(i).text() for i in range(tab.font_list.count())],
                ["Text", "Area Label", "Dimension Line", "Default Style Label"],
            )
            self.assertEqual(
                [tab.color_list.item(i).text() for i in range(tab.color_list.count())],
                [
                    "Text",
                    "Area Label",
                    "Default Style Label",
                    "Highlight",
                    "Hot Link",
                    "Inactive Objects",
                ],
            )
            all_labels = {
                *(label for _key, label in FONT_CATEGORIES),
                *(label for _key, label in COLOR_CATEGORIES),
            }
            self.assertTrue(
                {"Image Legend", "Legend", "Callout", "AutoName"}.isdisjoint(all_labels)
            )
            self.assertEqual(
                tab.font_list.item(0).data(QtCore.Qt.ItemDataRole.UserRole),
                FONT_CATEGORY_TEXT,
            )
            self.assertEqual(
                tab.color_list.item(5).data(QtCore.Qt.ItemDataRole.UserRole),
                COLOR_CATEGORY_INACTIVE_OBJECTS,
            )
        finally:
            dialog.close()

    def test_options_font_color_values_are_staged_through_apply(self):
        applied = []
        dialog = OptionsDialog(Config(), apply_callback=applied.append)
        real_color_dialog = QtWidgets.QColorDialog
        created_dialogs = []

        def create_color_dialog(color, parent):
            color_dialog = real_color_dialog(color, parent)
            created_dialogs.append(color_dialog)
            return color_dialog

        try:
            tab = dialog._fonts_colors_tab
            tab.color_list.setCurrentRow(5)
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
            self.assertTrue(dialog._apply_button.isEnabled())
            self.assertEqual(applied, [])
            dialog._apply_button.click()
            self.assertEqual(applied[-1].inactive_object_color, "#123456")
            self.assertIs(created_dialogs[0].parent(), tab.change_color_button)
            dialog.reject()
            self.assertEqual(applied[-1].inactive_object_color, "#123456")
        finally:
            dialog.close()

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
            self.assertEqual(selected.point_size, 48)
            self.assertTrue(selected.underline)
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

    def test_lossless_style_filter_and_missing_font_fallback(self):
        families = installed_font_families()
        self.assertTrue(any(family.casefold() == "arial" for family in families))
        styles = lossless_font_styles("Arial")
        self.assertIn("Regular", styles)
        self.assertIn("Bold", styles)
        self.assertNotIn("Narrow", styles)
        self.assertNotIn("Black", styles)
        mismatched_style = resolve_font_definition(
            FontDefinition("Arial", "Bold", 12, 400, False, False)
        )
        self.assertEqual(mismatched_style.style_name, "Regular")
        fallback = resolve_font_definition(
            FontDefinition(
                "Definitely Missing Family",
                "Definitely Missing Style",
                72,
                700,
                True,
                True,
            )
        )
        self.assertEqual(fallback.family.casefold(), "arial")
        self.assertEqual((fallback.weight, fallback.italic), (700, True))
        self.assertTrue(fallback.underline)

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

    def test_inactive_color_substitution_preserves_opacity(self):
        service = ColorService()
        takeoff = Takeoff(
            uid="t1", condition_uid="c1", page_uid="p1", area_uid="area-b"
        )
        condition = Condition(uid="c1")
        color_map = {"c1": {"color": "#abcdef", "opacity": 0.37}}
        result_2d = service.get_2d_color_for_takeoff(
            takeoff,
            condition,
            color_map,
            {"p1": "area-a"},
            inactive_object_color="#123456",
        )
        result_3d = service.get_color_for_takeoff(
            takeoff,
            condition,
            color_map,
            Config.DISPLAY_MODE_SOLID,
            {"p1": "area-a"},
            inactive_object_color="#123456",
        )
        self.assertEqual((result_2d.hex, result_2d.opacity), ("#123456", 0.37))
        self.assertEqual((result_3d.hex, result_3d.opacity), ("#123456", 0.37))

    def test_legacy_workspace_overlap_is_ignored_and_stripped(self):
        state = TakeoffWorkspaceState.from_dict(
            {
                "annotation_styles": {
                    "text": {
                        "color": "#123456",
                        "font_name": "Legacy",
                        "font_size": 33,
                        "text_align": 2,
                    },
                    "dimension": {"color": "#654321"},
                    "highlight": {"color": "#111111"},
                    "hotlink": {"color": "#222222"},
                    "rect": {"color": "#abcdef", "line_width": 7},
                }
            }
        )
        self.assertEqual(state.annotation_styles["text"].text_align, 2)
        self.assertEqual(state.annotation_styles["text"].color, "#ff0000")
        self.assertNotIn("dimension", state.annotation_styles)
        self.assertNotIn("highlight", state.annotation_styles)
        self.assertNotIn("hotlink", state.annotation_styles)
        serialized = state.to_dict()["annotation_styles"]
        self.assertEqual(serialized["text"], {"text_align": 2})
        self.assertEqual(serialized["rect"]["color"], "#abcdef")

    def test_workspace_restore_keeps_config_owned_creation_defaults(self):
        config = Config(
            default_text_font=FontDefinition(
                "Arial", "Bold Italic", 24, 700, True, True
            ),
            default_text_color="#123456",
            default_dimension_annotation_color="#654321",
            default_highlight_color="#abcdef",
            default_hotlink_color="#fedcba",
        )
        styles = set_annotation_styles_by_tool(
            {
                "text": {
                    "color": "#999999",
                    "font_name": "Legacy",
                    "font_size": 33,
                    "text_align": 2,
                },
                "dimension": {"color": "#111111"},
                "highlight": {"color": "#222222"},
                "hotlink": {"color": "#333333"},
            },
            config,
        )
        self.assertEqual(styles["text"].text_align, 2)
        self.assertEqual(styles["text"].color, "#123456")
        self.assertEqual(styles["text"].font_name, "Arial")
        self.assertEqual(styles["text"].font_size, 24)
        self.assertEqual(styles["dimension"].color, "#654321")
        self.assertEqual(styles["highlight"].color, "#abcdef")
        self.assertEqual(styles["hotlink"].color, "#fedcba")

    def test_creation_defaults_stamp_new_annotations(self):
        config = Config(
            default_text_font=FontDefinition(
                "Arial", "Bold Italic", 24, 700, True, True
            ),
            default_text_color="#123456",
            default_highlight_color="#abcdef",
            default_area_label_color="#112233",
            default_style_label_color="#445566",
        )
        apply_config_owned_annotation_defaults(config)
        text_spec = build_placed_annotation_spec("text", "p1", [1.0, 2.0])
        highlight_spec = build_placed_annotation_spec(
            "highlight", "p1", [1.0, 2.0, 3.0, 4.0]
        )
        self.assertEqual(text_spec.color, "#123456")
        self.assertEqual(text_spec.properties["FontSize"], 24)
        self.assertTrue(text_spec.properties["FontBold"])
        self.assertTrue(text_spec.properties["FontItalic"])
        self.assertTrue(text_spec.properties["FontUnderline"])
        self.assertEqual(highlight_spec.color, "#abcdef")


if __name__ == "__main__":
    unittest.main()
