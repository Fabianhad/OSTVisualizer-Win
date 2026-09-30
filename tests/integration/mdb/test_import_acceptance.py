import tempfile
import unittest
from pathlib import Path
import pyodbc
from ost_visualizer.infrastructure.mdb import database_creator
from ost_visualizer.infrastructure.mdb.importers.ost_importer import OstImporter
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from tests.helpers.mdb.import_export_support import (
    _ACCESS_DRIVER as _import_export_support__ACCESS_DRIVER,
    _access_conn_str as _import_export_support__access_conn_str,
    _access_driver_available as _import_export_support__access_driver_available,
    _connect_access_or_skip as _import_export_support__connect_access_or_skip,
)


class ImportAcceptanceRelationshipTests(unittest.TestCase):
    def test_access_import_clears_old_ost_missing_selected_page_reference(self):
        if not _import_export_support__access_driver_available():
            self.skipTest("Microsoft Access ODBC driver is not available")
        xml = """
        <XML_ROOT>
          <Bid UID="757" JobName="Imported">
            <BidSettings>
              <BidSetting UID="740" BidUID="757" BidPageSelectedUID="138631"/>
            </BidSettings>
            <BidPages>
              <BidPage UID="138791" BidUID="757" Name="Sheet" Sequence="1"/>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            temp_path = Path(temp_dir)
            ost_path = temp_path / "old_shape.ost"
            db_path = temp_path / "old_shape.mdb"
            ost_path.write_text(xml, encoding="utf-8")
            self.assertTrue(
                database_creator.DatabaseCreator().create_database(db_path, "Old Shape")
            )
            writer = MdbWriter()
            try:
                self.assertTrue(
                    OstImporter(writer).import_ost(str(ost_path), str(db_path))
                )
            finally:
                writer._conn_manager.close()

    def test_access_import_handles_new_ost_zero_bid_settings_uid(self):
        if not _import_export_support__access_driver_available():
            self.skipTest("Microsoft Access ODBC driver is not available")
        xml = """
        <XML_ROOT>
          <Bid UID="1" JobName="Imported">
            <BidSettings>
              <BidSetting UID="0" BidUID="1" BidPageSelectedUID="0"/>
            </BidSettings>
            <BidPages>
              <BidPage UID="20" BidUID="1" Name="Sheet" Sequence="1"/>
            </BidPages>
          </Bid>
        </XML_ROOT>
        """
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            temp_path = Path(temp_dir)
            ost_path = temp_path / "new_shape.ost"
            db_path = temp_path / "new_shape.mdb"
            ost_path.write_text(xml, encoding="utf-8")
            self.assertTrue(
                database_creator.DatabaseCreator().create_database(db_path, "New Shape")
            )
            writer = MdbWriter()
            try:
                self.assertTrue(
                    OstImporter(writer).import_ost(str(ost_path), str(db_path))
                )
            finally:
                writer._conn_manager.close()
            conn = _import_export_support__connect_access_or_skip(self, db_path)
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT [UID], [BidPageSelectedUID] FROM [BidSettings]")
                row = cursor.fetchone()
                self.assertIsNotNone(row[0])
                self.assertIsNone(row[1])
            finally:
                conn.rollback()
                cursor.close()
                conn.close()

    def test_database_creator_enforces_nullable_bid_settings_page_relationship(self):
        if not _import_export_support__access_driver_available():
            self.skipTest("Microsoft Access ODBC driver is not available")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "relationship.mdb"
            if not database_creator.DatabaseCreator().create_database(
                db_path, "Relationship"
            ):
                self.skipTest("Could not create an Access test database")
            conn = _import_export_support__connect_access_or_skip(self, db_path)
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO [Bids] ([UID], [JobName]) VALUES (?, ?)", 100, "Bid"
                )
                cursor.execute(
                    "INSERT INTO [BidSettings] ([BidUID], [BidPageSelectedUID]) "
                    "VALUES (?, ?)",
                    100,
                    None,
                )
                with self.assertRaises(pyodbc.IntegrityError):
                    cursor.execute(
                        "INSERT INTO [BidSettings] "
                        "([BidUID], [BidPageSelectedUID]) VALUES (?, ?)",
                        100,
                        999,
                    )
            finally:
                conn.rollback()
                cursor.close()
                conn.close()

    def test_access_bid_delete_clears_cross_bid_selected_page_reference(self):
        if not _import_export_support__access_driver_available():
            self.skipTest("Microsoft Access ODBC driver is not available")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "delete_cross_bid_selected_page.mdb"
            if not database_creator.DatabaseCreator().create_database(
                db_path, "Delete Relationship"
            ):
                self.skipTest("Could not create an Access test database")
            conn = _import_export_support__connect_access_or_skip(self, db_path)
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO [Bids] ([UID], [JobName]) VALUES (?, ?)",
                    100,
                    "Delete Me",
                )
                cursor.execute(
                    "INSERT INTO [Bids] ([UID], [JobName]) VALUES (?, ?)",
                    200,
                    "Keep Me",
                )
                cursor.execute(
                    "INSERT INTO [BidPages] ([UID], [BidUID], [Name]) "
                    "VALUES (?, ?, ?)",
                    300,
                    100,
                    "Selected Elsewhere",
                )
                cursor.execute(
                    "INSERT INTO [BidSettings] ([BidUID], [BidPageSelectedUID]) "
                    "VALUES (?, ?)",
                    200,
                    300,
                )
                conn.commit()
            finally:
                cursor.close()
                conn.close()
            writer = MdbWriter()
            try:
                self.assertTrue(writer.delete_bids(str(db_path), ["100"]))
            finally:
                writer._conn_manager.close()
            conn = _import_export_support__connect_access_or_skip(self, db_path)
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT COUNT(*) FROM [Bids] WHERE [UID]=100")
                self.assertEqual(cursor.fetchone()[0], 0)
                cursor.execute("SELECT COUNT(*) FROM [BidPages] WHERE [UID]=300")
                self.assertEqual(cursor.fetchone()[0], 0)
                cursor.execute(
                    "SELECT [BidPageSelectedUID] FROM [BidSettings] "
                    "WHERE [BidUID]=200"
                )
                self.assertIsNone(cursor.fetchone()[0])
            finally:
                conn.rollback()
                cursor.close()
                conn.close()

    def test_access_page_area_insert_uses_explicit_uid_after_imported_uid_gap(self):
        if not _import_export_support__access_driver_available():
            self.skipTest("Microsoft Access ODBC driver is not available")
        settings = [
            (86, 451, 81),
            (87, 450, 82),
            (88, 449, 83),
            (89, 448, 84),
            (90, 447, 85),
            (91, 444, 86),
            (92, 440, 87),
            (93, 436, 88),
            (94, 428, 89),
            (906, 183, 0),
            (907, 409, 94),
            (908, 410, 93),
            (909, 417, 92),
            (910, 418, 91),
            (911, 424, 90),
        ]
        page_uids = sorted({452} | {page_uid for _uid, page_uid, _area in settings})
        pages = []
        for page_uid in page_uids:
            nested = []
            for uid, settings_page_uid, area_uid in settings:
                if settings_page_uid != page_uid:
                    continue
                area_attr = "" if area_uid == 0 else f' BidAreaUID="{area_uid}"'
                nested.append(
                    f'<BidPageSetting UID="{uid}" BidPageUID="{settings_page_uid}"'
                    f'{area_attr} BidAreaSelected="2"/>'
                )
            if nested:
                pages.append(
                    f'<BidPage UID="{page_uid}" BidUID="80" Name="P{page_uid}">'
                    f'<BidPageSettings>{"".join(nested)}</BidPageSettings>'
                    f"</BidPage>"
                )
            else:
                pages.append(
                    f'<BidPage UID="{page_uid}" BidUID="80" Name="P{page_uid}"/>'
                )
        areas = "".join(
            f'<BidArea UID="{area_uid}" BidUID="80" Name="A{area_uid}" '
            f'Sequence="{area_uid}"/>'
            for area_uid in range(81, 95)
        )
        xml = (
            '<XML_ROOT><Bid UID="80" JobName="Mini">'
            f"<BidAreas>{areas}</BidAreas>"
            f'<BidPages>{"".join(pages)}</BidPages>'
            "</Bid></XML_ROOT>"
        )
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            temp_path = Path(temp_dir)
            ost_path = temp_path / "mini.ost"
            db_path = temp_path / "mini.mdb"
            ost_path.write_text(xml, encoding="utf-8")
            if not database_creator.DatabaseCreator().create_database(db_path, "Mini"):
                self.skipTest("Could not create an Access test database")
            writer = MdbWriter()
            try:
                self.assertTrue(
                    OstImporter(writer).import_ost(str(ost_path), str(db_path))
                )
            finally:
                writer._conn_manager.close()
            conn = _import_export_support__connect_access_or_skip(self, db_path)
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT [UID] FROM [BidPages] WHERE [Name]='P452'")
                page_uid = int(cursor.fetchone()[0])
                with self.assertRaises(pyodbc.IntegrityError):
                    cursor.execute(
                        "INSERT INTO [BidPageSettings] "
                        "([BidPageUID], [BidAreaUID], [BidAreaSelected]) "
                        "VALUES (?, NULL, 1)",
                        page_uid,
                    )
                conn.rollback()
            finally:
                cursor.close()
                conn.close()
            writer = MdbWriter()
            try:
                self.assertTrue(writer.save_page_area(str(db_path), str(page_uid), "0"))
            finally:
                writer._conn_manager.close()
            conn = _import_export_support__connect_access_or_skip(self, db_path)
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT [UID], [BidAreaUID], [BidAreaSelected] "
                    "FROM [BidPageSettings] WHERE [BidPageUID]=?",
                    page_uid,
                )
                row = cursor.fetchone()
                self.assertEqual((int(row[0]), row[1], int(row[2])), (42, None, 1))
            finally:
                conn.rollback()
                cursor.close()
                conn.close()

    def test_database_creator_does_not_add_non_ost_page_area_selection_uniqueness(self):
        class FakeCursor:
            def __init__(self):
                self.calls = []

            def execute(self, sql):
                self.calls.append(sql)

            def close(self):
                pass

        class FakeConnection:
            def __init__(self):
                self.cursor_instance = FakeCursor()

            def cursor(self):
                return self.cursor_instance

            def commit(self):
                pass

            def rollback(self):
                pass

            def close(self):
                pass

        fake_connection = FakeConnection()
        original_connect = database_creator.pyodbc.connect
        database_creator.pyodbc.connect = (
            lambda _connection_string, *, autocommit: fake_connection
        )
        try:
            creator = database_creator.DatabaseCreator()
            creator._apply_reference_schema_metadata = (
                lambda _db_path, progress_callback=None: None
            )
            creator._create_schema(Path("test.mdb"))
        finally:
            database_creator.pyodbc.connect = original_connect
        self.assertNotIn(
            "CREATE UNIQUE INDEX [UI_BidPageSettings_PageSelected] "
            "ON [BidPageSettings] ([BidPageUID], [BidAreaSelected])",
            fake_connection.cursor_instance.calls,
        )
