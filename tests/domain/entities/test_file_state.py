import unittest
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
)
from ost_visualizer.domain.entities.file_state import FileEntry, FileState


class FileStateDatabaseDescriptorTests(unittest.TestCase):
    def test_legacy_file_state_migrates_to_stable_access_descriptor(self):
        raw = {
            "file_entries": [{"file_path": r"C:\data\sample.mdb", "is_checked": True}]
        }
        first = FileState.from_dict(raw)
        second = FileState.from_dict(raw)
        self.assertEqual(first.file_entries[0].backend, DatabaseBackend.ACCESS)
        self.assertEqual(
            first.file_entries[0].database_id,
            second.file_entries[0].database_id,
        )
        serialized = first.to_dict()
        self.assertEqual(serialized["version"], 2)
        self.assertIn("database_entries", serialized)
        self.assertEqual(len(first.file_entries), 1)
        self.assertEqual(first.file_entries[0].file_path, r"C:\data\sample.mdb")
        self.assertTrue(first.file_entries[0].is_checked)
        self.assertEqual(FileState.from_dict(serialized), first)
        self.assertEqual(
            raw,
            {
                "file_entries": [
                    {"file_path": r"C:\data\sample.mdb", "is_checked": True}
                ]
            },
        )

    def test_canonical_file_entry_rejects_non_boolean_checked_state(self):
        descriptor = DatabaseDescriptor.for_access(r"C:\data\sample.mdb")
        with self.assertRaisesRegex(ValueError, "checked state"):
            FileEntry.from_dict(
                {"descriptor": descriptor.to_dict(), "is_checked": "false"}
            )

    def test_version_two_file_state_rejects_bare_database_paths(self):
        with self.assertRaisesRegex(ValueError, "unsupported format"):
            FileState.from_dict(
                {
                    "version": 2,
                    "database_entries": [r"C:\data\sample.mdb"],
                }
            )


def _sql_descriptor(server="Srv", database="DB", guid=""):
    from ost_visualizer.domain.entities.database_descriptor import (
        SqlServerDatabaseLocation,
    )

    return DatabaseDescriptor.for_sql_server(
        SqlServerDatabaseLocation(server=server, database=database, database_guid=guid),
        schema_version=1,
    )


class FileEntryIdentityTests(unittest.TestCase):
    def test_access_entry_exposes_path_identity_and_runtime_locator(self):
        import os

        entry = FileEntry("C:/Data/../Jobs/Plan.MDB")
        self.assertIs(entry.is_checked, True)
        self.assertEqual(entry.backend, DatabaseBackend.ACCESS)
        self.assertEqual(entry.file_path, "C:/Data/../Jobs/Plan.MDB")
        self.assertEqual(entry.runtime_locator, "C:/Data/../Jobs/Plan.MDB")
        self.assertEqual(
            entry.normalized_path,
            os.path.normcase(os.path.normpath("C:/Data/../Jobs/Plan.MDB")),
        )
        self.assertEqual(entry.identity_key, f"access:{entry.normalized_path}")
        self.assertEqual(entry.database_id, entry.descriptor.database_id)

    def test_sql_entry_exposes_database_id_identity_and_no_access_path(self):
        descriptor = _sql_descriptor(guid="ABC-DEF")
        entry = FileEntry.for_descriptor(descriptor)
        self.assertIs(entry.is_checked, True)
        self.assertEqual(entry.backend, DatabaseBackend.SQL_SERVER)
        self.assertEqual(entry.file_path, "")
        self.assertEqual(entry.runtime_locator, descriptor.database_id)
        self.assertEqual(entry.normalized_path, descriptor.database_id.casefold())
        self.assertEqual(
            entry.identity_key, f"sql_server:{descriptor.database_id.casefold()}"
        )
        self.assertEqual(entry.database_id, descriptor.database_id)

    def test_same_text_in_different_backends_never_shares_an_identity(self):
        descriptor = _sql_descriptor()
        sql_entry = FileEntry.for_descriptor(descriptor)
        fake_access = FileEntry(descriptor.database_id)
        self.assertNotEqual(sql_entry.identity_key, fake_access.identity_key)
        self.assertTrue(sql_entry.identity_key.startswith("sql_server:"))
        self.assertTrue(fake_access.identity_key.startswith("access:"))

    def test_for_descriptor_defaults_to_checked_and_keyword_controls_it(self):
        descriptor = DatabaseDescriptor.for_access("C:/a.mdb")
        self.assertIs(FileEntry.for_descriptor(descriptor).is_checked, True)
        self.assertIs(
            FileEntry.for_descriptor(descriptor, is_checked=False).is_checked, False
        )
        self.assertIs(FileEntry.for_descriptor(descriptor).descriptor, descriptor)

    def test_with_checked_returns_a_new_entry_sharing_only_the_descriptor(self):
        original = FileEntry("C:/a.mdb", is_checked=True)
        toggled = original.with_checked(False)
        self.assertIsNot(toggled, original)
        self.assertIs(toggled.is_checked, False)
        self.assertIs(original.is_checked, True)
        self.assertIs(toggled.descriptor, original.descriptor)
        self.assertIs(toggled.with_checked(True).is_checked, True)

    def test_default_entry_has_an_empty_access_path(self):
        entry = FileEntry()
        self.assertEqual(entry.file_path, "")
        self.assertIs(entry.is_checked, True)

    def test_entry_round_trips_through_its_dict_for_both_backends(self):
        for entry in (
            FileEntry("C:/a.mdb", is_checked=False),
            FileEntry.for_descriptor(_sql_descriptor(), is_checked=True),
        ):
            with self.subTest(backend=entry.backend):
                data = entry.to_dict()
                self.assertEqual(set(data), {"descriptor", "is_checked"})
                self.assertEqual(data["is_checked"], entry.is_checked)
                self.assertEqual(FileEntry.from_dict(data), entry)


