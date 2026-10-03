import unittest
from ost_visualizer.infrastructure.parsers.ost_serializer import (
    serialize_row,
    serialize_value,
)
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter
import tests.helpers.mdb.schema_support as access


class CrossSystemRawTextWorkflowTests(unittest.TestCase):
    def test_raw_export_import_mapping_uses_storage_encoding_on_both_backends(self):
        for table, column, content, encoding in (
            ("BidTexts", "Name", "café / Ã©\n  end ", "latin-1"),
            ("BidCallOuts", "Name", "Entrée", "latin-1"),
            # Bytes 0x93/0x94 are C1 controls in latin-1 (curly quotes only in
            # cp1252), so this pins the exact single-byte codec.
            ("BidTexts", "Name", "q\x93x\x94", "latin-1"),
            ("BidConditions", "Notes", "Résumé / 東京", "utf-8"),
        ):
            with self.subTest(table=table):
                stored = content.encode(encoding)
                raw = serialize_row((stored,), [(column, bytes)], table=table)[column]
                self.assertEqual(raw, content)
                mdb = access.MdbWriter.__new__(access.MdbWriter)
                sql = SqlProjectWriter.__new__(SqlProjectWriter)
                self.assertEqual(
                    mdb._convert_access_value(
                        raw, "longbinary", table=table, column=column
                    ),
                    stored,
                )
                self.assertEqual(
                    sql._convert_sql_import_value(
                        raw, "varbinary", table=table, column=column
                    ),
                    stored,
                )
