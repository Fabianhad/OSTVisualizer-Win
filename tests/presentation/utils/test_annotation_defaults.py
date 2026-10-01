from PySide6 import QtCore, QtGui, QtWidgets
from ost_visualizer.presentation.utils.annotation_defaults import (
    apply_config_owned_annotation_defaults,
    build_placed_annotation_spec,
    set_annotation_styles_by_tool,
)
from ost_visualizer.domain.entities.font_definition import FontDefinition
from ost_visualizer.domain.entities.config import Config
from pathlib import Path
import unittest
import os
from ost_visualizer.domain.entities.annotation_style import AnnotationStyle
from ost_visualizer.presentation.utils.annotation_defaults import (
    apply_config_owned_annotation_defaults,
    build_placed_annotation_spec,
    get_annotation_styles_by_tool,
    set_annotation_style_for_tool,
    set_annotation_styles_by_tool,
)


class AnnotationFontColorDefaultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        set_annotation_styles_by_tool({}, Config())
        self.app.processEvents()

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
                "rect": {"color": "#445566", "line_width": 9},
            },
            config,
        )
        self.assertEqual(styles["text"].text_align, 2)
        self.assertEqual(styles["text"].color, "#123456")
        self.assertEqual(styles["text"].font_name, "Arial")
        self.assertEqual(styles["text"].font_size, 24)
        self.assertTrue(styles["text"].font_bold)
        self.assertTrue(styles["text"].font_italic)
        self.assertTrue(styles["text"].font_underline)
        self.assertEqual(styles["rect"].color, "#445566")
        self.assertEqual(styles["rect"].line_width, 9.0)
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
        self.assertEqual(text_spec.properties["FontColor"], 0x563412)
        self.assertEqual(text_spec.properties["FontName"], "Arial")
        self.assertEqual(text_spec.properties["FontSize"], 24)
        self.assertTrue(text_spec.properties["FontBold"])
        self.assertTrue(text_spec.properties["FontItalic"])
        self.assertTrue(text_spec.properties["FontUnderline"])
        self.assertEqual(highlight_spec.color, "#abcdef")
        self.assertEqual(highlight_spec.width, 0.0)
        self.assertEqual(highlight_spec.properties, {})


class AnnotationPlacementDefaultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        font_directory = Path(r"C:\Windows\Fonts")
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def setUp(self):
        apply_config_owned_annotation_defaults(Config())

    def tearDown(self):
        for annotation_type in (
            "dimension",
            "text",
            "highlight",
            "arrow",
            "line",
            "rect",
            "oval",
            "polygon",
            "cloud",
            "ink",
        ):
            set_annotation_style_for_tool(
                annotation_type,
                color="#ff0000",
                line_width=4.0,
                font_name="Arial",
                font_size=12,
                font_bold=False,
                font_italic=False,
                font_underline=False,
                text_align=0,
            )
        apply_config_owned_annotation_defaults(Config())

    def test_markup_annotation_default_line_width_is_four_pixels(self):
        for annotation_type in (
            "arrow",
            "line",
            "rect",
            "oval",
            "polygon",
            "cloud",
            "ink",
        ):
            with self.subTest(annotation_type=annotation_type):
                spec = build_placed_annotation_spec(
                    annotation_type, "p1", [1.0, 2.0, 13.0, 14.0]
                )
                self.assertEqual(spec.width, 4.0)
                self.assertEqual(spec.color, "#ff0000")
        highlight_spec = build_placed_annotation_spec(
            "highlight", "p1", [1.0, 2.0, 13.0, 14.0]
        )
        self.assertEqual(highlight_spec.width, 0.0)
        self.assertEqual(highlight_spec.color, "#ffff00")

    def test_each_annotation_tool_default_is_independent(self):
        defaults = {
            "arrow": ("#110000", 2.0),
            "line": ("#002200", 3.0),
            "rect": ("#000033", 4.0),
            "oval": ("#445500", 5.0),
            "polygon": ("#006666", 6.0),
            "cloud": ("#770077", 7.0),
            "ink": ("#117777", 8.0),
            "highlight": ("#227788", 11.0),
            "text": ("#888800", 8.0),
            "dimension": ("#009999", 10.0),
        }
        for annotation_type, (color, width) in defaults.items():
            set_annotation_style_for_tool(
                annotation_type, color=color, line_width=width
            )
        set_annotation_style_for_tool(
            "text",
            font_name="Segoe UI",
            font_size=18,
            font_bold=True,
            font_italic=True,
            font_underline=True,
            text_align=1,
        )
        for annotation_type, (color, width) in defaults.items():
            with self.subTest(annotation_type=annotation_type):
                spec = build_placed_annotation_spec(
                    annotation_type, "p1", [1.0, 2.0, 13.0, 14.0]
                )
                self.assertEqual(spec.color, color)
                if annotation_type == "dimension":
                    self.assertEqual(spec.width, 1.0)
                elif annotation_type in ("text", "highlight"):
                    self.assertEqual(spec.width, 0.0)
                else:
                    self.assertEqual(spec.width, width)
        text_spec = build_placed_annotation_spec("text", "p1", [1.0, 2.0, 13.0, 14.0])
        self.assertEqual(text_spec.properties["FontColor"], 0x008888)
        self.assertEqual(text_spec.properties["FontName"], "Segoe UI")
        self.assertEqual(text_spec.properties["FontSize"], 18)
        self.assertTrue(text_spec.properties["FontBold"])
        self.assertTrue(text_spec.properties["FontItalic"])
        self.assertTrue(text_spec.properties["FontUnderline"])
        self.assertEqual(text_spec.properties["TextAlign"], 1)
        dimension_spec = build_placed_annotation_spec(
            "dimension", "p1", [1.0, 2.0, 13.0, 14.0]
        )
        self.assertEqual(dimension_spec.properties["FontColor"], "#009999")
        self.assertEqual(dimension_spec.width, 1.0)
        set_annotation_style_for_tool(
            "dimension",
            font_name="Calibri",
            font_size=16,
            font_bold=True,
            font_italic=True,
            font_underline=True,
        )
        dimension_spec = build_placed_annotation_spec(
            "dimension", "p1", [1.0, 2.0, 13.0, 14.0]
        )
        self.assertEqual(dimension_spec.properties["FontName"], "Calibri")
        self.assertEqual(dimension_spec.properties["FontSize"], 16)
        self.assertTrue(dimension_spec.properties["FontBold"])
        self.assertTrue(dimension_spec.properties["FontItalic"])
        self.assertTrue(dimension_spec.properties["FontUnderline"])

    def test_annotation_style_restore_ignores_retired_tool_keys(self):
        try:
            styles = set_annotation_styles_by_tool(
                {
                    "rect": AnnotationStyle(color="#123456", line_width=6.0),
                    "retired-tool": AnnotationStyle(color="#abcdef"),
                },
                Config(),
            )
            self.assertEqual(styles["rect"].color, "#123456")
            self.assertEqual(styles["rect"].line_width, 6.0)
            self.assertNotIn("retired-tool", styles)
            self.assertEqual(
                set(styles), set(get_annotation_styles_by_tool()) - {"retired-tool"}
            )
            self.assertEqual(styles["line"], AnnotationStyle())
        finally:
            set_annotation_styles_by_tool({}, Config())

    def test_hotlink_and_named_view_defaults_use_fixed_width_and_own_colors(self):
        hotlink_spec = build_placed_annotation_spec("hotlink", "p1", [1.0, 2.0])
        named_view_spec = build_placed_annotation_spec(
            "namedview", "p1", [1.0, 2.0, 13.0, 14.0]
        )
        self.assertEqual(hotlink_spec.color, "#ff0000")
        self.assertEqual(hotlink_spec.width, 2.0)
        self.assertEqual(hotlink_spec.properties, {"BidPageViewUID": ""})
        self.assertEqual(named_view_spec.color, "#008000")
        self.assertEqual(named_view_spec.width, 2.0)
        self.assertEqual(named_view_spec.properties, {"Text": ""})

    def test_unknown_tool_type_builds_no_spec_and_rejects_style_changes(self):
        self.assertIsNone(build_placed_annotation_spec("retired-tool", "p1", [1.0]))
        with self.assertRaises(ValueError):
            set_annotation_style_for_tool("retired-tool", color="#123456")

    def test_line_width_is_ignored_for_tools_with_fixed_width(self):
        before = {
            key: get_annotation_styles_by_tool()[key].line_width
            for key in ("dimension", "text", "highlight", "hotlink", "namedview")
        }
        for key in before:
            style = set_annotation_style_for_tool(key, line_width=9.0)
            self.assertEqual(style.line_width, before[key], key)
        self.assertEqual(
            set_annotation_style_for_tool("rect", line_width=99.0).line_width, 16.0
        )
