import os
import unittest
from types import SimpleNamespace
import pyodbc

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

ANNOTATION_TABLES = frozenset(
    {
        "BidAnnotationClouds",
        "BidAnnotationOvals",
        "BidAnnotationPolygons",
        "BidAnnotationRects",
        "BidAnnoInk",
        "BidALines",
        "BidDimensions",
        "BidArrows",
        "BidTexts",
        "BidHighlights",
        "BidNamedViews",
        "BidHotLinks",
        "BidCallOuts",
    }
)
NAMED_VIEW_POSITION = [
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


class _RecordingCursor(_dimension_support__FakeCursor):
    def __init__(self, rows_by_table, executions, failing_table=None):
        super().__init__(rows_by_table)
        self._executions = executions
        self._failing_table = failing_table

    def execute(self, query, *params):
        self._executions.append((" ".join(query.split()), params))
        if self._failing_table is not None and self._failing_table in query:
            raise pyodbc.Error("42S02", f"[42S02] no such table {self._failing_table}")
        super().execute(query, *params)


class _RecordingConnection:
    def __init__(self, rows_by_table, failing_table=None):
        self.rows_by_table = rows_by_table
        self.failing_table = failing_table
        self.executions = []

    def cursor(self):
        return _RecordingCursor(self.rows_by_table, self.executions, self.failing_table)


class _StrictReader(AnnotationReaderMixin):
    @staticmethod
    def _record_caught_read_error(_exc):
        return True


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

    def test_annotation_reader_rejects_non_positive_and_non_numeric_uids_in_any_table(
        self,
    ):
        position = encode_position([0.0, 0.0, 10.0, 10.0])
        for bad_uid, rendered in ((0, "0"), (-3, "-3"), ("abc", "abc"), ("1.5", "1.5")):
            row = SimpleNamespace(
                UID=bad_uid,
                BidPageUID=3,
                BidLayerUID=None,
                Position=position,
                Color=255,
                Width=2,
            )
            with self.subTest(bad_uid=bad_uid):
                with self.assertRaisesRegex(
                    RuntimeError,
                    f"BidAnnotationRects contains malformed UID {rendered}",
                ):
                    _dimension_support__Reader()._parse_bid_annotations_for_bid(
                        _dimension_support__FakeConnection(
                            {"BidAnnotationRects": [row]}
                        ),
                        "1",
                        {},
                        _dimension_support__annotation_reader_schema(),
                    )
        duplicate_rows = [
            SimpleNamespace(
                UID=5,
                BidPageUID=3,
                BidLayerUID=None,
                Position=position,
                Color=255,
                Width=2,
            )
            for _index in range(2)
        ]
        with self.assertRaisesRegex(
            RuntimeError, "BidAnnotationRects contains duplicate UID 5"
        ):
            _dimension_support__Reader()._parse_bid_annotations_for_bid(
                _dimension_support__FakeConnection(
                    {"BidAnnotationRects": duplicate_rows}
                ),
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
        self.assertEqual(len(annotations), 1)
        self.assertEqual(dimension.layer_uid, "99")
        self.assertTrue(dimension.visible)
        self.assertEqual(
            dimension.properties,
            {
                "FontName": "Arial",
                "FontColor": 255,
                "FontSize": 10,
                "FontBold": False,
                "FontItalic": False,
                "FontUnderline": False,
                "BidTakeoffFromUID": "11",
                "BidTakeoffToUID": "12",
            },
        )

    def test_dimension_defaults_and_unset_takeoff_references(self):
        row = SimpleNamespace(
            UID=7,
            BidPageUID=3,
            BidTakeoffFromUID=None,
            BidTakeoffToUID=None,
            Position=encode_position([0.0, 0.0, 255.0, 0.0]),
            FontName=None,
            FontColor=0x0000FF,
            FontSize=0,
            FontBold=1,
            FontItalic=None,
            FontUnderline=0,
        )
        annotations = _dimension_support__Reader()._parse_bid_annotations_for_bid(
            _dimension_support__FakeConnection({"BidDimensions": [row]}),
            "1",
            {},
            _dimension_support__annotation_reader_schema(),
        )
        self.assertEqual(len(annotations), 1)
        self.assertEqual(annotations[0].color, "#ff0000")
        self.assertEqual(
            annotations[0].properties,
            {
                "FontName": "Arial",
                "FontColor": 0x0000FF,
                "FontSize": 10,
                "FontBold": True,
                "FontItalic": False,
                "FontUnderline": False,
            },
        )

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
        self.assertEqual(len(annotations), 8)
        expected_shapes = {
            "line": ("11", [0.0, 0.0, 10.0, 10.0], "#ff0000", 2.0),
            "arrow": ("12", [1.0, 2.0, 13.0, 14.0], "#ff0000", 2.0),
            "rect": ("13", [1.0, 2.0, 13.0, 14.0], "#ff0000", 2.0),
            "oval": ("14", [2.0, 3.0, 14.0, 15.0], "#ff0000", 2.0),
            "polygon": ("15", [0.0, 0.0, 12.0, 0.0, 6.0, 8.0], "#ff0000", 2.0),
            "cloud": ("16", [1.0, 1.0, 13.0, 1.0, 7.0, 9.0], "#ff0000", 2.0),
            "highlight": (
                "17",
                [3.0, 4.0, 15.0, 4.0, 15.0, 16.0, 3.0, 16.0],
                "#ffff00",
                0.0,
            ),
            "ink": ("18", [0.0, 0.0, 5.0, 5.0, 10.0, 0.0], "#ff0000", 2.0),
        }
        for annotation_type, (uid, position, color, width) in expected_shapes.items():
            with self.subTest(annotation_type=annotation_type):
                annotation = by_type[annotation_type]
                self.assertEqual(annotation.uid, uid)
                self.assertEqual(annotation.page_uid, "3")
                self.assertEqual(annotation.layer_uid, "99")
                self.assertTrue(annotation.visible)
                self.assertEqual(annotation.position, position)
                self.assertEqual(annotation.color, color)
                self.assertEqual(annotation.width, width)
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
        self.assertEqual(by_type["line"].properties, {})
        self.assertEqual(by_type["arrow"].properties, {})

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
        self.assertEqual(named_views[0].position, NAMED_VIEW_POSITION)
        self.assertEqual(named_views[0].layer_uid, "99")
        self.assertEqual(len(annotations), 1)

    def test_named_view_query_selects_a_null_color_only_when_the_column_is_missing(
        self,
    ):
        for has_color, expected_select in (
            (False, "SELECT UID, BidPageUID, Name, NULL AS [Color], Position"),
            (True, "SELECT UID, BidPageUID, Name, [Color], Position"),
        ):
            with self.subTest(has_color=has_color):
                connection = _RecordingConnection({})
                _dimension_support__Reader()._parse_bid_annotations_for_bid(
                    connection,
                    "731",
                    {},
                    _dimension_support__annotation_reader_schema(
                        named_view_has_color=has_color
                    ),
                )
                named_view_queries = [
                    query
                    for query, _params in connection.executions
                    if "FROM BidNamedViews" in query
                ]
                self.assertEqual(
                    named_view_queries,
                    [f"{expected_select} FROM BidNamedViews WHERE BidUID = ?"],
                )

    def test_every_annotation_query_is_scoped_to_the_requested_bid(self):
        connection = _RecordingConnection({})
        annotations = _dimension_support__Reader()._parse_bid_annotations_for_bid(
            connection,
            "731",
            {},
            _dimension_support__annotation_reader_schema(),
        )
        self.assertEqual(annotations, [])
        queried_tables = []
        for query, params in connection.executions:
            self.assertIn("WHERE BidUID = ?", query)
            self.assertEqual(params, ("731",))
            queried_tables.append(query.split(" FROM ")[1].split(" ")[0])
        self.assertEqual(sorted(queried_tables), sorted(ANNOTATION_TABLES))

    def test_missing_optional_annotation_table_is_skipped_unless_the_error_is_recorded(
        self,
    ):
        rect = SimpleNamespace(
            UID=13,
            BidPageUID=3,
            BidLayerUID=None,
            Position=encode_position([1.0, 2.0, 13.0, 14.0]),
            Color=255,
            Width=2,
        )
        rows_by_table = {"BidAnnotationRects": [rect]}
        schema = _dimension_support__annotation_reader_schema()
        annotations = _dimension_support__Reader()._parse_bid_annotations_for_bid(
            _RecordingConnection(rows_by_table, failing_table="BidHighlights"),
            "1",
            {},
            schema,
        )
        self.assertEqual([ann.uid for ann in annotations], ["13"])
        with self.assertRaises(pyodbc.Error):
            _StrictReader()._parse_bid_annotations_for_bid(
                _RecordingConnection(rows_by_table, failing_table="BidHighlights"),
                "1",
                {},
                schema,
            )

    def test_rows_without_a_usable_position_are_not_loaded(self):
        def rect(uid, position):
            return SimpleNamespace(
                UID=uid,
                BidPageUID=3,
                BidLayerUID=None,
                Position=position,
                Color=255,
                Width=2,
            )

        short_text = SimpleNamespace(
            UID=21,
            BidPageUID=3,
            BidLayerUID=None,
            Name=b"short",
            FontName="Arial",
            FontColor=0,
            FontSize=12,
            FontBold=0,
            FontItalic=0,
            FontUnderline=0,
            TextAlign=0,
            Position=encode_position([1.0, 2.0]),
        )
        annotations = _dimension_support__Reader()._parse_bid_annotations_for_bid(
            _dimension_support__FakeConnection(
                {
                    "BidAnnotationRects": [
                        rect(1, None),
                        rect(2, b""),
                        rect(3, encode_position([0.0, 0.0, 4.0, 4.0])),
                    ],
                    "BidTexts": [short_text],
                }
            ),
            "1",
            {},
            _dimension_support__annotation_reader_schema(),
        )
        self.assertEqual([ann.uid for ann in annotations], ["3"])

    def test_text_and_callout_rows_are_decoded_with_defaults_and_layer_visibility(self):
        layers = {
            "99": Layer(uid="99", name="Annotation", visible=True),
            "50": Layer(uid="50", name="Hidden", visible=False),
        }
        text = SimpleNamespace(
            UID=31,
            BidPageUID=3,
            BidLayerUID=50,
            Name="Line one\r\nL\u00ednea dos\x00".encode("latin-1"),
            FontName=None,
            FontColor=0x0000FF,
            FontSize=None,
            FontBold=1,
            FontItalic=0,
            FontUnderline=1,
            TextAlign=None,
            Position=encode_position([7.0, 8.0, 12.0, 12.0]),
        )
        callout = SimpleNamespace(
            UID=32,
            BidPageUID=0,
            BidLayerUID=None,
            Name=None,
            FontName="Calibri",
            FontColor=0,
            FontSize=18,
            FontBold=0,
            FontItalic=1,
            FontUnderline=0,
            TextAlign=2,
            Position=encode_position([1.0, 1.0]),
            Color=0x00FF00,
            Width=None,
        )
        annotations = _dimension_support__Reader()._parse_bid_annotations_for_bid(
            _dimension_support__FakeConnection(
                {"BidTexts": [text], "BidCallOuts": [callout]}
            ),
            "1",
            layers,
            _dimension_support__annotation_reader_schema(),
        )
        by_uid = {ann.uid: ann for ann in annotations}
        self.assertEqual(set(by_uid), {"31", "32"})
        loaded_text = by_uid["31"]
        self.assertEqual(loaded_text.annotation_type, "text")
        self.assertEqual(loaded_text.layer_uid, "50")
        self.assertFalse(loaded_text.visible)
        self.assertEqual(loaded_text.color, "#ff0000")
        self.assertEqual(loaded_text.width, 0.0)
        self.assertEqual(
            loaded_text.properties,
            {
                "Text": "Line one\nL\u00ednea dos",
                "FontColor": 0x0000FF,
                "FontName": "Arial",
                "FontSize": 12,
                "FontBold": True,
                "FontItalic": False,
                "FontUnderline": True,
                "TextAlign": 0,
            },
        )
        loaded_callout = by_uid["32"]
        self.assertEqual(loaded_callout.annotation_type, "callout")
        self.assertEqual(loaded_callout.page_uid, "")
        self.assertEqual(loaded_callout.layer_uid, "99")
        self.assertTrue(loaded_callout.visible)
        self.assertEqual(loaded_callout.color, "#00ff00")
        self.assertEqual(loaded_callout.width, 2.0)
        self.assertEqual(loaded_callout.position, [1.0, 1.0])
        self.assertEqual(
            loaded_callout.properties,
            {
                "Text": "",
                "FontColor": 0,
                "FontName": "Calibri",
                "FontSize": 18,
                "FontBold": False,
                "FontItalic": True,
                "FontUnderline": False,
                "TextAlign": 2,
            },
        )

    def test_hidden_annotation_layer_hides_layerless_tables_and_unknown_layers_stay_visible(
        self,
    ):
        layers = {"99": Layer(uid="99", name="Annotation", visible=False)}
        line = SimpleNamespace(
            UID=11,
            BidPageUID=3,
            BidTakeoffFromUID=None,
            BidTakeoffToUID=None,
            Position=encode_position([0.0, 0.0, 10.0, 10.0]),
            Color=255,
            Width=2,
        )
        rect_on_unknown_layer = SimpleNamespace(
            UID=13,
            BidPageUID=3,
            BidLayerUID=77,
            Position=encode_position([1.0, 2.0, 13.0, 14.0]),
            Color=255,
            Width=0,
        )
        rect_on_hidden_layer = SimpleNamespace(
            UID=14,
            BidPageUID=3,
            BidLayerUID=99,
            Position=encode_position([1.0, 2.0, 13.0, 14.0]),
            Color="#123456",
            Width=0,
        )
        annotations = _dimension_support__Reader()._parse_bid_annotations_for_bid(
            _dimension_support__FakeConnection(
                {
                    "BidALines": [line],
                    "BidAnnotationRects": [rect_on_unknown_layer, rect_on_hidden_layer],
                }
            ),
            "1",
            layers,
            _dimension_support__annotation_reader_schema(),
        )
        by_uid = {ann.uid: ann for ann in annotations}
        self.assertEqual(
            {
                uid: (ann.layer_uid, ann.visible, ann.color, ann.width)
                for uid, ann in by_uid.items()
            },
            {
                "11": ("99", False, "#ff0000", 2.0),
                "13": ("77", True, "#ff0000", 2.0),
                "14": ("99", False, "#123456", 2.0),
            },
        )

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
        self.assertEqual(
            named_view.position,
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
            ],
        )
        self.assertEqual(named_view.layer_uid, "99")

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
        self.assertEqual(hotlinks[0].uid, "68459")
        self.assertEqual(hotlinks[0].layer_uid, "99")
        self.assertEqual(hotlinks[0].color, "#ff0000")
        self.assertEqual(hotlinks[0].width, 2.0)
        self.assertEqual(hotlinks[0].position, [1719.334, 283.375])
        self.assertEqual(hotlinks[0].properties, {"BidPageViewUID": "29280"})

    def test_hotlink_without_target_reads_as_unlinked(self):
        hotlinks = []
        for target in (None, 0):
            hotlink = SimpleNamespace(
                UID=68459,
                BidPageUID=133230,
                BidPageViewUID=target,
                BidLayerUID=None,
                Color=255,
                Position=encode_position([1719.334, 283.375]),
            )
            annotations = _dimension_support__Reader()._parse_bid_annotations_for_bid(
                _dimension_support__FakeConnection({"BidHotLinks": [hotlink]}),
                "731",
                {},
                _dimension_support__annotation_reader_schema(),
            )
            hotlinks.extend(annotations)
        self.assertEqual(len(hotlinks), 2)
        for hotlink in hotlinks:
            self.assertIsNone(hotlink.hotlink_target_view_uid)
            self.assertEqual(hotlink.properties, {"BidPageViewUID": None})

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
        self.assertEqual(len(annotations), 1)
        self.assertEqual(loaded.hotlink_target_view_uid, "29280")
        self.assertEqual(loaded.layer_uid, "99")
        self.assertTrue(loaded.visible)
        self.assertEqual(loaded.page_uid, "133230")
        self.assertEqual(loaded.position, [1719.334, 283.375])
