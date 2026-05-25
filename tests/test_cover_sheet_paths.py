import unittest

from ost_visualizer.infrastructure.mdb.components.settings_operations import \
    SettingsOperationsMixin


class _FakeSchema:
    def column_exists(self, table, column):
        return table == "Bids" and column == "MeasureBase"

    def optional_table_missing(self, _table):
        return False


class _FakeCursor:
    def __init__(self):
        self.connection = object()

    def execute(self, *_args):
        return None

    def fetchone(self):
        return [0]


class _FakeConnection:
    def __init__(self):
        self.cursor_obj = _FakeCursor()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self.cursor_obj


class _CoverSheetSettingsOps(SettingsOperationsMixin):
    def __init__(self):
        self.conn = _FakeConnection()
        self.schema = _FakeSchema()
        self.updates = []
        self.logger = _FakeLogger()

    def _connection(self, _db_path):
        return self.conn

    def _schema(self, _conn):
        return self.schema

    def _require_write_columns(self, *_args):
        return None

    def _execute_update_values(
        self,
        _cursor,
        _schema,
        table,
        values,
        _required_columns,
        _where_clause,
        _where_values,
        _operation,
    ):
        self.updates.append(
            {
                "table": table,
                "values": dict(values),
            }
        )
        return True


class _FakeLogger:
    def exception(self, *_args):
        return None


class CoverSheetPathSaveTests(unittest.TestCase):
    def test_cover_sheet_save_writes_page_image_paths_with_windows_separators(self):
        ops = _CoverSheetSettingsOps()
        success = ops.save_cover_sheet(
            "bid.mdb",
            "7",
            {
                "measure_base": 0,
                "pages": [
                    {
                        "uid": "11",
                        "width": 42.0,
                        "height": 30.0,
                        "scale_factor1": 0.125,
                        "scale_factor2": 12.0,
                        "show_mode": 0,
                        "sheet_no": "S-100",
                        "index": 1,
                        "name": "Level 1",
                        "image_path": (
                            "C:/OCS Documents/OST/25-051 Marriott Element, "
                            "Capel Hill, NC/S-100.pdf"
                        ),
                        "overlay_path": "C:/OCS Documents/OST/overlay.pdf",
                    }
                ],
            },
        )

        self.assertTrue(success)
        self.assertEqual(
            [update["table"] for update in ops.updates],
            ["Bids", "BidPages"],
        )
        bid_update = next(update for update in ops.updates if update["table"] == "Bids")
        page_update = next(
            update for update in ops.updates if update["table"] == "BidPages"
        )
        self.assertNotIn("ImageFolder", bid_update["values"])
        self.assertEqual(
            page_update["values"]["ImagePath"],
            (
                r"C:\OCS Documents\OST\25-051 Marriott Element, "
                r"Capel Hill, NC\S-100.pdf"
            ),
        )
        self.assertEqual(
            page_update["values"]["OverlayImagePath"],
            r"C:\OCS Documents\OST\overlay.pdf",
        )
        self.assertEqual(page_update["values"]["SheetNo"], "S-100")


if __name__ == "__main__":
    unittest.main()