class FileEntryFromDictValidationTests(unittest.TestCase):
    def failure(self, data):
        with self.assertRaises(ValueError) as raised:
            FileEntry.from_dict(data)
        return str(raised.exception)

    def test_descriptor_entry_with_extra_or_missing_keys_is_rejected(self):
        descriptor = DatabaseDescriptor.for_access("C:/a.mdb").to_dict()
        self.assertEqual(
            self.failure({"descriptor": descriptor, "is_checked": True, "x": 1}),
            "Saved database entry has an unsupported format",
        )
        self.assertEqual(
            self.failure({"descriptor": descriptor}),
            "Saved database entry has an unsupported format",
        )

    def test_legacy_entry_accepts_only_path_and_checked_keys(self):
        entry = FileEntry.from_dict({"file_path": "C:/a.mdb", "is_checked": False})
        self.assertEqual((entry.file_path, entry.is_checked), ("C:/a.mdb", False))
        message = "Saved Access database entry has an unsupported format"
        self.assertEqual(self.failure({"file_path": "C:/a.mdb"}), message)
        self.assertEqual(
            self.failure({"file_path": "C:/a.mdb", "is_checked": True, "x": 1}), message
        )
        self.assertEqual(self.failure({"descriptor": 5, "is_checked": True}), message)

    def test_legacy_path_must_be_text_and_checked_state_must_be_boolean(self):
        self.assertEqual(
            self.failure({"file_path": 5, "is_checked": True}),
            "Saved Access database file_path value is invalid",
        )
        for checked in (1, 0, None, "true"):
            with self.subTest(checked=checked):
                self.assertEqual(
                    self.failure({"file_path": "C:/a.mdb", "is_checked": checked}),
                    "Saved database checked state is invalid",
                )


class FileStateFromDictTests(unittest.TestCase):
    def failure(self, data):
        with self.assertRaises(ValueError) as raised:
            FileState.from_dict(data)
        return str(raised.exception)

    def test_empty_or_unrelated_data_gives_an_empty_state(self):
        self.assertEqual(FileState.from_dict({}).file_entries, [])
        self.assertEqual(FileState.from_dict(None).file_entries, [])
        self.assertEqual(FileState.from_dict({"other": 1}).file_entries, [])
        self.assertEqual(FileState().file_entries, [])

    def test_version_two_requires_the_exact_version_and_object_entries(self):
        entry = FileEntry("C:/a.mdb").to_dict()
        self.assertEqual(
            self.failure({"version": 1, "database_entries": [entry]}),
            "Saved database entries use an unsupported version",
        )
        self.assertEqual(
            self.failure({"database_entries": [entry]}),
            "Saved database entries use an unsupported version",
        )
        self.assertEqual(
            self.failure({"version": 2, "database_entries": [entry, "C:/b.mdb"]}),
            "Saved database entries use an unsupported format",
        )
        state = FileState.from_dict({"version": 2, "database_entries": [entry]})
        self.assertEqual([e.file_path for e in state.file_entries], ["C:/a.mdb"])

    def test_legacy_file_entries_accept_objects_and_bare_paths_and_deduplicate(self):
        state = FileState.from_dict(
            {
                "file_entries": [
                    "C:/a.mdb",
                    {"file_path": "c:/A.MDB", "is_checked": False},
                    {"file_path": "C:/b.mdb", "is_checked": False},
                ]
            }
        )
        self.assertEqual(
            [(e.file_path, e.is_checked) for e in state.file_entries],
            [("C:/a.mdb", True), ("C:/b.mdb", False)],
        )

    def test_database_entries_take_precedence_over_legacy_entries(self):
        state = FileState.from_dict(
            {
                "version": 2,
                "database_entries": [FileEntry("C:/new.mdb").to_dict()],
                "file_entries": ["C:/old.mdb"],
            }
        )
        self.assertEqual([e.file_path for e in state.file_entries], ["C:/new.mdb"])

    def test_non_list_entries_are_ignored(self):
        self.assertEqual(
            FileState.from_dict({"file_entries": "C:/a.mdb"}).file_entries, []
        )

    def test_to_dict_is_versioned_and_round_trips(self):
        state = FileState(
            file_entries=[
                FileEntry("C:/a.mdb", is_checked=False),
                FileEntry.for_descriptor(_sql_descriptor()),
            ]
        )
        data = state.to_dict()
        self.assertEqual(data["version"], 2)
        self.assertEqual(
            data["database_entries"], [entry.to_dict() for entry in state.file_entries]
        )
        self.assertEqual(FileState.from_dict(data), state)


