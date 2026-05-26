import logging
import unittest
from ost_visualizer.infrastructure.mdb.components.takeoff_operations import (
    TakeoffOperationsMixin,
)


class _FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def cursor(self):
        return object()


class _TakeoffTextStyleWriter(TakeoffOperationsMixin):
    def __init__(self):
        self.calls = []
        self.logger = logging.getLogger(__name__)

    def _connection(self, _db_path):
        return _FakeConnection()

    def _schema(self, _conn):
        return object()

    def _execute_update_values(
        self,
        cursor,
        _schema,
        table,
        values,
        required_columns,
        where_sql,
        params,
        operation,
        _allow_empty=False,
    ):
        self.calls.append(
            (table, dict(values), required_columns, where_sql, list(params), operation)
        )
        return True


class TakeoffTextStylePersistenceTests(unittest.TestCase):
    def test_takeoff_text_styles_write_bid_takeoff_font_columns(self):
        writer = _TakeoffTextStyleWriter()
        self.assertTrue(
            writer.save_takeoff_text_properties(
                "bid.mdb",
                [
                    (
                        "9200",
                        {
                            "dimension_font_name": "Arial",
                            "dimension_font_color": 16711680,
                            "dimension_font_size": 72,
                            "dimension_font_bold": True,
                            "dimension_font_italic": False,
                            "dimension_font_underline": False,
                            "name_font_name": "Arial",
                            "name_font_color": 8388608,
                            "name_font_size": 48,
                            "name_font_bold": True,
                            "name_font_italic": False,
                            "name_font_underline": False,
                        },
                    )
                ],
            )
        )
        self.assertEqual(len(writer.calls), 1)
        table, values, required_columns, where_sql, params, operation = writer.calls[0]
        self.assertEqual(table, "BidTakeoffs")
        self.assertEqual(required_columns, ("UID",))
        self.assertEqual(where_sql, "[UID]=?")
        self.assertEqual(params, [9200])
        self.assertEqual(operation, "save_takeoff_text_properties")
        self.assertEqual(values["FontName"], "Arial")
        self.assertEqual(values["FontColor"], 16711680)
        self.assertEqual(values["FontSize"], 72)
        self.assertTrue(values["FontBold"])
        self.assertEqual(values["NameFontName"], "Arial")
        self.assertEqual(values["NameFontColor"], 8388608)
        self.assertEqual(values["NameFontSize"], 48)
        self.assertTrue(values["NameFontBold"])


if __name__ == "__main__":
    unittest.main()
