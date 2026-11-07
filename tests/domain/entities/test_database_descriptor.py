import json
import os
import unittest
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
    validate_sql_database_creation_name,
    validate_sql_database_name,
)
from ost_visualizer.domain.entities.file_state import FileEntry

SCHEMA_VERSION = 1


class DatabaseDescriptorDatabaseDescriptorTests(unittest.TestCase):
    def test_sql_descriptor_serialization_and_repr_never_contain_password(self):
        location = SqlServerDatabaseLocation(
            server=r"server\instance",
            database="OSTV_TEST_123",
            authentication_mode=SqlAuthenticationMode.SQL_SERVER,
            username="test-user",
            database_guid="00000000-0000-0000-0000-000000000123",
        )
        descriptor = DatabaseDescriptor.for_sql_server(
            location, schema_version=SCHEMA_VERSION
        )
        payload = json.dumps(FileEntry.for_descriptor(descriptor).to_dict())
        self.assertNotIn("password", payload.casefold())
        self.assertNotIn("password", repr(descriptor).casefold())
        self.assertEqual(
            set(location.to_dict()),
            {
                "server",
                "database",
                "authentication_mode",
                "username",
                "database_guid",
                "encrypt",
                "trust_server_certificate",
                "connection_timeout_seconds",
                "command_timeout_seconds",
            },
        )
        self.assertEqual(DatabaseDescriptor.from_dict(descriptor.to_dict()), descriptor)
        polluted = descriptor.to_dict()
        polluted["location"]["password"] = "must-not-be-persisted"
        with self.assertRaisesRegex(ValueError, "unsupported format"):
            DatabaseDescriptor.from_dict(polluted)

    def test_sql_descriptor_requires_an_explicit_schema_version(self):
        location = SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        with self.assertRaises(TypeError):
            DatabaseDescriptor.for_sql_server(location)

    def test_temporary_sql_descriptor_fields_are_rejected(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SCHEMA_VERSION,
        )
        payload = descriptor.to_dict()
        payload["location"]["credential_target"] = "obsolete"
        with self.assertRaisesRegex(ValueError, "unsupported format"):
            DatabaseDescriptor.from_dict(payload)

    def test_saved_descriptors_reject_noncanonical_scalar_types(self):
        sql_payload = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SCHEMA_VERSION,
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
            schema_version=SCHEMA_VERSION,
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


def _sql_location(**overrides):
    values = dict(server="localhost", database="OSTV_TEST")
    values.update(overrides)
    return SqlServerDatabaseLocation(**values)


class DatabaseDescriptorEnumsAndDefaultsTests(unittest.TestCase):
    def test_backend_and_authentication_values_are_the_persisted_strings(self):
        from ost_visualizer.domain.entities.database_descriptor import DatabaseBackend

        self.assertEqual(
            (
                DatabaseBackend.ACCESS.value,
                DatabaseBackend.SQL_SERVER.value,
                SqlAuthenticationMode.WINDOWS.value,
                SqlAuthenticationMode.SQL_SERVER.value,
            ),
            ("access", "sql_server", "windows", "sql_server"),
        )
        self.assertEqual(DatabaseBackend("sql_server"), DatabaseBackend.SQL_SERVER)
        with self.assertRaises(ValueError):
            DatabaseBackend("oracle")

    def test_sql_location_defaults_are_secure_and_bounded(self):
        location = _sql_location()
        self.assertEqual(
            (
                location.authentication_mode,
                location.username,
                location.database_guid,
                location.encrypt,
                location.trust_server_certificate,
                location.connection_timeout_seconds,
                location.command_timeout_seconds,
            ),
            (SqlAuthenticationMode.WINDOWS, "", "", True, True, 10, 30),
        )

    def test_locations_and_descriptors_are_frozen(self):
        from dataclasses import FrozenInstanceError
        from ost_visualizer.domain.entities.database_descriptor import (
            AccessDatabaseLocation,
        )

        with self.assertRaises(FrozenInstanceError):
            AccessDatabaseLocation(file_path="a").file_path = "b"
        with self.assertRaises(FrozenInstanceError):
            _sql_location().server = "x"
        with self.assertRaises(FrozenInstanceError):
            DatabaseDescriptor.for_access("a.mdb").display_name = "x"

    def test_location_has_no_credential_field_and_repr_names_every_field_value(self):
        import dataclasses
        from ost_visualizer.domain.entities.database_descriptor import (
            DatabaseBackend,
            SqlServerDatabaseLocation,
        )

        # The descriptor is persisted and logged: it must never gain a secret field.
        field_names = [f.name for f in dataclasses.fields(SqlServerDatabaseLocation)]
        for name in field_names:
            for secret in ("password", "pwd", "secret", "token", "credential"):
                self.assertNotIn(secret, name.lower())
        location = _sql_location(username="u")
        text = repr(location)
        self.assertTrue(text.startswith("SqlServerDatabaseLocation("))
        for name in field_names:
            self.assertIn(f"{name}={getattr(location, name)!r}", text)
        descriptor = DatabaseDescriptor(
            database_id="id",
            backend=DatabaseBackend.ACCESS,
            display_name="n",
            location=location,
        )
        self.assertEqual(descriptor.schema_version, 0)
        text = repr(descriptor)
        self.assertTrue(text.startswith("DatabaseDescriptor("))
        for name in (
            "database_id",
            "backend",
            "display_name",
            "location",
            "schema_version",
        ):
            self.assertIn(f"{name}={getattr(descriptor, name)!r}", text)