class FileStateContainsAndDeduplicateTests(unittest.TestCase):
    def test_contains_path_matches_normalized_spelling_for_access_entries_only(self):
        state = FileState(
            file_entries=[
                FileEntry("C:/jobs/Plan.mdb"),
                FileEntry.for_descriptor(_sql_descriptor()),
            ]
        )
        self.assertIs(state.contains_path("C:/jobs/Plan.mdb"), True)
        self.assertIs(state.contains_path("c:\\jobs\\.\\PLAN.MDB"), True)
        self.assertIs(state.contains_path("C:/jobs/other.mdb"), False)
        self.assertIs(FileState().contains_path("C:/jobs/Plan.mdb"), False)

    def test_normalize_path_collapses_segments_and_case(self):
        import os

        from ost_visualizer.domain.entities.file_state import normalize_path

        self.assertEqual(
            normalize_path("C:/A/./B/../Plan.MDB"),
            os.path.normcase(os.path.normpath("C:/A/./B/../Plan.MDB")),
        )
        self.assertEqual(normalize_path("C:/A/B/../Plan.MDB"), normalize_path("c:/a/plan.mdb"))

    def test_deduplicate_keeps_first_position_and_checks_if_any_duplicate_is_checked(self):
        from ost_visualizer.domain.entities.file_state import deduplicate_entries

        entries = [
            FileEntry("C:/a.mdb", is_checked=False),
            FileEntry("C:/b.mdb", is_checked=False),
            FileEntry("c:/A.mdb", is_checked=True),
            FileEntry("C:/b.mdb", is_checked=False),
        ]
        result = deduplicate_entries(entries)
        self.assertEqual(
            [(e.file_path, e.is_checked) for e in result],
            [("C:/a.mdb", True), ("C:/b.mdb", False)],
        )
        # The input entries are never mutated.
        self.assertEqual([e.is_checked for e in entries], [False, False, True, False])

    def test_deduplicate_never_unchecks_an_already_checked_first_entry(self):
        from ost_visualizer.domain.entities.file_state import deduplicate_entries

        result = deduplicate_entries(
            [
                FileEntry("C:/a.mdb", is_checked=True),
                FileEntry("C:/A.mdb", is_checked=False),
                FileEntry("C:/a.mdb", is_checked=True),
            ]
        )
        self.assertEqual([(e.file_path, e.is_checked) for e in result], [("C:/a.mdb", True)])

    def test_deduplicate_treats_sql_ids_case_insensitively_and_separately_from_paths(self):
        from ost_visualizer.domain.entities.file_state import deduplicate_entries

        descriptor = _sql_descriptor()
        upper = DatabaseDescriptor(
            database_id=descriptor.database_id.upper(),
            backend=descriptor.backend,
            display_name="Other name",
            location=descriptor.location,
            schema_version=1,
        )
        result = deduplicate_entries(
            [
                FileEntry.for_descriptor(descriptor, is_checked=False),
                FileEntry.for_descriptor(upper, is_checked=True),
                FileEntry("C:/a.mdb"),
            ]
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].backend, DatabaseBackend.SQL_SERVER)
        self.assertIs(result[0].is_checked, True)
