import unittest
from pathlib import Path
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_CLOUD,
    ANNOTATION_TYPE_POLYGON,
    ANNOTATION_TYPE_RECT,
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
    hex_color_to_int,
)
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.presentation.utils.annotation_defaults import (
    apply_config_owned_annotation_defaults,
    build_placed_annotation_spec,
    set_annotation_style_for_tool,
    set_annotation_styles_by_tool,
)
from PySide6 import QtCore, QtGui, QtWidgets


class AnnotationPasteTranslationTests(unittest.TestCase):
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

    def test_annotation_copy_translation_round_trip_preserves_payload_slots(self):
        from ost_visualizer.presentation.utils.annotation_paste import (
            translate_annotation_position,
        )

        for kind, position in (
            ("text", [100, 200, 50, 60, 0.123456789]),
            ("ink", [0.123456789, 100, 200, 300, 400]),
            ("rect", [100, 200, 300, 400, 0.123456789]),
        ):
            with self.subTest(kind=kind):
                annotation = BidAnnotation("a1", kind, position=list(position))
                for _ in range(20):
                    translated = translate_annotation_position(annotation, 0.25, -0.5)
                    self.assertEqual(annotation.position, position)
                    moved = BidAnnotation("a1", kind, position=translated)
                    annotation.position = translate_annotation_position(
                        moved, -0.25, 0.5
                    )
                    self.assertEqual(annotation.position, position)