class DatabaseDescriptorAccessFactoryTests(unittest.TestCase):
    def test_access_descriptor_defaults_name_from_file_stem_and_has_stable_id(self):
        descriptor = DatabaseDescriptor.for_access(r"C:\data\Sample Job.mdb")
        self.assertEqual(descriptor.display_name, "Sample Job")
        self.assertEqual(descriptor.schema_version, 0)
        self.assertEqual(descriptor.access_path, r"C:\data\Sample Job.mdb")
        self.assertEqual(
            descriptor.database_id,
            DatabaseDescriptor.for_access(r"C:\data\Sample Job.mdb").database_id,
        )
        self.assertNotEqual(
            descriptor.database_id,
            DatabaseDescriptor.for_access(r"C:\data\Other.mdb").database_id,
        )

    @unittest.skipUnless(
        os.name == "nt", "Access paths are normalised by the Windows path rules"
    )
    def test_access_id_ignores_case_and_redundant_path_segments(self):
        spelled = DatabaseDescriptor.for_access(r"C:\Data\sub\..\Sample.MDB")
        canonical = DatabaseDescriptor.for_access(r"c:\data\sample.mdb")
        self.assertEqual(spelled.database_id, canonical.database_id)

    def test_access_location_keeps_the_path_exactly_as_given(self):
        spelled = DatabaseDescriptor.for_access(r"C:\Data\sub\..\Sample.MDB")
        self.assertEqual(spelled.location.file_path, r"C:\Data\sub\..\Sample.MDB")
        self.assertEqual(spelled.access_path, r"C:\Data\sub\..\Sample.MDB")

    def test_explicit_name_id_and_schema_version_are_used_and_empty_name_falls_back(
        self,
    ):
        explicit = DatabaseDescriptor.for_access(
            r"C:\data\a.mdb",
            display_name="Shown",
            database_id="fixed-id",
            schema_version=4,
        )
        self.assertEqual(
            (explicit.display_name, explicit.database_id, explicit.schema_version),
            ("Shown", "fixed-id", 4),
        )
        blank = DatabaseDescriptor.for_access(r"C:\data\a.mdb", display_name="")
        self.assertEqual(blank.display_name, "a.mdb")
        self.assertNotEqual(blank.database_id, "")

    def test_access_descriptor_has_no_sql_location(self):
        descriptor = DatabaseDescriptor.for_access(r"C:\data\a.mdb")
        with self.assertRaisesRegex(
            TypeError, "^Database descriptor is not for SQL Server$"
        ):
            descriptor.sql_location


