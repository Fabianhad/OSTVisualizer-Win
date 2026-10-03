import contextlib
import sqlite3
import unittest
from types import SimpleNamespace
from ost_visualizer.application.dtos.collaboration_dtos import (
    ConcurrencyToken,
    ResourceRef,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.entity_version_reader import (
    DatabaseEntityVersionReader,
)
from ost_visualizer.infrastructure.sql.connection_manager import SqlConnectionManager
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1


class _NoConnectionManager:
    def connection(self, *_args, **_kwargs):
        raise AssertionError("unversioned SQL must not query ostv tables")


class _VersionCursor:
    def __init__(self, rows, statements):
        self._rows = rows
        self._statements = statements

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        return False

    def execute(self, sql, *params):
        self._statements.append((sql, params))

    def fetchall(self):
        return list(self._rows)


class _VersionLease:
    def __init__(self, rows, statements):
        self._rows = rows
        self._statements = statements

    def cursor(self):
        return _VersionCursor(self._rows, self._statements)


class _RecordingConnectionManager:
    def __init__(self, rows):
        self._rows = rows
        self.requests = []
        self.statements = []

    @contextlib.contextmanager
    def connection(self, request, *, autocommit=False):
        self.requests.append((request, autocommit))
        yield _VersionLease(self._rows, self.statements)


class _CredentialStore:
    @staticmethod
    def read_password(_target):
        raise AssertionError("Windows authentication must not read a password")


class EntityVersionReaderCollaborationTests(unittest.TestCase):
    def test_unversioned_sql_does_not_read_collaboration_versions(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="EXTERNAL"),
            schema_version=0,
        )
        descriptors.register(descriptor)
        reader = DatabaseEntityVersionReader(
            descriptors,
            object(),
            _NoConnectionManager(),
        )
        self.assertEqual(reader.read_database_versions(descriptor.database_id), {})
        self.assertEqual(reader.read_bid_versions(descriptor.database_id, "8"), {})

    def test_access_and_unregistered_databases_have_no_collaboration_versions(self):
        descriptors = DatabaseDescriptorRegistry()
        access = DatabaseDescriptor.for_access(r"C:\data\one.mdb", schema_version=1)
        descriptors.register(access)
        reader = DatabaseEntityVersionReader(
            descriptors, object(), _NoConnectionManager()
        )
        self.assertEqual(reader.read_database_versions(access.database_id), {})
        self.assertEqual(reader.read_bid_versions(access.database_id, "8"), {})
        self.assertEqual(reader.read_database_versions("not-registered"), {})
        self.assertEqual(reader.read_bid_versions("not-registered", "8"), {})

    def test_versioned_sql_reads_tokens_in_the_requested_scope(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        first = (1).to_bytes(8, "big")
        second = (2).to_bytes(8, "big")
        manager = _RecordingConnectionManager(
            [
                ("condition", 42, 8, first),
                ("condition", "7", None, bytearray(second)),
            ]
        )
        reader = DatabaseEntityVersionReader(descriptors, _CredentialStore(), manager)
        expected = {
            ResourceRef("condition", "42", 8): ConcurrencyToken(first),
            ResourceRef("condition", "7", None): ConcurrencyToken(second),
        }
        database_id = descriptor.database_id
        self.assertEqual(reader.read_bid_versions(database_id, "8"), expected)
        self.assertEqual(reader.read_database_versions(database_id), expected)
        self.assertEqual(
            [params for _sql, params in manager.statements], [(8, 8), (None, None)]
        )
        for sql, _params in manager.statements:
            self.assertIn("[ostv].[EntityVersions]", sql)
        self.assertEqual(len(manager.requests), 2)
        for request, autocommit in manager.requests:
            self.assertTrue(request.read_only)
            self.assertTrue(autocommit)
            self.assertEqual(request.location, descriptor.sql_location)

    def test_versioned_sql_rejects_a_malformed_version_token(self):
        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        manager = _RecordingConnectionManager([("condition", "7", None, "not-bytes")])
        reader = DatabaseEntityVersionReader(descriptors, _CredentialStore(), manager)
        with self.assertRaisesRegex(ValueError, "invalid rowversion"):
            reader.read_database_versions(descriptor.database_id)

    def test_default_connection_manager_is_a_real_sql_connection_manager(self):
        reader = DatabaseEntityVersionReader(
            DatabaseDescriptorRegistry(), _CredentialStore()
        )
        self.assertIsInstance(reader._connections, SqlConnectionManager)
        explicit = _RecordingConnectionManager([])
        self.assertIs(
            DatabaseEntityVersionReader(
                DatabaseDescriptorRegistry(), _CredentialStore(), explicit
            )._connections,
            explicit,
        )

    def test_scope_predicate_text_selects_only_the_requested_scope(self):
        # The recording fake above returns the same rows whatever the WHERE
        # clause says. Here the production statement itself is evaluated (on
        # sqlite, with the ostv schema attached) so the predicate text matters:
        # a database-scope read returns only unscoped rows, a Bid-scope read
        # only that Bid's rows.
        stored = sqlite3.connect(":memory:")
        stored.execute("ATTACH DATABASE ':memory:' AS ostv")
        stored.execute(
            "CREATE TABLE ostv.EntityVersions (ResourceType TEXT, ResourceId TEXT, "
            "BidUID INTEGER, Token BLOB)"
        )
        tokens = [(index).to_bytes(8, "big") for index in range(1, 5)]
        stored.executemany(
            "INSERT INTO ostv.EntityVersions VALUES (?, ?, ?, ?)",
            [
                ("project", "1", None, tokens[0]),
                ("bid", "8", 8, tokens[1]),
                ("condition", "42", 8, tokens[2]),
                ("condition", "99", 9, tokens[3]),
            ],
        )

        class _SqliteCursor:
            def __init__(self):
                self._rows = []

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def execute(self, sql, *params):
                self._rows = stored.execute(sql, params).fetchall()

            def fetchall(self):
                return self._rows

        class _SqliteManager:
            @contextlib.contextmanager
            def connection(self, _request, *, autocommit=False):
                yield SimpleNamespace(cursor=_SqliteCursor)

        descriptors = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        descriptors.register(descriptor)
        reader = DatabaseEntityVersionReader(
            descriptors, _CredentialStore(), _SqliteManager()
        )
        self.assertEqual(
            reader.read_database_versions(descriptor.database_id),
            {ResourceRef("project", "1", None): ConcurrencyToken(tokens[0])},
        )
        self.assertEqual(
            reader.read_bid_versions(descriptor.database_id, "8"),
            {
                ResourceRef("bid", "8", 8): ConcurrencyToken(tokens[1]),
                ResourceRef("condition", "42", 8): ConcurrencyToken(tokens[2]),
            },
        )
        self.assertEqual(reader.read_bid_versions(descriptor.database_id, "77"), {})
