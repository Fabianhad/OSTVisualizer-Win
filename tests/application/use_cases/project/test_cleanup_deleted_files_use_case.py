import logging
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.use_cases.project.cleanup_deleted_files_use_case import (
    CleanupDeletedFilesUseCase,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.domain.entities.file_state import FileEntry, FileState
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1


class _FileStateRepository:
    def __init__(self, state=None, load_error=None, save_error=None):
        self.state = state
        self.load_error = load_error
        self.save_error = save_error
        self.saved = []

    def load(self):
        if self.load_error is not None:
            raise self.load_error
        return self.state

    def save(self, state):
        if self.save_error is not None:
            raise self.save_error
        self.saved.append(list(state.file_entries))


def _sql_entry(database="OSTV"):
    return FileEntry.for_descriptor(
        DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(
                server="server\\instance",
                database=database,
            ),
            schema_version=SQL_SCHEMA_V1.version,
        )
    )


class CleanupDeletedFilesUseCaseDatabaseDescriptorTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.existing_path = os.path.join(self._directory.name, "existing.mdb")
        with open(self.existing_path, "wb"):
            pass
        self.missing_path = os.path.join(self._directory.name, "missing.mdb")
        self.assertFalse(os.path.exists(self.missing_path))

    def test_missing_access_cleanup_retains_saved_sql_descriptors(self):
        sql_entry = _sql_entry()
        existing_access = FileEntry(file_path=self.existing_path)
        missing_access = FileEntry(file_path=self.missing_path)
        cleaned, removed = CleanupDeletedFilesUseCase(object()).execute(
            [missing_access, sql_entry, existing_access]
        )
        self.assertEqual(cleaned, [sql_entry, existing_access])
        self.assertEqual(removed, 1)

    def test_cleanup_with_nothing_missing_removes_nothing(self):
        entries = [FileEntry(file_path=self.existing_path), _sql_entry()]
        cleaned, removed = CleanupDeletedFilesUseCase(object()).execute(entries)
        self.assertEqual(cleaned, entries)
        self.assertEqual(removed, 0)

    def test_execute_and_save_persists_only_when_entries_were_removed(self):
        sql_entry = _sql_entry()
        existing_access = FileEntry(file_path=self.existing_path)
        repository = _FileStateRepository(
            FileState(
                [
                    FileEntry(file_path=self.missing_path),
                    sql_entry,
                    existing_access,
                ]
            )
        )
        use_case = CleanupDeletedFilesUseCase(repository)
        self.assertEqual(use_case.execute_and_save(), 1)
        self.assertEqual(repository.saved, [[sql_entry, existing_access]])
        unchanged = _FileStateRepository(
            FileState([existing_access, sql_entry]),
        )
        self.assertEqual(CleanupDeletedFilesUseCase(unchanged).execute_and_save(), 0)
        self.assertEqual(unchanged.saved, [])
        empty = _FileStateRepository(FileState([]))
        self.assertEqual(CleanupDeletedFilesUseCase(empty).execute_and_save(), 0)
        self.assertEqual(empty.saved, [])

    def test_execute_and_save_reports_zero_on_load_or_save_failure(self):
        logger = logging.getLogger("test.cleanup_deleted_files")
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        for error in (FileNotFoundError(), OSError("unreadable"), ValueError("bad")):
            with self.subTest(load_error=type(error).__name__):
                repository = _FileStateRepository(load_error=error)
                self.assertEqual(
                    CleanupDeletedFilesUseCase(repository, logger).execute_and_save(),
                    0,
                )
                self.assertEqual(repository.saved, [])
        repository = _FileStateRepository(
            FileState([FileEntry(file_path=self.missing_path)]),
            save_error=OSError("read-only"),
        )
        self.assertEqual(
            CleanupDeletedFilesUseCase(repository, logger).execute_and_save(), 0
        )
