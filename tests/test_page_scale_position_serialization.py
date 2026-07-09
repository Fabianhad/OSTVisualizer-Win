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
