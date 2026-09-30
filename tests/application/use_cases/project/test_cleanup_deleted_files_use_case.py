import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.use_cases.project.cleanup_deleted_files_use_case import (
    CleanupDeletedFilesUseCase,
)
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


class CleanupDeletedFilesUseCaseDatabaseDescriptorTests(unittest.TestCase):
    def test_missing_access_cleanup_retains_saved_sql_descriptors(self):
        sql_entry = FileEntry.for_descriptor(
            DatabaseDescriptor.for_sql_server(
                SqlServerDatabaseLocation(
                    server="server\\instance",
                    database="OSTV",
                ),
                schema_version=SQL_SCHEMA_V1.version,
            )
        )
        missing_access = FileEntry(file_path="missing-database.mdb")
        cleaned, removed = CleanupDeletedFilesUseCase(object()).execute(
            [missing_access, sql_entry]
        )
        self.assertEqual(cleaned, [sql_entry])
        self.assertEqual(removed, 1)
