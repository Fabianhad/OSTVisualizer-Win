import json
import os
import secrets
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
    credential_target_for,
)
from ost_visualizer.domain.entities.file_state import FileEntry, FileState
from ost_visualizer.infrastructure.sql.schema_definition import (
    SQL_SCHEMA_V1,
    schema_record_is_canonical,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
    validate_sql_database_creation_name,
    validate_sql_database_name,
)


class DatabaseDescriptorDatabaseDescriptorTests(unittest.TestCase):
    def test_sql_descriptor_serialization_and_repr_never_contain_password(self):
        password = secrets.token_urlsafe(24)
        location = SqlServerDatabaseLocation(
            server=r"server\instance",
            database="OSTV_TEST_123",
            authentication_mode=SqlAuthenticationMode.SQL_SERVER,
            username="test-user",
            database_guid="00000000-0000-0000-0000-000000000123",
        )
        descriptor = DatabaseDescriptor.for_sql_server(
            location, schema_version=SQL_SCHEMA_V1.version
        )
        payload = json.dumps(FileEntry.for_descriptor(descriptor).to_dict())
        self.assertNotIn(password, payload)
        self.assertNotIn("password", payload.casefold())
        self.assertNotIn(password, repr(descriptor))
        self.assertEqual(DatabaseDescriptor.from_dict(descriptor.to_dict()), descriptor)

    def test_sql_descriptor_requires_an_explicit_schema_version(self):
        location = SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        with self.assertRaises(TypeError):
            DatabaseDescriptor.for_sql_server(location)

    def test_temporary_sql_descriptor_fields_are_rejected(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        payload = descriptor.to_dict()
        payload["location"]["credential_target"] = "obsolete"
        with self.assertRaisesRegex(ValueError, "unsupported format"):
            DatabaseDescriptor.from_dict(payload)

    def test_saved_descriptors_reject_noncanonical_scalar_types(self):
        sql_payload = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        ).to_dict()
        sql_payload["location"]["server"] = None
        with self.assertRaisesRegex(ValueError, "server"):
            DatabaseDescriptor.from_dict(sql_payload)
        access_payload = DatabaseDescriptor.for_access(r"C:\data\sample.mdb").to_dict()
        access_payload["location"]["file_path"] = 7
        with self.assertRaisesRegex(ValueError, "file_path"):
            DatabaseDescriptor.from_dict(access_payload)
        timeout_payload = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        ).to_dict()
        timeout_payload["location"]["connection_timeout_seconds"] = True
        with self.assertRaisesRegex(ValueError, "connection_timeout_seconds"):
            DatabaseDescriptor.from_dict(timeout_payload)


class DatabaseDescriptorCreationPermissionAndNameTests(unittest.TestCase):
    def test_creation_limits_full_name_to_settings_capacity_without_truncation(self):
        for name in ("a" * 75, "Database [west]", "漢" * 75, "😀" * 37 + "x"):
            validate_sql_database_creation_name(name)
        for name in ("a" * 76, "漢" * 76, "😀" * 38, "", "master"):
            with self.assertRaises(ValueError):
                validate_sql_database_creation_name(name)
        # Existing connections keep the SQL identifier contract.
        validate_sql_database_name("a" * 128)
