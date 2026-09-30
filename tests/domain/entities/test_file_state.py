import os
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
