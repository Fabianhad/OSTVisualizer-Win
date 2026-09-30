import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.layer import Layer
from ost_visualizer.infrastructure.mdb.components.annotation_reader import (
    AnnotationReaderMixin,
)
from ost_visualizer.infrastructure.mdb.components.serialization import (
    encode_position,
    parse_position_storage,
    serialize_position_for_table,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsTextItem,
)
from tests.integration.annotations.dimension_support import (
    _FakeConnection as _dimension_support__FakeConnection,
    _FakeCursor as _dimension_support__FakeCursor,
    _FakeSchema as _dimension_support__FakeSchema,
    _Reader as _dimension_support__Reader,
    _annotation_reader_schema as _dimension_support__annotation_reader_schema,
)


class BidDimensionAnnotationTests(unittest.TestCase):
    def test_annotation_reader_rejects_duplicate_and_malformed_named_view_uids(self):
        valid_position = encode_position(
            [0.0, 0.0, 20.0, 0.0, 20.0, 10.0, 0.0, 10.0, 0.0]
        )
        fixtures = (
            (
                [
                    SimpleNamespace(
                        UID=7,
                        BidPageUID=3,
                        Name="First",
                        Color=0,
                        Position=valid_position,
                    ),
                    SimpleNamespace(
                        UID=7,
                        BidPageUID=3,
                        Name="Conflicting",
                        Color=0,
                        Position=valid_position,
                    ),
                ],
                "duplicate UID 7",
            ),
            (
                [
                    SimpleNamespace(
                        UID=None,
                        BidPageUID=3,
                        Name="Missing",
                        Color=0,
                        Position=valid_position,
                    )
                ],
                "malformed UID <missing>",
            ),
        )
        for rows, message in fixtures:
            with self.subTest(message=message):
                with self.assertRaisesRegex(RuntimeError, message):
                    _dimension_support__Reader()._parse_bid_annotations_for_bid(
                        _dimension_support__FakeConnection({"BidNamedViews": rows}),
                        "1",
                        {},
                        _dimension_support__annotation_reader_schema(),
                    )

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_bid_dimensions_are_read_as_dimension_annotations(self):
        row = SimpleNamespace(
            UID=7,
            BidPageUID=3,
            BidTakeoffFromUID=11,
            BidTakeoffToUID=12,
            Position=encode_position([0.0, 0.0, 255.0, 0.0]),
            FontName="Arial",
            FontColor=255,
            FontSize=10,
            FontBold=False,
            FontItalic=False,
            FontUnderline=False,
        )
        annotations = _dimension_support__Reader()._parse_bid_annotations_for_bid(
            _dimension_support__FakeConnection({"BidDimensions": [row]}),
            "1",
            {"99": Layer(uid="99", name="Annotation", visible=True)},
            _dimension_support__annotation_reader_schema(),
        )
        dimensions = [ann for ann in annotations if ann.is_dimension]
        self.assertEqual(len(dimensions), 1)
        dimension = dimensions[0]
        self.assertEqual(dimension.uid, "7")
        self.assertEqual(dimension.page_uid, "3")
        self.assertEqual(dimension.position, [0.0, 0.0, 255.0, 0.0])
        self.assertEqual(dimension.color, "#ff0000")
        self.assertEqual(dimension.width, 1.0)
        self.assertEqual(dimension.properties["BidTakeoffFromUID"], "11")
        self.assertEqual(dimension.properties["BidTakeoffToUID"], "12")

    def test_placeable_annotation_shapes_reload_from_existing_tables(self):
        rows_by_table = {
            "BidALines": [
                SimpleNamespace(
                    UID=11,
                    BidPageUID=3,
                    BidTakeoffFromUID=None,
                    BidTakeoffToUID=None,
                    Position=encode_position([0.0, 0.0, 10.0, 10.0]),
                    Color=255,
                    Width=2,
                )
            ],
            "BidArrows": [
                SimpleNamespace(
                    UID=12,
                    BidPageUID=3,
                    BidTakeoffFromUID=None,
                    BidTakeoffToUID=None,
                    Position=encode_position([1.0, 2.0, 13.0, 14.0]),
                    Color=255,
                    Width=2,
                )
            ],
            "BidAnnotationRects": [
                SimpleNamespace(
                    UID=13,
                    BidPageUID=3,
                    BidLayerUID=99,
                    Position=encode_position([1.0, 2.0, 13.0, 14.0]),
                    Color=255,
                    Width=2,
                )
            ],
            "BidAnnotationOvals": [
                SimpleNamespace(
                    UID=14,
                    BidPageUID=3,
                    BidLayerUID=99,
                    Position=encode_position([2.0, 3.0, 14.0, 15.0]),
                    Color=255,
                    Width=2,
                )
            ],
            "BidAnnotationPolygons": [
                SimpleNamespace(
                    UID=15,
                    BidPageUID=3,
                    BidLayerUID=99,
                    Position=encode_position([0.0, 0.0, 12.0, 0.0, 6.0, 8.0]),
                    Color=255,
                    Width=2,
                )
            ],
            "BidAnnotationClouds": [
                SimpleNamespace(
                    UID=16,
                    BidPageUID=3,
                    BidLayerUID=99,
                    Position=encode_position([1.0, 1.0, 13.0, 1.0, 7.0, 9.0]),
                    Color=255,
                    Width=2,
                )
            ],
            "BidAnnoInk": [
                SimpleNamespace(
                    UID=18,
                    BidPageUID=3,
                    Position=encode_position([0.0, 0.0, 5.0, 5.0, 10.0, 0.0]),
                    Color=255,
                    Width=2,
                )
            ],
            "BidHighlights": [
                SimpleNamespace(
                    UID=17,
                    BidPageUID=3,
                    BidLayerUID=99,
                    Position=encode_position(
                        [3.0, 4.0, 15.0, 4.0, 15.0, 16.0, 3.0, 16.0]
                    ),
                    Color=0x00FFFF,
                )
            ],
        }
        annotations = _dimension_support__Reader()._parse_bid_annotations_for_bid(
            _dimension_support__FakeConnection(rows_by_table),
            "1",
            {"99": Layer(uid="99", name="Annotation", visible=True)},
            _dimension_support__annotation_reader_schema(),
        )
        by_type = {ann.annotation_type: ann for ann in annotations}
        self.assertEqual(
            set(by_type),
            {
                "line",
                "arrow",
                "rect",
                "oval",
                "polygon",
                "cloud",
                "ink",
                "highlight",
            },
        )
        self.assertEqual(by_type["arrow"].position, [1.0, 2.0, 13.0, 14.0])
        self.assertEqual(by_type["highlight"].color, "#ffff00")
        self.assertEqual(by_type["highlight"].width, 0.0)
        self.assertEqual(
            by_type["polygon"].position,
            [0.0, 0.0, 12.0, 0.0, 6.0, 8.0],
        )
        self.assertEqual(by_type["ink"].position, [0.0, 0.0, 5.0, 5.0, 10.0, 0.0])
        self.assertFalse(by_type["line"].properties)

    def test_old_schema_named_view_without_color_column_uses_default_color(self):
        row = SimpleNamespace(
            UID=29280,
            BidPageUID=133266,
            Name="12/S3.04",
            Color=None,
            Position=encode_position(
                [
                    1577.16,
                    2209.582,
                    2305.93,
                    2828.142,
                    1577.16,
                    2828.142,
                    2305.93,
                    2209.582,
                    0.0,
                ]
            ),
        )
        annotations = _dimension_support__Reader()._parse_bid_annotations_for_bid(
            _dimension_support__FakeConnection({"BidNamedViews": [row]}),
            "731",
            {"99": Layer(uid="99", name="Annotation", visible=True)},
            _dimension_support__annotation_reader_schema(named_view_has_color=False),
        )
        named_views = [ann for ann in annotations if ann.is_namedview]
        self.assertEqual(len(named_views), 1)
        self.assertEqual(named_views[0].uid, "29280")
        self.assertEqual(named_views[0].page_uid, "133266")
        self.assertEqual(named_views[0].properties["Text"], "12/S3.04")
        self.assertEqual(named_views[0].color, "#008000")
        self.assertEqual(len(named_views[0].position), 9)

    def test_new_schema_named_view_with_color_column_preserves_color(self):
        row = SimpleNamespace(
            UID=6519,
            BidPageUID=6518,
            Name="SP3.02/9",
            Color=0x00AA00,
            Position=encode_position(
                [
                    494.708,
                    2832.397,
                    1558.459,
                    1437.986,
                    494.708,
                    1437.986,
                    1558.459,
                    2832.397,
                    0.0,
                ]
            ),
        )
        annotations = _dimension_support__Reader()._parse_bid_annotations_for_bid(
            _dimension_support__FakeConnection({"BidNamedViews": [row]}),
            "5326",
            {"99": Layer(uid="99", name="Annotation", visible=True)},
            _dimension_support__annotation_reader_schema(named_view_has_color=True),
        )
        named_view = next(ann for ann in annotations if ann.is_namedview)
        self.assertEqual(named_view.uid, "6519")
        self.assertEqual(named_view.page_uid, "6518")
        self.assertEqual(named_view.properties["Text"], "SP3.02/9")
        self.assertEqual(named_view.color, "#00aa00")

    def test_old_schema_hotlink_target_resolves_to_loaded_named_view(self):
        named_view = SimpleNamespace(
            UID=29280,
            BidPageUID=133266,
            Name="12/S3.04",
            Color=None,
            Position=encode_position(
                [
                    1577.16,
                    2209.582,
                    2305.93,
                    2828.142,
                    1577.16,
                    2828.142,
                    2305.93,
                    2209.582,
                    0.0,
                ]
            ),
        )
        hotlink = SimpleNamespace(
            UID=68459,
            BidPageUID=133230,
            BidPageViewUID=29280,
            BidLayerUID=99,
            Color=255,
            Position=encode_position([1719.334, 283.375]),
        )
        annotations = _dimension_support__Reader()._parse_bid_annotations_for_bid(
            _dimension_support__FakeConnection(
                {"BidNamedViews": [named_view], "BidHotLinks": [hotlink]}
            ),
            "731",
            {"99": Layer(uid="99", name="Annotation", visible=True)},
            _dimension_support__annotation_reader_schema(named_view_has_color=False),
        )
        named_view_uids = {ann.uid for ann in annotations if ann.is_namedview}
        hotlinks = [ann for ann in annotations if ann.is_hotlink]
        self.assertEqual(named_view_uids, {"29280"})
        self.assertEqual(len(hotlinks), 1)
        self.assertEqual(hotlinks[0].page_uid, "133230")
        self.assertEqual(hotlinks[0].hotlink_target_view_uid, "29280")
        self.assertIn(hotlinks[0].hotlink_target_view_uid, named_view_uids)

    def test_dangling_hotlink_target_and_layer_remain_inspectable_on_ordinary_reload(
        self,
    ):
        hotlink = SimpleNamespace(
            UID=68459,
            BidPageUID=133230,
            BidPageViewUID=29280,
            BidLayerUID=99,
            Color=255,
            Position=encode_position([1719.334, 283.375]),
        )
        annotations = _dimension_support__Reader()._parse_bid_annotations_for_bid(
            _dimension_support__FakeConnection({"BidHotLinks": [hotlink]}),
            "731",
            {},
            _dimension_support__annotation_reader_schema(named_view_has_color=False),
        )
        loaded = next(annotation for annotation in annotations if annotation.is_hotlink)
        self.assertEqual(loaded.hotlink_target_view_uid, "29280")
        self.assertEqual(loaded.layer_uid, "99")
        self.assertTrue(loaded.visible)
