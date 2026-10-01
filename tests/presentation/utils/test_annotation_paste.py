import unittest
from pathlib import Path
from types import SimpleNamespace
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_CLOUD,
    ANNOTATION_TYPE_POLYGON,
    ANNOTATION_TYPE_RECT,
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
    hex_color_to_int,
)
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.presentation.utils.annotation_paste import (
    annotation_paste_anchor,
    annotation_paste_source_anchor,
    annotation_paste_translation,
)
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

        for kind, position, expected in (
            (
                "text",
                [100, 200, 50, 60, 0.123456789],
                [100.25, 199.5, 50, 60, 0.123456789],
            ),
            (
                "ink",
                [0.123456789, 100, 200, 300, 400],
                [0.123456789, 100.25, 199.5, 300.25, 399.5],
            ),
            (
                "rect",
                [100, 200, 300, 400, 0.123456789],
                [100.25, 199.5, 300.25, 399.5, 0.123456789],
            ),
        ):
            with self.subTest(kind=kind):
                annotation = BidAnnotation("a1", kind, position=list(position))
                for _ in range(20):
                    translated = translate_annotation_position(annotation, 0.25, -0.5)
                    self.assertEqual(translated, expected)
                    self.assertEqual(annotation.position, position)
                    moved = BidAnnotation("a1", kind, position=translated)
                    annotation.position = translate_annotation_position(
                        moved, -0.25, 0.5
                    )
                    self.assertEqual(annotation.position, position)


class AnnotationPasteAnchorTests(unittest.TestCase):
    def test_anchor_skips_ink_count_slot_and_reads_first_point(self):
        odd_ink = BidAnnotation("i", "ink", position=[2, 10, 20, 30, 40])
        even_ink = BidAnnotation("i", "ink", position=[10, 20, 30, 40])
        rect = BidAnnotation("r", "rect", position=[5, 6, 7, 8])
        self.assertEqual(annotation_paste_anchor(odd_ink), (10.0, 20.0))
        self.assertEqual(annotation_paste_anchor(even_ink), (10.0, 20.0))
        self.assertEqual(annotation_paste_anchor(rect), (5.0, 6.0))

    def test_anchor_is_none_without_a_full_point(self):
        self.assertIsNone(
            annotation_paste_anchor(BidAnnotation("r", "rect", position=[5]))
        )
        self.assertIsNone(
            annotation_paste_anchor(BidAnnotation("i", "ink", position=[3]))
        )

    def test_source_anchor_uses_first_annotation_that_has_one(self):
        empty = BidAnnotation("e", "rect", position=[])
        rect = BidAnnotation("r", "rect", position=[5, 6, 7, 8])
        other = BidAnnotation("o", "rect", position=[1, 2, 3, 4])
        self.assertEqual(
            annotation_paste_source_anchor([empty, rect, other]), (5.0, 6.0)
        )
        self.assertIsNone(annotation_paste_source_anchor([empty]))


class AnnotationPasteTranslationOffsetTests(unittest.TestCase):
    def plan_view(self, snap, intelligent, mouse):
        return SimpleNamespace(
            snap_increments=snap,
            intelligent_paste_enabled=intelligent,
            current_mouse_ost_position=lambda: mouse,
        )

    def test_plain_paste_offsets_by_snap_increment_or_one(self):
        rect = BidAnnotation("r", "rect", position=[5, 6, 7, 8])
        self.assertEqual(
            annotation_paste_translation(self.plan_view(2.5, False, (1, 1)), [rect]),
            (2.5, 2.5, None),
        )
        self.assertEqual(
            annotation_paste_translation(self.plan_view(0, False, (1, 1)), [rect]),
            (1.0, 1.0, None),
        )

    def test_intelligent_paste_moves_source_anchor_to_mouse(self):
        rect = BidAnnotation("r", "rect", position=[5, 6, 7, 8])
        self.assertEqual(
            annotation_paste_translation(self.plan_view(2.5, True, (15, 4)), [rect]),
            (10.0, -2.0, (5.0, 6.0)),
        )

    def test_intelligent_paste_without_mouse_does_not_move_annotations(self):
        rect = BidAnnotation("r", "rect", position=[5, 6, 7, 8])
        self.assertEqual(
            annotation_paste_translation(self.plan_view(2.5, True, None), [rect]),
            (0.0, 0.0, (5.0, 6.0)),
        )

    def test_intelligent_paste_without_anchor_falls_back_to_snap_offset(self):
        empty = BidAnnotation("e", "rect", position=[])
        self.assertEqual(
            annotation_paste_translation(self.plan_view(2.5, True, (15, 4)), [empty]),
            (2.5, 2.5, None),
        )