class DatabaseDescriptorSqlFactoryTests(unittest.TestCase):
    def test_sql_identity_prefers_the_database_guid_case_insensitively(self):
        first = DatabaseDescriptor.for_sql_server(
            _sql_location(database_guid=" ABCDEF00-0000-0000-0000-000000000001 "),
            schema_version=1,
        )
        other_server = DatabaseDescriptor.for_sql_server(
            _sql_location(
                server="elsewhere",
                database="Other",
                database_guid="abcdef00-0000-0000-0000-000000000001",
            ),
            schema_version=1,
        )
        self.assertEqual(first.database_id, other_server.database_id)

    def test_sql_identity_without_guid_uses_server_database_mode_and_user(self):
        base = DatabaseDescriptor.for_sql_server(
            _sql_location(server=" Srv ", database="DB"), schema_version=1
        )
        self.assertEqual(
            base.database_id,
            DatabaseDescriptor.for_sql_server(
                _sql_location(server="srv", database=" db "), schema_version=1
            ).database_id,
        )
        for changed in (
            _sql_location(server="srv2", database="DB"),
            _sql_location(server="Srv", database="DB2"),
            _sql_location(
                server="Srv",
                database="DB",
                authentication_mode=SqlAuthenticationMode.SQL_SERVER,
            ),
            _sql_location(server="Srv", database="DB", username="Someone"),
        ):
            with self.subTest(changed=changed):
                self.assertNotEqual(
                    base.database_id,
                    DatabaseDescriptor.for_sql_server(
                        changed, schema_version=1
                    ).database_id,
                )
        self.assertEqual(
            DatabaseDescriptor.for_sql_server(
                _sql_location(username=" USER "), schema_version=1
            ).database_id,
            DatabaseDescriptor.for_sql_server(
                _sql_location(username="user"), schema_version=1
            ).database_id,
        )

    def test_sql_descriptor_name_id_schema_and_validation(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            _sql_location(), schema_version=0
        )
        self.assertEqual(descriptor.display_name, "OSTV_TEST")
        self.assertEqual(descriptor.schema_version, 0)
        self.assertEqual(descriptor.sql_location, _sql_location())
        self.assertEqual(descriptor.access_path, "")
        explicit = DatabaseDescriptor.for_sql_server(
            _sql_location(), display_name="Shown", database_id="fixed", schema_version=2
        )
        self.assertEqual(
            (explicit.display_name, explicit.database_id), ("Shown", "fixed")
        )
        with self.assertRaisesRegex(
            ValueError, "^Database schema version cannot be negative$"
        ):
            DatabaseDescriptor.for_sql_server(_sql_location(), schema_version=-1)

    @unittest.skipUnless(
        os.name == "nt", "the pinned Access id is derived from a Windows path"
    )
    def test_the_derived_access_id_is_pinned_because_saved_entries_are_matched_by_it(
        self,
    ):
        self.assertEqual(
            DatabaseDescriptor.for_access(r"C:\data\a.mdb").database_id,
            "9e1523b8-ef1f-5842-b001-9ac08a084aa6",
        )

    def test_derived_sql_ids_are_pinned_because_saved_entries_are_matched_by_them(self):
        self.assertEqual(
            DatabaseDescriptor.for_sql_server(
                _sql_location(server="Srv", database="DB", username="U"),
                schema_version=1,
            ).database_id,
            "30dbc71e-85fe-5a4c-b472-29e8ee45de4e",
        )
        self.assertEqual(
            DatabaseDescriptor.for_sql_server(
                _sql_location(server="Srv", database="DB", database_guid="AB-1"),
                schema_version=1,
            ).database_id,
            "6983f2e8-9cc5-5443-8cdd-5f81f5fe978c",
        )

    def test_a_pipe_in_a_derived_identity_part_is_rejected_so_ids_cannot_collide(self):
        windows_user_in_database = _sql_location(
            server="s", database="d|sql_server", username="u"
        )
        sql_user_with_pipe = _sql_location(
            server="s",
            database="d",
            authentication_mode=SqlAuthenticationMode.SQL_SERVER,
            username="windows|u",
        )
        for label, location in (
            ("database", windows_user_in_database),
            ("username", sql_user_with_pipe),
            ("server", _sql_location(server="a|b", database="c")),
            ("padded", _sql_location(server=" s ", database=" d| ")),
        ):
            with self.subTest(label=label):
                with self.assertRaisesRegex(
                    ValueError,
                    "^SQL Server connection details cannot contain the '[|]' "
                    "character without a database id.$",
                ):
                    DatabaseDescriptor.for_sql_server(location, schema_version=1)

    def test_ordinary_punctuation_still_derives_a_stable_id(self):
        sql = SqlAuthenticationMode.SQL_SERVER
        cases = (
            (
                _sql_location(
                    server="HOST\\INST",
                    database="db.v1-x",
                    username="u",
                    authentication_mode=sql,
                ),
                "006ea5f3-7a62-5919-b9d1-f8e78b4266ae",
            ),
            (
                _sql_location(server="h%7Ca", database="100%_ok"),
                "04ac30e8-e5d3-5d20-ad34-edec1d7451b3",
            ),
            (
                _sql_location(server="Srv", database="DB", username="U"),
                "30dbc71e-85fe-5a4c-b472-29e8ee45de4e",
            ),
        )
        for location, expected in cases:
            with self.subTest(server=location.server):
                self.assertEqual(
                    DatabaseDescriptor.for_sql_server(
                        location, schema_version=1
                    ).database_id,
                    expected,
                )

    def test_a_pipe_is_tolerated_where_a_guid_or_saved_id_already_identifies_it(self):
        with_guid = DatabaseDescriptor.for_sql_server(
            _sql_location(
                server="s|1",
                database="d|b",
                authentication_mode=SqlAuthenticationMode.SQL_SERVER,
                username="u|x",
                database_guid="AB-1",
            ),
            schema_version=1,
        )
        self.assertEqual(with_guid.database_id, "6983f2e8-9cc5-5443-8cdd-5f81f5fe978c")
        explicit = DatabaseDescriptor.for_sql_server(
            _sql_location(database="d|b"), database_id="saved-id", schema_version=1
        )
        self.assertEqual(explicit.database_id, "saved-id")

    def test_a_saved_descriptor_with_a_pipe_still_loads_and_keeps_its_id(self):
        saved = {
            "database_id": "5f14ce68-eac8-52c3-8d5c-4fc67f5379d0",
            "backend": "sql_server",
            "display_name": "d|sql_server",
            "location": _sql_location(
                server="s", database="d|sql_server", username="u"
            ).to_dict(),
            "schema_version": 1,
        }
        loaded = DatabaseDescriptor.from_dict(saved)
        self.assertEqual(loaded.database_id, saved["database_id"])
        self.assertEqual(loaded.sql_location.database, "d|sql_server")
        self.assertEqual(loaded.to_dict(), saved)

    def test_access_and_sql_ids_never_collide_for_the_same_text(self):
        access = DatabaseDescriptor.for_access("same")
        sql = DatabaseDescriptor.for_sql_server(
            _sql_location(database_guid="same"), schema_version=1
        )
        self.assertNotEqual(access.database_id, sql.database_id)


