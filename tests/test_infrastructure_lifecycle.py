import logging
import unittest
from contextlib import contextmanager
from types import MappingProxyType
from ost_visualizer.infrastructure import providers
from ost_visualizer.infrastructure.mdb import database_creator
from ost_visualizer.infrastructure.mdb.components.annotation_operations import (
    AnnotationOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.condition_operations import (
    ConditionOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)
from ost_visualizer.infrastructure.services.license_validation_scheduler import (
    LicenseValidationScheduler,
)


class InfrastructureLifecycleTests(unittest.TestCase):
    def test_license_validation_scheduler_stop_releases_thread_reference(self):
        scheduler = LicenseValidationScheduler(interval_seconds=60)
        scheduler.set_task(lambda: None)
        scheduler.start()
        scheduler.stop()
        self.assertIsNone(scheduler._thread)

    def test_license_validation_scheduler_clear_task_releases_callback(self):
        retained = object()
        scheduler = LicenseValidationScheduler(
            interval_seconds=60, task=lambda retained=retained: retained
        )
        scheduler.clear_task()
        self.assertIsNone(scheduler._task)

    def test_pdf_page_size_renderer_closes_when_page_read_fails(self):
        class FakeRenderer:
            last_instance = None

            def __init__(self):
                self.closed = False
                FakeRenderer.last_instance = self

            def open(self, _path):
                return True

            def page_count(self):
                return 1

            def page_size(self, _page_index):
                raise RuntimeError("page failed")

            def close(self):
                self.closed = True

        original_renderer = providers._ost_pdf.PDFRenderer
        providers._ost_pdf.PDFRenderer = FakeRenderer
        try:
            service_provider = providers.InfrastructureServiceProvider(
                logger=logging.getLogger("test"),
                callback_bridge_factory=lambda: None,
            )
            with self.assertLogs("test", level="ERROR"):
                self.assertEqual(service_provider.get_pdf_page_sizes("bad.pdf"), [])
            self.assertTrue(FakeRenderer.last_instance.closed)
        finally:
            providers._ost_pdf.PDFRenderer = original_renderer

    def test_database_creator_closes_cursor_and_connection_on_schema_failure(self):
        class FakeCursor:
            def __init__(self):
                self.closed = False

            def execute(self, _sql):
                raise RuntimeError("ddl failed")

            def close(self):
                self.closed = True

        class FakeConnection:
            def __init__(self):
                self.cursor_instance = FakeCursor()
                self.rolled_back = False
                self.closed = False

            def cursor(self):
                return self.cursor_instance

            def rollback(self):
                self.rolled_back = True

            def close(self):
                self.closed = True

        fake_connection = FakeConnection()
        original_connect = database_creator.pyodbc.connect
        database_creator.pyodbc.connect = lambda *_args, **_kwargs: fake_connection
        try:
            creator = database_creator.DatabaseCreator()
            with self.assertRaises(RuntimeError):
                creator._create_schema("test.mdb")
        finally:
            database_creator.pyodbc.connect = original_connect
        self.assertTrue(fake_connection.cursor_instance.closed)
        self.assertTrue(fake_connection.rolled_back)
        self.assertTrue(fake_connection.closed)

    def test_static_mdb_lookup_tables_are_immutable(self):
        self.assertIsInstance(
            AnnotationOperationsMixin._ANNOTATION_TABLE, MappingProxyType
        )
        self.assertIsInstance(
            ConditionOperationsMixin._FIELD_TO_COLUMN, MappingProxyType
        )
        self.assertIsInstance(PageOperationsMixin._POSITION_TABLES, tuple)

    def test_named_view_rename_writes_bid_named_views_name_only(self):
        class FakeSchema:
            def optional_table_missing(self, _table):
                return False

        class FakeCursor:
            def __init__(self):
                self.calls = []

            def execute(self, sql, *params):
                self.calls.append((sql, params))

        class FakeConnection:
            def __init__(self):
                self.cursor_instance = FakeCursor()

            def cursor(self):
                return self.cursor_instance

        class FakeWriter(AnnotationOperationsMixin):
            def __init__(self):
                self.connection = FakeConnection()
                self.required_columns = []
                self.logger = logging.getLogger("test")

            @contextmanager
            def _connection(self, _db_path):
                yield self.connection

            def _schema(self, _conn):
                return FakeSchema()

            def _require_write_columns(self, _schema, table, columns):
                self.required_columns.append((table, columns))

        writer = FakeWriter()
        self.assertTrue(
            writer.save_annotation_text_properties(
                "job.mdb",
                [("42", "namedview", {"Text": "New View"})],
            )
        )
        self.assertEqual(writer.required_columns, [("BidNamedViews", ("UID", "Name"))])
        sql, params = writer.connection.cursor_instance.calls[0]
        self.assertIn("UPDATE [BidNamedViews] SET [Name]=?", sql)
        self.assertEqual(params, ("New View", 42))


if __name__ == "__main__":
    unittest.main()
