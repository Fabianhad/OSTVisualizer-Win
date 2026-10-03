import unittest
from types import SimpleNamespace
from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.serialization import (
    TEXT_POSITION_TABLES,
    encode_position,
    parse_position_storage,
    serialize_position_for_table,
)
from tests.infrastructure.mdb.components.scale_position_support import (
    _Cursor as _scale_position_support__Cursor,
    _Logger as _scale_position_support__Logger,
    _PageOps as _scale_position_support__PageOps,
    _Schema as _scale_position_support__Schema,
)


class PageScaleGeometryStorageTests(unittest.TestCase):
    def test_legend_transform_keeps_extensions_and_null_position(self):
        from xml.etree.ElementTree import fromstring
        from ost_visualizer.infrastructure.mdb.components.legend_position import (
            rescale_legend_position,
        )

        payload = b'<Legends dX="1" dY="2" Custom="7"><!--keep--><Legend dX="3" dY="4" FontSize="12"/><Extension dX="9"/></Legends>'
        scaled = rescale_legend_position(payload, 2.0)
        root = fromstring(scaled)
        self.assertEqual(root.attrib, {"dX": "2", "dY": "4", "Custom": "7"})
        self.assertEqual(
            root.find("Legend").attrib, {"dX": "6", "dY": "8", "FontSize": "12"}
        )
        self.assertEqual(root.find("Extension").attrib["dX"], "9")
        self.assertIn(b"<!--keep-->", scaled)
        ops = _scale_position_support__PageOps()
        cursor = _scale_position_support__Cursor(
            "BidLegends", [SimpleNamespace(UID=7, Position=None)]
        )
        ops._rescale_page_positions(
            cursor, _scale_position_support__Schema("BidLegends"), 3, 2.0
        )
        self.assertEqual(cursor.updates, [])
        self.assertEqual(ops.logger.warnings, [])
        # Positive control: the same page-rescale path does write a populated row.
        populated = _scale_position_support__Cursor(
            "BidLegends",
            [
                SimpleNamespace(
                    UID=7,
                    Position=b'<Legends dX="1" dY="2"><Legend dX="3" dY="4"/></Legends>',
                )
            ],
        )
        ops._rescale_page_positions(
            populated, _scale_position_support__Schema("BidLegends"), 3, 2.0
        )
        self.assertEqual(
            populated.updates,
            [(b'<Legends dX="2" dY="4"><Legend dX="6" dY="8" /></Legends>', 7)],
        )

    def test_repeated_round_trips_obey_storage_precision(self):
        from xml.etree.ElementTree import fromstring
        from ost_visualizer.infrastructure.mdb.components.legend_position import (
            rescale_legend_position,
        )
        from ost_visualizer.infrastructure.mdb.components.overlay_rect import (
            parse_overlay_rect_storage,
            serialize_overlay_rect_storage,
        )

        numeric = b"1234.567;2345.678\n"
        # Hand-computed single step: 1234.567 * 0.3 = 370.3701 and
        # 2345.678 * 0.3 = 703.7034, stored to three decimals.
        single = _scale_position_support__Cursor(
            "BidTakeoffs", [SimpleNamespace(UID=7, Position=numeric)]
        )
        _scale_position_support__PageOps()._rescale_page_positions(
            single, _scale_position_support__Schema("BidTakeoffs"), 3, 0.3
        )
        self.assertEqual(single.updates, [(b"370.37;703.703\n", 7)])
        legend = b'<Legends dX="1234.567" dY="2345.678"/>'
        overlay = "1234.567,2345.678,100.123456,200.123456"
        for _ in range(20):
            for factor in (0.3, 1 / 0.3):
                cursor = _scale_position_support__Cursor(
                    "BidTakeoffs", [SimpleNamespace(UID=7, Position=numeric)]
                )
                _scale_position_support__PageOps()._rescale_page_positions(
                    cursor, _scale_position_support__Schema("BidTakeoffs"), 3, factor
                )
                numeric = cursor.updates[0][0]
                legend = rescale_legend_position(legend, factor)
                overlay = serialize_overlay_rect_storage(
                    tuple(v * factor for v in parse_overlay_rect_storage(overlay))
                )
        self.assertAlmostEqual(
            parse_position_storage(numeric)[0], 1234.567, delta=0.0022
        )
        self.assertAlmostEqual(
            float(fromstring(legend).attrib["dX"]), 1234.567, delta=0.0022
        )
        self.assertAlmostEqual(
            parse_overlay_rect_storage(overlay)[0], 1234.567, delta=0.0000022
        )