class DatabaseDescriptorSerializationTests(unittest.TestCase):
    def test_access_descriptor_round_trips_with_its_exact_shape(self):
        descriptor = DatabaseDescriptor.for_access(
            r"C:\data\a.mdb", display_name="A", database_id="id-1", schema_version=3
        )
        self.assertEqual(
            descriptor.to_dict(),
            {
                "database_id": "id-1",
                "backend": "access",
                "display_name": "A",
                "location": {"file_path": r"C:\data\a.mdb"},
                "schema_version": 3,
            },
        )
        self.assertEqual(DatabaseDescriptor.from_dict(descriptor.to_dict()), descriptor)

    def test_sql_descriptor_round_trips_every_field(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            _sql_location(
                authentication_mode=SqlAuthenticationMode.SQL_SERVER,
                username="u",
                database_guid="g",
                encrypt=False,
                trust_server_certificate=False,
                connection_timeout_seconds=7,
                command_timeout_seconds=99,
            ),
            display_name="Shown",
            database_id="fixed",
            schema_version=5,
        )
        payload = descriptor.to_dict()
        self.assertEqual(payload["backend"], "sql_server")
        self.assertEqual(
            payload["location"],
            {
                "server": "localhost",
                "database": "OSTV_TEST",
                "authentication_mode": "sql_server",
                "username": "u",
                "database_guid": "g",
                "encrypt": False,
                "trust_server_certificate": False,
                "connection_timeout_seconds": 7,
                "command_timeout_seconds": 99,
            },
        )
        self.assertEqual(DatabaseDescriptor.from_dict(payload), descriptor)

    def test_from_dict_strips_required_text_and_preserves_optional_text(self):
        payload = DatabaseDescriptor.for_sql_server(
            _sql_location(username=" keep "), database_id="i", schema_version=1
        ).to_dict()
        payload["database_id"] = "  id-1 "
        payload["display_name"] = " Name "
        payload["location"]["server"] = " srv "
        payload["location"]["database"] = " db "
        restored = DatabaseDescriptor.from_dict(payload)
        self.assertEqual(
            (
                restored.database_id,
                restored.display_name,
                restored.sql_location.server,
                restored.sql_location.database,
                restored.sql_location.username,
            ),
            ("id-1", "Name", "srv", "db", " keep "),
        )
        access = DatabaseDescriptor.for_access("a.mdb", database_id="i").to_dict()
        access["location"]["file_path"] = "  a.mdb  "
        self.assertEqual(DatabaseDescriptor.from_dict(access).access_path, "a.mdb")

    def test_from_dict_rejects_each_missing_or_blank_required_value_with_its_label(
        self,
    ):
        def sql():
            return DatabaseDescriptor.for_sql_server(
                _sql_location(), database_id="i", schema_version=1
            ).to_dict()

        def access():
            return DatabaseDescriptor.for_access("a.mdb", database_id="i").to_dict()

        cases = []
        for key in ("database_id", "display_name", "backend"):
            payload = sql()
            payload[key] = "" if key == "backend" else "  "
            cases.append((payload, f"database descriptor {key} value is missing"))
            payload = sql()
            payload[key] = 5
            cases.append((payload, f"database descriptor {key} value is invalid"))
        for key in ("server", "database", "authentication_mode"):
            payload = sql()
            payload["location"][key] = "" if key == "authentication_mode" else " "
            cases.append((payload, f"SQL Server location {key} value is missing"))
            payload = sql()
            payload["location"][key] = None
            cases.append((payload, f"SQL Server location {key} value is invalid"))
        for key in ("username", "database_guid"):
            payload = sql()
            payload["location"][key] = None
            cases.append((payload, f"SQL Server location {key} value is invalid"))
        payload = access()
        payload["location"]["file_path"] = "   "
        cases.append((payload, "Access database location file_path value is missing"))
        payload = access()
        payload["location"]["file_path"] = None
        cases.append((payload, "Access database location file_path value is invalid"))
        for payload, message in cases:
            with self.subTest(message=message):
                with self.assertRaises(ValueError) as raised:
                    DatabaseDescriptor.from_dict(payload)
                self.assertEqual(str(raised.exception), f"Saved {message}")

    def test_from_dict_rejects_missing_extra_keys_and_a_non_mapping_location(self):
        descriptor = DatabaseDescriptor.for_access("a.mdb", database_id="i")

        def failure(payload):
            with self.assertRaises(ValueError) as raised:
                DatabaseDescriptor.from_dict(payload)
            return str(raised.exception)

        payload = descriptor.to_dict()
        del payload["schema_version"]
        self.assertEqual(
            failure(payload), "Saved database descriptor has an unsupported format"
        )
        payload = descriptor.to_dict()
        payload["extra"] = 1
        self.assertEqual(
            failure(payload), "Saved database descriptor has an unsupported format"
        )
        payload = descriptor.to_dict()
        payload["location"] = ["a.mdb"]
        self.assertEqual(failure(payload), "Saved database location is missing")
        payload = descriptor.to_dict()
        payload["location"]["extra"] = 1
        self.assertEqual(
            failure(payload),
            "Saved Access database location has an unsupported format",
        )
        sql = DatabaseDescriptor.for_sql_server(
            _sql_location(), database_id="i", schema_version=1
        ).to_dict()
        del sql["location"]["encrypt"]
        self.assertEqual(
            failure(sql),
            "Saved SQL Server database location has an unsupported format",
        )

    def test_from_dict_rejects_unknown_backend_and_authentication_values(self):
        payload = DatabaseDescriptor.for_access("a.mdb", database_id="i").to_dict()
        payload["backend"] = "oracle"
        with self.assertRaises(ValueError):
            DatabaseDescriptor.from_dict(payload)
        sql = DatabaseDescriptor.for_sql_server(
            _sql_location(), database_id="i", schema_version=1
        ).to_dict()
        sql["location"]["authentication_mode"] = "kerberos"
        with self.assertRaises(ValueError):
            DatabaseDescriptor.from_dict(sql)

    def test_schema_version_and_boolean_fields_are_strictly_typed(self):
        def sql():
            return DatabaseDescriptor.for_sql_server(
                _sql_location(), database_id="i", schema_version=1
            ).to_dict()

        for value in (True, 1.0, "1", None, -1):
            payload = sql()
            payload["schema_version"] = value
            with self.subTest(schema_version=value):
                with self.assertRaisesRegex(
                    ValueError, "^Saved database schema version is invalid$"
                ):
                    DatabaseDescriptor.from_dict(payload)
        payload = sql()
        payload["schema_version"] = 0
        self.assertEqual(DatabaseDescriptor.from_dict(payload).schema_version, 0)
        for key in ("encrypt", "trust_server_certificate"):
            for value in (1, "true", None):
                payload = sql()
                payload["location"][key] = value
                with self.subTest(key=key, value=value):
                    with self.assertRaisesRegex(
                        ValueError, f"^Saved SQL Server {key} value is invalid$"
                    ):
                        DatabaseDescriptor.from_dict(payload)

    def test_timeouts_accept_one_through_their_maximum_and_reject_outside(self):
        for key, maximum in (
            ("connection_timeout_seconds", 60),
            ("command_timeout_seconds", 600),
        ):
            for value, ok in (
                (0, False),
                (1, True),
                (maximum, True),
                (maximum + 1, False),
            ):
                payload = DatabaseDescriptor.for_sql_server(
                    _sql_location(), database_id="i", schema_version=1
                ).to_dict()
                payload["location"][key] = value
                with self.subTest(key=key, value=value):
                    if ok:
                        restored = DatabaseDescriptor.from_dict(payload)
                        self.assertEqual(getattr(restored.sql_location, key), value)
                    else:
                        with self.assertRaisesRegex(
                            ValueError,
                            f"^Saved SQL Server {key} value is out of range$",
                        ):
                            DatabaseDescriptor.from_dict(payload)


