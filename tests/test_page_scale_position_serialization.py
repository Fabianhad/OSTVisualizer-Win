import unittest
from types import SimpleNamespace
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.domain.utils.position import parse_position
from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.serialization import (
    TEXT_POSITION_TABLES,
    encode_position,
    parse_position_storage,
    serialize_position_for_table,
)


class _Schema:
    def __init__(self, position_table):
        self.position_table = position_table

    def optional_table_missing(self, _table):
        return False

    def column_exists(self, table, column):
        return table == self.position_table and column in (
            "UID",
            "BidPageUID",
            "Position",
        )


class _Cursor:
    def __init__(self, table, rows):
        self.table = table
        self.rows = list(rows)
        self.updates = []

    def execute(self, query, *params):
        if query.startswith(f"UPDATE [{self.table}]"):
            self.updates.append((params[0], params[1]))

    def fetchall(self):
        return list(self.rows)


class _Logger:
    def __init__(self):
        self.warnings = []

    def warning(self, message, *args):
        self.warnings.append(message % args)


class _PageOps(PageOperationsMixin):
    def __init__(self):
        self.logger = _Logger()

    @staticmethod
    def _record_caught_mutation_error(_exc):
        return False


class PageScalePositionSerializationTests(unittest.TestCase):
    def test_text_position_table_classification_includes_text_annotation_tables(self):
        self.assertIn("BidTexts", TEXT_POSITION_TABLES)
        self.assertIn("BidCallOuts", TEXT_POSITION_TABLES)
        self.assertIn("BidComments", TEXT_POSITION_TABLES)
        self.assertNotIn("BidTakeoffs", TEXT_POSITION_TABLES)

    def test_position_serializer_returns_text_for_text_position_tables(self):
        position = [1.0, 2.0, 3.0, 4.0]
        self.assertIsInstance(serialize_position_for_table("BidTexts", position), str)
        self.assertIsInstance(
            serialize_position_for_table("BidCallOuts", position), str
        )
        self.assertIsInstance(
            serialize_position_for_table("BidComments", position), str
        )

    def test_position_serializer_returns_bytes_for_binary_position_tables(self):
        value = serialize_position_for_table("BidTakeoffs", [1.0, 2.0, 3.0, 4.0])
        self.assertIsInstance(value, bytes)

    def test_position_parser_reads_text_and_binary_storage_values(self):
        position = [1.0, 2.0, 3.0, 4.0]
        binary_value = serialize_position_for_table("BidTakeoffs", position)
        text_value = serialize_position_for_table("BidTexts", position)
        self.assertEqual(parse_position_storage(binary_value), position)
        self.assertEqual(parse_position_storage(text_value), position)

    def test_position_parsing_has_one_value_contract_across_consumers(self):
        text = "1; 2;&#xA;3;4"
        expected = [1.0, 2.0, 3.0, 4.0]
        self.assertEqual(parse_position(text), expected)
        self.assertEqual(parse_position_storage(text), expected)
        self.assertEqual(OSTCoordinateSystem.parse_position(text), expected)

    def test_position_parsing_returns_independent_lists(self):
        first = parse_position_storage("1;2;3;4")
        first.append(5.0)
        self.assertEqual(parse_position_storage("1;2;3;4"), [1.0, 2.0, 3.0, 4.0])

    def test_position_parsing_preserves_previous_text_edge_cases(self):
        cases = (
            (None, []),
            ("", []),
            ("   ", []),
            ("1;2;", [1.0, 2.0]),
            ("1;; 2 ;\n", [1.0, 2.0]),
            ("1;&#10;2;&#x0A;3;&#xA;4", [1.0, 2.0, 3.0, 4.0]),
            ("1;bad;3", []),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(parse_position(value), expected)
                self.assertEqual(OSTCoordinateSystem.parse_position(value), expected)

    def test_position_storage_preserves_binary_and_text_contracts(self):
        self.assertEqual(
            parse_position_storage(b"-1.5;0;2.25;4\n"),
            [-1.5, 0.0, 2.25, 4.0],
        )
        self.assertEqual(
            parse_position_storage(bytearray(b"1;2;3;4\n")),
            [1.0, 2.0, 3.0, 4.0],
        )
        self.assertEqual(OSTCoordinateSystem.parse_position((1, 2)), [1.0, 2.0])

    def test_page_scale_rescale_writes_text_payload_for_text_position_tables(self):
        ops = _PageOps()
        cursor = _Cursor(
            "BidTexts",
            [SimpleNamespace(UID=7, Position=encode_position([1.0, 2.0, 3.0, 4.0]))],
        )
        ops._rescale_page_positions(cursor, _Schema("BidTexts"), page_uid=3, factor=0.5)
        self.assertEqual(
            cursor.updates,
            [(serialize_position_for_table("BidTexts", [0.5, 1.0, 1.5, 2.0]), 7)],
        )

    def test_page_scale_rescale_writes_binary_payload_for_binary_position_tables(self):
        ops = _PageOps()
        cursor = _Cursor(
            "BidTakeoffs",
            [SimpleNamespace(UID=7, Position=encode_position([1.0, 2.0, 3.0, 4.0]))],
        )
        ops._rescale_page_positions(
            cursor, _Schema("BidTakeoffs"), page_uid=3, factor=0.5
        )
        self.assertEqual(
            cursor.updates,
            [
                (
                    serialize_position_for_table("BidTakeoffs", [0.5, 1.0, 1.5, 2.0]),
                    7,
                )
            ],
        )

    def test_legend_xml_coordinates_rescale_without_changing_metadata(self):
        import xml.etree.ElementTree as ET

        payload = (
            b'<Legends dX="30.804" dY="1022.679" Visible="255">\n'
            b'<Legend ConditionUID="11334" dX="30.804" dY="30.804" '
            b'Visible="1" FontSize="12" FontName="Arial" FontColor="0" FontStyle="0"/>\n'
            b"</Legends>\n"
        )
        ops = _PageOps()
        cursor = _Cursor("BidLegends", [SimpleNamespace(UID=11641, Position=payload)])
        ops._rescale_page_positions(cursor, _Schema("BidLegends"), 11376, 2.0)
        self.assertEqual(ops.logger.warnings, [])
        self.assertEqual(len(cursor.updates), 1)
        scaled, uid = cursor.updates[0]
        self.assertIsInstance(scaled, bytes)
        self.assertEqual(uid, 11641)
        before, after = ET.fromstring(payload), ET.fromstring(scaled)
        for old, new in zip(before.iter(), after.iter()):
            for key, value in old.attrib.items():
                if key in ("dX", "dY"):
                    self.assertAlmostEqual(
                        float(new.attrib[key]) / 256, float(value) / 128
                    )
                else:
                    self.assertEqual(new.attrib[key], value)

    def test_invalid_legend_xml_rejects_scale_instead_of_partially_rewriting_it(self):
        from xml.etree.ElementTree import ParseError

        for payload in (b"<Legends", b'<Other dX="1"/>', b'<Legends dX="NaN"/>'):
            with self.subTest(payload=payload):
                ops = _PageOps()
                cursor = _Cursor(
                    "BidLegends", [SimpleNamespace(UID=11641, Position=payload)]
                )
                with self.assertRaises((ValueError, ParseError)):
                    ops._rescale_page_positions(
                        cursor, _Schema("BidLegends"), 11376, 2.0
                    )
                self.assertEqual(cursor.updates, [])

    def test_legend_transform_keeps_extensions_and_null_position(self):
        from xml.etree.ElementTree import fromstring
        from ost_visualizer.infrastructure.mdb.components.legend_position import (
            rescale_legend_position,
        )

        payload = b'<Legends dX="1" dY="2" Custom="7"><!--keep--><Legend dX="3" dY="4" FontSize="12"/><Extension dX="9"/></Legends>'
        scaled = rescale_legend_position(payload, 2.0)
        root = fromstring(scaled)
        self.assertEqual(root.attrib, {"dX": "2", "dY": "4", "Custom": "7"})
        self.assertEqual(root.find("Extension").attrib["dX"], "9")
        self.assertIn(b"<!--keep-->", scaled)
        ops = _PageOps()
        cursor = _Cursor("BidLegends", [SimpleNamespace(UID=7, Position=None)])
        ops._rescale_page_positions(cursor, _Schema("BidLegends"), 3, 2.0)
        self.assertEqual(cursor.updates, [])
        self.assertEqual(ops.logger.warnings, [])

    def test_sql_uses_the_same_scale_position_contract(self):
        from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter

        self.assertIs(
            SqlProjectWriter._rescale_page_positions,
            PageOperationsMixin._rescale_page_positions,
        )

    def test_scale_preserves_annotation_rotation(self):
        for table in ("BidTexts", "BidAnnotationRects", "BidAnnotationOvals"):
            with self.subTest(table=table):
                ops = _PageOps()
                cursor = _Cursor(
                    table,
                    [
                        SimpleNamespace(
                            UID=7,
                            Position=serialize_position_for_table(
                                table, [1, 2, 3, 4, 0.5]
                            ),
                        )
                    ],
                )
                ops._rescale_page_positions(cursor, _Schema(table), 3, 2.0)
                self.assertEqual(
                    parse_position_storage(cursor.updates[0][0]), [2, 4, 6, 8, 0.5]
                )

    def test_all_annotation_rotation_fields_survive_scale(self):
        from ost_visualizer.infrastructure.database.annotation_storage import (
            ANNOTATION_TYPE_BY_TABLE,
        )
        from ost_visualizer.domain.entities.annotation import BidAnnotation

        for table, kind in ANNOTATION_TYPE_BY_TABLE.items():
            with self.subTest(table=table):
                position = (
                    [0.123456789, 100, 200, 300, 400]
                    if kind == "ink"
                    else [100, 200, 300, 400, 0.123456789]
                )
                payload = (";".join(map(str, position)) + "\n").encode("latin-1")
                cursor = _Cursor(table, [SimpleNamespace(UID=7, Position=payload)])
                _PageOps()._rescale_page_positions(cursor, _Schema(table), 3, 2)
                scaled = parse_position_storage(cursor.updates[0][0])
                self.assertEqual(
                    BidAnnotation("7", kind, position=scaled).stored_rotation_rad,
                    BidAnnotation("7", kind, position=position).stored_rotation_rad,
                )
                self.assertEqual(scaled[1], position[1] * 2)

    def test_large_coordinate_round_trip_retains_three_decimal_precision(self):
        payload = b"123456.789;987654.321\n"
        for _ in range(10):
            for factor in (2.0, 0.5):
                cursor = _Cursor(
                    "BidTakeoffs", [SimpleNamespace(UID=7, Position=payload)]
                )
                _PageOps()._rescale_page_positions(
                    cursor, _Schema("BidTakeoffs"), 3, factor
                )
                payload = cursor.updates[0][0]
        self.assertEqual(parse_position_storage(payload), [123456.789, 987654.321])

    def test_curved_takeoff_offset_is_a_length_not_a_trailing_angle(self):
        cursor = _Cursor(
            "BidTakeoffs", [SimpleNamespace(UID=7, Position=b"1;2;3;4;5;6;7\n")]
        )
        _PageOps()._rescale_page_positions(cursor, _Schema("BidTakeoffs"), 3, 2)
        self.assertEqual(
            parse_position_storage(cursor.updates[0][0]), [2, 4, 6, 8, 10, 12, 14]
        )

    def test_malformed_legend_rolls_back_earlier_geometry_updates(self):
        from contextlib import contextmanager
        from xml.etree.ElementTree import ParseError
        from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter

        class Schema:
            def optional_table_missing(self, table):
                return table not in ("BidTakeoffs", "BidLegends")

            def column_exists(self, table, column):
                return column in ("UID", "BidPageUID", "Position")

        class Connection:
            def __init__(self):
                self.pending = []
                self.committed = []
                self.attempted = 0
                self.rollbacks = 0
                self.table = ""

            def execute(self, query, *params):
                if query.startswith("SELECT UID"):
                    self.table = (
                        "BidLegends" if "BidLegends" in query else "BidTakeoffs"
                    )
                elif query.startswith("UPDATE"):
                    self.pending.append(params)
                    self.attempted += 1

            def fetchone(self):
                return (1.0, 128.0)

            def fetchall(self):
                value = b"<Legends" if self.table == "BidLegends" else b"1;2\n"
                return [SimpleNamespace(UID=7, Position=value)]

            def commit(self):
                self.committed.extend(self.pending)
                self.pending.clear()

            def rollback(self):
                self.rollbacks += 1
                self.pending.clear()

        connection = Connection()

        class Manager:
            @contextmanager
            def connection(self, path, *, autocommit):
                yield connection

        writer = MdbWriter(conn_manager=Manager())
        with self.assertRaises(ParseError):
            with writer._connection("fixture.mdb") as conn:
                writer._rescale_page_content_for_scale_change(
                    conn, Schema(), 3, 1, 256, rescale_overlay=False
                )
        self.assertEqual(connection.attempted, 1)
        self.assertEqual(connection.rollbacks, 1)
        self.assertEqual(connection.pending, [])
        self.assertEqual(connection.committed, [])

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
        legend = b'<Legends dX="1234.567" dY="2345.678"/>'
        overlay = "1234.567,2345.678,100.123456,200.123456"
        for _ in range(20):
            for factor in (0.3, 1 / 0.3):
                cursor = _Cursor(
                    "BidTakeoffs", [SimpleNamespace(UID=7, Position=numeric)]
                )
                _PageOps()._rescale_page_positions(
                    cursor, _Schema("BidTakeoffs"), 3, factor
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

    def test_unverified_position_tables_leave_empty_payloads_untouched(self):
        for table in ("BidComments", "BidTypGroupViews"):
            for payload in (None, "", b""):
                with self.subTest(table=table, payload=payload):
                    ops = _PageOps()
                    cursor = _Cursor(table, [SimpleNamespace(UID=7, Position=payload)])
                    ops._rescale_page_positions(cursor, _Schema(table), 3, 2.0)
                    self.assertEqual(cursor.updates, [])
                    self.assertEqual(ops.logger.warnings, [])

    def test_unverified_position_tables_do_not_rewrite_unparseable_payloads(self):
        # This characterizes the existing parser, not a valid OST payload format.
        for table, payload in (
            ("BidComments", "not-a-numeric-position"),
            ("BidTypGroupViews", b"not-a-numeric-position"),
        ):
            with self.subTest(table=table):
                ops = _PageOps()
                cursor = _Cursor(table, [SimpleNamespace(UID=7, Position=payload)])
                ops._rescale_page_positions(cursor, _Schema(table), 3, 2.0)
                self.assertEqual(cursor.updates, [])
                self.assertEqual(len(ops.logger.warnings), 1)
                self.assertIn(table, ops.logger.warnings[0])
                self.assertEqual(cursor.rows[0].Position, payload)

    def test_page_scale_rescale_skips_unparseable_position_payload(self):
        ops = _PageOps()
        cursor = _Cursor(
            "BidTexts", [SimpleNamespace(UID=8, Position="\ua0e3\ue2b8\ub7b8")]
        )
        ops._rescale_page_positions(cursor, _Schema("BidTexts"), page_uid=3, factor=0.5)
        self.assertEqual(cursor.updates, [])
        self.assertEqual(len(ops.logger.warnings), 1)
        self.assertIn("BidTexts", ops.logger.warnings[0])
        self.assertIn("8", ops.logger.warnings[0])


if __name__ == "__main__":
    unittest.main()
