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
from ost_visualizer.domain.services.page_selection_service import PageSelectionService
from ost_visualizer.presentation.utils.annotation_defaults import (
    apply_config_owned_annotation_defaults,
    build_placed_annotation_spec,
    set_annotation_style_for_tool,
    set_annotation_styles_by_tool,
)
from PySide6 import QtCore, QtGui, QtWidgets


class PageSelectionAnnotationIdentityTests(unittest.TestCase):
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

    def test_in_memory_annotation_add_replaces_existing_uid(self):
        service = PageSelectionService()
        service.set_annotations(
            [
                BidAnnotation(
                    uid="a1",
                    annotation_type="rect",
                    page_uid="p1",
                    position=[1.0, 1.0],
                ),
                BidAnnotation(
                    uid="a1",
                    annotation_type="oval",
                    page_uid="p1",
                    position=[4.0, 4.0],
                ),
                BidAnnotation(
                    uid="a2",
                    annotation_type="oval",
                    page_uid="p1",
                    position=[2.0, 2.0],
                ),
            ]
        )
        service.add_annotations(
            [
                BidAnnotation(
                    uid="a1",
                    annotation_type="rect",
                    page_uid="p2",
                    position=[3.0, 3.0],
                )
            ]
        )
        annotations = service.get_all_annotations()
        self.assertEqual(
            [(a.uid, a.annotation_type) for a in annotations],
            [("a1", "oval"), ("a2", "oval"), ("a1", "rect")],
        )
        self.assertEqual(annotations[0].page_uid, "p1")
        self.assertEqual(annotations[0].position, [4.0, 4.0])
        self.assertEqual(annotations[-1].page_uid, "p2")
        self.assertEqual(annotations[-1].position, [3.0, 3.0])

    def test_in_memory_annotation_remove_by_key_preserves_same_uid_other_type(self):
        service = PageSelectionService()
        service.set_annotations(
            [
                BidAnnotation(uid="a1", annotation_type="rect", page_uid="p1"),
                BidAnnotation(uid="a1", annotation_type="oval", page_uid="p2"),
            ]
        )
        page_uids = service.remove_annotations_by_keys([("a1", "rect")])
        self.assertEqual(page_uids, ["p1"])
        self.assertEqual(
            [
                (a.uid, a.annotation_type, a.page_uid)
                for a in service.get_all_annotations()
            ],
            [("a1", "oval", "p2")],
        )