class DatabaseDescriptorNameValidationTests(unittest.TestCase):
    def test_credential_target_is_namespaced_by_database_id(self):
        from ost_visualizer.domain.entities.database_descriptor import (
            credential_target_for,
        )

        self.assertEqual(credential_target_for("abc"), "OSTVisualizer/SqlServer/abc")

    def test_name_validation_boundaries_and_messages(self):
        validate_sql_database_name("a")
        validate_sql_database_name("a" * 128)
        validate_sql_database_name("a b")
        for name in ("", "a" * 129, " lead", "trail ", " "):
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                    ValueError,
                    "^Database names must be 1 to 128 characters without leading "
                    "or trailing spaces.$",
                ):
                    validate_sql_database_name(name)
        for name in ("a\x00b", "a\nb", "a\x1fb"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                    ValueError, "^Database name contains a control character.$"
                ):
                    validate_sql_database_name(name)
        validate_sql_database_name("a\x7fb")

    def test_a_pipe_is_rejected_in_a_new_database_name_but_other_punctuation_is_not(
        self,
    ):
        for name in ("a|b", "|", "d|sql_server"):
            for validate in (
                validate_sql_database_name,
                validate_sql_database_creation_name,
            ):
                with self.subTest(name=name, validate=validate.__name__):
                    with self.assertRaisesRegex(
                        ValueError,
                        "^Database name cannot contain the '[|]' character.$",
                    ):
                        validate(name)
        for name in ("a.b", "a-b", "a%b", "a%7Cb", "a\\b", "a]b[", "a_b 1"):
            with self.subTest(name=name):
                validate_sql_database_name(name)
                validate_sql_database_creation_name(name)

    def test_every_system_database_is_rejected_case_insensitively(self):
        for name in ("master", "MODEL", "MsDb", "tempdb", "TempDB"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                    ValueError, "^A SQL Server system database cannot be used.$"
                ):
                    validate_sql_database_name(name)
        validate_sql_database_name("master2")
        validate_sql_database_name("mastered")

    def test_creation_name_limit_message(self):
        validate_sql_database_creation_name("a" * 75)
        with self.assertRaisesRegex(
            ValueError,
            "^New database names must fit within 75 UTF-16 characters because "
            "the complete name is stored in the database settings.$",
        ):
            validate_sql_database_creation_name("a" * 76)
